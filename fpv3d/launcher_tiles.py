"""Map tiles for the launcher's map (Pillow only; no Tk here, so it can be tested on its own).

Switzerland and its neighbours (the WIDE box) are a map, from swisstopo WMTS (the same service as the locations map
page), per 256 px tile:
    base    ch.swisstopo.pixelkarte-grau                     grey national map (also covers the border regions)
    relief  ch.swisstopo.swissalti3d-reliefschattierung      hillshade, Switzerland only
    mask    ch.swisstopo.swissboundaries3d-land-flaeche.fill Switzerland's area: everything outside is dimmed
    zones   ch.bazl.einschraenkungen-drohnen                 FOCA drone restrictions
The rest of the world is a satellite picture: the Sentinel-2 cloudless mosaic of 2016 by EOX (CC BY 4.0, the same
as the photo of scenes abroad, see fpv3d/sentinel2.py), darkened to sit with the map. Zoomed far out (below zoom
ZMAP) everything is satellite, Switzerland too: one picture of the world, without a dark map patch in it.

Each tile is styled once (dark map shaded by the relief, dimmed outside Switzerland; zones as red outlines with a
hatch; satellite darkened) and stored in cache/launcher/tiles_v2/<z>/<x>_<y>.png (+ _z.png for the zones), so it
shows offline. A missing layer just leaves that part out (no relief, no dimming, no zones). STYLE changes need a
new folder name.

    overview()          the WIDE area at zoom 9 as one image (shown first, and when zoomed out)
    tile(z, x, y)       one styled tile (zoom 2..13), from disk or downloaded
    prefetch(points)    the detail tiles around your locations, for offline use at the field
"""
from __future__ import annotations

import io
import math
import os
import shutil
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

WIDE = (4.6, 45.2, 11.9, 48.6)            # lon/lat west, south, east, north of the overview (Switzerland + neighbours)
CH_BOX = (5.85, 45.75, 10.6, 47.9)        # Switzerland itself ([CH] button)
ZOV = 9                                    # zoom of the overview
ZMAX = 13                                  # deepest detail zoom (about 13 m per pixel at 46°: towns, roads, rivers)
ZMIN = 2                                   # the whole world in a handful of tiles
ZMAP = 8                                   # below this zoom the view is "the world": satellite everywhere, Switzerland
#                                            included (a small dark map in the middle of a satellite picture looked odd)
WORLD_URL = os.environ.get("ALPLINE_WORLD_TILES", "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g") \
    + "/{z}/{y}/{x}.jpg"
URL = "https://wmts.geo.admin.ch/1.0.0/{layer}/default/current/3857/{z}/{x}/{y}.{ext}"
LAYERS = {"base": ("ch.swisstopo.pixelkarte-grau", "jpeg"),
          "relief": ("ch.swisstopo.swissalti3d-reliefschattierung", "png"),
          "mask": ("ch.swisstopo.swissboundaries3d-land-flaeche.fill", "png"),
          "zones": ("ch.bazl.einschraenkungen-drohnen", "png")}
BG = (12, 16, 22)                          # page background (#0c1016)
STYLE = "tiles_v2"                         # v1: Switzerland only (tiles outside it were stored empty)


