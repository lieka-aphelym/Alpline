"""Run every Alpline check:   python tests/run_all.py   [--browser]      (pytest does 1-2 too: python -m pytest)

  1. python      every tests/test_*.py: basics, server, security, robustness, journeys, snapshots, launcher
  2. (same)      without pytest installed, each test function is run here one by one
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
    try:
        import pytest  # noqa: F401
        print("1. python checks (pytest)")
        results["python"] = subprocess.call([sys.executable, "-m", "pytest", "-q", str(HERE)], cwd=ROOT)
    except ImportError:
        for f in sorted(HERE.glob("test_*.py")):
            print(f"1. {f.stem[5:]}"); results[f.stem[5:]] = run_module(f.stem)
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
