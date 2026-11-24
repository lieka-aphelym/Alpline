"""Where terrain comes from: one TerrainSource per data provider.

The tile cache (tilecache.py) always works on 1 x 1 km tiles of the source's own metric grid (`crs`) and asks the
source three things: is a usable file already on disk, which files does the provider have for these tiles, and
download one. Everything provider-specific (catalogue, file names, native resolutions) stays inside the source.

Sources: swisstopo (swisstopo.py, Switzerland, 0.5 m and up), Copernicus (copernicus.py, worldwide heights, 30 m),
the ESA WorldCover composite of 2021 (worldcover.py, worldwide photo, 10 m) and, where that has nothing or cannot
be reached, Sentinel-2 cloudless 2016 (sentinel2.py, worldwide photo, 10 m).
chain() says which ones serve a place, in order of preference. A new one subclasses TerrainSource and sets
`cache_prefix` to its name (its files then live in cache/<name>/, apart from the others).

A source for one country (a national lidar model, say) is added with register_regional(): it says where it has
data, and is then asked before the worldwide model for places inside. France's (ign.py: IGN's aerial photo and 1 m
heights) is the first; its module is listed in _BUILTIN. See docs/data-sources.md for other candidates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

Key = Tuple[int, int]            # 1 km tile: (E // 1000, N // 1000) in the source's grid


@dataclass
class Found:
    """One provider file that covers (part of) a tile."""
    href: str
    info: dict = field(default_factory=dict)     # kept in the cache's _index.json (which item / year it came from)


class TerrainSource:
    name = ""
    host = ""                    # shown when the provider can't be reached
    crs = "EPSG:2056"            # the metric grid its cache tiles are cut on
    kinds: Tuple[str, ...] = ()  # of "dtm" (bare ground), "dsm" (trees + buildings), "ortho" (aerial photo)
    cache_prefix = ""            # sub-folder of the cache for this source's resampled tiles ("" = the cache folder)
    credit = ""                  # who to credit for the data

    def resampling(self, kind: str, res: float):
        """How to resample to `res` m (a rasterio Resampling), None = the usual way for this kind."""
        return None

    def raw_dir(self, root: Path, kind: str) -> Path:
        """Folder holding this source's downloads of `kind`."""
        raise NotImplementedError

    def raw_key(self, path: Path) -> Optional[str]:
        """The tile ("E-N") a downloaded file belongs to, None when it is not tied to one tile."""
        return None

    def local_raw(self, root: Path, kind: str, key: Key, res: float) -> List[Path]:
        """Files already downloaded that are enough to make tile `key` at `res` m ([] = a download is needed)."""
        return []

    def lookup(self, kind: str, keys: List[Key], res: float) -> Dict[Key, List[Found]]:
        """Ask the provider what it has for `keys` at `res` m. Tiles it has nothing for are left out.
        Network trouble is raised as OSError."""
        raise NotImplementedError

    def download(self, root: Path, kind: str, found: Found, on_progress=None) -> Optional[Path]:
        """Fetch one file into raw_dir (or reuse it when already there); returns its path, None when the
        provider turns out to have nothing there."""
        raise NotImplementedError


_SOURCES: List[TerrainSource] = []


def register(source: TerrainSource) -> TerrainSource:
    if all(s.name != source.name for s in _SOURCES):
        _SOURCES.append(source)
    return source


def default() -> TerrainSource:
    from . import swisstopo
    return swisstopo.SOURCE


def all_sources() -> List[TerrainSource]:
    default()                                    # makes sure swisstopo is registered
    return list(_SOURCES)


_WORLD: Dict[str, TerrainSource] = {}


@dataclass
class Regional:
    """A source that covers one country or region: what it is, where it has data, and how to make it for a grid."""
    name: str                    # also its cache folder: cache/<name>/
    label: str                   # for people: "Austria, 1 m lidar"
    kinds: Tuple[str, ...]       # of "dtm", "dsm", "ortho"
    covers: object               # covers(lat, lon) -> bool: roughly inside its area (a box is enough: where it has
    #                              no data after all, the next source of the chain fills in)
    make: object                 # make(crs) -> TerrainSource cut on that grid


_REGIONAL: List[Regional] = []


def register_regional(name: str, label: str, kinds, covers, make) -> Regional:
    """Add a source for one country or region. It is asked after the sources of the grid itself (swisstopo on the
    Swiss grid) and before the worldwide ones, for places `covers` says yes to."""
    unregister_regional(name)
    r = Regional(name, label, tuple(kinds), covers, make)
    _REGIONAL.append(r)
    return r


def unregister_regional(name: str) -> None:
    _REGIONAL[:] = [r for r in _REGIONAL if r.name != name]
    for k in [k for k in _WORLD if k.startswith(f"{name}:")]:
        del _WORLD[k]


_BUILTIN = ["ign"]               # modules that register a country's sources when imported (France: ign.py)


def _load_builtin() -> None:
    """Import the country modules once, so their register_regional() calls have run."""
    import importlib
    while _BUILTIN:
        importlib.import_module(f"{__package__}.{_BUILTIN.pop()}")


def regional_sources() -> List[Regional]:
    _load_builtin()
    return list(_REGIONAL)


def regional(r: Regional, crs: str) -> TerrainSource:
    """The regional source `r`, cut on the grid `crs` (one object per grid, like the worldwide ones)."""
    key = f"{r.name}:{crs}"
    if key not in _WORLD:
        _WORLD[key] = r.make(crs)
    return _WORLD[key]


def worldwide(crs: str) -> TerrainSource:
    """The worldwide elevation model, cut on the grid `crs`."""
    if crs not in _WORLD:
        from .copernicus import Copernicus
        _WORLD[crs] = Copernicus(crs)
    return _WORLD[crs]


def worldcover(crs: str) -> TerrainSource:
    """The worldwide satellite photo of 2021 (the first choice), cut on the grid `crs`."""
    key = "photo2021:" + crs
    if key not in _WORLD:
        from .worldcover import WorldCover
        _WORLD[key] = WorldCover(crs)
    return _WORLD[key]


def worldwide_photo(crs: str) -> TerrainSource:
    """The worldwide satellite photo of 2016 (the fallback), cut on the grid `crs`."""
    key = "photo:" + crs
    if key not in _WORLD:
        from .sentinel2 import Sentinel2
        _WORLD[key] = Sentinel2(crs)
    return _WORLD[key]


def chain(crs: Optional[str], kind: str, where=None) -> List[TerrainSource]:
    """The sources that can give `kind` on the grid `crs`, best first; a later one only fills what the
    earlier ones lack. Sources added with register() come first on their own grid, then the regional sources that
    cover `where` (lat, lon of the place, or a list of such points: one inside is enough, so an area across a border
    gets both countries; none are asked when it is not given), then the worldwide ones (for the photo: the 2021
    picture, then the 2016 one)."""
    crs = crs or default().crs
    _load_builtin()
    out = [s for s in all_sources() if s.crs == crs and kind in s.kinds]
    if where is not None:
        pts = [where] if isinstance(where[0], (int, float)) else list(where)
        out += [regional(r, crs) for r in _REGIONAL if kind in r.kinds and any(r.covers(la, lo) for la, lo in pts)]
    out += [worldwide(crs)] if kind in ("dtm", "dsm") else [worldcover(crs), worldwide_photo(crs)]
    return out
