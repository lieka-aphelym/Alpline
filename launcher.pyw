"""Alpline (by lieka) launcher: pick Full or Lite mode, see your locations on a map of Switzerland, open the 3D viewer.

Double-click Alpline.bat (or the desktop shortcut it can create). The window starts the local server in the
chosen mode, opens your browser, and stops the server when you close it. It also tells you whether your
locations are ready to use offline at the field.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SETTINGS = ROOT / "launcher.json"
LOG = ROOT / "logs" / "server.log"

# colours of the viewer's dark theme
BG, BG2, BG3, FG, FG2, RULE, ACC = "#07090c", "#10141a", "#171c24", "#f2f5f8", "#a9b4c2", "#2a313c", "#ffd60a"
MONO = ("Consolas", 10)
SANS = ("Segoe UI", 10)


def venv_exe(name: str) -> str:
    """python.exe / pythonw.exe of the project's virtual environment (.venv), where numpy, rasterio, PyYAML...
    are installed. Asked for explicitly: with the Microsoft Store Python, sys.executable inside a venv points
    to the base Python, which does not have those libraries."""
    for d in (ROOT / ".venv" / "Scripts", ROOT / ".venv" / "bin", Path(sys.prefix) / "Scripts", Path(sys.prefix) / "bin"):
        for n in (name, name.replace(".exe", ""), "python3" if name.startswith("python.") else name):
            if (d / n).exists():
                return str(d / n)
    exe = Path(sys.executable)
    twin = exe.with_name(name)
    return str(twin if twin.exists() else exe)


def python_exe() -> str:
    """The python that runs the server (console version, no window: CREATE_NO_WINDOW)."""
    return venv_exe("python.exe")


def port_free(port: int) -> bool:
    with socket.socket() as s:
        if os.name != "nt":                     # like the server: ignore old connections still closing (TIME_WAIT)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def load_settings() -> dict:
    try:
        return {"mode": "full", "port": 8000, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except Exception:
        return {"mode": "full", "port": 8000}


import math
import re
from tkinter import ttk

GREY = "#7d8796"


class Tip:
    """Small hover tooltip (the explanations live here instead of on the screen)."""
    def __init__(self, w, text):
        self.w, self.text, self.top = w, text, None
        w.bind("<Enter>", self.show, add="+"); w.bind("<Leave>", self.hide, add="+")

    def show(self, _=None):
        t = self.text() if callable(self.text) else self.text
        if not t:
            return
        self.top = tk.Toplevel(self.w); self.top.wm_overrideredirect(True)
        self.top.wm_geometry(f"+{self.w.winfo_rootx()}+{self.w.winfo_rooty() + self.w.winfo_height() + 4}")
        tk.Label(self.top, text=t, font=SANS, fg=FG, bg=BG3, justify="left", wraplength=340, padx=8, pady=5,
                 highlightthickness=1, highlightbackground=RULE).pack()

    def hide(self, _=None):
        if self.top:
            self.top.destroy(); self.top = None


def is_sim(t: dict) -> bool:
    """Training-flight logs: named <location>_sim_<date> or stored under logs/sim/."""
    return "_sim_" in t.get("name", "") or bool(re.search(r"[\\/]logs[\\/]sim[\\/]", t.get("source", "")))


def flight_stats(name: str) -> dict:
    """Real and simulator logs of a built location (from scenes/<name>/scene.json)."""
    out = {"real": 0, "sim": 0, "real_s": 0.0, "sim_s": 0.0, "last": None, "built": None}
    f = ROOT / "scenes" / name / "scene.json"
    if not f.exists():
        return out
    out["built"] = f.stat().st_mtime
    try:
        tracks = json.loads(f.read_text(encoding="utf-8")).get("tracks", [])
    except Exception:
        return out
    for t in tracks:
        k = "sim" if is_sim(t) else "real"
        out[k] += 1
        out[k + "_s"] += float(t.get("duration_s") or 0)
        p = ROOT / "scenes" / name / t.get("file", "")
        if p.exists():
            out["last"] = max(out["last"] or 0, p.stat().st_mtime)
    return out


def fmt_dur(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600} h {s % 3600 // 60:02d}" if s >= 3600 else f"{s // 60} min" if s >= 60 else f"{s} s"


def fmt_day(ts) -> str:
    return time.strftime("%d %b %Y", time.localtime(ts)) if ts else "–"


class Launcher:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_settings()
        self.proc: subprocess.Popen | None = None
        self.running_mode = None
        self.port = None
        self.online = None
        root.title("Alpline by lieka")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.style()

        # ---- top bar: title, mode, open buttons
        top = tk.Frame(root, bg=BG); top.pack(fill="x", padx=14, pady=(10, 8))
        tk.Label(top, text="ALPLINE", font=("Consolas", 16, "bold"), fg=FG, bg=BG).pack(side="left")
        tk.Label(top, text="by lieka", font=("Consolas", 9), fg=FG2, bg=BG).pack(side="left", padx=(6, 0), pady=(6, 0))
        self.mode = tk.StringVar(value=self.cfg.get("mode", "full"))
        seg = tk.Frame(top, bg=RULE, padx=1, pady=1); seg.pack(side="left", padx=(16, 8))
        self.mode_btns = {}
        for m in ("full", "lite"):
            b = tk.Button(seg, text=m, font=("Consolas", 10, "bold"), width=6, relief="flat", bd=0, cursor="hand2",
                          command=lambda m=m: self.set_mode(m))
            b.pack(side="left")
            self.mode_btns[m] = b
        Tip(self.mode_btns["full"], "Full: the whole 3D at full quality, redrawn continuously. New locations: 2 m terrain, "
                                    "2 m photo, 10 m signal grid, 3D buildings.")
        Tip(self.mode_btns["lite"], "Lite: for slower computers. 3D redrawn only when something changes, lighter mesh. "
                                    "New locations: 5 m terrain, lighter photo, 20 m signal grid, no 3D buildings.")
        self.mode_info = tk.Label(top, font=SANS, fg=FG2, bg=BG); self.mode_info.pack(side="left")
        self.stop_btn = self.button(top, "[stop]", self.stop); self.stop_btn.pack(side="right")
        Tip(self.stop_btn, "Stop the local server (closing this window does it too).")
        self.button(top, "[locations map]", lambda: self.open("/viewer/map.html")).pack(side="right", padx=(0, 6))
        self.button(top, "[3d viewer]", lambda: self.open("/viewer/"), primary=True).pack(side="right", padx=(0, 6))
        tk.Frame(root, bg=RULE, height=1).pack(fill="x")

        # ---- middle: map | locations table + details card
        mid = tk.Frame(root, bg=BG); mid.pack(fill="both", padx=14, pady=10)
        self.map = SwissMap(self, mid)
        right = tk.Frame(mid, bg=BG, width=390, height=self.map.h + 36)   # fixed size: the window never jumps
        right.pack(side="left", fill="y", padx=(12, 0)); right.pack_propagate(False)
        self.loc_title = self.section("LOCATIONS", right)
        self.table = Table(self, right, height=max(6, (self.map.h - 205) // 21))
        self.card = Card(self, right)

        # ---- status bar
        tk.Frame(root, bg=RULE, height=1).pack(fill="x")
        bar = tk.Frame(root, bg=BG); bar.pack(fill="x", padx=14, pady=5)
        self.status = tk.Label(bar, font=("Consolas", 9), fg=FG2, bg=BG); self.status.pack(side="left")
        self.offline = tk.Label(bar, font=("Consolas", 9), fg=FG2, bg=BG); self.offline.pack(side="left", padx=(18, 0))
        Tip(self.offline, self.offline_tip)
        self.net = tk.Label(bar, font=("Consolas", 9), fg=FG2, bg=BG); self.net.pack(side="left", padx=(18, 0))
        Tip(self.net, lambda: "Internet is used for the map background, new downloads and place search. Without it the "
                              "3D viewer still works for built locations." if self.online is not None else "")
        self.flights = tk.Label(bar, font=("Consolas", 9), fg=FG2, bg=BG); self.flights.pack(side="left", padx=(18, 0))
        sc = self.button(bar, "[shortcut]", self.make_shortcut, small=True); sc.pack(side="right")
        Tip(sc, "Add an 'Alpline' shortcut to your desktop.")
        ck = self.button(bar, "[check]", self.check_offline, small=True); ck.pack(side="right", padx=(0, 6))
        Tip(ck, "Reload the locations and check the internet again.")
        self.msg = tk.Label(bar, font=SANS, fg=ACC, bg=BG); self.msg.pack(side="right", padx=(0, 12))

        self.set_mode(self.mode.get(), save=False)
        self.check_offline()

    # ------------------------------------------------------------ widgets
    def style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("L.Treeview", background=BG2, fieldbackground=BG2, foreground=FG, font=MONO, rowheight=21,
                     borderwidth=0, relief="flat")
        st.map("L.Treeview", background=[("selected", ACC)], foreground=[("selected", "#000")])
        st.configure("L.Treeview.Heading", background=BG, foreground=FG2, font=("Consolas", 8, "bold"), relief="flat",
                     borderwidth=0)
        st.map("L.Treeview.Heading", background=[("active", BG3)])
        st.layout("L.Treeview", [("L.Treeview.treearea", {"sticky": "nswe"})])
        st.configure("L.Vertical.TScrollbar", background=BG3, troughcolor=BG2, bordercolor=BG2, arrowcolor=FG2,
                     lightcolor=BG3, darkcolor=BG3, gripcount=0)
        st.map("L.Vertical.TScrollbar", background=[("active", RULE), ("!active", BG3)])

    def section(self, title, parent):
        f = tk.Frame(parent, bg=BG); f.pack(fill="x", pady=(0, 6))
        lab = tk.Label(f, text=title, font=("Consolas", 9, "bold"), fg=FG, bg=BG); lab.pack(side="left")
        tk.Frame(f, bg=RULE, height=1).pack(side="left", fill="x", expand=True, padx=(8, 0), pady=(2, 0))
        return lab

    def button(self, parent, text, cmd, primary=False, small=False):
        return tk.Button(parent, text=text, command=cmd, font=("Consolas", 9 if small else 10), relief="flat", bd=0,
                         cursor="hand2", padx=6 if small else 10, pady=1 if small else 4,
                         bg=ACC if primary else BG2, fg="#000" if primary else FG,
                         activebackground=ACC if primary else BG3, activeforeground="#000" if primary else FG)

    def say(self, text):
        self.msg.configure(text=text)
        self.root.after(8000, lambda: self.msg.cget("text") == text and self.msg.configure(text=""))

    # ------------------------------------------------------------ mode
    def set_mode(self, m, save=True):
        self.mode.set(m)
        for k, b in self.mode_btns.items():
            on = k == m
            b.configure(bg=ACC if on else BG2, fg="#000" if on else FG2, activebackground=ACC if on else BG3)
        self.mode_info.configure(text="full quality" if m == "full" else "lighter, for slower computers")
        if save:
            self.cfg["mode"] = m
            self.save()
        self.refresh_status()

    def save(self):
        try:
            SETTINGS.write_text(json.dumps(self.cfg, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------ server
    def server_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> bool:
        self.stop()
        base = int(self.cfg.get("port", 8000))
        for _ in range(12):                     # same port as before if possible: the browser keeps your settings per port
            if port_free(base):
                break
            time.sleep(0.25)
        port = next((p for p in range(base, base + 20) if port_free(p)), None)
        if port is None:
            self.say("No free port between 8000 and 8019: close the other Alpline windows.")
            return False
        args = [python_exe(), "-m", "fpv3d", "serve", "--port", str(port), "--no-browser"]
        if self.mode.get() == "lite":
            args.append("--lite")
        LOG.parent.mkdir(exist_ok=True)
        log = open(LOG, "w", encoding="utf-8", errors="replace")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.port, self.running_mode = port, self.mode.get()
        for _ in range(60):                     # wait until it answers (max ~15 s)
            if self.proc.poll() is not None:
                self.say(f"The server stopped right away. See {LOG.relative_to(ROOT)}.")
                self.proc = None
                self.refresh_status()
                return False
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/mode.js", timeout=0.5).read()
                break
            except Exception:
                self.root.update(); time.sleep(0.25)
        self.refresh_status()
        return True

    def open(self, path):
        if not self.server_alive() or self.running_mode != self.mode.get():
            self.status.configure(text="○ starting…", fg=FG2); self.root.update()
            if not self.start():
                return
        webbrowser.open(f"http://127.0.0.1:{self.port}{path}")
        self.say("opened in your browser · keep this window open")

    def stop(self):
        if self.server_alive():
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc, self.running_mode = None, None
        self.refresh_status()

    def refresh_status(self):
        if not hasattr(self, "status"):
            return
        if self.server_alive():
            note = "" if self.running_mode == self.mode.get() else f" (→ {self.mode.get()} on next open)"
            self.status.configure(text=f"● running · {self.running_mode} · :{self.port}{note}", fg="#3ddc84")
            self.stop_btn.configure(state="normal")
        else:
            self.status.configure(text="○ server off · starts when you open", fg=FG2)
            self.stop_btn.configure(state="disabled")

    def quit(self):
        self.stop()
        self.root.destroy()

    # ------------------------------------------------------------ locations, offline check
    def check_offline(self):
        self.map.load_locations()
        locs = self.map.locs
        for l in locs:
            l["stats"] = flight_stats(l["name"])
        self.loc_title.configure(text=f"LOCATIONS · {len(locs)}")
        self.table.fill(locs)
        self.map.draw()
        self.card.show(self.map.current())
        built = [l for l in locs if l.get("built")]
        self.offline.configure(text=f"{len(built)}/{len(locs)} built" + (" · offline ok" if built else ""),
                               fg=FG2 if len(built) == len(locs) else FG)
        real = sum(l["stats"]["real"] for l in locs); sim = sum(l["stats"]["sim"] for l in locs)
        self.flights.configure(text=f"logs: {real} real · {sim} sim")
        self.net.configure(text="internet …", fg=FG2)

        def net():
            try:
                urllib.request.urlopen("https://wmts.geo.admin.ch/", timeout=3)
                ok = True
            except urllib.error.HTTPError:
                ok = True                       # the server answered: we are online
            except Exception:
                ok = False
            self.online = ok
            self.root.after(0, lambda: self.net.configure(text="internet yes" if ok else "internet no",
                                                          fg="#3ddc84" if ok else "#ff9f43"))
        threading.Thread(target=net, daemon=True).start()

    def offline_tip(self):
        missing = [l["name"] for l in self.map.locs if not l.get("built")]
        return ("Built locations open in the 3D viewer without internet." +
                (f"\nNot built yet: {', '.join(missing)}" if missing else ""))

    def select(self, name):
        """one location chosen (map click or table row): ring on the map, row in the table, details card"""
        self.map.selected = name
        self.map.draw(save=False)
        self.table.select(name)
        self.card.show(self.map.current())

    def open_location(self, l):
        if l:
            self.open(f"/viewer/?scene={l['name']}" if l.get("built") else "/viewer/map.html")

    # ------------------------------------------------------------ desktop shortcut (Windows)
    def make_shortcut(self):
        if os.name != "nt":
            self.say("Desktop shortcuts are made on Windows only.")
            return
        pyw = venv_exe("pythonw.exe")             # the project's .venv, so the map can read your locations
        ps = ("$d=[Environment]::GetFolderPath('Desktop');"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Alpline.lnk'));"
              f"$s.TargetPath='{pyw}';$s.Arguments='\"{ROOT / 'launcher.pyw'}\"';$s.WorkingDirectory='{ROOT}';"
              "$s.Description='Alpline by lieka: FPV line of sight on Swiss terrain';$s.Save()")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.say("shortcut 'Alpline' added to your desktop" if r.returncode == 0
                 else f"could not create the shortcut: {(r.stderr or r.stdout).strip()[:120]}")


def split_name(name):
    """'007_moleson' -> ('007', 'moleson'); 'test' -> ('', 'test')"""
    head, _, rest = name.partition("_")
    return (head, rest) if head.isdigit() and rest else ("", name)


class Table:
    """Locations in number order: # · name · real logs · sim logs (grey row = not built yet)."""
    def __init__(self, app, parent, height):
        self.app = app
        box = tk.Frame(parent, bg=RULE, padx=1, pady=1); box.pack(fill="x")
        self.tv = ttk.Treeview(box, style="L.Treeview", columns=("num", "name", "real", "sim"), show="headings",
                               height=height, selectmode="browse")
        for c, label, w, anchor in (("num", "#", 42, "w"), ("name", "LOCATION", 190, "w"),
                                    ("real", "REAL", 54, "e"), ("sim", "SIM", 54, "e")):
            self.tv.heading(c, text=label, anchor=anchor)
            self.tv.column(c, width=w, anchor=anchor, stretch=c == "name")
        self.tv.tag_configure("nb", foreground=GREY)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tv.yview, style="L.Vertical.TScrollbar")
        def autohide(lo, hi):                   # the scrollbar only shows when the list is longer than the box
            sb.set(lo, hi)
            if float(lo) <= 0 and float(hi) >= 1:
                sb.pack_forget()
            elif not sb.winfo_ismapped():
                sb.pack(side="left", fill="y")
        self.tv.configure(yscrollcommand=autohide)
        self.tv.pack(side="left", fill="x", expand=True)
        self.tv.bind("<<TreeviewSelect>>", self.on_select)
        self.tv.bind("<Double-1>", lambda e: app.open_location(app.map.current()))
        self.tv.bind("<Return>", lambda e: app.open_location(app.map.current()))
        self.busy = False

    def fill(self, locs):
        self.busy = True
        self.tv.delete(*self.tv.get_children())
        for l in locs:
            num, rest = split_name(l["name"])
            st = l.get("stats") or {}
            self.tv.insert("", "end", iid=l["name"], tags=() if l.get("built") else ("nb",),
                           values=(num, l.get("title") or rest, st.get("real", 0) or "·", st.get("sim", 0) or "·"))
        if self.app.map.selected in self.tv.get_children():
            self.tv.selection_set(self.app.map.selected); self.tv.see(self.app.map.selected)
        self.busy = False

    def select(self, name):
        if name in self.tv.get_children() and self.tv.selection() != (name,):
            self.busy = True
            self.tv.selection_set(name); self.tv.see(name)
            self.app.root.after_idle(lambda: setattr(self, "busy", False))

    def on_select(self, _):
        if self.busy:
            return
        sel = self.tv.selection()
        if sel:
            self.app.select(sel[0])


