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
; An update closes a running Live Transcription itself. The window ends on Windows' request
; (live_gui.end_session, which also saves a recording); its launcher has no window and cannot
; be asked, so "force" ends whatever is still running. *.pyd: the packages' modules are locked
; by the running Python as well.
CloseApplications=force
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
VersionInfoVersion={#MyAppVersion}.0
VersionInfoDescription=Live Transcription installer
; Product name and version are the same in every build of a version: SignPath's signing policy
; checks them (docs/SIGNING.md).
VersionInfoProductName=Live Transcription
VersionInfoProductVersion={#MyAppVersion}.0
VersionInfoCompany=sbaranau
VersionInfoCopyright=Copyright (c) 2026 sbaranau, MIT License

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
; AppUserModelID is the app ID of the window (live_gui.APP_ID): its taskbar button belongs to these
; shortcuts, and Windows shows its notifications ("the results are ready").
Name: "{group}\Live Transcription"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launch-live.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icons\live.ico"; AppUserModelID: "transcribe.live"
Name: "{group}\Transcribe a recording"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\transcribe-recording.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icons\transcribe.ico"; AppUserModelID: "transcribe.live"
Name: "{group}\Uninstall Live Transcription"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Live Transcription"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launch-live.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icons\live.ico"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Windows\SendTo\Transcribe with Live Transcription"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\transcribe-recording.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icons\transcribe.ico"; Tasks: sendto

[InstallDelete]
; The console launcher of v1.22 and earlier, replaced by transcribe-recording.vbs.
Type: files; Name: "{app}\transcribe-recording.cmd"

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\launch-live.vbs"""; Description: "Launch Live Transcription"; Flags: nowait postinstall skipifsilent
