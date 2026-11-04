"""Alpline (by lieka) launcher: pick Full or Lite mode, see your locations on a map of Switzerland, open the 3D viewer.

Double-click Alpline.bat (or the desktop shortcut it can create), or start the installed Alpline app. The window
starts the local server in the chosen mode, opens Alpline windows (or your browser), and stops the server when you
close it. It also tells you whether your locations are ready to use offline at the field.

Packaged app: the same file is Alpline.exe; `Alpline.exe --window <url>` opens one Alpline window (fpv3d.appwin).
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fpv3d import paths  # noqa: E402  (standard library only)

APP = paths.APP                                      # the program: viewer pages, logo frames, icon
ROOT = paths.DATA                                    # your files: launcher.json, logs, scenes, cache, locations
SETTINGS = ROOT / "launcher.json"
LOG = ROOT / "logs" / "server.log"

# colours of the viewer's dark theme
BG, BG2, BG3, FG, FG2, RULE, ACC = "#07090c", "#10141a", "#171c24", "#f2f5f8", "#a9b4c2", "#2a313c", "#ffd60a"
MONO = ("Consolas", 10)
SANS = ("Segoe UI", 10)
UI = 1.0                                             # screen scaling (1.5 on a 150 % Windows display), set at start


def S(v: float) -> int:
    """pixel size scaled for the screen (fonts in points scale by themselves)"""
    return round(v * UI)


def venv_exe(name: str) -> str:
    """python.exe / pythonw.exe of the project's virtual environment (.venv), where numpy, rasterio, PyYAML...
    are installed. Asked for explicitly: with the Microsoft Store Python, sys.executable inside a venv points
    to the base Python, which does not have those libraries."""
    for d in (APP / ".venv" / "Scripts", APP / ".venv" / "bin", Path(sys.prefix) / "Scripts", Path(sys.prefix) / "bin"):
        for n in (name, name.replace(".exe", ""), "python3" if name.startswith("python.") else name):
            if (d / n).exists():
                return str(d / n)
    exe = Path(sys.executable)
    twin = exe.with_name(name)
    return str(twin if twin.exists() else exe)


def python_exe() -> str:
    """The python that runs the server (console version, no window: CREATE_NO_WINDOW)."""
    return venv_exe("python.exe")


def lan_addresses() -> list:
    """IPv4 addresses of this computer on its local networks, best guess first (fpv3d.netinfo, shared with the server)."""
    try:
        from fpv3d.netinfo import lan_addresses as la
        return la()
    except Exception:
        return []


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


import math
import re
from tkinter import ttk

GREY = "#7d8796"


class Tip:
    """Small hover tooltip (the explanations live here instead of on the screen)."""
    def __init__(self, w, text):
        self.w, self.text, self.top = w, text, None
        w.bind("<Enter>", self.show, add="+"); w.bind("<Leave>", self.hide, add="+")

    def show(self, _=None):
        t = self.text() if callable(self.text) else self.text
        if not t:
            return
        self.top = tk.Toplevel(self.w); self.top.wm_overrideredirect(True)
        self.top.wm_geometry(f"+{self.w.winfo_rootx()}+{self.w.winfo_rooty() + self.w.winfo_height() + 4}")
        tk.Label(self.top, text=t, font=SANS, fg=FG, bg=BG3, justify="left", wraplength=S(340), padx=S(8), pady=S(5),
                 highlightthickness=1, highlightbackground=RULE).pack()

    def hide(self, _=None):
        if self.top:
            self.top.destroy(); self.top = None


def is_sim(t: dict) -> bool:
    """Training-flight logs: named <location>_sim_<date> or stored under logs/sim/."""
    return "_sim_" in t.get("name", "") or bool(re.search(r"[\\/]logs[\\/]sim[\\/]", t.get("source", "")))


def flight_stats(name: str) -> dict:
    """Real and simulator logs of a built location (from scenes/<name>/scene.json)."""
    out = {"real": 0, "sim": 0, "real_s": 0.0, "sim_s": 0.0, "last": None, "built": None}
    f = ROOT / "scenes" / name / "scene.json"
    if not f.exists():
        return out
    out["built"] = f.stat().st_mtime
    try:
        tracks = json.loads(f.read_text(encoding="utf-8")).get("tracks", [])
    except Exception:
        return out
    for t in tracks:
        k = "sim" if is_sim(t) else "real"
        out[k] += 1
        out[k + "_s"] += float(t.get("duration_s") or 0)
        p = ROOT / "scenes" / name / t.get("file", "")
        if p.exists():
            out["last"] = max(out["last"] or 0, p.stat().st_mtime)
    return out


def fmt_dur(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600} h {s % 3600 // 60:02d}" if s >= 3600 else f"{s // 60} min" if s >= 60 else f"{s} s"


def fmt_day(ts) -> str:
    return time.strftime("%d %b %Y", time.localtime(ts)) if ts else "–"


class Launcher:
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
        root.title("Alpline by lieka")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        try:                                       # window / taskbar icon: the red Alpline square
            self.icon = tk.PhotoImage(file=str(APP / "viewer" / "brand" / "icon-64.png"))
            root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        self.style()

        # ---- top bar: title, mode, open buttons
        top = tk.Frame(root, bg=BG); top.pack(fill="x", padx=14, pady=(10, 8))
        self.logo = LogoAnim(root, top, S(30))           # spins up once now, spins while the launcher works
        tk.Label(top, text="ALPLINE", font=("Consolas", 16, "bold"), fg=FG, bg=BG).pack(side="left")
        tk.Label(top, text="by lieka", font=("Consolas", 9), fg=FG2, bg=BG).pack(side="left", padx=(6, 0), pady=(6, 0))
        self.mode = tk.StringVar(value=self.cfg.get("mode", "full"))
        seg = tk.Frame(top, bg=RULE, padx=1, pady=1); seg.pack(side="left", padx=(16, 8))
        self.mode_btns = {}
        for m in ("full", "lite"):
            b = tk.Button(seg, text=m, font=("Consolas", 10, "bold"), width=6, relief="flat", bd=0, cursor="hand2",
                          command=lambda m=m: self.set_mode(m))
            b.pack(side="left")
            self.mode_btns[m] = b
        Tip(self.mode_btns["full"], "Full: the whole 3D at full quality, redrawn continuously. New locations: 2 m terrain, "
                                    "2 m photo, 10 m signal grid, 3D buildings.")
        Tip(self.mode_btns["lite"], "Lite: for slower computers. 3D redrawn only when something changes, lighter mesh. "
                                    "New locations: 5 m terrain, lighter photo, 20 m signal grid, no 3D buildings.")
        self.mode_info = tk.Label(top, font=SANS, fg=FG2, bg=BG); self.mode_info.pack(side="left")
        self.stop_btn = self.button(top, "[stop]", self.stop); self.stop_btn.pack(side="right")
        self.share_btn = self.button(top, "[phone]", self.toggle_share); self.share_btn.pack(side="right", padx=(0, 14))
        Tip(self.share_btn, "Share on your network: open Alpline on your phone (same Wi-Fi, or the phone's hotspot). "
                            "The phone can look, fly and build; deleting and renaming stay on this computer.")
        Tip(self.stop_btn, "Stop the local server (closing this window does it too).")
        self.button(top, "[locations map]", lambda: self.open("/viewer/map.html")).pack(side="right", padx=(0, 6))
        self.button(top, "[3d viewer]", lambda: self.open("/viewer/"), primary=True).pack(side="right", padx=(0, 6))
        tk.Frame(root, bg=RULE, height=1).pack(fill="x")

        # ---- middle: map | locations table + details card
        mid = tk.Frame(root, bg=BG); mid.pack(fill="both", padx=14, pady=10)
        self.map = SwissMap(self, mid)
        right = tk.Frame(mid, bg=BG, width=S(390), height=self.map.h + S(36))   # fixed size: the window never jumps
        right.pack(side="left", fill="y", padx=(12, 0)); right.pack_propagate(False)
        self.loc_title = self.section("LOCATIONS", right)
        self.table = Table(self, right, height=max(6, (self.map.h - S(205)) // S(21)))
        self.card = Card(self, right)

        # ---- status bar
        tk.Frame(root, bg=RULE, height=1).pack(fill="x")
        bar = tk.Frame(root, bg=BG); bar.pack(fill="x", padx=14, pady=5)
        self.status = tk.Label(bar, font=("Consolas", 9), fg=FG2, bg=BG); self.status.pack(side="left")
        self.offline = tk.Label(bar, font=("Consolas", 9), fg=FG2, bg=BG); self.offline.pack(side="left", padx=(18, 0))
        Tip(self.offline, self.offline_tip)
        self.net = tk.Label(bar, font=("Consolas", 9), fg=FG2, bg=BG); self.net.pack(side="left", padx=(18, 0))
        Tip(self.net, lambda: "Internet is used for the map background, new downloads and place search. Without it the "
                              "3D viewer still works for built locations." if self.online is not None else "")
        self.flights = tk.Label(bar, font=("Consolas", 9), fg=FG2, bg=BG); self.flights.pack(side="left", padx=(18, 0))
        self.phone = tk.Label(bar, font=("Consolas", 9, "bold"), fg=ACC, bg=BG); self.phone.pack(side="left", padx=(18, 0))
        self.qr_btn = self.button(bar, "[qr]", self.show_qr, small=True)
        Tip(self.qr_btn, "Show a QR code to scan with the phone's camera.")
        sc = self.button(bar, "[shortcut]", self.make_shortcut, small=True); sc.pack(side="right")
        self.where_btn = self.button(bar, self.where_text(), self.toggle_open_in, small=True)
        self.where_btn.pack(side="right", padx=(0, 6))
        Tip(self.where_btn, "Where the 3D viewer and the locations map open: in Alpline windows (no browser bar) "
                            "or in your web browser.")
        Tip(sc, "Add an 'Alpline' shortcut to your desktop.")
        dk = self.button(bar, "[disk]", self.disk_dialog, small=True); dk.pack(side="right", padx=(0, 6))
        Tip(dk, "How much space Alpline uses, and clean-up (deleted locations, unused map tiles).")
        ck = self.button(bar, "[check]", self.check_offline, small=True); ck.pack(side="right", padx=(0, 6))
        Tip(ck, "Reload the locations and check the internet again.")
        self.msg = tk.Label(bar, font=SANS, fg=ACC, bg=BG); self.msg.pack(side="right", padx=(0, 12))

        self.set_mode(self.mode.get(), save=False)
        self.check_offline()
        if self.cfg.get("share") and os.name == "nt":         # sharing was left on: check the phone can get in
            root.after(1200, lambda: self.check_phone_access(ask=True))

    # ------------------------------------------------------------ widgets
    @staticmethod
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

    def style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("L.Treeview", background=BG2, fieldbackground=BG2, foreground=FG, font=MONO, rowheight=S(21),
                     borderwidth=0, relief="flat")
        st.map("L.Treeview", background=[("selected", ACC)], foreground=[("selected", "#000")])
        st.configure("L.Treeview.Heading", background=BG, foreground=FG2, font=("Consolas", 8, "bold"), relief="flat",
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

    def button(self, parent, text, cmd, primary=False, small=False):
        return tk.Button(parent, text=text, command=cmd, font=("Consolas", 9 if small else 10), relief="flat", bd=0,
                         cursor="hand2", padx=6 if small else 10, pady=1 if small else 4,
                         bg=ACC if primary else BG2, fg="#000" if primary else FG,
                         activebackground=ACC if primary else BG3, activeforeground="#000" if primary else FG)

    def say(self, text):
        self.msg.configure(text=text)
        self.root.after(8000, lambda: self.msg.cget("text") == text and self.msg.configure(text=""))

    # ------------------------------------------------------------ mode
    def set_mode(self, m, save=True):
        self.mode.set(m)
        for k, b in self.mode_btns.items():
            on = k == m
            b.configure(bg=ACC if on else BG2, fg="#000" if on else FG2, activebackground=ACC if on else BG3)
        self.mode_info.configure(text="full quality" if m == "full" else "lighter, for slower computers")
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
            self.say("No free port between 8000 and 8019: close the other Alpline windows.")
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
            self.status.configure(text="○ starting…", fg=FG2); self.root.update()
            if not self.start():
                return
        self.open_url(f"http://127.0.0.1:{self.port}{path}")

    # ------------------------------------------------------------ Alpline windows (or the browser)
    def window_ok(self) -> bool:
        """pywebview available (always in the packaged app; in the .venv when installed)."""
        if self._win_ok is None:
            if paths.FROZEN:
                self._win_ok = True
            else:
                try:
                    self._win_ok = subprocess.run([python_exe(), "-c", "import webview"], capture_output=True, timeout=20,
                                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode == 0
                except Exception:
                    self._win_ok = False
        return self._win_ok

    def open_url(self, url):
        if self.cfg.get("open_in", "window") == "window" and self.window_ok():
            try:
                self.windows = [w for w in self.windows if w.poll() is None]
                self.windows.append(subprocess.Popen(paths.window_cmd(url), cwd=str(APP),
                                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
                self.say("opened in an Alpline window · keep this window open")
                return
            except OSError:
                pass
        webbrowser.open(url)
        self.say("opened in your browser · keep this window open")

    def toggle_open_in(self):
        self.cfg["open_in"] = "browser" if self.cfg.get("open_in", "window") == "window" else "window"
        self.save()
        self.where_btn.configure(text=self.where_text())
        if self.cfg["open_in"] == "window" and not self.window_ok():
            self.say("Alpline windows need pywebview: pip install -r requirements.txt (in the .venv), meanwhile the browser")

    def where_text(self):
        return "[open in: window]" if self.cfg.get("open_in", "window") == "window" else "[open in: browser]"

    def stop(self):
        if self.server_alive():
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc, self.running_mode, self.running_share = None, None, False
        self.refresh_status()

    # ------------------------------------------------------------ phone (share on the network)
    def pin(self) -> str:
        """6-digit PIN the phone needs once (kept in launcher.json so the phone's home-screen icon keeps working)."""
        if not str(self.cfg.get("pin", "")).isdigit():
            import secrets
            self.cfg["pin"] = f"{secrets.randbelow(10 ** 6):06d}"; self.save()
        return str(self.cfg["pin"])

    def https_ready(self) -> bool:
        """The secure page for the phone needs the 'cryptography' library in .venv; offer to install it once."""
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if paths.FROZEN:
            return True                                   # the packaged app comes with it
        ok = subprocess.run([python_exe(), "-c", "import cryptography"], capture_output=True, creationflags=flags).returncode == 0
        if ok or self.cfg.get("no_https"):
            return ok
        from tkinter import messagebox
        if not messagebox.askyesno("Alpline: phone", "For a secure (https) page on the phone, Alpline needs one more library "
                                   "(cryptography, about 5 MB). It lets the phone keep its screen on during a live flight.\n\n"
                                   "Install it now? (needs internet)", parent=self.root):
            self.cfg["no_https"] = True; self.save()
            return False
        self.status.configure(text="○ installing cryptography…", fg=FG2); self.root.update()
        r = subprocess.run([python_exe(), "-m", "pip", "install", "cryptography==50.0.2"], capture_output=True, text=True,
                           creationflags=flags)
        if r.returncode != 0:
            self.say("could not install cryptography: the phone uses http")
            return False
        return True

    def toggle_share(self):
        self.cfg["share"] = not self.cfg.get("share")
        self.save()
        if self.cfg["share"]:
            self.https_ready()
            if not self.server_alive() or self.running_share != True:
                self.status.configure(text="○ starting…", fg=FG2); self.root.update()
                if not self.start():
                    return
            if os.name == "nt":
                self.check_phone_access(ask=True)
        elif self.server_alive():
            self.start()                          # back to this computer only
        self.refresh_status()

    # Windows blocks connections from other devices unless (1) the firewall lets them in and (2) the Wi-Fi is a
    # "Private" network (on "Public" networks Windows refuses them, whatever the firewall says for Private).
    RULE = "Alpline (phone)"

    def ps(self, cmd: str, timeout=30) -> str:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd], capture_output=True,
                           text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=timeout)
        return (r.stdout or "").strip()

    # what can stop a phone: written to logs/phone_check.txt so it can be read when something doesn't work
    CHECK = r"""
$r = [ordered]@{}
$r.nets = @(Get-NetConnectionProfile | ForEach-Object { @{name=$_.Name; alias=$_.InterfaceAlias; category=[string]$_.NetworkCategory} })
$r.ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object { "$($_.InterfaceAlias) $($_.IPAddress)" })
$a = Get-NetFirewallRule -DisplayName 'Alpline (phone)' -ErrorAction SilentlyContinue
$r.rule = @($a | ForEach-Object { @{enabled=[string]$_.Enabled; profile=[string]$_.Profile; action=[string]$_.Action; ports=(@($_ | Get-NetFirewallPortFilter).LocalPort -join ',')} })
$r.pyblock = @(Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue | Where-Object { $_.Program -like '*python*' } | ForEach-Object {
  $x = $_ | Get-NetFirewallRule; @{name=$x.DisplayName; dir=[string]$x.Direction; action=[string]$x.Action; enabled=[string]$x.Enabled; profile=[string]$x.Profile; program=$_.Program} })
$r.fw = @(Get-NetFirewallProfile -ErrorAction SilentlyContinue | ForEach-Object { @{name=$_.Name; enabled=[string]$_.Enabled; inbound=[string]$_.DefaultInboundAction; local=[string]$_.AllowLocalFirewallRules} })
$r | ConvertTo-Json -Depth 4 -Compress
"""

    def check_phone_access(self, ask=False):
        self.logo.busy(True)

        def work():
            try:
                work_()
            finally:
                self.root.after(0, lambda: self.logo.busy(False))

        def work_():
            try:
                d = json.loads(self.ps(self.CHECK) or "{}")
            except Exception as ex:
                return self.root.after(0, lambda n=ex.__class__.__name__: self.say(f"could not check the network ({n})"))
            try:
                (ROOT / "logs").mkdir(exist_ok=True)
                (ROOT / "logs" / "phone_check.txt").write_text(json.dumps(d, indent=2), encoding="utf-8")
            except OSError:
                pass
            self.root.after(0, lambda: self.phone_access_result(d, ask))
        threading.Thread(target=work, daemon=True).start()

    def phone_access_result(self, d, ask):
        from tkinter import messagebox
        lst = lambda v: v if isinstance(v, list) else ([v] if v else [])
        nets, rules, py, fw = lst(d.get("nets")), lst(d.get("rule")), lst(d.get("pyblock")), lst(d.get("fw"))
        public = [n for n in nets if n.get("category") == "Public"]
        rule_ok = any(r.get("enabled") == "True" and r.get("action") == "Allow" and "8443" in str(r.get("ports", "")) for r in rules)
        blocks = [b for b in py if b.get("dir") == "Inbound" and b.get("action") == "Block" and b.get("enabled") == "True"]
        managed = any(f.get("local") == "False" for f in fw)          # company PCs: local rules are ignored
        problems = []
        if not rule_ok:
            problems.append("the Windows firewall has no rule letting the phone in")
        if blocks:
            problems.append(f"{len(blocks)} firewall rule(s) block Python (often created when the 'allow access' "
                            "question was closed or answered 'cancel')")
        if public:
            problems.append("your network " + ", ".join(f"{n.get('name')} ({n.get('alias')})" for n in public)
                            + " is set to Public")
        if managed:
            problems.append("this PC's firewall is managed by an organisation (local rules are ignored)")
        if not problems:
            self.say("phone access: ok · if it still doesn't load, see logs/phone_check.txt")
            return
        if not ask or (managed and len(problems) == 1):
            self.say("phone access: " + "; ".join(problems))
            return
        fix = ("The phone can't reach this computer:\n• " + "\n• ".join(problems) + "\n\n"
               "Fix it now? Windows asks for administrator permission once. This will:\n"
               "• allow incoming connections to Alpline (ports 8000-8019 and 8443-8462 only)\n"
               + ("• switch off the rules that block Python\n" if blocks else "")
               + ("• set " + ", ".join(n.get("name", "?") for n in public) + " to Private "
                  "(fine for your home Wi-Fi or your own phone hotspot)\n" if public else "")
               + "\nClick [phone] again later to stop sharing.")
        if not messagebox.askyesno("Alpline: phone access", fix, parent=self.root):
            self.say("phone access not fixed: the phone won't load the page")
            return
        log = ROOT / "logs" / "phone_fix.txt"
        cmds = [f"Start-Transcript -Path '{log}' -Force | Out-Null",
                f"Get-NetFirewallRule -DisplayName '{self.RULE}' -ErrorAction SilentlyContinue | Remove-NetFirewallRule",
                f"New-NetFirewallRule -DisplayName '{self.RULE}' -Direction Inbound -Action Allow -Protocol TCP "
                "-LocalPort 8000-8019,8443-8462 -Profile Any | Out-Null"]
        for b in blocks:
            cmds.append(f"Get-NetFirewallRule -DisplayName '{b.get('name')}' -ErrorAction SilentlyContinue | "
                        "Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' } | Disable-NetFirewallRule")
        for n in public:
            cmds.append(f"Set-NetConnectionProfile -InterfaceAlias '{n.get('alias')}' -NetworkCategory Private")
        cmds.append("Stop-Transcript | Out-Null")
        import base64
        enc = base64.b64encode("; ".join(cmds).encode("utf-16-le")).decode()   # no quoting problems

        def run():
            try:                                  # one elevated PowerShell (UAC prompt), then check again
                self.ps("Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
                        f"-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{enc}'", timeout=180)
            except Exception:
                pass
            self.root.after(0, lambda: self.check_phone_access(ask=False))
        self.say("Windows will ask for permission…")
        threading.Thread(target=run, daemon=True).start()

    def share_info(self) -> dict:
        try:
            return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/share", timeout=1).read())
        except Exception:
            return {}

    def show_qr(self):
        if self.server_alive():
            self.open_url(f"http://127.0.0.1:{self.port}/viewer/share.html")

    def refresh_status(self):
        if not hasattr(self, "status"):
            return
        on = bool(self.cfg.get("share"))
        self.share_btn.configure(bg=ACC if on else BG2, fg="#000" if on else FG, activebackground=ACC if on else BG3,
                                 text="[phone: on]" if on else "[phone]")
        if self.server_alive() and self.running_share:
            ip = (lan_addresses() or ["?"])[0]
            https = self.share_info().get("https")
            self.phone.configure(text=f"phone: {'https' if https else 'http'}://{ip}:{self.port + (443 if https else 0)} · PIN {self.pin()}", fg=ACC)
            self.qr_btn.pack(side="left", padx=(6, 0))
        else:
            self.phone.configure(text="")
            self.qr_btn.pack_forget()
        if self.server_alive():
            note = "" if self.running_mode == self.mode.get() else f" (→ {self.mode.get()} on next open)"
            self.status.configure(text=f"● running · {self.running_mode} · :{self.port}{note}", fg="#3ddc84")
            self.stop_btn.configure(state="normal")
        else:
            self.status.configure(text="○ server off · starts when you open", fg=FG2)
            self.stop_btn.configure(state="disabled")

    def quit(self):
        for w in self.windows:                              # the windows show nothing without the server
            if w.poll() is None:
                w.terminate()
        self.stop()
        self.root.destroy()

    # ------------------------------------------------------------ locations, offline check
    def check_offline(self):
        self.map.load_locations()
        locs = self.map.locs
        for l in locs:
            l["stats"] = flight_stats(l["name"])
        self.loc_title.configure(text=f"LOCATIONS · {len(locs)}")
        self.table.fill(locs)
        self.map.draw()
        self.card.show(self.map.current())
        built = [l for l in locs if l.get("built")]
        self.offline.configure(text=f"{len(built)}/{len(locs)} built" + (" · offline ok" if built else ""),
                               fg=FG2 if len(built) == len(locs) else FG)
        real = sum(l["stats"]["real"] for l in locs); sim = sum(l["stats"]["sim"] for l in locs)
        self.flights.configure(text=f"logs: {real} real · {sim} sim")
        self.net.configure(text="internet …", fg=FG2)

        def net():
            try:
                urllib.request.urlopen("https://wmts.geo.admin.ch/", timeout=3)
                ok = True
            except urllib.error.HTTPError:
                ok = True                       # the server answered: we are online
            except Exception:
                ok = False
            self.online = ok
            self.root.after(0, lambda: self.net.configure(text="internet yes" if ok else "internet no",
                                                          fg="#3ddc84" if ok else "#ff9f43"))
        threading.Thread(target=net, daemon=True).start()

    def offline_tip(self):
        missing = [l["name"] for l in self.map.locs if not l.get("built")]
        return ("Built locations open in the 3D viewer without internet." +
                (f"\nNot built yet: {', '.join(missing)}" if missing else ""))

    def select(self, name):
        """one location chosen (map click or table row): ring on the map, row in the table, details card"""
        self.map.selected = name
        self.map.draw(save=False)
        self.table.select(name)
        self.card.show(self.map.current())

    def open_location(self, l):
        if l:
            self.open(f"/viewer/?scene={l['name']}" if l.get("built") else "/viewer/map.html")

    # ------------------------------------------------------------ disk space + clean-up
    @staticmethod
    def folder_size(p: Path):
        total = n = 0
        stack = [p]
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat().st_size; n += 1
            except OSError:
                pass
        return total, n

    def disk_dialog(self):
        win = tk.Toplevel(self.root); win.title("Alpline · disk space"); win.configure(bg=BG); win.resizable(False, False)
        hdr = tk.Frame(win, bg=BG); hdr.pack(fill="x", padx=14, pady=(12, 0))
        self.section("DISK SPACE", hdr)
        rows = tk.Frame(win, bg=BG); rows.pack(fill="x", padx=14)
        out = tk.Label(win, font=SANS, fg=FG2, bg=BG, justify="left", anchor="w", wraplength=S(460))
        items = [("cache", "download cache (map tiles)", "Tiles from swisstopo. Lets you build offline; tiles no location uses can be removed."),
                 ("scenes", "built locations", "What the 3D viewer shows. Rebuilt from the cache if deleted."),
                 ("deleted", "deleted locations", "Kept so you can restore them. Emptying is permanent."),
                 ("logs", "flight logs", "Your recorded and training flights.")]
        labels = {}
        for key, name, tip in items:
            r = tk.Frame(rows, bg=BG); r.pack(fill="x", pady=1)
            tk.Label(r, text=name, font=SANS, fg=FG, bg=BG, width=26, anchor="w").pack(side="left")
            labels[key] = tk.Label(r, text="…", font=MONO, fg=FG, bg=BG, anchor="e", width=18); labels[key].pack(side="left")
            Tip(labels[key], tip)

        def measure():
            res = {k: self.folder_size(ROOT / k) for k, *_ in items}
            def show():
                for k, (b, n) in res.items():
                    labels[k].configure(text=f"{b / 1e9:.2f} GB" if b >= 1e9 else f"{b / 1e6:.0f} MB")
                tot = sum(b for b, _ in res.values())
                out.configure(text=f"Total {tot / 1e9:.1f} GB (Python libraries not counted).")
            self.root.after(0, show)
        threading.Thread(target=measure, daemon=True).start()

        def run(args, confirm=None, after=None):
            from tkinter import messagebox
            if confirm and not messagebox.askyesno("Alpline", confirm, parent=win):
                return
            out.configure(text="working…")

            self.logo.busy(True)

            def work():
                try:
                    work_()
                finally:
                    self.root.after(0, lambda: self.logo.busy(False))

            def work_():
                r = subprocess.run(paths.cli_cmd() + args, cwd=str(ROOT), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                text = (r.stdout.strip().splitlines() or [""])[-1] if r.returncode == 0 else (r.stderr or r.stdout).strip()[-300:]
                self.root.after(0, lambda: (out.configure(text=text), after and after(r), threading.Thread(target=measure, daemon=True).start()))
            threading.Thread(target=work, daemon=True).start()

        def prune():                              # first say how much, then ask
            def asked(r):
                if r.returncode == 0 and "would free 0 MB" not in r.stdout:
                    run(["cache", "prune"], confirm=r.stdout.strip().splitlines()[-1].replace("would free", "This will free")
                        + ".\n\nTiles of your location files (and 1 km around them) are kept. Delete the rest?")
            run(["cache", "prune", "--dry-run"], after=asked)

        btns = tk.Frame(win, bg=BG); btns.pack(fill="x", padx=14, pady=(10, 0))
        b1 = self.button(btns, "[clean unused tiles]", prune); b1.pack(side="left", padx=(0, 6))
        Tip(b1, "Deletes downloaded tiles that none of your location files uses. Your locations still build offline.")
        b2 = self.button(btns, "[empty deleted]", lambda: run(["deleted", "--purge"],
                         confirm="Permanently delete the locations in the 'deleted' folder? They can no longer be restored."))
        b2.pack(side="left")
        out.pack(fill="x", padx=14, pady=(8, 14))

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
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Alpline.lnk'));"
              f"$s.TargetPath='{target}';$s.Arguments='{arg}';$s.WorkingDirectory='{ROOT}';"
              f"$s.IconLocation='{icon},0';"
              "$s.Description='Alpline by lieka: FPV line of sight on Swiss terrain';$s.Save()")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.say("shortcut 'Alpline' added to your desktop" if r.returncode == 0
                 else f"could not create the shortcut: {(r.stderr or r.stdout).strip()[:120]}")


