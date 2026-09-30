#ifndef TargetVersion
  #error TargetVersion is required
#endif
#ifndef SourceReleaseId
  #error SourceReleaseId is required
#endif
#ifndef TargetReleaseId
  #error TargetReleaseId is required
#endif
#ifndef AssetDir
  #error AssetDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef MaximumMaterializedSuffixLength
  #error MaximumMaterializedSuffixLength is required
#endif

#define ProductName "Infinite Canvas Enterprise"
#define ProductNameZh "无限画布企业版"

[Setup]
AppId={{4778AD55-8CF3-45E8-B948-D9FBE86CC286}
AppName={#ProductName}
AppVerName={#ProductNameZh} 09.6 一键升级工具
AppVersion={#TargetVersion}
AppPublisher=MEIS-DaCaiTou
DefaultDirName={tmp}InfiniteCanvasEnterprise096Bridge
CreateAppDir=no
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableReadyMemo=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
SetupArchitecture=x64
Uninstallable=no
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
AllowCancelDuringInstall=no
SetupLogging=yes
TimeStampsInUTC=yes
VersionInfoVersion={#TargetVersion}.0
VersionInfoDescription={#ProductNameZh} 09.6 一键安全升级工具
VersionInfoProductName={#ProductName}
VersionInfoProductVersion={#TargetVersion}
VersionInfoCompany=MEIS-DaCaiTou

[Languages]
Name: "zhcn"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "{#AssetDir}\{#ArchiveFilename}"; Flags: dontcopy noencryption notimestamp
Source: "{#AssetDir}\{#ManifestFilename}"; Flags: dontcopy noencryption notimestamp
Source: "{#AssetDir}\{#InventoryFilename}"; Flags: dontcopy noencryption notimestamp
Source: "{#BridgeBootstrapPath}"; Flags: dontcopy noencryption notimestamp
Source: "{#MetadataPath}"; Flags: dontcopy noencryption notimestamp

[Code]
const
  DRIVE_FIXED = 3;
  INVALID_FILE_ATTRIBUTES = $FFFFFFFF;

var
  InstallRootPage: TInputDirWizardPage;
  ConfirmationPage: TInputOptionWizardPage;
  UpgradeProgress: TOutputProgressWizardPage;
  SelectedInstallRoot: String;
  DiagnosticsPath: String;
  LastStableCode: String;

function GetDriveTypeW(lpRootPathName: String): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';
function GetFileAttributesW(lpFileName: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function GetLastErrorNative: Cardinal;
  external 'GetLastError@kernel32.dll stdcall';

function Quote(const Value: String): String;
begin
  Result := '"' + Value + '"';
end;

function HasUnsafeAncestor(const Path: String): Boolean;
var
  Attributes, ErrorCode: Cardinal;
  Current, Parent: String;
begin
  Result := True;
  Current := RemoveBackslashUnlessRoot(ExpandFileName(Path));
  while Current <> '' do begin
    Attributes := GetFileAttributesW(Current);
    if Attributes = INVALID_FILE_ATTRIBUTES then begin
      ErrorCode := GetLastErrorNative;
      if (ErrorCode <> 2) and (ErrorCode <> 3) then exit;
    end else if (Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0 then exit;
    Parent := RemoveBackslashUnlessRoot(ExtractFileDir(Current));
    if (Parent = '') or (Parent = Current) then break;
    Current := Parent;
  end;
  Result := False;
end;

function IsCandidateRoot(const Root: String): Boolean;
var
  SourceRoot: String;
begin
  SourceRoot := AddBackslash(Root) + 'releases\{#SourceReleaseId}';
  Result := DirExists(Root) and
    FileExists(SourceRoot + '\python\python.exe') and
    FileExists(SourceRoot + '\release-manifest.json') and
    FileExists(AddBackslash(Root) + 'data\enterprise.db');
end;

function DetectInstallRoot: String;
var
  Candidate, Parent: String;
begin
  Candidate := ExpandConstant('{param:INSTALLROOT|}');
  if (Candidate <> '') and IsCandidateRoot(Candidate) then begin
    Result := Candidate;
    exit;
  end;
  Candidate := ExtractFileDir(ExpandConstant('{srcexe}'));
  if IsCandidateRoot(Candidate) then begin
    Result := Candidate;
    exit;
  end;
  Parent := ExtractFileDir(Candidate);
  if IsCandidateRoot(Parent) then begin
    Result := Parent;
    exit;
  end;
  Candidate := ExpandConstant('{localappdata}\Infinite-Canvas-Enterprise\install');
  Result := Candidate;
end;

function ValidateInstallRoot(const Root: String; var Code: String): Boolean;
var
  DriveRoot: String;
begin
  Result := False;
  Code := 'SECURITY_BRIDGE_INSTALL_ROOT_INVALID';
  if (Length(Root) < 3) or (Copy(Root, 2, 2) <> ':\') or
     (Pos('"', Root) <> 0) or (Pos(#13, Root) <> 0) or (Pos(#10, Root) <> 0) then exit;
  DriveRoot := ExtractFileDrive(Root) + '\';
  if GetDriveTypeW(DriveRoot) <> DRIVE_FIXED then begin
    Code := 'SECURITY_BRIDGE_INSTALL_ROOT_NOT_LOCAL';
    exit;
  end;
  if HasUnsafeAncestor(Root) or
     HasUnsafeAncestor(AddBackslash(Root) + 'releases\{#SourceReleaseId}\python\python.exe') or
     HasUnsafeAncestor(AddBackslash(Root) + 'releases\{#SourceReleaseId}\release-manifest.json') or
     HasUnsafeAncestor(AddBackslash(Root) + 'data\enterprise.db') or
     HasUnsafeAncestor(AddBackslash(Root) + '{#DiagnosticsRelative}') then begin
    Code := 'SECURITY_BRIDGE_INSTALL_ROOT_UNSAFE';
    exit;
  end;
  { The embedded 09.6 Python cannot reliably expand paths at the legacy }
  { Windows MAX_PATH boundary.  Keep headroom for the longest target file. }
  if Length(AddBackslash(Root)) + StrToInt('{#MaximumMaterializedSuffixLength}') > 240 then begin
    Code := 'SECURITY_BRIDGE_INSTALL_ROOT_TOO_LONG';
    exit;
  end;
  if not IsCandidateRoot(Root) then exit;
  Result := True;
end;

procedure RequireEmbeddedFile(const Path, ExpectedHash: String; ExpectedSize: Int64);
var
  ActualSize: Int64;
begin
  if not FileSize64(Path, ActualSize) then
    RaiseException('SECURITY_BRIDGE_EMBEDDED_ASSET_MISSING');
  if ActualSize <> ExpectedSize then
    RaiseException('SECURITY_BRIDGE_EMBEDDED_ASSET_SIZE_MISMATCH');
  if CompareText(GetSHA256OfFile(Path), ExpectedHash) <> 0 then
    RaiseException('SECURITY_BRIDGE_EMBEDDED_ASSET_HASH_MISMATCH');
end;

function ExtractJsonString(const Text, Name: String): String;
var
  Marker: String;
  StartAt, EndAt: Integer;
begin
  Result := '';
  Marker := '"' + Name + '":"';
  StartAt := Pos(Marker, Text);
  if StartAt = 0 then exit;
  StartAt := StartAt + Length(Marker);
  EndAt := StartAt;
  while (EndAt <= Length(Text)) and (Text[EndAt] <> '"') do
    EndAt := EndAt + 1;
  if (EndAt > StartAt) and (EndAt <= Length(Text)) then
    Result := Copy(Text, StartAt, EndAt - StartAt);
end;

procedure SetStage(const Caption: String; Position: Integer);
begin
  UpgradeProgress.SetText(Caption, '升级期间服务会暂停，请勿关闭本窗口。');
  UpgradeProgress.SetProgress(Position, 5);
end;

procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel1.Caption := '欢迎使用无限画布企业版一键升级工具';
  WizardForm.WelcomeLabel2.Caption :=
    '本工具仅用于将已知受影响的 2026.09.6 安全升级到 2026.09.9。' + #13#10 +
    '系统会自动校验、备份、迁移、重启和健康检查；失败时自动回退。';
  InstallRootPage := CreateInputDirPage(wpWelcome, '选择现有安装目录',
    '请选择包含 data 和 releases 目录的无限画布企业版安装根目录。',
    '工具会严格校验版本和数据库指纹，不会修改其他项目或目录。', False, '');
  InstallRootPage.Add('安装目录：');
  InstallRootPage.Values[0] := DetectInstallRoot;
  ConfirmationPage := CreateInputOptionPage(InstallRootPage.ID, '升级前确认',
    '请先确认业务任务已处理完成',
    '升级会暂停服务。未完成的图片、视频或其他 AI 任务不应在此时提交。', False, False);
  ConfirmationPage.Add('我已确认当前没有未完成的 AI 任务');
  UpgradeProgress := CreateOutputProgressPage('正在安全升级',
    '系统会自动恢复失败的升级。');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Code: String;
begin
  Result := True;
  { Silent tests are validated in PrepareToInstall, including their explicit }
  { task confirmation. Do not display a checkbox dialog in that mode. }
  if WizardSilent then exit;
  if CurPageID = InstallRootPage.ID then begin
    SelectedInstallRoot := InstallRootPage.Values[0];
    if not ValidateInstallRoot(SelectedInstallRoot, Code) then begin
      SuppressibleMsgBox('安装目录校验未通过。' + #13#10 + '错误代码：' + Code, mbError, MB_OK, IDOK);
      Result := False;
    end;
  end;
  if (CurPageID = ConfirmationPage.ID) and not ConfirmationPage.Values[0] then begin
    SuppressibleMsgBox('请确认当前没有未完成的 AI 任务。', mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ArchivePath, ManifestPath, InventoryPath, BridgePath, MetadataPath: String;
  SourceRoot, PythonExe, ResultPath, ResultText, ResultCode, Parameters, TerminalState, SourceRecovery: String;
  DiagnosticsRoot, ExceptionCode, InstallRootCode: String;
  ResultBytes: AnsiString;
  ProcessResult: Integer;
begin
  Result := '';
  LastStableCode := 'SECURITY_BRIDGE_GUI_FAILED';
  SelectedInstallRoot := ExpandFileName(InstallRootPage.Values[0]);
  if not ValidateInstallRoot(SelectedInstallRoot, InstallRootCode) then begin
    Result := '安装目录校验未通过。' + #13#10 + '错误代码：' + InstallRootCode;
    exit;
  end;
  if WizardSilent then begin
    if CompareText(ExpandConstant('{param:CONFIRMNOACTIVETASKS|}'), '1') <> 0 then begin
      Result := '静默验收缺少无活动任务确认。' + #13#10 +
        '错误代码：SECURITY_BRIDGE_ACTIVE_TASK_CONFIRMATION_REQUIRED';
      exit;
    end;
  end else if not ConfirmationPage.Values[0] then begin
    Result := '请确认当前没有未完成的 AI 任务。' + #13#10 +
      '错误代码：SECURITY_BRIDGE_ACTIVE_TASK_CONFIRMATION_REQUIRED';
    exit;
  end;
  UpgradeProgress.Show;
  try
    SetStage('验证升级工具和发布资产', 1);
    ExtractTemporaryFile('{#ArchiveFilename}');
    ExtractTemporaryFile('{#ManifestFilename}');
    ExtractTemporaryFile('{#InventoryFilename}');
    ExtractTemporaryFile('{#BridgeBootstrapFilename}');
    ExtractTemporaryFile('bridge-updater-metadata.json');
    ArchivePath := AddBackslash(ExpandConstant('{tmp}')) + '{#ArchiveFilename}';
    ManifestPath := AddBackslash(ExpandConstant('{tmp}')) + '{#ManifestFilename}';
    InventoryPath := AddBackslash(ExpandConstant('{tmp}')) + '{#InventoryFilename}';
    BridgePath := AddBackslash(ExpandConstant('{tmp}')) + '{#BridgeBootstrapFilename}';
    MetadataPath := AddBackslash(ExpandConstant('{tmp}')) + 'bridge-updater-metadata.json';
    RequireEmbeddedFile(ArchivePath, '{#ArchiveSha256}', StrToInt64('{#ArchiveSize}'));
    RequireEmbeddedFile(ManifestPath, '{#ManifestSha256}', StrToInt64('{#ManifestSize}'));
    RequireEmbeddedFile(InventoryPath, '{#InventorySha256}', StrToInt64('{#InventorySize}'));
    RequireEmbeddedFile(BridgePath, '{#BridgeBootstrapSha256}', StrToInt64('{#BridgeBootstrapSize}'));
    RequireEmbeddedFile(MetadataPath, '{#MetadataSha256}', StrToInt64('{#MetadataSize}'));

    SetStage('检查现有 09.6 安装与数据', 2);
    SourceRoot := AddBackslash(SelectedInstallRoot) + 'releases\{#SourceReleaseId}';
    PythonExe := SourceRoot + '\python\python.exe';
    if CompareText(GetSHA256OfFile(SourceRoot + '\release-manifest.json'), '{#SourceManifestSha256}') <> 0 then
      RaiseException('SECURITY_BRIDGE_SOURCE_IDENTITY_MISMATCH');
    if CompareText(GetSHA256OfFile(PythonExe), '{#SourcePythonSha256}') <> 0 then
      RaiseException('SECURITY_BRIDGE_PYTHON_IDENTITY_MISMATCH');
    ResultPath := AddBackslash(ExpandConstant('{tmp}')) + 'bridge-result.json';
    DiagnosticsRoot := AddBackslash(SelectedInstallRoot) + '{#DiagnosticsRelative}';
    if HasUnsafeAncestor(DiagnosticsRoot) then
      RaiseException('SECURITY_BRIDGE_DIAGNOSTICS_PATH_UNSAFE');
    if not ForceDirectories(DiagnosticsRoot) then
      RaiseException('SECURITY_BRIDGE_DIAGNOSTICS_DIRECTORY_FAILED');
    if HasUnsafeAncestor(DiagnosticsRoot) then
      RaiseException('SECURITY_BRIDGE_DIAGNOSTICS_PATH_UNSAFE');
    DiagnosticsPath := AddBackslash(DiagnosticsRoot) +
      'update-diagnostics-096-to-099-' + GetDateTimeString('yyyymmdd-hhnnss', '-', ':') + '.zip';

    SetStage('备份数据并执行受控迁移', 3);
    Parameters := '-I -B ' + Quote(BridgePath) +
      ' --install-root ' + Quote(SelectedInstallRoot) +
      ' --manifest ' + Quote(ManifestPath) +
      ' --archive ' + Quote(ArchivePath) +
      ' --inventory ' + Quote(InventoryPath) +
      ' --result-file ' + Quote(ResultPath) +
      ' --diagnostics-file ' + Quote(DiagnosticsPath) +
      ' --confirm-no-active-tasks';
    LastStableCode := 'SECURITY_BRIDGE_GUI_LAUNCH_FAILED';
    if not Exec(PythonExe, Parameters, SourceRoot, SW_HIDE, ewWaitUntilTerminated, ProcessResult) then
      RaiseException(LastStableCode);
    if not LoadStringFromFile(ResultPath, ResultBytes) then
      RaiseException('SECURITY_BRIDGE_GUI_RESULT_MISSING');
    ResultText := Utf8Decode(ResultBytes);
    ResultCode := ExtractJsonString(ResultText, 'code');
    if ResultCode = '' then ResultCode := ExtractJsonString(ResultText, 'result_code');
    TerminalState := ExtractJsonString(ResultText, 'terminal_state');
    SourceRecovery := ExtractJsonString(ResultText, 'source_recovery');
    if (ProcessResult <> 0) or (Pos('"result":"succeeded"', ResultText) = 0) then begin
      if ResultCode = '' then ResultCode := 'SECURITY_BRIDGE_GUI_UPDATE_FAILED';
      LastStableCode := ResultCode;
      if (TerminalState = 'RECOVERY_REQUIRED') or (SourceRecovery = 'failed') or
         (SourceRecovery = 'blocked_identity_changed') then
        Result := '升级未完成，恢复结果尚未确认。请暂停使用，并将诊断文件交给维护人员。'
      else if TerminalState = 'ROLLED_BACK' then
        Result := '升级未完成，已安全回退至原版本。'
      else
        Result := '升级未完成，请根据诊断记录检查当前状态。';
      Result := Result + #13#10 +
        '错误代码：' + LastStableCode + #13#10 +
        '诊断文件：' + DiagnosticsPath;
      exit;
    end;

    SetStage('启动 2026.09.9 并检查健康状态', 4);
    SetStage('升级完成', 5);
    if FileExists(DiagnosticsPath) then
      SuppressibleMsgBox('已成功升级到 2026.09.9。' + #13#10 +
        '诊断文件：' + DiagnosticsPath, mbInformation, MB_OK, IDOK)
    else
      SuppressibleMsgBox('已成功升级到 2026.09.9，诊断文件导出未完成。' + #13#10 +
        '请在管理后台导出日志；无需重复升级。', mbInformation, MB_OK, IDOK);
  except
    ExceptionCode := GetExceptionMessage;
    if Pos('SECURITY_BRIDGE_', ExceptionCode) = 1 then LastStableCode := ExceptionCode;
    Result := '升级未完成，未对其他项目或目录执行操作。' + #13#10 +
      '错误代码：' + LastStableCode;
    if DiagnosticsPath <> '' then Result := Result + #13#10 + '诊断文件：' + DiagnosticsPath;
  finally
    UpgradeProgress.Hide;
  end;
end;
