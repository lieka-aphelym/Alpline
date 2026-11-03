"""Server and safety checks (no internet, no browser):  python tests/test_server.py   (or python -m pytest tests)
Starts the real request handler on a free local port with an empty scenes folder."""
import http.client
import json
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fpv3d import buildlock, server  # noqa: E402
from fpv3d.locations import set_pilot  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="alpline_test_"))
_SRV = None


def _handler():
    h = server.make_handler(_TMP / "scenes", _TMP / "cache")
    h.log_message = lambda *a: None                                         # refused requests are expected here
    return h


def _server():
    global _SRV
    if _SRV is None:
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        _SRV = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _handler())
        _SRV.daemon_threads = True
        threading.Thread(target=_SRV.serve_forever, daemon=True).start()
    return _SRV.server_address[1]


def req(method, path, body=None, headers=None, host="127.0.0.1"):
    c = http.client.HTTPConnection(host, _server(), timeout=10)
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    c.request(method, path, body=data, headers={"Content-Type": "application/json", **(headers or {})})
    r = c.getresponse()
    out = r.status, r.read(), {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return out


def jreq(method, path, body=None):
    st, raw, _ = req(method, path, body)
    return st, json.loads(raw or b"{}")


# ------------------------------------------------------------ pages and API
def test_pages_load():
    for p in ("/viewer/", "/viewer/map.html", "/viewer/share.html", "/viewer/test/index.html", "/viewer/env.js", "/viewer/app.js"):
        st, body, h = req("GET", p)
        assert st == 200, (p, st)
        if p.endswith(".js"):
            assert h["content-type"].startswith("text/javascript"), (p, h["content-type"])


def test_mode_js():
    st, body, _ = req("GET", "/api/mode.js")
    assert st == 200 and b"FPV3D_MODE" in body


def test_bad_requests_are_refused():
    assert jreq("POST", "/api/build", {"name": "../evil"})[0] == 400
    assert jreq("POST", "/api/build", {"name": "does_not_exist"})[0] == 400
    assert jreq("POST", "/api/build", {})[0] == 400                          # missing name
    assert jreq("POST", "/api/pilot", {"scene": "nope", "lat": 46.5, "lon": 7.5})[0] == 400
    assert jreq("POST", "/api/zones", {"scene": "../x"})[0] == 400
    assert jreq("POST", "/api/jobs/unknown/cancel")[0] == 404
    assert jreq("POST", "/api/no_such_thing")[0] == 404
    assert jreq("GET", "/api/jobs/unknown")[0] in (404, 400)


def test_request_size_limit():
    st, _, _ = req("POST", "/api/simtrack", b"{}", headers={"Content-Length": str(30_000_000)})
    assert st == 413


def test_pin_for_other_devices():
    """A device that is not this computer needs the PIN; this computer never does."""
    ips = server.lan_addresses()
    ip = ips[0] if ips else None
    old = dict(server.SHARE)
    srv = None
    try:
        server.SHARE.update(on=True, pin="123456")
        assert req("GET", "/viewer/")[0] == 200                              # local: no PIN
        if not ip:
            return
        srv = socketserver.ThreadingTCPServer((ip, 0), _handler())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def get(path, headers=None):
            c = http.client.HTTPConnection(ip, port, timeout=5)
            c.request("GET", path, headers=headers or {})
            r = c.getresponse(); r.read(); c.close()
            return r.status, {k.lower(): v for k, v in r.getheaders()}
        assert get("/viewer/?scene=x")[0] == 401                             # no PIN: the PIN form
        assert get("/viewer/?k=000000")[0] == 401                            # wrong PIN
        st, h = get("/viewer/?scene=x&k=123456")                             # right PIN: cookie + clean address
        assert st == 302 and "alp_pin=123456" in h.get("set-cookie", "") and h["location"] == "/viewer/?scene=x"
        assert get("/viewer/", {"Cookie": "alp_pin=123456"})[0] == 200
        assert get("/api/ca.crt")[0] in (200, 404)                           # the CA is public (404 = no https set up)
        c = http.client.HTTPConnection(ip, port, timeout=5)                  # deleting / renaming: only on the computer
        c.request("POST", "/api/delete", body=b'{"name":"x"}', headers={"Cookie": "alp_pin=123456", "Content-Type": "application/json"})
        assert c.getresponse().status == 403
        c.close()
    except OSError:
        pass                                                                 # no usable network address on this PC
    finally:
        server.SHARE.clear(); server.SHARE.update(old)
        if srv:
            srv.shutdown(); srv.server_close()


# ------------------------------------------------------------ safety helpers
def test_one_build_per_location():
    scenes = _TMP / "lock"
    with buildlock.scene_lock(scenes, "001_test"):
        try:
            with buildlock.scene_lock(scenes, "001_test"):
                raise AssertionError("second build of the same location was allowed")
        except buildlock.Busy:
            pass
        with buildlock.scene_lock(scenes, "002_other"):                    # another location: fine
            pass
    with buildlock.scene_lock(scenes, "001_test"):                         # released after the build
        pass


def test_set_pilot_keeps_comments():
    p = _TMP / "loc.yaml"
    p.write_text("name: t   # my field\ncenter: {lat: 46.5, lon: 7.5}\npilot:\n  lat: 46.0   # old\n  lon: 7.0\n"
                 "  antenna_height_m: 2.5   # tripod\nlinks: []\n", encoding="utf-8")
    set_pilot(p, 46.512345, 7.498765)
    t = p.read_text(encoding="utf-8")
    assert "lat: 46.512345" in t and "lon: 7.498765" in t and "46.0" not in t
    assert "# my field" in t and "antenna_height_m: 2.5   # tripod" in t and "links: []" in t
    p.write_text("name: t\ncenter: {lat: 46.5, lon: 7.5}\npilot: {lat: 46.0, lon: 7.0}\n", encoding="utf-8")
    set_pilot(p, 46.6, 7.6)
    import yaml
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert abs(d["pilot"]["lat"] - 46.6) < 1e-9 and abs(d["pilot"]["lon"] - 7.6) < 1e-9


def test_size_estimate():
    class G: rows, cols = 2000, 3000
    class T: resolution_m, surface = 1.0, "dsm"
    class Cfg:
        terrain = T
        def grid(self, res): return G
    e = buildlock.estimate(Cfg())
    assert e["cells"] == 6_000_000 and e["scene_mb"] == round(6e6 * 4 / 1e6 * 2 + 5, 1)
    assert abs(e["ram_gb"] - 6e6 * 4 / 1e6 * buildlock.RAM_FACTOR / 1000) < 0.01


def test_cache_prune_keeps_used_tiles():
    from fpv3d.tilecache import TileCache
    root = _TMP / "cache_p"
    c = TileCache(root)
    d = root / "ch.swisstopo.swissalti3d"; d.mkdir(parents=True)
    keep = d / "swissalti3d_2021_2600-1200_2_2056_5728.tif"; drop = d / "swissalti3d_2021_2700-1100_2_2056_5728.tif"
    for f in (keep, drop):
        f.write_bytes(b"x" * 100)
    assert c.prune({"2600-1200"}, dry_run=True) == (1, 100) and drop.exists()   # dry run deletes nothing
    assert c.prune({"2600-1200"}, dry_run=False) == (1, 100)
    assert keep.exists() and not drop.exists()


def test_https_certificate():
    from fpv3d import tlscert
    if not tlscert.available():
        print("        (skipped: the cryptography package is not installed; phones use http)")
        return
    d = _TMP / "tls"
    tlscert.DIR = d
    tlscert.CA_CRT, tlscert.CA_KEY = d / "alpline-ca.crt", d / "ca.key"
    tlscert.SRV_CRT, tlscert.SRV_KEY, tlscert.SRV_META = d / "server.crt", d / "server.key", d / "server.json"
    crt, key = tlscert.ensure(["192.168.1.20"])
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(Path(crt).read_bytes())
    ips = [str(i) for i in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)]
    assert "192.168.1.20" in ips and "127.0.0.1" in ips
    ca1 = tlscert.CA_CRT.read_bytes()
    tlscert.ensure(["192.168.1.21"])                                         # new address: new server cert, same CA
    assert tlscert.CA_CRT.read_bytes() == ca1


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  ok    {name}")
            except Exception as ex:
                fails += 1; print(f"  FAIL  {name}: {ex!r}")
    print("server checks:", "all passed" if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
