"""Local web server for the viewer and the map page, with a small JSON API.

GET  /api/state                 locations, built scenes and the tile-cache inventory
GET  /api/height?lat=..&lon=..  ground height (from the local cache, else swisstopo's height service)
GET  /api/search?q=..           place search (swisstopo SearchServer)
POST /api/locations             create a location file           body: see write_location()
POST /api/links                 save radio link settings to the location file + rebuild  body: {"scene", "links": [...]}
POST /api/refresh-all           update every scene in the background  body: {"mode": "all"|"zones"|"buildings", "missing": false}
POST /api/build                 build a scene in the background  body: {"name": "...", "resolution": 5}
POST /api/simtrack              save a simulator training flight as a track  body: {"scene", "name", "csv"}
GET  /api/live/ports | /api/live/state?since=N        live telemetry (radio USB serial)
POST /api/live/start {scene, source: serial|replay, port | track, speed} · /api/live/stop {save}
POST /api/delete                delete a location (moved to deleted/)  body: {"name"}
POST /api/restore               restore it  body: {"folder"}
POST /api/rename                rename a location or a log  body: {"kind": "location"|"log", "scene", "old", "new", "title"}
GET  /api/terrain?scene=&which=surface|dtm&step=&c0=&r0=&cols=&rows=   terrain window (float32)
GET  /api/ortho?scene=&x0=&y0=&x1=&y1=&px=   sharp aerial photo crop (jpeg)
GET  /api/jobs/<id>?since=N     progress of a background build (log lines + progress events from N)

Only listens on 127.0.0.1, i.e. it is reachable from this computer only.
"""
from __future__ import annotations

import http.server
import os
import json
import re
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import numpy as np

from .geo import wgs84_to_lv95
from .locations import ROOT, list_locations, write_location
from .tilecache import TILE, TileCache

UA = {"User-Agent": "fpv3d/0.1 (local FPV planning tool)"}
JOBS: dict = {}


def _fetch_json(url: str, timeout=10):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


