"""Building safely: one build per location at a time, and an estimate of size and memory before starting.

The lock is an OS file lock on scenes/.<name>.lock, held for the whole build: a second window (another
terminal, the map page, refresh-all) building the same location is refused instead of writing the same files.
The OS releases it when the process ends, so a crash never leaves a stale lock behind.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

RAM_FACTOR = 6          # peak memory ~ 6 x one terrain layer (mosaic, resampling buffers, copies)


def estimate(cfg) -> dict:
    """Rough size of a location: cells, scene files (MB) and peak memory while building (GB)."""
    g = cfg.grid(cfg.terrain.resolution_m)
    cells = g.rows * g.cols
    layers = 2 if cfg.terrain.surface == "dsm" else 1          # surface model also keeps the bare ground
    layer_mb = cells * 4 / 1e6
    return dict(cells=cells, cols=g.cols, rows=g.rows, scene_mb=round(layer_mb * layers + 5, 1),
                ram_gb=round(layer_mb * RAM_FACTOR / 1000, 2))


def total_ram_gb():
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS(); m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 1e9
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except Exception:
        return None


from .filelock import try_lock, unlock  # noqa: E402


class Busy(RuntimeError):
    pass


@contextmanager
def scene_lock(scenes_dir: Path, name: str):
    scenes_dir.mkdir(parents=True, exist_ok=True)
    path = scenes_dir / f".{name}.lock"
    f = open(path, "a+")
    if not try_lock(f):
        f.close()
        raise Busy(f"'{name}' is already being built (another window or terminal). Wait for it to finish.") from None
    try:
        yield
    finally:
        unlock(f)
        f.close()
        try:
            path.unlink()
        except OSError:
            pass