class Card:
    """Details of the selected location, with a real / sim bar chart of its logs."""
    BAR_W = 200

    def __init__(self, app, parent):
        self.app = app
        f = tk.Frame(parent, bg=RULE, padx=1, pady=1); f.pack(fill="x", pady=(10, 0))
        inner = tk.Frame(f, bg=BG, padx=10, pady=8); inner.pack(fill="both")
        self.title = tk.Label(inner, font=("Consolas", 10, "bold"), fg=FG, bg=BG, anchor="w"); self.title.pack(fill="x")
        self.info = tk.Label(inner, font=("Consolas", 9), fg=FG2, bg=BG, anchor="w", justify="left", wraplength=350)
        self.info.pack(fill="x", pady=(2, 6))
        self.cv = tk.Canvas(inner, width=330, height=46, bg=BG, highlightthickness=0); self.cv.pack(anchor="w")
        row = tk.Frame(inner, bg=BG); row.pack(fill="x", pady=(8, 0))
        self.open_btn = app.button(row, "[open in 3d]", lambda: app.open_location(app.map.current()), primary=True)
        self.open_btn.pack(side="left")
        self.map_btn = app.button(row, "[locations map]", lambda: app.open("/viewer/map.html"))
        self.map_btn.pack(side="left", padx=(6, 0))

    def show(self, l):
        self.cv.delete("all")
        if not l:
            self.title.configure(text="no location selected")
            self.info.configure(text="click one on the map or in the list")
            self.open_btn.configure(state="disabled")
            return
        num, rest = split_name(l["name"])
        self.title.configure(text=f"{num + ' · ' if num else ''}{(l.get('title') or rest).upper()}")
        size = (f"route {l['corridor']['length_m'] / 1000:.1f} km" if l.get("corridor")
                else f"{2 * l['half_size_m'] / 1000:g} × {2 * l['half_size_m'] / 1000:g} km")
        st = l.get("stats") or {}
        built = f"built {fmt_day(st.get('built'))}" if l.get("built") else "not built yet"
        last = f" · last log {fmt_day(st.get('last'))}" if st.get("last") else ""
        self.info.configure(text=f"{size} · terrain {l.get('resolution_m', '?'):g} m · {built}{last}")
        self.open_btn.configure(state="normal", text="[open in 3d]" if l.get("built") else "[build on the map]")
        # bar chart: real vs sim logs (bars scaled to the location with the most logs)
        most = max([1] + [max(x["stats"]["real"], x["stats"]["sim"]) for x in self.app.map.locs if x.get("stats")])
        for i, (k, label, col) in enumerate((("real", "REAL", ACC), ("sim", "SIM", "#8fb3ff"))):
            y = 4 + i * 22
            n, secs = st.get(k, 0), st.get(k + "_s", 0)
            self.cv.create_text(0, y + 7, text=label, anchor="w", fill=FG2, font=("Consolas", 8, "bold"))
            self.cv.create_rectangle(40, y, 40 + self.BAR_W, y + 14, fill=BG2, outline="")
            if n:
                self.cv.create_rectangle(40, y, 40 + max(3, self.BAR_W * n / most), y + 14, fill=col, outline="")
            self.cv.create_text(48 + self.BAR_W, y + 7, anchor="w", fill=FG if n else GREY, font=("Consolas", 9),
                                text=f"{n}  {fmt_dur(secs)}" if n else "0")


