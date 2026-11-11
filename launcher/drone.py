"""The drone page: drone and radio on USB, blackbox download, battery packs, live flight."""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk

from fpv3d import paths
from fpv3d.brand import APP_NAME

from .common import APP, ROOT, unexpected
from .style import ACC, BAD, BG, BG2, FG, FG2, MONO_B, MONO_S, OK, RULE, S, SANS
from .widgets import FitLabel, Tip


class DronePage:
    """Mixed into Launcher (launcher/app.py): methods only, they share its self."""

    # ------------------------------------------------------------ drone page (USB)
    def build_drone_page(self, parent):
        col = self.page_frame(parent, "DRONE ON USB",
                              f"Plug the drone in with its USB cable (no battery needed). {APP_NAME} finds a Betaflight flight "
                              "controller by itself and can copy its blackbox: every flight with GPS is added to the location "
                              "where it took off. Close Betaflight Configurator first (it holds the port).")
        self.drone_lab = FitLabel(col, font=MONO_B, fg=FG2, bg=BG)
        self.drone_lab.pack(fill="x")
        self.drone_info = FitLabel(col, font=MONO_S, fg=FG2, bg=BG)
        self.drone_info.pack(fill="x", pady=(S(2), S(8)))
        row = tk.Frame(col, bg=BG); row.pack(fill="x")
        self.bb_btn = self.button(row, "[download blackbox]", self.download_blackbox, primary=True)
        self.bb_btn.pack(side="left")
        self.bb_here = tk.BooleanVar(value=False)
        self.bb_here_cb = tk.Checkbutton(row, variable=self.bb_here, font=SANS, fg=FG, bg=BG, selectcolor=BG2,
                                         activebackground=BG, activeforeground=FG, bd=0, highlightthickness=0)
        self.bb_here_cb.pack(side="left", padx=(S(12), 0))
        Tip(self.bb_here_cb, "Off: each flight goes to the location whose map contains its take-off point.")
        box = tk.Frame(col, bg=RULE, padx=1, pady=1); box.pack(fill="x", pady=(S(10), 0))
        self.bb_log = tk.Text(box, height=9, font=MONO_S, fg=FG2, bg=BG2, bd=0, relief="flat", wrap="word",
                              padx=S(8), pady=S(6), highlightthickness=0, cursor="arrow")
        self.bb_log.pack(fill="x")
        self.bb_log.tag_configure("ok", foreground=OK)
        self.bb_log.tag_configure("bad", foreground=BAD)
        self.bb_log.insert("end", "The download's progress shows here.")
        self.bb_log.configure(state="disabled")

        tk.Frame(col, bg=BG, height=S(18)).pack()
        self.section("RADIO ON USB", col)
        self.radio_lab = FitLabel(col, font=MONO_B, fg=FG2, bg=BG)
        self.radio_lab.pack(fill="x")
        self.radio_info = FitLabel(col, font=MONO_S, fg=FG2, bg=BG)
        self.radio_info.pack(fill="x", pady=(S(2), S(8)))
        row = tk.Frame(col, bg=BG); row.pack(fill="x")
        self.live_btn = self.button(row, "[live flight in 3d]", self.open_live)
        self.live_btn.pack(side="left")
        Tip(self.live_btn, "Opens the selected location on the fly tab: pick the radio's port there and connect.")
        tk.Frame(col, bg=BG, height=S(18)).pack()
        self.section("BATTERY PACKS", col)
        self.packs_lab = FitLabel(col, font=SANS, fg=FG2, bg=BG)
        self.packs_lab.pack(fill="x", pady=(0, S(6)))
        row = tk.Frame(col, bg=BG); row.pack(fill="x")
        b = self.button(row, "[battery packs]", lambda: self.open("/viewer/packs.html"))
        b.pack(side="left")
        Tip(b, "Every pack's health over time, how long it lasts at your flying, the flights without a pack, the charger check.")
        self.show_packs()
        self.show_devices()

    def show_packs(self):
        """The line under BATTERY PACKS; read in the background (it grows with every flight)."""
        def work():
            try:
                from fpv3d import battery
                o = battery.overview(ROOT)
                none = sum(1 for f in o["flights"] if not f.get("pack"))
                flagged = [p["name"] for p in o["packs"] if p["flags"] and not p.get("retired")]
                text = (f"{len(o['packs'])} pack(s) · {len(o['flights'])} flight(s) with battery data"
                        + (f" · {none} without a pack" if none else "")
                        + (f" · check: {', '.join(flagged)}" if flagged else ""))
            except Exception as ex:                      # noqa: BLE001 - the page works without it
                unexpected(ex)
                text = f"battery data not readable ({ex.__class__.__name__})"
            try:
                self.root.after(0, lambda: self.packs_lab.set(text))
            except Exception:                            # noqa: BLE001 - the window is closing
                pass
        threading.Thread(target=work, daemon=True).start()

    def start_device_watch(self):
        try:
            from serial.tools import list_ports  # noqa: F401
        except Exception as ex:
            unexpected(ex)
            self.drone_lab.set("USB detection needs the pyserial library (pip install pyserial)")
            self.bb_btn.configure(state="disabled"); self.live_btn.configure(state="disabled")
            return
        threading.Thread(target=self._watch_devices, daemon=True).start()

    def _watch_devices(self):
        """Every few seconds: which USB serial devices are plugged in (fpv3d/devices.py decides what each one is)."""
        import serial
        from serial.tools import list_ports
        from fpv3d.devices import Watcher
        try:
            from fpv3d.blackbox import probe
        except Exception as ex:
            unexpected(ex)
            probe = lambda dev: None

        def can_open(dev):
            serial.Serial(dev, 115200, timeout=0.05).close()
            return True
        w = Watcher(can_open, probe)
        while True:
            try:
                ports = [(p.device, p.hwid or "", p.description or "") for p in list_ports.comports()]
            except Exception as ex:
                unexpected(ex)
                ports = []
            changed, drones = w.update(ports, paused=self.bb_proc is not None)
            for d in drones:
                self.root.after(0, lambda d=d: self.say(f"drone plugged in: {d['board']} · {d['firmware']} · "
                                                        "see the drone page to download its blackbox", "ok"))
            if changed:
                snap = {k: dict(v) for k, v in w.known.items()}
                self.root.after(0, lambda s=snap: self._devices_changed(s))
            time.sleep(2.5)

    def _devices_changed(self, devs):
        self.devices = devs
        self.show_devices()
        self.draw_badge("drone")

    def show_devices(self):
        drones = [d for d in self.devices.values() if d["kind"] == "drone"]
        radios = [d for d in self.devices.values() if d["kind"] == "radio"]
        busy = [d for d in self.devices.values() if d["kind"] == "busy"]
        if drones:
            from fpv3d.devices import drone_text
            title, detail = drone_text(drones[0])
            self.drone_lab.set(title, fg=OK)
            self.drone_info.set(detail)
        else:
            self.drone_lab.set("○ no drone on USB", fg=FG2)
            self.drone_info.set(f"{', '.join(b['port'] for b in busy)} in use by another program (Betaflight Configurator?)"
                                if busy else "plug it in: it shows here within a few seconds")
        running = self.bb_proc is not None
        self.bb_btn.configure(state="normal" if drones and not running else "disabled",
                              text="[downloading…]" if running else "[download blackbox]")
        cur = self.map.current() if hasattr(self, "map") else None
        self.bb_here_cb.configure(text=f"add every flight to {cur.get('title') or cur['name']}" if cur
                                  else "add every flight to the selected location",
                                  state="normal" if cur else "disabled")
        if radios:
            r = radios[0]
            self.radio_lab.set(f"● radio · {r['port']}", fg=ACC)
            self.radio_info.set(f"{r['name']}" + (f" (+{len(radios) - 1} more USB serial)" if len(radios) > 1 else ""))
        else:
            self.radio_lab.set("○ no radio on USB", fg=FG2)
            self.radio_info.set("connect the radio by USB and choose USB Serial (VCP) on it, for live flight")
        self.live_btn.configure(state="normal" if cur and cur.get("built") else "disabled")

    def bb_write(self, line, tag=None):
        self.bb_log.configure(state="normal")
        self.bb_log.insert("end", line + "\n", tag or ())
        self.bb_log.see("end")
        self.bb_log.configure(state="disabled")

    def download_blackbox(self):
        drones = [d for d in self.devices.values() if d["kind"] == "drone"]
        if not drones or self.bb_proc is not None:
            return
        args = paths.cli_cmd(unbuffered=True) + ["--scenes", str(ROOT / "scenes"), "--cache", str(ROOT / "cache"),
                                                  "blackbox", "--port", drones[0]["port"]]
        cur = self.map.current()
        if self.bb_here.get() and cur:
            args += ["--location", cur["name"]]
        self.bb_log.configure(state="normal"); self.bb_log.delete("1.0", "end"); self.bb_log.configure(state="disabled")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8",
               "PYTHONPATH": os.pathsep.join(filter(None, [str(APP), os.environ.get("PYTHONPATH")]))}
        try:
            self.bb_proc = subprocess.Popen(args, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                            encoding="utf-8", errors="replace", env=env,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as ex:
            self.bb_write(f"could not start: {ex}", "bad")
            return
        self.logo.busy(True)
        self.show_devices()

        self.bb_bats = []

        def read():
            added = 0
            for line in self.bb_proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                if line.startswith("ADDED "):
                    added += 1
                    continue
                if line.startswith("BATTERY "):
                    self.bb_bats.append(line[8:].strip())
                    continue
                tag = "ok" if "→ added" in line or line.startswith("done:") else \
                      "bad" if re.search(r"^(No |The |error|Traceback)|could not", line) else None
                self.root.after(0, lambda l=line, t=tag: self.bb_write(l, t))
            code = self.bb_proc.wait()
            self.root.after(0, lambda: self._bb_done(code, added))
        threading.Thread(target=read, daemon=True).start()

    def _bb_done(self, code, added):
        self.bb_proc = None
        self.logo.busy(False)
        self.show_devices()
        self.check_offline(quiet=True)
        if code == 0:
            self.say(f"{added} flight(s) added · unplug the drone" if added else "no new flights · unplug the drone",
                     "ok" if added else "info")
            if self.bb_bats:
                self.ask_pack(self.bb_bats)
        else:
            self.say("blackbox download stopped: see the drone page", "bad")
        self.show_packs()

    def ask_pack(self, fids):
        """After a download: which pack flew these flights? (one choice for all; changeable per flight later)"""
        from fpv3d import battery
        o = battery.overview(ROOT)
        packs = [p for p in o["packs"] if not p.get("retired")]
        w = tk.Toplevel(self.root, bg=BG)
        w.title(f"{APP_NAME}: which pack?")
        w.transient(self.root)
        w.resizable(False, False)
        f = tk.Frame(w, bg=BG, padx=S(16), pady=S(14)); f.pack(fill="both")
        tk.Label(f, text=f"Which pack did you fly? ({len(fids)} flight(s) with battery data)", font=MONO_B,
                 fg=FG, bg=BG, anchor="w").pack(fill="x")
        tk.Label(f, text=f"{APP_NAME} then follows each pack's health and how long it lasts. You can change it per flight on the packs page.",
                 font=SANS, fg=FG2, bg=BG, anchor="w", justify="left", wraplength=S(420)).pack(fill="x", pady=(S(2), S(8)))
        names = [f"{p['name']} · {p['cells']}S {p['capacity']} {p['chem_label']}" for p in packs] + ["+ new pack…"]
        choice = tk.StringVar(value=next((n for p, n in zip(packs, names) if p["id"] == o.get("last_pack")), names[0]))
        cb = ttk.Combobox(f, textvariable=choice, values=names, state="readonly", width=34); cb.pack(anchor="w")
        newf = tk.Frame(f, bg=BG)
        name_v, cells_v, cap_v = tk.StringVar(value=f"pack {len(o['packs']) + 1}"), tk.StringVar(value="6"), tk.StringVar(value="1300")
        for lab, var, wd in (("name", name_v, 14), ("cells", cells_v, 3), ("mAh", cap_v, 6)):
            tk.Label(newf, text=lab, font=SANS, fg=FG2, bg=BG).pack(side="left", padx=(0, S(4)))
            tk.Entry(newf, textvariable=var, width=wd, bg=BG2, fg=FG, insertbackground=FG, relief="flat").pack(side="left", padx=(0, S(10)))
        chems = list(battery.CHEM)
        chem_v = tk.StringVar(value=battery.CHEM["lipo"]["label"])
        ttk.Combobox(newf, textvariable=chem_v, values=[battery.CHEM[k]["label"] for k in chems], state="readonly", width=8).pack(side="left")
        msg = tk.Label(f, text="", font=SANS, fg=BAD, bg=BG, anchor="w")

        def sync(*_):
            newf.pack(anchor="w", pady=(S(8), 0)) if choice.get().startswith("+") else newf.pack_forget()
        cb.bind("<<ComboboxSelected>>", sync); sync()
        btns = tk.Frame(f, bg=BG); btns.pack(fill="x", pady=(S(12), 0), side="bottom")
        msg.pack(fill="x", side="bottom")

        def save():
            try:
                if choice.get().startswith("+"):
                    kind = next(k for k in chems if battery.CHEM[k]["label"] == chem_v.get())
                    pid = battery.save_pack(dict(name=name_v.get(), cells=cells_v.get(), capacity=cap_v.get(), chemistry=kind), ROOT)["id"]
                else:
                    pid = packs[names.index(choice.get())]["id"]
                battery.assign(fids, pid, ROOT)
            except (ValueError, KeyError) as ex:
                msg.configure(text=str(ex))
                return
            w.destroy()
            self.show_packs()
            self.say("pack saved for the new flights", "ok")
        self.button(btns, "[save]", save, primary=True).pack(side="left")
        self.button(btns, "[not now]", w.destroy).pack(side="left", padx=(S(8), 0))
        w.update_idletasks()
        w.geometry(f"+{self.root.winfo_rootx() + S(120)}+{self.root.winfo_rooty() + S(120)}")
        w.grab_set()

    def open_live(self):
        cur = self.map.current()
        if cur and cur.get("built"):
            self.open(f"/viewer/?scene={cur['name']}&tab=fly")
