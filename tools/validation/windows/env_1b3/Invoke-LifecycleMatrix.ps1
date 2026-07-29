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
    Push-Location $DifferentCwd
    try {
        $output = @(& $env:ComSpec /d /c ('"' + $wrapper + '"') 2>&1)
        $exitCode = $LASTEXITCODE
    } finally { Pop-Location }
    $bounded = ($output -join "`n")
    if ($bounded.Length -gt 65536) { $bounded = $bounded.Substring($bounded.Length - 65536) }
    $payload = $null
    foreach ($line in @($output | Select-Object -Last 8)) {
        try { $candidate = [string]$line | ConvertFrom-Json; if ($null -ne $candidate) { $payload = $candidate } } catch { }
    }
    return [ordered]@{exit_code=$exitCode; payload=$payload; output_tail=$bounded}
}

try {
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
    try {
        foreach ($item in @(
            @('start','启动企业版.bat'),
            @('status','查看企业版状态.bat'),
            @('health','企业版健康检查.bat'),
            @('stop','停止企业版.bat')
        )) {
            $results[$item[0]] = Invoke-Wrapper $item[1]
            if ($results[$item[0]].exit_code -ne 0) { throw [InvalidOperationException]::new('ENV1B3_LIFECYCLE_COMMAND_FAILED|' + $item[0]) }
        }
    } finally {
        if ($null -eq $oldHome) { Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue } else { $env:PYTHONHOME=$oldHome }
        if ($null -eq $oldPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH=$oldPath }
    }
    $status = $results.status.payload
    $health = $results.health.payload
    $state = $status.runtime_state
    $executables = @([string]$state.supervisor_executable,[string]$state.upstream.executable,[string]$state.gateway.executable)
    $basenames = @($executables | ForEach-Object { [IO.Path]::GetFileName($_) })
    $identityValid = @($executables | Where-Object { [string]::Compare([IO.Path]::GetFullPath($_),$expectedPython,$true) -ne 0 }).Count -eq 0
    $ready = $health.readiness.ready -eq $true
    $owned = $status.portable_ownership_valid -eq $true
    $ack = $results.stop.payload.ack
    $portRelease = $null -ne $ack -and $ack.upstream_port_release -eq 'released' -and $ack.gateway_port_release -eq 'released' -and $ack.owned_pid_release_complete -eq $true -and $ack.supervisor_exit_confirmed -eq $true -and $ack.foreign_listener_detected -eq $false
    $appTreeAfter = Get-ENV1B3DirectoryTree $AppRoot
    $appRootUnchanged = $appTreeBefore.file_count -eq $appTreeAfter.file_count -and $appTreeBefore.tree_sha256 -eq $appTreeAfter.tree_sha256
    if (-not $identityValid -or -not $ready -or -not $owned -or -not $portRelease -or -not $appRootUnchanged) { throw [InvalidOperationException]::new('ENV1B3_LIFECYCLE_IDENTITY_INVALID|identity') }
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
    try { if(Test-Path (Join-Path $AppRoot '停止企业版.bat')){ Push-Location $DifferentCwd; & $env:ComSpec /d /c ('"' + (Join-Path $AppRoot '停止企业版.bat') + '"') 2>&1 | Out-Null; Pop-Location } } catch { }
    $code = 'ENV1B3_LIFECYCLE_FAILED'
    if ($_.Exception.Message -match '^([A-Z0-9_]+)\|') { $code=$Matches[1] }
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -Result 'FAIL' -Code $code -Evidence @{} | ConvertTo-Json -Compress
    exit 2
}
