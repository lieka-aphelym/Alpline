"""Download the blackbox from a Betaflight drone over USB and add its flights to Alpline.

    python -m fpv3d blackbox                 find the drone on USB, copy its blackbox, add every flight
    python -m fpv3d blackbox --file LOG.BBL  only read a log file you already have

How it works:
  1. the flight controller is found among the serial ports: it is the one that answers Betaflight's MSP
     protocol ("BTFL"); the radio uses the same USB chip family but doesn't answer
  2. it is switched to USB drive mode (MSP reboot "mass storage", the same as `msc` in the Betaflight CLI):
     the blackbox (onboard flash or SD card) appears as a USB drive (F4 / G4 / F7 / H7 boards)
  3. the logs are copied to logs/blackbox/<date>/, then read with orangebox (GPS frames)
  4. each flight becomes a CSV next to it and is added to the nearest location (the one whose map contains
     the take-off point), like any flight log

The drone stays in drive mode until it is unplugged or powered off.
"""
from __future__ import annotations

import csv
import glob
import os
import re
import shutil
import string
import struct
import time
from pathlib import Path

from .locations import ROOT

MSP_FC_VARIANT, MSP_FC_VERSION, MSP_BOARD_INFO = 2, 3, 4
MSP_DATAFLASH_SUMMARY, MSP_SET_REBOOT = 70, 68
REBOOT_MSC = 2                                   # Betaflight: reboot into USB mass storage mode
LOG_GLOBS = ("*.BBL", "*.bbl", "*.BFL", "*.bfl")


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- MSP (Betaflight's serial protocol, v1)
def _msp_frame(cmd: int, payload: bytes = b"") -> bytes:
    body = bytes([len(payload), cmd]) + payload
    crc = 0
    for b in body:
        crc ^= b
    return b"$M<" + body + bytes([crc])


def msp(ser, cmd: int, payload: bytes = b"", timeout: float = 0.6):
    """Send one MSP request and return the reply's payload, or None (no answer: not a Betaflight board)."""
    ser.reset_input_buffer()
    ser.write(_msp_frame(cmd, payload))
    buf, t0 = b"", time.monotonic()
    while time.monotonic() - t0 < timeout:
        buf += ser.read(64)
        i = buf.find(b"$M>")
        if i >= 0 and len(buf) >= i + 5:
            n, c = buf[i + 3], buf[i + 4]
            if len(buf) >= i + 6 + n:
                if c == cmd:
                    return buf[i + 5:i + 5 + n]
                buf = buf[i + 6 + n:]
    return None


def probe(port: str):
    """Ask a serial port whether it is a Betaflight flight controller. Returns its info or None."""
    import serial
    try:
        with serial.Serial(port, 115200, timeout=0.05) as ser:
            v = msp(ser, MSP_FC_VARIANT)
            if not v or v[:4] != b"BTFL":
                return None
            ver = msp(ser, MSP_FC_VERSION) or b"\0\0\0"
            board = msp(ser, MSP_BOARD_INFO) or b"????"
            fl = msp(ser, MSP_DATAFLASH_SUMMARY)
            info = dict(port=port, firmware=f"Betaflight {ver[0]}.{ver[1]}.{ver[2]}", board=board[:4].decode("ascii", "replace"))
            if fl and len(fl) >= 13:
                flags, sectors, total, used = struct.unpack("<BIII", fl[:13])
                info.update(flash_ready=bool(flags & 1), flash_total=total, flash_used=used)
            return info
    except Exception:
        return None


def find_drones(skip=()):
    """Betaflight flight controllers on USB (ports in `skip`, e.g. the radio of a running live flight, are left alone)."""
    from serial.tools import list_ports
    out = []
    for p in list_ports.comports():
        if p.device in skip:
            continue
        hw = (p.hwid or "").upper()
        if "VID:PID" in hw and "0483" not in hw and "2E3C" not in hw and "1209" not in hw:
            continue                             # not an STM32 / AT32 / generic USB serial: skip the probe
        info = probe(p.device)
        if info:
            out.append(info)
    return out


def enter_drive_mode(port: str):
    import serial
    with serial.Serial(port, 115200, timeout=0.2) as ser:
        ser.write(_msp_frame(MSP_SET_REBOOT, bytes([REBOOT_MSC])))
        ser.flush()
        time.sleep(0.3)


def enter_drive_mode_cli(port: str):
    import serial
    try:
        with serial.Serial(port, 115200, timeout=0.3) as ser:
            ser.write(b"#\r\n")
            time.sleep(0.4)
            ser.read(4096)
            ser.write(b"msc\r\n")
            ser.flush()
            time.sleep(0.3)
    except Exception:
        pass


def _port_exists(port: str) -> bool:
    from serial.tools import list_ports
    return any(p.device == port for p in list_ports.comports())


# ---------------------------------------------------------------- the USB drive
def _drive_roots():
    if os.name == "nt":
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1 and c not in "AB"]
    roots = glob.glob("/media/*/*") + glob.glob("/run/media/*/*") + glob.glob("/Volumes/*") + glob.glob("/mnt/*")
    return [r for r in roots if os.path.isdir(r)]


