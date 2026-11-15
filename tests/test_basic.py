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


def test_grid_other_coordinate_system():
    """A grid outside Switzerland: UTM zone picked from the place, there and back within a metre, kept in scene.json."""
    from fpv3d.geo import project, unproject, utm_crs
    assert utm_crs(45.83, 6.86) == "EPSG:32632" and utm_crs(-33.9, 18.4) == "EPSG:32734" and utm_crs(40.7, -74.0) == "EPSG:32618"
    crs = utm_crs(45.8326, 6.8652)                              # Mont Blanc
    e, n = project(45.8326, 6.8652, crs)
    lat, lon = unproject(e, n, crs)
    assert abs(lat - 45.8326) < 1e-5 and abs(lon - 6.8652) < 1e-5
    ea, na = project(np.array([45.8, 45.9]), np.array([6.8, 6.9]), crs)
    assert ea.shape == (2,) and na[1] - na[0] > 10_000          # 0.1 degree of latitude is about 11 km
    e2, n2 = project(46.95108, 7.43864, "EPSG:2056")            # LV95 still goes through the swisstopo formulas
    assert abs(float(e2) - 2600000) < 2 and abs(float(n2) - 1200000) < 2
    g = Grid.around(float(e), float(n), 500, 10, crs)
    assert g.with_resolution(5).crs == crs and Grid.from_dict(g.to_dict()).crs == crs
    lo0, la0, lo1, la1 = g.wgs84_bbox()
    assert lo0 < 6.8652 < lo1 and la0 < 45.8326 < la1
    old = {k: v for k, v in Grid(0, 0, 1000, 1000, 10).to_dict().items() if k != "crs"}
    assert Grid.from_dict(old).crs == "EPSG:2056"               # scenes written before crs existed are Swiss


def test_tilecache_second_source(tmp=None):
    """Another terrain source (own coordinate system, two files for one tile) fills the same cache, in its own folder."""
    import tempfile
    import rasterio
    from rasterio.transform import from_origin
    from fpv3d import sources
    from fpv3d.tilecache import TileCache
    root = Path(tmp or tempfile.mkdtemp())
    asked = []

    class Fake(sources.TerrainSource):
        name, host, crs, kinds, cache_prefix = "fake", "example.invalid", "EPSG:32632", ("dtm",), "fake"

        def raw_dir(self, root, kind):
            return Path(root) / "raw" / kind

        def lookup(self, kind, keys, res):
            asked.append(list(keys))
            return {k: [sources.Found(f"{k[0]}-{k[1]}-w", dict(part="w")), sources.Found(f"{k[0]}-{k[1]}-e", dict(part="e"))]
                    for k in keys if k != (341, 5077)}          # the provider has nothing for one tile

        def download(self, root, kind, found, on_progress=None):
            ke, kn, half = found.href.split("-")
            d = self.raw_dir(root, kind); d.mkdir(parents=True, exist_ok=True)
            p = d / f"{found.href}.tif"                          # west half holds 100 m, east half 200 m
            with rasterio.open(p, "w", driver="GTiff", width=50, height=100, count=1, dtype="float32", crs=self.crs,
                               transform=from_origin(int(ke) * 1000 + (500 if half == "e" else 0), (int(kn) + 1) * 1000, 10, 10)) as f:
                f.write(np.full((100, 50), 200 if half == "e" else 100, np.float32), 1)
            return p

    tc = TileCache(root, Fake())
    g = Grid(340000, 5076000, 342000, 5078000, 10, "EPSG:32632")
    m = tc.mosaic("dtm", g)
    assert m.shape == (200, 200) and m[150, 10] == 100 and m[150, 90] == 200    # both halves of the south-west tile
    assert np.isnan(m[10, 150]) and not np.isnan(m[10, 50])                       # the tile without data stays empty
    assert (root / "fake" / "lod" / "dtm" / "10m" / "340-5076.npy").exists() and not (root / "lod").exists()
    assert np.array_equal(tc.mosaic("dtm", g), m, equal_nan=True) and len(asked) == 1   # second call: no query
    assert TileCache(root).inventory() == {"lod": {}, "raw": {}}                  # the swisstopo cache is untouched
    assert [s.name for s in sources.chain("EPSG:2056", "dtm")] == ["swisstopo", "copernicus"]   # the world model fills gaps
    assert [s.name for s in sources.chain(None, "ortho")] == ["swisstopo"]
    assert [s.name for s in sources.chain("EPSG:32632", "dsm")] == ["copernicus"] and not sources.chain("EPSG:32632", "ortho")


