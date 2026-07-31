[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceInstallRoot,
    [Parameter(Mandatory)][string]$CaseRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][ValidateSet('All','Pointer','ReleaseManifest','RuntimeManifest','Payload','PythonDll','OwnedStop','ForeignStop','CombinedW09')][string]$Mode,
    [string]$ContractPath,
    [ValidateRange(5,300)][int]$WrapperTimeoutSeconds = 90
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
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

function ConvertFrom-BoundedJsonLine([string]$Text) {
    $payload = $null
    foreach ($line in @($Text.Split("`n"))) {
        try {
            $candidate = $line.TrimEnd("`r") | ConvertFrom-Json
            if ($null -ne $candidate) { $payload = $candidate }
        } catch { }
    }
    return $payload
}

function Invoke-Wrapper([string]$AppRoot, [string]$Command) {
    $wrapper = Join-Path $AppRoot (Get-WrapperName $Command)
    if (-not (Test-Path -LiteralPath $wrapper -PathType Leaf)) {
        throw [InvalidOperationException]::new('ENV1B3_WRAPPER_MISSING|wrapper')
    }
    $result = Invoke-ENV1B3ManagedProcess -FileName $env:ComSpec -Arguments ('/d /s /c ""' + $wrapper + '""') -WorkingDirectory ([IO.Path]::GetPathRoot($AppRoot)) -TimeoutSeconds $WrapperTimeoutSeconds
    $text = [string]$result.stdout + "`n" + [string]$result.stderr
    return [ordered]@{
        exit_code=[int]$result.exit_code
        timed_out=[bool]$result.timed_out
        process_id=[int]$result.process_id
        payload=(ConvertFrom-BoundedJsonLine $text)
        output_tail=$text
    }
}

