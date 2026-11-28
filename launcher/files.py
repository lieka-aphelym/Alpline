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
from .style import ACC, BG, BG2, FG, FG2, GREY, MONO, MONO_B, MONO_S, RULE, S, SANS, TERMINAL
from .widgets import FitLabel, Tip


class FilesPage:
    """Mixed into Launcher (launcher/app.py): methods only, they share its self."""

    # ------------------------------------------------------------ disk page
    FILES_INTRO = (f"What {APP_NAME} keeps on this computer. Tick what to delete: a backup zip is made first unless you "
                   "untick it. Ticking everything starts fresh, like a new install.")
    SHADES = ("#a9b4c2", "#7d8796", "#5f6a78", "#4a5462", "#3a424e", "#2f3640", "#262c35", "#20252d", "#1b2027")

    def build_disk_page(self, parent):
        """The same parts in both looks: what each kind of file takes, ticks to delete, clean-up, backups. Game look:
        the space as a map of blocks, big for big, ticked ones in yellow, and a backups card (H4 of the design canvas,
        files B). Terminal look: the folder as a tree with sizes like du, the scenes place by place, every action on
        a key."""
        from fpv3d.housekeeping import KINDS
        self.disk_vars = {k: tk.BooleanVar(value=False) for k in KINDS}
        self.disk_sizes, self.scene_sizes, self.disk_labels = {}, [], {}
        self.disk_backup_first = tk.BooleanVar(value=True)
        self.disk_inc_scenes = tk.BooleanVar(value=False)
        (self._disk_terminal if TERMINAL else self._disk_game)(parent)
        self.show_auto_backup()

    # ---- game look
    def _disk_game(self, parent):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True, padx=S(28), pady=S(20))
        tk.Label(outer, text="Files", font=("Segoe UI", 26, "bold"), fg=FG, bg=BG, anchor="w").pack(fill="x")
        tk.Label(outer, text=self.FILES_INTRO, font=SANS, fg=FG2, bg=BG, anchor="w", justify="left",
                 wraplength=S(900)).pack(fill="x", pady=(S(2), S(14)))
        grid = tk.Frame(outer, bg=BG)
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, minsize=S(320))
        grid.rowconfigure(0, weight=1)
        left = tk.Frame(grid, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, S(28)))
        head = tk.Frame(left, bg=BG)
        head.pack(fill="x", pady=(0, S(8)))
        self.disk_free = FitLabel(head, font=("Consolas", 12, "bold"), fg=FG, bg=BG)
        self.disk_free.pack(side="left", fill="x", expand=True)
        self.disk_sel_total = tk.Label(head, text="", font=MONO_B, fg=ACC, bg=BG)
        self.disk_sel_total.pack(side="right")
        self.disk_map = tk.Canvas(left, bg=BG, highlightthickness=0, bd=0, cursor="hand2")
        self.disk_map.pack(fill="both", expand=True)
        self.disk_map.bind("<Configure>", lambda e: self.draw_disk())
        self.disk_map.bind("<Button-1>", self._disk_map_click)
        self.disk_chips = tk.Frame(left, bg=BG)
        self.disk_chips.pack(fill="x", pady=(S(3), 0))
        act = tk.Frame(left, bg=BG)
        act.pack(fill="x", pady=(S(12), 0))
        self.button(act, "ALL: START FRESH", lambda: self.disk_select(True)).pack(side="left")
        self.button(act, "NONE", lambda: self.disk_select(False)).pack(side="left", padx=(S(6), S(14)))
        self.check(act, "make a backup first", self.disk_backup_first).pack(side="left")
        self.disk_del_btn = self.button(act, "DELETE SELECTED", self.disk_clear, danger=True)
        self.disk_del_btn.pack(side="right")
        b1 = self.button(act, "CLEAN UNUSED TILES", self.disk_prune)
        b1.pack(side="right", padx=(0, S(8)))
        Tip(b1, "Deletes only the downloaded tiles that none of your location files uses. Your locations still build offline.")
        self.disk_out = FitLabel(left, font=SANS, fg=FG2, bg=BG)
        self.disk_out.pack(fill="x", pady=(S(8), 0))

        edge = tk.Frame(grid, bg=ACC)
        edge.grid(row=0, column=1, sticky="nsew")
        card = tk.Frame(edge, bg=BG2, padx=S(18), pady=S(14))
        card.pack(fill="both", expand=True, padx=(S(4), 0))
        tk.Label(card, text="Backups", font=("Segoe UI", 15, "bold"), fg=FG, bg=BG2, anchor="w").pack(fill="x")
        tk.Label(card, text="Your places, flights, training flights and settings in one zip: keep it safe, or move "
                            "everything to another PC. Restoring never deletes anything; files you already have are kept.",
                 font=SANS, fg=FG2, bg=BG2, anchor="w", justify="left", wraplength=S(280)).pack(fill="x", pady=(S(4), S(12)))
        br = tk.Frame(card, bg=BG2)
        br.pack(fill="x")
        self.button(br, "BACK UP NOW", self.disk_backup, primary=True).pack(side="left")
        self.button(br, "RESTORE…", self.disk_restore).pack(side="left", padx=(S(8), 0))
        self.disk_inc_cb = self.check(card, "include the built 3D scenes", self.disk_inc_scenes)
        self.disk_inc_cb.configure(bg=BG2, activebackground=BG2, wraplength=S(280), justify="left")
        self.disk_inc_cb.pack(fill="x", pady=(S(10), S(12)))
        self.auto_lab = FitLabel(card, font=MONO_S, fg=FG2, bg=BG2)
        self.auto_lab.pack(fill="x")
        self.backup_list = tk.Frame(card, bg=BG2)
        self.backup_list.pack(fill="x", pady=(S(6), 0))

    def _treemap(self, items, x, y, w, h):
        """Squarified treemap: [(key, value)] (largest first) -> [(key, x, y, w, h)], blocks as square as can be."""
        total = sum(v for _, v in items)
        if total <= 0 or w <= 0 or h <= 0:
            return []
        rest = [(k, v * w * h / total) for k, v in items]
        out = []
        while rest:
            short = min(w, h)

            def worst(row, short=short):
                s = sum(a for _, a in row)
                return max(max(short * short * a / (s * s), s * s / (short * short * a)) for _, a in row)
            row, i = [rest[0]], 1
            while i < len(rest) and worst(row + [rest[i]]) <= worst(row):
                row.append(rest[i])
                i += 1
            rest = rest[i:]
            s = sum(a for _, a in row)
            if w >= h:                                    # a column on the left
                cw, yy = s / h, y
                for k, a in row:
                    out.append((k, x, yy, cw, a / cw))
                    yy += a / cw
                x, w = x + cw, w - cw
            else:                                         # a row on top
                rh, xx = s / w, x
                for k, a in row:
                    out.append((k, xx, y, a / rh, rh))
                    xx += a / rh
                y, h = y + rh, h - rh
        return out

    def _disk_split(self):
        """Kinds big enough for a block (2 % of the total or more), and the small ones, shown as a row of chips."""
        from fpv3d.housekeeping import KINDS
        total = sum(self.disk_sizes.values()) or 1
        order = sorted(KINDS, key=lambda k: -self.disk_sizes.get(k, 0))
        return ([k for k in order if self.disk_sizes.get(k, 0) / total >= .02],
                [k for k in order if self.disk_sizes.get(k, 0) / total < .02])

    def draw_disk(self):
        if TERMINAL:
            return self.draw_disk_tree()
        from fpv3d.housekeeping import KINDS, human
        cv = self.disk_map
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 50 or h < 50:
            return
        if not self.disk_sizes:
            cv.create_text(w // 2, h // 2, text="measuring…", fill=FG2, font=MONO)
            return
        big, small = self._disk_split()
        self._disk_blocks = []
        g = S(3)
        for i, (k, x, y, bw, bh) in enumerate(self._treemap([(k, self.disk_sizes[k]) for k in big], 0, 0, w, h)):
            on = self.disk_vars[k].get()
            fill = ACC if on else self.SHADES[min(i, len(self.SHADES) - 1)]
            ink = "#07090c" if on or i < 2 else FG
            x0, y0, x1, y1 = int(x), int(y), int(x + bw) - g, int(y + bh) - g
            cv.create_rectangle(x0, y0, x1, y1, fill=fill, width=0)
            self._disk_blocks.append((k, x0, y0, x1, y1))
            label, short, _ = KINDS[k]
            if x1 - x0 > S(70) and y1 - y0 > S(34):
                cv.create_text(x0 + S(12), y0 + S(10), text=("✓ " if on else "") + label, anchor="nw", fill=ink,
                               font=("Segoe UI", 11, "bold"), width=max(10, x1 - x0 - S(20)))
                cv.create_text(x0 + S(12), y1 - S(10), text=human(self.disk_sizes[k]), anchor="sw", fill=ink,
                               font=("Consolas", 15 if y1 - y0 > S(90) else 11, "bold"))
                if y1 - y0 > S(110) and x1 - x0 > S(150):
                    cv.create_text(x0 + S(12), y1 - S(38), text=short, anchor="sw", fill=ink, font=SANS,
                                   width=max(10, x1 - x0 - S(20)))
        for c in self.disk_chips.winfo_children():
            c.destroy()
        for i, k in enumerate(small):
            on = self.disk_vars[k].get()
            chip = tk.Label(self.disk_chips, text=f"{'✓ ' if on else ''}{KINDS[k][0]}  {human(self.disk_sizes.get(k, 0))}",
                            font=("Segoe UI", 9, "bold" if on else "normal"), fg="#07090c" if on else FG, bg=ACC if on else BG2,
                            padx=S(8), pady=S(5), cursor="hand2", anchor="w")
            chip.grid(row=i // 4, column=i % 4, sticky="ew", padx=(0, S(3)), pady=(0, S(3)))
            self.disk_chips.columnconfigure(i % 4, weight=1, uniform="chips")
            chip.bind("<Button-1>", lambda e, k=k: self._disk_toggle(k))

    def _disk_map_click(self, e):
        for k, x0, y0, x1, y1 in getattr(self, "_disk_blocks", []):
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                return self._disk_toggle(k)

    def _disk_toggle(self, k):
        self.disk_vars[k].set(not self.disk_vars[k].get())
        self.disk_ticked(k)

    # ---- terminal look
    def _disk_terminal(self, parent):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True, padx=S(20), pady=S(14))
        grid = tk.Frame(outer, bg=BG)
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=1)
        grid.rowconfigure(0, weight=1)
        left = tk.Frame(grid, bg=BG)
        left.grid(row=0, column=0, sticky="nsew")
        self.section("DU · YOUR FILES", left)
        self.disk_tree = tk.Text(left, font=MONO, fg=FG, bg=BG, bd=0, relief="flat", wrap="none", height=16,
                                 highlightthickness=0, cursor="arrow")
        self.disk_tree.pack(fill="both", expand=True)
        for tag, kw in (("root", dict(foreground=ACC)), ("dim", dict(foreground=FG2)), ("grey", dict(foreground=GREY)),
                        ("tick", dict(foreground=ACC)), ("cur", dict(background=FG, foreground=BG))):
            self.disk_tree.tag_configure(tag, **kw)
        self.disk_tree.bind("<Button-1>", self._disk_tree_click)
        foot = tk.Frame(left, bg=BG)
        foot.pack(fill="x", pady=(S(6), 0))
        self.disk_free = FitLabel(foot, font=MONO, fg=FG2, bg=BG)
        self.disk_free.pack(side="left", fill="x", expand=True)
        self.disk_sel_total = tk.Label(foot, text="", font=MONO, fg=ACC, bg=BG)
        self.disk_sel_total.pack(side="right")
        self.check(left, "make a backup first", self.disk_backup_first).pack(anchor="w")
        self.disk_out = FitLabel(left, font=MONO, fg=FG2, bg=BG)
        self.disk_out.pack(fill="x", pady=(S(4), 0))
        right = tk.Frame(grid, bg=BG, width=S(300))
        right.grid(row=0, column=1, sticky="nsew", padx=(S(18), 0))
        right.pack_propagate(False)
        self.section("BACKUPS", right)
        self.backup_list = tk.Frame(right, bg=BG)
        self.backup_list.pack(fill="x")
        self.auto_lab = tk.Label(right, text="", font=MONO_S, fg=GREY, bg=BG, anchor="w", justify="left", wraplength=S(290))
        self.auto_lab.set = lambda t: self.auto_lab.configure(text=t)
        self.auto_lab.pack(fill="x", pady=(S(6), 0))
        self.disk_inc_cb = self.check(right, "include the built 3D scenes", self.disk_inc_scenes)
        self.disk_inc_cb.configure(wraplength=S(280), justify="left")
        self.disk_inc_cb.pack(fill="x", pady=(S(8), 0))
        self.disk_del_btn = None
        tk.Label(outer, text="[↑ ↓] choose  [→ ←] open/close  [space] tick  [a] all  [n] none  [d] delete selected  "
                             "[t] clean unused tiles  [b] back up now  [r] restore",
                 font=MONO, fg=ACC, bg=BG, anchor="w").pack(fill="x", pady=(S(10), 0))
        self.disk_cur, self.disk_open, self.disk_rows = 0, False, []

        def key(e, act):
            if self.cfg.get("page") == "disk" and (e.widget is self.disk_tree or not isinstance(e.widget, (tk.Entry, tk.Text))):
                act()
                return "break"
        for k, act in (("space", lambda: self.disk_tick_row()), ("a", lambda: self.disk_select(True)),
                       ("n", lambda: self.disk_select(False)), ("d", self.disk_clear), ("t", self.disk_prune),
                       ("b", self.disk_backup), ("r", self.disk_restore)):
            self.root.bind(f"<KeyPress-{k}>", lambda e, a=act: key(e, a), add="+")

    def draw_disk_tree(self):
        """The tree: the data folder, its kinds of files with a tick box and size, the scenes opened place by place."""
        from fpv3d.housekeeping import KINDS
        t = self.disk_tree
        t.configure(state="normal")
        t.delete("1.0", "end")
        total = sum(self.disk_sizes.values())
        where = str(ROOT) if len(str(ROOT)) < 48 else "…" + os.sep + os.sep.join(Path(ROOT).parts[-2:])
        t.insert("end", f"      {self._du(total):>6}  {where}\n", "root")
        kinds = sorted(KINDS, key=lambda k: -self.disk_sizes.get(k, 0)) if self.disk_sizes else list(KINDS)
        rows = []
        for k in kinds:
            rows.append(("kind", k))
            if k == "scenes" and self.disk_open:
                rows += [("scene", n) for n, _ in self.scene_sizes]
        self.disk_rows = rows
        self.disk_cur = min(self.disk_cur, len(rows) - 1)
        last_kind = kinds[-1]
        for i, (kind, k) in enumerate(rows):
            cur = i == self.disk_cur
            t.insert("end", "▶ " if cur else "  ")
            if kind == "kind":
                on = self.disk_vars[k].get()
                t.insert("end", "[x]" if on else "[ ]", "tick" if on else ())
                size = self._du(self.disk_sizes[k]) if k in self.disk_sizes else "…"
                branch = "└──" if k == last_kind else "├──"
                more = (" ▾" if self.disk_open else " ▸") if k == "scenes" and self.scene_sizes else ""
                t.insert("end", f" {size:>6}  {branch} ")
                t.insert("end", f"{KINDS[k][0].lower()}{more}", "cur" if cur else ())
                t.insert("end", f"   {KINDS[k][1]}\n", "grey")
            else:
                size = dict(self.scene_sizes).get(k, 0)
                pipe = "│  " if k != last_kind else "   "
                t.insert("end", f"    {self._du(size):>6}  {pipe} ", "dim")
                t.insert("end", k, "cur" if cur else "dim")
                t.insert("end", "\n")
        t.configure(state="disabled")
        t.see(f"{self.disk_cur + 2}.0")

    @staticmethod
    def _du(n: float) -> str:
        """Sizes as du -h writes them: 1.8G, 612M, 40K."""
        for unit in ("B", "K", "M", "G"):
            if n < 1000 or unit == "G":
                return f"{n:.0f}{unit}" if unit in ("B", "K") or n >= 10 else f"{n:.1f}{unit}"
            n /= 1000
        return f"{n:.1f}G"

    def disk_move(self, step):
        if self.disk_rows:
            self.disk_cur = max(0, min(len(self.disk_rows) - 1, self.disk_cur + step))
            self.draw_disk_tree()

    def disk_fold(self, step):
        """Right opens the scenes place by place, Left closes them (from anywhere)."""
        if step > 0 and self.disk_rows and self.disk_rows[self.disk_cur] == ("kind", "scenes"):
            self.disk_open = True
        elif step < 0 and self.disk_open:
            self.disk_open = False
            self.disk_cur = [r[1] for r in self.disk_rows].index("scenes")
        self.draw_disk_tree()

    def disk_tick_row(self):
        if self.disk_rows and self.disk_rows[self.disk_cur][0] == "kind":
            self._disk_toggle(self.disk_rows[self.disk_cur][1])

    def _disk_tree_click(self, e):
        line = int(self.disk_tree.index(f"@{e.x},{e.y}").split(".")[0]) - 2
        if 0 <= line < len(self.disk_rows):
            self.disk_cur = line
            if self.disk_rows[line] == ("kind", "scenes") and e.x > S(200):
                self.disk_open = not self.disk_open
                self.draw_disk_tree()
            else:
                self.disk_tick_row() if e.x < S(70) else self.draw_disk_tree()
        return "break"

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
        if not TERMINAL:
            self.disk_del_btn.configure(text=f"DELETE {human(tot)}" if ks else "DELETE SELECTED")
        self.draw_disk()

    def measure_disk(self):
        from fpv3d.housekeeping import free_bytes, human, sizes

        def work():
            res, free = sizes(ROOT), free_bytes(ROOT)
            scenes = []
            try:
                for d in (ROOT / "scenes").iterdir():
                    if d.is_dir():
                        scenes.append((d.name, self.folder_size(d)[0]))
            except OSError:
                pass
            scenes.sort(key=lambda s: -s[1])

            def show():
                self.disk_sizes, self.scene_sizes = res, scenes
                used = sum(res.values())
                self.disk_free.set(f"{APP_NAME} uses {human(used)}" + (f" · {human(free)} free on the disk" if free is not None else ""))
                self.disk_inc_cb.configure(text=f"include the built 3D scenes ({human(res.get('scenes', 0))}; "
                                                "no rebuild needed after restoring)")
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
        """The line on the weekly backup, and the list of the backups in backups/, newest first."""
        from fpv3d import housekeeping as hk
        have = hk.auto_backups(ROOT)
        self.auto_lab.set("automatic: once a week, " + (f"{len(have)} kept in backups/" if have else "the first at the next start"))
        for w in self.backup_list.winfo_children():
            w.destroy()
        try:
            zips = sorted((ROOT / "backups").glob("*.zip"), key=lambda f: -f.stat().st_mtime)[:6]
        except OSError:
            zips = []
        bg = self.backup_list.cget("bg")
        for f in zips:
            st = f.stat()
            auto = f.name.startswith(hk.AUTO_PREFIX)
            r = tk.Frame(self.backup_list, bg=bg)
            r.pack(fill="x")
            if not TERMINAL:
                tk.Frame(self.backup_list, bg=RULE, height=1).pack(fill="x", before=r)
            when = time.strftime("%d %b", time.localtime(st.st_mtime))
            tk.Label(r, text=f"{when} · {'automatic' if auto else 'by hand'}", font=SANS if not TERMINAL else MONO, fg=FG,
                     bg=bg, anchor="w").pack(side="left", pady=S(4))
            tk.Label(r, text=hk.human(st.st_size), font=MONO, fg=FG2, bg=bg).pack(side="right")
        if not zips:
            tk.Label(self.backup_list, text="no backup yet", font=MONO_S, fg=FG2, bg=bg, anchor="w").pack(fill="x")

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
