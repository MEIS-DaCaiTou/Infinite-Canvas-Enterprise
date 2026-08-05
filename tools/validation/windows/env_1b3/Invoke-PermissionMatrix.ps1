[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AppRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [ValidateSet('VerifyReadOnly','DeniedWritableRoot')][string]$Mode = 'VerifyReadOnly',
    [string]$DeniedRoot,
    [string]$ContractPath
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
try {
    [void](Assert-ENV1B3AbsoluteSafePath $AppRoot)
    $probe = Join-Path $AppRoot ('.env1b3-write-probe-' + [Guid]::NewGuid().ToString('N'))
    $writeDenied = $false
    try {
        $handle = [IO.File]::Open($probe,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $handle.Dispose()
    } catch [UnauthorizedAccessException] { $writeDenied=$true } finally { if(Test-Path -LiteralPath $probe){ Remove-Item -LiteralPath $probe -Force } }
    if (-not $writeDenied) { throw [InvalidOperationException]::new('ENV1B3_APP_ROOT_WRITABLE|app_root') }
    $externalRoots = @('config','data','logs','backups','state','staging') | ForEach-Object { Join-Path (Split-Path -Parent (Split-Path -Parent $AppRoot)) $_ }
    foreach($root in $externalRoots){ if(-not (Test-Path -LiteralPath $root -PathType Container)){ throw [InvalidOperationException]::new('ENV1B3_EXTERNAL_ROOT_MISSING|root') } }
    if (-not [string]::IsNullOrWhiteSpace($ContractPath)) {
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId 'W06' -SubcheckId 'readonly_app_root' -Result 'PASS' -Code 'ENV1B3_APP_ROOT_READONLY_PASS' -Evidence @{app_root_write_denied=$true;external_root_count=$externalRoots.Count} | Out-Null
        $Mode = 'DeniedWritableRoot'
    }
    $deniedVerified = $false
    if($Mode -eq 'DeniedWritableRoot'){
        if([string]::IsNullOrWhiteSpace($DeniedRoot)){ throw [InvalidOperationException]::new('ENV1B3_DENIED_ROOT_REQUIRED|root') }
        [void](Assert-ENV1B3AbsoluteSafePath $DeniedRoot)
        $deniedProbe=Join-Path $DeniedRoot ('.env1b3-denied-probe-' + [Guid]::NewGuid().ToString('N'))
        try { $h=[IO.File]::Open($deniedProbe,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None); $h.Dispose(); throw [InvalidOperationException]::new('ENV1B3_DENIED_ROOT_WRITABLE|root') } catch [UnauthorizedAccessException] { } finally { if(Test-Path -LiteralPath $deniedProbe){ Remove-Item -LiteralPath $deniedProbe -Force } }
        $deniedVerified = $true
        if (-not [string]::IsNullOrWhiteSpace($ContractPath)) {
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId 'W06' -SubcheckId 'denied_writable_root' -Result 'PASS' -Code 'ENV1B3_DENIED_ROOT_PASS' -Evidence @{denied_root_write_denied=$true} | Out-Null
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ContractPath)) {
        Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W06' -ContractPath $ContractPath | ConvertTo-Json -Depth 8 -Compress
    } else {
        Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W06' -Result 'PASS' -Code 'ENV1B3_PERMISSION_MATRIX_PASS' -Evidence @{app_root_write_denied=$true; external_root_count=$externalRoots.Count; denied_root_checked=$deniedVerified} | ConvertTo-Json -Depth 6 -Compress
    }
} catch {
    $code='ENV1B3_PERMISSION_MATRIX_FAILED'; if($_.Exception.Message -match '^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W06' -Result 'FAIL' -Code $code -Evidence @{} | ConvertTo-Json -Compress
    exit 2
}
