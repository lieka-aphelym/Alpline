"""Location / radio configuration loaded from a YAML file (see locations/*.yaml)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import yaml

from .geo import LV95, project, utm_crs

VALID_RES = (0.5, 1, 2, 2.5, 4, 5, 8, 10, 20, 25, 40, 50)


SWISS_BOX = (45.7, 5.8, 47.9, 10.6)      # lat0, lon0, lat1, lon1: Switzerland and its border regions


def crs_for(lat: float, lon: float) -> str:
    """The metric grid a place is built on: Swiss LV95 in and right around Switzerland (swisstopo data, gaps
    across the border filled from the worldwide model), the place's UTM zone anywhere else."""
    la0, lo0, la1, lo1 = SWISS_BOX
    return LV95 if la0 <= lat <= la1 and lo0 <= lon <= lo1 else utm_crs(lat, lon)


@dataclass
class Point:
    """A location given either as lat/lon (WGS84) or e/n (metres on the location's grid, LV95 in Switzerland)."""
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

    def en(self, crs: str = LV95):
        """(E, N) metres on the grid `crs`."""
        if self.e is not None and self.n is not None:
            return self.e, self.n
        if self.lat is None or self.lon is None:
            raise ValueError("point needs lat/lon or e/n")
        e, n = project(self.lat, self.lon, crs)
        return float(e), float(n)

    def lv95(self):
        return self.en(LV95)


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
    ortho_resolution_m: object = 2.0  # metres, or "auto" = sharpest that keeps the photo <= 2048 px (Lite default)
    local_dem_files: List[str] = field(default_factory=list)   # optional offline GeoTIFFs
    buildings: bool = True            # 3D buildings (OpenStreetMap footprints; heights measured in Switzerland, else from tags)
    detail_radius_m: float = 600      # sharp aerial photo around the pilot ...
    ortho_detail_m: object = "auto"   # ... at this resolution (m); auto = 0.5 m when resolution_m <= 1, off = none


@dataclass
class AnalysisCfg:
    los_agl_m: List[float] = field(default_factory=lambda: [10, 30, 60, 120])
    los_resolution_m: float = 10.0
    primary_link: int = 0
    k_factor: float = 4.0 / 3.0
    fresnel_clearance: float = 0.6
    # radio-budget steps (dB) precomputed for the 3D "predicted loss" shadows (live antenna / power edits)
    loss_offsets_db: List[float] = field(default_factory=lambda: [-9, -6, -3, 0, 3, 6, 9, 12, 15, 18, 21])


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
    corridor: Optional[Any]    = None      # fpv3d.corridor.Corridor for route-shaped locations
    crs: str = LV95                        # the metric grid of this location (LV95 in Switzerland, else its UTM zone)

    def center_en(self):
        return self.center.en(self.crs)

    def pilot_en(self):
        """The pilot on this location's grid, None when it comes from the first flight log."""
        return self.pilot.en(self.crs) if self.pilot else None

    def ortho_res(self, grid=None) -> float:
        """Aerial photo resolution: the configured value, or for "auto" the sharpest valid one that
        keeps the image at most 2048 px wide (a light texture for the browser), never finer than 2 m."""
        r = self.terrain.ortho_resolution_m
        if r != "auto":
            return float(r)                          # type: ignore[arg-type]
        g: Any = grid or self.grid(10)
        span = max(g.max_e - g.min_e, g.max_n - g.min_n)
        return next((v for v in VALID_RES if v >= 2 and span / v <= 2048), VALID_RES[-1])

    def grid(self, res: float):
        """The scene's grid at `res`: square around the centre, or the box around a corridor."""
        from .geo import Grid
        if self.corridor is not None:
            return self.corridor.grid(res, self.pilot_en())
        ce, cn = self.center_en()
        return Grid.around(ce, cn, self.half_size_m, res, self.crs)

    @classmethod
    def load(cls, path) -> "LocationConfig":
        """Read a location file. Any mistake in it gives a ValueError saying what is wrong (shown on the map page,
        in the launcher and by the build), never a crash further on."""
        path = Path(path)
        try:
            c = cls._load(path)
        except (AttributeError, TypeError) as ex:          # a section with the wrong shape (text instead of {...} ...)
            raise ValueError(f"{path.name}: unexpected layout ({ex}); compare with a working location file") from None
        if isinstance(c.name, (int, float)) and not isinstance(c.name, bool):
            c.name = str(c.name)                           # name: 015 is read as a number
        if not isinstance(c.name, str) or not c.name:
            raise ValueError(f"{path.name}: 'name' must be a text")
        if not (c.half_size_m > 0):
            raise ValueError(f"{path.name}: half_size_m must be more than 0")
        return c

    @classmethod
    def _load(cls, path: Path) -> "LocationConfig":
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as ex:                        # typo in the file: say where
            mark = getattr(ex, "problem_mark", None)
            where = f" (line {mark.line + 1})" if mark else ""
            raise ValueError(f"{path.name}: not a valid location file{where}: {getattr(ex, 'problem', None) or ex}") from None
        if not isinstance(raw, dict):
            raise ValueError(f"{path.name}: expected 'name: ...', 'center: ...' lines, found something else")
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
        crs = _crs_of(raw)
        corridor = Corridor.from_raw(raw.get("corridor"), crs)  # type: ignore[arg-type]
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
            crs=crs,
            pilot=pilot,
            pilot_antenna_height_m=float(pilot_raw.get("antenna_height_m", 1.8)),
            terrain=terrain,
            analysis=analysis,
            links=links,
            logs=logs,
            log_options=raw.get("log_options") or {},
            source_path=path,
        )


def _crs_of(raw: dict) -> str:
    """The grid of a location file: its `crs:` line when it has one, else from where its centre (or the start of
    its route) is. Positions written as e/n metres are Swiss LV95."""
    if raw.get("crs"):
        crs = str(raw["crs"]).upper()
        if not crs.startswith("EPSG:"):
            raise ValueError("crs must look like EPSG:32632")
        return crs
    first = (raw.get("corridor") or {}).get("points") or [raw.get("center")]
    p = Point.from_dict(first[0]) if first and first[0] is not None else None
    if p is None or p.lat is None or p.lon is None:
        return LV95
    return crs_for(p.lat, p.lon)
