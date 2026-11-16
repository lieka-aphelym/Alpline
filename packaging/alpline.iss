; Inno Setup script: makes AlplineSetup.exe from dist\Alpline (build_app.bat runs it when Inno Setup 6 is installed:
; https://jrsoftware.org/isinfo.php). Installs for the current user only: no administrator rights needed.
; The version comes from fpv3d/__init__.py: build_app.bat passes it as /DAppVersion=...
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{6C1E7B2A-4F3D-4E59-9A7C-3B8D2E1F0A47}
AppName=Alpline
AppVersion={#AppVersion}
AppPublisher=lieka
AppPublisherURL=https://github.com/lieka-aphelym/Alpline
LicenseFile=..\LICENSE
DefaultDirName={localappdata}\Programs\Alpline
DefaultGroupName=Alpline
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AlplineSetup
VersionInfoVersion={#AppVersion}
SetupIconFile=..\viewer\brand\icon.ico
UninstallDisplayIcon={app}\Alpline.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Files]
Source: "..\dist\Alpline\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Alpline"; Filename: "{app}\Alpline.exe"
Name: "{userdesktop}\Alpline"; Filename: "{app}\Alpline.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\Alpline.exe"; Description: "Start Alpline"; Flags: nowait postinstall skipifsilent
