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


def test_buildings_block_the_signal_but_not_the_ground():
    """A bare-ground street with a 40 m block in it: the block hides a low drone, yet "30 m above ground" is still
    counted from the street, and the pilot stands on the street."""
    import json
    import tempfile
    from fpv3d import buildings
    from fpv3d.los import los_ceilings
    from fpv3d.scene import signal_terrain
    grid = Grid(0, 0, 400, 200, 2)
    dem = np.full(grid.shape, 10, np.float32)
    block = dict(p=[[190, 60], [210, 60], [210, 140], [190, 140]], b=10, t=50)     # 20 x 80 m, 40 m high
    blocked = buildings.burn(dem, grid, [block])
    r, c = int((200 - 100) / 2), int(200 / 2)                                     # the block's middle cell
    assert blocked[r, c] == 50 and blocked[r, 10] == 10 and dem[r, c] == 10        # dem itself left alone
    high = dem.copy(); high[r, c] = 80
    assert buildings.burn(high, grid, [block])[r, c] == 80                         # a higher surface model wins

    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        (out / "buildings.json").write_text(json.dumps(dict(items=[block])))
        t = signal_terrain(out, grid, dem, dict(file="buildings.json", count=1))
        assert float(t.height(200, 100)) == 10                                     # ground under the block
        off = signal_terrain(out, grid, dem, dict(count=0, disabled=True))        # buildings turned off: ignored
        assert off.ground is off.dem
        plain = signal_terrain(out, grid, dem, None)
        assert plain.ground is plain.dem                                           # no buildings: as before
    src = (50, 100, 12)                                                            # pilot west of the block, 2 m up
    c30, _, _ = path_clearance(t, src, [350], [100], [40], 5800)                   # drone east of it, 30 m up
    assert c30[0] < 0
    c30_plain, _, _ = path_clearance(plain, src, [350], [100], [40], 5800)
    assert c30_plain[0] > 0                                                        # bare ground alone: in sight
    lgrid = grid.with_resolution(10)
    ceil, ground = los_ceilings(t, src, lgrid, 5800, 4 / 3, 0.6, 100.0)
    row, col = int((200 - 100) / 10), int(350 / 10)
    assert np.allclose(ground, 10)                                                 # heights from the street
    assert 75 < ceil["los"][row, col] < 95        # the block's near roof edge seen from the pilot: about 85 m up
    assert ceil["los"][row, 10] == 0                                               # same side as the pilot: clear

    # a pilot point inside the block stands on its roof, and says so
    from types import SimpleNamespace
    from fpv3d.scene import pilot_position
    cfg = SimpleNamespace(pilot=True, pilot_en=lambda: (200, 100), pilot_antenna_height_m=1.8)
    p = pilot_position(cfg, t, [])
    assert p["ground"] == 50 and abs(p["z"] - 51.8) < 1e-6 and p["on_roof_m"] == 40 and p["street"] == 10
    cfg.pilot_en = lambda: (50, 100)
    assert "on_roof_m" not in pilot_position(cfg, t, []) and pilot_position(cfg, plain, [])["ground"] == 10


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
    assert [s.name for s in sources.chain(None, "ortho")] == ["swisstopo", "worldcover", "sentinel2"]
    assert [s.name for s in sources.chain("EPSG:32632", "dsm")] == ["copernicus"]
    assert [s.name for s in sources.chain("EPSG:32632", "ortho")] == ["worldcover", "sentinel2"]   # 2021 first, 2016 behind


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
        (tc.base / "_warp2").touch()                                 # tiles of today, not ones to be made again
        for k in [(2600, 1200), (2601, 1200)]:
            if k not in skip:
                np.save(tc.tile_path("dtm", 10, k), np.full((100, 100), height, np.float32))
        return s

    first, second = fake("first", 500, skip=[(2601, 1200)]), fake("second", 900)
    old = sources.chain
    sources.chain = lambda crs, kind, where=None: [first, second]
    try:
        used = []
        dem = terrain.elevation(Grid(2600000, 1200000, 2602000, 1201000, 10), "dtm", root, used=used)
        assert (dem[:, :100] == 500).all() and (dem[:, 100:] == 900).all() and [s.name for s in used] == ["first", "second"]
        used = []
        dem = terrain.elevation(Grid(2600000, 1200000, 2601000, 1201000, 10), "dtm", root, used=used)
        assert (dem == 500).all() and [s.name for s in used] == ["first"]          # nothing missing: the second is not asked
    finally:
        sources.chain = old


