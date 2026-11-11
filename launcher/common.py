"""What every part of the launcher uses: where things are, the settings file, the Python to run, small helpers."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

from fpv3d import paths


APP = paths.APP                                      # the program: viewer pages, logo frames, icon
ROOT = paths.DATA                                    # your files: launcher.json, logs, scenes, cache, locations
SETTINGS = ROOT / "launcher.json"
LOG = ROOT / "logs" / "server.log"


def venv_exe(name: str) -> str:
    """python.exe / pythonw.exe of the project's virtual environment (.venv), where numpy, rasterio, PyYAML...
    are installed. Asked for explicitly: with the Microsoft Store Python, sys.executable inside a venv points
    to the base Python, which does not have those libraries."""
    for d in (APP / ".venv" / "Scripts", APP / ".venv" / "bin", Path(sys.prefix) / "Scripts", Path(sys.prefix) / "bin"):
        for n in (name, name.replace(".exe", ""), "python3" if name.startswith("python.") else name):
            if (d / n).exists():
                return str(d / n)
    exe = Path(sys.executable)
    twin = exe.with_name(name)
    return str(twin if twin.exists() else exe)


def python_exe() -> str:
    """The python that runs the server (console version, no window: CREATE_NO_WINDOW)."""
    return venv_exe("python.exe")


def lan_addresses() -> list:
    """IPv4 addresses of this computer on its local networks, best guess first (fpv3d.netinfo, shared with the server)."""
    try:
        from fpv3d.netinfo import lan_addresses as la
        return la()
    except Exception as ex:
        unexpected(ex)
        return []


EXPECTED = (OSError, ImportError, ValueError, KeyError, TimeoutError, tk.TclError)


def unexpected(ex):
    """A fallback caught this error. Missing files, no network, a missing library or a damaged file are expected
    there and stay quiet; anything else is probably a bug and goes to logs/errors.txt, instead of vanishing."""
    if not isinstance(ex, EXPECTED):
        try:
            from fpv3d.errorlog import record_exception
            record_exception("launcher (handled)", ex)
        except Exception:                                      # noqa: BLE001 - never fail while reporting
            pass


def port_free(port: int) -> bool:
    with socket.socket() as s:
        if os.name != "nt":                     # like the server: ignore old connections still closing (TIME_WAIT)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def load_settings() -> dict:
    try:
        return {"mode": "full", "port": 8000, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except Exception as ex:
        unexpected(ex)
        return {"mode": "full", "port": 8000}


def is_sim(t: dict) -> bool:
    """Training-flight logs: named <location>_sim_<date> or stored under logs/sim/."""
    return "_sim_" in t.get("name", "") or bool(re.search(r"[\\/]logs[\\/]sim[\\/]", t.get("source", "")))


def flight_stats(name: str) -> dict:
    """Real and simulator logs of a built location (from scenes/<name>/scene.json)."""
    out = {"real": 0, "sim": 0, "real_s": 0.0, "sim_s": 0.0, "last": None, "built": None}
    f = ROOT / "scenes" / name / "scene.json"
    if not f.exists():
        return out
    out["built"] = f.stat().st_mtime
    try:
        tracks = json.loads(f.read_text(encoding="utf-8")).get("tracks", [])
    except Exception as ex:
        unexpected(ex)
        return out
    for t in tracks:
        k = "sim" if is_sim(t) else "real"
        out[k] += 1
        out[k + "_s"] += float(t.get("duration_s") or 0)
        p = ROOT / "scenes" / name / t.get("file", "")
        if p.exists():
            out["last"] = max(out["last"] or 0, p.stat().st_mtime)
    return out


def fmt_dur(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600} h {s % 3600 // 60:02d}" if s >= 3600 else f"{s // 60} min" if s >= 60 else f"{s} s"


def short_day(ts) -> str:
    """'07 Nov' this year, 'Nov 2025' before"""
    t = time.localtime(ts)
    return time.strftime("%d %b" if t.tm_year == time.localtime().tm_year else "%b %Y", t)


def split_name(name):
    """'007_moleson' -> ('007', 'moleson'); 'test' -> ('', 'test')"""
    head, _, rest = name.partition("_")
    return (head, rest) if head.isdigit() and rest else ("", name)


def open_file(f):
    try:
        if os.name == "nt":
            os.startfile(str(f))                               # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(f)])
    except Exception:                                          # noqa: BLE001
        pass
