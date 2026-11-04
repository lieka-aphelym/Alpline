"""An Alpline window: the viewer or the locations map in its own window instead of the browser (pywebview, which
uses the Edge WebView2 engine that comes with Windows 10 / 11).

    python -m fpv3d.appwin http://127.0.0.1:8000/viewer/      (the packaged app: Alpline.exe --window <url>)

Settings made in the pages (theme, warnings, antenna edits...) are kept in DATA/cache/webview, like a browser
profile. Links to other sites (map.geo.admin.ch, ...) open in the normal browser.
"""
from __future__ import annotations

import sys
import webbrowser

from .paths import APP, DATA


def available() -> bool:
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    url = argv[0] if argv else "http://127.0.0.1:8000/viewer/"
    try:
        import webview
    except Exception:                                   # pywebview missing: the browser does the job
        webbrowser.open(url)
        return 0
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
    try:
        webview.start(private_mode=False, storage_path=str(store), icon=str(icon) if icon.exists() else None)
    except Exception:                                   # no WebView2 / GUI backend: fall back to the browser
        webbrowser.open(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
