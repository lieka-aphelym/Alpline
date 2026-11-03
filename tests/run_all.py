"""Run every Alpline check:   python tests/run_all.py   [--browser]

  1. basics      coordinates, log readers, radio maths, telemetry parser     (tests/test_basic.py)
  2. server      pages, refused requests, phone PIN, build lock, cache, https (tests/test_server.py)
  3. warnings    what the pilot sees and hears, radio range, file names       (viewer/test/cases.js)
                 needs Node (nodejs.org); without it, open http://localhost:8000/viewer/test/ while Alpline runs
  4. --browser   opens the real pages in a hidden browser and looks for errors (tests/browser_check.py, needs playwright)
"""
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))


def run_module(name):
    mod = importlib.import_module(name)
    fails = 0
    for n, fn in vars(mod).items():
        if n.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  ok    {n}")
            except Exception as ex:                       # noqa: BLE001  (report every failure, keep going)
                fails += 1; print(f"  FAIL  {n}: {ex!r}")
    return fails


def main():
    results = {}
    print("1. basics"); results["basics"] = run_module("test_basic")
    print("2. server"); results["server"] = run_module("test_server")
    print("3. warnings")
    node = shutil.which("node")
    if node:
        results["warnings"] = subprocess.call([node, str(HERE / "test_warn.mjs")], cwd=ROOT)
    else:
        print("  (skipped: Node is not installed. Open http://localhost:8000/viewer/test/ while Alpline runs instead.)")
    if "--browser" in sys.argv:
        print("4. pages in a browser")
        results["browser"] = subprocess.call([sys.executable, str(HERE / "browser_check.py")], cwd=ROOT)
    bad = [k for k, v in results.items() if v]
    print("\n" + ("ALL CHECKS PASSED" if not bad else f"FAILED: {', '.join(bad)}") + f"   ({', '.join(results)})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
