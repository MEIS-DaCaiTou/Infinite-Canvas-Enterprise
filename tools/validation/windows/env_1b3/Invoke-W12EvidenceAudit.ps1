[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProbeManifestPath,
    [Parameter(Mandatory)][string]$ProbeV2EvidenceZip,
    [Parameter(Mandatory)][string]$W12EvidenceRoot,
    [Parameter(Mandatory)][string]$CandidateId,
    [Parameter(Mandatory)][string]$EvidenceRoot
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
$task='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE'
$matrix='env-1b3-windows-validation-matrix-v1'
try{
    $manifest=Read-ENV1B3Json $ProbeManifestPath
    $probeSha=Get-ENV1B3Sha256 $ProbeV2EvidenceZip
    $aggregatePath=Join-Path $W12EvidenceRoot 'W12.json'
    $w12Sha=Get-ENV1B3Sha256 $aggregatePath
    if($probeSha-ne[string]$manifest.expected_probe_v2_evidence_sha256-or$w12Sha-ne[string]$manifest.expected_w12_evidence_sha256-or$CandidateId-ne[string]$manifest.expected_candidate_id){throw 'ENV1B3_W12_EVIDENCE_BINDING_INVALID|identity'}
    $aggregate=Read-ENV1B3Json $aggregatePath
    if($aggregate.schema_version-ne'env-1b3-case-result-v1'-or$aggregate.overall_task_id-ne$task-or$aggregate.matrix_version-ne$matrix-or$aggregate.case_id-ne'W12'-or$aggregate.result-ne'PASS'){throw 'ENV1B3_W12_EVIDENCE_BINDING_INVALID|aggregate'}
    $expected=@('archive_preflight_low_space','materialization_low_space','writable_root_low_space','pointer_atomicity')
    $fields=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach($id in $expected){
        $path=Join-Path $W12EvidenceRoot (Join-Path 'subchecks\W12' ($id+'.json'));$record=Read-ENV1B3Json $path
        if($record.schema_version-ne'env-1b3-subcheck-result-v1'-or$record.overall_task_id-ne$task-or$record.matrix_version-ne$matrix-or$record.case_id-ne'W12'-or$record.subcheck_id-ne$id-or$record.result-ne'PASS'){throw 'ENV1B3_W12_EVIDENCE_BINDING_INVALID|subcheck'}
        foreach($property in $record.evidence.PSObject.Properties){if($null-ne$property.Value-and($property.Value-isnot[string]-or-not[String]::IsNullOrWhiteSpace([string]$property.Value))){[void]$fields.Add($property.Name)}}
    }
    foreach($required in @('no_final_app_root','pointer_unchanged','pointer_temp_absent')){if(-not$fields.Contains($required)){throw 'ENV1B3_W12_EVIDENCE_BINDING_INVALID|field'}}
    $recovery=Read-ENV1B3Json (Join-Path $W12EvidenceRoot 'w12-recovery-materialization\W02.json')
    $pointer=Read-ENV1B3Json (Join-Path $W12EvidenceRoot 'subchecks\W12\pointer_atomicity.json')
    $passed=$recovery.result-eq'PASS'-and$pointer.evidence.pointer_unchanged-eq$true-and$pointer.evidence.pointer_temp_absent-eq$true
    $document=[ordered]@{schema_version='env-1b3-w12-evidence-audit-v2';overall_task_id=$task;matrix_version=$matrix;case_id='W12';result=$(if($passed){'PASS'}else{'FAIL'});code=$(if($passed){'ENV1B3_W12_EVIDENCE_AUDIT_PASS'}else{'ENV1B3_W12_EVIDENCE_AUDIT_FAILED'});candidate_id=$CandidateId;probe_v2_evidence_sha256=$probeSha;w12_evidence_sha256=$w12Sha;retry_after_cleanup_passed=($recovery.result-eq'PASS');pointer_unchanged=[bool]$pointer.evidence.pointer_unchanged;pointer_temp_absent=[bool]$pointer.evidence.pointer_temp_absent;exit_code=$(if($passed){0}else{2})}
    [IO.Directory]::CreateDirectory($EvidenceRoot)|Out-Null;[IO.File]::WriteAllText((Join-Path $EvidenceRoot 'W12-EVIDENCE-AUDIT.json'),($document|ConvertTo-Json -Compress)+"`n",[Text.UTF8Encoding]::new($false));$document|ConvertTo-Json -Compress
    if(-not$passed){exit 2}
}catch{
    $code='ENV1B3_W12_EVIDENCE_AUDIT_FAILED';if($_.Exception.Message-match'(ENV1B3_[A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{schema_version='env-1b3-w12-evidence-audit-v2';result='FAIL';code=$code;exit_code=2}|ConvertTo-Json -Compress;exit 2
}