def test_regional_source_comes_before_the_world(tmp=None):
    """A source for one country is asked for places inside its area, before the worldwide model, and the worldwide
    model still fills what it lacks. Outside its area it is not asked at all. The cache tools know about it."""
    import tempfile
    from fpv3d import sources, terrain
    from fpv3d.tilecache import TileCache
    root = Path(tmp or tempfile.mkdtemp())

    class Land(sources.TerrainSource):
        name, host, kinds, credit = "testland", "example.invalid", ("dtm",), "© Testland survey"

        def __init__(self, crs):
            self.crs, self.cache_prefix = crs, f"testland/{crs.split(':')[-1]}"

        def raw_dir(self, root, kind):
            return Path(root) / "testland" / "raw"

        def lookup(self, kind, keys, res):
            return {}

        def raw_names(self, key):
            return set()

    def tiles(src, height, keys):                       # put ready tiles in a source's cache (no download needed)
        tc = TileCache(root, src)
        tc.lod_dir("dtm", 10).mkdir(parents=True, exist_ok=True)
        (tc.base / "_warp2").touch()                                 # tiles of today, not ones to be made again
        for k in keys:
            np.save(tc.tile_path("dtm", 10, k), np.full((100, 100), height, np.float32))

    def land():
        return next(r for r in sources.regional_sources() if r.name == "testland")

    crs = "EPSG:32633"
    sources.register_regional("testland", "Testland, fine model", ("dtm",), lambda lat, lon: 48 <= lat <= 50 and 14 <= lon <= 17, Land)
    try:
        inside, outside = (49.17, 15.48), (52.0, 15.48)
        assert [s.name for s in sources.chain(crs, "dtm", inside)] == ["testland", "copernicus"]
        assert [s.name for s in sources.chain(crs, "dtm", outside)] == ["copernicus"]
        assert [s.name for s in sources.chain(crs, "dtm")] == ["copernicus"]                # no place given: not asked
        assert [s.name for s in sources.chain(crs, "ortho", inside)] == ["worldcover", "sentinel2"]   # it has no photo
        assert [s.name for s in sources.chain("EPSG:2056", "dtm", inside)] == ["swisstopo", "testland", "copernicus"]
        g = Grid(534000, 5446000, 536000, 5447000, 10, crs)                                   # two tiles near 49.17 N, 15.48 E
        tiles(sources.regional(land(), crs), 700, [(534, 5446)])       # the country has the west tile
        tiles(sources.worldwide(crs), 300, [(534, 5446), (535, 5446)])                        # the world has both
        used = []
        dem = terrain.elevation(g, "dtm", root, used=used)
        assert (dem[:, :100] == 700).all() and (dem[:, 100:] == 300).all()
        assert [s.name for s in used] == ["testland", "copernicus"] and used[0].credit == "© Testland survey"
        inv = terrain.world_inventory(root)
        assert ("testland", crs) in [(w["source"], w["crs"]) for w in inv]
        assert any("testland" in line for line in terrain.world_info(root))
        files, _ = terrain.prune_world(root, {crs: {"535-5446"}}, dry_run=False)             # the west tile is no longer needed
        assert files == 2 and (dem.shape == (100, 200))
        assert not TileCache(root, sources.regional(land(), crs)).tile_path("dtm", 10, (534, 5446)).exists()
    finally:
        sources.unregister_regional("testland")
    assert "testland" not in [r.name for r in sources.regional_sources()]
    assert [s.name for s in sources.chain(crs, "dtm", inside)] == ["copernicus"]


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


def test_clear_world_cache(tmp=None):
    """`cache clear` on the worldwide caches: resampled tiles of one kind, or the downloads."""
    import tempfile
    from fpv3d import terrain
    root = Path(tmp or tempfile.mkdtemp())
    files = {k: root / p for k, p in dict(
        dtm="copernicus/32632/lod/dtm/10m/681-5239.npy", dsm="copernicus/32632/lod/dsm/10m/681-5239.npy",
        photo="sentinel2/32632/lod/ortho/10m/681-5239.jpg", dem_raw="copernicus/raw/Copernicus_DSM_COG_10_N47_00_E011_00_DEM.tif",
        photo_raw="sentinel2/raw/14-8710-5743.tif").items()}
    for f in files.values():
        f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(b"x")
    have = lambda: sorted(k for k, f in files.items() if f.exists())  # noqa: E731
    assert len(terrain.world_info(root)) == 5
    terrain.clear_world(root, lod=True, kind="dsm")
    assert have() == ["dem_raw", "dtm", "photo", "photo_raw"]
    terrain.clear_world(root, raw=True, kind="dtm")                 # the download also serves "dsm": it stays
    assert have() == ["dem_raw", "dtm", "photo", "photo_raw"]
    terrain.clear_world(root, raw=True, kind="ortho")
    assert have() == ["dem_raw", "dtm", "photo"]
    terrain.clear_world(root, raw=True, lod=True)
    assert have() == [] and terrain.world_info(root) == []


