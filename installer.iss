; F1 Desktop Widget — Inno Setup Installer Script
; Build steps:
;   1. pyinstaller f1_widget.spec --noconfirm
;   2. Open this file in Inno Setup Compiler → Build → Compile (F9)

#define AppName      "F1 Desktop Widget"
#define AppVersion   "1.0.0"
#define AppPublisher "F1 Widget"
#define AppExeName   "F1Widget.exe"
#define BuildDir     "dist\F1Widget"
#define IconFile     "resources\icon.ico"

[Setup]
AppId={{A4F1B2C3-D5E6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisherURL=https://github.com/Charlo-tech/f1-race-replay
DefaultDirName={autopf}\F1Widget
DefaultGroupName={#AppName}
AllowNoIcons=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer_output
OutputBaseFilename=F1Widget_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";  Description: "Create a desktop shortcut";        GroupDescription: "Shortcuts:";
Name: "startupentry"; Description: "Launch F1 Widget when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";           Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}";   Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "F1DesktopWidget"; \
    ValueData: """{app}\{#AppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: startupentry

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "Launch F1 Desktop Widget now"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "reg"; \
    Parameters: "delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v F1DesktopWidget /f"; \
    Flags: runhidden
