"""The launcher's own widgets: buttons, tooltips, labels that fit, status pills, rail icons and the logo animation."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from fpv3d.brand import APP_NAME

from .common import APP
from .style import ACC, BAD, BG, BG2, BG3, FG, FG2, GREY, MONO, MONO_S, RULE, RULE2, S, SANS


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


class Btn(tk.Button):
    """A flat [button] in one of three kinds. A switched-off button always looks switched off (grey on dark), also a
    primary one: Tk alone would keep it yellow with unreadable text."""
    def __init__(self, parent, text, cmd, primary=False, small=False, danger=False):
        self.kind = "primary" if primary else "danger" if danger else "normal"
        super().__init__(parent, text=text, command=cmd, font=MONO_S if small else MONO, relief="flat", bd=0,
                         padx=6 if small else 10, pady=1 if small else 4, disabledforeground=GREY,
                         highlightthickness=1)
        self._paint()

    def _paint(self):
        off = str(self["state"]) == "disabled"
        bg, fg, edge = {"primary": (ACC, "#000", ACC), "danger": (BG2, BAD, BAD)}.get(self.kind, (BG2, FG, RULE2))
        if off:
            bg, edge = BG2, RULE
        hover = ACC if self.kind == "primary" else BAD if self.kind == "danger" else BG3
        super().configure(bg=bg, fg=fg, activebackground=bg if off else hover,
                          activeforeground="#000" if self.kind == "primary" else "#fff" if self.kind == "danger" else FG,
                          highlightbackground=edge, highlightcolor=edge, cursor="arrow" if off else "hand2")

    def configure(self, cnf=None, **kw):
        out = super().configure(cnf, **kw)
        if "state" in kw:
            self._paint()
        return out
    config = configure


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
        self.lab = tk.Label(self, font=MONO_S, fg=FG2, bg=BG, width=chars, anchor="w")
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


# the pages: key, label, tooltip (in this order in the header or the key bar, F1 to F7: chrome.py)
PAGES = (("home", "home", "The chosen place, big: fly it in 3D (F1)"),
         ("map", "map", "Your locations on the map"),
         ("drone", "drone", "Drone and radio on USB: download the blackbox, start a live flight"),
         ("phone", "phone", f"Open {APP_NAME} on your phone (same Wi-Fi or the phone's hotspot)"),
         ("checks", "checks", f"Run {APP_NAME}'s own tests on this computer"),
         ("disk", "files", "Your files: sizes, clean-up / start fresh, backup and restore"),
         ("settings", "settings", "Full / Lite, where pages open, desktop shortcut, your files"))


class LogoAnim:
    """The logo in the top bar: spins up once when the launcher opens, spins steadily while it works (starting the
    server, checking phone access, cleaning the cache). Frames: viewer/brand/anim-*-<size>.png, made from the web logo
    by tools/render_logo_frames.py. Without them the still logo is shown."""
    MS = {"intro": 60, "busy": 70}

    def __init__(self, root, parent, px):
        self.root, self.n_busy, self.mode, self.i, self.job = root, 0, None, 0, None
        self.still = brand_image("logo-dark", px)
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
