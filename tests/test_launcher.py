"""The launcher: what it detects on USB, its map maths, and its window layout.   python -m pytest tests/test_launcher.py

The USB and map parts need no screen. The layout check opens the real launcher window (in a separate Python, with a
fresh data folder) and is skipped where there is no screen or no Tk (e.g. a server)."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fpv3d.devices import Watcher, classify, drone_text, is_usb  # noqa: E402
from fpv3d.launcher_tiles import CH_BOX, group_points, in_wide, merc, tile_range, view_zoom, zoom_for_scale  # noqa: E402

BF = dict(port="COM7", firmware="Betaflight 4.5.1", board="FLWO", flash_ready=True, flash_total=16 * 2 ** 20, flash_used=3 * 2 ** 20)


# ------------------------------------------------------------ USB devices
def test_classify():
    assert classify("COM7", "STM32 VCP", lambda d: True, lambda d: dict(BF))["kind"] == "drone"
    assert classify("COM5", "EdgeTX", lambda d: True, lambda d: None) == dict(kind="radio", port="COM5", name="EdgeTX")
    assert classify("COM6", "", lambda d: False, lambda d: dict(BF)) == dict(kind="busy", port="COM6", name="COM6")

    def boom(d):
        raise OSError("access denied")
    assert classify("COM6", "x", boom, lambda d: None)["kind"] == "busy"        # can't open = busy, not a crash
    assert classify("COM6", "x", lambda d: True, boom)["kind"] == "radio"       # probe error = not Betaflight
    assert is_usb("USB VID:PID=0483:5740 SER=1") and not is_usb("ACPI\\PNP0501") and not is_usb("")


def test_watcher_follows_plugging():
    held = {"COM5"}                                         # e.g. a live flight holds the radio
    probes = []

    def probe(dev):
        probes.append(dev)
        return dict(BF, port=dev) if dev == "COM7" else None
    w = Watcher(lambda d: d not in held, probe)
    usb = "USB VID:PID=0483:5740"
    ch, new = w.update([("COM1", "ACPI", "serial"), ("COM5", usb, "radio"), ("COM7", usb, "fc")])
    assert ch and [d["port"] for d in new] == ["COM7"] and "COM1" not in w.known
    assert w.known["COM5"]["kind"] == "busy"
    ch, new = w.update([("COM5", usb, "radio"), ("COM7", usb, "fc")])
    assert not ch and not new and probes.count("COM7") == 1              # asked once, not every few seconds
    held.clear()
    ch, _ = w.update([("COM5", usb, "radio"), ("COM7", usb, "fc")])
    assert ch and w.known["COM5"]["kind"] == "radio"                      # free again: now recognised
    ch, _ = w.update([("COM5", usb, "radio")], paused=True)               # drone unplugged during a download
    assert ch and "COM7" not in w.known
    n = len(probes)
    w.update([("COM5", usb, "radio"), ("COM9", usb, "new")], paused=True)
    assert len(probes) == n and "COM9" not in w.known                     # nothing is probed while paused


def test_drone_text():
    t, d = drone_text(dict(BF))
    assert "FLWO" in t and "COM7" in t and d == "blackbox: 3.0 of 16 MB used"
    assert drone_text(dict(BF, flash_used=0))[1].endswith("(empty)")
    assert drone_text(dict(port="COM7", board="X", firmware="Y"))[1] == "blackbox on an SD card"


# ------------------------------------------------------------ map maths
def test_groups():
    pts = [("a", (100, 100)), ("b", (110, 104)), ("c", (300, 300)), ("d", (115, 98))]
    g = group_points(pts, 22)
    assert sorted(len(x["m"]) for x in g) == [1, 3]
    big = next(x for x in g if len(x["m"]) == 3)
    assert abs(big["p"][0] - 108.3) < 0.1 and abs(big["p"][1] - 100.7) < 0.1
    assert len(group_points(pts, 1)) == 4 and group_points([], 22) == []


def test_zoom_for_scale():
    assert zoom_for_scale(0.4) == 9 and zoom_for_scale(1.0) == 9               # overview is enough
    assert zoom_for_scale(1.5) == 10 and zoom_for_scale(4) == 11
    assert zoom_for_scale(100) == 13                                          # never past the deepest tiles


def test_world_tiles():
    """Outside Switzerland and its neighbours the map is the satellite picture: which tiles, at which zoom."""
    assert view_zoom(0.4, True) == 9 and view_zoom(1.5, True) == 10 and view_zoom(100, True) == 13   # as before, inside
    assert view_zoom(0.4, False) == 8 and view_zoom(0.01, False) == 3 and view_zoom(0.0001, False) == 2   # the world
    assert view_zoom(4, False) == 11                                          # zoomed in abroad: the same detail
    bern = [int(v // 256) for v in merc(7.4474, 46.948, 12)]
    innsbruck = [int(v // 256) for v in merc(11.39, 47.26, 12)]               # just inside the overview's east edge
    tokyo = [int(v // 256) for v in merc(139.7, 35.6, 12)]
    assert in_wide(12, *bern) and in_wide(12, *innsbruck) and not in_wide(12, *tokyo)
    assert not in_wide(3, 4, 2)                                               # a tile bigger than the overview: satellite
    # zoomed far out the whole world is satellite, Switzerland included: no tile below zoom 8 is a map tile,
    # while at zoom 8 the ones over Switzerland still are
    assert not any(in_wide(z, x, y) for z in range(2, 8) for x in range(2 ** z) for y in range(2 ** z))
    assert in_wide(8, *[int(v // 256) for v in merc(8.2, 46.8, 8)])
    assert not in_wide(9, *[int(v // 256) for v in merc(11.95, 47.0, 9)])     # past the east edge


def test_border_mask_is_filled(tmp=None):
    """swisstopo's border layer only draws the outline at the overview's zoom: the launcher fills it, so the map shows
    inside Switzerland and the satellite picture around it. A fake ring around Bern stands for the border."""
    import tempfile
    from pathlib import Path
    from PIL import Image, ImageDraw
    from fpv3d import launcher_tiles as lt
    cx, cy = merc(7.4474, 46.948, lt.ZOV)

    def fake(key, z, x, y, timeout=10):
        t = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        ImageDraw.Draw(t).ellipse([cx - 300 - x * 256, cy - 200 - y * 256, cx + 300 - x * 256, cy + 200 - y * 256],
                                  outline=(255, 0, 0, 255), width=2)
        return t
    old, lt.fetch = lt.fetch, fake
    try:
        m = lt.Tiles(Path(tmp or tempfile.mkdtemp())).overview_mask(workers=2)
    finally:
        lt.fetch = old
    gx0, gy0 = merc(lt.WIDE[0], lt.WIDE[3], lt.ZOV)
    at = lambda lat, lon: m.getpixel(tuple(int(v - o) for v, o in zip(merc(lon, lat, lt.ZOV), (gx0, gy0))))  # noqa: E731
    assert at(46.948, 7.4474) == 255 and at(48.14, 11.58) == 0 and at(45.46, 9.19) == 0    # Bern in, Munich and Milan out
    assert m.size == (round(merc(lt.WIDE[2], 0, lt.ZOV)[0] - gx0), round(merc(0, lt.WIDE[1], lt.ZOV)[1] - gy0))


def test_tiles_cover_switzerland():
    x0, y0, x1, y1 = tile_range(CH_BOX, 9)
    assert (x1 - x0 + 1) * (y1 - y0 + 1) < 80                                 # overview stays a small download
    gx, gy = merc(7.4474, 46.948, 9)                                          # Bern is inside
    assert x0 <= gx // 256 <= x1 and y0 <= gy // 256 <= y1


# ------------------------------------------------------------ the window (real Tk)
LAYOUT = r"""
import json, os, runpy, sys, tkinter as tk
out = {}
try:
    g = runpy.run_path(os.path.join(sys.argv[1], "launcher.pyw"), run_name="launcher_test")
    root = tk.Tk(); g["paths"].ensure_data()
    app = g["Launcher"](root)
    app.start_device_watch = lambda: None
    root.geometry("980x600+0+0"); app.show_page("map")
    def check():
        # an error in here must end the window: Tk would only print it and keep waiting (a 120 s time-out)
        try:
            root.update()
            W0, H0 = root.winfo_width(), root.winfo_height()
            m = app.map
            cw, ch = m.cv.winfo_width(), m.cv.winfo_height()
            boxes = {}
            for name, w in (("list", m.listp), ("bar", m.bar), ("zoom", m.zbox)):
                boxes[name] = (w.winfo_x(), w.winfo_y(), w.winfo_x() + w.winfo_width(), w.winfo_y() + w.winfo_height())
            out["inside"] = all(0 <= b[0] and 0 <= b[1] and b[2] <= cw and b[3] <= ch for b in boxes.values())
            ov = lambda a, b: a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
            out["overlap"] = [f"{a}/{b}" for a in boxes for b in boxes if a < b and ov(boxes[a], boxes[b])]
            # things that change must not change the window's size
            app.say("a very long message " * 20, "bad")
            app.server_pill.set("server full :8000 → lite and much more text", "#3ddc84")
            app.map.card.title.set("001 · " + "A VERY LONG LOCATION NAME " * 6)
            app.map.info.set("hover text " * 30)
            app._devices_changed({"COM7": dict(kind="drone", port="COM7", board="FLWO", firmware="Betaflight 4.5.1 " * 4,
                                               flash_total=2 ** 24, flash_used=2 ** 20)})
            for p in ("home", "drone", "phone", "disk", "settings", "map"):
                app.show_page(p); root.update()
            out["size_kept"] = (root.winfo_width(), root.winfo_height()) == (W0, H0)
            app.select(None); root.update()
            out["callout_hidden_when_none"] = not m.card.frame.winfo_ismapped()
        except Exception as ex:
            import traceback
            out["error"] = repr(ex) + " " + traceback.format_exc()[-600:]
        finally:
            root.destroy()
    root.after(1500, check)
    root.mainloop()