def split_name(name):
    """'007_moleson' -> ('007', 'moleson'); 'test' -> ('', 'test')"""
    head, _, rest = name.partition("_")
    return (head, rest) if head.isdigit() and rest else ("", name)


class LogoAnim:
    """The logo in the top bar: spins up once when the launcher opens, spins steadily while it works (starting the
    server, checking phone access, cleaning the cache). Frames: viewer/brand/anim-*-<size>.png, made from the web logo
    by tools/render_logo_frames.py. Without them the still logo is shown."""
    MS = {"intro": 60, "busy": 70}

    def __init__(self, root, parent, px):
        self.root, self.n_busy, self.mode, self.i, self.job = root, 0, None, 0, None
        self.still = Launcher.brand_image("logo-dark", px)
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


class Table:
    """Locations in number order: # · name · real logs · sim logs (grey row = not built yet)."""
    def __init__(self, app, parent, height):
        self.app = app
        box = tk.Frame(parent, bg=RULE, padx=1, pady=1); box.pack(fill="x")
        self.tv = ttk.Treeview(box, style="L.Treeview", columns=("num", "name", "real", "sim"), show="headings",
                               height=height, selectmode="browse")
        for c, label, w, anchor in (("num", "#", 42, "w"), ("name", "LOCATION", 190, "w"),
                                    ("real", "REAL", 54, "e"), ("sim", "SIM", 54, "e")):
            self.tv.heading(c, text=label, anchor=anchor)
            self.tv.column(c, width=S(w), anchor=anchor, stretch=c == "name")
        self.tv.tag_configure("nb", foreground=GREY)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tv.yview, style="L.Vertical.TScrollbar")
        def autohide(lo, hi):                   # the scrollbar only shows when the list is longer than the box
            sb.set(lo, hi)
            if float(lo) <= 0 and float(hi) >= 1:
                sb.pack_forget()
            elif not sb.winfo_ismapped():
                sb.pack(side="left", fill="y")
        self.tv.configure(yscrollcommand=autohide)
        self.tv.pack(side="left", fill="x", expand=True)
        self.tv.bind("<<TreeviewSelect>>", self.on_select)
        self.tv.bind("<Double-1>", lambda e: app.open_location(app.map.current()))
        self.tv.bind("<Return>", lambda e: app.open_location(app.map.current()))
        self.busy = False

    def fill(self, locs):
        self.busy = True
        self.tv.delete(*self.tv.get_children())
        for l in locs:
            num, rest = split_name(l["name"])
            st = l.get("stats") or {}
            self.tv.insert("", "end", iid=l["name"], tags=() if l.get("built") else ("nb",),
                           values=(num, l.get("title") or rest, st.get("real", 0) or "·", st.get("sim", 0) or "·"))
        if self.app.map.selected in self.tv.get_children():
            self.tv.selection_set(self.app.map.selected); self.tv.see(self.app.map.selected)
        self.busy = False

    def select(self, name):
        if name in self.tv.get_children() and self.tv.selection() != (name,):
            self.busy = True
            self.tv.selection_set(name); self.tv.see(name)
            self.app.root.after_idle(lambda: setattr(self, "busy", False))

    def on_select(self, _):
        if self.busy:
            return
        sel = self.tv.selection()
        if sel:
            self.app.select(sel[0])


