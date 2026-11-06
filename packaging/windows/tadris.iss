; Inno Setup 6 script for Tadris. Built by packaging/build.py on Windows, after PyInstaller:
;   ISCC /DAppVersion=1.0.0 packaging\windows\tadris.iss  ->  dist\Tadris-1.0.0-setup.exe
;
; Installed for the user who runs it (no administrator needed), in
; %LOCALAPPDATA%\Programs\Tadris. The school's data is elsewhere, in %LOCALAPPDATA%\Tadris
; (the database, backups, documents, log): neither an upgrade nor an uninstall touches it.

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=1.0.0 tadris.iss
#endif

[Setup]
; The AppId says which installed app this is: never change it, or an upgrade installs a
; second Tadris beside the first.
AppId={{65B26EFD-9A0B-4AF6-BACF-BB179577FE7E}
AppName=Tadris
AppVersion={#AppVersion}
AppVerName=Tadris {#AppVersion}
AppPublisher=Tadris
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\Tadris
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
OutputDir=..\..\dist
OutputBaseFilename=Tadris-{#AppVersion}-setup
SetupIconFile=..\tadris.ico
UninstallDisplayIcon={app}\Tadris.exe
UninstallDisplayName=Tadris
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Tadris open during an upgrade: the setup offers to close it first. It is never started
; again by the setup on its own (its close takes the day's backup).
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; An upgrade replaces the whole app folder: no module of the old version stays beside the
; new ones.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\Tadris\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Tadris"; Filename: "{app}\Tadris.exe"
Name: "{autodesktop}\Tadris"; Filename: "{app}\Tadris.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Tadris.exe"; Description: "{cm:LaunchProgram,Tadris}"; Flags: nowait postinstall skipifsilent
