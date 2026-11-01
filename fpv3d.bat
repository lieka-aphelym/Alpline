@echo off
rem fpv3d: opens the launcher (Full / Lite, 3D viewer or locations map)
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" launcher.pyw
) else (
  start "" pythonw launcher.pyw
)
