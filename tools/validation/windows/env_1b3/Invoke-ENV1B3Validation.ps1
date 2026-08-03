[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Full','FinalIdentity','Baseline','Verify','Materialize','Lifecycle','UnicodeLifecycle','LongPathMaterialize','Permission','OfflinePollution','Tamper','OwnedStop','ForeignStop','PortConflict','RebootPrepare','RebootResume','LowDisk','ArchiveLock','DefenderStatus','Export','W08PrepareHealthy','W08Pointer','W08ReleaseManifest','W08RuntimeManifest','W08Payload','W08PythonDll','W08Aggregate','W09','W10','W11StoppedPrepare','W11StoppedResume','W11RunningPrepare','W11RunningResume','W13','W14Prepare','W14Validate')][string]$Mode,
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [ValidateSet('fresh_vm_snapshot','fresh_physical_image','dedicated_clean_test_host')][string]$CleanHostClassification = 'dedicated_clean_test_host',
    [string]$AppRoot,
    [string]$SourceInstallRoot,
    [string]$CaseRoot,
    [string]$DeniedRoot,
    [string]$ArchivePath,
    [string]$IsolatedLowDiskRoot,
    [string]$CandidateId,
    [string]$DiagnosticProbeManifestPath,
    [string]$ContractPath,
    [int]$Port = 18000
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if([String]::IsNullOrWhiteSpace($ContractPath)){$ContractPath=Join-Path $here 'matrix-contracts.json'}

function Invoke-ScriptChecked([string]$Name, [hashtable]$Arguments) {
    $path = Join-Path $here $Name
    try {
        & $path @Arguments
        $powerShellSucceeded = $?
    } catch {
        [ordered]@{schema_version='env-1b3-entrypoint-error-v1';status='blocked';code='ENV1B3_ENTRYPOINT_POWERSHELL_STEP_FAILED';step=$Name;exit_code=2} | ConvertTo-Json -Compress
        exit 2
    }
    if (-not $powerShellSucceeded) {
        [ordered]@{schema_version='env-1b3-entrypoint-error-v1';status='blocked';code='ENV1B3_ENTRYPOINT_POWERSHELL_STEP_FAILED';step=$Name;exit_code=2} | ConvertTo-Json -Compress
        exit 2
    }
}

function Invoke-W14Process([string]$ChildMode) {
    $script = Join-Path $here 'Invoke-FinalIdentityMatrix.ps1'
    $items = @(
        '-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',('"'+$script+'"'),
        '-Mode',$ChildMode,'-HandoffRoot',('"'+$HandoffRoot+'"'),'-TestRoot',('"'+$TestRoot+'"'),
        '-EvidenceRoot',('"'+$EvidenceRoot+'"'),'-ContractPath',('"'+$ContractPath+'"')
    )
    if(-not[String]::IsNullOrWhiteSpace($DiagnosticProbeManifestPath)){$items+=@('-DiagnosticProbeManifestPath',('"'+$DiagnosticProbeManifestPath+'"'))}
    $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName='powershell.exe';$info.Arguments=($items-join' ')
    $info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
    $process=[Diagnostics.Process]::new();$process.StartInfo=$info
    try{if(-not$process.Start()){throw[InvalidOperationException]::new('ENV1B3_W14_PROCESS_START_FAILED')};$stdout=$process.StandardOutput.ReadToEnd();$stderr=$process.StandardError.ReadToEnd();$process.WaitForExit();$exitCode=[int]$process.ExitCode}finally{$process.Dispose()}
    if($stdout){[Console]::Out.Write($stdout)};if($stderr){[Console]::Error.Write($stderr)}
    if($exitCode-ne0){exit 2}
}

$common = @{HandoffRoot=$HandoffRoot; TestRoot=$TestRoot; EvidenceRoot=$EvidenceRoot; DiagnosticProbeManifestPath=$DiagnosticProbeManifestPath}
switch ($Mode) {
    'Baseline' { Invoke-ScriptChecked 'Invoke-EnvironmentBaseline.ps1' @{TestRoot=$TestRoot; EvidenceRoot=$EvidenceRoot; Classification=$CleanHostClassification} }
    'Verify' { Invoke-ScriptChecked 'Invoke-ArtifactVerification.ps1' @{HandoffRoot=$HandoffRoot; EvidenceRoot=$EvidenceRoot} }
    'Materialize' { Invoke-ScriptChecked 'Invoke-Materialization.ps1' $common }
    'Lifecycle' {
        $handoff = Get-Content -Raw -LiteralPath (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json') | ConvertFrom-Json
        $appRoot = Join-Path $TestRoot ('install\releases\' + [string]$handoff.release_id)
        Invoke-ScriptChecked 'Invoke-LifecycleMatrix.ps1' @{AppRoot=$appRoot; EvidenceRoot=$EvidenceRoot; CaseId='W03'; DifferentCwd=$TestRoot}
    }
    'UnicodeLifecycle' {
        Invoke-ScriptChecked 'Invoke-Materialization.ps1' $common
        $handoff = Get-Content -Raw -LiteralPath (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json') | ConvertFrom-Json
        $caseAppRoot = Join-Path $TestRoot ('install\releases\' + [string]$handoff.release_id)
        Invoke-ScriptChecked 'Invoke-LifecycleMatrix.ps1' @{AppRoot=$caseAppRoot; EvidenceRoot=$EvidenceRoot; CaseId='W04'; DifferentCwd=([IO.Path]::GetPathRoot($TestRoot)); PolluteEnvironment=$true}
    }
    'LongPathMaterialize' {
        Invoke-ScriptChecked 'Invoke-Materialization.ps1' @{HandoffRoot=$HandoffRoot;TestRoot=$TestRoot;EvidenceRoot=$EvidenceRoot;CaseId='W05';DiagnosticProbeManifestPath=$DiagnosticProbeManifestPath}
        $handoff = Get-Content -Raw -LiteralPath (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json') | ConvertFrom-Json
        $caseAppRoot = Join-Path $TestRoot ('install\releases\' + [string]$handoff.release_id)
        Invoke-ScriptChecked 'Invoke-LifecycleMatrix.ps1' @{AppRoot=$caseAppRoot;EvidenceRoot=$EvidenceRoot;CaseId='W05';DifferentCwd=([IO.Path]::GetPathRoot($TestRoot));PolluteEnvironment=$true}
    }
    'Permission' { Invoke-ScriptChecked 'Invoke-PermissionMatrix.ps1' @{AppRoot=$AppRoot;EvidenceRoot=$EvidenceRoot;Mode=$(if($DeniedRoot){'DeniedWritableRoot'}else{'VerifyReadOnly'});DeniedRoot=$DeniedRoot} }
    'OfflinePollution' { Invoke-ScriptChecked 'Invoke-LifecycleMatrix.ps1' @{AppRoot=$AppRoot;EvidenceRoot=$EvidenceRoot;CaseId='W07';DifferentCwd=$TestRoot;PolluteEnvironment=$true} }
    'Tamper' { Invoke-ScriptChecked 'Invoke-TamperMatrix.ps1' @{SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;EvidenceRoot=$EvidenceRoot;Mode='All'} }
    'OwnedStop' { Invoke-ScriptChecked 'Invoke-TamperMatrix.ps1' @{SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;EvidenceRoot=$EvidenceRoot;Mode='OwnedStop'} }
    'ForeignStop' { Invoke-ScriptChecked 'Invoke-TamperMatrix.ps1' @{SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;EvidenceRoot=$EvidenceRoot;Mode='ForeignStop'} }
    'PortConflict' { Invoke-ScriptChecked 'Invoke-ResourceInterferenceMatrix.ps1' @{Mode='PortConflict';EvidenceRoot=$EvidenceRoot;AppRoot=$AppRoot} }
    'RebootPrepare' { Invoke-ScriptChecked 'Invoke-RebootResume.ps1' @{Mode='StoppedPrepare';EvidenceRoot=$EvidenceRoot;CandidateId=$CandidateId;AppRoot=$AppRoot;ContractPath=$ContractPath;RebootKind='graceful_guest_reboot'} }
    'RebootResume' { Invoke-ScriptChecked 'Invoke-RebootResume.ps1' @{Mode='StoppedResume';EvidenceRoot=$EvidenceRoot;CandidateId=$CandidateId;AppRoot=$AppRoot;ContractPath=$ContractPath;RebootKind='graceful_guest_reboot'} }
    'LowDisk' { Invoke-ScriptChecked 'Invoke-ResourceInterferenceMatrix.ps1' @{Mode='LowDisk';EvidenceRoot=$EvidenceRoot;IsolatedLowDiskRoot=$IsolatedLowDiskRoot} }
    'ArchiveLock' { Invoke-ScriptChecked 'Invoke-ResourceInterferenceMatrix.ps1' @{Mode='ArchiveLock';EvidenceRoot=$EvidenceRoot;ArchivePath=$ArchivePath} }
    'DefenderStatus' { Invoke-ScriptChecked 'Invoke-ResourceInterferenceMatrix.ps1' @{Mode='DefenderStatus';EvidenceRoot=$EvidenceRoot} }
    'W08PrepareHealthy' { Invoke-ScriptChecked 'Invoke-MatrixContractCase.ps1' @{Mode='W08PrepareHealthy';HandoffRoot=$HandoffRoot;TestRoot=$TestRoot;EvidenceRoot=$EvidenceRoot;ContractPath=$ContractPath;DiagnosticProbeManifestPath=$DiagnosticProbeManifestPath} }
    { $_ -in @('W08Pointer','W08ReleaseManifest','W08RuntimeManifest','W08Payload','W08PythonDll') } {
        $targetMap=@{W08Pointer='Pointer';W08ReleaseManifest='ReleaseManifest';W08RuntimeManifest='RuntimeManifest';W08Payload='Payload';W08PythonDll='PythonDll'}
        Invoke-ScriptChecked 'Invoke-TamperMatrix.ps1' @{SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;EvidenceRoot=$EvidenceRoot;Mode=$targetMap[$Mode];ContractPath=$ContractPath}
    }
    'W08Aggregate' { Invoke-ScriptChecked 'Invoke-TamperMatrix.ps1' @{SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;EvidenceRoot=$EvidenceRoot;Mode='All';ContractPath=$ContractPath} }
    'W09' { Invoke-ScriptChecked 'Invoke-TamperMatrix.ps1' @{SourceInstallRoot=$SourceInstallRoot;CaseRoot=$CaseRoot;EvidenceRoot=$EvidenceRoot;Mode='CombinedW09';ContractPath=$ContractPath} }
    'W10' { Invoke-ScriptChecked 'Invoke-ResourceInterferenceMatrix.ps1' @{Mode='PortConflict';EvidenceRoot=$EvidenceRoot;AppRoot=$AppRoot} }
    { $_ -in @('W11StoppedPrepare','W11StoppedResume','W11RunningPrepare','W11RunningResume') } { Invoke-ScriptChecked 'Invoke-RebootResume.ps1' @{Mode=$Mode.Substring(3);EvidenceRoot=$EvidenceRoot;CandidateId=$CandidateId;AppRoot=$AppRoot;ContractPath=$ContractPath;RebootKind='graceful_guest_reboot'} }
    'W13' { Invoke-ScriptChecked 'Invoke-ResourceInterferenceMatrix.ps1' @{Mode='W13Full';EvidenceRoot=$EvidenceRoot;HandoffRoot=$HandoffRoot;TestRoot=$TestRoot;DiagnosticProbeManifestPath=$DiagnosticProbeManifestPath;ContractPath=$ContractPath} }
    'W14Prepare' { Invoke-W14Process 'Prepare' }
    'W14Validate' { Invoke-W14Process 'Validate' }
    'Export' { Invoke-ScriptChecked 'Export-ValidationEvidence.ps1' @{HandoffRoot=$HandoffRoot; EvidenceRoot=$EvidenceRoot; OutputRoot=$TestRoot} }
    { $_ -in @('Full','FinalIdentity') } {
        Invoke-ScriptChecked 'Invoke-EnvironmentBaseline.ps1' @{TestRoot=$TestRoot; EvidenceRoot=$EvidenceRoot; Classification=$CleanHostClassification}
        Invoke-ScriptChecked 'Invoke-ArtifactVerification.ps1' @{HandoffRoot=$HandoffRoot; EvidenceRoot=$EvidenceRoot}
        Invoke-ScriptChecked 'Invoke-Materialization.ps1' $common
        $handoff = Get-Content -Raw -LiteralPath (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json') | ConvertFrom-Json
        $appRoot = Join-Path $TestRoot ('install\releases\' + [string]$handoff.release_id)
        Invoke-ScriptChecked 'Invoke-LifecycleMatrix.ps1' @{AppRoot=$appRoot; EvidenceRoot=$EvidenceRoot; CaseId=($(if($Mode -eq 'FinalIdentity'){'W14'}else{'W03'})); DifferentCwd=$TestRoot; PolluteEnvironment=$true}
    }
}
