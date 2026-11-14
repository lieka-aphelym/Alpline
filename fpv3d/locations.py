"""Location files (locations/*.yaml): create, list, summarise.

Used by `python -m fpv3d new` and by the map page (`python -m fpv3d map`).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from .paths import DATA
from .safefile import write_atomic

ROOT = DATA          # your files (locations, scenes, cache, logs); the program itself is paths.APP
LOC_DIR = ROOT / "locations"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")

TEMPLATE = """# fpv3d location - edit freely. Coordinates: lat/lon (WGS84) or e/n (LV95).
name: {name}
title: "{title}"

center: {{lat: {clat:.6f}, lon: {clon:.6f}}}
half_size_m: {half:g}          # map extends this far from the centre in each direction

pilot:                     # remove lat/lon to use the first GPS fix of the first log
  lat: {plat:.6f}
  lon: {plon:.6f}
  antenna_height_m: {antenna:g}    # goggles / ground-station antenna above ground

terrain:
  resolution_m: {res:g}          # 0.5,1,2,2.5,4,5,8,10,20,25,40,50
  surface: {surface}             # dtm = bare ground (swissALTI3D), dsm = incl. trees/buildings (swissSURFACE3D)
  ortho: true
{terrain_opts}
  detail_radius_m: 600

analysis:                  # created in {mode} mode
{analysis_opts}
  primary_link: 0          # index into links: used for the shadow map
  k_factor: 1.333
  fresnel_clearance: 0.6

{links}
logs: []
log_options:
  altitude_mode: auto      # auto | amsl | relative | agl
  altitude_offset_m: 0
"""

# what differs between a location created in Full and in Lite mode (see fpv3d/mode.py)
MODE_OPTS = {
    "full": dict(
        terrain_opts="""  ortho_resolution_m: 2          # aerial photo (m), or auto = sharpest that stays <= 2048 px
  buildings: true          # 3D buildings: OpenStreetMap footprints, heights from swisstopo
  ortho_detail_m: auto     # sharp photo near the pilot: auto (0.5 m if resolution_m <= 1), a value, or off""",
        analysis_opts="""  los_agl_m: [10, 30, 60, 120]   # flat shadow maps
  los_resolution_m: 10     # signal analysis grid (m)
  loss_offsets_db: [-9, -6, -3, 0, 3, 6, 9, 12, 15, 18, 21]   # radio-budget steps for live antenna / power edits"""),
    "lite": dict(
        terrain_opts="""  ortho_resolution_m: auto       # sharpest photo that stays <= 2048 px (or a value in m, e.g. 2)
  buildings: false         # off in Lite mode. true = 3D buildings (OpenStreetMap footprints, swisstopo heights)
  ortho_detail_m: off      # off in Lite mode. auto = sharp 0.5 m photo near the pilot when resolution_m <= 1""",
        analysis_opts="""  los_agl_m: [30, 120]     # flat shadow maps (the 3D shadows already cover every height)
  los_resolution_m: 20     # signal analysis grid (m)
  loss_offsets_db: [-6, 0, 6, 12]   # radio-budget steps for live antenna / power edits"""),
}

DEFAULT_LINKS = """links:
  - name: "Video 5.8 GHz"
    freq_mhz: 5800
    tx_power_dbm: 27       # 500 mW
    tx_gain_dbi: 2
    rx_gain_dbi: 8
    rx_sensitivity_dbm: -90
    misc_losses_db: 3
    fade_margin_db: 10
    color: "#ff4fd8"
  - name: "Control ELRS 2.4 GHz"
    freq_mhz: 2440
    tx_power_dbm: 24       # 250 mW
    tx_gain_dbi: 2
    rx_gain_dbi: 2
    rx_sensitivity_dbm: -108
    misc_losses_db: 3
    fade_margin_db: 10
    color: "#33d0ff"
"""


