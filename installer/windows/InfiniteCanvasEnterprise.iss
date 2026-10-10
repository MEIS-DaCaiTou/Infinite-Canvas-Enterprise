#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef ReleaseId
  #error ReleaseId is required
#endif
#ifndef AssetDir
  #error AssetDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif

#define ProductName "Infinite Canvas Enterprise"
#define ProductNameZh "无限画布企业版"

[Setup]
AppId={{39A24659-F291-4C88-A57F-A8B5E990BAA2}
AppName={#ProductName}
AppVerName={#ProductNameZh} {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=MEIS-DaCaiTou
DefaultDirName={localappdata}\Infinite-Canvas-Enterprise\install
CreateAppDir=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
SetupArchitecture=x64
Uninstallable=no
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2/max
SolidCompression=yes
ArchiveExtraction=full
WizardStyle=modern
CloseApplications=no
RestartApplications=no
AllowCancelDuringInstall=no
SetupLogging=yes
TimeStampsInUTC=yes
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription={#ProductNameZh} 单文件安装器
VersionInfoProductName={#ProductName}
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany=MEIS-DaCaiTou

[Languages]
Name: "zhcn"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce
Name: "launchafter"; Description: "完成后打开固定启动窗口"; Flags: checkedonce

[Files]
Source: "{#AssetDir}\{#ArchiveFilename}"; Flags: dontcopy noencryption notimestamp
Source: "{#AssetDir}\{#ManifestFilename}"; Flags: dontcopy noencryption notimestamp
Source: "{#AssetDir}\{#InventoryFilename}"; Flags: dontcopy noencryption notimestamp
Source: "{#MetadataPath}"; Flags: dontcopy noencryption notimestamp
Source: "{#NativeEntryDir}\InfiniteCanvas.exe"; Flags: dontcopy noencryption notimestamp
Source: "{#NativeEntryDir}\native-entry-build-record.json"; Flags: dontcopy noencryption notimestamp

[Icons]
Name: "{autoprograms}\无限画布企业版"; Filename: "{code:GetInstalledEntry}"; WorkingDir: "{code:GetInstallRoot}"; Check: ShouldMaintainEntry
Name: "{autodesktop}\无限画布企业版"; Filename: "{code:GetInstalledEntry}"; WorkingDir: "{code:GetInstallRoot}"; Tasks: desktopicon; Check: ShouldMaintainEntry

[Run]
Filename: "{code:GetInstalledEntry}"; Description: "打开无限画布企业版启动窗口"; Flags: postinstall nowait skipifsilent; Tasks: launchafter; Check: ShouldMaintainEntry

[Code]
const
  GENERIC_READ = $80000000;
  GENERIC_WRITE = $40000000;
  OPEN_EXISTING = 3;
  INVALID_HANDLE_VALUE = -1;
  DRIVE_FIXED = 3;
  INVALID_FILE_ATTRIBUTES = $FFFFFFFF;
  MaxFrameBytes = 16384;
  PipeWaitMilliseconds = 45000;
  HexDigits = '0123456789abcdef';

var
  ModePage: TInputOptionWizardPage;
  TargetPage: TInputDirWizardPage;
  EnvironmentPage: TOutputMsgMemoWizardPage;
  OperationPage: TInputOptionWizardPage;
  TaskConfirmationPage: TInputOptionWizardPage;
  CredentialPage: TInputQueryWizardPage;
  InstallProgress: TOutputProgressWizardPage;
  DetachButton, StatusButton: TNewButton;
  SelectedInstallRoot: String;
  BundleRoot: String;
  LastStableCode: String;
  DefaultInstallRoot: String;
  ExistingEntryRepair: Boolean;
  MultipleInstalls: Boolean;
  InstallationId: String;
  RepairState: String;
  ObservedPhase: String;
  GraphicalPipeActive, Detached, PersistentBundle: Boolean;

function CreateFileW(lpFileName: String; dwDesiredAccess, dwShareMode: Cardinal;
  lpSecurityAttributes: LongWord; dwCreationDisposition, dwFlagsAndAttributes: Cardinal;
  hTemplateFile: LongWord): THandle;
  external 'CreateFileW@kernel32.dll stdcall';
function WaitNamedPipeW(lpNamedPipeName: String; nTimeOut: Cardinal): Boolean;
  external 'WaitNamedPipeW@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';
function GetDriveTypeW(lpRootPathName: String): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';
function GetFileAttributesW(lpFileName: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function GetTickCount64: Int64;
  external 'GetTickCount64@kernel32.dll stdcall';
function PeekNamedPipe(hNamedPipe: THandle; lpBuffer, nBufferSize, lpBytesRead: LongWord;
  var lpTotalBytesAvail: Cardinal; lpBytesLeftThisMessage: LongWord): Boolean;
  external 'PeekNamedPipe@kernel32.dll stdcall';

function MaintenanceOperation: String;
begin
  Result := 'install';
  if not ExistingEntryRepair then exit;
  case OperationPage.SelectedValueIndex of
    0: Result := 'repair-entry';
    1: Result := 'repair-program';
    2: Result := 'recover-program';
    3: Result := 'inspect-program';
    4: Result := 'recover-entry';
  end;
end;

function ShouldMaintainEntry: Boolean;
begin
  Result := (MaintenanceOperation = 'install') or (MaintenanceOperation = 'repair-entry') or
    (MaintenanceOperation = 'recover-entry');
end;

function MaintenanceCaption: String;
begin
  Result := '仅查看维护状态';
  if MaintenanceOperation = 'repair-program' then Result := '修复当前版本程序与 Python'
  else if MaintenanceOperation = 'recover-program' then Result := '恢复上次中断的程序修复'
  else if MaintenanceOperation = 'recover-entry' then Result := '恢复上次中断的固定入口修复';
end;

procedure PrepareBundle; forward;

function PhaseCaption(const Phase: String): String;
begin
  Result := '正在核验维护状态';
  if Phase = 'preparing' then Result := '正在准备完整程序与 Python（尚未切换）'
  else if Phase = 'locked' then Result := '正在核验停机、安装身份与维护锁'
  else if Phase = 'publishing' then Result := '正在替换已核验的同版本程序'
  else if Phase = 'verifying' then Result := '正在复核完整程序与运行环境'
  else if Phase = 'committed' then Result := '程序修复已提交，正在确认收尾'
  else if Phase = 'recovering' then Result := '正在核验上次记录并恢复一致状态'
  else if Phase = 'rolled_back' then Result := '已回退到修复前状态，仍需重新修复';
end;

procedure PaintMaintenanceProgress;
begin
  InstallProgress.SetText(MaintenanceCaption + '：' + PhaseCaption(ObservedPhase), '关闭查看不取消后台作业；重开安装包可仅查看状态。');
  InstallProgress.SetProgress(0, 0); { Real phase only, no invented percentage. }
end;

procedure ObserveMaintenancePhase(const Response: String);
begin
  { Allow-listed backend phases only; no arbitrary response text. }
  if Pos('"phase":"preparing"', Response) > 0 then ObservedPhase := 'preparing'
  else if Pos('"phase":"locked"', Response) > 0 then ObservedPhase := 'locked'
  else if Pos('"phase":"publishing"', Response) > 0 then ObservedPhase := 'publishing'
  else if Pos('"phase":"verifying"', Response) > 0 then ObservedPhase := 'verifying'
  else if Pos('"phase":"committed"', Response) > 0 then ObservedPhase := 'committed'
  else if Pos('"phase":"recovering"', Response) > 0 then ObservedPhase := 'recovering'
  else if Pos('"phase":"rolled_back"', Response) > 0 then ObservedPhase := 'rolled_back';
end;
function UTF8Bytes(const Value: String): AnsiString;
begin
  Result := Utf8Encode(Value);
end;

function UTF8Text(const Value: AnsiString): String;
begin
  Result := Utf8Decode(Value);
end;

function HexFixed(Value, Digits: Integer): String;
var
  I: Integer;
begin
  SetLength(Result, Digits);
  for I := Digits downto 1 do begin
    Result[I] := HexDigits[(Value mod 16) + 1];
    Value := Value div 16;
  end;
end;

function JsonEscape(const Value: String): String;
var
  I, Code: Integer;
  C: Char;
begin
  Result := '';
  for I := 1 to Length(Value) do begin
    C := Value[I];
    Code := Ord(C);
    if C = '"' then Result := Result + '\"'
    else if C = '\' then Result := Result + '\\'
    else if C = #8 then Result := Result + '\b'
    else if C = #9 then Result := Result + '\t'
    else if C = #10 then Result := Result + '\n'
    else if C = #12 then Result := Result + '\f'
    else if C = #13 then Result := Result + '\r'
    else if Code < 32 then Result := Result + '\u' + HexFixed(Code, 4)
    else Result := Result + C;
  end;
end;

function RequestJson: String;
var
  Mode, Target, Operation, Schema, Confirmation: String;
begin
  Operation := MaintenanceOperation;
  if (ModePage.SelectedValueIndex = 0) and not ExistingEntryRepair and not MultipleInstalls then begin
    Mode := 'quick';
    Target := 'null';
  end else begin
    Mode := 'custom';
    Target := '"' + JsonEscape(SelectedInstallRoot) + '"';
  end;
  Schema := 'enterprise-install-maintenance-request-v2';
  Confirmation := '';
  if not ShouldMaintainEntry then begin
    Schema := 'enterprise-install-maintenance-request-v4';
    if Operation = 'inspect-program' then Confirmation := ',"confirm_no_active_tasks":false'
    else Confirmation := ',"confirm_no_active_tasks":true';
  end;
  Result := '{"operation":"' + Operation + '","install_mode":"' + Mode + '","install_root":' + Target + Confirmation +
    ',"password":"' + JsonEscape(CredentialPage.Values[1]) +
    '","password_confirmation":"' + JsonEscape(CredentialPage.Values[2]) +
    '","schema_version":"' + Schema + '","username":"' +
    JsonEscape(CredentialPage.Values[0]) + '"}';
end;

function WriteAll(Stream: THandleStream; const Data: AnsiString): Boolean;
var
  Offset, Written: Integer;
  Chunk: AnsiString;
begin
  Result := False;
  Offset := 1;
  while Offset <= Length(Data) do begin
    Chunk := Copy(Data, Offset, 4096);
    Written := Stream.Write(Chunk, Length(Chunk));
    if Written <= 0 then exit;
    Offset := Offset + Written;
  end;
  Result := True;
end;

function ReadExact(Stream: THandleStream; Count: Integer; var Data: AnsiString): Boolean;
var
  Received, Wanted: Integer;
  Available: Cardinal;
  Chunk: AnsiString;
begin
  Result := False;
  Data := '';
  while Length(Data) < Count do begin
    Wanted := Count - Length(Data);
    if GraphicalPipeActive then begin
      PaintMaintenanceProgress;
      if Detached then exit;
      if not PeekNamedPipe(Stream.Handle, 0, 0, 0, Available, 0) then exit;
      if Available = 0 then begin Sleep(75); continue; end;
      if Available < Cardinal(Wanted) then Wanted := Available;
    end;
    SetLength(Chunk, Wanted);
    Received := Stream.Read(Chunk, Length(Chunk));
    if Received <= 0 then exit;
    SetLength(Chunk, Received);
    Data := Data + Chunk;
  end;
  Result := True;
end;

function WaitForPipeServer(const PipeName: String): Boolean;
var
  Deadline: Int64;
begin
  Result := False;
  Deadline := GetTickCount64 + PipeWaitMilliseconds;
  repeat
    if GraphicalPipeActive then begin
      PaintMaintenanceProgress;
      if Detached then exit;
    end;
    if WaitNamedPipeW(PipeName, 250) then begin
      Result := True;
      exit;
    end;
    Sleep(50);
  until GetTickCount64 >= Deadline;
end;

function PipeExchange(const PipeSuffix, Request: String; var Response: String): Boolean;
var
  PipeName: String;
  Handle: THandle;
  Stream: THandleStream;
  Payload, Frame, Header, ResponseBytes: AnsiString;
  ResponseLength: Integer;
begin
  Result := False;
  PipeName := '\\.\pipe\InfiniteCanvasEnterprise-InstallUX1-' + PipeSuffix;
  LastStableCode := 'INSTALL_SETUP_BRIDGE_PIPE_NOT_READY';
  if not WaitForPipeServer(PipeName) then exit;
  LastStableCode := 'INSTALL_SETUP_BRIDGE_PIPE_OPEN_FAILED';
  Handle := CreateFileW(PipeName, GENERIC_READ or GENERIC_WRITE, 0, 0, OPEN_EXISTING, 0, 0);
  if Handle = INVALID_HANDLE_VALUE then exit;
  Stream := THandleStream.Create(Handle);
  try
    Payload := UTF8Bytes(Request);
    LastStableCode := 'INSTALL_SETUP_BRIDGE_REQUEST_INVALID';
    if (Length(Payload) < 1) or (Length(Payload) > MaxFrameBytes) then exit;
    Frame := AnsiString(HexFixed(Length(Payload), 8)) + Payload;
    LastStableCode := 'INSTALL_SETUP_BRIDGE_WRITE_FAILED';
    if not WriteAll(Stream, Frame) then exit;
    LastStableCode := 'INSTALL_SETUP_BRIDGE_READ_FAILED';
    repeat
      if not ReadExact(Stream, 8, Header) then exit;
      ResponseLength := StrToIntDef('$' + String(Header), -1);
      LastStableCode := 'INSTALL_SETUP_BRIDGE_RESPONSE_INVALID';
      if (ResponseLength < 1) or (ResponseLength > MaxFrameBytes) then exit;
      LastStableCode := 'INSTALL_SETUP_BRIDGE_READ_FAILED';
      if not ReadExact(Stream, ResponseLength, ResponseBytes) then exit;
      Response := UTF8Text(ResponseBytes);
      if GraphicalPipeActive and (Pos('"event":"progress"', Response) > 0) then begin
        { Backend enum only; do not display paths, credentials or arbitrary response. }
        ObserveMaintenancePhase(Response);
        PaintMaintenanceProgress;
      end else break;
    until False;
    Result := True;
  finally
    Stream.Free;
    CloseHandle(Handle);
  end;
end;

function ExtractCode(const Response: String): String;
var
  Marker: String;
  StartAt, EndAt: Integer;
begin
  Result := 'INSTALL_SETUP_BRIDGE_RESPONSE_INVALID';
  Marker := '"code":"';
  StartAt := Pos(Marker, Response);
  if StartAt = 0 then exit;
  StartAt := StartAt + Length(Marker);
  EndAt := StartAt;
  while (EndAt <= Length(Response)) and (Response[EndAt] <> '"') do
    EndAt := EndAt + 1;
  if (EndAt <= StartAt) or (EndAt > Length(Response)) then exit;
  Result := Copy(Response, StartAt, EndAt - StartAt);
end;

function IsDirectoryEmpty(const Directory: String): Boolean;
var
  FindRec: TFindRec;
begin
  Result := True;
  if not DirExists(Directory) then exit;
  if FindFirst(AddBackslash(Directory) + '*', FindRec) then begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then begin
          Result := False;
          exit;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function HasExistingReparseLeaf(const Path: String): Boolean;
var
  Attributes: Cardinal;
begin
  Attributes := GetFileAttributesW(Path);
  Result := (Attributes <> INVALID_FILE_ATTRIBUTES) and
    ((Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0);
end;

function ValidateTarget(const Target: String; var Code: String): Boolean;
var
  DriveRoot: String;
  FreeBytes, TotalBytes, RequiredBytes: Int64;
begin
  Result := False;
  ExistingEntryRepair := False;
  Code := 'INSTALL_TARGET_UNSAFE';
  if (Length(Target) < 3) or (Copy(Target, 1, 2) = '\\') then exit;
  DriveRoot := ExtractFileDrive(Target) + '\';
  if GetDriveTypeW(DriveRoot) <> DRIVE_FIXED then begin
    Code := 'INSTALL_TARGET_NOT_LOCAL_FIXED_DISK';
    exit;
  end;
  if HasExistingReparseLeaf(Target) then exit;
  if DirExists(Target) and not IsDirectoryEmpty(Target) then begin
    if FileExists(AddBackslash(Target) + 'state\current-release.json') and
       DirExists(AddBackslash(Target) + 'releases') then
      ExistingEntryRepair := True
    else begin
      Code := 'INSTALL_TARGET_NOT_GREENFIELD';
      exit;
    end;
  end;
  if not GetSpaceOnDisk64(DriveRoot, FreeBytes, TotalBytes) then begin
    Code := 'INSTALL_DISK_SPACE_CHECK_FAILED';
    exit;
  end;
  RequiredBytes := StrToInt64('{#ArchiveSize}') + 536870912;
  if FreeBytes < RequiredBytes then begin
    Code := 'INSTALL_DISK_SPACE_INSUFFICIENT';
    exit;
  end;
  Result := True;
end;

procedure FindRegisteredInstall;
var
  Keys: TArrayOfString;
  I, Count: Integer;
  Candidate, Found: String;
begin
  DefaultInstallRoot := ExpandConstant('{localappdata}\Infinite-Canvas-Enterprise\install');
  Count := 0;
  if RegGetSubkeyNames(HKCU, 'Software\Infinite-Canvas-Enterprise\Installations', Keys) then begin
    if GetArrayLength(Keys) > 32 then begin
      MultipleInstalls := True;
      exit;
    end;
    for I := 0 to GetArrayLength(Keys) - 1 do begin
      if RegQueryStringValue(HKCU, 'Software\Infinite-Canvas-Enterprise\Installations\' + Keys[I],
         'InstallLocation', Candidate) and
         (Length(Candidate) > 3) and (Copy(Candidate, 1, 2) <> '\\') and
         (GetDriveTypeW(ExtractFileDrive(Candidate) + '\') = DRIVE_FIXED) and
         FileExists(AddBackslash(Candidate) + 'state\current-release.json') then begin
        if CompareText(Candidate, Found) <> 0 then begin
          Count := Count + 1;
          Found := Candidate;
        end;
      end;
    end;
  end;
  MultipleInstalls := Count > 1;
  if Count = 1 then DefaultInstallRoot := Found;
end;

function ExtractInstallationId(const Response: String): String;
var
  StartAt, I: Integer;
  Marker: String;
begin
  Result := '';
  Marker := '"installation_id":"';
  StartAt := Pos(Marker, Response);
  if StartAt = 0 then exit;
  StartAt := StartAt + Length(Marker);
  Result := Copy(Response, StartAt, 32);
  if (Length(Result) <> 32) or (Copy(Response, StartAt + 32, 1) <> '"') then begin
    Result := '';
    exit;
  end;
  for I := 1 to 32 do
    if Pos(Result[I], HexDigits) = 0 then begin Result := ''; exit; end;
end;

procedure SetStage(const Caption: String; Position: Integer);
begin
  if not ShouldMaintainEntry then begin
    InstallProgress.SetText(Caption, '程序维护不会改变业务数据；后台接管后可关闭查看。');
    InstallProgress.SetProgress(0, 0);
  end else begin
    InstallProgress.SetText(Caption, '请勿关闭安装程序。');
    InstallProgress.SetProgress(Position, 6);
  end;
end;

procedure DetachProgress(Sender: TObject);
begin
  Detached := True; { Presentation only: never terminate the backend. }
end;

procedure RequireEmbeddedFile(const Path, ExpectedHash: String; ExpectedSize: Int64);
var
  ActualSize: Int64;
begin
  if not FileSize64(Path, ActualSize) then
    RaiseException('INSTALL_EMBEDDED_ASSET_MISSING');
  if ActualSize <> ExpectedSize then
    RaiseException('INSTALL_EMBEDDED_ASSET_SIZE_MISMATCH');
  if CompareText(GetSHA256OfFile(Path), ExpectedHash) <> 0 then
    RaiseException('INSTALL_EMBEDDED_ASSET_HASH_MISMATCH');
end;

procedure MoveExtractedAssetToBundle(const FileName: String);
var
  SourcePath, TargetPath: String;
begin
  SourcePath := AddBackslash(ExpandConstant('{tmp}')) + FileName;
  TargetPath := AddBackslash(BundleRoot) + FileName;
  if not RenameFile(SourcePath, TargetPath) then
    RaiseException('INSTALL_EMBEDDED_ASSET_EXTRACTION_FAILED');
end;

function BuildPipeSuffix: String;
begin
  Result := Lowercase(Copy(GetSHA256OfUnicodeString(
    IntToStr(GetTickCount64) + '|' +
    IntToStr(Random(2147483647)) + '|' + ExpandConstant('{tmp}')), 1, 32));
end;

function RunBridge: Boolean;
var
  RawRoot, PythonExe, BridgePath, PipeSuffix, Parameters: String;
  Request, Response: String;
  ProcessResult: Integer;
begin
  Result := False;
  Detached := False;
  ObservedPhase := '';
  RepairState := '';
  InstallationId := '';
  RawRoot := BundleRoot + '\raw\{#ArchiveRootPrefix}';
  PythonExe := RawRoot + '\python\python.exe';
  BridgePath := RawRoot + '\enterprise\install_setup_bridge.py';
  if not FileExists(PythonExe) or not FileExists(BridgePath) then begin
    LastStableCode := 'INSTALL_BOOTSTRAP_INVALID';
    exit;
  end;
  LastStableCode := 'INSTALL_SETUP_BRIDGE_PIPE_NAME_FAILED';
  PipeSuffix := BuildPipeSuffix;
  Parameters := '-I -B "' + BridgePath + '" --pipe-name ' + PipeSuffix;
  LastStableCode := 'INSTALL_SETUP_BRIDGE_LAUNCH_FAILED';
  if not Exec(PythonExe, Parameters, RawRoot, SW_HIDE, ewNoWait, ProcessResult) then begin
    exit;
  end;
  LastStableCode := 'INSTALL_SETUP_BRIDGE_REQUEST_BUILD_FAILED';
  Request := RequestJson;
  CredentialPage.Values[1] := '';
  CredentialPage.Values[2] := '';
  GraphicalPipeActive := not ShouldMaintainEntry;
  DetachButton.Visible := GraphicalPipeActive and (MaintenanceOperation <> 'inspect-program');
  try
    if not PipeExchange(PipeSuffix, Request, Response) then begin
      Request := '';
      if Detached then LastStableCode := 'INSTALL_PROGRAM_VIEW_DETACHED';
      exit;
    end;
  finally
    GraphicalPipeActive := False;
    DetachButton.Visible := False;
  end;
  Request := '';
  LastStableCode := ExtractCode(Response);
  Result := Pos('"status":"succeeded"', Response) > 0;
  if Result then begin
    InstallationId := ExtractInstallationId(Response);
    if InstallationId = '' then begin
      LastStableCode := 'INSTALL_IDENTITY_INVALID';
      Result := False;
    end;
    if not ShouldMaintainEntry or (MaintenanceOperation = 'recover-entry') then begin
      ObserveMaintenancePhase(Response);
      if Pos('"repair_state":"SUCCEEDED"', Response) > 0 then RepairState := 'SUCCEEDED'
      else if Pos('"repair_state":"ROLLED_BACK"', Response) > 0 then RepairState := 'ROLLED_BACK'
      else if Pos('"repair_state":"RUNNING"', Response) > 0 then RepairState := 'RUNNING'
      else if Pos('"repair_state":"RECOVERY_REQUIRED"', Response) > 0 then RepairState := 'RECOVERY_REQUIRED'
      else if Pos('"repair_state":"STOPPED_BEFORE_SWITCH"', Response) > 0 then RepairState := 'STOPPED_BEFORE_SWITCH'
      else if Pos('"repair_state":"NONE"', Response) > 0 then RepairState := 'NONE'
      else begin Result := False; LastStableCode := 'INSTALL_SETUP_BRIDGE_RESPONSE_INVALID'; end;
    end;
  end;
  Response := '';
end;

function RepairStateCaption: String;
begin
  Result := '状态尚未核准；请保留记录，不要重复提交或删除锁文件。';
  if RepairState = 'RUNNING' then Result := '后台仍在执行：' + PhaseCaption(ObservedPhase) + #13#10 + '请稍后刷新，不要重复提交。'
  else if RepairState = 'RECOVERY_REQUIRED' then Result := '上次执行已中断；请选择恢复，后台核验后才会解除本次修复阻断。'
  else if RepairState = 'SUCCEEDED' then Result := '程序修复已完成；当前版本与业务数据未改变。'
  else if RepairState = 'ROLLED_BACK' then Result := '已恢复到修复前状态，原有损坏也可能仍在；请重新修复，不能当作修好。'
  else if RepairState = 'STOPPED_BEFORE_SWITCH' then Result := '作业在切换前停止，原程序未改变；可重新确认修复。'
  else if RepairState = 'NONE' then Result := '暂无程序修复记录；未执行修复或恢复。';
end;

procedure InspectMaintenance(Sender: TObject);
var
  SelectedOperation: Integer;
begin
  SelectedOperation := OperationPage.SelectedValueIndex;
  OperationPage.SelectedValueIndex := 3;
  InstallProgress.Show;
  try
    PrepareBundle;
    if RunBridge then MsgBox(RepairStateCaption, mbInformation, MB_OK)
    else MsgBox('状态未核准：' + LastStableCode + #13#10 +
      '没有执行恢复；请保留诊断与恢复记录。', mbError, MB_OK);
  except
    MsgBox('状态检查未完成；没有执行恢复。' + #13#10 + GetExceptionMessage, mbError, MB_OK);
  finally
    OperationPage.SelectedValueIndex := SelectedOperation;
    InstallProgress.Hide;
  end;
end;

procedure InitializeWizard;
begin
  FindRegisteredInstall;
  WizardForm.WelcomeLabel1.Caption := '欢迎安装无限画布企业版';
  WizardForm.WelcomeLabel2.Caption := '版本 {#AppVersion}' + #13#10 + #13#10 +
    '安装包已包含独立 Python 运行环境，无需安装 Python。';

  ModePage := CreateInputOptionPage(wpWelcome, '选择安装或维护位置',
    '已有安装优先使用原位置', '维护不重置账号、数据库、配置或当前版本；后续页面明确选择入口修复、程序修复、恢复或查看状态。业务升级仍由更新中心执行。', True, False);
  ModePage.Add('使用推荐位置（已有安装优先）');
  ModePage.Add('选择安装位置');
  ModePage.SelectedValueIndex := 0;
  if MultipleInstalls then ModePage.SelectedValueIndex := 1;

  TargetPage := CreateInputDirPage(ModePage.ID, '选择安装位置',
    '选择全新目录，或要维护的已有安装。',
    '多个安装须明确选择；仅有目录/登记不代表已通过身份核验。其他项目、未知目录及损坏程序不会被覆盖。', False, '');
  TargetPage.Add('安装根目录：');
  TargetPage.Values[0] := DefaultInstallRoot;

  EnvironmentPage := CreateOutputMsgMemoPage(TargetPage.ID, '环境检查',
    '安装器将在继续前执行以下检查：', '',
    'Windows x64' + #13#10 +
    '当前用户安装（不请求管理员权限）' + #13#10 +
    '本机固定磁盘与可用空间' + #13#10 +
    '新装目录安全，或已有安装完整 Release 身份' + #13#10 +
    '内嵌 Release 身份和三个核心资产');

  OperationPage := CreateInputOptionPage(EnvironmentPage.ID, '选择维护操作',
    '保留原账号、数据库、画布、素材、配置及当前版本',
    '程序修复需要与当前 Release 完全相同的安装包，且服务已停止。未知升级或恢复记录不能由这里解除。', True, False);
  OperationPage.Add('只修复固定入口与快捷方式');
  OperationPage.Add('修复当前版本程序与 Python（不是业务升级）');
  OperationPage.Add('恢复上次中断的程序修复');
  OperationPage.Add('仅查看维护状态／跨窗口进度（不执行恢复）');
  OperationPage.Add('恢复上次中断的固定入口修复（仅核验本包可证明的事务）');
  OperationPage.SelectedValueIndex := 0;
  StatusButton := TNewButton.Create(WizardForm);
  StatusButton.Parent := OperationPage.Surface;
  StatusButton.Caption := '刷新维护状态';
  StatusButton.Width := ScaleX(125);
  StatusButton.Height := ScaleY(28);
  StatusButton.Top := OperationPage.SurfaceHeight - StatusButton.Height;
  StatusButton.OnClick := @InspectMaintenance;

  TaskConfirmationPage := CreateInputOptionPage(OperationPage.ID, '确认安全维护',
    '此操作不取消或重新提交 AI 任务',
    '请先确认没有未完成的 AI 任务，并从固定入口停止本安装服务。后台还会核验进程、端口与维护锁；不会强行停止其他安装。', False, False);
  TaskConfirmationPage.Add('我确认没有未完成的 AI 任务，并已停止本安装服务。');
  TaskConfirmationPage.Values[0] := False;

  CredentialPage := CreateInputQueryPage(TaskConfirmationPage.ID, '创建首个管理员',
    '创建唯一的首个 super_admin', '凭据只通过当前用户的一次性内存管道传递，不写入命令行、环境或文件。');
  CredentialPage.Add('管理员用户名：', False);
  CredentialPage.Add('密码：', True);
  CredentialPage.Add('确认密码：', True);

  InstallProgress := CreateOutputProgressPage('正在安装', '安装未完成前不会发布 current-release 指针。');
  DetachButton := TNewButton.Create(WizardForm);
  DetachButton.Parent := InstallProgress.Surface;
  DetachButton.Caption := '关闭查看（后台继续）';
  DetachButton.Width := ScaleX(185);
  DetachButton.Height := ScaleY(28);
  DetachButton.Left := InstallProgress.SurfaceWidth - DetachButton.Width;
  DetachButton.Top := InstallProgress.SurfaceHeight - DetachButton.Height;
  DetachButton.OnClick := @DetachProgress;
  DetachButton.Visible := False;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ((PageID = TargetPage.ID) and (ModePage.SelectedValueIndex = 0) and not MultipleInstalls) or
    ((PageID = CredentialPage.ID) and ExistingEntryRepair) or
    ((PageID = OperationPage.ID) and not ExistingEntryRepair) or
    ((PageID = TaskConfirmationPage.ID) and (ShouldMaintainEntry or (MaintenanceOperation = 'inspect-program'))) or
    ((PageID = wpSelectTasks) and not ShouldMaintainEntry);
end;

procedure ShowMaintenanceScope;
begin
  if ExistingEntryRepair then
    EnvironmentPage.RichEditViewer.Text := '操作：只修复固定入口' + #13#10 +
      '原安装目录：' + SelectedInstallRoot + #13#10 + #13#10 +
      '已发现已有安装候选，执行时仍需完整核验其当前 Release。' + #13#10 +
      '只修复固定 EXE、实例登记和快捷方式。不会初始化或迁移数据库，不会改变当前版本。' + #13#10 +
      '下一页明确选择入口修复、同版本程序/Python 修复、上次中断恢复或只读进度查看。'
  else
    EnvironmentPage.RichEditViewer.Text := '操作：首次安装' + #13#10 +
      '安装根目录：' + SelectedInstallRoot + #13#10 + #13#10 +
      '目标必须是全新空目录，已有数据不会被当作新安装重建。' + #13#10 +
      'Windows x64；当前用户安装；本机固定磁盘与可用空间。' + #13#10 +
      '执行时验证内嵌 Release 身份、核心资产和固定入口，再创建首个管理员。';
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Code: String;
begin
  if CurPageID = EnvironmentPage.ID then begin
    if ValidateTarget(SelectedInstallRoot, Code) then ShowMaintenanceScope
    else EnvironmentPage.RichEditViewer.Text := '目标位置检查未通过：' + SelectedInstallRoot + #13#10 +
      '错误代码：' + Code + #13#10 + '尚未执行安装；请选择有效目录。';
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  if ExistingEntryRepair and not ShouldMaintainEntry then
    Result := '操作：' + MaintenanceCaption + NewLine +
      Space + '原安装目录：' + SelectedInstallRoot + NewLine +
      Space + '保留原账号、数据库、画布、素材、配置及当前版本。' + NewLine +
      Space + '后台复核准确身份与停机状态；不是业务升级，不解除未知恢复阻断。'
  else if ExistingEntryRepair then
    Result := '操作：只修复固定入口（不是业务升级）' + NewLine +
      Space + '原安装目录：' + SelectedInstallRoot + NewLine +
      Space + '保留原账号、数据库、画布、素材、配置及当前版本。' + NewLine +
      Space + '仅修复或恢复根 EXE 与实例登记；未知或旧 v1 锁不会自动解除。'
  else
    Result := '操作：首次安装' + NewLine + Space + '安装根目录：' + SelectedInstallRoot + NewLine +
      Space + '安装版本：{#AppVersion}' + NewLine + Space + 'Release：{#ReleaseId}';
  if MemoTasksInfo <> '' then Result := Result + NewLine + NewLine + MemoTasksInfo;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Code: String;
begin
  Result := True;
  if CurPageID = ModePage.ID then begin
    if ModePage.SelectedValueIndex = 0 then
      SelectedInstallRoot := DefaultInstallRoot
    else
      SelectedInstallRoot := TargetPage.Values[0];
  end;
  if CurPageID = TargetPage.ID then
    SelectedInstallRoot := TargetPage.Values[0];
  if CurPageID = EnvironmentPage.ID then begin
    if not ValidateTarget(SelectedInstallRoot, Code) then begin
      MsgBox('安装环境检查未通过。' + #13#10 + '错误代码：' + Code,
        mbError, MB_OK);
      Result := False;
    end else if ExistingEntryRepair then begin
      CredentialPage.Values[0] := '';
      CredentialPage.Values[1] := '';
      CredentialPage.Values[2] := '';
      ShowMaintenanceScope;
    end;
  end;
  if CurPageID = CredentialPage.ID then begin
    if Trim(CredentialPage.Values[0]) = '' then begin
      MsgBox('请输入管理员用户名。', mbError, MB_OK);
      Result := False;
    end else if CredentialPage.Values[1] = '' then begin
      MsgBox('请输入密码。', mbError, MB_OK);
      Result := False;
    end else if CredentialPage.Values[1] <> CredentialPage.Values[2] then begin
      MsgBox('两次输入的密码不一致。', mbError, MB_OK);
      Result := False;
    end;
  end;
  if (CurPageID = TaskConfirmationPage.ID) and not TaskConfirmationPage.Values[0] then begin
    MsgBox('请先确认没有未完成任务，并停止本安装服务。', mbError, MB_OK);
    Result := False;
  end;
  if (CurPageID = OperationPage.ID) and (MaintenanceOperation = 'inspect-program') then begin
    InspectMaintenance(nil);
    Result := False; { Inspection never reaches installation/shortcut/registry steps. }
  end;
end;

function HasReparseAncestors(const Path: String): Boolean;
var
  Current, Parent: String;
begin
  Result := True;
  Current := Path;
  repeat
    if HasExistingReparseLeaf(Current) then exit;
    Parent := ExtractFileDir(Current);
    if (Parent = Current) or (Parent = '') then break;
    Current := Parent;
  until False;
  Result := False;
end;

procedure PrepareBundle;
var
  MetadataPath, ArchivePath, ManifestPath, InventoryPath, RawDir, CacheRoot: String;
  FreeBytes, TotalBytes, RequiredBytes: Int64;
begin
    if BundleRoot <> '' then begin
      if (MaintenanceOperation <> 'install') and not PersistentBundle then
        RaiseException('INSTALL_PROGRAM_REOPEN_REQUIRED');
      exit;
    end;
    { Closing Setup does not prove the external maintenance Python has exited. }
    PersistentBundle := MaintenanceOperation <> 'install';
    if PersistentBundle then begin
      CacheRoot := ExpandConstant('{localappdata}\Infinite-Canvas-Enterprise\maintenance-payloads');
      if HasReparseAncestors(CacheRoot) then RaiseException('INSTALL_TEMP_ROOT_UNSAFE');
      RequiredBytes := StrToInt64('{#ArchiveSize}') + StrToInt64('{#ArchiveUncompressedSize}') + 67108864;
      if not GetSpaceOnDisk64(ExtractFileDrive(CacheRoot) + '\', FreeBytes, TotalBytes) then
        RaiseException('INSTALL_DISK_SPACE_CHECK_FAILED');
      if FreeBytes < RequiredBytes then RaiseException('INSTALL_DISK_SPACE_INSUFFICIENT');
      BundleRoot := CacheRoot + '\' + BuildPipeSuffix + '\install-ux-bundle';
    end else BundleRoot := ExpandConstant('{tmp}\install-ux-bundle');
    SetStage('验证安装包', 1);
    LastStableCode := 'INSTALL_TEMP_ROOT_UNSAFE';
    if HasExistingReparseLeaf(ExpandConstant('{tmp}')) then
      RaiseException('INSTALL_TEMP_ROOT_UNSAFE');
    LastStableCode := 'INSTALL_EMBEDDED_ASSET_EXTRACTION_FAILED';
    ExtractTemporaryFile('{#ArchiveFilename}');
    ExtractTemporaryFile('{#ManifestFilename}');
    ExtractTemporaryFile('{#InventoryFilename}');
    ExtractTemporaryFile('installer-metadata.json');
    ExtractTemporaryFile('InfiniteCanvas.exe');
    ExtractTemporaryFile('native-entry-build-record.json');
    if DirExists(BundleRoot) then
      RaiseException('INSTALL_TEMP_ROOT_UNSAFE');
    ForceDirectories(BundleRoot);
    MoveExtractedAssetToBundle('{#ArchiveFilename}');
    MoveExtractedAssetToBundle('{#ManifestFilename}');
    MoveExtractedAssetToBundle('{#InventoryFilename}');
    ArchivePath := BundleRoot + '\{#ArchiveFilename}';
    ManifestPath := BundleRoot + '\{#ManifestFilename}';
    InventoryPath := BundleRoot + '\{#InventoryFilename}';
    MetadataPath := ExpandConstant('{tmp}\installer-metadata.json');
    LastStableCode := 'INSTALL_EMBEDDED_ASSET_VERIFICATION_FAILED';
    RequireEmbeddedFile(ArchivePath, '{#ArchiveSha256}', StrToInt64('{#ArchiveSize}'));
    RequireEmbeddedFile(ManifestPath, '{#ManifestSha256}', StrToInt64('{#ManifestSize}'));
    RequireEmbeddedFile(InventoryPath, '{#InventorySha256}', StrToInt64('{#InventorySize}'));
    RequireEmbeddedFile(MetadataPath, '{#MetadataSha256}', StrToInt64('{#MetadataSize}'));
    RequireEmbeddedFile(ExpandConstant('{tmp}\InfiniteCanvas.exe'), '{#NativeEntrySha256}', StrToInt64('{#NativeEntrySize}'));
    RequireEmbeddedFile(ExpandConstant('{tmp}\native-entry-build-record.json'), '{#NativeRecordSha256}', StrToInt64('{#NativeRecordSize}'));
    ForceDirectories(BundleRoot + '\native-entry');
    if not RenameFile(ExpandConstant('{tmp}\InfiniteCanvas.exe'), BundleRoot + '\native-entry\InfiniteCanvas.exe') or
       not RenameFile(ExpandConstant('{tmp}\native-entry-build-record.json'), BundleRoot + '\native-entry\native-entry-build-record.json') then
      RaiseException('INSTALL_EMBEDDED_ASSET_EXTRACTION_FAILED');

    SetStage('准备程序文件', 2);
    LastStableCode := 'INSTALL_ARCHIVE_EXTRACTION_FAILED';
    RawDir := BundleRoot + '\raw';
    ForceDirectories(RawDir);
    ExtractArchive(ArchivePath, RawDir, '', True, nil);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExceptionCode: String;
begin
  Result := '';
  LastStableCode := 'INSTALL_SETUP_FAILED';
  InstallProgress.Show;
  try
    if not ShouldMaintainEntry and not TaskConfirmationPage.Values[0] then
      RaiseException('INSTALL_PROGRAM_TASK_CONFIRMATION_REQUIRED');
    PrepareBundle;
    if not ShouldMaintainEntry then SetStage('核验并执行已确认的程序维护', 3)
    else if ExistingEntryRepair then SetStage('核验并修复固定入口（不修改业务数据）', 3)
    else SetStage('初始化企业数据库', 3);
    LastStableCode := 'INSTALL_SETUP_BRIDGE_FAILED';
    if not RunBridge then begin
      if LastStableCode = 'INSTALL_ENTRY_TARGET_PATH_TOO_LONG' then
        Result := '安装目录过深，请选择较短的本机路径；尚未初始化安装或业务数据。' + #13#10
      else if LastStableCode = 'INSTALL_PROGRAM_VIEW_DETACHED' then
        Result := '已关闭进度查看，后台作业可能仍在继续；关闭此安装包，重开后选择刷新维护状态。不要重复提交。' + #13#10
      else Result := '操作未完成；不会把原目录当作新安装重建。请保留诊断与恢复记录。' + #13#10;
      Result := Result +
        '错误代码：' + LastStableCode;
      exit;
    end;
    if (MaintenanceOperation = 'recover-entry') and (RepairState <> 'SUCCEEDED') then begin
      Result := '入口事务已恢复到修复前状态；原入口可能仍缺失，请重新选择入口修复。' + #13#10 +
        '业务数据、配置及当前版本未改变；不会生成指向缺失入口的快捷方式或自动启动。';
      exit;
    end;
    if not ShouldMaintainEntry then begin
      if RepairState <> 'SUCCEEDED' then begin
        Result := RepairStateCaption;
        exit;
      end;
      WizardForm.FinishedLabel.Caption := RepairStateCaption + #13#10 +
        '服务未自动启动；可从原固定入口查看状态并启动。';
      SetStage('同版本程序维护完成（业务数据不变）', 6);
      exit;
    end;
    SetStage('固定入口已就绪', 4);
    if ExistingEntryRepair then begin
      SetStage('原账号、数据及当前版本保持不变', 5);
      SetStage('入口修复完成', 6);
    end else begin
      SetStage('配置运行环境已就绪', 5);
      SetStage('完成安装', 6);
    end;
  except
    ExceptionCode := GetExceptionMessage;
    if Pos('INSTALL_', ExceptionCode) = 1 then
      LastStableCode := ExceptionCode;
    Result := '操作未完成，请保留诊断与恢复记录；不要删除业务数据或锁文件重试。' + #13#10 +
      '错误代码：' + LastStableCode;
  finally
    CredentialPage.Values[1] := '';
    CredentialPage.Values[2] := '';
    InstallProgress.Hide;
  end;
end;

function GetInstalledEntry(Param: String): String;
begin
  Result := AddBackslash(SelectedInstallRoot) + 'InfiniteCanvas.exe';
end;

function GetInstallRoot(Param: String): String;
begin
  Result := SelectedInstallRoot;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Key: String;
begin
  if (CurStep = ssPostInstall) and ShouldMaintainEntry and (InstallationId <> '') then begin
    Key := 'Software\Infinite-Canvas-Enterprise\Installations\' + InstallationId;
    if not RegWriteStringValue(HKCU, Key, 'InstallLocation', SelectedInstallRoot) or
       not RegWriteStringValue(HKCU, Key, 'Launcher', GetInstalledEntry('')) then
      MsgBox('固定入口已安装，但自动定位登记未完成。请从原安装根打开 InfiniteCanvas.exe；业务数据未重建。', mbInformation, MB_OK);
  end;
end;

procedure DeinitializeSetup;
begin
  { Never remove the external interpreter beneath a detached worker. Persistent
    payloads stay in this product's cache pending verified retention/cleanup. }
  if (BundleRoot <> '') and not PersistentBundle then
    DelTree(BundleRoot, True, True, True);
end;
