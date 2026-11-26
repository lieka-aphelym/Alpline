"""The window's frame around the pages, in the launcher's look (H4 of the design canvas). No side rail any more:

    game      one bar on top: the logo and name, the pages as words (the open one underlined in yellow), and on the
              right the internet and server status, [stop] and [locations map]
    terminal  a status line on top (name, version, internet, server, [stop], [locations map]) and the pages as a bar
              of function keys along the bottom, F1 to F7, the open one in brackets; a turning character instead of
              the logo shows when the launcher works

build_chrome() puts it in the window and returns the frame the pages go in. It gives the launcher what the pages
already use: app.logo.busy(), app.server_pill / app.net_pill.set(), app.stop_btn; set_tab() and set_badge() follow
the open page and the dots (drone plugged in, phone sharing, checks)."""
from __future__ import annotations

import tkinter as tk

from fpv3d.brand import APP_NAME

from .style import ACC, BG, FG, FG2, GREY, MONO, MONO_B, RULE, S, TERMINAL
from .widgets import LogoAnim, PAGES, Pill, Tip

TAB_WORDS = {"home": "Home", "map": "Map", "drone": "Drone", "phone": "Phone", "checks": "Checks", "disk": "Files",
             "settings": "Settings"}
SERVER_TIP = "The local server shows the 3D viewer and the map pages. It starts when you open one and stops with this window."
NET_TIP = "Internet is used for the map background, new downloads and place search. Built locations open in 3D without it."


class TextStatus(tk.Label):
    """The terminal look's status words: the same set(text, colour) as a Pill, as plain text of a fixed width (the
    line never moves); the colour only tells good from not."""
    def __init__(self, parent, chars, tip=None):
        super().__init__(parent, font=MONO, fg=FG2, bg=BG, width=chars, anchor="w")
        if tip:
            Tip(self, tip)

    def set(self, text, color=None):
        n = int(self.cget("width"))
        self.configure(text=text if len(text) <= n else text[:n - 1] + "…", fg=FG if color else FG2)


class Spinner:
    """The terminal look's stand-in for the turning logo: busy(True) ... busy(False), counted like LogoAnim."""
    FRAMES = "|/-\\"

    def __init__(self, root, label):
        self.root, self.label, self.n, self.i, self.job = root, label, 0, 0, None

    def busy(self, on: bool):
        self.n = max(0, self.n + (1 if on else -1))
        if self.n and self.job is None:
            self._tick()

    def _tick(self):
        self.job = None
        if not self.n:
            self.label.configure(text=" ")
            return
        self.label.configure(text=self.FRAMES[self.i % len(self.FRAMES)])
        self.i += 1
        self.job = self.root.after(120, self._tick)


def build_chrome(app, root):
    """The header (and the terminal's key bar) around a stage for the pages; returns the stage."""
    root.columnconfigure(0, weight=1)
    root.rowconfigure(2, weight=1)
    app.tabs = {}
    top = tk.Frame(root, bg=BG, height=S(56 if not TERMINAL else 40))
    top.grid(row=0, column=0, sticky="ew"); top.pack_propagate(False)
    tk.Frame(root, bg=RULE, height=1).grid(row=1, column=0, sticky="ew")
    stage = tk.Frame(root, bg=BG)
    stage.grid(row=2, column=0, sticky="nsew")
    stage.rowconfigure(0, weight=1); stage.columnconfigure(0, weight=1)
    (_terminal_bars if TERMINAL else _game_bar)(app, root, top)
    return stage


def _right_side(app, top):
    """[locations map], [stop], the server and internet status: the same on every page, packed from the right."""
    b = app.button(top, "[locations map]", lambda: app.open("/viewer/map.html"), small=True)
    b.pack(side="right", padx=(S(6), S(14)))
    Tip(b, f"The map page in {APP_NAME}: search places, create and build locations, drone zones.")
    app.stop_btn = app.button(top, "[stop]", app.stop, small=True)
    app.stop_btn.pack(side="right", padx=(S(4), 0))
    Tip(app.stop_btn, "Stop the local server (closing this window does it too).")