function Flip-FirstByte([string]$Path) {
    $stream = [IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try {
        $stream.Position = 0
        $value = $stream.ReadByte()
        if ($value -lt 0) { throw [InvalidOperationException]::new('ENV1B3_TAMPER_TARGET_EMPTY|target') }
        $stream.Position = 0
        $stream.WriteByte(($value -bxor 0x01))
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
}

function New-CaseCopy([string]$Label) {
    $root = Join-Path $CaseRoot $Label
    if (Test-Path -LiteralPath $root) {
        throw [InvalidOperationException]::new('ENV1B3_TAMPER_CASE_EXISTS|case')
    }
    Copy-Item -LiteralPath $SourceInstallRoot -Destination $root -Recurse
    return $root
}

function Get-AppRoot([string]$InstallRoot) {
    $pointer = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $InstallRoot 'state\current-release.json') | ConvertFrom-Json
    return Join-Path $InstallRoot ([string]$pointer.app_root_relative).Replace('/',[IO.Path]::DirectorySeparatorChar)
}

function Get-RuntimeRoot {
    return Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'InfiniteCanvasEnterprise\runtime'
}

function Read-OptionalJson([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try { return Get-Content -Raw -Encoding UTF8 -LiteralPath $Path | ConvertFrom-Json } catch { return $null }
}

function Get-RuntimeSummary([string]$AppRoot) {
    $runtimeRoot = Get-RuntimeRoot
    $lock = Read-OptionalJson (Join-Path $runtimeRoot 'runtime-supervisor.lock')
    $state = Read-OptionalJson (Join-Path $runtimeRoot 'runtime-state.json')
    $context = Read-OptionalJson (Join-Path $runtimeRoot 'launch-context.json')
    return [ordered]@{
        lock_present=($null -ne $lock)
        lock_phase=$(if ($null -ne $lock) { [string]$lock.lock_phase } else { $null })
        lock_instance_id=$(if ($null -ne $lock) { [string]$lock.supervisor_instance_id } else { $null })
        lock_supervisor_pid=$(if ($null -ne $lock) { [int]$lock.supervisor_pid } else { 0 })
        state_present=($null -ne $state)
        state_value=$(if ($null -ne $state) { [string]$state.state } else { $null })
        state_instance_id=$(if ($null -ne $state) { [string]$state.supervisor_instance_id } else { $null })
        state_supervisor_pid=$(if ($null -ne $state) { [int]$state.supervisor_pid } else { 0 })
        retained_launch_context_identity=$(if ($null -ne $context) { [string]$context.startup_preflight_sha256 } else { $null })
        app_root_symbol='<CASE_ROOT>/install/releases/<RELEASE_ID>'
        expected_python_basename='python.exe'
    }
}

function Get-CandidatePids([string]$AppRoot) {
    return @(
        (Get-CimInstance Win32_Process -ErrorAction Stop |
            Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($AppRoot,[StringComparison]::OrdinalIgnoreCase) -ge 0 }
        ).ProcessId | Sort-Object
    )
}

function Test-PidAlive([int]$ProcessId) {
    try { return $null -ne (Get-Process -Id $ProcessId -ErrorAction Stop) } catch { return $false }
}

function Stop-VerifiedOwnedProcesses([string]$AppRoot) {
    $runtimeRoot = Get-RuntimeRoot
    $state = Read-OptionalJson (Join-Path $runtimeRoot 'runtime-state.json')
    if ($null -eq $state) { return @() }
    $expectedPython = [IO.Path]::GetFullPath((Join-Path $AppRoot 'python\python.exe'))
    $terminated = @()
    foreach ($identity in @(
        [ordered]@{pid=$state.supervisor_pid;created=$state.supervisor_process_created_at;executable=$state.supervisor_executable}
    )) {
        $pid = [int]$identity.pid
        if ($pid -le 0 -or -not (Test-PidAlive $pid)) { continue }
        $process = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $pid) -ErrorAction Stop
        $pathProperty = $process.PSObject.Properties['ExecutablePath']
        if ($null -eq $pathProperty -or [String]::IsNullOrWhiteSpace([string]$pathProperty.Value)) { continue }
        $actualPath = [IO.Path]::GetFullPath([string]$pathProperty.Value)
        $actualCreated = ([DateTime]$process.CreationDate).ToUniversalTime().ToFileTimeUtc()
        if ([string]::Compare($actualPath,$expectedPython,$true) -ne 0 -or
            [int64]$actualCreated -ne [int64]$identity.created -or
            [string]::Compare([IO.Path]::GetFullPath([string]$identity.executable),$expectedPython,$true) -ne 0) {
            continue
        }
        Stop-Process -Id $pid -Force -ErrorAction Stop
        $terminated += $pid
    }
    return @($terminated)
}

function Start-ForeignSentinel {
    $ping = Join-Path ([Environment]::GetFolderPath('System')) 'ping.exe'
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $ping
    $startInfo.Arguments = '-t 127.0.0.1'
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        $process.Dispose()
        throw [InvalidOperationException]::new('ENV1B3_FOREIGN_SENTINEL_FAILED|process')
    }
    $process.BeginOutputReadLine()
    $process.BeginErrorReadLine()
    return $process
}

function Stop-ForeignSentinel([Diagnostics.Process]$Process) {
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) {
            $Process.Kill()
            [void]$Process.WaitForExit(5000)
        }
    } finally {
        $Process.Dispose()
    }
}

