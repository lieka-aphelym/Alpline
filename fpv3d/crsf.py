"""CRSF (Crossfire / ExpressLRS) telemetry frames, as EdgeTX mirrors them on USB.

Frame:  [address][length][type][payload ...][crc8]   length = type + payload + crc
CRC:    CRC-8/DVB-S2 (poly 0xD5) over type + payload. All numbers are big-endian.

Decoded frame types (the ones Betaflight / ELRS send down):
    0x02 GPS              lat, lon (deg), ground speed (km/h), course (deg), altitude (m), satellites
    0x07 vario            vertical speed (m/s)
    0x08 battery          voltage (V), current (A), used capacity (mAh), remaining (%)
    0x09 baro altitude    altitude above the arming point (m)
    0x14 link statistics  RSSI ant 1/2 (dBm), LQ (%), SNR (dB), TX power (mW), downlink RSSI/LQ/SNR
    0x1E attitude         pitch, roll, yaw (deg)
    0x21 flight mode      text, e.g. "ANGL", "ACRO", "!FS!", "RTH"
"""
from __future__ import annotations

import struct

SYNC = (0xC8, 0xEA, 0xEE, 0xEC)          # flight controller, radio, TX module, RX addresses
TX_POWER_MW = [0, 10, 25, 100, 500, 1000, 2000, 250, 50]


def dbm(v: int) -> int:
    """CRSF RSSI byte -> dBm. The spec sends dBm x -1 (51 = -51 dBm); ExpressLRS and others send the signed value
    (-51 dBm = 205). Real RSSI is always negative, so both read the same way."""
    return v - 256 if v > 127 else -v


def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def encode(ftype: int, payload: bytes, address=0xEA) -> bytes:
    """Build a frame (used by tests and the replay source)."""
    body = bytes([ftype]) + payload
    return bytes([address, len(body) + 1]) + body + bytes([crc8(body)])


def decode(ftype: int, p: bytes):
    """dict of values for a known frame type, else None."""
    try:
        if ftype == 0x02 and len(p) >= 15:
            lat, lon, gs, hdg, alt, sats = struct.unpack(">iiHHHB", p[:15])
            return dict(kind="gps", lat=lat / 1e7, lon=lon / 1e7, speed_kmh=gs / 10, heading=hdg / 100,
                        alt=alt - 1000, sats=sats)
        if ftype == 0x07 and len(p) >= 2:
            return dict(kind="vario", vspeed=struct.unpack(">h", p[:2])[0] / 100)
        if ftype == 0x08 and len(p) >= 8:
            v, a = struct.unpack(">HH", p[:4])
            mah = int.from_bytes(p[4:7], "big")
            return dict(kind="battery", voltage=v / 10, current=a / 10, mah=mah, remaining=p[7])
        if ftype == 0x09 and len(p) >= 2:
            raw = struct.unpack(">H", p[:2])[0]
            alt = (raw - 10000) / 10 if raw < 0x8000 else (raw & 0x7FFF)     # dm with offset, or whole metres
            return dict(kind="baro", baro_alt=alt)
        if ftype == 0x14 and len(p) >= 10:
            r1, r2, lq, snr, ant, mode, pw, drssi, dlq, dsnr = struct.unpack(">BBBbBBBBBb", p[:10])
            return dict(kind="link", rssi1=dbm(r1), rssi2=dbm(r2), lq=lq, snr=snr, antenna=ant, rf_mode=mode,
                        tx_power=TX_POWER_MW[pw] if pw < len(TX_POWER_MW) else None,
                        down_rssi=dbm(drssi), down_lq=dlq, down_snr=dsnr)
        if ftype == 0x1E and len(p) >= 6:
            pitch, roll, yaw = struct.unpack(">hhh", p[:6])
            k = 180 / 3.141592653589793 / 10000
            return dict(kind="attitude", pitch=pitch * k, roll=roll * k, yaw=(yaw * k) % 360)
        if ftype == 0x21:
            return dict(kind="mode", mode=p.split(b"\0")[0].decode("ascii", "replace"))
    except struct.error:
        return None
    return None


class Parser:
    """Feed it raw bytes in any chunk sizes; it returns the decoded frames."""

    def __init__(self):
        self.buf = bytearray()
        self.bad = 0
        self.frames = 0

    def feed(self, data: bytes):
        self.buf += data
        out = []
        b = self.buf
        while len(b) >= 4:
            if b[0] not in SYNC:
                del b[0]
                continue
            n = b[1]
            if n < 2 or n > 62:
                del b[0]
                continue
            if len(b) < n + 2:
                break
            body, crc = bytes(b[2:n + 1]), b[n + 1]
            if crc8(body) != crc:
                self.bad += 1
                del b[0]
                continue
            del b[:n + 2]
            self.frames += 1
            d = decode(body[0], body[1:])
            if d:
                out.append(d)
        return out


# ---------------------------------------------------------------- encoders for tests / replay

def gps_frame(lat, lon, speed_kmh, heading, alt, sats=12):
    return encode(0x02, struct.pack(">iiHHHB", int(round(lat * 1e7)), int(round(lon * 1e7)),
                                    int(round(speed_kmh * 10)), int(round(heading % 360 * 100)),
                                    int(round(alt + 1000)), sats))


def link_frame(rssi, lq, snr=8, tx_power_idx=3):
    r = max(0, min(255, int(round(-rssi))))
    return encode(0x14, struct.pack(">BBBbBBBBBb", r, r, int(lq), int(snr), 0, 6, tx_power_idx, r, int(lq), int(snr)))


def battery_frame(volt, amp, mah, pct):
    return encode(0x08, struct.pack(">HH", int(volt * 10), int(amp * 10)) + int(mah).to_bytes(3, "big") + bytes([int(pct)]))


def vario_frame(vs):
    return encode(0x07, struct.pack(">h", int(round(vs * 100))))


def mode_frame(text):
    return encode(0x21, text.encode("ascii") + b"\0")
