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


def venv_exe(name: str) -> str:
    """python.exe / pythonw.exe of the project's virtual environment (.venv), where numpy, rasterio, PyYAML...
    are installed. Asked for explicitly: with the Microsoft Store Python, sys.executable inside a venv points
    to the base Python, which does not have those libraries."""
    for d in (ROOT / ".venv" / "Scripts", ROOT / ".venv" / "bin", Path(sys.prefix) / "Scripts", Path(sys.prefix) / "bin"):
        for n in (name, name.replace(".exe", ""), "python3" if name.startswith("python.") else name):
            if (d / n).exists():
                return str(d / n)
    exe = Path(sys.executable)
    twin = exe.with_name(name)
    return str(twin if twin.exists() else exe)


def python_exe() -> str:
    """The python that runs the server (console version, no window: CREATE_NO_WINDOW)."""
    return venv_exe("python.exe")


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

        left = tk.Frame(root, bg=BG); left.pack(side="left", fill="y", anchor="n")
        self.left = left
        pad = dict(padx=14)
        tk.Label(left, text="FPV3D", font=("Consolas", 16, "bold"), fg=FG, bg=BG).pack(anchor="w", pady=(12, 0), **pad)
        tk.Label(left, text="FPV flight and signal visualiser", font=SANS, fg=FG2, bg=BG).pack(anchor="w", **pad)

        self.section("MODE")
        self.mode = tk.StringVar(value=self.cfg.get("mode", "full"))
        row = tk.Frame(left, bg=BG); row.pack(fill="x", **pad)
        self.mode_btns = {}
        for m, label in (("full", "full"), ("lite", "lite")):
            b = tk.Button(row, text=label, font=("Consolas", 11, "bold"), width=8, relief="flat", bd=0, cursor="hand2",
                          command=lambda m=m: self.set_mode(m))
            b.pack(side="left", padx=(0, 4))
            self.mode_btns[m] = b
        self.mode_info = tk.Label(left, font=SANS, fg=FG2, bg=BG, justify="left", wraplength=360)
        self.mode_info.pack(anchor="w", pady=(6, 0), **pad)

        self.section("OPEN")
        row = tk.Frame(left, bg=BG); row.pack(fill="x", **pad)
        self.button(row, "[3d viewer]", lambda: self.open("/viewer/"), primary=True).pack(side="left", padx=(0, 6))
        self.button(row, "[locations map]", lambda: self.open("/viewer/map.html")).pack(side="left")
        self.status = tk.Label(left, font=MONO, fg=FG2, bg=BG, justify="left", anchor="w")
        self.status.pack(fill="x", pady=(8, 0), **pad)
        self.stop_btn = self.button(left, "[stop server]", self.stop)
        self.stop_btn.pack(anchor="w", pady=(4, 0), **pad)

        self.section("OFFLINE AT THE FIELD")
        self.offline = tk.Label(left, font=MONO, fg=FG, bg=BG, justify="left", anchor="w", wraplength=360)
        self.offline.pack(fill="x", **pad)
        row = tk.Frame(left, bg=BG); row.pack(fill="x", pady=(6, 0), **pad)
        self.button(row, "[check again]", self.check_offline).pack(side="left", padx=(0, 6))
        self.button(row, "[desktop shortcut]", self.make_shortcut).pack(side="left")
        self.msg = tk.Label(left, font=SANS, fg=FG2, bg=BG, justify="left", anchor="w", wraplength=360)
        self.msg.pack(fill="x", pady=(6, 12), **pad)

        tk.Frame(root, bg=RULE, width=1).pack(side="left", fill="y", pady=12)
        self.map = SwissMap(self, root)

        self.set_mode(self.mode.get(), save=False)
        self.refresh_status()
        self.check_offline()

    # ------------------------------------------------------------ widgets
    def section(self, title, parent=None):
        f = tk.Frame(parent or self.left, bg=BG); f.pack(fill="x", padx=14, pady=(14, 6))
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
        if hasattr(self, "map"):
            self.map.load_locations(); self.map.draw()
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
        pyw = venv_exe("pythonw.exe")             # the project's .venv, so the map can read your locations
        ps = ("$d=[Environment]::GetFolderPath('Desktop');"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'fpv3d.lnk'));"
              f"$s.TargetPath='{pyw}';$s.Arguments='\"{ROOT / 'launcher.pyw'}\"';$s.WorkingDirectory='{ROOT}';"
              "$s.Description='fpv3d: Full or Lite, 3D viewer or locations map';$s.Save()")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.msg.configure(text="Shortcut 'fpv3d' added to your desktop." if r.returncode == 0
                           else f"Could not create the shortcut: {(r.stderr or r.stdout).strip()[:200]}")


