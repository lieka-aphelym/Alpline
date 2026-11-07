"""Flight-log readers. Every reader returns a `Track` with WGS84 positions.

Supported out of the box:
  * EdgeTX / OpenTX telemetry logs (.csv)  - ELRS / Crossfire, incl. RSSI / LQ / SNR
  * Betaflight / INAV blackbox decoded CSV - from `blackbox_decode` (*.gps.csv) or Blackbox Explorer export
  * GPX (.gpx)                             - most GPS apps, DJI converters, etc.
  * Any CSV with lat/lon/alt(/time) columns

Add a new format by writing a function `(path) -> Track` and registering it in READERS.
"""
from __future__ import annotations

import csv
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np


@dataclass
class Track:
    name: str
    source_format: str
    t: np.ndarray                 # seconds since start
    lat: np.ndarray
    lon: np.ndarray
    alt: np.ndarray               # metres, as logged (AMSL or relative; resolved later)
    telemetry: Dict[str, np.ndarray] = field(default_factory=dict)
    start_time: Optional[str] = None


# ----------------------------------------------------------------- helpers

def _num(s):
    try:
        v = float(str(s).strip())
        return v if math.isfinite(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _find(cols: List[str], *cands: str) -> Optional[str]:
    low = {c.strip().lower(): c for c in cols}
    for cand in cands:
        if cand.lower() in low:
            return low[cand.lower()]
    for cand in cands:  # prefix match, e.g. "Alt(m)" for "alt"
        for lc, c in low.items():
            if re.fullmatch(re.escape(cand.lower()) + r"\s*\(.*\)", lc):
                return c
    return None


def _parse_time(row, cols) -> Optional[float]:
    tcol = _find(cols, "time (us)", "time(us)", "time_us")
    if tcol:
        v = _num(row.get(tcol))
        return v / 1e6 if not np.isnan(v) else None
    tcol = _find(cols, "time (s)", "time_s", "seconds", "t")
    if tcol:
        return _num(row.get(tcol))
    dcol, tcol = _find(cols, "date"), _find(cols, "time", "timestamp", "datetime")
    if tcol:
        txt = ((row.get(dcol) or "").strip() + "T" if dcol else "") + (row.get(tcol) or "").strip()
        txt = txt.replace("Z", "+00:00")
        for parse in (datetime.fromisoformat,
                      lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f")):
            try:
                return parse(txt).timestamp()
            except (ValueError, OverflowError, OSError):     # not a date, or a date Windows can't convert
                pass
        v = _num(row.get(tcol))
        return v if not np.isnan(v) else None
    return None


TELEMETRY_HINTS = re.compile(r"(rss|qly|snr|rssi|lq|tpwr|rxbt|sats|numsat|gspd|speed|curr|bat|vbat)",
                             re.I)


def _clean_name(c: str) -> str:
    return re.sub(r"[^A-Za-z0-9_%]+", "_", c.strip()).strip("_")


# ----------------------------------------------------------------- readers

def read_csv(path: Path) -> Track:
    text = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    # blackbox_decode / explorer exports may have preamble lines; find the header row
    start = 0
    for i, line in enumerate(text[:50]):
        l = line.lower()
        if ("gps" in l or "lat" in l) and "," in line:
            start = i
            break
    try:
        rows = list(csv.DictReader(text[start:]))
    except csv.Error as ex:                              # e.g. a damaged file with one enormous line
        raise ValueError(f"{path.name}: not a readable CSV ({ex})") from None
    if not rows:
        raise ValueError(f"{path.name}: empty CSV")
    cols = [c for c in rows[0].keys() if c is not None]  # (rows with extra values put them under None)

    fmt = "csv"
    gps_combined = _find(cols, "GPS")
    lat_c = _find(cols, "GPS_coord[0]", "lat", "latitude", "gps_lat")
    lon_c = _find(cols, "GPS_coord[1]", "lon", "lng", "long", "longitude", "gps_lon")
    alt_c = _find(cols, "GPS_altitude", "alt", "altitude", "ele", "elevation", "galt", "gps_alt")
    if gps_combined and not lat_c:
        fmt = "edgetx"
    elif lat_c and lat_c.strip().startswith("GPS_coord"):
        fmt = "blackbox"
    elif not (lat_c and lon_c):
        raise ValueError(f"{path.name}: could not find GPS columns (have: {', '.join(cols[:15])} ...)")

    tel_cols = [c for c in cols if c and TELEMETRY_HINTS.search(c) and c not in (lat_c, lon_c, alt_c)]
    T, LA, LO, AL = [], [], [], []
    TEL = {c: [] for c in tel_cols}
    for r in rows:
        if fmt == "edgetx":
            parts = (r.get(gps_combined) or "").split()
            if len(parts) != 2:
                continue
            la, lo = _num(parts[0]), _num(parts[1])
        else:
            la, lo = _num(r.get(lat_c)), _num(r.get(lon_c))
        if np.isnan(la) or np.isnan(lo) or (abs(la) < 1e-6 and abs(lo) < 1e-6):
            continue
        if abs(la) > 90 or abs(lo) > 180:     # raw integer degrees * 1e7
            la, lo = la / 1e7, lo / 1e7
        t = _parse_time(r, cols)
        T.append(np.nan if t is None else t)
        LA.append(la)
        LO.append(lo)
        AL.append(_num(r.get(alt_c)) if alt_c else np.nan)
        for c in tel_cols:
            TEL[c].append(_num(r.get(c)))
    if not LA:
        raise ValueError(f"{path.name}: no rows with a GPS fix")
    t = np.array(T, float)
    if np.isnan(t).all():
        t = np.arange(len(LA), dtype=float)   # unknown rate: 1 sample = 1 s
    t = t - np.nanmin(t)
    t = _fill_nan(t)
    tel = {_clean_name(c): np.array(v, float) for c, v in TEL.items() if np.isfinite(v).any()}
    return Track(path.stem, fmt, t, np.array(LA), np.array(LO), _fill_nan(np.array(AL, float)), tel)


def read_gpx(path: Path) -> Track:
    root = ET.parse(path).getroot()
    ns = {"g": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
    q = (lambda tag: f"g:{tag}") if ns else (lambda tag: tag)
    pts = root.findall(f".//{q('trkpt')}", ns) or root.findall(f".//{q('rtept')}", ns)
    T, LA, LO, AL = [], [], [], []
    for p in pts:
        LA.append(float(p.get("lat")))
        LO.append(float(p.get("lon")))
        e = p.find(q("ele"), ns)
        AL.append(float(e.text) if e is not None and e.text else np.nan)
        tm = p.find(q("time"), ns)
        T.append(datetime.fromisoformat(tm.text.replace("Z", "+00:00")).timestamp()
                 if tm is not None and tm.text else np.nan)
    if not LA:
        raise ValueError(f"{path.name}: no track points")
    t = np.array(T, float)
    t = np.arange(len(t), dtype=float) if np.isnan(t).all() else _fill_nan(t - np.nanmin(t))
    return Track(path.stem, "gpx", t, np.array(LA), np.array(LO), _fill_nan(np.array(AL, float)))


def _fill_nan(a: np.ndarray) -> np.ndarray:
    a = a.astype(float)
    ok = np.isfinite(a)
    if ok.all() or not ok.any():
        return a
    idx = np.arange(a.size)
    a[~ok] = np.interp(idx[~ok], idx[ok], a[ok])
    return a


READERS: Dict[str, Callable[[Path], Track]] = {
    ".csv": read_csv,
    ".txt": read_csv,
    ".gpx": read_gpx,
}


def read_log(path) -> Track:
    path = Path(path)
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise ValueError(f"unsupported log type '{path.suffix}' (supported: {', '.join(READERS)})")
    return reader(path)


def resolve_altitude_amsl(track: Track, ground_at_points: np.ndarray, mode: str = "auto",
                          offset_m: float = 0.0, scale: Optional[float] = None) -> np.ndarray:
    """Turn logged altitude into metres above sea level.

    mode = "amsl"     : the log already contains GPS altitude above sea level
           "relative" : altitude is relative to the take-off point (baro / home-relative)
           "agl"      : altitude is height above ground at each point
           "auto"     : guess from the first samples vs. the terrain under them
    scale: multiply raw values (e.g. 0.01 for centimetres). Auto-detected if None.
    """
    alt = track.alt.copy()
    if np.isnan(alt).all():
        return ground_at_points + 30.0  # no altitude at all: assume 30 m AGL
    if scale is None:
        if track.source_format == "blackbox":
            # Betaflight has logged GPS altitude in m, dm or cm depending on version
            # (4.5 uses dm): pick the unit that puts the first fix closest to the terrain.
            a0 = float(np.nanmedian(alt[: max(3, len(alt) // 50)]))
            g0 = float(ground_at_points[0])
            scale = min((1.0, 0.1, 0.01), key=lambda s: abs(a0 * s - g0))
        else:
            med = np.nanmedian(np.abs(alt))
            scale = 0.01 if med > 9000 else 1.0     # centimetres
    alt = alt * scale
    if mode == "auto":
        g0 = float(ground_at_points[0])
        a0 = float(np.nanmedian(alt[: max(3, len(alt) // 50)]))
        if abs(a0 - g0) < 60:
            mode = "amsl"
        elif abs(a0) < 60:
            mode = "relative"
        else:
            mode = "amsl"
    if mode == "relative":
        alt = alt + float(ground_at_points[0])
    elif mode == "agl":
        alt = alt + ground_at_points
    return alt + offset_m
