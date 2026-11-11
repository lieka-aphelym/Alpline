"""Safety of the local server: other web pages, other devices, file paths.   python -m pytest tests/test_security.py

The server runs on this computer; the risks are (1) a website open in your browser talking to it behind your back,
(2) another device on the Wi-Fi when sharing with the phone, (3) a request reaching files outside the pages."""
import http.client
import json
import socketserver
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from test_server import _TMP, _handler, req  # noqa: E402
from fpv3d import server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

PHONE = {}


def phone_port():
    """The real handler, but every request counts as coming from another device (the phone)."""
    if "port" not in PHONE:
        h = _handler()

        class Phone(h):
            def _local(self):
                return False
        srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Phone)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        PHONE["port"] = srv.server_address[1]
    return PHONE["port"]


def phone(method, path, body=b"", headers=None):
    c = http.client.HTTPConnection("127.0.0.1", phone_port(), timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    out = r.status, r.read()
    c.close()
    return out


def make_location(name="099_target"):
    """A location file + built scene that an attack would try to delete."""
    loc = _TMP / "locations"
    loc.mkdir(parents=True, exist_ok=True)
    f = loc / f"{name}.yaml"
    f.write_text(f"name: {name}\ncenter: {{lat: 46.5, lon: 7.5}}\n", encoding="utf-8")
    sd = _TMP / "scenes" / name
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "scene.json").write_text(json.dumps({"name": name, "tracks": []}), encoding="utf-8")
    return sd


