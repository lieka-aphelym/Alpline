@echo off
rem Builds the Windows app: dist\Alpline\Alpline.exe, and dist\AlplineSetup.exe when Inno Setup 6 is installed.
rem Run it from this folder (double-click, or in PyCharm's terminal). Takes a few minutes.
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python
"%PY%" -m pip install -r requirements.txt -r packaging\requirements-build.txt || goto :fail
"%PY%" -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\alpline.spec || goto :fail
set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ISCC%" ( "%ISCC%" packaging\alpline.iss || goto :fail ) else ( echo Inno Setup 6 not found: no installer, the app is in dist\Alpline )
echo.
echo Done. App: dist\Alpline\Alpline.exe
if exist dist\AlplineSetup.exe echo Installer: dist\AlplineSetup.exe
pause
exit /b 0
:fail
echo.
echo Build failed: see the messages above.
pause
exit /b 1
