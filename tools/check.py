"""The quick check before each commit:  python tools/check.py      (about 10 s)

  1. ruff      style and likely bugs (unused names, undefined names, risky patterns)
  2. pytest    every test in tests/ that needs no browser
Run automatically before each `git commit` after:  python tools/install_hooks.py
Skip once with `git commit --no-verify` (e.g. to save half-finished work).
Missing tools are reported, not fatal: pip install -r requirements-dev.txt
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(name, cmd):
    print(f"-- {name}", flush=True)
    try:
        return subprocess.call(cmd, cwd=ROOT)
    except FileNotFoundError:
        print(f"   (skipped: {cmd[0]} not installed - pip install -r requirements-dev.txt)")
        return 0


def has(mod):
    return subprocess.call([sys.executable, "-c", f"import {mod}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def main():
    bad = []
    ruff = shutil.which("ruff")
    if ruff or has("ruff"):
        if run("ruff", ([ruff] if ruff else [sys.executable, "-m", "ruff"]) + ["check", "."]):
            bad.append("ruff")
    else:
        print("-- ruff (skipped: not installed - pip install -r requirements-dev.txt)")
    if has("pytest"):
        if run("pytest", [sys.executable, "-m", "pytest", "-x", "-q", "tests"]):
            bad.append("tests")
    else:
        print("-- pytest (skipped: not installed); running the basic checks instead")
        if run("tests", [sys.executable, str(ROOT / "tests" / "run_all.py")]):
            bad.append("tests")
    print("OK" if not bad else f"FAILED: {', '.join(bad)} (commit anyway with: git commit --no-verify)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
