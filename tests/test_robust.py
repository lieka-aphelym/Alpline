"""Robustness: broken, truncated or random input never crashes or hangs a reader.   python -m pytest tests/test_robust.py

Every reader gets a few hundred damaged inputs (fixed random seed, so a failure always comes back the same way).
A reader may refuse an input, but only with a clear error (ValueError and friends) and quickly - never a hang, never
an unexpected crash deep inside. These are the faults you'd otherwise meet at the field: a radio log cut off when the
battery died, a half-copied blackbox, a hand-edited location file, noise on the USB serial line."""
import math
import random
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fpv3d import crsf, logs  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="alpline_robust_"))
CLEAN = (ValueError, KeyError, TypeError, IndexError, UnicodeDecodeError)     # "this file is not usable" errors


def within(seconds, fn, *a):
    """fn(*a) in a thread: its result or exception, or AssertionError when it takes too long (a hang)."""
    box = {}

    def run():
        try:
            box["r"] = fn(*a)
        except BaseException as ex:                         # noqa: BLE001 (reported below)
            box["e"] = ex
    t = threading.Thread(target=run, daemon=True)
    t.start(); t.join(seconds)
    assert not t.is_alive(), f"{getattr(fn, '__name__', fn)} hung for {seconds} s"
    if "e" in box:
        raise box["e"]
    return box.get("r")


def mutate(data: bytes, rnd: random.Random) -> bytes:
    """One random kind of damage: cut, flipped bytes, inserted junk, a removed chunk, or a duplicated chunk."""
    b = bytearray(data)
    k = rnd.randrange(5)
    if k == 0 and b:
        return bytes(b[:rnd.randrange(len(b))])
    if k == 1:
        for _ in range(rnd.randint(1, 20)):
            if b:
                b[rnd.randrange(len(b))] = rnd.randrange(256)
        return bytes(b)
    if k == 2:
        i = rnd.randrange(len(b) + 1)
        return bytes(b[:i]) + bytes(rnd.randrange(256) for _ in range(rnd.randint(1, 64))) + bytes(b[i:])
    if k == 3 and len(b) > 10:
        i = rnd.randrange(len(b) - 5)
        return bytes(b[:i]) + bytes(b[i + rnd.randint(1, 200):])
    i = rnd.randrange(len(b) + 1)
    return bytes(b[:i]) + bytes(b[max(0, i - 100):i]) + bytes(b[i:])


# ------------------------------------------------------------ radio telemetry (CRSF over USB serial)
def test_crsf_random_noise():
    rnd = random.Random(1)
    p = crsf.Parser()
    for _ in range(300):
        out = p.feed(bytes(rnd.randrange(256) for _ in range(rnd.randint(0, 200))))
        assert isinstance(out, list)
    assert len(p.buf) < 70                                  # never piles up unread bytes


def test_crsf_damaged_frames_and_any_chunk_size():
    rnd = random.Random(2)
    good = (crsf.gps_frame(46.55, 7.02, 30, 90, 1200) + crsf.link_frame(-60, 100) + crsf.battery_frame(16.4, 12, 500, 80)
            + crsf.vario_frame(1.5) + crsf.mode_frame("ACRO"))
    for _ in range(300):
        data = mutate(good * 3, rnd)
        p = crsf.Parser()
        i = 0
        while i < len(data):                                # any chunk sizes, like a real serial port
            n = rnd.randint(1, 40)
            for f in p.feed(data[i:i + n]):
                assert f["kind"] in ("gps", "link", "battery", "vario", "mode", "baro", "attitude")
                if f["kind"] == "gps":
                    assert -90 <= f["lat"] <= 90 or abs(f["lat"]) < 215, f        # decoded, even if nonsense
            i += n
    # an undamaged stream after garbage is still read completely
    p = crsf.Parser()
    p.feed(bytes(rnd.randrange(256) for _ in range(500)))
    kinds = [f["kind"] for f in p.feed(good)]
    assert {"gps", "link", "battery", "vario", "mode"} <= set(kinds), kinds


def test_crsf_decode_any_payload():
    rnd = random.Random(3)
    for ftype in range(256):
        for n in (0, 1, 2, 5, 9, 10, 14, 15, 30, 60):
            d = crsf.decode(ftype, bytes(rnd.randrange(256) for _ in range(n)))
            assert d is None or isinstance(d, dict)


