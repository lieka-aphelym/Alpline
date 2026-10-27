"""Delete / restore locations.

Deleting never destroys anything right away: the location file, its built scene and its
simulator training flights are moved to  deleted/<date>_<name>/  and can be restored.
`python -m fpv3d deleted --purge` empties that folder for good. The terrain cache (shared by all
locations) and your own flight logs elsewhere are never touched.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .locations import LOC_DIR, ROOT

TRASH = ROOT / "deleted"
LOGS = ROOT / "logs"


def _loc_file(name: str) -> Path:
    from .rename import _loc_file as lf
    return lf(name)


def delete_location(name: str, scenes_dir: Path, log=print) -> dict:
    src = _loc_file(name)
    import yaml
    title = (yaml.safe_load(src.read_text(encoding="utf-8")) or {}).get("title") or name
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = TRASH / f"{stamp}_{name}"
    dest.mkdir(parents=True)
    moved = []
    src.rename(dest / "location.yaml"); moved.append(f"locations/{src.name}")
    sd = scenes_dir / name
    if sd.exists():
        shutil.move(str(sd), str(dest / "scene")); moved.append(f"scene {name}/")
    sim = LOGS / "sim" / name
    n_sim = 0
    if sim.exists():
        n_sim = sum(1 for _ in sim.glob("*.csv"))
        shutil.move(str(sim), str(dest / "sim_logs")); moved.append(f"{n_sim} training flight(s)")
    (dest / "info.json").write_text(json.dumps(dict(name=name, title=title, deleted=time.strftime("%Y-%m-%d %H:%M"),
                                                    file=src.name, scenes_dir=str(scenes_dir), moved=moved), indent=1),
                                    encoding="utf-8")
    _index(scenes_dir)
    log(f"deleted '{title}': {', '.join(moved)} -> deleted/{dest.name}/  (restore: python -m fpv3d restore {dest.name})")
    return dict(folder=dest.name, name=name, title=title, moved=moved)


def list_deleted():
    out = []
    for d in sorted(TRASH.glob("*_*"), reverse=True) if TRASH.exists() else []:
        try:
            info = json.loads((d / "info.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = dict(name=d.name.split("_", 1)[-1], title=d.name)
        info["folder"] = d.name
        out.append(info)
    return out


def restore_location(folder: str, scenes_dir: Path, log=print) -> dict:
    d = TRASH / folder
    if not d.is_dir() or "/" in folder or "\\" in folder or folder.startswith("."):
        matches = [x for x in list_deleted() if x.get("name") == folder]
        if not matches:
            raise FileNotFoundError(f"nothing called '{folder}' in deleted/")
        d = TRASH / matches[0]["folder"]          # newest deletion of that name
    info = json.loads((d / "info.json").read_text(encoding="utf-8")) if (d / "info.json").exists() else {}
    name = info.get("name") or d.name.split("_", 1)[-1]
    loc = LOC_DIR / info.get("file", f"{name}.yaml")
    if loc.exists() or (scenes_dir / name).exists():
        raise FileExistsError(f"a location '{name}' exists again - rename it first (python -m fpv3d rename location ...)")
    LOC_DIR.mkdir(exist_ok=True)
    (d / "location.yaml").rename(loc)
    if (d / "scene").exists():
        shutil.move(str(d / "scene"), str(scenes_dir / name))
    if (d / "sim_logs").exists():
        (LOGS / "sim").mkdir(parents=True, exist_ok=True)
        shutil.move(str(d / "sim_logs"), str(LOGS / "sim" / name))
    (d / "info.json").unlink(missing_ok=True)
    try:
        d.rmdir()
    except OSError:
        pass
    _index(scenes_dir)
    log(f"restored '{info.get('title', name)}' ({name})")
    return dict(name=name, title=info.get("title", name))


def purge(older_than_days: float = 0, log=print) -> int:
    n = 0
    for x in list_deleted():
        d = TRASH / x["folder"]
        if older_than_days and time.time() - d.stat().st_mtime < older_than_days * 86400:
            continue
        shutil.rmtree(d)
        n += 1
        log(f"permanently removed deleted/{d.name}")
    return n


def _index(scenes_dir: Path):
    from .rename import _update_index
    if scenes_dir.exists():
        _update_index(scenes_dir)
