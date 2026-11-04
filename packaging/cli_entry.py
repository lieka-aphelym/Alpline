"""Entry of alpline-cli.exe (the packaged app's console part): the server and every `fpv3d` command (builds, cache
cleaning...). Started by Alpline.exe in the background, never shown."""
import multiprocessing
import sys

from fpv3d.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    for s in (sys.stdout, sys.stderr):                   # progress lines reach the launcher / map page right away
        try:
            s.reconfigure(write_through=True)
        except Exception:
            pass
    sys.exit(main())
