"""Worldwide aerial photo: the ESA WorldCover Sentinel-2 composite of 2021 (satellite, 10 m per pixel).

One picture of the whole of 2021: for every pixel the middle value of that year's cloud-free Sentinel-2 passes. So it
is free of clouds and seams, five years newer than the Sentinel-2 cloudless mosaic of 2016 (sentinel2.py, kept as
the fallback) and sharper, but it shows the *average* of a year: ground that is under snow for most of it (high
ridges) looks white and hazy, where the 2016 mosaic shows summer.
Where snow lies all year (glaciers, the highest summits) it has no picture at all: the files hold 0 there,
and those holes are filled from the 2016 mosaic (terrain.orthophoto).

One GeoTIFF per 1 x 1 degree on AWS, no account needed, named by its south-west corner like the Copernicus heights:
    https://esa-worldcover-s2.s3.amazonaws.com/rgbnir/2021/N47/ESA_WorldCover_10m_2021_v200_N47E011_S2RGBNIR.tif
A square that is all sea does not exist ("not found"); none south of 57 S or north of 83 N.
Each file is about 560 MB (12000 x 12000 pixels, bands red, green, blue, infrared, 16 bit), far too big to
download for a 1 km tile. It is made to be read in part: only the pixels of the tile are fetched, turned into an
ordinary 8 bit picture and kept as a small GeoTIFF in cache/worldcover/raw/.

Licence, as written in the files themselves, in the AWS open-data registry and on the project's page (checked on
16 November 2026): CC BY 4.0, "free of charge, without restriction of use". Credit to show wherever it is used:
(c) ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover
consortium.
"""
from __future__ import annotations

import math
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import sources
from .geo import unproject

# an https address, or (tests) a folder holding the same files in the same layout
BASE = os.environ.get("FPV3D_WORLDCOVER_BASE", "https://esa-worldcover-s2.s3.amazonaws.com")
YEAR = 2021
NATIVE_M = 10.0
CREDIT = ("ESA WorldCover Sentinel-2 composite 2021: © ESA WorldCover project 2021 / Contains modified Copernicus "
          "Sentinel data (2021) processed by ESA WorldCover consortium, CC BY 4.0")
# The files hold reflectance x 10000. An ordinary picture from it: this much reflectance becomes white, and the
# curve lifts the dark half (forest, shadow), as the eye expects. Chosen by looking at valleys, forest, rock and snow.
WHITE, GAMMA = 3000.0, 1.8
_GDAL = dict(GDAL_HTTP_TIMEOUT="30", GDAL_HTTP_CONNECTTIMEOUT="10", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
             CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_HTTP_MAX_RETRY="2", GDAL_HTTP_RETRY_DELAY="3")


def square_code(lat: int, lon: int) -> str:
    """'N47E011' for the 1 degree square whose south-west corner is (lat, lon)."""
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"


def square_path(lat: int, lon: int) -> str:
    """Where the square's file is, below BASE."""
    code = square_code(lat, lon)
    return f"rgbnir/{YEAR}/{code[:3]}/ESA_WorldCover_10m_{YEAR}_v200_{code}_S2RGBNIR.tif"


def to_picture(red, green, blue) -> np.ndarray:
    """Reflectance bands (x 10000, 0 = no data) -> RGB uint8 (rows, cols, 3). A pixel with data is never pure
    black, because black means "nothing here" to the tile cache."""
    dn = np.stack([red, green, blue], 2).astype(np.float32)
    rgb = np.clip(np.clip(dn / WHITE, 0, 1) ** (1 / GAMMA) * 255 + 0.5, 1, 255).astype(np.uint8)
    rgb[(dn == 0).all(axis=2)] = 0
    return rgb


