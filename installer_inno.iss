#define MyAppName "精灵鉴定器"
#define MyAppEnglishName "PetAnalyzer"
#define MyAppVersion "1.1"
#define MyAppPublisher "PocketBole"
#define MyAppExeName "PetAnalyzer.exe"
#ifndef BuildRoot
#define BuildRoot "dist\PetAnalyzer"
#endif

[Setup]
AppId={{4F88F777-5F34-4DD6-84D5-5B8965F91862}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppEnglishName}
DefaultGroupName={#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=PetAnalyzerSetup
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "{#BuildRoot}\PetAnalyzer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildRoot}\_internal\*"; DestDir: "{app}\_internal"; Excludes: "data\*;assets\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#BuildRoot}\data\*"; DestDir: "{app}\data"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#BuildRoot}\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\app.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\app.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
