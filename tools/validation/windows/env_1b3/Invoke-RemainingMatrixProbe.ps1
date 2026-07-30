[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('W02','W03','W04','W05','W06','W07','W08','W09','W10','W11','W14','M01')][string]$Mode,
    [Parameter(Mandatory)][string]$CandidateHandoffZip,
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [string]$AppRoot,[string]$SourceInstallRoot,[string]$CaseRoot,[string]$DeniedRoot,[int]$Port=18000,[string]$CandidateId
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
$here=Split-Path -Parent $MyInvocation.MyCommand.Path
Import-Module (Join-Path $here 'validation-kit\ENV1B3.Validation.psm1') -Force

try{
    $stage='probe_manifest'
    $manifestPath=Join-Path $here 'PROBE-MANIFEST.json'
    $probe=Read-ENV1B3Json $manifestPath
    if($probe.schema_version -ne 'env-1b3-remaining-matrix-probe-v1' -or $probe.diagnostic_only -ne $true -or
       $probe.not_a_release_candidate -ne $true -or $probe.cannot_support_final_acceptance -ne $true -or $probe.production_approved -ne $false){
        throw [InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_PROBE_IDENTITY_INVALID|probe')
    }
    $stage='probe_sums'
    $sums=Read-ENV1B3Sums -LiteralPath (Join-Path $here 'SHA256SUMS') -Root $here
    $actual=@(Get-ChildItem -LiteralPath $here -File -Recurse -Force|Where-Object{$_.FullName -ne (Join-Path $here 'SHA256SUMS')})
    if($actual.Count -ne $sums.Count){throw [InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_PROBE_SUMS_INVALID|closure')}
    $stage='candidate_zip'
    if((Get-ENV1B3Sha256 $CandidateHandoffZip) -ne [string]$probe.expected_candidate_handoff_sha256){throw [InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_CANDIDATE_HASH_MISMATCH|candidate')}
    $stage='candidate_identity'
    $handoff=Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json')
    if([string]$handoff.candidate_id -ne [string]$probe.expected_candidate_id){throw [InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_CANDIDATE_IDENTITY_MISMATCH|candidate')}
    $entry=Join-Path $here 'validation-kit\Invoke-ENV1B3Validation.ps1'
    $stage='case_dispatch'
    if($Mode -eq 'W02'){
        & (Join-Path $here 'validation-kit\Invoke-Materialization.ps1') -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot $EvidenceRoot -CaseId W02 -DiagnosticProbeManifestPath $manifestPath
    }elseif($Mode -eq 'M01'){
        & (Join-Path $here 'validation-kit\Invoke-MaterializationAtomicityProbe.ps1') -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot $EvidenceRoot -ProbeManifestPath $manifestPath
    }else{
        $map=@{W03='Lifecycle';W04='UnicodeLifecycle';W05='LongPathMaterialize';W06='Permission';W07='OfflinePollution';W08='Tamper';W09='OwnedStop';W10='PortConflict';W11='RebootPrepare';W14='FinalIdentity'}
        $arguments=@{Mode=$map[$Mode];HandoffRoot=$HandoffRoot;TestRoot=$TestRoot;EvidenceRoot=$EvidenceRoot;AppRoot=$AppRoot;SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;DeniedRoot=$DeniedRoot;Port=$Port;CandidateId=$CandidateId;DiagnosticProbeManifestPath=$manifestPath}
        & $entry @arguments
    }
    if(-not $?){exit 2}
}catch{
    $code='ENV1B3_REMAINING_MATRIX_PROBE_FAILED';if($_.Exception.Message -match '^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{schema_version='env-1b3-probe-error-v1';status='blocked';code=$code;step=$stage;exit_code=2}|ConvertTo-Json -Compress
    exit 2
}
