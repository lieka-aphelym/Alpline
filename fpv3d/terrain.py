"""Elevation and aerial photo on a Grid, from whichever terrain sources cover it (sources.py).

The first source of the grid's chain is asked for everything; where it has nothing (swisstopo across the Swiss
border), the next one fills in. What is still missing after that is filled from its neighbours.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import List, Optional

import numpy as np

from . import sources
from .geo import Grid, unproject
from .tilecache import TILE, TileCache, tile_keys


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def _where(grid: Grid):
    """(lat, lon) of the middle of a grid: decides which regional sources are asked for it."""
    lat, lon = unproject((grid.min_e + grid.max_e) / 2, (grid.min_n + grid.max_n) / 2, grid.crs)
    return float(lat), float(lon)


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
    chain = sources.chain(grid.crs, surface, _where(grid))
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


def _grow(mask: np.ndarray, steps: int) -> np.ndarray:
    """The mask, widened by `steps` pixels on every side."""
    out = mask.copy()
    for _ in range(steps):
        m = out.copy()
        out[1:] |= m[:-1]
        out[:-1] |= m[1:]
        out[:, 1:] |= m[:, :-1]
        out[:, :-1] |= m[:, 1:]
    return out


def _tile_area(grid: Grid, k):
    """The (rows, cols) slices of 1 km tile `k` on the grid, or None when it lies outside."""
    n = int(round(TILE / grid.res))
    c0 = int(round((k[0] * TILE - grid.min_e) / grid.res))
    r0 = int(round((grid.max_n - (k[1] + 1) * TILE) / grid.res))
    r, c = slice(max(r0, 0), min(r0 + n, grid.rows)), slice(max(c0, 0), min(c0 + n, grid.cols))
    return (r, c) if r.start < r.stop and c.start < c.stop else None


HOLE_DARK = 8        # a cached photo tile is a JPEG: a hole comes back as almost black, not as exactly 0
HOLE_SHARE = 0.002   # a tile is asked from the next source when more than this share of it is still empty


def orthophoto(grid: Grid, cache_root: Path, refresh=False, keys=None, used: Optional[List] = None) -> np.ndarray:
    """RGB uint8 image (rows, cols, 3) on grid. Memoised per 1 km tile. What the first source has no picture for
    comes from the next one: whole 1 km tiles (swisstopo across the border), and, for a source that says its
    pictures have holes (`patchy`: the 2021 satellite composite has none where snow lies all year), the holes
    inside a tile. `used` receives the sources.
    A source that cannot be reached: a satellite one (it says how coarse it is, `native_m`) is simply passed over,
    the next is as good; a sharp one (swisstopo) stops the photo, as before, so that a 10 cm picture is never
    silently replaced by a 10 m one."""
    chain = sources.chain(grid.crs, "ortho", _where(grid))
    if not chain:
        raise RuntimeError(f"no aerial photo source for {grid.crs}")
    todo = tile_keys(grid) if keys is None else [tuple(k) for k in keys]
    img = None
    need = np.ones(grid.shape, bool)             # the pixels that have no photo yet
    for src in chain:
        if not todo:
            break
        tc = TileCache(cache_root, src)
        try:
            part = tc.mosaic("ortho", grid, refresh, todo)
        except (SystemExit, OSError) as ex:
            if getattr(src, "native_m", 0) and src is not chain[-1]:
                log(f"  {src.name} photo unavailable ({str(ex)[:120]}): trying {chain[chain.index(src) + 1].name}")
                continue
            if img is None:                      # the main source can't be reached: say so, don't swap in a coarser one
                raise
            log(f"  {src.name} photo unavailable ({str(ex)[:120]}): {len(todo)} tile(s) stay without a photo")
            break
        patchy = getattr(src, "patchy", False)
        if patchy:
            # the rim of a hole is a blend of picture and nothing (resampling, JPEG): leave it to the next source too
            got = ~_grow(part.max(axis=2) < HOLE_DARK, int(math.ceil(src.native_m / grid.res)) + 1)
        else:
            got = part.any(axis=2)
        if img is None:
            img = part
        else:
            log(f"  {len(todo)} tile(s) without a full photo: completed from {src.name}")
            m = need & got
            img[m] = part[m]
        need &= ~got
        have = [k for k in todo if tc.tile_path("ortho", grid.res, k).exists()]
        if have and used is not None and src not in used:
            used.append(src)
        done = set(have)
        if patchy and src is not chain[-1]:
            areas = {k: _tile_area(grid, k) for k in have}
            done = {k for k, a in areas.items() if a is None or need[a].mean() <= HOLE_SHARE}
        todo = [k for k in todo if k not in done]
    if img is None:
        raise RuntimeError("no aerial photo could be downloaded")
    return img


# the worldwide sources: (cache folder, what it is, how to get the source for a grid, the kinds it serves)
def _world_sources():
    """Every source other than swisstopo: the two worldwide ones and the regional ones that were registered."""
    regional = tuple((r.name, r.label, (lambda crs, r=r: sources.regional(r, crs)), r.kinds) for r in sources.regional_sources())
    return (("copernicus", "worldwide 30 m model", sources.worldwide, ("dtm", "dsm")),
            ("worldcover", "satellite photo 2021", sources.worldcover, ("ortho",)),
            ("sentinel2", "satellite photo 2016", sources.worldwide_photo, ("ortho",))) + regional


def _world_grids(cache_root: Path, name: str) -> List[str]:
    """The grids ("EPSG:32632") a worldwide source has resampled tiles for."""
    folder = Path(cache_root) / name
    return [f"EPSG:{d.name}" for d in sorted(folder.iterdir()) if d.is_dir() and d.name.isdigit()] if folder.exists() else []


def _key(k: str):
    """"681-5239" -> (681, 5239). Kilometre numbers are never negative on LV95 or a UTM grid."""
    e, n = k.split("-")
    return int(e), int(n)


def prune_world(cache_root: Path, keep: dict, dry_run=True):
    """Clean the worldwide caches: delete the resampled tiles no location needs, and the downloads (1 degree
    elevation files, photo tiles) none of the kept tiles is made from.
    `keep`: {grid: {"E-N", ...}} = the 1 km tiles the location files use, per grid. A grid no location is on loses
    all its tiles. Returns (files, bytes) removed, or that would be removed with dry_run."""
    files = size = 0
    for name, _label, make, kinds in _world_sources():
        for crs in _world_grids(cache_root, name):
            f, s = TileCache(cache_root, make(crs)).prune(keep.get(crs, set()), dry_run)
            files, size = files + f, size + s
        raw = make("EPSG:2056").raw_dir(cache_root, kinds[0])
        if not raw.exists():
            continue
        needed = set()
        for crs, keys in keep.items():
            src = make(crs)
            for k in keys:
                needed |= src.raw_names(_key(k))
        for f in raw.iterdir():
            if f.suffix in (".tif", ".missing", ".part") and f.stem not in needed:
                files += 1; size += f.stat().st_size
                if not dry_run:
                    f.unlink(missing_ok=True)
    return files, size


def clear_world(cache_root: Path, raw=False, lod=False, kind=None):
    """`cache clear` for the worldwide caches: the downloads (raw) and / or the resampled tiles (lod), of one kind
    or of all."""
    import shutil
    for name, _label, make, kinds in _world_sources():
        if kind and kind not in kinds:
            continue
        if lod:
            for crs in _world_grids(cache_root, name):
                base = TileCache(cache_root, make(crs)).base / "lod"
                shutil.rmtree(base / kind if kind else base, ignore_errors=True)
        # one download serves "dtm" and "dsm" alike: it only goes when all elevation is cleared
        if raw and (kind is None or len(kinds) == 1):
            shutil.rmtree(make("EPSG:2056").raw_dir(cache_root, kinds[0]), ignore_errors=True)


def world_info(cache_root: Path) -> List[str]:
    """Lines for `cache info`: what is kept of the worldwide sources."""
    lines = []

    def size(p: Path):
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0
    for name, label, make, kinds in _world_sources():
        raw = make("EPSG:2056").raw_dir(cache_root, kinds[0])
        if raw.exists() and any(raw.glob("*.tif")):
            lines.append(f"raw  {name + ' (' + label + ')':40s} {len(list(raw.glob('*.tif'))):5d} files {size(raw) / 1e6:9.1f} MB")
        for crs in _world_grids(cache_root, name):
            lod = TileCache(cache_root, make(crs)).base / "lod"
            for kd in sorted(lod.iterdir()) if lod.exists() else []:
                for rd in sorted((d for d in kd.iterdir() if d.is_dir()), key=lambda x: float(x.name[:-1])):
                    tiles = len([f for f in rd.iterdir() if f.suffix in (".npy", ".jpg")])
                    if tiles:
                        lines.append(f"lod  {kd.name:5s} {rd.name:>6s}  {tiles:5d} tiles (= {tiles} km²) {size(rd) / 1e6:9.1f} MB"
                                     f"   {name}, {crs}")
    return lines


def world_inventory(cache_root: Path) -> List[dict]:
    """What is cached of the worldwide sources, per source and grid (for the map page):
    [{"source": "copernicus", "label": "worldwide 30 m model", "crs": "EPSG:32632", "lod": {kind: {res: [key, ...]}}}]."""
    out = []
    for name, label, make, _kinds in _world_sources():
        for crs in _world_grids(cache_root, name):
            lod = TileCache(cache_root, make(crs)).inventory()["lod"]
            if lod:
                out.append(dict(source=name, label=label, crs=crs, lod=lod))
    return out


def cached_height(tc: TileCache, e: float, n: float):
    """Ground height at (e, n) of the cache's grid from its finest resampled tile: (height, "cache (dtm 2 m)") or None."""
    key = (int(e // TILE), int(n // TILE))
    for kind in ("dtm", "dsm"):
        d = tc.base / "lod" / kind
        if not d.exists():
            continue
        for rd in sorted((p for p in d.iterdir() if p.name[:-1].replace(".", "").isdigit()), key=lambda p: float(p.name[:-1])):
            res = float(rd.name[:-1])
            t = tc.load(kind, res, key)
            if t is None:
                continue
            c = int((e - key[0] * TILE) / res)
            r = int(((key[1] + 1) * TILE - n) / res)
            v = float(t[min(r, t.shape[0] - 1), min(c, t.shape[1] - 1)])
            if np.isfinite(v):
                return v, f"cache ({kind} {res:g} m)"
    return None


def world_height(cache_root: Path, lat: float, lon: float, crs: str, online=True):
    """Ground height of a place from the worldwide model: from the cache, else from its 1 degree file when it is
    already downloaded, else (online) by reading just that spot of the file on the server. (height, source) or None."""
    import math
    import rasterio
    from .copernicus import BASE, square_name
    from .geo import project
    e, n = (float(v) for v in project(lat, lon, crs))
    src = sources.worldwide(crs)
    hit = cached_height(TileCache(cache_root, src), e, n)
    if hit:
        return hit[0], f"worldwide 30 m model, {hit[1]}"
    name = square_name(math.floor(lat), math.floor(lon))
    local = src.raw_dir(cache_root, "dtm") / f"{name}.tif"
    if local.exists():
        where, env = str(local), {}
    elif online and not local.with_suffix(".missing").exists():
        # the files are made for this: only the few kilobytes around the spot are fetched
        where, env = f"/vsicurl/{BASE}/{name}/{name}.tif", dict(
            GDAL_HTTP_TIMEOUT="10", GDAL_HTTP_CONNECTTIMEOUT="5", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")
    else:
        return None
    with rasterio.Env(**env), rasterio.open(where) as ds:
        v = float(next(ds.sample([(lon, lat)]))[0])
    return (v, "worldwide 30 m model") if math.isfinite(v) and v > -1000 else None


def photo_native_m(crs: str, where=None) -> float:
    """The finest photo worth asking for on this grid (at the place `where`, lat / lon, when a regional source may
    cover it), in metres: sharper would only enlarge the picture."""
    return min((getattr(s, "native_m", 0.0) for s in sources.chain(crs, "ortho", where)), default=0.0)
