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


def test_restore_refuses_oversized_entries():
    root = make_data()
    big = root / "big.zip"
    with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(hk.BACKUP_TAG, json.dumps(dict(kinds=["flights"])))
        z.writestr("logs/huge.csv", "0" * 5_000_000)
        z.writestr("logs/small.csv", "ok")
    old = hk.MAX_ENTRY
    try:
        hk.MAX_ENTRY = 1_000_000
        out = hk.restore(big, root)
    finally:
        hk.MAX_ENTRY = old
    assert out["restored"] == 1 and out["refused"] == 1
    assert not (root / "logs" / "huge.csv").exists() and (root / "logs" / "small.csv").read_text() == "ok"
    assert not list((root / "logs").glob(".*.tmp"))


def test_error_log_hides_the_home_folder():
    home = str(Path.home())
    text = errorlog._private(f'File "{home}{os.sep}proj{os.sep}x.py", line 3')
    assert home not in text and text.startswith('File "~')


def test_weekly_backup_keeps_the_newest_five():
    import time
    root = make_data()
    t0 = time.time()
    made = []
    for week in range(8):
        f = hk.auto_backup(root, now=t0 + week * 7 * 86400 + 60)
        assert f is not None, week
        os.utime(f, (t0 + week * 7 * 86400 + 60,) * 2)            # as if made that week
        made.append(f.name)
    assert len(set(made)) == 8 and [f.name for f in hk.auto_backups(root)] == sorted(made)[-5:]
    assert hk.auto_backup(root, now=t0 + 7 * 7 * 86400 + 3 * 86400) is None      # 3 days later: not yet
    info = hk.read_backup(hk.auto_backups(root)[-1])
    assert "scenes" not in info["kinds"] and any(n.startswith("locations/") for n in info["names"])
    fresh = Path(tempfile.mkdtemp(prefix="alpline_fresh_"))
    assert hk.auto_backup(fresh) is None                           # nothing of yours yet: no empty backup


def test_library_check_reads_the_pins():
    from fpv3d import deps
    d = Path(tempfile.mkdtemp())
    req = d / "requirements.txt"
    req.write_text("# comment\nnumpy==0.0.1\nnot-a-real-lib==1.0   # optional: nothing\nalso-missing==2.0\n", encoding="utf-8")
    diff = {x["name"]: x for x in deps.differences(req)}
    assert diff["numpy"]["want"] == "0.0.1" and diff["numpy"]["have"] not in (None, "0.0.1")
    assert "not-a-real-lib" not in diff and diff["also-missing"]["have"] is None
    assert deps.differences(HERE.parent / "requirements.txt") is not None and deps.differences(d / "none.txt") == []


def test_scene_files_hold_no_full_paths():
    """A log inside the Alpline folder is written down relative to it: no user name in scene files or backups, and a
    restore on another PC still finds the log. Scene files of older versions are rewritten."""
    from fpv3d import paths, scene
    root = make_data()
    old = paths.DATA
    try:
        paths.DATA = root
        log = root / "logs" / "flight1.csv"
        assert paths.portable(log) == "logs/flight1.csv" and paths.from_portable("logs/flight1.csv") == root / "logs" / "flight1.csv"
        outside = Path(tempfile.mkdtemp()) / "elsewhere.csv"
        assert paths.portable(outside) == str(outside)                          # not yours to shorten
        # written by an older version on Windows, and on this system under another folder
        win = "C:\\Users\\somebody\\PycharmProjects\\fpv3d\\logs\\flight1.csv"
        assert paths.from_portable(win) == log and paths.from_portable("/old/home/x/logs/blackbox/2026/a.csv") == root / "logs/blackbox/2026/a.csv"
        sj = root / "scenes" / "001_a" / "scene.json"
        meta = json.loads(sj.read_text(encoding="utf-8"))
        meta["tracks"] = [dict(name="flight1", file="tracks/flight1.json", source=win),
                          dict(name="gone", file="tracks/gone.json", source="C:\\Users\\somebody\\x\\logs\\sim\\001_a\\gone.csv"),
                          dict(name="ext", file="tracks/ext.json", source=str(outside)), dict(name="cfg", file="t.json", source="config")]
        sj.write_text(json.dumps(meta), encoding="utf-8")
        outside.write_text("x", encoding="utf-8")
        assert scene.make_sources_portable(root / "scenes") == 2
        srcs = [t["source"] for t in json.loads(sj.read_text(encoding="utf-8"))["tracks"]]
        assert srcs == ["logs/flight1.csv", "logs/sim/001_a/gone.csv", str(outside), "config"]
        assert "somebody" not in sj.read_text(encoding="utf-8") and scene.make_sources_portable(root / "scenes") == 0
    finally:
        paths.DATA = old


