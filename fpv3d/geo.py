"""Coordinate helpers: WGS84 (lat/lon) <-> Swiss LV95 (EPSG:2056).

Uses swisstopo's official approximate formulas (accuracy ~1 m), which is
plenty for flight visualisation and keeps the project free of pyproj.
"""
from __future__ import annotations

import numpy as np


def wgs84_to_lv95(lat, lon):
    """Return (E, N) in LV95 metres. Accepts scalars or numpy arrays."""
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    phi = (lat * 3600.0 - 169028.66) / 10000.0
    lam = (lon * 3600.0 - 26782.5) / 10000.0
    e = (2600072.37 + 211455.93 * lam - 10938.51 * lam * phi
         - 0.36 * lam * phi ** 2 - 44.54 * lam ** 3)
    n = (1200147.07 + 308807.95 * phi + 3745.25 * lam ** 2 + 76.63 * phi ** 2
         - 194.56 * lam ** 2 * phi + 119.79 * phi ** 3)
    return e, n


def lv95_to_wgs84(e, n):
    """Return (lat, lon) in degrees. Accepts scalars or numpy arrays."""
    y = (np.asarray(e, dtype=np.float64) - 2600000.0) / 1e6
    x = (np.asarray(n, dtype=np.float64) - 1200000.0) / 1e6
    lam = (2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x ** 2
           - 0.0436 * y ** 3)
    phi = (16.9023892 + 3.238272 * x - 0.270978 * y ** 2 - 0.002528 * x ** 2
           - 0.0447 * y ** 2 * x - 0.0140 * x ** 3)
    return phi * 100.0 / 36.0, lam * 100.0 / 36.0


class Grid:
    """A north-up raster grid in LV95.

    Cell (row, col) has its centre at
        E = min_e + (col + 0.5) * res
        N = max_n - (row + 0.5) * res
    "Local" coordinates used by the viewer are x = E - min_e, y = N - min_n.
    """

    def __init__(self, min_e: float, min_n: float, max_e: float, max_n: float, res: float):
        self.min_e, self.min_n, self.max_e, self.max_n, self.res = min_e, min_n, max_e, max_n, res
        self.cols = int(round((max_e - min_e) / res))
        self.rows = int(round((max_n - min_n) / res))

    @classmethod
    def around(cls, center_e: float, center_n: float, half_size: float, res: float) -> "Grid":
        min_e = np.floor((center_e - half_size) / res) * res
        min_n = np.floor((center_n - half_size) / res) * res
        max_e = np.ceil((center_e + half_size) / res) * res
        max_n = np.ceil((center_n + half_size) / res) * res
        return cls(float(min_e), float(min_n), float(max_e), float(max_n), res)

    @property
    def shape(self):
        return (self.rows, self.cols)

    def with_resolution(self, res: float) -> "Grid":
        return Grid(self.min_e, self.min_n, self.max_e, self.max_n, res)

    def wgs84_bbox(self, pad_m: float = 0.0):
        """(min_lon, min_lat, max_lon, max_lat) covering the grid."""
        es = [self.min_e - pad_m, self.max_e + pad_m]
        ns = [self.min_n - pad_m, self.max_n + pad_m]
        lats, lons = [], []
        for e in es:
            for n in ns:
                la, lo = lv95_to_wgs84(e, n)
                lats.append(float(la))
                lons.append(float(lo))
        return min(lons), min(lats), max(lons), max(lats)

    def to_local(self, e, n):
        return np.asarray(e) - self.min_e, np.asarray(n) - self.min_n

    def cell_centers_local(self):
        xs = (np.arange(self.cols) + 0.5) * self.res
        ys = self.max_n - self.min_n - (np.arange(self.rows) + 0.5) * self.res
        return np.meshgrid(xs, ys)

    def to_dict(self):
        return dict(min_e=self.min_e, min_n=self.min_n, max_e=self.max_e, max_n=self.max_n,
                    res=self.res, rows=self.rows, cols=self.cols)
