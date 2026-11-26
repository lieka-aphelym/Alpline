"""Alpline (by lieka) launcher: your locations on a map of Switzerland, the drone and radio on USB, phone sharing,
settings. Opens the 3D viewer and the map page.

Double-click Alpline.bat (or the desktop shortcut it can create), or start the installed Alpline app. The window
starts the local server in the chosen mode, opens Alpline windows (or your browser), and stops the server when you
close it. It also tells you whether your locations are ready to use offline at the field.

The code is in launcher/, one file per page (app.py puts them together). Packaged app: this file is Alpline.exe.
"""
import sys
from pathlib import Path

try:                    # the installed app's first picture (launcher/startup.py): say what it waits for meanwhile
    import pyi_splash
    pyi_splash.update_text("loading")
except ImportError:     # run from the source: there is none
    pass
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fpv3d import paths  # noqa: E402, F401  (tests reach paths and Launcher through this file)
from launcher.app import Launcher  # noqa: E402, F401
from launcher.main import main  # noqa: E402

if __name__ == "__main__":
    main()
