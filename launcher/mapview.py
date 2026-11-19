"""The map page: the map (Switzerland, and the world around it) with your locations, the locations list and the
callout of the selected one."""
from __future__ import annotations

import math
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import TYPE_CHECKING

from .common import APP, ROOT, fmt_dur, short_day, split_name, unexpected
from .style import ACC, BG, BG2, BG3, FG, FG2, GREY, MONO, MONO_B, MONO_S, RULE, RULE2, S, SANS
from .widgets import FitLabel, LogoAnim, Tip


if TYPE_CHECKING:                                    # only for type hints: app.py imports this file
    from .app import Launcher


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
        self.title = FitLabel(top, font=MONO_B, fg=FG, bg=BG); self.title.pack(side="left", fill="x", expand=True)
        self.info = FitLabel(inner, font=MONO_S, fg=FG2, bg=BG); self.info.pack(fill="x", pady=(S(3), 0))
        self.stats = FitLabel(inner, font=MONO_S, fg=FG2, bg=BG); self.stats.pack(fill="x", pady=(S(1), S(8)))
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


# ---------------------------------------------------------------- the map
# swisstopo's grey map with relief shading, dimmed outside Switzerland, and the FOCA drone zones as red outlines (styled
# tiles: fpv3d/launcher_tiles.py). An overview of Switzerland and its neighbours at zoom 9 shows at once; sharper tiles
# (down to zoom 13: towns, roads, rivers) load while you zoom in and stay in cache/launcher/ for offline use, as do the
# tiles around your locations ([update map] fetches them).
# Beyond that overview the map goes on as a darkened satellite picture of the whole world (tiles from zoom 2), so
# locations abroad show too. Everything is measured in overview pixels (zoom 9) from the overview's top-left corner:
# places west or north of it simply have negative coordinates.

MAP_DIR = ROOT / "cache" / "launcher"
WIDE = (4.6, 45.2, 11.9, 48.6)                      # overview area: Switzerland + neighbours (lon/lat W, S, E, N)
CH_BOX = (5.85, 45.75, 10.6, 47.9)                  # Switzerland ([CH] button)
ZM = 9                                               # zoom of the overview = the map's own pixel unit
ZMAX = 13
WORLD = (-179.9, -78.0, 179.9, 80.0)                 # how far the map can be moved (lon/lat W, S, E, N)
MAP_BG = "#0c1016"
MPP = 156543.03 / 2 ** ZM                            # metres per map pixel at the equator


