"""What shows while Alpline starts, in two steps that follow each other without a gap.

1. The installed app shows viewer/brand/launch-splash.png the moment it is started, before Python even runs
   (PyInstaller's splash screen, see packaging/alpline.spec), with the current step written under it. On a cold
   start that takes about 2.4 s on the owner's PC (0.75 s once Windows has the files in memory, 26 Nov 2026).
   launcher.pyw writes "loading" on it, splash_close() closes it; run from the source there is none.
   It closes just before the window opens (main.py says why).
2. The launcher's window opens at once showing a start-up screen, and the launcher is built behind it (a second or
   more). The screen is in the launcher's look (settings key "look"): "game" shows the last place's photo with its
   name (splash S19 of the design canvas), "terminal" the flower in characters and the start-up lines in amber
   (S17). It goes when the launcher is ready, after at least MIN_S and at most MAX_S, or at once on a click or a key.
   Settings key "start_screen": false leaves it out.
"""
from __future__ import annotations

import json
import time
import tkinter as tk
from tkinter import font as tkfont

from fpv3d import paths
from fpv3d.brand import APP_NAME, BY

from .common import APP
from .style import ACC, BG, FG, FG2, S

AMBER, AMBER_DIM, AMBER_BG = "#ffb000", "#7a5410", "#0b0700"
MIN_S, MAX_S = 1.2, 3.0


def splash_close() -> None:
    try:
        import pyi_splash  # noqa: PLC0415  (exists only inside the packaged app)
        pyi_splash.close()
    except Exception:                                          # noqa: BLE001
        pass


def last_place(selected: str | None):
    """(title, photo file) of the place to show: the one selected last time, else the first built one with a
    photo; None when there is none."""
    scenes = paths.DATA / "scenes"
    names = [selected] if selected else []
    try:
        names += [s["name"] for s in json.loads((scenes / "index.json").read_text(encoding="utf-8"))]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    for n in names:
        f = scenes / str(n) / "ortho.jpg"
        try:
            if f.stat().st_size > 1000:
                meta = json.loads((scenes / str(n) / "scene.json").read_text(encoding="utf-8"))
                return str(meta.get("title") or n), f
        except (OSError, ValueError):
            continue
    return None


def _photo(f, w: int, h: int):
    """The photo cut to fill w x h, darkened, darker still on the left where the name is written."""
    from PIL import Image, ImageTk  # noqa: PLC0415
    im = Image.open(f)
    im.draft("RGB", (w, h))                                     # a 10 MB photo reads in a few tens of ms at this size
    im = im.convert("RGB")
    k = max(w / im.width, h / im.height)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.BILINEAR)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    im = im.crop((left, top, left + w, top + h))
    shade = Image.linear_gradient("L").rotate(90).resize((w, h))          # 255 on the left .. 0 on the right
    dark = Image.new("RGB", (w, h), (7, 9, 12))
    im = Image.composite(dark, Image.blend(dark, im, .55), shade.point(lambda v: int(v * .8)))
    return ImageTk.PhotoImage(im)


