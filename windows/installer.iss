#ifndef MyAppVersion
  #error MyAppVersion must be supplied by build-release.ps1
#endif
#ifndef PayloadDir
  #error PayloadDir must be supplied by build-release.ps1
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build-release.ps1
#endif

[Setup]
AppId={{7E0F9C4B-6907-4CE8-966A-2870664F5B32}
AppName=Live Transcription
AppVersion={#MyAppVersion}
AppPublisher=sbaranau
AppPublisherURL=https://github.com/sbaranau/transcribe
AppSupportURL=https://github.com/sbaranau/transcribe/blob/main/ИНСТРУКЦИЯ.md
AppUpdatesURL=https://github.com/sbaranau/transcribe/releases/latest
DefaultDirName={localappdata}\Programs\Live Transcription
DefaultGroupName=Live Transcription
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=Live-Transcription-Windows-x64-v{#MyAppVersion}-Setup
SetupIconFile={#PayloadDir}\app\icons\live.ico
UninstallDisplayIcon={app}\app\icons\live.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#MyAppVersion}.0
VersionInfoDescription=Live Transcription installer

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "sendto"; Description: "Add Transcribe to the Explorer Send to menu"; GroupDescription: "Explorer:"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Live Transcription"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launch-live.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icons\live.ico"
Name: "{group}\Transcribe a recording"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\transcribe-recording.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icons\transcribe.ico"
Name: "{group}\Uninstall Live Transcription"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Live Transcription"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launch-live.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icons\live.ico"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Windows\SendTo\Transcribe with Live Transcription"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\transcribe-recording.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icons\transcribe.ico"; Tasks: sendto

[InstallDelete]
; The console launcher of v1.22 and earlier, replaced by transcribe-recording.vbs.
Type: files; Name: "{app}\transcribe-recording.cmd"

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\launch-live.vbs"""; Description: "Launch Live Transcription"; Flags: nowait postinstall skipifsilent
