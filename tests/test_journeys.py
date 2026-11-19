"""Whole user journeys, start to finish, with the real commands:   python -m pytest tests/test_journeys.py

Each test works in its own fresh data folder (ALPLINE_DATA) against the fake swisstopo service (tests/mock_stac.py,
started here), so nothing touches your real locations and no internet is needed. They check that every step leaves
the files where the next step (and you) expect them."""
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

LOC = """name: {name}
title: "{title}"
center: {{lat: 46.553, lon: 7.022}}
half_size_m: 1000
pilot: {{lat: 46.5553, lon: 7.0305}}
terrain: {{resolution_m: 10, surface: dtm, ortho: false}}
links:
  - {{name: "Video 5.8 GHz", freq_mhz: 5800, tx_power_dbm: 14, tx_gain_dbi: 2, rx_gain_dbi: 2, rx_sensitivity_dbm: -85}}
"""
MOCK = {}


def mock_port():
    if "port" not in MOCK:
        os.environ.setdefault("MOCK_PORT", "0")
        import mock_stac
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), mock_stac.H)
        srv.daemon_threads = True
        mock_stac.PORT = srv.server_address[1]              # tile links point back here
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        MOCK["port"] = srv.server_address[1]
    return MOCK["port"]


class Data:
    """A fresh Alpline data folder + a runner for `python -m fpv3d ...` inside it."""
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="alpline_journey_"))
        for d in ("locations", "scenes", "cache", "logs"):
            (self.dir / d).mkdir()
        p = mock_port()
        self.env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy")}
        self.env.update(ALPLINE_DATA=str(self.dir), PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8",
                        FPV3D_STAC_BASE=f"http://127.0.0.1:{p}/api/stac/v0.9",
                        FPV3D_COPERNICUS_BASE=f"http://127.0.0.1:{p}/copernicus",
                        FPV3D_SENTINEL2_BASE=f"http://127.0.0.1:{p}/s2",
                        FPV3D_WORLDCOVER_BASE=str(self.dir / "fake_worldcover"),      # a folder: no square exists yet
                        FPV3D_OVERPASS_URL=f"http://127.0.0.1:{p}/api/interpreter")

    def run(self, *args, ok=True, input_text=None):
        cmd = [sys.executable, "-m", "fpv3d"]
        if os.environ.get("ALPLINE_COV"):               # tools/cover.py: also measure the code these commands run
            cmd = [sys.executable, "-m", "coverage", "run", "--parallel-mode", f"--rcfile={ROOT / 'pyproject.toml'}",
                   f"--data-file={ROOT / '.coverage'}", "-m", "fpv3d"]
        r = subprocess.run([*cmd, *args], cwd=self.dir, env=self.env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", input=input_text, timeout=300)
        if ok:
            assert r.returncode == 0, f"fpv3d {' '.join(args)} failed:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}"
        return r

    def location(self, name="001_field", title="Field"):
        f = self.dir / "locations" / f"{name}.yaml"
        f.write_text(LOC.format(name=name, title=title), encoding="utf-8")
        return f

    def scene(self, name):
        return json.loads((self.dir / "scenes" / name / "scene.json").read_text(encoding="utf-8"))


def demo_log(path, minutes=1.0):
    """A small flight around the test field, in the CSV format radios write."""
    import math
    rows = ["Date,Time,GPS,Alt(m),1RSS(dB),RQly(%)"]
    for i in range(int(minutes * 60)):
        a = i / 20
        la, lo = 46.5553 + 0.002 * math.sin(a), 7.0305 + 0.003 * (1 - math.cos(a))
        rows.append(f"2026-11-01,10:{i // 60:02d}:{i % 60:02d}.000,{la:.6f} {lo:.6f},{1220 + i % 40},{-60 - i % 20},{100 - i % 5}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------ journeys
def test_build_add_rename_delete_restore():
    d = Data()
    d.location("001_field", "Field")
    d.run("build", "locations/001_field.yaml")
    m = d.scene("001_field")
    assert m["name"] == "001_field" and (d.dir / "scenes" / "001_field" / "terrain.f32").exists()

    log = demo_log(d.dir / "logs" / "flight1.csv")
    d.run("add-log", "locations/001_field.yaml", str(log))
    m = d.scene("001_field")
    assert len(m["tracks"]) == 1 and (d.dir / "scenes" / "001_field" / m["tracks"][0]["file"]).exists()

    d.run("rename", "log", "001_field", m["tracks"][0]["name"], "001_field_first_flight")
    m = d.scene("001_field")
    assert m["tracks"][0]["name"] == "001_field_first_flight"
    assert (d.dir / "scenes" / "001_field" / m["tracks"][0]["file"]).exists()

    d.run("rename", "location", "001_field", "001_ridge", "--title", "Ridge spot")
    assert (d.dir / "locations" / "001_ridge.yaml").exists() and not (d.dir / "locations" / "001_field.yaml").exists()
    assert d.scene("001_ridge")["title"] == "Ridge spot" and len(d.scene("001_ridge")["tracks"]) == 1
    assert not (d.dir / "scenes" / "001_field").exists()

    d.run("delete", "001_ridge", "--yes")
    assert not (d.dir / "locations" / "001_ridge.yaml").exists() and not (d.dir / "scenes" / "001_ridge").exists()
    assert "001_ridge" in d.run("restore").stdout          # listed in deleted/

    d.run("restore", "001_ridge")
    assert (d.dir / "locations" / "001_ridge.yaml").exists()
    m = d.scene("001_ridge")
    assert len(m["tracks"]) == 1 and (d.dir / "scenes" / "001_ridge" / m["tracks"][0]["file"]).exists()


def test_rename_refuses_to_overwrite():
    d = Data()
    d.location("001_a", "A"); d.location("002_b", "B")
    d.run("build", "locations/001_a.yaml"); d.run("build", "locations/002_b.yaml")
    r = d.run("rename", "location", "001_a", "002_b", ok=False)
    assert r.returncode != 0
    assert d.scene("001_a")["name"] == "001_a" and d.scene("002_b")["name"] == "002_b"


def test_delete_needs_confirmation():
    d = Data()
    d.location()
    d.run("build", "locations/001_field.yaml")
    r = d.run("delete", "001_field", ok=False, input_text="n\n")
    assert r.returncode != 0 and (d.dir / "locations" / "001_field.yaml").exists()


def test_purge_deleted_is_final():
    d = Data()
    d.location()
    d.run("build", "locations/001_field.yaml")
    d.run("delete", "001_field", "--yes")
    d.run("deleted", "--purge")
    assert "nothing" in d.run("restore").stdout
    assert d.run("restore", "001_field", ok=False).returncode != 0


def test_blackbox_twice_adds_once():
    try:
        import orangebox  # noqa: F401
    except ImportError:
        print("  (orangebox not installed: skipped)")
        return
    from make_bbl import make
    d = Data()
    d.location()
    d.run("build", "locations/001_field.yaml")
    bbl = d.dir / "LOG00001.BBL"
    make(bbl, [dict(lat0=46.5553, lon0=7.0305, alt_m=1215), dict(lat0=46.0207, lon0=7.7491, alt_m=1620)])
    out1 = d.run("blackbox", "--file", str(bbl)).stdout
    assert "1 flight(s) added" in out1 and "no location contains" in out1
    out2 = d.run("blackbox", "--file", str(bbl)).stdout
    assert "already added before" in out2 and "0 flight(s) added" in out2
    assert len(d.scene("001_field")["tracks"]) == 1


def test_cache_prune_keeps_what_locations_need():
    d = Data()
    d.location()
    d.run("build", "locations/001_field.yaml")
    cache = d.dir / "cache"
    tiles = [p for p in cache.rglob("*.tif")]
    assert tiles, "the build downloaded no tiles?"
    junk = tiles[0].parent / "swissalti3d_2019_2700-1100_2_2056_5728.tif"   # a tile far away, no location uses it
    junk.write_bytes(b"x" * 1000)
    out = d.run("cache", "prune", "--dry-run").stdout
    assert junk.exists() and "would free" in out
    d.run("cache", "prune")
    assert not junk.exists()
    assert all(p.exists() for p in tiles), "a tile the location needs was removed"
    t = time.time()
    d.run("build", "locations/001_field.yaml", "--reuse-terrain")    # still builds from what is left
    assert time.time() - t < 120


def test_broken_location_file_does_not_break_the_rest():
    d = Data()
    d.location("001_ok", "OK")
    (d.dir / "locations" / "002_broken.yaml").write_text("name: [\n", encoding="utf-8")
    d.run("build", "locations/001_ok.yaml")
    r = d.run("build", "locations/002_broken.yaml", ok=False)
    assert r.returncode != 0 and "Traceback" not in r.stderr, r.stderr[-800:]     # a message, not a crash dump
    r = d.run("refresh-all", "--zones-only", ok=False)                            # the good one still updates,
    out = r.stdout + r.stderr                                                     # the broken one is named with why
    assert "ok      001_ok" in out and "002_broken" in out and "line 2" in out, out[-800:]


def test_location_outside_switzerland():
    """A place abroad builds from the worldwide model and the 2021 satellite photo: on its UTM grid, the right way
    up, with a flight in the right spot, no Swiss drone zones, and a rebuild without internet."""
    import numpy as np
    import mock_stac
    d = Data()
    mock_stac.make_worldcover(d.dir / "fake_worldcover", 47, 11)
    f = d.dir / "locations" / "010_abroad.yaml"
    f.write_text(LOC.format(name="010_abroad", title="Abroad").replace("lat: 46.553, lon: 7.022", "lat: 47.26, lon: 11.39")
                 .replace("lat: 46.5553, lon: 7.0305", "lat: 47.262, lon: 11.395").replace("ortho: false", "ortho: true, ortho_resolution_m: 2"),
                 encoding="utf-8")
    log = d.dir / "logs" / "abroad.csv"
    log.write_text("Date,Time,GPS,Alt(m),1RSS(dB),RQly(%)\n" + "\n".join(
        f"2026-11-01,10:00:{i:02d}.000,{47.262 + i * 1e-5:.6f} {11.395 + i * 1e-5:.6f},{50 + i},-60,100" for i in range(30)) + "\n",
        encoding="utf-8")
    d.run("build", "locations/010_abroad.yaml", "--log", str(log))
    m = d.scene("010_abroad")
    g = m["grid"]
    assert g["crs"] == "EPSG:32632" and [s["name"] for s in m["terrain_sources"]] == ["copernicus"]
    assert "Copernicus" in m["terrain_sources"][0]["credit"] and m["geozones"] is None
    assert m["ortho"] == "ortho.jpg" and [s["name"] for s in m["ortho_sources"]] == ["worldcover"]
    assert "CC BY 4.0" in m["ortho_sources"][0]["credit"] and "2021" in m["ortho_sources"][0]["credit"] and m["detail"] is None
    from PIL import Image
    img = np.asarray(Image.open(d.dir / "scenes" / "010_abroad" / "ortho.jpg").convert("RGB")).astype(float)
    assert img.shape == (g["rows"], g["cols"], 3), img.shape                      # 10 m: the satellite's own detail, not the 2 m asked
    assert img.min() > 20 and abs(img[..., 2].mean() - 120) < 6         # no black gaps between the web-map tiles
    assert img[:, -20:, 0].mean() > img[:, :20, 0].mean() + 20          # red grows to the east: not mirrored
    assert img[:20, :, 1].mean() > img[-20:, :, 1].mean() + 20          # green grows to the north: not upside down
    assert abs(m["center_wgs84"][0] - 47.26) < 0.01 and abs(m["center_wgs84"][1] - 11.39) < 0.01
    dem = np.fromfile(d.dir / "scenes" / "010_abroad" / "terrain.f32", dtype="<f4").reshape(g["rows"], g["cols"])
    import mock_stac
    want = float(mock_stac.world_height(np.array(47.26), np.array(11.39)))
    assert not np.isnan(dem).any() and abs(float(dem[g["rows"] // 2, g["cols"] // 2]) - want) < 40, (dem.min(), dem.max(), want)
    assert dem[0].mean() > dem[-1].mean()                               # the fake model rises to the north: not flipped
    p, t = m["pilot"], m["tracks"][0]
    assert 0 < p["x"] < 2000 and 0 < p["y"] < 2000 and t["max_dist_m"] < 200     # pilot and flight sit inside the map
    assert (d.dir / "cache" / "copernicus" / "32632" / "lod" / "dtm" / "10m").exists()
    assert not (d.dir / "cache" / "lod").exists()                       # nothing was asked of swisstopo
    assert (d.dir / "cache" / "worldcover" / "32632" / "lod" / "ortho" / "10m").exists()
    assert not (d.dir / "cache" / "sentinel2" / "32632" / "lod" / "ortho" / "2m").exists()    # the 2016 picture: not for the area
    # the surroundings: a coarse ring (worldwide heights, the 2016 photo) around the 2 km area, meeting its border
    su = m["surround"]
    sg = su["grid"]
    assert su["file"] == "surround.f32" and su["photo"] == "surround.jpg" and sg["res"] == 25 and sg["crs"] == g["crs"]
    assert sg["min_e"] <= g["min_e"] - 2000 and sg["max_n"] >= g["max_n"] + 2000
    ring = np.fromfile(d.dir / "scenes" / "010_abroad" / "surround.f32", dtype="<f4").reshape(sg["rows"], sg["cols"])
    assert np.isfinite(ring).all() and ring[0].mean() > ring[-1].mean()          # rises to the north, like the area
    r0, c0 = int((sg["max_n"] - g["max_n"]) / sg["res"]), int((g["min_e"] - sg["min_e"]) / sg["res"])
    assert abs(float(ring[r0 + 40, c0 + 40]) - float(dem[100, 100])) < 30          # where they overlap, the same heights
    assert Image.open(d.dir / "scenes" / "010_abroad" / "surround.jpg").size == (sg["cols"] * 25 // 10, sg["rows"] * 25 // 10)
    assert {s["name"] for s in su["sources"]} == {"copernicus", "sentinel2"}
    # cleaning the cache keeps what this location needs (downloads and tiles) and drops the rest
    raw = d.dir / "cache" / "copernicus" / "raw"
    junk = [raw / "Copernicus_DSM_COG_10_N10_00_E010_00_DEM.tif", d.dir / "cache" / "worldcover" / "raw" / "32632_1-1_N10E010.tif",
            d.dir / "cache" / "copernicus" / "32632" / "lod" / "dtm" / "10m" / "300-4000.npy"]
    other = d.dir / "cache" / "copernicus" / "32654" / "lod" / "dtm" / "10m" / "293-3915.npy"      # a grid no location is on
    other.parent.mkdir(parents=True)
    for f in junk + [other]:
        f.write_bytes(b"x" * 2000)
    kept = [f for f in (d.dir / "cache").rglob("*") if f.is_file() and f not in junk + [other]]
    assert "would free" in d.run("cache", "prune", "--dry-run").stdout and all(f.exists() for f in junk + [other])
    assert "4 tiles" in d.run("cache", "prune").stdout
    assert not any(f.exists() for f in junk + [other]) and all(f.exists() for f in kept)
    info = d.run("cache", "info").stdout
    assert "copernicus" in info and "worldcover" in info and "EPSG:32632" in info
    d.env["FPV3D_COPERNICUS_BASE"] = d.env["FPV3D_SENTINEL2_BASE"] = "http://127.0.0.1:9/none"   # no internet: the cache is enough
    d.env["FPV3D_WORLDCOVER_BASE"] = "http://127.0.0.1:9/none"
    d.run("build", "locations/010_abroad.yaml")


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                t = time.time(); fn(); print(f"  ok    {name} ({time.time() - t:.1f} s)")
            except Exception as ex:                         # noqa: BLE001
                fails += 1; print(f"  FAIL  {name}: {ex!r}")
    sys.exit(1 if fails else 0)