def test_gaps_filled_by_next_source(tmp=None):
    """Where the first source has nothing (swisstopo across the border), the next one fills in; the first one's
    heights are never replaced."""
    import tempfile
    from fpv3d import sources, terrain
    from fpv3d.tilecache import TileCache
    root = Path(tmp or tempfile.mkdtemp())

    def fake(name, height, skip=()):
        class Src(sources.TerrainSource):
            crs, kinds, cache_prefix, credit = "EPSG:2056", ("dtm",), name, name

            def raw_dir(self, root, kind):
                return Path(root) / name

            def lookup(self, kind, keys, res):
                return {}
        s = Src(); s.name = name
        tc = TileCache(root, s)
        tc.lod_dir("dtm", 10).mkdir(parents=True, exist_ok=True)
        for k in [(2600, 1200), (2601, 1200)]:
            if k not in skip:
                np.save(tc.tile_path("dtm", 10, k), np.full((100, 100), height, np.float32))
        return s

    first, second = fake("first", 500, skip=[(2601, 1200)]), fake("second", 900)
    old = sources.chain
    sources.chain = lambda crs, kind: [first, second]
    try:
        used = []
        dem = terrain.elevation(Grid(2600000, 1200000, 2602000, 1201000, 10), "dtm", root, used=used)
        assert (dem[:, :100] == 500).all() and (dem[:, 100:] == 900).all() and [s.name for s in used] == ["first", "second"]
        used = []
        dem = terrain.elevation(Grid(2600000, 1200000, 2601000, 1201000, 10), "dtm", root, used=used)
        assert (dem == 500).all() and [s.name for s in used] == ["first"]          # nothing missing: the second is not asked
    finally:
        sources.chain = old


def test_copernicus_squares():
    """The worldwide model's file names, in all four quarters of the globe and across a square's edge."""
    from fpv3d.copernicus import Copernicus, square_name
    assert square_name(45, 6) == "Copernicus_DSM_COG_10_N45_00_E006_00_DEM"
    assert square_name(-34, 18) == "Copernicus_DSM_COG_10_S34_00_E018_00_DEM"
    assert square_name(40, -75) == "Copernicus_DSM_COG_10_N40_00_W075_00_DEM"
    c = Copernicus("EPSG:32632")
    assert c.squares((681, 5239)) == [(47, 11)]                                 # Innsbruck
    assert sorted(c.squares((652, 5207))) == [(46, 10), (46, 11), (47, 10), (47, 11)]   # the corner of four squares
    assert Copernicus("EPSG:32734").squares((259, 6245)) == [(-34, 18)]         # Cape Town


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


def test_launcher_tile_style():
    """Launcher map tiles: dark, dimmed outside Switzerland, zones become an outline + hatch; tile keys around a point."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  (Pillow not installed: skipped)")
        return
    from fpv3d.launcher_tiles import Tiles, style
    base = Image.new("RGBA", (256, 256), (240, 240, 240, 255))
    mask = Image.new("RGBA", (256, 256), (0, 0, 0, 0)); ImageDraw.Draw(mask).rectangle((0, 0, 127, 255), fill=(255, 0, 0, 255))
    zones = Image.new("RGBA", (256, 256), (0, 0, 0, 0)); ImageDraw.Draw(zones).ellipse((60, 60, 200, 200), fill=(230, 80, 80, 150))
    rgb, zo = style(base, None, mask, zones)
    assert rgb.size == (256, 256) and max(rgb.getpixel((20, 128))) < 80              # paper turned dark
    assert sum(rgb.getpixel((20, 128))) > sum(rgb.getpixel((236, 128)))             # outside Switzerland dimmer
    assert zo.getpixel((60, 130))[3] > 150 and zo.getpixel((5, 5))[3] == 0           # outline at the zone's edge only
    keys = Tiles(Path("/nonexistent")).around([(46.55, 7.02)], km=10)
    assert {k[0] for k in keys} == {10, 11, 12, 13} and 20 < len(keys) < 200, len(keys)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
