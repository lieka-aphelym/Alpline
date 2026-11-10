"""How much of the code do the tests run?   python tools/cover.py      (about a minute)

The journey tests start the real commands (build, add-log, blackbox...) as separate programs. Plain `pytest --cov`
does not see those, and reports 0 % for the command line. This script measures both: the tests themselves and every
command they start, then prints one table (and writes htmlcov/index.html to browse line by line).
Needs: pip install -r requirements-dev.txt
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    for f in ROOT.glob(".coverage*"):
        f.unlink()
    env = dict(os.environ, ALPLINE_COV="1")
    cov = [sys.executable, "-m", "coverage"]
    code = subprocess.call(cov + ["run", "--parallel-mode", "-m", "pytest", "-q", "tests"], cwd=ROOT, env=env)
    subprocess.call(cov + ["combine", "-q"], cwd=ROOT)
    subprocess.call(cov + ["html", "-q"], cwd=ROOT)
    subprocess.call(cov + ["report", "--sort=cover"], cwd=ROOT)
    print("line by line: htmlcov/index.html")
    return code


if __name__ == "__main__":
    sys.exit(main())
