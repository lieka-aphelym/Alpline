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
gui = Analysis([os.path.join(ROOT, "launcher.pyw")], pathex=[ROOT], datas=datas,
               hiddenimports=fpv3d_mods + raster_mods + ["yaml", "serial", "serial.tools.list_ports", "PIL.ImageTk"], excludes=["matplotlib", "pytest", "webview", "clr", "pythonnet"])
cli = Analysis([os.path.join(SPECPATH, "cli_entry.py")], pathex=[ROOT], datas=raster_data,
               hiddenimports=fpv3d_mods + raster_mods + ["serial", "serial.tools.list_ports", "cryptography"]
               + collect_submodules("orangebox"),          # blackbox download
               excludes=["matplotlib", "pytest", "tkinter", "webview", "clr", "pythonnet"])

# the picture shown the moment Alpline.exe starts, before Python runs (a cold start takes a few seconds); the
# launcher writes its current step at text_pos and closes it once its window is drawn (launcher/startup.py).
# The picture is made by tools/make_brand.py; text_pos is SPLASH_TEXT there.
splash = Splash(os.path.join(ROOT, "viewer", "brand", "launch-splash.png"), binaries=gui.binaries, datas=gui.datas,
                text_pos=(24, 274), text_size=10, text_font="Consolas", text_color="#a9b4c2", minify_script=True,
                always_on_top=False)
gui_exe = EXE(PYZ(gui.pure), gui.scripts, splash, [], exclude_binaries=True, name="Alpline", console=False, icon=ICON)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [("u", None, "OPTION")], exclude_binaries=True, name="alpline-cli",
              console=True, icon=ICON)
COLLECT(gui_exe, gui.binaries, gui.datas, splash.binaries, cli_exe, cli.binaries, cli.datas, name="Alpline")
