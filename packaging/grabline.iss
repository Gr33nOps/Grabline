; Inno Setup script for Grabline (Windows).
;
; Builds a per-user installer (no admin / UAC) that installs the one-file
; binary, registers the Native Messaging host and stages the browser
; extension (Grabline.exe --register-host), and adds shortcuts.
;
; Build:  iscc packaging\grabline.iss  (after PyInstaller has made dist\Grabline.exe)
; Override the version:  iscc /DAppVersion=1.2.3 packaging\grabline.iss

#ifndef AppVersion
  #define AppVersion "1.0.1"
#endif
#define AppName "Grabline"
#define AppExe "Grabline.exe"
#define AppPublisher "Grabline"
#define AppUrl "https://github.com/Gr33nOps/Grabline"

[Setup]
AppId={{8B0A6C2E-2C7A-4E4E-9C2E-6D1B7F3A9C24}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppSupportURL={#AppUrl}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Grabline-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start Grabline when I log in (in the tray)"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "--minimized"; Tasks: startup

[Run]
; Register the native host and stage the extension, silently, as the user.
Filename: "{app}\{#AppExe}"; Parameters: "--register-host"; Flags: runhidden waituntilterminated
; Offer to launch (which shows the Browser Setup wizard on first run).
Filename: "{app}\{#AppExe}"; Description: "Launch Grabline"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\Grabline\browser-extension"
