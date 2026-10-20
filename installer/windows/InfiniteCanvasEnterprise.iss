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
AppId={code:GetLifecycleAppId}
AppName={#ProductName}
AppVerName={#ProductNameZh} {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=MEIS-DaCaiTou
DefaultDirName={localappdata}\Infinite-Canvas-Enterprise\install
CreateAppDir=yes
DisableDirPage=yes
UsePreviousAppDir=no
UsePreviousLanguage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
SetupArchitecture=x64
Uninstallable=RegisterLifecycle
UninstallFilesDir={app}\state\windows-uninstaller
UninstallDisplayName={#ProductNameZh} {#AppVersion} ({app})
UninstallDisplayIcon={app}\InfiniteCanvas.exe
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
Name: "{autoprograms}\无限画布企业版\{code:GetLifecycleInstance}\无限画布企业版"; Filename: "{code:GetInstalledEntry}"; WorkingDir: "{code:GetInstallRoot}"; Check: ShouldMaintainEntry
Name: "{autodesktop}\无限画布企业版-{code:GetLifecycleInstance}"; Filename: "{code:GetInstalledEntry}"; WorkingDir: "{code:GetInstallRoot}"; Tasks: desktopicon; Check: ShouldMaintainEntry

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
  CachePage: TInputOptionWizardPage;
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
  CacheCleaning: Boolean;
  CacheIds, CacheTokens, CacheSizes: TArrayOfString;
  CacheRows, SelectedCacheId, SelectedCacheToken: String;
  CacheRefreshButton: TNewButton;
  HeadlessLifecycle, LifecycleSupportReady, MatchingLifecycleRelease: Boolean;
  HeadlessOperation, HeadlessRoot, LifecycleState, UpgradeState: String;
  FinalizingUpgrade: Boolean;
  InspectingEntry: Boolean;
  EntryState: String;

procedure ExitProcess(ExitCode: Cardinal);
  external 'ExitProcess@kernel32.dll stdcall';

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
  if InspectingEntry then begin Result := 'inspect-entry'; exit; end;
  if FinalizingUpgrade then begin Result := 'finish-upgrade'; exit; end;
  if HeadlessLifecycle then begin Result := HeadlessOperation; exit; end;
  if CacheCleaning then begin Result := 'clean-cache'; exit; end;
  Result := 'install';
  if not ExistingEntryRepair then exit;
  case OperationPage.SelectedValueIndex of
    0: Result := 'repair-entry';
    1: Result := 'repair-program';
    2: Result := 'recover-program';
    3: Result := 'inspect-program';
    4: Result := 'recover-entry';
    5: Result := 'inspect-cache';
    6: Result := 'uninstall-retain';
    7: Result := 'recover-uninstall';
    8: Result := 'reinstall-retained';
    9: Result := 'inspect-lifecycle';
    10: Result := 'upgrade-retained';
    11: Result := 'recover-upgrade';
    12: Result := 'inspect-upgrade';
  end;
end;

function IsUpgradeOperation: Boolean;
begin
  Result := (MaintenanceOperation = 'upgrade-retained') or
    (MaintenanceOperation = 'recover-upgrade') or
    (MaintenanceOperation = 'inspect-upgrade') or
    (MaintenanceOperation = 'finish-upgrade');
end;

function IsLifecycleOperation: Boolean;
begin
  Result := (MaintenanceOperation = 'uninstall-retain') or
    (MaintenanceOperation = 'recover-uninstall') or
    (MaintenanceOperation = 'reinstall-retained') or
    (MaintenanceOperation = 'inspect-lifecycle');
end;

function IsCacheOperation: Boolean;
begin
  Result := (MaintenanceOperation = 'inspect-cache') or (MaintenanceOperation = 'clean-cache');
end;

function ShouldMaintainEntry: Boolean;
begin
  Result := (MaintenanceOperation = 'install') or (MaintenanceOperation = 'repair-entry') or
    (MaintenanceOperation = 'recover-entry') or (MaintenanceOperation = 'reinstall-retained') or
    (MaintenanceOperation = 'upgrade-retained') or (MaintenanceOperation = 'recover-upgrade');
end;

function MaintenanceCaption: String;
begin
  Result := '仅查看维护状态';
  if IsUpgradeOperation then begin Result := '离线跨版本升级／保留数据重装'; exit; end;
  if IsLifecycleOperation then begin Result := '保留数据卸载／重装'; exit; end;
  if IsCacheOperation then begin Result := '维护准备包管理（不清理业务数据）'; exit; end;
  if MaintenanceOperation = 'repair-entry' then begin Result := '修复固定入口与快捷方式'; exit; end;
  if MaintenanceOperation = 'install' then begin Result := '安装无限画布企业版'; exit; end;
  if MaintenanceOperation = 'repair-program' then Result := '修复当前版本程序与 Python'
  else if MaintenanceOperation = 'recover-program' then Result := '恢复上次中断的程序修复'
  else if MaintenanceOperation = 'recover-entry' then Result := '恢复上次中断的固定入口修复';
end;

procedure PrepareBundle; forward;
procedure RunRegisteredUninstall; forward;

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
  InstallProgress.Caption := MaintenanceCaption;
  InstallProgress.Description := '只处理已确认的维护范围；业务数据与备份保持不变。';
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
  if IsUpgradeOperation then begin
    Schema := 'enterprise-install-maintenance-request-v7';
    if (Operation = 'upgrade-retained') or (Operation = 'recover-upgrade') then
      Confirmation := ',"confirm_no_active_tasks":true'
    else Confirmation := ',"confirm_no_active_tasks":false';
  end else if IsLifecycleOperation then begin
    Schema := 'enterprise-install-maintenance-request-v6';
    if Operation = 'inspect-lifecycle' then Confirmation := ',"confirm_no_active_tasks":false'
    else Confirmation := ',"confirm_no_active_tasks":true';
  end else if IsCacheOperation then begin
    Schema := 'enterprise-install-maintenance-request-v5';
    if CacheCleaning then Confirmation := ',"confirm_cache_cleanup":true'
    else Confirmation := ',"confirm_cache_cleanup":false';
    Confirmation := Confirmation + ',"cache_id":"' + SelectedCacheId + '","cache_token":"' + SelectedCacheToken + '"';
  end else if not ShouldMaintainEntry and (Operation <> 'inspect-entry') then begin
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
  if MaintenanceOperation <> 'install' then begin
    InstallProgress.Caption := MaintenanceCaption;
    InstallProgress.Description := '只处理已确认的维护范围；业务数据与备份保持不变。';
  end else begin
    InstallProgress.Caption := '正在安装';
    InstallProgress.Description := '安装未完成前不会发布 current-release 指针。';
  end;
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
  LifecycleState := '';
  UpgradeState := '';
  EntryState := '';
  MatchingLifecycleRelease := False;
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
  GraphicalPipeActive := not ShouldMaintainEntry or IsUpgradeOperation;
  DetachButton.Visible := GraphicalPipeActive and (MaintenanceOperation <> 'inspect-program') and (MaintenanceOperation <> 'inspect-entry') and not IsCacheOperation and not IsLifecycleOperation and not IsUpgradeOperation;
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
  MatchingLifecycleRelease := Result and (Pos('"release_id":"{#ReleaseId}"', Response) > 0);
  if Result and IsCacheOperation then begin
    CacheRows := Response;
    exit; { Cache-only requests never register an installation or maintain shortcuts. }
  end;
  if Result and (MaintenanceOperation = 'inspect-entry') then begin
    if Pos('"entry_state":"REGISTERED"', Response) > 0 then EntryState := 'REGISTERED'
    else if Pos('"entry_state":"REGISTRATION_REQUIRED"', Response) > 0 then begin
      EntryState := 'REGISTRATION_REQUIRED';
      Response := '';
      exit; { Read-only inspection must not manufacture an installation ID. }
    end else begin Result := False; LastStableCode := 'INSTALL_SETUP_BRIDGE_RESPONSE_INVALID'; end;
  end;
  if Result then begin
    InstallationId := ExtractInstallationId(Response);
    if InstallationId = '' then begin
      LastStableCode := 'INSTALL_IDENTITY_INVALID';
      Result := False;
    end;
    if IsUpgradeOperation then begin
      if Pos('"upgrade_state":"ELIGIBLE"', Response) > 0 then UpgradeState := 'ELIGIBLE'
      else if Pos('"upgrade_state":"AWAITING_REGISTRATION"', Response) > 0 then UpgradeState := 'AWAITING_REGISTRATION'
      else if Pos('"upgrade_state":"COMPLETE"', Response) > 0 then UpgradeState := 'COMPLETE'
      else if Pos('"upgrade_state":"ROLLED_BACK"', Response) > 0 then UpgradeState := 'ROLLED_BACK'
      else if Pos('"upgrade_state":"RECOVERY_REQUIRED"', Response) > 0 then UpgradeState := 'RECOVERY_REQUIRED'
      else begin Result := False; LastStableCode := 'INSTALL_SETUP_BRIDGE_RESPONSE_INVALID'; end;
    end else if IsLifecycleOperation then begin
      if Pos('"lifecycle_state":"UNINSTALLED"', Response) > 0 then LifecycleState := 'UNINSTALLED'
      else if Pos('"lifecycle_state":"INSTALLED"', Response) > 0 then LifecycleState := 'INSTALLED'
      else if Pos('"lifecycle_state":"UNINSTALLING"', Response) > 0 then LifecycleState := 'UNINSTALLING'
      else if Pos('"lifecycle_state":"REINSTALLING"', Response) > 0 then LifecycleState := 'REINSTALLING'
      else if Pos('"lifecycle_state":"NONE"', Response) > 0 then LifecycleState := 'NONE'
      else begin Result := False; LastStableCode := 'INSTALL_SETUP_BRIDGE_RESPONSE_INVALID'; end;
    end else if (MaintenanceOperation <> 'inspect-entry') and (not ShouldMaintainEntry or (MaintenanceOperation = 'recover-entry')) then begin
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

function TakePart(var Value: String; Separator: String): String;
var
  Position: Integer;
begin
  Position := Pos(Separator, Value);
  if Position = 0 then begin Result := Value; Value := ''; end
  else begin Result := Copy(Value, 1, Position - 1); Delete(Value, 1, Position); end;
end;

function HexValue(const Value: String; RequiredLength: Integer): Boolean;
var
  I: Integer;
begin
  Result := False;
  if Length(Value) <> RequiredLength then exit;
  for I := 1 to Length(Value) do if Pos(Value[I], HexDigits) = 0 then exit;
  Result := True;
end;

function GetLifecycleAppId(Param: String): String;
begin
  Result := '';
  if HexValue(InstallationId, 32) then Result := 'InfiniteCanvasEnterprise-' + InstallationId;
end;

function GetLifecycleInstance(Param: String): String;
begin
  if not HexValue(InstallationId, 32) then RaiseException('INSTALL_IDENTITY_INVALID');
  Result := InstallationId;
end;

function RegisterLifecycle: Boolean;
begin
  Result := LifecycleSupportReady and HexValue(InstallationId, 32) and
    ((MaintenanceOperation = 'install') or
     ((MaintenanceOperation = 'repair-entry') and MatchingLifecycleRelease) or
     ((MaintenanceOperation = 'reinstall-retained') and (LifecycleState = 'INSTALLED')) or
     (IsUpgradeOperation and ((UpgradeState = 'AWAITING_REGISTRATION') or (UpgradeState = 'COMPLETE'))));
end;

function ExtractCacheRows(const Response: String): String;
var
  StartAt, EndAt: Integer;
begin
  Result := '';
  StartAt := Pos('"cache_rows":"', Response);
  if StartAt = 0 then RaiseException('INSTALL_SETUP_BRIDGE_RESPONSE_INVALID');
  StartAt := StartAt + Length('"cache_rows":"');
  EndAt := StartAt;
  while (EndAt <= Length(Response)) and (Response[EndAt] <> '"') do begin
    if (Ord(Response[EndAt]) < 32) or (Ord(Response[EndAt]) > 126) or (Response[EndAt] = '\') then
      RaiseException('INSTALL_SETUP_BRIDGE_RESPONSE_INVALID');
    EndAt := EndAt + 1;
  end;
  if EndAt > Length(Response) then RaiseException('INSTALL_SETUP_BRIDGE_RESPONSE_INVALID');
  Result := Copy(Response, StartAt, EndAt - StartAt);
end;

procedure PreviewMaintenanceCache(Sender: TObject);
var
  Rows, Row, CacheId, Size, Token, State, Caption: String;
  I: Integer;
begin
  SelectedCacheId := '';
  SelectedCacheToken := '';
  CacheCleaning := False;
  CachePage.CheckListBox.Items.Clear;
  SetArrayLength(CacheIds, 0);
  SetArrayLength(CacheTokens, 0);
  SetArrayLength(CacheSizes, 0);
  InstallProgress.Show;
  try
    PrepareBundle;
    if not RunBridge then RaiseException(LastStableCode);
    Rows := ExtractCacheRows(CacheRows);
    while Rows <> '' do begin
      Row := TakePart(Rows, ';');
      CacheId := TakePart(Row, ',');
      Size := TakePart(Row, ',');
      Token := TakePart(Row, ',');
      State := TakePart(Row, ',');
      if (Row <> '') or not HexValue(CacheId, 32) or (StrToInt64(Size) < 0) or
         ((State = 'CLEANABLE') and not HexValue(Token, 64)) or
         ((State <> 'CLEANABLE') and ((Copy(State, 1, 14) <> 'INSTALL_CACHE_') or (Token <> ''))) then
        RaiseException('INSTALL_SETUP_BRIDGE_RESPONSE_INVALID');
      I := GetArrayLength(CacheIds);
      if I >= 64 then RaiseException('INSTALL_CACHE_LIMIT');
      SetArrayLength(CacheIds, I + 1); CacheIds[I] := CacheId;
      SetArrayLength(CacheTokens, I + 1); CacheTokens[I] := Token;
      SetArrayLength(CacheSizes, I + 1); CacheSizes[I] := Size;
      Caption := '保留 ' + State + '：' + CacheId;
      if State = 'CLEANABLE' then Caption := '可清理 ' + IntToStr(StrToInt64(Size) div 1048576) + ' MiB：' + CacheId;
      CachePage.Add(Caption);
    end;
    CachePage.SelectedValueIndex := -1;
  finally
    CacheRows := '';
    InstallProgress.Hide;
  end;
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

function MaintenanceFailureCaption: String;
begin
  Result := '状态或资格未通过核验；请保留诊断与恢复记录。';
  if LastStableCode = 'INSTALL_LIFECYCLE_IDENTITY_REQUIRED' then
    Result := '本安装尚无身份登记，页面升级到当前版本不会自动补齐。' + #13#10 +
      '请先选择“只修复固定入口与快捷方式”，完成后再检查离线升级资格。账号、数据库和当前业务版本不会因此重建。'
  else if LastStableCode = 'INSTALL_ENTRY_UNOWNED_FILE' then
    Result := '旧固定入口的归属未能核验。请保留原安装目录并导出诊断；未覆盖该入口或初始化业务数据。'
  else if LastStableCode = 'INSTALL_ENTRY_WRITE_DENIED' then
    Result := 'Windows 拒绝写入入口或登记文件，本次操作已回退。请确认服务已停止，并关闭本安装的固定 EXE 启动窗口后重试。' + #13#10 +
      '若仍失败，请保留诊断与恢复记录，继续核查文件占用或写入权限；不要手工覆盖入口或删除锁文件。'
  else if (LastStableCode = 'INSTALL_PROGRAM_RUNTIME_BUSY') or
          (LastStableCode = 'INSTALL_ENTRY_RUNTIME_BUSY') or
          (LastStableCode = 'INSTALL_LIFECYCLE_RUNTIME_BUSY') then
    Result := '请从本安装的固定入口点击“停止”，再用“查看状态”确认已停止，随后重新执行维护。' + #13#10 +
      '关闭窗口不会停止后台服务；若仍提示占用，请保留诊断与恢复记录，不要删除 Runtime 锁文件。'
  else if LastStableCode = 'INSTALL_PROGRAM_SAME_RELEASE_REQUIRED' then
    Result := '程序修复必须使用当前版本安装包。跨版本更新请选择“升级到本包版本／跨版本保留数据重装”。'
  else if LastStableCode = 'INSTALL_UPGRADE_TARGET_NOT_NEWER' then
    Result := '本包不是比当前版本更新的版本。同版本维护请使用对应的程序修复或保留数据重装选项。'
  else if LastStableCode = 'INSTALL_LIFECYCLE_DATABASE_RECOVERY_REQUIRED' then
    Result := '数据库日志尚不能证明可安全处理，本次未执行升级。这不等于已确认数据库损坏。' + #13#10 +
      '请保留数据库、WAL、SHM、journal 和维护记录并导出诊断；不要手工删除这些文件。'
  else if LastStableCode = 'INSTALL_UPGRADE_DATABASE_PREPARATION_REQUIRED' then
    Result := 'SQLite 未能完成受控日志预处理，维护阻断和恢复记录已保留。' + #13#10 +
      '请确认服务停止后选择“显式恢复本包上次中断的离线升级”；仍失败时保留诊断，不要删除锁或数据库日志。';
  Result := Result + #13#10 + '错误代码：' + LastStableCode;
end;

function InspectSelectedMaintenance(ShowResult: Boolean): Boolean;
var
  SelectedOperation: Integer;
begin
  Result := False;
  SelectedOperation := OperationPage.SelectedValueIndex;
  if SelectedOperation = 5 then begin
    MsgBox('请点击“下一步”查看维护准备包列表；刷新状态不会清理文件。', mbInformation, MB_OK);
    exit;
  end;
  case SelectedOperation of
    0, 4: InspectingEntry := True;
    6, 7, 8, 9: OperationPage.SelectedValueIndex := 9;
    10, 11, 12: OperationPage.SelectedValueIndex := 12;
  else OperationPage.SelectedValueIndex := 3;
  end;
  InstallProgress.Show;
  try
    PrepareBundle;
    Result := RunBridge;
    if not Result then MsgBox(MaintenanceFailureCaption, mbError, MB_OK)
    else if ShowResult then begin
      if InspectingEntry then begin
        if EntryState = 'REGISTRATION_REQUIRED' then
          MsgBox('当前 Release 与固定入口归属已核验，但尚无安装身份登记。' + #13#10 +
            '请继续完成所选固定入口修复；本次刷新没有写入登记或变更业务版本。', mbInformation, MB_OK)
        else MsgBox('当前 Release、固定入口与安装身份登记已核验。' + #13#10 +
          '本次刷新没有执行修复；执行维护前仍须停止服务。', mbInformation, MB_OK);
      end else if IsUpgradeOperation then
        MsgBox('本包核验的离线升级状态：' + UpgradeState + #13#10 + '未执行升级或恢复。', mbInformation, MB_OK)
      else if IsLifecycleOperation then
        MsgBox('已核验的卸载／重装状态：' + LifecycleState + #13#10 + '未执行恢复或初始化业务数据。', mbInformation, MB_OK)
      else MsgBox(RepairStateCaption, mbInformation, MB_OK);
    end;
  except
    Result := False;
    MsgBox('状态检查未完成；没有执行修复或恢复。' + #13#10 + GetExceptionMessage, mbError, MB_OK);
  finally
    InspectingEntry := False;
    OperationPage.SelectedValueIndex := SelectedOperation;
    InstallProgress.Hide;
  end;
end;

procedure InspectMaintenance(Sender: TObject);
begin
  InspectSelectedMaintenance(True);
end;

procedure InitializeWizard;
begin
  FindRegisteredInstall;
  WizardForm.WelcomeLabel1.Caption := '欢迎安装无限画布企业版';
  WizardForm.WelcomeLabel2.Caption := '版本 {#AppVersion}' + #13#10 + #13#10 +
    '安装包已包含独立 Python 运行环境，无需安装 Python。';

  ModePage := CreateInputOptionPage(wpWelcome, '选择安装或维护位置',
    '已有安装优先使用原位置', '已有数据不作为新安装重建；可选择入口修复、同版本维护、保留数据卸载重装或本包支持的离线升级。', True, False);
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
    '保留原账号、数据库、画布、素材、配置和安装身份',
    '同版本修复使用原包；离线升级只接受本包证明兼容的较新版本。服务须已停止，未知升级或数据库 Schema 会被阻断。', True, False);
  OperationPage.Add('只修复固定入口与快捷方式');
  OperationPage.Add('修复当前版本程序与 Python（不是业务升级）');
  OperationPage.Add('恢复上次中断的程序修复');
  OperationPage.Add('仅查看维护状态／跨窗口进度（不执行恢复）');
  OperationPage.Add('恢复上次中断的固定入口修复（仅核验本包可证明的事务）');
  OperationPage.Add('查看并明确选择清理已完成的维护准备包（不是业务数据）');
  OperationPage.Add('运行本安装的 Windows 标准卸载（默认保留业务数据）');
  OperationPage.Add('完成上次中断的保留数据卸载（需本包证明原事务）');
  OperationPage.Add('恢复保留数据安装／上次中断的重装（只接受同一 Release）');
  OperationPage.Add('仅检查卸载／重装状态（不执行恢复）');
  OperationPage.Add('升级到本包版本／跨版本保留数据重装（包含固定入口与维护安装器）');
  OperationPage.Add('显式恢复本包上次中断的离线升级／继续完成 Windows 登记');
  OperationPage.Add('仅检查本包离线升级资格或恢复状态（不执行升级）');
  OperationPage.SelectedValueIndex := 0;
  StatusButton := TNewButton.Create(WizardForm);
  StatusButton.Parent := OperationPage.Surface;
  StatusButton.Caption := '刷新维护状态';
  StatusButton.Width := ScaleX(125);
  StatusButton.Height := ScaleY(28);
  StatusButton.Top := OperationPage.SurfaceHeight - StatusButton.Height;
  StatusButton.OnClick := @InspectMaintenance;

  CachePage := CreateInputOptionPage(OperationPage.ID, '维护准备包安全清理',
    '不按时间或容量自动删除；只清理本次明确选择的一项',
    '未知旧包、当前安装器、活动进程及恢复依赖均保留。仅删除已核验的 ZIP、程序与 Python 准备副本；不删除安装版本、数据库、素材、配置或备份。中断后需刷新并再次确认。', True, False);
  CacheRefreshButton := TNewButton.Create(WizardForm);
  CacheRefreshButton.Parent := CachePage.Surface;
  CacheRefreshButton.Caption := '刷新准备包列表';
  CacheRefreshButton.Width := ScaleX(150);
  CacheRefreshButton.Height := ScaleY(28);
  CacheRefreshButton.Top := CachePage.SurfaceHeight - CacheRefreshButton.Height;
  CacheRefreshButton.OnClick := @PreviewMaintenanceCache;

  TaskConfirmationPage := CreateInputOptionPage(CachePage.ID, '确认安全维护',
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
  if HeadlessLifecycle then begin
    SelectedInstallRoot := HeadlessRoot;
    ExistingEntryRepair := True;
    ModePage.SelectedValueIndex := 1;
    TargetPage.Values[0] := HeadlessRoot;
    CredentialPage.Values[0] := ''; CredentialPage.Values[1] := ''; CredentialPage.Values[2] := '';
    TaskConfirmationPage.Values[0] := True;
    try
      PrepareBundle;
      if RunBridge and (LifecycleState = 'UNINSTALLED') then ExitProcess(0);
    except
      LastStableCode := 'INSTALL_UNINSTALL_BOOTSTRAP_FAILED';
    end;
    ExitProcess(1); { Bootstrap only: never install/register/create shortcuts. }
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ((PageID = TargetPage.ID) and (ModePage.SelectedValueIndex = 0) and not MultipleInstalls) or
    ((PageID = CredentialPage.ID) and ExistingEntryRepair) or
    ((PageID = OperationPage.ID) and not ExistingEntryRepair) or
    ((PageID = CachePage.ID) and not IsCacheOperation) or
    ((PageID = TaskConfirmationPage.ID) and ((ShouldMaintainEntry and not IsLifecycleOperation and not IsUpgradeOperation) or (MaintenanceOperation = 'inspect-program') or (MaintenanceOperation = 'inspect-lifecycle') or (MaintenanceOperation = 'inspect-upgrade') or IsCacheOperation)) or
    ((PageID = wpSelectTasks) and not ShouldMaintainEntry);
end;

procedure ShowMaintenanceScope;
begin
  if ExistingEntryRepair then
    EnvironmentPage.RichEditViewer.Text := '操作：只修复固定入口' + #13#10 +
      '原安装目录：' + SelectedInstallRoot + #13#10 + #13#10 +
      '已发现已有安装候选，执行时仍需完整核验其当前 Release。' + #13#10 +
      '只修复固定 EXE、实例登记和快捷方式。不会初始化或迁移数据库，不会改变当前版本。' + #13#10 +
      '下一页明确选择入口修复、同版本维护、保留数据卸载重装或本包支持的离线升级。'
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
  if IsUpgradeOperation then
    Result := '操作：' + MaintenanceCaption + NewLine +
      Space + '原安装目录：' + SelectedInstallRoot + NewLine +
      Space + '目标版本：{#AppVersion}；账号、数据库、画布、素材、配置和安装身份保持。' + NewLine +
      Space + '仅接受已证明兼容的相同 Schema；分别核验程序、固定入口、维护安装器和 Windows 登记。' + NewLine +
      Space + '如存在空 WAL／SHM 残留，将在停机与维护锁内由 SQLite 处理并复核；非空日志仍会阻断。' + NewLine +
      Space + '目标失败恢复来源版本；成功后完成登记才开放业务访问。'
  else if IsLifecycleOperation then
    Result := '操作：' + MaintenanceCaption + NewLine +
      Space + '原安装目录：' + SelectedInstallRoot + NewLine +
      Space + '保留原账号、数据库、画布、素材、配置、备份及安装身份。' + NewLine +
      Space + '只接受同一 Release；恢复已核验的原程序，不创建新账号或升级数据库。' + NewLine +
      Space + '卸载保留程序恢复副本；服务不会自动启动。'
  else if ExistingEntryRepair and not ShouldMaintainEntry then
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
  Index: Integer;
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
      WizardForm.DirEdit.Text := SelectedInstallRoot;
      CredentialPage.Values[0] := '';
      CredentialPage.Values[1] := '';
      CredentialPage.Values[2] := '';
      ShowMaintenanceScope;
    end;
    if Result then WizardForm.DirEdit.Text := SelectedInstallRoot;
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
  if (CurPageID = TaskConfirmationPage.ID) and Result and (MaintenanceOperation = 'uninstall-retain') then begin
    Result := False; { Use the actual Windows uninstaller, never a Setup install step. }
    try RunRegisteredUninstall;
    except MsgBox('Windows 卸载入口未通过核验；未删除程序或业务数据。' + #13#10 + GetExceptionMessage, mbError, MB_OK); end;
  end;
  if (CurPageID = OperationPage.ID) and (MaintenanceOperation = 'inspect-lifecycle') then begin
    Result := False;
    InspectSelectedMaintenance(True);
  end;
  if (CurPageID = OperationPage.ID) and (MaintenanceOperation = 'inspect-upgrade') then begin
    Result := False;
    InspectSelectedMaintenance(True);
  end;
  if (CurPageID = OperationPage.ID) and (MaintenanceOperation = 'upgrade-retained') then begin
    Result := InspectSelectedMaintenance(False);
  end;
  if (CurPageID = OperationPage.ID) and (MaintenanceOperation = 'inspect-program') then begin
    InspectMaintenance(nil);
    Result := False; { Inspection never reaches installation/shortcut/registry steps. }
  end;
  if (CurPageID = OperationPage.ID) and IsCacheOperation then begin
    try PreviewMaintenanceCache(nil);
    except
      MsgBox('列表核验未完成；未清理任何准备包。' + #13#10 + GetExceptionMessage, mbError, MB_OK);
      Result := False;
    end;
  end;
  if CurPageID = CachePage.ID then begin
    Result := False; { Never reach installation, registry, shortcuts, or auto-start. }
    Index := CachePage.SelectedValueIndex;
    if (Index < 0) or (Index >= GetArrayLength(CacheIds)) then begin
      MsgBox('请明确选择一个可清理准备包；无可清理项时可直接关闭安装器。', mbInformation, MB_OK);
      exit;
    end;
    if CacheTokens[Index] = '' then begin
      MsgBox('该项归属、占用或恢复状态未通过；不能清理。请保留原记录。', mbInformation, MB_OK);
      exit;
    end;
    if MsgBox('确定永久删除这个已核验的维护准备包？' + #13#10 + CacheIds[Index] + #13#10 +
      '大小：' + CacheSizes[Index] + ' 字节。仅此程序准备副本会删除，业务数据与备份不变。' + #13#10 +
      '当前安装器自身准备包继续保留，关闭后才可能成为可清理项。', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then exit;
    SelectedCacheId := CacheIds[Index];
    SelectedCacheToken := CacheTokens[Index];
    CacheCleaning := True;
    InstallProgress.Show;
    try
      if RunBridge then MsgBox('所选准备包已删除；业务数据、备份和安装版本未修改。', mbInformation, MB_OK)
      else MsgBox('清理未完成或预览已变化。已隔离的剩余材料保留；请刷新，需再次明确确认才继续。' + #13#10 + LastStableCode, mbError, MB_OK);
    finally
      CacheCleaning := False;
      SelectedCacheId := ''; SelectedCacheToken := ''; CacheRows := '';
      InstallProgress.Hide;
    end;
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

function SupportInfo(const Root: String): String;
begin
  Result := AddBackslash(Root) + 'state\windows-maintenance\support.ini';
end;

function CheckedMaintenanceSetup(const Root: String): String;
var
  Info, ExpectedId, ExpectedSha, Size: String;
  RecordBytes: AnsiString;
begin
  Info := SupportInfo(Root);
  if HasReparseAncestors(Root) or HasReparseAncestors(Info) or
     not FileExists(Info) then RaiseException('INSTALL_UNINSTALL_SUPPORT_UNPROVEN');
  ExpectedId := GetIniString('Lifecycle', 'InstallationId', '', Info);
  ExpectedSha := GetIniString('Lifecycle', 'SetupSha256', '', Info);
  Size := GetIniString('Lifecycle', 'SetupSize', '', Info);
  if not HexValue(ExpectedId, 32) or not HexValue(ExpectedSha, 64) or
     (GetIniString('Lifecycle', 'Product', '', Info) <> 'MEIS-DaCaiTou/Infinite-Canvas-Enterprise') or
     not LoadStringFromFile(AddBackslash(Root) + 'state\installation.json', RecordBytes) or
     (ExtractInstallationId(String(RecordBytes)) <> ExpectedId) then
    RaiseException('INSTALL_UNINSTALL_SUPPORT_UNPROVEN');
  Result := AddBackslash(Root) + 'state\windows-maintenance\maintenance-setup.exe';
  if HasReparseAncestors(Result) then RaiseException('INSTALL_UNINSTALL_SUPPORT_UNPROVEN');
  RequireEmbeddedFile(Result, ExpectedSha, StrToInt64(Size));
end;

procedure PrepareLifecycleSupport;
var
  Directory, Info, Target, Source, Digest: String;
  Size: Int64;
begin
  if not ((MaintenanceOperation = 'install') or
      ((MaintenanceOperation = 'repair-entry') and MatchingLifecycleRelease) or
      ((MaintenanceOperation = 'reinstall-retained') and (LifecycleState = 'INSTALLED')) or
      (IsUpgradeOperation and (UpgradeState = 'AWAITING_REGISTRATION'))) then exit;
  Directory := AddBackslash(SelectedInstallRoot) + 'state\windows-maintenance';
  Info := SupportInfo(SelectedInstallRoot);
  Target := AddBackslash(Directory) + 'maintenance-setup.exe';
  Source := ExpandConstant('{srcexe}');
  Digest := GetSHA256OfFile(Source);
  if HasReparseAncestors(Directory) or not FileSize64(Source, Size) or (Size <= 0) then
    RaiseException('INSTALL_UNINSTALL_SUPPORT_UNPROVEN');
  if FileExists(Info) then begin
    if CheckedMaintenanceSetup(SelectedInstallRoot) <> Target then RaiseException('INSTALL_UNINSTALL_SUPPORT_UNPROVEN');
    RequireEmbeddedFile(Target, Digest, Size);
  end else if FileExists(Target) then RequireEmbeddedFile(Target, Digest, Size);
  { Inno's FileCopy cannot copy Setup itself in PrepareToInstall. Mark only
    proven eligibility here; ssInstall publishes before Inno changes anything. }
  LifecycleSupportReady := True;
end;

procedure PublishLifecycleSupport;
var
  Directory, Info, Target, Source, Digest: String;
  Size: Int64;
begin
  if not ((MaintenanceOperation = 'install') or
      ((MaintenanceOperation = 'repair-entry') and MatchingLifecycleRelease) or
      ((MaintenanceOperation = 'reinstall-retained') and (LifecycleState = 'INSTALLED')) or
      (IsUpgradeOperation and (UpgradeState = 'AWAITING_REGISTRATION'))) then exit;
  Directory := AddBackslash(SelectedInstallRoot) + 'state\windows-maintenance';
  if HasReparseAncestors(Directory) then RaiseException('INSTALL_UNINSTALL_SUPPORT_UNPROVEN');
  Info := SupportInfo(SelectedInstallRoot);
  Target := AddBackslash(Directory) + 'maintenance-setup.exe';
  Source := ExpandConstant('{srcexe}');
  Digest := GetSHA256OfFile(Source);
  if not FileSize64(Source, Size) or (Size <= 0) then RaiseException('INSTALL_UNINSTALL_SUPPORT_UNPROVEN');
  if FileExists(Info) then begin
    if CheckedMaintenanceSetup(SelectedInstallRoot) <> Target then RaiseException('INSTALL_UNINSTALL_SUPPORT_UNPROVEN');
    RequireEmbeddedFile(Target, Digest, Size);
  end else begin
    if not ForceDirectories(Directory) then
      RaiseException('INSTALL_UNINSTALL_SUPPORT_PUBLICATION_FAILED');
    if not FileExists(Target) and not FileCopy(Source, Target, True) then
      RaiseException('INSTALL_UNINSTALL_SUPPORT_PUBLICATION_FAILED');
    RequireEmbeddedFile(Target, Digest, Size);
    if not SetIniString('Lifecycle', 'Product', 'MEIS-DaCaiTou/Infinite-Canvas-Enterprise', Info) or
       not SetIniString('Lifecycle', 'InstallationId', InstallationId, Info) or
       not SetIniString('Lifecycle', 'SetupSha256', Digest, Info) or
       not SetIniString('Lifecycle', 'SetupSize', IntToStr(Size), Info) then
      RaiseException('INSTALL_UNINSTALL_SUPPORT_PUBLICATION_FAILED');
  end;
  LifecycleSupportReady := True;
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  HeadlessOperation := ExpandConstant('{param:ICE_LIFECYCLE|}');
  HeadlessLifecycle := HeadlessOperation <> '';
  if HeadlessLifecycle then begin
    HeadlessRoot := ExpandConstant('{param:ICE_LIFECYCLE_ROOT|}');
    if ((HeadlessOperation <> 'uninstall-retain') and (HeadlessOperation <> 'recover-uninstall')) or
       (HeadlessRoot = '') or
       (ExpandConstant('{param:ICE_LIFECYCLE_CONFIRMED|}') <> '1') then begin
      Result := False;
    end;
  end;
end;

procedure RunRegisteredUninstall;
var
  Info, Name, Uninstaller, Hash: String;
  ExitCode: Integer;
begin
  CheckedMaintenanceSetup(SelectedInstallRoot);
  Info := SupportInfo(SelectedInstallRoot);
  Name := GetIniString('Lifecycle', 'Uninstaller', '', Info);
  Hash := GetIniString('Lifecycle', 'UninstallerSha256', '', Info);
  if (Length(Name) <> 12) or (Copy(Name, 1, 5) <> 'unins') or
     (Copy(Name, 9, 4) <> '.exe') or not HexValue(Hash, 64) or
     (Pos(Name[6], '0123456789') = 0) or (Pos(Name[7], '0123456789') = 0) or
     (Pos(Name[8], '0123456789') = 0) then RaiseException('INSTALL_UNINSTALL_SUPPORT_UNPROVEN');
  Uninstaller := AddBackslash(SelectedInstallRoot) + 'state\windows-uninstaller\' + Name;
  if HasReparseAncestors(Uninstaller) or (GetSHA256OfFile(Uninstaller) <> Hash) then
    RaiseException('INSTALL_UNINSTALL_SUPPORT_UNPROVEN');
  if not Exec(Uninstaller, '', SelectedInstallRoot, SW_SHOWNORMAL, ewNoWait, ExitCode) then
    RaiseException('INSTALL_UNINSTALL_LAUNCH_FAILED');
end;

function InitializeUninstall: Boolean;
begin
  Result := False;
  try
    CheckedMaintenanceSetup(ExpandConstant('{app}'));
    Result := True;
  except
    MsgBox('卸载支持身份未通过；没有删除程序或业务数据。请保留原位置，用同版本安装包检查。' + #13#10 + GetExceptionMessage, mbError, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Root, Helper, Parameters, Key, Operation, RegisteredRoot, RegisteredLauncher: String;
  ExitCode: Integer;
  StateBytes: AnsiString;
begin
  Root := ExpandConstant('{app}');
  if CurUninstallStep = usUninstall then begin
    if UninstallSilent then begin
      if ExpandConstant('{param:ICECONFIRM_NO_ACTIVE_TASKS|}') <> '1' then Abort;
    end else if MsgBox('确认没有未完成 AI 任务，且已从固定入口停止本安装服务？' + #13#10 +
      '卸载默认保留账号、数据库、画布、素材、配置、备份和恢复记录。程序会移入已核验恢复副本，未自动释放该副本空间；同版本重装可恢复。',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then Abort;
    try
      Helper := CheckedMaintenanceSetup(Root);
      Operation := 'uninstall-retain';
      if FileExists(AddBackslash(Root) + 'state\system-update-active.lock') then Operation := 'recover-uninstall';
      Parameters := '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ICE_LIFECYCLE=' + Operation +
        ' /ICE_LIFECYCLE_CONFIRMED=1 /ICE_LIFECYCLE_ROOT="' + Root + '"';
      if not Exec(Helper, Parameters, Root, SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) or
         not LoadStringFromFile(AddBackslash(Root) + 'state\retained-installation.json', StateBytes) or
         (Pos('"status":"UNINSTALLED"', String(StateBytes)) = 0) then
        RaiseException('INSTALL_UNINSTALL_RECOVERY_REQUIRED');
      Key := 'Software\Infinite-Canvas-Enterprise\Installations\' +
        GetIniString('Lifecycle', 'InstallationId', '', SupportInfo(Root));
      { This product locator contains only the two values written by Setup. }
      if RegValueExists(HKCU, Key, 'InstallLocation') then begin
        if RegQueryStringValue(HKCU, Key, 'InstallLocation', RegisteredRoot) and
           RegQueryStringValue(HKCU, Key, 'Launcher', RegisteredLauncher) and
           (CompareText(RegisteredRoot, Root) = 0) and
           (CompareText(RegisteredLauncher, AddBackslash(Root) + 'InfiniteCanvas.exe') = 0) then begin
          RegDeleteValue(HKCU, Key, 'InstallLocation');
          RegDeleteValue(HKCU, Key, 'Launcher');
          RegDeleteKeyIfEmpty(HKCU, Key);
        end;
      end;
    except
      MsgBox('卸载未完成，Windows 登记和剩余程序保留；业务数据未重建。请从同版本安装包检查或显式恢复。' + #13#10 + GetExceptionMessage, mbError, MB_OK);
      Abort; { Stop before Inno removes registration, shortcuts or its log. }
    end;
  end;
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
    if IsCacheOperation then RaiseException('INSTALL_CACHE_INSPECTION_ONLY');
    if MaintenanceOperation = 'uninstall-retain' then RaiseException('INSTALL_UNINSTALL_WINDOWS_ENTRY_REQUIRED');
    if (not ShouldMaintainEntry or IsLifecycleOperation or IsUpgradeOperation) and not TaskConfirmationPage.Values[0] then
      RaiseException('INSTALL_PROGRAM_TASK_CONFIRMATION_REQUIRED');
    PrepareBundle;
    if IsUpgradeOperation then SetStage('核验并执行保留数据升级／恢复', 3)
    else if not ShouldMaintainEntry then SetStage('核验并执行已确认的程序维护', 3)
    else if ExistingEntryRepair then SetStage('核验并修复固定入口（不修改业务数据）', 3)
    else SetStage('初始化企业数据库', 3);
    LastStableCode := 'INSTALL_SETUP_BRIDGE_FAILED';
    if not RunBridge then begin
      if LastStableCode = 'INSTALL_ENTRY_TARGET_PATH_TOO_LONG' then
        Result := '安装目录过深，请选择较短的本机路径；尚未初始化安装或业务数据。' + #13#10
      else if LastStableCode = 'INSTALL_PROGRAM_VIEW_DETACHED' then
        Result := '已关闭进度查看，后台作业可能仍在继续；关闭此安装包，重开后选择刷新维护状态。不要重复提交。' + #13#10
      else begin
        Result := '操作未完成；不会把原目录当作新安装重建。' + #13#10 + MaintenanceFailureCaption;
        exit;
      end;
      Result := Result +
        '错误代码：' + LastStableCode;
      exit;
    end;
    if IsUpgradeOperation then begin
      if UpgradeState = 'AWAITING_REGISTRATION' then begin
        PrepareLifecycleSupport;
        WizardForm.FinishedLabel.Caption := '程序、固定入口和维护安装器已升级；正在完成 Windows 登记，业务访问暂时暂停。原业务数据和安装身份保持。';
        SetStage('等待 Windows 登记与最终核验', 6);
        exit;
      end;
      if UpgradeState = 'ROLLED_BACK' then begin
        Result := '离线升级已恢复来源版本和原工具；业务数据未恢复旧备份。请检查原入口后再决定升级，不会登记目标版本。';
        exit;
      end;
      RaiseException('INSTALL_UPGRADE_RECOVERY_REQUIRED');
    end;
    if IsLifecycleOperation then begin
      if (MaintenanceOperation = 'reinstall-retained') and (LifecycleState = 'INSTALLED') then begin
        PrepareLifecycleSupport;
        WizardForm.FinishedLabel.Caption := '原账号、数据库、素材、配置和安装身份已保留；同版本程序与固定入口已恢复。服务未自动启动。';
        SetStage('保留数据重装完成', 6);
        exit;
      end;
      if (MaintenanceOperation = 'recover-uninstall') and (LifecycleState = 'UNINSTALLED') then begin
        Result := '保留数据卸载事务已完成；请再次运行原 Windows 卸载入口注销登记。也可在本包选择同版本恢复安装。';
        exit;
      end;
      RaiseException('INSTALL_LIFECYCLE_STATE_UNPROVEN');
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
    PrepareLifecycleSupport;
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
  Key, Info, Uninstaller: String;
begin
  if (CurStep = ssInstall) and RegisterLifecycle then begin
    try PublishLifecycleSupport;
    except
      LifecycleSupportReady := False;
      RaiseException('INSTALL_UNINSTALL_SUPPORT_PUBLICATION_FAILED');
    end;
  end;
  if (CurStep = ssPostInstall) and ShouldMaintainEntry and (InstallationId <> '') then begin
    Key := 'Software\Infinite-Canvas-Enterprise\Installations\' + InstallationId;
    if not RegWriteStringValue(HKCU, Key, 'InstallLocation', SelectedInstallRoot) or
       not RegWriteStringValue(HKCU, Key, 'Launcher', GetInstalledEntry('')) then
      MsgBox('固定入口已安装，但自动定位登记未完成。请从原安装根打开 InfiniteCanvas.exe；业务数据未重建。', mbInformation, MB_OK);
  end;
  if (CurStep = ssDone) and RegisterLifecycle then begin
    Info := SupportInfo(SelectedInstallRoot);
    Uninstaller := ExpandConstant('{uninstallexe}');
    if not SetIniString('Lifecycle', 'Uninstaller', ExtractFileName(Uninstaller), Info) or
       not SetIniString('Lifecycle', 'UninstallerSha256', GetSHA256OfFile(Uninstaller), Info) then
      MsgBox('安装已完成，但卸载入口登记未完成；请保留同版本安装包进行检查。业务数据未重建。', mbInformation, MB_OK);
    if IsUpgradeOperation then begin
      FinalizingUpgrade := True;
      try
        if RunBridge and (UpgradeState = 'COMPLETE') then
          WizardForm.FinishedLabel.Caption := '离线升级／跨版本保留数据重装已完成。程序、固定入口、维护安装器及 Windows 登记已核验；原账号、数据库、素材、配置和安装身份保留。'
        else begin
          WizardForm.FinishedLabel.Caption := '目标版本运行检查已通过，但 Windows 登记尚未完成，业务访问仍暂停。请重开本安装包并选择显式恢复；不会自动回退已成功运行的新版本。';
          MsgBox(WizardForm.FinishedLabel.Caption + #13#10 + LastStableCode, mbInformation, MB_OK);
        end;
      finally FinalizingUpgrade := False; end;
    end;
  end;
end;

procedure DeinitializeSetup;
begin
  { Never remove the external interpreter beneath a detached worker. Persistent
    payloads stay in this product's cache pending verified retention/cleanup. }
  if (BundleRoot <> '') and not PersistentBundle then
    DelTree(BundleRoot, True, True, True);
end;
