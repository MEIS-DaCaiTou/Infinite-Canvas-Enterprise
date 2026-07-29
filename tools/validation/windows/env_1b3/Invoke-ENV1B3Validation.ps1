[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Full','FinalIdentity','Baseline','Verify','Materialize','Lifecycle','UnicodeLifecycle','LongPathMaterialize','Permission','OfflinePollution','Tamper','OwnedStop','ForeignStop','PortConflict','RebootPrepare','RebootResume','LowDisk','ArchiveLock','DefenderStatus','Export')][string]$Mode,
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [ValidateSet('fresh_vm_snapshot','fresh_physical_image','dedicated_clean_test_host')][string]$CleanHostClassification = 'dedicated_clean_test_host',
    [string]$AppRoot,
    [string]$SourceInstallRoot,
    [string]$CaseRoot,
    [string]$DeniedRoot,
    [string]$ArchivePath,
    [string]$IsolatedLowDiskRoot,
    [string]$CandidateId,
    [int]$Port = 18000
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Invoke-ScriptChecked([string]$Name, [hashtable]$Arguments) {
    $path = Join-Path $here $Name
    try {
        & $path @Arguments
        $powerShellSucceeded = $?
    } catch {
        [ordered]@{schema_version='env-1b3-entrypoint-error-v1';status='blocked';code='ENV1B3_ENTRYPOINT_POWERSHELL_STEP_FAILED';step=$Name;exit_code=2} | ConvertTo-Json -Compress
        exit 2
    }
    if (-not $powerShellSucceeded) {
        [ordered]@{schema_version='env-1b3-entrypoint-error-v1';status='blocked';code='ENV1B3_ENTRYPOINT_POWERSHELL_STEP_FAILED';step=$Name;exit_code=2} | ConvertTo-Json -Compress
        exit 2
    }
}

$common = @{HandoffRoot=$HandoffRoot; TestRoot=$TestRoot; EvidenceRoot=$EvidenceRoot}
switch ($Mode) {
    'Baseline' { Invoke-ScriptChecked 'Invoke-EnvironmentBaseline.ps1' @{TestRoot=$TestRoot; EvidenceRoot=$EvidenceRoot; Classification=$CleanHostClassification} }
    'Verify' { Invoke-ScriptChecked 'Invoke-ArtifactVerification.ps1' @{HandoffRoot=$HandoffRoot; EvidenceRoot=$EvidenceRoot} }
    'Materialize' { Invoke-ScriptChecked 'Invoke-Materialization.ps1' $common }
    'Lifecycle' {
        $handoff = Get-Content -Raw -LiteralPath (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json') | ConvertFrom-Json
        $appRoot = Join-Path $TestRoot ('install\releases\' + [string]$handoff.release_id)
        Invoke-ScriptChecked 'Invoke-LifecycleMatrix.ps1' @{AppRoot=$appRoot; EvidenceRoot=$EvidenceRoot; CaseId='W03'; DifferentCwd=$TestRoot}
    }
    'UnicodeLifecycle' {
        Invoke-ScriptChecked 'Invoke-Materialization.ps1' $common
        $handoff = Get-Content -Raw -LiteralPath (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json') | ConvertFrom-Json
        $caseAppRoot = Join-Path $TestRoot ('install\releases\' + [string]$handoff.release_id)
        Invoke-ScriptChecked 'Invoke-LifecycleMatrix.ps1' @{AppRoot=$caseAppRoot; EvidenceRoot=$EvidenceRoot; CaseId='W04'; DifferentCwd=([IO.Path]::GetPathRoot($TestRoot)); PolluteEnvironment=$true}
    }
    'LongPathMaterialize' {
        Invoke-ScriptChecked 'Invoke-Materialization.ps1' @{HandoffRoot=$HandoffRoot;TestRoot=$TestRoot;EvidenceRoot=$EvidenceRoot;CaseId='W05'}
        $handoff = Get-Content -Raw -LiteralPath (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json') | ConvertFrom-Json
        $caseAppRoot = Join-Path $TestRoot ('install\releases\' + [string]$handoff.release_id)
        Invoke-ScriptChecked 'Invoke-LifecycleMatrix.ps1' @{AppRoot=$caseAppRoot;EvidenceRoot=$EvidenceRoot;CaseId='W05';DifferentCwd=([IO.Path]::GetPathRoot($TestRoot));PolluteEnvironment=$true}
    }
    'Permission' { Invoke-ScriptChecked 'Invoke-PermissionMatrix.ps1' @{AppRoot=$AppRoot;EvidenceRoot=$EvidenceRoot;Mode=$(if($DeniedRoot){'DeniedWritableRoot'}else{'VerifyReadOnly'});DeniedRoot=$DeniedRoot} }
    'OfflinePollution' { Invoke-ScriptChecked 'Invoke-LifecycleMatrix.ps1' @{AppRoot=$AppRoot;EvidenceRoot=$EvidenceRoot;CaseId='W07';DifferentCwd=$TestRoot;PolluteEnvironment=$true} }
    'Tamper' { Invoke-ScriptChecked 'Invoke-TamperMatrix.ps1' @{SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;EvidenceRoot=$EvidenceRoot;Mode='All'} }
    'OwnedStop' { Invoke-ScriptChecked 'Invoke-TamperMatrix.ps1' @{SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;EvidenceRoot=$EvidenceRoot;Mode='OwnedStop'} }
    'ForeignStop' { Invoke-ScriptChecked 'Invoke-TamperMatrix.ps1' @{SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;EvidenceRoot=$EvidenceRoot;Mode='ForeignStop'} }
    'PortConflict' { Invoke-ScriptChecked 'Invoke-ResourceInterferenceMatrix.ps1' @{Mode='PortConflict';EvidenceRoot=$EvidenceRoot;AppRoot=$AppRoot;Port=$Port} }
    'RebootPrepare' { Invoke-ScriptChecked 'Invoke-RebootResume.ps1' @{Mode='Prepare';EvidenceRoot=$EvidenceRoot;CandidateId=$CandidateId} }
    'RebootResume' { Invoke-ScriptChecked 'Invoke-RebootResume.ps1' @{Mode='Resume';EvidenceRoot=$EvidenceRoot;CandidateId=$CandidateId} }
    'LowDisk' { Invoke-ScriptChecked 'Invoke-ResourceInterferenceMatrix.ps1' @{Mode='LowDisk';EvidenceRoot=$EvidenceRoot;IsolatedLowDiskRoot=$IsolatedLowDiskRoot} }
    'ArchiveLock' { Invoke-ScriptChecked 'Invoke-ResourceInterferenceMatrix.ps1' @{Mode='ArchiveLock';EvidenceRoot=$EvidenceRoot;ArchivePath=$ArchivePath} }
    'DefenderStatus' { Invoke-ScriptChecked 'Invoke-ResourceInterferenceMatrix.ps1' @{Mode='DefenderStatus';EvidenceRoot=$EvidenceRoot} }
    'Export' { Invoke-ScriptChecked 'Export-ValidationEvidence.ps1' @{HandoffRoot=$HandoffRoot; EvidenceRoot=$EvidenceRoot; OutputRoot=$TestRoot} }
    { $_ -in @('Full','FinalIdentity') } {
        Invoke-ScriptChecked 'Invoke-EnvironmentBaseline.ps1' @{TestRoot=$TestRoot; EvidenceRoot=$EvidenceRoot; Classification=$CleanHostClassification}
        Invoke-ScriptChecked 'Invoke-ArtifactVerification.ps1' @{HandoffRoot=$HandoffRoot; EvidenceRoot=$EvidenceRoot}
        Invoke-ScriptChecked 'Invoke-Materialization.ps1' $common
        $handoff = Get-Content -Raw -LiteralPath (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json') | ConvertFrom-Json
        $appRoot = Join-Path $TestRoot ('install\releases\' + [string]$handoff.release_id)
        Invoke-ScriptChecked 'Invoke-LifecycleMatrix.ps1' @{AppRoot=$appRoot; EvidenceRoot=$EvidenceRoot; CaseId=($(if($Mode -eq 'FinalIdentity'){'W14'}else{'W03'})); DifferentCwd=$TestRoot; PolluteEnvironment=$true}
    }
}