def _game_bar(app, root, top):
    app.logo = LogoAnim(root, top, S(28))
    if app.logo.label:
        app.logo.label.pack_configure(padx=(S(16), S(8)))
    tk.Label(top, text=APP_NAME.upper(), font=("Consolas", 14, "bold"), fg=FG, bg=BG).pack(
        side="left", padx=(0 if app.logo.label else S(16), S(18)))
    for key, _, tip in PAGES:
        it = tk.Frame(top, bg=BG, cursor="hand2")
        it.pack(side="left", fill="y", padx=(0, S(2)))
        row = tk.Frame(it, bg=BG)
        row.pack(side="top", fill="both", expand=True, padx=S(9))
        lab = tk.Label(row, text=TAB_WORDS[key], font=("Segoe UI", 10, "bold"), fg=FG2, bg=BG)
        lab.pack(side="left")
        dot = tk.Canvas(row, width=S(8), height=S(8), bg=BG, highlightthickness=0)
        dot.pack(side="left", padx=(S(3), 0))
        line = tk.Frame(it, bg=BG, height=S(2))
        line.pack(side="bottom", fill="x")
        for w in (it, row, lab, dot):
            w.bind("<Button-1>", lambda e, k=key: app.show_page(k))
        Tip(it, tip)
        app.tabs[key] = dict(lab=lab, line=line, dot=dot)
    _right_side(app, top)
    app.server_pill = Pill(top, 20, lambda: SERVER_TIP)
    app.server_pill.pack(side="right")
    app.net_pill = Pill(top, 7, lambda: NET_TIP)
    app.net_pill.pack(side="right", padx=(0, S(8)))
    app.net_pill.set("…", None)


def _terminal_bars(app, root, top):
    try:
        from fpv3d import __version__ as ver
    except ImportError:
        ver = ""
    spin = tk.Label(top, text=" ", font=MONO_B, fg=ACC, bg=BG, width=2)
    spin.pack(side="left", padx=(S(12), 0))
    app.logo = Spinner(root, spin)
    tk.Label(top, text=f"{APP_NAME.upper()} {ver}", font=MONO_B, fg=ACC, bg=BG).pack(side="left")
    sep = lambda: tk.Label(top, text=" ── ", font=MONO, fg=GREY, bg=BG).pack(side="left")  # noqa: E731
    sep()
    app.net_pill = TextStatus(top, 8, NET_TIP)
    app.net_pill.pack(side="left")
    app.net_pill.set("…", None)
    sep()
    app.server_pill = TextStatus(top, 24, SERVER_TIP)
    app.server_pill.pack(side="left")
    _right_side(app, top)
    # the function keys along the bottom: click or press them
    bar = tk.Frame(root, bg=FG)
    bar.grid(row=3, column=0, sticky="ew")
    for i, (key, _, tip) in enumerate(PAGES):
        lab = tk.Label(bar, font=MONO, fg=BG, bg=FG, cursor="hand2", padx=S(6), pady=S(2))
        lab.pack(side="left")
        lab.bind("<Button-1>", lambda e, k=key: app.show_page(k))
        Tip(lab, tip)
        app.tabs[key] = dict(lab=lab, fkey=f"F{i + 1}", word=TAB_WORDS[key].lower(), badge=False)
    tk.Label(bar, text="ctrl+f search  ", font=MONO, fg=BG, bg=FG).pack(side="right")


def set_tab(app, key):
    """Show which page is open."""
    for k, t in app.tabs.items():
        on = k == key
        if TERMINAL:
            t["on"] = on
            _term_text(t)
        else:
            t["lab"].configure(fg=FG if on else FG2)
            t["line"].configure(bg=ACC if on else BG)


def set_badge(app, key, col):
    """A dot next to a page's name (game) or a * after its key (terminal): something there wants a look."""
    t = app.tabs.get(key)
    if not t:
        return
    if TERMINAL:
        t["badge"] = bool(col)
        _term_text(t)
        return
    t["dot"].delete("all")
    if col:
        r = S(3)
        t["dot"].create_oval(S(4) - r, S(4) - r, S(4) + r, S(4) + r, fill=col, outline="")


def _term_text(t):
    txt = f"{t['fkey']} {t['word']}{'*' if t.get('badge') else ''}"
    t["lab"].configure(text=f"[{txt}]" if t.get("on") else f" {txt} ", font=MONO_B if t.get("on") else MONO)
