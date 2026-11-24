"""France: the national aerial photo (BD ORTHO, 15-20 cm) and bare-ground heights (RGE ALTI, 1 m) of IGN.

Both come from IGN's Geoplateforme, no account needed (checked 24 November 2026):
  photo   web-map tiles  https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&LAYER=ORTHOIMAGERY.ORTHOPHOTOS
          &TILEMATRIXSET=PM&TILEMATRIX=<zoom>&TILEROW=<row>&TILECOL=<column>  (zoom 19 at most; "404 No data found"
          where there is no French picture)
  heights a WMS that cuts any box on any grid (UTM, the Swiss grid ...) and answers 32 bit floats:
          https://data.geopf.fr/wms-r?...&LAYERS=ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES&FORMAT=image/x-bil;bits=32
          (-99999 where there is no French height)
Licence: Licence Ouverte / Open License 2.0 (Etalab), read in IGN's own catalogue records IGNF_BD-ORTHO and
IGNF_RGE-ALTI. It asks for the source to be named: "IGN - BD ORTHO" and "IGN - RGE ALTI".

The heights are "altitudes normales" (NGF-IGN69), within a few decimetres of the sea-level heights of the worldwide
model. RGE ALTI is bare ground only: a location asking for trees and buildings ("dsm") keeps the worldwide model.

Only places inside France's outline (roughly: mainland and Corsica, Switzerland left out) ask IGN; where IGN has
nothing after all (across a border) the worldwide sources fill in, tile by tile and, for the photo, pixel by pixel.
"""
from __future__ import annotations

import io
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import sources
from .geo import unproject

BASE = os.environ.get("FPV3D_IGN_BASE", "https://data.geopf.fr")
HALF_WORLD = 20037508.342789244          # web mercator: the world is a square of 2 x this, in metres
MAX_ZOOM, MIN_ZOOM = 19, 12
PHOTO_NATIVE_M = 0.2
HEIGHT_STEPS = (1.0, 5.0)                # the detail the heights are fetched at (m): RGE ALTI is 1 m
NODATA = -99999.0
MARGIN = 100                             # m fetched around a 1 km tile, for the resampling at its edges
PHOTO_CREDIT = "IGN - BD ORTHO (aerial photo of France), Licence Ouverte / Open License 2.0 (Etalab)"
HEIGHT_CREDIT = "IGN - RGE ALTI (1 m heights of France), Licence Ouverte / Open License 2.0 (Etalab)"

# France's outline, generous by a few kilometres except along the Swiss border, (lon, lat)
_MAINLAND = [(-5.3, 48.3), (-5.2, 48.9), (-1.9, 49.8), (1.3, 50.2), (1.5, 51.0), (2.5, 51.15), (3.2, 50.8),
             (4.2, 50.3), (4.9, 50.2), (5.8, 49.6), (6.4, 49.5), (7.6, 49.1), (8.25, 49.0), (7.6, 47.6), (7.0, 47.5),
             (6.68, 47.07), (6.12, 46.55), (5.96, 46.13), (6.20, 46.13), (6.21, 46.19), (6.30, 46.25), (6.32, 46.30),
             (6.80, 46.38), (6.78, 46.20), (6.88, 46.12), (6.95, 46.06), (6.99, 46.03), (7.04, 45.92), (6.86, 45.83),
             (6.80, 45.74), (6.88, 45.66), (7.13, 45.25), (6.75, 44.95), (6.95, 44.40), (7.70, 44.15), (7.55, 43.78),
             (7.7, 43.0), (4.0, 43.0), (3.3, 42.3), (1.7, 42.45), (-0.5, 42.75), (-1.8, 43.3), (-2.0, 43.5),
             (-1.6, 46.0), (-3.2, 47.0)]


def _inside(lon: float, lat: float, poly) -> bool:
    """Point in polygon (a ray to the east crosses the outline an odd number of times)."""
    inside, j = False, len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def covers(lat: float, lon: float) -> bool:
    return _inside(lon, lat, _MAINLAND) or (41.3 <= lat <= 43.1 and 8.5 <= lon <= 9.6)       # + Corsica


def _ua():
    from .swisstopo import _UA
    return _UA


