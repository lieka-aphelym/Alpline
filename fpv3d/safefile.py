"""Writing files so they are never left half written: write a temporary file next to it, then swap it in.

If the PC crashes or the power goes in the middle, you keep either the old file or the new one, never a cut one
(a cut settings file would silently reset the launcher; a cut scene.json would need a full rebuild)."""
from __future__ import annotations

import os
import time
from pathlib import Path


def write_atomic(path, data, encoding: str = "utf-8") -> None:
    """Write text (str) or bytes to `path` in one step."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    raw = data.encode(encoding) if isinstance(data, str) else data
    try:
        with open(tmp, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(10):                   # Windows: an antivirus or the indexer may hold the file a moment
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