def test_worldcover_holes_are_filled(tmp=None):
    """The 2021 picture has no pixels where snow lies all year (glaciers). Those holes inside a tile must not stay
    black: they are filled from the 2016 picture, and only the tile with the hole asks for it."""
    import tempfile
    import mock_stac
    from PIL import Image
    from fpv3d import sources, terrain, worldcover
    from fpv3d.tilecache import TileCache
    root, data = Path(tmp or tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    mock_stac.make_worldcover(data, 47, 11, hole=(11.382, 47.2545, 11.387, 47.2585))    # inside the western tile
    old, worldcover.BASE = worldcover.BASE, str(data)
    worldcover._EXISTS.clear()
    try:
        g = Grid(680000, 5236000, 682000, 5237000, 10, "EPSG:32632")
        fallback = TileCache(root, sources.worldwide_photo("EPSG:32632"))
        fallback.lod_dir("ortho", 10).mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.full((100, 100, 3), 77, np.uint8)).save(fallback.tile_path("ortho", 10, (680, 5236)))
        fallback._none_path("ortho", 10, (681, 5236)).touch()      # would be found empty if it were asked for
        used = []
        img = terrain.orthophoto(g, root, used=used).astype(int)
        assert [s.name for s in used] == ["worldcover", "sentinel2"]
        assert img.max(axis=2).min() > 20                              # nothing black, no dark rim either
        filled = (np.abs(img - 77) < 4).all(axis=2)
        assert 500 < filled.sum() < 2500 and not filled[:, 100:].any()  # a patch of the 2016 picture, in the west tile only
        assert abs(img[~filled][:, 2].mean() - 120) < 4               # the rest is still the 2021 picture
    finally:
        worldcover.BASE = old
        worldcover._EXISTS.clear()


def test_old_world_tiles_on_the_swiss_grid_are_made_again(tmp=None):
    """Worldwide data on the Swiss grid, cached by a version whose warp could leave an empty band: thrown away
    once (a note marks it), then left alone. Other grids and swisstopo's own cache are never touched."""
    import tempfile
    from fpv3d import sources
    from fpv3d.tilecache import TileCache
    root = Path(tmp or tempfile.mkdtemp())
    swiss, world = TileCache(root), TileCache(root, sources.worldwide_photo("EPSG:2056"))
    utm = TileCache(root, sources.worldwide_photo("EPSG:32632"))
    for tc in (swiss, world, utm):
        tc.lod_dir("ortho", 10).mkdir(parents=True, exist_ok=True)
        tc.tile_path("ortho", 10, (1, 1)).write_bytes(b"old")
        tc._drop_faulty()
    assert not world.tile_path("ortho", 10, (1, 1)).exists() and (world.base / "_warp2").exists()
    assert swiss.tile_path("ortho", 10, (1, 1)).exists() and utm.tile_path("ortho", 10, (1, 1)).exists()
    world.lod_dir("ortho", 10).mkdir(parents=True, exist_ok=True)
    world.tile_path("ortho", 10, (1, 1)).write_bytes(b"new")
    world._drop_faulty()
    assert world.tile_path("ortho", 10, (1, 1)).exists()            # only once


