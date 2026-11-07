"""Alpline (by lieka) launcher: your locations on a map of Switzerland, the drone and radio on USB, phone sharing,
settings. Opens the 3D viewer and the map page.

Double-click Alpline.bat (or the desktop shortcut it can create), or start the installed Alpline app. The window
starts the local server in the chosen mode, opens Alpline windows (or your browser), and stops the server when you
close it. It also tells you whether your locations are ready to use offline at the field.

Packaged app: the same file is Alpline.exe. Alpline windows are Edge (or Chrome) in app mode (fpv3d.paths.window_cmd).
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fpv3d import paths  # noqa: E402  (standard library only)

APP = paths.APP                                      # the program: viewer pages, logo frames, icon
ROOT = paths.DATA                                    # your files: launcher.json, logs, scenes, cache, locations
SETTINGS = ROOT / "launcher.json"
LOG = ROOT / "logs" / "server.log"

# colours of the viewer's dark theme
BG, BG2, BG3, FG, FG2, RULE, ACC = "#07090c", "#10141a", "#171c24", "#f2f5f8", "#a9b4c2", "#2a313c", "#ffd60a"
MONO = ("Consolas", 10)
SANS = ("Segoe UI", 10)
UI = 1.0                                             # screen scaling (1.5 on a 150 % Windows display), set at start


def S(v: float) -> int:
    """pixel size scaled for the screen (fonts in points scale by themselves)"""
    return round(v * UI)


def venv_exe(name: str) -> str:
    """python.exe / pythonw.exe of the project's virtual environment (.venv), where numpy, rasterio, PyYAML...
    are installed. Asked for explicitly: with the Microsoft Store Python, sys.executable inside a venv points
    to the base Python, which does not have those libraries."""
    for d in (APP / ".venv" / "Scripts", APP / ".venv" / "bin", Path(sys.prefix) / "Scripts", Path(sys.prefix) / "bin"):
        for n in (name, name.replace(".exe", ""), "python3" if name.startswith("python.") else name):
            if (d / n).exists():
                return str(d / n)
    exe = Path(sys.executable)
    twin = exe.with_name(name)
    return str(twin if twin.exists() else exe)


def python_exe() -> str:
    """The python that runs the server (console version, no window: CREATE_NO_WINDOW)."""
    return venv_exe("python.exe")


def lan_addresses() -> list:
    """IPv4 addresses of this computer on its local networks, best guess first (fpv3d.netinfo, shared with the server)."""
    try:
        from fpv3d.netinfo import lan_addresses as la
        return la()
    except Exception:
        return []


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
import tkinter.font as tkfont

GREY = "#7d8796"
RULE2 = "#4a5462"                                     # control borders


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
        tk.Label(self.top, text=t, font=SANS, fg=FG, bg=BG3, justify="left", wraplength=S(340), padx=S(8), pady=S(5),
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


def short_day(ts) -> str:
    """'07 Nov' this year, 'Nov 2025' before"""
    t = time.localtime(ts)
    return time.strftime("%d %b" if t.tm_year == time.localtime().tm_year else "%b %Y", t)



class FitLabel(tk.Label):
    """A label that never makes the window grow: it takes the width the layout gives it and cuts its text with '…'
    (the whole text is in the tooltip)."""
    def __init__(self, parent, text="", **kw):
        kw.setdefault("anchor", "w")
        super().__init__(parent, width=1, **kw)
        self.full = ""
        self._font = tkfont.Font(font=self.cget("font"))
        Tip(self, lambda: self.full if self.cget("text") != self.full else "")
        self.bind("<Configure>", lambda e: self._fit())
        self.set(text)

    def set(self, text, **kw):
        self.full = text
        if kw:
            self.configure(**kw)
            if "font" in kw:
                self._font = tkfont.Font(font=self.cget("font"))
        self._fit()

    def _fit(self):
        w = self.winfo_width() - 2 * int(self.cget("padx") or 0) - 4
        t = self.full
        if w > 8 and self._font.measure(t) > w:
            while t and self._font.measure(t + "…") > w:
                t = t[:-1]
            t = t.rstrip() + "…"
        if self.cget("text") != t:
            super().configure(text=t)


class Pill(tk.Frame):
    """Status pill: coloured dot + short text, fixed width (the header never moves)."""
    def __init__(self, parent, chars, tip=None):
        super().__init__(parent, bg=BG, highlightthickness=1, highlightbackground=RULE2)
        self.dot = tk.Canvas(self, width=S(10), height=S(10), bg=BG, highlightthickness=0)
        self.dot.pack(side="left", padx=(S(7), S(4)))
        self.lab = tk.Label(self, font=("Consolas", 9), fg=FG2, bg=BG, width=chars, anchor="w")
        self.lab.pack(side="left", padx=(0, S(6)), pady=S(2))
        if tip:
            Tip(self, tip)

    def set(self, text, color=None):
        n = int(self.lab.cget("width"))
        self.lab.configure(text=text if len(text) <= n else text[:n - 1] + "…")
        self.dot.delete("all")
        r = S(4)
        c = S(5)
        if color:
            self.dot.create_oval(c - r, c - r, c + r, c + r, fill=color, outline="")
        else:
            self.dot.create_oval(c - r, c - r, c + r, c + r, outline=FG2)


# rail pages: key, label, tooltip
PAGES = (("map", "map", "Your locations on the map of Switzerland"),
         ("drone", "drone", "Drone and radio on USB: download the blackbox, start a live flight"),
         ("phone", "phone", "Open Alpline on your phone (same Wi-Fi or the phone's hotspot)"),
         ("disk", "disk", "Disk space and clean-up"),
         ("settings", "settings", "Full / Lite, where pages open, desktop shortcut, your files"))


def rail_icon(cv, key, col):
    """Small line icons for the rail (drawn, so they stay sharp at any screen scaling)."""
    cv.delete("all")
    w = lambda *a: [S(v) for v in a]
    lw = max(1, S(1.6))
    if key == "map":
        cv.create_line(*w(3, 5, 9, 3, 15, 5, 21, 3, 21, 15, 15, 17, 9, 15, 3, 17, 3, 5), fill=col, width=lw)
        cv.create_line(*w(9, 3, 9, 15), fill=col, width=lw); cv.create_line(*w(15, 5, 15, 17), fill=col, width=lw)
    elif key == "drone":
        cv.create_line(*w(6, 4, 18, 16), fill=col, width=lw); cv.create_line(*w(18, 4, 6, 16), fill=col, width=lw)
        for x, y in ((5, 3), (19, 3), (5, 17), (19, 17)):
            cv.create_oval(*w(x - 3, y - 2, x + 3, y + 2), outline=col, width=lw)
        cv.create_rectangle(*w(10, 8, 14, 12), outline=col, width=lw)
    elif key == "phone":
        cv.create_rectangle(*w(7, 1, 17, 19), outline=col, width=lw); cv.create_line(*w(10, 16, 14, 16), fill=col, width=lw)
    elif key == "disk":
        for y in (3, 8, 13):
            cv.create_rectangle(*w(4, y, 20, y + 4), outline=col, width=lw)
        cv.create_line(*w(16, 5, 17, 5), fill=col, width=lw)
    elif key == "settings":
        for y, x in ((4, 15), (10, 8), (16, 13)):
            cv.create_line(*w(3, y, 21, y), fill=col, width=lw)
            cv.create_rectangle(*w(x - 2, y - 2, x + 2, y + 2), fill=BG, outline=col, width=lw)


class Launcher:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_settings()
        self.proc: subprocess.Popen | None = None
        self.windows: list = []                             # Alpline windows opened from here (closed with the launcher)
        self._win_ok = None
        self.running_mode = None
        self.running_share = False
        self.port = None
        self.online = None
        self.devices: dict = {}                             # serial port -> what is plugged in there (drone / radio / busy)
        self.bb_proc = None                                 # blackbox download running
        self._last_refresh = time.monotonic()
        root.title("Alpline by lieka")
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        try:                                       # window / taskbar icon
            self.icon = tk.PhotoImage(file=str(APP / "viewer" / "brand" / "icon-64.png"))
            root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        self.style()
        self.mode = tk.StringVar(value=self.cfg.get("mode", "full"))

        # the window: rail | (header / page). Everything sits in fixed slots; only the page area grows.
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        self.rail = tk.Frame(root, bg=BG, width=S(68))
        self.rail.grid(row=0, column=0, sticky="ns"); self.rail.grid_propagate(False)
        tk.Frame(root, bg=RULE, width=1).grid(row=0, column=0, sticky="nse")
        body = tk.Frame(root, bg=BG)
        body.grid(row=0, column=1, sticky="nsew")
        body.columnconfigure(0, weight=1); body.rowconfigure(2, weight=1)

        # ---- header
        top = tk.Frame(body, bg=BG, height=S(52))
        top.grid(row=0, column=0, sticky="ew"); top.pack_propagate(False)
        tk.Frame(body, bg=RULE, height=1).grid(row=1, column=0, sticky="ew")
        self.logo = LogoAnim(root, top, S(28))
        if self.logo.label:
            self.logo.label.pack_configure(padx=(S(14), S(8)))
        tk.Label(top, text="ALPLINE", font=("Consolas", 15, "bold"), fg=FG, bg=BG).pack(side="left",
                 padx=(0 if self.logo.label else S(14), 0))
        tk.Label(top, text="by lieka", font=("Consolas", 9), fg=FG2, bg=BG).pack(side="left", padx=(S(6), 0), pady=(S(5), 0))
        b = self.button(top, "[locations map]", lambda: self.open("/viewer/map.html"))
        b.pack(side="right", padx=(S(6), S(14)))
        Tip(b, "The map page in Alpline: search places, create and build locations, drone zones.")
        b = self.button(top, "[3d viewer]", lambda: self.open_location(self.map.current()) if self.map.current()
                        and self.map.current().get("built") else self.open("/viewer/"), primary=True)
        b.pack(side="right")
        Tip(b, "Open the selected location in 3D (Enter or double-click does the same).")
        self.stop_btn = self.button(top, "[stop]", self.stop, small=True)
        self.stop_btn.pack(side="right", padx=(S(4), S(14)))
        Tip(self.stop_btn, "Stop the local server (closing this window does it too).")
        self.server_pill = Pill(top, 22, lambda: "The local server shows the 3D viewer and the map pages. It starts when "
                                                 "you open one and stops with this window.")
        self.server_pill.pack(side="right")
        self.net_pill = Pill(top, 7, lambda: "Internet is used for the map background, new downloads and place search. "
                                             "Built locations open in 3D without it.")
        self.net_pill.pack(side="right", padx=(0, S(8)))
        self.net_pill.set("…", None)

        # ---- pages (stacked in one cell, raised one at a time)
        stage = tk.Frame(body, bg=BG)
        stage.grid(row=2, column=0, sticky="nsew")
        stage.rowconfigure(0, weight=1); stage.columnconfigure(0, weight=1)
        self.pages = {}
        for key, *_ in PAGES:
            f = tk.Frame(stage, bg=BG)
            f.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = f
        self.map = SwissMap(self, self.pages["map"])
        self.build_drone_page(self.pages["drone"])
        self.build_phone_page(self.pages["phone"])
        self.build_disk_page(self.pages["disk"])
        self.build_settings_page(self.pages["settings"])

        # ---- rail
        self.rail_items = {}
        tk.Frame(self.rail, bg=BG, height=S(8)).pack()
        for key, label, tip in PAGES:
            if key == "disk":
                tk.Frame(self.rail, bg=BG).pack(fill="y", expand=True)       # disk + settings at the bottom
            it = tk.Frame(self.rail, bg=BG, cursor="hand2")
            it.pack(fill="x", pady=S(2))
            bar = tk.Frame(it, bg=BG, width=S(3)); bar.pack(side="left", fill="y")
            inner = tk.Frame(it, bg=BG); inner.pack(side="left", fill="x", expand=True, pady=S(6))
            cv = tk.Canvas(inner, width=S(24), height=S(20), bg=BG, highlightthickness=0); cv.pack()
            lab = tk.Label(inner, text=label, font=("Consolas", 8), fg=FG2, bg=BG); lab.pack()
            for w in (it, inner, cv, lab):
                w.bind("<Button-1>", lambda e, k=key: self.show_page(k))
            Tip(it, tip)
            self.rail_items[key] = dict(frame=it, bar=bar, inner=inner, cv=cv, lab=lab, badge=None)
        tk.Frame(self.rail, bg=BG, height=S(8)).pack()

        # ---- toast: messages float over the bottom right corner, nothing else moves
        self.toast = tk.Label(root, font=SANS, fg=ACC, bg=BG, padx=S(10), pady=S(6), highlightthickness=1,
                              highlightbackground=ACC, justify="left", wraplength=S(420), cursor="hand2")
        self.toast.bind("<Button-1>", lambda e: self.toast.place_forget())
        self._toast_job = None

        # ---- size: resizable, remembered, never smaller than the layout needs
        root.minsize(S(980), S(600))
        g = self.cfg.get("geometry")
        if g and re.match(r"^\d+x\d+[+-]-?\d+[+-]-?\d+$", g):
            w, h = map(int, g.split("+")[0].split("x"))
            root.geometry(g if w <= root.winfo_screenwidth() and h <= root.winfo_screenheight() else f"{S(1120)}x{S(700)}")
        else:
            root.geometry(f"{S(1120)}x{S(700)}")

        # ---- keys + refresh when the window comes back to the front (replaces [check])
        root.bind("<Control-f>", lambda e: self.focus_filter())
        root.bind("<Control-F>", lambda e: self.focus_filter())
        root.bind("<FocusIn>", self.on_focus)
        root.bind("<Up>", lambda e: self.move_selection(-1, e))
        root.bind("<Down>", lambda e: self.move_selection(1, e))
        root.bind("<Return>", lambda e: self.on_return(e))

        self.show_page(self.cfg.get("page", "map") if self.cfg.get("page") in self.pages else "map")
        self.set_mode(self.mode.get(), save=False)
        self.check_offline()
        self.start_device_watch()
        if self.cfg.get("share") and os.name == "nt":         # sharing was left on: check the phone can get in
            root.after(1200, lambda: self.check_phone_access(ask=True))

    # ------------------------------------------------------------ widgets
    @staticmethod
    def brand_image(name, px):
        """viewer/brand/<name>-<size>.png closest to px (pre-rendered sizes), or None"""
        sizes = sorted(int(p.stem.rsplit("-", 1)[1]) for p in (APP / "viewer" / "brand").glob(f"{name}-*.png")
                       if p.stem.rsplit("-", 1)[1].isdigit())
        if not sizes:
            return None
        best = min(sizes, key=lambda s: abs(s - px))
        try:
            return tk.PhotoImage(file=str(APP / "viewer" / "brand" / f"{name}-{best}.png"))
        except tk.TclError:
            return None

    def style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("L.Treeview", background=BG2, fieldbackground=BG2, foreground=FG, font=MONO, rowheight=S(21),
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


    # ------------------------------------------------------------ mode
    MODE_TEXT = {"full": "Full: the whole 3D at full quality, redrawn continuously. New locations: 2 m terrain, 2 m photo, "
                         "10 m signal grid, 3D buildings.",
                 "lite": "Lite: for slower computers. 3D redrawn only when something changes, lighter mesh. New locations: "
                         "5 m terrain, lighter photo, 20 m signal grid, no 3D buildings."}

    def set_mode(self, m, save=True):
        self.mode.set(m)
        for k, b in self.mode_btns.items():
            on = k == m
            b.configure(bg=ACC if on else BG2, fg="#000" if on else FG2, activebackground=ACC if on else BG3)
        self.mode_info.configure(text=self.MODE_TEXT[m])
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
        self.logo.busy(True)
        try:
            return self._start()
        finally:
            self.logo.busy(False)

    def _start(self) -> bool:
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
        args = paths.cli_cmd(unbuffered=True) + ["serve", "--port", str(port), "--no-browser"]
        if self.mode.get() == "lite":
            args.append("--lite")
        if self.cfg.get("share"):
            args.append("--lan")
        LOG.parent.mkdir(exist_ok=True)
        log = open(LOG, "w", encoding="utf-8", errors="replace")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8", "FPV3D_PIN": self.pin()})
        self.port, self.running_mode, self.running_share = port, self.mode.get(), bool(self.cfg.get("share"))
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
                for _ in range(5):                  # keep the window (and the spinning logo) alive meanwhile
                    self.root.update(); time.sleep(0.05)
        self.refresh_status()
        return True

    def open(self, path):
        if not self.server_alive() or self.running_mode != self.mode.get() or self.running_share != bool(self.cfg.get("share")):
            self.busy_status("starting…")
            if not self.start():
                return
        self.open_url(f"http://127.0.0.1:{self.port}{path}")

    # ------------------------------------------------------------ Alpline windows (or the browser)
    def window_ok(self) -> bool:
        """Edge or Chrome is there to open Alpline windows (app mode)."""
        if self._win_ok is None:
            self._win_ok = paths.app_browser() is not None
        return self._win_ok

    def open_url(self, url):
        cmd = paths.window_cmd(url) if self.cfg.get("open_in", "window") == "window" else None
        if cmd:
            try:
                self.windows = [w for w in self.windows if w.poll() is None]
                w = subprocess.Popen(cmd, cwd=str(ROOT))
                self.windows.append(w)
                self.say("opening an Alpline window…")
                self.root.after(5000, lambda: self.window_check(w, url))
                return
            except OSError:
                pass
        webbrowser.open(url)
        self.say("opened in your browser · keep this window open")

    def window_check(self, w, url):
        """Edge hands a second window to the one already open and stops at once (code 0): fine. Any other early
        stop means the window did not open: show the page in the browser instead and say so."""
        code = w.poll()
        if code is None or code == 0:
            self.say("opened in an Alpline window · keep this window open")
        else:
            try:
                with open(ROOT / "logs" / "window.log", "a", encoding="utf-8") as f:
                    f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + f"window ({paths.app_browser()}) ended with code {code}\n")
            except OSError:
                pass
            webbrowser.open(url)
            self.say("the Alpline window did not open (see logs/window.log): opened in the browser")

    def stop(self):
        if self.server_alive():
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc, self.running_mode, self.running_share = None, None, False
        self.refresh_status()

    # ------------------------------------------------------------ phone (share on the network)
    def pin(self) -> str:
        """6-digit PIN the phone needs once (kept in launcher.json so the phone's home-screen icon keeps working)."""
        if not str(self.cfg.get("pin", "")).isdigit():
            import secrets
            self.cfg["pin"] = f"{secrets.randbelow(10 ** 6):06d}"; self.save()
        return str(self.cfg["pin"])

    def https_ready(self) -> bool:
        """The secure page for the phone needs the 'cryptography' library in .venv; offer to install it once."""
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if paths.FROZEN:
            return True                                   # the packaged app comes with it
        ok = subprocess.run([python_exe(), "-c", "import cryptography"], capture_output=True, creationflags=flags).returncode == 0
        if ok or self.cfg.get("no_https"):
            return ok
        from tkinter import messagebox
        if not messagebox.askyesno("Alpline: phone", "For a secure (https) page on the phone, Alpline needs one more library "
                                   "(cryptography, about 5 MB). It lets the phone keep its screen on during a live flight.\n\n"
                                   "Install it now? (needs internet)", parent=self.root):
            self.cfg["no_https"] = True; self.save()
            return False
        self.busy_status("installing cryptography…")
        r = subprocess.run([python_exe(), "-m", "pip", "install", "cryptography==50.0.2"], capture_output=True, text=True,
                           creationflags=flags)
        if r.returncode != 0:
            self.say("could not install cryptography: the phone uses http")
            return False
        return True

    def toggle_share(self):
        self.cfg["share"] = not self.cfg.get("share")
        self.save()
        if self.cfg["share"]:
            self.https_ready()
            if not self.server_alive() or self.running_share != True:
                self.busy_status("starting…")
                if not self.start():
                    return
            if os.name == "nt":
                self.check_phone_access(ask=True)
        elif self.server_alive():
            self.start()                          # back to this computer only
        self.refresh_status()

    # Windows blocks connections from other devices unless (1) the firewall lets them in and (2) the Wi-Fi is a
    # "Private" network (on "Public" networks Windows refuses them, whatever the firewall says for Private).
    RULE = "Alpline (phone)"

    def ps(self, cmd: str, timeout=30) -> str:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd], capture_output=True,
                           text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=timeout)
        return (r.stdout or "").strip()

    # what can stop a phone: written to logs/phone_check.txt so it can be read when something doesn't work
    CHECK = r"""
$r = [ordered]@{}
$r.nets = @(Get-NetConnectionProfile | ForEach-Object { @{name=$_.Name; alias=$_.InterfaceAlias; category=[string]$_.NetworkCategory} })
$r.ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object { "$($_.InterfaceAlias) $($_.IPAddress)" })
$a = Get-NetFirewallRule -DisplayName 'Alpline (phone)' -ErrorAction SilentlyContinue
$r.rule = @($a | ForEach-Object { @{enabled=[string]$_.Enabled; profile=[string]$_.Profile; action=[string]$_.Action; ports=(@($_ | Get-NetFirewallPortFilter).LocalPort -join ',')} })
$r.pyblock = @(Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue | Where-Object { $_.Program -like '*python*' } | ForEach-Object {
  $x = $_ | Get-NetFirewallRule; @{name=$x.DisplayName; dir=[string]$x.Direction; action=[string]$x.Action; enabled=[string]$x.Enabled; profile=[string]$x.Profile; program=$_.Program} })
$r.fw = @(Get-NetFirewallProfile -ErrorAction SilentlyContinue | ForEach-Object { @{name=$_.Name; enabled=[string]$_.Enabled; inbound=[string]$_.DefaultInboundAction; local=[string]$_.AllowLocalFirewallRules} })
$r | ConvertTo-Json -Depth 4 -Compress
"""

    def check_phone_access(self, ask=False):
        self.logo.busy(True)

        def work():
            try:
                work_()
            finally:
                self.root.after(0, lambda: self.logo.busy(False))

        def work_():
            try:
                d = json.loads(self.ps(self.CHECK) or "{}")
            except Exception as ex:
                return self.root.after(0, lambda n=ex.__class__.__name__: self.say(f"could not check the network ({n})"))
            try:
                (ROOT / "logs").mkdir(exist_ok=True)
                (ROOT / "logs" / "phone_check.txt").write_text(json.dumps(d, indent=2), encoding="utf-8")
            except OSError:
                pass
            self.root.after(0, lambda: self.phone_access_result(d, ask))
        threading.Thread(target=work, daemon=True).start()

    def phone_access_result(self, d, ask):
        from tkinter import messagebox
        lst = lambda v: v if isinstance(v, list) else ([v] if v else [])
        nets, rules, py, fw = lst(d.get("nets")), lst(d.get("rule")), lst(d.get("pyblock")), lst(d.get("fw"))
        public = [n for n in nets if n.get("category") == "Public"]
        rule_ok = any(r.get("enabled") == "True" and r.get("action") == "Allow" and "8443" in str(r.get("ports", "")) for r in rules)
        blocks = [b for b in py if b.get("dir") == "Inbound" and b.get("action") == "Block" and b.get("enabled") == "True"]
        managed = any(f.get("local") == "False" for f in fw)          # company PCs: local rules are ignored
        problems = []
        if not rule_ok:
            problems.append("the Windows firewall has no rule letting the phone in")
        if blocks:
            problems.append(f"{len(blocks)} firewall rule(s) block Python (often created when the 'allow access' "
                            "question was closed or answered 'cancel')")
        if public:
            problems.append("your network " + ", ".join(f"{n.get('name')} ({n.get('alias')})" for n in public)
                            + " is set to Public")
        if managed:
            problems.append("this PC's firewall is managed by an organisation (local rules are ignored)")
        if not problems:
            self.say("phone access: ok · if it still doesn't load, see logs/phone_check.txt")
            return
        if not ask or (managed and len(problems) == 1):
            self.say("phone access: " + "; ".join(problems))
            return
        fix = ("The phone can't reach this computer:\n• " + "\n• ".join(problems) + "\n\n"
               "Fix it now? Windows asks for administrator permission once. This will:\n"
               "• allow incoming connections to Alpline (ports 8000-8019 and 8443-8462 only)\n"
               + ("• switch off the rules that block Python\n" if blocks else "")
               + ("• set " + ", ".join(n.get("name", "?") for n in public) + " to Private "
                  "(fine for your home Wi-Fi or your own phone hotspot)\n" if public else "")
               + "\nClick [phone] again later to stop sharing.")
        if not messagebox.askyesno("Alpline: phone access", fix, parent=self.root):
            self.say("phone access not fixed: the phone won't load the page")
            return
        log = ROOT / "logs" / "phone_fix.txt"
        cmds = [f"Start-Transcript -Path '{log}' -Force | Out-Null",
                f"Get-NetFirewallRule -DisplayName '{self.RULE}' -ErrorAction SilentlyContinue | Remove-NetFirewallRule",
                f"New-NetFirewallRule -DisplayName '{self.RULE}' -Direction Inbound -Action Allow -Protocol TCP "
                "-LocalPort 8000-8019,8443-8462 -Profile Any | Out-Null"]
        for b in blocks:
            cmds.append(f"Get-NetFirewallRule -DisplayName '{b.get('name')}' -ErrorAction SilentlyContinue | "
                        "Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' } | Disable-NetFirewallRule")
        for n in public:
            cmds.append(f"Set-NetConnectionProfile -InterfaceAlias '{n.get('alias')}' -NetworkCategory Private")
        cmds.append("Stop-Transcript | Out-Null")
        import base64
        enc = base64.b64encode("; ".join(cmds).encode("utf-16-le")).decode()   # no quoting problems

        def run():
            try:                                  # one elevated PowerShell (UAC prompt), then check again
                self.ps("Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
                        f"-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{enc}'", timeout=180)
            except Exception:
                pass
            self.root.after(0, lambda: self.check_phone_access(ask=False))
        self.say("Windows will ask for permission…")
        threading.Thread(target=run, daemon=True).start()

    def share_info(self) -> dict:
        try:
            return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/share", timeout=1).read())
        except Exception:
            return {}

    def show_qr(self):
        if self.server_alive():
            self.open_url(f"http://127.0.0.1:{self.port}/viewer/share.html")


    def refresh_status(self):
        if not hasattr(self, "server_pill"):
            return
        on = bool(self.cfg.get("share"))
        self.share_btn.configure(bg=ACC if on else BG2, fg="#000" if on else FG, activebackground=ACC if on else BG3,
                                 text="[share on my network: on]" if on else "[share on my network: off]")
        sharing = self.server_alive() and self.running_share
        if sharing:
            ip = (lan_addresses() or ["?"])[0]
            https = self.share_info().get("https")
            self.set_entry("addr", f"{'https' if https else 'http'}://{ip}:{self.port + (443 if https else 0)}")
            self.set_entry("pin", self.pin())
            self.set_entry("state", "shared · the phone can connect")
        else:
            self.set_entry("addr", "–")
            self.set_entry("pin", self.pin() if on else "–")
            self.set_entry("state", "starts sharing when the server starts" if on else "this computer only")
        self.qr_btn.configure(state="normal" if sharing else "disabled")
        self.draw_badge("phone")
        if self.server_alive():
            note = "" if self.running_mode == self.mode.get() else f" →{self.mode.get()}"
            self.server_pill.set(f"server {self.running_mode} :{self.port}{note}", "#3ddc84")
            self.stop_btn.configure(state="normal")
        else:
            self.server_pill.set(f"server off · {self.mode.get()}", None)
            self.stop_btn.configure(state="disabled")

    def quit(self):
        for w in self.windows:                              # the windows show nothing without the server
            if w.poll() is None:
                w.terminate()
        if self.bb_proc is not None and self.bb_proc.poll() is None:
            self.bb_proc.terminate()
        try:
            if self.root.state() == "normal":
                self.cfg["geometry"] = self.root.geometry()
        except tk.TclError:
            pass
        self.save()
        self.stop()
        self.root.destroy()

    # ------------------------------------------------------------ locations, internet
    def check_offline(self, quiet=False):
        self.map.load_locations()
        locs = self.map.locs
        for l in locs:
            l["stats"] = flight_stats(l["name"])
        self.map.table.fill(locs)
        self.map.draw()
        self.map.card.show(self.map.current())
        built = [l for l in locs if l.get("built")]
        self.map.list_foot.set(f"{len(built)}/{len(locs)} built" + (" · ready offline" if built and len(built) == len(locs)
                                                                    else " · built ones work offline" if built else ""))
        self.show_devices()
        if quiet and self.online is not None:
            return

        def net():
            try:
                urllib.request.urlopen("https://wmts.geo.admin.ch/", timeout=3)
                ok = True
            except urllib.error.HTTPError:
                ok = True                       # the server answered: we are online
            except Exception:
                ok = False
            self.online = ok
            self.root.after(0, lambda: self.net_pill.set("online" if ok else "offline", "#3ddc84" if ok else "#ff9f43"))
        threading.Thread(target=net, daemon=True).start()

    def select(self, name):
        """one location chosen (map click or table row): ring on the map, row in the table, details card"""
        self.map.selected = name
        self.map.draw(save=False)
        self.map.table.select(name)
        self.map.card.show(self.map.current())
        self.show_devices()

    def open_location(self, l):
        if l:
            self.open(f"/viewer/?scene={l['name']}" if l.get("built") else "/viewer/map.html")

    # ------------------------------------------------------------ pages
    def show_page(self, key):
        self.pages[key].tkraise()
        for k, it in self.rail_items.items():
            on = k == key
            bg = BG3 if on else BG
            for w in (it["frame"], it["inner"], it["cv"], it["lab"]):
                w.configure(bg=bg)
            it["bar"].configure(bg=ACC if on else bg)
            it["lab"].configure(fg=ACC if on else FG2)
            rail_icon(it["cv"], k, ACC if on else FG2)
            self.draw_badge(k)
        self.cfg["page"] = key
        if key == "disk":
            self.measure_disk()
        if key == "phone":
            self.refresh_status()

    def draw_badge(self, key):
        """A dot on a rail icon: drone / radio plugged in, phone sharing on."""
        it = self.rail_items.get(key)
        if not it:
            return
        it["cv"].delete("badge")
        col = None
        if key == "drone":
            kinds = {d.get("kind") for d in self.devices.values()}
            col = "#3ddc84" if "drone" in kinds else (ACC if "radio" in kinds else None)
        elif key == "phone" and self.cfg.get("share"):
            col = ACC
        if col:
            r = S(3.5)
            x, y = S(21), S(3.5)
            it["cv"].create_oval(x - r, y - r, x + r, y + r, fill=col, outline=BG, width=S(1.5), tags="badge")

    def page_frame(self, parent, title, intro=None):
        """Common page layout: a column of fixed width on the left, with a title and an optional intro."""
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True, padx=S(24), pady=S(18))
        col = tk.Frame(outer, bg=BG, width=S(660))
        col.pack(side="left", fill="y"); col.pack_propagate(False)
        self.section(title, col)
        if intro:
            tk.Label(col, text=intro, font=SANS, fg=FG2, bg=BG, justify="left", anchor="w", wraplength=S(640)).pack(fill="x", pady=(0, S(12)))
        return col

    def say(self, text, kind="info"):
        """A message for a few seconds over the bottom right corner (errors stay longer; click to close)."""
        col = {"info": ACC, "ok": "#3ddc84", "bad": "#ff6b6b"}.get(kind, ACC)
        self.toast.configure(text=text, fg=col, highlightbackground=col)
        self.toast.place(relx=1, rely=0, x=-S(16), y=S(66), anchor="ne")      # top right of the page: free on every page
        self.toast.lift()
        if self._toast_job:
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(15000 if kind == "bad" else 6000, self.toast.place_forget)

    def busy_status(self, text):
        self.server_pill.set(text, ACC)
        self.root.update()

    # ------------------------------------------------------------ keys
    def focus_filter(self):
        self.show_page("map")
        self.map.list_open(True)
        self.map.filter.focus_set()
        self.map.filter.select_range(0, "end")
        return "break"

    def on_focus(self, e):
        if e.widget is not self.root or time.monotonic() - self._last_refresh < 8:
            return
        self._last_refresh = time.monotonic()
        self.check_offline(quiet=True)

    def move_selection(self, step, e):
        if isinstance(e.widget, (tk.Entry, ttk.Treeview, tk.Text)) or self.cfg.get("page") != "map":
            return
        self.map.table.step(step)

    def on_return(self, e):
        if isinstance(e.widget, (tk.Entry, ttk.Treeview, tk.Text, tk.Button)) or self.cfg.get("page") != "map":
            return
        self.open_location(self.map.current())

    # ------------------------------------------------------------ drone page (USB)
    def build_drone_page(self, parent):
        col = self.page_frame(parent, "DRONE ON USB",
                              "Plug the drone in with its USB cable (no battery needed). Alpline finds a Betaflight flight "
                              "controller by itself and can copy its blackbox: every flight with GPS is added to the location "
                              "where it took off. Close Betaflight Configurator first (it holds the port).")
        self.drone_lab = FitLabel(col, font=("Consolas", 10, "bold"), fg=FG2, bg=BG)
        self.drone_lab.pack(fill="x")
        self.drone_info = FitLabel(col, font=("Consolas", 9), fg=FG2, bg=BG)
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
        self.bb_log = tk.Text(box, height=9, font=("Consolas", 9), fg=FG2, bg=BG2, bd=0, relief="flat", wrap="word",
                              padx=S(8), pady=S(6), highlightthickness=0, cursor="arrow")
        self.bb_log.pack(fill="x")
        self.bb_log.tag_configure("ok", foreground="#3ddc84")
        self.bb_log.tag_configure("bad", foreground="#ff6b6b")
        self.bb_log.insert("end", "The download's progress shows here.")
        self.bb_log.configure(state="disabled")

        tk.Frame(col, bg=BG, height=S(18)).pack()
        self.section("RADIO ON USB", col)
        self.radio_lab = FitLabel(col, font=("Consolas", 10, "bold"), fg=FG2, bg=BG)
        self.radio_lab.pack(fill="x")
        self.radio_info = FitLabel(col, font=("Consolas", 9), fg=FG2, bg=BG)
        self.radio_info.pack(fill="x", pady=(S(2), S(8)))
        row = tk.Frame(col, bg=BG); row.pack(fill="x")
        self.live_btn = self.button(row, "[live flight in 3d]", self.open_live)
        self.live_btn.pack(side="left")
        Tip(self.live_btn, "Opens the selected location on the fly tab: pick the radio's port there and connect.")
        self.show_devices()

    def start_device_watch(self):
        try:
            from serial.tools import list_ports  # noqa: F401
        except Exception:
            self.drone_lab.set("USB detection needs the pyserial library (pip install pyserial)")
            self.bb_btn.configure(state="disabled"); self.live_btn.configure(state="disabled")
            return
        threading.Thread(target=self._watch_devices, daemon=True).start()

    def _watch_devices(self):
        """Every few seconds: which USB serial devices are plugged in. A new one is asked once whether it is a
        Betaflight flight controller (MSP); anything else is taken as the radio. A port another program holds
        (a live flight, Betaflight Configurator) shows as busy and is asked again later."""
        import serial
        from serial.tools import list_ports
        try:
            from fpv3d.blackbox import probe
        except Exception:
            probe = lambda dev: None
        known = {}
        while True:
            changed = False
            try:
                ports = {p.device: p for p in list_ports.comports()}
            except Exception:
                ports = {}
            for dev in list(known):
                if dev not in ports:
                    known.pop(dev); changed = True
            for dev, p in ports.items():
                if "VID:PID" not in (p.hwid or "").upper():
                    continue                         # built-in / Bluetooth ports
                if dev in known and known[dev]["kind"] != "busy":
                    continue
                if self.bb_proc is not None:
                    continue                         # the download is using the drone
                try:
                    serial.Serial(dev, 115200, timeout=0.05).close()
                except Exception:
                    new = dict(kind="busy", port=dev, name=p.description or dev)
                else:
                    info = probe(dev)
                    new = dict(kind="drone", **info) if info else dict(kind="radio", port=dev, name=p.description or dev)
                if known.get(dev) != new:
                    old = known.get(dev, {}).get("kind")
                    known[dev] = new; changed = True
                    if new["kind"] == "drone" and old != "drone":
                        self.root.after(0, lambda d=new: self.say(f"drone plugged in: {d['board']} · {d['firmware']} · "
                                                                  "see the drone page to download its blackbox", "ok"))
            if changed:
                snap = {k: dict(v) for k, v in known.items()}
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
            d = drones[0]
            self.drone_lab.set(f"● {d['board']} · {d['firmware']} · {d['port']}", fg="#3ddc84")
            used, tot = d.get("flash_used"), d.get("flash_total")
            self.drone_info.set(f"blackbox: {used / 2 ** 20:.1f} of {tot / 2 ** 20:.0f} MB used" + (" (empty)" if not used else "")
                                if used is not None else "blackbox on an SD card")
        else:
            self.drone_lab.set("○ no drone on USB", fg=FG2)
            self.drone_info.set(f"{', '.join(b['port'] for b in busy)} in use by another program (Betaflight Configurator?)"
                                if busy else "plug it in: it shows here within a few seconds")
        running = self.bb_proc is not None
        self.bb_btn.configure(state="normal" if drones and not running else "disabled",
                              text="[downloading…]" if running else "[download blackbox]")
        cur = self.map.current() if hasattr(self, "map") else None
        self.bb_here_cb.configure(text=f"add every flight to {cur.get('title') or cur['name']}" if cur else "add every flight to the selected location",
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

        def read():
            added = 0
            for line in self.bb_proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                if line.startswith("ADDED "):
                    added += 1
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
        else:
            self.say("blackbox download stopped: see the drone page", "bad")

    def open_live(self):
        cur = self.map.current()
        if cur and cur.get("built"):
            self.open(f"/viewer/?scene={cur['name']}&tab=fly")

    # ------------------------------------------------------------ phone page
    def build_phone_page(self, parent):
        col = self.page_frame(parent, "PHONE",
                              "Open Alpline on your phone: same Wi-Fi as this computer, or connect the computer to the "
                              "phone's hotspot. The phone can look, fly and build; deleting and renaming stay on this computer.")
        row = tk.Frame(col, bg=BG); row.pack(fill="x")
        self.share_btn = self.button(row, "[share on my network: off]", self.toggle_share)
        self.share_btn.pack(side="left")
        self.qr_btn = self.button(row, "[qr code]", self.show_qr)
        self.qr_btn.pack(side="left", padx=(S(6), 0))
        Tip(self.qr_btn, "Show a QR code to scan with the phone's camera.")
        ck = self.button(row, "[check access]", lambda: self.check_phone_access(ask=True) if os.name == "nt"
                         else self.say("the access check is for Windows"))
        ck.pack(side="left", padx=(S(6), 0))
        Tip(ck, "Check that Windows lets the phone in (firewall, Private network) and offer to fix it.")
        grid = tk.Frame(col, bg=BG); grid.pack(fill="x", pady=(S(14), 0))
        grid.columnconfigure(1, weight=1)
        self.phone_vals = {}
        for i, (k, label) in enumerate((("addr", "address"), ("pin", "PIN"), ("state", "state"))):
            tk.Label(grid, text=label, font=("Consolas", 9), fg=FG2, bg=BG, width=10, anchor="w").grid(row=i, column=0, sticky="w", pady=S(2))
            e = tk.Entry(grid, font=("Consolas", 11, "bold"), fg=FG, bg=BG, bd=0, relief="flat", readonlybackground=BG,
                         highlightthickness=0, insertbackground=FG)
            e.grid(row=i, column=1, sticky="ew", pady=S(2))
            self.phone_vals[k] = e
        tk.Label(col, text="Type the address in the phone's browser, then the PIN once. Add it to the home screen for an "
                           "app icon.", font=SANS, fg=FG2, bg=BG, justify="left", anchor="w", wraplength=S(640)).pack(fill="x", pady=(S(12), 0))

    def set_entry(self, key, text):
        e = self.phone_vals[key]
        e.configure(state="normal"); e.delete(0, "end"); e.insert(0, text); e.configure(state="readonly")

    # ------------------------------------------------------------ settings page
    def build_settings_page(self, parent):
        col = self.page_frame(parent, "SETTINGS")
        def row(label):
            r = tk.Frame(col, bg=BG); r.pack(fill="x", pady=S(6))
            tk.Label(r, text=label, font=("Consolas", 9, "bold"), fg=FG, bg=BG, width=16, anchor="nw").pack(side="left", anchor="n")
            inner = tk.Frame(r, bg=BG); inner.pack(side="left", fill="x", expand=True)
            return inner
        r = row("QUALITY")
        seg = tk.Frame(r, bg=RULE, padx=1, pady=1); seg.pack(anchor="w")
        self.mode_btns = {}
        for m in ("full", "lite"):
            b = tk.Button(seg, text=m, font=("Consolas", 10, "bold"), width=6, relief="flat", bd=0, cursor="hand2",
                          command=lambda m=m: self.set_mode(m))
            b.pack(side="left")
            self.mode_btns[m] = b
        self.mode_info = tk.Label(r, font=SANS, fg=FG2, bg=BG, justify="left", anchor="w", wraplength=S(500), height=2)
        self.mode_info.pack(fill="x", pady=(S(4), 0))
        r = row("OPEN PAGES IN")
        seg = tk.Frame(r, bg=RULE, padx=1, pady=1); seg.pack(anchor="w")
        self.where_btns = {}
        for k, label in (("window", "Alpline window"), ("browser", "my browser")):
            b = tk.Button(seg, text=label, font=("Consolas", 10, "bold"), relief="flat", bd=0, cursor="hand2", padx=S(10),
                          command=lambda k=k: self.set_open_in(k))
            b.pack(side="left")
            self.where_btns[k] = b
        tk.Label(r, text="Alpline windows: Edge or Chrome in app mode, no address bar or tabs, own taskbar icon.",
                 font=SANS, fg=FG2, bg=BG, anchor="w", justify="left", wraplength=S(500)).pack(fill="x", pady=(S(4), 0))
        self.set_open_in(self.cfg.get("open_in", "window"), save=False)
        r = row("DESKTOP")
        self.button(r, "[add a desktop shortcut]", self.make_shortcut).pack(anchor="w")
        r = row("YOUR FILES")
        self.data_lab = FitLabel(r, font=("Consolas", 9), fg=FG, bg=BG)
        self.data_lab.set(str(ROOT))
        self.data_lab.pack(fill="x")
        br = tk.Frame(r, bg=BG); br.pack(anchor="w", pady=(S(4), 0))
        self.button(br, "[open folder]", self.open_data_folder, small=True).pack(side="left")
        if paths.FROZEN:
            ch = self.button(br, "[change…]", self.change_data_folder, small=True)
            ch.pack(side="left", padx=(S(6), 0))
            Tip(ch, "Use another folder for locations, flights and maps (e.g. an existing project folder). Restarts Alpline.")
        r = row("ABOUT")
        try:
            from fpv3d import __version__ as ver
        except Exception:
            ver = "?"
        tk.Label(r, text=f"Alpline {ver} · {'installed app' if paths.FROZEN else 'from the source folder'}",
                 font=("Consolas", 9), fg=FG2, bg=BG, anchor="w").pack(fill="x")

    def set_open_in(self, k, save=True):
        if save:
            self.cfg["open_in"] = k
            self.save()
            if k == "window" and not self.window_ok():
                self.say("Alpline windows need Microsoft Edge or Google Chrome: meanwhile the browser", "bad")
        for key, b in self.where_btns.items():
            on = key == self.cfg.get("open_in", "window")
            b.configure(bg=ACC if on else BG2, fg="#000" if on else FG2, activebackground=ACC if on else BG3)

    def open_data_folder(self):
        try:
            if os.name == "nt":
                os.startfile(str(ROOT))                     # noqa: S606
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(ROOT)])
        except Exception as ex:
            self.say(f"could not open the folder: {ex}", "bad")

    def change_data_folder(self):
        from tkinter import filedialog, messagebox
        pick = filedialog.askdirectory(parent=self.root, title="Folder for Alpline's files", initialdir=str(ROOT))
        if not pick or Path(pick) == ROOT:
            return
        if not messagebox.askyesno("Alpline", f"Use {pick} for your files? Alpline restarts.", parent=self.root):
            return
        paths.set_data(Path(pick))
        self.quit()
        subprocess.Popen([sys.executable] + sys.argv[1:])

    # ------------------------------------------------------------ disk page
    DISK_ITEMS = [("cache", "download cache (map tiles)", "Tiles from swisstopo. Lets you build offline; tiles no location uses can be removed."),
                  ("scenes", "built locations", "What the 3D viewer shows. Rebuilt from the cache if deleted."),
                  ("deleted", "deleted locations", "Kept so you can restore them. Emptying is permanent."),
                  ("logs", "flight logs", "Your recorded, downloaded and training flights.")]

    def build_disk_page(self, parent):
        col = self.page_frame(parent, "DISK SPACE")
        self.disk_labels = {}
        for key, name, tip in self.DISK_ITEMS:
            r = tk.Frame(col, bg=BG); r.pack(fill="x", pady=S(2))
            tk.Label(r, text=name, font=SANS, fg=FG, bg=BG, width=28, anchor="w").pack(side="left")
            self.disk_labels[key] = tk.Label(r, text="…", font=MONO, fg=FG, bg=BG, anchor="e", width=12)
            self.disk_labels[key].pack(side="left")
            Tip(self.disk_labels[key], tip)
        self.disk_total = FitLabel(col, font=("Consolas", 9), fg=FG2, bg=BG)
        self.disk_total.pack(fill="x", pady=(S(6), 0))
        btns = tk.Frame(col, bg=BG); btns.pack(fill="x", pady=(S(12), 0))
        b1 = self.button(btns, "[clean unused tiles]", self.disk_prune); b1.pack(side="left", padx=(0, S(6)))
        Tip(b1, "Deletes downloaded tiles that none of your location files uses. Your locations still build offline.")
        b2 = self.button(btns, "[empty deleted]", lambda: self.disk_run(["deleted", "--purge"],
                         confirm="Permanently delete the locations in the 'deleted' folder? They can no longer be restored."))
        b2.pack(side="left")
        self.disk_out = FitLabel(col, font=SANS, fg=FG2, bg=BG)
        self.disk_out.pack(fill="x", pady=(S(10), 0))

    def measure_disk(self):
        def work():
            res = {k: self.folder_size(ROOT / k) for k, *_ in self.DISK_ITEMS}
            def show():
                for k, (b, n) in res.items():
                    self.disk_labels[k].configure(text=f"{b / 1e9:.2f} GB" if b >= 1e9 else f"{b / 1e6:.0f} MB")
                tot = sum(b for b, _ in res.values())
                self.disk_total.set(f"total {tot / 1e9:.1f} GB" if tot >= 1e9 else f"total {tot / 1e6:.0f} MB")
            self.root.after(0, show)
        threading.Thread(target=work, daemon=True).start()

    def disk_run(self, args, confirm=None, after=None):
        from tkinter import messagebox
        if confirm and not messagebox.askyesno("Alpline", confirm, parent=self.root):
            return
        self.disk_out.set("working…")
        self.logo.busy(True)

        def work():
            try:
                r = subprocess.run(paths.cli_cmd() + args, cwd=str(ROOT), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                text = (r.stdout.strip().splitlines() or [""])[-1] if r.returncode == 0 else (r.stderr or r.stdout).strip()[-300:]
                self.root.after(0, lambda: (self.disk_out.set(text), after and after(r), self.measure_disk()))
            finally:
                self.root.after(0, lambda: self.logo.busy(False))
        threading.Thread(target=work, daemon=True).start()

    def disk_prune(self):                         # first say how much, then ask
        def asked(r):
            if r.returncode == 0 and "would free 0 MB" not in r.stdout:
                self.disk_run(["cache", "prune"], confirm=r.stdout.strip().splitlines()[-1].replace("would free", "This will free")
                              + ".\n\nTiles of your location files (and 1 km around them) are kept. Delete the rest?")
        self.disk_run(["cache", "prune", "--dry-run"], after=asked)

    # ------------------------------------------------------------ disk sizes
    @staticmethod
    def folder_size(p: Path):
        total = n = 0
        stack = [p]
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat().st_size; n += 1
            except OSError:
                pass
        return total, n

    # ------------------------------------------------------------ desktop shortcut (Windows)
    def make_shortcut(self):
        if os.name != "nt":
            self.say("Desktop shortcuts are made on Windows only.")
            return
        if paths.FROZEN:                          # the installed app: Alpline.exe
            target, arg, icon = paths.EXE_DIR / "Alpline.exe", "", paths.EXE_DIR / "Alpline.exe"
        else:                                     # from the source folder: the project's .venv, so the map can read your locations
            target, arg, icon = venv_exe("pythonw.exe"), f'\"{APP / "launcher.pyw"}\"', APP / "viewer" / "brand" / "icon.ico"
        ps = ("$d=[Environment]::GetFolderPath('Desktop');"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Alpline.lnk'));"
              f"$s.TargetPath='{target}';$s.Arguments='{arg}';$s.WorkingDirectory='{ROOT}';"
              f"$s.IconLocation='{icon},0';"
              "$s.Description='Alpline by lieka: FPV line of sight on Swiss terrain';$s.Save()")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.say("shortcut 'Alpline' added to your desktop" if r.returncode == 0
                 else f"could not create the shortcut: {(r.stderr or r.stdout).strip()[:120]}")



def split_name(name):
    """'007_moleson' -> ('007', 'moleson'); 'test' -> ('', 'test')"""
    head, _, rest = name.partition("_")
    return (head, rest) if head.isdigit() and rest else ("", name)



class LogoAnim:
    """The logo in the top bar: spins up once when the launcher opens, spins steadily while it works (starting the
    server, checking phone access, cleaning the cache). Frames: viewer/brand/anim-*-<size>.png, made from the web logo
    by tools/render_logo_frames.py. Without them the still logo is shown."""
    MS = {"intro": 60, "busy": 70}

    def __init__(self, root, parent, px):
        self.root, self.n_busy, self.mode, self.i, self.job = root, 0, None, 0, None
        self.still = Launcher.brand_image("logo-dark", px)
        self.frames = {k: self._load(k, px) for k in self.MS}
        self.label = None
        if self.still:
            self.label = tk.Label(parent, image=self.still, bg=BG)
            self.label.pack(side="left", padx=(0, 8))
            root.after(250, self.intro)

    @staticmethod
    def _load(kind, px):
        brand = APP / "viewer" / "brand"
        sizes = [int(p.stem.rsplit("-", 1)[1]) for p in brand.glob(f"anim-{kind}-*.png") if p.stem.rsplit("-", 1)[1].isdigit()]
        if not sizes:
            return []
        n = min(sizes, key=lambda s: abs(s - px))
        try:
            sheet = tk.PhotoImage(file=str(brand / f"anim-{kind}-{n}.png"))
        except tk.TclError:
            return []
        out = []
        for i in range(sheet.width() // n):
            f = tk.PhotoImage(width=n, height=n)
            f.tk.call(f, "copy", sheet, "-from", i * n, 0, (i + 1) * n, n, "-to", 0, 0)
            out.append(f)
        return out

    def intro(self):
        if self.frames["intro"] and self.mode is None:
            self._play("intro")

    def busy(self, on: bool):
        """busy(True) ... busy(False) around work; nested calls are counted. Call from the Tk thread."""
        self.n_busy = max(0, self.n_busy + (1 if on else -1))
        if self.n_busy and self.mode is None and self.frames["busy"]:
            self._play("busy")

    def _play(self, mode):
        self.mode, self.i = mode, 0
        if self.job is None:
            self._tick()

    def _tick(self):
        self.job = None
        if self.label is None or self.mode is None:
            return
        fr = self.frames[self.mode]
        if self.i >= len(fr):                       # the intro ended, or one busy turn ended
            if self.n_busy and self.frames["busy"]:
                self.mode, self.i = "busy", 0
                fr = self.frames["busy"]
            else:
                self.mode = None
                self.label.configure(image=self.still)
                return
        self.label.configure(image=fr[self.i])
        self.i += 1
        self.job = self.root.after(self.MS[self.mode], self._tick)



class Table:
    """Locations in number order: # · name · real logs · sim logs (grey row = not built yet). Filtered by the box above."""
    def __init__(self, app, parent):
        self.app = app
        self.box = tk.Frame(parent, bg=RULE, padx=1, pady=1)
        self.tv = ttk.Treeview(self.box, style="L.Treeview", columns=("num", "name", "real", "sim"), show="headings",
                               height=8, selectmode="browse")
        for c, label, w, anchor in (("num", "#", 40, "w"), ("name", "LOCATION", 150, "w"),
                                    ("real", "REAL", 46, "e"), ("sim", "SIM", 42, "e")):
            self.tv.heading(c, text=label, anchor=anchor)
            self.tv.column(c, width=S(w), minwidth=S(w if c != "name" else 60), anchor=anchor, stretch=c == "name")
        self.tv.tag_configure("nb", foreground=GREY)
        sb = ttk.Scrollbar(self.box, orient="vertical", command=self.tv.yview, style="L.Vertical.TScrollbar")
        def autohide(lo, hi):                   # the scrollbar only shows when the list is longer than the box
            sb.set(lo, hi)
            if float(lo) <= 0 and float(hi) >= 1:
                sb.pack_forget()
            elif not sb.winfo_ismapped():
                sb.pack(side="right", fill="y")
        self.tv.configure(yscrollcommand=autohide)
        self.tv.pack(side="left", fill="both", expand=True)
        self.tv.bind("<<TreeviewSelect>>", self.on_select)
        self.tv.bind("<Double-1>", lambda e: app.open_location(app.map.current()))
        self.tv.bind("<Return>", lambda e: app.open_location(app.map.current()))
        self.busy = False
        self.locs = []
        self.query = ""
        self.font = tkfont.Font(font=MONO)

    def fill(self, locs=None):
        if locs is not None:
            self.locs = locs
        q = self.query.lower().strip()
        self.busy = True
        self.tv.delete(*self.tv.get_children())
        for l in self.locs:
            num, rest = split_name(l["name"])
            title = l.get("title") or rest
            if q and q not in f"{l['name']} {title}".lower():
                continue
            st = l.get("stats") or {}
            self.tv.insert("", "end", iid=l["name"], tags=() if l.get("built") else ("nb",),
                           values=(num, self.cut(title), st.get("real", 0) or "·", st.get("sim", 0) or "·"))
        if self.app.map.selected in self.tv.get_children():
            self.tv.selection_set(self.app.map.selected); self.tv.see(self.app.map.selected)
        self.busy = False

    def cut(self, t):
        w = self.tv.column("name", "width") - S(10)
        if self.font.measure(t) <= w:
            return t
        while t and self.font.measure(t + "…") > w:
            t = t[:-1]
        return t.rstrip() + "…"

    def rows(self):
        return list(self.tv.get_children())

    def select(self, name):
        if name in self.tv.get_children() and self.tv.selection() != (name,):
            self.busy = True
            self.tv.selection_set(name); self.tv.see(name)
            self.app.root.after_idle(lambda: setattr(self, "busy", False))

    def step(self, d):
        rows = self.rows()
        if not rows:
            return
        cur = self.app.map.selected
        i = rows.index(cur) + d if cur in rows else 0
        self.app.select(rows[max(0, min(len(rows) - 1, i))])

    def on_select(self, _):
        if self.busy:
            return
        sel = self.tv.selection()
        if sel:
            self.app.select(sel[0])


class Card:
    """Details of the selected location: three lines of fixed height and the open button."""
    def __init__(self, app, parent):
        self.app = app
        self.frame = tk.Frame(parent, bg=RULE, padx=1, pady=1)
        inner = tk.Frame(self.frame, bg=BG, padx=S(12), pady=S(10)); inner.pack(fill="both")
        self.title = FitLabel(inner, font=("Consolas", 10, "bold"), fg=FG, bg=BG); self.title.pack(fill="x")
        self.info = FitLabel(inner, font=("Consolas", 9), fg=FG2, bg=BG); self.info.pack(fill="x", pady=(S(3), 0))
        self.stats = FitLabel(inner, font=("Consolas", 9), fg=FG2, bg=BG); self.stats.pack(fill="x", pady=(S(1), S(8)))
        row = tk.Frame(inner, bg=BG); row.pack(fill="x")
        self.open_btn = app.button(row, "[open in 3d]", lambda: app.open_location(app.map.current()), primary=True)
        self.open_btn.pack(side="left")
        self.fly_btn = app.button(row, "[fly]", app.open_live)
        self.fly_btn.pack(side="left", padx=(S(6), 0))
        Tip(self.fly_btn, "Open this location on the fly tab: training flight, or live flight with the radio.")

    def show(self, l):
        if not l:
            self.title.set("no location selected")
            self.info.set("click one on the map or in the list")
            self.stats.set("")
            self.open_btn.configure(state="disabled"); self.fly_btn.configure(state="disabled")
            return
        num, rest = split_name(l["name"])
        self.title.set(f"{num + ' · ' if num else ''}{(l.get('title') or rest).upper()}")
        size = (f"route {l['corridor']['length_m'] / 1000:.1f} km" if l.get("corridor")
                else f"{2 * l['half_size_m'] / 1000:g} × {2 * l['half_size_m'] / 1000:g} km")
        st = l.get("stats") or {}
        built = f"built {short_day(st.get('built'))}" if l.get("built") else "not built yet"
        self.info.set(f"{size} · {l.get('resolution_m', '?'):g} m terrain · {built}")
        parts = []
        for k in ("real", "sim"):
            n = st.get(k, 0)
            parts.append(f"{n} {k}" + (f" ({fmt_dur(st.get(k + '_s', 0))})" if n else ""))
        last = f" · last {short_day(st['last'])}" if st.get("last") else ""
        self.stats.set(" · ".join(parts) + last)
        self.open_btn.configure(state="normal", text="[open in 3d]" if l.get("built") else "[build on the map]")
        self.fly_btn.configure(state="normal" if l.get("built") else "disabled")


# ---------------------------------------------------------------- Switzerland map
# swisstopo grey map + FOCA drone restrictions (the same tiles as the locations map page), downloaded once at zoom 9,
# cropped to Switzerland and kept in cache/launcher/ so the map also shows offline. Scaled to the window's size.

MAP_DIR = ROOT / "cache" / "launcher"
BBOX = (5.85, 45.75, 10.6, 47.9)                    # lon/lat west, south, east, north
ZM = 9                                               # zoom of the stored map (about 1730 px wide)
TILE_URL = "https://wmts.geo.admin.ch/1.0.0/{layer}/default/current/3857/{z}/{x}/{y}.{ext}"


def merc(lon, lat, z=ZM):
    """lon/lat -> global pixel coordinates at zoom z (Web Mercator, 256 px tiles)."""
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    la = math.radians(lat)
    y = (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n
    return x, y


class SwissMap:
    """The map page: the map fills it; the locations list (top left), the selected location (bottom right) and the
    map options (bottom left) float over it at fixed sizes, so a resize only rescales the map."""
    def __init__(self, app: "Launcher", parent):
        self.app = app
        x0, y0 = merc(BBOX[0], BBOX[3]); x1, y1 = merc(BBOX[2], BBOX[1])
        self.org, self.span = (x0, y0), (x1 - x0, y1 - y0)
        self.s, self.ox, self.oy = 1.0, 0.0, 0.0
        self.cv = tk.Canvas(parent, bg=BG2, highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.src, self.imgs, self.photo = {}, {}, None
        self.locs = []
        self.selected = app.cfg.get("selected")
        self.downloading, self.spin, self.spin_i, self._spin_job, self._resize_job = False, None, 0, None, None
        self.label_font = tkfont.Font(family="Consolas", size=9, weight="bold")

        # ---- locations list (top left)
        self.listp = tk.Frame(self.cv, bg=RULE, padx=1, pady=1)
        li = tk.Frame(self.listp, bg=BG, padx=S(10), pady=S(8)); li.pack(fill="both", expand=True)
        hdr = tk.Frame(li, bg=BG); hdr.pack(fill="x")
        self.list_title = tk.Label(hdr, text="LOCATIONS", font=("Consolas", 9, "bold"), fg=FG, bg=BG)
        self.list_title.pack(side="left")
        self.fold_btn = app.button(hdr, "[–]", lambda: self.list_open(not self.open_), small=True)
        self.fold_btn.pack(side="right")
        Tip(self.fold_btn, "Fold the list to see the whole map.")
        self.list_body = tk.Frame(li, bg=BG)
        self.list_body.pack(fill="both", expand=True)
        self.filter = tk.Entry(self.list_body, font=("Consolas", 10), fg=FG, bg=BG2, insertbackground=FG, bd=0, relief="flat",
                               highlightthickness=1, highlightbackground=RULE2, highlightcolor=ACC)
        self.filter.pack(fill="x", pady=(S(6), S(6)), ipady=S(3))
        self.placeholder = tk.Label(self.filter, text="filter  (Ctrl+F)", font=("Consolas", 9), fg=GREY, bg=BG2)
        self.placeholder.place(x=S(6), rely=0.5, anchor="w")
        self.placeholder.bind("<Button-1>", lambda e: self.filter.focus_set())
        self.filter.bind("<KeyRelease>", self.on_filter)
        self.filter.bind("<Escape>", lambda e: (self.filter.delete(0, "end"), self.on_filter()))
        self.filter.bind("<Down>", lambda e: self.into_list())
        self.filter.bind("<Return>", lambda e: self.filter_enter())
        self.table = Table(app, self.list_body)
        self.table.box.pack(fill="both", expand=True)
        self.list_foot = FitLabel(self.list_body, font=("Consolas", 8), fg=FG2, bg=BG)
        self.list_foot.pack(fill="x", pady=(S(6), 0))
        self.open_ = True

        # ---- selected location (bottom right)
        self.card = Card(app, self.cv)

        # ---- map options (bottom left)
        self.bar = tk.Frame(self.cv, bg=RULE, padx=1, pady=1)
        bi = tk.Frame(self.bar, bg=BG, padx=S(8), pady=S(4)); bi.pack(fill="both")
        self.zones = tk.BooleanVar(value=app.cfg.get("map_zones", True))
        cb = tk.Checkbutton(bi, text="drone zones", variable=self.zones, command=self.draw, font=SANS, fg=FG, bg=BG,
                            selectcolor=BG2, activebackground=BG, activeforeground=FG, bd=0, highlightthickness=0)
        cb.pack(side="left")
        Tip(cb, "Official drone restrictions from FOCA (map.geo.admin.ch). An overview only: check the locations map "
                "for the details before flying.")
        up = app.button(bi, "[update map]", lambda: self.download(force=True), small=True)
        up.pack(side="left", padx=(S(8), 0))
        Tip(up, "Download the map and the latest drone zones again (needs internet; kept for offline use).")
        self.info = FitLabel(bi, font=("Consolas", 9), fg=FG2, bg=BG)
        self.info.pack(side="left", fill="x", expand=True, padx=(S(10), 0))
        self.hint = ""

        self.cv.bind("<Configure>", lambda e: self.schedule_layout())
        self.load_sources()
        if not self.src:
            self.download()

    # ---------------------------------------------------------- list panel
    def list_open(self, on):
        self.open_ = on
        if on:
            self.list_body.pack(fill="both", expand=True)
        else:
            self.list_body.pack_forget()
        self.fold_btn.configure(text="[–]" if on else "[+]")
        self.layout()

    def on_filter(self, _=None):
        q = self.filter.get()
        self.placeholder.place_forget() if q else self.placeholder.place(x=S(6), rely=0.5, anchor="w")
        if q != self.table.query:
            self.table.query = q
            self.table.fill()
            self.layout()
            rows = self.table.rows()
            if rows and self.selected not in rows:
                self.app.select(rows[0])

    def into_list(self):
        rows = self.table.rows()
        if rows:
            self.table.tv.focus_set()
            self.table.tv.focus(self.selected if self.selected in rows else rows[0])
        return "break"

    def filter_enter(self):
        rows = self.table.rows()
        if rows:
            self.app.open_location(next((l for l in self.locs if l["name"] == (self.selected if self.selected in rows else rows[0])), None))
        return "break"

    # ---------------------------------------------------------- layout
    def schedule_layout(self):
        if self._resize_job:
            self.app.root.after_cancel(self._resize_job)
        self._resize_job = self.app.root.after(60, self.layout)

    def layout(self):
        self._resize_job = None
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        if W < 50 or H < 50:
            return
        m = S(12)
        self.bar.place(x=m, y=H - m, anchor="sw", width=min(S(470), W - S(370)))
        self.card.frame.place(x=W - m, y=H - m, anchor="se", width=S(360))
        self.app.root.update_idletasks()
        bar_h = self.bar.winfo_reqheight()
        # the list: as tall as fits above the map options, in whole rows
        rowh = S(21)
        fixed = self.listp.winfo_reqheight() - (int(self.table.tv.cget("height")) * rowh if self.open_ else 0)
        avail = H - 3 * m - bar_h - fixed - S(24)
        rows = max(4, min(16, avail // rowh, len(self.table.rows()) + 1))     # no big empty box for a few locations
        if self.open_ and int(self.table.tv.cget("height")) != rows:
            self.table.tv.configure(height=rows)
        self.listp.place(x=m, y=m, anchor="nw", width=S(330))
        self.app.root.update_idletasks()
        self.table.fill()                           # names cut to the final column width
        # the map: as large as the page allows, centred
        pad = S(16)
        self.s = min((W - 2 * pad) / self.span[0], (H - 2 * pad) / self.span[1])
        self.ox = (W - self.span[0] * self.s) / 2
        self.oy = (H - self.span[1] * self.s) / 2
        self.photo = None
        self.draw(save=False)

    def px(self, lat, lon):
        x, y = merc(lon, lat)
        return self.ox + (x - self.org[0]) * self.s, self.oy + (y - self.org[1]) * self.s

    def current(self):
        return next((l for l in self.locs if l["name"] == self.selected), None)

    # ---------------------------------------------------------- data
    def load_locations(self):
        try:
            sp = APP / ".venv" / "Lib" / "site-packages"   # in case this window was started without the .venv
            if sp.exists() and str(sp) not in sys.path:
                sys.path.append(str(sp))
            from fpv3d.locations import list_locations
            self.locs = sorted((l for l in list_locations(ROOT / "scenes") if "center" in l), key=lambda l: l["name"])
            self.hint = self.map_age()
        except Exception as ex:                     # missing libraries etc.: the map still works without them
            self.locs = []
            self.hint = f"locations not shown ({ex.__class__.__name__})"
        self.info.set(self.hint)
        self.list_title.configure(text=f"LOCATIONS · {len(self.locs)}")
        if self.selected not in [l["name"] for l in self.locs]:
            self.selected = self.locs[0]["name"] if self.locs else None

    def map_age(self):
        p = MAP_DIR / "ch_base.png"
        return f"map from {time.strftime('%d %b %Y', time.localtime(p.stat().st_mtime))}" if p.exists() else "no map yet"

    def load_sources(self):
        """The stored map images (full size). Older launchers stored a small one: used until the new one is there."""
        self.src.clear(); self.imgs.clear(); self.photo = None
        for key in ("base", "zones"):
            p = MAP_DIR / f"ch_{key}.png"
            if not p.exists():
                old = sorted(MAP_DIR.glob(f"ch_{key}_*.png"), key=lambda f: f.stat().st_size)
                p = old[-1] if old else None
            if p:
                self.src[key] = p

    def image(self, key, w, h):
        """The map image at w x h px (PIL resamples it sharply; without PIL the stored size is used)."""
        k = (key, w, h)
        if k not in self.imgs:
            self.imgs = {kk: v for kk, v in self.imgs.items() if kk[1:] == (w, h)}     # keep only this size
            try:
                from PIL import Image, ImageTk
                with Image.open(self.src[key]) as im:
                    self.imgs[k] = ImageTk.PhotoImage(im.convert("RGB").resize((w, h), Image.LANCZOS))
            except Exception:
                try:
                    self.imgs[k] = tk.PhotoImage(file=str(self.src[key]))
                except tk.TclError:
                    return None
        return self.imgs[k]

    def download(self, force=False):
        if self.downloading:                        # [update map] pressed again while it runs
            return
        self.downloading = True
        logo = getattr(self.app, "logo", None)
        if logo:
            logo.busy(True)
        self.draw(save=False)                       # the old map stays under the loading box

        def done(msg=None):
            self.downloading = False
            if logo:
                logo.busy(False)
            if msg is None:
                self.load_sources()
                self.hint = self.map_age()
            self.draw()
            self.info.set(msg or self.hint)
            if msg:
                self.app.say(msg, "bad")

        def work():
            try:
                from PIL import Image
                import io
                x0, y0 = self.org
                x1, y1 = x0 + self.span[0], y0 + self.span[1]
                tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)
                out = {}
                for key, layer, ext in (("base", "ch.swisstopo.pixelkarte-grau", "jpeg"),
                                        ("zones", "ch.bazl.einschraenkungen-drohnen", "png")):
                    mosaic = Image.new("RGBA", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (0, 0, 0, 0))
                    for tx in range(tx0, tx1 + 1):
                        for ty in range(ty0, ty1 + 1):
                            url = TILE_URL.format(layer=layer, z=ZM, x=tx, y=ty, ext=ext)
                            req = urllib.request.Request(url, headers={"User-Agent": "alpline-launcher"})
                            try:
                                data = urllib.request.urlopen(req, timeout=10).read()
                            except urllib.error.HTTPError:
                                continue            # no tile there (outside the data)
                            mosaic.paste(Image.open(io.BytesIO(data)).convert("RGBA"), ((tx - tx0) * 256, (ty - ty0) * 256))
                    out[key] = mosaic.crop((round(x0 - tx0 * 256), round(y0 - ty0 * 256),
                                            round(x1 - tx0 * 256), round(y1 - ty0 * 256)))
                base = out["base"].convert("RGB").convert("RGBA")
                MAP_DIR.mkdir(parents=True, exist_ok=True)
                base.convert("RGB").save(MAP_DIR / "ch_base.png")
                Image.alpha_composite(base, out["zones"]).convert("RGB").save(MAP_DIR / "ch_zones.png")
                self.app.root.after(0, done)
            except Exception as ex:
                msg = f"map not downloaded ({ex.__class__.__name__}): needs internet once"
                self.app.root.after(0, lambda: done(msg))
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- drawing
    def draw(self, save=True):
        if save:
            self.app.cfg["map_zones"] = self.zones.get(); self.app.save()
        self.app.cfg["selected"] = self.selected
        cv = self.cv
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        key = "zones" if self.zones.get() else "base"
        w, h = round(self.span[0] * self.s), round(self.span[1] * self.s)
        if key in self.src and w > 10:
            img = self.image(key, w, h)
            if img:
                cv.create_image(self.ox, self.oy, image=img, anchor="nw")
        elif not self.downloading:
            cv.create_text(W / 2, H / 2, text="no map yet: [update map] when online", fill=FG2, font=MONO)
        mpp = 156543.03 / 2 ** ZM                    # metres per stored-map pixel at the equator
        order = sorted(self.locs, key=lambda l: (l["name"] != self.selected, not l.get("built")))
        anchors = {}
        for l in reversed(order):                   # shapes first (selected and built ones on top) ...
            col = ACC if l.get("built") else "#8a93a0"
            tag = f"loc_{l['name']}"
            if l.get("corridor"):
                pts = [c for la, lo in l["corridor"]["points"] for c in self.px(la, lo)]
                wd = max(3, 2 * l["corridor"]["width_m"] / mpp * self.s)
                cv.create_line(*pts, fill="#000", width=wd + 2, tags=tag)
                cv.create_line(*pts, fill=col, width=wd, tags=tag)
                anchors[l["name"]] = (pts[-2], pts[-1], pts[0], pts[1])
            else:
                cx, cy = self.px(*l["center"])
                r = max(4, l["half_size_m"] / (mpp * math.cos(math.radians(l["center"][0]))) * self.s)
                cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline="#000", width=3, tags=tag)
                cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline=col, width=2,
                                    fill=col if l.get("built") else "", stipple="gray50" if l.get("built") else "", tags=tag)
                anchors[l["name"]] = (cx + r, cy - r, cx, cy)
            if l["name"] == self.selected:                          # selected: a ring around it
                rx, ry = anchors[l["name"]][2:]
                rr = S(14)
                cv.create_oval(rx - rr, ry - rr, rx + rr, ry + rr, outline="#000", width=S(4), tags=tag)
                cv.create_oval(rx - rr, ry - rr, rx + rr, ry + rr, outline=ACC, width=S(2), tags=tag)
        labels = []
        for l in order:                             # ... then the numbers, selected and built ones first
            col = ACC if l.get("built") else "#8a93a0"
            tag = f"loc_{l['name']}"
            lx, ly = anchors[l["name"]][:2]
            label = split_name(l["name"])[0] or l["name"]          # the number on the map, the names are in the list
            tw = self.label_font.measure(label)
            box = (lx + 2, ly - S(14), lx + 6 + tw, ly + 1)
            if not any(box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3] for o in labels):
                labels.append(box)                  # numbers that would overlap another one are left out (hover shows them)
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):    # dark halo so the number reads on any background
                    cv.create_text(lx + 4 + dx, ly + dy, text=label, anchor="sw", fill="#000", font=self.label_font, tags=tag)
                cv.create_text(lx + 4, ly, text=label, anchor="sw", fill=col, font=self.label_font, tags=tag)
            cv.tag_bind(tag, "<Enter>", lambda e, l=l: (self.cv.configure(cursor="hand2"), self.info.set(
                f"{split_name(l['name'])[0]} {l.get('title') or l['name']}" + ("" if l.get("built") else " (not built)"))))
            cv.tag_bind(tag, "<Leave>", lambda e: (self.cv.configure(cursor=""), self.info.set(self.hint)))
            cv.tag_bind(tag, "<Button-1>", lambda e, l=l: self.app.select(l["name"]))   # click: select (list + card)
            cv.tag_bind(tag, "<Double-Button-1>", lambda e, l=l: self.app.open_location(l))
        self.busy_box()

    def busy_box(self):
        """While the map updates: a box in the middle with the transmitting logo and 'updating the map…'."""
        if not self.downloading:
            return
        if self.spin is None:
            self.spin = LogoAnim._load("busy", S(64))
        cx, cy, w, h = self.cv.winfo_width() / 2, self.cv.winfo_height() / 2, S(210), S(118)
        self.cv.create_rectangle(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, fill=BG, outline=RULE, tags="busy")
        if self.spin:
            self.cv.create_image(cx, cy - S(14), image=self.spin[self.spin_i % len(self.spin)], tags=("busy", "busyimg"))
        self.cv.create_text(cx, cy + h / 2 - S(16), text="updating the map…", fill=FG2, font=MONO, tags="busy")
        if self.spin and not self._spin_job:
            self._spin_tick()

    def _spin_tick(self):
        self._spin_job = None
        if not self.downloading or not self.spin:
            return
        self.spin_i += 1
        self.cv.itemconfigure("busyimg", image=self.spin[self.spin_i % len(self.spin)])
        self._spin_job = self.app.root.after(LogoAnim.MS["busy"], self._spin_tick)



def sharp_on_windows():
    """Tell Windows this window draws itself at the real screen resolution. Without it, on a display scaled to
    125 % / 150 %, Windows stretches a 100 % picture of the window: that is the blurry, 'hazy' look."""
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)       # per-monitor (Windows 8.1+)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()          # older Windows
        except Exception:
            pass


