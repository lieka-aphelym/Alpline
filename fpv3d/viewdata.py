"""Pieces of a scene served on demand to the viewer (local server only):

    terrain_window  part of the terrain grid at a given step (decimated overview / sharp close-up)
    ortho_window    aerial photo crop from the finest cached swissimage tiles (sharp close-up)
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

TILE = 1000


def _scene_meta(scene_dir: Path):
    return json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))


def terrain_window(scene_dir: Path, which="surface", step=1, c0=0, r0=0, cols=None, rows=None):
    """float32 array (rows, cols) sampled every `step` cells starting at (r0, c0)."""
    m = _scene_meta(scene_dir)
    if which == "dtm" and m.get("terrain_dtm"):
        g, f = m["terrain_dtm"]["grid"], scene_dir / m["terrain_dtm"]["file"]
    else:
        g, f = m["grid"], scene_dir / m["terrain"]
    arr = np.memmap(f, dtype="<f4", mode="r", shape=(g["rows"], g["cols"]))
    step = max(1, int(step))
    c0, r0 = max(0, int(c0)), max(0, int(r0))
    cols = (g["cols"] - c0 + step - 1) // step if cols is None else int(cols)
    rows = (g["rows"] - r0 + step - 1) // step if rows is None else int(rows)
    win = np.ascontiguousarray(arr[r0:r0 + rows * step:step, c0:c0 + cols * step:step], dtype="<f4")
    del arr
    return win, g


def encode_d16(win: np.ndarray):
    """Terrain heights in a compact form for the viewer: decimetres above the lowest point, as 16-bit numbers, each
    stored as the difference to its left neighbour (wrapping at 65536). Half the size of float32, and the small
    differences of real terrain compress 3-5x better on top. Returns (bytes, base_m). Precision: 0.1 m."""
    base = float(np.nanmin(win)) if np.isfinite(win).any() else 0.0
    q = np.round((np.nan_to_num(win, nan=base) - base) * 10).clip(0, 65535).astype(np.uint32)
    d = (np.diff(q, axis=1, prepend=0) & 0xFFFF).astype("<u2")
    return d.tobytes(), base


def decode_d16(data: bytes, rows: int, cols: int, base: float) -> np.ndarray:
    """The inverse of encode_d16 (what the viewer does in JavaScript), for the tests."""
    d = np.frombuffer(data, dtype="<u2").reshape(rows, cols).astype(np.uint32)
    q = np.cumsum(d, axis=1) & 0xFFFF
    return (q * 0.1 + base).astype(np.float32)


def ortho_window(scene_dir: Path, cache_dir: Path, x0, y0, x1, y1, max_px=2048):
    """JPEG bytes of the aerial photo over local rect (x0, y0)-(x1, y1), or None."""
    m = _scene_meta(scene_dir)
    det = m.get("detail") or {}
    res_list = [det["res"]] if det.get("res") else []
    g = m["grid"]
    e0, n0, e1, n1 = g["min_e"] + x0, g["min_n"] + y0, g["min_e"] + x1, g["min_n"] + y1
    for res in res_list:
        d = cache_dir / "lod" / "ortho" / f"{res:g}m"
        if not d.exists():
            continue
        px = TILE / res
        W, H = int(round((e1 - e0) / res)), int(round((n1 - n0) / res))
        if W <= 0 or H <= 0:
            return None
        canvas = Image.new("RGB", (W, H), (0, 0, 0))
        mask = Image.new("L", (W, H), 0)
        hit = False
        for ke in range(int(e0 // TILE), int((e1 - 1e-6) // TILE) + 1):
            for kn in range(int(n0 // TILE), int((n1 - 1e-6) // TILE) + 1):
                p = d / f"{ke}-{kn}.jpg"
                if not p.exists():
                    continue
                hit = True
                # tile top-left (north-west) in window pixels
                ox = int(round((ke * TILE - e0) / res))
                oy = int(round((n1 - (kn + 1) * TILE) / res))
                im = Image.open(p).convert("RGB")
                if im.size[0] != int(px):
                    im = im.resize((int(px), int(px)))
                canvas.paste(im, (ox, oy))
                mask.paste(255, (max(ox, 0), max(oy, 0), min(ox + int(px), W), min(oy + int(px), H)))
        if not hit:
            continue
        if mask.getextrema()[0] == 0:      # partly outside the sharp area: only send if mostly covered
            cov = np.asarray(mask).mean() / 255
            if cov < 0.6:
                return None
        s = min(1.0, max_px / max(W, H))
        if s < 1:
            canvas = canvas.resize((max(1, int(W * s)), max(1, int(H * s))), Image.BILINEAR)
        buf = io.BytesIO()
        canvas.save(buf, "JPEG", quality=88)
        return buf.getvalue()
    return None
