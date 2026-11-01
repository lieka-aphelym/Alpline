"""Full or Lite mode, chosen when the program starts (launcher, or `--lite` on serve / map / new).

Lite = lighter on the computer: the 3D view is only redrawn when something changes, a coarser 3D mesh and
close-up patch, fewer pixels on high-DPI screens, and lighter defaults for new locations (5 m terrain,
"auto" photo, 20 m signal grid, no 3D buildings). Everything else is the same program.
The mode travels in the FPV3D_MODE environment variable, so builds started by the server inherit it.
"""
import os

MODES = ("full", "lite")


def current() -> str:
    m = os.environ.get("FPV3D_MODE", "full").strip().lower()
    return m if m in MODES else "full"


def set_mode(m: str) -> None:
    os.environ["FPV3D_MODE"] = m if m in MODES else "full"


def is_lite() -> bool:
    return current() == "lite"
