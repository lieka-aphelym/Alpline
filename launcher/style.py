"""Colours, fonts and screen scaling of the launcher: the same dark theme as the pages (viewer/css/theme.css)."""
from __future__ import annotations


# colours of the viewer's dark theme
BG, BG2, BG3, FG, FG2, RULE, ACC = "#07090c", "#10141a", "#171c24", "#f2f5f8", "#a9b4c2", "#2a313c", "#ffd60a"
MONO = ("Consolas", 10)
MONO_S = ("Consolas", 9)                             # notes, pills, small buttons (the smallest text there is)
MONO_B = ("Consolas", 10, "bold")
OK, WARN, BAD = "#3ddc84", "#ffb000", "#ff6b6b"      # the same three status colours as the pages
SANS = ("Segoe UI", 10)
UI = 1.0                                             # screen scaling (1.5 on a 150 % Windows display), set at start
GREY = "#7d8796"
RULE2 = "#4a5462"                                     # control borders


def S(v: float) -> int:
    """pixel size scaled for the screen (fonts in points scale by themselves)"""
    return round(v * UI)
