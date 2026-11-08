"""Your files: safe writing, the error log, clean-up / start fresh, backup and restore, disk space.
python -m pytest tests/test_files.py      (works in temporary folders: your own files are never touched)"""
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from fpv3d import errorlog, housekeeping as hk  # noqa: E402
from fpv3d.safefile import write_atomic  # noqa: E402


def make_data():
    """A small Alpline folder that is also a program folder (as when started from the source)."""
    root = Path(tempfile.mkdtemp(prefix="alpline_files_"))
    def put(rel, data="x" * 100):
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(data, encoding="utf-8")
    put("launcher.pyw", "program"); put("fpv3d/core.py", "program"); put("README.md", "program")
    put("locations/001_a.yaml", "name: 001_a\n")
    tracks = [dict(name="flight1", file="tracks/flight1.json"), dict(name="001_a_sim_2026", file="tracks/001_a_sim_2026.json")]
    put("scenes/001_a/scene.json", json.dumps(dict(name="001_a", title="A", tracks=tracks)))
    put("scenes/001_a/terrain.f32", "t" * 5000)
    put("scenes/001_a/tracks/flight1.json", "f" * 300)
    put("scenes/001_a/tracks/001_a_sim_2026.json", "s" * 200)
    put("scenes/index.json", "[]")
    put("logs/flight1.csv", "c" * 400); put("logs/blackbox/2026/a.csv", "b" * 50); put("logs/live/001_a/l.csv", "l" * 60)
    put("logs/sim/001_a/001_a_sim_2026.csv", "s" * 70)
    put("logs/server.log", "log"); put("logs/errors.txt", "err"); put("logs/checks/viewer.png", "png")
    put("cache/swissalti/1.tif", "c" * 1000); put("deleted/old/info.json", "{}"); put("launcher.json", '{"port": 8123}')
    return root


def program_ok(root):
    return all((root / f).read_text(encoding="utf-8") == "program" for f in ("launcher.pyw", "fpv3d/core.py", "README.md"))


def test_write_atomic_keeps_old_file_on_failure():
    d = Path(tempfile.mkdtemp())
    f = d / "settings.json"
    write_atomic(f, "old")
    real = os.replace
    try:
        os.replace = lambda a, b: (_ for _ in ()).throw(OSError("disk gone"))
        try:
            write_atomic(f, "new")
            raise AssertionError("should have failed")
        except OSError:
            pass
    finally:
        os.replace = real
    assert f.read_text() == "old" and [p.name for p in d.iterdir()] == ["settings.json"]   # no temporary file left
    write_atomic(f, b"\x00bytes")
    assert f.read_bytes() == b"\x00bytes"


def test_error_log_records_and_stays_small():
    f = errorlog.log_file()
    old = f.read_text(encoding="utf-8") if f.exists() else None
    try:
        try:
            raise ValueError("boom in a button")
        except ValueError as ex:
            errorlog.record_exception("launcher", ex)
        text = f.read_text(encoding="utf-8")
        assert "launcher: ValueError: boom in a button" in text and "Traceback" in text
        for i in range(400):
            errorlog.record("test", f"entry {i}", "x" * 3000)
        assert f.stat().st_size <= errorlog.LIMIT * 1.5 and f.read_text(encoding="utf-8").startswith("--- ")
    finally:
        if old is None:
            f.unlink(missing_ok=True)
        else:
            f.write_text(old, encoding="utf-8")


def test_sizes_by_kind():
    root = make_data()
    s = hk.sizes(root)
    assert s["flights"] == 400 + 50 + 60 + 300 and s["training"] == 70 + 200
    assert s["cache"] == 1000 and s["settings"] > 0 and s["applogs"] == 3 + 3 + 3 and s["locations"] > 0


def test_clear_training_keeps_real_flights():
    root = make_data()
    freed = hk.clear(["training"], root)
    assert freed["training"] == 270
    meta = json.loads((root / "scenes/001_a/scene.json").read_text(encoding="utf-8"))
    assert [t["name"] for t in meta["tracks"]] == ["flight1"]
    assert (root / "scenes/001_a/tracks/flight1.json").exists() and not (root / "logs/sim").exists()
    assert (root / "logs/flight1.csv").exists()


def test_clear_flights_and_app_logs():
    root = make_data()
    hk.clear(["flights", "applogs"], root)
    assert not (root / "logs/flight1.csv").exists() and not (root / "logs/blackbox").exists()
    assert (root / "logs/sim/001_a/001_a_sim_2026.csv").exists()                  # training flights stay
    assert not (root / "logs/server.log").exists() and not (root / "logs/checks/viewer.png").exists()
    meta = json.loads((root / "scenes/001_a/scene.json").read_text(encoding="utf-8"))
    assert [t["name"] for t in meta["tracks"]] == ["001_a_sim_2026"]
    assert json.loads((root / "scenes/index.json").read_text())[0]["tracks"] == 1


