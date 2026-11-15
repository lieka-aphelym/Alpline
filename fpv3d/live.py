"""Live telemetry: the radio's CRSF stream (EdgeTX "USB-VCP: Telemetry mirror") -> viewer.

One link at a time, run in a background thread by the local server:
    serial  read the radio's USB serial port (needs `pip install pyserial`)
    replay  play a processed flight log of the scene back as a CRSF stream, in real time
            (to try the live view and the warnings without flying; goes through the same decoder)

Everything received is recorded to logs/live/<scene>/<scene>_live_<date>_<time>.csv, which becomes a
normal track of the scene when the link is stopped with "save".
"""
from __future__ import annotations

import csv
import json
import math
import threading
import time
from pathlib import Path

from . import crsf
from .locations import ROOT

COLS = ["time_s", "lat", "lon", "alt", "gspd_kmh", "heading", "sats", "rssi1", "rssi2", "lq", "snr",
        "tpwr_mw", "vspeed", "baro_alt", "rxbt", "curr", "capa", "mode"]


def list_ports():
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        raise RuntimeError("the live link needs pyserial: pip install pyserial") from None
    out = []
    for p in lp.comports():
        desc = " ".join(x for x in (p.description, p.manufacturer or "") if x and x != "n/a")
        likely = any(k in (desc + (p.hwid or "")).lower() for k in ("stm", "0483", "edgetx", "radiomaster", "opentx", "frsky", "usb serial"))
        out.append(dict(device=p.device, description=desc or p.device, likely=likely))
    out.sort(key=lambda d: not d["likely"])
    return out


