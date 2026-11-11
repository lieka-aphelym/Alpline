"""The launcher window: the parts that every page shares. The pages themselves are mixed in from their files."""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import tkinter as tk
import urllib.request
from tkinter import ttk

from fpv3d.brand import APP_NAME
from fpv3d.brand import BY

from .checks import ChecksPage
from .common import APP, flight_stats, load_settings
from .drone import DronePage
from .files import FilesPage
from .mapview import SwissMap
from .phone import PhonePage
from .server import ServerMixin
from .settings import SettingsPage
from .style import ACC, BAD, BG, BG2, BG3, FG, FG2, MONO, MONO_S, OK, RULE, S, SANS, WARN
from .widgets import Btn, LogoAnim, PAGES, Pill, Tip, rail_icon


class Launcher(ServerMixin, PhonePage, DronePage, SettingsPage, ChecksPage, FilesPage):
    """The launcher window: header, rail of pages and the pages. Each page lives in its own file (the classes
    above); this file holds what they share: the frame, the widgets, selecting a location, the keys."""
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
        root.title(f"{APP_NAME} by {BY}")
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
        tk.Label(top, text=APP_NAME.upper(), font=("Consolas", 15, "bold"), fg=FG, bg=BG).pack(side="left",
                 padx=(0 if self.logo.label else S(14), 0))
        tk.Label(top, text=f"by {BY}", font=MONO_S, fg=FG2, bg=BG).pack(side="left", padx=(S(6), 0), pady=(S(5), 0))
        b = self.button(top, "[locations map]", lambda: self.open("/viewer/map.html"))
        b.pack(side="right", padx=(S(6), S(14)))
        Tip(b, f"The map page in {APP_NAME}: search places, create and build locations, drone zones.")
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
            lab = tk.Label(inner, text=label, font=MONO_S, fg=FG2, bg=BG); lab.pack()
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
        self.root.after(1500, self.check_libraries)
        self.root.after(4000, self.auto_backup)
        if self.cfg.get("share") and os.name == "nt":         # sharing was left on: check the phone can get in
            root.after(1200, lambda: self.check_phone_access(ask=True))

    # ------------------------------------------------------------ widgets
    def style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("L.Treeview", background=BG2, fieldbackground=BG2, foreground=FG, font=MONO, rowheight=S(21),
                     borderwidth=0, relief="flat")
        st.map("L.Treeview", background=[("selected", ACC)], foreground=[("selected", "#000")])
        st.configure("L.Treeview.Heading", background=BG, foreground=FG2, font=("Consolas", 9, "bold"), relief="flat",
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

    def button(self, parent, text, cmd, primary=False, small=False, danger=False):
        """Every button of the launcher. Normal, primary (filled: the next thing to do) or danger (red: it deletes).
        small is only for the header and the map's own controls; a row of a page never mixes sizes."""
        return Btn(parent, text, cmd, primary, small, danger)

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
            self.root.after(0, lambda: self.net_pill.set("online" if ok else "offline", OK if ok else WARN))
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
            col = OK if "drone" in kinds else (ACC if "radio" in kinds else None)
        elif key == "phone" and self.cfg.get("share"):
            col = ACC
        elif key == "checks" and (self.cfg.get("last_check") or {}).get("failed"):
            col = BAD                              # the last check found a problem
        elif key == "checks" and getattr(self, "libs_diff", None):
            col = WARN                              # libraries to update
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
        col = {"info": ACC, "ok": OK, "bad": BAD}.get(kind, ACC)
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