# ---------------------------------------------------------------- Switzerland map
# swisstopo grey map + FOCA drone restrictions (the same tiles as the locations map page), downloaded once
# at zoom 8, cropped to Switzerland and kept in cache/launcher/ so the map also shows offline.

MAP_DIR = ROOT / "cache" / "launcher"
BBOX = (5.85, 45.75, 10.6, 47.9)                    # lon/lat west, south, east, north
Z = 8
MAP_W = 600                                          # canvas width (px)
TILE_URL = "https://wmts.geo.admin.ch/1.0.0/{layer}/default/current/3857/{z}/{x}/{y}.{ext}"


def merc(lon, lat, z=Z):
    """lon/lat -> global pixel coordinates at zoom z (Web Mercator, 256 px tiles)."""
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    la = math.radians(lat)
    y = (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n
    return x, y


class SwissMap:
    def __init__(self, app: "Launcher", parent):
        self.app = app
        x0, y0 = merc(BBOX[0], BBOX[3]); x1, y1 = merc(BBOX[2], BBOX[1])
        self.org, self.scale = (x0, y0), MAP_W / (x1 - x0)
        self.h = round((y1 - y0) * self.scale)
        f = tk.Frame(parent, bg=BG); f.pack(side="left", anchor="n")
        self.cv = tk.Canvas(f, width=MAP_W, height=self.h, bg=BG2, highlightthickness=1, highlightbackground=RULE)
        self.cv.pack()
        row = tk.Frame(f, bg=BG); row.pack(fill="x", pady=(6, 0))
        self.zones = tk.BooleanVar(value=app.cfg.get("map_zones", True))
        cb = tk.Checkbutton(row, text="drone zones (FOCA)", variable=self.zones, command=self.draw, font=SANS, fg=FG, bg=BG,
                            selectcolor=BG2, activebackground=BG, activeforeground=FG, bd=0, highlightthickness=0)
        cb.pack(side="left")
        Tip(cb, "Official drone restrictions from FOCA (map.geo.admin.ch). An overview only: check the locations map "
                "for the details before flying.")
        up = app.button(row, "[update map]", lambda: self.download(force=True), small=True); up.pack(side="right")
        Tip(up, "Download the map and the latest drone zones again (needs internet; kept for offline use).")
        self.hint = "click = select · double-click = open"
        self.info = tk.Label(row, text=self.hint, font=SANS, fg=FG2, bg=BG); self.info.pack(side="right", padx=(0, 10))
        self.imgs = {}
        self.locs = []
        self.selected = app.cfg.get("selected")
        if not all((MAP_DIR / f"ch_{k}_{MAP_W}.png").exists() for k in ("base", "zones")):
            self.download()

    def px(self, lat, lon):
        x, y = merc(lon, lat)
        return (x - self.org[0]) * self.scale, (y - self.org[1]) * self.scale

    def current(self):
        return next((l for l in self.locs if l["name"] == self.selected), None)

    # ---------------------------------------------------------- data
    def load_locations(self):
        try:
            sys.path.insert(0, str(ROOT))
            sp = ROOT / ".venv" / "Lib" / "site-packages"   # in case this window was started without the .venv
            if sp.exists() and str(sp) not in sys.path:
                sys.path.append(str(sp))
            from fpv3d.locations import list_locations
            self.locs = sorted((l for l in list_locations(ROOT / "scenes") if "center" in l), key=lambda l: l["name"])
        except Exception as ex:                     # missing libraries etc.: the map still works without them
            self.locs = []
            self.info.configure(text=f"locations not shown ({ex.__class__.__name__})")
        if self.selected not in [l["name"] for l in self.locs]:
            self.selected = self.locs[0]["name"] if self.locs else None

    def download(self, force=False):
        self.cv.delete("all")
        self.cv.create_text(MAP_W / 2, self.h / 2, text="downloading the map of Switzerland…", fill=FG2, font=MONO)

        def work():
            try:
                from PIL import Image
                import io
                x0, y0 = self.org
                tx0, ty0 = int(x0 // 256), int(y0 // 256)
                x1, y1 = merc(BBOX[2], BBOX[1])
                tx1, ty1 = int(x1 // 256), int(y1 // 256)
                out = {}
                for key, layer, ext in (("base", "ch.swisstopo.pixelkarte-grau", "jpeg"),
                                        ("zones", "ch.bazl.einschraenkungen-drohnen", "png")):
                    mosaic = Image.new("RGBA", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (0, 0, 0, 0))
                    for tx in range(tx0, tx1 + 1):
                        for ty in range(ty0, ty1 + 1):
                            url = TILE_URL.format(layer=layer, z=Z, x=tx, y=ty, ext=ext)
                            req = urllib.request.Request(url, headers={"User-Agent": "alpline-launcher"})
                            try:
                                data = urllib.request.urlopen(req, timeout=10).read()
                            except urllib.error.HTTPError:
                                continue            # no tile there (outside the data)
                            mosaic.paste(Image.open(io.BytesIO(data)).convert("RGBA"), ((tx - tx0) * 256, (ty - ty0) * 256))
                    crop = mosaic.crop((round(x0 - tx0 * 256), round(y0 - ty0 * 256),
                                        round(x1 - tx0 * 256), round(y1 - ty0 * 256))).resize((MAP_W, self.h), Image.LANCZOS)
                    out[key] = crop
                base = out["base"].convert("RGB").convert("RGBA")
                MAP_DIR.mkdir(parents=True, exist_ok=True)
                base.save(MAP_DIR / f"ch_base_{MAP_W}.png")
                Image.alpha_composite(base, out["zones"]).save(MAP_DIR / f"ch_zones_{MAP_W}.png")
                self.app.root.after(0, lambda: (self.imgs.clear(), self.draw(), self.info.configure(text=self.hint)))
            except Exception as ex:
                msg = f"map not downloaded ({ex.__class__.__name__}): needs internet once"
                self.app.root.after(0, lambda: (self.draw(), self.info.configure(text=msg)))
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- drawing
    def draw(self, save=True):
        if save:
            self.app.cfg["map_zones"] = self.zones.get(); self.app.save()
        self.app.cfg["selected"] = self.selected
        cv = self.cv
        cv.delete("all")
        key = "zones" if self.zones.get() else "base"
        p = MAP_DIR / f"ch_{key}_{MAP_W}.png"
        if p.exists():
            try:
                self.imgs[key] = self.imgs.get(key) or tk.PhotoImage(file=str(p))
                cv.create_image(0, 0, image=self.imgs[key], anchor="nw")
            except tk.TclError:
                pass
        else:
            cv.create_text(MAP_W / 2, 20, text="no map yet: [update map] when online", fill=FG2, font=MONO)
        labels = []
        for l in sorted(self.locs, key=lambda l: not l.get("built")):   # built ones get their name first
            col = ACC if l.get("built") else "#8a93a0"
            tag = f"loc_{l['name']}"
            if l.get("corridor"):
                pts = [c for la, lo in l["corridor"]["points"] for c in self.px(la, lo)]
                w = max(3, 2 * l["corridor"]["width_m"] / 611 * self.scale)
                cv.create_line(*pts, fill="#000", width=w + 2, tags=tag)
                cv.create_line(*pts, fill=col, width=w, tags=tag)
                lx, ly = pts[-2], pts[-1]
            else:
                cx, cy = self.px(*l["center"])
                # metres -> px: 1 px at zoom 8 is ~611 m / cos(lat) on the ground... at scale `self.scale`
                r = max(4, l["half_size_m"] / (611.5 * math.cos(math.radians(l["center"][0]))) * self.scale)
                cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline="#000", width=3, tags=tag)
                cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline=col, width=2,
                                    fill=col if l.get("built") else "", stipple="gray50" if l.get("built") else "", tags=tag)
                lx, ly = cx + r, cy - r
            label = split_name(l["name"])[0] or l["name"]          # the number on the map, the names are in the list
            if l["name"] == self.selected:                          # selected in the list: a ring around it
                rx, ry = (cx, cy) if not l.get("corridor") else (pts[0], pts[1])
                cv.create_oval(rx - 14, ry - 14, rx + 14, ry + 14, outline="#000", width=4)
                cv.create_oval(rx - 14, ry - 14, rx + 14, ry + 14, outline=ACC, width=2)
            box = (lx + 3, ly - 13, lx + 6 + 7 * len(label), ly + 1)
            if not any(box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3] for o in labels):
                labels.append(box)                  # names that would overlap another one are left out (hover shows them)
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):    # dark halo so the name reads on any background
                    cv.create_text(lx + 4 + dx, ly + dy, text=label, anchor="sw", fill="#000", font=("Consolas", 9, "bold"), tags=tag)
                cv.create_text(lx + 4, ly, text=label, anchor="sw", fill=col, font=("Consolas", 9, "bold"), tags=tag)
            cv.tag_bind(tag, "<Enter>", lambda e, l=l: (self.cv.configure(cursor="hand2"), self.info.configure(
                text=f"{l.get('title') or l['name']}" + ("" if l.get("built") else " (not built)"))))
            cv.tag_bind(tag, "<Leave>", lambda e: (self.cv.configure(cursor=""), self.info.configure(text=self.hint)))
            cv.tag_bind(tag, "<Button-1>", lambda e, l=l: self.app.select(l["name"]))   # click: select (table + card)
            cv.tag_bind(tag, "<Double-Button-1>", lambda e, l=l: self.app.open_location(l))



if __name__ == "__main__":
    root = tk.Tk()
    Launcher(root)
    root.mainloop()
