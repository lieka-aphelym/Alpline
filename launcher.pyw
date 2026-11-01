"""fpv3d launcher: pick Full or Lite mode, then open the 3D viewer or the locations map.

Double-click fpv3d.bat (or the desktop shortcut it can create). The window starts the local server in the
chosen mode, opens your browser, and stops the server when you close it. It also tells you whether your
locations are ready to use offline at the field.
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

ROOT = Path(__file__).resolve().parent
SETTINGS = ROOT / "launcher.json"
LOG = ROOT / "logs" / "server.log"

# colours of the viewer's dark theme
BG, BG2, BG3, FG, FG2, RULE, ACC = "#07090c", "#10141a", "#171c24", "#f2f5f8", "#a9b4c2", "#2a313c", "#ffd60a"
MONO = ("Consolas", 10)
SANS = ("Segoe UI", 10)


def python_exe() -> str:
    """The console-less python that runs this window -> its python.exe twin for the server."""
    exe = Path(sys.executable)
    twin = exe.with_name("python.exe") if exe.name.lower() == "pythonw.exe" else exe
    return str(twin if twin.exists() else exe)


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


class Launcher:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_settings()
        self.proc: subprocess.Popen | None = None
        self.running_mode = None
        self.port = None
        root.title("fpv3d")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.quit)

        pad = dict(padx=14)
        tk.Label(root, text="FPV3D", font=("Consolas", 16, "bold"), fg=FG, bg=BG).pack(anchor="w", pady=(12, 0), **pad)
        tk.Label(root, text="FPV flight and signal visualiser", font=SANS, fg=FG2, bg=BG).pack(anchor="w", **pad)

        self.section("MODE")
        self.mode = tk.StringVar(value=self.cfg.get("mode", "full"))
        row = tk.Frame(root, bg=BG); row.pack(fill="x", **pad)
        self.mode_btns = {}
        for m, label in (("full", "full"), ("lite", "lite")):
            b = tk.Button(row, text=label, font=("Consolas", 11, "bold"), width=8, relief="flat", bd=0, cursor="hand2",
                          command=lambda m=m: self.set_mode(m))
            b.pack(side="left", padx=(0, 4))
            self.mode_btns[m] = b
        self.mode_info = tk.Label(root, font=SANS, fg=FG2, bg=BG, justify="left", wraplength=360)
        self.mode_info.pack(anchor="w", pady=(6, 0), **pad)

        self.section("OPEN")
        row = tk.Frame(root, bg=BG); row.pack(fill="x", **pad)
        self.button(row, "[3d viewer]", lambda: self.open("/viewer/"), primary=True).pack(side="left", padx=(0, 6))
        self.button(row, "[locations map]", lambda: self.open("/viewer/map.html")).pack(side="left")
        self.status = tk.Label(root, font=MONO, fg=FG2, bg=BG, justify="left", anchor="w")
        self.status.pack(fill="x", pady=(8, 0), **pad)
        self.stop_btn = self.button(root, "[stop server]", self.stop)
        self.stop_btn.pack(anchor="w", pady=(4, 0), **pad)

        self.section("OFFLINE AT THE FIELD")
        self.offline = tk.Label(root, font=MONO, fg=FG, bg=BG, justify="left", anchor="w", wraplength=360)
        self.offline.pack(fill="x", **pad)
        row = tk.Frame(root, bg=BG); row.pack(fill="x", pady=(6, 0), **pad)
        self.button(row, "[check again]", self.check_offline).pack(side="left", padx=(0, 6))
        self.button(row, "[desktop shortcut]", self.make_shortcut).pack(side="left")
        self.msg = tk.Label(root, font=SANS, fg=FG2, bg=BG, justify="left", anchor="w", wraplength=360)
        self.msg.pack(fill="x", pady=(6, 12), **pad)

        self.set_mode(self.mode.get(), save=False)
        self.refresh_status()
        self.check_offline()

    # ------------------------------------------------------------ widgets
    def section(self, title):
        f = tk.Frame(self.root, bg=BG); f.pack(fill="x", padx=14, pady=(14, 6))
        tk.Label(f, text=title, font=("Consolas", 9, "bold"), fg=FG, bg=BG).pack(side="left")
        tk.Frame(f, bg=RULE, height=1).pack(side="left", fill="x", expand=True, padx=(8, 0), pady=(2, 0))

    def button(self, parent, text, cmd, primary=False):
        return tk.Button(parent, text=text, command=cmd, font=MONO, relief="flat", bd=0, cursor="hand2", padx=10, pady=4,
                         bg=ACC if primary else BG2, fg="#000" if primary else FG,
                         activebackground=ACC if primary else BG3, activeforeground="#000" if primary else FG)

    # ------------------------------------------------------------ mode
    def set_mode(self, m, save=True):
        self.mode.set(m)
        for k, b in self.mode_btns.items():
            on = k == m
            b.configure(bg=ACC if on else BG2, fg="#000" if on else FG2, activebackground=ACC if on else BG3)
        self.mode_info.configure(text=(
            "Full: the whole 3D at full quality, redrawn continuously. New locations: 2 m terrain, "
            "2 m photo, 10 m signal grid, 3D buildings." if m == "full" else
            "Lite: for slower computers. 3D redrawn only when something changes, lighter mesh. New locations: "
            "5 m terrain, lighter photo, 20 m signal grid, no 3D buildings."))
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
        self.stop()
        base = int(self.cfg.get("port", 8000))
        for _ in range(12):                     # same port as before if possible: the browser keeps your settings per port
            if port_free(base):
                break
            time.sleep(0.25)
        port = next((p for p in range(int(self.cfg.get("port", 8000)), int(self.cfg.get("port", 8000)) + 20) if port_free(p)), None)
        if port is None:
            self.msg.configure(text="No free port between 8000 and 8019: close the other fpv3d windows.")
            return False
        args = [python_exe(), "-m", "fpv3d", "serve", "--port", str(port), "--no-browser"]
        if self.mode.get() == "lite":
            args.append("--lite")
        LOG.parent.mkdir(exist_ok=True)
        log = open(LOG, "w", encoding="utf-8", errors="replace")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.port, self.running_mode = port, self.mode.get()
        for _ in range(60):                     # wait until it answers (max ~15 s)
            if self.proc.poll() is not None:
                self.msg.configure(text=f"The server stopped right away. See {LOG.relative_to(ROOT)}.")
                self.proc = None
                self.refresh_status()
                return False
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/mode.js", timeout=0.5).read()
                break
            except Exception:
                self.root.update(); time.sleep(0.25)
        self.refresh_status()
        return True

    def open(self, path):
        if not self.server_alive() or self.running_mode != self.mode.get():
            self.status.configure(text="starting…"); self.root.update()
            if not self.start():
                return
        webbrowser.open(f"http://127.0.0.1:{self.port}{path}")
        self.msg.configure(text="Opened in your browser. Keep this window open while you use fpv3d.")

    def stop(self):
        if self.server_alive():
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc, self.running_mode = None, None
        self.refresh_status()

    def refresh_status(self):
        if self.server_alive():
            note = "" if self.running_mode == self.mode.get() else f"\n(restarts in {self.mode.get()} mode when you open)"
            self.status.configure(text=f"running · {self.running_mode} · http://127.0.0.1:{self.port}{note}", fg=FG)
            self.stop_btn.configure(state="normal")
        else:
            self.status.configure(text="not running (starts when you open)", fg=FG2)
            self.stop_btn.configure(state="disabled")

    def quit(self):
        self.stop()
        self.root.destroy()

    # ------------------------------------------------------------ offline check
    def check_offline(self):
        locs = sorted(p.stem for p in (ROOT / "locations").glob("*.yaml"))
        built = [n for n in locs if (ROOT / "scenes" / n / "scene.json").exists()]
        missing = [n for n in locs if n not in built]
        lines = [f"{len(built)} of {len(locs)} locations built: the 3D viewer works without internet for these."]
        if missing:
            lines.append("not built yet: " + ", ".join(missing[:6]) + (" …" if len(missing) > 6 else ""))
        lines.append("internet: checking…")
        self.offline.configure(text="\n".join(lines))

        def net():
            try:
                urllib.request.urlopen("https://wmts.geo.admin.ch/", timeout=3)
                ok = True
            except urllib.error.HTTPError:
                ok = True                       # the server answered: we are online
            except Exception:
                ok = False
            lines[-1] = ("internet: yes (map background, new downloads and searches work)" if ok else
                         "internet: no. The viewer works; the locations map has no background and "
                         "new locations can only use what is in the cache.")
            self.root.after(0, lambda: self.offline.configure(text="\n".join(lines)))
        threading.Thread(target=net, daemon=True).start()

    # ------------------------------------------------------------ desktop shortcut (Windows)
    def make_shortcut(self):
        if os.name != "nt":
            self.msg.configure(text="Desktop shortcuts are made on Windows only. Start with: python launcher.pyw")
            return
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
        ps = ("$d=[Environment]::GetFolderPath('Desktop');"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'fpv3d.lnk'));"
              f"$s.TargetPath='{pyw}';$s.Arguments='\"{ROOT / 'launcher.pyw'}\"';$s.WorkingDirectory='{ROOT}';"
              "$s.Description='fpv3d: Full or Lite, 3D viewer or locations map';$s.Save()")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.msg.configure(text="Shortcut 'fpv3d' added to your desktop." if r.returncode == 0
                           else f"Could not create the shortcut: {(r.stderr or r.stdout).strip()[:200]}")


if __name__ == "__main__":
    root = tk.Tk()
    Launcher(root)
    root.mainloop()
