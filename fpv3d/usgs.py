"""United States: bare-ground heights of the USGS 3D Elevation Program (3DEP, 1 m where lidar exists, 10 m elsewhere)
and the aerial photo of the National Agriculture Imagery Program (NAIP, 0.6 m, through the USGS "NAIP Plus" service).

Both are ArcGIS image services of The National Map, no account needed (checked 25 November 2026):
  heights https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage
          cuts any box on any grid (UTM, latitude/longitude ...) and answers a 32 bit float GeoTIFF; outside the US
          every value is the nodata value asked for
  photo   https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer/exportImage
          the same for the photo, as a JPEG; black where there is no picture (outside the US)
Both answer "200 OK" with an HTML error page when a request is too large (4000 x 4000 heights): the content type is
checked, not only the status.

Licence: works of the US federal government, in the public domain. The services credit "USGS National Map 3D
Elevation Program (3DEP)" and "USGS, USDA, The National Map: Orthoimagery"; those credits are shown.

The heights are NAVD 88 (Alaska, Hawaii: their own datums), within about a metre of the worldwide model's sea level.
3DEP is bare ground only: a location asking for trees and buildings ("dsm") keeps the worldwide model.

The photo is often a few years old (2017 to 2019 in the places checked; 2013 in Hawaii); newer NAIP years exist in
Microsoft's Planetary Computer, whose terms were not settled (see docs/data-sources.md).
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from . import sources
from .ign import MARGIN, _get, _inside

_BASE = os.environ.get("FPV3D_USGS_BASE")        # tests: one fake server for both services
HEIGHT_URL = f"{_BASE}/3dep" if _BASE else "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
PHOTO_URL = f"{_BASE}/naip" if _BASE else "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer"
NODATA = -99999.0
HEIGHT_STEPS = (1.0, 2.0, 5.0)
PHOTO_NATIVE_M = 0.6
PHOTO_STEPS = (0.6, 1.2, 2.4, 4.8, 9.6, 19.2)
HEIGHT_CREDIT = "USGS National Map 3D Elevation Program (3DEP), public domain"
PHOTO_CREDIT = "USGS, USDA, The National Map: Orthoimagery (NAIP), public domain"

# the 48 states, a little generous (lon, lat); where the outline reaches into Canada or Mexico the services have
# nothing (photo) or the neighbour's coarse model (heights), and the worldwide sources fill in
_LOWER48 = [(-125.0, 49.1), (-95.1, 49.1), (-94.8, 49.5), (-89.5, 48.1), (-84.5, 46.7), (-82.3, 45.4), (-82.3, 43.0),
            (-79.0, 43.5), (-76.8, 44.1), (-74.7, 45.1), (-71.5, 45.1), (-70.0, 46.8), (-69.2, 47.5), (-67.7, 47.2),
            (-66.8, 44.8), (-69.8, 41.2), (-74.0, 40.3), (-75.3, 35.1), (-80.0, 31.8), (-79.9, 25.0), (-82.0, 24.4),
            (-83.0, 28.8), (-85.0, 29.4), (-89.5, 28.8), (-94.0, 29.2), (-97.2, 25.8), (-99.5, 27.4), (-101.4, 29.7),
            (-103.0, 28.9), (-104.8, 29.8), (-106.6, 31.7), (-108.3, 31.2), (-111.1, 31.2), (-114.9, 32.4),
            (-117.2, 32.4), (-118.6, 33.5), (-120.8, 34.3), (-124.6, 40.2), (-124.9, 46.0)]


# Alaska's panhandle along the Canadian border (lon, lat); the rest of Alaska is the box west of 141 W
_PANHANDLE = [(-141.0, 60.4), (-139.1, 60.4), (-137.5, 59.2), (-136.5, 59.7), (-135.0, 59.9), (-133.4, 58.5),
              (-131.8, 56.7), (-130.0, 56.1), (-129.9, 55.3), (-130.6, 54.6), (-133.8, 54.5), (-137.0, 57.5),
              (-141.0, 59.6)]


def covers(lat: float, lon: float) -> bool:
    return (_inside(lon, lat, _LOWER48)
            or (51.0 <= lat <= 71.6 and (-180.0 <= lon <= -141.0 or 172.0 <= lon <= 180.0))   # Alaska, the Aleutians
            or _inside(lon, lat, _PANHANDLE)
            or (18.8 <= lat <= 22.4 and -160.5 <= lon <= -154.6))         # Hawaii


def height_step(res: float) -> float:
    """The detail to fetch for heights wanted at `res` m, averaged here. Not the service's own coarse answer: from
    10 m on it switches to another dataset (1.5 m off the averaged 1 m data, up to 12 m on steep ground, checked
    25 November 2026), while its 2 m answer matches the averaged 1 m to a few centimetres."""
    return 1.0 if res < 2 else 2.0 if res < 20 else 5.0


def photo_step(res: float) -> float:
    """The coarsest pixel at least as fine as `res` m (never finer than the 0.6 m of NAIP)."""
    fit = [s for s in PHOTO_STEPS if s <= res + 1e-9]
    return fit[-1] if fit else PHOTO_STEPS[0]


def _export(url: str, crs: str, key, step: float, fmt: str) -> str:
    n = int(round((1000 + 2 * MARGIN) / step))
    epsg = crs.split(":")[-1]
    bbox = f"{key[0] * 1000 - MARGIN},{key[1] * 1000 - MARGIN},{(key[0] + 1) * 1000 + MARGIN},{(key[1] + 1) * 1000 + MARGIN}"
    extra = "&pixelType=F32&noData=-99999&interpolation=RSP_BilinearInterpolation" if fmt == "tiff" else ""
    return f"{url}/exportImage?bbox={bbox}&bboxSR={epsg}&imageSR={epsg}&size={n},{n}&format={fmt}{extra}&f=image"


def _check(data: bytes, magic, what: str) -> None:
    if not data.startswith(magic):          # an error comes back as an HTML page with "200 OK"
        raise OSError(f"USGS {what}: unexpected answer ({data[:120]!r})")


class _Usgs(sources.TerrainSource):
    kind = ""
    steps: tuple = ()

    def __init__(self, crs: str):
        self.crs = crs
        self.cache_prefix = f"{self.name}/{crs.split(':')[-1]}"

    def raw_dir(self, root: Path, kind: str) -> Path:
        return Path(root) / self.name / "raw"

    def step(self, res: float) -> float:
        raise NotImplementedError

    def _stem(self, key, step: float) -> str:
        # cut on a grid: its number keeps the same tile of two grids apart (UTM 10 / 11)
        return f"{self.crs.split(':')[-1]}-{key[0]}-{key[1]}-{step:g}m"

    def raw_names(self, key) -> set:
        return {self._stem(key, s) for s in self.steps} | {self._stem(key, 0)}

    def local_raw(self, root: Path, kind: str, key, res: float) -> List[Path]:
        folder = self.raw_dir(root, kind)
        if (folder / f"{self._stem(key, 0)}.missing").exists():
            return []                     # nothing there: remembered by download(), the next source answers
        for s in self.steps:
            if s <= self.step(res):
                f = folder / f"{self._stem(key, s)}.tif"
                if f.exists() and f.stat().st_size > 0:
                    return [f]
        return []

    def lookup(self, kind: str, keys, res: float) -> Dict[tuple, List[sources.Found]]:
        """No catalogue to ask: the service cuts the box asked for."""
        step = self.step(res)
        url = HEIGHT_URL if self.kind == "dtm" else PHOTO_URL
        fmt = "tiff" if self.kind == "dtm" else "jpg"
        return {tuple(k): [sources.Found(_export(url, self.crs, k, step, fmt),
                                         dict(source=f"{self.label} {step:g} m", key=list(k), step=step))] for k in keys}

    def download(self, root: Path, kind: str, found: sources.Found, on_progress=None) -> Optional[Path]:
        import rasterio
        from rasterio.transform import from_origin
        k, step = tuple(found.info["key"]), float(found.info["step"])
        folder = self.raw_dir(root, kind)
        dest = folder / f"{self._stem(k, step)}.tif"
        missing = folder / f"{self._stem(k, 0)}.missing"
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        if missing.exists():
            return None
        n = int(round((1000 + 2 * MARGIN) / step))
        bands = self._read(_get(found.href, dest.name), n)
        folder.mkdir(parents=True, exist_ok=True)
        if bands is None:
            missing.touch()                                         # outside the US: nothing here
            return None
        tmp = dest.with_suffix(".part")
        dtm = self.kind == "dtm"
        with rasterio.open(tmp, "w", driver="GTiff", width=n, height=n, count=bands.shape[0], dtype=bands.dtype,
                           crs=self.crs, **(dict(compress="deflate", nodata=NODATA, predictor=3) if dtm else
                                            # a 0.6 m picture is 10 MB per km² losslessly; as JPEG about 1 MB
                                            dict(compress="jpeg", photometric="ycbcr", jpeg_quality=90)),
                           transform=from_origin(k[0] * 1000 - MARGIN, (k[1] + 1) * 1000 + MARGIN, step, step)) as d:
            d.write(bands)
        tmp.replace(dest)
        return dest

    def _read(self, data: bytes, n: int) -> Optional[np.ndarray]:
        raise NotImplementedError


class UsgsHeights(_Usgs):
    name = "usgs_3dep"
    label = "USGS 3DEP"
    host = "elevation.nationalmap.gov"
    kinds = ("dtm",)
    kind = "dtm"
    credit = HEIGHT_CREDIT
    steps = HEIGHT_STEPS

    def step(self, res: float) -> float:
        return height_step(res)

    def resampling(self, kind: str, res: float):
        from rasterio.warp import Resampling
        return Resampling.bilinear if res < HEIGHT_STEPS[0] else Resampling.average

    def _read(self, data: bytes, n: int) -> Optional[np.ndarray]:
        from rasterio.io import MemoryFile
        _check(data, (b"II*\x00", b"MM\x00*"), "heights")
        with MemoryFile(data) as mf, mf.open() as r:
            z = r.read(1).astype("float32")
        if z.shape != (n, n):
            raise OSError(f"USGS heights: {z.shape} instead of {n} x {n}")
        good = (z > -1000) & np.isfinite(z)
        if not good.any():
            return None
        return np.where(good, z, NODATA).astype("float32")[None]


class UsgsPhoto(_Usgs):
    name = "usgs_naip"
    label = "USGS NAIP"
    host = "imagery.nationalmap.gov"
    kinds = ("ortho",)
    kind = "ortho"
    credit = PHOTO_CREDIT
    native_m = PHOTO_NATIVE_M
    patchy = True                        # black where NAIP has no picture (across a border): the satellite fills it
    steps = PHOTO_STEPS

    def step(self, res: float) -> float:
        return photo_step(res)

    def resampling(self, kind: str, res: float):
        from rasterio.warp import Resampling
        return Resampling.bilinear if res < PHOTO_NATIVE_M else Resampling.average

    def _read(self, data: bytes, n: int) -> Optional[np.ndarray]:
        from PIL import Image
        _check(data, b"\xff\xd8", "photo")
        rgb = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
        if rgb.shape[:2] != (n, n):
            raise OSError(f"USGS photo: {rgb.shape[:2]} instead of {n} x {n}")
        if rgb.max() < 8:
            return None                  # all black: no picture here
        return np.transpose(rgb, (2, 0, 1)).copy()


def register():
    sources.register_regional("usgs_3dep", "United States, 1 to 10 m heights (USGS 3DEP)", ("dtm",), covers, UsgsHeights)
    sources.register_regional("usgs_naip", "United States, aerial photo (USGS NAIP)", ("ortho",), covers, UsgsPhoto)


register()
