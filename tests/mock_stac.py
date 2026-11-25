"""Offline test helper: serves a fake swisstopo STAC API with synthetic terrain tiles
(one peak with a side ridge) so the full pipeline can be tested without internet.

    python tests/mock_stac.py  &      # serves on :8765
    FPV3D_STAC_BASE=http://127.0.0.1:8765/api/stac/v0.9 python -m fpv3d build locations/my_spot.yaml
"""
import http.server
import os
import time
import json
import re
import socketserver
import sys
import tempfile
import urllib.parse
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fpv3d.geo import wgs84_to_lv95  # noqa: E402

PORT = int(os.environ.get("MOCK_PORT", "8765"))
TMP = Path(tempfile.mkdtemp(prefix="mockstac_"))
PEAK = wgs84_to_lv95(46.5486, 7.0181)


def height(E, N):
    dx, dy = (E - PEAK[0]) / 1000, (N - PEAK[1]) / 1000
    h = 1050 + 950 * np.exp(-(dx ** 2 / 1.1 + dy ** 2 / 0.6))           # main peak
    h += 300 * np.exp(-((dx - 1.6) ** 2 / 0.3 + (dy + 0.8) ** 2 / 1.5))  # a side ridge
    h += 25 * np.sin(E / 170.0) * np.cos(N / 230.0)
    return h.astype(np.float32)


# a small village (LV95 rectangles: e0, n0, e1, n1, height) for the buildings test
VILLAGE = []
_rng = np.random.default_rng(3)
for i in range(6):
    for j in range(4):
        e0 = PEAK[0] - 1500 + i * 45 + _rng.uniform(0, 8)
        n0 = PEAK[1] - 1100 + j * 40 + _rng.uniform(0, 8)
        w, d = _rng.uniform(10, 25), _rng.uniform(9, 18)
        VILLAGE.append((float(e0), float(n0), float(e0 + w), float(n0 + d), float(_rng.choice([4, 7, 10, 14]))))


def buildings_at(E, N):
    out = np.zeros(E.shape, np.float32)
    for e0, n0, e1, n1, hh in VILLAGE:
        out[(E >= e0) & (E <= e1) & (N >= n0) & (N <= n1)] = hh
    return out


def make_tile(kind, ke, kn, gsd):
    n = int(1000 / gsd)
    p = TMP / f"{kind}_{ke}-{kn}_{gsd}.tif"
    if p.exists():
        return p
    xs = ke * 1000 + (np.arange(n) + 0.5) * gsd
    ys = (kn + 1) * 1000 - (np.arange(n) + 0.5) * gsd
    E, N = np.meshgrid(xs, ys)
    h = height(E, N)
    tr = from_origin(ke * 1000, (kn + 1) * 1000, gsd, gsd)
    if kind == "ortho":
        t = np.clip((h - 1000) / 1000, 0, 1)
        rgb = np.stack([60 + 120 * t, 110 + 60 * t, 50 + 150 * t]).astype(np.uint8)
        rgb[:, (E.astype(int) // 50 + N.astype(int) // 50) % 7 == 0] = 90  # some texture
        rgb[:, buildings_at(E, N) > 0] = np.array([[150], [70], [60]], np.uint8)  # red roofs
        with rasterio.open(p, "w", driver="GTiff", width=n, height=n, count=3, dtype="uint8",
                           crs="EPSG:2056", transform=tr) as d:
            d.write(rgb)
    else:
        if kind == "dsm":
            bl = buildings_at(E, N)
            h = h + (np.random.default_rng(ke * 7 + kn).random(h.shape) > 0.6) * 18 * (bl == 0)  # "trees"
            h = h + bl
        with rasterio.open(p, "w", driver="GTiff", width=n, height=n, count=1, dtype="float32",
                           crs="EPSG:2056", transform=tr) as d:
            d.write(h, 1)
    return p


def world_height(lat, lon):
    """The fake worldwide model: a slope rising to the north-east, with ripples."""
    return (800 + 4000 * (lat % 1) + 2000 * (lon % 1) + 30 * np.sin(lat * 900) * np.cos(lon * 700)).astype(np.float32)


PHOTO_SPOT = (47.26, 11.39)     # lat, lon where the fake photo is mid-grey (the test location abroad)


def make_photo_tile(z, x, y):
    """A tile of the fake satellite photo: around PHOTO_SPOT red grows to the east and green to the north
    (about 20 levels per km), blue is constant."""
    import io
    from PIL import Image
    n = 1 << z
    lon = ((x + (np.arange(256) + 0.5) / 256) / n) * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + (np.arange(256) + 0.5) / 256) / n))))
    LO, LA = np.meshgrid(lon, lat)
    rgb = np.stack([np.clip(128 + 1500 * (LO - PHOTO_SPOT[1]), 0, 255), np.clip(128 + 1500 * (LA - PHOTO_SPOT[0]), 0, 255),
                    np.full(LO.shape, 120.0)], 2).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "JPEG", quality=95)
    return buf.getvalue()


