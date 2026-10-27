"""Corridor locations: a strip of terrain along a route (pilot -> summit, along a ridge, ...)
instead of a full square.

    corridor:
      points: [{lat: 46.55, lon: 7.01}, {lat: 46.56, lon: 7.04}]   # 2+ points (LV95 [e, n] also ok)
      width_m: 500                                                  # each side of the line

Only the 1 km tiles the strip touches are downloaded at full detail. Signal analysis needs the
terrain between the pilot and every point of the strip, so the area spanned by the pilot and the
route (its convex hull) is filled with a coarse bare-ground model ("context", 10 m).
Inside the program the scene is still a rectangle; cells outside the strip are just not shown
and not analysed.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from .geo import Grid

TILE = 1000
CONTEXT_RES = 10.0


class Corridor:
    def __init__(self, points: List[Tuple[float, float]], width_m: float):
        if len(points) < 2:
            raise ValueError("corridor: needs at least 2 points")
        if not 50 <= width_m <= 5000:
            raise ValueError("corridor.width_m must be between 50 and 5000")
        self.points = np.array(points, np.float64)       # LV95 (e, n)
        self.width = float(width_m)

    @classmethod
    def from_raw(cls, raw: dict) -> Optional["Corridor"]:
        if not raw:
            return None
        from .config import Point
        pts = [Point.from_dict(p).lv95() for p in raw.get("points") or []]
        return cls(pts, float(raw.get("width_m", 500)))

    # ------------------------------------------------------------ geometry
    @property
    def length_m(self) -> float:
        return float(np.sum(np.hypot(*np.diff(self.points, axis=0).T)))

    def bbox(self, extra=0.0, also=None):
        w = self.width + extra
        p = self.points if also is None else np.vstack([self.points, np.atleast_2d(also)])
        return (p[:, 0].min() - w, p[:, 1].min() - w, p[:, 0].max() + w, p[:, 1].max() + w)

    def grid(self, res: float, pilot_en=None) -> Grid:
        """Box around the strip (and the pilot, so every signal path stays inside)."""
        e0, n0, e1, n1 = self.bbox(also=pilot_en)
        return Grid(float(np.floor(e0 / res) * res), float(np.floor(n0 / res) * res),
                    float(np.ceil(e1 / res) * res), float(np.ceil(n1 / res) * res), res)

    def center(self):
        e0, n0, e1, n1 = self.bbox()
        return (e0 + e1) / 2, (n0 + n1) / 2

    def area_km2(self) -> float:
        """Strip area (segments x 2w + round ends), ignoring overlaps at bends."""
        return (self.length_m * 2 * self.width + np.pi * self.width ** 2) / 1e6

    def distance(self, e, n):
        """Distance (m) from LV95 points to the route line (arrays ok)."""
        e = np.asarray(e, np.float64)
        n = np.asarray(n, np.float64)
        best = np.full(np.broadcast(e, n).shape, np.inf)
        for (ax, ay), (bx, by) in zip(self.points[:-1], self.points[1:]):
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy or 1e-9
            t = np.clip(((e - ax) * dx + (n - ay) * dy) / L2, 0, 1)
            np.minimum(best, np.hypot(e - (ax + t * dx), n - (ay + t * dy)), out=best)
        return best

    def mask(self, grid: Grid, extra=0.0, rows_per_chunk=256) -> np.ndarray:
        """bool (rows, cols): cell centre within width (+extra) of the route."""
        out = np.zeros(grid.shape, bool)
        es = grid.min_e + (np.arange(grid.cols) + 0.5) * grid.res
        for r0 in range(0, grid.rows, rows_per_chunk):
            r1 = min(r0 + rows_per_chunk, grid.rows)
            ns = grid.max_n - (np.arange(r0, r1) + 0.5) * grid.res
            E, N = np.meshgrid(es, ns)
            out[r0:r1] = self.distance(E, N) <= self.width + extra
        return out

    # ------------------------------------------------------------ tiles
    def tile_keys(self, extra=0.0):
        """1 km tiles that the strip touches."""
        e0, n0, e1, n1 = self.bbox(extra)
        keys = []
        for ke in range(int(e0 // TILE), int(np.ceil(e1 / TILE))):
            for kn in range(int(n0 // TILE), int(np.ceil(n1 / TILE))):
                if self._rect_distance(ke * TILE, kn * TILE, (ke + 1) * TILE, (kn + 1) * TILE) <= self.width + extra:
                    keys.append((ke, kn))
        return keys

    def _rect_distance(self, x0, y0, x1, y1) -> float:
        """Distance between the route and an axis-aligned rectangle (0 when they touch)."""
        # sample the route densely enough (25 m) and clamp to the rectangle: robust and simple
        best = np.inf
        for (ax, ay), (bx, by) in zip(self.points[:-1], self.points[1:]):
            n = max(2, int(np.hypot(bx - ax, by - ay) / 25) + 1)
            t = np.linspace(0, 1, n)
            px, py = ax + (bx - ax) * t, ay + (by - ay) * t
            dx = np.maximum(np.maximum(x0 - px, 0), px - x1)
            dy = np.maximum(np.maximum(y0 - py, 0), py - y1)
            best = min(best, float(np.hypot(dx, dy).min()))
        return best

    def hull(self, pilot_en=None):
        """Convex hull (LV95 polygon) of the route points and the pilot."""
        pts = self.points if pilot_en is None else np.vstack([self.points, [pilot_en]])
        pts = sorted(set(map(tuple, pts)))
        if len(pts) < 3:
            return np.array(pts)

        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
        lower, upper = [], []
        for p in pts:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)
        for p in reversed(pts):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)
        return np.array(lower[:-1] + upper[:-1])

    def context_keys(self, pilot_en=None):
        """Tiles inside the (buffered) hull of route + pilot: coarse terrain for signal analysis."""
        h = self.hull(pilot_en)
        hc = Corridor(list(map(tuple, np.vstack([h, h[:1]]))) if len(h) >= 2 else [tuple(h[0]), tuple(h[0])], self.width)
        e0, n0, e1, n1 = hc.bbox()
        keys = []
        for ke in range(int(e0 // TILE), int(np.ceil(e1 / TILE))):
            for kn in range(int(n0 // TILE), int(np.ceil(n1 / TILE))):
                cx, cy = (ke + 0.5) * TILE, (kn + 0.5) * TILE
                if _inside(h, cx, cy) or hc._rect_distance(ke * TILE, kn * TILE, (ke + 1) * TILE, (kn + 1) * TILE) <= self.width:
                    keys.append((ke, kn))
        return keys

    def to_meta(self, grid: Grid, pilot_en=None):
        """For scene.json: route in local metres (viewer), plus hull."""
        loc = (self.points - [grid.min_e, grid.min_n]).round(2).tolist()
        h = self.hull(pilot_en) - [grid.min_e, grid.min_n]
        return dict(points=loc, width_m=self.width, length_m=round(self.length_m, 1),
                    area_km2=round(self.area_km2(), 2), hull=h.round(1).tolist())


def _inside(poly, x, y) -> bool:
    if len(poly) < 3:
        return False
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside
