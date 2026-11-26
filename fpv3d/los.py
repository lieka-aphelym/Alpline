"""Line-of-sight and Fresnel-zone analysis over a DEM (fully vectorised numpy)."""
from __future__ import annotations

import numpy as np

from .geo import Grid
from .radio import wavelength_m

EARTH_R = 6_371_000.0


class Terrain:
    """Heights on a grid, with bilinear sampling of the ground in local coordinates (x east, y north).

    `dem` is what the signal meets on its way (it may have the 3D buildings standing on it); `ground` (default: the
    same) is what the pilot stands on and what "metres above ground" is measured from. They differ on a bare-ground
    scene with buildings: a drone 30 m above a street is 30 m above the street, not above the roofs, yet a block
    between it and the pilot hides it."""

    def __init__(self, dem: np.ndarray, grid: Grid, ground: np.ndarray = None):
        self.dem = dem.astype(np.float32)
        self.ground = self.dem if ground is None else ground.astype(np.float32)
        self.grid = grid
        self._height_n = grid.max_n - grid.min_n

    def height(self, x, y):
        g = self.grid
        c = np.asarray(x, dtype=np.float64) / g.res - 0.5
        r = (self._height_n - np.asarray(y, dtype=np.float64)) / g.res - 0.5
        c = np.clip(c, 0, g.cols - 1.000001)
        r = np.clip(r, 0, g.rows - 1.000001)
        c0 = c.astype(np.int64)
        r0 = r.astype(np.int64)
        fc = (c - c0).astype(np.float32)
        fr = (r - r0).astype(np.float32)
        d = self.ground
        h00 = d[r0, c0]
        h01 = d[r0, c0 + 1]
        h10 = d[r0 + 1, c0]
        h11 = d[r0 + 1, c0 + 1]
        top = h00 + (h01 - h00) * fc
        bot = h10 + (h11 - h10) * fc
        return top + (bot - top) * fr


def path_clearance(terrain: Terrain, src, tx, ty, tz, freq_mhz: float, k_factor: float = 4 / 3,
                   chunk: int = 32_768, on_progress=None):
    """For each target point, walk the straight line from `src` (x, y, z) and return

        clearance_m   - smallest vertical gap between ray and terrain (<0 = blocked)
        fresnel_ratio - smallest (gap / first Fresnel radius); >= 0.6 is a "clean" link
        dist_m        - 3D distance src->target

    Earth curvature with effective radius k*R is applied (matters a little beyond ~3 km).
    """
    tx = np.asarray(tx, dtype=np.float64).ravel()
    ty = np.asarray(ty, dtype=np.float64).ravel()
    tz = np.asarray(tz, dtype=np.float64).ravel()
    sx, sy, sz = src
    lam = wavelength_m(freq_mhz)
    res = terrain.grid.res
    out_c = np.empty(tx.size, np.float32)
    out_f = np.empty(tx.size, np.float32)
    dist = np.sqrt((tx - sx) ** 2 + (ty - sy) ** 2 + (tz - sz) ** 2)

    # Process targets sorted by distance so each chunk only needs as many steps as its farthest point.
    hd_all = np.hypot(tx - sx, ty - sy)
    order = np.argsort(hd_all)
    dem = terrain.dem
    g = terrain.grid
    flat = dem.ravel()
    ncols = g.cols
    hN = g.max_n - g.min_n
    kR2 = np.float32(2 * k_factor * EARTH_R)
    lam32 = np.float32(lam)
    for a in range(0, tx.size, chunk):
        idx = order[a:a + chunk]
        cx = tx[idx].astype(np.float32)
        cy = ty[idx].astype(np.float32)
        cz = tz[idx].astype(np.float32)
        hd = hd_all[idx].astype(np.float32)
        n = int(np.clip(np.ceil(hd.max() / (0.8 * res)), 16, 4000))
        dx, dy, dz = cx - np.float32(sx), cy - np.float32(sy), cz - np.float32(sz)
        hd_safe = np.maximum(hd, np.float32(1e-3))
        min_c = np.full(idx.size, np.inf, np.float32)
        min_f = np.full(idx.size, np.inf, np.float32)
        # ignore ~1.5 cells around each endpoint (DEM noise right under pilot / drone)
        skip = np.minimum(np.float32(1.5 * res) / hd_safe, np.float32(0.45))
        for i in range(1, n):
            t = np.float32(i / n)
            px = np.float32(sx) + dx * t
            py = np.float32(sy) + dy * t
            col = np.clip((px / res).astype(np.int32), 0, ncols - 1)
            row = np.clip(((hN - py) / res).astype(np.int32), 0, g.rows - 1)
            d1 = hd * t
            d2 = hd - d1
            dd = d1 * d2
            ground = flat[row * ncols + col] + dd / kR2
            gap = np.float32(sz) + dz * t - ground
            r1 = np.sqrt(np.maximum(lam32 * dd / hd_safe, np.float32(1e-6)))
            valid = (t > skip) & (t < 1 - skip)
            gap[~valid] = np.inf
            np.minimum(min_c, gap, out=min_c)
            np.minimum(min_f, gap / r1, out=min_f)
        min_c[np.isinf(min_c)] = 1e4
        min_f[np.isinf(min_f)] = 1e4
        out_c[idx] = min_c
        out_f[idx] = min_f
        if on_progress:
            on_progress(min(a + chunk, tx.size) / tx.size)
    return out_c, out_f, dist


