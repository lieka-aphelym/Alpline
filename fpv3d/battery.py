"""Battery analysis: the pack's voltage and current during a flight, what they say about the flight, and about the
pack itself as it ages.

Sources:
  * Betaflight blackbox: vbatLatest + amperageLatest (about 50 readings a second), throttle and motor outputs
  * radio telemetry logs (EdgeTX, Alpline's live recordings): RxBt / Curr / Capa, about once a second

Per flight (summary()):
  mAh and Wh used, average / peak current (and C with the pack's capacity), the lowest cell voltage under load and
  how long it stayed under 3.5 V, the cell voltage at take-off and the resting voltage at landing (the voltage
  without the sag), the worst sag, and the pack's internal resistance:
      under load the voltage drops by current x resistance. Over a flight the voltage is
          V = rest(charge) - R * I
      rest(charge) is a smooth curve of the mAh used (a cubic is plenty over one flight), R is found by least
      squares on 0.1 s averages, with the outliers dropped. It needs some punch-outs: with steady current
      (or less than ~8 A of spread) R is not reported.
The flights and the packs (name, cells, capacity) are kept in battery/packs.json in your Alpline folder; the
series of each flight in battery/flights/<flight>.json.
"""
from __future__ import annotations

import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from .filelock import try_lock, unlock
from .paths import DATA
from .safefile import write_atomic
from .brand import APP_NAME

BIN_S = 0.1                       # analysis resolution
LOW_CELL = 3.5                    # LiPo "under load" level per cell (V); each chemistry has its own in CHEM
# Pack chemistries: the voltages that matter per cell, the warning levels and what a healthy resistance looks like.
#   LiPo: 4.20 V full, sags little, hurt below ~3.5 V under load / 3.7 V resting at the end of a flight.
#   LiPo HV: the same at 4.35 V full.
#   Li-ion (18650 / 21700 packs for long range): 4.20 V full, made to go much lower (about 3.0 V under load,
#   2.5-2.8 V cut-off), more resistance (more sag), so other levels and other "healthy" numbers.
CHEM: dict[str, dict] = {
    "lipo": dict(label="LiPo", full=4.20, low=3.5, warn_load=3.3, crit_rest=3.4, deep_rest=3.35, ir_good=6, ir_used=10),
    "lihv": dict(label="LiPo HV", full=4.35, low=3.5, warn_load=3.3, crit_rest=3.4, deep_rest=3.35, ir_good=6, ir_used=10),
    "liion": dict(label="Li-ion", full=4.20, low=3.0, warn_load=2.9, crit_rest=3.1, deep_rest=2.9, ir_good=20, ir_used=35),
}


def chem(key):
    return CHEM.get(key or "lipo", CHEM["lipo"])
LANDING_PCT = 80                  # land when this share of the capacity is used (the usual LiPo advice)
_LOCK = threading.Lock()


def store_dir(root: Path | None = None) -> Path:
    root = Path(root) if root else DATA      # (looked up at call time: the tests point it elsewhere)
    return root / "battery"


def flight_file(fid: str, root: Path | None = None) -> Path:
    root = Path(root) if root else DATA
    return store_dir(root) / "flights" / f"{fid}.json"


FID_RE = re.compile(r"^[\w.-]{1,120}$")


# ------------------------------------------------------------------------------------------------------ reading
def cells_from_voltage(v_start: float, max_cell: float = 4.30) -> int:
    """Betaflight's own rule: the pack's cell count from its voltage when plugged in."""
    if not v_start or v_start <= 0:
        return 0
    return int(min(8, v_start / max_cell + 1))


