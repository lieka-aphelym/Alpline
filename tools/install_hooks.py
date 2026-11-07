"""Run tools/check.py before every `git commit` in this folder:  python tools/install_hooks.py
(writes .git/hooks/pre-commit; run again after cloning the project elsewhere. Remove the file to stop it.)"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
hook = ROOT / ".git" / "hooks" / "pre-commit"
if not hook.parent.exists():
    sys.exit("no .git folder here: is this the project folder?")
py = Path(sys.executable).as_posix()
hook.write_text(f'#!/bin/sh\n# Alpline: quick check before each commit (tools/check.py). Skip once: git commit --no-verify\n'
                f'"{py}" tools/check.py\n', encoding="utf-8", newline="\n")
os.chmod(hook, 0o755)
print(f"installed: {hook}  (uses {py})")
