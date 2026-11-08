"""Rename locations and flight logs, and tidy old names.

All names that end up as file names are plain ASCII: lowercase letters, digits, '-' and '_'
(no spaces, accents or emoji), so they are easy to type, sort and copy.

    rename_location("t", "gruyere_north", title="Gruyère north")
    rename_track("teysachaux", "sim_20261011_152509", "first_try")
    tidy(scenes_dir, apply=False)   -> list of planned changes
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from .locations import LOC_DIR, NAME_RE, ROOT
from .safefile import write_atomic

LOGS = ROOT / "logs"
TRACK_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}$", re.I)
SIM_OLD = re.compile(r"^sim_(?:(?P<label>[a-z0-9_]+?)_)?(?P<d>\d{8})_(?P<t>\d{4})\d{2}$")
SMALL = {"de", "du", "des", "la", "le", "les", "d", "l", "am", "im", "an", "der", "die", "das", "von", "sur", "en"}


def slug(text: str, keep_case: bool = False, max_len: int = 60) -> str:
    """'Moléson (FR) 🚁 east' -> 'moleson_fr_east'. Accents are folded, emoji and symbols dropped."""
    s = unicodedata.normalize("NFKD", text or "")
    s = s.encode("ascii", "ignore").decode()
    if not keep_case:
        s = s.lower()
    s = re.sub(r"[^A-Za-z0-9-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_-")
    return s[:max_len].strip("_-")


def nice_title(name: str) -> str:
    """'dent_de_broc' -> 'Dent de Broc'."""
    words = [w for w in re.split(r"[_\-\s]+", name) if w]
    return " ".join(w if (i and w.lower() in SMALL) else w[:1].upper() + w[1:] for i, w in enumerate(words)) or name


def strip_emoji(text: str) -> str:
    """Remove emoji / pictographs from a display title, keep accents."""
    out = "".join(ch for ch in text if not (unicodedata.category(ch) in ("So", "Cs", "Co") or 0xFE00 <= ord(ch) <= 0xFE0F
                                            or ord(ch) in (0x200D, 0x20E3)))
    return re.sub(r"\s{2,}", " ", out).strip()


# ---------------------------------------------------------------- helpers

def _loc_file(name: str) -> Path:
    f = LOC_DIR / f"{name}.yaml"
    if f.exists():
        return f
    import yaml
    for g in LOC_DIR.glob("*.yaml"):
        try:
            if (yaml.safe_load(g.read_text(encoding="utf-8")) or {}).get("name") == name:
                return g
        except Exception:
            continue
    raise FileNotFoundError(f"no location '{name}' in {LOC_DIR}")


def _set_yaml_key(path: Path, key: str, value: str, quote: bool):
    txt = path.read_text(encoding="utf-8")
    v = '"' + value.replace('"', "'") + '"' if quote else value
    txt, n = re.subn(rf"(?m)^{key}:.*$", f"{key}: {v}", txt, count=1)
    if not n:
        txt = f"{key}: {v}\n" + txt
    write_atomic(path, txt)


def _read_meta(scene_dir: Path):
    f = scene_dir / "scene.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def _write_meta(scene_dir: Path, meta):
    write_atomic((scene_dir / "scene.json"), json.dumps(meta, indent=1))


def _update_index(scenes_dir: Path):
    """Same as scene.update_index, without the heavy terrain imports (rasterio...)."""
    scenes = []
    for d in sorted(scenes_dir.iterdir()) if scenes_dir.exists() else []:
        m = _read_meta(d) if d.is_dir() else None
        if m:
            scenes.append(dict(name=m["name"], title=m.get("title", m["name"]), tracks=len(m.get("tracks", []))))
    write_atomic((scenes_dir / "index.json"), json.dumps(scenes, indent=1))


def _inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- locations

def rename_location(old: str, new: str, scenes_dir: Path, title: str | None = None, log=print):
    """Rename a location: its yaml file + `name:`, the built scene folder, logs/sim/<name>/ and the
    simulator logs that start with the old name. Optionally set a new display title."""
    new = slug(new)
    if not NAME_RE.match(new):
        raise ValueError("name: lowercase letters, digits, - and _ only (e.g. moleson_east)")
    src = _loc_file(old)
    old = src.stem if src.stem == old else old
    from .locations import NUM_RE
    m = NUM_RE.match(src.stem)
    if m and not NUM_RE.match(new):                # keep the location's number: 007_moleson -> 007_moleson_east
        new = f"{m.group(1)}_{new}"
    if new != old:
        if (LOC_DIR / f"{new}.yaml").exists() or (scenes_dir / new).exists():
            raise FileExistsError(f"a location or scene called '{new}' already exists")
    title = strip_emoji(title) if title else None

    _set_yaml_key(src, "name", new, quote=False)
    if title:
        _set_yaml_key(src, "title", title, quote=True)
    dst = LOC_DIR / f"{new}.yaml"
    if dst != src:
        src.rename(dst)
    log(f"location: {src.name} -> {dst.name}" + (f'  (title "{title}")' if title else ""))

    sim_old, sim_new = LOGS / "sim" / old, LOGS / "sim" / new
    if new != old and sim_old.exists():
        if sim_new.exists():
            raise FileExistsError(f"{sim_new} already exists")
        sim_old.rename(sim_new)
        log(f"logs: logs/sim/{old}/ -> logs/sim/{new}/")

    sd_old, sd = scenes_dir / old, scenes_dir / new
    if new != old and sd_old.exists():
        sd_old.rename(sd)
        log(f"scene: {sd_old.name}/ -> {sd.name}/")
    meta = _read_meta(sd)
    if meta is not None:
        meta["name"] = new
        if title:
            meta["title"] = title
        for t in meta.get("tracks", []):
            s = t.get("source")
            if s and new != old:     # works for Windows and POSIX paths alike
                t["source"] = re.sub(rf"([\\/]sim[\\/]){re.escape(old)}(?=[\\/])", lambda m: m.group(1) + new, s, count=1)
        _write_meta(sd, meta)
        # simulator tracks carry the location in their name -> follow the rename
        if new != old:
            for t in list(meta.get("tracks", [])):
                if t["name"].startswith(old + "_sim_"):
                    rename_track(new, t["name"], new + t["name"][len(old):], scenes_dir, log=log)
    _update_index(scenes_dir)
    return new


# ---------------------------------------------------------------- flight logs (tracks)

def rename_track(scene: str, old: str, new: str, scenes_dir: Path, log=print):
    """Rename a track of a scene: the processed track file, its entry in scene.json and - when the
    log lives inside the project's logs/ folder - the log file itself (so rebuilds keep the name)."""
    new = slug(new)
    if not TRACK_RE.match(new):
        raise ValueError("log name: letters, digits, - and _ only")
    sd = scenes_dir / scene
    meta = _read_meta(sd)
    if meta is None:
        raise FileNotFoundError(f"scene '{scene}' is not built")
    tracks = meta.get("tracks", [])
    t = next((x for x in tracks if x["name"] == old), None)
    if t is None:
        raise FileNotFoundError(f"no log '{old}' in scene '{scene}'")
    if new == old:
        return new
    if any(x["name"] == new for x in tracks) or (sd / "tracks" / f"{new}.json").exists():
        raise FileExistsError(f"scene '{scene}' already has a log called '{new}'")

    # 1. the source log file (only inside the project, never the user's own folders)
    src = t.get("source")
    sp = Path(src) if src else None
    if sp is None or not sp.exists():                  # older scenes: look for it under logs/
        cand = [c for c in LOGS.rglob(f"{old}.*") if c.suffix.lower() in (".csv", ".gpx", ".txt")] if LOGS.exists() else []
        sp = cand[0] if cand else None
    listed = False
    try:
        loc = _loc_file(scene)
        listed = sp is not None and sp.name in loc.read_text(encoding="utf-8")
    except FileNotFoundError:
        loc = None
    if sp is not None and sp.exists() and _inside(sp, LOGS):
        dst = sp.with_name(new + sp.suffix)
        if dst.exists():
            raise FileExistsError(f"{dst.relative_to(ROOT)} already exists")
        sp.rename(dst)
        if listed and loc is not None:             # keep `logs:` of the location file valid
            write_atomic(loc, loc.read_text(encoding="utf-8").replace(sp.name, dst.name))
        log(f"log file: {sp.relative_to(ROOT)} -> {dst.name}")
        if src:   # keep the path style of the stored source (it may have been written on another OS)
            base = re.split(r"[\\/]", src)[-1]
            t["source"] = src[: len(src) - len(base)] + dst.name
        else:
            t["source"] = str(dst)
        (t.get("log_options") or {}).pop("track_name", None)
    else:
        # log outside the project: leave the file alone, remember the display name for rebuilds
        t.setdefault("log_options", {})["track_name"] = new

    # 2. the processed track + scene.json
    f_old, f_new = sd / t["file"], sd / "tracks" / f"{new}.json"
    if f_old.exists():
        d = json.loads(f_old.read_text(encoding="utf-8"))
        d["name"] = new
        f_old.rename(f_new)            # move first (no delete needed), then update its content
        write_atomic(f_new, json.dumps(d, separators=(",", ":")))
    t["name"], t["file"] = new, f"tracks/{new}.json"
    if not t.get("log_options"):
        t.pop("log_options", None)
    _write_meta(sd, meta)
    log(f"track: {scene}/{old} -> {new}")
    return new