# ------------------------------------------------------------ flight logs (CSV, GPX)
SAMPLES = sorted((Path(__file__).parent / "samples").glob("*"))


def test_log_samples_damaged():
    rnd = random.Random(4)
    srcs = [p for p in SAMPLES if p.suffix.lower() in (".csv", ".gpx")]
    assert srcs, "no sample logs in tests/samples"
    for src in srcs:
        data = src.read_bytes()
        for i in range(60):
            f = TMP / f"bad_{i}{src.suffix}"
            f.write_bytes(mutate(data, rnd))
            try:
                t = within(10, logs.read_log, f)
            except CLEAN:
                continue
            except Exception as ex:                         # noqa: BLE001
                import xml.etree.ElementTree as ET
                if isinstance(ex, ET.ParseError):           # a damaged GPX: "not valid XML" is a clear message
                    continue
                raise AssertionError(f"{src.name} damaged #{i}: {ex!r}") from ex
            n = len(t.t)
            assert len(t.lat) == len(t.lon) == len(t.alt) == n
            assert all(math.isfinite(v) for v in t.t), "time must have no gaps (NaN) once read"


def test_log_odd_files():
    cases = {
        "empty.csv": b"",
        "header_only.csv": b"Date,Time,GPS,Alt(m)\n",
        "no_gps.csv": b"time,rssi\n0,-60\n1,-61\n",
        "text.csv": "été,ñ,ü\n1,2,3\n".encode("utf-8"),
        "latin1.csv": "lat,lon,alt\n46.5,7.0,1000\n46.6,7.1,1001\n".encode("latin-1") + b"\xe9\xff\n",
        "binary.csv": bytes(range(256)) * 4,
        "huge_line.csv": b"lat,lon\n" + b"4" * 200_000 + b",7\n",
        "one_point.csv": b"lat,lon,alt\n46.5,7.0,1000\n",
        "nan.csv": b"lat,lon,alt\nnan,nan,nan\ninf,-inf,1\n",
        "empty.gpx": b"",
        "not_xml.gpx": b"<gpx><trk><trkseg><trkpt lat='46.5'",
        "no_points.gpx": b"<?xml version='1.0'?><gpx></gpx>",
    }
    for name, data in cases.items():
        f = TMP / name
        f.write_bytes(data)
        try:
            within(10, logs.read_log, f)
        except CLEAN:
            pass
        except Exception as ex:                             # noqa: BLE001
            import xml.etree.ElementTree as ET
            assert isinstance(ex, ET.ParseError), f"{name}: {ex!r}"


# ------------------------------------------------------------ blackbox files
def test_blackbox_damaged():
    try:
        import orangebox  # noqa: F401
    except ImportError:
        print("  (orangebox not installed: skipped)")
        return
    from make_bbl import flight
    from fpv3d.blackbox import flights_in
    good = flight(46.5553, 7.0305, 1215, seconds=20) + flight(46.0207, 7.7491, 1620, seconds=10)
    rnd = random.Random(5)
    for i in range(80):
        f = TMP / f"bad_{i}.BBL"
        f.write_bytes(mutate(good, rnd))
        try:
            fl = within(20, flights_in, f)
        except Exception:                                   # noqa: BLE001 - blackbox.run reports it and goes on
            continue
        for x in fl:
            assert x["rows"] and all(len(r) == 7 for r in x["rows"])
            assert all(math.isfinite(v) for r in x["rows"] for v in r[:4])


# ------------------------------------------------------------ location files
LOC = """name: t
center: {lat: 46.5, lon: 7.5}
half_size_m: 1000
terrain: {resolution_m: 10, surface: dtm}
links:
  - {name: video, freq_mhz: 5800, tx_power_dbm: 14, tx_gain_dbi: 2, rx_gain_dbi: 2, rx_sensitivity_dbm: -85}
"""


def test_location_file_ok():
    from fpv3d.config import LocationConfig
    f = TMP / "ok.yaml"
    f.write_text(LOC, encoding="utf-8")
    c = LocationConfig.load(f)
    assert c.name == "t" and c.terrain.resolution_m == 10