def path_for(name: str) -> Path:
    return LOC_DIR / f"{name}.yaml"


NUM_RE = re.compile(r"^(\d{2,4})_")


def numbered_name(name: str) -> str:
    """New locations are numbered in creation order: 'gruyere' -> '015_gruyere' (next free number, same number of
    digits as the existing ones, 2 when there are none yet). A name that already starts with a number is kept,
    and 'moleson' finds an existing '007_moleson' (so saving it again is an overwrite, not a new number)."""
    if NUM_RE.match(name):
        return name
    names = [f.stem for f in LOC_DIR.glob("*.yaml")]
    trash = ROOT / "deleted"                       # deleted locations keep their number (they can be restored)
    if trash.exists():
        names += [f.stem for f in trash.rglob("*.yaml")]
    for n in names:
        m = NUM_RE.match(n)
        if m and n[m.end():] == name and (LOC_DIR / f"{n}.yaml").exists():
            return n
    nums = [(int(m.group(1)), len(m.group(1))) for n in names if (m := NUM_RE.match(n))]
    width = max((w for _, w in nums), default=2)
    return f"{max((v for v, _ in nums), default=0) + 1:0{width}d}_{name}"


def write_location(name: str, title: str, center, pilot=None, half_size_m=2500, resolution_m=5,
                   surface="dtm", antenna_height_m=1.8, radio_from: Optional[str] = None,
                   overwrite=False, corridor: Optional[dict] = None) -> Path:
    """center / pilot = (lat, lon). radio_from = copy the `links:` of another location.
    corridor = {"points": [(lat, lon), ...], "width_m": 500} for a route-shaped location."""
    from .config import VALID_RES
    if not NAME_RE.match(name or ""):
        raise ValueError("name: lowercase letters, digits, - and _ only (e.g. my_spot_east)")
    name = numbered_name(name)
    if resolution_m not in VALID_RES:
        raise ValueError(f"resolution must be one of {VALID_RES}")
    if surface not in ("dtm", "dsm"):
        raise ValueError("surface must be dtm or dsm")
    if not corridor and not 100 <= half_size_m <= 15000:
        raise ValueError("half size must be between 100 m and 15 km")
    if corridor:
        pts = [tuple(map(float, p)) for p in corridor.get("points") or []]
        width = float(corridor.get("width_m", 500))
        if len(pts) < 2:
            raise ValueError("a route needs at least 2 points")
        if not 50 <= width <= 5000:
            raise ValueError("corridor width must be between 50 m and 5 km (each side)")
    out = path_for(name)
    if out.exists() and not overwrite:
        raise FileExistsError(f"locations/{name}.yaml already exists")
    links = DEFAULT_LINKS
    if radio_from:
        src = yaml.safe_load(path_for(radio_from).read_text(encoding="utf-8")) or {}
        if src.get("links"):
            links = yaml.safe_dump({"links": src["links"]}, sort_keys=False, allow_unicode=True)
    pilot = pilot or center
    from . import mode as _mode
    m = _mode.current()
    LOC_DIR.mkdir(exist_ok=True)
    text = TEMPLATE.format(
        name=name, title=(title or name).replace('"', "'"), clat=center[0], clon=center[1],
        plat=pilot[0], plon=pilot[1], half=half_size_m, antenna=antenna_height_m,
        res=resolution_m, surface=surface, links=links, mode=m, **MODE_OPTS[m])
    if corridor:
        block = ("corridor:                  # route-shaped location: only a strip along these points\n"
                 f"  width_m: {width:g}             # each side of the line\n  points:\n"
                 + "".join(f"    - {{lat: {la:.6f}, lon: {lo:.6f}}}\n" for la, lo in pts))
        text = text.replace(f"center: {{lat: {center[0]:.6f}, lon: {center[1]:.6f}}}\n"
                            f"half_size_m: {half_size_m:g}          # map extends this far from the centre in each direction\n",
                            block, 1)
    write_atomic(out, text)
    return out