# ------------------------------------------------------------ other web pages (cross-site requests)
def test_foreign_page_cannot_post():
    """A website can make your browser send a form or a fetch to 127.0.0.1. It never gets through."""
    sd = make_location()
    evil = {"Origin": "https://evil.example"}
    st, _, _ = req("POST", "/api/delete", {"name": "099_target"}, headers=evil)
    assert st == 403, st
    # an HTML form can only send text/plain or form data (no preflight): refused before anything runs
    st, _, _ = req("POST", "/api/delete", b'{"name":"099_target"}', headers={"Content-Type": "text/plain"})
    assert st == 415, st
    st, _, _ = req("POST", "/api/delete", b"name=099_target", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert st == 415, st
    st, _, _ = req("POST", "/api/rename", {"kind": "location", "old": "099_target", "new": "x"}, headers={"Origin": "null"})
    assert st == 403, st
    assert (sd / "scene.json").exists()                     # nothing was deleted


def test_own_page_can_post():
    """Alpline's own pages send their address as Origin: allowed."""
    from test_server import _server
    p = _server()
    st, _, _ = req("POST", "/api/live/stop", {}, headers={"Origin": f"http://127.0.0.1:{p}"})
    assert st == 200, st
    st, _, _ = req("POST", "/api/live/stop", {})            # no Origin (launcher, scripts): allowed
    assert st == 200, st


def test_dns_rebinding_refused():
    """A website pointing its own name at 127.0.0.1 sends that name in Host: refused (GET and POST)."""
    from test_server import _server
    p = _server()
    for method, path in (("GET", "/api/state"), ("GET", "/viewer/"), ("POST", "/api/live/stop")):
        st, _, _ = req(method, path, {} if method == "POST" else None, headers={"Host": f"evil.example:{p}"})
        assert st == 403, (method, path, st)
    assert req("GET", "/api/state", headers={"Host": f"localhost:{p}"})[0] == 200
    assert req("GET", "/api/state", headers={"Host": f"127.0.0.1:{p}"})[0] == 200


# ------------------------------------------------------------ files outside the pages
def test_only_pages_and_scenes_are_served():
    for path in ("/launcher.json", "/locations/001_test.yaml", "/logs/server.log", "/fpv3d/server.py", "/requirements.txt",
                 "/cache/", "/.git/config", "/tests/test_security.py", "/scenes/../launcher.json",
                 "/scenes/..%2flauncher.json", "/viewer/../launcher.json", "/viewer/%2e%2e/launcher.json"):
        st, _, _ = req("GET", path)
        assert st == 404, (path, st)
    assert req("GET", "/viewer/")[0] == 200
    make_location("098_served")
    assert req("GET", "/scenes/098_served/scene.json")[0] == 200


def test_names_are_checked():
    """Scene, track and location names: letters, digits, _ and - only, everywhere."""
    for body in ({"scene": "../../etc", "lat": 46.5, "lon": 7.5}, {"scene": "a/b", "lat": 46.5, "lon": 7.5}):
        assert req("POST", "/api/pilot", body)[0] == 400
    assert req("POST", "/api/live/start", {"scene": "..\\x", "source": "replay"})[0] == 400
    assert req("POST", "/api/live/start", {"scene": "098_served", "source": "replay", "track": "../../launcher.json"})[0] == 400
    assert req("GET", "/api/terrain?scene=../098_served")[0] == 404
    assert req("POST", "/api/simtrack", {"scene": "../x", "csv": "a"})[0] == 400


def test_bad_json_is_a_clean_error():
    st, body, _ = req("POST", "/api/build", b"{not json")
    assert st == 400 and b"error" in body


# ------------------------------------------------------------ other devices (phone sharing)
def test_phone_needs_pin_everywhere():
    old = dict(server.SHARE)
    try:
        server.SHARE.update(on=True, pin="424242")
        for path in ("/viewer/", "/api/state", "/scenes/098_served/scene.json"):
            assert phone("GET", path)[0] == 401, path
        st, _ = phone("POST", "/api/build", b'{"name":"x"}', {"Content-Type": "application/json"})
        assert st == 401
        ok = {"Cookie": f"alp_pin={server.pin_cookie('424242')}"}
        assert phone("GET", "/api/state", headers=ok)[0] == 200
        st, _ = phone("POST", "/api/delete", b'{"name":"099_target"}', {**ok, "Content-Type": "application/json"})
        assert st == 403                                    # deleting only on the computer
        st, body = phone("GET", "/api/share", headers=ok)
        assert json.loads(body).get("pin") is None          # the phone never learns the PIN from the server
    finally:
        server.SHARE.clear(); server.SHARE.update(old)


def test_pin_guessing_is_slowed_down():
    old = dict(server.SHARE)
    try:
        server.SHARE.update(on=True, pin="424242")
        server.PIN_TRIES.clear()
        for i in range(10):
            phone("GET", f"/viewer/?k={i:06d}")
        assert phone("GET", "/viewer/?k=424242")[0] == 429  # locked for a minute, even with the right PIN
        server.PIN_TRIES.clear()
        assert phone("GET", "/viewer/?k=424242")[0] == 302  # after the minute: fine
    finally:
        server.SHARE.clear(); server.SHARE.update(old); server.PIN_TRIES.clear()


def test_safety_headers():
    _, _, h = req("GET", "/viewer/")
    assert h.get("x-content-type-options") == "nosniff" and h.get("referrer-policy") == "no-referrer"
    assert "access-control-allow-origin" not in h          # no page elsewhere may read the answers
    csp = h.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp and h.get("x-frame-options") == "DENY"   # no other site can frame the viewer
    script = next(p for p in csp.split(";") if p.strip().startswith("script-src"))
    assert "'unsafe-inline'" not in script and "'unsafe-eval'" not in script


def test_inline_scripts_are_allowed_by_hash():
    """Every inline <script> of our pages is in the policy (else the page would break), and no onclick= etc."""
    import base64
    import hashlib
    import re
    _, _, h = req("GET", "/viewer/")
    csp = h["content-security-policy"]
    pages = sorted((ROOT / "viewer").rglob("*.html"))
    assert pages
    for f in pages:
        txt = f.read_text(encoding="utf-8")
        assert not re.search(r"<[a-z][^>]*\son[a-z]+\s*=", txt, re.I), f"{f.name}: inline event handler"
        for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", txt, re.S):
            hsh = base64.b64encode(hashlib.sha256(m.group(1).encode()).digest()).decode()
            assert f"'sha256-{hsh}'" in csp, f"{f.name}: inline script not in the policy"


def test_request_size_is_limited():
    for length, want in (("-1", 400), ("abc", 400), (str(200_000_000), 413)):
        st, raw, _ = req("POST", "/api/simtrack", body=b"", headers={"Content-Length": length})
        assert st == want, (length, st, raw)
    assert req("GET", "/viewer/")[0] == 200            # the server is still fine afterwards


def test_names_are_escaped_in_pages():
    """Names from files and the internet (OSM buildings, zones, locations, flights, serial ports) are put in the page
    as text: every innerHTML / tooltip template that shows one goes through esc()."""
    import re
    risky = re.compile(r"\$\{(?![^}]*(esc\(|===|!\w))[^}]*\b(name|title|file|description|device|error)\b[^}]*\}")   # not tests
    bad = []
    for f in sorted((ROOT / "viewer" / "js").rglob("*.js")):
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not risky.search(line):
                continue
            ctx = " ".join(lines[max(0, i - 3): i + 1])                   # the template may start a few lines up
            safe_use = re.search(r"textContent|localStorage|fetch\(|encodeURIComponent|CSS\.escape|\.download", line)
            if re.search(r"innerHTML|bindTooltip|locMsg\(", ctx) and not safe_use:
                bad.append(f"{f.name}:{i + 1}: {line.strip()[:110]}")
    assert not bad, "\n".join(bad)


def test_esc_in_javascript():
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("  (Node not installed: skipped)")
        return
    js = (f"import {{ esc }} from {json.dumps((ROOT / 'viewer' / 'js' / 'core' / 'esc.js').as_uri())};"
          "process.stdout.write(esc(`<img src=x onerror=\"alert(1)\"> & 'q'`) + '|' + esc(null) + '|' + esc(5));")
    out = subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30, check=True).stdout
    assert out == "&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; &#39;q&#39;||5", out


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  ok    {name}")
            except Exception as ex:
                fails += 1; print(f"  FAIL  {name}: {ex!r}")
    sys.exit(1 if fails else 0)
