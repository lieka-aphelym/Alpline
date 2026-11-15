"""Local web server for the viewer and the map page, with a small JSON API.

GET  /api/state                 locations, built scenes and the tile-cache inventory
GET  /api/height?lat=..&lon=..  ground height (the local cache, else swisstopo's height service, else the world model)
GET  /api/search?q=..[&world=1] place search (swisstopo SearchServer; with world=1 also OpenStreetMap's Photon)
POST /api/locations             create a location file           body: see write_location()
POST /api/links                 save radio link settings to the location file + rebuild  body: {"scene", "links": [...]}
POST /api/refresh-all           update every scene in the background  body: {"mode": "all"|"zones"|"buildings", "missing": false}
POST /api/build                 build a scene in the background  body: {"name": "...", "resolution": 5}
POST /api/client-error          a page's error, added to logs/errors.txt  body: {"page", "message", "stack"}
POST /api/simtrack              save a simulator training flight as a track  body: {"scene", "name", "csv"}
GET  /api/live/ports | /api/live/state?since=N        live telemetry (radio USB serial)
POST /api/live/start {scene, source: serial|replay, port | track, speed} · /api/live/stop {save}
POST /api/blackbox {scene?}     download the blackbox from a Betaflight drone on USB, add its flights (background job)
POST /api/delete                delete a location (moved to deleted/)  body: {"name"}
POST /api/restore               restore it  body: {"folder"}
POST /api/rename                rename a location or a log  body: {"kind": "location"|"log", "scene", "old", "new", "title"}
GET  /api/terrain?scene=&which=surface|dtm&step=&c0=&r0=&cols=&rows=   terrain window (float32)
GET  /api/ortho?scene=&x0=&y0=&x1=&y1=&px=   sharp aerial photo crop (jpeg)
GET  /api/jobs/<id>?since=N     progress of a background build (log lines + progress events from N)
POST /api/jobs/<id>/cancel      stop a running build
POST /api/zones {scene}         download the current drone no-fly zones for one scene
POST /api/pilot {scene,lat,lon} move the pilot point (live flight: takeoff point) and rebuild
GET  /api/battery/packs · /api/battery/flight?id=   battery: packs with health and advice, one flight's series
POST /api/battery/pack {id?, name, cells, capacity, chemistry, retired, note} · assign {flights, pack} · charger {flight, mah}
     · note {pack, kind, text, when?, flight?} · delete-pack {id} · delete-note {id} (deletes: this PC only)
GET  /api/share · /api/ca.crt   phone sharing: addresses + PIN (this PC only) · the private CA for https

Listens on 127.0.0.1 only (this computer), unless started with --lan (launcher [phone]): then other devices on
the network can connect too, over http on the port and https on port + 443, after typing the PIN.

Safety (tests/test_security.py):
  - other web pages open in your browser can't use the API: POST needs Content-Type application/json and, when the
    browser says where it comes from (Origin), the same address as Alpline itself; requests on this computer must be
    addressed to 127.0.0.1 / localhost (blocks "DNS rebinding" through a website's own name)
  - only the pages (/viewer/), scenes (/scenes/) and the API are served: never your locations, logs or settings files
  - the phone needs the PIN (10 wrong tries from one address: locked out for a minute); deleting and renaming only
    work on this computer
  - names in requests are letters, digits, _ and - only; paths with .. are refused
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import html
import http.server
import os
import json
import re
import secrets
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .errorlog import record, record_exception
from .locations import ROOT, list_locations, write_location
from .paths import APP, cli_cmd
from .netinfo import lan_addresses  # shared with the launcher
from .tilecache import TILE, TileCache
from .safefile import write_atomic
from .brand import APP_NAME, BY

UA = {"User-Agent": "fpv3d/0.1 (local FPV planning tool)"}
JOBS: dict = {}


def _fetch_json(url: str, timeout=10):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


def cached_height(cache: TileCache, e: float, n: float):
    """Ground height from the finest cached elevation tile, or None."""
    from .terrain import cached_height as ch
    return ch(cache, e, n)


def place_height(cache: TileCache, lat: float, lon: float) -> dict:
    """Ground height of a place for the map page: the local cache, then swisstopo's height service (Switzerland),
    then the worldwide model. {"height": m or None, "source": text, "e", "n" (on the place's grid), "crs"}."""
    from . import terrain
    from .config import crs_for
    from .geo import LV95, project
    crs = crs_for(lat, lon)
    e, n = (float(v) for v in project(lat, lon, crs))
    out = dict(e=e, n=n, crs=crs)
    why = "unavailable"
    if crs == LV95:
        hit = cached_height(cache, e, n)
        if hit:
            return dict(out, height=hit[0], source=hit[1])
        try:
            d = _fetch_json(f"{HEIGHT_URL}?easting={e:.1f}&northing={n:.1f}&sr=2056")
            return dict(out, height=float(d["height"]), source="swisstopo height service")
        except urllib.error.HTTPError:
            pass                                    # the service knows Switzerland only: across the border, ask the world model
        except Exception as ex:                     # noqa: BLE001 - offline
            why = f"unavailable ({ex.__class__.__name__})"
    try:
        hit = terrain.world_height(cache.root, lat, lon, crs)
        if hit:
            return dict(out, height=hit[0], source=hit[1])
    except Exception:                               # noqa: BLE001 - no file for this square (sea), or offline
        why = "no height here (sea, or offline)"
    return dict(out, height=None, source=why)


HEIGHT_URL = os.environ.get("FPV3D_HEIGHT_URL", "https://api3.geo.admin.ch/rest/services/height")
SEARCH_URL = os.environ.get("FPV3D_SEARCH_URL", "https://api3.geo.admin.ch/rest/services/ech/SearchServer")
WORLD_SEARCH_URL = os.environ.get("FPV3D_WORLD_SEARCH_URL", "https://photon.komoot.io/api/")
_COORD_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def place_search(text: str, world: bool = False) -> list:
    """Places matching `text` for the map page: [{"label", "lat", "lon"}].
    "47.26, 11.39" is taken as a position (nothing is sent anywhere). Else swisstopo's search (Swiss places, addresses,
    postcodes) and, only when the user switched it on (`world`), the worldwide OpenStreetMap search (Photon, by
    Komoot): what is typed then goes to that second service too, so it is never asked without that choice.
    swisstopo always answers something, however far-fetched ("Innsbruck" gives Swiss hamlets): only its results that
    contain the words typed count; the far-fetched ones are shown only when the worldwide search finds nothing."""
    text = (text or "").strip()
    m = _COORD_RE.match(text)
    if m and abs(float(m.group(1))) <= 90 and abs(float(m.group(2))) <= 180:
        la, lo = float(m.group(1)), float(m.group(2))
        return [dict(label=f"{la:.5f}, {lo:.5f} (position)", lat=la, lon=lo)]
    out, loose, failed = [], [], 0
    words = [w for w in re.split(r"[^a-z0-9]+", _plain(text)) if len(w) >= 2]
    try:
        url = f"{SEARCH_URL}?type=locations&sr=2056&limit=8&searchText=" + urllib.parse.quote(text)
        for r in _fetch_json(url).get("results", []):
            a = r.get("attrs", {})
            label = re.sub(r"<[^>]+>", "", a.get("label", ""))
            hit = None
            if "lat" in a and "lon" in a:
                hit = dict(label=label, lat=a["lat"], lon=a["lon"])
            elif "y" in a and "x" in a:      # LV95: y = east, x = north
                from .geo import lv95_to_wgs84
                la, lo = lv95_to_wgs84(a["y"], a["x"])
                hit = dict(label=label, lat=float(la), lon=float(lo))
            if hit:
                (out if words and all(w in _plain(label) for w in words) else loose).append(hit)
    except Exception:                               # noqa: BLE001
        failed += 1
    if not world:
        if failed:
            raise OSError("place search unavailable")
        return out or loose
    out = out[:5]            # room for the rest of the world: a name can be both (Chamonix: streets in Geneva, a town in France)
    try:
        url = f"{WORLD_SEARCH_URL}?lang=en&limit={8 - len(out)}&q=" + urllib.parse.quote(text)
        for f in _fetch_json(url).get("features", []):
            p, c = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates") or []
            if len(c) < 2 or not p.get("name"):
                continue
            if p.get("countrycode") == "CH" and out:        # swisstopo already answered for Switzerland
                continue
            where = ", ".join(dict.fromkeys(v for v in (p.get("city"), p.get("state"), p.get("country")) if v and v != p["name"]))
            out.append(dict(label=p["name"] + (f" ({where})" if where else ""), lat=float(c[1]), lon=float(c[0])))
    except Exception:                               # noqa: BLE001
        failed += 1
    if failed == 2:
        raise OSError("place search unavailable")
    return out or loose


def _plain(s: str) -> str:
    """Lower case without accents, to compare what was typed with a place name."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def run_build(job_id: str, args: list):
    job = JOBS[job_id]
    cmd = cli_cmd(unbuffered=True) + args
    job["cmd"] = " ".join(args)
    job.setdefault("events", [])
    env = dict(os.environ, FPV3D_PROGRESS="1", PYTHONIOENCODING="utf-8")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(APP), env.get("PYTHONPATH")]))  # data folder elsewhere
    try:
        p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", bufsize=1, env=env)
        PROCS[job_id] = p
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
        code = p.wait()
        job["status"] = "cancelled" if job.get("cancel") else "done" if code == 0 else "failed"
        PROCS.pop(job_id, None)
    except Exception as ex:
        job["lines"].append(f"error: {ex}")
        job["status"] = "failed"


PROCS = {}       # job id -> running build process (kept out of JOBS, which is sent as JSON)


def busy_job():
    """The build that is running now, if any: one build at a time (memory, disk and the same files)."""
    return next((j for j in JOBS.values() if j["status"] == "running"), None)


JOBS_LOCK = threading.Lock()


def new_job(name: str, exclusive=True, **extra):
    """Register a background job, or return None when a build is running and this one needs to be alone. The check
    and the registration happen under one lock (two clicks in the same instant start one build), and only the last
    20 finished jobs are kept."""
    with JOBS_LOCK:
        if exclusive and busy_job():
            return None
        done = [k for k, j in JOBS.items() if j["status"] != "running"]
        for k in done[:-20]:
            del JOBS[k]
        jid = uuid.uuid4().hex[:10]
        JOBS[jid] = dict(id=jid, name=name, status="running", lines=[], **extra)
        return jid


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
    write_atomic(out, b.get("csv", ""))
    r = subprocess.run(cli_cmd() + ["--scenes", str(scenes_dir), "--cache", str(cache_dir),
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
                          ".f32": "application/octet-stream", ".webmanifest": "application/manifest+json"}

        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(APP), **kw)       # the pages (viewer/) come with the program

        def translate_path(self, path):
            # /scenes/... is served from the configured scenes folder (default: ./scenes)
            clean = urllib.parse.unquote(urllib.parse.urlparse(path).path)
            if clean.startswith("/scenes/") and ".." not in clean:
                return str(scenes_dir / clean[len("/scenes/"):])
            return super().translate_path(path)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store, must-revalidate")   # always serve fresh files
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")            # the PIN link never leaks to other sites
            self.send_header("Content-Security-Policy", csp())            # only our own scripts run, never inside a frame
            self.send_header("X-Frame-Options", "DENY")
            super().end_headers()

        def _refuse(self, status, msg):
            self._json(dict(error=msg), status)
            return True

        def _host_ok(self) -> bool:
            """On this computer, only requests addressed to 127.0.0.1 / localhost. A website that points its own name
            at 127.0.0.1 ("DNS rebinding") sends its name here and is refused."""
            if not self._local():
                return True                        # other devices: the PIN decides
            host = (self.headers.get("Host") or "").strip().lower()
            name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
            return name in ("127.0.0.1", "localhost", "[::1]", "")

        def _origin_ok(self) -> bool:
            """A request sent by another web page carries that page's address in Origin: it must be Alpline's own."""
            origin = self.headers.get("Origin")
            if origin is None:
                return True                        # not sent by a web page (tests, the launcher, scripts)
            o = urllib.parse.urlparse(origin)
            return o.scheme in ("http", "https") and o.netloc.lower() == (self.headers.get("Host") or "").lower()

        def _static_ok(self, path: str) -> bool:
            """Files served as they are: the pages and the built scenes only (not locations, logs, settings, code)."""
            p = urllib.parse.unquote(path)
            return (p.startswith("/viewer/") or p.startswith("/scenes/") or p in ("/favicon.ico",)) and ".." not in p

        def log_message(self, fmt, *args):   # keep the terminal quiet except for errors
            if args and str(args[1])[:1] in "45":
                super().log_message(fmt, *args)

        # ---------------------------------------------------------------- helpers
        def _local(self) -> bool:
            return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

        def _json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _gzip_ok(self) -> bool:
            """Compress for other devices (the phone over Wi-Fi); on this computer sending is free and compressing
            would only cost time."""
            return not self._local() and "gzip" in (self.headers.get("Accept-Encoding") or "")

        def _bin(self, data: bytes, ctype: str, headers=None):
            enc = None
            if self._gzip_ok() and len(data) > 1024 and not ctype.startswith("image/"):
                data, enc = gzip.compress(data, 5), "gzip"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            if enc:
                self.send_header("Content-Encoding", enc)
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Access-Control-Expose-Headers", "X-Rows, X-Cols, X-Res, X-Enc, X-Base, X-Scale")
            for k, v in (headers or {}).items():
                self.send_header(k, str(v))
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")   # size checked in do_POST

        # ---------------------------------------------------------------- GET
        def _gate(self, u) -> bool:
            """Other devices (the phone) need the PIN shown in the launcher, once: it comes in the QR link as ?k=,
            or typed on the page below, and is then kept in a cookie for a year. True = request answered here."""
            if self._local() or u.path in ("/api/ca.crt", "/favicon.ico", "/viewer/manifest.webmanifest") or u.path.startswith("/viewer/brand/"):
                return False
            pin = SHARE["pin"]
            cookies = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
            if pin and hmac.compare_digest(cookies.get("alp_pin", ""), pin_cookie(pin)):
                return False
            q = urllib.parse.parse_qs(u.query)
            ip = self.client_address[0]
            if PIN_TRIES.get(ip, (0, 0))[1] > time.time():      # too many wrong PINs: wait a minute
                return self._refuse(429, "Too many wrong PINs: wait a minute.")
            if pin and hmac.compare_digest((q.get("k") or [""])[0], pin):   # right PIN in the link: remember it
                rest = urllib.parse.urlencode({k: v[0] for k, v in q.items() if k != "k"})
                self.send_response(302)
                # the cookie holds a token made from the PIN, not the PIN; page scripts can't read it (HttpOnly)
                self.send_header("Set-Cookie", f"alp_pin={pin_cookie(pin)}; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly"
                                 + ("; Secure" if SHARE["https_port"] and self.server.server_address[1] == SHARE["https_port"] else ""))
                self.send_header("Location", u.path + (f"?{rest}" if rest else ""))
                self.end_headers()
                return True
            wrong = bool(q.get("k"))
            if wrong:
                n = PIN_TRIES.get(ip, (0, 0))[0] + 1
                PIN_TRIES[ip] = (0, time.time() + 60) if n >= 10 else (n, 0)
            body = (f"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>{APP_NAME}</title>"
                    "<body style='font:16px system-ui;background:#07090c;color:#f2f5f8;padding:28px'>"
                    f"<h2 style='font-family:monospace'>{APP_NAME.upper()}</h2><p>Type the PIN shown in the {APP_NAME} launcher on the computer "
                    "(status bar, next to the phone address).</p>"
                    f"{'<p style=color:#ff6b6b>Wrong PIN.</p>' if wrong else ''}"
                    "<form method=get>" + "".join(f"<input type=hidden name='{html.escape(k)}' value='{html.escape(v[0])}'>"
                                                  for k, v in q.items() if k != "k") +
                    "<input name=k inputmode=numeric autocomplete=off autofocus "
                    "style='font:24px monospace;width:8em;padding:6px'> "
                    "<button style='font:18px monospace;padding:6px 12px'>open</button></form>").encode()
            self.send_response(401)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if not self._host_ok():
                return self._refuse(403, f"{APP_NAME} only answers requests addressed to 127.0.0.1 or localhost.")
            if self._gate(u):
                return
            if not self._local() and (u.path.endswith("/") or u.path.endswith(".html")):
                sys.stderr.write(f"[phone] {self.client_address[0]} opened {u.path}\n")   # shows it reached the PC
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            try:
                if u.path == "/api/share":       # addresses a phone can use (launcher "share on my network")
                    if not SHARE["on"]:
                        return self._json(dict(shared=False, urls=[]))
                    scheme, p = ("https", SHARE["https_port"]) if SHARE["https_port"] else ("http", SHARE["port"])
                    return self._json(dict(shared=True, https=bool(SHARE["https_port"]), pin=SHARE["pin"] if self._local() else None,
                                           urls=[f"{scheme}://{ip}:{p}/viewer/" for ip in lan_addresses()]))
                if u.path == "/api/ca.crt":      # the private CA to install once on the phone (public, no PIN)
                    from .tlscert import CA_CRT
                    if not CA_CRT.exists():
                        return self._json(dict(error="no certificate yet: share with the phone first"), 404)
                    return self._bin(CA_CRT.read_bytes(), "application/x-x509-ca-cert",
                                     {"Content-Disposition": 'attachment; filename="alpline-ca.crt"'})
                if u.path == "/viewer/manifest.webmanifest" and APP_NAME != "Alpline":   # the installed phone app's name
                    m = json.loads((APP / "viewer" / "manifest.webmanifest").read_text(encoding="utf-8"))
                    m.update(name=APP_NAME, short_name=APP_NAME)
                    return self._json(m)
                if u.path == "/api/mode.js":     # loaded by the pages before anything else: Full or Lite mode
                    from . import mode
                    body = (f'window.FPV3D_MODE = "{mode.current()}";\n'
                            f'window.APP_BRAND = {json.dumps(dict(name=APP_NAME, by=BY))};\n').encode()   # see fpv3d/brand.py
                    self.send_response(200)
                    self.send_header("Content-Type", "text/javascript")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    return self.wfile.write(body)
                if u.path == "/api/battery/packs":
                    from . import battery
                    return self._json(battery.overview())
                if u.path == "/api/battery/flight":
                    from . import battery
                    try:
                        return self._json(battery.load_flight(q.get("id", "")))
                    except (OSError, ValueError):
                        return self._json(dict(error="no battery data for this flight"), 404)
                if u.path == "/api/state":
                    from .trash import list_deleted
                    from . import mode
                    from .terrain import world_inventory
                    return self._json(dict(locations=list_locations(scenes_dir), cache=cache.inventory(),
                                           cache_world=world_inventory(cache.root),
                                           tile_size_m=TILE, deleted=list_deleted()[:10], mode=mode.current()))
                if u.path == "/api/height":
                    lat, lon = float(q["lat"]), float(q["lon"])
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        return self._json(dict(error="lat / lon out of range"), 400)
                    return self._json(place_height(cache, lat, lon))
                if u.path == "/api/search":
                    return self._json(place_search(q.get("q", ""), world=q.get("world") == "1"))
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
                        hdr = {"X-Rows": win.shape[0], "X-Cols": win.shape[1], "X-Res": g["res"]}
                        if q.get("enc") == "d16":           # compact: 0.1 m steps, half the size, compresses well
                            data, base = viewdata.encode_d16(win)
                            return self._bin(data, "application/octet-stream", {**hdr, "X-Enc": "d16", "X-Base": base, "X-Scale": 0.1})
                        return self._bin(win.tobytes(), "application/octet-stream", hdr)
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
            if u.path.startswith("/api/"):
                return self._json(dict(error="not found"), 404)
            if not self._static_ok(u.path):
                return self._json(dict(error="not found"), 404)
            if self._gzip_ok() and u.path.endswith(GZIP_TYPES) and self._send_gzipped(u.path):
                return
            return super().do_GET()

        def _send_gzipped(self, path: str) -> bool:
            """A page or scene file, compressed (kept compressed in memory until the file changes)."""
            f = Path(self.translate_path(path))
            try:
                st = f.stat()
            except OSError:
                return False
            if not f.is_file() or st.st_size < 1024:
                return False
            key = (str(f), st.st_mtime_ns, st.st_size)
            data = GZ_CACHE.get(key)
            if data is None:
                data = gzip.compress(f.read_bytes(), 5)
                with GZ_LOCK:
                    GZ_CACHE[key] = data
                    while sum(len(v) for v in GZ_CACHE.values()) > 150_000_000:      # keep at most ~150 MB
                        GZ_CACHE.pop(next(iter(GZ_CACHE)))
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(str(f)))
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return True

        def do_HEAD(self):
            if not self._host_ok() or not self._static_ok(urllib.parse.urlparse(self.path).path):
                return self._refuse(404, "not found")
            if self._gate(urllib.parse.urlparse(self.path)):
                return
            return super().do_HEAD()

        # ---------------------------------------------------------------- POST
        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            if not self._host_ok():
                return self._refuse(403, f"{APP_NAME} only answers requests addressed to 127.0.0.1 or localhost.")
            # other web pages can't post here: a JSON body needs a browser "preflight" that this server never
            # allows, and a page's Origin must be Alpline's own address
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                return self._refuse(415, "requests must be JSON (Content-Type: application/json)")
            if not self._origin_ok():
                return self._refuse(403, "requests from other web pages are not allowed")
            if self._gate(u):
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                self.close_connection = True                    # the unread body must not be taken as the next request
                return self._json(dict(error="request too large" if n > 0 else "bad Content-Length"), 413 if n > 0 else 400)
            # shared on the network (phone): other devices may look, fly and build, but not delete or rename
            if u.path in LOCAL_ONLY and not self._local():
                return self._json(dict(error=f"Deleting and renaming only work on the computer running {APP_NAME}."), 403)
            try:
                b = self._body()
                m = re.match(r"^/api/jobs/([\w-]+)/cancel$", u.path)
                if m:
                    return self._post_job_cancel(b, u, m)
                handler = self.POST.get(u.path)
                if handler:
                    return getattr(self, handler)(b, u)
            except FileExistsError as ex:
                return self._json(dict(error=str(ex), exists=True), 409)
            except (KeyError, ValueError) as ex:
                return self._json(dict(error=str(ex)), 400)
            except Exception as ex:
                record_exception(f"server {u.path}", ex)
                return self._json(dict(error=str(ex)), 500)
            self._json(dict(error="not found"), 404)

        def _post_job_cancel(self, b, u, m):   # stop a running build (the map page's [cancel])
            job, p = JOBS.get(m.group(1)), PROCS.get(m.group(1))
            if not job or job["status"] != "running" or p is None:
                return self._json(dict(error="no such running build"), 404)
            job["cancel"] = True
            job["lines"].append("cancelled by the user")
            p.terminate()
            return self._json(dict(ok=True))

        def _post_locations(self, b, u):
            out = write_location(
                b["name"], b.get("title") or b["name"], tuple(b["center"]), tuple(b.get("pilot") or b["center"]),
                float(b.get("half_size_m", 2500)), float(b.get("resolution_m", 5)), b.get("surface", "dtm"),
                float(b.get("antenna_height_m", 1.8)), b.get("radio_from") or None, bool(b.get("overwrite")),
                b.get("corridor") or None)
            return self._json(dict(ok=True, file=f"locations/{out.name}", name=out.stem))

        def _post_rename(self, b, u):
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

        def _post_delete_restore(self, b, u):
            from . import trash
            if any(j["status"] == "running" for j in JOBS.values()):
                return self._json(dict(error="wait for the running build to finish"), 409)
            try:
                if u.path == "/api/delete":
                    return self._json(dict(ok=True, **trash.delete_location(b["name"], scenes_dir, log=lambda *_: None)))
                return self._json(dict(ok=True, **trash.restore_location(b["folder"], scenes_dir, log=lambda *_: None)))
            except (FileNotFoundError, FileExistsError, KeyError, OSError) as ex:
                return self._json(dict(error=str(ex)), 400)

        def _post_live_start(self, b, u):
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

        def _post_live_stop(self, b, u):
            from .live import LINK
            LINK.stop()
            st = LINK.snapshot(10 ** 9)
            out = dict(ok=True, gps_count=st["gps_count"], csv=st["csv"])
            if b.get("save") and st["csv"] and st["gps_count"] >= 10 and st.get("scene"):
                loc = location_file_for_scene(st["scene"])
                if loc is not None:
                    r = subprocess.run(cli_cmd() + ["--scenes", str(scenes_dir), "--cache", str(cache_dir),
                                        "add-log", str(loc.relative_to(ROOT)), st["csv"]],
                                       cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
                    stem = Path(st["csv"]).stem
                    if r.returncode == 0 and (scenes_dir / st["scene"] / "tracks" / f"{stem}.json").exists():
                        out.update(track=stem, file=f"tracks/{stem}.json")
                    else:
                        out["warning"] = "saved the CSV, but adding it to the scene failed: " + (r.stderr or r.stdout)[-300:]
            return self._json(out)

        def _post_battery(self, b, u):   # packs: create / change, which pack flew, charger check
            from . import battery
            act = u.path.rsplit("/", 1)[1]
            if act == "pack":
                return self._json(dict(ok=True, pack=battery.save_pack(b)))
            if act == "assign":
                battery.assign(b["flights"], b.get("pack"))
                return self._json(dict(ok=True))
            if act == "flight-date":
                battery.set_when(b["flight"], b.get("when"))
                return self._json(dict(ok=True))
            if act == "charger":
                battery.set_charged(b["flight"], b.get("mah"))
                return self._json(dict(ok=True))
            if act == "note":
                return self._json(dict(ok=True, note=battery.add_note(b["pack"], b["kind"], b.get("text", ""),
                                                                      b.get("when"), b.get("flight"))))
            if act == "delete-note":
                battery.delete_note(b["id"])
                return self._json(dict(ok=True))
            if act == "delete-pack":
                battery.delete_pack(b["id"])
                return self._json(dict(ok=True))

        def _post_client_error(self, b, u):   # the pages report their own errors (theme.js) to logs/errors.txt
            now = time.time()
            CLIENT_ERRORS[:] = [t for t in CLIENT_ERRORS if now - t < 60]
            if len(CLIENT_ERRORS) >= 30:                 # a page stuck in a loop must not fill the disk
                return self._json(dict(ok=False, error="too many reports"), 429)
            CLIENT_ERRORS.append(now)
            who = "viewer" if self._local() else "phone"
            record(f"{who} {str(b.get('page', ''))[:80]}", str(b.get("message", ""))[:500], str(b.get("stack", ""))[:4000])
            return self._json(dict(ok=True))

        def _post_simtrack(self, b, u):
            return self._json(*save_sim_track(scenes_dir, cache_dir, b))

        def _post_links(self, b, u):
            # save edited radio settings into the location file, then rebuild the scene's shadows
            from .locations import patch_links
            scene = b.get("scene", "")
            loc = location_file_for_scene(scene) if re.match(r"^[\w-]+$", scene) else None
            if loc is None:
                return self._json(dict(error=f"no location file for scene '{scene}'"), 400)
            if busy_job():
                return self._json(dict(error=f"another build is running ({busy_job()['name']}): wait for it or cancel it"), 409)
            changed = patch_links(loc, b.get("links") or [])
            args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "build",
                    str(loc.relative_to(ROOT)), "--reuse-terrain"]
            jid = new_job(scene)
            if jid is None:
                return self._json(dict(error="another build has just started: wait for it to finish"), 409)
            JOBS[jid]["lines"] += [f"saved to {loc.name}: " + (", ".join(changed) or "no change")]
            threading.Thread(target=run_build, args=(jid, args), daemon=True).start()
            return self._json(dict(job=jid, changed=changed, file=loc.name))

        def _post_refresh_all(self, b, u):
            if busy_job():
                return self._json(dict(error=f"another build is running ({busy_job()['name']}): wait for it or cancel it"), 409)
            args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "refresh-all"]
            if b.get("mode") == "buildings":
                args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "buildings"]
            elif b.get("mode") == "zones":
                args.append("--zones-only")
            if b.get("missing"):
                args.append("--missing")
            jid = new_job("(all scenes)")
            if jid is None:
                return self._json(dict(error="another build has just started: wait for it to finish"), 409)
            threading.Thread(target=run_build, args=(jid, args), daemon=True).start()
            return self._json(dict(job=jid))

        def _post_zones(self, b, u):   # fresh no-fly zones for one scene (viewer: [refresh zones])
            scene = b.get("scene", "")
            loc = location_file_for_scene(scene) if re.match(r"^[\w-]+$", scene) else None
            if loc is None:
                return self._json(dict(error="no location file for this scene"), 400)
            if busy_job():
                return self._json(dict(error=f"another build is running ({busy_job()['name']}): try again when it is done"), 409)
            args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "zones", f"locations/{loc.name}"]
            jid = new_job(loc.stem)
            if jid is None:
                return self._json(dict(error="another build has just started: wait for it to finish"), 409)
            threading.Thread(target=run_build, args=(jid, args), daemon=True).start()
            return self._json(dict(job=jid))

        def _post_pilot(self, b, u):   # live flight: move the pilot point to the takeoff point, rebuild
            from .locations import set_pilot
            scene = b.get("scene", "")
            loc = location_file_for_scene(scene) if re.match(r"^[\w-]+$", scene) else None
            if loc is None:
                return self._json(dict(error="no location file for this scene"), 400)
            lat, lon = float(b["lat"]), float(b["lon"])
            if not (45.5 < lat < 48.0 and 5.8 < lon < 10.7):
                return self._json(dict(error="position outside Switzerland"), 400)
            if busy_job():
                return self._json(dict(error=f"another build is running ({busy_job()['name']}): wait for it to finish"), 409)
            set_pilot(loc, lat, lon)
            args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "build", f"locations/{loc.name}"]
            jid = new_job(loc.stem)
            if jid is None:
                return self._json(dict(error="another build has just started: wait for it to finish"), 409)
            threading.Thread(target=run_build, args=(jid, args), daemon=True).start()
            return self._json(dict(job=jid))

        def _post_blackbox(self, b, u):   # flights tab: [download from the drone]
            from .live import LINK
            if busy_job():
                return self._json(dict(error=f"another job is running ({busy_job()['name']}): wait for it to finish"), 409)
            args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "blackbox"]
            scene = b.get("scene") or ""
            if b.get("only_here") and re.match(r"^[\w-]+$", scene):
                args += ["--location", scene]
            if LINK.thread and LINK.thread.is_alive() and LINK.state.get("port"):
                args += ["--skip", LINK.state["port"]]      # the radio of a running live flight
            jid = new_job("blackbox", kind="blackbox")
            if jid is None:
                return self._json(dict(error="another build has just started: wait for it to finish"), 409)
            threading.Thread(target=run_build, args=(jid, args), daemon=True).start()
            return self._json(dict(job=jid))

        def _post_battery_rescan(self, b, u):   # packs page: [read battery from saved logs]
            if busy_job():
                return self._json(dict(error=f"another job is running ({busy_job()['name']}): wait for it to finish"), 409)
            jid = new_job("saved blackbox logs", kind="blackbox")
            if jid is None:
                return self._json(dict(error="another build has just started: wait for it to finish"), 409)
            args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "blackbox", "--saved"]
            threading.Thread(target=run_build, args=(jid, args), daemon=True).start()
            return self._json(dict(job=jid))

        def _post_build(self, b, u):
            name = b["name"]
            if not re.match(r"^[\w-]+$", name) or not (ROOT / "locations" / f"{name}.yaml").exists():
                return self._json(dict(error="unknown location"), 400)
            if busy_job():
                return self._json(dict(error=f"another build is running ({busy_job()['name']}): wait for it or cancel it"), 409)
            args = ["--scenes", str(scenes_dir), "--cache", str(cache_dir), "build", f"locations/{name}.yaml"]
            if b.get("resolution"):
                args += ["--resolution", str(float(b["resolution"]))]
            jid = new_job(name)
            if jid is None:
                return self._json(dict(error="another build has just started: wait for it to finish"), 409)
            threading.Thread(target=run_build, args=(jid, args), daemon=True).start()
            return self._json(dict(job=jid))

        # address -> handler. Other devices (the phone) may look, fly and build; the LOCAL addresses (delete, rename)
        # only answer this computer. A new address = one method above + one line here.
        POST = {
            "/api/locations": "_post_locations",
            "/api/rename": "_post_rename",
            "/api/delete": "_post_delete_restore",
            "/api/restore": "_post_delete_restore",
            "/api/live/start": "_post_live_start",
            "/api/live/stop": "_post_live_stop",
            "/api/client-error": "_post_client_error",
            "/api/simtrack": "_post_simtrack",
            "/api/links": "_post_links",
            "/api/refresh-all": "_post_refresh_all",
            "/api/zones": "_post_zones",
            "/api/pilot": "_post_pilot",
            "/api/blackbox": "_post_blackbox",
            "/api/build": "_post_build",
            "/api/battery/rescan": "_post_battery_rescan",
            "/api/battery/pack": "_post_battery",
            "/api/battery/assign": "_post_battery",
            "/api/battery/charger": "_post_battery",
            "/api/battery/flight-date": "_post_battery",
            "/api/battery/note": "_post_battery",
            "/api/battery/delete-note": "_post_battery",
            "/api/battery/delete-pack": "_post_battery",
        }

    return Handler


LOCAL_ONLY = ("/api/delete", "/api/restore", "/api/rename", "/api/battery/delete-pack", "/api/battery/delete-note")
CLIENT_ERRORS: list = []        # times of the pages' error reports in the last minute
MAX_BODY = 20_000_000           # largest request body: a long training flight's CSV fits
_CSP: dict = {}                 # (newest page time) -> header


def csp() -> str:
    """Content-Security-Policy: scripts only from this server (plus the few inline blocks of our own pages, by hash),
    map tiles from swisstopo / OpenStreetMap / EOX (satellite), never inside another site's frame. Recomputed when a page changes."""
    pages = sorted((APP / "viewer").rglob("*.html"))
    key = max((f.stat().st_mtime_ns for f in pages), default=0)
    if key not in _CSP:
        hashes = set()
        for f in pages:
            for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", f.read_text(encoding="utf-8"), re.S):
                hashes.add("'sha256-" + base64.b64encode(hashlib.sha256(m.group(1).encode()).digest()).decode() + "'")
        tiles = "https://wmts.geo.admin.ch https://tile.openstreetmap.org https://tiles.maps.eox.at"
        _CSP.clear()
        _CSP[key] = "; ".join([
            "default-src 'self'", "script-src 'self' " + " ".join(sorted(hashes)),
            "style-src 'self' 'unsafe-inline'", f"img-src 'self' data: blob: {tiles}", "media-src 'self' blob:",
            "connect-src 'self'", "worker-src 'self'", "font-src 'self' data:", "object-src 'none'",
            "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'"])
    return _CSP[key]
GZIP_TYPES = (".json", ".bin", ".f32", ".js", ".css", ".html", ".svg", ".geojson", ".webmanifest")   # not png/jpg: already packed
GZ_CACHE: dict = {}             # (file, mtime, size) -> compressed bytes, for the phone
GZ_LOCK = threading.Lock()
PIN_TRIES: dict = {}            # phone address -> (wrong PINs in a row, locked until)


SHARE = {"on": False, "pin": None, "port": None, "https_port": None}   # set by serve(lan=True)
_COOKIE_KEY = secrets.token_bytes(32)                 # new at every start: old cookies stop working with the old PIN


def pin_cookie(pin: str) -> str:
    """What the phone's cookie holds once the PIN was typed: a token only this running server can make from it."""
    return hmac.new(_COOKIE_KEY, str(pin).encode(), hashlib.sha256).hexdigest()[:40]


def serve(port: int, scenes_dir: Path, cache_dir: Path, open_path: str = "/viewer/", open_browser=True, lan=False):
    import webbrowser
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    host = "0.0.0.0" if lan else "127.0.0.1"
    handler = make_handler(scenes_dir, cache_dir)
    with socketserver.ThreadingTCPServer((host, port), handler) as httpd:
        url = f"http://127.0.0.1:{port}{open_path}"
        print(f"fpv3d: {url}   (map: http://127.0.0.1:{port}/viewer/map.html)   Ctrl+C to stop")
        if lan:
            import secrets
            pin = os.environ.get("FPV3D_PIN") or f"{secrets.randbelow(10 ** 6):06d}"
            SHARE.update(on=True, pin=pin, port=port)
            scheme, p = "http", port
            from . import tlscert
            if tlscert.available():                # https for the phone on port + 443 (8000 -> 8443)
                try:
                    import ssl
                    cert, key = tlscert.ensure(lan_addresses())
                    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    ctx.load_cert_chain(cert, key)
                    hs = socketserver.ThreadingTCPServer((host, port + 443), handler)
                    hs.socket = ctx.wrap_socket(hs.socket, server_side=True)
                    threading.Thread(target=hs.serve_forever, daemon=True).start()
                    scheme, p = "https", port + 443
                    SHARE["https_port"] = p
                except Exception as ex:
                    print(f"       https not available ({ex}); the phone uses http")
            else:
                print("       https needs the 'cryptography' library (pip install -r requirements.txt); the phone uses http")
            for ip in lan_addresses():
                print(f"       on your phone (same Wi-Fi / hotspot): {scheme}://{ip}:{p}/viewer/   PIN {pin}")
        if open_browser:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
