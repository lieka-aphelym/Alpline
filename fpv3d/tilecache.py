"""Memoised swisstopo terrain: every 1 km tile is downloaded once and resampled once
per level of detail, then reused by every scene / location that touches it.

cache/
  ch.swisstopo.swissalti3d/...tif        raw downloads (kept so new resolutions need no download)
  lod/<kind>/<res>m/<E>-<N>.npy          elevation tile resampled to <res> m (float32)
  lod/ortho/<res>m/<E>-<N>.jpg           aerial photo tile at <res> m (RGB, JPEG q92)
  lod/<kind>/<res>m/<E>-<N>.none         marker: no data there (outside Switzerland)
  lod/<kind>/<res>m/_index.json          which swisstopo item / year each tile came from

Once a tile is in lod/ the build needs no network at all, so prefetched areas work offline.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from . import progress, swisstopo
from .geo import Grid

TILE = 1000  # swisstopo tiles are 1 x 1 km on the LV95 kilometre grid

KIND_RESAMPLING = {
    "dtm": Resampling.average,   # bare ground: smooth average
    "dsm": Resampling.max,       # surface: keep tree tops / roofs, they block the signal
    "ortho": Resampling.average,
}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def _res_dir(res: float) -> str:
    return f"{res:g}m"


def tile_keys(grid: Grid) -> List[Tuple[int, int]]:
    e0, e1 = int(np.floor(grid.min_e / TILE)), int(np.ceil(grid.max_e / TILE))
    n0, n1 = int(np.floor(grid.min_n / TILE)), int(np.ceil(grid.max_n / TILE))
    return [(e, n) for e in range(e0, e1) for n in range(n0, n1)]


class TileCache:
    def __init__(self, root: Path):
        self.root = Path(root)

    # ------------------------------------------------------------ paths
    def lod_dir(self, kind: str, res: float) -> Path:
        return self.root / "lod" / kind / _res_dir(res)

    def tile_path(self, kind: str, res: float, key) -> Path:
        ext = ".jpg" if kind == "ortho" else ".npy"
        return self.lod_dir(kind, res) / f"{key[0]}-{key[1]}{ext}"

    def _none_path(self, kind, res, key) -> Path:
        return self.lod_dir(kind, res) / f"{key[0]}-{key[1]}.none"

    def has(self, kind, res, key) -> bool:
        return self.tile_path(kind, res, key).exists() or self._none_path(kind, res, key).exists()

    def load(self, kind, res, key) -> Optional[np.ndarray]:
        p = self.tile_path(kind, res, key)
        if not p.exists():
            return None
        return np.asarray(Image.open(p).convert("RGB")) if kind == "ortho" else np.load(p)

    # ------------------------------------------------------------ fill
    def ensure(self, kind: str, res: float, keys, refresh=False) -> Dict[str, int]:
        """Make sure every tile in `keys` exists at `res` (downloading only what is missing)."""
        if refresh:
            for k in keys:
                for p in (self.tile_path(kind, res, k), self._none_path(kind, res, k)):
                    p.unlink(missing_ok=True)
        missing = [k for k in keys if not self.has(kind, res, k)]
        stats = dict(cached=len(keys) - len(missing), downloaded=0, empty=0, from_raw=0)
        ks = lambda k: f"{k[0]}-{k[1]}"  # noqa: E731
        miss_set = set(missing)
        progress.emit("tiles", kind=kind, res=res, keys=[ks(k) for k in keys],
                      cached=[ks(k) for k in keys if k not in miss_set])
        if not missing:
            return stats
        src_gsd = res if kind != "dsm" else 0.5      # swissSURFACE3D raster only exists at 0.5 m
        coll = swisstopo.COLLECTIONS[kind]
        d = self.lod_dir(kind, res)
        d.mkdir(parents=True, exist_ok=True)

        # 1) a new resolution of an area already downloaded: resample the raw tiles, no network
        if not refresh:
            still = []
            for k in missing:
                raw = self._local_raw(coll, k, src_gsd)
                if raw is None:
                    still.append(k)
                    continue
                self._store(kind, res, k, self._resample(raw, kind, res, k))
                stats["from_raw"] += 1
                progress.emit("tile", kind=kind, res=res, key=ks(k), state="raw")
            missing = still
            if not missing:
                return stats

        # one STAC query for the bounding box of the missing tiles
        e0 = min(k[0] for k in missing) * TILE
        n0 = min(k[1] for k in missing) * TILE
        e1 = (max(k[0] for k in missing) + 1) * TILE
        n1 = (max(k[1] for k in missing) + 1) * TILE
        bbox_grid = Grid(e0 + 5, n0 + 5, e1 - 5, n1 - 5, TILE)
        log(f"  {kind} {res:g} m: {len(missing)} tile(s) missing, querying {coll} ...")
        progress.emit("query", kind=kind, res=res, n=len(missing))
        try:
            items = swisstopo.latest_per_tile(swisstopo.stac_items(coll, bbox_grid.wgs84_bbox()))
        except OSError as ex:
            raise SystemExit(f"cannot reach data.geo.admin.ch ({ex}). {len(missing)} {kind} tile(s) at "
                             f"{res:g} m are not cached yet - connect to the internet once, or use "
                             f"`python -m fpv3d prefetch` beforehand.") from ex
        index_path = d / "_index.json"
        try:
            index = json.loads(index_path.read_text())
        except (OSError, ValueError):
            index = {}

        for k in missing:
            key = f"{k[0]}-{k[1]}"
            item = items.get(key)
            asset = swisstopo.pick_asset(item, src_gsd) if item else None
            if asset is None:
                self._none_path(kind, res, k).touch()
                stats["empty"] += 1
                progress.emit("tile", kind=kind, res=res, key=key, state="empty")
                continue
            progress.emit("tile", kind=kind, res=res, key=key, state="download", pct=0)
            raw = swisstopo.download(asset["href"], self.root / coll, on_progress=lambda d, t, key=key: progress.emit(
                "tile", throttle=0.25, kind=kind, res=res, key=key, state="download",
                pct=round(100 * d / t) if t else None, bytes=d, total=t))
            self._store(kind, res, k, self._resample(raw, kind, res, k))
            progress.emit("tile", kind=kind, res=res, key=key, state="done")
            index[key] = dict(item=item.get("id"), datetime=(item.get("properties") or {}).get("datetime"),
                              source=Path(asset["href"]).name)
            stats["downloaded"] += 1
        index_path.write_text(json.dumps(index, indent=1))
        return stats

    def _store(self, kind, res, k, arr):
        if kind == "ortho":
            Image.fromarray(arr).save(self.tile_path(kind, res, k), quality=92)
        else:
            np.save(self.tile_path(kind, res, k), arr)

    _RAW_RE = re.compile(r"_(\d{4})_(\d{4}-\d{4})_(\d+(?:\.\d+)?)(?:_|\.tif$)")

    def _local_raw(self, coll: str, k, want_gsd: float) -> Optional[Path]:
        """Newest already-downloaded raw tile for key k that is at least as fine as want_gsd."""
        folder = self.root / coll
        if not folder.exists():
            return None
        key, best = f"{k[0]}-{k[1]}", None
        for f in folder.glob(f"*{key}*.tif"):
            m = self._RAW_RE.search(f.name)
            if not m or m.group(2) != key:
                continue
            year, gsd = int(m.group(1)), float(m.group(3))
            if gsd > want_gsd + 1e-9:
                continue
            rank = (year, gsd)                     # newest year, then coarsest usable resolution
            if best is None or rank > best[0]:
                best = (rank, f)
        return best[1] if best else None

    @staticmethod
    def _resample(raw: Path, kind: str, res: float, k) -> np.ndarray:
        n = int(round(TILE / res))
        tr = from_origin(k[0] * TILE, (k[1] + 1) * TILE, res, res)
        bands = 3 if kind == "ortho" else 1
        dtype = np.uint8 if kind == "ortho" else np.float32
        nodata = 0 if kind == "ortho" else np.nan
        out = np.full((bands, n, n), nodata, dtype=dtype)
        with rasterio.open(raw) as src:
            for b in range(bands):
                reproject(source=rasterio.band(src, min(b + 1, src.count)), destination=out[b],
                          src_crs=src.crs or "EPSG:2056", dst_crs="EPSG:2056",
                          dst_transform=tr, dst_nodata=nodata, resampling=KIND_RESAMPLING[kind])
        if kind == "ortho":
            return np.transpose(out, (1, 2, 0))
        a = out[0]
        a[a < -1000] = np.nan
        return a

    # ------------------------------------------------------------ assemble
    def mosaic(self, kind: str, grid: Grid, refresh=False, keys=None) -> np.ndarray:
        """Grid-sized array built from cached tiles (rows, cols) or (rows, cols, 3).
        `keys` limits it to some tiles (corridors); the rest stays NaN / black."""
        if (TILE / grid.res) % 1:
            raise ValueError(f"resolution {grid.res} must divide 1000 m")
        keys = tile_keys(grid) if keys is None else [tuple(k) for k in keys]
        st = self.ensure(kind, grid.res, keys, refresh)
        log(f"  {kind} {grid.res:g} m: {len(keys)} tile(s) - {st['cached']} from cache, "
            f"{st['downloaded']} downloaded" + (f", {st['from_raw']} resampled from earlier downloads" if st["from_raw"] else "")
            + (f", {st['empty']} without data" if st["empty"] else ""))
        ortho = kind == "ortho"
        out = np.zeros((grid.rows, grid.cols, 3), np.uint8) if ortho else np.full(grid.shape, np.nan, np.float32)
        n = int(round(TILE / grid.res))
        for k in keys:
            t = self.load(kind, grid.res, k)
            if t is None:
                continue
            c0 = int(round((k[0] * TILE - grid.min_e) / grid.res))
            r0 = int(round((grid.max_n - (k[1] + 1) * TILE) / grid.res))
            gr0, gr1 = max(r0, 0), min(r0 + n, grid.rows)
            gc0, gc1 = max(c0, 0), min(c0 + n, grid.cols)
            if gr0 >= gr1 or gc0 >= gc1:
                continue
            out[gr0:gr1, gc0:gc1] = t[gr0 - r0:gr1 - r0, gc0 - c0:gc1 - c0]
        return out

    # ------------------------------------------------------------ inventory (for the map page)
    def inventory(self) -> dict:
        """{"lod": {kind: {res: [key, ...]}}, "raw": {kind: [key, ...]}} with key = "E-N" (km)."""
        inv = {"lod": {}, "raw": {}}
        lod = self.root / "lod"
        if lod.exists():
            for kd in lod.iterdir():
                if not kd.is_dir():
                    continue
                for rd in kd.iterdir():
                    if rd.is_dir():
                        keys = sorted(f.stem for f in rd.iterdir() if f.suffix in (".npy", ".jpg"))
                        if keys:
                            inv["lod"].setdefault(kd.name, {})[rd.name[:-1]] = keys
        for kind, coll in swisstopo.COLLECTIONS.items():
            folder = self.root / coll
            if folder.exists():
                keys = set()
                for f in folder.glob("*.tif"):
                    m = self._RAW_RE.search(f.name)
                    if m:
                        keys.add(m.group(2))
                if keys:
                    inv["raw"][kind] = sorted(keys)
        return inv

    # ------------------------------------------------------------ housekeeping
    def info(self) -> List[str]:
        lines = []

        def size(p: Path):
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0

        for coll in sorted(set(swisstopo.COLLECTIONS.values())):
            p = self.root / coll
            if p.exists():
                lines.append(f"raw  {coll:40s} {len(list(p.glob('*.tif'))):5d} files {size(p) / 1e6:9.1f} MB")
        lod = self.root / "lod"
        if lod.exists():
            for kd in sorted(lod.iterdir()):
                for rd in sorted(kd.iterdir(), key=lambda x: float(x.name[:-1])):
                    tiles = len([f for f in rd.iterdir() if f.suffix in (".npy", ".jpg")])
                    lines.append(f"lod  {kd.name:5s} {rd.name:>6s}  {tiles:5d} tiles (= {tiles} km²) {size(rd) / 1e6:9.1f} MB")
        return lines or ["cache is empty"]

    def prune(self, keep: set, dry_run=True):
        """Delete downloaded and resampled tiles whose 1 km key ("E-N") is not in `keep`.
        Returns (files, bytes) removed, or that would be removed with dry_run."""
        files = size = 0
        for coll in set(swisstopo.COLLECTIONS.values()):
            for f in (self.root / coll).glob("*.tif") if (self.root / coll).exists() else []:
                m = self._RAW_RE.search(f.name)
                if m and m.group(2) not in keep:
                    files += 1; size += f.stat().st_size
                    if not dry_run:
                        f.unlink(missing_ok=True)
        lod = self.root / "lod"
        if lod.exists():
            for f in lod.rglob("*"):
                if f.is_file() and f.suffix in (".npy", ".jpg", ".none") and f.stem not in keep:
                    files += 1; size += f.stat().st_size
                    if not dry_run:
                        f.unlink(missing_ok=True)
        return files, size

    def clear(self, raw=False, lod=False, kind=None):
        if lod:
            target = self.root / "lod" / kind if kind else self.root / "lod"
            shutil.rmtree(target, ignore_errors=True)
        if raw:
            colls = [swisstopo.COLLECTIONS[kind]] if kind else set(swisstopo.COLLECTIONS.values())
            for c in colls:
                shutil.rmtree(self.root / c, ignore_errors=True)