def los_map(terrain: Terrain, src, agl_m: float, los_grid: Grid, freq_mhz: float, k_factor: float, on_progress=None,
            mask=None):
    """Clearance maps for a drone flying `agl_m` above ground everywhere on `los_grid`
    (only where `mask` is True, if given; elsewhere 'clear')."""
    xs, ys = los_grid.cell_centers_local()
    shp = los_grid.shape
    tz = terrain.height(xs, ys) + agl_m
    if mask is None:
        c, f, d = path_clearance(terrain, src, xs, ys, tz, freq_mhz, k_factor, on_progress=on_progress)
        return c.reshape(shp), f.reshape(shp), d.reshape(shp)
    m = mask.ravel()
    c = np.full(m.size, 1e4, np.float32); f = np.full(m.size, 99, np.float32)
    d = np.sqrt((xs.ravel() - src[0]) ** 2 + (ys.ravel() - src[1]) ** 2 + (tz.ravel() - src[2]) ** 2)
    if m.any():
        c[m], f[m], d[m] = path_clearance(terrain, src, xs.ravel()[m], ys.ravel()[m], tz.ravel()[m], freq_mhz, k_factor,
                                          on_progress=on_progress)
    return c.reshape(shp), f.reshape(shp), d.reshape(shp)


class _SubGrid:
    """A list of target points that looks like a Grid to los_ceilings (corridor cells only)."""
    def __init__(self, xs, ys):
        self._xs, self._ys = xs, ys
        self.shape = (xs.size,)

    def cell_centers_local(self):
        return self._xs, self._ys


def _knife_edge_inverse(loss_db):
    """F (clearance / Fresnel radius) at which single knife-edge loss equals loss_db (>0)."""
    v = np.linspace(-0.78, 60, 4000)
    j = 6.9 + 20 * np.log10(np.sqrt((v - 0.1) ** 2 + 1) + v - 0.1)
    return -np.interp(loss_db, j, v) / np.sqrt(2.0)


