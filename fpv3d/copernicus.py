"""Worldwide elevation: the Copernicus DEM GLO-30 (about 30 m), read from its public copy on AWS.

One GeoTIFF per 1 x 1 degree, no account needed:
    https://copernicus-dem-30m.s3.amazonaws.com/<name>/<name>.tif
    <name> = Copernicus_DSM_COG_10_N45_00_E006_00_DEM       (south-west corner of the square)
Squares that are all sea do not exist (the server answers "not found"); that is remembered in a small .missing file.

It is a surface model (tree tops and roofs are partly in it) and there is no bare-ground version, so it serves both
"dtm" and "dsm". Heights are above the EGM2008 geoid (sea level, within about a metre of national heights).

Credit, to be shown wherever the data is used: produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and
(c) Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA; all rights reserved.
"""
from __future__ import annotations

import math
import os
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import sources
from .geo import unproject

BASE = os.environ.get("FPV3D_COPERNICUS_BASE", "https://copernicus-dem-30m.s3.amazonaws.com")
NATIVE_M = 30.0
CREDIT = ("Copernicus DEM GLO-30: produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and "
          "Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA; all rights reserved")


def square_name(lat: int, lon: int) -> str:
    """File name of the 1 degree square whose south-west corner is (lat, lon)."""
    return (f"Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
            f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM")


class Copernicus(sources.TerrainSource):
    name = "copernicus"
    host = "copernicus-dem-30m.s3.amazonaws.com"
    kinds = ("dtm", "dsm")
    credit = CREDIT

    def __init__(self, crs: str):
        self.crs = crs
        self.cache_prefix = f"copernicus/{crs.split(':')[-1]}"      # resampled tiles: one folder per grid

    def raw_dir(self, root: Path, kind: str) -> Path:
        return Path(root) / "copernicus" / "raw"                    # the downloads are shared by every grid

    def resampling(self, kind: str, res: float):
        from rasterio.warp import Resampling
        return Resampling.bilinear if res < NATIVE_M else Resampling.average     # finer than the data: smooth, no steps

    def squares(self, key) -> List[Tuple[int, int]]:
        """The 1 degree squares a 1 km tile (+ 100 m around, for the resampling) lies in."""
        e = np.linspace(key[0] * 1000 - 100, (key[0] + 1) * 1000 + 100, 5)
        n = np.linspace(key[1] * 1000 - 100, (key[1] + 1) * 1000 + 100, 5)
        E, N = np.meshgrid(e, n)
        lat, lon = unproject(E.ravel(), N.ravel(), self.crs)
        return [(la, lo) for la in range(math.floor(lat.min()), math.floor(lat.max()) + 1)
                for lo in range(math.floor(lon.min()), math.floor(lon.max()) + 1)]

    def _file(self, root: Path, sq) -> Path:
        return self.raw_dir(root, "dtm") / f"{square_name(*sq)}.tif"

    def local_raw(self, root: Path, kind: str, key, res: float) -> List[Path]:
        have = []
        for sq in self.squares(key):
            f = self._file(root, sq)
            if f.exists() and f.stat().st_size > 0:
                have.append(f)
            elif not f.with_suffix(".missing").exists():
                return []                                           # one square was never asked for: go online
        return have

    def lookup(self, kind: str, keys, res: float) -> Dict[tuple, List[sources.Found]]:
        """No catalogue to ask: the file names follow from the position."""
        out = {}
        for k in keys:
            names = [square_name(*sq) for sq in self.squares(k)]
            out[tuple(k)] = [sources.Found(f"{BASE}/{n}/{n}.tif", dict(source=f"{n}.tif")) for n in names]
        return out

    def download(self, root: Path, kind: str, found: sources.Found, on_progress=None) -> Optional[Path]:
        from .swisstopo import download
        folder = self.raw_dir(root, kind)
        missing = folder / (found.href.rsplit("/", 1)[-1][:-4] + ".missing")
        if missing.exists():
            return None
        try:
            return download(found.href, folder, on_progress)
        except urllib.error.HTTPError as ex:
            if ex.code != 404:
                raise
            folder.mkdir(parents=True, exist_ok=True)
            missing.touch()                                         # all sea: there is no file for this square
            return None
