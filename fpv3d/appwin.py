"""An Alpline window: the viewer or the locations map in its own window instead of the browser (pywebview, which
uses the Edge WebView2 engine that comes with Windows 10 / 11).

    python -m fpv3d.appwin http://127.0.0.1:8000/viewer/      (the packaged app: Alpline.exe --window <url>)

Settings made in the pages (theme, warnings, antenna edits...) are kept in DATA/cache/webview, like a browser
profile. Links to other sites (map.geo.admin.ch, ...) open in the normal browser.
"""
from __future__ import annotations

import sys
import time
import traceback
import webbrowser

from .paths import APP, DATA


def available() -> bool:
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def _log(msg: str) -> None:
    try:
        (DATA / "logs").mkdir(parents=True, exist_ok=True)
        with open(DATA / "logs" / "window.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg.rstrip() + "\n")
    except OSError:
        pass


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    url = argv[0] if argv else "http://127.0.0.1:8000/viewer/"
    # the packaged Alpline.exe has no console: anything printed would crash it, so it goes to logs/window.log
    if sys.stdout is None or sys.stderr is None:
        try:
            (DATA / "logs").mkdir(parents=True, exist_ok=True)
            out = open(DATA / "logs" / "window.log", "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stdout or out
            sys.stderr = sys.stderr or out
        except OSError:
            pass
    # a hard crash inside the web engine leaves no Python error: the crash tracer and pywebview's own log say where
    try:
        import faulthandler
        import logging
        _crash = open(DATA / "logs" / "window.log", "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_crash, all_threads=True)
        h = logging.StreamHandler(_crash)
        h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        lg = logging.getLogger("pywebview")
        lg.addHandler(h); lg.setLevel(logging.DEBUG)
    except Exception:
        pass
    _log(f"python {sys.version.split()[0]} at {sys.executable}")
    try:
        return _run(url)
    except BaseException:                               # never fail silently: log it, and show the page anyway
        _log(f"Alpline window failed for {url}:\n{traceback.format_exc()}")
        webbrowser.open(url)
        return 1


def _run(url: str) -> int:
    import webview
    if sys.platform == "win32":                         # own taskbar entry and icon, not Python's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("lieka.alpline")
        except Exception:
            pass
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["ALLOW_DOWNLOADS"] = True          # the phone certificate, saved logs
    title = "Alpline · locations map" if "map.html" in url else "Alpline"
    webview.create_window(title, url, width=1440, height=900, min_size=(820, 560), background_color="#07090C",
                          text_select=True)
    store = DATA / "cache" / "webview"
    store.mkdir(parents=True, exist_ok=True)
    icon = APP / "viewer" / "brand" / "icon-256.png"
    gui = "edgechromium" if sys.platform == "win32" else None     # the Edge engine; an error rather than an old fallback
    _log(f"open {url} (pywebview {getattr(webview, '__version__', '?')}, gui {gui or 'auto'})")
    webview.start(gui=gui, private_mode=False, storage_path=str(store), icon=str(icon) if icon.exists() else None)
    _log("window closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
