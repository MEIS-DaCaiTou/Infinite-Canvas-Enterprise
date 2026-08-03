[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AppRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][ValidateSet('W03','W04','W05','W07','W11','W14')][string]$CaseId,
    [Parameter(Mandatory)][string]$DifferentCwd,
    [switch]$PolluteEnvironment,
    [switch]$RequireOffline,
    [switch]$RequireExternalPathRoots,
    [string]$SubcheckId
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

function Invoke-Wrapper([string]$Name) {
    $wrapper = Join-Path $AppRoot $Name
    if (-not (Test-Path -LiteralPath $wrapper -PathType Leaf)) { throw [InvalidOperationException]::new('ENV1B3_WRAPPER_MISSING|wrapper') }
    $startInfo=[Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName=$env:ComSpec
    $startInfo.Arguments='/d /s /c ""'+$wrapper+'""'
    $startInfo.WorkingDirectory=$DifferentCwd
    $startInfo.UseShellExecute=$false
    $startInfo.CreateNoWindow=$true
    $startInfo.RedirectStandardOutput=$true
    $startInfo.RedirectStandardError=$true
    $process=[Diagnostics.Process]::new();$process.StartInfo=$startInfo
    try {
        if(-not $process.Start()){throw [InvalidOperationException]::new('ENV1B3_LIFECYCLE_COMMAND_FAILED|process')}
        $stdout=$process.StandardOutput.ReadToEnd();$stderr=$process.StandardError.ReadToEnd();$process.WaitForExit()
        $exitCode=[int]$process.ExitCode
    } finally { $process.Dispose() }
    $output=@(($stdout+"`n"+$stderr).Split("`n")|ForEach-Object{$_.TrimEnd("`r")})
    $bounded = ($output -join "`n")
    if ($bounded.Length -gt 65536) { $bounded = $bounded.Substring($bounded.Length - 65536) }
    $payload = $null
    foreach ($line in $output) {
        try { $candidate = [string]$line | ConvertFrom-Json; if ($null -ne $candidate) { $payload = $candidate } } catch { }
    }
    return [ordered]@{exit_code=$exitCode; payload=$payload; output_tail=$bounded}
}

try {
    $failureStage='path_preflight'
    $lastWrapperRole=$null;$lastWrapperResult=$null
    [void](Assert-ENV1B3AbsoluteSafePath $AppRoot)
    [void](Assert-ENV1B3AbsoluteSafePath $DifferentCwd)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) { throw [InvalidOperationException]::new('ENV1B3_APPLICATION_USER_ADMIN_FORBIDDEN|user') }
    $expectedPython = ConvertTo-ENV1B3ComparableProcessPath (Join-Path $AppRoot 'python\python.exe')
    if (-not (Test-Path -LiteralPath $expectedPython -PathType Leaf)) { throw [InvalidOperationException]::new('ENV1B3_FIXED_PYTHON_MISSING|python') }
    $appTreeBefore = Get-ENV1B3DirectoryTree $AppRoot
    $candidatePythonDirectory = [IO.Path]::GetDirectoryName($expectedPython)
    $pathEntries = @(([string]$env:PATH).Split([IO.Path]::PathSeparator) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $candidatePythonOnPath = $false
    foreach ($entry in $pathEntries) {
        try {
            if ([string]::Compare([IO.Path]::GetFullPath($entry.Trim('"')), $candidatePythonDirectory, $true) -eq 0) {
                $candidatePythonOnPath = $true
            }
        } catch { }
    }
    if ($RequireOffline -and $candidatePythonOnPath) { throw [InvalidOperationException]::new('ENV1B3_OFFLINE_CONTRACT_INVALID|path') }
    $networkOffline = $null
    if ($RequireOffline) {
        $profiles = @(Get-NetConnectionProfile -ErrorAction Stop)
        $internetProfiles = @($profiles | Where-Object {
            [string]$_.IPv4Connectivity -eq 'Internet' -or [string]$_.IPv6Connectivity -eq 'Internet'
        })
        $networkOffline = $internetProfiles.Count -eq 0
        if (-not $networkOffline) { throw [InvalidOperationException]::new('ENV1B3_OFFLINE_CONTRACT_INVALID|network') }
    }
    $pathRootsExternal = $null
    if ($RequireExternalPathRoots) {
        $releaseRoot = Split-Path -Parent $AppRoot
        $installRoot = Split-Path -Parent $releaseRoot
        $externalRoots = @('config','data','logs','backups','state','staging') | ForEach-Object { Join-Path $installRoot $_ }
        $appPrefix = [IO.Path]::GetFullPath($AppRoot) + [IO.Path]::DirectorySeparatorChar
        $pathRootsExternal = @($externalRoots | Where-Object {
            (-not (Test-Path -LiteralPath $_ -PathType Container)) -or
            [IO.Path]::GetFullPath($_).StartsWith($appPrefix, [StringComparison]::OrdinalIgnoreCase)
        }).Count -eq 0
        if (-not $pathRootsExternal) { throw [InvalidOperationException]::new('ENV1B3_PATH_ROOTS_EXTERNAL_INVALID|path_roots') }
    }
    $oldHome = $env:PYTHONHOME; $oldPath = $env:PYTHONPATH
    if ($PolluteEnvironment) { $env:PYTHONHOME = '<INVALID-PYTHONHOME>'; $env:PYTHONPATH = '<INVALID-PYTHONPATH>' }
    $results = [ordered]@{}
    $livePythonPaths=@()
    $livePythonIdentityValid=$false
    $candidateNonLoopbackConnectionCount=0
    try {
        $failureStage='wrapper_sequence'
        # Keep this Windows PowerShell 5.1 script ASCII-safe: PS 5.1 treats a
        # UTF-8-without-BOM source file as the active ANSI code page.
        $startWrapper=(-join @([char]0x542F,[char]0x52A8,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat'
        $statusWrapper=(-join @([char]0x67E5,[char]0x770B,[char]0x4F01,[char]0x4E1A,[char]0x7248,[char]0x72B6,[char]0x6001))+'.bat'
        $healthWrapper=(-join @([char]0x4F01,[char]0x4E1A,[char]0x7248,[char]0x5065,[char]0x5EB7,[char]0x68C0,[char]0x67E5))+'.bat'
        $stopWrapper=(-join @([char]0x505C,[char]0x6B62,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat'
        foreach ($item in @(
            @('start',$startWrapper),
            @('status',$statusWrapper),
            @('health',$healthWrapper),
            @('stop',$stopWrapper)
        )) {
            $failureStage='wrapper_'+$item[0]
            $lastWrapperRole=[string]$item[0];$results[$item[0]] = Invoke-Wrapper $item[1];$lastWrapperResult=$results[$item[0]]
            if ($results[$item[0]].exit_code -ne 0) { throw [InvalidOperationException]::new('ENV1B3_LIFECYCLE_COMMAND_FAILED|' + $item[0]) }
            if($item[0] -eq 'status'){
                $failureStage='live_python_identity_snapshot'
                $snapshot=$results.status.payload.runtime_state
                $pids=@([int]$snapshot.supervisor_pid,[int]$snapshot.upstream.pid,[int]$snapshot.gateway.pid)
                foreach($processId in $pids){
                    $failureStage='live_python_identity_pid'
                    if($processId -le 0){throw [InvalidOperationException]::new('ENV1B3_LIFECYCLE_PROCESS_IDENTITY_INVALID|pid')}
                    $failureStage='live_python_identity_cim'
                    $process=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$processId)
                    $failureStage='live_python_identity_path'
                    $property=$process.PSObject.Properties['ExecutablePath']
                    if($null -eq $property -or [String]::IsNullOrWhiteSpace([string]$property.Value)){
                        throw [InvalidOperationException]::new('ENV1B3_LIFECYCLE_PROCESS_IDENTITY_INVALID|executable')
                    }
                    $actual=ConvertTo-ENV1B3ComparableProcessPath ([string]$property.Value)
                    $livePythonPaths+=$actual
                }
                if ($RequireOffline) {
                    $connections = @(Get-NetTCPConnection -ErrorAction Stop | Where-Object { $pids -contains [int]$_.OwningProcess })
                    $candidateNonLoopbackConnectionCount = @($connections | Where-Object {
                        $remote = [string]$_.RemoteAddress
                        $remote -notin @('127.0.0.1','::1','0.0.0.0','::','')
                    }).Count
                    if ($candidateNonLoopbackConnectionCount -ne 0) {
                        throw [InvalidOperationException]::new('ENV1B3_OFFLINE_CONTRACT_INVALID|connection')
                    }
                }
                $failureStage='live_python_identity_compare'
                $livePythonIdentityValid=@($livePythonPaths|Where-Object{[string]::Compare($_,$expectedPython,$true)-ne 0}).Count -eq 0
                if(-not $livePythonIdentityValid){throw [InvalidOperationException]::new('ENV1B3_LIFECYCLE_PROCESS_IDENTITY_INVALID|executable')}
            }
        }
    } finally {
        if ($null -eq $oldHome) { Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue } else { $env:PYTHONHOME=$oldHome }
        if ($null -eq $oldPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH=$oldPath }
    }
    $status = $results.status.payload
    $failureStage='result_contract'
    $health = $results.health.payload
    $state = $status.runtime_state
    $basenames = @($livePythonPaths | ForEach-Object { [IO.Path]::GetFileName($_) })
    $identityValid = $livePythonIdentityValid -and $livePythonPaths.Count -eq 3
    $ready = $health.readiness.ready -eq $true
    $owned = $status.portable_ownership_valid -eq $true
    $ack = $results.stop.payload.ack
    $portRelease = $null -ne $ack -and $ack.upstream_port_release -eq 'released' -and $ack.gateway_port_release -eq 'released' -and $ack.owned_pid_release_complete -eq $true -and $ack.supervisor_exit_confirmed -eq $true -and $ack.foreign_listener_detected -eq $false
    $appTreeAfter = Get-ENV1B3DirectoryTree $AppRoot
    $appRootUnchanged = $appTreeBefore.file_count -eq $appTreeAfter.file_count -and $appTreeBefore.tree_sha256 -eq $appTreeAfter.tree_sha256
    if (-not $identityValid -or -not $ready -or -not $owned -or -not $portRelease -or -not $appRootUnchanged) { throw [InvalidOperationException]::new('ENV1B3_LIFECYCLE_IDENTITY_INVALID|identity') }
    $failureStage='evidence_write'
    $evidence = @{
        application_user_is_admin=$false
        elevation_used_for_application=$false
        wrapper_exit_codes=@{start=0;status=0;health=0;stop=0}
        portable_ownership_valid=$owned
        readiness_ready=$ready
        process_python_basenames=$basenames
        fixed_python_all_roles=$identityValid
        port_release_verified=$portRelease
        app_root_tree_unchanged=$appRootUnchanged
        app_root_tree_sha256=$appTreeAfter.tree_sha256
        different_cwd_verified=$true
        environment_pollution_enabled=[bool]$PolluteEnvironment
        path_candidate_python_absent=(-not $candidatePythonOnPath)
        network_offline=$(if ($RequireOffline) { [bool]$networkOffline } else { $null })
        candidate_non_loopback_connection_count=$candidateNonLoopbackConnectionCount
        download_behavior_observed=($candidateNonLoopbackConnectionCount -ne 0)
        path_roots_external=$(if ($RequireExternalPathRoots) { [bool]$pathRootsExternal } else { $null })
    }
    if ([string]::IsNullOrWhiteSpace($SubcheckId)) {
        $record = Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -Result 'PASS' -Code 'ENV1B3_LIFECYCLE_PASS' -Evidence $evidence
    } else {
        $record = Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -SubcheckId $SubcheckId -Result 'PASS' -Code 'ENV1B3_LIFECYCLE_PASS' -Evidence $evidence
    }
    $record | ConvertTo-Json -Depth 8 -Compress
} catch {
    try {
        $stopWrapper=(-join @([char]0x505C,[char]0x6B62,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat'
        if(Test-Path (Join-Path $AppRoot $stopWrapper)){ Push-Location $DifferentCwd; & $env:ComSpec /d /c ('"' + (Join-Path $AppRoot $stopWrapper) + '"') 2>&1 | Out-Null; Pop-Location }
    } catch { }
    $code = 'ENV1B3_LIFECYCLE_FAILED'
    if ($_.Exception.Message -match '^([A-Z0-9_]+)\|') { $code=$Matches[1] }
    $runtimeRoot=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'InfiniteCanvasEnterprise\runtime'
    $failureEvidence=@{failure_stage=$failureStage;wrapper_role=$lastWrapperRole;wrapper_exit=$(if($null-ne$lastWrapperResult){$lastWrapperResult.exit_code}else{$null});stdout_stderr_tail=$(if($null-ne$lastWrapperResult){$lastWrapperResult.output_tail}else{''});different_cwd_exists=(Test-Path -LiteralPath $DifferentCwd -PathType Container);app_root_exists=(Test-Path -LiteralPath $AppRoot -PathType Container);runtime_summary=@{lock_present=(Test-Path -LiteralPath (Join-Path $runtimeRoot 'runtime-supervisor.lock'));state_present=(Test-Path -LiteralPath (Join-Path $runtimeRoot 'runtime-state.json'))}}
    if ([string]::IsNullOrWhiteSpace($SubcheckId)) {
        Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -Result 'FAIL' -Code $code -Evidence $failureEvidence | ConvertTo-Json -Compress
    } else {
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -SubcheckId $SubcheckId -Result 'FAIL' -Code $code -Evidence $failureEvidence | ConvertTo-Json -Compress
    }
    exit 2
}