def merc(lon, lat, z):
    """lon/lat -> global pixel at zoom z (Web Mercator, 256 px tiles)."""
    n = 256 * 2 ** z
    la = math.radians(lat)
    return (lon + 180) / 360 * n, (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n


def zoom_for_scale(s, zov=ZOV, zmax=ZMAX):
    """Tile zoom for a view drawn at `s` screen pixels per overview pixel: the first zoom at least about as sharp as
    the screen (zov = the overview is enough)."""
    return max(zov, min(zmax, math.ceil(zov + math.log2(max(s, 1e-6)) - 0.35)))


def group_points(pts, radius):
    """[(item, (x, y))] -> [{"m": [(item, (x, y)), ...], "p": (x, y)}]: points closer than `radius` to a group's
    centre join it (the launcher's numbered badges). Order of the input decides who starts a group."""
    groups = []
    for item, p in pts:
        g = next((g for g in groups if math.hypot(g["p"][0] - p[0], g["p"][1] - p[1]) < radius), None)
        if g:
            g["m"].append((item, p))
            n = len(g["m"])
            g["p"] = (sum(q[1][0] for q in g["m"]) / n, sum(q[1][1] for q in g["m"]) / n)
        else:
            groups.append({"m": [(item, p)], "p": p})
    return groups


def in_wide(z, x, y) -> bool:
    """A tile that lies wholly inside the WIDE box is a swisstopo map tile; any other is satellite, and so is
    every tile of the zoomed-out world view (zoom below ZMAP)."""
    if z < ZMAP:
        return False
    x0, y0 = merc(WIDE[0], WIDE[3], z)
    x1, y1 = merc(WIDE[2], WIDE[1], z)
    return x * 256 >= x0 and (x + 1) * 256 <= x1 and y * 256 >= y0 and (y + 1) * 256 <= y1


def view_zoom(s, inside, zm=ZOV, zmin=ZMIN, zmax=ZMAX):
    """Tile zoom for a view drawn at `s` screen pixels per overview pixel. A view that stays inside the overview
    never needs less than the overview's own zoom; one that leaves it goes down to the world's zmin."""
    z = math.ceil(zm + math.log2(max(s, 1e-9)) - 0.35)
    return max(zm if inside else zmin, min(zmax, z))


def fetch_world(z, x, y, timeout=10):
    """One raw satellite tile as a PIL image, or None (no data there). Network errors raise."""
    from PIL import Image
    req = urllib.request.Request(WORLD_URL.format(z=z, x=x, y=y), headers={"User-Agent": "alpline-launcher"})
    try:
        data = urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.HTTPError:
        return None
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None


def style_world(img):
    """Satellite tile -> dark, slightly muted picture that sits with the dark map (dots and names stay readable)."""
    from PIL import Image, ImageEnhance
    if img is None:
        return Image.new("RGB", (256, 256), BG)
    img = ImageEnhance.Color(img).enhance(0.75)
    return Image.merge("RGB", tuple(c.point(lambda p, k=k: int(8 + p * k)) for c, k in zip(img.split(), (0.44, 0.48, 0.55))))


def tile_range(box, z):
    x0, y0 = merc(box[0], box[3], z)
    x1, y1 = merc(box[2], box[1], z)
    return int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)