def _logs_on(root):
    files = []
    for g in LOG_GLOBS:
        files += glob.glob(os.path.join(root, g))
    return sorted(set(files))


def wait_for_drive(timeout=60, before=None):
    """The drive that appears with blackbox files on it (or one that already has them)."""
    before = set(before or [])
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        for r in _drive_roots():
            if (r not in before or not before) and _logs_on(r):
                return r
        time.sleep(1)
    return None


def copy_logs(root, dest: Path):
    """Copy the log files. Betaflight's drive for the onboard flash shows each log as its own file plus BTFL_ALL
    with everything: the single logs are taken when there are some."""
    files = _logs_on(root)
    singles = [f for f in files if "ALL" not in Path(f).stem.upper()]
    pick = singles or files
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for f in pick:
        d = dest / Path(f).name
        shutil.copyfile(f, d)
        out.append(d)
        log(f"copied {Path(f).name} ({os.path.getsize(d) / 1e6:.1f} MB)")
    return out


# ---------------------------------------------------------------- reading the logs
def _alt_scale(headers, raw_alts):
    """GPS_altitude unit: 0.1 m in recent Betaflight (with a home altitude), whole metres before. Checked
    against what is possible in Switzerland (about 190 to 4700 m)."""
    if not raw_alts:
        return 0.1
    med = sorted(raw_alts)[len(raw_alts) // 2]
    ok = [s for s in (0.1, 1.0) if 150 <= med * s <= 5000]
    if len(ok) == 1:
        return ok[0]
    m = re.search(r"(\d+)\.(\d+)", str(headers.get("Firmware revision", "")))
    newer = bool(m) and (int(m.group(1)), int(m.group(2))) >= (4, 5)
    return 0.1 if newer else 1.0


def _log_time(headers):
    """Local start time of a log ("Log start datetime", set when the FC knows the time: GPS or the
    Configurator's clock), or None."""
    from datetime import datetime
    v = str(headers.get("Log start datetime", ""))
    if not v or v.startswith("0000"):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def _fingerprint(rows):
    import hashlib
    return hashlib.sha1(repr((len(rows), rows[0], rows[len(rows) // 2], rows[-1])).encode()).hexdigest()[:16]


def flights_in(path: Path):
    """Every log inside a blackbox file -> list of flights: dict(index, rows, start, seconds).
    rows: (time_s, lat, lon, alt_m, sats, speed_m_s, course_deg), one per new GPS position."""
    import logging
    from orangebox import Parser
    logging.getLogger("orangebox").setLevel(logging.ERROR)      # it warns about headers we don't need
    first = Parser.load(str(path))
    n = first.reader.log_count
    flights = []
    for idx in range(1, n + 1):
        try:
            p = first if idx == 1 else Parser.load(str(path), idx)
            names = p.field_names
            need = ["time", "GPS_numSat", "GPS_coord[0]", "GPS_coord[1]", "GPS_altitude", "GPS_speed", "GPS_ground_course"]
            if not all(k in names for k in need):
                log(f"log {idx}: no GPS in this log (is GPS logging on in Betaflight's Blackbox tab?)")
                continue
            ix = [names.index(k) for k in need]
            raw, last, t0 = [], None, None
            for fr in p.frames():
                d = fr.data
                try:
                    t, sats, la, lo, alt, spd, crs = (d[i] for i in ix)
                except IndexError:
                    continue
                if la in ("", None) or lo in ("", None) or (la == 0 and lo == 0):
                    continue
                key = (la, lo, alt)
                if key == last:
                    continue
                last = key
                t0 = t if t0 is None else t0
                raw.append(((t - t0) / 1e6, la / 1e7, lo / 1e7, alt, sats, spd / 100, crs / 10))
        except Exception as ex:                  # a damaged log: keep the others
            log(f"log {idx}: could not be read ({ex.__class__.__name__}: {ex})")
            continue
        if len(raw) < 3:
            log(f"log {idx}: too few GPS positions ({len(raw)}): skipped")
            continue
        s = _alt_scale(p.headers, [r[3] for r in raw])
        rows = [(round(r[0], 3), r[1], r[2], round(r[3] * s, 1), r[4], round(r[5], 2), round(r[6], 1)) for r in raw]
        flights.append(dict(index=idx, rows=rows, start=(rows[0][1], rows[0][2]), seconds=rows[-1][0],
                            when=_log_time(p.headers)))
    return flights


def write_csv(rows, out: Path):
    """Same columns as Betaflight's blackbox_decode *.gps.csv, which Alpline already reads."""
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time (us)", "GPS_numSat", "GPS_coord[0]", "GPS_coord[1]", "GPS_altitude", "GPS_speed (m/s)", "GPS_ground_course"])
        for t, la, lo, alt, sats, spd, crs in rows:
            w.writerow([int(t * 1e6), sats, f"{la:.7f}", f"{lo:.7f}", alt, f"{spd:.2f}", crs])


def nearest_location(lat, lon, scenes_dir=None):
    """The location whose map contains this point (the closest centre if several), or None."""
    import math
    from .locations import list_locations
    best = None
    for l in list_locations(Path(scenes_dir or ROOT / "scenes")):
        c = l.get("center")
        if not c:
            continue
        dy = (lat - c[0]) * 111_320
        dx = (lon - c[1]) * 111_320 * math.cos(math.radians(lat))
        half = l.get("half_size_m") or 2000
        if l.get("corridor"):
            near = min(math.hypot((lat - a) * 111_320, (lon - b) * 111_320 * math.cos(math.radians(lat)))
                       for a, b in l["corridor"]["points"])
            inside, dist = near <= l["corridor"].get("width_m", 500) + 200, near
        else:
            inside, dist = abs(dx) <= half and abs(dy) <= half, math.hypot(dx, dy)
        if inside and (best is None or dist < best[0]):
            best = (dist, l)
    return best[1] if best else None


# ---------------------------------------------------------------- the whole thing
def run(port=None, file=None, location=None, scenes=None, timeout=60, skip=()):
    """Find the drone, copy, read, add. Prints one line per step (shown live on the viewer's flights tab)."""
    stamp = time.strftime("%Y-%m-%d_%H%M")
    dest = ROOT / "logs" / "blackbox" / stamp
    if file:
        files = [Path(file)]
    else:
        root = None
        if not port:
            log("looking for the drone on USB…")
            drones = find_drones(skip)
            if not drones:
                root = wait_for_drive(0.5)               # already in drive mode, or an SD card in a reader
                if not root:
                    raise SystemExit("No Betaflight drone found on USB. Plug the drone in (battery not needed), "
                                     "close Betaflight Configurator (it holds the port) and try again.")
                log(f"no drone on the serial ports, but {root} has blackbox files: taking them")
            else:
                d = drones[0]
                port = d["port"]
                used = d.get("flash_used")
                log(f"found {d['board']} · {d['firmware']} on {port}"
                    + (f" · blackbox {used / 1e6:.1f} of {d['flash_total'] / 1e6:.0f} MB used" if used is not None else ""))
                if used == 0:
                    raise SystemExit("The blackbox is empty: nothing to download.")
        if not root:
            before = _drive_roots()
            log("switching the drone to USB drive mode…")
            enter_drive_mode(port)
            log("waiting for the drive to appear (Windows may take a few seconds)…")
            root = wait_for_drive(min(15, timeout), before)
            if not root and _port_exists(port):         # older firmware: the CLI command does the same
                log("trying the CLI command `msc`…")
                enter_drive_mode_cli(port)
                root = wait_for_drive(max(5, timeout - 15), before)
            if not root:
                raise SystemExit("The drive did not appear. Your board may not support it (needs F4 / G4 / F7 / H7 and "
                                 "Betaflight 4.x); unplug and plug the drone, then try again.")
        log(f"drive {root} found")
        files = copy_logs(root, dest)
        if not files:
            raise SystemExit("The drive has no blackbox files.")
    seen_file = ROOT / "logs" / "blackbox" / "added.txt"   # flights already added: downloading again skips them
    try:
        seen = set(seen_file.read_text(encoding="utf-8").split())
    except OSError:
        seen = set()
    added = 0
    for f in files:
        try:
            fl = flights_in(f)
        except Exception as ex:
            log(f"{f.name}: not a readable blackbox ({ex.__class__.__name__}: {ex})")
            continue
        log(f"{f.name}: {len(fl)} flight(s) with GPS")
        folder = Path(f).parent
        for x in fl:
            mins = x["seconds"] / 60
            fp = _fingerprint(x["rows"])
            if fp in seen:
                log(f"flight {x['index']}: {mins:.1f} min, already added before: skipped")
                continue
            loc = None
            if location:
                from .locations import list_locations
                loc = next((l for l in list_locations(Path(scenes or ROOT / "scenes")) if l["name"] == location), None)
            loc = loc or nearest_location(*x["start"], scenes)
            when = x["when"].strftime("%Y-%m-%d_%H%M") if x["when"] else f"{stamp}_{x['index']:02d}"
            out = folder / f"{loc['name'] if loc else Path(f).stem}_bb_{when}.csv"
            write_csv(x["rows"], out)
            if not loc:
                log(f"flight {x['index']}: {mins:.1f} min, no location contains its take-off point "
                    f"({x['start'][0]:.5f}, {x['start'][1]:.5f}): kept as {out.name}")
                continue
            if not loc.get("built"):
                log(f"flight {x['index']}: {mins:.1f} min, {loc['name']} is not built yet: kept as {out.name}")
                continue
            try:
                from .config import LocationConfig
                from .locations import LOC_DIR
                from .scene import add_logs
                add_logs(LocationConfig.load(LOC_DIR / loc["file"]), Path(scenes or ROOT / "scenes"), [str(out)],
                         {"altitude_mode": "amsl"})
            except Exception as ex:
                log(f"flight {x['index']}: could not be added to {loc['name']}: {ex.__class__.__name__}: {ex}")
                continue
            added += 1
            seen.add(fp)
            seen_file.parent.mkdir(parents=True, exist_ok=True)
            with open(seen_file, "a", encoding="utf-8") as sf:
                sf.write(fp + "\n")
            log(f"flight {x['index']}: {mins:.1f} min → added to {loc['name']} ({out.stem})")
            log(f"ADDED {loc['name']} {out.stem}")
    log(f"done: {added} flight(s) added" + ("" if file else " · you can unplug the drone now"))
    return added
