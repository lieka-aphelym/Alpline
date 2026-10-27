"""Location files (locations/*.yaml): create, list, summarise.

Used by `python -m fpv3d new` and by the map page (`python -m fpv3d map`).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
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
  ortho_resolution_m: 2
  buildings: true          # 3D buildings: OpenStreetMap footprints, heights from swisstopo
  ortho_detail_m: auto     # sharp photo near the pilot: auto (0.5 m if resolution_m <= 1), a value, or off
  detail_radius_m: 600

analysis:
  los_agl_m: [10, 30, 60, 120]
  los_resolution_m: 10
  primary_link: 0          # index into links: used for the shadow map
  k_factor: 1.333
  fresnel_clearance: 0.6

{links}
logs: []
log_options:
  altitude_mode: auto      # auto | amsl | relative | agl
  altitude_offset_m: 0
"""

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


def write_location(name: str, title: str, center, pilot=None, half_size_m=2500, resolution_m=5,
                   surface="dtm", antenna_height_m=1.8, radio_from: Optional[str] = None,
                   overwrite=False, corridor: Optional[dict] = None) -> Path:
    """center / pilot = (lat, lon). radio_from = copy the `links:` of another location.
    corridor = {"points": [(lat, lon), ...], "width_m": 500} for a route-shaped location."""
    from .config import VALID_RES
    if not NAME_RE.match(name or ""):
        raise ValueError("name: lowercase letters, digits, - and _ only (e.g. moleson_east)")
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
    LOC_DIR.mkdir(exist_ok=True)
    text = TEMPLATE.format(
        name=name, title=(title or name).replace('"', "'"), clat=center[0], clon=center[1],
        plat=pilot[0], plon=pilot[1], half=half_size_m, antenna=antenna_height_m,
        res=resolution_m, surface=surface, links=links)
    if corridor:
        block = ("corridor:                  # route-shaped location: only a strip along these points\n"
                 f"  width_m: {width:g}             # each side of the line\n  points:\n"
                 + "".join(f"    - {{lat: {la:.6f}, lon: {lo:.6f}}}\n" for la, lo in pts))
        text = text.replace(f"center: {{lat: {center[0]:.6f}, lon: {center[1]:.6f}}}\n"
                            f"half_size_m: {half_size_m:g}          # map extends this far from the centre in each direction\n",
                            block, 1)
    out.write_text(text, encoding="utf-8")
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
    path.write_text(new, encoding="utf-8")
    return changed