def cached_height(cache: TileCache, e: float, n: float):
    """Ground height from the finest cached elevation tile, or None."""
    key = (int(e // TILE), int(n // TILE))
    for kind in ("dtm", "dsm"):
        d = cache.root / "lod" / kind
        if not d.exists():
            continue
        for rd in sorted(d.iterdir(), key=lambda p: float(p.name[:-1]) if p.name[:-1].replace(".", "").isdigit() else 1e9):
            res = float(rd.name[:-1])
            t = cache.load(kind, res, key)
            if t is None:
                continue
            c = int((e - key[0] * TILE) / res)
            r = int(((key[1] + 1) * TILE - n) / res)
            v = float(t[min(r, t.shape[0] - 1), min(c, t.shape[1] - 1)])
            if np.isfinite(v):
                return v, f"cache ({kind} {res:g} m)"
    return None


def run_build(job_id: str, args: list):
    job = JOBS[job_id]
    cmd = [sys.executable, "-u", "-m", "fpv3d"] + args
    job["cmd"] = " ".join(args)
    job.setdefault("events", [])
    env = dict(os.environ, FPV3D_PROGRESS="1", PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", bufsize=1, env=env)
        buf = ""
        while True:
            ch = p.stdout.read(1)
            if not ch:
                break
            if ch in "\r\n":                       # download progress uses \r
                if buf.startswith("@@"):             # progress event for the map animation
                    try:
                        job["events"].append(json.loads(buf[2:]))
                    except ValueError:
                        pass
                    buf = ""
                    continue
                if buf.strip():
                    if ch == "\r" and job["lines"] and job["lines"][-1].startswith(buf.split(":")[0]):
                        job["lines"][-1] = buf
                    else:
                        job["lines"].append(buf)
                buf = ""
            else:
                buf += ch
        if buf.strip():
            job["lines"].append(buf)
        job["status"] = "done" if p.wait() == 0 else "failed"
    except Exception as ex:
        job["lines"].append(f"error: {ex}")
        job["status"] = "failed"


def location_file_for_scene(scene: str):
    from .config import LocationConfig
    for f in sorted((ROOT / "locations").glob("*.yaml")):
        try:
            if f.stem == scene or LocationConfig.load(f).name == scene:
                return f
        except Exception:
            continue
    return None


def save_sim_track(scenes_dir: Path, cache_dir: Path, b: dict):
    """Write the simulator CSV under logs/sim/<scene>/ and run add-log on it."""
    import time
    scene = b.get("scene", "")
    if not re.match(r"^[\w-]+$", scene):
        return dict(error="bad scene name"), 400
    loc = location_file_for_scene(scene)
    if loc is None:
        return dict(error=f"no location file for scene '{scene}' (locations/{scene}.yaml)"), 400
    label = re.sub(r"[^a-z0-9]+", "_", (b.get("name") or "").lower()).strip("_")[:30]
    stem = f"{scene}_sim_" + time.strftime("%Y-%m-%d_%H%M") + (f"_{label}" if label else "")
    out = ROOT / "logs" / "sim" / scene / f"{stem}.csv"
    if out.exists():                                   # two saves in the same minute
        stem += time.strftime("%S")
        out = out.with_name(f"{stem}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(b.get("csv", ""), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "fpv3d", "--scenes", str(scenes_dir), "--cache", str(cache_dir),
                        "add-log", str(loc.relative_to(ROOT)), str(out.relative_to(ROOT)),
                        "--altitude-mode", "amsl", "--altitude-offset", "0", "--altitude-scale", "1"],
                       cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not (scenes_dir / scene / "tracks" / f"{stem}.json").exists():
        return dict(error="add-log failed: " + (r.stderr or r.stdout)[-400:]), 500
    return dict(ok=True, track=stem, file=f"tracks/{stem}.json", csv=str(out.relative_to(ROOT))), 200


def make_handler(scenes_dir: Path, cache_dir: Path):
    cache = TileCache(cache_dir)

    class Handler(http.server.SimpleHTTPRequestHandler):
        extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                          ".js": "text/javascript", ".json": "application/json",
                          ".f32": "application/octet-stream"}

        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT), **kw)

        def translate_path(self, path):
            # /scenes/... is served from the configured scenes folder (default: ./scenes)
            clean = urllib.parse.unquote(urllib.parse.urlparse(path).path)
            if clean.startswith("/scenes/") and ".." not in clean:
                return str(scenes_dir / clean[len("/scenes/"):])
            return super().translate_path(path)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store, must-revalidate")   # always serve fresh files
            super().end_headers()

        def log_message(self, fmt, *args):   # keep the terminal quiet except for errors
            if args and str(args[1])[:1] in "45":
                super().log_message(fmt, *args)

        # ---------------------------------------------------------------- helpers
        def _json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bin(self, data: bytes, ctype: str, headers=None):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Expose-Headers", "X-Rows, X-Cols, X-Res")
            for k, v in (headers or {}).items():
                self.send_header(k, str(v))
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        # ---------------------------------------------------------------- GET
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            try:
                if u.path == "/api/mode.js":     # loaded by the pages before anything else: Full or Lite mode
                    from . import mode
                    body = f'window.FPV3D_MODE = "{mode.current()}";\n'.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/javascript")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    return self.wfile.write(body)
                if u.path == "/api/state":
                    from .trash import list_deleted
                    from . import mode
                    return self._json(dict(locations=list_locations(scenes_dir), cache=cache.inventory(),
                                           tile_size_m=TILE, deleted=list_deleted()[:10], mode=mode.current()))
                if u.path == "/api/height":
                    e, n = wgs84_to_lv95(float(q["lat"]), float(q["lon"]))
                    e, n = float(e), float(n)
                    hit = cached_height(cache, e, n)
                    if hit:
                        return self._json(dict(height=hit[0], source=hit[1], e=e, n=n))
                    try:
                        d = _fetch_json(f"https://api3.geo.admin.ch/rest/services/height?easting={e:.1f}&northing={n:.1f}&sr=2056")
                        return self._json(dict(height=float(d["height"]), source="swisstopo height service", e=e, n=n))
                    except Exception as ex:
                        return self._json(dict(height=None, source=f"unavailable ({ex.__class__.__name__})", e=e, n=n))
                if u.path == "/api/search":
                    url = ("https://api3.geo.admin.ch/rest/services/ech/SearchServer?type=locations&sr=2056&limit=8&searchText="
                           + urllib.parse.quote(q.get("q", "")))
                    out = []
                    for r in _fetch_json(url).get("results", []):
                        a = r.get("attrs", {})
                        label = re.sub(r"<[^>]+>", "", a.get("label", ""))
                        if "lat" in a and "lon" in a:
                            out.append(dict(label=label, lat=a["lat"], lon=a["lon"]))
                        elif "y" in a and "x" in a:      # LV95: y = east, x = north
                            from .geo import lv95_to_wgs84
                            la, lo = lv95_to_wgs84(a["y"], a["x"])
                            out.append(dict(label=label, lat=float(la), lon=float(lo)))
                    return self._json(out)
                if u.path in ("/api/terrain", "/api/ortho"):
                    from . import viewdata
                    scene = q.get("scene", "")
                    sd = scenes_dir / scene
                    if not re.match(r"^[\w-]+$", scene) or not (sd / "scene.json").exists():
                        return self._json(dict(error="unknown scene"), 404)
                    if u.path == "/api/terrain":
                        win, g = viewdata.terrain_window(sd, q.get("which", "surface"), int(q.get("step", 1)),
                                                         int(q.get("c0", 0)), int(q.get("r0", 0)),
                                                         int(q["cols"]) if "cols" in q else None, int(q["rows"]) if "rows" in q else None)
                        return self._bin(win.tobytes(), "application/octet-stream",
                                         {"X-Rows": win.shape[0], "X-Cols": win.shape[1], "X-Res": g["res"]})
                    jpg = viewdata.ortho_window(sd, cache_dir, float(q["x0"]), float(q["y0"]), float(q["x1"]), float(q["y1"]),
                                                int(q.get("px", 2048)))
                    if jpg is None:
                        return self._json(dict(error="no sharp photo here"), 404)
                    return self._bin(jpg, "image/jpeg")
                if u.path == "/api/live/state":
                    from .live import LINK
                    return self._json(LINK.snapshot(int(q.get("since", 0) or 0)))
                if u.path == "/api/live/ports":
                    from .live import list_ports
                    try:
                        return self._json(dict(ports=list_ports()))
                    except RuntimeError as ex:
                        return self._json(dict(ports=[], error=str(ex)))
                m = re.match(r"^/api/jobs/([\w-]+)$", u.path)
                if m:
                    job = JOBS.get(m.group(1))
                    if not job:
                        return self._json({"status": "unknown"}, 404)
                    q = urllib.parse.parse_qs(u.query)
                    since = int((q.get("since") or ["0"])[0] or 0)
                    ev = job.get("events", [])
                    return self._json(dict(job, events=ev[since:], events_total=len(ev)))
                if u.path in ("/", "/map"):
                    self.send_response(302)
                    self.send_header("Location", "/viewer/map.html")
                    self.end_headers()
                    return
            except Exception as ex:
                return self._json(dict(error=str(ex)), 500)
            return super().do_GET()

        # ---------------------------------------------------------------- POST
        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            try:
                b = self._body()
                if u.path == "/api/locations":
                    out = write_location(
                        b["name"], b.get("title") or b["name"], tuple(b["center"]), tuple(b.get("pilot") or b["center"]),
                        float(b.get("half_size_m", 2500)), float(b.get("resolution_m", 5)), b.get("surface", "dtm"),
                        float(b.get("antenna_height_m", 1.8)), b.get("radio_from") or None, bool(b.get("overwrite")),
                        b.get("corridor") or None)
                    return self._json(dict(ok=True, file=f"locations/{out.name}", name=out.stem))
                if u.path == "/api/rename":
                    # {"kind": "location", "old", "new", "title"} or {"kind": "log", "scene", "old", "new"}
                    from . import rename as rn
                    if any(j["status"] == "running" for j in JOBS.values()):
                        return self._json(dict(error="wait for the running build to finish"), 409)
                    try:
                        if b.get("kind") == "location":
                            name = rn.rename_location(b["old"], b.get("new") or b["old"], scenes_dir, title=b.get("title"), log=lambda *_: None)
                            return self._json(dict(ok=True, name=name))
                        name = rn.rename_track(b["scene"], b["old"], b["new"], scenes_dir, log=lambda *_: None)
                        return self._json(dict(ok=True, name=name, file=f"tracks/{name}.json"))
                    except (ValueError, FileExistsError, FileNotFoundError, KeyError) as ex:
                        return self._json(dict(error=str(ex)), 400)
                if u.path in ("/api/delete", "/api/restore"):
                    from . import trash
                    if any(j["status"] == "running" for j in JOBS.values()):
                        return self._json(dict(error="wait for the running build to finish"), 409)
                    try:
                        if u.path == "/api/delete":
                            return self._json(dict(ok=True, **trash.delete_location(b["name"], scenes_dir, log=lambda *_: None)))
                        return self._json(dict(ok=True, **trash.restore_location(b["folder"], scenes_dir, log=lambda *_: None)))
                    except (FileNotFoundError, FileExistsError, KeyError, OSError) as ex:
                        return self._json(dict(error=str(ex)), 400)
                if u.path == "/api/live/start":
                    from .live import LINK
                    scene = b.get("scene", "")
                    if not re.match(r"^[\w-]+$", scene) or not (scenes_dir / scene / "scene.json").exists():
                        return self._json(dict(error="unknown scene"), 400)
                    if b.get("source") == "replay":
                        tf = scenes_dir / scene / str(b.get("track", ""))
                        if ".." in str(b.get("track", "")) or not tf.exists():
                            return self._json(dict(error="pick a flight log to replay"), 400)
                        LINK.start(scene, "replay", replay_file=tf, speed=float(b.get("speed", 1)))
                    else:
                        if not b.get("port"):
                            return self._json(dict(error="pick the radio's serial port"), 400)
                        LINK.start(scene, "serial", port=b["port"])
                    return self._json(dict(ok=True))
                if u.path == "/api/live/stop":
                    from .live import LINK
                    LINK.stop()
                    st = LINK.snapshot(10 ** 9)
                    out = dict(ok=True, gps_count=st["gps_count"], csv=st["csv"])
                    if b.get("save") and st["csv"] and st["gps_count"] >= 10 and st.get("scene"):
                        loc = location_file_for_scene(st["scene"])
                        if loc is not None:
                            r = subprocess.run([sys.executable, "-m", "fpv3d", "--scenes", str(scenes_dir), "--cache", str(cache_dir),
                                                "add-log", str(loc.relative_to(ROOT)), st["csv"]],
                                               cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
                            stem = Path(st["csv"]).stem
                            if r.returncode == 0 and (scenes_dir / st["scene"] / "tracks" / f"{stem}.json").exists():
                                out.update(track=stem, file=f"tracks/{stem}.json")
                            else:
                                out["warning"] = "saved the CSV, but adding it to the scene failed: " + (r.stderr or r.stdout)[-300:]
                    return self._json(out)
                if u.path == "/api/simtrack":
                    return self._json(*save_sim_track(scenes_dir, cache_dir, b))
                if u.path == "/api/links":
                    # save edited radio settings into the location file, then rebuild the scene's shadows
                    from .locations import patch_links
                    scene = b.get("scene", "")
                    loc = location_file_for_scene(scene) if re.match(r"^[\w-]+$", scene) else None
                    if loc is None:
                        return self._json(dict(error=f"no location file for scene '{scene}'"), 400)
                    if any(j["status"] == "running" for j in JOBS.values()):
                        return self._json(dict(error="a build is already running"), 409)
                    changed = patch_links(loc, b.get("links") or [])
                    args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "build",
                            str(loc.relative_to(ROOT)), "--reuse-terrain"]
                    jid = uuid.uuid4().hex[:10]
                    JOBS[jid] = dict(id=jid, name=scene, status="running", lines=[f"saved to {loc.name}: " + (", ".join(changed) or "no change")])
                    threading.Thread(target=run_build, args=(jid, args), daemon=True).start()
                    return self._json(dict(job=jid, changed=changed, file=loc.name))
                if u.path == "/api/refresh-all":
                    if any(j["status"] == "running" for j in JOBS.values()):
                        return self._json(dict(error="a build is already running"), 409)
                    args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "refresh-all"]
                    if b.get("mode") == "buildings":
                        args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "buildings"]
                    elif b.get("mode") == "zones":
                        args.append("--zones-only")
                    if b.get("missing"):
                        args.append("--missing")
                    jid = uuid.uuid4().hex[:10]
                    JOBS[jid] = dict(id=jid, name="(all scenes)", status="running", lines=[])
                    threading.Thread(target=run_build, args=(jid, args), daemon=True).start()
                    return self._json(dict(job=jid))
                if u.path == "/api/build":
                    name = b["name"]
                    if not re.match(r"^[\w-]+$", name) or not (ROOT / "locations" / f"{name}.yaml").exists():
                        return self._json(dict(error="unknown location"), 400)
                    if any(j["status"] == "running" and j["name"] == name for j in JOBS.values()):
                        return self._json(dict(error="a build of this location is already running"), 409)
                    args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "build", f"locations/{name}.yaml"]
                    if b.get("resolution"):
                        args += ["--resolution", str(float(b["resolution"]))]
                    jid = uuid.uuid4().hex[:10]
                    JOBS[jid] = dict(id=jid, name=name, status="running", lines=[])
                    threading.Thread(target=run_build, args=(jid, args), daemon=True).start()
                    return self._json(dict(job=jid))
            except FileExistsError as ex:
                return self._json(dict(error=str(ex), exists=True), 409)
            except (KeyError, ValueError) as ex:
                return self._json(dict(error=str(ex)), 400)
            except Exception as ex:
                return self._json(dict(error=str(ex)), 500)
            self._json(dict(error="not found"), 404)

    return Handler


def serve(port: int, scenes_dir: Path, cache_dir: Path, open_path: str = "/viewer/", open_browser=True):
    import webbrowser
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), make_handler(scenes_dir, cache_dir)) as httpd:
        url = f"http://127.0.0.1:{port}{open_path}"
        print(f"fpv3d: {url}   (map: http://127.0.0.1:{port}/viewer/map.html)   Ctrl+C to stop")
        if open_browser:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