def test_locations_take_their_scenes():
    root = make_data()
    hk.clear(["locations"], root)
    assert not list((root / "locations").glob("*.yaml")) and not (root / "scenes/001_a").exists()
    assert (root / "cache/swissalti/1.tif").exists() and program_ok(root)


def test_start_fresh_backup_and_restore():
    root = make_data()
    zf = root / "backups" / "b.zip"
    r = hk.backup(zf, hk.backup_kinds(), root)
    assert r["files"] > 5 and zf.exists()
    hk.clear(list(hk.KINDS), root)                                                  # everything: start fresh
    assert program_ok(root) and zf.exists()                                         # the program and backups stay
    assert sum(hk.sizes(root).values()) <= 2                                       # (an empty scenes list)
    out = hk.restore(zf, root)
    assert out["restored"] == r["files"] and out["refused"] == 0
    assert (root / "locations/001_a.yaml").exists() and (root / "logs/flight1.csv").exists()
    assert json.loads((root / "launcher.json").read_text())["port"] == 8123
    # without the scenes in the backup, the location is "not built" but its flights come back on the next build
    assert not (root / "scenes/001_a/scene.json").exists()
    assert [t["name"] for t in json.loads((root / "scenes/001_a/flights.json").read_text())["tracks"]] == ["flight1", "001_a_sim_2026"]
    from fpv3d.scene import previous_tracks
    redo, keep = previous_tracks(None, root / "scenes/001_a", [])
    assert {t["name"] for t in keep} == {"flight1", "001_a_sim_2026"} and not redo
    again = hk.restore(zf, root)                                                    # restoring twice: yours are kept
    assert again["restored"] == 0 and again["kept"] == r["files"]


def test_restore_refuses_unsafe_entries():
    root = make_data()
    bad = root / "evil.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr(hk.BACKUP_TAG, json.dumps(dict(kinds=["locations"])))
        for name in ("../outside.txt", "C:/Windows/x.txt", "/etc/x", "fpv3d/core.py", "launcher.pyw",
                     "locations/../../outside2.txt", "logs\\..\\..\\x.txt", "locations/ok.yaml"):
            z.writestr(name, "evil")
    out = hk.restore(bad, root, replace=True)
    assert out == dict(restored=1, kept=0, refused=7)
    assert program_ok(root) and not (root.parent / "outside.txt").exists() and not (root.parent / "outside2.txt").exists()
    try:
        hk.read_backup(root / "launcher.json")
        raise AssertionError("not a zip")
    except ValueError:
        pass


def test_clear_refused_while_building():
    from fpv3d.buildlock import scene_lock
    root = make_data()
    with scene_lock(root / "scenes", "001_a"):
        try:
            hk.clear(["cache"], root)
            raise AssertionError("should be refused")
        except RuntimeError as ex:
            assert "001_a" in str(ex)
        hk.clear(["applogs"], root)                                                  # harmless kinds still work
    assert (root / "cache/swissalti/1.tif").exists()


def test_build_stops_without_disk_space():
    from fpv3d import scene
    real = hk.free_bytes
    try:
        hk.free_bytes = lambda p=None: 500_000_000                                  # 500 MB free
        try:
            scene.check_disk(dict(scene_mb=400), Path("."), Path("."))
            raise AssertionError("should stop")
        except scene.NoSpace as ex:
            assert "not enough disk space" in str(ex)
        scene.check_disk(dict(scene_mb=1), Path("."), Path("."))                     # small builds go on
    finally:
        hk.free_bytes = real


def test_pages_report_errors_to_the_log():
    from test_server import req
    from fpv3d import server
    f = errorlog.log_file()
    old = f.read_text(encoding="utf-8") if f.exists() else None
    try:
        server.CLIENT_ERRORS.clear()
        st, _, _ = req("POST", "/api/client-error", dict(page="/viewer/?scene=x", message="TypeError: x is undefined", stack="at app.js:1"))
        assert st == 200 and "viewer /viewer/?scene=x: TypeError: x is undefined" in f.read_text(encoding="utf-8")
        codes = [req("POST", "/api/client-error", dict(message=f"m{i}"))[0] for i in range(40)]
        assert codes.count(429) >= 10                                                # a page in a loop can't fill the disk
    finally:
        server.CLIENT_ERRORS.clear()
        if old is None:
            f.unlink(missing_ok=True)
        else:
            f.write_text(old, encoding="utf-8")


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  ok    {name}")
            except Exception as ex:                         # noqa: BLE001
                fails += 1; print(f"  FAIL  {name}: {ex!r}")
    sys.exit(1 if fails else 0)
