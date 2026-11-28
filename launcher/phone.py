"""The phone page: sharing on the network, the PIN, the secure (https) page and the phone access check."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import tkinter as tk
import urllib.request

from fpv3d import paths
from fpv3d.brand import APP_NAME

from .common import ROOT, python_exe, unexpected
from .style import ACC, BAD, BG, BG2, BG3, FG, FG2, MONO, MONO_B, MONO_S, OK, RULE, RULE2, S, SANS, TERMINAL
from .widgets import FitLabel, Tip


class PhonePage:
    """Mixed into Launcher (launcher/app.py): methods only, they share its self."""

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
        if not messagebox.askyesno(f"{APP_NAME}: phone", f"For a secure (https) page on the phone, {APP_NAME} needs one more library "
                                   "(cryptography, about 5 MB). It lets the phone keep its screen on during a live flight.\n\n"
                                   "Install it now? (needs internet)", parent=self.root):
            self.cfg["no_https"] = True; self.save()
            return False
        self.busy_status("installing cryptography…")
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
            if not self.server_alive() or not self.running_share:
                self.busy_status("starting…")
                if not self.start():
                    return
            if os.name == "nt":
                self.check_phone_access(ask=True)
        elif self.server_alive():
            self.start()                          # back to this computer only
        self.refresh_status()

    # Windows blocks connections from other devices unless (1) the firewall lets them in and (2) the Wi-Fi is a
    # "Private" network (on "Public" networks Windows refuses them, whatever the firewall says for Private).
    RULE = "Alpline (phone)"                 # the Windows firewall rule keeps its first name (it may exist already)

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
        import time
        rows = [("Firewall rule for " + APP_NAME, rule_ok, "ok" if rule_ok else "missing"),
                ("Wi-Fi network" + ("s" if len(nets) > 1 else ""), not public,
                 "private" if not public else ", ".join(str(n.get("name")) for n in public) + " is Public"),
                ("Rules that block Python", not blocks, "none" if not blocks else str(len(blocks)))]
        if managed:
            rows.append(("Firewall managed by an organisation", False, "local rules ignored"))
        self.phone_checks = (time.strftime("%H:%M"), rows)
        self.show_phone_checks()
        if not problems:
            self.say("phone access: ok · if it still doesn't load, see logs/phone_check.txt")
            return
        if not ask or (managed and len(problems) == 1):
            self.say("phone access: " + "; ".join(problems))
            return
        fix = ("The phone can't reach this computer:\n• " + "\n• ".join(problems) + "\n\n"
               "Fix it now? Windows asks for administrator permission once. This will:\n"
               f"• allow incoming connections to {APP_NAME} (ports 8000-8019 and 8443-8462 only)\n"
               + ("• switch off the rules that block Python\n" if blocks else "")
               + ("• set " + ", ".join(n.get("name", "?") for n in public) + " to Private "
                  "(fine for your home Wi-Fi or your own phone hotspot)\n" if public else "")
               + "\nClick [phone] again later to stop sharing.")
        if not messagebox.askyesno(f"{APP_NAME}: phone access", fix, parent=self.root):
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
        except Exception as ex:
            unexpected(ex)
            return {}

    def show_qr(self):
        if self.server_alive():
            self.open_url(f"http://127.0.0.1:{self.port}/viewer/share.html")




    # ------------------------------------------------------------ phone page
    PHONE_INTRO = (f"Open {APP_NAME} on your phone: look, fly and build from the field. Deleting and renaming stay on "
                   "this computer.")
    PHONE_STEPS = (("Same Wi-Fi", "Or connect this computer to the phone's hotspot, out in the field."),
                   ("Scan the code or type the address", "In the phone's camera or browser."),
                   ("Type the PIN once", "Then add it to the home screen: it opens like an app."))

    def build_phone_page(self, parent):
        """The same parts in both looks: sharing on or off, the address, the PIN, a QR code that carries both, the
        access check. Game look: a big switch, the address and PIN large, the code on the right (H4 of the design
        canvas, phone A). Terminal look: a banner with the address and PIN, a live log of what the phones open, the
        check as [ ok ] lines and the code in amber (phone B), everything on keys."""
        self.phone_link = None                            # what the QR code carries (address + PIN)
        self.phone_checks = None                          # the last access check: (when, [(label, ok, detail)])
        self._phone_polling = False
        (self._phone_terminal if TERMINAL else self._phone_game)(parent)
        self.show_phone_checks()

    # ---- game look
    def _phone_game(self, parent):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True, padx=S(28), pady=S(20))
        tk.Label(outer, text="Phone", font=("Segoe UI", 26, "bold"), fg=FG, bg=BG, anchor="w").pack(fill="x")
        tk.Label(outer, text=self.PHONE_INTRO, font=SANS, fg=FG2, bg=BG, anchor="w", justify="left",
                 wraplength=S(900)).pack(fill="x", pady=(S(2), S(16)))
        grid = tk.Frame(outer, bg=BG)
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, minsize=S(330))
        left = tk.Frame(grid, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, S(32)))
        right = tk.Frame(grid, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")

        edge = tk.Frame(left, bg=ACC)                     # the switch's card: a yellow edge on the left
        edge.pack(fill="x")
        card = tk.Frame(edge, bg=BG2, padx=S(20), pady=S(14))
        card.pack(fill="x", padx=(S(4), 0))
        words = tk.Frame(card, bg=BG2)
        words.pack(side="left", fill="x", expand=True)
        tk.Label(words, text="Share on my network", font=("Segoe UI", 15, "bold"), fg=FG, bg=BG2, anchor="w").pack(fill="x")
        self.phone_state = FitLabel(words, font=SANS, fg=FG2, bg=BG2)
        self.phone_state.pack(fill="x")
        seg = tk.Frame(card, bg=RULE2, padx=1, pady=1)
        seg.pack(side="right")
        self.share_seg = {}
        for k, label in ((True, "ON"), (False, "OFF")):
            b = tk.Button(seg, text=label, font=("Consolas", 11, "bold"), relief="flat", bd=0, cursor="hand2",
                          padx=S(16), pady=S(6), command=lambda k=k: self.toggle_share() if bool(self.cfg.get("share")) != k else None)
            b.pack(side="left")
            self.share_seg[k] = b

        vals = tk.Frame(left, bg=BG)
        vals.pack(fill="x", pady=(S(22), 0))
        vals.columnconfigure(0, weight=3, uniform="v"); vals.columnconfigure(1, weight=2, uniform="v")
        self.phone_vals = {}
        for c, (k, label, font, fg, note) in enumerate((("addr", "ADDRESS", ("Consolas", 17, "bold"), FG, "phone_net"),
                                                        ("pin", "PIN", ("Consolas", 28, "bold"), ACC, None))):
            box = tk.Frame(vals, bg=BG)
            box.grid(row=0, column=c, sticky="new")        # full column width: the values are never cut
            tk.Label(box, text=label, font=("Consolas", 9, "bold"), fg=FG2, bg=BG, anchor="w").pack(fill="x")
            self.phone_vals[k] = FitLabel(box, font=font, fg=fg, bg=BG)
            self.phone_vals[k].pack(fill="x", pady=(S(4), 0))
            sub = tk.Label(box, text="asked once per phone" if k == "pin" else "", font=MONO_S, fg=FG2, bg=BG, anchor="w")
            sub.pack(fill="x", pady=(S(4), 0))
            if note:
                self.phone_net = sub
        steps = tk.Frame(left, bg=BG)
        steps.pack(fill="x", pady=(S(22), 0))
        for i, (a, b) in enumerate(self.PHONE_STEPS):
            tk.Frame(steps, bg=RULE, height=1).pack(fill="x")
            r = tk.Frame(steps, bg=BG)
            r.pack(fill="x", pady=S(9))
            tk.Label(r, text=str(i + 1), font=("Consolas", 16, "bold"), fg=ACC, bg=BG, width=2, anchor="nw").pack(side="left", anchor="n")
            t = tk.Frame(r, bg=BG)
            t.pack(side="left", fill="x", expand=True, padx=(S(8), 0))
            tk.Label(t, text=a, font=("Segoe UI", 11, "bold"), fg=FG, bg=BG, anchor="w").pack(fill="x")
            tk.Label(t, text=b, font=SANS, fg=FG2, bg=BG, anchor="w").pack(fill="x")

        self.qr_cv = tk.Canvas(right, width=S(300), height=S(300), bg="#ffffff", highlightthickness=0, bd=0, cursor="hand2")
        self.qr_cv.pack(anchor="w")
        self.qr_cv.bind("<Button-1>", lambda e: self.show_qr())
        Tip(self.qr_cv, "Scan it with the phone's camera: it opens the page and gives the PIN. Click for a big one.")
        tk.Label(right, text="scan with the phone's camera", font=MONO_S, fg=FG2, bg=BG, anchor="w").pack(fill="x", pady=(S(6), S(16)))
        head = tk.Frame(right, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="ACCESS FROM THE PHONE", font=("Consolas", 9, "bold"), fg=FG2, bg=BG).pack(side="left")
        self.access_when = tk.Label(head, text="", font=MONO_S, fg=FG2, bg=BG)
        self.access_when.pack(side="right")
        self.access_rows = tk.Frame(right, bg=BG)
        self.access_rows.pack(fill="x", pady=(S(4), S(12)))
        self.access_btn = self.button(right, "CHECK ACCESS", self.phone_check_now)
        self.access_btn.pack(anchor="w")
        Tip(self.access_btn, "Check that Windows lets the phone in (firewall, Private network) and offer to fix it.")

    # ---- terminal look
    def _phone_terminal(self, parent):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True, padx=S(20), pady=S(14))
        banner = tk.Frame(outer, bg=BG, highlightthickness=S(2), highlightbackground=FG, padx=S(16), pady=S(10))
        banner.pack(fill="x")
        self.phone_vals = {}
        for k, label, font in (("addr", "open on the phone", ("Consolas", 18, "bold")), ("pin", "PIN", ("Consolas", 18, "bold"))):
            box = tk.Frame(banner, bg=BG)
            box.pack(side="left", padx=(0, S(40)))
            tk.Label(box, text=label, font=MONO, fg=FG2, bg=BG, anchor="w").pack(fill="x")
            self.phone_vals[k] = tk.Label(box, text="", font=font, fg=ACC, bg=BG, anchor="w")
            self.phone_vals[k].pack(fill="x")
        box = tk.Frame(banner, bg=BG)
        box.pack(side="right")
        tk.Label(box, text="share", font=MONO, fg=FG2, bg=BG, anchor="e").pack(fill="x")
        self.share_word = tk.Label(box, text="", font=("Consolas", 14, "bold"), fg=BG, bg=FG, padx=S(8))
        self.share_word.pack(anchor="e")
        self.phone_state = FitLabel(outer, font=MONO, fg=FG2, bg=BG)
        self.phone_state.pack(fill="x", pady=(S(6), S(10)))

        grid = tk.Frame(outer, bg=BG)
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=1)
        grid.rowconfigure(0, weight=1)

        def box(c, title, **kw):
            f = tk.Frame(grid, bg=BG)
            f.grid(row=0, column=c, sticky="nsew", padx=(0 if c == 0 else S(14), 0), **kw)
            self.section(title, f)
            return f
        log = box(0, "CONNECTIONS")
        self.phone_log = tk.Text(log, height=8, font=MONO, fg=FG, bg=BG, bd=0, relief="flat", wrap="none",
                                 highlightthickness=0, cursor="arrow")
        self.phone_log.pack(fill="both", expand=True)
        self.phone_log.tag_configure("dim", foreground=FG2)
        self.phone_log.tag_configure("bad", foreground=BAD)
        self.phone_log.tag_configure("ok", foreground=ACC)
        acc = box(1, "ACCESS")
        self.access_rows = tk.Frame(acc, bg=BG)
        self.access_rows.pack(fill="x")
        self.access_when = tk.Label(acc, text="", font=MONO_S, fg=FG2, bg=BG, anchor="w")
        self.access_when.pack(fill="x", pady=(S(6), 0))
        qr = box(2, "QR")
        self.qr_cv = tk.Canvas(qr, width=S(210), height=S(210), bg=BG, highlightthickness=0, bd=0)
        self.qr_cv.pack(anchor="w")
        tk.Label(outer, text="[s] share on/off   [a] check access   [q] qr code, big   [c] copy address   [x] clear the log",
                 font=MONO, fg=ACC, bg=BG, anchor="w").pack(fill="x", pady=(S(10), 0))
        self.phone_log_shown = 0
        self.show_phone_log([])

        def key(e, act):
            if self.cfg.get("page") == "phone" and not isinstance(e.widget, (tk.Entry, tk.Text)):
                act()
        for k, act in (("s", self.toggle_share), ("a", self.phone_check_now), ("q", self.show_qr),
                       ("c", self.copy_phone_address), ("x", self.clear_phone_log)):
            self.root.bind(f"<KeyPress-{k}>", lambda e, a=act: key(e, a), add="+")

    # ---- what both looks share
    def phone_check_now(self):
        if os.name == "nt":
            self.check_phone_access(ask=True)
        else:
            self.say("the access check is for Windows")

    def show_phone(self, on: bool, sharing: bool, addr: str | None, pin: str | None, https: bool):
        """Fill the page in: called by refresh_status (server.py) whenever the server or the setting changes."""
        if TERMINAL:
            self.share_word.configure(text=" ON " if on else " OFF ", bg=FG if on else BG, fg=BG if on else FG2)
        else:
            for k, b in self.share_seg.items():
                sel = k == on
                b.configure(bg=ACC if sel else BG2, fg="#000" if sel else FG2, activebackground=ACC if sel else BG3)
        self.phone_addr = addr
        for k, text in (("addr", addr or "–"), ("pin", (f"{pin[:3]} {pin[3:]}" if not TERMINAL else pin) if pin else "–")):
            w = self.phone_vals[k]
            w.set(text) if isinstance(w, FitLabel) else w.configure(text=text)
        if not TERMINAL:
            self.phone_net.configure(text=("https · the phone can keep its screen on" if https else "http") if sharing else "")
        self.phone_state.set("shared: the phone can connect" if sharing else
                             "starts sharing when the server starts (open a page)" if on else
                             "off: this computer only")
        link = f"{addr}/viewer/?k={pin}" if sharing and addr and pin else None   # as share.html: the PIN in the link
        if link != self.phone_link or not self.qr_cv.find_all():
            self.phone_link = link
            self.draw_qr()
        self.draw_badge("phone")
        if sharing:
            self.poll_phone()

    def draw_qr(self):
        cv = self.qr_cv
        cv.delete("all")
        size = int(cv.cget("width"))
        fg, bg = (FG, BG) if TERMINAL else ("#07090c", "#ffffff")
        if not self.phone_link:
            cv.configure(bg=BG2 if not TERMINAL else BG)
            cv.create_rectangle(1, 1, size - 1, size - 1, outline=RULE, dash=(3, 3))
            cv.create_text(size // 2, size // 2, text="share is off" if not self.cfg.get("share") else "starts with the server",
                           fill=FG2, font=MONO_S)
            return
        from .qr import qr_matrix
        m = qr_matrix(self.phone_link)
        n = len(m) + 4                                    # a quiet edge of two modules all round
        cell = max(1, size // n)
        off = (size - cell * n) // 2 + 2 * cell
        cv.configure(bg=bg)
        if TERMINAL:
            cv.create_rectangle(0, 0, size, size, fill=fg, width=0)
            fg = bg                                        # amber square, dark modules, as on the canvas
        for r, row in enumerate(m):
            for c, dark in enumerate(row):
                if dark:
                    cv.create_rectangle(off + c * cell, off + r * cell, off + (c + 1) * cell, off + (r + 1) * cell,
                                        fill=fg, width=0)

    def show_phone_checks(self):
        """The access check's result as a list; "not checked yet" until it has run."""
        for w in self.access_rows.winfo_children():
            w.destroy()
        when, rows = self.phone_checks or (None, [])
        self.access_when.configure(text=f"checked {when}" if when else "")
        if not rows:
            tk.Label(self.access_rows, text="not checked yet" if os.name == "nt" else "the check is for Windows",
                     font=MONO_S if not TERMINAL else MONO, fg=FG2, bg=BG, anchor="w").pack(fill="x", pady=S(4))
            return
        for label, ok, detail in rows:
            if TERMINAL:
                r = tk.Frame(self.access_rows, bg=BG)
                r.pack(fill="x")
                tk.Label(r, text="[ ok ]" if ok else "[ !! ]", font=MONO, fg=ACC if ok else BAD, bg=BG).pack(side="left")
                tk.Label(r, text=f" {label}" + (f" · {detail}" if detail else ""), font=MONO, fg=FG if ok else BAD,
                         bg=BG, anchor="w").pack(side="left")
            else:
                tk.Frame(self.access_rows, bg=RULE, height=1).pack(fill="x")
                r = tk.Frame(self.access_rows, bg=BG)
                r.pack(fill="x", pady=S(6))
                tk.Label(r, text=label, font=SANS, fg=FG, bg=BG, anchor="w").pack(side="left")
                tk.Label(r, text=("✓ " if ok else "✗ ") + detail, font=MONO_B, fg=OK if ok else BAD, bg=BG).pack(side="right")

    def poll_phone(self):
        """While the phone page is open and sharing is on: the log of what phones opened, every two seconds."""
        if self._phone_polling or not TERMINAL:
            return
        self._phone_polling = True

        def tick():
            if self.cfg.get("page") != "phone" or not (self.server_alive() and self.running_share):
                self._phone_polling = False
                return

            def work():
                d = self.share_info()
                self.root.after(0, lambda: self.show_phone_log(d.get("phones") or []))
            threading.Thread(target=work, daemon=True).start()
            self.root.after(2000, tick)
        tick()

    def show_phone_log(self, events):
        if not TERMINAL:
            return
        t = self.phone_log
        t.configure(state="normal")
        t.delete("1.0", "end")
        shown = events[self.phone_log_shown:] if self.phone_log_shown <= len(events) else events
        for e in reversed(shown[-14:]):                   # newest on top
            what = e.get("what", "")
            t.insert("end", f"{e.get('t', '')}  {e.get('ip', ''):<16} ", "dim")
            t.insert("end", what + "\n", "bad" if what == "wrong PIN" else "ok" if what == "PIN ok" else ())
        if not shown:
            t.insert("end", "what the phones open shows here, once sharing is on", "dim")
        t.configure(state="disabled")
        self._phone_events = events

    def clear_phone_log(self):
        self.phone_log_shown = len(getattr(self, "_phone_events", []))
        self.show_phone_log(getattr(self, "_phone_events", []))

    def copy_phone_address(self):
        addr = getattr(self, "phone_addr", None)
        if addr:
            self.root.clipboard_clear()
            self.root.clipboard_append(addr)
            self.say("address copied")