def los_ceilings(terrain: Terrain, src, los_grid: Grid, freq_mhz: float, k_factor: float,
                 fresnel_clearance: float, budget_db: float, loss_offsets_db=(0,), chunk: int = 32_768,
                 on_progress=None, mask=None):
    """3D blind-spot volumes as 'ceilings': for every column of the map, the height above ground
    below which the drone is
        los      - out of direct line of sight
        fresnel  - Fresnel zone obstructed (clearance < fresnel_clearance * r1)
        loss@d   - predicted link margin < 0 with the link budget changed by d dB
                   (free space + knife edge; budget_db = allowed path loss of the saved settings)
    Several budget offsets are computed in the same pass so the viewer can follow antenna / power
    changes live by interpolating between them. inf = the whole column is blind.

    Uses the 'horizon slope' trick: the lowest visible point above a target is set by the
    steepest terrain slope (seen from the antenna) along the path, so one pass gives all heights.
    """
    from .radio import fspl_db
    xs, ys = los_grid.cell_centers_local()
    shp = los_grid.shape
    if mask is not None:                     # corridor: only the strip, 'never blind' elsewhere
        m = mask.ravel()
        sub, ground_sub = los_ceilings(terrain, src, _SubGrid(xs.ravel()[m], ys.ravel()[m]), freq_mhz, k_factor,
                                       fresnel_clearance, budget_db, loss_offsets_db, chunk, on_progress)
        out = {}
        for k, v in sub.items():
            full = np.zeros(m.size, np.float32)
            full[m] = v.ravel()
            out[k] = full.reshape(shp)
        g = np.zeros(m.size, np.float32)
        g[m] = ground_sub.ravel()
        return out, g.reshape(shp)
    tx, ty = xs.ravel().astype(np.float64), ys.ravel().astype(np.float64)
    ground_t = terrain.height(tx, ty)
    sx, sy, sz = src
    lam = np.float32(wavelength_m(freq_mhz))
    res = terrain.grid.res
    g = terrain.grid
    flat = terrain.dem.ravel()
    ncols, hN = g.cols, g.max_n - g.min_n
    kR2 = np.float32(2 * k_factor * EARTH_R)
    hd_all = np.hypot(tx - sx, ty - sy)
    offs = list(loss_offsets_db)
    # required Fresnel ratio for "margin >= 0" depends only on distance (approx. horizontal)
    f_loss = []
    for d in offs:
        allowed = budget_db + d - fspl_db(hd_all, freq_mhz)              # dB left for diffraction
        f_loss.append(np.where(allowed > 0, _knife_edge_inverse(np.maximum(allowed, 1e-3)), np.inf))
    out = {k: np.empty(tx.size, np.float32) for k in ("los", "fresnel")}
    loss = [np.empty(tx.size, np.float32) for _ in offs]
    order = np.argsort(hd_all)
    for a in range(0, tx.size, chunk):
        idx = order[a:a + chunk]
        cx, cy = tx[idx].astype(np.float32), ty[idx].astype(np.float32)
        hd = hd_all[idx].astype(np.float32)
        fl = [f[idx].astype(np.float32) for f in f_loss]
        n = int(np.clip(np.ceil(hd.max() / (0.8 * res)), 16, 4000))
        dx, dy = cx - np.float32(sx), cy - np.float32(sy)
        hd_safe = np.maximum(hd, np.float32(1e-3))
        skip = np.minimum(np.float32(1.5 * res) / hd_safe, np.float32(0.45))
        s_los = np.full(idx.size, -np.inf, np.float32)
        s_fr = np.full(idx.size, -np.inf, np.float32)
        s_ls = [np.full(idx.size, -np.inf, np.float32) for _ in offs]
        fl_fin = [np.where(np.isfinite(f), f, 0).astype(np.float32) for f in fl]
        for i in range(1, n):
            t = np.float32(i / n)
            col = np.clip(((np.float32(sx) + dx * t) / res).astype(np.int32), 0, ncols - 1)
            row = np.clip(((hN - (np.float32(sy) + dy * t)) / res).astype(np.int32), 0, g.rows - 1)
            d1 = hd * t
            d2 = hd - d1
            obst = flat[row * ncols + col] + d1 * d2 / kR2 - np.float32(sz)   # obstacle height vs antenna
            r1 = np.sqrt(np.maximum(lam * d1 * d2 / hd_safe, np.float32(1e-6)))
            valid = (t > skip) & (t < 1 - skip)
            w = np.where(valid, np.float32(1) / np.maximum(d1, np.float32(1e-3)), np.float32(np.nan))
            np.fmax(s_los, obst * w, out=s_los)
            np.fmax(s_fr, (obst + np.float32(fresnel_clearance) * r1) * w, out=s_fr)
            for j in range(len(offs)):
                np.fmax(s_ls[j], (obst + fl_fin[j] * r1) * w, out=s_ls[j])
        gt = ground_t[idx].astype(np.float32)
        ceil = lambda s: np.maximum(np.float32(sz) + np.where(np.isfinite(s), s, -1e3) * hd - gt, 0)  # noqa: E731, B023 (used at once, in this loop turn)
        out["los"][idx] = ceil(s_los)
        out["fresnel"][idx] = ceil(s_fr)
        for j in range(len(offs)):
            loss[j][idx] = np.where(np.isfinite(fl[j]), ceil(s_ls[j]), np.inf)
        if on_progress:
            on_progress(min(a + chunk, tx.size) / tx.size)
    out = {k: v.reshape(shp) for k, v in out.items()}
    for d, arr in zip(offs, loss):
        out["loss" if d == 0 else f"loss{d:+g}"] = arr.reshape(shp)
    return out, ground_t.reshape(shp)
