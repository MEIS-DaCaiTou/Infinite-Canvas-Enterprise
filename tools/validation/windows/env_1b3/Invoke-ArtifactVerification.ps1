[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
try {
    $result = Test-ENV1B3Handoff -HandoffRoot $HandoffRoot
    $record = Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W02-artifact' -Result 'PASS' -Code 'ENV1B3_ARTIFACT_VERIFY_PASS' -Evidence @{
        candidate_id=$result.candidate_id
        release_id=$result.release_id
        archive_sha256=$result.artifact.archive_sha256
        manifest_sha256=$result.artifact.manifest_sha256
        inventory_sha256=$result.artifact.inventory_sha256
        payload_tree_sha256=$result.artifact.payload_tree_sha256
        file_count=$result.artifact.file_count
        offline_verified=$true
    }
    $record | ConvertTo-Json -Depth 8 -Compress
} catch {
    $code = 'ENV1B3_ARTIFACT_VERIFY_FAILED'
    if ($_.Exception.Message -match '^([A-Z0-9_]+)\|') { $code = $Matches[1] }
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W02-artifact' -Result 'FAIL' -Code $code -Evidence @{} | ConvertTo-Json -Compress
    exit 2
}
