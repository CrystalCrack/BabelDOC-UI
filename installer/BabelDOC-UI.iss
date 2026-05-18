#define MyAppName "BabelDOC UI"
#define MyAppPublisher "CrystalCrack"

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

[UninstallDelete]
Type: files; Name: "{app}\launch_babeldoc_ui.vbs"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "wscript.exe"; Parameters: """{app}\launch_babeldoc_ui.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\babeldoc\assets\ui\babeldoc-ui-icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "wscript.exe"; Parameters: """{app}\launch_babeldoc_ui.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\babeldoc\assets\ui\babeldoc-ui-icon.ico"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\setup_windows.ps1"" -NoShortcuts"; WorkingDir: "{app}"; StatusMsg: "Preparing BabelDOC UI runtime. This may take several minutes on first install..."; Flags: runhidden waituntilterminated

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  LauncherPath: string;
  LauncherText: string;
begin
  if CurStep = ssPostInstall then
  begin
    LauncherPath := ExpandConstant('{app}\launch_babeldoc_ui.vbs');
    LauncherText :=
      'Set shell = CreateObject("WScript.Shell")' + #13#10 +
      'appDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)' + #13#10 +
      'shell.CurrentDirectory = appDir' + #13#10 +
      'pythonw = appDir & "\.venv\Scripts\pythonw.exe"' + #13#10 +
      'cmd = """" & pythonw & """ -m babeldoc.ui_app"' + #13#10 +
      'shell.Run cmd, 0, False' + #13#10;
    SaveStringToFile(LauncherPath, LauncherText, False);
  end;
end;
