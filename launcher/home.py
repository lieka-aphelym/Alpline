"""The home page (look H4 of the design canvas): the chosen place, big, and the way to fly it.

    game      its aerial photo fills the page like a game's title screen, the name and the numbers over it, a big
              FLY IN 3D button, and the other places as a strip of photo cards along the bottom
    terminal  the places as a list on the left, the chosen one drawn as an ASCII relief of its real heights with the
              pilot at X, its numbers as plain lines, and the keys for each action

The place shown is the one selected (on the map or here), else the first built one; selecting here selects on the
map too, it is the same selection. Keys on this page: Up / Down (Left / Right in the game look) choose, Enter flies.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import font as tkfont

from fpv3d import paths

from .common import split_name
from .style import ACC, BG, BG2, FG, FG2, GREY, MONO, MONO_S, RULE, S, TERMINAL

LEVELS = 10                                              # steps of the terminal look's relief, dark to bright


def scene_facts(name: str) -> dict:
    """What the home page says about a built place, read from its scene.json (empty when not built)."""
    try:
        m = json.loads((paths.DATA / "scenes" / name / "scene.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    g, p = m.get("grid") or {}, m.get("pilot") or {}
    seen = next((1 - l["blocked"] for l in m.get("los_layers") or [] if l.get("agl") == 30 and "blocked" in l), None)
    link = (m.get("links") or [{}])[0]
    return dict(ground=p.get("ground"), res=g.get("res"), width_km=(g.get("max_e", 0) - g.get("min_e", 0)) / 1000,
                height_km=(g.get("max_n", 0) - g.get("min_n", 0)) / 1000, range_km=(link.get("range_m") or 0) / 1000,
                seen30=seen, buildings=(m.get("buildings") or {}).get("count"), generated=m.get("generated"),
                photo=(paths.DATA / "scenes" / name / "ortho.jpg") if m.get("ortho") else None)


def relief(name: str, w: int):
    """The place's real heights as a shaded relief w cells wide (square cells, the scene's own proportions):
    (levels, pilot). Each cell mixes its height with hill shading lit from the north-west, as on a relief map, so
    slopes and ridges read and not only high and low; levels are 0 .. LEVELS - 1, dark to bright. pilot is
    (column, row) or None. None when the place is not built."""
    import numpy as np  # noqa: PLC0415
    d = paths.DATA / "scenes" / name
    try:
        m = json.loads((d / "scene.json").read_text(encoding="utf-8"))
        g = m["grid"]
        dem = np.memmap(d / m.get("terrain", "terrain.f32"), dtype="<f4", mode="r", shape=(g["rows"], g["cols"]))
    except (OSError, ValueError, KeyError):
        return None
    W, H = g["max_e"] - g["min_e"], g["max_n"] - g["min_n"]
    h = max(4, round(w * H / W))
    # each cell averages a few samples (a 16 000 x 16 000 grid stays quick to read)
    k = 3
    rr = np.clip(((np.arange(h * k) + .5) / (h * k) * g["rows"]).astype(int), 0, g["rows"] - 1)
    cc = np.clip(((np.arange(w * k) + .5) / (w * k) * g["cols"]).astype(int), 0, g["cols"] - 1)
    a = np.asarray(dem[np.ix_(rr, cc)], dtype=float)
    a[~np.isfinite(a)] = np.nan
    if not np.isfinite(a).any():
        return None
    a = np.where(np.isfinite(a), a, np.nanmin(a)).reshape(h, k, w, k).mean(axis=(1, 3))
    lo, hi = np.percentile(a, 2), np.percentile(a, 98)
    height = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)
    dy, dx = np.gradient(a * 2, H / h, W / w)                # x2: a little relief exaggeration; row 0 is north
    az, alt = np.radians(315), np.radians(40)
    slope, aspect = np.arctan(np.hypot(dx, dy)), np.arctan2(-dx, dy)
    shade = np.clip(np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect), 0, 1)
    levels = np.clip(((.35 * height + .65 * shade) * LEVELS).astype(int), 0, LEVELS - 1)
    p = m.get("pilot") or {}
    at = None
    if "x" in p and "y" in p:
        at = (min(w - 1, max(0, int(p["x"] / W * w))), min(h - 1, max(0, int((1 - p["y"] / H) * h))))
    return levels, at


def shades(n: int, dark: str, bright: str) -> list:
    """n colours from dark to bright, as (r, g, b)."""
    a = [int(dark[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bright[i:i + 2], 16) for i in (1, 3, 5)]
    return [tuple(round(x + (y - x) * t / (n - 1)) for x, y in zip(a, b)) for t in range(n)]


class Home:
    def __init__(self, app, parent):
        self.app, self.parent = app, parent
        self.thumbs, self.hero = {}, None
        if TERMINAL:
            self._build_terminal()
        else:
            self._build_game()

    # ---------------------------------------------------------------- shared
    def shown(self):
        """The place on show: the selected one, else the first built one, else the first."""
        locs = [l for l in self.app.map.locs if "error" not in l]
        cur = self.app.map.current()
        return cur or next((l for l in locs if l.get("built")), locs[0] if locs else None)

    def fly(self):
        l = self.shown()
        if l:
            self.app.open_location(l)

    def choose(self, step):
        locs = [l for l in self.app.map.locs if "error" not in l]
        if not locs:
            return
        cur = self.shown()
        i = next((k for k, l in enumerate(locs) if cur and l["name"] == cur["name"]), 0)
        self.app.select(locs[max(0, min(len(locs) - 1, i + step))]["name"])

    def refresh(self):
        if TERMINAL:
            self._fill_terminal()
        else:
            self._draw_game()

    @staticmethod
    def flights(l) -> str:
        st = l.get("stats") or {}
        n = (st.get("real") or 0) + (st.get("sim") or 0)
        return f"{n} flight{'s' if n != 1 else ''}"

    # ---------------------------------------------------------------- game: the title screen
    def _build_game(self):
        self.cv = tk.Canvas(self.parent, bg=BG, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self._draw_game())
        self.fly_btn = self.app.button(self.cv, "▶  FLY IN 3D", self.fly, primary=True)
        self.fly_btn.configure(font=("Consolas", 13, "bold"), padx=S(22), pady=S(10))
        self.map_btn = self.app.button(self.cv, "[show on the map]", self._on_map)
        self.new_btn = self.app.button(self.cv, "[+ new place]", lambda: self.app.open("/viewer/map.html"))

    def _on_map(self):
        l = self.shown()
        if l:
            self.app.select(l["name"])
        self.app.show_page("map")

    def _thumb(self, l, w, h):
        key = (l["name"], w, h)
        if key not in self.thumbs:
            f = paths.DATA / "scenes" / l["name"] / "ortho.jpg"
            img = None
            if l.get("built") and f.exists():
                try:
                    from .startup import photo_fill  # noqa: PLC0415
                    img = photo_fill(f, w, h, light=.85, left_shade=0)
                except Exception:                                   # noqa: BLE001  (a damaged photo: a plain card)
                    img = None
            self.thumbs[key] = img
        return self.thumbs[key]

    def _draw_game(self):
        cv = self.cv
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 100 or h < 100:
            return
        cv.delete("all")
        l = self.shown()
        facts = scene_facts(l["name"]) if l and l.get("built") else {}
        if facts.get("photo") and facts["photo"].exists():
            key = (l["name"], w, h)
            if not self.hero or self.hero[0] != key:
                try:
                    from .startup import photo_fill  # noqa: PLC0415
                    self.hero = (key, photo_fill(facts["photo"], w, h, light=.5, left_shade=.85))
                except Exception:                                   # noqa: BLE001
                    self.hero = (key, None)
            if self.hero[1]:
                cv.create_image(0, 0, image=self.hero[1], anchor="nw")
        x = S(40)
        name_f = tkfont.Font(family="Segoe UI", size=40, weight="bold")
        if not l:
            cv.create_text(x, S(60), anchor="nw", fill=FG, font=name_f, text="No place yet")
            cv.create_text(x, S(60) + name_f.metrics("linespace"), anchor="nw", fill=FG2, font=MONO,
                           text="Create one on the locations map: search a place, draw its square, build it.")
            cv.create_window(x, S(60) + name_f.metrics("linespace") + S(40), window=self.new_btn, anchor="nw")
            return
        num, rest = split_name(l["name"])
        y = S(46)
        tag = (f"#{num} · " if num else "") + ("BUILT" if l.get("built") else "NOT BUILT YET")
        if facts.get("generated"):
            tag += f" · {facts['generated']}"
        cv.create_text(x, y, anchor="nw", fill=ACC, font=("Consolas", 10, "bold"), text=tag)
        y += S(22)
        cv.create_text(x, y, anchor="nw", fill=FG, font=name_f, text=l.get("title") or rest, width=w - 2 * x)
        y += name_f.metrics("linespace") + S(4)
        lat, lon = (l.get("center") or [0, 0])[:2]
        line1 = f"{abs(lat):.4f} {'N' if lat >= 0 else 'S'} · {abs(lon):.4f} {'E' if lon >= 0 else 'W'}"
        if facts.get("ground") is not None:
            line1 += f" · pilot {facts['ground']:.0f} m"
        cv.create_text(x, y, anchor="nw", fill=FG, font=MONO, text=line1)
        y += S(22)
        bits = []
        if facts:
            bits.append(f"{facts['width_km']:.1f} × {facts['height_km']:.1f} km at {facts['res']:g} m")
            if facts.get("range_km"):
                bits.append(f"video reaches {facts['range_km']:.1f} km")
            if facts.get("seen30") is not None:
                bits.append(f"{facts['seen30'] * 100:.0f} % in sight at 30 m")
            if facts.get("buildings"):
                bits.append(f"{facts['buildings']} buildings")
        bits.append(self.flights(l))
        cv.create_text(x, y, anchor="nw", fill=FG2, font=MONO, text="  ·  ".join(bits), width=w - 2 * x)
        y += S(40)
        self.fly_btn.configure(text="▶  FLY IN 3D" if l.get("built") else "BUILD ON THE MAP")
        cv.create_window(x, y, window=self.fly_btn, anchor="nw")
        cv.create_window(x + self.fly_btn.winfo_reqwidth() + S(12), y + (self.fly_btn.winfo_reqheight() - self.map_btn.winfo_reqheight()) // 2,
                         window=self.map_btn, anchor="nw")
        self._draw_strip(w, h)

    def _draw_strip(self, w, h):
        """The places as photo cards along the bottom, drawn straight on the page (the photo shows between them),
        the chosen one larger and outlined; a "+ new place" card at the end."""
        locs = [l for l in self.app.map.locs if "error" not in l]
        cur = self.shown()
        cw, ch, big, gap = S(150), S(190), S(30), S(12)
        n = max(1, (w - S(80)) // (cw + gap) - 1)
        i = next((k for k, l in enumerate(locs) if cur and l["name"] == cur["name"]), 0)
        first = max(0, min(i - n // 2, len(locs) - n))
        x, base = S(40), h - S(24)
        cv = self.cv
        for k, l in enumerate(locs[first:first + n]):
            on = bool(cur and l["name"] == cur["name"])
            cw2, ch2 = (cw + big, ch + big) if on else (cw, ch)
            top, tag = base - ch2, f"card{k}"
            cv.create_rectangle(x, top, x + cw2, base, fill=BG2, outline="", tags=tag)
            img = self._thumb(l, cw2, ch2)
            if img:
                cv.create_image(x, top, image=img, anchor="nw", tags=tag)
            cv.create_rectangle(x, base - S(46), x + cw2, base, fill=BG, stipple="gray50", width=0, tags=tag)
            num, rest = split_name(l["name"])
            cv.create_text(x + S(8), base - S(40), anchor="nw", fill=FG, font=("Segoe UI", 10, "bold"),
                           text=(l.get("title") or rest)[:22], tags=tag)
            what = self.flights(l) if l.get("built") else "not built"
            cv.create_text(x + S(8), base - S(20), anchor="nw", fill=FG2 if l.get("built") else GREY, font=MONO_S,
                           text=(f"#{num} · " if num else "") + what, tags=tag)
            cv.create_rectangle(x, top, x + cw2, base, outline=ACC if on else RULE, width=S(2) if on else 1, tags=tag)
            cv.tag_bind(tag, "<Button-1>", lambda e, nm=l["name"]: self.app.select(nm))
            cv.tag_bind(tag, "<Double-Button-1>", lambda e, l=l: self.app.open_location(l))
            x += cw2 + gap
        cv.create_rectangle(x, base - ch, x + cw, base, fill=BG, outline=GREY, tags="newcard")
        cv.create_text(x + cw // 2, base - ch // 2, text="+ new place", fill=FG2, font=MONO, tags="newcard")
        cv.tag_bind("newcard", "<Button-1>", lambda e: self.app.open("/viewer/map.html"))

    # ---------------------------------------------------------------- terminal: list, relief, keys
    def _build_terminal(self):
        f = tk.Frame(self.parent, bg=BG)
        f.pack(fill="both", expand=True, padx=S(18), pady=S(14))
        f.columnconfigure(1, weight=1); f.rowconfigure(0, weight=1)
        left = tk.Frame(f, bg=BG, highlightthickness=1, highlightbackground=RULE)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, S(16)))
        self.list_title = tk.Label(left, font=MONO, fg=ACC, bg=BG, anchor="w")
        self.list_title.pack(fill="x", padx=S(10), pady=(S(8), S(4)))
        tk.Label(left, text="  #    PLACE             DETAIL  FLT", font=MONO, fg=GREY, bg=BG, anchor="w").pack(fill="x", padx=S(10))
        self.rows = tk.Frame(left, bg=BG)
        self.rows.pack(fill="both", expand=True, padx=S(10), pady=(0, S(8)))
        right = tk.Frame(f, bg=BG, highlightthickness=1, highlightbackground=RULE)
        right.grid(row=0, column=1, sticky="nsew")
        self.head = tk.Label(right, font=MONO, fg=ACC, bg=BG, anchor="w")
        self.head.pack(fill="x", padx=S(12), pady=(S(8), S(6)))
        keys = tk.Label(right, text="[enter] fly in 3d    [m] show on the map    ↑ ↓ choose", font=MONO, fg=ACC, bg=BG,
                        anchor="w")
        keys.pack(side="bottom", fill="x", padx=S(12), pady=(S(12), S(10)))
        self.facts = tk.Label(right, font=MONO, fg=FG, bg=BG, anchor="w", justify="left")
        self.facts.pack(side="bottom", fill="x", padx=S(12), pady=(S(10), 0))
        # the relief takes the room left, and is drawn as large as fits in it (a new size: drawn again)
        self.relief_box = tk.Frame(right, bg=BG)
        self.relief_box.pack(fill="both", expand=True, padx=S(12))
        self.relief = tk.Canvas(self.relief_box, bg=BG, highlightthickness=0, bd=0)
        self.relief.pack(fill="both", expand=True)
        self.relief_img = None
        self._relief_for = None
        self.relief.bind("<Configure>", lambda e: self._draw_relief())
        self.app.root.bind("<KeyPress-m>", lambda e: self._on_map() if self.app.cfg.get("page") == "home"
                           and not isinstance(e.widget, (tk.Entry, tk.Text)) else None)

    def _fill_terminal(self):
        locs = [l for l in self.app.map.locs if "error" not in l]
        cur = self.shown()
        built = sum(1 for l in locs if l.get("built"))
        self.list_title.configure(text=f"┤ PLACES {len(locs)} · {built} BUILT ├")
        for c in self.rows.winfo_children():
            c.destroy()
        for l in locs:
            on = cur and l["name"] == cur["name"]
            num, rest = split_name(l["name"])
            st = l.get("stats") or {}
            n = (st.get("real") or 0) + (st.get("sim") or 0)
            res = l.get("resolution_m")
            txt = f"{'▶' if on else ' '} {num:<4} {(l.get('title') or rest)[:16]:<16}  {(f'{res:g} m' if res else ''):>6}  {n:>3}"
            r = tk.Label(self.rows, text=txt, font=MONO, anchor="w", cursor="hand2",
                         fg=BG if on else (FG if l.get("built") else GREY), bg=ACC if on else BG)
            r.pack(fill="x")
            r.bind("<Button-1>", lambda e, nm=l["name"]: self.app.select(nm))
            r.bind("<Double-Button-1>", lambda e, l=l: self.app.open_location(l))
        if not cur:
            self.relief.delete("all")
            self.head.configure(text="┤ NO PLACE YET ├")
            self.facts.configure(text="create one on the locations map:  ctrl+f, or the [locations map] button")
            return
        lat, lon = (cur.get("center") or [0, 0])[:2]
        self.head.configure(text=f"┤ {(cur.get('title') or cur['name']).upper()} · {abs(lat):.4f} {'N' if lat >= 0 else 'S'} "
                                 f"· {abs(lon):.4f} {'E' if lon >= 0 else 'W'} ├")
        self._relief_for = None
        self._draw_relief()
        facts = scene_facts(cur["name"]) if cur.get("built") else {}
        if facts:
            bar = ""
            if facts.get("seen30") is not None:
                k = round(facts["seen30"] * 20)
                bar = f"in sight   {'█' * k}{'░' * (20 - k)} {facts['seen30'] * 100:.0f} %  at 30 m\n"
            self.facts.configure(text=(
                f"pilot      {facts['ground']:.0f} m          area   {facts['width_km']:.1f} × {facts['height_km']:.1f} km at {facts['res']:g} m\n"
                f"video      {facts['range_km']:.1f} km          buildings {facts.get('buildings') or 0}\n"
                + bar + f"flights    {self.flights(cur)}"))
        else:
            self.facts.configure(text=f"flights    {self.flights(cur)}")

    def _draw_relief(self):
        """The chosen place's relief in big square cells of amber, like a text screen's block graphics: as large as
        fits in the room left, the scene's own proportions, the pilot marked X."""
        cur = self.shown()
        cv = self.relief
        bw, bh = cv.winfo_width(), cv.winfo_height()
        if bw < 50 or bh < 30 or not cur:
            return
        key = (cur["name"], bw, bh)
        if key == self._relief_for:
            return
        self._relief_for = key
        cv.delete("all")
        if not cur.get("built"):
            cv.create_text(S(4), S(12), anchor="nw", fill=FG2, font=MONO,
                           text="not built yet: [enter] opens the locations map to build it")
            return
        f = scene_facts(cur["name"])
        aspect = (f.get("height_km") or 1) / (f.get("width_km") or 1)
        cell = S(7)                                         # one cell: about one character wide
        cols = max(16, min(bw // cell, int(bh / cell / max(aspect, .1))))
        r = relief(cur["name"], cols)
        if not r:
            return
        levels, at = r
        from PIL import Image, ImageTk  # noqa: PLC0415
        pal = shades(LEVELS, "#1c1203", "#ffd27a")
        img = Image.new("RGB", (levels.shape[1], levels.shape[0]))
        img.putdata([pal[v] for v in levels.ravel()])
        size = (levels.shape[1] * cell, levels.shape[0] * cell)
        self.relief_img = ImageTk.PhotoImage(img.resize(size, Image.NEAREST))
        cv.create_image(0, 0, image=self.relief_img, anchor="nw")
        if at:
            x, y = at[0] * cell + cell // 2, at[1] * cell + cell // 2
            cv.create_rectangle(x - S(8), y - S(9), x + S(8), y + S(9), fill=ACC, outline=BG)
            cv.create_text(x, y, text="X", fill=BG, font=("Consolas", 10, "bold"))
