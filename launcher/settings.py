"""The settings page: Full / Lite, where pages open, your files folder, the desktop shortcut."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path

from fpv3d import paths
from fpv3d.brand import APP_NAME
from fpv3d.brand import BY
from fpv3d.safefile import write_atomic

from .common import APP, ROOT, SETTINGS, venv_exe
from .style import ACC, BG, BG2, BG3, FG, FG2, LOOK, MONO, RULE, RULE2, S, SANS, TERMINAL
from .widgets import FitLabel, Tip


class SettingsPage:
    """Mixed into Launcher (launcher/app.py): methods only, they share its self."""

    # ------------------------------------------------------------ mode
    MODE_TEXT = {"full": "Full: the whole 3D at full quality. New locations: 2 m terrain, 2 m photo, "
                         "10 m signal grid, 3D buildings.",
                 "lite": "Lite: for slower computers: lighter mesh, fewer pixels on sharp screens. New locations: "
                         "5 m terrain, lighter photo, 20 m signal grid, no 3D buildings."}

    def set_mode(self, m, save=True):
        self.mode.set(m)
        for k, b in getattr(self, "mode_btns", {}).items():
            on = k == m
            b.configure(bg=ACC if on else BG2, fg="#000" if on else FG2, activebackground=ACC if on else BG3)
        if hasattr(self, "mode_info"):
            self.mode_info.configure(text=self.MODE_TEXT[m])
        if TERMINAL and hasattr(self, "set_rows"):
            self.draw_settings()
        if save:
            self.cfg["mode"] = m
            self.save()
        self.refresh_status()

    def save(self):
        try:
            write_atomic(SETTINGS, json.dumps(self.cfg, indent=2))
        except OSError:
            pass


    # ------------------------------------------------------------ settings page
    LOOK_TEXT = ("game: the places as pictures. terminal: one amber colour, everything on keys. Same places, keys "
                 f"and actions; {APP_NAME} restarts in the new look.")
    WHERE_TEXT = f"{APP_NAME} windows: Edge or Chrome in app mode, no address bar or tabs, own taskbar icon."

    def build_settings_page(self, parent):
        """The same settings in both looks. Game look: one large row per setting, its explanation beside it, the look
        as two pictures (H4 of the design canvas). Terminal look: a config screen, one line per setting; Up / Down
        choose, Left / Right change, Enter does the line's action."""
        (self._settings_terminal if TERMINAL else self._settings_game)(parent)

    def _version(self):
        try:
            from fpv3d import __version__ as ver
        except Exception:                                   # noqa: BLE001
            ver = "?"
        return f"{APP_NAME} {ver} · {'installed app' if paths.FROZEN else 'from the source folder'}"

    # ---- game look
    def _settings_game(self, parent):
        col = self.page_frame(parent, "SETTINGS", width=900)

        def row(label, help_):
            r = tk.Frame(col, bg=BG)
            r.pack(fill="x", pady=(S(10), 0))
            r.columnconfigure(0, minsize=S(300)); r.columnconfigure(1, weight=1)
            tk.Frame(col, bg=RULE, height=1).pack(fill="x", pady=(S(10), 0))
            left = tk.Frame(r, bg=BG)
            left.grid(row=0, column=0, sticky="nw")
            tk.Label(left, text=label, font=("Segoe UI", 12, "bold"), fg=FG, bg=BG, anchor="w").pack(fill="x")
            h = tk.Label(left, text=help_, font=SANS, fg=FG2, bg=BG, anchor="nw", justify="left", wraplength=S(280))
            h.pack(fill="x")
            right = tk.Frame(r, bg=BG)
            right.grid(row=0, column=1, sticky="nw", padx=(S(20), 0))
            return right, h

        def seg(parent, items, cmd, store):
            f = tk.Frame(parent, bg=RULE, padx=1, pady=1)
            f.pack(anchor="w")
            for k, label in items:
                b = tk.Button(f, text=label, font=("Consolas", 11, "bold"), relief="flat", bd=0, cursor="hand2",
                              padx=S(16), pady=S(6), command=lambda k=k: cmd(k))
                b.pack(side="left")
                store[k] = b
        r, _ = row("Look", self.LOOK_TEXT)
        tiles = tk.Frame(r, bg=BG)
        tiles.pack(anchor="w")
        self._look_tile(tiles, "game").pack(side="left", padx=(0, S(12)))
        self._look_tile(tiles, "terminal").pack(side="left")
        r, self.mode_info = row("Quality", "")
        self.mode_btns = {}
        seg(r, (("full", "FULL"), ("lite", "LITE")), self.set_mode, self.mode_btns)
        r, _ = row("Open pages in", self.WHERE_TEXT)
        self.where_btns = {}
        seg(r, (("window", f"{APP_NAME.upper()} WINDOW"), ("browser", "MY BROWSER")), self.set_open_in, self.where_btns)
        self.set_open_in(self.cfg.get("open_in", "window"), save=False)
        r, _ = row("Desktop", f"A shortcut that starts {APP_NAME}.")
        self.button(r, "[add a desktop shortcut]", self.make_shortcut).pack(anchor="w")
        r, _ = row("Your files", "Places, flights, maps and logs.")
        self.data_lab = FitLabel(r, font=MONO, fg=FG, bg=BG)
        self.data_lab.set(str(ROOT))
        self.data_lab.pack(fill="x")
        br = tk.Frame(r, bg=BG)
        br.pack(anchor="w", pady=(S(6), 0))
        self.button(br, "[open folder]", self.open_data_folder).pack(side="left")
        if paths.FROZEN:
            ch = self.button(br, "[change…]", self.change_data_folder)
            ch.pack(side="left", padx=(S(6), 0))
            Tip(ch, f"Use another folder for locations, flights and maps (e.g. an existing project folder). Restarts {APP_NAME}.")
        r, _ = row("About", "")
        tk.Label(r, text=self._version(), font=MONO, fg=FG2, bg=BG, anchor="w").pack(fill="x")

    def _look_tile(self, parent, k):
        """A small picture of a look, to click: the selected place's photo for game, the flower in amber for terminal."""
        on = k == LOOK
        f = tk.Frame(parent, bg=BG2, highlightthickness=S(2) if on else 1, highlightbackground=ACC if on else RULE2,
                     cursor="hand2")
        w, h = S(200), S(104)
        cv = tk.Canvas(f, width=w, height=h, highlightthickness=0, bd=0, bg="#0b0700" if k == "terminal" else BG)
        cv.pack()
        if k == "game":
            self._game_tile = cv                     # its photo comes once the places are known (paint_look_tile)
            cv.create_text(w // 2, h // 2, text="▶", fill=FG2, font=("Segoe UI", 20))
        else:
            try:
                flower = (APP / "viewer" / "brand" / "flower.txt").read_text(encoding="utf-8")
            except OSError:
                flower = ""
            cv.create_text(w // 2, h // 2, text=flower, fill="#ffb000", font=("Consolas", 4), justify="left")
        lab = tk.Label(f, text=k.upper(), font=("Consolas", 10, "bold"), fg=FG if on else FG2, bg=BG2, anchor="w",
                       padx=S(8), pady=S(4))
        lab.pack(fill="x")
        for x in (f, cv, lab):
            x.bind("<Button-1>", lambda e: self.set_look(k))
        return f

    def paint_look_tile(self):
        """The game look's tile shows the selected place's photo (or the first built one's): called when the page is
        opened, by then the places are known."""
        cv = getattr(self, "_game_tile", None)
        if cv is None or getattr(self, "_look_img", None) is not None:
            return
        cur = self.map.current()
        for l in [cur] + list(self.map.locs):
            f = ROOT / "scenes" / l["name"] / "ortho.jpg" if l else None
            if l and l.get("built") and f.exists():
                try:
                    from .startup import photo_fill
                    self._look_img = photo_fill(f, int(cv.cget("width")), int(cv.cget("height")), light=.8, left_shade=0)
                except Exception:                           # noqa: BLE001  (a damaged photo: the plain tile stays)
                    return
                cv.delete("all")
                cv.create_image(0, 0, image=self._look_img, anchor="nw")
                return

    # ---- terminal look: a config screen
    def _settings_terminal(self, parent):
        col = self.page_frame(parent, "SETTINGS", width=900)
        self.set_rows = []                     # (label, kind, values / action)
        self.look_next = LOOK                 # ← → only choose it; Enter restarts in it (settings_enter)
        self.set_rows.append(("look", "choice", ("game", "terminal"), lambda: self.look_next,
                              lambda v: setattr(self, "look_next", v)))
        self.set_rows.append(("quality", "choice", ("full", "lite"), lambda: self.mode.get(), self.set_mode))
        self.set_rows.append(("open pages in", "choice", ("window", "browser"), lambda: self.cfg.get("open_in", "window"),
                              self.set_open_in))
        self.set_rows.append(("desktop", "action", "add a shortcut", None, self.make_shortcut))
        self.set_rows.append(("your files", "action", "open folder", lambda: str(ROOT), self.open_data_folder))
        if paths.FROZEN:
            self.set_rows.append(("", "action", "use another folder…", None, self.change_data_folder))
        self.set_rows.append(("about", "info", self._version(), None, None))
        self.set_at = 0
        self.set_lines = []
        for i in range(len(self.set_rows)):
            lab = tk.Label(col, font=MONO, fg=FG, bg=BG, anchor="w", cursor="hand2")
            lab.pack(fill="x", pady=S(3))
            lab.bind("<Button-1>", lambda e, i=i: self.settings_click(i))
            self.set_lines.append(lab)
        self.set_help = tk.Label(col, font=MONO, fg=FG2, bg=BG, anchor="w", justify="left", wraplength=S(860))
        self.set_help.pack(fill="x", pady=(S(16), 0))
        tk.Label(col, text="↑ ↓ choose    ← → change    enter apply", font=MONO, fg=ACC, bg=BG,
                 anchor="w").pack(fill="x", pady=(S(16), 0))
        self.draw_settings()

    def draw_settings(self):
        for i, (label, kind, values, get, _) in enumerate(self.set_rows):
            on = i == self.set_at
            if kind == "choice":
                cur = get()
                shown = "  ".join(f"[ {v} ]" if v == cur else f"  {v}  " for v in values)
                text = f"{'▶' if on else ' '} {label:<15} ◀ {shown} ▶"
            elif kind == "action":
                extra = f"   {get()}" if get else ""
                text = f"{'▶' if on else ' '} {label:<15} [ {values} ]{extra}"
            else:
                text = f"  {label:<15} {values}"
            self.set_lines[i].configure(text=text, fg=BG if on else FG, bg=ACC if on else BG)
        label, kind, values, get, _ = self.set_rows[self.set_at]
        look = self.LOOK_TEXT + ("  [enter] restarts in it now." if self.look_next != LOOK else "")
        self.set_help.configure(text={"look": look, "quality": self.MODE_TEXT[self.mode.get()],
                                      "open pages in": self.WHERE_TEXT}.get(label, ""))

    def settings_move(self, step):
        self.set_at = max(0, min(len(self.set_rows) - 1, self.set_at + step))
        self.draw_settings()

    def settings_change(self, step):
        label, kind, values, get, act = self.set_rows[self.set_at]
        if kind == "choice":
            i = values.index(get()) if get() in values else 0
            act(values[(i + step) % len(values)])
            self.draw_settings()

    def settings_enter(self):
        label, kind, values, get, act = self.set_rows[self.set_at]
        if kind == "action":
            act()
        elif label == "look":
            self.set_look(get())                      # the look restarts the launcher: only on Enter, not on ← →
        elif kind == "choice":
            self.settings_change(1)

    def settings_click(self, i):
        if i == self.set_at:
            self.settings_enter()
        else:
            self.set_at = i
            self.draw_settings()

    def set_look(self, k):
        """Every page takes its colours when the window is built (style.py), so a new look needs a new window."""
        if k == LOOK:
            return
        self.cfg["look"] = k
        self.save()
        self.quit()
        subprocess.Popen([sys.executable] + sys.argv[1:])

    def set_open_in(self, k, save=True):
        if save:
            self.cfg["open_in"] = k
            self.save()
            if k == "window" and not self.window_ok():
                self.say(f"{APP_NAME} windows need Microsoft Edge or Google Chrome: meanwhile the browser", "bad")
        for key, b in getattr(self, "where_btns", {}).items():
            on = key == self.cfg.get("open_in", "window")
            b.configure(bg=ACC if on else BG2, fg="#000" if on else FG2, activebackground=ACC if on else BG3)
        if TERMINAL and hasattr(self, "set_rows"):
            self.draw_settings()

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
        pick = filedialog.askdirectory(parent=self.root, title=f"Folder for {APP_NAME}'s files", initialdir=str(ROOT))
        if not pick or Path(pick) == ROOT:
            return
        if not messagebox.askyesno(f"{APP_NAME}", f"Use {pick} for your files? {APP_NAME} restarts.", parent=self.root):
            return
        paths.set_data(Path(pick))
        self.quit()
        subprocess.Popen([sys.executable] + sys.argv[1:])


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
              f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d '{APP_NAME}.lnk'));"
              f"$s.TargetPath='{target}';$s.Arguments='{arg}';$s.WorkingDirectory='{ROOT}';"
              f"$s.IconLocation='{icon},0';"
              f"$s.Description='{APP_NAME} by {BY}: FPV line of sight on Swiss terrain';$s.Save()")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.say(f"shortcut '{APP_NAME}' added to your desktop" if r.returncode == 0
                 else f"could not create the shortcut: {(r.stderr or r.stdout).strip()[:120]}")
