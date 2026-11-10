; Inno Setup script for the Lute3 Windows installer.
; Built by windows\build.ps1, which passes /DAppVersion=x.y.z.
; Requires Inno Setup 6 (https://jrsoftware.org/isinfo.php).
;
; Installs per-user (no admin rights needed) into
; %LOCALAPPDATA%\Programs\Lute3.  User data lives in
; %LOCALAPPDATA%\Lute3\Lute3 and is NOT removed on uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B0E2C1A-5D7B-4C0B-9C47-3F1E8E2A7D11}
AppName=Lute3
AppVersion={#AppVersion}
AppVerName=Lute3 {#AppVersion}
AppPublisher=LuteOrg
AppPublisherURL=https://luteorg.github.io/lute-manual/
DefaultDirName={localappdata}\Programs\Lute3
DefaultGroupName=Lute3
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Lute3-{#AppVersion}-setup
SetupIconFile=..\lute\static\favicon.ico
UninstallDisplayIcon={app}\Lute3.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Ask a running Lute to close before upgrading/uninstalling.
AppMutex=Local\Lute3DesktopSingleInstance

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Lute3\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Clear old bundled files on upgrade (never touches user data).
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Lute3"; Filename: "{app}\Lute3.exe"
Name: "{group}\Uninstall Lute3"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Lute3"; Filename: "{app}\Lute3.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Lute3.exe"; Description: "{cm:LaunchProgram,Lute3}"; Flags: nowait postinstall skipifsilent