class WorldCover(sources.TerrainSource):
    name = "worldcover"
    host = "esa-worldcover-s2.s3.amazonaws.com"
    kinds = ("ortho",)
    credit = CREDIT
    native_m = NATIVE_M
    patchy = True     # no picture where snow lies all year (glaciers): those holes are filled from the next source

    def __init__(self, crs: str):
        self.crs = crs
        self.epsg = crs.split(":")[-1]
        self.cache_prefix = f"worldcover/{self.epsg}"               # resampled tiles: one folder per grid

    def raw_dir(self, root: Path, kind: str) -> Path:
        return Path(root) / "worldcover" / "raw"                    # the pieces cut from the big files

    def resampling(self, kind: str, res: float):
        from rasterio.warp import Resampling
        return Resampling.bilinear if res < NATIVE_M else Resampling.average

    def bounds(self, key) -> Tuple[float, float, float, float]:
        """(west, south, east, north) in degrees of a 1 km tile and 100 m around it (for the resampling)."""
        e = np.linspace(key[0] * 1000 - 100, (key[0] + 1) * 1000 + 100, 5)
        n = np.linspace(key[1] * 1000 - 100, (key[1] + 1) * 1000 + 100, 5)
        E, N = np.meshgrid(e, n)
        lat, lon = unproject(E.ravel(), N.ravel(), self.crs)
        return float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max())

    def squares(self, key) -> List[Tuple[int, int]]:
        w, s, e, n = self.bounds(key)
        return [(la, lo) for la in range(math.floor(s), math.floor(n) + 1) for lo in range(math.floor(w), math.floor(e) + 1)]

    def _piece(self, root: Path, key, sq) -> Path:
        """The part of square `sq` that tile `key` of this grid needs, as its own small file."""
        return self.raw_dir(root, "ortho") / f"{self.epsg}_{key[0]}-{key[1]}_{square_code(*sq)}.tif"

    def _missing(self, root: Path, sq) -> Path:
        return self.raw_dir(root, "ortho") / f"{square_code(*sq)}.missing"

    def raw_names(self, key) -> set:
        """Names (without .tif) of the pieces a 1 km tile is made from: what the cache clean-up must keep."""
        return {f"{self.epsg}_{key[0]}-{key[1]}_{square_code(*sq)}" for sq in self.squares(key)} | \
            {square_code(*sq) for sq in self.squares(key)}           # and the "no such square" notes

    def local_raw(self, root: Path, kind: str, key, res: float) -> List[Path]:
        have = []
        for sq in self.squares(key):
            f = self._piece(root, key, sq)
            if f.exists() and f.stat().st_size > 0:
                have.append(f)
            elif not self._missing(root, sq).exists():
                return []                                           # one square was never asked for: go online
        return have

    def lookup(self, kind: str, keys, res: float) -> Dict[tuple, List[sources.Found]]:
        """No catalogue to ask: the file names follow from the position."""
        out = {}
        for k in keys:
            out[tuple(k)] = [sources.Found(f"{BASE}/{square_path(*sq)}",
                                           dict(source=f"WorldCover {YEAR} {square_code(*sq)}", key=list(k), square=list(sq)))
                             for sq in self.squares(k)]
        return out

    def _exists(self, href: str) -> bool:
        """Is there a file for this square? Asked once per run and square (an all-sea square has none)."""
        if href not in _EXISTS:
            if not href.startswith("http"):
                _EXISTS[href] = Path(href).exists()
            else:
                from .swisstopo import _UA, _retry

                def head():
                    try:
                        with urllib.request.urlopen(urllib.request.Request(href, headers=_UA, method="HEAD"), timeout=30):
                            return True
                    except urllib.error.HTTPError as ex:
                        if ex.code in (403, 404):
                            return False
                        raise
                _EXISTS[href] = bool(_retry(head, "WorldCover"))
        return _EXISTS[href]

    def download(self, root: Path, kind: str, found: sources.Found, on_progress=None) -> Optional[Path]:
        """Read the tile's part of the big file (only those pixels travel) and keep it as a small picture."""
        import rasterio
        from rasterio.windows import Window, from_bounds
        key, sq = tuple(found.info["key"]), tuple(found.info["square"])
        dest = self._piece(root, key, sq)
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        if self._missing(root, sq).exists():
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not self._exists(found.href):
            self._missing(root, sq).touch()
            return None
        where = f"/vsicurl/{found.href}" if found.href.startswith("http") else found.href
        w, s, e, n = self.bounds(key)
        with rasterio.Env(**_GDAL), rasterio.open(where) as ds:
            win = from_bounds(w, s, e, n, ds.transform).round_offsets().round_lengths()
            win = win.intersection(Window(0, 0, ds.width, ds.height)) if _overlaps(win, ds) else None
            if win is None or win.width < 1 or win.height < 1:
                return None                                          # the tile only touches this square's edge
            bands = ds.read((1, 2, 3), window=win)                   # red, green, blue
            transform = ds.window_transform(win)
        rgb = to_picture(*bands)
        tmp = dest.with_suffix(".part")
        with rasterio.open(tmp, "w", driver="GTiff", width=rgb.shape[1], height=rgb.shape[0], count=3, dtype="uint8",
                           crs="EPSG:4326", compress="deflate", transform=transform) as d:
            d.write(np.transpose(rgb, (2, 0, 1)))
        tmp.replace(dest)
        if on_progress:
            on_progress(dest.stat().st_size, dest.stat().st_size)
        return dest


_EXISTS: Dict[str, bool] = {}


def _overlaps(win, ds) -> bool:
    return win.col_off < ds.width and win.row_off < ds.height and win.col_off + win.width > 0 and win.row_off + win.height > 0
