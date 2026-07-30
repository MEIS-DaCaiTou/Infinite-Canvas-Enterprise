[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceInstallRoot,
    [Parameter(Mandatory)][string]$CaseRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][ValidateSet('All','Pointer','ReleaseManifest','RuntimeManifest','Payload','PythonDll','OwnedStop','ForeignStop','CombinedW09')][string]$Mode,
    [string]$ContractPath
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

function Get-WrapperName([string]$Command) {
    switch ($Command) {
        'start'   { return (-join @([char]0x542F,[char]0x52A8,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat' }
        'status'  { return (-join @([char]0x67E5,[char]0x770B,[char]0x4F01,[char]0x4E1A,[char]0x7248,[char]0x72B6,[char]0x6001))+'.bat' }
        'health'  { return (-join @([char]0x4F01,[char]0x4E1A,[char]0x7248,[char]0x5065,[char]0x5EB7,[char]0x68C0,[char]0x67E5))+'.bat' }
        'restart' { return (-join @([char]0x91CD,[char]0x542F,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat' }
        'stop'    { return (-join @([char]0x505C,[char]0x6B62,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat' }
    }
    throw [InvalidOperationException]::new('ENV1B3_WRAPPER_MISSING|wrapper')
}

function Invoke-Wrapper([string]$AppRoot,[string]$Command) {
    $wrapper = Join-Path $AppRoot (Get-WrapperName $Command)
    if (-not (Test-Path -LiteralPath $wrapper -PathType Leaf)) { throw [InvalidOperationException]::new('ENV1B3_WRAPPER_MISSING|wrapper') }
    $startInfo=[Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName=$env:ComSpec
    $startInfo.Arguments='/d /s /c ""'+$wrapper+'""'
    $startInfo.WorkingDirectory=[IO.Path]::GetPathRoot($AppRoot)
    $startInfo.UseShellExecute=$false
    $startInfo.CreateNoWindow=$true
    $startInfo.RedirectStandardOutput=$true
    $startInfo.RedirectStandardError=$true
    $process=[Diagnostics.Process]::new();$process.StartInfo=$startInfo
    try {
        if(-not $process.Start()){throw [InvalidOperationException]::new('ENV1B3_TAMPER_COMMAND_FAILED|process')}
        $stdout=$process.StandardOutput.ReadToEnd();$stderr=$process.StandardError.ReadToEnd();$process.WaitForExit()
        $exitCode=[int]$process.ExitCode
    } finally { $process.Dispose() }
    $text=$stdout+"`n"+$stderr;if($text.Length -gt 65536){$text=$text.Substring($text.Length-65536)}
    $payload=$null
    foreach($line in $text.Split("`n")){try{$candidate=$line.TrimEnd("`r")|ConvertFrom-Json;if($null-ne$candidate){$payload=$candidate}}catch{}}
    return [ordered]@{exit_code=$exitCode;payload=$payload;output_tail=$text}
}

function Flip-FirstByte([string]$Path) {
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try{$stream.Position=0;$value=$stream.ReadByte();$stream.Position=0;$stream.WriteByte(($value -bxor 0x01));$stream.Flush($true)}finally{$stream.Dispose()}
}
function New-CaseCopy([string]$Label) {
    $root=Join-Path $CaseRoot $Label
    if(Test-Path -LiteralPath $root){throw [InvalidOperationException]::new('ENV1B3_TAMPER_CASE_EXISTS|case')}
    Copy-Item -LiteralPath $SourceInstallRoot -Destination $root -Recurse
    return $root
}
function Get-AppRoot([string]$Install) {
    $pointer=Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Install 'state\current-release.json')|ConvertFrom-Json
    return Join-Path $Install ([string]$pointer.app_root_relative).Replace('/',[IO.Path]::DirectorySeparatorChar)
}
function Get-CandidatePids([string]$AppRoot) {
    return @((Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {$_.CommandLine -and $_.CommandLine.IndexOf($AppRoot,[StringComparison]::OrdinalIgnoreCase)-ge 0}).ProcessId | Sort-Object)
}
function Test-PidAlive([int]$ProcessId) { try { return $null -ne (Get-Process -Id $ProcessId -ErrorAction Stop) } catch { return $false } }
function Start-ForeignSentinel {
    $startInfo=[Diagnostics.ProcessStartInfo]::new();$startInfo.FileName=$env:ComSpec;$startInfo.Arguments='/d /c ping.exe -t 127.0.0.1';$startInfo.UseShellExecute=$false;$startInfo.CreateNoWindow=$true
    $process=[Diagnostics.Process]::new();$process.StartInfo=$startInfo;if(-not$process.Start()){throw [InvalidOperationException]::new('ENV1B3_FOREIGN_SENTINEL_FAILED|process')};return $process
}

try {
    [void](Assert-ENV1B3AbsoluteSafePath $SourceInstallRoot);[void](Assert-ENV1B3AbsoluteSafePath $CaseRoot -AllowMissingLeaf)
    [IO.Directory]::CreateDirectory($CaseRoot)|Out-Null

    if($Mode -eq 'CombinedW09' -or $Mode -eq 'OwnedStop'){
        $install=New-CaseCopy 'owned-stop';$app=Get-AppRoot $install
        $start=Invoke-Wrapper $app 'start';if($start.exit_code-ne0){throw [InvalidOperationException]::new('ENV1B3_OWNED_START_FAILED|start')}
        Flip-FirstByte (Join-Path $app 'release-manifest.json')
        $stop=Invoke-Wrapper $app 'stop';$ownedPass=$stop.exit_code-eq0
        if($Mode -eq 'CombinedW09'){
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W09 -SubcheckId owned_stop_after_tamper -Result $(if($ownedPass){'PASS'}else{'FAIL'}) -Code $(if($ownedPass){'ENV1B3_OWNED_RETAINED_STOP_PASS'}else{'ENV1B3_OWNED_RETAINED_STOP_FAILED'}) -Evidence @{owned_start_exit=$start.exit_code;owned_stop_exit=$stop.exit_code}|Out-Null
        }else{
            Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W09 -Result $(if($ownedPass){'PASS'}else{'FAIL'}) -Code $(if($ownedPass){'ENV1B3_OWNED_RETAINED_STOP_PASS'}else{'ENV1B3_OWNED_RETAINED_STOP_FAILED'}) -Evidence @{owned_start_exit=$start.exit_code;owned_stop_exit=$stop.exit_code}|ConvertTo-Json -Compress
            if(-not$ownedPass){exit 2};exit 0
        }
        if(-not$ownedPass){throw [InvalidOperationException]::new('ENV1B3_OWNED_RETAINED_STOP_FAILED|stop')}
    }

    if($Mode -eq 'CombinedW09' -or $Mode -eq 'ForeignStop'){
        $install=New-CaseCopy 'foreign-stop';$app=Get-AppRoot $install
        $start=Invoke-Wrapper $app 'start';if($start.exit_code-ne0){throw [InvalidOperationException]::new('ENV1B3_FOREIGN_START_FAILED|start')}
        $runtimeRoot=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'InfiniteCanvasEnterprise\runtime'
        $lockPath=Join-Path $runtimeRoot 'runtime-supervisor.lock';$original=[IO.File]::ReadAllBytes($lockPath)
        $lock=Get-Content -Raw -Encoding UTF8 -LiteralPath $lockPath|ConvertFrom-Json;$ownedSupervisorPid=[int]$lock.supervisor_pid;$lock.supervisor_instance_id=[Guid]::NewGuid().ToString('N')
        [IO.File]::WriteAllText($lockPath,($lock|ConvertTo-Json -Depth 10 -Compress)+"`n",[Text.UTF8Encoding]::new($false))
        $foreignStop=Invoke-Wrapper $app 'stop';$supervisorAlive=Test-PidAlive $ownedSupervisorPid
        [IO.File]::WriteAllBytes($lockPath,$original);$cleanup=Invoke-Wrapper $app 'stop'
        $cleanupAck=$cleanup.payload.ack
        $portsReleased=$null-ne$cleanupAck-and$cleanupAck.upstream_port_release-eq'released'-and$cleanupAck.gateway_port_release-eq'released'
        $foreignRejected=$foreignStop.exit_code-eq2
        $cleanupSucceeded=$cleanup.exit_code-eq0-and$portsReleased
        if($Mode -eq 'CombinedW09'){
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W09 -SubcheckId foreign_stop_rejected -Result $(if($foreignRejected){'PASS'}else{'FAIL'}) -Code $(if($foreignRejected){'ENV1B3_FOREIGN_STOP_REJECTED'}else{'ENV1B3_FOREIGN_STOP_REJECTION_FAILED'}) -Evidence @{foreign_stop_exit=$foreignStop.exit_code}|Out-Null
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W09 -SubcheckId foreign_process_survived -Result $(if($supervisorAlive){'PASS'}else{'FAIL'}) -Code $(if($supervisorAlive){'ENV1B3_FOREIGN_PROCESS_SURVIVED'}else{'ENV1B3_FOREIGN_PROCESS_TERMINATED'}) -Evidence @{supervisor_survived=$supervisorAlive}|Out-Null
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W09 -SubcheckId owned_cleanup_succeeded -Result $(if($cleanupSucceeded){'PASS'}else{'FAIL'}) -Code $(if($cleanupSucceeded){'ENV1B3_OWNED_CLEANUP_PASS'}else{'ENV1B3_OWNED_CLEANUP_FAILED'}) -Evidence @{owned_cleanup_stop_exit=$cleanup.exit_code;ports_released=$portsReleased}|Out-Null
            $aggregate=Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W09 -ContractPath $ContractPath
            $aggregate|ConvertTo-Json -Depth 8 -Compress
            if($aggregate.result-ne'PASS'){exit 2};exit 0
        }else{
            $pass=$foreignRejected-and$supervisorAlive-and$cleanupSucceeded
            Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W09 -Result $(if($pass){'PASS'}else{'FAIL'}) -Code $(if($pass){'ENV1B3_FOREIGN_STOP_REJECTED'}else{'ENV1B3_FOREIGN_STOP_REJECTION_FAILED'}) -Evidence @{foreign_stop_exit=$foreignStop.exit_code;supervisor_survived=$supervisorAlive;owned_cleanup_stop_exit=$cleanup.exit_code}|ConvertTo-Json -Compress
            if(-not$pass){exit 2};exit 0
        }
    }

    $targets=$(if($Mode-eq'All'){@('Pointer','ReleaseManifest','RuntimeManifest','Payload','PythonDll')}else{@($Mode)})
    $subcheckNames=@{Pointer='current_release';ReleaseManifest='release_manifest';RuntimeManifest='runtime_manifest';Payload='payload';PythonDll='python314_dll'}
    $results=@()
    foreach($targetName in $targets){
        $install=New-CaseCopy ('tamper-'+$targetName.ToLowerInvariant());$app=Get-AppRoot $install
        $startHealthy=Invoke-Wrapper $app 'start';if($startHealthy.exit_code-ne0){throw [InvalidOperationException]::new('ENV1B3_TAMPER_SETUP_FAILED|start')}
        $beforePids=@(Get-CandidatePids $app)
        $foreign=Start-ForeignSentinel
        try{
            switch($targetName){'Pointer'{$target=Join-Path $install 'state\current-release.json'}'ReleaseManifest'{$target=Join-Path $app 'release-manifest.json'}'RuntimeManifest'{$target=Join-Path $app 'runtime-manifest.json'}'Payload'{$target=Join-Path $app 'VERSION'}'PythonDll'{$target=Join-Path $app 'python\python314.dll'}}
            Flip-FirstByte $target
            $start=Invoke-Wrapper $app 'start';$restart=Invoke-Wrapper $app 'restart';$health=Invoke-Wrapper $app 'health';$status=Invoke-Wrapper $app 'status'
            $afterPids=@(Get-CandidatePids $app)
            $noNewProcesses=(Compare-Object $beforePids $afterPids).Count-eq0
            $stop=Invoke-Wrapper $app 'stop';$foreignSurvived=Test-PidAlive $foreign.Id
            $passed=$start.exit_code-eq2-and$restart.exit_code-eq2-and$health.exit_code-eq2-and$status.exit_code-eq0-and$noNewProcesses-and$stop.exit_code-eq0-and$foreignSurvived
            $evidence=@{target=$targetName;start_failed_closed=($start.exit_code-eq2);restart_failed_closed=($restart.exit_code-eq2);health_failed_closed=($health.exit_code-eq2);status_diagnostic=($status.exit_code-eq0);no_new_candidate_process=$noNewProcesses;owned_stop_succeeded=($stop.exit_code-eq0);foreign_process_survived=$foreignSurvived}
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W08 -SubcheckId $subcheckNames[$targetName] -Result $(if($passed){'PASS'}else{'FAIL'}) -Code $(if($passed){'ENV1B3_TAMPER_TARGET_PASS'}else{'ENV1B3_TAMPER_FAIL_CLOSED_FAILED'}) -Evidence $evidence|Out-Null
            $results+=$evidence
        }finally{if(Test-PidAlive $foreign.Id){$foreign.Kill()};$foreign.Dispose()}
    }
    $aggregate=Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W08 -ContractPath $ContractPath
    $aggregate|ConvertTo-Json -Depth 10 -Compress
    if($aggregate.result-ne'PASS'){exit 2}
} catch {
    $caseId=$(if($Mode-in@('OwnedStop','ForeignStop','CombinedW09')){'W09'}else{'W08'})
    $code='ENV1B3_TAMPER_MATRIX_FAILED';if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    try{if($app){[void](Invoke-Wrapper $app 'stop')}}catch{}
    if(-not(Test-Path -LiteralPath (Join-Path $EvidenceRoot ($caseId+'.json')))){
        Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $caseId -Result FAIL -Code $code -Evidence @{}|ConvertTo-Json -Compress
    }
    exit 2
}
