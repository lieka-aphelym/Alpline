"""Location / radio configuration loaded from a YAML file (see locations/*.yaml)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

from .geo import wgs84_to_lv95

VALID_RES = (0.5, 1, 2, 2.5, 4, 5, 8, 10, 20, 25, 40, 50)


@dataclass
class Point:
    """A location given either as lat/lon (WGS84) or e/n (LV95)."""
    lat: Optional[float] = None
    lon: Optional[float] = None
    e: Optional[float] = None
    n: Optional[float] = None

    @classmethod
    def from_dict(cls, d):
        if d is None:
            return None
        if isinstance(d, (list, tuple)) and len(d) == 2:
            a, b = float(d[0]), float(d[1])
            # Heuristic: LV95 numbers are huge, lat/lon are small.
            return cls(e=a, n=b) if a > 1e6 else cls(lat=a, lon=b)
        return cls(**{k: float(v) for k, v in d.items() if k in ("lat", "lon", "e", "n")})

    def lv95(self):
        if self.e is not None and self.n is not None:
            return self.e, self.n
        if self.lat is None or self.lon is None:
            raise ValueError("point needs lat/lon or e/n")
        e, n = wgs84_to_lv95(self.lat, self.lon)
        return float(e), float(n)


@dataclass
class Link:
    name: str
    freq_mhz: float
    tx_power_dbm: float
    tx_gain_dbi: float = 2.0
    rx_gain_dbi: float = 2.0
    rx_sensitivity_dbm: float = -90.0
    misc_losses_db: float = 3.0
    fade_margin_db: float = 10.0
    color: str = "#ff4fd8"


@dataclass
class TerrainCfg:
    resolution_m: float = 5.0
    surface: str = "dtm"          # "dtm" = bare ground, "dsm" = incl. trees & buildings
    ortho: bool = True
    ortho_resolution_m: float = 2.0
    local_dem_files: List[str] = field(default_factory=list)   # optional offline GeoTIFFs
    buildings: bool = True            # 3D buildings (OpenStreetMap footprints + swisstopo heights)
    detail_radius_m: float = 600      # sharp aerial photo around the pilot ...
    ortho_detail_m: object = "auto"   # ... at this resolution (m); auto = 0.5 m when resolution_m <= 1, off = none


@dataclass
class AnalysisCfg:
    los_agl_m: List[float] = field(default_factory=lambda: [10, 30, 60, 120])
    los_resolution_m: float = 10.0
    primary_link: int = 0
    k_factor: float = 4.0 / 3.0
    fresnel_clearance: float = 0.6


@dataclass
class LocationConfig:
    name: str
    title: str
    center: Point
    half_size_m: float
    pilot: Optional[Point]
    pilot_antenna_height_m: float
    terrain: TerrainCfg
    analysis: AnalysisCfg
    links: List[Link]
    logs: List[str]
    log_options: dict
    source_path: Path
    corridor: Optional[object] = None      # fpv3d.corridor.Corridor for route-shaped locations

    def grid(self, res: float):
        """The scene's grid at `res`: square around the centre, or the box around a corridor."""
        from .geo import Grid
        if self.corridor is not None:
            return self.corridor.grid(res, self.pilot.lv95() if self.pilot else None)
        ce, cn = self.center.lv95()
        return Grid.around(ce, cn, self.half_size_m, res)

    @classmethod
    def load(cls, path) -> "LocationConfig":
        path = Path(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        terrain = TerrainCfg(**(raw.get("terrain") or {}))
        if terrain.resolution_m not in VALID_RES:
            raise ValueError(f"terrain.resolution_m must be one of {VALID_RES}")
        if terrain.surface not in ("dtm", "dsm"):
            raise ValueError("terrain.surface must be 'dtm' or 'dsm'")
        analysis = AnalysisCfg(**(raw.get("analysis") or {}))
        pilot_raw = raw.get("pilot") or {}
        pilot = Point.from_dict({k: v for k, v in pilot_raw.items() if k in ("lat", "lon", "e", "n")}) \
            if any(k in pilot_raw for k in ("lat", "lon", "e", "n")) else None
        links = [Link(**l) for l in (raw.get("links") or [])]
        if not links:
            raise ValueError("define at least one radio link under 'links:'")
        base = path.parent
        logs = [str((base / p).resolve()) if not Path(p).is_absolute() else p for p in (raw.get("logs") or [])]
        from .corridor import Corridor
        corridor = Corridor.from_raw(raw.get("corridor"))
        if corridor is not None:
            ce, cn = corridor.center()
            e0, n0, e1, n1 = corridor.bbox()
            center, half = Point(e=ce, n=cn), max(e1 - e0, n1 - n0) / 2
            if pilot is None:                      # default pilot: start of the route
                pilot = Point(e=float(corridor.points[0][0]), n=float(corridor.points[0][1]))
        else:
            center, half = Point.from_dict(raw["center"]), float(raw.get("half_size_m", 2500))
        return cls(
            name=raw.get("name") or path.stem,
            title=raw.get("title") or raw.get("name") or path.stem,
            center=center,
            half_size_m=half,
            corridor=corridor,
            pilot=pilot,
            pilot_antenna_height_m=float(pilot_raw.get("antenna_height_m", 1.8)),
            terrain=terrain,
            analysis=analysis,
            links=links,
            logs=logs,
            log_options=raw.get("log_options") or {},
            source_path=path,
        )
