"""Your files in Alpline's folder: how much space each kind takes, clearing some of them (start fresh), and a backup
zip to keep them or move them to another PC.

Only the folders and files listed in KINDS are ever touched. Alpline's folder may also be the program's own folder
(started from the source), so nothing else in it is deleted, and nothing outside it."""
from __future__ import annotations

import json
import os
import shutil
import time
import zipfile
from pathlib import Path

from .paths import DATA
from .safefile import write_atomic

MAX_ENTRY = 4_000_000_000                   # largest single file a restore accepts (a 15 km scene's terrain is ~1 GB)
BACKUP_TAG = "alpline_backup.json"           # inside every backup zip: what it holds and when it was made
APP_LOG_FILES = ("server.log", "window.log", "errors.txt", "phone_check.txt", "phone_fix.txt")

# key: (label, short note for the list, explanation)
KINDS = {
    "flights": ("Flight logs", "logs, blackbox, live recordings",
                "your logs, blackbox downloads and live recordings, and the flights shown in 3D"),
    "training": ("Training flights", "saved in the simulator", "flights saved in the simulator"),
    "scenes": ("Built 3D scenes", "terrain, photos, signal maps",
               "terrain, photos and signal maps; rebuild them from the locations "
               "(flights shown in 3D go with them, their log files stay)"),
    "cache": ("Downloaded maps", "swisstopo tiles", "swisstopo tiles kept to build faster; downloaded again when needed"),
    "locations": ("Locations", "location files (+ their scenes)",
                  "your location files with their radio setup (their 3D scenes go too)"),
    "packs": ("Battery packs", "names, capacity, health history",
              "your packs (name, cells, capacity), which pack flew which flight, charger entries"),
    "deleted": ("Deleted items", "kept to restore them", "locations you deleted, kept so you could restore them"),
    "applogs": ("App logs", "error and server logs", "error and server logs, check screenshots"),
    "settings": ("Launcher settings", "back to the defaults",
                 "port, Full/Lite mode and the other choices (back to the defaults)"),
}


def _is_training(name: str) -> bool:
    return "_sim_" in name


def _files(kind: str, root: Path):
    """The files of one kind (for sizes and backups)."""
    logs = root / "logs"
    if kind == "flights":
        if logs.exists():
            for f in logs.rglob("*"):
                rel = f.relative_to(logs).parts
                if f.is_file() and rel[0] not in ("sim", "checks") and not (len(rel) == 1 and rel[0] in APP_LOG_FILES):
                    yield f
        yield from _track_files(root, training=False)
        if (root / "battery" / "flights").exists():
            yield from (f for f in (root / "battery" / "flights").glob("*.json"))
    elif kind == "packs":
        if (root / "battery" / "packs.json").is_file():
            yield root / "battery" / "packs.json"
    elif kind == "training":
        if (logs / "sim").exists():
            yield from (f for f in (logs / "sim").rglob("*") if f.is_file())
        yield from _track_files(root, training=True)
    elif kind in ("scenes", "cache", "deleted"):
        d = root / kind
        if d.exists():
            yield from (f for f in d.rglob("*") if f.is_file())
    elif kind == "locations":
        d = root / "locations"
        if d.exists():
            yield from (f for f in d.glob("*.yaml") if f.is_file())
    elif kind == "applogs":
        for n in APP_LOG_FILES:
            if (logs / n).is_file():
                yield logs / n
        if (logs / "checks").exists():
            yield from (f for f in (logs / "checks").rglob("*") if f.is_file())
    elif kind == "settings":
        if (root / "launcher.json").is_file():
            yield root / "launcher.json"


def _track_files(root: Path, training: bool):
    sd = root / "scenes"
    for f in sorted(sd.glob("*/tracks/*.json")) if sd.exists() else []:
        if _is_training(f.stem) == training:
            yield f


def sizes(root: Path = DATA) -> dict:
    """{kind: bytes} (a flight's 3D track is counted with its kind, not with the scenes)."""
    out = {}
    for k in KINDS:
        try:
            out[k] = sum(f.stat().st_size for f in _files(k, root))
        except OSError:
            out[k] = 0
    return out


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} GB"


# ------------------------------------------------------------------------------------------------------------ clear