class Card:
    """Details of the selected location, with a real / sim bar chart of its logs."""
    BAR_W = 200

    def __init__(self, app, parent):
        self.app = app
        f = tk.Frame(parent, bg=RULE, padx=1, pady=1); f.pack(fill="x", pady=(10, 0))
        inner = tk.Frame(f, bg=BG, padx=10, pady=8); inner.pack(fill="both")
        self.title = tk.Label(inner, font=("Consolas", 10, "bold"), fg=FG, bg=BG, anchor="w"); self.title.pack(fill="x")
        self.info = tk.Label(inner, font=("Consolas", 9), fg=FG2, bg=BG, anchor="w", justify="left", wraplength=S(350))
        self.info.pack(fill="x", pady=(2, 6))
        self.cv = tk.Canvas(inner, width=S(330), height=S(46), bg=BG, highlightthickness=0); self.cv.pack(anchor="w")
        row = tk.Frame(inner, bg=BG); row.pack(fill="x", pady=(8, 0))
        self.open_btn = app.button(row, "[open in 3d]", lambda: app.open_location(app.map.current()), primary=True)
        self.open_btn.pack(side="left")
        self.map_btn = app.button(row, "[locations map]", lambda: app.open("/viewer/map.html"))
        self.map_btn.pack(side="left", padx=(6, 0))

    def show(self, l):
        self.cv.delete("all")
        if not l:
            self.title.configure(text="no location selected")
            self.info.configure(text="click one on the map or in the list")
            self.open_btn.configure(state="disabled")
            return
        num, rest = split_name(l["name"])
        self.title.configure(text=f"{num + ' · ' if num else ''}{(l.get('title') or rest).upper()}")
        size = (f"route {l['corridor']['length_m'] / 1000:.1f} km" if l.get("corridor")
                else f"{2 * l['half_size_m'] / 1000:g} × {2 * l['half_size_m'] / 1000:g} km")
        st = l.get("stats") or {}
        built = f"built {fmt_day(st.get('built'))}" if l.get("built") else "not built yet"
        last = f" · last log {fmt_day(st.get('last'))}" if st.get("last") else ""
        self.info.configure(text=f"{size} · terrain {l.get('resolution_m', '?'):g} m · {built}{last}")
        self.open_btn.configure(state="normal", text="[open in 3d]" if l.get("built") else "[build on the map]")
        # bar chart: real vs sim logs (bars scaled to the location with the most logs)
        most = max([1] + [max(x["stats"]["real"], x["stats"]["sim"]) for x in self.app.map.locs if x.get("stats")])
        for i, (k, label, col) in enumerate((("real", "REAL", ACC), ("sim", "SIM", "#8fb3ff"))):
            y, bw, x0, h = S(4 + i * 22), S(self.BAR_W), S(40), S(14)
            n, secs = st.get(k, 0), st.get(k + "_s", 0)
            self.cv.create_text(0, y + h / 2, text=label, anchor="w", fill=FG2, font=("Consolas", 8, "bold"))
            self.cv.create_rectangle(x0, y, x0 + bw, y + h, fill=BG2, outline="")
            if n:
                self.cv.create_rectangle(x0, y, x0 + max(3, bw * n / most), y + h, fill=col, outline="")
            self.cv.create_text(x0 + bw + S(8), y + h / 2, anchor="w", fill=FG if n else GREY, font=("Consolas", 9),
                                text=f"{n}  {fmt_dur(secs)}" if n else "0")


