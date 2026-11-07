"""Write a small Betaflight-style blackbox file (.BBL) for the tests: same headers, frame types and encodings
Betaflight 4.5 uses for the main (I) frames, GPS home (H) and GPS (G) frames, several logs in one file like the
onboard flash. No flight controller needed.

    python tests/make_bbl.py OUT.BBL
"""
from __future__ import annotations

import math
import sys


def uvb(v: int) -> bytes:
    out = b""
    while v >= 0x80:
        out += bytes([(v & 0x7F) | 0x80])
        v >>= 7
    return out + bytes([v])


def svb(v: int) -> bytes:
    return uvb(((v << 1) ^ (v >> 31)) & 0xFFFFFFFF)       # zigzag, as Betaflight writes it


def header(firmware="4.5.1"):
    lines = [
        "Product:Blackbox flight data recorder by Nicholas Sherlock",
        "Data version:2",
        "I interval:1",
        "P interval:1/1",
        f"Firmware revision:Betaflight {firmware} (77d01ba3b) STM32F7X2",
        "Board information:FLWO FLYWOOF722PRO",
        "Field I name:loopIteration,time",
        "Field I signed:0,0",
        "Field I predictor:0,0",
        "Field I encoding:1,1",
        "Field P predictor:6,2",
        "Field P encoding:9,0",
        "Field G name:time,GPS_numSat,GPS_coord[0],GPS_coord[1],GPS_altitude,GPS_speed,GPS_ground_course",
        "Field G signed:0,0,1,1,0,0,0",
        "Field G predictor:10,0,7,7,0,0,0",
        "Field G encoding:1,1,0,0,1,1,1",
        "Field H name:GPS_home[0],GPS_home[1]",
        "Field H signed:1,1",
        "Field H predictor:0,0",
        "Field H encoding:0,0",
    ]
    return "".join(f"H {l}\n" for l in lines).encode("ascii")


def flight(lat0, lon0, alt_m, seconds=30, gps_hz=10, main_hz=50, alt_unit=0.1, firmware="4.5.1"):
    """One log: a circle of 60 m radius around (lat0, lon0) climbing 40 m."""
    out = bytearray(header(firmware))
    home = (round(lat0 * 1e7), round(lon0 * 1e7))
    it, t_us = 0, 0
    step = 1_000_000 // main_hz
    per_gps = main_hz // gps_hz
    while t_us <= seconds * 1_000_000:
        if it == 1:                                              # home after the first main frame, as Betaflight
            out += b"H" + svb(home[0]) + svb(home[1])
        if it % per_gps == 0 and it:
            s = t_us / 1e6
            a = s / seconds * 2 * math.pi
            lat = lat0 + 60 * math.sin(a) / 111_320
            lon = lon0 + 60 * (1 - math.cos(a)) / (111_320 * math.cos(math.radians(lat0)))
            alt = alt_m + 40 * s / seconds
            spd = 2 * math.pi * 60 / seconds                     # m/s
            crs = (math.degrees(a) + 90) % 360
            out += (b"G" + uvb(t_us) + uvb(14) + svb(round(lat * 1e7) - home[0]) + svb(round(lon * 1e7) - home[1])
                    + uvb(round(alt / alt_unit)) + uvb(round(spd * 100)) + uvb(round(crs * 10)))
        out += b"I" + uvb(it) + uvb(t_us)
        it += 1
        t_us += step
    out += b"E" + bytes([255]) + b"End of log\x00"
    return bytes(out)


def make(path, flights):
    with open(path, "wb") as f:
        for fl in flights:
            f.write(flight(**fl))


if __name__ == "__main__":
    make(sys.argv[1], [dict(lat0=46.5553, lon0=7.0305, alt_m=1215), dict(lat0=46.0207, lon0=7.7491, alt_m=1620)])
