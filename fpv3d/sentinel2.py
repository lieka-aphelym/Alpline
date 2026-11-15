"""Worldwide aerial photo: the Sentinel-2 cloudless mosaic of 2016 by EOX (satellite, about 10 m per pixel).

Served as ordinary 256 px web-map tiles, no account needed:
    https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/<zoom>/<row>/<column>.jpg
Only the 2016 mosaic is used: it is the one free for any use (CC BY 4.0); the later years are non-commercial only.
Zoom 14 (about 10 m per pixel at the equator, finer towards the poles) is the data's own detail; higher zooms are
the same picture enlarged.

Each downloaded tile is saved as a small GeoTIFF that knows where it is, so the tile cache can resample it like any
other terrain file.

Credit, to be shown wherever the picture is used: Sentinel-2 cloudless - https://cloudless.eox.at by EOX IT Services
GmbH (Contains modified Copernicus Sentinel data 2016), CC BY 4.0.
"""
from __future__ import annotations

import io
import math
import os
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import sources
from .geo import unproject

BASE = os.environ.get("FPV3D_SENTINEL2_BASE", "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g")
MAX_ZOOM = 14
NATIVE_M = 10.0
HALF_WORLD = 20037508.342789244          # web mercator: the world is a square of 2 x this, in metres
CREDIT = ("Sentinel-2 cloudless - https://cloudless.eox.at by EOX IT Services GmbH "
          "(Contains modified Copernicus Sentinel data 2016), CC BY 4.0")


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


class Sentinel2(sources.TerrainSource):
    name = "sentinel2"
    host = "tiles.maps.eox.at"
    kinds = ("ortho",)
    credit = CREDIT
    native_m = NATIVE_M

    def __init__(self, crs: str):
        self.crs = crs
        self.cache_prefix = f"sentinel2/{crs.split(':')[-1]}"       # resampled tiles: one folder per grid

    def raw_dir(self, root: Path, kind: str) -> Path:
        return Path(root) / "sentinel2" / "raw"                     # the downloads are shared by every grid

    def resampling(self, kind: str, res: float):
        from rasterio.warp import Resampling
        return Resampling.bilinear if res < NATIVE_M else Resampling.average

    def tiles(self, key) -> List[Tuple[int, int, int]]:
        """The (zoom, column, row) web-map tiles a 1 km tile (+ 100 m around) lies in."""
        e = np.linspace(key[0] * 1000 - 100, (key[0] + 1) * 1000 + 100, 5)
        n = np.linspace(key[1] * 1000 - 100, (key[1] + 1) * 1000 + 100, 5)
        E, N = np.meshgrid(e, n)
        lat, lon = unproject(E.ravel(), N.ravel(), self.crs)
        x0, y0 = tile_at(float(lat.max()), float(lon.min()), MAX_ZOOM)     # north-west corner
        x1, y1 = tile_at(float(lat.min()), float(lon.max()), MAX_ZOOM)
        return [(MAX_ZOOM, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]

    def _file(self, root: Path, t) -> Path:
        return self.raw_dir(root, "ortho") / f"{t[0]}-{t[1]}-{t[2]}.tif"

    def raw_names(self, key) -> set:
        """Names (without .tif) of the downloads a 1 km tile is made from: what the cache clean-up must keep."""
        return {f"{z}-{x}-{y}" for z, x, y in self.tiles(key)}

    def local_raw(self, root: Path, kind: str, key, res: float) -> List[Path]:
        files = [self._file(root, t) for t in self.tiles(key)]
        return files if all(f.exists() and f.stat().st_size > 0 for f in files) else []

    def lookup(self, kind: str, keys, res: float) -> Dict[tuple, List[sources.Found]]:
        """No catalogue to ask: the tile numbers follow from the position."""
        return {tuple(k): [sources.Found(f"{BASE}/{z}/{y}/{x}.jpg", dict(source=f"s2cloudless 2016 {z}/{y}/{x}", tile=[z, x, y]))
                           for z, x, y in self.tiles(k)] for k in keys}

    def download(self, root: Path, kind: str, found: sources.Found, on_progress=None) -> Optional[Path]:
        import rasterio
        from PIL import Image
        from rasterio.transform import from_origin
        from .swisstopo import _UA, _retry
        z, x, y = found.info["tile"]
        dest = self._file(root, (z, x, y))
        if dest.exists() and dest.stat().st_size > 0:
            return dest

        def get():
            with urllib.request.urlopen(urllib.request.Request(found.href, headers=_UA), timeout=60) as r:
                return r.read()
        rgb = np.asarray(Image.open(io.BytesIO(_retry(get, dest.name))).convert("RGB"))
        west, north, size = tile_bounds(z, x, y)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with rasterio.open(tmp, "w", driver="GTiff", width=rgb.shape[1], height=rgb.shape[0], count=3, dtype="uint8",
                           crs="EPSG:3857", compress="deflate",
                           transform=from_origin(west, north, size / rgb.shape[1], size / rgb.shape[0])) as d:
            d.write(np.transpose(rgb, (2, 0, 1)))
        tmp.replace(dest)
        return dest
