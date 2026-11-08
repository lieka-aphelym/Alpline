"""Battery analysis: python -m pytest tests/test_battery.py

  - the analysis finds the pack's resistance it was given, filters the glitches real logs have, counts mAh / Wh
  - cells by Betaflight's rule, radio-log columns (RxBt / Curr), logs without a current sensor, short bench logs
  - a blackbox with a GPS flight and a battery-only flight: both kept, the GPS one linked to its 3D track (+ path
    colours), packs, which pack flew what, health flags, landing advice, the charger check and its Betaflight scale
  - the server's battery API (and delete only from this computer)"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from fpv3d import battery  # noqa: E402

OCV = [[0, 3.30], [.05, 3.55], [.1, 3.65], [.2, 3.72], [.3, 3.76], [.4, 3.80], [.5, 3.84], [.6, 3.88], [.7, 3.95], [.8, 4.03], [.9, 4.11], [1, 4.20]]


def sim_flight(r_cell=0.0045, cap=1300, dur=200, rate=50, cells=6, seed=1, noise=0.03):
    """A pack under a freestyle-like load with a known resistance."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, dur, 1 / rate)
    base = 0.27 + 0.08 * np.sin(t / 7)
    punch = ((t % 9) < 0.8).astype(float) * 0.55
    thr = np.where((t > 3) & (t < dur - 5), np.clip(base + punch, 0, 1), 0.04)
    i = 1.2 + 100 * thr ** 1.7 * (0.9 + 0.2 * rng.random(len(t)))
    mah = np.cumsum(i / rate) / 3.6
    soc = np.clip(0.99 - mah / cap, 0, 1)
    v = cells * (np.interp(soc, [a for a, _ in OCV], [b for _, b in OCV]) - i * r_cell) + rng.normal(0, noise, len(t))
    return t, v, i, thr


def test_resistance_is_found():
    for r in (0.002, 0.0045, 0.009):
        t, v, i, thr = sim_flight(r)
        sm = battery.summary(battery.series(t, v, i, thr), capacity=1300)
        assert abs(sm["ir_cell_mohm"] - r * 1000) < 0.15 * r * 1000 + 0.1, (r, sm["ir_cell_mohm"])
        mah = float(np.sum(i) / 50 / 3.6)
        assert abs(sm["mah"] - mah) < 0.02 * mah
        assert sm["cells"] == 6 and sm["peak_c"] > 50 and sm["landing_mah"] == 1040


def test_glitches_are_filtered():
    t, v, i, thr = sim_flight(0.005)
    v2, i2 = v.copy(), i.copy()
    v2[::97] += 9                                    # the spikes seen in a real log (32 V, 184 A on a 6S)
    i2[::97] += 150
    clean = battery.summary(battery.series(t, v, i, thr))
    dirty = battery.summary(battery.series(t, v2, i2, thr))
    assert abs(dirty["ir_cell_mohm"] - clean["ir_cell_mohm"]) < 0.3
    assert abs(dirty["mah"] - clean["mah"]) < 0.03 * clean["mah"] and dirty["peak_a"] < 140


def test_cells_by_betaflight_rule():
    assert [battery.cells_from_voltage(v) for v in (25.2, 22.0, 18.0, 16.8, 14.8, 12.6, 8.4, 4.2)] == [6, 6, 5, 4, 4, 3, 2, 1]


def test_without_current_and_short_bench_logs():
    t, v, i, thr = sim_flight(0.005, dur=60)
    s = battery.series(t, v, np.zeros_like(i), thr, meta=dict(has_current=False))
    sm = battery.summary(s, capacity=1300)
    assert sm["mah"] is None and sm["ir_cell_mohm"] is None and sm["min_cell"] > 3 and "used_pct" not in sm
    tb = np.arange(0, 8, 0.02)                        # 8 s on the bench, under 1 A: no resistance, no crash
    sm = battery.summary(battery.series(tb, 22.0 + 0 * tb, 0.3 + 0 * tb))
    assert sm["ir_cell_mohm"] is None and (sm["mah"] or 0) < 5


def test_radio_log_columns():
    t = np.arange(0, 120, 1.0)
    tel = {"RxBt_V": 16.6 - 0.008 * t - 0.4 * ((t % 10) < 2), "Curr_A": 8 + 30 * ((t % 10) < 2), "1RSS_dB": -60 + 0 * t}
    s = battery.from_telemetry(t, tel)
    assert s and s["cells"] == 4 and s["source"] == "telemetry"
    assert battery.from_telemetry(t, {"1RSS_dB": -60 + 0 * t}) is None
    rs = battery.resample(s, [0, 30.5, 500])
    assert rs["cell_v"][2] is None and 3.5 < rs["cell_v"][1] < 4.2


