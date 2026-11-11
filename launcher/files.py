"""The files page: sizes of your files, clean-up / start fresh, backup and restore."""
from __future__ import annotations

import os
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path

from fpv3d import paths
from fpv3d.brand import APP_NAME

from .common import ROOT, load_settings, unexpected
from .style import BG, BG2, FG, FG2, MONO, MONO_S, S, SANS
from .widgets import FitLabel, Tip


class FilesPage:
    """Mixed into Launcher (launcher/app.py): methods only, they share its self."""

    # ------------------------------------------------------------ disk page
    def build_disk_page(self, parent):
        from fpv3d.housekeeping import KINDS
        col = self.page_frame(parent, "YOUR FILES",
                              f"What {APP_NAME} keeps on this computer. Tick what to delete: a backup zip is made first "
                              "unless you untick it. Ticking everything starts fresh, like a new install.")
        self.disk_free = FitLabel(col, font=MONO_S, fg=FG2, bg=BG)
        self.disk_free.pack(fill="x", pady=(0, S(8)))
        grid = tk.Frame(col, bg=BG); grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.disk_vars, self.disk_labels = {}, {}
        for i, (key, (label, short, desc)) in enumerate(KINDS.items()):
            v = tk.BooleanVar(value=False)
            cb = self.check(grid, label, v, command=lambda k=key: self.disk_ticked(k), width=18)
            cb.grid(row=i, column=0, sticky="w", pady=S(1))
            d = FitLabel(grid, font=SANS, fg=FG2, bg=BG); d.set(short); d.grid(row=i, column=1, sticky="ew", padx=(S(4), S(8)))
            Tip(cb, desc); Tip(d, desc)
            self.disk_labels[key] = tk.Label(grid, text="…", font=MONO, fg=FG, bg=BG, anchor="e", width=9)
            self.disk_labels[key].grid(row=i, column=2, sticky="e")
            self.disk_vars[key] = v
        sel = tk.Frame(col, bg=BG); sel.pack(fill="x", pady=(S(6), 0))
        self.button(sel, "[all: start fresh]", lambda: self.disk_select(True)).pack(side="left")
        self.button(sel, "[none]", lambda: self.disk_select(False)).pack(side="left", padx=(S(6), 0))
        self.disk_sel_total = tk.Label(sel, text="", font=MONO, fg=FG2, bg=BG, anchor="e")
        self.disk_sel_total.pack(side="right")
        act = tk.Frame(col, bg=BG); act.pack(fill="x", pady=(S(10), 0))
        self.disk_backup_first = tk.BooleanVar(value=True)
        self.check(act, "make a backup first", self.disk_backup_first).pack(side="left")
        self.disk_del_btn = self.button(act, "[delete selected]", self.disk_clear, danger=True)
        self.disk_del_btn.pack(side="right")
        b1 = self.button(act, "[clean unused tiles]", self.disk_prune); b1.pack(side="right", padx=(0, S(8)))
        Tip(b1, "Deletes only the downloaded tiles that none of your location files uses. Your locations still build offline.")
        tk.Frame(col, bg=BG, height=S(14)).pack(fill="x")
        self.section("BACKUP", col)
        br = tk.Frame(col, bg=BG); br.pack(fill="x")
        self.button(br, "[make a backup…]", self.disk_backup, primary=True).pack(side="left")
        self.button(br, "[restore a backup…]", self.disk_restore).pack(side="left", padx=(S(8), 0))
        self.disk_inc_scenes = tk.BooleanVar(value=False)
        self.disk_inc_cb = self.check(col, "include the built 3D scenes (bigger; no rebuild needed after restoring)", self.disk_inc_scenes)
        self.disk_inc_cb.pack(fill="x", pady=(S(6), 0))
        tk.Label(col, text="A backup holds your locations, flights, training flights and settings: keep it safe, or use it "
                           "to move everything to another PC. Restoring never deletes anything; files you already have are kept.",
                 font=SANS, fg=FG2, bg=BG, justify="left", anchor="w", wraplength=S(640)).pack(fill="x", pady=(S(4), 0))
        self.auto_lab = FitLabel(col, font=MONO_S, fg=FG2, bg=BG)
        self.auto_lab.pack(fill="x", pady=(S(6), 0))
        self.show_auto_backup()
        self.disk_out = FitLabel(col, font=SANS, fg=FG2, bg=BG)
        self.disk_out.pack(fill="x", pady=(S(10), 0))
        self.disk_sizes = {}

    def check(self, parent, text, var, command=None, width=0):
        return tk.Checkbutton(parent, text=text, variable=var, command=command, font=SANS, fg=FG, bg=BG, selectcolor=BG2,
                              activebackground=BG, activeforeground=FG, anchor="w", width=width, bd=0,
                              highlightthickness=0, cursor="hand2", padx=0)

    def disk_ticked(self, key):
        if key == "locations" and self.disk_vars["locations"].get():
            self.disk_vars["scenes"].set(True)             # a scene without its location file can't be rebuilt or opened
        if key == "scenes" and not self.disk_vars["scenes"].get() and self.disk_vars["locations"].get():
            self.disk_vars["locations"].set(False)
        self.disk_show_selection()

    def disk_select(self, on):
        for v in self.disk_vars.values():
            v.set(on)
        self.disk_show_selection()

    def disk_show_selection(self):
        from fpv3d.housekeeping import human
        ks = [k for k, v in self.disk_vars.items() if v.get()]
        tot = sum(self.disk_sizes.get(k, 0) for k in ks)
        self.disk_sel_total.configure(text=f"selected: {human(tot)}" if ks else "")

    def measure_disk(self):
        from fpv3d.housekeeping import free_bytes, human, sizes

        def work():
            res, free = sizes(ROOT), free_bytes(ROOT)
            def show():
                self.disk_sizes = res
                for k, b in res.items():
                    self.disk_labels[k].configure(text=human(b))
                used = sum(res.values())
                self.disk_free.set(f"{APP_NAME} uses {human(used)}" + (f" · {human(free)} free on the disk" if free is not None else ""))
                self.disk_inc_cb.configure(text=f"include the built 3D scenes ({human(res.get('scenes', 0))}; no rebuild needed after restoring)")
                self.disk_show_selection()
            self.root.after(0, show)
        threading.Thread(target=work, daemon=True).start()

    def disk_job(self, text, fn, done):
        """Run fn() in the background with the logo busy; done(result or exception) back in the window."""
        self.disk_out.set(text)
        self.logo.busy(True)

        def work():
            try:
                r = fn()
            except Exception as ex:                    # noqa: BLE001 - shown to you, and logged
                from fpv3d.errorlog import record_exception
                record_exception("launcher files page", ex)
                r = ex
            self.root.after(0, lambda: (self.logo.busy(False), done(r), self.measure_disk()))
        threading.Thread(target=work, daemon=True).start()

    def auto_backup(self):
        """Once a week, at start: a small backup in backups/ (the five newest are kept)."""
        def work():
            try:
                from fpv3d.scene import make_sources_portable
                make_sources_portable(ROOT / "scenes")   # older scene files: no full paths (your user name) in them
            except Exception as ex:                      # noqa: BLE001
                unexpected(ex)
            try:
                from fpv3d import housekeeping as hk
                f = hk.auto_backup(ROOT)
            except Exception as ex:                      # noqa: BLE001 - never in the way of starting
                unexpected(ex)
                return
            if f:
                self.root.after(0, lambda: (self.say(f"weekly backup saved: backups/{f.name}", "ok"), self.show_auto_backup()))
        threading.Thread(target=work, daemon=True).start()

    def show_auto_backup(self):
        from fpv3d import housekeeping as hk
        have = hk.auto_backups(ROOT)
        self.auto_lab.set("automatic weekly backup: " + (f"latest {have[-1].stem[len(hk.AUTO_PREFIX):]} "
                          f"({hk.human(have[-1].stat().st_size)}), {len(have)} kept in backups/" if have else "none yet (made at the next start)"))

    def backup_name(self):
        return f"alpline_backup_{time.strftime('%Y-%m-%d_%H%M')}.zip"

    def disk_backup(self):
        from tkinter import filedialog
        from fpv3d import housekeeping as hk
        (ROOT / "backups").mkdir(exist_ok=True)
        dest = filedialog.asksaveasfilename(parent=self.root, title="Save the backup", initialdir=str(ROOT / "backups"),
                                            initialfile=self.backup_name(), defaultextension=".zip",
                                            filetypes=[(f"{APP_NAME} backup", "*.zip")])
        if not dest:
            return
        kinds = hk.backup_kinds(include_scenes=self.disk_inc_scenes.get())
        self.disk_job("making the backup…", lambda: hk.backup(Path(dest), kinds, ROOT),
                      lambda r: self.disk_out.set(f"could not make the backup: {r}") if isinstance(r, Exception)
                      else (self.disk_out.set(f"backup saved: {dest} ({r['files']} files, {hk.human(r['bytes'])})"),
                            self.say("backup saved", "ok")))

    def disk_restore(self):
        from tkinter import filedialog, messagebox
        from fpv3d import housekeeping as hk
        src = filedialog.askopenfilename(parent=self.root, title="Restore a backup", initialdir=str(ROOT / "backups"),
                                         filetypes=[(f"{APP_NAME} backup", "*.zip")])
        if not src:
            return
        try:
            info = hk.read_backup(Path(src))
        except ValueError as ex:
            self.say(str(ex), "bad")
            return
        labels = ", ".join(hk.KINDS[k][0].lower() for k in info.get("kinds", []) if k in hk.KINDS)
        ans = messagebox.askyesnocancel(
            f"{APP_NAME}: restore",
            f"Backup from {info.get('made', '?')}: {labels} ({len(info['names'])} files).\n\n"
            "Replace the files you already have with the ones in the backup?\n"
            "Yes: replace them · No: keep yours, add only what's missing", parent=self.root)
        if ans is None:
            return
        def done(r):
            if isinstance(r, Exception):
                self.disk_out.set(f"could not restore: {r}")
                return
            self.disk_out.set(f"restored {r['restored']} files" + (f", kept {r['kept']} you already had" if r["kept"] else "")
                              + (f", refused {r['refused']} unsafe entries" if r["refused"] else "")
                              + ". Locations without their 3D scene: build them from the map page.")
            self.say("backup restored", "ok")
            self.after_files_changed()
        self.disk_job("restoring…", lambda: hk.restore(Path(src), ROOT, replace=bool(ans)), done)

    def disk_clear(self):
        from tkinter import messagebox
        from fpv3d import housekeeping as hk
        ks = [k for k, v in self.disk_vars.items() if v.get()]
        if not ks:
            self.say("tick what to delete first")
            return
        if "locations" in ks and "scenes" not in ks:
            ks.append("scenes")
        everything = set(ks) == set(hk.KINDS)
        names = "\n".join(f"  · {hk.KINDS[k][0]} ({hk.human(self.disk_sizes.get(k, 0))})" for k in hk.KINDS if k in ks)
        backup = self.disk_backup_first.get()
        if not messagebox.askyesno(
                f"{APP_NAME}: start fresh" if everything else f"{APP_NAME}: delete",
                (f"Start fresh: delete ALL your {APP_NAME} files?\n\n" if everything else "Delete these files?\n\n") + names
                + ("\n\nA backup zip is saved first in the 'backups' folder." if backup
                   else "\n\nNo backup: this cannot be undone."), icon="warning", parent=self.root):
            return
        if self.server_alive() and {"scenes", "locations", "settings"} & set(ks):
            self.stop()                                   # nothing open on files that are about to go
        dest = ROOT / "backups" / self.backup_name()

        def fn():
            out = {}
            if backup:
                inc = [k for k in ks if k in ("locations", "flights", "training", "settings", "scenes")]
                out["backup"] = hk.backup(dest, inc or hk.backup_kinds(), ROOT) if inc else None
            out["freed"] = hk.clear(ks, ROOT)
            return out

        def done(r):
            if isinstance(r, Exception):
                self.disk_out.set(f"nothing deleted: {r}" if isinstance(r, RuntimeError) else f"stopped: {r}")
                self.say(str(r)[:140], "bad")
                return
            freed = sum(r["freed"].values())
            self.disk_out.set(f"freed {hk.human(freed)}" + (f" · backup: backups/{dest.name}" if r.get("backup") else ""))
            self.say(f"freed {hk.human(freed)}", "ok")
            self.disk_select(False)
            if "settings" in ks:
                self.cfg = load_settings()
                self.set_mode(self.cfg.get("mode", "full"), save=False)
                self.set_open_in(self.cfg.get("open_in", "window"), save=False)
            self.after_files_changed()
        self.disk_job("making the backup…" if backup else "deleting…", fn, done)

    def after_files_changed(self):
        """Locations, scenes or flights changed on disk: refresh what the window shows."""
        self.check_offline(quiet=True)
        if self.map.selected and not any(l["name"] == self.map.selected for l in self.map.locs):
            self.select(None)

    def disk_run(self, args, confirm=None, after=None):
        from tkinter import messagebox
        if confirm and not messagebox.askyesno(f"{APP_NAME}", confirm, parent=self.root):
            return
        self.disk_out.set("working…")
        self.logo.busy(True)

        def work():
            try:
                r = subprocess.run(paths.cli_cmd() + args, cwd=str(ROOT), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                text = (r.stdout.strip().splitlines() or [""])[-1] if r.returncode == 0 else (r.stderr or r.stdout).strip()[-300:]
                self.root.after(0, lambda: (self.disk_out.set(text), after and after(r), self.measure_disk()))
            finally:
                self.root.after(0, lambda: self.logo.busy(False))
        threading.Thread(target=work, daemon=True).start()

    def disk_prune(self):                         # first say how much, then ask
        def asked(r):
            if r.returncode == 0 and "would free 0 MB" not in r.stdout:
                self.disk_run(["cache", "prune"], confirm=r.stdout.strip().splitlines()[-1].replace("would free", "This will free")
                              + ".\n\nTiles of your location files (and 1 km around them) are kept. Delete the rest?")
        self.disk_run(["cache", "prune", "--dry-run"], after=asked)

    # ------------------------------------------------------------ disk sizes
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