def test_worldcover_photo(tmp=None):
    """The 2021 satellite picture: file names in every quarter of the globe, reflectance turned into a picture, only
    the tile's part read from the big file, an all-sea square remembered, and the 2016 picture as the fallback."""
    import tempfile
    import mock_stac
    from fpv3d import sources, terrain, worldcover
    from fpv3d.tilecache import TileCache
    assert worldcover.square_path(47, 11) == "rgbnir/2021/N47/ESA_WorldCover_10m_2021_v200_N47E011_S2RGBNIR.tif"
    assert worldcover.square_code(-34, 18) == "S34E018" and worldcover.square_code(40, -75) == "N40W075"
    pic = worldcover.to_picture(np.array([[0, 3000, 9000, 1]]), np.array([[0, 3000, 9000, 1]]), np.array([[0, 3000, 9000, 1]]))
    assert pic[0, 0].tolist() == [0, 0, 0] and pic[0, 1].tolist() == [255] * 3 and pic[0, 2].tolist() == [255] * 3
    assert pic[0, 3].min() >= 1                                    # the darkest real pixel is not "no data"
    root, data = Path(tmp or tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    big = mock_stac.make_worldcover(data, 47, 11)
    old, worldcover.BASE = worldcover.BASE, str(data)
    worldcover._EXISTS.clear()
    try:
        src = sources.worldcover("EPSG:32632")
        g = Grid(680000, 5236000, 682000, 5237000, 10, "EPSG:32632")       # two 1 km tiles near 47.26 N, 11.39 E
        used = []
        img = terrain.orthophoto(g, root, used=used).astype(float)
        assert img.shape == (100, 200, 3) and [s.name for s in used] == ["worldcover"] and img.min() > 20
        assert abs(img[..., 2].mean() - 120) < 4                           # blue came back as it was put in
        assert img[:, -20:, 0].mean() > img[:, :20, 0].mean() + 20         # red grows east: not mirrored
        assert img[:10, :, 1].mean() > img[-10:, :, 1].mean() + 10         # green grows north: not upside down
        pieces = sorted((root / "worldcover" / "raw").glob("*.tif"))
        assert [p.name for p in pieces] == ["32632_680-5236_N47E011.tif", "32632_681-5236_N47E011.tif"]
        assert sum(p.stat().st_size for p in pieces) < big.stat().st_size / 20     # a small part, not the whole file
        assert src.raw_names((680, 5236)) >= {"32632_680-5236_N47E011"}
        # a square with no file (all sea): noted, and the 2016 picture is asked for that tile instead
        sea = Grid(500000, 5000000, 501000, 5001000, 10, "EPSG:32632")      # 45.15 N, 9.0 E: not in the fake data
        tc = TileCache(root, src)
        assert tc.ensure("ortho", 10, [(500, 5000)])["empty"] == 1 and (root / "worldcover" / "raw" / "N45E009.missing").exists()
        from fpv3d import sentinel2
        fallback = TileCache(root, sources.worldwide_photo("EPSG:32632"))
        fallback.lod_dir("ortho", 10).mkdir(parents=True, exist_ok=True)
        from PIL import Image
        Image.fromarray(np.full((100, 100, 3), 77, np.uint8)).save(fallback.tile_path("ortho", 10, (500, 5000)))
        used = []
        img = terrain.orthophoto(sea, root, used=used)
        assert abs(int(img[50, 50, 0]) - 77) < 3 and [s.name for s in used] == ["sentinel2"] and sentinel2.NATIVE_M == 10
    finally:
        worldcover.BASE = old
        worldcover._EXISTS.clear()


def test_sentinel2_tiles():
    """The satellite photo's web-map tile numbers (Innsbruck: checked against PROJ's web-mercator position)."""
    from fpv3d.sentinel2 import Sentinel2, tile_at, tile_bounds
    assert tile_at(0.0, 0.0, 1) == (1, 1) and tile_at(85.0, -180.0, 3) == (0, 0) and tile_at(-85.0, 179.9, 3) == (7, 7)
    x, y = tile_at(47.2867, 11.3986, 14)
    assert (x, y) == (8710, 5743), (x, y)
    west, north, size = tile_bounds(14, x, y)
    assert abs(size - 2445.98) < 0.01 and west < 1268890 < west + size        # Innsbruck's web-mercator easting
    t = Sentinel2("EPSG:32632").tiles((681, 5239))
    assert (14, x, y) in t and 1 <= len(t) <= 4 and len(set(t)) == len(t)


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


def test_surroundings_are_sewn_to_the_area():
    """The coarse ring takes the area's own heights on and under its border, so no step (and no sky) shows between
    them, and goes back to its own heights a little way out, smoothly."""
    from fpv3d.scene import stitch_surround
    area = Grid(1000, 1000, 2000, 2000, 10)                       # 1 km area, 10 m cells
    E = area.min_e + (np.arange(area.cols) + 0.5) * area.res
    dem = np.tile((500 + 0.3 * (E - 1000)).astype(np.float32), (area.rows, 1))   # rises to the east, 0 to 300 m
    ring = Grid(0, 0, 3000, 3000, 25)
    coarse = np.full(ring.shape, 400.0, np.float32)               # the worldwide model: flat, 100 m below at the west
    h = stitch_surround(coarse, ring, dem, area, blend_m=150)
    col = lambda e: int((e - ring.min_e) // ring.res)             # noqa: E731
    row = lambda n: int((ring.max_n - n) // ring.res)             # noqa: E731
    assert abs(h[row(1500), col(1012.5)] - (500 + 0.3 * 12.5)) < 2      # just inside the west border: the area
    assert abs(h[row(1500), col(987.5)] - 500) < 3                       # just outside: still the area's edge
    assert abs(h[row(1500), col(1987.5)] - 796) < 3                      # the east border too (300 m higher)
    assert h[row(1500), col(500)] == 400 and h[row(200), col(1500)] == 400     # far out: the worldwide model
    west = h[row(1500), col(800):col(1000)]
    assert (np.diff(west) >= -1e-3).all()                                # it climbs to the edge without a dip
    assert np.isfinite(h).all()


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
