[CmdletBinding()]
param([Parameter(Mandatory)][string]$W12EvidenceRoot,[Parameter(Mandatory)][string]$EvidenceRoot)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
try{
    $recovery=Read-ENV1B3Json (Join-Path $W12EvidenceRoot 'w12-recovery-materialization\W02.json')
    $pointer=Read-ENV1B3Json (Join-Path $W12EvidenceRoot 'subchecks\W12\pointer_atomicity.json')
    $passed=$recovery.result-eq'PASS'-and$pointer.evidence.pointer_unchanged-eq$true-and$pointer.evidence.pointer_temp_absent-eq$true
    $document=[ordered]@{schema_version='env-1b3-w12-evidence-audit-v1';result=$(if($passed){'PASS'}else{'FAIL'});code=$(if($passed){'ENV1B3_W12_EVIDENCE_AUDIT_PASS'}else{'ENV1B3_W12_EVIDENCE_AUDIT_FAILED'});retry_after_cleanup_passed=($recovery.result-eq'PASS');pointer_unchanged=[bool]$pointer.evidence.pointer_unchanged;pointer_temp_absent=[bool]$pointer.evidence.pointer_temp_absent;exit_code=$(if($passed){0}else{2})}
    [IO.Directory]::CreateDirectory($EvidenceRoot)|Out-Null;[IO.File]::WriteAllText((Join-Path $EvidenceRoot 'W12-EVIDENCE-AUDIT.json'),($document|ConvertTo-Json -Compress)+"`n",[Text.UTF8Encoding]::new($false));$document|ConvertTo-Json -Compress
    if(-not$passed){exit 2}
}catch{[ordered]@{schema_version='env-1b3-w12-evidence-audit-v1';result='FAIL';code='ENV1B3_W12_EVIDENCE_AUDIT_FAILED';exit_code=2}|ConvertTo-Json -Compress;exit 2}
