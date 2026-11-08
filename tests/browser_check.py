"""Saved browser check: opens the main pages in a hidden browser, the way you would, and reports page errors.

    python tests/browser_check.py [--scene NAME] [--show]

Needs playwright once:  pip install playwright   then   python -m playwright install chromium   (about 150 MB)
Uses your own scenes folder (read only: nothing is built or changed). Screenshots go to logs/checks/.
"""
import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(pg, js, seconds):
    """Like wait_for_function, but evaluated from outside: the pages' security policy forbids running strings as code."""
    import time
    end = time.time() + seconds
    while not pg.evaluate(js):
        if time.time() > end:
            raise TimeoutError(f"waited {seconds} s for: {js}")
        pg.wait_for_timeout(250)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", help="location to open (default: the first one that is built)")
    ap.add_argument("--scenes", default=str(ROOT / "scenes"))
    ap.add_argument("--show", action="store_true", help="show the browser window")
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  (skipped: playwright is not installed:  pip install playwright  then  python -m playwright install chromium)")
        return 0
    scenes = Path(a.scenes)
    scene = a.scene or next((d.name for d in sorted(scenes.iterdir()) if (d / "scene.json").exists()), None) if scenes.exists() else a.scene
    port = free_port()
    env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
    srv = subprocess.Popen([sys.executable, "-m", "fpv3d.cli", "--scenes", str(scenes), "serve", "--port", str(port), "--no-browser"],
                           cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/api/mode.js", timeout=1); break
        except OSError:
            time.sleep(0.25)
    out = ROOT / "logs" / "checks"; out.mkdir(parents=True, exist_ok=True)
    pages = [("checks", "/viewer/test/index.html", None), ("map", "/viewer/map.html", "#map .leaflet-pane"),
             ("share", "/viewer/share.html", None), ("packs", "/viewer/packs.html", "#flights")]
    if scene:
        pages += [("viewer", f"/viewer/?scene={scene}", "LOADED"),
                  ("viewer lite", f"/viewer/?scene={scene}&mode=lite", "LOADED")]
    else:
        print("  (no built location found: the 3D viewer is not checked)")
    fails = 0
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=not a.show, args=["--proxy-server=direct://", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
            for name, path, ready in pages:
                pg = b.new_page(viewport={"width": 1400, "height": 900})
                errors = []
                pg.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                offline = []                             # tiles / zones that did not download: no internet is not a program error
                pg.on("console", lambda m, errors=errors, offline=offline: (offline if "Failed to load resource" in m.text else errors).append(m.text)
                      if m.type == "error" and "favicon" not in m.text else None)
                try:
                    pg.goto(base + path, wait_until="load", timeout=30000)
                    if ready == "LOADED":                # the viewer removes #loading when the scene is up (error: it stays, red)
                        wait_until(pg, "!document.getElementById('loading') || "
                                   "document.getElementById('loading').classList.contains('err')", 90)
                        if pg.evaluate("!!document.getElementById('loading')"):
                            errors.append("viewer: " + pg.inner_text("#loading"))
                    elif ready:
                        pg.wait_for_selector(ready, state="attached", timeout=90000)
                    if name == "viewer" and ready == "LOADED" and not pg.evaluate("!!document.getElementById('loading')"):
                        # a short training flight: start, arm, climb, fly forward, and the flight model / OSD run
                        pg.click('button[data-tab="fly"]'); pg.click("#simStart"); pg.wait_for_timeout(300)
                        pg.keyboard.press("Enter"); pg.keyboard.down("KeyW"); pg.wait_for_timeout(2500); pg.keyboard.up("KeyW")
                        pg.keyboard.down("ArrowUp"); pg.wait_for_timeout(800); pg.keyboard.up("ArrowUp")
                        sim = pg.evaluate("() => { const st = window.fpv3d.SIM._state; return { armed: st.armed, v: st.vel.length(), "
                                          "osd: document.getElementById('simOsd').innerText } }")
                        if not sim["armed"] or "BAT" not in sim["osd"]:
                            errors.append(f"training flight did not run: {sim}")
                        pg.screenshot(path=str(out / "training_flight.png"))
                        pg.keyboard.press("Escape")
                    if name == "checks":
                        wait_until(pg, "document.title.includes('passed') || document.title.includes('FAILED')", 30)
                        if "FAILED" in pg.title():
                            errors.append(pg.title())
                    pg.wait_for_timeout(1500)
                    if pg.evaluate("!!document.querySelector('.alpOops')"):       # the page's own error notice
                        errors.append("error notice on the page: " + pg.inner_text(".alpOops"))
                    pg.screenshot(path=str(out / f"{name.replace(' ', '_')}.png"))
                except Exception as ex:                    # noqa: BLE001
                    errors.append(f"{ex.__class__.__name__}: {str(ex).splitlines()[0]}")
                print(f"  {'ok  ' if not errors else 'FAIL'}  {name:12} {path}" + "".join(f"\n        {e}" for e in errors[:5])
                      + (f"   ({len(offline)} downloads failed: offline?)" if offline else ""))
                fails += bool(errors)
                pg.close()
            b.close()
    finally:
        srv.terminate()
    print(f"  screenshots: {out}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