FRANCE_SPOT = (45.62, 6.77)     # lat, lon of the test location in France (Bourg-Saint-Maurice: outside the Swiss band)
FRANCE_EAST_EDGE = 6.775        # the fake IGN has nothing east of this longitude (as across a real border)


def ign_height(lat, lon):
    """The fake IGN heights: a plane rising north (3 m per 0.001 degree) and east, far from the worldwide model."""
    return (1100 + 3000 * (lat - 45.6) + 1000 * (lon - 6.75)).astype(np.float32)


def make_ign_photo(z, x, y):
    """A tile of the fake IGN photo, or None (no picture east of FRANCE_EAST_EDGE). Around FRANCE_SPOT red grows to
    the east and green to the north; blue is 200 (the satellite's is 120), so the test can tell them apart."""
    import io
    from PIL import Image
    n = 1 << z
    lon = ((x + (np.arange(256) + 0.5) / 256) / n) * 360 - 180
    if lon[0] >= FRANCE_EAST_EDGE:
        return None
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + (np.arange(256) + 0.5) / 256) / n))))
    LO, LA = np.meshgrid(lon, lat)
    rgb = np.stack([np.clip(128 + 6000 * (LO - FRANCE_SPOT[1]), 20, 235), np.clip(128 + 6000 * (LA - FRANCE_SPOT[0]), 20, 235),
                    np.full(LO.shape, 200.0)], 2).astype(np.uint8)
    rgb[LO >= FRANCE_EAST_EDGE] = 0                          # a tile across the edge: its outside part is black
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def make_ign_heights(crs, bbox, w, h):
    """The fake IGN height service: 32 bit floats for a box on any grid, -99999 east of FRANCE_EAST_EDGE."""
    from fpv3d.geo import unproject
    e0, n0, e1, n1 = bbox
    E, N = np.meshgrid(e0 + (np.arange(w) + 0.5) * (e1 - e0) / w, n1 - (np.arange(h) + 0.5) * (n1 - n0) / h)
    lat, lon = unproject(E.ravel(), N.ravel(), crs)
    z = ign_height(np.asarray(lat), np.asarray(lon))
    z[np.asarray(lon) >= FRANCE_EAST_EDGE] = -99999.0
    return z.astype("<f4").tobytes()


US_SPOT = (40.0, -105.27)       # lat, lon of the test location in the United States (Boulder, Colorado)
US_EAST_EDGE = -105.265         # the fake USGS services have nothing east of this longitude (as across a border)


def usgs_height(lat, lon):
    """The fake 3DEP heights: a plane rising north (2 m per 0.001 degree) and east, far from the worldwide model."""
    return (1600 + 2000 * (lat - 40.0) + 1000 * (lon + 105.3)).astype(np.float32)


