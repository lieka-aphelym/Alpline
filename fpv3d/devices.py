"""What is plugged in by USB: the launcher's drone page (no Tk here, so it can be tested on its own).

A serial port is one of:
    drone   answers Betaflight's MSP protocol (fpv3d.blackbox.probe): board, firmware, blackbox size
    radio   any other USB serial device (EdgeTX radios in USB Serial / VCP mode use the same chip family)
    busy    another program holds it (a live flight, Betaflight Configurator): asked again later
Ports without a USB id (built-in COM1, Bluetooth) are left out.
"""
from __future__ import annotations


def is_usb(hwid: str) -> bool:
    return "VID:PID" in (hwid or "").upper()


def classify(dev: str, description: str, can_open, probe) -> dict:
    """can_open(dev) -> bool, probe(dev) -> Betaflight info dict or None. Both are passed in so tests need no port."""
    name = description or dev
    try:
        ok = can_open(dev)
    except Exception:
        ok = False
    if not ok:
        return dict(kind="busy", port=dev, name=name)
    try:
        info = probe(dev)
    except Exception:
        info = None
    return dict(kind="drone", **info) if info else dict(kind="radio", port=dev, name=name)


class Watcher:
    """Keeps the list of devices up to date from successive port listings. A port is asked again only when it is new
    or was busy, never while `paused` (the blackbox download is using the drone)."""
    def __init__(self, can_open, probe):
        self.can_open, self.probe = can_open, probe
        self.known: dict = {}

    def update(self, ports, paused=False):
        """ports: [(device, hwid, description)]. Returns (changed, newly plugged drones)."""
        changed, new_drones = False, []
        current = {d: (h, desc) for d, h, desc in ports if is_usb(h)}
        for dev in list(self.known):
            if dev not in current:
                self.known.pop(dev); changed = True
        if paused:
            return changed, new_drones
        for dev, (_h, desc) in current.items():
            if dev in self.known and self.known[dev]["kind"] != "busy":
                continue
            new = classify(dev, desc, self.can_open, self.probe)
            if self.known.get(dev) != new:
                if new["kind"] == "drone" and self.known.get(dev, {}).get("kind") != "drone":
                    new_drones.append(new)
                self.known[dev] = new; changed = True
        return changed, new_drones


def drone_text(d: dict) -> tuple:
    """(title line, detail line) for a drone found on USB."""
    used, tot = d.get("flash_used"), d.get("flash_total")
    detail = (f"blackbox: {used / 2 ** 20:.1f} of {tot / 2 ** 20:.0f} MB used" + (" (empty)" if not used else "")
              if used is not None and tot else "blackbox on an SD card")
    return f"● {d.get('board', '?')} · {d.get('firmware', '?')} · {d.get('port', '?')}", detail