except Exception as ex:
    out["error"] = repr(ex)
print("RESULT " + json.dumps(out))
from launcher.main import leave
leave()           # as the launcher does after its window closed: the map download may still be running
"""


def _can_show_windows():
    if os.environ.get("ALPLINE_NO_WINDOW_TEST"):
        return False
    if sys.platform != "win32" and not os.environ.get("DISPLAY"):
        return False
    return subprocess.call([sys.executable, "-c", "import tkinter; tkinter.Tk().destroy()"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def test_window_layout_stays_put():
    _layout_check("game")


def test_window_layout_stays_put_terminal_look():
    """The same checks in the terminal look (other fonts in places, the home page as a list)."""
    _layout_check("terminal")


def _layout_check(look):
    if os.environ.get("ALPLINE_NO_WINDOW_TEST"):
        print("  (left out when run from the launcher: it opens a second launcher window. python -m pytest runs it: skipped)")
        return
    if not _can_show_windows():
        print("  (no screen / Tk here: skipped)")
        return
    data = Path(tempfile.mkdtemp(prefix="alpline_launcher_"))
    (data / "locations").mkdir()
    for i, (la, lo) in enumerate(((46.55, 7.02), (46.551, 7.021), (46.0, 7.75)), 1):
        (data / "locations" / f"00{i}_loc.yaml").write_text(
            f"name: 00{i}_loc\ntitle: \"Location {i} with a rather long name\"\ncenter: {{lat: {la}, lon: {lo}}}\n"
            "links:\n  - {name: v, freq_mhz: 5800, tx_power_dbm: 14}\n", encoding="utf-8")
    env = dict(os.environ, ALPLINE_DATA=str(data), ALPLINE_LOOK=look)
    script = data / "layout_check.py"
    script.write_text(textwrap.dedent(LAYOUT), encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(ROOT)], env=env, capture_output=True, text=True, timeout=120)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line, f"no result:\n{r.stdout[-800:]}\n{r.stderr[-800:]}"
    res = json.loads(line[7:])
    assert "error" not in res, res
    assert res["inside"], "a floating panel sticks out of the map at the smallest window size"
    assert not res["overlap"], f"panels overlap at the smallest size: {res['overlap']}"
    assert res["size_kept"], "long texts or messages changed the window's size"
    assert res["callout_hidden_when_none"]


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  ok    {name}")
            except Exception as ex:                         # noqa: BLE001
                fails += 1; print(f"  FAIL  {name}: {ex!r}")
    sys.exit(1 if fails else 0)


# ------------------------------------------------------------ start-up screen
def test_start_screen_picks_a_place_with_a_photo():
    """The game look shows the place selected last time, else the first built one that has a photo."""
    from PIL import Image
    from fpv3d import paths
    from launcher.startup import last_place
    data = Path(tempfile.mkdtemp(prefix="alpline_start_"))
    scenes = data / "scenes"
    for name, photo in (("001_a", False), ("002_b", True), ("003_c", True)):
        (scenes / name).mkdir(parents=True)
        (scenes / name / "scene.json").write_text(json.dumps(dict(name=name, title=name.upper())), encoding="utf-8")
        if photo:
            Image.effect_noise((200, 100), 60).convert("RGB").save(scenes / name / "ortho.jpg", quality=95)
    (scenes / "index.json").write_text(json.dumps([dict(name=n, title=n) for n in ("001_a", "002_b", "003_c")]), encoding="utf-8")
    old = paths.DATA
    try:
        paths.DATA = data
        assert last_place("003_c") == ("003_C", scenes / "003_c" / "ortho.jpg")
        assert last_place("001_a")[0] == "002_B"                     # selected one has no photo: first with one
        assert last_place("gone")[0] == "002_B"
        paths.DATA = data / "nothing"
        assert last_place(None) is None
    finally:
        paths.DATA = old


START = r"""
import json, os, runpy, sys, time, tkinter as tk
out = {}
try:
    g = runpy.run_path(os.path.join(sys.argv[1], "launcher.pyw"), run_name="launcher_test")
    from launcher.startup import StartScreen, MAX_S
    root = tk.Tk(); g["paths"].ensure_data()
    app = g["Launcher"](root)
    app.start_device_watch = lambda: None
    root.geometry("980x600+0+0")
    screens = {}
    for look in ("game", "terminal"):
        app.cfg["look"] = look
        screens[look] = StartScreen(root, app.cfg).attach(app)
        screens[look].run()
    clicked = StartScreen(root, app.cfg).attach(app)
    # shown: checked at once; by the time the loop below runs they may have done their steps and gone already
    out["shown"] = all(s.frame.winfo_exists() and not s.done and s.frame.winfo_manager() == "place" for s in screens.values())
    def check():
        try:
            root.update()
            clicked.frame.event_generate("<Button-1>", x=5, y=5); root.update()
            out["click_closes"] = clicked.done and not clicked.frame.winfo_exists()
            root.after(int(MAX_S * 1000) + 600, finish)
        except Exception as ex:
            import traceback
            out["error"] = repr(ex) + " " + traceback.format_exc()[-600:]; root.destroy()
    def finish():
        out["gone_in_time"] = all(s.done for s in screens.values())
        out["steps"] = screens["terminal"].steps
        root.destroy()
    root.after(300, check)
    root.mainloop()
