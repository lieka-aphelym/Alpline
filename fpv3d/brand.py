"""The app's name, in ONE place. To rename the app, change APP_NAME here (and BY, the maker's name next to it).

Everything a user sees takes the name from here: the launcher window, its texts, the Windows taskbar id, the desktop
shortcut, the pages (the server hands the name to them, viewer/js/core/theme.js puts it in), the phone app's name, messages.

What deliberately keeps the first name, because users never see it and changing it would lose things:
  - the folder with your files and the note that says where it is: the folders of EARLIER_NAMES are still found,
    so a renamed app opens your existing locations and flights (new installs use the new name)
  - internal names: the ALPLINE_DATA setting, alpline-cli.exe, backup files (alpline_backup_*.zip stay readable),
    the browser's saved preferences, the Python package fpv3d
The installer (packaging/alpline.iss) and the two .bat files spell the name themselves: change it there too.
"""
APP_NAME = "Alpline"
BY = "lieka"

EARLIER_NAMES = ("Alpline",)                       # names this app had: their data folders are still used
APP_ID = f"{BY}.{APP_NAME}.Launcher".replace(" ", "")   # Windows taskbar identity
