"""Where Alpline lives and where your files go (standard library only: the launcher imports it first).

    APP   the program: code and the viewer/ pages (read only once installed)
    DATA  your files: locations/, scenes/, cache/, logs/, deleted/, launcher.json

From the source folder (PyCharm, Alpline.bat) both are that folder, as before. The installed Windows app keeps
DATA in Documents\\Alpline by default; the launcher asks the first time, so an existing project folder can be used.
ALPLINE_DATA in the environment overrides both (tests, a second setup).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .brand import APP_NAME, EARLIER_NAMES

FROZEN = bool(getattr(sys, "frozen", False))                 # running as the packaged Alpline.exe
APP = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parent.parent
EXE_DIR = Path(sys.executable).resolve().parent if FROZEN else APP

# the installed app remembers the chosen data folder here (outside the data folder itself)
_CONF = Path(os.environ.get("APPDATA") or Path.home() / ".config")


def _named(base: Path, tail: str = "") -> Path:
    """<base>/<app name>[/tail]. After a rename of the app (fpv3d/brand.py) the folder of an earlier name is used
    when it exists and the new one does not: your existing files are found, new installs get the new name."""
    new = base / APP_NAME / tail if tail else base / APP_NAME
    if not new.exists():
        for old in EARLIER_NAMES:
            cand = base / old / tail if tail else base / old
            if old != APP_NAME and cand.exists():
                return cand
    return new


POINTER = _named(_CONF, "data_folder.txt")
DEFAULT_DATA = _named(Path.home() / "Documents")


def _data() -> Path:
    if os.environ.get("ALPLINE_DATA"):
        return Path(os.environ["ALPLINE_DATA"])
    if not FROZEN:
        return APP
    try:
        p = Path(POINTER.read_text(encoding="utf-8").strip())
        if p.is_dir():
            return p
    except OSError:
        pass
    return DEFAULT_DATA


DATA = _data()


def portable(path) -> str:
    """How a file of yours is written down in scene files: relative to your Alpline folder when it is inside it
    ("logs/sim/x.csv"), so no file carries the folder's full path (it holds your Windows user name) and a backup
    restored on another PC still finds its logs. Files elsewhere keep their full path."""
    p = Path(path)
    try:
        return p.resolve().relative_to(DATA.resolve()).as_posix()
    except (ValueError, OSError):
        return str(p)


def from_portable(src: str) -> Path:
    """The file a stored path means. Relative = inside your Alpline folder. A full path written by an older version
    (or on another PC) that no longer exists is looked for under logs/ here."""
    s = str(src or "")
    absolute = s.startswith(("/", "\\")) or (len(s) > 2 and s[1] == ":")
    if not absolute:
        return DATA / s
    p = Path(s)
    if not p.exists():
        parts = [x for x in s.replace("\\", "/").split("/") if x]
        if "logs" in parts:
            cand = DATA.joinpath(*parts[len(parts) - 1 - parts[::-1].index("logs"):])
            if cand.exists():
                return cand
    return p


def data_chosen() -> bool:
    """False only for the installed app before the first start has chosen a folder."""
    return not FROZEN or bool(os.environ.get("ALPLINE_DATA")) or POINTER.exists()


def set_data(folder: Path) -> None:
    """Remember the data folder (installed app). Takes effect at the next start."""
    folder.mkdir(parents=True, exist_ok=True)
    POINTER.parent.mkdir(parents=True, exist_ok=True)
    POINTER.write_text(str(folder), encoding="utf-8")


def ensure_data() -> None:
    for d in ("locations", "scenes", "cache", "logs"):
        (DATA / d).mkdir(parents=True, exist_ok=True)


def _venv(name: str) -> str:
    """The project's .venv interpreter when there is one (the Microsoft Store Python points sys.executable at the
    base install even inside a venv, which then misses the libraries)."""
    for d in (APP / ".venv" / "Scripts", APP / ".venv" / "bin", Path(sys.prefix) / "Scripts", Path(sys.prefix) / "bin",
              Path(sys.prefix)):
        for n in (f"{name}.exe", name, "python3"):
            if (d / n).exists():
                return str(d / n)
    return sys.executable


def cli_cmd(unbuffered: bool = False) -> list:
    """Command that runs `fpv3d <args>`: a build, the server, cache cleaning..."""
    if FROZEN:
        return [str(EXE_DIR / ("alpline-cli.exe" if os.name == "nt" else "alpline-cli"))]
    return [_venv("python"), *(["-u"] if unbuffered else []), "-m", "fpv3d"]


def app_browser() -> str | None:
    """Edge (or Chrome / Chromium) to open Alpline windows in app mode: a window with no address bar or tabs, its
    own taskbar icon (Alpline's app icon). Edge comes with Windows 10 / 11. ALPLINE_APP_BROWSER overrides."""
    import shutil
    if os.environ.get("ALPLINE_APP_BROWSER"):
        return os.environ["ALPLINE_APP_BROWSER"]
    if os.name == "nt":
        roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            for r in roots:
                if r and (Path(r) / rel).exists():
                    return str(Path(r) / rel)
        return None
    if sys.platform == "darwin":
        for p in ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
            if Path(p).exists():
                return p
        return None
    for n in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        if shutil.which(n):
            return shutil.which(n)
    return None


def window_cmd(url: str) -> list | None:
    """Command that opens an Alpline window on `url`: Edge / Chrome in app mode with Alpline's own profile
    (DATA/cache/appwindow: the pages' settings stay there, apart from your normal browser). None = no such browser."""
    exe = app_browser()
    if not exe:
        return None
    prof = DATA / "cache" / "appwindow"
    return [exe, f"--app={url}", f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
            "--hide-crash-restore-bubble", "--disable-session-crashed-bubble", "--window-size=1440,900"]