def merc(lon, lat, z=ZM):
    """lon/lat -> global pixel coordinates at zoom z (Web Mercator, 256 px tiles)."""
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    la = math.radians(lat)
    y = (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n
    return x, y


def edge_mask(size, width=110):
    """White in the middle, fading to black along the edges."""
    from PIL import Image, ImageDraw
    w, h = size
    mask = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(mask)
    for i in range(width):
        t = i / width
        d.rectangle([i, i, w - 1 - i, h - 1 - i], outline=int(255 * t * t * (3 - 2 * t)))
    return mask


def soft_edges(img, width=110):
    """Fade the map into the page background along its edges, so it doesn't end like a picture on a screen."""
    from PIL import Image
    return Image.composite(img, Image.new("RGB", img.size, MAP_BG), edge_mask(img.size, width))


class SwissMap:
    """The map page. The map fills it and can be zoomed (wheel, + / −, out to the whole world) and moved (drag); it
    opens framed on your locations. Locations are dots (yellow = built, grey ring = not built); nearby ones merge into a numbered group
    (click: zoom in). Names show once zoomed in. The selected location gets a callout next to its dot. The list
    (top left), the zoom buttons (top right) and the map options (bottom left) float over the map at fixed sizes."""
    GROUP_PX = 22                                    # dots closer than this merge into a group

    def __init__(self, app: "Launcher", parent):
        self.app = app
        x0, y0 = merc(WIDE[0], WIDE[3]); x1, y1 = merc(WIDE[2], WIDE[1])
        self.org, self.span = (x0, y0), (x1 - x0, y1 - y0)
        wx0, wy0 = merc(WORLD[0], WORLD[3]); wx1, wy1 = merc(WORLD[2], WORLD[1])
        self.world = (wx0 - x0, wy0 - y0, wx1 - x0, wy1 - y0)      # the world's box, in the same pixels
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
        self.placeholder = tk.Label(self.filter, text="filter  (Ctrl+F)", font=MONO_S, fg=GREY, bg=BG2)
        self.placeholder.place(x=S(6), rely=0.5, anchor="w")
        self.placeholder.bind("<Button-1>", lambda e: self.filter.focus_set())
        self.filter.bind("<KeyRelease>", self.on_filter)
        self.filter.bind("<Escape>", lambda e: (self.filter.delete(0, "end"), self.on_filter()))
        self.filter.bind("<Down>", lambda e: self.into_list())
        self.filter.bind("<Return>", lambda e: self.filter_enter())
        self.table = Table(app, self.list_body)
        self.table.box.pack(fill="both", expand=True)
        self.list_foot = FitLabel(self.list_body, font=MONO_S, fg=FG2, bg=BG)
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
        Tip(up, "Download the map, the relief and the latest drone zones again (needs internet; kept for offline use).\n"
                "Map: © swisstopo. Outside it: Sentinel-2 cloudless 2016 by EOX (CC BY 4.0).")
        self.info = FitLabel(bi, font=MONO_S, fg=FG2, bg=BG)
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
        """Keep the map on screen: the view never leaves the world's box (centred on it when it is smaller)."""
        for axis, size in ((0, W), (1, H)):
            w0, w1 = self.world[axis], self.world[axis + 2]
            half = size / 2 / self.s
            c = self.cx if axis == 0 else self.cy
            c = (w0 + w1) / 2 if (w1 - w0) * self.s <= size else min(max(c, w0 + half), w1 - half)
            if axis == 0:
                self.cx = c
            else:
                self.cy = c

    def ch_box(self):
        x0, y0 = self.mpx(CH_BOX[3], CH_BOX[0]); x1, y1 = self.mpx(CH_BOX[1], CH_BOX[2])
        return x0, y0, x1, y1

    def ch_s(self):
        """The scale at which Switzerland fills the page with a margin of its neighbours (the usual zoomed-out view;
        names next to the dots and the framing of your locations are measured against it)."""
        W, H = self.size()
        x0, y0, x1, y1 = self.ch_box()
        return min((W - S(32)) / (x1 - x0), (H - S(32)) / (y1 - y0)) / 1.25

    def min_s(self):
        """Zoomed out all the way: the world fills the page."""
        W, H = self.size()
        return min(self.ch_s(), max(W / (self.world[2] - self.world[0]), H / (self.world[3] - self.world[1])))

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
        self.fit_box(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad, max_zoom=self.ch_s() * 4)
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
            unexpected(ex)
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
            self.src["mask"] = edge_mask(full.size)          # to lay the overview over the satellite picture
            pm = MAP_DIR / "overview_mask.png"
            if not pm.exists():                                # maps downloaded before it existed: fetch it once, quietly
                self.fetch_border()
            if pm.exists():                                    # Switzerland's outline: the map inside, satellite around
                from PIL import ImageChops, ImageFilter
                with Image.open(pm) as m:
                    border = m.convert("L").resize(full.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(2.5))
                self.src["border"] = ImageChops.multiply(border, self.src["mask"])
                self.src["border_full"] = border             # zoomed in: which detail tiles are Swiss, which abroad
                self.src["edge"] = border.filter(ImageFilter.FIND_EDGES).point(lambda p: min(255, p * 3))
            if pz.exists():
                with Image.open(pz) as z:
                    ov = z.convert("RGBA").resize(full.size)
                zm = full.copy(); zm.paste(ov, (0, 0), ov)
                self.src["map_z"] = soft_edges(zm)
            for k in list(self.src):                  # half size: used when zoomed out (4x fewer pixels to scale)
                self.src[k + "_half"] = self.src[k].resize((full.size[0] // 2, full.size[1] // 2), Image.LANCZOS)
            # small copies for the world view, where the whole overview is a few dozen pixels wide
            for k in ("map", "map_z", "mask", "border"):
                if k in self.src:
                    self.src[k + "_small"] = self.src[k].resize((full.size[0] // 8, full.size[1] // 8), Image.LANCZOS)
        except Exception as ex:                       # a damaged file: download again with [update map]
            unexpected(ex)
            self.hint = f"map file not readable ({ex.__class__.__name__}): [update map]"

    def fetch_border(self):
        """Background: Switzerland's outline for a map downloaded by an older launcher (small: one layer at zoom 9).
        Offline, the map simply keeps its old look until the next try."""
        if getattr(self, "_border_job", False) or not self.tiles:
            return
        self._border_job = True

        def work():
            try:
                self.tiles.overview_mask().save(MAP_DIR / "overview_mask.png")
            except Exception:
                return                                  # no internet now: try again next start
            def done():
                self.load_sources(); self.draw()
            self.app.root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def view_inside(self, W, H):
        """Is the whole view inside the overview picture (the usual case: Switzerland and its neighbours)?"""
        hw, hh = W / 2 / self.s, H / 2 / self.s
        return self.cx - hw >= 0 and self.cy - hh >= 0 and self.cx + hw <= self.span[0] and self.cy + hh <= self.span[1]

    def detail_zoom(self, W=None, H=None):
        """Tile zoom for the current view (ZM = only the overview; less when the view shows more of the world)."""
        from fpv3d.launcher_tiles import view_zoom
        if W is None:
            W, H = self.size()
        return view_zoom(self.s, self.view_inside(W, H), ZM, zmax=ZMAX)

    def view_image(self, W, H, fast):
        from PIL import ImageTk
        return ImageTk.PhotoImage(self.compose(W, H, fast))

    def compose(self, W, H, fast):
        """The visible part of the map at the window's size, as one image: the overview, with sharper tiles on top
        when zoomed in (those not loaded yet are fetched in the background; the overview shows meanwhile). A view
        that reaches beyond the overview gets the world's satellite tiles first, and the overview laid over them;
        zoomed out further still (tile zoom below ZMAP) it is the satellite picture alone, Switzerland included."""
        from PIL import Image
        from fpv3d.launcher_tiles import ZMAP, in_wide
        zones = self.zones.get()
        out = Image.new("RGB", (W, H), MAP_BG)
        z = self.detail_zoom(W, H)
        self.wanted = set()
        clip = "border" in self.src and z <= ZM                # the map only inside Switzerland, satellite around it
        under = z <= ZM and (clip or not self.view_inside(W, H))   # the world goes under the overview
        world = under and z < ZMAP                            # zoomed far out: satellite only, Switzerland included

        def tiles(skip_map, sat=False, border=None):
            f = 2 ** (z - ZM)                         # tile pixels per map pixel
            gx = lambda X: W / 2 + (X / f - self.org[0] - self.cx) * self.s       # global px at z -> screen
            gy = lambda Y: H / 2 + (Y / f - self.org[1] - self.cy) * self.s
            last = 2 ** z - 1
            tx0 = max(0, int(((self.cx - W / 2 / self.s) + self.org[0]) * f // 256))
            ty0 = max(0, int(((self.cy - H / 2 / self.s) + self.org[1]) * f // 256))
            tx1 = min(last, int(((self.cx + W / 2 / self.s) + self.org[0]) * f // 256))
            ty1 = min(last, int(((self.cy + H / 2 / self.s) + self.org[1]) * f // 256))
            ctr = ((tx0 + tx1) / 2, (ty0 + ty1) / 2)
            for tx, ty in sorted(((x, y) for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)),
                                 key=lambda t: (t[0] - ctr[0]) ** 2 + (t[1] - ctr[1]) ** 2):    # centre first
                if skip_map and in_wide(z, tx, ty):   # the overview shows this part
                    continue
                L, T = round(gx(tx * 256)), round(gy(ty * 256))
                R, B = round(gx(tx * 256 + 256)), round(gy(ty * 256 + 256))
                if R - L < 2 or B - T < 2:
                    continue
                flt = Image.BILINEAR if fast or abs((R - L) - 256) > 64 else Image.LANCZOS
                cut = None
                if border is not None:                # zoomed in: the map inside Switzerland, the satellite picture around
                    ox, oy, ow = tx * 256 / f - self.org[0], ty * 256 / f - self.org[1], 256 / f
                    cut = border.crop((math.floor(ox), math.floor(oy), math.ceil(ox + ow), math.ceil(oy + ow)))
                    lo, hi = cut.getextrema()
                    if lo < 255:                      # some of it is abroad: the satellite picture first
                        st = self.tile(z, tx, ty, load=not fast, sat=in_wide(z, tx, ty))
                        if st is not None:
                            out.paste(st[0].resize((R - L, B - T), flt), (L, T))
                    if hi == 0:                       # all abroad: no map tile needed
                        continue
                    cut = None if lo == 255 else cut.resize((R - L, B - T), Image.BILINEAR)
                t = self.tile(z, tx, ty, load=not fast, sat=sat and in_wide(z, tx, ty))
                if t is None:
                    continue
                out.paste(t[0].resize((R - L, B - T), flt), (L, T), cut)
                if zones and t[1] is not None:
                    zt = t[1].resize((R - L, B - T), Image.BILINEAR)
                    out.paste(zt, (L, T), zt)

        if under and self.tiles:
            tiles(skip_map=not world and not clip, sat=clip)
        if world:
            return out
        key = "map_z" if zones and "map_z" in self.src else "map"
        k, size = 1.0, ""
        if self.s <= 0.14 and key + "_small" in self.src:         # the world view: the overview is tiny
            k, size = 0.125, "_small"
        elif self.s <= 0.55 and key + "_half" in self.src:        # zoomed out: the half-size copy is enough
            k, size = 0.5, "_half"
        im = self.src[key + size]
        s = self.s / k
        x0, y0 = (self.cx - W / 2 / self.s) * k, (self.cy - H / 2 / self.s) * k
        x1, y1 = x0 + W / s, y0 + H / s
        ix0, iy0 = max(0, x0), max(0, y0)
        ix1, iy1 = min(im.size[0], x1), min(im.size[1], y1)
        if ix1 - ix0 >= 1 and iy1 - iy0 >= 1:
            box = (int(ix0), int(iy0), math.ceil(ix1), math.ceil(iy1))
            dx, dy = round((box[0] - x0) * s), round((box[1] - y0) * s)
            dw, dh = max(1, round((box[2] - box[0]) * s)), max(1, round((box[3] - box[1]) * s))
            flt = Image.BILINEAR if fast else Image.LANCZOS
            part = im.crop(box).resize((dw, dh), flt)
            if clip:                                  # Switzerland only, with a faint line along its border
                out.paste(part, (dx, dy), self.src["border" + size].crop(box).resize((dw, dh), Image.BILINEAR))
                if not size and "edge" in self.src:
                    line = self.src["edge"].crop(box).resize((dw, dh), Image.BILINEAR)
                    out.paste(Image.new("RGB", (dw, dh), (190, 200, 212)), (dx, dy), line.point(lambda p: int(p * 0.55)))
            elif under:                               # fade its edges into the satellite picture, not into the page
                out.paste(part, (dx, dy), self.src["mask" + size].crop(box).resize((dw, dh), Image.BILINEAR))
            else:
                out.paste(part, (dx, dy))
        if z > ZM and self.tiles:
            tiles(skip_map=False, border=self.src.get("border_full"))
        return out

    def tile(self, z, x, y, load=True, sat=False):
        """A styled tile from memory, else from disk (load=True), else asked for in the background (None).
        sat: the satellite picture even inside the WIDE box (under the map clipped to the border)."""
        key = (z, x, y, "sat") if sat else (z, x, y)
        t = self.tcache.pop(key, None)
        if t is None and load:
            t = self.tiles.load(z, x, y, sat=sat)
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
            t = self.tiles.get_sat(*key[:3]) if len(key) == 4 else self.tiles.get(*key)
            self.app.root.after(0, lambda: self._tile_arrived(key, t))
        except Exception as ex:
            unexpected(ex)
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
                try:
                    self.tiles.overview_mask().save(MAP_DIR / "overview_mask.png")
                except Exception as ex:               # the map still works, just with its old dark surroundings
                    unexpected(ex)
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
            except Exception as ex:
                unexpected(ex)
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
            except Exception as ex:
                unexpected(ex)
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
        names = self.s >= self.ch_s() * 2.2          # zoomed in: names next to the dots
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
