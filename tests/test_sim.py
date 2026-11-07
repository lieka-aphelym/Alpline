"""The training flight's flight model:   python -m pytest tests/test_sim.py   (runs tests/test_sim.mjs with Node)

Hover throttle, battery (empties in its time, sags, an empty pack can't hover), top speed close to the setting,
drag through the prop disk, ground effect, propwash, Betaflight throttle mid/expo, walls and ground."""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def test_flight_model():
    node = shutil.which("node")
    if not node:
        print("  (Node not installed: skipped)")
        return
    r = subprocess.run([node, str(HERE / "test_sim.mjs")], capture_output=True, text=True, timeout=120, cwd=HERE.parent)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]


if __name__ == "__main__":
    test_flight_model(); print("  ok    test_flight_model")
    sys.exit(0)
