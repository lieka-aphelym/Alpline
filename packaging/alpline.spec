# PyInstaller recipe for the Windows app:  build_app.bat  (or: python -m PyInstaller packaging/alpline.spec)
#
# dist/Alpline/
#   Alpline.exe       the launcher + Alpline windows (no console)       = launcher.pyw
#   alpline-cli.exe   the server and the fpv3d commands (no window)     = packaging/cli_entry.py
#   _internal/        Python, the libraries, viewer/ (the pages)
# Your files are not in here: they go to Documents\Alpline (or the folder chosen at the first start).
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "viewer", "brand", "icon.ico")
fpv3d_mods = collect_submodules("fpv3d")
# rasterio (the map library) loads some of its parts and its GDAL / PROJ data files at run time
raster_mods = collect_submodules("rasterio")
raster_data = collect_data_files("rasterio")
datas = [(os.path.join(ROOT, "viewer"), "viewer")] + raster_data
# pywebview picks its Windows engine (WebView2 through pythonnet) at run time
try:
    web_mods = collect_submodules("webview") + ["clr"]
    datas += collect_data_files("webview")
except Exception:
    web_mods = []

gui = Analysis([os.path.join(ROOT, "launcher.pyw")], pathex=[ROOT], datas=datas,
               hiddenimports=fpv3d_mods + raster_mods + web_mods + ["webview", "yaml"], excludes=["matplotlib", "pytest"])
cli = Analysis([os.path.join(SPECPATH, "cli_entry.py")], pathex=[ROOT], datas=raster_data,
               hiddenimports=fpv3d_mods + raster_mods + ["serial", "serial.tools.list_ports", "cryptography"],
               excludes=["matplotlib", "pytest", "tkinter", "webview"])

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="Alpline", console=False, icon=ICON)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [("u", None, "OPTION")], exclude_binaries=True, name="alpline-cli",
              console=True, icon=ICON)
COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas, name="Alpline")
