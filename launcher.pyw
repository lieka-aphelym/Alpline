"""Alpline (by lieka) launcher: your locations on a map of Switzerland, the drone and radio on USB, phone sharing,
settings. Opens the 3D viewer and the map page.

Double-click Alpline.bat (or the desktop shortcut it can create), or start the installed Alpline app. The window
starts the local server in the chosen mode, opens Alpline windows (or your browser), and stops the server when you
close it. It also tells you whether your locations are ready to use offline at the field.

Packaged app: the same file is Alpline.exe. Alpline windows are Edge (or Chrome) in app mode (fpv3d.paths.window_cmd).
"""
from __future__ import annotations

import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fpv3d import paths  # noqa: E402  (standard library only)
from fpv3d.safefile import write_atomic

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



GREY = "#7d8796"
RULE2 = "#4a5462"                                     # control borders


class Tip:
    """Small hover tooltip (the explanations live here instead of on the screen). Shows after a short pause, one at a
    time, and checks the mouse itself: it goes away even when the window moves under the mouse (Tk then sends no
    'leave'), on a click, or when its widget is hidden."""
    current = None

    def __init__(self, w, text):
        self.w, self.text, self.top, self.job = w, text, None, None
        for ev, fn in (("<Enter>", self.enter), ("<Leave>", self.hide), ("<ButtonPress>", self.hide),
                       ("<Unmap>", self.hide), ("<Destroy>", self.hide)):
            w.bind(ev, fn, add="+")

    def enter(self, _=None):
        self.cancel()
        self.job = self.w.after(450, self.show)

    def cancel(self):
        if self.job:
            try:
                self.w.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None

    def over(self) -> bool:
        try:
            x, y = self.w.winfo_pointerxy()
            wx, wy = self.w.winfo_rootx(), self.w.winfo_rooty()
            return self.w.winfo_viewable() and wx <= x < wx + self.w.winfo_width() and wy <= y < wy + self.w.winfo_height()
        except tk.TclError:
            return False

    def show(self):
        self.job = None
        t = self.text() if callable(self.text) else self.text
        if not t or not self.over():
            return
        if Tip.current and Tip.current is not self:
            Tip.current.hide()
        self.top = tk.Toplevel(self.w); self.top.wm_overrideredirect(True)
        lab = tk.Label(self.top, text=t, font=SANS, fg=FG, bg=BG3, justify="left", wraplength=S(340), padx=S(8), pady=S(5),
                       highlightthickness=1, highlightbackground=RULE)
        lab.pack()
        self.top.update_idletasks()
        x, y = self.w.winfo_rootx(), self.w.winfo_rooty() + self.w.winfo_height() + 4
        if y + self.top.winfo_reqheight() > self.w.winfo_screenheight() - 40:      # no room below: above
            y = self.w.winfo_rooty() - self.top.winfo_reqheight() - 4
        x = min(x, self.w.winfo_screenwidth() - self.top.winfo_reqwidth() - 8)
        self.top.wm_geometry(f"+{x}+{y}")
        Tip.current = self
        self.w.after(250, self.watch)

    def watch(self):
        if not self.top:
            return
        if not self.over():
            self.hide()
            return
        self.w.after(250, self.watch)

    def hide(self, _=None):
        self.cancel()
        if self.top:
            try:
                self.top.destroy()
            except tk.TclError:
                pass
            self.top = None
        if Tip.current is self:
            Tip.current = None


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
         ("checks", "checks", "Run Alpline's own tests on this computer"),
         ("disk", "files", "Your files: sizes, clean-up / start fresh, backup and restore"),
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
    elif key == "checks":
        cv.create_rectangle(*w(4, 2, 20, 18), outline=col, width=lw)
        cv.create_line(*w(7, 10, 11, 14, 17, 6), fill=col, width=max(1, S(2)))
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
            if os.name == "nt":                    # the .ico has every size Windows wants (taskbar, Alt+Tab)
                root.iconbitmap(default=str(APP / "viewer" / "brand" / "icon.ico"))
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
        self.build_checks_page(self.pages["checks"])
        self.build_settings_page(self.pages["settings"])

        # ---- rail
        self.rail_items = {}
        tk.Frame(self.rail, bg=BG, height=S(8)).pack()
        for key, label, tip in PAGES:
            if key == "checks":
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
        root.bind("<Escape>", lambda e: self.select(None) if self.cfg.get("page") == "map"
                  and not isinstance(e.widget, (tk.Entry, tk.Text)) else None)

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
    MODE_TEXT = {"full": "Full: the whole 3D at full quality. New locations: 2 m terrain, 2 m photo, "
                         "10 m signal grid, 3D buildings.",
                 "lite": "Lite: for slower computers: lighter mesh, fewer pixels on sharp screens. New locations: "
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
            write_atomic(SETTINGS, json.dumps(self.cfg, indent=2))
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
            if not self.server_alive() or not self.running_share:
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
        for p in (self.bb_proc, self.check_proc):
            if p is not None and p.poll() is None:
                p.terminate()
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
            if ok and "map" in self.map.src:          # new locations: their detail tiles, quietly
                self.root.after(3000, self.map.prefetch)
        threading.Thread(target=net, daemon=True).start()

    def select(self, name):
        """one location chosen (map click or table row): ring on the map, row in the table, callout. None = no
        location selected: the plain map."""
        self.map.selected = name
        self.map.show_selected()
        self.map.draw()
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
        elif key == "checks" and (self.cfg.get("last_check") or {}).get("failed"):
            col = "#ff6b6b"                              # the last check found a problem
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
        self.toast.bind("<Button-1>", lambda e: self.toast.place_forget())      # (an error notice opens its file instead)
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
        try:
            from fpv3d import battery
            o = battery.overview(ROOT)
            none = sum(1 for f in o["flights"] if not f.get("pack"))
            flagged = [p["name"] for p in o["packs"] if p["flags"] and not p.get("retired")]
            self.packs_lab.set(f"{len(o['packs'])} pack(s) · {len(o['flights'])} flight(s) with battery data"
                               + (f" · {none} without a pack" if none else "")
                               + (f" · check: {', '.join(flagged)}" if flagged else ""))
        except Exception as ex:                          # noqa: BLE001 - the page works without it
            self.packs_lab.set(f"battery data not readable ({ex.__class__.__name__})")

    def start_device_watch(self):
        try:
            from serial.tools import list_ports  # noqa: F401
        except Exception:
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
        except Exception:
            probe = lambda dev: None

        def can_open(dev):
            serial.Serial(dev, 115200, timeout=0.05).close()
            return True
        w = Watcher(can_open, probe)
        while True:
            try:
                ports = [(p.device, p.hwid or "", p.description or "") for p in list_ports.comports()]
            except Exception:
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
            self.drone_lab.set(title, fg="#3ddc84")
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
        from tkinter import ttk
        from fpv3d import battery
        o = battery.overview(ROOT)
        packs = [p for p in o["packs"] if not p.get("retired")]
        w = tk.Toplevel(self.root, bg=BG)
        w.title("Alpline: which pack?")
        w.transient(self.root)
        w.resizable(False, False)
        f = tk.Frame(w, bg=BG, padx=S(16), pady=S(14)); f.pack(fill="both")
        tk.Label(f, text=f"Which pack did you fly? ({len(fids)} flight(s) with battery data)", font=("Consolas", 10, "bold"),
                 fg=FG, bg=BG, anchor="w").pack(fill="x")
        tk.Label(f, text="Alpline then follows each pack's health and how long it lasts. You can change it per flight on the packs page.",
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
        msg = tk.Label(f, text="", font=SANS, fg="#ff6b6b", bg=BG, anchor="w")

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

    # ------------------------------------------------------------ checks page
    CHECK_GROUPS = (("basic", "Basics", "coordinates, flight logs, radio maths, telemetry, blackbox, map tiles"),
                    ("server", "Server", "pages load, bad requests refused, one build at a time, cache, https"),
                    ("security", "Security", "other websites blocked, names shown as text, private files hidden, phone PIN"),
                    ("robust", "Robustness", "damaged logs, blackbox files, radio data and location files"),
                    ("journeys", "Journeys", "build, add a log, rename, delete, restore, blackbox, cache clean-up"),
                    ("files", "Your files", "safe saving, error log, clean-up, backup and restore, disk space"),
                    ("battery", "Battery", "resistance and mAh found, glitches filtered, packs, charger check, blackbox to 3D"),
                    ("snapshots", "Signal model", "line of sight and range give the same results as before"),
                    ("performance", "Speed-ups", "compact terrain and compression give the same data"),
                    ("sim", "Training flight", "flight model: hover, battery, top speed, propwash, walls"),
                    ("launcher", "Launcher", "USB detection, map groups and zoom"))

    def build_checks_page(self, parent):
        col = self.page_frame(parent, "CHECKS",
                              "Runs Alpline's own tests on this computer, about 20 seconds. Your locations and flights are "
                              "not touched: the tests work in a temporary folder with a fake swisstopo service.")
        row = tk.Frame(col, bg=BG); row.pack(fill="x")
        self.check_btn = self.button(row, "[run quick check]", self.run_checks, primary=True)
        self.check_btn.pack(side="left")
        self.copy_btn = self.button(row, "[copy report]", self.copy_check_report, small=True)
        self.copy_btn.pack(side="left", padx=(S(8), 0))
        Tip(self.copy_btn, "Copy the results, to paste them in a message when something fails.")
        self.check_status = FitLabel(col, font=("Consolas", 9), fg=FG2, bg=BG)
        self.check_status.pack(fill="x", pady=(S(8), S(4)))
        self.check_bar = tk.Canvas(col, height=S(6), bg=BG2, highlightthickness=0)
        self.check_bar.pack(fill="x", pady=(0, S(10)))
        grid = tk.Frame(col, bg=BG); grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.check_rows = {}
        for i, (key, label, desc) in enumerate(self.CHECK_GROUPS):
            tk.Label(grid, text=label, font=("Consolas", 10, "bold"), fg=FG, bg=BG, width=14, anchor="w").grid(row=i, column=0, sticky="w", pady=S(2))
            d = FitLabel(grid, font=SANS, fg=FG2, bg=BG); d.set(desc); d.grid(row=i, column=1, sticky="ew", padx=(0, S(8)))
            res = tk.Label(grid, text="–", font=("Consolas", 10), fg=FG2, bg=BG, width=13, anchor="e")
            res.grid(row=i, column=2, sticky="e")
            self.check_rows[key] = res
        box = tk.Frame(col, bg=RULE, padx=1, pady=1); box.pack(fill="x", pady=(S(12), 0))
        self.check_log = tk.Text(box, height=9, font=("Consolas", 9), fg=FG2, bg=BG2, bd=0, relief="flat", wrap="word",
                                 padx=S(8), pady=S(6), highlightthickness=0, cursor="arrow")
        self.check_log.pack(fill="x")
        self.check_log.tag_configure("bad", foreground="#ff6b6b")
        self.check_log.tag_configure("skip", foreground=ACC)
        self.check_log.tag_configure("ok", foreground="#3ddc84")
        self.check_proc, self.check_results = None, []
        self.check_runner = APP / "tests" / "run_quick.py"
        self.check_write("Failures and skipped checks show here, with what went wrong.", clear=True)
        if not self.check_runner.exists():                 # the installed app comes without the tests
            self.check_btn.configure(state="disabled")
            self.check_status.set("the checks come with the source folder (PyCharm / Alpline.bat), not with the installed app")
        else:
            self.show_last_check()

    def check_write(self, text, tag=None, clear=False):
        self.check_log.configure(state="normal")
        if clear:
            self.check_log.delete("1.0", "end")
        self.check_log.insert("end", text, tag or ())
        self.check_log.see("end")
        self.check_log.configure(state="disabled")

    def show_last_check(self):
        lc = self.cfg.get("last_check")
        if not lc:
            self.check_status.set("not run yet on this computer")
            return
        self.check_status.set(f"last run {lc['when']} · {lc['ok']} ok · {lc['failed']} failed · {lc['skipped']} skipped"
                              f" ({lc['seconds']:.0f} s)", fg="#ff6b6b" if lc["failed"] else FG2)

    def draw_check_bar(self, done, total, bad):
        c = self.check_bar
        c.delete("all")
        w = c.winfo_width() or S(600)
        if total:
            c.create_rectangle(0, 0, w * done / total, S(6), fill="#ff6b6b" if bad else "#3ddc84", outline="")

    def run_checks(self):
        if self.check_proc is not None:
            return
        self.check_results = []
        for r in self.check_rows.values():
            r.configure(text="…", fg=FG2)
        self.check_write("", clear=True)
        self.check_btn.configure(state="disabled", text="[running…]")
        self.check_status.set("running…", fg=FG2)
        self.draw_check_bar(0, 1, False)
        self.logo.busy(True)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(APP)}
        try:
            self.check_proc = subprocess.Popen([python_exe(), "-u", str(self.check_runner)], cwd=str(APP), env=env,
                                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                               encoding="utf-8", errors="replace",
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as ex:
            self.check_write(f"could not start the checks: {ex}\n", "bad")
            self._checks_done(None, 0)
            return
        t0 = time.time()

        def read():
            total, summary = 0, None
            for line in self.check_proc.stdout:
                parts = line.rstrip("\n").split("\t")
                if parts[0] == "PLAN" and len(parts) > 1:
                    total = int(parts[1])
                elif parts[0] == "RESULT" and len(parts) >= 6:
                    self.root.after(0, lambda p=parts, n=total: self._check_result(p, n))
                elif parts[0] == "DONE":
                    summary = parts
            self.check_proc.wait()
            self.root.after(0, lambda: self._checks_done(summary, time.time() - t0))
        threading.Thread(target=read, daemon=True).start()

    def _check_result(self, p, total):
        _, group, name, state, secs, msg = p[:6]
        self.check_results.append(dict(group=group, name=name, state=state, secs=float(secs or 0), msg=msg.replace(chr(31), "\n")))
        mine = [r for r in self.check_results if r["group"] == group]
        nbad = sum(r["state"] == "fail" for r in mine)
        nok = sum(r["state"] == "ok" for r in mine)
        lab = self.check_rows.get(group)
        if lab:
            lab.configure(text=f"{nbad} failed" if nbad else f"{nok} ok" + (f", {len(mine) - nok} skip" if len(mine) > nok else ""),
                          fg="#ff6b6b" if nbad else "#3ddc84")
        nice = name[5:].replace("_", " ") if name.startswith("test_") else name
        if state == "fail":
            self.check_write(f"✗ {group} · {nice}\n", "bad")
            self.check_write("   " + self.check_results[-1]["msg"].strip().replace("\n", "\n   ") + "\n")
        elif state == "skip":
            self.check_write(f"– {group} · {nice}: {self.check_results[-1]['msg']}\n", "skip")
        self.draw_check_bar(len(self.check_results), max(total, 1), any(r["state"] == "fail" for r in self.check_results))

    def _checks_done(self, summary, seconds):
        self.check_proc = None
        self.logo.busy(False)
        self.check_btn.configure(state="normal", text="[run quick check]")
        res = self.check_results
        ok, bad, skip = (sum(r["state"] == s for r in res) for s in ("ok", "fail", "skip"))
        if not res:
            self.check_write("the checks did not run (is the project's .venv complete? pip install -r requirements.txt)\n", "bad")
            self.check_status.set("the checks did not run", fg="#ff6b6b")
            return
        self.check_log.see("1.0")                         # the first problem on top
        if not bad:
            self.check_write(f"✓ all {ok} checks passed" + (f", {skip} skipped" if skip else "") + "\n", "ok")
        self.cfg["last_check"] = dict(when=time.strftime("%d %b %H:%M"), ok=ok, failed=bad, skipped=skip, seconds=seconds)
        self.save()
        self.show_last_check()
        self.draw_badge("checks")
        self.say(f"checks: all {ok} passed" if not bad else f"checks: {bad} failed (see the checks page)", "ok" if not bad else "bad")

    def copy_check_report(self):
        res = self.check_results
        if not res:
            return self.say("run the checks first")
        try:
            from fpv3d import __version__ as ver
        except Exception:
            ver = "?"
        lines = [f"Alpline {ver} checks, {time.strftime('%Y-%m-%d %H:%M')}, {sys.platform}, Python {sys.version.split()[0]}"]
        for key, label, _ in self.CHECK_GROUPS:
            mine = [r for r in res if r["group"] == key]
            if mine:
                odd = [f"{r['name'][5:]} {r['state']}" for r in mine if r["state"] != "ok"]
                lines.append(f"{label}: " + (", ".join(odd) if odd else f"all {len(mine)} ok"))
        for r in res:
            if r["state"] == "fail":
                lines.append(f"\n--- {r['group']} / {r['name']}\n{r['msg'].strip()}")
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        self.say("report copied: paste it in a message")

    # ------------------------------------------------------------ disk page
    def build_disk_page(self, parent):
        from fpv3d.housekeeping import KINDS
        col = self.page_frame(parent, "YOUR FILES",
                              "What Alpline keeps on this computer. Tick what to delete: a backup zip is made first "
                              "unless you untick it. Ticking everything starts fresh, like a new install.")
        self.disk_free = FitLabel(col, font=("Consolas", 9), fg=FG2, bg=BG)
        self.disk_free.pack(fill="x", pady=(0, S(8)))
        grid = tk.Frame(col, bg=BG); grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.disk_vars, self.disk_labels = {}, {}
        for i, (key, (label, short, desc)) in enumerate(KINDS.items()):
            v = tk.BooleanVar(value=False)
            cb = self.check(grid, label, v, command=lambda k=key: self.disk_ticked(k), width=18)
            cb.grid(row=i, column=0, sticky="w", pady=S(1))
            d = FitLabel(grid, font=SANS, fg=FG2, bg=BG); d.set(short); d.grid(row=i, column=1, sticky="ew", padx=(S(4), S(8)))
            Tip(cb, desc); Tip(d, desc)
            self.disk_labels[key] = tk.Label(grid, text="…", font=MONO, fg=FG, bg=BG, anchor="e", width=9)
            self.disk_labels[key].grid(row=i, column=2, sticky="e")
            self.disk_vars[key] = v
        sel = tk.Frame(col, bg=BG); sel.pack(fill="x", pady=(S(6), 0))
        self.button(sel, "[all: start fresh]", lambda: self.disk_select(True), small=True).pack(side="left")
        self.button(sel, "[none]", lambda: self.disk_select(False), small=True).pack(side="left", padx=(S(6), 0))
        self.disk_sel_total = tk.Label(sel, text="", font=MONO, fg=FG2, bg=BG, anchor="e")
        self.disk_sel_total.pack(side="right")
        act = tk.Frame(col, bg=BG); act.pack(fill="x", pady=(S(10), 0))
        self.disk_backup_first = tk.BooleanVar(value=True)
        self.check(act, "make a backup first", self.disk_backup_first).pack(side="left")
        self.disk_del_btn = self.button(act, "[delete selected]", self.disk_clear)
        self.disk_del_btn.configure(fg="#ff6b6b")
        self.disk_del_btn.pack(side="right")
        b1 = self.button(act, "[clean unused tiles]", self.disk_prune, small=True); b1.pack(side="right", padx=(0, S(8)))
        Tip(b1, "Deletes only the downloaded tiles that none of your location files uses. Your locations still build offline.")
        tk.Frame(col, bg=BG, height=S(14)).pack(fill="x")
        self.section("BACKUP", col)
        br = tk.Frame(col, bg=BG); br.pack(fill="x")
        self.button(br, "[make a backup…]", self.disk_backup, primary=True).pack(side="left")
        self.button(br, "[restore a backup…]", self.disk_restore).pack(side="left", padx=(S(8), 0))
        self.disk_inc_scenes = tk.BooleanVar(value=False)
        self.disk_inc_cb = self.check(col, "include the built 3D scenes (bigger; no rebuild needed after restoring)", self.disk_inc_scenes)
        self.disk_inc_cb.pack(fill="x", pady=(S(6), 0))
        tk.Label(col, text="A backup holds your locations, flights, training flights and settings: keep it safe, or use it "
                           "to move everything to another PC. Restoring never deletes anything; files you already have are kept.",
                 font=SANS, fg=FG2, bg=BG, justify="left", anchor="w", wraplength=S(640)).pack(fill="x", pady=(S(4), 0))
        self.disk_out = FitLabel(col, font=SANS, fg=FG2, bg=BG)
        self.disk_out.pack(fill="x", pady=(S(10), 0))
        self.disk_sizes = {}

    def check(self, parent, text, var, command=None, width=0):
        return tk.Checkbutton(parent, text=text, variable=var, command=command, font=SANS, fg=FG, bg=BG, selectcolor=BG2,
                              activebackground=BG, activeforeground=FG, anchor="w", width=width, bd=0,
                              highlightthickness=0, cursor="hand2", padx=0)

    def disk_ticked(self, key):
        if key == "locations" and self.disk_vars["locations"].get():
            self.disk_vars["scenes"].set(True)             # a scene without its location file can't be rebuilt or opened
        if key == "scenes" and not self.disk_vars["scenes"].get() and self.disk_vars["locations"].get():
            self.disk_vars["locations"].set(False)
        self.disk_show_selection()

    def disk_select(self, on):
        for v in self.disk_vars.values():
            v.set(on)
        self.disk_show_selection()

    def disk_show_selection(self):
        from fpv3d.housekeeping import human
        ks = [k for k, v in self.disk_vars.items() if v.get()]
        tot = sum(self.disk_sizes.get(k, 0) for k in ks)
        self.disk_sel_total.configure(text=f"selected: {human(tot)}" if ks else "")

    def measure_disk(self):
        from fpv3d.housekeeping import free_bytes, human, sizes

        def work():
            res, free = sizes(ROOT), free_bytes(ROOT)
            def show():
                self.disk_sizes = res
                for k, b in res.items():
                    self.disk_labels[k].configure(text=human(b))
                used = sum(res.values())
                self.disk_free.set(f"Alpline uses {human(used)}" + (f" · {human(free)} free on the disk" if free is not None else ""))
                self.disk_inc_cb.configure(text=f"include the built 3D scenes ({human(res.get('scenes', 0))}; no rebuild needed after restoring)")
                self.disk_show_selection()
            self.root.after(0, show)
        threading.Thread(target=work, daemon=True).start()

    def disk_job(self, text, fn, done):
        """Run fn() in the background with the logo busy; done(result or exception) back in the window."""
        self.disk_out.set(text)
        self.logo.busy(True)

        def work():
            try:
                r = fn()
            except Exception as ex:                    # noqa: BLE001 - shown to you, and logged
                from fpv3d.errorlog import record_exception
                record_exception("launcher files page", ex)
                r = ex
            self.root.after(0, lambda: (self.logo.busy(False), done(r), self.measure_disk()))
        threading.Thread(target=work, daemon=True).start()

    def backup_name(self):
        return f"alpline_backup_{time.strftime('%Y-%m-%d_%H%M')}.zip"

    def disk_backup(self):
        from tkinter import filedialog
        from fpv3d import housekeeping as hk
        (ROOT / "backups").mkdir(exist_ok=True)
        dest = filedialog.asksaveasfilename(parent=self.root, title="Save the backup", initialdir=str(ROOT / "backups"),
                                            initialfile=self.backup_name(), defaultextension=".zip",
                                            filetypes=[("Alpline backup", "*.zip")])
        if not dest:
            return
        kinds = hk.backup_kinds(include_scenes=self.disk_inc_scenes.get())
        self.disk_job("making the backup…", lambda: hk.backup(Path(dest), kinds, ROOT),
                      lambda r: self.disk_out.set(f"could not make the backup: {r}") if isinstance(r, Exception)
                      else (self.disk_out.set(f"backup saved: {dest} ({r['files']} files, {hk.human(r['bytes'])})"),
                            self.say("backup saved", "ok")))

    def disk_restore(self):
        from tkinter import filedialog, messagebox
        from fpv3d import housekeeping as hk
        src = filedialog.askopenfilename(parent=self.root, title="Restore a backup", initialdir=str(ROOT / "backups"),
                                         filetypes=[("Alpline backup", "*.zip")])
        if not src:
            return
        try:
            info = hk.read_backup(Path(src))
        except ValueError as ex:
            self.say(str(ex), "bad")
            return
        labels = ", ".join(hk.KINDS[k][0].lower() for k in info.get("kinds", []) if k in hk.KINDS)
        ans = messagebox.askyesnocancel(
            "Alpline: restore",
            f"Backup from {info.get('made', '?')}: {labels} ({len(info['names'])} files).\n\n"
            "Replace the files you already have with the ones in the backup?\n"
            "Yes: replace them · No: keep yours, add only what's missing", parent=self.root)
        if ans is None:
            return
        def done(r):
            if isinstance(r, Exception):
                self.disk_out.set(f"could not restore: {r}")
                return
            self.disk_out.set(f"restored {r['restored']} files" + (f", kept {r['kept']} you already had" if r["kept"] else "")
                              + (f", refused {r['refused']} unsafe entries" if r["refused"] else "")
                              + ". Locations without their 3D scene: build them from the map page.")
            self.say("backup restored", "ok")
            self.after_files_changed()
        self.disk_job("restoring…", lambda: hk.restore(Path(src), ROOT, replace=bool(ans)), done)

    def disk_clear(self):
        from tkinter import messagebox
        from fpv3d import housekeeping as hk
        ks = [k for k, v in self.disk_vars.items() if v.get()]
        if not ks:
            self.say("tick what to delete first")
            return
        if "locations" in ks and "scenes" not in ks:
            ks.append("scenes")
        everything = set(ks) == set(hk.KINDS)
        names = "\n".join(f"  · {hk.KINDS[k][0]} ({hk.human(self.disk_sizes.get(k, 0))})" for k in hk.KINDS if k in ks)
        backup = self.disk_backup_first.get()
        if not messagebox.askyesno(
                "Alpline: start fresh" if everything else "Alpline: delete",
                ("Start fresh: delete ALL your Alpline files?\n\n" if everything else "Delete these files?\n\n") + names
                + ("\n\nA backup zip is saved first in the 'backups' folder." if backup
                   else "\n\nNo backup: this cannot be undone."), icon="warning", parent=self.root):
            return
        if self.server_alive() and {"scenes", "locations", "settings"} & set(ks):
            self.stop()                                   # nothing open on files that are about to go
        dest = ROOT / "backups" / self.backup_name()

        def fn():
            out = {}
            if backup:
                inc = [k for k in ks if k in ("locations", "flights", "training", "settings", "scenes")]
                out["backup"] = hk.backup(dest, inc or hk.backup_kinds(), ROOT) if inc else None
            out["freed"] = hk.clear(ks, ROOT)
            return out

        def done(r):
            if isinstance(r, Exception):
                self.disk_out.set(f"nothing deleted: {r}" if isinstance(r, RuntimeError) else f"stopped: {r}")
                self.say(str(r)[:140], "bad")
                return
            freed = sum(r["freed"].values())
            self.disk_out.set(f"freed {hk.human(freed)}" + (f" · backup: backups/{dest.name}" if r.get("backup") else ""))
            self.say(f"freed {hk.human(freed)}", "ok")
            self.disk_select(False)
            if "settings" in ks:
                self.cfg = load_settings()
                self.set_mode(self.cfg.get("mode", "full"), save=False)
                self.set_open_in(self.cfg.get("open_in", "window"), save=False)
            self.after_files_changed()
        self.disk_job("making the backup…" if backup else "deleting…", fn, done)

    def after_files_changed(self):
        """Locations, scenes or flights changed on disk: refresh what the window shows."""
        self.check_offline(quiet=True)
        if self.map.selected and not any(l["name"] == self.map.selected for l in self.map.locs):
            self.select(None)

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
        if name is None:
            if self.tv.selection():
                self.busy = True
                self.tv.selection_remove(*self.tv.selection())
                self.app.root.after_idle(lambda: setattr(self, "busy", False))
            return
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
    """Details of the selected location (a callout next to its dot): three lines of fixed height and the buttons."""
    def __init__(self, app, parent):
        self.app = app
        self.frame = tk.Frame(parent, bg=ACC, padx=1, pady=1)
        inner = tk.Frame(self.frame, bg=BG, padx=S(12), pady=S(10)); inner.pack(fill="both")
        top = tk.Frame(inner, bg=BG); top.pack(fill="x")
        close = tk.Button(top, text="×", command=lambda: app.select(None), font=("Consolas", 11, "bold"), relief="flat", bd=0,
                          cursor="hand2", bg=BG, fg=FG2, activebackground=BG3, activeforeground=FG, padx=S(4), pady=0)
        close.pack(side="right")
        Tip(close, "Close: no location selected (Esc, or click an empty spot on the map)")
        self.title = FitLabel(top, font=("Consolas", 10, "bold"), fg=FG, bg=BG); self.title.pack(side="left", fill="x", expand=True)
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
# swisstopo's grey map with relief shading, dimmed outside Switzerland, and the FOCA drone zones as red outlines (styled
# tiles: fpv3d/launcher_tiles.py). An overview of Switzerland and its neighbours at zoom 9 shows at once; sharper tiles
# (down to zoom 13: towns, roads, rivers) load while you zoom in and stay in cache/launcher/ for offline use, as do the
# tiles around your locations ([update map] fetches them).

MAP_DIR = ROOT / "cache" / "launcher"
WIDE = (4.6, 45.2, 11.9, 48.6)                      # overview area: Switzerland + neighbours (lon/lat W, S, E, N)
CH_BOX = (5.85, 45.75, 10.6, 47.9)                  # Switzerland ([CH] button)
ZM = 9                                               # zoom of the overview = the map's own pixel unit
ZMAX = 13
MAP_BG = "#0c1016"
MPP = 156543.03 / 2 ** ZM                            # metres per map pixel at the equator


def merc(lon, lat, z=ZM):
    """lon/lat -> global pixel coordinates at zoom z (Web Mercator, 256 px tiles)."""
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    la = math.radians(lat)
    y = (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n
    return x, y


def soft_edges(img, width=110):
    """Fade the map into the page background along its edges, so it doesn't end like a picture on a screen."""
    from PIL import Image, ImageDraw
    w, h = img.size
    mask = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(mask)
    for i in range(width):
        t = i / width
        d.rectangle([i, i, w - 1 - i, h - 1 - i], outline=int(255 * t * t * (3 - 2 * t)))
    return Image.composite(img, Image.new("RGB", (w, h), MAP_BG), mask)


class SwissMap:
    """The map page. The map fills it and can be zoomed (wheel, + / −) and moved (drag); it opens framed on your
    locations. Locations are dots (yellow = built, grey ring = not built); nearby ones merge into a numbered group
    (click: zoom in). Names show once zoomed in. The selected location gets a callout next to its dot. The list
    (top left), the zoom buttons (top right) and the map options (bottom left) float over the map at fixed sizes."""
    GROUP_PX = 22                                    # dots closer than this merge into a group

    def __init__(self, app: "Launcher", parent):
        self.app = app
        x0, y0 = merc(WIDE[0], WIDE[3]); x1, y1 = merc(WIDE[2], WIDE[1])
        self.org, self.span = (x0, y0), (x1 - x0, y1 - y0)
        self.tiles = None                            # fpv3d.launcher_tiles.Tiles (needs Pillow)
        self.tcache = {}                             # (z, x, y) -> (RGB, zones) in memory, newest last
        self.wanted, self.pending, self.failed = set(), set(), {}
        self.pool = None
        self._tiles_job = None
        self.prefetching = False
        self.cx, self.cy, self.s = self.span[0] / 2, self.span[1] / 2, 0.5     # view: centre (stored px) + zoom
        self.fitted = False
        self.cv = tk.Canvas(parent, bg=MAP_BG, highlightthickness=0, cursor="fleur")
        self.cv.pack(fill="both", expand=True)
        self.src = {}                                # composed full-size images: dark map, zone overlay
        self.photo = None
        self.locs = []
        self.hits = []
        self.selected = app.cfg.get("selected")
        self.downloading, self.spin, self.spin_i, self._spin_job, self._resize_job, self._sharp_job = False, None, 0, None, None, None
        self.drag = None
        self.label_font = tkfont.Font(family="Consolas", size=9, weight="bold")

        # ---- locations list (top left)
        self.listp = tk.Frame(self.cv, bg=RULE, padx=1, pady=1)
        li = tk.Frame(self.listp, bg=BG, padx=S(10), pady=S(8)); li.pack(fill="both", expand=True)
        hdr = tk.Frame(li, bg=BG); hdr.pack(fill="x")
        self.list_title = tk.Label(hdr, text="LOCATIONS", font=("Consolas", 9, "bold"), fg=FG, bg=BG)
        self.list_title.pack(side="left")
        self.fold_btn = app.button(hdr, "[–]", lambda: self.list_open(not self.open_), small=True)
        self.fold_btn.pack(side="right")
        Tip(self.fold_btn, "Fold the list to see more of the map.")
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

        # ---- selected location: a callout next to its dot
        self.card = Card(app, self.cv)

        # ---- zoom buttons (top right)
        self.zbox = tk.Frame(self.cv, bg=RULE, padx=1, pady=1)
        for text, cmd, tip in (("+", lambda: self.zoom(1.4), "Zoom in (mouse wheel)"),
                               ("−", lambda: self.zoom(1 / 1.4), "Zoom out"),
                               ("fit", self.fit_locations, "Show all your locations"),
                               ("CH", self.fit_switzerland, "Show all of Switzerland")):
            b = tk.Button(self.zbox, text=text, command=cmd, font=("Consolas", 10 if len(text) == 1 else 8, "bold"), width=3,
                          relief="flat", bd=0, cursor="hand2", bg=BG, fg=FG, activebackground=BG3, activeforeground=FG, pady=S(3))
            b.pack(fill="x", pady=(0, 1))
            Tip(b, tip)

        # ---- map options (bottom left)
        self.bar = tk.Frame(self.cv, bg=RULE, padx=1, pady=1)
        bi = tk.Frame(self.bar, bg=BG, padx=S(8), pady=S(4)); bi.pack(fill="both")
        self.zones = tk.BooleanVar(value=app.cfg.get("map_zones", True))
        cb = tk.Checkbutton(bi, text="drone zones", variable=self.zones, command=lambda: self.draw(save=True), font=SANS,
                            fg=FG, bg=BG, selectcolor=BG2, activebackground=BG, activeforeground=FG, bd=0, highlightthickness=0)
        cb.pack(side="left")
        Tip(cb, "Official drone restrictions from FOCA (map.geo.admin.ch). An overview only: check the locations map "
                "for the details before flying.")
        up = app.button(bi, "[update map]", lambda: self.download(force=True), small=True)
        up.pack(side="left", padx=(S(8), 0))
        Tip(up, "Download the map, the relief and the latest drone zones again (needs internet; kept for offline use).")
        self.info = FitLabel(bi, font=("Consolas", 9), fg=FG2, bg=BG)
        self.info.pack(side="left", fill="x", expand=True, padx=(S(10), 0))
        self.hint = ""

        # ---- mouse: drag = move, wheel = zoom, click = select, double-click = open (or zoom in on empty map)
        self.cv.bind("<Configure>", lambda e: self.schedule_layout())
        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        self.cv.bind("<Double-Button-1>", self.on_double)
        self.cv.bind("<MouseWheel>", lambda e: self.zoom(1.25 if e.delta > 0 else 0.8, e.x, e.y))
        self.cv.bind("<Button-4>", lambda e: self.zoom(1.25, e.x, e.y))          # Linux wheel
        self.cv.bind("<Button-5>", lambda e: self.zoom(0.8, e.x, e.y))
        self.cv.bind("<Motion>", self.on_hover)
        self.cv.bind("<Leave>", lambda e: self.info.set(self.hint))
        self.load_sources()
        if "map" not in self.src:
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

    # ---------------------------------------------------------- layout + view
    def schedule_layout(self):
        if self._resize_job:
            self.app.root.after_cancel(self._resize_job)
        self._resize_job = self.app.root.after(60, self.layout)

    def size(self):
        return max(50, self.cv.winfo_width()), max(50, self.cv.winfo_height())

    def layout(self):
        self._resize_job = None
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        if W < 50 or H < 50:
            return
        m = S(12)
        self.bar.place(x=m, y=H - m, anchor="sw", width=min(S(470), W - S(120)))
        self.zbox.place(x=W - m, y=m, anchor="ne")
        self.app.root.update_idletasks()
        bar_h = self.bar.winfo_reqheight()
        rowh = S(21)                                 # the list: as tall as fits above the map options, in whole rows
        fixed = self.listp.winfo_reqheight() - (int(self.table.tv.cget("height")) * rowh if self.open_ else 0)
        avail = H - 3 * m - bar_h - fixed - S(24)
        rows = max(4, min(16, avail // rowh, len(self.table.rows()) + 1))
        if self.open_ and int(self.table.tv.cget("height")) != rows:
            self.table.tv.configure(height=rows)
        self.listp.place(x=m, y=m, anchor="nw", width=S(330))
        self.app.root.update_idletasks()
        self.table.fill()                           # names cut to the final column width
        if not self.fitted and W > S(600) and H > S(400):         # first real size: frame the locations
            self.fitted = True
            self.fit_locations(draw=False)
        self.s = max(self.min_s(), self.s)
        self.draw()

    def clamp(self, W, H):
        """Keep the map on screen: at most a panel's width of empty space beside it (or centred when it is smaller)."""
        for axis, size, room in ((0, W, S(360)), (1, H, S(110))):
            span, half = self.span[axis], size / 2 / self.s
            c = self.cx if axis == 0 else self.cy
            if span * self.s + 2 * room <= size:
                c = span / 2
            else:
                lo, hi = half - room / self.s, span - half + room / self.s
                c = min(max(c, lo), hi)
            if axis == 0:
                self.cx = c
            else:
                self.cy = c

    def ch_box(self):
        x0, y0 = self.mpx(CH_BOX[3], CH_BOX[0]); x1, y1 = self.mpx(CH_BOX[1], CH_BOX[2])
        return x0, y0, x1, y1

    def min_s(self):
        """Zoomed out: Switzerland with a margin of its neighbours."""
        W, H = self.size()
        x0, y0, x1, y1 = self.ch_box()
        return min((W - S(32)) / (x1 - x0), (H - S(32)) / (y1 - y0)) / 1.25

    def max_s(self):
        return 2 ** (ZMAX - ZM) * 1.3                # a little past the sharpest tiles

    def free_area(self):
        """The part of the page the floating panels leave free (to frame locations in)."""
        W, H = self.size()
        left = S(12) + S(330) + S(20) if self.open_ else S(30)
        return left, S(30), W - S(70), H - S(70)

    def fit_box(self, x0, y0, x1, y1, max_zoom=None):
        fx0, fy0, fx1, fy1 = self.free_area()
        W, H = self.size()
        s = min((fx1 - fx0) / max(1e-6, x1 - x0), (fy1 - fy0) / max(1e-6, y1 - y0))
        self.s = max(self.min_s(), min(max_zoom or self.max_s(), s))
        self.cx = (x0 + x1) / 2 - ((fx0 + fx1) / 2 - W / 2) / self.s
        self.cy = (y0 + y1) / 2 - ((fy0 + fy1) / 2 - H / 2) / self.s

    def fit_locations(self, draw=True):
        pts = [self.mpx(*l["center"]) for l in self.locs]
        if not pts:
            return self.fit_switzerland(draw)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        pad = 60                                     # stored px around them (about 15 km)
        self.fit_box(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad, max_zoom=self.min_s() * 4)
        if draw:
            self.draw()

    def fit_switzerland(self, draw=True):
        x0, y0, x1, y1 = self.ch_box()
        W, H = self.size()
        self.s = min((W - S(32)) / (x1 - x0), (H - S(32)) / (y1 - y0))
        self.cx, self.cy = (x0 + x1) / 2, (y0 + y1) / 2
        if draw:
            self.draw()

    def zoom(self, f, x=None, y=None):
        W, H = self.size()
        x = W / 2 if x is None else x
        y = H / 2 if y is None else y
        wx, wy = self.cx + (x - W / 2) / self.s, self.cy + (y - H / 2) / self.s
        self.s = max(self.min_s(), min(self.max_s(), self.s * f))
        self.cx, self.cy = wx - (x - W / 2) / self.s, wy - (y - H / 2) / self.s
        if not getattr(self, "_zoom_job", None):    # several wheel notches: one redraw
            self._zoom_job = self.app.root.after(16, self._zoom_draw)

    def _zoom_draw(self):
        self._zoom_job = None
        self.draw(fast=True)

    def mpx(self, lat, lon):
        """stored-map pixel of a point"""
        x, y = merc(lon, lat)
        return x - self.org[0], y - self.org[1]

    def px(self, lat, lon):
        """screen pixel of a point"""
        W, H = self.size()
        x, y = self.mpx(lat, lon)
        return W / 2 + (x - self.cx) * self.s, H / 2 + (y - self.cy) * self.s

    def current(self):
        return next((l for l in self.locs if l["name"] == self.selected), None)

    def show_selected(self):
        """Bring the selected location into view (picked in the list while off screen)."""
        l = self.current()
        if not l:
            return
        x, y = self.px(*l["center"])
        fx0, fy0, fx1, fy1 = self.free_area()
        if not (fx0 < x < fx1 - S(260) and fy0 < y < fy1):
            W, H = self.size()
            mx, my = self.mpx(*l["center"])
            self.cx = mx - ((fx0 + fx1 - S(260)) / 2 - W / 2) / self.s
            self.cy = my - ((fy0 + fy1) / 2 - H / 2) / self.s

    # ---------------------------------------------------------- mouse
    def hit(self, x, y):
        return next((h for h in self.hits if math.hypot(h["x"] - x, h["y"] - y) <= h["r"]), None)

    def on_press(self, e):
        self.drag = dict(x=e.x, y=e.y, cx=self.cx, cy=self.cy, moved=False)

    def on_drag(self, e):
        d = self.drag
        if not d:
            return
        if abs(e.x - d["x"]) + abs(e.y - d["y"]) > 3:
            d["moved"] = True
        if d["moved"]:                               # move what is drawn (cheap); redraw once on release
            W, H = self.size()
            ocx, ocy = self.cx, self.cy
            self.cx = d["cx"] - (e.x - d["x"]) / self.s
            self.cy = d["cy"] - (e.y - d["y"]) / self.s
            self.clamp(W, H)
            dx, dy = round((ocx - self.cx) * self.s), round((ocy - self.cy) * self.s)
            if dx or dy:
                self.cv.move("all", dx, dy)
                for h in self.hits:
                    h["x"] += dx; h["y"] += dy
                f = self.card.frame
                if f.winfo_ismapped():
                    info = f.place_info()
                    f.place_configure(x=int(float(info["x"])) + dx, y=int(float(info["y"])) + dy)

    def on_release(self, e):
        d, self.drag = self.drag, None
        if d and d["moved"]:
            self.draw()
            return
        h = self.hit(e.x, e.y)
        if not h:
            if self.selected:
                self.app.select(None)              # click on empty map: no location selected
            return
        if h.get("group"):                          # a group: zoom in until its locations separate
            pts = [self.mpx(*l["center"]) for l in h["group"]]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            pad = 8
            self.fit_box(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
            if self.selected not in [l["name"] for l in h["group"]]:
                self.selected = h["group"][0]["name"]
                self.app.select(self.selected)
            else:
                self.draw()
        else:
            self.app.select(h["loc"]["name"])

    def on_double(self, e):
        h = self.hit(e.x, e.y)
        if h and h.get("loc"):
            self.app.open_location(h["loc"])
        elif not h:
            self.zoom(1.6, e.x, e.y)

    def on_hover(self, e):
        h = self.hit(e.x, e.y)
        if h and h.get("loc"):
            l = h["loc"]
            self.cv.configure(cursor="hand2")
            self.info.set(f"{split_name(l['name'])[0]} {l.get('title') or l['name']}" + ("" if l.get("built") else " (not built)"))
        elif h:
            self.cv.configure(cursor="hand2")
            self.info.set(f"{len(h['group'])} locations: click to zoom in")
        else:
            self.cv.configure(cursor="fleur")
            self.info.set(self.hint)

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
            self.selected = None

    def map_age(self):
        p = MAP_DIR / "overview.png"
        return f"map from {time.strftime('%d %b %Y', time.localtime(p.stat().st_mtime))}" if p.exists() else "no map yet"

    def load_sources(self):
        """The overview (styled, faded at its edges) + half-size copies for zoomed-out views."""
        self.src.clear(); self.photo = None; self.tcache.clear()
        try:
            from PIL import Image
            from fpv3d.launcher_tiles import Tiles
            self.tiles = Tiles(MAP_DIR)
        except ImportError:
            self.hint = "the map needs the Pillow library"
            return
        try:
            p, pz = MAP_DIR / "overview.png", MAP_DIR / "overview_zones.png"
            if not p.exists():
                return
            with Image.open(p) as im:
                full = im.convert("RGB")
            if full.size != (round(self.span[0]), round(self.span[1])):
                full = full.resize((round(self.span[0]), round(self.span[1])), Image.LANCZOS)
            self.src["map"] = soft_edges(full)
            if pz.exists():
                with Image.open(pz) as z:
                    ov = z.convert("RGBA").resize(full.size)
                zm = full.copy(); zm.paste(ov, (0, 0), ov)
                self.src["map_z"] = soft_edges(zm)
            for k in list(self.src):                  # half size: used when zoomed out (4x fewer pixels to scale)
                self.src[k + "_half"] = self.src[k].resize((full.size[0] // 2, full.size[1] // 2), Image.LANCZOS)
        except Exception as ex:                       # a damaged file: download again with [update map]
            self.hint = f"map file not readable ({ex.__class__.__name__}): [update map]"

    def detail_zoom(self):
        """Tile zoom for the current view (ZM = only the overview)."""
        from fpv3d.launcher_tiles import zoom_for_scale
        return zoom_for_scale(self.s, ZM, ZMAX)

    def view_image(self, W, H, fast):
        """The visible part of the map at the window's size, as one image: the overview, with sharper tiles on top
        when zoomed in (those not loaded yet are fetched in the background; the overview shows meanwhile)."""
        from PIL import Image, ImageTk
        zones = self.zones.get()
        key = "map_z" if zones and "map_z" in self.src else "map"
        k = 1.0
        if self.s <= 0.55 and key + "_half" in self.src:          # zoomed out: the half-size copy is enough
            key, k = key + "_half", 0.5
        im = self.src[key]
        s = self.s / k
        x0, y0 = (self.cx - W / 2 / self.s) * k, (self.cy - H / 2 / self.s) * k
        x1, y1 = x0 + W / s, y0 + H / s
        out = Image.new("RGB", (W, H), MAP_BG)
        ix0, iy0 = max(0, x0), max(0, y0)
        ix1, iy1 = min(im.size[0], x1), min(im.size[1], y1)
        if ix1 - ix0 >= 1 and iy1 - iy0 >= 1:
            box = (int(ix0), int(iy0), math.ceil(ix1), math.ceil(iy1))
            dx, dy = round((box[0] - x0) * s), round((box[1] - y0) * s)
            dw, dh = max(1, round((box[2] - box[0]) * s)), max(1, round((box[3] - box[1]) * s))
            out.paste(im.crop(box).resize((dw, dh), Image.BILINEAR if fast else Image.LANCZOS), (dx, dy))
        z = self.detail_zoom()
        self.wanted = set()
        if z > ZM and self.tiles:
            f = 2 ** (z - ZM)                         # tile pixels per map pixel
            gx = lambda X: W / 2 + (X / f - self.org[0] - self.cx) * self.s       # global px at z -> screen
            gy = lambda Y: H / 2 + (Y / f - self.org[1] - self.cy) * self.s
            tx0 = int(((self.cx - W / 2 / self.s) + self.org[0]) * f // 256)
            ty0 = int(((self.cy - H / 2 / self.s) + self.org[1]) * f // 256)
            tx1 = int(((self.cx + W / 2 / self.s) + self.org[0]) * f // 256)
            ty1 = int(((self.cy + H / 2 / self.s) + self.org[1]) * f // 256)
            ctr = ((tx0 + tx1) / 2, (ty0 + ty1) / 2)
            for tx, ty in sorted(((x, y) for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)),
                                 key=lambda t: (t[0] - ctr[0]) ** 2 + (t[1] - ctr[1]) ** 2):    # centre first
                t = self.tile(z, tx, ty, load=not fast)
                if t is None:
                    continue
                L, T = round(gx(tx * 256)), round(gy(ty * 256))
                R, B = round(gx(tx * 256 + 256)), round(gy(ty * 256 + 256))
                if R - L < 2 or B - T < 2:
                    continue
                flt = Image.BILINEAR if fast or abs((R - L) - 256) > 64 else Image.LANCZOS
                out.paste(t[0].resize((R - L, B - T), flt), (L, T))
                if zones and t[1] is not None:
                    zt = t[1].resize((R - L, B - T), Image.BILINEAR)
                    out.paste(zt, (L, T), zt)
        return ImageTk.PhotoImage(out)

    def tile(self, z, x, y, load=True):
        """A styled tile from memory, else from disk (load=True), else asked for in the background (None)."""
        key = (z, x, y)
        t = self.tcache.pop(key, None)
        if t is None and load:
            t = self.tiles.load(z, x, y)
        if t is not None:
            self.tcache[key] = t                      # newest last
            while len(self.tcache) > 220:
                self.tcache.pop(next(iter(self.tcache)))
            return t
        self.wanted.add(key)
        if key not in self.pending and time.monotonic() > self.failed.get(key, 0) and \
                time.monotonic() > self.failed.get("net", 0):
            self.pending.add(key)
            if self.pool is None:
                from concurrent.futures import ThreadPoolExecutor
                self.pool = ThreadPoolExecutor(6)
            self.pool.submit(self._fetch_tile, key)
        return None

    def _fetch_tile(self, key):
        """Worker thread: download one tile unless the view has moved on."""
        try:
            if key not in self.wanted:
                return
            t = self.tiles.get(*key)
            self.app.root.after(0, lambda: self._tile_arrived(key, t))
        except Exception:
            now = time.monotonic()
            self.failed[key] = now + 60
            self.failed["net"] = now + 20             # offline: stop asking for a while
        finally:
            self.pending.discard(key)

    def _tile_arrived(self, key, t):
        self.tcache[key] = t
        if key in self.wanted and not self._tiles_job and not self.drag:
            self._tiles_job = self.app.root.after(200, self._tiles_draw)

    def _tiles_draw(self):
        self._tiles_job = None
        self.draw()

    def download(self, force=False):
        """[update map]: the overview again (latest zones), then the detail around your locations for offline use."""
        if self.downloading:                        # [update map] pressed again while it runs
            return
        if not self.tiles:
            self.load_sources()
            if not self.tiles:
                return
        self.downloading = True
        logo = getattr(self.app, "logo", None)
        if logo:
            logo.busy(True)
        self.draw()                                 # the old map stays under the loading box

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
            else:
                self.prefetch()

        def work():
            try:
                if force:
                    self.tiles.clear()
                rgb, zo, _ = self.tiles.overview(progress=lambda n, t: self.app.root.after(
                    0, lambda: self.info.set(f"downloading the map… {n}/{t}")))
                MAP_DIR.mkdir(parents=True, exist_ok=True)
                rgb.save(MAP_DIR / "overview.png")
                zo.save(MAP_DIR / "overview_zones.png")
                for old in MAP_DIR.glob("ch_*.png"):  # older launchers' single-picture maps
                    try:
                        old.unlink()
                    except OSError:
                        pass
                self.app.root.after(0, done)
            except Exception as ex:
                msg = f"map not downloaded ({ex.__class__.__name__}): needs internet once"
                self.app.root.after(0, lambda: done(msg))
        threading.Thread(target=work, daemon=True).start()

    def prefetch(self):
        """Background: the detailed tiles ~10 km around each location, so the map is sharp there offline too."""
        if self.prefetching or not self.tiles or not self.locs:
            return
        self.prefetching = True
        pts = [tuple(l["center"]) for l in self.locs]

        def work():
            def prog(n, t):
                if n % 10 == 0 or n == t:
                    self.app.root.after(0, lambda: self.info.set(f"detail around your locations… {n}/{t}"))
            try:
                _, failed = self.tiles.prefetch(pts, progress=prog)
            except Exception:
                failed = 1
            def fin():
                self.prefetching = False
                self.info.set(self.hint if not failed else f"{self.hint} · {failed} detail tiles missing (offline?)")
                self.draw()
            self.app.root.after(0, fin)
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- drawing
    def draw(self, save=False, fast=False):
        """Redraw the map. fast=True while dragging / zooming: quicker resampling, then a sharp redraw when it stops."""
        if save:
            self.app.cfg["map_zones"] = self.zones.get(); self.app.save()
        self.app.cfg["selected"] = self.selected
        cv = self.cv
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 50 or H < 50:
            return
        self.clamp(W, H)
        cv.delete("all")
        if "map" in self.src:
            try:
                self.photo = self.view_image(W, H, fast)
                cv.create_image(0, 0, image=self.photo, anchor="nw")
            except Exception:
                self.photo = None
        elif not self.downloading:
            cv.create_text(W / 2, H / 2, text="no map yet: [update map] when online", fill=FG2, font=MONO)
        if fast:
            if self._sharp_job:
                self.app.root.after_cancel(self._sharp_job)
            self._sharp_job = self.app.root.after(180, self.draw)
        self.draw_locations(W, H)
        self.place_callout(W, H)
        self.busy_box()

    def draw_locations(self, W, H):
        cv = self.cv
        self.hits = []
        from fpv3d.launcher_tiles import group_points
        pts = [(l, self.px(*l["center"])) for l in self.locs]
        items = group_points(pts, S(self.GROUP_PX))  # dots closer than GROUP_PX merge into groups
        names = self.s >= self.min_s() * 2.2         # zoomed in: names next to the dots
        labels = [(i["p"][0] - S(15), i["p"][1] - S(15), i["p"][0] + S(15), i["p"][1] + S(15))
                  for i in items if len(i["m"]) > 1]  # numbers never cover a group badge

        def label(text, x, y, col, force=False):
            tw = self.label_font.measure(text)
            box = (x, y - S(13), x + tw + S(4), y + S(2))
            if not force and any(box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3] for o in labels):
                return
            labels.append(box)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)):   # dark halo: reads on any background
                cv.create_text(x + S(2) + dx, y + dy, text=text, anchor="sw", fill="#000", font=self.label_font)
            cv.create_text(x + S(2), y, text=text, anchor="sw", fill=col, font=self.label_font)

        r_dot, r_ring = S(5.5), S(11)
        # selected location's real area first (under everything)
        cur = self.current()
        if cur:
            x, y = self.px(*cur["center"])
            if cur.get("corridor"):
                cpts = [c for la, lo in cur["corridor"]["points"] for c in self.px(la, lo)]
                wd = 2 * cur["corridor"]["width_m"] / MPP * self.s
                if wd > 4:
                    cv.create_line(*cpts, fill="#5c4f10", width=wd, capstyle="round", joinstyle="round")
                cv.create_line(*cpts, fill=ACC, width=S(1.5), dash=(4, 3))
            else:
                r = cur["half_size_m"] / (MPP * math.cos(math.radians(cur["center"][0]))) * self.s
                if r > S(7):
                    cv.create_rectangle(x - r, y - r, x + r, y + r, outline=ACC, width=S(1.2), dash=(4, 3))
        for it in sorted(items, key=lambda i: any(q[0]["name"] == self.selected for q in i["m"])):   # selected on top
            x, y = it["p"]
            if len(it["m"]) > 1:
                group = [q[0] for q in it["m"]]
                built = any(l.get("built") for l in group)
                has_sel = any(l["name"] == self.selected for l in group)
                cv.create_oval(x - S(14), y - S(14), x + S(14), y + S(14), outline=ACC if has_sel else "#7a6a1e", width=S(2 if has_sel else 1))
                cv.create_oval(x - S(11), y - S(11), x + S(11), y + S(11), fill=ACC if built else "#2a313c", outline="#000", width=S(2))
                cv.create_text(x, y, text=str(len(group)), fill="#000" if built else FG, font=self.label_font)
                self.hits.append(dict(x=x, y=y, r=S(15), group=group))
                continue
            l = it["m"][0][0]
            col = ACC if l.get("built") else "#8a93a0"
            if l.get("built"):
                cv.create_oval(x - r_dot, y - r_dot, x + r_dot, y + r_dot, fill=col, outline="#000", width=S(1.5))
            else:
                cv.create_oval(x - r_dot, y - r_dot, x + r_dot, y + r_dot, outline="#000", width=S(3.5))
                cv.create_oval(x - r_dot, y - r_dot, x + r_dot, y + r_dot, outline=col, width=S(2))
            sel = l["name"] == self.selected
            if sel:
                cv.create_oval(x - r_ring, y - r_ring, x + r_ring, y + r_ring, outline="#000", width=S(4))
                cv.create_oval(x - r_ring, y - r_ring, x + r_ring, y + r_ring, outline=ACC, width=S(2))
            num, rest = split_name(l["name"])
            text = f"{num} {l.get('title') or rest}".strip() if names else (num or l["name"])
            if not sel:                              # the selected one's name is in its callout
                label(text, x + S(8), y - S(3), col)
            self.hits.append(dict(x=x, y=y, r=S(10), loc=l))

    def place_callout(self, W, H):
        """The selected location's details next to its dot, on the side with room; hidden when it is off screen."""
        f = self.card.frame
        cur = self.current()
        if not cur:
            f.place_forget()
            return
        it = next((h for h in self.hits if h.get("loc", {}).get("name") == cur["name"]
                   or cur["name"] in [g["name"] for g in h.get("group", [])]), None)
        if not it:
            f.place_forget()
            return
        x, y = it["x"], it["y"]
        if x < -S(10) or x > W + S(10) or y < -S(10) or y > H + S(10):
            f.place_forget()
            return
        cw, ch = S(340), f.winfo_reqheight() or S(110)
        gap = S(22)
        right = x + gap + cw <= W - S(56)           # room on the right (the zoom buttons sit there)
        fx = x + gap if right else x - gap - cw
        fy = max(S(8), min(H - ch - S(8), y - S(22)))
        f.place(x=fx, y=fy, anchor="nw", width=cw)
        f.lift()
        ex = fx if right else fx + cw               # a short leader line from the ring to the callout
        self.cv.create_line(x + (S(11) if right else -S(11)), y, ex, min(max(y, fy + S(10)), fy + ch - S(10)),
                            fill=ACC, width=S(1.5))

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


APP_ID = "lieka.Alpline.Launcher"


def sharp_on_windows():
    """Tell Windows this window draws itself at the real screen resolution. Without it, on a display scaled to
    125 % / 150 %, Windows stretches a 100 % picture of the window: that is the blurry, 'hazy' look.
    Also give the launcher its own app id: started from the source folder the program is pythonw.exe, and Windows
    would otherwise show (and group under) Python's icon in the taskbar instead of the window's Alpline icon."""
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)       # per-monitor (Windows 8.1+)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()          # older Windows
        except Exception:
            pass


def catch_errors(root, app):
    """The launcher has no console window: an error in a button, a timer or a background task would vanish. Each one
    goes to logs/errors.txt and shows a short notice (click it to open the file)."""
    import threading
    from fpv3d.errorlog import record_exception
    last = {"t": 0.0}

    def report(ex):
        f = record_exception("launcher", ex)
        def notice():
            if time.time() - last["t"] < 3:                    # a burst of the same failure: one notice
                return
            last["t"] = time.time()
            try:
                app.say(f"Something went wrong: {type(ex).__name__}: {str(ex)[:120]}\nDetails saved in logs/errors.txt", "bad")
                app.toast.bind("<Button-1>", lambda e: (app.toast.place_forget(), open_file(f)))
            except Exception:                                  # noqa: BLE001 - the window may be closing
                pass
        try:
            root.after(0, notice)
        except Exception:                                      # noqa: BLE001
            pass

    root.report_callback_exception = lambda typ, ex, tb: report(ex)
    sys.excepthook = lambda typ, ex, tb: report(ex)
    threading.excepthook = lambda a: report(a.exc_value) if a.exc_type is not SystemExit else None


def open_file(f):
    try:
        if os.name == "nt":
            os.startfile(str(f))                               # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(f)])
    except Exception:                                          # noqa: BLE001
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
    app = Launcher(root)
    catch_errors(root, app)
    root.mainloop()
