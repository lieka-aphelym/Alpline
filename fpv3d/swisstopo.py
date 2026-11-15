"""Download swisstopo open data (swissALTI3D, swissSURFACE3D, SWISSIMAGE) via the
STAC API at data.geo.admin.ch and mosaic it onto a target Grid.

Nothing here is tied to a specific place: give it any Grid inside Switzerland.
Downloaded tiles are cached on disk so re-running a build is fast.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from . import sources
from .geo import Grid

STAC_BASE = os.environ.get("FPV3D_STAC_BASE", "https://data.geo.admin.ch/api/stac/v0.9")

COLLECTIONS = {
    "dtm": "ch.swisstopo.swissalti3d",                # bare-earth elevation
    "dsm": "ch.swisstopo.swisssurface3d-raster",      # surface incl. vegetation & buildings
    "ortho": "ch.swisstopo.swissimage-dop10",         # aerial imagery
}

_TILE_RE = re.compile(r"_(\d{4}-\d{4})$")
_UA = {"User-Agent": "fpv3d/0.1 (FPV flight visualiser)"}


def _retry(fn, what: str, tries: int = 3):
    """Run fn(); on a network hiccup (time-out, dropped connection, server busy 429/5xx) wait 5 s, 15 s and retry.
    A real 'not found' (4xx) is not retried."""
    import time
    for attempt in range(tries):
        try:
            return fn()
        except urllib.error.HTTPError as ex:
            if ex.code != 429 and ex.code < 500 or attempt == tries - 1:
                raise
            err = f"HTTP {ex.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as ex:
            if attempt == tries - 1:
                raise
            err = ex.__class__.__name__
        wait = (5, 15, 30)[attempt]
        print(f"\n    {what}: {err}, retrying in {wait} s", file=sys.stderr)
        time.sleep(wait)


def _get_json(url: str) -> dict:
    def get():
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    return _retry(get, "swisstopo catalogue")


def stac_items(collection: str, bbox_wgs84) -> List[dict]:
    """All STAC items of `collection` intersecting bbox (min_lon, min_lat, max_lon, max_lat)."""
    q = urllib.parse.urlencode({"bbox": ",".join(f"{v:.6f}" for v in bbox_wgs84), "limit": 100})
    url = f"{STAC_BASE}/collections/{collection}/items?{q}"
    items = []
    while url:
        page = _get_json(url)
        items.extend(page.get("features", []))
        url = next((l["href"] for l in page.get("links", []) if l.get("rel") == "next"), None)
    return items


def latest_per_tile(items: List[dict]) -> Dict[str, dict]:
    """swisstopo publishes several acquisition years per 1 km tile; keep the newest."""
    best: Dict[str, dict] = {}
    for it in items:
        m = _TILE_RE.search(it["id"])
        key = m.group(1) if m else it["id"]
        dt = (it.get("properties") or {}).get("datetime") or ""
        if key not in best or dt > (best[key].get("properties") or {}).get("datetime", ""):
            best[key] = it
    return best


def pick_asset(item: dict, wanted_gsd: float) -> Optional[dict]:
    """Choose the GeoTIFF asset whose ground sampling distance best fits `wanted_gsd`.
    Prefers the coarsest asset that is still at least as fine as requested."""
    tifs = []
    for a in item.get("assets", {}).values():
        if not a["href"].lower().endswith(".tif"):
            continue
        gsd = a.get("eo:gsd") or a.get("gsd")
        if gsd is None:
            m = re.search(r"_(\d+(?:\.\d+)?)_2056", a["href"])
            gsd = float(m.group(1)) if m else 1.0
        tifs.append((float(gsd), a))
    if not tifs:
        return None
    finer = [t for t in tifs if t[0] <= wanted_gsd + 1e-9]
    return (max(finer, key=lambda t: t[0]) if finer else min(tifs, key=lambda t: t[0]))[1]


def download(url: str, cache_dir: Path, on_progress=None) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / url.rsplit("/", 1)[-1]
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    return _retry(lambda: _download_once(url, dest, tmp, on_progress), dest.name)


def _download_once(url: str, dest: Path, tmp: Path, on_progress=None) -> Path:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r    {dest.name}: {done * 100 // total:3d}%", end="", file=sys.stderr)
            if on_progress:
                on_progress(done, total)
    print("", file=sys.stderr)
    tmp.replace(dest)
    return dest


class Swisstopo(sources.TerrainSource):
    """swisstopo open data as a terrain source: 1 km tiles on the LV95 kilometre grid, one file per tile."""
    name = "swisstopo"
    host = "data.geo.admin.ch"
    crs = "EPSG:2056"
    kinds = ("dtm", "dsm", "ortho")
    cache_prefix = ""                            # the original cache layout: caches made before sources existed stay valid

    _RAW_RE = re.compile(r"_(\d{4})_(\d{4}-\d{4})_(\d+(?:\.\d+)?)(?:_|\.tif$)")

    @staticmethod
    def _gsd(kind: str, res: float) -> float:
        return res if kind != "dsm" else 0.5     # swissSURFACE3D raster only exists at 0.5 m

    def raw_dir(self, root: Path, kind: str) -> Path:
        return Path(root) / COLLECTIONS[kind]

    def raw_key(self, path: Path) -> Optional[str]:
        m = self._RAW_RE.search(Path(path).name)
        return m.group(2) if m else None

    def local_raw(self, root: Path, kind: str, key, res: float) -> List[Path]:
        """Newest already-downloaded raw tile for `key` that is at least as fine as needed."""
        folder, want = self.raw_dir(root, kind), self._gsd(kind, res)
        if not folder.exists():
            return []
        name, best = f"{key[0]}-{key[1]}", None
        for f in folder.glob(f"*{name}*.tif"):
            m = self._RAW_RE.search(f.name)
            if not m or m.group(2) != name:
                continue
            year, gsd = int(m.group(1)), float(m.group(3))
            if gsd > want + 1e-9:
                continue
            rank = (year, gsd)                   # newest year, then coarsest usable resolution
            if best is None or rank > best[0]:
                best = (rank, f)
        return [best[1]] if best else []

    def lookup(self, kind: str, keys, res: float) -> Dict[tuple, List[sources.Found]]:
        """One STAC query for the bounding box of `keys`."""
        t = 1000
        e0, n0 = min(k[0] for k in keys) * t, min(k[1] for k in keys) * t
        e1, n1 = (max(k[0] for k in keys) + 1) * t, (max(k[1] for k in keys) + 1) * t
        bbox = Grid(e0 + 5, n0 + 5, e1 - 5, n1 - 5, t, self.crs).wgs84_bbox()
        items = latest_per_tile(stac_items(COLLECTIONS[kind], bbox))
        out = {}
        for k in keys:
            item = items.get(f"{k[0]}-{k[1]}")
            asset = pick_asset(item, self._gsd(kind, res)) if item else None
            if asset is not None:
                out[tuple(k)] = [sources.Found(asset["href"], dict(
                    item=item.get("id"), datetime=(item.get("properties") or {}).get("datetime"),
                    source=Path(asset["href"]).name))]
        return out

    def download(self, root: Path, kind: str, found: sources.Found, on_progress=None) -> Path:
        return download(found.href, self.raw_dir(root, kind), on_progress)


SOURCE = sources.register(Swisstopo())


def fetch_tiles(kind: str, grid: Grid, gsd: float, cache_root: Path) -> List[Path]:
    """Download (or reuse cached) tiles of `kind` ('dtm' | 'dsm' | 'ortho') covering grid."""
    coll = COLLECTIONS[kind]
    print(f"  querying {coll} ...", file=sys.stderr)
    items = latest_per_tile(stac_items(coll, grid.wgs84_bbox(pad_m=10)))
    if not items:
        raise RuntimeError(f"no {coll} tiles found here - is the area inside Switzerland?")
    paths = []
    for _key, it in sorted(items.items()):
        asset = pick_asset(it, gsd)
        if asset is None:
            continue
        paths.append(download(asset["href"], cache_root / coll))
    print(f"  {len(paths)} tile(s) for {kind}", file=sys.stderr)
    return paths


def mosaic(paths: List[Path], grid: Grid, bands: int = 1, dtype=np.float32,
           resampling=Resampling.average) -> np.ndarray:
    """Reproject/resample a set of GeoTIFFs onto `grid`. Returns (bands, rows, cols)."""
    dst_transform = from_origin(grid.min_e, grid.max_n, grid.res, grid.res)
    nodata = np.nan if np.issubdtype(dtype, np.floating) else 0
    out = np.full((bands, grid.rows, grid.cols), nodata, dtype=dtype)
    for p in paths:
        with rasterio.open(p) as src:
            src_crs = src.crs or grid.crs
            for b in range(bands):
                tmp = np.full((grid.rows, grid.cols), nodata, dtype=dtype)
                reproject(
                    source=rasterio.band(src, min(b + 1, src.count)),
                    destination=tmp,
                    src_crs=src_crs, dst_crs=grid.crs,
                    dst_transform=dst_transform, dst_nodata=nodata,
                    resampling=resampling,
                )
                if np.issubdtype(dtype, np.floating):
                    m = ~np.isnan(tmp)
                    m &= tmp > -1000  # guard against weird nodata values
                else:
                    m = tmp != 0
                out[b][m] = tmp[m]
    return out


def fill_holes(dem: np.ndarray) -> np.ndarray:
    """Fill NaNs (missing tiles / outside CH) by iterative neighbour averaging."""
    dem = dem.copy()
    if not np.isnan(dem).any():
        return dem
    if np.isnan(dem).all():
        raise RuntimeError("elevation mosaic is empty")
    for _ in range(max(dem.shape)):
        nan = np.isnan(dem)
        if not nan.any():
            break
        p = np.pad(dem, 1, mode="edge")
        stack = np.stack([p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]])
        with np.errstate(all="ignore"):
            avg = np.nanmean(stack, axis=0)
        dem[nan] = avg[nan]
    dem[np.isnan(dem)] = np.nanmedian(dem)
    return dem


def elevation(grid: Grid, surface: str, cache_root: Path, local_files=None, refresh=False, keys=None,
              fill=True) -> np.ndarray:
    """Elevation (m, LN02/LHN95 heights) on grid, row 0 = north. Memoised per 1 km tile.
    `keys`: only these 1 km tiles (corridors); fill=False leaves the rest NaN."""
    if local_files:
        rs = Resampling.max if surface == "dsm" else Resampling.average
        dem = mosaic([Path(p) for p in local_files], grid, bands=1, dtype=np.float32, resampling=rs)[0]
    else:
        from .tilecache import TileCache
        dem = TileCache(cache_root, sources.for_crs(grid.crs)).mosaic(surface, grid, refresh, keys)
    return fill_holes(dem) if fill else dem


def orthophoto(grid: Grid, cache_root: Path, refresh=False, keys=None) -> np.ndarray:
    """RGB uint8 image (rows, cols, 3) on grid. Memoised per 1 km tile."""
    from .tilecache import TileCache
    return TileCache(cache_root, sources.for_crs(grid.crs)).mosaic("ortho", grid, refresh, keys)