# ---------------------------------------------------------------- Switzerland map
# swisstopo grey map + FOCA drone restrictions (the same tiles as the locations map page), downloaded once
# at zoom 8 (9 on high-DPI screens), cropped to Switzerland and kept in cache/launcher/ so the map also shows offline.

MAP_DIR = ROOT / "cache" / "launcher"
BBOX = (5.85, 45.75, 10.6, 47.9)                    # lon/lat west, south, east, north
Z = 8
MAP_W = 600                                          # canvas width (px)
TILE_URL = "https://wmts.geo.admin.ch/1.0.0/{layer}/default/current/3857/{z}/{x}/{y}.{ext}"


def merc(lon, lat, z=None):
    """lon/lat -> global pixel coordinates at zoom z (Web Mercator, 256 px tiles)."""
    z = Z if z is None else z
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    la = math.radians(lat)
    y = (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n
    return x, y


class SwissMap:
    def __init__(self, app: "Launcher", parent):
        self.app = app
        x0, y0 = merc(BBOX[0], BBOX[3]); x1, y1 = merc(BBOX[2], BBOX[1])
        self.org, self.scale = (x0, y0), MAP_W / (x1 - x0)
        self.h = round((y1 - y0) * self.scale)
        f = tk.Frame(parent, bg=BG); f.pack(side="left", anchor="n")
        self.cv = tk.Canvas(f, width=MAP_W, height=self.h, bg=BG2, highlightthickness=1, highlightbackground=RULE)
        self.cv.pack()
        row = tk.Frame(f, bg=BG); row.pack(fill="x", pady=(6, 0))
        self.zones = tk.BooleanVar(value=app.cfg.get("map_zones", True))
        cb = tk.Checkbutton(row, text="drone zones (FOCA)", variable=self.zones, command=self.draw, font=SANS, fg=FG, bg=BG,
                            selectcolor=BG2, activebackground=BG, activeforeground=FG, bd=0, highlightthickness=0)
        cb.pack(side="left")
        Tip(cb, "Official drone restrictions from FOCA (map.geo.admin.ch). An overview only: check the locations map "
                "for the details before flying.")
        up = app.button(row, "[update map]", lambda: self.download(force=True), small=True); up.pack(side="right")
        Tip(up, "Download the map and the latest drone zones again (needs internet; kept for offline use).")
        self.hint = "click = select · double-click = open"
        self.info = tk.Label(row, text=self.hint, font=SANS, fg=FG2, bg=BG); self.info.pack(side="right", padx=(0, 10))
        self.imgs = {}
        self.locs = []
        self.selected = app.cfg.get("selected")
        self.downloading, self.spin, self.spin_i = False, None, 0
        if not all((MAP_DIR / f"ch_{k}_{MAP_W}.png").exists() for k in ("base", "zones")):
            self.download()

    def px(self, lat, lon):
        x, y = merc(lon, lat)
        return (x - self.org[0]) * self.scale, (y - self.org[1]) * self.scale

    def current(self):
        return next((l for l in self.locs if l["name"] == self.selected), None)

    # ---------------------------------------------------------- data
    def load_locations(self):
        try:
            sp = APP / ".venv" / "Lib" / "site-packages"   # in case this window was started without the .venv
            if sp.exists() and str(sp) not in sys.path:
                sys.path.append(str(sp))
            from fpv3d.locations import list_locations
            self.locs = sorted((l for l in list_locations(ROOT / "scenes") if "center" in l), key=lambda l: l["name"])
        except Exception as ex:                     # missing libraries etc.: the map still works without them
            self.locs = []
            self.info.configure(text=f"locations not shown ({ex.__class__.__name__})")
        if self.selected not in [l["name"] for l in self.locs]:
            self.selected = self.locs[0]["name"] if self.locs else None

    def download(self, force=False):
        if self.downloading:                        # [update map] pressed again while it runs
            return
        self.downloading = True
        logo = getattr(self.app, "logo", None)
        if logo:
            logo.busy(True)
        self.draw(save=False)                       # the old map stays under the loading box

        def done(msg=None):
            self.downloading = False
            if logo:
                logo.busy(False)
            if msg is None:
                self.imgs.clear()
            self.draw()
            self.info.configure(text=msg or self.hint)

        def work():
            try:
                from PIL import Image
                import io
                x0, y0 = self.org
                tx0, ty0 = int(x0 // 256), int(y0 // 256)
                x1, y1 = merc(BBOX[2], BBOX[1])
                tx1, ty1 = int(x1 // 256), int(y1 // 256)
                out = {}
                for key, layer, ext in (("base", "ch.swisstopo.pixelkarte-grau", "jpeg"),
                                        ("zones", "ch.bazl.einschraenkungen-drohnen", "png")):
                    mosaic = Image.new("RGBA", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (0, 0, 0, 0))
                    for tx in range(tx0, tx1 + 1):
                        for ty in range(ty0, ty1 + 1):
                            url = TILE_URL.format(layer=layer, z=Z, x=tx, y=ty, ext=ext)
                            req = urllib.request.Request(url, headers={"User-Agent": "alpline-launcher"})
                            try:
                                data = urllib.request.urlopen(req, timeout=10).read()
                            except urllib.error.HTTPError:
                                continue            # no tile there (outside the data)
                            mosaic.paste(Image.open(io.BytesIO(data)).convert("RGBA"), ((tx - tx0) * 256, (ty - ty0) * 256))
                    crop = mosaic.crop((round(x0 - tx0 * 256), round(y0 - ty0 * 256),
                                        round(x1 - tx0 * 256), round(y1 - ty0 * 256))).resize((MAP_W, self.h), Image.LANCZOS)
                    out[key] = crop
                base = out["base"].convert("RGB").convert("RGBA")
                MAP_DIR.mkdir(parents=True, exist_ok=True)
                base.save(MAP_DIR / f"ch_base_{MAP_W}.png")
                Image.alpha_composite(base, out["zones"]).save(MAP_DIR / f"ch_zones_{MAP_W}.png")
                self.app.root.after(0, done)
            except Exception as ex:
                msg = f"map not downloaded ({ex.__class__.__name__}): needs internet once"
                self.app.root.after(0, lambda: done(msg))
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- drawing
    def draw(self, save=True):
        if save:
            self.app.cfg["map_zones"] = self.zones.get(); self.app.save()
        self.app.cfg["selected"] = self.selected
        cv = self.cv
        cv.delete("all")
        key = "zones" if self.zones.get() else "base"
        p = MAP_DIR / f"ch_{key}_{MAP_W}.png"
        if p.exists():
            try:
                self.imgs[key] = self.imgs.get(key) or tk.PhotoImage(file=str(p))
                cv.create_image(0, 0, image=self.imgs[key], anchor="nw")
            except tk.TclError:
                pass
        elif not self.downloading:
            cv.create_text(MAP_W / 2, 20, text="no map yet: [update map] when online", fill=FG2, font=MONO)
        labels = []
        for l in sorted(self.locs, key=lambda l: not l.get("built")):   # built ones get their name first
            col = ACC if l.get("built") else "#8a93a0"
            tag = f"loc_{l['name']}"
            if l.get("corridor"):
                pts = [c for la, lo in l["corridor"]["points"] for c in self.px(la, lo)]
                w = max(3, 2 * l["corridor"]["width_m"] / (156543.03 / 2 ** Z) * self.scale)
                cv.create_line(*pts, fill="#000", width=w + 2, tags=tag)
                cv.create_line(*pts, fill=col, width=w, tags=tag)
                lx, ly = pts[-2], pts[-1]
            else:
                cx, cy = self.px(*l["center"])
                # metres -> px: one tile pixel is 156543 m / 2^Z at the equator (x cos(lat)), then `self.scale`
                r = max(4, l["half_size_m"] / (156543.03 / 2 ** Z * math.cos(math.radians(l["center"][0]))) * self.scale)
                cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline="#000", width=3, tags=tag)
                cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline=col, width=2,
                                    fill=col if l.get("built") else "", stipple="gray50" if l.get("built") else "", tags=tag)
                lx, ly = cx + r, cy - r
            label = split_name(l["name"])[0] or l["name"]          # the number on the map, the names are in the list
            if l["name"] == self.selected:                          # selected in the list: a ring around it
                rx, ry = (cx, cy) if not l.get("corridor") else (pts[0], pts[1])
                rr = S(14)
                cv.create_oval(rx - rr, ry - rr, rx + rr, ry + rr, outline="#000", width=S(4))
                cv.create_oval(rx - rr, ry - rr, rx + rr, ry + rr, outline=ACC, width=S(2))
            box = (lx + 3, ly - 13, lx + 6 + 7 * len(label), ly + 1)
            if not any(box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3] for o in labels):
                labels.append(box)                  # names that would overlap another one are left out (hover shows them)
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):    # dark halo so the name reads on any background
                    cv.create_text(lx + 4 + dx, ly + dy, text=label, anchor="sw", fill="#000", font=("Consolas", 9, "bold"), tags=tag)
                cv.create_text(lx + 4, ly, text=label, anchor="sw", fill=col, font=("Consolas", 9, "bold"), tags=tag)
            cv.tag_bind(tag, "<Enter>", lambda e, l=l: (self.cv.configure(cursor="hand2"), self.info.configure(
                text=f"{l.get('title') or l['name']}" + ("" if l.get("built") else " (not built)"))))
            cv.tag_bind(tag, "<Leave>", lambda e: (self.cv.configure(cursor=""), self.info.configure(text=self.hint)))
            cv.tag_bind(tag, "<Button-1>", lambda e, l=l: self.app.select(l["name"]))   # click: select (table + card)
            cv.tag_bind(tag, "<Double-Button-1>", lambda e, l=l: self.app.open_location(l))
        self.busy_box()

    def busy_box(self):
        """While the map updates: a box in the middle with the transmitting logo and 'updating the map…'."""
        if not self.downloading:
            return
        if self.spin is None:
            self.spin = LogoAnim._load("busy", S(64))
        cx, cy, w, h = MAP_W / 2, self.h / 2, S(210), S(118)
        self.cv.create_rectangle(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, fill=BG, outline=RULE, tags="busy")
        if self.spin:
            self.cv.create_image(cx, cy - S(14), image=self.spin[self.spin_i % len(self.spin)], tags=("busy", "busyimg"))
        self.cv.create_text(cx, cy + h / 2 - S(16), text="updating the map…", fill=FG2, font=MONO, tags="busy")
        if self.spin and not getattr(self, "_spin_job", None):
            self._spin_tick()

    def _spin_tick(self):
        self._spin_job = None
        if not self.downloading or not self.spin:
            return
        self.spin_i += 1
        self.cv.itemconfigure("busyimg", image=self.spin[self.spin_i % len(self.spin)])
        self._spin_job = self.app.root.after(LogoAnim.MS["busy"], self._spin_tick)



