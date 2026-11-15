"""Swiss drone geozones (FOCA / BAZL "Geographical UAS zones", dataset ch.bazl.einschraenkungen-drohnen).

The national GeoJSON is downloaded once and cached (refreshed when older than a week), then the
zones touching a scene are written to scenes/<name>/geozones.json in the scene's local metres.

INFORMATIVE ONLY: zones change (temporary restrictions, events). Always check the official map
(map.geo.admin.ch, layer "Restrictions for drones") or an official app before flying.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

from .geo import LV95, Grid, wgs84_to_lv95

SOURCE_URL = os.environ.get(
    "FPV3D_GEOZONES_URL",
    "https://data.geo.admin.ch/ch.bazl.einschraenkungen-drohnen/einschraenkungen-drohnen/einschraenkungen-drohnen_4326.geojson")
MAX_AGE_S = 7 * 24 * 3600
FT = 0.3048


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def fetch(cache_root: Path, refresh=False):
    """Path of the cached national GeoJSON (downloading it if missing / old), or None if unavailable."""
    d = Path(cache_root) / "geozones"
    d.mkdir(parents=True, exist_ok=True)
    f, meta = d / "einschraenkungen-drohnen_4326.geojson", d / "fetched.json"
    age = time.time() - f.stat().st_mtime if f.exists() else None
    if f.exists() and not refresh and age < MAX_AGE_S:
        return f
    try:
        req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "fpv3d/0.1 (FPV planning)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        json.loads(data)                              # validate before replacing the cache
        f.write_bytes(data)
        meta.write_text(json.dumps(dict(url=SOURCE_URL, fetched=time.strftime("%Y-%m-%d %H:%M"))))
        log(f"[zones] downloaded drone geozones ({len(data) / 1e6:.1f} MB)")
    except Exception as ex:
        if f.exists():
            log(f"[zones] could not refresh ({ex.__class__.__name__}), using cached copy from "
                f"{time.strftime('%Y-%m-%d', time.localtime(f.stat().st_mtime))}")
        else:
            log(f"[zones] drone geozones unavailable ({ex}) - scene built without them")
            return None
    return f


def _to_m(v, uom):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v * FT if str(uom).upper().startswith("F") else v


def _rings(geom):
    t, c = geom.get("type"), geom.get("coordinates") or []
    if t == "Polygon":
        return [c]
    if t == "MultiPolygon":
        return list(c)
    if t == "GeometryCollection":
        out = []
        for g in geom.get("geometries", []):
            out += _rings(g)
        return out
    return []


def clip_to_grid(geojson_path: Path, grid: Grid, pad_m=200):
    """Zones intersecting the grid, converted to local metres (x east, y north)."""
    data = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
    lon0, lat0, lon1, lat1 = grid.wgs84_bbox(pad_m)
    W, H = grid.max_e - grid.min_e, grid.max_n - grid.min_n
    out = []
    for i, feat in enumerate(data.get("features", [])):
        geom = feat.get("geometry") or {}
        polys = []
        for poly in _rings(geom):
            rings = []
            for ring in poly:
                a = np.asarray(ring, dtype=np.float64)
                if a.ndim != 2 or len(a) < 3:
                    continue
                rings.append(a[:, :2])
            if not rings:
                continue
            ext = rings[0]
            if ext[:, 0].max() < lon0 or ext[:, 0].min() > lon1 or ext[:, 1].max() < lat0 or ext[:, 1].min() > lat1:
                continue
            loc = []
            for r in rings:
                e, n = wgs84_to_lv95(r[:, 1], r[:, 0])
                x, y = np.round(e - grid.min_e, 1), np.round(n - grid.min_n, 1)
                loc.append(np.stack([x, y], 1).tolist())
            xs = np.asarray(loc[0])[:, 0]
            ys = np.asarray(loc[0])[:, 1]
            if xs.max() < -pad_m or xs.min() > W + pad_m or ys.max() < -pad_m or ys.min() > H + pad_m:
                continue
            polys.append(loc)
        if not polys:
            continue
        p = feat.get("properties") or {}
        uom = p.get("uomDimensions", "M")
        out.append(dict(
            id=p.get("identifier") or f"z{i}", name=p.get("name") or "(unnamed zone)",
            restriction=(p.get("restriction") or "").upper(), reason=p.get("reason") or "",
            conditions=p.get("restrictionConditions") or "", message=p.get("message") or "",
            lower=_to_m(p.get("lowerLimit"), uom), lower_ref=(p.get("lowerVerticalReference") or "AGL").upper(),
            upper=_to_m(p.get("upperLimit"), uom), upper_ref=(p.get("upperVerticalReference") or "AGL").upper(),
            permanent=str(p.get("permanent", "")).upper() == "YES",
            start=p.get("startDateTime") or "", end=p.get("endDateTime") or "",
            authority=p.get("authorityName") or "", url=p.get("siteURL") or "",
            email=p.get("email") or "", phone=p.get("phone") or "",
            polygons=polys,
        ))
    return out


def write_scene_zones(out_dir: Path, grid: Grid, cache_root: Path, refresh=False):
    """Write <scene>/geozones.json; returns the metadata block for scene.json (or None)."""
    if grid.crs != LV95:
        log("[zones] drone geozones are only known for Switzerland - none for this place")
        return None
    src = fetch(cache_root, refresh)
    if src is None:
        return None
    zones = clip_to_grid(src, grid)
    try:
        fetched = json.loads((Path(cache_root) / "geozones" / "fetched.json").read_text())["fetched"]
    except Exception:
        fetched = time.strftime("%Y-%m-%d %H:%M", time.localtime(src.stat().st_mtime))
    (Path(out_dir) / "geozones.json").write_text(json.dumps(dict(
        source="FOCA/BAZL geographical UAS zones (ch.bazl.einschraenkungen-drohnen)", url=SOURCE_URL,
        fetched=fetched, zones=zones), separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    counts = {}
    for z in zones:
        counts[z["restriction"]] = counts.get(z["restriction"], 0) + 1
    log(f"[zones] {len(zones)} drone geozone(s) in the map area " +
        (", ".join(f"{v} {k.lower().replace('_', ' ')}" for k, v in sorted(counts.items())) if counts else ""))
    return dict(file="geozones.json", fetched=fetched, count=len(zones), counts=counts)