def first_start_folder(root) -> bool:
    """Installed app, very first start: where should your files go? True = continue, False = restart needed / quit."""
    from tkinter import filedialog, messagebox
    ans = messagebox.askyesnocancel(
        "Alpline: your files",
        "Where should Alpline keep your locations, flights and downloaded maps?\n\n"
        f"Yes: in {paths.DEFAULT_DATA}\n"
        "No: choose a folder (for example your existing fpv3d project folder, to keep everything you already have)",
        parent=root)
    if ans is None:
        return False
    folder = paths.DEFAULT_DATA
    if ans is False:
        pick = filedialog.askdirectory(parent=root, title="Folder for Alpline's files", mustexist=False,
                                       initialdir=str(Path.home()))
        if not pick:
            return False
        folder = Path(pick)
    paths.set_data(folder)
    subprocess.Popen([sys.executable] + sys.argv[1:])       # start again with the chosen folder
    return False


if __name__ == "__main__":
    sharp_on_windows()
    root = tk.Tk()
    if not paths.data_chosen():
        root.withdraw()
        first_start_folder(root)
        sys.exit(0)
    paths.ensure_data()
    paths.ensure_data()
    UI = max(1.0, root.winfo_fpixels("1i") / 96)            # 1.25, 1.5 ... on scaled displays
    root.tk.call("tk", "scaling", UI * 96 / 72)              # fonts in points follow the same factor
    Launcher(root)
    root.mainloop()
