[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProbeManifestPath,
    [Parameter(Mandatory)][string]$ContractPath,
    [Parameter(Mandatory)][string]$MatrixEvidenceRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
$task='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE'
$matrix='env-1b3-windows-validation-matrix-v1'
function Test-Value([object]$Value){$null-ne$Value-and($Value-isnot[string]-or-not[String]::IsNullOrWhiteSpace([string]$Value))}
function Get-CanonicalSetSha256([Collections.IDictionary]$Hashes){
    $lines=@();foreach($key in @($Hashes.Keys|Sort-Object)){$lines+=([string]$key+'='+[string]$Hashes[$key])}
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($lines-join"`n")+"`n");$hasher=[Security.Cryptography.SHA256]::Create()
    try{return([BitConverter]::ToString($hasher.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()}finally{$hasher.Dispose()}
}
try{
    $manifest=Read-ENV1B3Json $ProbeManifestPath;$actualContractSha=Get-ENV1B3Sha256 $ContractPath
    if($actualContractSha-ne[string]$manifest.matrix_contract_sha256){throw[InvalidOperationException]::new('ENV1B3_MATRIX_CONTRACT_INVALID|hash')}
    $contracts=Read-ENV1B3MatrixContracts $ContractPath
    $scope=@('W05','W08','W09','W10','W11','W12','W13');$caseResults=@();$overall=$true
    foreach($caseId in $scope){
        if($caseId-eq'W12'){
            $audit=Read-ENV1B3Json (Join-Path $MatrixEvidenceRoot 'W12\W12-EVIDENCE-AUDIT.json')
            $subcheckHashProperties=@($audit.w12_subcheck_sha256s.PSObject.Properties)
            $subcheckHashesValid=$subcheckHashProperties.Count-eq4-and@($subcheckHashProperties|Where-Object{$_.Name-notin@('archive_preflight_low_space','materialization_low_space','writable_root_low_space','pointer_atomicity')-or[string]$_.Value-notmatch'^[0-9a-f]{64}$'}).Count-eq0
            $pass=$audit.schema_version-eq'env-1b3-w12-evidence-audit-v3'-and$audit.overall_task_id-eq$task-and$audit.matrix_version-eq$matrix-and$audit.case_id-eq'W12'-and$audit.result-eq'PASS'-and$audit.candidate_id-eq[string]$manifest.expected_candidate_id-and$audit.source_probe_v2_zip_sha256-eq[string]$manifest.expected_probe_v2_evidence_sha256-and$audit.candidate_handoff_sha256-eq[string]$manifest.expected_candidate_handoff_sha256-and$audit.candidate_modified-eq$false-and$audit.w12_aggregate_sha256-eq[string]$manifest.expected_w12_evidence_sha256-and[string]$audit.w12_evidence_set_sha256-match'^[0-9a-f]{64}$'-and[string]$audit.recovery_evidence_sha256-match'^[0-9a-f]{64}$'-and$subcheckHashesValid-and$audit.retry_after_cleanup_passed-eq$true
            if(-not$pass){$overall=$false};$caseResults+=[ordered]@{case_id='W12';result=$(if($pass){'PASS'}else{'FAIL'});supplemental_binding_valid=$pass};continue
        }
        $case=$contracts.cases[$caseId];$caseRoot=Join-Path $MatrixEvidenceRoot $caseId;$subRoot=Join-Path $caseRoot (Join-Path 'subchecks' $caseId)
        $files=@(Get-ChildItem -LiteralPath $subRoot -File -Filter '*.json' -ErrorAction SilentlyContinue)
        $names=@($files|ForEach-Object{$_.BaseName});$casefold=@($names|Group-Object{$_.ToLowerInvariant()}|Where-Object{$_.Count-ne1})
        $expected=@($case.mandatory_subchecks|ForEach-Object{[string]$_});$missing=@($expected|Where-Object{$_-notin$names});$unexpected=@($names|Where-Object{$_-notin$expected})
        $records=@();$invalidRecords=@();$values=@{}
        foreach($file in $files){
            $record=Read-ENV1B3Json $file.FullName;$records+=$record
            if($record.schema_version-ne'env-1b3-subcheck-result-v1'-or$record.overall_task_id-ne$task-or$record.matrix_version-ne$matrix-or$record.case_id-ne$caseId-or$record.subcheck_id-ne$file.BaseName-or$record.result-notin@('PASS','FAIL','BLOCKED')){$invalidRecords+=$file.BaseName}
            foreach($property in $record.evidence.PSObject.Properties){if(Test-Value $property.Value){$values[$property.Name]=$property.Value}}
        }
        $requiredMissing=@($case.required_evidence_fields|Where-Object{-not$values.ContainsKey([string]$_)})
        $contextMissing=@($case.required_execution_context|Where-Object{$values['execution_context_'+[string]$_]-ne$true})
        $fixtureMissing=@($case.required_fixtures|Where-Object{$values['fixture_'+[string]$_]-ne$true})
        $aggregateValid=$false;$aggregatePath=Join-Path $caseRoot ($caseId+'.json')
        if(Test-Path -LiteralPath $aggregatePath -PathType Leaf){
            $aggregate=Read-ENV1B3Json $aggregatePath;$listed=@($aggregate.evidence.subchecks)
            $listedIds=@($listed|ForEach-Object{[string]$_.subcheck_id})
            $aggregateValid=$aggregate.schema_version-eq'env-1b3-case-result-v1'-and$aggregate.overall_task_id-eq$task-and$aggregate.matrix_version-eq$matrix-and$aggregate.case_id-eq$caseId-and$aggregate.result-eq'PASS'-and@($records|Where-Object{$_.result-ne'PASS'}).Count-eq0-and@($listed|Where-Object{$_.result-ne'PASS'}).Count-eq0-and@($expected|Where-Object{$_-notin$listedIds}).Count-eq0-and$listedIds.Count-eq$expected.Count
            if($caseId-eq'W08'){
                $declared=@{};foreach($property in @($aggregate.evidence.source_evidence_sha256s.PSObject.Properties)){$declared[$property.Name]=[string]$property.Value}
                $actual=@{};foreach($id in $expected){$actual[$id]=Get-ENV1B3Sha256 (Join-Path $subRoot ($id+'.json'))}
                $hashesValid=$declared.Count-eq$expected.Count-and@($expected|Where-Object{-not$declared.ContainsKey($_)-or$declared[$_]-ne$actual[$_]}).Count-eq0
                $aggregateValid=$aggregateValid-and$aggregate.evidence.aggregation_source-eq'host_only_evidence_aggregator'-and$hashesValid-and[string]$aggregate.evidence.w08_evidence_set_sha256-match'^[0-9a-f]{64}$'-and$aggregate.evidence.w08_evidence_set_sha256-eq(Get-CanonicalSetSha256 $actual)
            }
        }
        $pass=$missing.Count-eq0-and$unexpected.Count-eq0-and$casefold.Count-eq0-and$invalidRecords.Count-eq0-and$requiredMissing.Count-eq0-and$contextMissing.Count-eq0-and$fixtureMissing.Count-eq0-and$aggregateValid
        if(-not$pass){$overall=$false}
        $caseResults+=[ordered]@{case_id=$caseId;result=$(if($pass){'PASS'}else{'FAIL'});missing_subchecks=$missing;unexpected_subchecks=$unexpected;duplicate_subchecks=@($casefold|ForEach-Object{$_.Name});invalid_records=$invalidRecords;missing_fields=$requiredMissing;invalid_context=$contextMissing;invalid_fixtures=$fixtureMissing;aggregate_consistent=$aggregateValid}
    }
    $document=[ordered]@{schema_version='env-1b3-matrix-contract-audit-v2';overall_task_id=$task;matrix_version=$matrix;result=$(if($overall){'PASS'}else{'FAIL'});code=$(if($overall){'ENV1B3_MATRIX_CONTRACT_AUDIT_PASS'}else{'ENV1B3_MATRIX_CONTRACT_AUDIT_FAILED'});matrix_contract_sha256=$actualContractSha;cases=$caseResults;exit_code=$(if($overall){0}else{2})}
    [IO.Directory]::CreateDirectory($EvidenceRoot)|Out-Null;[IO.File]::WriteAllText((Join-Path $EvidenceRoot 'MATRIX-CONTRACT-AUDIT.json'),($document|ConvertTo-Json -Depth 14 -Compress)+"`n",[Text.UTF8Encoding]::new($false));$document|ConvertTo-Json -Depth 14 -Compress
    if(-not$overall){exit 2}
}catch{
    $code='ENV1B3_MATRIX_CONTRACT_AUDIT_FAILED';if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{schema_version='env-1b3-matrix-contract-audit-v2';result='FAIL';code=$code;exit_code=2}|ConvertTo-Json -Compress;exit 2
}