def _drop_tracks(root: Path, training: bool):
    """Remove flights of one kind from every built scene (their files and their line in scene.json)."""
    sd = root / "scenes"
    for meta_f in sorted(sd.glob("*/scene.json")) if sd.exists() else []:
        try:
            meta = json.loads(meta_f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        keep = [t for t in meta.get("tracks", []) if _is_training(t.get("name", "")) != training]
        if len(keep) != len(meta.get("tracks", [])):
            meta["tracks"] = keep
            write_atomic(meta_f, json.dumps(meta, indent=1))
    for f in list(_track_files(root, training)):
        f.unlink(missing_ok=True)


def building_now(root: Path = DATA) -> str | None:
    """Name of a location being built right now (its lock is held), else None."""
    from .buildlock import Busy, scene_lock
    sd = root / "scenes"
    for f in sorted(sd.glob(".*.lock")) if sd.exists() else []:
        name = f.name[1:-5]
        try:
            with scene_lock(sd, name):
                pass
        except Busy:
            return name
    return None


def clear(kinds, root: Path = DATA) -> dict:
    """Delete the chosen kinds. Returns {kind: bytes freed}. Locations always take their scenes with them.
    Refused (RuntimeError) while a location is being built."""
    kinds = set(kinds) & set(KINDS)
    if "locations" in kinds:
        kinds.add("scenes")
    busy = building_now(root)
    if busy and kinds & {"scenes", "cache", "locations", "flights", "training"}:
        raise RuntimeError(f"'{busy}' is being built right now: wait for it to finish, then clean up")
    before = sizes(root)
    logs = root / "logs"
    if "flights" in kinds and "scenes" not in kinds:
        _drop_tracks(root, training=False)
    if "training" in kinds and "scenes" not in kinds:
        _drop_tracks(root, training=True)
    if "flights" in kinds:
        for f in list(_files("flights", root)):
            if logs in f.parents or f.parent == root / "battery" / "flights":
                f.unlink(missing_ok=True)
        if logs.exists():
            _prune_empty(logs, keep=("sim", "checks"))
    if "packs" in kinds:
        (root / "battery" / "packs.json").unlink(missing_ok=True)
    if "training" in kinds:
        shutil.rmtree(logs / "sim", ignore_errors=True)
    for k in ("scenes", "cache", "deleted"):
        if k in kinds and (root / k).exists():
            shutil.rmtree(root / k, ignore_errors=True)
            (root / k).mkdir(exist_ok=True)
            if k == "scenes":
                write_atomic(root / "scenes" / "index.json", "[]")
    if "locations" in kinds:
        for f in list(_files("locations", root)):
            f.unlink(missing_ok=True)
    if "applogs" in kinds:
        for f in list(_files("applogs", root)):
            try:
                f.unlink(missing_ok=True)
            except PermissionError:                     # server.log is open while the server runs: empty it instead
                f.write_text("", encoding="utf-8")
    if "settings" in kinds:
        (root / "launcher.json").unlink(missing_ok=True)
    _rebuild_index(root)
    if "flights" in kinds:                               # flights whose battery series went leave the packs list
        from .battery import forget_missing
        forget_missing(root)
    after = sizes(root)
    return {k: max(0, before[k] - after[k]) for k in kinds}


def _prune_empty(d: Path, keep=()):
    for sub in sorted((p for p in d.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        if sub.relative_to(d).parts[0] in keep:
            continue
        try:
            sub.rmdir()                                  # only when empty
        except OSError:
            pass


# ----------------------------------------------------------------------------------------------------------- backup

def backup_kinds(include_scenes=False, include_cache=False):
    ks = ["locations", "flights", "training", "packs", "settings"]
    return ks + (["scenes"] if include_scenes else []) + (["cache"] if include_cache else [])


def backup(dest: Path, kinds=None, root: Path = DATA, progress=None) -> dict:
    """Zip the chosen kinds into `dest`. Without the scenes, each scene's flights list (scene.json) still goes in,
    so a rebuild after restoring shows the flights again. Returns {"files": n, "bytes": size of the zip}."""
    kinds = list(kinds or backup_kinds())
    files = {}
    for k in kinds:
        for f in _files(k, root):
            files[f.relative_to(root).as_posix()] = f
    lists = {}                     # without the scenes: each scene's flights list, so a rebuild shows them again
    if "scenes" not in kinds and ("flights" in kinds or "training" in kinds):
        for f in (root / "scenes").glob("*/scene.json") if (root / "scenes").exists() else []:
            try:
                tracks = json.loads(f.read_text(encoding="utf-8")).get("tracks", [])
            except (OSError, ValueError):
                continue
            tracks = [t for t in tracks if ("training" if _is_training(t.get("name", "")) else "flights") in kinds]
            if tracks:
                lists[f"scenes/{f.parent.name}/flights.json"] = json.dumps(dict(tracks=tracks), indent=1)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr(BACKUP_TAG, json.dumps(dict(made=time.strftime("%Y-%m-%d %H:%M"), kinds=kinds, files=len(files)), indent=1))
        for name, text in lists.items():
            z.writestr(name, text)
        for i, (name, f) in enumerate(sorted(files.items())):
            packed = zipfile.ZIP_STORED if f.suffix.lower() in (".jpg", ".png", ".zip", ".bbl") else zipfile.ZIP_DEFLATED
            z.write(f, name, compress_type=packed)
            if progress and i % 50 == 0:
                progress(i, len(files))
    os.replace(tmp, dest)
    return dict(files=len(files) + len(lists), bytes=dest.stat().st_size)


def read_backup(src: Path) -> dict:
    """What a backup holds; ValueError when it is not an Alpline backup."""
    try:
        with zipfile.ZipFile(src) as z:
            info = json.loads(z.read(BACKUP_TAG))
            info["names"] = [n for n in z.namelist() if n != BACKUP_TAG]
            return info
    except (KeyError, zipfile.BadZipFile, ValueError, OSError) as ex:
        raise ValueError(f"{Path(src).name} is not an Alpline backup") from ex


def _safe_target(root: Path, name: str) -> Path | None:
    """Where a zip entry goes, or None when it would land outside Alpline's folder (../, C:\\, /etc ...) or in a
    place a backup never writes (only our own kinds of files are restored)."""
    if not name or name.endswith("/") or "\\" in name or ":" in name or name.startswith("/"):
        return None
    parts = Path(name).parts
    if ".." in parts or parts[0] not in ("locations", "logs", "scenes", "cache", "deleted", "battery", "launcher.json"):
        return None
    target = (root / name).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def restore(src: Path, root: Path = DATA, replace=False) -> dict:
    """Unpack a backup into Alpline's folder. Existing files are kept unless replace=True.
    Returns {"restored": n, "kept": n, "refused": n}."""
    read_backup(src)
    n = kept = refused = 0
    with zipfile.ZipFile(src) as z:
        for zi in z.infolist():
            if zi.filename == BACKUP_TAG or zi.is_dir():
                continue
            t = _safe_target(root, zi.filename)
            if t is None:
                refused += 1
                continue
            if t.exists() and not replace:
                kept += 1
                continue
            if zi.file_size > MAX_ENTRY:                 # a damaged or hostile zip claiming a huge file
                refused += 1
                continue
            t.parent.mkdir(parents=True, exist_ok=True)
            tmp = t.with_name(f".{t.name}.restore.tmp")
            try:
                with z.open(zi) as fin, open(tmp, "wb") as fout:   # in pieces: never the whole file in memory
                    left = zi.file_size
                    while True:
                        chunk = fin.read(1 << 20)
                        if not chunk:
                            break
                        left -= len(chunk)
                        if left < 0:                     # more data than the zip declared
                            raise ValueError("entry larger than declared")
                        fout.write(chunk)
                os.replace(tmp, t)
            except (ValueError, zipfile.BadZipFile, OSError):
                refused += 1
                continue
            finally:
                if tmp.exists():
                    tmp.unlink()
            n += 1
    _rebuild_index(root)
    return dict(restored=n, kept=kept, refused=refused)


def _rebuild_index(root: Path):
    """scenes/index.json lists the built scenes (scene.json and terrain there): make it match what is on disk."""
    sd = root / "scenes"
    if not sd.exists():
        return
    out = []
    for d in sorted(p for p in sd.iterdir() if (p / "scene.json").exists()):
        try:
            m = json.loads((d / "scene.json").read_text(encoding="utf-8"))
            out.append(dict(name=m.get("name", d.name), title=m.get("title", d.name), tracks=len(m.get("tracks", []))))
        except (OSError, ValueError):
            pass
    write_atomic(sd / "index.json", json.dumps(out, indent=1))


# ------------------------------------------------------------------------------------------------------- disk space

def free_bytes(path: Path = DATA) -> int | None:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


# -------------------------------------------------------------------------------------------- automatic backups
AUTO_PREFIX, AUTO_EVERY_DAYS, AUTO_KEEP = "auto_", 7, 5


def auto_backups(root: Path = DATA) -> list:
    d = root / "backups"
    return sorted(d.glob(f"{AUTO_PREFIX}*.zip")) if d.exists() else []


def auto_backup(root: Path = DATA, now=None) -> Path | None:
    """Once a week: a small backup (locations, flights, packs, settings; no scenes or maps) in backups/, named
    auto_<date>.zip; the five newest are kept. Returns the new file, or None when the last one is recent enough or
    there is nothing to save yet."""
    now = now or time.time()
    have = auto_backups(root)
    if have and now - have[-1].stat().st_mtime < AUTO_EVERY_DAYS * 86400:
        return None
    kinds = backup_kinds()
    if not any(True for k in kinds if k != "settings" for _ in _files(k, root)):
        return None                                           # a fresh install: nothing of yours yet
    dest = root / "backups" / f"{AUTO_PREFIX}{time.strftime('%Y-%m-%d', time.localtime(now))}.zip"
    backup(dest, kinds, root)
    for old in auto_backups(root)[:-AUTO_KEEP]:
        old.unlink(missing_ok=True)
    return dest