def sharp_on_windows():
    """Tell Windows this window draws itself at the real screen resolution. Without it, on a display scaled to
    125 % / 150 %, Windows stretches a 100 % picture of the window: that is the blurry, 'hazy' look."""
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)       # per-monitor (Windows 8.1+)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()          # older Windows
        except Exception:
            pass


def first_start_folder(root) -> bool:
    """Installed app, very first start: where should your files go? True = continue, False = restart needed / quit."""
    from tkinter import filedialog, messagebox
    ans = messagebox.askyesnocancel(
        "Alpline: your files",
        "Where should Alpline keep your locations, flights and downloaded maps?\n\n"
        f"Yes: in {paths.DEFAULT_DATA}\n"
        "No: choose a folder (for example your existing fpv3d project folder, to keep everything you already have)",
        parent=root)
    if ans is None:
        return False
    folder = paths.DEFAULT_DATA
    if ans is False:
        pick = filedialog.askdirectory(parent=root, title="Folder for Alpline's files", mustexist=False,
                                       initialdir=str(Path.home()))
        if not pick:
            return False
        folder = Path(pick)
    paths.set_data(folder)
    subprocess.Popen([sys.executable] + sys.argv[1:])       # start again with the chosen folder
    return False


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--window":      # Alpline.exe --window <url>: one Alpline window
        from fpv3d.appwin import main as window_main
        sys.exit(window_main(sys.argv[2:]))
    sharp_on_windows()
    root = tk.Tk()
    if not paths.data_chosen():
        root.withdraw()
        first_start_folder(root)
        sys.exit(0)
    paths.ensure_data()
    UI = max(1.0, root.winfo_fpixels("1i") / 96)            # 1.25, 1.5 ... on scaled displays
    root.tk.call("tk", "scaling", UI * 96 / 72)              # fonts in points follow the same factor
    MAP_W = S(600)                                           # map width in real screen pixels
    Z = 8 if MAP_W <= 860 else 9                             # sharper tiles when the map is drawn larger
    Launcher(root)
    root.mainloop()
