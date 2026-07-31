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
try{
    $manifest=Read-ENV1B3Json $ProbeManifestPath
    $actualContractSha=Get-ENV1B3Sha256 $ContractPath
    if($actualContractSha-ne[string]$manifest.matrix_contract_sha256){throw[InvalidOperationException]::new('ENV1B3_MATRIX_CONTRACT_INVALID|hash')}
    $contracts=Read-ENV1B3MatrixContracts $ContractPath
    $scope=@('W05','W08','W09','W10','W11','W13');$caseResults=@();$overall=$true
    foreach($caseId in $scope){
        $case=$contracts.cases[$caseId];$caseRoot=Join-Path $MatrixEvidenceRoot $caseId
        $subRoot=Join-Path $caseRoot (Join-Path 'subchecks' $caseId)
        $files=@(Get-ChildItem -LiteralPath $subRoot -File -Filter '*.json' -ErrorAction SilentlyContinue)
        $names=@($files|ForEach-Object{$_.BaseName});$casefold=@($names|Group-Object {$_.ToLowerInvariant()}|Where-Object{$_.Count-ne1})
        $expected=@($case.mandatory_subchecks|ForEach-Object{[string]$_});$missing=@($expected|Where-Object{$_-notin$names});$unexpected=@($names|Where-Object{$_-notin$expected})
        $records=@();$fields=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach($file in $files){
            $record=Read-ENV1B3Json $file.FullName;$records+=$record
            foreach($property in $record.evidence.PSObject.Properties){[void]$fields.Add($property.Name)}
        }
        $requiredMissing=@($case.required_evidence_fields|Where-Object{-not$fields.Contains([string]$_)})
        $contextMissing=@($case.required_execution_context|Where-Object{-not$fields.Contains('execution_context_'+[string]$_)})
        $fixtureMissing=@($case.required_fixtures|Where-Object{-not$fields.Contains('fixture_'+[string]$_)})
        $aggregatePath=Join-Path $caseRoot ($caseId+'.json');$aggregateValid=$false
        if(Test-Path -LiteralPath $aggregatePath -PathType Leaf){
            $aggregate=Read-ENV1B3Json $aggregatePath
            $expectedResult=$(if(@($records|Where-Object{$_.result-eq'FAIL'}).Count){'FAIL'}elseif(@($records|Where-Object{$_.result-eq'BLOCKED'}).Count){'BLOCKED'}elseif($records.Count-eq$expected.Count){'PASS'}else{'FAIL'})
            $aggregateValid=$aggregate.result-eq$expectedResult
        }
        $pass=$missing.Count-eq0-and$unexpected.Count-eq0-and$casefold.Count-eq0-and$requiredMissing.Count-eq0-and$contextMissing.Count-eq0-and$fixtureMissing.Count-eq0-and$aggregateValid
        if(-not$pass){$overall=$false}
        $caseResults+=[ordered]@{case_id=$caseId;result=$(if($pass){'PASS'}else{'FAIL'});missing_subchecks=$missing;unexpected_subchecks=$unexpected;duplicate_subchecks=@($casefold|ForEach-Object{$_.Name});missing_fields=$requiredMissing;missing_context=$contextMissing;missing_fixtures=$fixtureMissing;aggregate_consistent=$aggregateValid}
    }
    $document=[ordered]@{schema_version='env-1b3-matrix-contract-audit-v1';result=$(if($overall){'PASS'}else{'FAIL'});code=$(if($overall){'ENV1B3_MATRIX_CONTRACT_AUDIT_PASS'}else{'ENV1B3_MATRIX_CONTRACT_AUDIT_FAILED'});matrix_contract_sha256=$actualContractSha;cases=$caseResults;exit_code=$(if($overall){0}else{2})}
    [IO.Directory]::CreateDirectory($EvidenceRoot)|Out-Null
    [IO.File]::WriteAllText((Join-Path $EvidenceRoot 'MATRIX-CONTRACT-AUDIT.json'),($document|ConvertTo-Json -Depth 14 -Compress)+"`n",[Text.UTF8Encoding]::new($false))
    $document|ConvertTo-Json -Depth 14 -Compress
    if(-not$overall){exit 2}
}catch{
    $code='ENV1B3_MATRIX_CONTRACT_AUDIT_FAILED';if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{schema_version='env-1b3-matrix-contract-audit-v1';result='FAIL';code=$code;exit_code=2}|ConvertTo-Json -Compress;exit 2
}
