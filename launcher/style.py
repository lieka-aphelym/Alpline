"""Colours, fonts and screen scaling of the launcher, in its two looks (settings key "look", read once at start):

    game      the viewer's dark theme (viewer/css/theme.css), pictures first
    terminal  one amber colour on near-black, everything in monospace (like the amber start-up screen)

Every page imports these names, so the look is fixed for the life of the window: switching it in the settings
restarts the launcher (settings.py). ALPLINE_LOOK in the environment overrides the setting (tests)."""
from __future__ import annotations

import json
import os


def _look() -> str:
    if os.environ.get("ALPLINE_LOOK") in ("game", "terminal"):
        return os.environ["ALPLINE_LOOK"]
    try:
        from fpv3d import paths
        return json.loads((paths.DATA / "launcher.json").read_text(encoding="utf-8")).get("look", "game")
    except Exception:                                      # noqa: BLE001  (no settings yet: the default look)
        return "game"


LOOK = _look()
LOOK = LOOK if LOOK in ("game", "terminal") else "game"
TERMINAL = LOOK == "terminal"

if TERMINAL:
    BG, BG2, BG3, FG, FG2, RULE, ACC = "#0b0700", "#150e03", "#231808", "#f2a900", "#c08a1e", "#4a3410", "#ffc640"
    OK, WARN, BAD = "#ffd27a", "#ff8c1a", "#ff5c4d"         # one colour family: bright, orange, red
    GREY, RULE2 = "#8a6418", "#6b4a12"
    SANS = ("Consolas", 10)
else:
    # colours of the viewer's dark theme
    BG, BG2, BG3, FG, FG2, RULE, ACC = "#07090c", "#10141a", "#171c24", "#f2f5f8", "#a9b4c2", "#2a313c", "#ffd60a"
    OK, WARN, BAD = "#3ddc84", "#ffb000", "#ff6b6b"      # the same three status colours as the pages
    GREY, RULE2 = "#7d8796", "#4a5462"                   # GREY: quiet text; RULE2: control borders
    SANS = ("Segoe UI", 10)
MONO = ("Consolas", 10)
MONO_S = ("Consolas", 9)                             # notes, pills, small buttons (the smallest text there is)
MONO_B = ("Consolas", 10, "bold")
UI = 1.0                                             # screen scaling (1.5 on a 150 % Windows display), set at start


def S(v: float) -> int:
    """pixel size scaled for the screen (fonts in points scale by themselves)"""
    return round(v * UI)
