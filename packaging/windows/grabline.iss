; Inno Setup script for Grabline (Windows installer).
; Compiled in CI by ISCC.exe against the PyInstaller onedir bundle in
; dist\grabline\. Produces Grabline-Setup-<version>.exe.
;
; The installer:
;   - installs the bundle to Program Files
;   - adds a Start Menu entry (so Grabline is searchable) and optional desktop icon
;   - launches Grabline once, which registers the Native Messaging host with
;     the correct installed path (browsers then pair with the extension)
;
; #define AppVersion is passed on the ISCC command line (/DAppVersion=1.3.5).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Grabline"
#define AppExe "grabline.exe"

[Setup]
AppId={{A1F0C0DE-4B3A-4E5D-9C2B-0F1A2B3C4D5E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Grabline
AppPublisherURL=https://github.com/Gr33nOps/Grabline
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputBaseFilename=Grabline-Setup-{#AppVersion}
; Paths are relative to this .iss file (packaging\windows\), so reach up to the
; repo root where PyInstaller wrote dist\grabline\ and where CI expects the exe.
OutputDir=..\..\dist
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\..\dist\grabline\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch Grabline"; Flags: nowait postinstall skipifsilent
