"""Speed-ups that must not change results:   python -m pytest tests/test_performance.py

  - compact terrain (&enc=d16): half the size, heights within 5 cm, same in Python and in the viewer's JavaScript
  - compression for the phone: same bytes after unpacking; never on this computer (no use there)
(The faster builds - flat maps drawn from the 3D volumes - are checked in test_snapshots.py.)"""
import gzip
import http.client
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from fpv3d.viewdata import decode_d16, encode_d16  # noqa: E402
from test_security import phone_port  # noqa: E402
from test_server import _TMP, req  # noqa: E402


def sample_terrain():
    rng = np.random.default_rng(7)
    y, x = np.mgrid[0:120, 0:150]
    h = 600 + 1800 * np.exp(-((x - 70) ** 2 + (y - 50) ** 2) / 900) + rng.normal(0, 0.3, x.shape)
    h[:, 100] += 900                                         # a 900 m cliff
    h[5, 5] = np.nan                                         # a hole in the data
    return h.astype(np.float32)


def test_d16_roundtrip():
    h = sample_terrain()
    data, base = encode_d16(h)
    assert len(data) == h.size * 2                           # half of float32
    back = decode_d16(data, *h.shape, base)
    ok = np.isfinite(h)
    assert np.abs(back[ok] - h[ok]).max() <= 0.051
    assert len(gzip.compress(data)) < len(gzip.compress(h.tobytes())) / 2   # and it compresses much better


def test_d16_in_javascript():
    node = shutil.which("node")
    if not node:
        print("  (Node not installed: skipped)")
        return
    h = sample_terrain()
    data, base = encode_d16(h)
    f = _TMP / "d16.bin"
    f.write_bytes(data)
    js = f"""
import {{ readTerrain }} from {json.dumps((HERE.parent / 'viewer' / 'terrain_codec.js').as_uri())};
import {{ readFileSync }} from 'fs';
const buf = readFileSync({json.dumps(str(f))});
const hdr = {{ 'X-Enc': 'd16', 'X-Base': '{base}', 'X-Scale': '0.1', 'X-Cols': '{h.shape[1]}' }};
const r = {{ headers: {{ get: (k) => hdr[k] }}, arrayBuffer: async () => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length) }};
const out = await readTerrain(r, {h.shape[1]});
process.stdout.write(JSON.stringify(Array.from(out.filter((_, i) => i % 97 === 0))));
"""
    m = _TMP / "d16_check.mjs"
    m.write_text(js, encoding="utf-8")
    out = json.loads(subprocess.run([node, str(m)], capture_output=True, text=True, timeout=30, check=True).stdout)
    py = decode_d16(data, *h.shape, base).ravel()[::97]
    assert len(out) == len(py) and np.abs(np.array(out) - py).max() < 1e-3


def make_scene(name="097_perf"):
    sd = _TMP / "scenes" / name
    sd.mkdir(parents=True, exist_ok=True)
    h = sample_terrain()
    (sd / "terrain.f32").write_bytes(h.astype("<f4").tobytes())
    meta = dict(name=name, terrain="terrain.f32", grid=dict(rows=h.shape[0], cols=h.shape[1], res=2.0), tracks=[])
    (sd / "scene.json").write_text(json.dumps(meta), encoding="utf-8")
    (sd / "big.json").write_text(json.dumps({"points": list(range(20000))}), encoding="utf-8")
    return name, h


def test_terrain_api_compact():
    name, h = make_scene()
    st, raw32, _ = req("GET", f"/api/terrain?scene={name}&step=1")
    st2, raw16, hd = req("GET", f"/api/terrain?scene={name}&step=1&enc=d16")
    assert st == st2 == 200 and hd.get("x-enc") == "d16" and len(raw16) * 2 == len(raw32)
    a = np.frombuffer(raw32, "<f4")
    b = decode_d16(raw16, int(hd["x-rows"]), int(hd["x-cols"]), float(hd["x-base"])).ravel()
    ok = np.isfinite(a)
    assert np.abs(a[ok] - b[ok]).max() <= 0.051
    assert "content-encoding" not in hd                     # this computer: never compressed


def phone_get(path, accept="gzip, deflate"):
    from fpv3d import server
    old = dict(server.SHARE)
    try:
        server.SHARE.update(on=True, pin="424242")
        c = http.client.HTTPConnection("127.0.0.1", phone_port(), timeout=10)
        c.request("GET", path, headers={"Cookie": "alp_pin=424242", "Accept-Encoding": accept})
        r = c.getresponse()
        out = r.status, r.read(), {k.lower(): v for k, v in r.getheaders()}
        c.close()
        return out
    finally:
        server.SHARE.clear(); server.SHARE.update(old)


def test_phone_gets_compressed_files():
    name, _ = make_scene()
    plain = (_TMP / "scenes" / name / "big.json").read_bytes()
    st, body, h = phone_get(f"/scenes/{name}/big.json")
    assert st == 200 and h.get("content-encoding") == "gzip" and len(body) < len(plain) / 2
    assert gzip.decompress(body) == plain
    st, body, h = phone_get(f"/api/terrain?scene={name}&step=1&enc=d16")
    assert st == 200 and h.get("content-encoding") == "gzip" and len(gzip.decompress(body)) == 120 * 150 * 2
    st, body, h = phone_get(f"/scenes/{name}/big.json", accept="identity")   # a browser that can't unpack: plain
    assert st == 200 and "content-encoding" not in h and body == plain
    st, body, h = phone_get("/viewer/app.js")
    assert st == 200 and h.get("content-encoding") == "gzip"


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  ok    {name}")
            except Exception as ex:                         # noqa: BLE001
                fails += 1; print(f"  FAIL  {name}: {ex!r}")
    sys.exit(1 if fails else 0)
