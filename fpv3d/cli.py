"""Command line:  python -m fpv3d <command> ...

  build      locations/moleson.yaml [--log FILE ...]   download data, compute LOS, write scene
  add-log    locations/moleson.yaml FILE [FILE ...]    add flight logs to an existing scene (fast)
  serve      [--port 8000] [--scene NAME] [--lite]      open the 3D viewer in your browser (--lite = Lite mode)
  map        [--port 8000]                              Swiss map: cached areas, click to create locations
  new        NAME --lat 46.x --lon 7.x                  create a new location file
  refresh-all [--zones-only | --full] [--missing]      update every scene at once (new features, zones, tracks)
  buildings [location.yaml ...] [--all]               add / retry 3D buildings (scenes without them)
  delete NAME | restore [NAME] | deleted [--purge]    delete a location (restorable), undo, empty the bin
  zones      locations/x.yaml [--no-refresh]           update the drone no-fly / restricted zones of a scene
  prefetch   locations/x.yaml --res 2 5 10              download + memoise terrain at several detail levels
  cache      info | clear [--raw] [--lod] [--kind dtm] | prune [--dry-run]   inspect / clean the tile cache
  blackbox   [--port COM5] [--file LOG.BBL]             download the drone's blackbox over USB, add its flights
  video-convert FILE [...]                             re-encode H.265 DVR footage to browser-friendly H.264
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .paths import DATA

ROOT = DATA          # your files: locations/, scenes/, cache/ (see fpv3d/paths.py)




def cmd_build(a):
    from .config import LocationConfig
    from .scene import build
    cfg = LocationConfig.load(a.config)
    if a.resolution:
        from .config import VALID_RES
        if a.resolution not in VALID_RES:
            sys.exit(f"--resolution must be one of {VALID_RES}")
        cfg.terrain.resolution_m = a.resolution
    if a.name:
        cfg.name = a.name
    build(cfg, Path(a.scenes), Path(a.cache), extra_logs=a.log or [], skip_ortho=a.no_ortho,
          reuse_terrain=a.reuse_terrain, refresh=a.refresh)


def cmd_zones(a):
    from .config import LocationConfig
    from .scene import refresh_zones
    cfg = LocationConfig.load(a.config)
    refresh_zones(cfg, Path(a.scenes), Path(a.cache), refresh=not a.no_refresh)


def cmd_refresh_all(a):
    """Bring every built scene up to date in one go."""
    import time
    import traceback
    from . import geozones
    from .config import LocationConfig
    from .scene import build, refresh_zones, update_index
    scenes, cache = Path(a.scenes), Path(a.cache)
    files = sorted((ROOT / "locations").glob("*.yaml"))
    if a.only:
        files = [f for f in files if f.stem in a.only]
    geozones.fetch(cache, refresh=True)          # one fresh download of the zones for all scenes
    done, skipped, failed = [], [], []
    for i, f in enumerate(files, 1):
        try:
            cfg = LocationConfig.load(f)
        except Exception as ex:
            failed.append((f.stem, f"bad location file: {ex}"))
            continue
        built = (scenes / cfg.name / "scene.json").exists()
        if not built and not a.missing:
            skipped.append(cfg.name)
            continue
        print(f"\n=== [{i}/{len(files)}] {cfg.title} ({f.name}) ===", file=sys.stderr, flush=True)
        t0 = time.time()
        try:
            if a.zones_only and built:
                refresh_zones(cfg, scenes, cache, refresh=False)
            else:
                build(cfg, scenes, cache, reuse_terrain=built and not a.full)
            done.append((cfg.name, time.time() - t0))
        except Exception as ex:
            traceback.print_exc()
            failed.append((cfg.name, str(ex)))
    update_index(scenes)
    print("\n=== summary ===", file=sys.stderr)
    for n, dt in done:
        print(f"  ok      {n} ({dt:.0f}s)", file=sys.stderr)
    for n in skipped:
        print(f"  skipped {n} (never built - add --missing to build it)", file=sys.stderr)
    for n, err in failed:
        print(f"  FAILED  {n}: {err}", file=sys.stderr)
    if failed:
        sys.exit(1)


def cmd_buildings(a):
    """Add / retry the 3D buildings of built scenes (only the ones without buildings by default)."""
    import json
    import time
    from .config import LocationConfig
    from .scene import refresh_buildings
    scenes, cache = Path(a.scenes), Path(a.cache)
    files = [Path(f) for f in a.config] if a.config else sorted((ROOT / "locations").glob("*.yaml"))
    rows = []
    for i, f in enumerate(files):
        cfg = LocationConfig.load(f)
        sj = scenes / cfg.name / "scene.json"
        if not sj.exists():
            continue
        b = json.loads(sj.read_text(encoding="utf-8")).get("buildings")
        if b and b.get("count") and not (a.all or a.config):
            rows.append((cfg.name, f"already has {b['count']} buildings"))
            continue
        if not cfg.terrain.buildings:
            rows.append((cfg.name, "buildings: false in the location file"))
            continue
        if i and rows and not rows[-1][1].startswith("already"):
            time.sleep(3)                      # be gentle with the public Overpass servers
        print(f"=== {cfg.title} ===", file=sys.stderr, flush=True)
        r = refresh_buildings(cfg, scenes, cache, refresh=a.refresh)
        rows.append((cfg.name, f"{r['count']} buildings" if r and not r.get("error") else f"FAILED: {(r or {}).get('error', 'disabled')}"))
    print("\n=== summary ===", file=sys.stderr)
    for n, s in rows:
        print(f"  {n:18} {s}", file=sys.stderr)


def cmd_prefetch(a):
    from .config import VALID_RES, LocationConfig
    from .geo import Grid
    from .tilecache import TileCache, tile_keys
    cfg = LocationConfig.load(a.config)
    ce, cn = cfg.center.lv95()
    half = a.half_size or cfg.half_size_m
    cor = cfg.corridor if not a.half_size else None
    if cor is not None:                       # route-shaped location: only the strip's tiles
        keys = cor.tile_keys()
        tc = TileCache(Path(a.cache))
        kinds = ["dtm", "dsm"] if a.surface == "both" else [a.surface or cfg.terrain.surface]
        for res in a.res or [cfg.terrain.resolution_m]:
            for k in kinds:
                tc.ensure(k, res, keys, a.refresh)
        if not a.no_ortho:
            for res in a.ortho_res or [cfg.ortho_res()]:
                tc.ensure("ortho", res, keys, a.refresh)
        tc.ensure("dtm", 10, cor.context_keys(cfg.pilot.lv95() if cfg.pilot else None), a.refresh)
        print(f"{len(keys)} km² along the route of {cfg.title} cached (+ coarse context).")
        print("\n".join(tc.info()))
        return
    tc = TileCache(Path(a.cache))
    kinds = ["dtm", "dsm"] if a.surface == "both" else [a.surface or cfg.terrain.surface]
    for res in a.res or [cfg.terrain.resolution_m]:
        if res not in VALID_RES:
            sys.exit(f"--res values must be among {VALID_RES}")
        grid = Grid.around(ce, cn, half, res)
        for k in kinds:
            tc.mosaic(k, grid, a.refresh)
    if not a.no_ortho:
        for res in a.ortho_res or [cfg.ortho_res()]:
            tc.mosaic("ortho", Grid.around(ce, cn, half, res), a.refresh)
    print(f"{len(tile_keys(Grid.around(ce, cn, half, 10)))} km² cached around {cfg.title}. "
          "Builds of this area (any location file) now work offline.")
    print("\n".join(tc.info()))


def location_tile_keys(margin_km: int = 1) -> set:
    """1 km tile keys ("E-N") used by the location files, + a margin of tiles around each one."""
    from .config import LocationConfig
    from .tilecache import tile_keys
    keep = set()
    for f in sorted((ROOT / "locations").glob("*.yaml")):
        try:
            cfg = LocationConfig.load(f)
        except Exception as ex:                  # a broken file: keep everything rather than guess
            raise SystemExit(f"{f.name} cannot be read ({ex}); fix it before cleaning the cache") from ex
        if cfg.corridor is not None:
            ks = set(cfg.corridor.tile_keys()) | set(cfg.corridor.context_keys(cfg.pilot.lv95() if cfg.pilot else None))
        else:
            ks = set(tile_keys(cfg.grid(10)))
        for e, n in ks:
            for de in range(-margin_km, margin_km + 1):
                for dn in range(-margin_km, margin_km + 1):
                    keep.add(f"{e + de}-{n + dn}")
    return keep


def cmd_cache(a):
    from .tilecache import TileCache
    tc = TileCache(Path(a.cache))
    if a.action == "prune":
        files, size = tc.prune(location_tile_keys(), dry_run=a.dry_run)
        print(f"{'would free' if a.dry_run else 'freed'} {size / 1e6:.0f} MB ({files} tiles not used by any location file)")
        return
    if a.action == "clear":
        if not (a.raw or a.lod):
            sys.exit("say what to clear: --raw (downloads), --lod (resampled tiles) or both")
        tc.clear(raw=a.raw, lod=a.lod, kind=a.kind)
    print("\n".join(tc.info()))


def cmd_add_log(a):
    from .config import LocationConfig
    from .scene import add_logs
    cfg = LocationConfig.load(a.config)
    ov = {}
    if a.altitude_mode:
        ov["altitude_mode"] = a.altitude_mode
    if a.altitude_offset is not None:
        ov["altitude_offset_m"] = a.altitude_offset
    if a.altitude_scale is not None:
        ov["altitude_scale"] = a.altitude_scale
    add_logs(cfg, Path(a.scenes), a.logs, ov)


def cmd_blackbox(a):
    from .blackbox import run
    if a.saved:                                  # read the logs kept from earlier downloads again (battery data)
        from .blackbox import rescan_saved
        return rescan_saved(scenes=a.scenes)
    run(port=a.port, file=a.file, location=a.location, scenes=a.scenes, timeout=a.timeout, skip=a.skip or ())


def cmd_serve(a, path=None):
    from .server import serve
    from . import mode
    if getattr(a, "lite", False):
        mode.set_mode("lite")
    print(f"fpv3d: {mode.current()} mode")
    path = path or ("/viewer/" + (f"?scene={a.scene}" if a.scene else ""))
    serve(a.port, Path(a.scenes), Path(a.cache), path, not a.no_browser, lan=getattr(a, "lan", False))


def cmd_map(a):
    cmd_serve(a, "/viewer/map.html")


def cmd_new(a):
    from .locations import write_location
    from . import mode
    if getattr(a, "lite", False):
        mode.set_mode("lite")
    pilot = (a.pilot_lat, a.pilot_lon) if a.pilot_lat is not None and a.pilot_lon is not None else None
    try:
        out = write_location(a.name, a.title or a.name, (a.lat, a.lon), pilot, a.half_size, a.resolution,
                             a.surface, radio_from=a.radio_from)
    except (ValueError, FileExistsError) as ex:
        sys.exit(str(ex))
    print(f"created {out}\nnext: python -m fpv3d build {out.relative_to(ROOT)}   (or click around: python -m fpv3d map)")


def cmd_video_convert(a):
    import shutil
    import subprocess
    ff = shutil.which("ffmpeg")
    if not ff:
        sys.exit("ffmpeg not found. Install it (Windows: `winget install Gyan.FFmpeg`) and open a new terminal.")
    for f in a.files:
        src = Path(f)
        dst = src.with_name(src.stem + "_h264.mp4")
        cmd = [ff, "-hide_banner", "-y", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast",
               "-crf", str(a.crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "aac", str(dst)]
        if a.height:
            cmd[cmd.index("-c:v"):cmd.index("-c:v")] = ["-vf", f"scale=-2:{a.height}"]
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)
        srt = src.with_suffix(".srt")
        if srt.exists():
            shutil.copyfile(srt, dst.with_suffix(".srt"))
        print(f"-> {dst}")


def cmd_rename(a):
    from . import rename as rn
    try:
        if a.what == "location":
            rn.rename_location(a.old, a.new or a.old, Path(a.scenes), title=a.title)
        else:
            if not a.new:
                sys.exit("usage: python -m fpv3d rename log <location> <old log name> <new log name>")
            rn.rename_track(a.scene, a.old, a.new, Path(a.scenes))
    except (ValueError, FileExistsError, FileNotFoundError) as ex:
        sys.exit(str(ex))


def cmd_delete(a):
    from .trash import delete_location
    if not a.yes:
        ans = input(f"Delete location '{a.name}' (file, 3D scene, training flights)? It goes to deleted/ and can be restored. [y/N] ")
        if ans.strip().lower() not in ("y", "yes", "o", "oui"):
            sys.exit("cancelled")
    try:
        delete_location(a.name, Path(a.scenes))
    except FileNotFoundError as ex:
        sys.exit(str(ex))


def cmd_restore(a):
    from .trash import list_deleted, restore_location
    if not a.what:
        rows = list_deleted()
        if not rows:
            print("nothing in deleted/")
        for r in rows:
            print(f"  {r['folder']:40} {r.get('title', '')}  (deleted {r.get('deleted', '?')})")
        if rows:
            print("\nrestore one with: python -m fpv3d restore <folder or name>")
        return
    try:
        restore_location(a.what, Path(a.scenes))
    except (FileNotFoundError, FileExistsError) as ex:
        sys.exit(str(ex))


def cmd_deleted(a):
    from .trash import list_deleted, purge
    if a.purge:
        n = purge(a.older_than or 0)
        print(f"{n} deleted location(s) removed for good")
        return
    rows = list_deleted()
    for r in rows:
        print(f"  {r['folder']:40} {r.get('title', '')}  (deleted {r.get('deleted', '?')})")
    print(f"{len(rows)} in deleted/. Restore: python -m fpv3d restore <name>. Empty: python -m fpv3d deleted --purge")


def cmd_tidy(a):
    from .rename import tidy
    plan = tidy(Path(a.scenes), apply=False)
    if not plan:
        print("all names are already clean")
        return
    for kind, loc, old, new in plan:
        print(f"  {kind:5} {loc:18} {old}  ->  {new}")
    if not a.apply:
        print(f"\n{len(plan)} change(s) planned. Run again with --apply to do them.")
        return
    tidy(Path(a.scenes), apply=True)
    print("done - reload the viewer (Ctrl+F5)")


def _in_data(a) -> None:
    """File arguments written from the project folder still work now that your files live in data/:
    `build locations/x.yaml` finds data/locations/x.yaml when there is no locations/x.yaml where you are."""
    def fix(v):
        if isinstance(v, list):
            return [fix(x) for x in v]
        if isinstance(v, str) and v and not Path(v).is_absolute() and not Path(v).exists() and (ROOT / v).exists():
            return str(ROOT / v)
        return v
    for k in ("config", "logs", "log", "file"):
        if hasattr(a, k):
            setattr(a, k, fix(getattr(a, k)))


def main(argv=None):
    p = argparse.ArgumentParser(prog="fpv3d", description="3D FPV flight & signal visualiser for Swiss terrain")
    p.add_argument("--scenes", default=str(ROOT / "scenes"), help="output folder for scenes")
    p.add_argument("--cache", default=str(ROOT / "cache"), help="download cache folder")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build a scene from a location file")
    b.add_argument("config")
    b.add_argument("--log", action="append", help="flight log to include (repeatable)")
    b.add_argument("--no-ortho", action="store_true", help="skip aerial imagery download")
    b.add_argument("--reuse-terrain", action="store_true", help="keep existing terrain, recompute LOS only")
    b.add_argument("--resolution", type=float, help="override terrain.resolution_m (e.g. 2 for more detail)")
    b.add_argument("--name", help="write the scene under another name (e.g. moleson_2m)")
    b.add_argument("--refresh", action="store_true", help="ignore cached tiles and download again")
    b.set_defaults(func=cmd_build)

    al = sub.add_parser("add-log", help="add flight logs to an existing scene")
    al.add_argument("config")
    al.add_argument("logs", nargs="+")
    al.add_argument("--altitude-mode", choices=["auto", "amsl", "relative", "agl"], help="override log_options")
    al.add_argument("--altitude-offset", type=float, help="override log_options.altitude_offset_m")
    al.add_argument("--altitude-scale", type=float, help="override log_options.altitude_scale")
    al.set_defaults(func=cmd_add_log)

    bb = sub.add_parser("blackbox", help="download the blackbox from a Betaflight drone on USB and add its flights")
    bb.add_argument("--port", help="serial port of the drone (default: found automatically)")
    bb.add_argument("--file", help="read a .BBL / .BFL file you already have instead")
    bb.add_argument("--location", help="add the flights to this location (default: the one containing the take-off)")
    bb.add_argument("--timeout", type=float, default=60, help="seconds to wait for the USB drive")
    bb.add_argument("--skip", action="append", help="serial port to leave alone (e.g. the radio)")
    bb.add_argument("--saved", action="store_true",
                    help="read the blackbox files kept in logs/blackbox/ again: adds the battery data of flights added "
                         "before the battery analysis (and any flight not added yet)")
    bb.set_defaults(func=cmd_blackbox)

    s = sub.add_parser("serve", help="open the viewer")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--scene")
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--lite", action="store_true", help="Lite mode: lighter 3D and lighter defaults for new locations")
    s.add_argument("--lan", action="store_true", help="share on your network: open it on your phone (same Wi-Fi / hotspot)")
    s.set_defaults(func=cmd_serve)

    mp = sub.add_parser("map", help="open the Switzerland map (cached areas, create locations by clicking)")
    mp.add_argument("--port", type=int, default=8000)
    mp.add_argument("--no-browser", action="store_true")
    mp.add_argument("--lite", action="store_true", help="Lite mode: lighter 3D and lighter defaults for new locations")
    mp.add_argument("--lan", action="store_true", help="share on your network: open it on your phone (same Wi-Fi / hotspot)")
    mp.set_defaults(func=cmd_map, scene=None)

    n = sub.add_parser("new", help="create a location file")
    n.add_argument("name")
    n.add_argument("--lat", type=float, required=True)
    n.add_argument("--lon", type=float, required=True)
    n.add_argument("--title")
    n.add_argument("--pilot-lat", type=float)
    n.add_argument("--pilot-lon", type=float)
    n.add_argument("--half-size", type=float, default=2500)
    n.add_argument("--resolution", type=float, default=5)
    n.add_argument("--surface", choices=["dtm", "dsm"], default="dtm")
    n.add_argument("--radio-from", help="copy the radio links of an existing location")
    n.add_argument("--lite", action="store_true", help="lighter defaults (photo auto, 20 m signal grid, no 3D buildings)")
    n.set_defaults(func=cmd_new)

    ra = sub.add_parser("refresh-all", help="update every scene at once (keeps your tracks)")
    g = ra.add_mutually_exclusive_group()
    g.add_argument("--zones-only", action="store_true", help="only refresh the drone zones (fastest)")
    g.add_argument("--full", action="store_true", help="also rebuild the terrain from the cache")
    ra.add_argument("--missing", action="store_true", help="also build locations that were never built")
    ra.add_argument("--only", nargs="+", metavar="NAME", help="limit to these location names")
    ra.set_defaults(func=cmd_refresh_all)

    zo = sub.add_parser("zones", help="update the drone geozones (FOCA) of an existing scene")
    zo.add_argument("config")
    zo.add_argument("--no-refresh", action="store_true", help="use the cached zone file even if it is old")
    zo.set_defaults(func=cmd_zones)

    bd = sub.add_parser("buildings", help="add or retry the 3D buildings of built scenes (missing ones by default)")
    bd.add_argument("config", nargs="*", help="location files (default: every built scene without buildings)")
    bd.add_argument("--all", action="store_true", help="redo every scene, also those that already have buildings")
    bd.add_argument("--refresh", action="store_true", help="ignore the 30-day OpenStreetMap cache")
    bd.set_defaults(func=cmd_buildings)

    pf = sub.add_parser("prefetch", help="download + memoise terrain for an area at several resolutions")
    pf.add_argument("config")
    pf.add_argument("--res", type=float, nargs="+", help="elevation resolutions in m (default: the config's)")
    pf.add_argument("--ortho-res", type=float, nargs="+", help="aerial photo resolutions in m")
    pf.add_argument("--surface", choices=["dtm", "dsm", "both"], help="default: the config's")
    pf.add_argument("--half-size", type=float, help="area half size in m (default: the config's)")
    pf.add_argument("--no-ortho", action="store_true")
    pf.add_argument("--refresh", action="store_true")
    pf.set_defaults(func=cmd_prefetch)

    ca = sub.add_parser("cache", help="show or clean the tile cache")
    ca.add_argument("action", choices=["info", "clear", "prune"],
                    help="prune = delete tiles that no location file uses (keeps 1 km around each location)")
    ca.add_argument("--dry-run", action="store_true", help="prune: only say how much it would free")
    ca.add_argument("--raw", action="store_true", help="delete raw downloads")
    ca.add_argument("--lod", action="store_true", help="delete resampled tiles")
    ca.add_argument("--kind", choices=["dtm", "dsm", "ortho"])
    ca.set_defaults(func=cmd_cache)

    rn = sub.add_parser("rename", help="rename a location or a flight log (clean ASCII file names)")
    rsub = rn.add_subparsers(dest="what", required=True)
    rl = rsub.add_parser("location", help="rename a location: yaml file, scene folder, sim logs")
    rl.add_argument("old")
    rl.add_argument("new", nargs="?", help="new name (lowercase, digits, _ and -); omit to only change --title")
    rl.add_argument("--title", help="display title (accents ok, emoji are removed)")
    rl.set_defaults(func=cmd_rename)
    rg = rsub.add_parser("log", help="rename a flight log of a location")
    rg.add_argument("scene", help="location name")
    rg.add_argument("old")
    rg.add_argument("new")
    rg.set_defaults(func=cmd_rename, title=None)

    de = sub.add_parser("delete", help="delete a location (moved to deleted/, restorable)")
    de.add_argument("name")
    de.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    de.set_defaults(func=cmd_delete)
    rs = sub.add_parser("restore", help="restore a deleted location (no argument = list them)")
    rs.add_argument("what", nargs="?", help="location name or deleted/ folder")
    rs.set_defaults(func=cmd_restore)
    dl = sub.add_parser("deleted", help="list deleted locations, or --purge them for good")
    dl.add_argument("--purge", action="store_true", help="permanently remove the deleted locations")
    dl.add_argument("--older-than", type=float, metavar="DAYS", help="with --purge: only those deleted more than DAYS ago")
    dl.set_defaults(func=cmd_deleted)

    td = sub.add_parser("tidy", help="clean up titles and log names (sim logs -> <location>_sim_<date>_<time>)")
    td.add_argument("--apply", action="store_true", help="do it (default: only show the plan)")
    td.set_defaults(func=cmd_tidy)

    vc = sub.add_parser("video-convert", help="re-encode video (e.g. DJI H.265) to H.264 for the viewer")
    vc.add_argument("files", nargs="+")
    vc.add_argument("--crf", type=int, default=22, help="quality, lower = better/bigger (default 22)")
    vc.add_argument("--height", type=int, help="downscale, e.g. 720 for lighter files")
    vc.set_defaults(func=cmd_video_convert)

    a = p.parse_args(argv)
    _in_data(a)
    try:
        a.func(a)
    except (ValueError, FileNotFoundError) as ex:        # a broken location file, a missing file: the message, not a crash dump
        if os.environ.get("FPV3D_DEBUG"):
            raise
        sys.exit(f"error: {ex}")


if __name__ == "__main__":
    main()
