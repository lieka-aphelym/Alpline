"""Generate a SYNTHETIC EdgeTX-style telemetry log for an existing scene, so you can try
the viewer before you have a real flight log. The path takes off at the pilot, climbs,
flies a loop that goes behind the terrain, and comes home. RSSI/LQ are simulated.

    python tests/make_demo_log.py scenes/moleson logs/demo_moleson_edgetx.csv
"""
import csv
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fpv3d.geo import Grid, lv95_to_wgs84  # noqa: E402
from fpv3d.los import Terrain, path_clearance  # noqa: E402
from fpv3d.radio import fspl_db, knife_edge_loss_db  # noqa: E402


def main(scene_dir, out_csv):
    scene_dir = Path(scene_dir)
    meta = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    g = meta["grid"]
    grid = Grid(g["min_e"], g["min_n"], g["max_e"], g["max_n"], g["res"])
    terrain = Terrain(np.fromfile(scene_dir / "terrain.f32", "<f4").reshape(grid.shape), grid)
    p = meta["pilot"]
    w, h = grid.max_e - grid.min_e, grid.max_n - grid.min_n

    # aim the loop at the highest point of the map so the drone passes behind it
    r, c = np.unravel_index(np.argmax(terrain.dem), terrain.dem.shape)
    peak = np.array([(c + 0.5) * grid.res, h - (r + 0.5) * grid.res])
    home = np.array([p["x"], p["y"]])
    v = peak - home
    dist = np.linalg.norm(v)
    u = v / dist
    nrm = np.array([-u[1], u[0]])

    hz, speed = 10, 18.0  # 10 samples/s, 18 m/s cruise
    wps = [home, home + u * dist * 0.5 + nrm * 300, peak + nrm * 500, peak + u * 450,
           peak - nrm * 500, home + u * dist * 0.4 - nrm * 250, home]
    pts = []
    for a, b in zip(wps[:-1], wps[1:]):
        seg = np.linalg.norm(b - a)
        k = max(2, int(seg / speed * hz))
        for t in np.linspace(0, 1, k, endpoint=False):
            pts.append(a + (b - a) * t)
    pts.append(home)
    pts = np.array(pts)
    pts[:, 0] = np.clip(pts[:, 0], 5, w - 5)
    pts[:, 1] = np.clip(pts[:, 1], 5, h - 5)
    n = len(pts)
    ground = terrain.height(pts[:, 0], pts[:, 1])
    s = np.linspace(0, 1, n)
    agl = 2 + 55 * np.clip(np.minimum(s, 1 - s) * 12, 0, 1) + 12 * np.sin(s * 23)
    alt = ground + np.maximum(agl, 1.5)

    clear, fres, d3 = path_clearance(terrain, (p["x"], p["y"], p["z"]), pts[:, 0], pts[:, 1], alt, 2440)
    rng = np.random.default_rng(3)
    rssi = 24 + 2 - fspl_db(d3, 2440) - knife_edge_loss_db(fres) - 6 + rng.normal(0, 2.5, n)
    lq = np.clip(100 - np.maximum(0, (-100 - rssi)) * 9 + rng.normal(0, 1.5, n), 0, 100)
    snr = np.clip(rssi + 112 + rng.normal(0, 1, n), -10, 14)

    lat, lon = lv95_to_wgs84(grid.min_e + pts[:, 0], grid.min_n + pts[:, 1])
    t0 = datetime(2026, 9, 12, 14, 30, 0)
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["Date", "Time", "1RSS(dB)", "2RSS(dB)", "RQly(%)", "RSNR(dB)", "TPWR(mW)",
                     "RxBt(V)", "GPS", "GSpd(kmh)", "Alt(m)", "Sats"])
        for i in range(n):
            ts = t0 + timedelta(seconds=i / hz)
            spd = 0 if i == 0 else np.linalg.norm(pts[i] - pts[i - 1]) * hz * 3.6
            wr.writerow([ts.strftime("%Y-%m-%d"), ts.strftime("%H:%M:%S.%f")[:-3],
                         round(rssi[i]), round(rssi[i] - 3), round(lq[i]), round(snr[i]), 250,
                         round(16.4 - 2.2 * i / n, 2), f"{lat[i]:.7f} {lon[i]:.7f}",
                         round(spd, 1), round(alt[i] - ground[0], 1), 14])
    print(f"wrote {n} samples ({n / hz:.0f} s) to {out_csv} - altitude is relative to take-off")


if __name__ == "__main__":
    main(*sys.argv[1:3])