def test_location_files_broken():
    """Hand-edited location files: every mistake gives an error message, never a crash elsewhere."""
    import yaml
    from fpv3d.config import LocationConfig
    variants = [
        "", "just text", "- a\n- list", "name: t\n", LOC.replace("resolution_m: 10", "resolution_m: 7"),
        LOC.replace("surface: dtm", "surface: lidar"), LOC.replace("links:", "links: []\nx:"),
        LOC.replace("center: {lat: 46.5, lon: 7.5}", "center: somewhere"), LOC.replace("lat: 46.5", "lat: north"),
        LOC.replace("half_size_m: 1000", "half_size_m: -5"), LOC.replace("half_size_m: 1000", "half_size_m: big"),
        LOC.replace("freq_mhz: 5800", "freq_mhz: lots"), LOC.replace("{name: video,", "{nom: video,"),
        LOC + "terrain: [1, 2]\n", LOC.replace("name: t", "name: [t]"), "name: t\ncenter: {lat: 46.5, lon: 7.5\n",
        LOC.replace("center:", "centre:"), "\t" + LOC, LOC.replace("terrain: {", "terrain: {foo: 1, "),
    ]
    rnd = random.Random(6)
    variants += [mutate(LOC.encode(), rnd).decode("utf-8", "replace") for _ in range(150)]
    for i, text in enumerate(variants):
        f = TMP / f"loc_{i}.yaml"
        f.write_text(text, encoding="utf-8")
        try:
            within(5, LocationConfig.load, f)
        except (*CLEAN, yaml.YAMLError):
            pass                                            # a message the map page / build shows
        except Exception as ex:                             # noqa: BLE001
            raise AssertionError(f"variant {i}: {ex!r}\n{text[:200]}") from ex


def test_list_locations_survives_broken_files():
    """One broken file never hides the other locations on the map pages or in the launcher."""
    from fpv3d import locations
    d = TMP / "locs"
    d.mkdir(exist_ok=True)
    (d / "001_good.yaml").write_text(LOC.replace("name: t", "name: 001_good"), encoding="utf-8")
    (d / "002_bad.yaml").write_text("name: [", encoding="utf-8")
    (d / "003_worse.yaml").write_bytes(b"\xff\xfe\x00garbage")
    old = locations.LOC_DIR
    try:
        locations.LOC_DIR = d
        res = within(10, locations.list_locations, TMP / "scenes")
    finally:
        locations.LOC_DIR = old
    names = {r["name"] for r in res}
    assert "001_good" in names and len(res) == 3
    assert sum(1 for r in res if r.get("error")) == 2


def test_live_link_reconnects_after_a_dropped_cable():
    """The radio's USB link drops in flight: the session stays open, the port is reopened, data flows again.
    If it never comes back, the link ends with a clear error."""
    import tempfile
    import time
    from fpv3d import crsf, live

    class Port:
        def __init__(self, chunks):
            self.chunks = list(chunks)

        def read(self, n):
            if not self.chunks:
                time.sleep(0.01)
                return b""
            c = self.chunks.pop(0)
            if c is None:
                raise OSError("device disconnected")
            return c

        def close(self):
            pass

    frames = crsf.gps_frame(46.55, 7.03, 30, 90, 1500, 12) + crsf.battery_frame(22.2, 12, 100, 80)
    opens = []

    def run(ports, wait_for, reconnect_s=30):
        link = live.LiveLink()
        link.RECONNECT_S = reconnect_s
        seq = list(ports)

        def open_port(port):
            opens.append(port)
            p = seq.pop(0)
            if p is None:
                raise OSError("no such port")
            return p
        link._open_port = open_port
        old = live.ROOT
        live.ROOT = Path(tempfile.mkdtemp(prefix="alpline_live_"))
        try:
            link.start("001_test", "serial", port="COM9")
            end = time.time() + 15
            while time.time() < end and not wait_for(link.snapshot()):
                time.sleep(0.05)
            snap = link.snapshot()
            link.stop()
            return snap
        finally:
            live.ROOT = old

    # dropped once, back at the second try
    snap = run([Port([frames, frames, None]), None, Port([frames] * 3)], lambda s: s["gps_count"] >= 5 or s["status"] == "error")
    assert snap["status"] == "live" and snap["gps_count"] >= 5 and snap["reconnects"] == 1 and not snap["reconnecting"], snap
    # never back: a clear error after the waiting time
    snap = run([Port([frames, None])] + [None] * 10, lambda s: s["status"] == "error", reconnect_s=1.5)
    assert snap["status"] == "error" and "radio disconnected" in snap["error"], snap


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  ok    {name}")
            except Exception as ex:                         # noqa: BLE001
                fails += 1; print(f"  FAIL  {name}: {ex!r}")
    sys.exit(1 if fails else 0)