class StartScreen:
    def __init__(self, root, cfg):
        """Drawn into the empty window before the launcher is built in it (that takes a second or more), so the window
        shows this from the moment it opens; attach() then hands it the launcher for the real steps."""
        self.app, self.root = None, root
        self.look = cfg.get("look", "game")
        self.t0, self.done, self.steps = time.monotonic(), False, []
        self.place = last_place(cfg.get("selected"))
        bg = AMBER_BG if self.look == "terminal" else BG
        self.frame = tk.Frame(self.root, bg=bg, cursor="hand2")
        self.frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.frame.lift()
        if self.look == "terminal":
            self._terminal()
        else:
            self._game()
        for w in [self.frame] + list(self.frame.winfo_children()):
            w.bind("<Button-1>", lambda e: self.close())
        self.frame.bind("<Key>", lambda e: self.close())
        self.frame.focus_set()

    # ---- game: the last place's photo, the name, a thin line that fills
    def _game(self):
        self.cv = tk.Canvas(self.frame, bg=BG, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        try:
            px = min((n for n in (64, 96, 128) if n >= S(64)), default=128)          # sharp at any screen scaling
            self.logo = tk.PhotoImage(file=str(APP / "viewer" / "brand" / f"logo-dark-{px}.png"))
        except tk.TclError:
            self.logo = None
        self.img, self.progress = None, 0.0
        self.cv.bind("<Configure>", lambda e: self._draw_game())

    def paint(self):
        """Draw now, before the window is shown (it is hidden, so its size comes from the geometry it was given)."""
        if self.look != "terminal":
            try:
                w, h = map(int, self.root.geometry().split("+")[0].split("x"))
            except ValueError:
                return
            self._draw_game(w, h)

    def _draw_game(self, w=None, h=None):
        cv = self.cv
        if w is None:
            w, h = cv.winfo_width(), cv.winfo_height()
        if w < 50 or h < 50:
            return
        cv.delete("all")
        if self.place and (self.img is None or (self.img.width(), self.img.height()) != (w, h)):
            try:
                self.img = _photo(self.place[1], w, h)
            except Exception:                                    # noqa: BLE001  (a damaged photo: no picture)
                self.place, self.img = None, None
        if self.img:
            cv.create_image(0, 0, image=self.img, anchor="nw")
        # stacked from the middle by the fonts' real heights, so nothing overlaps at any screen scaling
        name_f, next_f = tkfont.Font(family="Segoe UI", size=44, weight="bold"), tkfont.Font(family="Consolas", size=11, weight="bold")
        x, y = S(56), h // 2
        top = y - name_f.metrics("linespace") // 2
        if self.logo:
            cv.create_image(x, top - S(8), image=self.logo, anchor="sw")
        cv.create_text(x, top, text=APP_NAME, anchor="nw", fill=FG, font=name_f)
        nxt = f"NEXT: {self.place[0].upper()}" if self.place else f"by {BY}"
        cv.create_text(x + S(4), top + name_f.metrics("linespace") + S(6), text=nxt, anchor="nw",
                       fill=ACC if self.place else FG2, font=next_f)
        self.step_id = cv.create_text(x + S(4), h - S(26), text=self.steps[-1] if self.steps else "", anchor="w",
                                      fill=FG2, font=("Consolas", 9))
        cv.create_rectangle(0, h - S(3), w, h, fill="#2a313c", width=0)
        self.bar = cv.create_rectangle(0, h - S(3), int(w * self.progress), h, fill=ACC, width=0)

    # ---- terminal: the flower in characters, the start-up lines appearing one by one
    def _terminal(self):
        box = tk.Frame(self.frame, bg=AMBER_BG)
        box.place(relx=.5, rely=.5, anchor="center")
        try:
            flower = (APP / "viewer" / "brand" / "flower.txt").read_text(encoding="utf-8").rstrip("\n")
        except OSError:
            flower = ""
        tk.Label(box, text=flower, font=("Consolas", 9), fg=AMBER, bg=AMBER_BG, justify="left").pack(side="left", padx=(0, S(36)))
        self.lines = tk.Frame(box, bg=AMBER_BG)
        self.lines.pack(side="left")
        tk.Label(self.lines, text=f"{APP_NAME.upper()} {self.app_version()}", font=("Consolas", 11, "bold"), fg=AMBER,
                 bg=AMBER_BG, anchor="w").pack(fill="x", pady=(0, S(6)))
        self.cursor = tk.Label(self.lines, text="█", font=("Consolas", 11), fg=AMBER, bg=AMBER_BG, anchor="w")
        self.cursor.pack(fill="x")
        self._blink()

    def _blink(self):
        if self.done:
            return
        self.cursor.configure(fg=AMBER if self.cursor.cget("fg") == AMBER_BG else AMBER_BG)
        self.root.after(500, self._blink)

    @staticmethod
    def app_version():
        try:
            from fpv3d import __version__  # noqa: PLC0415
            return __version__
        except ImportError:
            return ""

    # ---- what both looks share
    def step(self, label: str, value: str = "", ok: bool | None = True, progress: float | None = None):
        """One start-up step: a line in the terminal look, the small text and the line's length in the game look."""
        if self.done:
            return
        text = f"{label:<8} {value}".rstrip()
        self.steps.append(text)
        if self.look == "terminal":
            tag = {True: "[ OK ]", False: "[ -- ]", None: ""}[ok]
            row = tk.Frame(self.lines, bg=AMBER_BG)
            tk.Label(row, text=f"{text:<33}", font=("Consolas", 11), fg=AMBER, bg=AMBER_BG).pack(side="left")
            tk.Label(row, text=tag, font=("Consolas", 11), fg=AMBER if ok else AMBER_DIM, bg=AMBER_BG).pack(side="left")
            row.pack(fill="x", before=self.cursor)
            row.bind("<Button-1>", lambda e: self.close())
        else:
            if progress is not None:
                self.progress = progress
            if self.cv.winfo_width() > 50:
                self.cv.itemconfigure(self.step_id, text=text)
                self.cv.coords(self.bar, 0, self.cv.winfo_height() - S(3), int(self.cv.winfo_width() * self.progress),
                               self.cv.winfo_height())

    def attach(self, app):
        """The launcher is built (behind this screen): keep this on top of it, and go on with the real steps."""
        self.app = app
        if not self.done:
            self.frame.lift()
            self.frame.focus_set()
        return self

    def run(self):
        """The real steps: the places read, then the network check the launcher does anyway; ready after that."""
        locs = getattr(self.app.map, "locs", []) or []
        built = sum(1 for l in locs if l.get("built"))
        self.step("places", f"{len(locs)} · {built} built", True, .35)
        self.step("server", "starts when a page opens", None, .5)
        self._wait_network()

    def _wait_network(self):
        if self.done:
            return
        late = time.monotonic() - self.t0 > MAX_S - .4
        if self.app.online is None and not late:
            self.root.after(100, self._wait_network)
            return
        self.step("network", {True: "online", False: "offline"}.get(self.app.online, "still checking"),
                  True if self.app.online else False, .85)
        self.step("ready", "", None, 1.0)
        wait = max(.4, MIN_S - (time.monotonic() - self.t0))
        self.root.after(int(wait * 1000), self.close)

    def close(self):
        if self.done:
            return
        self.done = True
        self.frame.destroy()
