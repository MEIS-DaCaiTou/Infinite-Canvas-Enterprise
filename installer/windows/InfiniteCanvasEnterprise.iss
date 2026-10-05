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
Name: "{autoprograms}\无限画布企业版"; Filename: "{code:GetInstalledEntry}"; WorkingDir: "{code:GetInstallRoot}"
Name: "{autodesktop}\无限画布企业版"; Filename: "{code:GetInstalledEntry}"; WorkingDir: "{code:GetInstallRoot}"; Tasks: desktopicon

[Run]
Filename: "{code:GetInstalledEntry}"; Description: "打开无限画布企业版启动窗口"; Flags: postinstall nowait skipifsilent; Tasks: launchafter

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
  CredentialPage: TInputQueryWizardPage;
  InstallProgress: TOutputProgressWizardPage;
  SelectedInstallRoot: String;
  BundleRoot: String;
  LastStableCode: String;
  DefaultInstallRoot: String;
  ExistingEntryRepair: Boolean;
  MultipleInstalls: Boolean;
  InstallationId: String;

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
  Mode, Target, Operation: String;
begin
  Operation := 'install';
  if ExistingEntryRepair then Operation := 'repair-entry';
  if (ModePage.SelectedValueIndex = 0) and not ExistingEntryRepair and not MultipleInstalls then begin
    Mode := 'quick';
    Target := 'null';
  end else begin
    Mode := 'custom';
    Target := '"' + JsonEscape(SelectedInstallRoot) + '"';
  end;
  Result := '{"operation":"' + Operation + '","install_mode":"' + Mode + '","install_root":' + Target +
    ',"password":"' + JsonEscape(CredentialPage.Values[1]) +
    '","password_confirmation":"' + JsonEscape(CredentialPage.Values[2]) +
    '","schema_version":"enterprise-install-maintenance-request-v2","username":"' +
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
  Received: Integer;
  Chunk: AnsiString;
begin
  Result := False;
  Data := '';
  while Length(Data) < Count do begin
    SetLength(Chunk, Count - Length(Data));
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
    if not ReadExact(Stream, 8, Header) then exit;
    ResponseLength := StrToIntDef('$' + String(Header), -1);
    LastStableCode := 'INSTALL_SETUP_BRIDGE_RESPONSE_INVALID';
    if (ResponseLength < 1) or (ResponseLength > MaxFrameBytes) then exit;
    LastStableCode := 'INSTALL_SETUP_BRIDGE_READ_FAILED';
    if not ReadExact(Stream, ResponseLength, ResponseBytes) then exit;
    Response := UTF8Text(ResponseBytes);
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
  InstallProgress.SetText(Caption, '请勿关闭安装程序。');
  InstallProgress.SetProgress(Position, 6);
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
  if not PipeExchange(PipeSuffix, Request, Response) then begin
    Request := '';
    exit;
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
  end;
  Response := '';
end;

procedure InitializeWizard;
begin
  FindRegisteredInstall;
  WizardForm.WelcomeLabel1.Caption := '欢迎安装无限画布企业版';
  WizardForm.WelcomeLabel2.Caption := '版本 {#AppVersion}' + #13#10 + #13#10 +
    '安装包已包含独立 Python 运行环境，无需安装 Python。';

  ModePage := CreateInputOptionPage(wpWelcome, '选择安装或入口修复',
    '已有安装优先使用原位置', '已有安装仅修复固定入口，不重置账号、数据库、配置或当前版本。业务升级仍由更新中心执行。', True, False);
  ModePage.Add('快速安装（推荐）');
  ModePage.Add('自定义安装');
  ModePage.SelectedValueIndex := 0;
  if MultipleInstalls then ModePage.SelectedValueIndex := 1;

  TargetPage := CreateInputDirPage(ModePage.ID, '选择安装位置',
    '选择全新目录，或要修复入口的已有安装。',
    '多个安装须明确选择；仅有目录/登记不代表已通过身份核验。其他项目、未知目录及损坏程序不会被覆盖。', False, '');
  TargetPage.Add(DefaultInstallRoot);
  TargetPage.Values[0] := DefaultInstallRoot;

  EnvironmentPage := CreateOutputMsgMemoPage(TargetPage.ID, '环境检查',
    '安装器将在继续前执行以下检查：', '',
    'Windows x64' + #13#10 +
    '当前用户安装（不请求管理员权限）' + #13#10 +
    '本机固定磁盘与可用空间' + #13#10 +
    '新装目录安全，或已有安装完整 Release 身份' + #13#10 +
    '内嵌 Release 身份和三个核心资产');

  CredentialPage := CreateInputQueryPage(EnvironmentPage.ID, '创建首个管理员',
    '创建唯一的首个 super_admin', '凭据只通过当前用户的一次性内存管道传递，不写入命令行、环境或文件。');
  CredentialPage.Add('管理员用户名：', False);
  CredentialPage.Add('密码：', True);
  CredentialPage.Add('确认密码：', True);

  InstallProgress := CreateOutputProgressPage('正在安装', '安装未完成前不会发布 current-release 指针。');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ((PageID = TargetPage.ID) and (ModePage.SelectedValueIndex = 0) and not MultipleInstalls) or
    ((PageID = CredentialPage.ID) and ExistingEntryRepair);
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
      EnvironmentPage.RichEditViewer.Text := '已发现原安装。将完整校验其当前程序并只修复固定 EXE、实例登记和快捷方式。不会初始化或迁移数据库，不会改变当前版本。若校验失败则停止；业务更新请在管理后台执行。';
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
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  MetadataPath, ArchivePath, ManifestPath, InventoryPath, RawDir, ExceptionCode: String;
begin
  Result := '';
  LastStableCode := 'INSTALL_SETUP_FAILED';
  BundleRoot := ExpandConstant('{tmp}\install-ux-bundle');
  InstallProgress.Show;
  try
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

    if ExistingEntryRepair then SetStage('核验并修复固定入口（不修改业务数据）', 3)
    else SetStage('初始化企业数据库', 3);
    LastStableCode := 'INSTALL_SETUP_BRIDGE_FAILED';
    if not RunBridge then begin
      if LastStableCode = 'INSTALL_ENTRY_TARGET_PATH_TOO_LONG' then
        Result := '安装目录过深，请选择较短的本机路径；尚未初始化安装或业务数据。' + #13#10
      else Result := '操作未完成；不会把原目录当作新安装重建。请保留诊断与恢复记录。' + #13#10;
      Result := Result +
        '错误代码：' + LastStableCode;
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
  if (CurStep = ssPostInstall) and (InstallationId <> '') then begin
    Key := 'Software\Infinite-Canvas-Enterprise\Installations\' + InstallationId;
    if not RegWriteStringValue(HKCU, Key, 'InstallLocation', SelectedInstallRoot) or
       not RegWriteStringValue(HKCU, Key, 'Launcher', GetInstalledEntry('')) then
      MsgBox('固定入口已安装，但自动定位登记未完成。请从原安装根打开 InfiniteCanvas.exe；业务数据未重建。', mbInformation, MB_OK);
  end;
end;

procedure DeinitializeSetup;
begin
  if BundleRoot <> '' then
    DelTree(BundleRoot, True, True, True);
end;