def make_usgs_export(service, q):
    """The fake USGS exportImage of both services: a box on any grid (bboxSR = imageSR, an EPSG number), heights as a
    32 bit GeoTIFF (-99999 east of US_EAST_EDGE), the photo as a JPEG (black there). Around US_SPOT red grows to the
    east and green to the north; blue is 60 (the satellite's is 120), so the test can tell them apart."""
    import io
    from PIL import Image
    from fpv3d.geo import unproject
    e0, n0, e1, n1 = [float(v) for v in q["bbox"].split(",")]
    w, h = [int(v) for v in q["size"].split(",")]
    E, N = np.meshgrid(e0 + (np.arange(w) + 0.5) * (e1 - e0) / w, n1 - (np.arange(h) + 0.5) * (n1 - n0) / h)
    lat, lon = unproject(E.ravel(), N.ravel(), f"EPSG:{q['imageSR']}")
    LA, LO = np.asarray(lat).reshape(h, w), np.asarray(lon).reshape(h, w)
    out = LO >= US_EAST_EDGE
    if service == "3dep":
        from rasterio.io import MemoryFile
        from rasterio.transform import from_bounds
        z = usgs_height(LA, LO)
        z[out] = -99999.0
        with MemoryFile() as mf:
            with mf.open(driver="GTiff", width=w, height=h, count=1, dtype="float32", crs=f"EPSG:{q['imageSR']}",
                         transform=from_bounds(e0, n0, e1, n1, w, h)) as d:
                d.write(z, 1)
            return mf.read()
    rgb = np.stack([np.clip(128 + 6000 * (LO - US_SPOT[1]), 20, 235), np.clip(128 + 6000 * (LA - US_SPOT[0]), 20, 235),
                    np.full(LO.shape, 60.0)], 2).astype(np.uint8)
    rgb[out] = 0
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def make_worldcover(folder, lat, lon, n=2400, hole=None):
    """One 1 degree file of the fake 2021 satellite picture, where the real ones are (rgbnir/2021/N47/...), in the
    real layout: red, green, blue, infrared as reflectance x 10000. It shows the same colours as make_photo_tile
    (red grows east, green north around PHOTO_SPOT) once Alpline has turned it into an ordinary picture.
    `hole` (west, south, east, north in degrees): no picture there, as the real files have over glaciers."""
    from fpv3d.worldcover import GAMMA, WHITE, square_path
    p = Path(folder) / square_path(lat, lon)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        lons = lon + (np.arange(n) + 0.5) / n
        lats = lat + 1 - (np.arange(n) + 0.5) / n
        LO, LA = np.meshgrid(lons, lats)
        seen = np.stack([np.clip(128 + 1500 * (LO - PHOTO_SPOT[1]), 0, 255), np.clip(128 + 1500 * (LA - PHOTO_SPOT[0]), 0, 255),
                         np.full(LO.shape, 120.0), np.full(LO.shape, 200.0)])
        dn = np.maximum(1, np.round(WHITE * (seen / 255.0) ** GAMMA)).astype(np.uint16)     # undo the picture curve
        if hole:
            dn[:, (LO > hole[0]) & (LO < hole[2]) & (LA > hole[1]) & (LA < hole[3])] = 0
        with rasterio.open(p, "w", driver="GTiff", width=n, height=n, count=4, dtype="uint16", crs="EPSG:4326", nodata=0,
                           tiled=True, compress="deflate", transform=from_origin(lon, lat + 1, 1 / n, 1 / n)) as d:
            d.write(dn)
    return p


