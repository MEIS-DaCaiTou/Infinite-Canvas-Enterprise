[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceInstallRoot,
    [Parameter(Mandatory)][string]$CaseRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][ValidateSet('All','Pointer','ReleaseManifest','RuntimeManifest','Payload','PythonDll','OwnedStop','ForeignStop')][string]$Mode
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

function Invoke-Wrapper([string]$AppRoot,[string]$Name){$output=@(& $env:ComSpec /d /c ('"'+(Join-Path $AppRoot $Name)+'"') 2>&1);return [ordered]@{exit_code=$LASTEXITCODE;output=$output}}
function Flip-FirstByte([string]$Path){$stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);try{$stream.Position=0;$value=$stream.ReadByte();$stream.Position=0;$stream.WriteByte(($value -bxor 0x01));$stream.Flush($true)}finally{$stream.Dispose()}}
function New-CaseCopy([string]$Label){$root=Join-Path $CaseRoot $Label;if(Test-Path -LiteralPath $root){throw [InvalidOperationException]::new('ENV1B3_TAMPER_CASE_EXISTS|case')};Copy-Item -LiteralPath $SourceInstallRoot -Destination $root -Recurse;return $root}
function Get-AppRoot([string]$Install){$pointer=Get-Content -Raw -LiteralPath (Join-Path $Install 'state\current-release.json')|ConvertFrom-Json;return Join-Path $Install ([string]$pointer.app_root_relative).Replace('/',[IO.Path]::DirectorySeparatorChar)}

try {
    [void](Assert-ENV1B3AbsoluteSafePath $SourceInstallRoot);[void](Assert-ENV1B3AbsoluteSafePath $CaseRoot -AllowMissingLeaf)
    [IO.Directory]::CreateDirectory($CaseRoot)|Out-Null
    if($Mode -eq 'OwnedStop'){
        $install=New-CaseCopy 'owned-stop';$app=Get-AppRoot $install
        $start=Invoke-Wrapper $app '启动企业版.bat';if($start.exit_code -ne 0){throw [InvalidOperationException]::new('ENV1B3_OWNED_START_FAILED|start')}
        Flip-FirstByte (Join-Path $app 'release-manifest.json')
        $stop=Invoke-Wrapper $app '停止企业版.bat';$pass=$stop.exit_code -eq 0
        Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W09' -Result ($(if($pass){'PASS'}else{'FAIL'})) -Code ($(if($pass){'ENV1B3_OWNED_RETAINED_STOP_PASS'}else{'ENV1B3_OWNED_RETAINED_STOP_FAILED'})) -Evidence @{owned_start_exit=$start.exit_code;owned_stop_after_manifest_tamper_exit=$stop.exit_code}|ConvertTo-Json -Compress
        if(-not $pass){exit 2};exit 0
    }
    if($Mode -eq 'ForeignStop'){
        $install=New-CaseCopy 'foreign-stop';$app=Get-AppRoot $install
        $start=Invoke-Wrapper $app '启动企业版.bat';if($start.exit_code -ne 0){throw [InvalidOperationException]::new('ENV1B3_FOREIGN_START_FAILED|start')}
        $runtimeRoot=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'InfiniteCanvasEnterprise\runtime'
        $lockPath=Join-Path $runtimeRoot 'runtime-supervisor.lock';$original=[IO.File]::ReadAllBytes($lockPath);$lock=Get-Content -Raw -LiteralPath $lockPath|ConvertFrom-Json;$lock.instance_id=[Guid]::NewGuid().ToString()
        [IO.File]::WriteAllText($lockPath,($lock|ConvertTo-Json -Depth 10 -Compress)+"`n",[Text.UTF8Encoding]::new($false))
        $foreignStop=Invoke-Wrapper $app '停止企业版.bat';$supervisorAlive=$false;try{$supervisorAlive=$null -ne (Get-Process -Id ([int]$lock.supervisor_pid) -ErrorAction Stop)}catch{}
        [IO.File]::WriteAllBytes($lockPath,$original);$cleanup=Invoke-Wrapper $app '停止企业版.bat'
        $pass=$foreignStop.exit_code -eq 2 -and $supervisorAlive -and $cleanup.exit_code -eq 0
        Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W09' -Result ($(if($pass){'PASS'}else{'FAIL'})) -Code ($(if($pass){'ENV1B3_FOREIGN_STOP_REJECTED'}else{'ENV1B3_FOREIGN_STOP_REJECTION_FAILED'})) -Evidence @{foreign_stop_exit=$foreignStop.exit_code;supervisor_survived=$supervisorAlive;owned_cleanup_stop_exit=$cleanup.exit_code}|ConvertTo-Json -Compress
        if(-not $pass){exit 2};exit 0
    }
    $targets=$(if($Mode -eq 'All'){@('Pointer','ReleaseManifest','RuntimeManifest','Payload','PythonDll')}else{@($Mode)})
    $results=@()
    foreach($targetName in $targets){
        $install=New-CaseCopy ('tamper-'+$targetName.ToLowerInvariant());$app=Get-AppRoot $install
        switch($targetName){'Pointer'{$target=Join-Path $install 'state\current-release.json'}'ReleaseManifest'{$target=Join-Path $app 'release-manifest.json'}'RuntimeManifest'{$target=Join-Path $app 'runtime-manifest.json'}'Payload'{$target=Join-Path $app 'VERSION'}'PythonDll'{$target=Join-Path $app 'python\python314.dll'}}
        Flip-FirstByte $target
        $start=Invoke-Wrapper $app '启动企业版.bat'
        $processes=@(Get-CimInstance Win32_Process|Where-Object{$_.CommandLine -and $_.CommandLine.IndexOf($app,[StringComparison]::OrdinalIgnoreCase) -ge 0})
        $passed=$start.exit_code -eq 2 -and $processes.Count -eq 0
        $results+=[ordered]@{target=$targetName;start_exit=$start.exit_code;candidate_process_count=$processes.Count;passed=$passed}
    }
    $allPass=@($results|Where-Object{-not $_.passed}).Count -eq 0
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W08' -Result ($(if($allPass){'PASS'}else{'FAIL'})) -Code ($(if($allPass){'ENV1B3_TAMPER_FAIL_CLOSED_PASS'}else{'ENV1B3_TAMPER_FAIL_CLOSED_FAILED'})) -Evidence @{targets=$results;case_root_symbol='<TEST_ROOT>/tamper-copies'}|ConvertTo-Json -Depth 8 -Compress
    if(-not $allPass){exit 2}
} catch {
    $caseId=$(if($Mode -in @('OwnedStop','ForeignStop')){'W09'}else{'W08'});$code='ENV1B3_TAMPER_MATRIX_FAILED';if($_.Exception.Message -match '^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    try{if($app){[void](Invoke-Wrapper $app '停止企业版.bat')}}catch{}
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $caseId -Result 'FAIL' -Code $code -Evidence @{}|ConvertTo-Json -Compress;exit 2
}
