"""Locking a file between programs (the launcher, the server and the command line are separate programs that share
the same folder). One copy of the Windows / Unix difference, used by buildlock.py (one build per location) and
battery.py (one writer for packs.json)."""
from __future__ import annotations

import os


def try_lock(f) -> bool:
    """Take the lock on an open file without waiting. False when another program holds it."""
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)   # type: ignore[attr-defined]
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def unlock(f) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)   # type: ignore[attr-defined]
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        pass
