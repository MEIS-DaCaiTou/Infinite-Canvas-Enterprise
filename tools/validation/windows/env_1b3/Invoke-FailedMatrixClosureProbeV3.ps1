[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('W05','W08','W09','W10','W11StoppedPrepare','W11StoppedResume','W11RunningPrepare','W11RunningResume','W12EvidenceAudit','W13','ContractAudit')][string]$Mode,
    [Parameter(Mandatory)][string]$CandidateHandoffZip,
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [string]$SourceInstallRoot,[string]$CaseRoot,[string]$W12EvidenceRoot,[string]$MatrixEvidenceRoot,[int]$Port=18000,
    [ValidateSet('graceful_guest_reboot','hyperv_hard_reset')][string]$RebootKind='graceful_guest_reboot'
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
$here=Split-Path -Parent $MyInvocation.MyCommand.Path
Import-Module (Join-Path $here 'validation-kit\ENV1B3.Validation.psm1') -Force
function Quote-Argument([string]$Value){'"'+$Value.Replace('"','\"')+'"'}
function Invoke-Child([string]$Script,[hashtable]$Parameters){
    $parts=@('-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Quote-Argument $Script))
    foreach($key in $Parameters.Keys|Sort-Object){if($null-ne$Parameters[$key]-and[string]$Parameters[$key]-ne''){$parts+=('-'+$key);$parts+=(Quote-Argument ([string]$Parameters[$key]))}}
    $ps=Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell\v1.0\powershell.exe'
    Invoke-ENV1B3ManagedProcess -FileName $ps -Arguments ($parts-join' ') -WorkingDirectory $here -TimeoutSeconds 900
}
try{
    $stage='probe_manifest';$manifestPath=Join-Path $here 'PROBE-MANIFEST.json';$probe=Read-ENV1B3Json $manifestPath
    if($probe.schema_version-ne'env-1b3-failed-matrix-closure-probe-v3'-or$probe.diagnostic_only-ne$true-or$probe.not_a_release_candidate-ne$true-or$probe.cannot_support_final_acceptance-ne$true-or$probe.production_approved-ne$false){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_PROBE_IDENTITY_INVALID|probe')}
    $stage='probe_sums';$sums=Read-ENV1B3Sums -LiteralPath (Join-Path $here 'SHA256SUMS') -Root $here;$actual=@(Get-ChildItem -LiteralPath $here -File -Recurse -Force|Where-Object{$_.FullName-ne(Join-Path $here 'SHA256SUMS')});if($actual.Count-ne$sums.Count){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_PROBE_SUMS_INVALID|closure')}
    $stage='candidate_zip';if((Get-ENV1B3Sha256 $CandidateHandoffZip)-ne[string]$probe.expected_candidate_handoff_sha256){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_CANDIDATE_HASH_MISMATCH|candidate')}
    $handoff=Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json');if([string]$handoff.candidate_id-ne[string]$probe.expected_candidate_id){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_CANDIDATE_IDENTITY_MISMATCH|candidate')}
    $contract=Join-Path $here 'validation-kit\matrix-contracts.json';if((Get-ENV1B3Sha256 $contract)-ne[string]$probe.matrix_contract_sha256){throw[InvalidOperationException]::new('ENV1B3_MATRIX_CONTRACT_INVALID|hash')}
    $appRoot=Join-Path $TestRoot ('install\releases\'+[string]$handoff.release_id);$kit=Join-Path $here 'validation-kit'
    $stage='case_dispatch'
    if($Mode-eq'ContractAudit'){
        $r=Invoke-Child (Join-Path $kit 'Invoke-MatrixContractAudit.ps1') @{ProbeManifestPath=$manifestPath;ContractPath=$contract;MatrixEvidenceRoot=$MatrixEvidenceRoot;EvidenceRoot=$EvidenceRoot}
    }elseif($Mode-eq'W12EvidenceAudit'){
        $r=Invoke-Child (Join-Path $kit 'Invoke-W12EvidenceAudit.ps1') @{W12EvidenceRoot=$W12EvidenceRoot;EvidenceRoot=$EvidenceRoot}
    }else{
        $caseMode=$Mode
        $r=Invoke-Child (Join-Path $kit 'Invoke-MatrixContractCase.ps1') @{Mode=$caseMode;HandoffRoot=$HandoffRoot;TestRoot=$TestRoot;EvidenceRoot=$EvidenceRoot;ContractPath=$contract;DiagnosticProbeManifestPath=$manifestPath;AppRoot=$appRoot;SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;Port=$Port;CandidateId=[string]$probe.expected_candidate_id;RebootKind=$RebootKind}
    }
    if($r.timed_out-or$r.exit_code-ne0){[ordered]@{schema_version='env-1b3-probe-v3-result-v1';result='FAIL';code=$(if($r.timed_out){'ENV1B3_PUBLIC_MODE_TIMEOUT'}else{'ENV1B3_PUBLIC_MODE_FAILED'});mode=$Mode;exit_code=2}|ConvertTo-Json -Compress;exit 2}
    [ordered]@{schema_version='env-1b3-probe-v3-result-v1';result='PASS';code='ENV1B3_PUBLIC_MODE_PASS';mode=$Mode;exit_code=0}|ConvertTo-Json -Compress
    exit 0
}catch{
    $code='ENV1B3_FAILED_MATRIX_PROBE_V3_FAILED';if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{schema_version='env-1b3-probe-v3-result-v1';result='BLOCKED';code=$code;step=$stage;mode=$Mode;exit_code=2}|ConvertTo-Json -Compress;exit 2
}