class LiveLink:
    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.stop_ev = threading.Event()
        self.reset()

    def reset(self):
        self.state = dict(status="idle", source=None, scene=None, error=None, frames=0, bad=0, gps_count=0,
                          started=None, csv=None, bytes=0, port=None, reconnecting=False, reconnects=0)
        self.opened = None         # when the port opened: "nothing for N s" needs to know how long we waited
        self.latest = {}
        self.samples = []          # one per GPS frame (merged with the latest other values)
        self.seq = 0
        self.last_frame = None
        self.last_gps = None
        self.gaps = dict(frame=[], gps=[])   # recent intervals between messages (s): the usual rate of this radio

    # ------------------------------------------------------------ control
    def start(self, scene: str, source: str, port: str = None, replay_file: Path = None, speed: float = 1.0):
        self.stop()
        with self.lock:
            self.reset()
            self.state.update(status="connecting", source=source, scene=scene, port=port, started=time.time())
            stamp = time.strftime("%Y-%m-%d_%H%M")
            out = ROOT / "logs" / "live" / scene / f"{scene}_live_{stamp}{'_replay' if source == 'replay' else ''}.csv"
            out.parent.mkdir(parents=True, exist_ok=True)
            self.state["csv"] = str(out)
        self.stop_ev.clear()
        target = self._run_serial if source == "serial" else self._run_replay
        args = (port,) if source == "serial" else (replay_file, speed)
        self.thread = threading.Thread(target=target, args=args, daemon=True)
        self.thread.start()

    def stop(self):
        if self.thread and self.thread.is_alive():
            self.stop_ev.set()
            self.thread.join(timeout=3)
        self.thread = None
        with self.lock:
            if self.state["status"] in ("connecting", "live"):
                self.state["status"] = "stopped"

    # ------------------------------------------------------------ data in
    def _handle(self, frames, writer, t0):
        now = time.monotonic()
        with self.lock:
            for f in frames:
                if self.last_frame is not None and now - self.last_frame > 0.02:     # one read can hold several frames
                    self._gap("frame", now - self.last_frame)
                self.last_frame = now
                kind = f.pop("kind")
                self.latest.update(f)
                if kind != "gps":
                    continue
                if self.last_gps is not None:
                    self._gap("gps", now - self.last_gps)
                self.last_gps = now
                self.seq += 1
                L = self.latest
                s = dict(seq=self.seq, t=round(now - t0, 3), **{k: L.get(k) for k in (
                    "lat", "lon", "alt", "speed_kmh", "heading", "sats", "rssi1", "rssi2", "lq", "snr", "tx_power",
                    "vspeed", "baro_alt", "voltage", "current", "mah", "mode", "pitch", "roll", "yaw")})
                self.samples.append(s)
                if len(self.samples) > 20000:
                    del self.samples[:5000]
                self.state["gps_count"] += 1
                if writer and s["lat"] and abs(s["lat"]) > 1e-6:
                    writer.writerow([s["t"], f"{s['lat']:.7f}", f"{s['lon']:.7f}", s["alt"], s["speed_kmh"], s["heading"],
                                     s["sats"], s["rssi1"], s["rssi2"], s["lq"], s["snr"], s["tx_power"], s["vspeed"],
                                     s["baro_alt"], s["voltage"], s["current"], s["mah"], s["mode"]])

    def _gap(self, kind, dt):
        g = self.gaps[kind]
        g.append(dt)
        del g[:-15]

    def _usual(self, kind):
        g = sorted(self.gaps[kind])
        return round(g[len(g) // 2], 2) if len(g) >= 3 else None

    def _open_csv(self):
        f = open(self.state["csv"], "w", newline="", encoding="utf-8")
        w = csv.writer(f)
        w.writerow(COLS)
        return f, w

    RECONNECT_S = 30          # a dropped USB cable: keep trying to reopen the port this long before giving up

    def _open_port(self, port):
        import serial
        return serial.Serial(port, 115200, timeout=0.1)        # USB CDC: the baud rate is ignored

    def _run_serial(self, port):
        try:
            import serial  # noqa: F401
        except ImportError:
            return self._fail("the live link needs pyserial: pip install pyserial")
        try:
            ser = self._open_port(port)
        except Exception as ex:
            return self._fail(f"cannot open {port}: {ex}")
        p, (fh, w) = crsf.Parser(), self._open_csv()
        t0 = time.monotonic()
        with self.lock:
            self.state.update(status="live", port=port)
            self.opened = t0
        try:
            while not self.stop_ev.is_set():
                try:
                    data = ser.read(512)
                except Exception as ex:                    # cable pulled, radio switched off: try to get it back
                    ser = self._reconnect(ser, port, ex)
                    if ser is None:
                        return
                    continue
                if data:
                    self._handle(p.feed(data), w, t0)
                    with self.lock:
                        self.state.update(frames=p.frames, bad=p.bad, bytes=self.state["bytes"] + len(data))
                    fh.flush()
        finally:
            try:
                ser and ser.close()
            except Exception:                              # noqa: BLE001 - already gone
                pass
            fh.close()

    def _reconnect(self, ser, port, why):
        """The port stopped answering. Keep the flight open (the recording, the map) and reopen the port every second;
        returns the new port object, or None after RECONNECT_S seconds (the link then ends with an error) or on stop."""
        try:
            ser.close()
        except Exception:                                  # noqa: BLE001
            pass
        since = time.monotonic()
        with self.lock:
            self.state.update(reconnecting=True, reconnects=self.state.get("reconnects", 0) + 1)
        while not self.stop_ev.wait(1.0):
            try:
                new = self._open_port(port)
            except Exception:                              # noqa: BLE001 - still unplugged
                if time.monotonic() - since > self.RECONNECT_S:
                    self._fail(f"radio disconnected ({why}); not back after {self.RECONNECT_S} s")
                    return None
                continue
            with self.lock:
                self.state.update(reconnecting=False)
            return new
        return None

    def _run_replay(self, track_file: Path, speed: float):
        """Turn a processed track (scene/tracks/*.json) back into CRSF frames, paced in real time."""
        from .geo import unproject
        try:
            d = json.loads(Path(track_file).read_text(encoding="utf-8"))
            meta = json.loads((Path(track_file).parent.parent / "scene.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            return self._fail(f"cannot read {track_file}: {ex}")
        g = meta["grid"]
        margin = next(iter((d.get("margin") or {}).values()), None)
        p, (fh, w) = crsf.Parser(), self._open_csv()
        t0 = time.monotonic()
        with self.lock:
            self.state["status"] = "live"
        try:
            n, T = d["n"], d["t"]
            start_t = T[0] or 0
            prev = None
            cv, amps, cells = d.get("cell_v"), d.get("amps"), d.get("bat_cells") or 0   # the flight's real battery
            mah, last_t = 0.0, None
            for i in range(n):
                if self.stop_ev.is_set():
                    break
                if d["x"][i] is None:
                    continue
                wait = ((T[i] or 0) - start_t) / max(speed, 0.05) - (time.monotonic() - t0)
                if wait > 0 and self.stop_ev.wait(wait):
                    break
                lat, lon = (float(v) for v in unproject(g["min_e"] + d["x"][i], g["min_n"] + d["y"][i], g.get("crs") or "EPSG:2056"))
                if prev is not None:
                    dt = max((T[i] or 0) - (T[prev] or 0), 1e-3)
                    dx, dy, dz = d["x"][i] - d["x"][prev], d["y"][i] - d["y"][prev], d["z"][i] - d["z"][prev]
                    spd, hdg, vs = math.hypot(dx, dy) / dt * 3.6, (math.degrees(math.atan2(dx, dy)) + 360) % 360, dz / dt
                else:
                    spd = hdg = vs = 0.0
                prev = i
                m = margin[i] if margin and margin[i] is not None else 20
                lq = max(0, min(100, 70 + 3 * m)) if m > -10 else 0
                buf = crsf.gps_frame(lat, lon, spd, hdg, d["z"][i], 14) + crsf.vario_frame(vs)
                if lq > 0:                         # no link statistics while the link is "lost"
                    buf = crsf.link_frame(-60 - max(0, 30 - m), lq) + buf     # margin 30 dB -> -60 dBm
                if cv and cells and cv[i] is not None:
                    a_ = (amps[i] or 0.0) if amps else 0.0
                    mah += a_ * min(1.0, (T[i] or 0) - (last_t if last_t is not None else (T[i] or 0))) / 3.6
                    last_t = T[i] or 0
                    buf += crsf.battery_frame(cv[i] * cells, a_, mah, 0)
                else:
                    buf += crsf.battery_frame(16.4 - 0.002 * i, 12, i // 2, max(0, 100 - i // 50))
                buf += crsf.mode_frame("ANGL")
                self._handle(p.feed(buf), w, t0)
                with self.lock:
                    self.state.update(frames=p.frames, bad=p.bad)
            with self.lock:
                self.state["status"] = "ended"
        finally:
            fh.close()

    def _fail(self, msg):
        with self.lock:
            self.state.update(status="error", error=msg)

    # ------------------------------------------------------------ data out
    def snapshot(self, since: int = 0):
        now = time.monotonic()
        with self.lock:
            st = dict(self.state)
            st["frame_age"] = None if self.last_frame is None else round(now - self.last_frame, 2)
            st["gps_age"] = None if self.last_gps is None else round(now - self.last_gps, 2)
            st["latest"] = dict(self.latest)
            st["open_for"] = None if self.opened is None else round(now - self.opened, 1)
            st["gps_every"] = self._usual("gps")         # e.g. 2.9 s with a slow telemetry ratio
            st["frame_every"] = self._usual("frame")
            st["seq"] = self.seq
            st["samples"] = [s for s in self.samples[-2000:] if s["seq"] > since]
        return st


LINK = LiveLink()