# ---------------------------------------------------------------- tidy everything

def sim_name(scene: str, old: str) -> str | None:
    """'sim_20261011_152509' -> 'teysachaux_sim_2026-10-11_1525' (label kept: ..._1525_first_try)."""
    m = SIM_OLD.match(old)
    if not m:
        return None
    d, t = m["d"], m["t"]
    return f"{scene}_sim_{d[:4]}-{d[4:6]}-{d[6:]}_{t}" + (f"_{m['label']}" if m["label"] else "")


def tidy(scenes_dir: Path, apply: bool = False, log=print):
    """Plan (and with apply=True do) the clean-up of names:
       - display titles: emoji removed, 'dent_de_broc' -> 'Dent de Broc'
       - simulator logs: sim_YYYYMMDD_HHMMSS -> <location>_sim_YYYY-MM-DD_HHMM
       - any other log name with spaces / accents / emoji -> ASCII
    Location *names* are not changed automatically (use rename_location)."""
    import yaml
    plan = []
    for f in sorted(LOC_DIR.glob("*.yaml")):
        try:
            y = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        name, title = y.get("name") or f.stem, str(y.get("title") or "")
        want = strip_emoji(title) or name
        if want == name or re.fullmatch(r"[a-z0-9_ -]+", want) or ("_" in want and " " not in want):
            want = nice_title(slug(want, keep_case=True))      # 'dent_de_broc' / 'Eiger_test' -> 'Dent de Broc' / 'Eiger Test'
        if want != title:
            plan.append(("title", name, title, want))
        meta = _read_meta(scenes_dir / name)
        for t in (meta or {}).get("tracks", []):
            nn = sim_name(name, t["name"]) or (slug(t["name"], keep_case=True) if not TRACK_RE.match(t["name"]) else None)
            if nn and nn != t["name"]:
                plan.append(("log", name, t["name"], nn))
    if apply:
        for kind, name, old, new in plan:
            if kind == "title":
                f = _loc_file(name)
                _set_yaml_key(f, "title", new, quote=True)
                meta = _read_meta(scenes_dir / name)
                if meta is not None:
                    meta["title"] = new
                    _write_meta(scenes_dir / name, meta)
                log(f'title: {name}: "{old}" -> "{new}"')
            else:
                rename_track(name, old, new, scenes_dir, log=log)
        if scenes_dir.exists():
            _update_index(scenes_dir)
    return plan