# ---------------------------------------------------------------- Switzerland map
# swisstopo grey map + FOCA drone restrictions (the same tiles as the locations map page), downloaded once
# at zoom 8, cropped to Switzerland and kept in cache/launcher/ so the map also shows offline.
import math

MAP_DIR = ROOT / "cache" / "launcher"
BBOX = (5.85, 45.75, 10.6, 47.9)                    # lon/lat west, south, east, north
Z = 8
MAP_W = 560                                          # canvas width (px)
TILE_URL = "https://wmts.geo.admin.ch/1.0.0/{layer}/default/current/3857/{z}/{x}/{y}.{ext}"


def merc(lon, lat, z=Z):
    """lon/lat -> global pixel coordinates at zoom z (Web Mercator, 256 px tiles)."""
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    la = math.radians(lat)
    y = (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n
    return x, y


class SwissMap:
    def __init__(self, app: "Launcher", root):
        self.app = app
        x0, y0 = merc(BBOX[0], BBOX[3]); x1, y1 = merc(BBOX[2], BBOX[1])
        self.org, self.scale = (x0, y0), MAP_W / (x1 - x0)
        self.h = round((y1 - y0) * self.scale)
        f = tk.Frame(root, bg=BG); f.pack(side="left", fill="both", anchor="n")
        app.section("SWITZERLAND", f)
        self.cv = tk.Canvas(f, width=MAP_W, height=self.h, bg=BG2, highlightthickness=1, highlightbackground=RULE)
        self.cv.pack(padx=14)
        row = tk.Frame(f, bg=BG); row.pack(fill="x", padx=14, pady=(6, 0))
        self.zones = tk.BooleanVar(value=app.cfg.get("map_zones", True))
        tk.Checkbutton(row, text="drone zones (FOCA)", variable=self.zones, command=self.draw, font=SANS, fg=FG, bg=BG,
                       selectcolor=BG2, activebackground=BG, activeforeground=FG, bd=0).pack(side="left")
        app.button(row, "[update map]", lambda: self.download(force=True)).pack(side="right")
        self.info = tk.Label(f, font=SANS, fg=FG2, bg=BG, justify="left", anchor="w", wraplength=MAP_W)
        self.info.pack(fill="x", padx=14, pady=(6, 12))
        self.hint = ("Squares and routes: your locations (yellow = built, click to open it in 3D; grey = not built, "
                     "click to open the locations map). Coloured areas: drone restrictions from FOCA, check the "
                     "locations map for the details before flying.")
        self.info.configure(text=self.hint)
        self.imgs = {}
        self.locs = []
        self.load_locations()
        if all((MAP_DIR / f"ch_{k}.png").exists() for k in ("base", "zones")):
            self.draw()
        else:
            self.download()

    def px(self, lat, lon):
        x, y = merc(lon, lat)
        return (x - self.org[0]) * self.scale, (y - self.org[1]) * self.scale

    # ---------------------------------------------------------- data
    def load_locations(self):
        try:
            sys.path.insert(0, str(ROOT))
            sp = ROOT / ".venv" / "Lib" / "site-packages"   # in case this window was started without the .venv
            if sp.exists() and str(sp) not in sys.path:
                sys.path.append(str(sp))
            from fpv3d.locations import list_locations
            self.locs = [l for l in list_locations(ROOT / "scenes") if "center" in l]
        except Exception as ex:                     # missing libraries etc.: the map still works without them
            self.locs = []
            self.info.configure(text=f"Locations not shown ({ex.__class__.__name__}: {ex})")

    def download(self, force=False):
        self.cv.delete("all")
        self.cv.create_text(MAP_W / 2, self.h / 2, text="downloading the map of Switzerland…", fill=FG2, font=MONO)

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
                            req = urllib.request.Request(url, headers={"User-Agent": "fpv3d-launcher"})
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
                base.save(MAP_DIR / "ch_base.png")
                Image.alpha_composite(base, out["zones"]).save(MAP_DIR / "ch_zones.png")
                self.app.root.after(0, lambda: (self.imgs.clear(), self.draw(), self.info.configure(text=self.hint)))
            except Exception as ex:
                msg = (f"Map not downloaded ({ex.__class__.__name__}). It needs internet once, then it also works offline. "
                       "Try [update map] later.")
                self.app.root.after(0, lambda: (self.draw(), self.info.configure(text=msg)))
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- drawing
    def draw(self):
        self.app.cfg["map_zones"] = self.zones.get(); self.app.save()
        cv = self.cv
        cv.delete("all")
        key = "zones" if self.zones.get() else "base"
        p = MAP_DIR / f"ch_{key}.png"
        if p.exists():
            try:
                self.imgs[key] = self.imgs.get(key) or tk.PhotoImage(file=str(p))
                cv.create_image(0, 0, image=self.imgs[key], anchor="nw")
            except tk.TclError:
                pass
        else:
            cv.create_text(MAP_W / 2, 20, text="no map yet: [update map] when online", fill=FG2, font=MONO)
        labels = []
        for l in sorted(self.locs, key=lambda l: not l.get("built")):   # built ones get their name first
            col = ACC if l.get("built") else "#8a93a0"
            tag = f"loc_{l['name']}"
            if l.get("corridor"):
                pts = [c for la, lo in l["corridor"]["points"] for c in self.px(la, lo)]
                w = max(3, 2 * l["corridor"]["width_m"] / 611 * self.scale)
                cv.create_line(*pts, fill="#000", width=w + 2, tags=tag)
                cv.create_line(*pts, fill=col, width=w, tags=tag)
                lx, ly = pts[-2], pts[-1]
            else:
                cx, cy = self.px(*l["center"])
                # metres -> px: 1 px at zoom 8 is ~611 m / cos(lat) on the ground... at scale `self.scale`
                r = max(4, l["half_size_m"] / (611.5 * math.cos(math.radians(l["center"][0]))) * self.scale)
                cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline="#000", width=3, tags=tag)
                cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline=col, width=2,
                                    fill=col if l.get("built") else "", stipple="gray50" if l.get("built") else "", tags=tag)
                lx, ly = cx + r, cy - r
            box = (lx + 3, ly - 13, lx + 6 + 7 * len(l["name"]), ly + 1)
            if not any(box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3] for o in labels):
                labels.append(box)                  # names that would overlap another one are left out (hover shows them)
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):    # dark halo so the name reads on any background
                    cv.create_text(lx + 4 + dx, ly + dy, text=l["name"], anchor="sw", fill="#000", font=("Consolas", 9, "bold"), tags=tag)
                cv.create_text(lx + 4, ly, text=l["name"], anchor="sw", fill=col, font=("Consolas", 9, "bold"), tags=tag)
            cv.tag_bind(tag, "<Enter>", lambda e, l=l: (self.cv.configure(cursor="hand2"), self.info.configure(
                text=f"{l.get('title') or l['name']} · " + ("built: click to open it in 3D" if l.get("built")
                                                             else "not built yet: click to open the locations map"))))
            cv.tag_bind(tag, "<Leave>", lambda e: (self.cv.configure(cursor=""), self.info.configure(text=self.hint)))
            cv.tag_bind(tag, "<Button-1>", lambda e, l=l: self.app.open(
                f"/viewer/?scene={l['name']}" if l.get("built") else "/viewer/map.html"))


if __name__ == "__main__":
    root = tk.Tk()
    Launcher(root)
    root.mainloop()
