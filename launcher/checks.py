"""The checks page: Alpline's own tests on this computer and the library check (requirements.txt)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk

from fpv3d import paths
from fpv3d.brand import APP_NAME

from .common import APP, python_exe, unexpected
from .style import ACC, BAD, BG, BG2, FG, FG2, MONO_B, MONO_S, OK, RULE, S, SANS
from .widgets import FitLabel, Tip


class ChecksPage:
    """Mixed into Launcher (launcher/app.py): methods only, they share its self."""

    # ------------------------------------------------------------ checks page
    CHECK_GROUPS = (("basic", "Basics", "coordinates, flight logs, radio maths, telemetry, blackbox, map tiles"),
                    ("server", "Server", "pages load, bad requests refused, one build at a time, cache, https"),
                    ("security", "Security", "other websites blocked, names shown as text, private files hidden, phone PIN"),
                    ("robust", "Robustness", "damaged logs, blackbox files, radio data and location files"),
                    ("journeys", "Journeys", "build, add a log, rename, delete, restore, blackbox, cache clean-up"),
                    ("files", "Your files", "safe saving, error log, clean-up, backup and restore, disk space"),
                    ("battery", "Battery", "resistance and mAh found, glitches filtered, packs, charger check, blackbox to 3D"),
                    ("snapshots", "Signal model", "line of sight and range give the same results as before"),
                    ("performance", "Speed-ups", "compact terrain and compression give the same data"),
                    ("sim", "Training flight", "flight model: hover, battery, top speed, propwash, walls"),
                    ("launcher", "Launcher", "USB detection, map groups and zoom"))

    def build_checks_page(self, parent):
        col = self.page_frame(parent, "CHECKS",
                              f"Runs {APP_NAME}'s own tests on this computer, about 20 seconds. Your locations and flights are "
                              "not touched: the tests work in a temporary folder with a fake swisstopo service.")
        self.libs_row = tk.Frame(col, bg=BG2, padx=S(8), pady=S(6), highlightthickness=1, highlightbackground=ACC)
        self.libs_lab = tk.Label(self.libs_row, text="", font=SANS, fg=FG, bg=BG2, justify="left", anchor="w", wraplength=S(460))
        self.libs_lab.pack(side="left", fill="x", expand=True)
        self.libs_btn = self.button(self.libs_row, "[update libraries]", self.update_libraries, primary=True)
        self.libs_btn.pack(side="right")
        self.libs_diff = []
        self.check_top = row = tk.Frame(col, bg=BG); row.pack(fill="x")
        self.check_btn = self.button(row, "[run quick check]", self.run_checks, primary=True)
        self.check_btn.pack(side="left")
        self.copy_btn = self.button(row, "[copy report]", self.copy_check_report)
        self.copy_btn.pack(side="left", padx=(S(8), 0))
        Tip(self.copy_btn, "Copy the results, to paste them in a message when something fails.")
        self.check_status = FitLabel(col, font=MONO_S, fg=FG2, bg=BG)
        self.check_status.pack(fill="x", pady=(S(8), S(4)))
        self.check_bar = tk.Canvas(col, height=S(6), bg=BG2, highlightthickness=0)
        self.check_bar.pack(fill="x", pady=(0, S(10)))
        grid = tk.Frame(col, bg=BG); grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.check_rows = {}
        for i, (key, label, desc) in enumerate(self.CHECK_GROUPS):
            tk.Label(grid, text=label, font=MONO_B, fg=FG, bg=BG, width=17, anchor="w").grid(row=i, column=0, sticky="w", pady=S(2))
            d = FitLabel(grid, font=SANS, fg=FG2, bg=BG); d.set(desc); d.grid(row=i, column=1, sticky="ew", padx=(0, S(8)))
            res = tk.Label(grid, text="–", font=("Consolas", 10), fg=FG2, bg=BG, width=13, anchor="e")
            res.grid(row=i, column=2, sticky="e")
            self.check_rows[key] = res
        box = tk.Frame(col, bg=RULE, padx=1, pady=1); box.pack(fill="x", pady=(S(12), 0))
        self.check_log = tk.Text(box, height=9, font=MONO_S, fg=FG2, bg=BG2, bd=0, relief="flat", wrap="word",
                                 padx=S(8), pady=S(6), highlightthickness=0, cursor="arrow")
        self.check_log.pack(fill="x")
        self.check_log.tag_configure("bad", foreground=BAD)
        self.check_log.tag_configure("skip", foreground=ACC)
        self.check_log.tag_configure("ok", foreground=OK)
        self.check_proc, self.check_results = None, []
        self.check_runner = APP / "tests" / "run_quick.py"
        self.check_write("Failures and skipped checks show here, with what went wrong.", clear=True)
        if not self.check_runner.exists():                 # the installed app comes without the tests
            self.check_btn.configure(state="disabled")
            self.check_status.set("the checks come with the source folder (PyCharm / Alpline.bat), not with the installed app")
        else:
            self.show_last_check()

    # ------------------------------------------------------------ libraries (requirements.txt)
    def check_libraries(self):
        """After an update of Alpline a pinned library may have changed: compare what is installed in the project's
        Python with requirements.txt (in the background) and offer one button to install the difference."""
        if paths.FROZEN or not (APP / "requirements.txt").exists():
            return

        def work():
            try:
                r = subprocess.run([python_exe(), "-m", "fpv3d.deps", str(APP / "requirements.txt")], cwd=str(APP),
                                   capture_output=True, text=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                diff = json.loads(r.stdout or "[]") if r.returncode == 0 else []
            except Exception as ex:                      # noqa: BLE001 - no check, no notice
                unexpected(ex)
                diff = []
            self.root.after(0, lambda: self.show_libraries(diff))
        threading.Thread(target=work, daemon=True).start()

    def show_libraries(self, diff):
        self.libs_diff = diff
        if not diff:
            self.libs_row.pack_forget()
            self.draw_badge("checks")
            return
        parts = [f"{d['name']} {d['have'] or 'missing'} → {d['want']}" for d in diff]
        self.libs_lab.configure(text="Libraries to update: " + ", ".join(parts))
        self.libs_row.pack(fill="x", pady=(0, S(10)), before=self.check_top)
        self.say(f"{len(diff)} library update(s) waiting: see the checks page")
        self.draw_badge("checks")

    def update_libraries(self):
        if self.server_alive():
            self.stop()                                   # the server holds the libraries open while it runs
        self.libs_btn.configure(state="disabled")
        self.libs_lab.configure(text="installing… (needs internet, about a minute)")
        self.logo.busy(True)

        def work():
            r = subprocess.run([python_exe(), "-m", "pip", "install", "-r", str(APP / "requirements.txt")], cwd=str(APP),
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

            def done():
                self.logo.busy(False)
                self.libs_btn.configure(state="normal")
                if r.returncode == 0:
                    self.say("libraries updated", "ok")
                    self.check_libraries()
                else:
                    self.libs_lab.configure(text="could not install: " + ((r.stderr or r.stdout).strip().splitlines() or ["?"])[-1][:200])
            self.root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def check_write(self, text, tag=None, clear=False):
        self.check_log.configure(state="normal")
        if clear:
            self.check_log.delete("1.0", "end")
        self.check_log.insert("end", text, tag or ())
        self.check_log.see("end")
        self.check_log.configure(state="disabled")

    def show_last_check(self):
        lc = self.cfg.get("last_check")
        if not lc:
            self.check_status.set("not run yet on this computer")
            return
        self.check_status.set(f"last run {lc['when']} · {lc['ok']} ok · {lc['failed']} failed · {lc['skipped']} skipped"
                              f" ({lc['seconds']:.0f} s)", fg=BAD if lc["failed"] else FG2)

    def draw_check_bar(self, done, total, bad):
        c = self.check_bar
        c.delete("all")
        w = c.winfo_width() or S(600)
        if total:
            c.create_rectangle(0, 0, w * done / total, S(6), fill=BAD if bad else OK, outline="")

    def run_checks(self):
        if self.check_proc is not None:
            return
        self.check_results = []
        for r in self.check_rows.values():
            r.configure(text="…", fg=FG2)
        self.check_write("", clear=True)
        self.check_btn.configure(state="disabled", text="[running…]")
        self.check_status.set("running…", fg=FG2)
        self.draw_check_bar(0, 1, False)
        self.logo.busy(True)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(APP)}
        try:
            self.check_proc = subprocess.Popen([python_exe(), "-u", str(self.check_runner)], cwd=str(APP), env=env,
                                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                               encoding="utf-8", errors="replace",
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as ex:
            self.check_write(f"could not start the checks: {ex}\n", "bad")
            self._checks_done(None, 0)
            return
        t0 = time.time()

        def read():
            total, summary = 0, None
            for line in self.check_proc.stdout:
                parts = line.rstrip("\n").split("\t")
                if parts[0] == "PLAN" and len(parts) > 1:
                    total = int(parts[1])
                elif parts[0] == "RESULT" and len(parts) >= 6:
                    self.root.after(0, lambda p=parts, n=total: self._check_result(p, n))
                elif parts[0] == "DONE":
                    summary = parts
            self.check_proc.wait()
            self.root.after(0, lambda: self._checks_done(summary, time.time() - t0))
        threading.Thread(target=read, daemon=True).start()

    def _check_result(self, p, total):
        _, group, name, state, secs, msg = p[:6]
        self.check_results.append(dict(group=group, name=name, state=state, secs=float(secs or 0), msg=msg.replace(chr(31), "\n")))
        mine = [r for r in self.check_results if r["group"] == group]
        nbad = sum(r["state"] == "fail" for r in mine)
        nok = sum(r["state"] == "ok" for r in mine)
        lab = self.check_rows.get(group)
        if lab:
            lab.configure(text=f"{nbad} failed" if nbad else f"{nok} ok" + (f", {len(mine) - nok} skip" if len(mine) > nok else ""),
                          fg=BAD if nbad else OK)
        nice = name[5:].replace("_", " ") if name.startswith("test_") else name
        if state == "fail":
            self.check_write(f"✗ {group} · {nice}\n", "bad")
            self.check_write("   " + self.check_results[-1]["msg"].strip().replace("\n", "\n   ") + "\n")
        elif state == "skip":
            self.check_write(f"– {group} · {nice}: {self.check_results[-1]['msg']}\n", "skip")
        self.draw_check_bar(len(self.check_results), max(total, 1), any(r["state"] == "fail" for r in self.check_results))

    def _checks_done(self, summary, seconds):
        self.check_proc = None
        self.logo.busy(False)
        self.check_btn.configure(state="normal", text="[run quick check]")
        res = self.check_results
        ok, bad, skip = (sum(r["state"] == s for r in res) for s in ("ok", "fail", "skip"))
        if not res:
            self.check_write("the checks did not run (is the project's .venv complete? pip install -r requirements.txt)\n", "bad")
            self.check_status.set("the checks did not run", fg=BAD)
            return
        self.check_log.see("1.0")                         # the first problem on top
        if not bad:
            self.check_write(f"✓ all {ok} checks passed" + (f", {skip} skipped" if skip else "") + "\n", "ok")
        self.cfg["last_check"] = dict(when=time.strftime("%d %b %H:%M"), ok=ok, failed=bad, skipped=skip, seconds=seconds)
        self.save()
        self.show_last_check()
        self.draw_badge("checks")
        self.say(f"checks: all {ok} passed" if not bad else f"checks: {bad} failed (see the checks page)", "ok" if not bad else "bad")

    def copy_check_report(self):
        res = self.check_results
        if not res:
            return self.say("run the checks first")
        try:
            from fpv3d import __version__ as ver
        except Exception:
            ver = "?"
        lines = [f"{APP_NAME} {ver} checks, {time.strftime('%Y-%m-%d %H:%M')}, {sys.platform}, Python {sys.version.split()[0]}"]
        for key, label, _ in self.CHECK_GROUPS:
            mine = [r for r in res if r["group"] == key]
            if mine:
                odd = [f"{r['name'][5:]} {r['state']}" for r in mine if r["state"] != "ok"]
                lines.append(f"{label}: " + (", ".join(odd) if odd else f"all {len(mine)} ok"))
        for r in res:
            if r["state"] == "fail":
                lines.append(f"\n--- {r['group']} / {r['name']}\n{r['msg'].strip()}")
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        self.say("report copied: paste it in a message")
