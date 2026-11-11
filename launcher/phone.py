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
from .style import BG, FG, FG2, MONO_S, S, SANS
from .widgets import Tip


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
    def build_phone_page(self, parent):
        col = self.page_frame(parent, "PHONE",
                              f"Open {APP_NAME} on your phone: same Wi-Fi as this computer, or connect the computer to the "
                              "phone's hotspot. The phone can look, fly and build; deleting and renaming stay on this computer.")
        row = tk.Frame(col, bg=BG); row.pack(fill="x")
        self.share_btn = self.button(row, "[share on my network: off]", self.toggle_share)
        self.share_btn.pack(side="left")
        self.qr_btn = self.button(row, "[qr code]", self.show_qr)
        self.qr_btn.pack(side="left", padx=(S(6), 0))
        Tip(self.qr_btn, "Show a QR code to scan with the phone's camera.")
        ck = self.button(row, "[check access]", lambda: self.check_phone_access(ask=True) if os.name == "nt"
                         else self.say("the access check is for Windows"))
        ck.pack(side="left", padx=(S(6), 0))
        Tip(ck, "Check that Windows lets the phone in (firewall, Private network) and offer to fix it.")
        grid = tk.Frame(col, bg=BG); grid.pack(fill="x", pady=(S(14), 0))
        grid.columnconfigure(1, weight=1)
        self.phone_vals = {}
        for i, (k, label) in enumerate((("addr", "address"), ("pin", "PIN"), ("state", "state"))):
            tk.Label(grid, text=label, font=MONO_S, fg=FG2, bg=BG, width=10, anchor="w").grid(row=i, column=0, sticky="w", pady=S(2))
            e = tk.Entry(grid, font=("Consolas", 11, "bold"), fg=FG, bg=BG, bd=0, relief="flat", readonlybackground=BG,
                         highlightthickness=0, insertbackground=FG)
            e.grid(row=i, column=1, sticky="ew", pady=S(2))
            self.phone_vals[k] = e
        tk.Label(col, text="Type the address in the phone's browser, then the PIN once. Add it to the home screen for an "
                           "app icon.", font=SANS, fg=FG2, bg=BG, justify="left", anchor="w", wraplength=S(640)).pack(fill="x", pady=(S(12), 0))

    def set_entry(self, key, text):
        e = self.phone_vals[key]
        e.configure(state="normal"); e.delete(0, "end"); e.insert(0, text); e.configure(state="readonly")
