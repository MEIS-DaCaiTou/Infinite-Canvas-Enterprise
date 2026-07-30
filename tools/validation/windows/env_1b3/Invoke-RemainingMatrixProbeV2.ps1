[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('W02','W03','W04','W05','W06','W07','W08','W09','W10','W11StoppedPrepare','W11StoppedResume','W11RunningPrepare','W11RunningResume','W12','W13','W14Prepare','W14Validate','M01')][string]$Mode,
    [Parameter(Mandatory)][string]$CandidateHandoffZip,
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [string]$AppRoot,[string]$SourceInstallRoot,[string]$CaseRoot,[string]$DeniedRoot,[string]$IsolatedLowDiskRoot,[int]$Port=18000,[string]$CandidateId
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
$here=Split-Path -Parent $MyInvocation.MyCommand.Path
Import-Module (Join-Path $here 'validation-kit\ENV1B3.Validation.psm1') -Force
try{
    $stage='probe_manifest';$manifestPath=Join-Path $here 'PROBE-MANIFEST.json';$probe=Read-ENV1B3Json $manifestPath
    if($probe.schema_version-ne'env-1b3-remaining-matrix-probe-v2'-or$probe.diagnostic_only-ne$true-or$probe.not_a_release_candidate-ne$true-or$probe.cannot_support_final_acceptance-ne$true-or$probe.production_approved-ne$false){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_PROBE_IDENTITY_INVALID|probe')}
    $stage='probe_sums';$sums=Read-ENV1B3Sums -LiteralPath (Join-Path $here 'SHA256SUMS') -Root $here;$actual=@(Get-ChildItem -LiteralPath $here -File -Recurse -Force|Where-Object{$_.FullName-ne(Join-Path $here 'SHA256SUMS')});if($actual.Count-ne$sums.Count){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_PROBE_SUMS_INVALID|closure')}
    $stage='candidate_zip';if((Get-ENV1B3Sha256 $CandidateHandoffZip)-ne[string]$probe.expected_candidate_handoff_sha256){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_CANDIDATE_HASH_MISMATCH|candidate')}
    $stage='candidate_identity';$handoff=Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json');if([string]$handoff.candidate_id-ne[string]$probe.expected_candidate_id){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_CANDIDATE_IDENTITY_MISMATCH|candidate')}
    if([string]::IsNullOrWhiteSpace($CandidateId)){$CandidateId=[string]$probe.expected_candidate_id}elseif($CandidateId-ne[string]$probe.expected_candidate_id){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_CANDIDATE_IDENTITY_MISMATCH|argument')}
    if([string]::IsNullOrWhiteSpace($AppRoot)){$AppRoot=Join-Path $TestRoot ('install\releases\'+[string]$handoff.release_id)}
    $contractPath=Join-Path $here 'validation-kit\matrix-contracts.json';if((Get-ENV1B3Sha256 $contractPath)-ne[string]$probe.matrix_contract_sha256){throw[InvalidOperationException]::new('ENV1B3_MATRIX_CONTRACT_INVALID|hash')};[void](Read-ENV1B3MatrixContracts $contractPath)
    $stage='case_dispatch';$arguments=@{Mode=$Mode;HandoffRoot=$HandoffRoot;TestRoot=$TestRoot;EvidenceRoot=$EvidenceRoot;ContractPath=$contractPath;DiagnosticProbeManifestPath=$manifestPath;AppRoot=$AppRoot;SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;DeniedRoot=$DeniedRoot;IsolatedLowDiskRoot=$IsolatedLowDiskRoot;Port=$Port;CandidateId=$CandidateId}
    & (Join-Path $here 'validation-kit\Invoke-MatrixContractCase.ps1') @arguments
    if(-not$?){exit 2}
}catch{
    $code='ENV1B3_REMAINING_MATRIX_PROBE_V2_FAILED';if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{schema_version='env-1b3-probe-error-v1';status='blocked';code=$code;step=$stage;exit_code=2}|ConvertTo-Json -Compress;exit 2
}
