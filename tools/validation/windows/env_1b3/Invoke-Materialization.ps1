[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [ValidateSet('W02','W05')][string]$CaseId = 'W02',
    [string]$DiagnosticProbeManifestPath
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Materialization.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

try {
    $handoff = Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json')
    $verifierName = $null
    $verifierHash = $null
    if (-not [String]::IsNullOrWhiteSpace($DiagnosticProbeManifestPath)) {
        $probe = Read-ENV1B3Json $DiagnosticProbeManifestPath
        if ([string]$probe.schema_version -notin @('env-1b3-remaining-matrix-probe-v1','env-1b3-remaining-matrix-probe-v2') -or
            $probe.diagnostic_only -ne $true -or $probe.not_a_release_candidate -ne $true -or
            $probe.cannot_support_final_acceptance -ne $true -or $probe.production_approved -ne $false -or
            [string]$probe.expected_candidate_id -ne [string]$handoff.candidate_id) {
            throw [InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_PROBE_IDENTITY_INVALID|probe')
        }
        $verifierName = [string]$probe.materialized_verifier_filename
        $verifierHash = [string]$probe.materialized_verifier_sha256
    } else {
        $verifierName = [string]$handoff.materialized_verifier_filename
        $verifierHash = [string]$handoff.materialized_verifier_sha256
    }
    if ($verifierName -ne 'validation-kit/verify_materialized_release.py' -or $verifierHash -notmatch '^[0-9a-f]{64}$') {
        throw [InvalidOperationException]::new('ENV1B3_MATERIALIZED_VERIFIER_BINDING_INVALID|verifier')
    }
    $verifierPath = Join-Path $HandoffRoot ($verifierName.Replace('/',[IO.Path]::DirectorySeparatorChar))
    if (-not [String]::IsNullOrWhiteSpace($DiagnosticProbeManifestPath)) {
        $verifierPath = Join-Path $PSScriptRoot 'verify_materialized_release.py'
    }
    $result = Invoke-ENV1B3AtomicMaterialization -HandoffRoot $HandoffRoot -TestRoot $TestRoot -VerifierPath $verifierPath -ExpectedVerifierSha256 $verifierHash
    $record = Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -Result 'PASS' -Code 'ENV1B3_MATERIALIZATION_PASS' -Evidence @{
        candidate_id=$result.candidate_id
        release_id=$result.release_id
        materialized_verify_exit=$result.materialized_verify_exit
        fixed_python_basename='python.exe'
        payload_tree_sha256=$result.payload_tree_sha256
        app_root_symbol='<APP_ROOT>'
        install_root_symbol='<TEST_ROOT>/install'
        staging_verified_before_final_move=$true
        pointer_committed_after_materialized_verify=$true
    }
    $record | ConvertTo-Json -Depth 8 -Compress
} catch {
    $code = 'ENV1B3_MATERIALIZATION_FAILED'
    if ($_.Exception.Message -match '^([A-Z0-9_]+)\|') { $code = $Matches[1] }
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -Result 'FAIL' -Code $code -Evidence @{} | ConvertTo-Json -Compress
    exit 2
}