def make_square(lat, lon, n=1200):
    """A 1 degree square of the fake worldwide model (3 arc-seconds to keep it light), like Copernicus' files."""
    p = TMP / f"world_{lat}_{lon}.tif"
    if not p.exists():
        lons = lon + (np.arange(n) + 0.5) / n
        lats = lat + 1 - (np.arange(n) + 0.5) / n
        LO, LA = np.meshgrid(lons, lats)
        with rasterio.open(p, "w", driver="GTiff", width=n, height=n, count=1, dtype="float32", crs="EPSG:4326",
                           transform=from_origin(lon, lat + 1, 1 / n, 1 / n)) as d:
            d.write(world_height(LA, LO), 1)
    return p


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        m = re.match(r"/api/stac/v0.9/collections/([^/]+)/items", u.path)
        if m:
            coll = m.group(1)
            kind = {"ch.swisstopo.swissalti3d": "dtm", "ch.swisstopo.swisssurface3d-raster": "dsm",
                    "ch.swisstopo.swissimage-dop10": "ortho"}[coll]
            lo1, la1, lo2, la2 = map(float, urllib.parse.parse_qs(u.query)["bbox"][0].split(","))
            e1, n1 = wgs84_to_lv95(la1, lo1)
            e2, n2 = wgs84_to_lv95(la2, lo2)
            feats = []
            for ke in range(int(e1 // 1000), int(e2 // 1000) + 1):
                for kn in range(int(n1 // 1000), int(n2 // 1000) + 1):
                    for year in (2019, 2022):  # two vintages to test "latest" selection
                        gsds = {"dtm": [0.5, 2.0], "dsm": [0.5], "ortho": [0.1, 2.0]}[kind]
                        assets = {f"{kind}_{ke}-{kn}_{g}.tif": {
                            "href": f"http://127.0.0.1:{PORT}/tiles/{kind}/{ke}/{kn}/{g}/{kind}_{year}_{ke}-{kn}_{g}.tif",
                            "eo:gsd": g, "type": "image/tiff"} for g in gsds}
                        feats.append({"id": f"{coll}_{year}_{ke}-{kn}",
                                      "properties": {"datetime": f"{year}-01-01T00:00:00Z"},
                                      "assets": assets})
            body = json.dumps({"features": feats, "links": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        m = re.match(r"/copernicus/Copernicus_DSM_COG_10_([NS])(\d+)_00_([EW])(\d+)_00_DEM/", u.path)
        if m:                           # worldwide model: 1 degree squares, the southern hemisphere is "all sea"
            if m.group(1) == "S":
                return self.send_error(404)
            data = make_square(int(m.group(2)), int(m.group(4)) * (1 if m.group(3) == "E" else -1)).read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        m = re.match(r"/s2/(\d+)/(\d+)/(\d+)\.jpg", u.path)
        if m:                           # worldwide satellite photo: web-map tiles, zoom / row / column
            data = make_photo_tile(int(m.group(1)), int(m.group(3)), int(m.group(2)))
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path in ("/ign/wmts", "/ign/wms-r"):          # France: IGN's photo tiles and height service
            q = {k.upper(): v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            if u.path == "/ign/wmts":
                data = make_ign_photo(int(q["TILEMATRIX"]), int(q["TILECOL"]), int(q["TILEROW"]))
                if data is None:
                    return self.send_error(404, "No data found")
            else:
                data = make_ign_heights(q["CRS"], [float(v) for v in q["BBOX"].split(",")], int(q["WIDTH"]), int(q["HEIGHT"]))
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        m = re.match(r"/usgs/(3dep|naip)/exportImage$", u.path)
        if m:                           # United States: the 3DEP height and NAIP photo services
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            if int(q["size"].split(",")[0]) > 3000:
                data = b"<html><body>Error exporting image</body></html>"      # as the real one: an HTML "200 OK"
            else:
                data = make_usgs_export(m.group(1), q)
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        m = re.match(r"/tiles/(\w+)/(\d+)/(\d+)/([\d.]+)/", u.path)
        if m:
            kind, ke, kn, g = m.group(1), int(m.group(2)), int(m.group(3)), float(m.group(4))
            g = (max(g, 0.5) if kind == "ortho" else max(g, 2.0)) if kind != "dsm" else 1.0  # keep the mock light
            data = make_tile(kind, ke, kn, g).read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            slow = float(os.environ.get("MOCK_SLOW", "0"))    # seconds per tile, to watch the map animation
            for i in range(10):
                self.wfile.write(data[i * len(data) // 10:(i + 1) * len(data) // 10])
                self.wfile.flush()
                if slow:
                    time.sleep(slow / 10)
            return
        self.send_error(404)

    def do_POST(self):          # Overpass API (OpenStreetMap buildings)
        from fpv3d.geo import lv95_to_wgs84 as l2w
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        els = []
        for i, (e0, n0, e1, n1, hh) in enumerate(VILLAGE):
            ring = [(e0, n0), (e1, n0), (e1, n1), (e0, n1), (e0, n0)]
            geom = [dict(zip(("lat", "lon"), map(float, l2w(e, n)))) for e, n in ring]
            tags = {"building": "house" if hh < 12 else "apartments"}
            if i % 5 == 0:
                tags["building:levels"] = str(int(hh // 3))
            els.append(dict(type="way", id=1000 + i, tags=tags, geometry=geom))
        body = json.dumps(dict(elements=els)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H) as s:
        print(f"mock STAC on :{PORT}")
        s.serve_forever()