def test_packs_health_landing_and_charger():
    root = Path(tempfile.mkdtemp(prefix="alpline_bat_"))
    p1 = battery.save_pack(dict(name="pack 1", cells=6, capacity=1300), root)
    p2 = battery.save_pack(dict(name="pack 2", cells=6, capacity=1300), root)
    for k, (pid, r) in enumerate([(p1, .0040), (p1, .0041), (p1, .0042), (p1, .0042), (p2, .0040), (p2, .0050), (p2, .0062), (p2, .0072)]):
        t, v, i, thr = sim_flight(r, seed=k)
        s = battery.series(t, v, i, thr, source="blackbox", meta=dict(current_sensor=[0, 170], has_current=True))
        fid = battery.save_flight(f"f{k}", s, when=f"2026-0{k + 1}-01 12:00", root=root)
        battery.assign([fid], pid["id"], root)
    o = battery.overview(root)
    a, b = (next(p for p in o["packs"] if p["id"] == x["id"]) for x in (p1, p2))
    assert not a["flags"] and any("ageing" in f for f in b["flags"]) and any("weaker" in f for f in b["flags"])
    assert a["mah_per_min"] and a["landing_mah"] == 1040 and 2 < a["landing_min"] < 12
    assert o["last_pack"] == p2["id"]
    # charger: the drone logged 20 % less than the charger put back -> the sensor reads low, smaller scale
    logged = o["flights"][0]["summary"]["mah"]
    battery.set_charged("f0", round(logged / 0.8), root)
    c = battery.overview(root)["charger"]
    assert not c["ok"] and abs(c["ratio"] - 0.8) < 0.01 and c["scale_now"] == 170 and c["scale_new"] == 136
    # bad input, unknown names
    for bad in (dict(name="", cells=6, capacity=1300), dict(name="x", cells=12, capacity=1300), dict(name="x", cells=6, capacity=5)):
        try:
            battery.save_pack(bad, root)
            raise AssertionError(bad)
        except ValueError:
            pass
    for call in (lambda: battery.assign(["nope"], p1["id"], root), lambda: battery.assign(["f0"], "p99", root),
                 lambda: battery.load_flight("../../etc/passwd", root)):
        try:
            call()
            raise AssertionError("accepted")
        except ValueError:
            pass
    battery.delete_pack(p2["id"], root)
    assert all(f["pack"] != p2["id"] for f in battery.overview(root)["flights"])
    (root / "battery" / "flights" / "f7.json").unlink()                 # cleaned up: the flight leaves the list
    assert "f7" not in [f["id"] for f in battery.overview(root)["flights"]]


def test_blackbox_battery_end_to_end():
    try:
        import orangebox  # noqa: F401
    except ImportError:
        print("  (orangebox not installed: skipped)")
        return
    from make_bbl import make
    from test_journeys import Data
    d = Data()
    d.location()
    d.run("build", "locations/001_field.yaml")
    bbl = d.dir / "LOG00002.BBL"
    make(bbl, [dict(lat0=46.5553, lon0=7.0305, alt_m=1215, seconds=90, battery=dict(cells=6, r_cell=0.005, cap_mah=1300, glitch=True)),
               dict(lat0=46.5553, lon0=7.0305, alt_m=1215, seconds=40, gps=False, battery=dict(cells=4, r_cell=0.008, cap_mah=1500))])
    out = d.run("blackbox", "--file", str(bbl)).stdout
    bats = [l.split()[1] for l in out.splitlines() if l.startswith("BATTERY ")]
    assert len(bats) == 2 and "1 flight(s) added" in out and "battery kept" in out
    reg = json.loads((d.dir / "battery" / "packs.json").read_text(encoding="utf-8"))
    gps, only = reg["flights"][bats[0]], reg["flights"][bats[1]]
    assert gps["scene"] == "001_field" and gps["track"] == bats[0] and only.get("scene") is None
    assert abs(gps["summary"]["ir_cell_mohm"] - 5.0) < 0.5 and gps["cells"] == 6
    assert abs(only["summary"]["ir_cell_mohm"] - 8.0) < 0.8 and only["cells"] == 4
    meta = d.scene("001_field")
    tr = next(t for t in meta["tracks"] if t["name"] == bats[0])
    assert tr["battery"] == bats[0]
    data = json.loads((d.dir / "scenes" / "001_field" / tr["file"]).read_text(encoding="utf-8"))
    cv = [x for x in data["cell_v"] if x is not None]
    assert len(data["cell_v"]) == data["n"] and 3.4 < min(cv) < max(cv) < 4.25 and max(data["amps"]) > 40
    # a rebuild keeps the link (the battery is found again from the log's name)
    d.run("build", "locations/001_field.yaml", "--reuse-terrain")
    assert next(t for t in d.scene("001_field")["tracks"] if t["name"] == bats[0]).get("battery") == bats[0]
    out2 = d.run("blackbox", "--file", str(bbl)).stdout                # twice: nothing new
    assert "BATTERY" not in out2


def test_battery_api():
    from test_security import phone_port  # noqa: F401 - starts the phone server used below
    from test_server import req
    from fpv3d import server
    import http.client
    old_data = battery.DATA
    battery.DATA = Path(tempfile.mkdtemp(prefix="alpline_bat_api_"))      # never your own packs
    try:
        _api_checks(req, server, http, phone_port)
    finally:
        battery.DATA = old_data


def _api_checks(req, server, http, phone_port):
    st, raw, _ = req("GET", "/api/battery/packs")
    assert st == 200 and "packs" in json.loads(raw)
    st, raw, _ = req("POST", "/api/battery/pack", dict(name="api pack", cells=4, capacity=1500))
    pid = json.loads(raw)["pack"]["id"]
    assert st == 200
    assert req("POST", "/api/battery/pack", dict(name="", cells=4, capacity=1500))[0] == 400
    assert req("GET", "/api/battery/flight?id=../../x")[0] == 404
    assert req("POST", "/api/battery/assign", dict(flights=["nope"], pack=pid))[0] == 400
    # the phone may name packs but not delete them
    old = dict(server.SHARE)
    try:
        server.SHARE.update(on=True, pin="424242")
        c = http.client.HTTPConnection("127.0.0.1", phone_port(), timeout=10)
        c.request("POST", "/api/battery/delete-pack", body=json.dumps(dict(id=pid)),
                  headers={"Cookie": "alp_pin=424242", "Content-Type": "application/json"})
        assert c.getresponse().status == 403
    finally:
        server.SHARE.clear(); server.SHARE.update(old)
    assert req("POST", "/api/battery/delete-pack", dict(id=pid))[0] == 200


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  ok    {name}")
            except Exception as ex:                         # noqa: BLE001
                fails += 1; print(f"  FAIL  {name}: {ex!r}")
    sys.exit(1 if fails else 0)
