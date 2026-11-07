"""Quick self-test:  python -m pytest tests   (or just: python tests/test_basic.py)"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fpv3d import logs, radio  # noqa: E402
from fpv3d.config import Link  # noqa: E402
from fpv3d.geo import Grid, lv95_to_wgs84, wgs84_to_lv95  # noqa: E402
from fpv3d.los import Terrain, path_clearance  # noqa: E402

S = Path(__file__).parent / "samples"


def test_geo_roundtrip():
    # swisstopo reference point: Bern old observatory ~ E 2600000 / N 1200000
    lat, lon = lv95_to_wgs84(2600000, 1200000)
    assert abs(lat - 46.95108) < 1e-3 and abs(lon - 7.43864) < 1e-3
    e, n = wgs84_to_lv95(lat, lon)
    assert abs(e - 2600000) < 2 and abs(n - 1200000) < 2


def test_parsers():
    bb = logs.read_log(S / "bf_blackbox.gps.csv")
    assert bb.source_format == "blackbox" and len(bb.lat) == 3 and abs(bb.t[1] - 0.1) < 1e-6
    raw = logs.read_log(S / "explorer_raw.csv")
    assert abs(raw.lat[0] - 46.5553) < 1e-6 and "rssi" in raw.telemetry
    alt = logs.resolve_altitude_amsl(raw, np.array([1210.0, 1210.0]))
    assert abs(alt[0] - 1212) < 1e-6  # centimetres auto-detected
    g = logs.read_log(S / "track.gpx")
    assert g.t[-1] == 5 and g.alt[1] == 1240


def test_relative_altitude():
    tr = logs.Track("x", "csv", np.arange(3.0), np.zeros(3), np.zeros(3), np.array([0.0, 10, 20]))
    z = logs.resolve_altitude_amsl(tr, np.array([1500.0, 1500, 1500]))
    assert list(z) == [1500, 1510, 1520]


def test_los_blocked_by_wall():
    grid = Grid(0, 0, 1000, 1000, 10)
    dem = np.full(grid.shape, 1000, np.float32)
    dem[:, 50] = 1100  # a 100 m wall at x = 505 m
    t = Terrain(dem, grid)
    c, f, d = path_clearance(t, (100, 500, 1002), [900, 900], [500, 500], [1002, 1300], 5800)
    assert c[0] < 0          # low drone behind the wall: blocked
    assert c[1] > 0          # high drone: clear


def test_range():
    l = Link("v", 5800, 27, 2, 8, -90, 3, 10)
    r = radio.max_range_m(l)
    assert abs(radio.link_margin_db(l, r, 99)) < 1e-6


def test_tilecache_offline_mosaic(tmp=None):
    """Raw tiles already on disk -> any resolution is built without network, aligned exactly."""
    import tempfile
    import rasterio
    from rasterio.transform import from_origin
    from fpv3d.tilecache import TileCache
    root = Path(tmp or tempfile.mkdtemp())
    folder = root / "ch.swisstopo.swissalti3d"
    folder.mkdir(parents=True, exist_ok=True)
    for ke in (2600, 2601):
        for kn in (1200, 1201):
            h = np.full((500, 500), ke - 2600 + 10 * (kn - 1200) + 500, np.float32)   # 500/501/510/511
            with rasterio.open(folder / f"swissalti3d_2021_{ke}-{kn}_2_2056_5728.tif", "w", driver="GTiff",
                               width=500, height=500, count=1, dtype="float32", crs="EPSG:2056",
                               transform=from_origin(ke * 1000, (kn + 1) * 1000, 2, 2)) as d:
                d.write(h, 1)
    g = Grid(2600500, 1200500, 2601500, 1201500, 10)
    m = TileCache(root).mosaic("dtm", g)
    assert m.shape == (100, 100) and not np.isnan(m).any()
    assert m[0, 0] == 510 and m[0, -1] == 511 and m[-1, 0] == 500 and m[-1, -1] == 501
    m2 = TileCache(root).mosaic("dtm", g)          # second call: pure cache hit
    assert np.array_equal(m, m2)


def test_crsf_roundtrip():
    """CRSF frames (as EdgeTX mirrors them on USB) decode back, even split in odd chunks."""
    from fpv3d import crsf
    assert crsf.crc8(b"123456789") == 0xBC                     # CRC-8/DVB-S2 check value
    data = (b"\x00\xff" + crsf.gps_frame(46.5486, 7.0181, 72.5, 123.4, 1850, 11) + crsf.link_frame(-75, 96, 7)
            + crsf.battery_frame(15.8, 22.3, 640, 71) + crsf.vario_frame(-2.5) + crsf.mode_frame("ACRO"))
    p, out = crsf.Parser(), []
    for i in range(0, len(data), 7):
        out += p.feed(data[i:i + 7])
    kinds = {d["kind"]: d for d in out}
    assert set(kinds) == {"gps", "link", "battery", "vario", "mode"} and p.bad == 0
    g = kinds["gps"]
    assert abs(g["lat"] - 46.5486) < 1e-7 and g["alt"] == 1850 and g["speed_kmh"] == 72.5 and g["sats"] == 11
    assert kinds["link"]["lq"] == 96 and kinds["link"]["rssi1"] == -75 and kinds["mode"]["mode"] == "ACRO"
    assert abs(kinds["vario"]["vspeed"] + 2.5) < 1e-9 and kinds["battery"]["mah"] == 640
    bad = bytearray(crsf.link_frame(-75, 96)); bad[-1] ^= 0xFF  # corrupted CRC is skipped
    assert crsf.Parser().feed(bytes(bad)) == []



def test_crsf_rssi_both_conventions():
    from fpv3d import crsf
    assert crsf.dbm(51) == -51          # CRSF spec: dBm x -1
    assert crsf.dbm(205) == -51         # ExpressLRS: the signed byte (-51 dBm), was shown as -205
    p = crsf.Parser()
    f = crsf.encode(0x14, bytes([205, 211, 100, 11, 0, 6, 1, 200, 100, 9]))
    out = p.feed(f)[0]
    assert out["rssi1"] == -51 and out["rssi2"] == -45 and out["lq"] == 100

def test_blackbox_read():
    """A synthetic Betaflight log file with two logs (two flights): GPS read in degrees, metres, m/s."""
    import tempfile
    try:
        import orangebox  # noqa: F401
    except ImportError:
        print("  (orangebox not installed: skipped)")
        return
    sys.path.insert(0, str(Path(__file__).parent))
    from make_bbl import make
    from fpv3d.blackbox import _alt_scale, flights_in, write_csv
    from fpv3d.logs import read_csv
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "LOG00001.BBL"
        make(f, [dict(lat0=46.5553, lon0=7.0305, alt_m=1215), dict(lat0=46.0207, lon0=7.7491, alt_m=1620, alt_unit=1.0,
                                                                   firmware="4.3.2")])
        fl = flights_in(f)
        assert [x["index"] for x in fl] == [1, 2], fl
        a, b = fl
        assert abs(a["start"][0] - 46.5553) < 1e-4 and abs(a["start"][1] - 7.0305) < 1e-4, a["start"]
        assert abs(a["rows"][0][3] - 1215) < 1 and abs(a["rows"][-1][3] - 1255) < 1.5, a["rows"][-1]
        assert abs(b["rows"][0][3] - 1620) < 1, b["rows"][0]             # older Betaflight: whole metres
        assert 29 < a["seconds"] < 31 and len(a["rows"]) == 300
        assert abs(a["rows"][5][5] - 12.57) < 0.02                       # cm/s -> m/s
        out = Path(d) / "x.csv"
        write_csv(a["rows"], out)
        t = read_csv(out)
        assert t.source_format == "blackbox" and len(t.t) == 300, (t.source_format, len(t.t))
    assert _alt_scale({}, [12150]) == 0.1 and _alt_scale({}, [1215]) == 1.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
