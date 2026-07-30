[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][string]$ProbeManifestPath
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Materialization.psm1') -Force

try {
    $probe=Read-ENV1B3Json $ProbeManifestPath
    $handoff=Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json')
    if($probe.schema_version -ne 'env-1b3-remaining-matrix-probe-v1' -or
       $probe.expected_candidate_id -ne $handoff.candidate_id -or
       $probe.diagnostic_only -ne $true -or $probe.not_a_release_candidate -ne $true -or
       $probe.cannot_support_final_acceptance -ne $true -or $probe.production_approved -ne $false){
        throw [InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_PROBE_IDENTITY_INVALID|probe')
    }
    $verifier=Join-Path $PSScriptRoot 'verify_materialized_release.py'
    $verifierHash=[string]$probe.materialized_verifier_sha256
    $releaseId=[string]$handoff.release_id
    $results=@()
    foreach($withOldPointer in @($false,$true)){
        foreach($fault in @('Extraction','Verifier','FinalMove','PointerWrite')){
            $caseRoot=Join-Path $TestRoot ('m01-'+$(if($withOldPointer){'old'}else{'none'})+'-'+$fault.ToLowerInvariant())
            [IO.Directory]::CreateDirectory((Join-Path $caseRoot 'install\state'))|Out-Null
            $pointer=Join-Path $caseRoot 'install\state\current-release.json'
            $oldBytes=$null
            if($withOldPointer){
                $oldBytes=[Text.UTF8Encoding]::new($false).GetBytes('{"schema_version":"fixture-old-pointer"}' + "`n")
                [IO.File]::WriteAllBytes($pointer,$oldBytes)
            }
            $failed=$false
            try {
                Invoke-ENV1B3AtomicMaterialization -HandoffRoot $HandoffRoot -TestRoot $caseRoot -VerifierPath $verifier -ExpectedVerifierSha256 $verifierHash -FaultInjection $fault | Out-Null
            } catch { $failed=$true }
            $partial=Join-Path $caseRoot ('install\staging\'+$releaseId+'.partial')
            $final=Join-Path $caseRoot ('install\releases\'+$releaseId)
            $temp=$pointer+'.new'
            $pointerPreserved=if($withOldPointer){
                (Test-Path -LiteralPath $pointer -PathType Leaf) -and [Convert]::ToBase64String([IO.File]::ReadAllBytes($pointer)) -eq [Convert]::ToBase64String($oldBytes)
            } else { -not (Test-Path -LiteralPath $pointer) }
            $pass=$failed -and $pointerPreserved -and -not (Test-Path -LiteralPath $partial) -and -not (Test-Path -LiteralPath $final) -and -not (Test-Path -LiteralPath $temp)
            $results+=[ordered]@{fault=$fault;old_pointer=$withOldPointer;pass=$pass}
        }
    }
    if(@($results|Where-Object{-not $_.pass}).Count -ne 0){throw [InvalidOperationException]::new('ENV1B3_MATERIALIZATION_ATOMICITY_FAILED|m01')}
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'M01' -Result 'PASS' -Code 'ENV1B3_MATERIALIZATION_ATOMICITY_PASS' -Evidence @{
        injected_cases=$results.Count;staging_cleaned=$true;final_app_root_absent=$true;pointer_preserved=$true;pointer_temp_cleaned=$true
    }|ConvertTo-Json -Depth 8 -Compress
}catch{
    $code='ENV1B3_MATERIALIZATION_ATOMICITY_FAILED';if($_.Exception.Message -match '^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'M01' -Result 'FAIL' -Code $code -Evidence @{}|ConvertTo-Json -Compress
    exit 2
}