def test_app_name_in_one_place():
    from fpv3d import brand, paths
    base = Path(tempfile.mkdtemp())
    old = (paths.APP_NAME, paths.EARLIER_NAMES)
    try:
        paths.APP_NAME, paths.EARLIER_NAMES = "Newname", ("Alpline",)
        assert paths._named(base) == base / "Newname"                           # a new install: the new name
        (base / "Alpline").mkdir()
        assert paths._named(base) == base / "Alpline"                           # your existing folder is still found
        (base / "Newname").mkdir()
        assert paths._named(base) == base / "Newname"
    finally:
        paths.APP_NAME, paths.EARLIER_NAMES = old
    assert brand.APP_NAME in brand.APP_ID and brand.APP_NAME in brand.EARLIER_NAMES
    # no user-visible text spells the name itself any more (comments, docstrings and internal file names aside)
    import re
    bad = []
    keep = re.compile(r'Alpline\.exe|Alpline\.bat|Alpline \(phone\)|"Alpline"|^\s*#|alpline')
    for f in [*sorted((HERE.parent / "launcher").glob("*.py")), *sorted((HERE.parent / "fpv3d").glob("*.py"))]:
        if f.name in ("brand.py",):
            continue
        doc = False
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.count('"""') == 1:
                doc = not doc
                continue
            if doc or line.count('"""') == 2:
                continue
            code = line.split("  #")[0]
            if re.search(r"[\"'][^\"']*Alpline", code) and not keep.search(code):
                bad.append(f"{f.name}:{i}: {line.strip()[:90]}")
    assert not bad, "\n".join(bad)


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


def test_older_project_moves_into_data():
    """An older source folder kept your files next to the code: the first start moves them into data/, untouched."""
    from fpv3d import paths
    root = Path(tempfile.mkdtemp(prefix="alpline_move_"))
    (root / "fpv3d").mkdir(); (root / "fpv3d" / "x.py").write_text("code")
    (root / "locations").mkdir(); (root / "locations" / "001_a.yaml").write_text("loc")
    (root / "logs" / "blackbox").mkdir(parents=True); (root / "logs" / "blackbox" / "f.bbl").write_text("bb")
    (root / "launcher.json").write_text("{}")
    data = paths._move_into_data(root)
    assert data == root / "data"
    assert (data / "locations" / "001_a.yaml").read_text() == "loc"
    assert (data / "logs" / "blackbox" / "f.bbl").read_text() == "bb" and (data / "launcher.json").exists()
    assert not (root / "locations").exists() and (root / "fpv3d" / "x.py").exists()
    assert paths._move_into_data(root) == data                      # second start: nothing to do


def test_move_into_data_rolls_back():
    """If one item cannot move, the ones already moved go back and the old place is used this time."""
    from fpv3d import paths
    root = Path(tempfile.mkdtemp(prefix="alpline_move_"))
    for n in ("locations", "scenes", "logs"):
        (root / n).mkdir(); (root / n / "f").write_text(n)
    real = Path.rename

    def rename(self, target):
        if self.name == "logs" and Path(target).parent.name == "data":
            raise PermissionError("in use")
        return real(self, target)
    Path.rename = rename                                            # one folder "in use" (like a file open in Windows)
    try:
        assert paths._move_into_data(root) == root
    finally:
        Path.rename = real
    for n in ("locations", "scenes", "logs"):
        assert (root / n / "f").read_text() == n


def test_quick_check_can_run_every_test():
    """The launcher's [run quick check] calls each test with no arguments (no pytest helpers such as tmp_path):
    a test that needs one would fail there while passing under pytest."""
    import ast
    bad = []
    for f in sorted(HERE.glob("test_*.py")):
        for n in ast.parse(f.read_text(encoding="utf-8")).body:
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_"):
                a = n.args
                if len(a.args) > len(a.defaults):
                    bad.append(f"{f.name}: {n.name}")
    assert not bad, bad
