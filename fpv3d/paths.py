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

FROZEN = bool(getattr(sys, "frozen", False))                 # running as the packaged Alpline.exe
APP = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parent.parent
EXE_DIR = Path(sys.executable).resolve().parent if FROZEN else APP

# the installed app remembers the chosen data folder here (outside the data folder itself)
POINTER = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "Alpline" / "data_folder.txt"
DEFAULT_DATA = Path.home() / "Documents" / "Alpline"


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


def window_cmd(url: str) -> list:
    """Command that opens an Alpline window (pywebview) on `url`."""
    if FROZEN:
        return [str(EXE_DIR / ("Alpline.exe" if os.name == "nt" else "Alpline")), "--window", url]
    return [_venv("pythonw") if os.name == "nt" else _venv("python"), "-m", "fpv3d.appwin", url]