function Write-StageRecord([string]$Path, [object]$Stages) {
    $json = [ordered]@{
        schema_version='env-1b3-tamper-stage-evidence-v1'
        stages=$Stages
    } | ConvertTo-Json -Depth 14 -Compress
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json + "`n")
    $stream = [IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {
        $stream.Write($bytes,0,$bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
}

function Write-MissingW09Failures([object]$Evidence) {
    foreach ($subcheck in @('owned_stop_after_tamper','foreign_stop_rejected','foreign_process_survived','owned_cleanup_succeeded')) {
        $path = Join-Path $EvidenceRoot (Join-Path 'subchecks\W09' ($subcheck + '.json'))
        if (-not (Test-Path -LiteralPath $path)) {
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W09 -SubcheckId $subcheck -Result FAIL -Code ENV1B3_W09_STAGE_FAILED -Evidence $Evidence | Out-Null
        }
    }
}

try {
    [void](Assert-ENV1B3AbsoluteSafePath $SourceInstallRoot)
    [void](Assert-ENV1B3AbsoluteSafePath $CaseRoot -AllowMissingLeaf)
    [void](Assert-ENV1B3AbsoluteSafePath $EvidenceRoot -AllowMissingLeaf)
    [IO.Directory]::CreateDirectory($CaseRoot) | Out-Null
    [IO.Directory]::CreateDirectory($EvidenceRoot) | Out-Null

    if ($Mode -in @('CombinedW09','OwnedStop','ForeignStop')) {
        $stages = [ordered]@{}
        $app = $null
        $failureStage = 'fixture_copy'
        try {
            $prior = Get-RuntimeSummary ''
            $install = New-CaseCopy 'w09-combined'
            $app = Get-AppRoot $install
            $stages.fixture_copy = @{result='PASS';app_root_symbol='<CASE_ROOT>/w09-combined/releases/<RELEASE_ID>'}

            $failureStage = 'healthy_start'
            $start = Invoke-Wrapper $app 'start'
            $summary = Get-RuntimeSummary $app
            $healthy = $start.exit_code -eq 0 -and -not $start.timed_out -and $summary.lock_present -and $summary.state_present
            $stages.healthy_start = @{result=$(if($healthy){'PASS'}else{'FAIL'});wrapper_exit=$start.exit_code;timed_out=$start.timed_out;runtime=$summary;previous_owned_state_present=$prior.lock_present}
            if (-not $healthy) { throw [InvalidOperationException]::new('ENV1B3_W09_HEALTHY_START_FAILED|healthy_start') }

            $manifestPath = Join-Path $app 'release-manifest.json'
            $manifestOriginal = [IO.File]::ReadAllBytes($manifestPath)
            Flip-FirstByte $manifestPath
            $failureStage = 'owned_stop_after_tamper'
            $ownedStop = Invoke-Wrapper $app 'stop'
            $ownedPass = $ownedStop.exit_code -eq 0 -and -not $ownedStop.timed_out
            $stages.owned_stop_after_tamper = @{result=$(if($ownedPass){'PASS'}else{'FAIL'});wrapper_exit=$ownedStop.exit_code;timed_out=$ownedStop.timed_out}
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W09 -SubcheckId owned_stop_after_tamper -Result $(if($ownedPass){'PASS'}else{'FAIL'}) -Code $(if($ownedPass){'ENV1B3_OWNED_RETAINED_STOP_PASS'}else{'ENV1B3_OWNED_RETAINED_STOP_FAILED'}) -Evidence @{owned_stop_exit=$ownedStop.exit_code;healthy_start_exit=$start.exit_code;retained_context_identity=$summary.retained_launch_context_identity;stage='owned_stop_after_tamper';execution_context_isolated_case_copy=$true;fixture_materialized_release=$true} | Out-Null
            if (-not $ownedPass) { throw [InvalidOperationException]::new('ENV1B3_OWNED_RETAINED_STOP_FAILED|owned_stop_after_tamper') }
            [IO.File]::WriteAllBytes($manifestPath,$manifestOriginal)

            $failureStage = 'healthy_start_after_restore'
            $restartOwned = Invoke-Wrapper $app 'start'
            if ($restartOwned.exit_code -ne 0 -or $restartOwned.timed_out) { throw [InvalidOperationException]::new('ENV1B3_W09_HEALTHY_START_FAILED|healthy_start_after_restore') }
            $runtimeRoot = Get-RuntimeRoot
            $lockPath = Join-Path $runtimeRoot 'runtime-supervisor.lock'
            $lockOriginal = [IO.File]::ReadAllBytes($lockPath)
            $lock = Get-Content -Raw -Encoding UTF8 -LiteralPath $lockPath | ConvertFrom-Json
            $ownedSupervisorPid = [int]$lock.supervisor_pid
            $ownedInstanceId = [string]$lock.supervisor_instance_id

            $failureStage = 'foreign_identity_mutation'
            $lock.supervisor_instance_id = [Guid]::NewGuid().ToString('N')
            [IO.File]::WriteAllText($lockPath,($lock | ConvertTo-Json -Depth 10 -Compress) + "`n",[Text.UTF8Encoding]::new($false))
            $stages.foreign_identity_mutation = @{result='PASS';owned_instance_id_present=(-not [String]::IsNullOrWhiteSpace($ownedInstanceId));mutated_instance_id_present=$true}

            $failureStage = 'foreign_stop_rejection'
            $foreignStop = Invoke-Wrapper $app 'stop'
            $foreignRejected = $foreignStop.exit_code -eq 2 -and -not $foreignStop.timed_out
            $stages.foreign_stop_rejection = @{result=$(if($foreignRejected){'PASS'}else{'FAIL'});wrapper_exit=$foreignStop.exit_code;timed_out=$foreignStop.timed_out}
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W09 -SubcheckId foreign_stop_rejected -Result $(if($foreignRejected){'PASS'}else{'FAIL'}) -Code $(if($foreignRejected){'ENV1B3_FOREIGN_STOP_REJECTED'}else{'ENV1B3_FOREIGN_STOP_REJECTION_FAILED'}) -Evidence @{foreign_stop_exit=$foreignStop.exit_code;stage='foreign_stop_rejection';execution_context_isolated_case_copy=$true;fixture_materialized_release=$true} | Out-Null

            $failureStage = 'foreign_survival'
            $supervisorAlive = Test-PidAlive $ownedSupervisorPid
            $stages.foreign_survival = @{result=$(if($supervisorAlive){'PASS'}else{'FAIL'});verified_owned_supervisor_pid_present=($ownedSupervisorPid -gt 0)}
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W09 -SubcheckId foreign_process_survived -Result $(if($supervisorAlive){'PASS'}else{'FAIL'}) -Code $(if($supervisorAlive){'ENV1B3_FOREIGN_PROCESS_SURVIVED'}else{'ENV1B3_FOREIGN_PROCESS_TERMINATED'}) -Evidence @{foreign_process_survived=$supervisorAlive;stage='foreign_survival'} | Out-Null

            $failureStage = 'identity_restore'
            [IO.File]::WriteAllBytes($lockPath,$lockOriginal)
            $hash=[Security.Cryptography.SHA256]::Create();try{$expectedLockHash=([BitConverter]::ToString($hash.ComputeHash($lockOriginal))).Replace('-','').ToLowerInvariant()}finally{$hash.Dispose()}
            $restored = (Get-ENV1B3Sha256 $lockPath) -eq $expectedLockHash
            $stages.identity_restore = @{result=$(if($restored){'PASS'}else{'FAIL'});identity_restored=$restored}
            if (-not $restored) { throw [InvalidOperationException]::new('ENV1B3_W09_IDENTITY_RESTORE_FAILED|identity_restore') }

            $failureStage = 'owned_cleanup'
            $cleanup = Invoke-Wrapper $app 'stop'
            $ack = $cleanup.payload.ack
            $portsReleased = $null -ne $ack -and $ack.upstream_port_release -eq 'released' -and $ack.gateway_port_release -eq 'released'
            $cleanupPass = $cleanup.exit_code -eq 0 -and -not $cleanup.timed_out -and $portsReleased
            $stages.owned_cleanup = @{result=$(if($cleanupPass){'PASS'}else{'FAIL'});wrapper_exit=$cleanup.exit_code;ports_released=$portsReleased}
            $stages.port_release = @{result=$(if($portsReleased){'PASS'}else{'FAIL'});ports_released=$portsReleased}
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W09 -SubcheckId owned_cleanup_succeeded -Result $(if($cleanupPass){'PASS'}else{'FAIL'}) -Code $(if($cleanupPass){'ENV1B3_OWNED_CLEANUP_PASS'}else{'ENV1B3_OWNED_CLEANUP_FAILED'}) -Evidence @{owned_cleanup_stop_exit=$cleanup.exit_code;ports_released=$portsReleased;stage='owned_cleanup';execution_context_isolated_case_copy=$true;fixture_materialized_release=$true} | Out-Null
            if (-not ($foreignRejected -and $supervisorAlive -and $cleanupPass)) {
                throw [InvalidOperationException]::new('ENV1B3_W09_STAGE_FAILED|aggregate')
            }
        } catch {
            $message = [string]$_.Exception.Message
            $code = $(if ($message -match '^([A-Z0-9_]+)\|') { $Matches[1] } else { 'ENV1B3_W09_STAGE_FAILED' })
            $diagnostic = @{
                failure_stage=$failureStage
                failure_code=$code
                stages=$stages
                runtime_summary=$(if($null-ne$app){Get-RuntimeSummary $app}else{$null})
                app_root_symbol='<CASE_ROOT>/w09-combined/releases/<RELEASE_ID>'
                candidate_runtime_defect_proven=$false
            }
            Write-MissingW09Failures $diagnostic
            try {
                if ($null -ne $app) {
                    $stop = Invoke-Wrapper $app 'stop'
                    if ($stop.exit_code -ne 0) { [void](Stop-VerifiedOwnedProcesses $app) }
                }
            } catch { }
        }
        Write-StageRecord (Join-Path $EvidenceRoot 'W09-STAGES.json') $stages
        $aggregate = Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W09 -ContractPath $ContractPath
        $aggregate | ConvertTo-Json -Depth 10 -Compress
        if ($aggregate.result -ne 'PASS') { exit 2 }
        exit 0
    }

    $targets = $(if ($Mode -eq 'All') { @('Pointer','ReleaseManifest','RuntimeManifest','Payload','PythonDll') } else { @($Mode) })
    $subcheckNames = @{Pointer='current_release';ReleaseManifest='release_manifest';RuntimeManifest='runtime_manifest';Payload='payload';PythonDll='python314_dll'}
    foreach ($targetName in $targets) {
        $subcheckId = $subcheckNames[$targetName]
        $stage = 'fixture_copy'
        $foreign = $null
        $app = $null
        $evidence = [ordered]@{
            target=$targetName
            stage=$stage
            start_exit=$null
            restart_exit=$null
            health_exit=$null
            status_exit=$null
            stop_exit=$null
            process_before=@()
            process_after=@()
            failure_code=$null
            start_failed_closed=$false
            restart_failed_closed=$false
            health_failed_closed=$false
            status_diagnostic=$false
            no_new_candidate_process=$false
            owned_stop_succeeded=$false
            foreign_process_survived=$false
            independent_case_root=$true
            execution_context_isolated_case_copies=$true
            fixture_materialized_release=$true
        }
        try {
            $install = New-CaseCopy ('w08-' + $targetName.ToLowerInvariant())
            $app = Get-AppRoot $install
            $stage = 'healthy_start'
            $healthy = Invoke-Wrapper $app 'start'
            $evidence.healthy_start_exit = $healthy.exit_code
            $evidence.healthy_start_timed_out = $healthy.timed_out
            if ($healthy.exit_code -ne 0 -or $healthy.timed_out) {
                throw [InvalidOperationException]::new('ENV1B3_TAMPER_SETUP_FAILED|healthy_start')
            }
            $ownership = Get-RuntimeSummary $app
            if (-not $ownership.lock_present -or -not $ownership.state_present) {
                throw [InvalidOperationException]::new('ENV1B3_TAMPER_SETUP_FAILED|ownership')
            }
            $evidence.healthy_ownership_context = $ownership
            $evidence.process_before = @(Get-CandidatePids $app)
            $foreign = Start-ForeignSentinel

            $stage = 'tamper'
            switch ($targetName) {
                'Pointer' { $target = Join-Path $install 'state\current-release.json' }
                'ReleaseManifest' { $target = Join-Path $app 'release-manifest.json' }
                'RuntimeManifest' { $target = Join-Path $app 'runtime-manifest.json' }
                'Payload' { $target = Join-Path $app 'VERSION' }
                'PythonDll' { $target = Join-Path $app 'python\python314.dll' }
            }
            Flip-FirstByte $target

            foreach ($command in @('start','restart','health','status','stop')) {
                $stage = $command
                $result = Invoke-Wrapper $app $command
                $evidence.($command + '_exit') = $result.exit_code
                $evidence.($command + '_timed_out') = $result.timed_out
                if ($command -eq 'status') { $evidence.process_after = @(Get-CandidatePids $app) }
            }
            $evidence.start_failed_closed = $evidence.start_exit -eq 2 -and -not $evidence.start_timed_out
            $evidence.restart_failed_closed = $evidence.restart_exit -eq 2 -and -not $evidence.restart_timed_out
            $evidence.health_failed_closed = $evidence.health_exit -eq 2 -and -not $evidence.health_timed_out
            $evidence.status_diagnostic = $evidence.status_exit -eq 0 -and -not $evidence.status_timed_out
            $evidence.no_new_candidate_process = @(Compare-Object @($evidence.process_before) @($evidence.process_after)).Count -eq 0
            $evidence.owned_stop_succeeded = $evidence.stop_exit -eq 0 -and -not $evidence.stop_timed_out
            $evidence.foreign_process_survived = Test-PidAlive $foreign.Id
            $passed = $evidence.start_failed_closed -and $evidence.restart_failed_closed -and
                $evidence.health_failed_closed -and $evidence.status_diagnostic -and
                $evidence.no_new_candidate_process -and $evidence.owned_stop_succeeded -and
                $evidence.foreign_process_survived
            if (-not $passed) { $evidence.failure_code = 'ENV1B3_TAMPER_FAIL_CLOSED_FAILED' }
        } catch {
            $message = [string]$_.Exception.Message
            $evidence.stage = $stage
            $evidence.failure_code = $(if ($message -match '^([A-Z0-9_]+)\|') { $Matches[1] } else { 'ENV1B3_TAMPER_TARGET_EXCEPTION' })
            $passed = $false
            try {
                if ($null -ne $app) {
                    $cleanup = Invoke-Wrapper $app 'stop'
                    $evidence.cleanup_stop_exit = $cleanup.exit_code
                    if ($cleanup.exit_code -ne 0) {
                        $evidence.verified_owned_cleanup_pids = @(Stop-VerifiedOwnedProcesses $app)
                    }
                }
            } catch { }
        } finally {
            if ($null -ne $foreign) { Stop-ForeignSentinel $foreign }
        }
        $evidence.stage = $stage
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W08 -SubcheckId $subcheckId -Result $(if($passed){'PASS'}else{'FAIL'}) -Code $(if($passed){'ENV1B3_TAMPER_TARGET_PASS'}else{'ENV1B3_TAMPER_FAIL_CLOSED_FAILED'}) -Evidence $evidence | Out-Null
    }
    $aggregate = Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W08 -ContractPath $ContractPath
    $aggregate | ConvertTo-Json -Depth 10 -Compress
    if ($aggregate.result -ne 'PASS') { exit 2 }
} catch {
    $caseId = $(if ($Mode -in @('OwnedStop','ForeignStop','CombinedW09')) { 'W09' } else { 'W08' })
    $code = 'ENV1B3_TAMPER_MATRIX_FAILED'
    if ($_.Exception.Message -match '^([A-Z0-9_]+)\|') { $code = $Matches[1] }
    if (-not (Test-Path -LiteralPath (Join-Path $EvidenceRoot ($caseId + '.json')))) {
        Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $caseId -Result FAIL -Code $code -Evidence @{failure_stage='outer';failure_code=$code;candidate_runtime_defect_proven=$false} | ConvertTo-Json -Compress
    }
    exit 2
}