def _get(url: str, name: str, tries: int = 3) -> bytes:
    """One download, retried on network hiccups. IGN's servers sometimes answer a request that works a second later
    with "400 Bad Request" (seen once in a dozen builds): that is retried too; "404" (no data) is not."""
    import time
    from .swisstopo import _retry

    def get():
        with urllib.request.urlopen(urllib.request.Request(url, headers=_ua()), timeout=60) as r:
            return r.read()
    for attempt in range(tries):
        try:
            return _retry(get, name)
        except urllib.error.HTTPError as ex:
            if ex.code != 400 or attempt == tries - 1:
                raise
            print(f"\n    {name}: HTTP 400, retrying in {3 * (attempt + 1)} s", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise AssertionError("unreachable")


def _corners(key, crs):
    """lat, lon of a 1 km tile's corners (+ MARGIN around)."""
    e = np.linspace(key[0] * 1000 - MARGIN, (key[0] + 1) * 1000 + MARGIN, 5)
    n = np.linspace(key[1] * 1000 - MARGIN, (key[1] + 1) * 1000 + MARGIN, 5)
    E, N = np.meshgrid(e, n)
    return unproject(E.ravel(), N.ravel(), crs)


# ---------------------------------------------------------------- photo

def tile_at(lat: float, lon: float, z: int) -> Tuple[int, int]:
    """(column, row) of the web-map tile holding a place at zoom z."""
    n = 1 << z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tile_bounds(z: int, x: int, y: int):
    """(west, north, size) of a tile in web-mercator metres."""
    size = 2 * HALF_WORLD / (1 << z)
    return -HALF_WORLD + x * size, HALF_WORLD - y * size, size


def zoom_for(res: float, lat: float) -> int:
    """The coarsest zoom whose pixels are at least as fine as `res` metres on the ground at `lat`."""
    ground = 2 * HALF_WORLD / 256 * math.cos(math.radians(lat))      # metres per pixel at zoom 0
    z = math.ceil(math.log2(ground / max(res, 0.01)))
    return min(max(z, MIN_ZOOM), MAX_ZOOM)


class IgnPhoto(sources.TerrainSource):
    name = "ign_photo"
    host = "data.geopf.fr"
    kinds = ("ortho",)
    credit = PHOTO_CREDIT
    native_m = PHOTO_NATIVE_M
    patchy = True                        # across the border its web tiles are missing: the satellite fills them

    def __init__(self, crs: str):
        self.crs = crs
        self.cache_prefix = f"{self.name}/{crs.split(':')[-1]}"

    def raw_dir(self, root: Path, kind: str) -> Path:
        return Path(root) / self.name / "raw"

    def resampling(self, kind: str, res: float):
        from rasterio.warp import Resampling
        return Resampling.bilinear if res < PHOTO_NATIVE_M else Resampling.average

    def tiles(self, key, res: float) -> List[Tuple[int, int, int]]:
        """The (zoom, column, row) web-map tiles a 1 km tile (+ margin) lies in, at the zoom that `res` needs."""
        lat, _ = _corners(key, self.crs)
        return self.tiles_at(key, zoom_for(res, float(lat.max())))

    def tiles_at(self, key, z: int) -> List[Tuple[int, int, int]]:
        lat, lon = _corners(key, self.crs)
        x0, y0 = tile_at(float(lat.max()), float(lon.min()), z)
        x1, y1 = tile_at(float(lat.min()), float(lon.max()), z)
        return [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]

    def _file(self, root: Path, t) -> Path:
        return self.raw_dir(root, "ortho") / f"{t[0]}-{t[1]}-{t[2]}.tif"

    def raw_names(self, key) -> set:
        """Names of the downloads a 1 km tile can be made from (every zoom): what the cache clean-up keeps."""
        return {f"{z}-{x}-{y}" for zz in range(MIN_ZOOM, MAX_ZOOM + 1) for z, x, y in self.tiles_at(key, zz)}

    def local_raw(self, root: Path, kind: str, key, res: float) -> List[Path]:
        have = []
        for t in self.tiles(key, res):
            f = self._file(root, t)
            if f.exists() and f.stat().st_size > 0:
                have.append(f)
            elif not f.with_suffix(".missing").exists():
                return []                                           # one tile was never asked for: go online
        return have

    def lookup(self, kind: str, keys, res: float) -> Dict[tuple, List[sources.Found]]:
        """No catalogue to ask: the tile numbers follow from the position."""
        out = {}
        for k in keys:
            out[tuple(k)] = [sources.Found(
                f"{BASE}/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&STYLE=normal"
                f"&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/jpeg",
                dict(source=f"IGN BD ORTHO {z}/{y}/{x}", tile=[z, x, y])) for z, x, y in self.tiles(k, res)]
        return out

    def download(self, root: Path, kind: str, found: sources.Found, on_progress=None) -> Optional[Path]:
        import rasterio
        from PIL import Image
        from rasterio.transform import from_origin
        z, x, y = found.info["tile"]
        dest = self._file(root, (z, x, y))
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        missing = dest.with_suffix(".missing")
        if missing.exists():
            return None
        try:
            data = _get(found.href, dest.name)
        except urllib.error.HTTPError as ex:
            if ex.code != 404:
                raise
            dest.parent.mkdir(parents=True, exist_ok=True)
            missing.touch()                                         # outside France: no picture here
            return None
        rgb = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
        west, north, size = tile_bounds(z, x, y)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with rasterio.open(tmp, "w", driver="GTiff", width=rgb.shape[1], height=rgb.shape[0], count=3, dtype="uint8",
                           crs="EPSG:3857", compress="deflate",
                           transform=from_origin(west, north, size / rgb.shape[1], size / rgb.shape[0])) as d:
            d.write(np.transpose(rgb, (2, 0, 1)))
        tmp.replace(dest)
        return dest


# ---------------------------------------------------------------- heights

def height_step(res: float) -> float:
    """The detail to fetch for heights wanted at `res` m. Always 1 m, averaged here, below 20 m: IGN's service
    thins coarser answers out without smoothing them, which leaves fine straight lines in the relief (seen
    24 November 2026 at 2, 5 and 10 m, on every grid, its own Lambert-93 included). From 20 m on, the average of 16
    points or more hides them, and 1 m would mean 6 MB per square kilometre."""
    return 1.0 if res < 20 else 5.0


class IgnHeights(sources.TerrainSource):
    name = "ign_alti"
    host = "data.geopf.fr"
    kinds = ("dtm",)
    credit = HEIGHT_CREDIT

    def __init__(self, crs: str):
        self.crs = crs
        self.cache_prefix = f"{self.name}/{crs.split(':')[-1]}"

    def raw_dir(self, root: Path, kind: str) -> Path:
        return Path(root) / self.name / "raw"

    def resampling(self, kind: str, res: float):
        from rasterio.warp import Resampling
        return Resampling.bilinear if res < HEIGHT_STEPS[0] else Resampling.average

    def _stem(self, key, step: float) -> str:
        # the files are cut on a grid: its number keeps the same tile of two grids apart (UTM 31 / 32, LV95)
        return f"{self.crs.split(':')[-1]}-{key[0]}-{key[1]}-{step:g}m"

    def raw_names(self, key) -> set:
        return {self._stem(key, s) for s in HEIGHT_STEPS} | {self._stem(key, 0)}

    def local_raw(self, root: Path, kind: str, key, res: float) -> List[Path]:
        folder = self.raw_dir(root, kind)
        if (folder / f"{self._stem(key, 0)}.missing").exists():
            return []                     # IGN has nothing here: the empty answer is remembered by download()
        for s in HEIGHT_STEPS:
            if s <= height_step(res):
                f = folder / f"{self._stem(key, s)}.tif"
                if f.exists() and f.stat().st_size > 0:
                    return [f]
        return []

    def lookup(self, kind: str, keys, res: float) -> Dict[tuple, List[sources.Found]]:
        """No catalogue to ask: the WMS cuts the box asked for."""
        step = height_step(res)
        out = {}
        for k in keys:
            n = int(round((1000 + 2 * MARGIN) / step))
            bbox = f"{k[0] * 1000 - MARGIN},{k[1] * 1000 - MARGIN},{(k[0] + 1) * 1000 + MARGIN},{(k[1] + 1) * 1000 + MARGIN}"
            out[tuple(k)] = [sources.Found(
                f"{BASE}/wms-r?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES"
                f"&STYLES=&CRS={self.crs}&BBOX={bbox}&WIDTH={n}&HEIGHT={n}&FORMAT=image/x-bil;bits=32",
                dict(source=f"IGN RGE ALTI {step:g} m", key=list(k), step=step))]
        return out

    def download(self, root: Path, kind: str, found: sources.Found, on_progress=None) -> Optional[Path]:
        import rasterio
        from rasterio.transform import from_origin
        k, step = tuple(found.info["key"]), float(found.info["step"])
        folder = self.raw_dir(root, kind)
        dest = folder / f"{self._stem(k, step)}.tif"
        missing = folder / f"{self._stem(k, 0)}.missing"
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        if missing.exists():
            return None
        n = int(round((1000 + 2 * MARGIN) / step))
        data = _get(found.href, dest.name)
        if len(data) != n * n * 4:
            raise OSError(f"IGN heights: unexpected answer ({len(data)} bytes, {data[:120]!r})")
        z = np.frombuffer(data, "<f4").reshape(n, n)
        folder.mkdir(parents=True, exist_ok=True)
        if not (z > -1000).any():
            missing.touch()                                         # outside France: nothing here
            return None
        tmp = dest.with_suffix(".part")
        with rasterio.open(tmp, "w", driver="GTiff", width=n, height=n, count=1, dtype="float32", crs=self.crs,
                           nodata=NODATA, compress="deflate", predictor=3,
                           transform=from_origin(k[0] * 1000 - MARGIN, (k[1] + 1) * 1000 + MARGIN, step, step)) as d:
            d.write(np.where(z > -1000, z, NODATA).astype("float32"), 1)
        tmp.replace(dest)
        return dest


def register():
    sources.register_regional("ign_alti", "France, 1 m heights (IGN)", ("dtm",), covers, IgnHeights)
    sources.register_regional("ign_photo", "France, aerial photo (IGN)", ("ortho",), covers, IgnPhoto)


register()
