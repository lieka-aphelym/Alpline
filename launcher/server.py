"""The local server and the windows it opens: start, stop, Alpline windows or the browser, the status in the header."""
from __future__ import annotations

import os
import subprocess
import time
import tkinter as tk
import urllib.request
import webbrowser

from fpv3d import paths
from fpv3d.brand import APP_NAME

from .common import LOG, ROOT, lan_addresses, port_free
from .style import OK


class ServerMixin:
    """Mixed into Launcher (launcher/app.py): methods only, they share its self."""

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
            self.say(f"No free port between 8000 and 8019: close the other {APP_NAME} windows.")
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
                self.say(f"opening an {APP_NAME} window…")
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
            self.say(f"opened in an {APP_NAME} window · keep this window open")
        else:
            try:
                with open(ROOT / "logs" / "window.log", "a", encoding="utf-8") as f:
                    f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + f"window ({paths.app_browser()}) ended with code {code}\n")
            except OSError:
                pass
            webbrowser.open(url)
            self.say(f"the {APP_NAME} window did not open (see logs/window.log): opened in the browser")

    def stop(self):
        if self.server_alive():
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc, self.running_mode, self.running_share = None, None, False
        self.refresh_status()


    def refresh_status(self):
        if not hasattr(self, "server_pill"):
            return
        on = bool(self.cfg.get("share"))
        sharing = self.server_alive() and self.running_share
        if sharing:
            ip = (lan_addresses() or ["?"])[0]
            https = bool(self.share_info().get("https"))
            self.show_phone(on, True, f"{'https' if https else 'http'}://{ip}:{self.port + (443 if https else 0)}", self.pin(), https)
        else:
            self.show_phone(on, False, None, self.pin() if on else None, False)
        if self.server_alive():
            note = "" if self.running_mode == self.mode.get() else f" →{self.mode.get()}"
            self.server_pill.set(f"server {self.running_mode} :{self.port}{note}", OK)
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