except Exception as ex:
    out["error"] = repr(ex)
print("RESULT " + json.dumps(out))
from launcher.main import leave
leave()
"""


def test_start_screen_shows_and_goes():
    """Both looks of the start-up screen open over the window and go by themselves within MAX_S, or at a click."""
    if os.environ.get("ALPLINE_NO_WINDOW_TEST") or not _can_show_windows():
        print("  (no screen / Tk here, or run from the launcher: skipped)")
        return
    data = Path(tempfile.mkdtemp(prefix="alpline_start_"))
    script = data / "start_check.py"
    script.write_text(textwrap.dedent(START), encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(ROOT)], env=dict(os.environ, ALPLINE_DATA=str(data)),
                       capture_output=True, text=True, timeout=120)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line, f"no result:\n{r.stdout[-800:]}\n{r.stderr[-800:]}"
    res = json.loads(line[7:])
    assert "error" not in res, res
    assert res["shown"] and res["click_closes"] and res["gone_in_time"], res
    assert res["steps"][0].startswith("places") and res["steps"][-1] == "ready", res["steps"]


# ------------------------------------------------------------ home page (no screen needed)
def test_home_page_reads_a_scene():
    """The home page's numbers and the terminal look's relief come from the scene's own files."""
    import numpy as np
    from fpv3d import paths
    from launcher.home import LEVELS, relief, scene_facts
    data = Path(tempfile.mkdtemp(prefix="alpline_home_"))
    sd = data / "scenes" / "001_hill"
    sd.mkdir(parents=True)
    rows, cols = 50, 100                                    # 1000 x 500 m at 10 m, a hill in the east
    yy, xx = np.mgrid[0:rows, 0:cols]
    (1000 + 300 * np.exp(-((xx - 80) ** 2 + (yy - 25) ** 2) / 200)).astype("<f4").tofile(sd / "terrain.f32")
    (sd / "scene.json").write_text(json.dumps(dict(
        grid=dict(min_e=0, min_n=0, max_e=1000, max_n=500, res=10, rows=rows, cols=cols), terrain="terrain.f32",
        pilot=dict(x=100, y=250, ground=1000.4), links=[dict(range_m=2100)], ortho="ortho.jpg",
        los_layers=[dict(agl=10, blocked=.7), dict(agl=30, blocked=.4)], buildings=dict(count=12))), encoding="utf-8")
    old = paths.DATA
    try:
        paths.DATA = data
        f = scene_facts("001_hill")
        assert (f["width_km"], f["height_km"], f["res"], f["buildings"]) == (1.0, .5, 10, 12)
        assert abs(f["seen30"] - .6) < 1e-9 and f["range_km"] == 2.1 and round(f["ground"]) == 1000
        levels, at = relief("001_hill", 40)
        assert levels.shape == (20, 40) and 0 <= levels.min() and levels.max() <= LEVELS - 1   # square cells
        assert levels[10, 30] > levels[10, 34]                  # the hill's west face, lit from the west, is brighter
        assert levels[10, 2] == levels[10, 6]                   # flat ground: one even shade
        assert at == (4, 10)                                    # the pilot, 10 % from the west, mid-height
        assert scene_facts("nothing") == {} and relief("nothing", 40) is None
    finally:
        paths.DATA = old
