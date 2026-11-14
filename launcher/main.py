"""Starting the launcher: sharp text on Windows, errors to logs/errors.txt, the first-start folder question."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

from fpv3d import paths
from fpv3d.brand import APP_ID
from fpv3d.brand import APP_NAME

from . import style
from .app import Launcher
from .common import open_file


def sharp_on_windows():
    """Tell Windows this window draws itself at the real screen resolution. Without it, on a display scaled to
    125 % / 150 %, Windows stretches a 100 % picture of the window: that is the blurry, 'hazy' look.
    Also give the launcher its own app id: started from the source folder the program is pythonw.exe, and Windows
    would otherwise show (and group under) Python's icon in the taskbar instead of the window's Alpline icon."""
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)       # per-monitor (Windows 8.1+)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()          # older Windows
        except Exception:
            pass


def catch_errors(root, app):
    """The launcher has no console window: an error in a button, a timer or a background task would vanish. Each one
    goes to logs/errors.txt and shows a short notice (click it to open the file)."""
    from fpv3d.errorlog import record_exception
    last = {"t": 0.0}

    def report(ex):
        f = record_exception("launcher", ex)
        def notice():
            if time.time() - last["t"] < 3:                    # a burst of the same failure: one notice
                return
            last["t"] = time.time()
            try:
                app.say(f"Something went wrong: {type(ex).__name__}: {str(ex)[:120]}\nDetails saved in logs/errors.txt", "bad")
                app.toast.bind("<Button-1>", lambda e: (app.toast.place_forget(), open_file(f)))
            except Exception:                                  # noqa: BLE001 - the window may be closing
                pass
        try:
            root.after(0, notice)
        except Exception:                                      # noqa: BLE001
            pass

    root.report_callback_exception = lambda typ, ex, tb: report(ex)
    sys.excepthook = lambda typ, ex, tb: report(ex)


def first_start_folder(root) -> bool:
    """Installed app, very first start: where should your files go? True = continue, False = restart needed / quit."""
    from tkinter import filedialog, messagebox
    ans = messagebox.askyesnocancel(
        f"{APP_NAME}: your files",
        f"Where should {APP_NAME} keep your locations, flights and downloaded maps?\n\n"
        f"Yes: in {paths.DEFAULT_DATA}\n"
        "No: choose a folder (for example your existing fpv3d project folder, to keep everything you already have)",
        parent=root)
    if ans is None:
        return False
    folder = paths.DEFAULT_DATA
    if ans is False:
        pick = filedialog.askdirectory(parent=root, title=f"Folder for {APP_NAME}'s files", mustexist=False,
                                       initialdir=str(Path.home()))
        if not pick:
            return False
        folder = Path(pick)
    paths.set_data(folder)
    subprocess.Popen([sys.executable] + sys.argv[1:])       # start again with the chosen folder
    return False


def leave(code=0):
    """End the program once the window is closed. A download still running in the background (the map's tiles)
    may be waiting to tell a window that no longer exists; Python would wait for it forever and the launcher
    would stay in the task manager. Everything is saved by then (Launcher.quit), files are written whole."""
    for f in (sys.stdout, sys.stderr):
        try:
            f.flush()
        except Exception:                                      # noqa: BLE001  (pythonw has no output)
            pass
    os._exit(code)


def main():
    sharp_on_windows()
    root = tk.Tk()
    if not paths.data_chosen():
        root.withdraw()
        first_start_folder(root)
        sys.exit(0)
    paths.ensure_data()
    style.UI = max(1.0, root.winfo_fpixels("1i") / 96)      # 1.25, 1.5 ... on scaled displays
    root.tk.call("tk", "scaling", style.UI * 96 / 72)        # fonts in points follow the same factor
    app = Launcher(root)
    catch_errors(root, app)
    root.mainloop()
    leave()
