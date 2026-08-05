[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][string]$OutputRoot
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
try {
    [void](Assert-ENV1B3AbsoluteSafePath $EvidenceRoot)
    [void](Assert-ENV1B3AbsoluteSafePath $OutputRoot -AllowMissingLeaf)
    $handoff=Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json')
    $results=@()
    foreach($number in 1..14){
        $caseId='W{0:d2}' -f $number
        $path=Join-Path $EvidenceRoot ($caseId+'.json')
        if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw [InvalidOperationException]::new('ENV1B3_MATRIX_INCOMPLETE|'+$caseId)}
        $record=Read-ENV1B3Json $path
        if($record.case_id -ne $caseId -or $record.result -ne 'PASS'){throw [InvalidOperationException]::new('ENV1B3_MATRIX_NOT_PASS|'+$caseId)}
        $results+=$record
    }
    $summary=[ordered]@{schema_version='env-1b3-test-host-result-v1';overall_task_id='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE';candidate_id=[string]$handoff.candidate_id;matrix_version=[string]$handoff.validation_matrix_version;passed=14;failed=0;blocked=0;result='pass';production_touched=$false;repository_modified=$false}
    [IO.File]::WriteAllText((Join-Path $EvidenceRoot 'TEST-HOST-RESULT.json'),($summary|ConvertTo-Json -Compress)+"`n",[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $EvidenceRoot 'MATRIX-RESULTS.json'),([ordered]@{schema_version='env-1b3-matrix-results-v1';candidate_id=[string]$handoff.candidate_id;results=$results}|ConvertTo-Json -Depth 15 -Compress)+"`n",[Text.UTF8Encoding]::new($false))
    $forbidden=@('.env','.db','.sqlite','.sqlite3','.log','.key','.pem','.pfx')
    $files=@(Get-ChildItem -LiteralPath $EvidenceRoot -File -Recurse | Sort-Object FullName)
    foreach($file in $files){if($forbidden -contains $file.Extension.ToLowerInvariant()){throw [InvalidOperationException]::new('ENV1B3_EVIDENCE_FORBIDDEN_FILE|file')}}
    $sumLines=@()
    foreach($file in $files){$relative=$file.FullName.Substring($EvidenceRoot.Length).TrimStart('\').Replace('\','/');$sumLines+=(Get-ENV1B3Sha256 $file.FullName)+'  '+$relative}
    [IO.File]::WriteAllText((Join-Path $EvidenceRoot 'SHA256SUMS'),($sumLines -join "`n")+"`n",[Text.UTF8Encoding]::new($false))
    [IO.Directory]::CreateDirectory($OutputRoot)|Out-Null
    $zip=Join-Path $OutputRoot ('ENV-1B3-'+[string]$handoff.candidate_id+'-TEST-HOST-EVIDENCE.zip')
    if(Test-Path -LiteralPath $zip){throw [InvalidOperationException]::new('ENV1B3_EVIDENCE_ZIP_EXISTS|zip')}
    Compress-Archive -Path (Join-Path $EvidenceRoot '*') -DestinationPath $zip -CompressionLevel Optimal
    [ordered]@{result='pass';candidate_id=[string]$handoff.candidate_id;evidence_zip=[IO.Path]::GetFileName($zip);sha256=(Get-ENV1B3Sha256 $zip)}|ConvertTo-Json -Compress
} catch {
    $code='ENV1B3_EVIDENCE_EXPORT_FAILED';if($_.Exception.Message -match '^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{status='blocked';code=$code}|ConvertTo-Json -Compress;exit 2
}