def clean(t, v, i):
    """Drop the glitches (a voltage far from its neighbours, an absurd current) and average into 0.1 s bins.
    Returns t, v, i as numpy arrays (bins with no good sample are left out)."""
    t, v, i = (np.asarray(a, float) for a in (t, v, i))
    ok = np.isfinite(t) & np.isfinite(v) & (v > 1)
    t, v, i = t[ok], v[ok], np.nan_to_num(i[ok], nan=0.0)
    if len(t) < 5:
        return t, v, i
    order = np.argsort(t, kind="stable")
    t, v, i = t[order], v[order], i[order]
    # rolling median over ~1 s (on the sample index: rates differ between sources)
    rate = max(1.0, (len(t) - 1) / max(t[-1] - t[0], 1e-3))
    k = int(min(max(3, rate), 201)) | 1
    pad = k // 2
    vp = np.pad(v, pad, mode="edge")
    med = np.median(np.lib.stride_tricks.sliding_window_view(vp, k), axis=1)
    good = np.abs(v - med) <= np.maximum(0.6, 0.06 * med)
    ip = np.abs(i[good])
    if len(ip) > 20:
        cap = max(np.percentile(ip, 99.5) * 2.5, 30.0)
        good &= (i > -3) & (i < cap)
    t, v, i = t[good], v[good], np.clip(i[good], 0, None)
    if len(t) < 2:
        return t, v, i
    b = np.floor((t - t[0]) / BIN_S).astype(int)
    n = np.bincount(b)
    keep = n > 0
    tb = (np.bincount(b, t)[keep] / n[keep])
    return tb, np.bincount(b, v)[keep] / n[keep], np.bincount(b, i)[keep] / n[keep]


def series(t, v, i, thr=None, cells=0, source="", meta=None, t0=0.0, cells_guessed=False):
    """A flight's battery series (0.1 s), with the cell count when known (else from the voltage)."""
    tb, vb, ib = clean(t, v, i)
    if len(tb) < 10:
        return None
    th = None
    if thr is not None:
        tt = np.asarray(t, float); th_raw = np.asarray(thr, float)
        ok = np.isfinite(tt) & np.isfinite(th_raw)
        if ok.sum() > 1:
            th = np.interp(tb, tt[ok], th_raw[ok])
    n0 = max(1, int(np.ceil(1.0 / BIN_S)))
    v_start = float(np.median(vb[:n0]))
    guessed = not cells or cells_guessed
    cells = cells or cells_from_voltage(v_start)
    meta = dict(meta or {})
    if guessed and cells > 1 and v_start / (cells - 1) <= 4.40:
        meta["cells_alt"] = cells - 1                      # a full LiPo HV pack with one cell fewer reads the same
    r = lambda a, d: [round(float(x), d) for x in a]  # noqa: E731
    out = dict(version=1, source=source, cells=cells, t=r(tb - t0, 2), v=r(vb, 3), i=r(ib, 2), meta=meta or {})
    if th is not None:
        out["thr"] = r(np.clip(th, 0, 1), 3)
    return out