def list_locations(scenes_dir: Path):
    """Summaries of all location files (+ whether a scene was built) for the map page."""
    from .config import LocationConfig
    from .geo import lv95_to_wgs84
    res = []
    for f in sorted(LOC_DIR.glob("*.yaml")):
        try:
            c = LocationConfig.load(f)
            ce, cn = c.center.lv95()
            pe, pn = c.pilot.lv95() if c.pilot else (ce, cn)
            clat, clon = lv95_to_wgs84(ce, cn)
            plat, plon = lv95_to_wgs84(pe, pn)
            res.append(dict(
                file=f.name, name=c.name, title=c.title, center=[float(clat), float(clon)],
                center_lv95=[ce, cn], pilot=[float(plat), float(plon)], pilot_from_log=c.pilot is None,
                half_size_m=c.half_size_m, resolution_m=c.terrain.resolution_m, surface=c.terrain.surface,
                antenna_height_m=c.pilot_antenna_height_m,
                corridor=None if c.corridor is None else dict(
                    width_m=c.corridor.width, length_m=round(c.corridor.length_m),
                    points=[[float(v) for v in lv95_to_wgs84(e, n)] for e, n in c.corridor.points]),
                built=(scenes_dir / c.name / "scene.json").exists()))
        except Exception as ex:  # a broken file shouldn't break the map
            res.append(dict(file=f.name, name=f.stem, error=str(ex)))
    return res


LINK_FIELDS = ("tx_power_dbm", "tx_gain_dbi", "rx_gain_dbi", "rx_sensitivity_dbm", "misc_losses_db", "fade_margin_db")


def patch_links(path: Path, updates: list) -> list:
    """Update the radio values of the `links:` block of a location file (matched by link name).
    Only that block is rewritten; the rest of the file (and its comments) is left untouched."""
    import re as _re
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    links = data.get("links") or []
    by_name = {u.get("name"): u for u in updates}
    changed = []
    for l in links:
        u = by_name.get(l.get("name"))
        if not u:
            continue
        for k in LINK_FIELDS:
            if u.get(k) is not None:
                v = round(float(u[k]), 2)
                if l.get(k) != v:
                    l[k] = v
                    changed.append(f"{l['name']}.{k}={v}")
    block = yaml.safe_dump({"links": links}, sort_keys=False, allow_unicode=True)
    m = _re.search(r"^links:.*?(?=^[A-Za-z_][\w-]*:|\Z)", text, flags=_re.M | _re.S)
    new = text[:m.start()] + block + ("\n" if m.end() < len(text) else "") + text[m.end():] if m else text.rstrip() + "\n\n" + block
    write_atomic(path, new)
    return changed


def set_pilot(path: Path, lat: float, lon: float) -> None:
    """Move the pilot point of a location file to lat/lon (keeps comments and the antenna height).
    Used by the live flight's "use the takeoff point as pilot" button."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(r"^pilot:", l)), None)
    if start is None:                                  # no pilot block yet: add one after the centre
        at = next((i + 1 for i, l in enumerate(lines) if re.match(r"^(center|half_size_m|corridor):", l)), len(lines))
        lines[at:at] = ["", "pilot:", f"  lat: {lat:.6f}", f"  lon: {lon:.6f}", "  antenna_height_m: 1.8"]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith((" ", "#"))), len(lines))
        block = lines[start + 1:end]
        block = [l for l in block if not re.match(r"^\s+(lat|lon|e|n):", l)]    # old position (lat/lon or LV95)
        lines[start + 1:end] = [f"  lat: {lat:.6f}", f"  lon: {lon:.6f}"] + block
        if re.match(r"^pilot:\s*\{", lines[start]):      # inline form "pilot: {lat: .., lon: ..}"
            lines[start] = "pilot:"
    write_atomic(path, "\n".join(lines) + "\n")
