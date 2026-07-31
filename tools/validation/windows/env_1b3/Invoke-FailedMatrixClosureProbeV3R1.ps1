[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('W05','W08Pointer','W08ReleaseManifest','W08RuntimeManifest','W08Payload','W08PythonDll','W08Aggregate','W09','W10','W11StoppedPrepare','W11StoppedResume','W11RunningPrepare','W11RunningResume','W12EvidenceAudit','W13','ContractAudit')][string]$Mode,
    [Parameter(Mandatory)][string]$CandidateHandoffZip,
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [string]$SourceInstallRoot,[string]$CaseRoot,[string]$ProbeV2EvidenceZip,[string]$W12EvidenceRoot,[string]$MatrixEvidenceRoot,[int]$Port=18000,
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
function Read-FinalResult([string]$Text){
    $value=$null
    foreach($line in $Text.Split("`n")){
        try{$candidate=$line.TrimEnd("`r")|ConvertFrom-Json;if($null-ne$candidate-and$null-ne$candidate.PSObject.Properties['code']-and($null-ne$candidate.PSObject.Properties['result']-or$null-ne$candidate.PSObject.Properties['status'])){$value=$candidate}}catch{}
    }
    return $value
}
function Publish-ChildResult($Child,[string]$PublicMode){
    if($Child.timed_out){[ordered]@{schema_version='env-1b3-probe-v3r1-result-v1';result='FAIL';code='ENV1B3_PUBLIC_MODE_TIMEOUT';mode=$PublicMode;exit_code=2}|ConvertTo-Json -Compress;exit 2}
    $payload=Read-FinalResult ([string]$Child.stdout)
    if($null-eq$payload){[ordered]@{schema_version='env-1b3-probe-v3r1-result-v1';result='FAIL';code='ENV1B3_PUBLIC_MODE_OUTPUT_INVALID';mode=$PublicMode;exit_code=2}|ConvertTo-Json -Compress;exit 2}
    $raw=if($null-ne$payload.PSObject.Properties['result']){[string]$payload.result}else{[string]$payload.status}
    $result=$raw.ToUpperInvariant()
    if($result-notin@('PASS','FAIL','BLOCKED')){[ordered]@{schema_version='env-1b3-probe-v3r1-result-v1';result='FAIL';code='ENV1B3_PUBLIC_MODE_OUTPUT_INVALID';mode=$PublicMode;exit_code=2}|ConvertTo-Json -Compress;exit 2}
    $expectedExit=if($result-eq'PASS'){0}else{2}
    if([int]$Child.exit_code-ne$expectedExit){[ordered]@{schema_version='env-1b3-probe-v3r1-result-v1';result='FAIL';code='ENV1B3_PUBLIC_MODE_EXIT_CONTRACT_INVALID';mode=$PublicMode;exit_code=2}|ConvertTo-Json -Compress;exit 2}
    [ordered]@{schema_version='env-1b3-probe-v3r1-result-v1';result=$result;code=[string]$payload.code;mode=$PublicMode;exit_code=$expectedExit}|ConvertTo-Json -Compress
    exit $expectedExit
}
try{
    $stage='probe_manifest';$manifestPath=Join-Path $here 'PROBE-MANIFEST.json';$probe=Read-ENV1B3Json $manifestPath
    if($probe.schema_version-ne'env-1b3-failed-matrix-closure-probe-v3r1'-or$probe.diagnostic_only-ne$true-or$probe.not_a_release_candidate-ne$true-or$probe.cannot_support_final_acceptance-ne$true-or$probe.production_approved-ne$false){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_PROBE_IDENTITY_INVALID|probe')}
    $stage='probe_sums';$sums=Read-ENV1B3Sums -LiteralPath (Join-Path $here 'SHA256SUMS') -Root $here;$actual=@(Get-ChildItem -LiteralPath $here -File -Recurse -Force|Where-Object{$_.FullName-ne(Join-Path $here 'SHA256SUMS')});if($actual.Count-ne$sums.Count){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_PROBE_SUMS_INVALID|closure')}
    $stage='candidate_zip';if((Get-ENV1B3Sha256 $CandidateHandoffZip)-ne[string]$probe.expected_candidate_handoff_sha256){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_CANDIDATE_HASH_MISMATCH|candidate')}
    $handoff=Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json');if([string]$handoff.candidate_id-ne[string]$probe.expected_candidate_id){throw[InvalidOperationException]::new('ENV1B3_DIAGNOSTIC_CANDIDATE_IDENTITY_MISMATCH|candidate')}
    $contract=Join-Path $here 'validation-kit\matrix-contracts.json';if((Get-ENV1B3Sha256 $contract)-ne[string]$probe.matrix_contract_sha256){throw[InvalidOperationException]::new('ENV1B3_MATRIX_CONTRACT_INVALID|hash')}
    $appRoot=Join-Path $TestRoot ('install\releases\'+[string]$handoff.release_id);$kit=Join-Path $here 'validation-kit';$stage='case_dispatch'
    $w08Map=@{W08Pointer='Pointer';W08ReleaseManifest='ReleaseManifest';W08RuntimeManifest='RuntimeManifest';W08Payload='Payload';W08PythonDll='PythonDll'}
    if($w08Map.ContainsKey($Mode)){
        $r=Invoke-Child (Join-Path $kit 'Invoke-TamperMatrix.ps1') @{SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;EvidenceRoot=$EvidenceRoot;Mode=$w08Map[$Mode];ContractPath=$contract}
    }elseif($Mode-eq'ContractAudit'){
        $r=Invoke-Child (Join-Path $kit 'Invoke-MatrixContractAudit.ps1') @{ProbeManifestPath=$manifestPath;ContractPath=$contract;MatrixEvidenceRoot=$MatrixEvidenceRoot;EvidenceRoot=$EvidenceRoot}
    }elseif($Mode-eq'W12EvidenceAudit'){
        $r=Invoke-Child (Join-Path $kit 'Invoke-W12EvidenceAudit.ps1') @{ProbeManifestPath=$manifestPath;ProbeV2EvidenceZip=$ProbeV2EvidenceZip;W12EvidenceRoot=$W12EvidenceRoot;CandidateId=[string]$probe.expected_candidate_id;EvidenceRoot=$EvidenceRoot}
    }else{
        $caseMode=if($Mode-eq'W08Aggregate'){'W08'}else{$Mode}
        $r=Invoke-Child (Join-Path $kit 'Invoke-MatrixContractCase.ps1') @{Mode=$caseMode;HandoffRoot=$HandoffRoot;TestRoot=$TestRoot;EvidenceRoot=$EvidenceRoot;ContractPath=$contract;DiagnosticProbeManifestPath=$manifestPath;AppRoot=$appRoot;SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;Port=$Port;CandidateId=[string]$probe.expected_candidate_id;RebootKind=$RebootKind}
    }
    Publish-ChildResult $r $Mode
}catch{
    $code='ENV1B3_FAILED_MATRIX_PROBE_V3R1_FAILED';if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{schema_version='env-1b3-probe-v3r1-result-v1';result='BLOCKED';code=$code;step=$stage;mode=$Mode;exit_code=2}|ConvertTo-Json -Compress;exit 2
}
