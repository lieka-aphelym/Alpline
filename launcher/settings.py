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
from .style import ACC, BG, BG2, BG3, FG, FG2, MONO_B, MONO_S, RULE, S, SANS
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
            b = tk.Button(seg, text=m, font=MONO_B, width=6, relief="flat", bd=0, cursor="hand2",
                          command=lambda m=m: self.set_mode(m))
            b.pack(side="left")
            self.mode_btns[m] = b
        self.mode_info = tk.Label(r, font=SANS, fg=FG2, bg=BG, justify="left", anchor="w", wraplength=S(500), height=2)
        self.mode_info.pack(fill="x", pady=(S(4), 0))
        r = row("OPEN PAGES IN")
        seg = tk.Frame(r, bg=RULE, padx=1, pady=1); seg.pack(anchor="w")
        self.where_btns = {}
        for k, label in (("window", f"{APP_NAME} window"), ("browser", "my browser")):
            b = tk.Button(seg, text=label, font=MONO_B, relief="flat", bd=0, cursor="hand2", padx=S(10),
                          command=lambda k=k: self.set_open_in(k))
            b.pack(side="left")
            self.where_btns[k] = b
        tk.Label(r, text=f"{APP_NAME} windows: Edge or Chrome in app mode, no address bar or tabs, own taskbar icon.",
                 font=SANS, fg=FG2, bg=BG, anchor="w", justify="left", wraplength=S(500)).pack(fill="x", pady=(S(4), 0))
        self.set_open_in(self.cfg.get("open_in", "window"), save=False)
        r = row("DESKTOP")
        self.button(r, "[add a desktop shortcut]", self.make_shortcut).pack(anchor="w")
        r = row("YOUR FILES")
        self.data_lab = FitLabel(r, font=MONO_S, fg=FG, bg=BG)
        self.data_lab.set(str(ROOT))
        self.data_lab.pack(fill="x")
        br = tk.Frame(r, bg=BG); br.pack(anchor="w", pady=(S(4), 0))
        self.button(br, "[open folder]", self.open_data_folder).pack(side="left")
        if paths.FROZEN:
            ch = self.button(br, "[change…]", self.change_data_folder)
            ch.pack(side="left", padx=(S(6), 0))
            Tip(ch, f"Use another folder for locations, flights and maps (e.g. an existing project folder). Restarts {APP_NAME}.")
        r = row("ABOUT")
        try:
            from fpv3d import __version__ as ver
        except Exception:
            ver = "?"
        tk.Label(r, text=f"{APP_NAME} {ver} · {'installed app' if paths.FROZEN else 'from the source folder'}",
                 font=MONO_S, fg=FG2, bg=BG, anchor="w").pack(fill="x")

    def set_open_in(self, k, save=True):
        if save:
            self.cfg["open_in"] = k
            self.save()
            if k == "window" and not self.window_ok():
                self.say(f"{APP_NAME} windows need Microsoft Edge or Google Chrome: meanwhile the browser", "bad")
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
