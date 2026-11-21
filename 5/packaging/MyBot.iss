#define MyAppName "MyBot"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "MyBot"
#define MyAppExeName "MyBot.exe"

[Setup]
AppId={{D990E4AF-BB95-4C7B-9E13-10C0C86CC1FA}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\MyBot
DefaultGroupName=MyBot
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release\MyBot-Windows-v1.0.0
OutputBaseFilename=MyBot-Setup-1.0.0
SetupIconFile=MyBot.ico
UninstallDisplayIcon={app}\MyBot.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
VersionInfoVersion=1.0.0.0
VersionInfoDescription=MyBot Desktop Installer
VersionInfoProductName=MyBot
VersionInfoProductVersion=1.0.0
CloseApplications=yes
RestartApplications=no
ChangesAssociations=no

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: checkedonce

[Files]
Source: "..\release\MyBot-Windows-v1.0.0\MyBot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\MyBot"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\MyBot"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 MyBot"; Flags: nowait postinstall skipifsilent