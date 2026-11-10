"""One file for everything that went wrong: logs/errors.txt in your Alpline folder.

The launcher runs without a console window and the viewer's errors only reach the browser's developer tools, so
without this a failing button or a broken page would leave no trace. Each entry: time, where (launcher, server,
viewer, phone), the message and the details. The file is kept small (the newest ~500 KB)."""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path

from .paths import DATA

LIMIT = 500_000
_LOCK = threading.Lock()


def log_file() -> Path:
    return DATA / "logs" / "errors.txt"


def _private(text: str) -> str:
    """Your home folder (it holds your user name) is written as ~: this file is sent along with problem reports."""
    home = str(Path.home())
    if len(home) < 4:
        return text
    for h in {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}:
        text = text.replace(h, "~")
    return text


def record(source: str, message: str, details: str = "") -> Path:
    """Add one entry; never raises (logging an error must not cause another one)."""
    f = log_file()
    entry = f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}  {source}: {_private(message.strip()[:500])}\n"
    if details.strip():
        entry += _private(details.rstrip()[:8000]) + "\n"
    try:
        with _LOCK:
            f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "a", encoding="utf-8") as out:
                out.write(entry)
            if f.stat().st_size > LIMIT * 1.5:                     # keep the newest part, cut at an entry
                text = f.read_text(encoding="utf-8", errors="replace")[-LIMIT:]
                cut = text.find("\n--- ")
                f.write_text(text[cut + 1:] if cut >= 0 else text, encoding="utf-8")
    except OSError:
        pass
    return f


def record_exception(source: str, ex: BaseException) -> Path:
    return record(source, f"{type(ex).__name__}: {ex}", "".join(traceback.format_exception(type(ex), ex, ex.__traceback__)))
