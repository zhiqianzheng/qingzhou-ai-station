[Setup]
AppId={{2C280749-F021-4BF4-87D1-2857B37D61BC}
AppName=Qingzhou AI Station
AppVersion=0.2.1
AppPublisher=zhiqianzheng
DefaultDirName={localappdata}\Programs\QingzhouAIStation
DefaultGroupName=Qingzhou AI Station
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=qingzhou-ai-station-0.2.1-windows-x64-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\QingzhouAIStation.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
[Files]
Source: "..\dist\QingzhouAIStation\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Qingzhou AI Station"; Filename: "{app}\QingzhouAIStation.exe"
Name: "{autodesktop}\Qingzhou AI Station"; Filename: "{app}\QingzhouAIStation.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
[Run]
Filename: "{app}\QingzhouAIStation.exe"; Description: "Launch Qingzhou AI Station"; Flags: nowait postinstall skipifsilent
