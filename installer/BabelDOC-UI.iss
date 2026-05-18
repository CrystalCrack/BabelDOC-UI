#define MyAppName "BabelDOC UI"
#define MyAppPublisher "CrystalCrack"
#define MyAppExeName "run_babeldoc_ui.bat"

#ifndef SourceDir
  #define SourceDir ".."
#endif

#ifndef OutputDir
  #define OutputDir "..\releases"
#endif

#ifndef BuildVersion
  #define BuildVersion "dev"
#endif

[Setup]
AppId={{B35D0954-6B5C-4F17-8C86-5CB6FC15549A}
AppName={#MyAppName}
AppVersion={#BuildVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\BabelDOC-UI
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=BabelDOC-UI-Inno-Setup-{#BuildVersion}
SetupIconFile={#SourceDir}\babeldoc\assets\ui\babeldoc-ui-icon.ico
UninstallDisplayIcon={app}\babeldoc\assets\ui\babeldoc-ui-icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m babeldoc.ui_app"; WorkingDir: "{app}"; IconFilename: "{app}\babeldoc\assets\ui\babeldoc-ui-icon.ico"; Check: PythonwExists
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\babeldoc\assets\ui\babeldoc-ui-icon.ico"; Check: not PythonwExists
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m babeldoc.ui_app"; WorkingDir: "{app}"; IconFilename: "{app}\babeldoc\assets\ui\babeldoc-ui-icon.ico"; Tasks: desktopicon; Check: PythonwExists
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\babeldoc\assets\ui\babeldoc-ui-icon.ico"; Tasks: desktopicon; Check: not PythonwExists

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\setup_windows.ps1"" -NoShortcuts"; WorkingDir: "{app}"; StatusMsg: "Preparing BabelDOC UI runtime. This may take several minutes on first install..."; Flags: runhidden waituntilterminated

[Code]
function PythonwExists: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\.venv\Scripts\pythonw.exe'));
end;
