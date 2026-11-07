"""Regression snapshots of the signal model:   python -m pytest tests/test_snapshots.py

The line of sight, the blind-spot ceilings and the radio range for a fixed test terrain are saved once in
tests/snapshots/signal.json. If a later change moves them (even by a few metres or a few percent), this fails and
says which number moved. When a change is meant to move them (a better model), refresh the file:
    UPDATE_SNAPSHOTS=1 python -m pytest tests/test_snapshots.py
and say why in the commit message."""
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fpv3d import radio  # noqa: E402
from fpv3d.config import Link  # noqa: E402
from fpv3d.geo import Grid  # noqa: E402
from fpv3d.los import Terrain, los_ceilings, los_map  # noqa: E402

SNAP = Path(__file__).parent / "snapshots" / "signal.json"


def terrain():
    """2 x 2 km, 10 m cells: a valley floor at 1000 m, a 300 m ridge across it and a peak (like a launch spot)."""
    grid = Grid(2_560_000, 1_160_000, 2_562_000, 1_162_000, 10)
    xs, ys = np.meshgrid(np.arange(grid.shape[1]) * 10 + 5.0, (grid.shape[0] - 1 - np.arange(grid.shape[0])) * 10 + 5.0)  # row 0 = north
    dem = 1000 + 300 * np.exp(-((xs - 1100) / 90) ** 2) * (0.6 + 0.4 * np.cos(ys / 300))
    dem += 450 * np.exp(-(((xs - 1600) / 250) ** 2 + ((ys - 600) / 300) ** 2))
    dem += 8 * np.sin(xs / 70) * np.cos(ys / 90)
    return Terrain(dem.astype(np.float32), grid), grid


def compute():
    t, grid = terrain()
    src = (300.0, 1000.0, float(t.height(np.array([300.0]), np.array([1000.0]))[0]) + 1.8)   # pilot west of the ridge
    lg = grid.with_resolution(40)
    out = {}
    for agl in (10, 60):
        c, f, d = los_map(t, src, agl, lg, 5800, 4 / 3)
        out[f"no_los_pct_{agl}m"] = round(float((c < 0).mean() * 100), 2)
        out[f"fresnel_pct_{agl}m"] = round(float((f < 0.6).mean() * 100), 2)
    link = Link("video", 5800, 27, 8, 8, -95, 3, 10)                  # 500 mW, patch antennas: reaches most of the map
    ce, _ground = los_ceilings(t, src, lg, 5800, 4 / 3, 0.6, radio.allowed_path_loss_db(link), loss_offsets_db=(0, 6))
    for k in ("los", "fresnel", "loss", "loss+6"):
        a = ce[k]
        fin = a[np.isfinite(a)]
        out[f"ceiling_{k}_mean_m"] = round(float(fin.mean()), 1) if fin.size else None
        out[f"ceiling_{k}_blind_pct"] = round(float((~np.isfinite(a)).mean() * 100), 2)
    # a few fixed spots (row, col on the 40 m grid): behind the ridge, on the peak, open valley
    for name, (r, cc) in {"behind_ridge": (25, 33), "peak": (35, 40), "valley": (10, 15)}.items():
        v = float(ce["los"][r, cc])
        out[f"ceiling_los_{name}_m"] = round(v, 1) if np.isfinite(v) else "inf"
    for mw, gain in ((25, 2), (500, 2), (1000, 8)):
        l = Link("x", 5800, 10 * np.log10(mw), gain, 2, -85, 3, 10)
        out[f"range_{mw}mW_{gain}dBi_km"] = round(radio.max_range_m(l) / 1000, 3)
    return out


TOL = {"pct": 0.5, "_m": 1.0, "_km": 0.002}


def test_signal_model_unchanged():
    now = compute()
    if os.environ.get("UPDATE_SNAPSHOTS") or not SNAP.exists():
        SNAP.parent.mkdir(exist_ok=True)
        SNAP.write_text(json.dumps(now, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  (snapshot written: {SNAP.name})")
        return
    old = json.loads(SNAP.read_text(encoding="utf-8"))
    moved = []
    for k in sorted(set(old) | set(now)):
        a, b = old.get(k), now.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            tol = next((v for suf, v in TOL.items() if k.endswith(suf) or suf in k), 0.01)
            if abs(a - b) > tol:
                moved.append(f"{k}: {a} -> {b}")
        elif a != b:
            moved.append(f"{k}: {a} -> {b}")
    assert not moved, "the signal model changed:\n  " + "\n  ".join(moved) + \
        "\n(if that is intended: UPDATE_SNAPSHOTS=1 python -m pytest tests/test_snapshots.py)"


def test_flat_maps_equal_the_3d_volumes():
    """Builds draw the flat shadow maps from the 3D volumes (one pass instead of one per height). Checks that this
    gives the same answer as computing each flat map on its own, for line of sight, Fresnel zone and signal loss."""
    t, grid = terrain()
    src = (300.0, 1000.0, float(t.height(np.array([300.0]), np.array([1000.0]))[0]) + 1.8)
    lg = grid.with_resolution(40)
    for link in (Link("v", 5800, 27, 8, 8, -95, 3, 10), Link("w", 5800, 14, 2, 2, -85, 3, 10)):
        ce, _ = los_ceilings(t, src, lg, link.freq_mhz, 4 / 3, 0.6, radio.allowed_path_loss_db(link))
        for agl in (10, 30, 60, 120):
            c, f, d = los_map(t, src, agl, lg, link.freq_mhz, 4 / 3)
            same = lambda a, b: float((a == b).mean())                                  # noqa: E731
            assert same(c < 0, ce["los"] > agl) > 0.999, (link.name, agl, "line of sight")

            def colours(blocked, fresnel_bad, lost):             # what the map shows (see scene.build_los_layers)
                k = np.zeros(blocked.shape, int)
                k[fresnel_bad] = 1; k[fresnel_bad & lost] = 2; k[blocked] = 3; k[blocked & lost] = 4
                return k
            one_by_one = colours(c < 0, (f < 0.6) & (c >= 0), radio.link_margin_db(link, d, f) < 0)
            bl = ce["los"] > agl
            from_3d = colours(bl, (ce["fresnel"] > agl) & ~bl, ce["loss"] > agl)
            assert same(one_by_one, from_3d) > 0.999, (link.name, agl, "map colours")


def test_snapshot_terrain_is_meaningful():
    """The test terrain really has shadows and clear areas (otherwise the snapshot would prove nothing)."""
    now = compute()
    assert 5 < now["no_los_pct_10m"] < 80 and now["no_los_pct_60m"] < now["no_los_pct_10m"]
    assert now["ceiling_los_valley_m"] in (0.0, 0) and (now["ceiling_los_behind_ridge_m"] == "inf"
                                                       or now["ceiling_los_behind_ridge_m"] > 20)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ok    {name}")