def fetch(key, z, x, y, timeout=10):
    """One raw tile as a PIL image, or None (no data there). Network errors raise."""
    from PIL import Image
    layer, ext = LAYERS[key]
    req = urllib.request.Request(URL.format(layer=layer, z=z, x=x, y=y, ext=ext), headers={"User-Agent": "alpline-launcher"})
    try:
        data = urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.HTTPError:
        return None                        # outside the layer's data
    try:
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def style(base, relief, mask, zones, gx0=0, gy0=0):
    """Raw tiles -> (dark RGB map, zones RGBA or None). gx0 / gy0: global pixel of the tile's corner (keeps the
    zone hatch continuous from tile to tile)."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    size = base.size if base is not None else (256, 256)
    if base is None:
        return Image.new("RGB", size, BG), None
    g = base.convert("L")
    v = g.point(lambda p: 14 + (255 - p) * 0.42)                   # paper -> dark, lines and names -> light
    if relief is not None:
        shade = relief.convert("L").point(lambda p: int(min(255, 70 + p * 0.95)))
        neutral = Image.new("L", size, 134)                        # where there's no relief (outside CH): unchanged
        shade = Image.composite(shade, neutral, relief.getchannel("A").point(lambda a: 255 if a > 20 else 0))
        v = ImageChops.multiply(v.point(lambda p: min(255, p * 1.9)), shade)
    if mask is not None:                                           # outside Switzerland: dimmer
        inside = mask.getchannel("A").point(lambda a: 255 if a > 10 else 0).filter(ImageFilter.GaussianBlur(1.2))
        v = Image.composite(v, v.point(lambda p: p * 0.52), inside)
    rgb = Image.merge("RGB", (v.point(lambda p: p * 0.90), v.point(lambda p: p * 0.96), v.point(lambda p: min(255, p * 1.10 + 4))))
    zo = None
    if zones is not None:
        a = zones.getchannel("A").point(lambda p: 255 if p > 40 else 0)
        if a.getbbox():
            edge = ImageChops.subtract(a, a.filter(ImageFilter.MinFilter(3)))
            hatch = Image.new("L", size, 0)
            d = ImageDraw.Draw(hatch)
            off = (gx0 + gy0) % 9
            for k in range(-size[1] - off, size[0], 9):
                d.line([(k, size[1]), (k + size[1], 0)], fill=60, width=1)
            alpha = ImageChops.lighter(ImageChops.multiply(hatch, a), edge.point(lambda p: 200 if p else 0))
            zo = Image.new("RGBA", size, (255, 90, 90, 0))
            zo.putalpha(alpha)
    return rgb, zo


class Tiles:
    """Styled tiles on disk + downloads. Thread-safe enough for the launcher's few worker threads."""
    def __init__(self, cache: Path):
        self.dir = Path(cache) / STYLE
        self.lock = threading.Lock()

    def path(self, z, x, y, zones=False, ov=False, sat=False):
        """ov: a tile of the overview picture (always the map, also at its edges), kept apart from the view's tiles.
        sat: the satellite picture of a tile inside the WIDE box (shown around Switzerland, under its map)."""
        return self.dir / f"{z}{'ov' if ov else ''}{'sat' if sat else ''}" / f"{x}_{y}{'_z' if zones else ''}.png"

    def have(self, z, x, y, ov=False):
        return self.path(z, x, y, ov=ov).exists()

    def load(self, z, x, y, ov=False, sat=False):
        """(RGB, zones RGBA or None) from disk, or None."""
        from PIL import Image
        p = self.path(z, x, y, ov=ov, sat=sat)
        if not p.exists():
            return None
        try:
            rgb = Image.open(p).convert("RGB")
            pz = self.path(z, x, y, True, ov, sat)
            zo = Image.open(pz).convert("RGBA") if pz.exists() else None
            return rgb, zo
        except Exception:
            return None

    def get(self, z, x, y, ov=False):
        """Download, style and store one tile: the swisstopo map inside the WIDE box (and for the overview), the
        satellite picture elsewhere. Returns (RGB, zones or None). Network errors raise."""
        if ov or in_wide(z, x, y):
            raw = {k: fetch(k, z, x, y) for k in LAYERS}
            rgb, zo = style(raw["base"], raw["relief"], raw["mask"], raw["zones"], x * 256, y * 256)
        else:
            rgb, zo = style_world(fetch_world(z, x, y)), None
        p = self.path(z, x, y, ov=ov)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        rgb.save(tmp, "PNG", optimize=False)
        os.replace(tmp, p)
        pz = self.path(z, x, y, True, ov)
        if zo is not None:
            zo.save(pz)
        elif pz.exists():
            pz.unlink()
        return rgb, zo

    def get_sat(self, z, x, y):
        """The satellite picture of any tile, also inside the WIDE box (where get() gives the map)."""
        rgb = style_world(fetch_world(z, x, y))
        p = self.path(z, x, y, sat=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        rgb.save(tmp, "PNG", optimize=False)
        os.replace(tmp, p)
        return rgb, None

    def overview_mask(self, workers=6):
        """Where Switzerland is, over the overview's area (255 inside, 0 outside), from swisstopo's border layer:
        the launcher clips its map to the border with it and shows the satellite picture around."""
        from PIL import Image
        tx0, ty0, tx1, ty1 = tile_range(WIDE, ZOV)
        folder = self.dir / f"{ZOV}mask"
        folder.mkdir(parents=True, exist_ok=True)

        def one(k):
            f = folder / f"{k[0]}_{k[1]}.png"
            if not f.exists():
                t = fetch("mask", ZOV, *k)
                (t.getchannel("A") if t is not None else Image.new("L", (256, 256), 0)).save(f)
        keys = [(x, y) for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)]
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(one, keys))
        out = Image.new("L", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), 0)
        for x, y in keys:
            with Image.open(folder / f"{x}_{y}.png") as t:
                out.paste(t.convert("L").point(lambda a: 255 if a > 10 else 0), ((x - tx0) * 256, (y - ty0) * 256))
        # the layer draws Switzerland's outline at these zooms, not its area: fill it from outside (a corner far from
        # the border) and take what the fill cannot reach as the inside; the outline is thickened first so no gap leaks
        from PIL import ImageDraw, ImageFilter
        line = out.filter(ImageFilter.MaxFilter(5))
        ImageDraw.floodfill(line, (0, 0), 128)
        out = line.point(lambda v: 0 if v == 128 else 255)
        gx0, gy0 = merc(WIDE[0], WIDE[3], ZOV)
        gx1, gy1 = merc(WIDE[2], WIDE[1], ZOV)
        return out.crop((round(gx0 - tx0 * 256), round(gy0 - ty0 * 256), round(gx1 - tx0 * 256), round(gy1 - ty0 * 256)))

    def clear(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        for old in self.dir.parent.glob("tiles_v*"):        # tiles of older launchers (other styles): no longer used
            if old != self.dir:
                shutil.rmtree(old, ignore_errors=True)

    # ---------------------------------------------------------- overview
    def overview(self, workers=6, progress=None):
        """The whole WIDE area at zoom 9, stitched from styled tiles (downloaded when missing). Returns
        (RGB, zones RGBA, (gx0, gy0) global pixel of its top-left corner)."""
        from PIL import Image
        tx0, ty0, tx1, ty1 = tile_range(WIDE, ZOV)
        keys = [(x, y) for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)]
        todo = [k for k in keys if not self.have(ZOV, *k, ov=True)]
        done = [0]

        def one(k):
            self.get(ZOV, *k, ov=True)
            done[0] += 1
            if progress:
                progress(done[0], len(todo))
        if todo:
            with ThreadPoolExecutor(workers) as ex:
                list(ex.map(one, todo))           # re-raises the first network error
        W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
        rgb = Image.new("RGB", (W, H), BG)
        zo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for x, y in keys:
            t = self.load(ZOV, x, y, ov=True)
            if t:
                rgb.paste(t[0], ((x - tx0) * 256, (y - ty0) * 256))
                if t[1] is not None:
                    zo.paste(t[1], ((x - tx0) * 256, (y - ty0) * 256))
        gx0, gy0 = merc(WIDE[0], WIDE[3], ZOV)
        gx1, gy1 = merc(WIDE[2], WIDE[1], ZOV)
        box = (round(gx0 - tx0 * 256), round(gy0 - ty0 * 256), round(gx1 - tx0 * 256), round(gy1 - ty0 * 256))
        return rgb.crop(box), zo.crop(box), (gx0, gy0)

    # ---------------------------------------------------------- offline detail around locations
    def around(self, points, km=10.0, zooms=range(10, ZMAX + 1)):
        """Tile keys within km of each (lat, lon) point, for the given zooms."""
        keys = set()
        for la, lo in points:
            dla = km / 111.32
            dlo = km / (111.32 * math.cos(math.radians(la)))
            for z in zooms:
                x0, y0, x1, y1 = tile_range((lo - dlo, la - dla, lo + dlo, la + dla), z)
                keys.update((z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))
        return sorted(keys)

    def prefetch(self, points, km=10.0, workers=6, progress=None, stop=None):
        todo = [k for k in self.around(points, km) if not self.have(*k)]
        done, failed = [0], [0]

        def one(k):
            if stop and stop():
                return
            try:
                self.get(*k)
            except Exception:
                failed[0] += 1
            done[0] += 1
            if progress:
                progress(done[0], len(todo))
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(one, todo))
        return len(todo), failed[0]
