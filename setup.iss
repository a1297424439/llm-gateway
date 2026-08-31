#define MyAppName "LLM Gateway"
#define MyAppVersion "1.0.6"
#define MyAppPublisher "DaFeiPower"
#define MyAppExeName "llm-gateway.exe"

[Setup]
SetupIconFile=icon.ico
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=LLM-Gateway-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Auto start on boot"; GroupDescription: "Other options:"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Code]
// 安装前自动关闭正在运行的旧版网关，避免文件占用导致安装卡住。
// 不用 taskkill /F：先温和请求退出，等 4 秒后再强制结束残留进程。
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  resultCode: Integer;
  i: Integer;
begin
  Result := '';
  // 温和关闭（WM_CLOSE，托盘程序可能弹确认框则由系统自行处理）
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM llm-gateway.exe', '',
       SW_HIDE, ewWaitUntilTerminated, resultCode);
  // 轮询最多 4 秒等进程退出
  for i := 1 to 8 do
  begin
    if Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq llm-gateway.exe" | find /I "llm-gateway.exe"',
            '', SW_HIDE, ewWaitUntilTerminated, resultCode) then
    begin
      if resultCode <> 0 then
        Exit; // find 未匹配到 = 进程已全部退出
    end;
    Sleep(500);
  end;
  // 仍有残留 → 强制结束
  Exec(ExpandConstant('{cmd}'), '/C taskkill /F /IM llm-gateway.exe', '',
       SW_HIDE, ewWaitUntilTerminated, resultCode);
  Sleep(500);
end;

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: autostart; Flags: uninsdeletevalue
