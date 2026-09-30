; Read-only harness compiling the exact production discovery include.
[Setup]
AppId={{92B751A6-D820-4715-B0C8-718ED7B7205A}
AppName=ICE discovery test harness
AppVersion=1.0
DefaultDirName={tmp}ICE-Discovery-Test
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
SetupArchitecture=x64
OutputDir={#OutputDir}
OutputBaseFilename=discovery-test
Compression=none
SetupLogging=yes
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes

[Code]
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
  while (EndAt <= Length(Text)) and (Text[EndAt] <> '"') do EndAt := EndAt + 1;
  if (EndAt > StartAt) and (EndAt <= Length(Text)) then
    Result := Copy(Text, StartAt, EndAt - StartAt);
end;

#include "..\..\..\installer\windows\096-install-discovery.issinc"

procedure InitializeWizard;
var
  RegistryKey, Code, Chosen: String;
  I: Integer;
begin
  DiscoveredInstallRoots := TStringList.Create;
  DiscoveredInstallRoots.CaseSensitive := False;
  InspectedInstallRoots := TStringList.Create;
  InspectedInstallRoots.CaseSensitive := False;
  DiscoveryIncomplete := False;
  AddInstallLocationHint(ExpandConstant('{param:ROOT1|}'));
  AddInstallLocationHint(ExpandConstant('{param:ROOT2|}'));
  AddNearbyInstallLocationHints(ExpandConstant('{param:NEARBY|}'));
  RegistryKey := ExpandConstant('{param:REGISTRYKEY|}');
  if RegistryKey <> '' then ReadRegisteredInstallLocations(HKCU, RegistryKey);
  ReadKnownShortcutLocation(ExpandConstant('{param:SHORTCUT|}'));
  if ExpandConstant('{param:INCOMPLETE|}') = '1' then DiscoveryIncomplete := True;
  Log('TEST_COUNT=' + IntToStr(DiscoveredInstallRoots.Count));
  for I := 0 to DiscoveredInstallRoots.Count - 1 do
    Log('TEST_ROOT=' + DiscoveredInstallRoots[I]);
  Chosen := DetectInstallRoot;
  Log('TEST_CHOSEN=' + Chosen);
  if not ValidateInstallRoot(Chosen, Code) then Log('TEST_VALIDATION=' + Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  { Always terminate before installation or any production bridge execution. }
  Result := 'TEST_READ_ONLY_COMPLETE';
end;
