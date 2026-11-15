"""Build a scene folder that the 3D viewer loads:

scenes/<name>/
    scene.json        metadata (grid, pilot, links, layers, tracks)
    terrain.f32       elevation, float32 little-endian, row-major, row 0 = north
    ortho.jpg         SWISSIMAGE aerial photo (optional)
    los_<agl>.png     signal-shadow overlay for a drone flying <agl> m above ground
    tracks/<log>.json flight track with per-sample LOS / Fresnel / predicted margin
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import logs as logmod
from . import buildings as bldmod
from . import geozones, progress, radio, swisstopo
from .config import VALID_RES, LocationConfig
from .geo import Grid, lv95_to_wgs84, wgs84_to_lv95
from .los import Terrain, los_ceilings, path_clearance
from .paths import from_portable, portable
from .safefile import write_atomic


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- terrain

def elevation_for(cfg: LocationConfig, grid: Grid, kind: str, cache: Path, refresh=False):
    """Elevation on `grid`. For a corridor: full detail on the strip's tiles, a coarse bare-ground
    'context' (10 m) between the pilot and the route, the lowest height elsewhere (never crossed
    by a signal path)."""
    cor = cfg.corridor
    if cor is None or cfg.terrain.local_dem_files:
        return swisstopo.elevation(grid, kind, cache, cfg.terrain.local_dem_files if kind == cfg.terrain.surface else None, refresh)
    from .corridor import CONTEXT_RES
    dem = swisstopo.elevation(grid, kind, cache, None, refresh, keys=cor.tile_keys(), fill=False)
    nan = np.isnan(dem)
    if nan.any():
        cres = max(CONTEXT_RES, grid.res)
        cgrid = grid.with_resolution(cres)
        pil = cfg.pilot.lv95() if cfg.pilot else None
        ckeys = cor.context_keys(pil)
        log(f"[terrain] context between pilot and route: {len(ckeys)} km² of bare ground at {cres:g} m")
        ctx = swisstopo.elevation(cgrid, "dtm", cache, None, refresh, keys=ckeys, fill=False)
        low = float(np.nanmin(ctx)) if np.isfinite(ctx).any() else float(np.nanmin(dem))
        ctx[np.isnan(ctx)] = low
        t = Terrain(ctx, cgrid)
        H = grid.max_n - grid.min_n
        for r0 in range(0, grid.rows, 512):              # fill the gaps by rows (big grids)
            blk = nan[r0:r0 + 512]
            rr, cc = np.nonzero(blk)
            if not len(rr):
                continue
            dem[r0:r0 + 512][blk] = t.height((cc + 0.5) * grid.res, H - (rr + r0 + 0.5) * grid.res)
    if np.isnan(dem).any():
        dem[np.isnan(dem)] = np.nanmin(dem)
    return dem


def build_terrain(cfg: LocationConfig, out: Path, cache: Path, skip_ortho=False, refresh=False):
    grid = cfg.grid(cfg.terrain.resolution_m)
    shape = f"corridor {cfg.corridor.length_m / 1000:.1f} km x {2 * cfg.corridor.width:g} m" if cfg.corridor else "square"
    log(f"[terrain] {grid.cols}x{grid.rows} cells @ {grid.res} m  ({cfg.terrain.surface}, {shape})")
    progress.emit("phase", id="terrain", label=f"Elevation {grid.res:g} m ({'trees + buildings' if cfg.terrain.surface == 'dsm' else 'bare ground'})")
    dem = elevation_for(cfg, grid, cfg.terrain.surface, cache, refresh)
    out.mkdir(parents=True, exist_ok=True)
    dem.astype("<f4").tofile(out / "terrain.f32")

    has_ortho = False
    if cfg.terrain.ortho and not skip_ortho:
        try:
            log("[ortho] SWISSIMAGE")
            ores = cfg.ortho_res(grid)
            progress.emit("phase", id="ortho", label=f"Aerial photo {ores:g} m")
            ogrid = grid.with_resolution(ores)
            img = swisstopo.orthophoto(ogrid, cache, refresh, keys=cfg.corridor.tile_keys() if cfg.corridor else None)
            Image.fromarray(img).save(out / "ortho.jpg", quality=88)
            has_ortho = True
        except Exception as ex:  # imagery is optional
            log(f"[ortho] skipped: {ex}")
    return grid, dem, has_ortho


def load_terrain(out: Path):
    meta = json.loads((out / "scene.json").read_text(encoding="utf-8"))
    g = meta["grid"]
    grid = Grid.from_dict(g)
    dem = np.fromfile(out / "terrain.f32", dtype="<f4").reshape(grid.shape)
    return meta, grid, dem


# ---------------------------------------------------------------- bare ground + buildings + sharp photo

MAX_DTM_CELLS = 40e6      # bare-ground copy of a surface-model scene: coarser above this (memory)


def build_extras(cfg: LocationConfig, out: Path, cache: Path, grid: Grid, dem, refresh=False):
    """Bare-ground terrain (for scenes on the surface model) and 3D buildings.
    Returns meta entries {terrain_dtm, buildings}."""
    meta = {}
    dtm, dgrid = (dem, grid) if cfg.terrain.surface == "dtm" else (None, None)
    if cfg.terrain.surface == "dsm" and not cfg.terrain.local_dem_files:
        res = grid.res
        while (grid.max_e - grid.min_e) * (grid.max_n - grid.min_n) / res ** 2 > MAX_DTM_CELLS:
            res = next(r for r in sorted(VALID_RES) if r > res)
        dgrid = grid if res == grid.res else grid.with_resolution(res)
        f = out / "terrain_dtm.f32"
        try:
            old = json.loads((out / "scene.json").read_text(encoding="utf-8")).get("terrain_dtm") or {}
        except (OSError, ValueError):
            old = {}
        if f.exists() and not refresh and old.get("grid", {}).get("res") == res and old.get("grid", {}).get("cols") == dgrid.cols:
            dtm = np.fromfile(f, dtype="<f4").reshape(dgrid.shape)
            log("[terrain] bare ground: reusing")
        else:
            log(f"[terrain] bare ground (swissALTI3D) {res:g} m, for the 3D-buildings view")
            progress.emit("phase", id="terrain", label=f"Bare ground {res:g} m (for 3D buildings)")
            try:
                dtm = elevation_for(cfg, dgrid, "dtm", cache, refresh)
                dtm.astype("<f4").tofile(f)
            except (Exception, SystemExit) as ex:        # offline: keep the scene, retry later
                log(f"[terrain] bare ground unavailable ({ex}) - no 3D buildings this time")
                return dict(buildings=dict(count=0, error=f"bare-ground terrain unavailable: {str(ex)[:200]}",
                                           when=time.strftime("%Y-%m-%d %H:%M")))
        meta["terrain_dtm"] = dict(file="terrain_dtm.f32", grid=dgrid.to_dict())
    if not cfg.terrain.buildings:
        meta["buildings"] = dict(count=0, disabled=True)
    elif dtm is not None:
        progress.emit("phase", id="buildings", label="3D buildings (OpenStreetMap)")
        keep = None
        if cfg.corridor is not None:
            cor = cfg.corridor
            keep = lambda xy: cor.distance(grid.min_e + xy[:, 0].mean(), grid.min_n + xy[:, 1].mean()) <= cor.width + 15  # noqa: E731
        meta["buildings"] = bldmod.write_scene_buildings(out, grid, dtm, dem if cfg.terrain.surface == "dsm" else None,
                                                         cache, refresh, dtm_grid=dgrid, keep=keep)
    return meta


def detail_ortho(cfg: LocationConfig, cache: Path, grid: Grid, pilot, refresh=False):
    """Sharp aerial photo tiles around the pilot (served to the viewer's close-up patch)."""
    od = cfg.terrain.ortho_detail_m
    if od in (None, False, "off", 0) or not cfg.terrain.ortho:
        return None
    if od == "auto":
        if cfg.terrain.resolution_m > 1:
            return None
        od = 0.5
    od = float(od)
    if od >= cfg.ortho_res(grid):
        return None
    from .tilecache import TILE, TileCache
    r = cfg.terrain.detail_radius_m
    e, n = grid.min_e + pilot["x"], grid.min_n + pilot["y"]
    keys = [(ke, kn) for ke in range(int((e - r) // TILE), int((e + r) // TILE) + 1)
            for kn in range(int((n - r) // TILE), int((n + r) // TILE) + 1)]
    if cfg.corridor is not None:
        keys = sorted(set(keys) & set(cfg.corridor.tile_keys()))
        if not keys:
            return None
    log(f"[ortho] sharp photo {od:g} m within {r:g} m of the pilot ({len(keys)} tile(s))")
    progress.emit("phase", id="ortho", label=f"Sharp aerial photo {od:g} m near the pilot")
    try:
        TileCache(cache).ensure("ortho", od, keys, refresh)
    except (Exception, SystemExit) as ex:
        log(f"[ortho] sharp photo skipped: {ex}")
        return None
    return dict(res=od, radius_m=r)


# ---------------------------------------------------------------- pilot

def pilot_position(cfg: LocationConfig, terrain: Terrain, tracks):
    if cfg.pilot is not None:
        e, n = cfg.pilot.lv95()
        src = "config"
    elif tracks:
        e, n = wgs84_to_lv95(tracks[0].lat[0], tracks[0].lon[0])
        src = f"first fix of {tracks[0].name}"
    else:
        e, n = cfg.center.lv95()
        src = "map centre"
    x, y = terrain.grid.to_local(float(e), float(n))
    ground = float(terrain.height(x, y))
    z = ground + cfg.pilot_antenna_height_m
    log(f"[pilot] from {src}: E{float(e):.0f} N{float(n):.0f}, ground {ground:.0f} m, antenna {z:.0f} m")
    return dict(x=float(x), y=float(y), z=float(z), ground=ground, e=float(e), n=float(n), source=src)


# ---------------------------------------------------------------- LOS overlays

def build_los_layers(cfg: LocationConfig, terrain: Terrain, pilot, out: Path):
    link = cfg.links[cfg.analysis.primary_link]
    lgrid = terrain.grid.with_resolution(max(cfg.analysis.los_resolution_m, terrain.grid.res))
    # corridor: analyse only the strip (+ one cell so the edges blend)
    lmask = cfg.corridor.mask(lgrid, extra=lgrid.res) if cfg.corridor is not None else None
    src = (pilot["x"], pilot["y"], pilot["z"])
    layers = []
    memo_path = out / "los_memo.json"
    try:
        memo = json.loads(memo_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        memo = {}
    base_key = hashlib.sha1(terrain.dem.tobytes()).hexdigest()[:16] + json.dumps(
        [round(pilot["x"], 2), round(pilot["y"], 2), round(pilot["z"], 2), lgrid.res,
         None if lmask is None else hashlib.sha1(np.packbits(lmask).tobytes()).hexdigest()[:12],
         vars(link), cfg.analysis.k_factor, cfg.analysis.fresnel_clearance], sort_keys=True, default=str)
    progress.emit("phase", id="los", label="Signal shadows")
    # One pass computes the 3D blind-spot volumes: per map column, the height above ground below which the drone is
    # out of sight / in a blocked Fresnel zone / losing the signal. The flat shadow maps at 10, 30, 60... m are then
    # just "is that height above the ceiling" (identical to computing each map on its own, see tests, and ~3x faster).
    offsets = sorted(set(cfg.analysis.loss_offsets_db) | {0})    # dB: lets the viewer follow antenna/power edits live
    names = ["los", "fresnel", "loss"] + [f"loss{d:+g}" for d in offsets if d != 0]
    key = hashlib.sha1(f"{base_key}|ceilings|v2|{offsets}".encode()).hexdigest()
    ceil = None
    if memo.get("shadow3d", {}).get("key") == key and (out / "shadow3d.bin").exists():
        vol = memo["shadow3d"]["meta"]
        log("[3d] blind-spot volumes: unchanged, reused")
    else:
        t0 = time.time()
        ceil, _ = los_ceilings(terrain, src, lgrid, link.freq_mhz, cfg.analysis.k_factor,
                               cfg.analysis.fresnel_clearance, radio.allowed_path_loss_db(link), offsets, mask=lmask,
                               on_progress=lambda f: progress.emit("pct", throttle=0.3, phase="los", label="3D blind-spot volumes",
                                                                   pct=round(90 * f)))
        stack = np.stack([np.where(np.isfinite(ceil[k]), np.clip(np.round(ceil[k] * 10), 0, 65534), 65535)
                          for k in names]).astype("<u2")           # decimetres, 65535 = whole column
        stack.tofile(out / "shadow3d.bin")
        vol = dict(file="shadow3d.bin", layers=names, rows=lgrid.rows, cols=lgrid.cols, res=lgrid.res,
                   scale=0.1, inf=65535, dtype="uint16", loss_offsets_db=offsets, agl_grid=True,
                   link=link.name)
        memo["shadow3d"] = dict(key=key, meta=vol)
        write_atomic(memo_path, json.dumps(memo))
        log(f"[3d] blind-spot volumes {lgrid.cols}x{lgrid.rows} ({time.time() - t0:.1f}s)")

    def ceilings():
        """The volumes as heights in metres (inf = whole column), from this build or read back from shadow3d.bin."""
        nonlocal ceil
        if ceil is None:
            raw = np.fromfile(out / vol["file"], dtype="<u2").reshape(len(vol["layers"]), vol["rows"], vol["cols"])
            ceil = {k: np.where(raw[i] == vol["inf"], np.inf, raw[i] * vol["scale"]).astype(np.float32)
                    for i, k in enumerate(vol["layers"])}
        return ceil

    layers = []
    for agl in cfg.analysis.los_agl_m:
        t0 = time.time()
        key = hashlib.sha1(f"{base_key}|{agl}|from-ceilings".encode()).hexdigest()
        name = f"los_{int(agl)}.png"
        if memo.get(name, {}).get("key") == key and (out / name).exists():
            layers.append(memo[name]["layer"])
            log(f"[los] {agl:>5} m AGL: unchanged, reused")
            continue
        c = ceilings()
        blocked = c["los"] > agl                     # no direct line of sight at this height
        fresnel_bad = (c["fresnel"] > agl) & ~blocked
        lost = c["loss"] > agl                       # predicted link margin below 0
        rgba = np.zeros(blocked.shape + (4,), np.uint8)
        # Out-of-range-only areas are left transparent: the range sphere / ring shows those.
        rgba[fresnel_bad] = (255, 176, 0, 110)       # amber: Fresnel zone partly obstructed
        rgba[fresnel_bad & lost] = (255, 120, 0, 150)
        rgba[blocked] = (40, 30, 90, 175)            # indigo: no direct line of sight (diffraction may still work)
        rgba[blocked & lost] = (5, 5, 12, 225)       # near-black: no LOS and predicted signal loss
        Image.fromarray(rgba, "RGBA").save(out / name)
        stats = dict(blocked=float(blocked.mean()), fresnel=float(fresnel_bad.mean()), lost=float((lost & blocked).mean()))
        layers.append(dict(agl=float(agl), file=name, **stats))
        memo[name] = dict(key=key, layer=layers[-1])
        write_atomic(memo_path, json.dumps(memo))
        log(f"[los] {agl:>5} m AGL: no-LOS {stats['blocked']:.0%}, Fresnel {stats['fresnel']:.0%}, "
            f"shadow+loss {stats['lost']:.0%}  ({time.time() - t0:.1f}s)")
        progress.emit("pct", throttle=0.3, phase="los", pct=90 + round(10 * len(layers) / len(cfg.analysis.los_agl_m)),
                      label=f"shadow map at {agl:g} m above ground")
    return layers, vol


# ---------------------------------------------------------------- tracks

def process_track(cfg: LocationConfig, terrain: Terrain, pilot, track: logmod.Track, opts: dict):
    e, n = wgs84_to_lv95(track.lat, track.lon)
    x, y = terrain.grid.to_local(e, n)
    ground = terrain.height(x, y)
    z = logmod.resolve_altitude_amsl(track, ground, opts.get("altitude_mode", "auto"),
                                     float(opts.get("altitude_offset_m", 0.0)), opts.get("altitude_scale"))
    src = (pilot["x"], pilot["y"], pilot["z"])
    link0 = cfg.links[cfg.analysis.primary_link]
    clear, fres, dist = path_clearance(terrain, src, x, y, z, link0.freq_mhz, cfg.analysis.k_factor)
    margins = {}
    for l in cfg.links:
        f = fres if l is link0 else path_clearance(terrain, src, x, y, z, l.freq_mhz, cfg.analysis.k_factor)[1]
        margins[l.name] = radio.link_margin_db(l, dist, f)
    inside = (x >= 0) & (y >= 0) & (x <= terrain.grid.max_e - terrain.grid.min_e) & \
             (y <= terrain.grid.max_n - terrain.grid.min_n)
    if not inside.all():
        log(f"[track] warning: {np.count_nonzero(~inside)} samples of {track.name} are outside the map")

    def r(a, d=1):
        return [None if not np.isfinite(v) else round(float(v), d) for v in a]

    data = dict(
        name=track.name, format=track.source_format, n=int(len(x)),
        t=r(track.t, 2), x=r(x), y=r(y), z=r(z), agl=r(z - ground),
        dist=r(dist), clearance=r(np.minimum(clear, 9999)), fresnel=r(np.minimum(fres, 99), 2),
        margin={k: r(v) for k, v in margins.items()}, telemetry={k: r(v, 1) for k, v in track.telemetry.items()},
    )
    summary = dict(
        name=track.name, file=f"tracks/{track.name}.json", n=data["n"],
        duration_s=round(float(track.t[-1] - track.t[0]), 1),
        max_dist_m=round(float(np.nanmax(dist)), 0),
        max_agl_m=round(float(np.nanmax(z - ground)), 0),
        no_los_pct=round(float(np.mean(clear < 0) * 100), 1),
        fresnel_pct=round(float(np.mean((fres < cfg.analysis.fresnel_clearance) & (clear >= 0)) * 100), 1),
    )
    log(f"[track] {track.name} ({track.source_format}): {summary['n']} pts, {summary['duration_s']} s, "
        f"max {summary['max_dist_m']:.0f} m, no-LOS {summary['no_los_pct']}% of samples")
    return data, summary


def _attach_battery(cfg, p, tr, data, summ):
    """The flight's battery (blackbox: saved when it was downloaded; radio logs: from RxBt / Curr): cell voltage and
    current along the track (path colours) and the flight's id for the viewer's battery tab."""
    if "_sim_" in tr.name:                               # training flights: the battery is simulated
        return
    from . import battery
    try:
        fid = Path(p).stem
        f = battery.flight_file(fid)
        if f.exists():
            s = json.loads(f.read_text(encoding="utf-8"))
            battery.link_track(fid, cfg.name, summ["name"])
        else:
            s = battery.from_telemetry(tr.t, tr.telemetry)
            if not s:
                return
            when = tr.start_time or time.strftime("%Y-%m-%d %H:%M", time.localtime(Path(p).stat().st_mtime))
            fid = battery.save_flight(fid, s, when=when, scene=cfg.name, track=summ["name"])
        data.update(battery.resample(s, tr.t), bat_cells=s.get("cells"))
        summ["battery"] = fid
        log(f"[battery] {summ['name']}: {battery.describe(battery.summary(s))}")
    except Exception as ex:                              # noqa: BLE001 - the track is fine without it
        log(f"[battery] {tr.name}: not read ({ex.__class__.__name__}: {ex})")


def _stem(src: str) -> str:
    """File name without folder and extension, whatever the path style (it may come from another system)."""
    return src.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]


def make_sources_portable(scenes_dir: Path) -> int:
    """Scene files written by older versions hold each log's full path (C:\\Users\\<you>\\...). Rewrite those inside
    your Alpline folder as relative paths; returns how many were changed. Safe to run at every start."""
    from .paths import DATA
    n = 0
    for f in sorted(Path(scenes_dir).glob("*/scene.json")):
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        changed = 0
        for t in meta.get("tracks", []):
            src = t.get("source")
            if not src or src == "config" or not (src.startswith(("/", "\\")) or (len(src) > 2 and src[1] == ":")):
                continue
            p = from_portable(src)
            new = portable(p) if p.exists() else None
            if new is None:                                 # the log is gone: keep only where it was inside the folder
                parts = [x for x in src.replace("\\", "/").split("/") if x]
                new = "/".join(parts[len(parts) - 1 - parts[::-1].index("logs"):]) if "logs" in parts else parts[-1]
            if new != src and not Path(new).is_absolute() and DATA:
                t["source"] = new
                changed += 1
        if changed:
            write_atomic(f, json.dumps(meta, indent=1))
            n += changed
    return n


def attach_battery_to_track(scene_dir: Path, fid: str) -> bool:
    """Give an existing track (whose log is named `fid`) its battery series without rebuilding: path colours and the
    link the viewer's battery tab needs. False when no track of this scene came from that log."""
    from . import battery
    try:
        meta = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
        t = next((t for t in meta.get("tracks", []) if t["name"] == fid or _stem(t.get("source", "")) == fid), None)
        if not t:
            return False
        s = json.loads(battery.flight_file(fid).read_text(encoding="utf-8"))
        f = scene_dir / t["file"]
        data = json.loads(f.read_text(encoding="utf-8"))
        data.update(battery.resample(s, data["t"]), bat_cells=s.get("cells"))
        write_atomic(f, json.dumps(data, separators=(",", ":")))
        t["battery"] = fid
        write_atomic(scene_dir / "scene.json", json.dumps(meta, indent=1))
        battery.link_track(fid, meta.get("name", scene_dir.name), t["name"])
        return True
    except (OSError, ValueError, KeyError):
        return False


def add_tracks(cfg, terrain, pilot, out: Path, log_paths, meta_tracks, overrides=None):
    """Process logs into tracks. `log_paths` items are paths or (path, log_option_overrides)."""
    (out / "tracks").mkdir(exist_ok=True)
    by_name = {t["name"]: t for t in meta_tracks}
    for item in log_paths:
        p, ov = item if isinstance(item, tuple) else (item, overrides or {})
        try:
            tr = logmod.read_log(p)
        except Exception as ex:
            log(f"[track] cannot read {p}: {ex}")
            continue
        ov_proc = {k: v for k, v in ov.items() if k != "track_name"}
        if ov.get("track_name"):                       # renamed in fpv3d, the log file itself was left alone
            tr.name = ov["track_name"]
        data, summ = process_track(cfg, terrain, pilot, tr, dict(cfg.log_options, **ov_proc))
        summ["source"] = portable(p)                      # remembered so rebuilds keep this track (no full path)
        _attach_battery(cfg, p, tr, data, summ)
        if ov:
            summ["log_options"] = ov
        write_atomic((out / summ["file"]), json.dumps(data, separators=(",", ":")))
        by_name[summ["name"]] = summ
    return list(by_name.values())


def _summary_from_json(out: Path, f: Path, fresnel_clearance: float):
    """Rebuild a track summary from an already processed track file (source log unknown)."""
    d = json.loads(f.read_text(encoding="utf-8"))
    fin = lambda a: np.array([np.nan if v is None else v for v in a], float)  # noqa: E731
    t, dist, agl, clr, fr = (fin(d[k]) for k in ("t", "dist", "agl", "clearance", "fresnel"))
    return dict(name=d["name"], file=f"tracks/{f.name}", n=d["n"], duration_s=round(float(np.nanmax(t) - np.nanmin(t)), 1),
                max_dist_m=round(float(np.nanmax(dist)), 0), max_agl_m=round(float(np.nanmax(agl)), 0),
                no_los_pct=round(float(np.mean(clr < 0) * 100), 1),
                fresnel_pct=round(float(np.mean((fr < fresnel_clearance) & (clr >= 0)) * 100), 1), stale=True)


def previous_tracks(cfg, out: Path, log_paths):
    """Tracks added earlier (add-log, simulator) that a rebuild must keep.
    Returns (items to re-process, summaries to keep as they are)."""
    old = []
    for f in ("scene.json", "flights.json"):          # flights.json: the flights list from a backup without the scene
        try:
            old = json.loads((out / f).read_text(encoding="utf-8")).get("tracks", [])
            break
        except (OSError, ValueError):
            pass
    wanted = {Path(p).stem for p in log_paths}
    redo, keep, seen = [], [], set(wanted)
    root = Path(__file__).resolve().parent.parent
    for t in old:
        if t["name"] in seen:
            continue
        seen.add(t["name"])
        src = t.get("source")
        if src and src != "config" and from_portable(src).exists():
            redo.append((str(from_portable(src)), t.get("log_options") or {}))
        elif (out / t["file"]).exists():
            keep.append(t)
    # track files no longer listed (lost by an older rebuild): find their log again, else keep as is
    tdir = out / "tracks"
    for f in sorted(tdir.glob("*.json")) if tdir.exists() else []:
        if f.stem in seen:
            continue
        seen.add(f.stem)
        cand = [c for c in (root / "logs").rglob(f"{f.stem}.*") if c.suffix.lower() in (".csv", ".gpx", ".txt")]
        if cand:
            sim = "sim" in cand[0].parts
            redo.append((str(cand[0]), dict(altitude_mode="amsl", altitude_offset_m=0, altitude_scale=1) if sim else {}))
        else:
            try:
                keep.append(_summary_from_json(out, f, cfg.analysis.fresnel_clearance))
            except Exception as ex:
                log(f"[track] cannot recover {f.name}: {ex}")
    if redo or keep:
        log(f"[track] keeping {len(redo) + len(keep)} track(s) added earlier")
    return redo, keep


# ---------------------------------------------------------------- top level

class NoSpace(RuntimeError):
    pass


def check_disk(est: dict, scenes_dir: Path, cache: Path):
    """Stop before a build that can't fit on the disk (instead of failing half way): the scene, the downloaded
    tiles (about as big again, more for the surface model) and room for temporary files."""
    from .housekeeping import free_bytes, human
    need = (est["scene_mb"] * 3 + 300) * 1e6
    known = [f for f in (free_bytes(scenes_dir), free_bytes(cache)) if f is not None]
    if not known:
        return
    free = min(known)
    if free < need:
        raise NoSpace(f"not enough disk space: this build needs about {human(need)}, only {human(free)} free. "
                      "Free some space (launcher → files: downloaded maps, old scenes) or build a smaller area.")
    if free < 2 * need:
        log(f"[size] WARNING: only {human(free)} free on the disk (this build needs about {human(need)}).")


def build(cfg: LocationConfig, scenes_dir: Path, cache: Path, extra_logs=(), skip_ortho=False,
          reuse_terrain=False, refresh=False):
    """Build (or rebuild) a scene; refused while another process builds the same location."""
    from .buildlock import Busy, estimate, scene_lock, total_ram_gb
    est, ram = estimate(cfg), total_ram_gb()
    log(f"[size] {est['cols']} x {est['rows']} cells: scene about {est['scene_mb']:.0f} MB, "
        "needs about " + (f"{est['ram_gb']:.1f} GB" if est['ram_gb'] >= 1 else f"{est['ram_gb'] * 1000:.0f} MB")
        + " of memory while building" + (f" (this PC has {ram:.0f} GB)" if ram else ""))
    if ram and est["ram_gb"] > 0.7 * ram:
        log("[size] WARNING: that is close to this PC's memory: the build may fail or make the PC very slow. "
            "Use a coarser terrain detail or a smaller area.")
    try:
        check_disk(est, scenes_dir, cache)
    except NoSpace as ex:
        raise SystemExit(str(ex)) from None
    try:
        with scene_lock(scenes_dir, cfg.name):
            return _build(cfg, scenes_dir, cache, extra_logs, skip_ortho, reuse_terrain, refresh)
    except Busy as ex:
        raise SystemExit(str(ex)) from None


def _build(cfg: LocationConfig, scenes_dir: Path, cache: Path, extra_logs=(), skip_ortho=False,
           reuse_terrain=False, refresh=False):
    out = scenes_dir / cfg.name
    log_paths = list(cfg.logs) + [str(p) for p in extra_logs]
    tracks_for_pilot = []
    if cfg.pilot is None and log_paths:
        try:
            tracks_for_pilot = [logmod.read_log(log_paths[0])]
        except Exception:
            pass

    if reuse_terrain and (out / "scene.json").exists():
        old, grid, dem = load_terrain(out)
        has_ortho = old.get("ortho") is not None
        log("[terrain] reusing existing terrain")
    else:
        grid, dem, has_ortho = build_terrain(cfg, out, cache, skip_ortho, refresh)
    terrain = Terrain(dem, grid)
    pilot = pilot_position(cfg, terrain, tracks_for_pilot)
    extras = build_extras(cfg, out, cache, grid, dem, refresh)
    extras["detail"] = detail_ortho(cfg, cache, grid, pilot, refresh)
    layers, shadow3d = build_los_layers(cfg, terrain, pilot, out)
    redo, keep = previous_tracks(cfg, out, log_paths)
    progress.emit("phase", id="tracks", label="Flight logs")
    tracks = add_tracks(cfg, terrain, pilot, out, list(log_paths) + redo, keep)
    progress.emit("phase", id="zones", label="Drone zones (FOCA)")
    zones = geozones.write_scene_zones(out, grid, cache, refresh)

    lat, lon = lv95_to_wgs84((grid.min_e + grid.max_e) / 2, (grid.min_n + grid.max_n) / 2)
    meta = dict(
        version=1, name=cfg.name, title=cfg.title,
        generated=time.strftime("%Y-%m-%d %H:%M"),
        grid=grid.to_dict(), center_wgs84=[float(lat), float(lon)],
        surface=cfg.terrain.surface,
        elevation=dict(min=float(dem.min()), max=float(dem.max())),
        terrain="terrain.f32", ortho="ortho.jpg" if has_ortho else None,
        pilot=pilot,
        links=[dict(name=l.name, freq_mhz=l.freq_mhz, color=l.color, range_m=round(radio.max_range_m(l), 0),
                    tx_power_dbm=l.tx_power_dbm, tx_gain_dbi=l.tx_gain_dbi, rx_gain_dbi=l.rx_gain_dbi,
                    rx_sensitivity_dbm=l.rx_sensitivity_dbm, misc_losses_db=l.misc_losses_db,
                    fade_margin_db=l.fade_margin_db) for l in cfg.links],
        primary_link=cfg.analysis.primary_link,
        fresnel_clearance=cfg.analysis.fresnel_clearance,
        los_layers=layers,
        shadow3d=shadow3d,
        geozones=zones,
        corridor=cfg.corridor.to_meta(grid, cfg.pilot.lv95() if cfg.pilot else None) if cfg.corridor is not None else None,
        tracks=tracks,
        **extras,
    )
    for l in meta["links"]:
        log(f"[radio] {l['name']}: free-space range ~ {l['range_m'] / 1000:.2f} km")
    write_atomic((out / "scene.json"), json.dumps(meta, indent=1))
    update_index(scenes_dir)
    progress.emit("phase", id="done", label="Done")
    log(f"[done] scene written to {out}")
    return out


def add_logs(cfg: LocationConfig, scenes_dir: Path, log_paths, overrides=None):
    out = scenes_dir / cfg.name
    meta, grid, dem = load_terrain(out)
    terrain = Terrain(dem, grid)
    pilot = meta["pilot"]
    meta["tracks"] = add_tracks(cfg, terrain, pilot, out, log_paths, meta.get("tracks", []), overrides)
    write_atomic((out / "scene.json"), json.dumps(meta, indent=1))
    update_index(scenes_dir)


def refresh_buildings(cfg: LocationConfig, scenes_dir: Path, cache: Path, refresh=False):
    """(Re)make only the 3D buildings (and the bare ground they stand on) of an existing scene."""
    out = scenes_dir / cfg.name
    meta, grid, dem = load_terrain(out)
    extras = build_extras(cfg, out, cache, grid, dem, refresh)
    meta.update(extras)
    write_atomic((out / "scene.json"), json.dumps(meta, indent=1))
    b = extras.get("buildings")
    return b


def refresh_zones(cfg: LocationConfig, scenes_dir: Path, cache: Path, refresh=True):
    """Update only the drone geozones of an existing scene (fast, no terrain work)."""
    out = scenes_dir / cfg.name
    meta, grid, _ = load_terrain(out)
    meta["geozones"] = geozones.write_scene_zones(out, grid, cache, refresh)
    write_atomic((out / "scene.json"), json.dumps(meta, indent=1))


def update_index(scenes_dir: Path):
    scenes = []
    for d in sorted(scenes_dir.iterdir()):
        f = d / "scene.json"
        if f.exists():
            m = json.loads(f.read_text(encoding="utf-8"))
            scenes.append(dict(name=m["name"], title=m.get("title", m["name"]), tracks=len(m.get("tracks", []))))
    write_atomic((scenes_dir / "index.json"), json.dumps(scenes, indent=1))