class BlackboxCollector:
    """Gathers voltage, current and throttle while the caller walks a blackbox log's frames ONCE (the GPS reader in
    blackbox.py walks the same frames; decoding is the slow part, about 18 s for a 5-minute flight)."""

    def __init__(self, names):
        self.ok = "vbatLatest" in names and "time" in names
        if not self.ok:
            return
        self.it, self.iv = names.index("time"), names.index("vbatLatest")
        self.ia = names.index("amperageLatest") if "amperageLatest" in names else None
        self.ith = names.index("rcCommand[3]") if "rcCommand[3]" in names else None
        self.T, self.V, self.I, self.TH = [], [], [], []

    def add(self, d):
        if not self.ok:
            return
        try:
            tt, vv = d[self.it], d[self.iv]
        except IndexError:
            return
        if tt in ("", None) or vv in ("", None):
            return
        ia, ith = self.ia, self.ith
        self.T.append(tt); self.V.append(vv / 100)
        self.I.append((d[ia] / 100) if ia is not None and ia < len(d) and d[ia] not in ("", None) else 0.0)
        self.TH.append(((d[ith] - 1000) / 1000) if ith is not None and ith < len(d) and d[ith] not in ("", None) else np.nan)

    def result(self, headers, t0_us=None):
        """The series, or None. t0_us: the time that is 0 in the flight's track (the first GPS fix), so the battery
        and the 3D replay share the same clock."""
        if not self.ok or len(self.T) < 20:
            return None
        h, V, I = headers, self.V, self.I
        T = np.asarray(self.T, float) / 1e6
        zero = (t0_us / 1e6) if t0_us is not None else T[0]
        cellv = h.get("vbatcellvoltage")
        cellv = cellv if isinstance(cellv, (list, tuple)) and len(cellv) >= 3 else [330, 350, 430]
        v0 = float(np.median(np.asarray(V[: max(5, len(V) // 200)], float)))
        sensor = h.get("currentSensor")
        meta = dict(craft=str(h.get("Craft name", "") or ""), firmware=str(h.get("Firmware revision", "") or ""),
                    current_sensor=list(sensor) if isinstance(sensor, (list, tuple)) else None,
                    has_current=self.ia is not None and any(x > 0.5 for x in I), warn_cell=cellv[1] / 100)
        # Betaflight's default full-cell voltage (4.3 V) can't tell a full HV pack from one more cell: flag the doubt
        return series(T, V, I, self.TH, cells_from_voltage(v0, cellv[-1] / 100), "blackbox", meta, t0=zero,
                      cells_guessed=cellv[-1] <= 430)


def from_blackbox(parser, t0_us=None):
    """Battery series from an orangebox Parser (one log), or None when the log has no voltage."""
    c = BlackboxCollector(parser.field_names)
    if not c.ok:
        return None
    for fr in parser.frames():
        c.add(fr.data)
    return c.result(parser.headers, t0_us)


VOLT_KEYS = re.compile(r"^(rxbt|vbat|voltage|bat_?v|batt?_?volt)", re.I)
CURR_KEYS = re.compile(r"^(curr|current|amperage|amps?)(_|$)", re.I)


def from_telemetry(t, telemetry: dict):
    """Battery series from a radio log's telemetry columns (RxBt / Curr), or None."""
    vk = next((k for k in telemetry if VOLT_KEYS.match(k)), None)
    if not vk:
        return None
    ck = next((k for k in telemetry if CURR_KEYS.match(k)), None)
    v = np.asarray(telemetry[vk], float)
    if np.isfinite(v).sum() < 10 or np.nanmax(v) < 3:
        return None
    i = np.asarray(telemetry[ck], float) if ck else np.zeros_like(v)
    return series(t, v, i, None, 0, "telemetry", dict(columns=[vk, ck], has_current=bool(ck and np.nanmax(i) > 0.5)))


# ----------------------------------------------------------------------------------------------------- analysis
def internal_resistance(t, v, i, mah, cells=1):
    """Pack resistance (ohm) from V = rest(mAh) - R I, robust least squares on 0.5 s averages.
    None without enough load changes, or when the result is not believable (1 to 60 mΩ per cell)."""
    t, v, i, mah = (np.asarray(a, float) for a in (t, v, i, mah))
    if len(t) < 30:
        return None
    b = np.floor((t - t[0]) / 0.5).astype(int)
    n = np.bincount(b)
    k = n > 0
    v, i, mah = (np.bincount(b, a)[k] / n[k] for a in (v, i, mah))
    if len(v) < 12 or np.percentile(i, 95) - np.percentile(i, 5) < 8:
        return None
    x = (mah - mah.min()) / max(np.ptp(mah), 1.0)
    A = np.column_stack([np.ones_like(x), x, x ** 2, x ** 3, -i])
    keep = np.ones(len(v), bool)
    for _ in range(4):
        coef, *_ = np.linalg.lstsq(A[keep], v[keep], rcond=None)
        res = v - A @ coef
        s = np.std(res[keep]) or 1e-6
        nk = np.abs(res) < 3 * s
        if (nk == keep).all() or nk.sum() < 12:
            break
        keep = nk
    R = float(coef[-1])
    return R if 0.001 * cells <= R <= 0.060 * cells else None


def summary(s: dict, capacity=None, cells=None, chemistry=None):
    """What a flight's series says. capacity (mAh), cells and chemistry (lipo, lihv, liion) come from the pack."""
    ch = chem(chemistry)
    t, v, i = (np.asarray(s[k], float) for k in ("t", "v", "i"))
    cells = int(cells or s.get("cells") or 0) or cells_from_voltage(float(v[0]))
    dt = np.diff(t, prepend=t[0])
    dt = np.clip(dt, 0, 1.0)                                         # a gap in the log is not time on the pack
    mah = np.cumsum(i * dt) / 3.6
    wh = float(np.sum(v * i * dt) / 3600)
    has_i = bool(s.get("meta", {}).get("has_current", np.nanmax(i) > 0.5))
    R = internal_resistance(t, v, i, mah, cells) if has_i else None
    cell = v / cells
    n0 = max(1, min(len(v), int(1 / BIN_S)))
    rest_end = float((v[-n0:] + i[-n0:] * (R or 0)).mean() / cells)
    sag = (R * i / cells) if R else None
    out = dict(
        cells=cells, seconds=round(float(t[-1] - t[0]), 1), has_current=has_i,
        mah=round(float(mah[-1]), 0) if has_i else None, wh=round(wh, 2) if has_i else None,
        avg_a=round(float(np.average(i, weights=np.maximum(dt, 1e-3))), 1) if has_i else None,
        peak_a=round(float(np.max(i)), 1) if has_i else None,
        min_cell=round(float(cell.min()), 3), min_cell_t=round(float(t[int(np.argmin(cell))]), 1),
        below_low_s=round(float(np.sum(dt[cell < ch["low"]])), 1), low=ch["low"],
        chemistry=chemistry or None, chem_label=ch["label"] if chemistry else None,
        start_cell=round(float(cell[:n0].mean()), 3), end_rest_cell=round(rest_end, 3),
        ir_pack_mohm=round(R * 1000, 1) if R else None, ir_cell_mohm=round(R * 1000 / cells, 2) if R else None,
        worst_sag_cell=round(float(sag.max()), 3) if sag is not None else None,
        sag100_cell=round(R * 100 / cells, 3) if R else None,
    )
    if R:
        irc = R * 1000 / cells
        out["health"] = "good" if irc < ch["ir_good"] else "used" if irc < ch["ir_used"] else "tired"
    alt = s.get("meta", {}).get("cells_alt")
    if alt and not chemistry and not capacity:               # no pack chosen and the voltage fits two pack sizes
        out["cells_unsure"] = f"counted as {cells}S; a fully charged {alt}S LiPo HV reads the same: pick the pack to be sure"
    # a LiPo (or a pack of unknown kind) discharged this deep: say so (fine for Li-ion, harmful for a LiPo)
    if chemistry != "liion" and rest_end < CHEM["lipo"]["deep_rest"]:
        out["hint"] = (f"landed at {rest_end:.2f} V/cell resting: "
                       + ("too deep for a LiPo (keep above about 3.5 V)" if chemistry else "normal for Li-ion, too deep for a LiPo"))
    elif chemistry == "liion" and rest_end < CHEM["liion"]["deep_rest"]:
        out["hint"] = f"landed at {rest_end:.2f} V/cell resting: very deep even for Li-ion (keep above about 3.0 V)"
    if capacity and has_i:
        out["capacity"] = capacity
        out["used_pct"] = round(100 * float(mah[-1]) / capacity, 0)
        out["peak_c"] = round(float(np.max(i)) / (capacity / 1000), 1)
        land = LANDING_PCT / 100 * capacity
        k = int(np.searchsorted(mah, land))
        out["landing_mah"] = round(land)
        out["landing_t"] = round(float(t[k]), 1) if k < len(t) else None
    return out


def resample(s: dict, t_track):
    """Cell voltage and current at the track's sample times (for colouring the 3D path)."""
    t, v, i = (np.asarray(s[k], float) for k in ("t", "v", "i"))
    tt = np.asarray(t_track, float)
    inside = (tt >= t[0]) & (tt <= t[-1])
    cv = np.where(inside, np.interp(tt, t, v / max(1, s.get("cells") or 1)), np.nan)
    ia = np.where(inside, np.interp(tt, t, i), np.nan)
    r = lambda a, d: [None if not np.isfinite(x) else round(float(x), d) for x in a]  # noqa: E731
    return dict(cell_v=r(cv, 3), amps=r(ia, 1))


# ------------------------------------------------------------------------------------------- packs and flights
@contextmanager
def _locked(root: Path):
    """One writer at a time for battery/packs.json, also across programs: the server, the launcher and a blackbox
    download are three programs that all change it. A lock file is held around read - change - write."""
    d = store_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    with _LOCK, open(d / ".lock", "a+") as f:
        end = time.monotonic() + 10
        while not try_lock(f):
            if time.monotonic() > end:
                raise RuntimeError(f"the packs file is in use by another {APP_NAME} window: try again") from None
            time.sleep(0.05)
        try:
            yield
        finally:
            unlock(f)


def _load(root: Path | None = None) -> dict:
    root = Path(root) if root else DATA
    f = store_dir(root) / "packs.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("packs", []); d.setdefault("flights", {}); d.setdefault("last_pack", None); d.setdefault("notes", [])
    return d


def _save(d: dict, root: Path | None = None):
    root = Path(root) if root else DATA
    store_dir(root).mkdir(parents=True, exist_ok=True)
    write_atomic(store_dir(root) / "packs.json", json.dumps(d, indent=1))
    _OVERVIEW.clear()                # two saves within one tick of the clock leave the file's time unchanged


def save_flight(fid: str, s: dict, when=None, scene=None, track=None, root: Path | None = None) -> str:
    """Store a flight's series and register it (keeps its pack and charger entry when it was there already)."""
    root = Path(root) if root else DATA
    fid = re.sub(r"[^\w.-]+", "_", fid)[:120]
    f = flight_file(fid, root)
    f.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(f, json.dumps(s, separators=(",", ":")))
    with _locked(root):
        d = _load(root)
        fl = d["flights"].get(fid, {})
        if not when and not fl.get("when"):                  # the drone had no clock (no GPS fix): the date is a guess
            fl["when_approx"] = True
        elif when:
            fl.pop("when_approx", None)
        fl.update(file=f"flights/{fid}.json", when=when or fl.get("when") or time.strftime("%Y-%m-%d %H:%M"),
                  cells=s.get("cells"), source=s.get("source"), craft=s.get("meta", {}).get("craft", ""))
        if scene:
            fl["scene"] = scene
        if track:
            fl["track"] = track
        fl.setdefault("pack", None)
        fl["summary"] = summary(s, **_pack_args(d, fl.get("pack")))
        d["flights"][fid] = fl
        _save(d, root)
    return fid


def link_track(fid: str, scene: str, track: str, root: Path | None = None):
    root = Path(root) if root else DATA
    with _locked(root):
        d = _load(root)
        if fid in d["flights"]:
            d["flights"][fid].update(scene=scene, track=track)
            _save(d, root)


def _pack_args(d, pid):
    p = next((p for p in d["packs"] if p["id"] == pid), None)
    return dict(capacity=p.get("capacity"), cells=p.get("cells"), chemistry=p.get("chemistry", "lipo")) if p else {}


def load_flight(fid: str, root: Path | None = None):
    root = Path(root) if root else DATA
    if not FID_RE.match(fid or ""):
        raise ValueError("bad flight name")
    s = json.loads(flight_file(fid, root).read_text(encoding="utf-8"))
    d = _load(root)
    fl = d["flights"].get(fid, {})
    s["summary"] = summary(s, **_pack_args(d, fl.get("pack")))
    s["pack"] = fl.get("pack")
    s["id"] = fid
    s["charged_mah"] = fl.get("charged_mah")
    return s


def save_pack(p: dict, root: Path | None = None) -> dict:
    """Create (no id) or change a pack: name, cells, capacity (mAh), chemistry (lipo, lihv, liion), retired, note."""
    root = Path(root) if root else DATA
    with _locked(root):
        d = _load(root)
        name = str(p.get("name") or "").strip()[:40]
        cells = int(p.get("cells") or 0)
        cap = int(float(p.get("capacity") or 0))
        if not name or not (1 <= cells <= 8) or not (100 <= cap <= 30000):
            raise ValueError("a pack needs a name, 1 to 8 cells and a capacity of 100 to 30000 mAh")
        kind = str(p.get("chemistry") or "lipo").lower()
        if kind not in CHEM:
            raise ValueError("the chemistry is lipo, lihv or liion")
        cur = next((x for x in d["packs"] if x["id"] == p.get("id")), None) if p.get("id") else None
        if cur is None:
            n = 1 + max([int(x["id"][1:]) for x in d["packs"] if re.match(r"^p\d+$", x["id"])] or [0])
            cur = dict(id=f"p{n}", since=time.strftime("%Y-%m-%d"))
            d["packs"].append(cur)
        cur.update(name=name, cells=cells, capacity=cap, chemistry=kind, retired=bool(p.get("retired", False)),
                   note=str(p.get("note") or "")[:200])
        _resummarize(d, root, pack=cur["id"])
        _save(d, root)
        return cur


# Notes about a pack: what happened to it (a crash, puffing, a damaged lead...). Each kind says how serious it is:
#   retire: stop using it (a swollen or punctured LiPo can catch fire)
#   check:  look it over before the next flight
#   info:   worth remembering (it explains a worse flight or a jump in resistance)
NOTE_KINDS = {
    "crash": ("Crash / hard landing", "check"),
    "puffed": ("Puffed / swollen", "retire"),
    "damage": ("Damaged wrap, leads or plug", "check"),
    "deep": ("Over-discharged", "check"),
    "hot": ("Came back hot", "info"),
    "cold": ("Flown in the cold", "info"),
    "storage": ("Left full / not at storage", "info"),
    "repair": ("Repaired (plug, wrap)", "info"),
    "other": ("Other", "info"),
}


def add_note(pid: str, kind: str, text: str = "", when=None, flight=None, root: Path | None = None) -> dict:
    """Write down what happened to a pack (a crash, puffing...), dated, optionally tied to a flight."""
    root = Path(root) if root else DATA
    if kind not in NOTE_KINDS:
        raise ValueError(f"unknown kind of note (one of: {', '.join(NOTE_KINDS)})")
    when = str(when or time.strftime("%Y-%m-%d"))[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", when):
        raise ValueError("the date is YYYY-MM-DD")
    with _locked(root):
        d = _load(root)
        if not any(p["id"] == pid for p in d["packs"]):
            raise ValueError("unknown pack")
        if flight and flight not in d["flights"]:
            raise ValueError("unknown flight")
        n = 1 + max([int(x["id"][1:]) for x in d["notes"] if re.match(r"^n\d+$", x.get("id", ""))] or [0])
        note = dict(id=f"n{n}", pack=pid, kind=kind, text=str(text or "").strip()[:500], when=when, flight=flight or None)
        d["notes"].append(note)
        _save(d, root)
        return note


def delete_note(nid: str, root: Path | None = None):
    root = Path(root) if root else DATA
    with _locked(root):
        d = _load(root)
        d["notes"] = [n for n in d["notes"] if n.get("id") != nid]
        _save(d, root)


def delete_pack(pid: str, root: Path | None = None):
    root = Path(root) if root else DATA
    with _locked(root):
        d = _load(root)
        d["packs"] = [p for p in d["packs"] if p["id"] != pid]
        d["notes"] = [n for n in d["notes"] if n.get("pack") != pid]
        for fl in d["flights"].values():
            if fl.get("pack") == pid:
                fl["pack"] = None
        if d.get("last_pack") == pid:
            d["last_pack"] = None
        _save(d, root)


def assign(fids, pid, root: Path | None = None):
    """Say which pack flew these flights (None: unknown)."""
    root = Path(root) if root else DATA
    with _locked(root):
        d = _load(root)
        if pid is not None and not any(p["id"] == pid for p in d["packs"]):
            raise ValueError("unknown pack")
        for fid in fids if isinstance(fids, (list, tuple)) else [fids]:
            if fid not in d["flights"]:
                raise ValueError(f"unknown flight {fid}")
            d["flights"][fid]["pack"] = pid
        if pid:
            d["last_pack"] = pid
        _resummarize(d, root, flights=fids if isinstance(fids, (list, tuple)) else [fids])
        _save(d, root)


def set_when(fid: str, when: str, root: Path | None = None):
    """Correct a flight's date ("YYYY-MM-DD" or "YYYY-MM-DD HH:MM"): flights logged without a GPS fix carry the
    download date, which puts them out of order in a pack's history."""
    root = Path(root) if root else DATA
    when = str(when or "").strip().replace("T", " ")[:16]
    if not re.match(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$", when):
        raise ValueError("the date is YYYY-MM-DD or YYYY-MM-DD HH:MM")
    with _locked(root):
        d = _load(root)
        if fid not in d["flights"]:
            raise ValueError("unknown flight")
        d["flights"][fid]["when"] = when if len(when) > 10 else when + " 12:00"
        d["flights"][fid].pop("when_approx", None)
        _save(d, root)


def set_charged(fid: str, mah, root: Path | None = None):
    """What the charger put back in after this flight (mAh), for the current-sensor check. None clears it."""
    root = Path(root) if root else DATA
    with _locked(root):
        d = _load(root)
        if fid not in d["flights"]:
            raise ValueError("unknown flight")
        d["flights"][fid]["charged_mah"] = None if mah in (None, "") else max(0, int(float(mah)))
        _save(d, root)


def _resummarize(d, root, pack=None, flights=None):
    for fid, fl in d["flights"].items():
        if (pack and fl.get("pack") == pack) or (flights and fid in flights):
            try:
                s = json.loads(flight_file(fid, root).read_text(encoding="utf-8"))
                fl["summary"] = summary(s, **_pack_args(d, fl.get("pack")))
            except (OSError, ValueError):
                pass


def forget_missing(root: Path | None = None):
    """Flights whose series file is gone (cleaned up) leave the list."""
    root = Path(root) if root else DATA
    with _locked(root):
        d = _load(root)
        gone = [k for k in d["flights"] if not flight_file(k, root).exists()]
        for k in gone:
            del d["flights"][k]
        if gone:
            _save(d, root)


# --------------------------------------------------------------------------------------------- health, advice
def _median(a):
    return float(np.median(a)) if len(a) else None


_OVERVIEW: dict = {}             # (root, packs.json change time, flights folder change time) -> result


def overview(root: Path | None = None) -> dict:
    """Everything the packs page shows: packs with health, landing advice and their flights; the charger check.
    Kept in memory until the packs file or the flights folder changes."""
    root = Path(root) if root else DATA
    try:
        key = (str(root), (store_dir(root) / "packs.json").stat().st_mtime_ns,
               (store_dir(root) / "flights").stat().st_mtime_ns if (store_dir(root) / "flights").exists() else 0)
    except OSError:
        key = None
    if key and key in _OVERVIEW:
        return json.loads(_OVERVIEW[key])                    # a copy: callers may change what they get
    out = _overview(root)
    if key:
        _OVERVIEW.clear()
        _OVERVIEW[key] = json.dumps(out)
    return out


def _overview(root: Path) -> dict:
    d = _load(root)
    have = {f.stem for f in (store_dir(root) / "flights").glob("*.json")} if (store_dir(root) / "flights").exists() else set()
    flights = [dict(id=k, **v) for k, v in d["flights"].items() if k in have]   # (cleaned-up ones: forget_missing)
    flights.sort(key=lambda f: f.get("when") or "")
    packs = []
    for p in d["packs"]:
        mine = [f for f in flights if f.get("pack") == p["id"]]
        irs = [f["summary"]["ir_cell_mohm"] for f in mine if f["summary"].get("ir_cell_mohm")]
        trend = [dict(when=f["when"], ir=f["summary"]["ir_cell_mohm"]) for f in mine if f["summary"].get("ir_cell_mohm")]
        k = max(1, min(3, len(irs) // 3))                    # first and latest flights, without overlap
        first, now = _median(irs[:k]), _median(irs[-k:])
        long_ = [f for f in mine if (f["summary"].get("seconds") or 0) >= 60 and f["summary"].get("mah")]
        rate = (sum(f["summary"]["mah"] for f in long_) / sum(f["summary"]["seconds"] for f in long_) * 60) if long_ else None
        land_mah = round(p["capacity"] * LANDING_PCT / 100)
        ch = chem(p.get("chemistry"))
        packs.append(dict(p, chemistry=p.get("chemistry", "lipo"), chem_label=ch["label"], low=ch["low"], warn_load=ch["warn_load"],
                          crit_rest=ch["crit_rest"], ir_good=ch["ir_good"], ir_used=ch["ir_used"], flights=len(mine),
                          ir_now=round(now, 2) if now else None, ir_first=round(first, 2) if first else None,
                          trend=trend, sag100=_median([f["summary"]["sag100_cell"] for f in mine if f["summary"].get("sag100_cell")]),
                          mah_per_min=round(rate) if rate else None, landing_mah=land_mah,
                          landing_min=round(land_mah / rate, 1) if rate else None, flags=[]))
    # flags: rising fast, or clearly worse than similar packs
    for p in packs:
        if p["ir_now"] and p["ir_first"] and len(p["trend"]) >= 4 and p["ir_now"] > 1.4 * p["ir_first"]:
            p["flags"].append(f"ageing: resistance {p['ir_now']:.1f} mΩ, +{100 * (p['ir_now'] / p['ir_first'] - 1):.0f} % since its first flights")
        sib = [q["ir_now"] for q in packs if q is not p and q["ir_now"] and q["cells"] == p["cells"] and q["chemistry"] == p["chemistry"]
               and abs(q["capacity"] - p["capacity"]) <= 0.25 * p["capacity"] and not q.get("retired")]
        if p["ir_now"] and len(sib) >= 1 and p["ir_now"] > 1.35 * _median(sib):
            p["flags"].append(f"weaker than your other {p['cells']}S {p['capacity']} {p['chem_label']} packs "
                              f"({p['ir_now']:.1f} vs {_median(sib):.1f} mΩ)")
        elif p["ir_now"] and p["ir_now"] >= p["ir_used"]:
            p["flags"].append(f"tired: {p['ir_now']:.1f} mΩ per cell is high for a {p['chem_label']} pack")
        low = [f for f in flights if f.get("pack") == p["id"] and (f["summary"].get("below_low_s") or 0) > 5]
        if low:
            p["flags"].append(f"{len(low)} flight(s) with cells under {p['low']} V for more than 5 s")
        deep = [f for f in flights if f.get("pack") == p["id"] and f["summary"].get("hint")]
        if deep:
            p["flags"].append(f"{len(deep)} flight(s) landed very low for a {p['chem_label']} pack")
    # notes: newest first; serious ones become flags, and a crash is checked against the resistance before / after it
    for p in packs:
        notes = sorted((dict(n, label=NOTE_KINDS[n["kind"]][0], level=NOTE_KINDS[n["kind"]][1])
                        for n in d["notes"] if n.get("pack") == p["id"] and n.get("kind") in NOTE_KINDS),
                       key=lambda n: (n["when"], n["id"]), reverse=True)
        p["notes"] = notes
        lvl = {"retire": 0, "check": 1, "info": 2}
        for n in sorted(notes, key=lambda n: lvl[n["level"]]):
            if n["level"] == "retire":
                p["flags"].insert(0, f"{n['label'].lower()} on {n['when']}: retire it (a swollen or damaged pack can catch fire)")
            elif n["level"] == "check":
                later = [t["ir"] for t in p["trend"] if (t["when"] or "")[:10] > n["when"]]
                before = [t["ir"] for t in p["trend"] if (t["when"] or "")[:10] <= n["when"]]
                jump = (_median(later[:3]) / _median(before[-3:]) - 1) if later and before else None
                msg = f"{n['label'].lower()} on {n['when']}"
                if jump is not None and jump > 0.2:
                    msg += f": resistance up {round(jump * 100)} % since"
                elif jump is not None:
                    msg += ": no change in resistance since"
                elif not later:
                    msg += ": check it before the next flight (dents, puffing, loose leads)"
                p["flags"].append(msg)
        p["state"] = "retire" if any(n["level"] == "retire" for n in notes) else p.get("state")
    for f in flights:
        f["notes"] = [n["id"] for n in d["notes"] if n.get("flight") == f["id"]]
    return dict(packs=packs, flights=flights, last_pack=d.get("last_pack"), charger=charger_check(flights, root),
                note_kinds={k: dict(label=v[0], level=v[1]) for k, v in NOTE_KINDS.items()},
                landing_pct=LANDING_PCT, low_cell=LOW_CELL, chemistries={k: v["label"] for k, v in CHEM.items()})


def charger_check(flights, root: Path | None = None):
    """Logged mAh vs what the charger put back in: is the current sensor right? With the Betaflight scale to set."""
    root = Path(root) if root else DATA
    rows = [f for f in flights if f.get("charged_mah") and (f["summary"].get("mah") or 0) > 50]
    if not rows:
        return None
    logged = sum(f["summary"]["mah"] for f in rows)
    charged = sum(f["charged_mah"] for f in rows)
    ratio = logged / charged
    out = dict(flights=len(rows), logged=round(logged), charged=round(charged), ratio=round(ratio, 3), ok=0.95 <= ratio <= 1.05)
    scales = []
    for f in rows:
        try:
            s = json.loads(flight_file(f["id"], root).read_text(encoding="utf-8"))
            cs = s.get("meta", {}).get("current_sensor")
            if cs and cs[1]:
                scales.append(int(cs[1]))
        except (OSError, ValueError):
            pass
    if scales:
        old = max(set(scales), key=scales.count)
        out["scale_now"] = old
        out["scale_new"] = int(round(old * ratio))
    return out


def fmt_mmss(s):
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


def describe(sm: dict) -> str:
    """One sentence for a flight (log lines, launcher)."""
    if not sm:
        return ""
    parts = [f"{sm['mah']:.0f} mAh" if sm.get("mah") is not None else "no current sensor",
             f"lowest {sm['min_cell']:.2f} V/cell"]
    if sm.get("ir_cell_mohm"):
        parts.append(f"{sm['ir_cell_mohm']:.1f} mΩ/cell")
    return " · ".join(parts)
