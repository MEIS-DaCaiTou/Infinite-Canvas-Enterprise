[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AppRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][ValidateSet('W03','W04','W05','W07','W14')][string]$CaseId,
    [Parameter(Mandatory)][string]$DifferentCwd,
    [switch]$PolluteEnvironment
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
    [void](Assert-ENV1B3AbsoluteSafePath $AppRoot)
    [void](Assert-ENV1B3AbsoluteSafePath $DifferentCwd)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) { throw [InvalidOperationException]::new('ENV1B3_APPLICATION_USER_ADMIN_FORBIDDEN|user') }
    $expectedPython = [IO.Path]::GetFullPath((Join-Path $AppRoot 'python\python.exe'))
    if (-not (Test-Path -LiteralPath $expectedPython -PathType Leaf)) { throw [InvalidOperationException]::new('ENV1B3_FIXED_PYTHON_MISSING|python') }
    $appTreeBefore = Get-ENV1B3DirectoryTree $AppRoot
    $oldHome = $env:PYTHONHOME; $oldPath = $env:PYTHONPATH
    if ($PolluteEnvironment) { $env:PYTHONHOME = '<INVALID-PYTHONHOME>'; $env:PYTHONPATH = '<INVALID-PYTHONPATH>' }
    $results = [ordered]@{}
    $livePythonPaths=@()
    $livePythonIdentityValid=$false
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
            $results[$item[0]] = Invoke-Wrapper $item[1]
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
                    $actual=[IO.Path]::GetFullPath([string]$property.Value)
                    $livePythonPaths+=$actual
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
    $record = Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -Result 'PASS' -Code 'ENV1B3_LIFECYCLE_PASS' -Evidence @{
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
    }
    $record | ConvertTo-Json -Depth 8 -Compress
} catch {
    try {
        $stopWrapper=(-join @([char]0x505C,[char]0x6B62,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat'
        if(Test-Path (Join-Path $AppRoot $stopWrapper)){ Push-Location $DifferentCwd; & $env:ComSpec /d /c ('"' + (Join-Path $AppRoot $stopWrapper) + '"') 2>&1 | Out-Null; Pop-Location }
    } catch { }
    $code = 'ENV1B3_LIFECYCLE_FAILED'
    if ($_.Exception.Message -match '^([A-Z0-9_]+)\|') { $code=$Matches[1] }
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -Result 'FAIL' -Code $code -Evidence @{failure_stage=$failureStage} | ConvertTo-Json -Compress
    exit 2
}
