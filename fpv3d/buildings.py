"""3D buildings: footprints from OpenStreetMap, heights from swisstopo elevation models.

    footprints  OpenStreetMap (Overpass API). Swiss building coverage is very complete.
    ground      lowest swissALTI3D (bare ground) height inside the footprint
    roof        median of swissSURFACE3D (incl. buildings) inside the footprint, when the
                scene uses the surface model; otherwise OSM height / levels, else a default

The result (scenes/<name>/buildings.json) is drawn by the viewer as clean extruded blocks on the
bare-ground terrain, instead of the blurry "blobs" a surface model gives at a few metres per cell.
The signal analysis keeps using the surface model, which also contains trees.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .geo import Grid, wgs84_to_lv95
from .safefile import write_atomic

# public Overpass servers, tried in turn (they limit how many queries one computer may run in a row)
OVERPASS_URLS = [os.environ["FPV3D_OVERPASS_URL"]] if os.environ.get("FPV3D_OVERPASS_URL") else [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
RETRY_HTTP = {429, 502, 503, 504}
MAX_AGE_S = 30 * 86400
UA = {"User-Agent": "fpv3d/1.0 (local FPV flight visualiser)"}
LOW = {"garage", "garages", "shed", "carport", "hut", "kiosk", "roof", "greenhouse", "cabin", "toilets", "bunker"}


def log(msg):
    import sys
    print(msg, file=sys.stderr, flush=True)


def fetch_osm(grid: Grid, cache: Path, refresh=False) -> dict:
    """Overpass JSON with all building ways / multipolygons in the grid (cached 30 days)."""
    lo1, la1, lo2, la2 = grid.wgs84_bbox(pad_m=20)
    key = hashlib.sha1(f"{la1:.5f},{lo1:.5f},{la2:.5f},{lo2:.5f}".encode()).hexdigest()[:16]
    f = cache / "buildings" / f"osm_{key}.json"
    if f.exists() and not refresh and time.time() - f.stat().st_mtime < MAX_AGE_S:
        return json.loads(f.read_text(encoding="utf-8"))
    q = (f'[out:json][timeout:120];(way["building"]({la1},{lo1},{la2},{lo2});'
         f'relation["building"]["type"="multipolygon"]({la1},{lo1},{la2},{lo2}););out geom;')
    try:
        data = _overpass(q)
    except Exception:
        if f.exists():                      # offline: an older copy is better than nothing
            return json.loads(f.read_text(encoding="utf-8"))
        raise
    f.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(f, json.dumps(data))
    return data


def _overpass(q: str) -> dict:
    """Run an Overpass query: retries busy servers (HTTP 429 / 50x / time-outs) and falls back to
    other public servers. Raises the last error with a readable message."""
    import urllib.error
    errors = []
    for url in OVERPASS_URLS:
        host = urllib.parse.urlparse(url).netloc
        for attempt in range(3):
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA)
            try:
                with urllib.request.urlopen(req, timeout=200) as r:
                    data = json.loads(r.read().decode("utf-8"))
                remark = str(data.get("remark") or "")
                if "error" in remark.lower():          # e.g. "runtime error: Query timed out" (HTTP 200!)
                    raise RuntimeError(remark.strip()[:160])
                return data
            except urllib.error.HTTPError as ex:
                errors.append(f"{host}: HTTP {ex.code} {ex.reason}")
                if ex.code not in RETRY_HTTP:
                    break
                wait = int(ex.headers.get("Retry-After") or 0) or (10, 30, 60)[attempt]
            except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as ex:
                errors.append(f"{host}: {getattr(ex, 'reason', ex)}")
                if isinstance(ex, urllib.error.URLError) and "Tunnel" in str(ex):
                    break                                # proxy refuses this host: next server
                wait = (5, 15, 30)[attempt]
            if attempt < 2:
                log(f"[buildings] {errors[-1]} - retrying in {wait}s")
                time.sleep(min(wait, 90))
    raise RuntimeError("; ".join(errors[-3:]))


def _rings(el):
    """Outer rings [(lat, lon), ...] of an Overpass way / multipolygon relation."""
    if el.get("type") == "way" and el.get("geometry"):
        return [[(p["lat"], p["lon"]) for p in el["geometry"]]]
    out = []
    for m in el.get("members", []):
        if m.get("role") == "outer" and m.get("geometry") and len(m["geometry"]) >= 4:
            g = m["geometry"]
            if g[0] == g[-1]:
                out.append([(p["lat"], p["lon"]) for p in g])
    return out


def _tag_height(tags, ground_h=None):
    for k in ("height", "building:height"):
        try:
            return float(str(tags[k]).replace("m", "").strip())
        except (KeyError, ValueError):
            pass
    try:
        lv = float(tags["building:levels"])
        roof = float(tags.get("roof:levels", 0) or 0)
        return 3.0 * (lv + roof) + 1.0
    except (KeyError, ValueError):
        pass
    return 3.5 if tags.get("building") in LOW else 8.0


def _cells_inside(poly_xy, grid: Grid, res: float):
    """Row/col indices of grid cells whose centre is inside the polygon (local metres)."""
    xs, ys = poly_xy[:, 0], poly_xy[:, 1]
    hN = grid.max_n - grid.min_n
    c0, c1 = int(max(xs.min() / res - 1, 0)), int(min(xs.max() / res + 2, grid.cols))
    r0, r1 = int(max((hN - ys.max()) / res - 1, 0)), int(min((hN - ys.min()) / res + 2, grid.rows))
    if c1 <= c0 or r1 <= r0:
        return None
    img = Image.new("1", (c1 - c0, r1 - r0), 0)
    pts = [((x / res) - c0 - 0.5, ((hN - y) / res) - r0 - 0.5) for x, y in poly_xy]
    ImageDraw.Draw(img).polygon(pts, fill=1, outline=1)
    m = np.array(img, bool)
    rr, cc = np.nonzero(m)
    return rr + r0, cc + c0


def _shrink(xy, d):
    """Move every vertex `d` metres towards the centroid (cheap inward offset, enough for roofs)."""
    c = xy.mean(0)
    v = xy - c
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return c + v * np.maximum(n - d, 0) / np.maximum(n, 1e-6)


def _cells(xy, grid: Grid):
    idx = _cells_inside(xy, grid, grid.res)
    if idx is None or not len(idx[0]):          # footprint smaller than a cell: nearest cell
        H = grid.max_n - grid.min_n
        c = int(np.clip(xy[:, 0].mean() / grid.res, 0, grid.cols - 1))
        r = int(np.clip((H - xy[:, 1].mean()) / grid.res, 0, grid.rows - 1))
        idx = (np.array([r]), np.array([c]))
    return idx


def build_buildings(grid: Grid, dtm: np.ndarray, dsm, cache: Path, refresh=False, dtm_grid: Grid = None, keep=None):
    """List of buildings {p: [[x, y], ...] local m, b: ground AMSL, t: roof AMSL, src: 'dsm'|'tags'}.
    `dsm` is on `grid` (or None); `dtm` is on `dtm_grid` (default: grid), same extent."""
    dgrid = dtm_grid or grid
    data = fetch_osm(grid, cache, refresh)
    W, H = grid.max_e - grid.min_e, grid.max_n - grid.min_n
    out, n_dsm = [], 0
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        if tags.get("building") in (None, "no") or tags.get("location") == "underground":
            continue
        for ring in _rings(el):
            lat = np.array([p[0] for p in ring]); lon = np.array([p[1] for p in ring])
            e, n = wgs84_to_lv95(lat, lon)
            x, y = np.asarray(e) - grid.min_e, np.asarray(n) - grid.min_n
            if x.max() < 0 or y.max() < 0 or x.min() > W or y.min() > H:
                continue
            xy = np.stack([x, y], 1)
            if len(xy) > 1 and np.allclose(xy[0], xy[-1]):
                xy = xy[:-1]
            if len(xy) < 3 or (keep is not None and not keep(xy)):
                continue
            area = 0.5 * abs(np.dot(xy[:, 0], np.roll(xy[:, 1], 1)) - np.dot(xy[:, 1], np.roll(xy[:, 0], 1)))
            if area < 4:
                continue
            ground = float(np.nanmin(dtm[_cells(xy, dgrid)]))
            idx = _cells(xy, grid)
            top, src = None, "tags"
            if dsm is not None:
                inner = _cells_inside(_shrink(xy, grid.res), grid, grid.res) if len(idx[0]) > 12 else None
                cells = inner if inner is not None and len(inner[0]) >= 4 else idx
                roof = float(np.nanmedian(dsm[cells]))       # median of the inner cells: robust to edges / trees
                # a big footprint at coarse resolution is reliable; tiny ones mix in the ground
                if roof - ground > 2.0 and (len(idx[0]) >= 3 or grid.res <= 1):
                    top, src = roof, "dsm"
                    n_dsm += 1
            if top is None:
                top = ground + _tag_height(tags)
            out.append(dict(p=np.round(xy, 2).tolist(), b=round(ground, 2), t=round(top, 2), src=src,
                            k=tags.get("building", "yes"), name=tags.get("name")))
    return out, n_dsm


def write_scene_buildings(out_dir: Path, grid: Grid, dtm: np.ndarray, dsm, cache: Path, refresh=False, dtm_grid=None,
                          keep=None):
    """scenes/<name>/buildings.json + meta for scene.json. When the download fails, the meta holds
    the reason (shown in the viewer) and `python -m fpv3d buildings` retries later."""
    t0 = time.time()
    try:
        items, n_dsm = build_buildings(grid, dtm, dsm, cache, refresh, dtm_grid, keep)
    except Exception as ex:
        log(f"[buildings] unavailable ({ex}) - scene built without them; retry with: python -m fpv3d buildings")
        return dict(count=0, error=str(ex)[:300], when=time.strftime("%Y-%m-%d %H:%M"))
    write_atomic((out_dir / "buildings.json"), json.dumps(dict(items=items), separators=(",", ":")))
    log(f"[buildings] {len(items)} from OpenStreetMap, {n_dsm} with heights measured on swissSURFACE3D "
        f"({time.time() - t0:.1f}s)")
    return dict(file="buildings.json", count=len(items), heights_from_dsm=n_dsm, source="OpenStreetMap + swisstopo")
