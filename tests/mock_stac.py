"""Offline test helper: serves a fake swisstopo STAC API with synthetic terrain tiles
(a Moléson-like peak) so the full pipeline can be tested without internet.

    python tests/mock_stac.py  &      # serves on :8765
    FPV3D_STAC_BASE=http://127.0.0.1:8765/api/stac/v0.9 python -m fpv3d build locations/moleson.yaml
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
    h += 300 * np.exp(-((dx - 1.6) ** 2 / 0.3 + (dy + 0.8) ** 2 / 1.5))  # side ridge (Teysachaux-ish)
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
