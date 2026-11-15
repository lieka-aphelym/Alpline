"""Elevation and aerial photo on a Grid, from whichever terrain sources cover it (sources.py).

The first source of the grid's chain is asked for everything; where it has nothing (swisstopo across the Swiss
border), the next one fills in. What is still missing after that is filled from its neighbours.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import numpy as np

from . import sources
from .geo import Grid
from .tilecache import TILE, TileCache, tile_keys


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def _keys_with_gaps(dem: np.ndarray, grid: Grid, keys) -> list:
    """The 1 km tiles of `keys` in which `dem` has cells without a height."""
    nan, out = np.isnan(dem), []
    if not nan.any():
        return out
    for k in keys:
        c0, c1 = int(round((k[0] * TILE - grid.min_e) / grid.res)), int(round(((k[0] + 1) * TILE - grid.min_e) / grid.res))
        r0, r1 = int(round((grid.max_n - (k[1] + 1) * TILE) / grid.res)), int(round((grid.max_n - k[1] * TILE) / grid.res))
        if nan[max(r0, 0):max(r1, 0), max(c0, 0):max(c1, 0)].any():
            out.append(k)
    return out


def elevation(grid: Grid, surface: str, cache_root: Path, local_files=None, refresh=False, keys=None,
              fill=True, used: Optional[List] = None) -> np.ndarray:
    """Elevation (m above sea level) on grid, row 0 = north. Memoised per 1 km tile.
    `keys`: only these 1 km tiles (corridors); fill=False leaves the rest NaN.
    `used`: a list that receives the sources the heights came from."""
    from .swisstopo import fill_holes, mosaic
    if local_files:
        from rasterio.warp import Resampling
        rs = Resampling.max if surface == "dsm" else Resampling.average
        dem = mosaic([Path(p) for p in local_files], grid, bands=1, dtype=np.float32, resampling=rs)[0]
        return fill_holes(dem) if fill else dem
    chain = sources.chain(grid.crs, surface)
    if not chain:
        raise RuntimeError(f"no elevation source for {grid.crs}")
    todo = tile_keys(grid) if keys is None else [tuple(k) for k in keys]
    dem = None
    for src in chain:
        tc = TileCache(cache_root, src)
        if dem is None:
            dem = tc.mosaic(surface, grid, refresh, todo)
            got = np.isfinite(dem).any()
        else:
            todo = _keys_with_gaps(dem, grid, todo)
            if not todo:
                break
            log(f"  {len(todo)} tile(s) not (fully) covered: filling from {src.name}")
            try:
                part = tc.mosaic(surface, grid, refresh, todo)
            except (SystemExit, OSError) as ex:                 # offline: the neighbours fill the gap, as before
                log(f"  {src.name} unavailable ({str(ex)[:120]})")
                continue
            m = np.isnan(dem) & np.isfinite(part)
            got = bool(m.any())
            dem[m] = part[m]
        if got and used is not None and src not in used:
            used.append(src)
    return fill_holes(dem) if fill else dem


def orthophoto(grid: Grid, cache_root: Path, refresh=False, keys=None, used: Optional[List] = None) -> np.ndarray:
    """RGB uint8 image (rows, cols, 3) on grid. Memoised per 1 km tile. The 1 km tiles the first source has no
    picture for (swisstopo across the border) come from the next one. `used` receives the sources."""
    chain = sources.chain(grid.crs, "ortho")
    if not chain:
        raise RuntimeError(f"no aerial photo source for {grid.crs}")
    todo = tile_keys(grid) if keys is None else [tuple(k) for k in keys]
    img = None
    for src in chain:
        if not todo:
            break
        tc = TileCache(cache_root, src)
        try:
            part = tc.mosaic("ortho", grid, refresh, todo)
        except (SystemExit, OSError) as ex:
            if img is None:                      # the main source can't be reached: say so, don't swap in a coarser one
                raise
            log(f"  {src.name} photo unavailable ({str(ex)[:120]}): {len(todo)} tile(s) stay without a photo")
            break
        if img is None:
            img = part
        else:
            log(f"  {len(todo)} tile(s) without a photo: taken from {src.name}")
            m = part.any(axis=2)
            img[m] = part[m]
        have = [k for k in todo if tc.tile_path("ortho", grid.res, k).exists()]
        if have and used is not None and src not in used:
            used.append(src)
        todo = [k for k in todo if k not in set(have)]
    if img is None:
        raise RuntimeError("no aerial photo could be downloaded")
    return img


def photo_native_m(crs: str) -> float:
    """The finest photo worth asking for on this grid, in metres: sharper would only enlarge the picture."""
    return min((getattr(s, "native_m", 0.0) for s in sources.chain(crs, "ortho")), default=0.0)
