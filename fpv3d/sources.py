"""Where terrain comes from: one TerrainSource per data provider.

The tile cache (tilecache.py) always works on 1 x 1 km tiles of the source's own metric grid (`crs`) and asks the
source three things: is a usable file already on disk, which files does the provider have for these tiles, and
download one. Everything provider-specific (catalogue, file names, native resolutions) stays inside the source.

swisstopo (swisstopo.py) is the only source today. A new one subclasses TerrainSource, sets `cache_prefix` to its
name (its files then live in cache/<name>/, apart from the others) and is added with register().
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
    cache_prefix = ""            # sub-folder of the cache for this source's files ("" = the cache folder itself)

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

    def download(self, root: Path, kind: str, found: Found, on_progress=None) -> Path:
        """Fetch one file into raw_dir (or reuse it when already there); returns its path."""
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


def for_crs(crs: Optional[str]) -> TerrainSource:
    """The source whose tiles are cut on `crs` (a Grid's crs)."""
    for s in all_sources():
        if s.crs == (crs or default().crs):
            return s
    raise RuntimeError(f"no terrain source for the coordinate system {crs}")
