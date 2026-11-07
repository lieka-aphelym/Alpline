"""The quick check, one line per test, for the launcher's checks page:   python tests/run_quick.py

Runs every test function of tests/test_*.py directly (no pytest needed). Each result is printed as
    RESULT <tab> group <tab> test <tab> ok|fail|skip <tab> seconds <tab> message
(message: the error for a failure, newlines as \\x1f). Ends with `DONE <tab> ok <tab> failed <tab> skipped`.
Nothing touches your own locations: the tests use temporary folders. The window test of the launcher is left out
here (it would open a second launcher while you look at the first)."""
import contextlib
import importlib
import io
import os
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
os.environ["ALPLINE_NO_WINDOW_TEST"] = "1"
ORDER = ["basic", "server", "security", "robust", "journeys", "snapshots", "performance", "sim", "launcher"]


def main():
    files = sorted(HERE.glob("test_*.py"), key=lambda f: (ORDER.index(f.stem[5:]) if f.stem[5:] in ORDER else 99, f.stem))
    plan = []
    for f in files:
        try:
            mod = importlib.import_module(f.stem)
        except Exception as ex:                              # noqa: BLE001 - a file that doesn't even load
            print(f"RESULT\t{f.stem[5:]}\t(loading)\tfail\t0\t{ex!r}", flush=True)
            continue
        plan += [(f.stem[5:], n, fn) for n, fn in vars(mod).items() if n.startswith("test_") and callable(fn)]
    print(f"PLAN\t{len(plan)}", flush=True)
    ok = bad = skip = 0
    for group, name, fn in plan:
        out = io.StringIO()
        t = time.time()
        try:
            with contextlib.redirect_stdout(out):
                fn()
            note = next((l.strip() for l in out.getvalue().splitlines()            # a test says "(... skipped)"
                         if l.strip().startswith("(") and "skipped" in l), None)
            state, msg = ("skip", note) if note else ("ok", "")
        except Exception as ex:                              # noqa: BLE001 - every failure is reported, the rest go on
            state = "fail"
            frames = traceback.extract_tb(ex.__traceback__)
            where = next((f for f in reversed(frames) if "fpv3d" in f.filename or "tests" in f.filename), frames[-1])
            msg = (f"{type(ex).__name__}: {ex}\n(at {Path(where.filename).name} line {where.lineno})")[-1500:]
        ok += state == "ok"; bad += state == "fail"; skip += state == "skip"
        print(f"RESULT\t{group}\t{name}\t{state}\t{time.time() - t:.2f}\t{msg.replace(chr(10), chr(31)).replace(chr(9), ' ')}",
              flush=True)
    print(f"DONE\t{ok}\t{bad}\t{skip}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
