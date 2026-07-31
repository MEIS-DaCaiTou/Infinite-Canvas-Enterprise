[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('W02','W03','W04','W05','W06','W07','W08','W09','W10','W11StoppedPrepare','W11StoppedResume','W11RunningPrepare','W11RunningResume','W12','W13','W14Prepare','W14Validate','M01')][string]$Mode,
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][string]$ContractPath,
    [string]$DiagnosticProbeManifestPath,
    [string]$AppRoot,[string]$SourceInstallRoot,[string]$CaseRoot,[string]$DeniedRoot,[string]$IsolatedLowDiskRoot,[int]$Port=18000,[string]$CandidateId
    ,[ValidateSet('graceful_guest_reboot','hyperv_hard_reset')][string]$RebootKind='graceful_guest_reboot'
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

function Invoke-TranslatedLifecycle([string]$CaseId,[string]$SubcheckId,[string]$Root,[string]$Cwd,[switch]$Pollute,[switch]$Offline){
    $temporary=Join-Path $EvidenceRoot ('translated-'+$CaseId+'-'+[Guid]::NewGuid().ToString('N'))
    try{
        $arguments=@{AppRoot=$Root;EvidenceRoot=$temporary;CaseId=$CaseId;DifferentCwd=$Cwd}
        if($Pollute){$arguments.PolluteEnvironment=$true};if($Offline){$arguments.RequireOffline=$true}
        & (Join-Path $PSScriptRoot 'Invoke-LifecycleMatrix.ps1') @arguments
        if(-not$?){throw[InvalidOperationException]::new('ENV1B3_MATRIX_LIFECYCLE_FAILED|lifecycle')}
        $result=Read-ENV1B3Json (Join-Path $temporary ($CaseId+'.json'))
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -SubcheckId $SubcheckId -Result ([string]$result.result) -Code ([string]$result.code) -Evidence $result.evidence|Out-Null
        return $result
    }finally{if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary -Recurse -Force}}
}
function Complete-Translated([string]$CaseId){$r=Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -ContractPath $ContractPath;$r|ConvertTo-Json -Depth 10 -Compress;if($r.result-ne'PASS'){exit 2}}
function Get-DefaultAppRoot{$h=Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json');return Join-Path $TestRoot ('install\releases\'+[string]$h.release_id)}

try{
    [void](Read-ENV1B3MatrixContracts $ContractPath)
    switch($Mode){
        'W02'{
            $artifact=Test-ENV1B3Handoff -HandoffRoot $HandoffRoot
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W02 -SubcheckId artifact_verify -Result PASS -Code ENV1B3_ARTIFACT_VERIFY_PASS -Evidence @{payload_tree_sha256=[string]$artifact.artifact.payload_tree_sha256}|Out-Null
            $temporary=Join-Path $EvidenceRoot ('w02-materialization-'+[Guid]::NewGuid().ToString('N'))
            try{& (Join-Path $PSScriptRoot 'Invoke-Materialization.ps1') -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot $temporary -CaseId W02 -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath;if(-not$?){throw[InvalidOperationException]::new('ENV1B3_MATERIALIZATION_FAILED|materialization')};$materialized=Read-ENV1B3Json (Join-Path $temporary 'W02.json')}finally{if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary -Recurse -Force}}
            $root=Get-DefaultAppRoot;$handoff=Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json');$pointer=Read-ENV1B3Json (Join-Path $TestRoot 'install\state\current-release.json')
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W02 -SubcheckId materialization -Result PASS -Code ENV1B3_MATERIALIZATION_PASS -Evidence @{app_root_created=(Test-Path -LiteralPath $root -PathType Container)}|Out-Null
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W02 -SubcheckId materialized_verify -Result PASS -Code ENV1B3_MATERIALIZED_VERIFY_PASS -Evidence @{payload_tree_sha256=[string]$materialized.evidence.payload_tree_sha256;external_verifier_used=$true}|Out-Null
            $pointerPass=$pointer.release_id-eq$handoff.release_id-and-not(Test-Path -LiteralPath (Join-Path $TestRoot 'install\state\current-release.json.new'))
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W02 -SubcheckId pointer_commit -Result $(if($pointerPass){'PASS'}else{'FAIL'}) -Code $(if($pointerPass){'ENV1B3_POINTER_COMMIT_PASS'}else{'ENV1B3_POINTER_COMMIT_FAILED'}) -Evidence @{pointer_committed=$pointerPass;pointer_temp_absent=(-not(Test-Path -LiteralPath (Join-Path $TestRoot 'install\state\current-release.json.new')))}|Out-Null
            Complete-Translated W02
        }
        'W03'{if([string]::IsNullOrWhiteSpace($AppRoot)){$AppRoot=Get-DefaultAppRoot};[void](Invoke-TranslatedLifecycle W03 formal_lifecycle $AppRoot $TestRoot);Complete-Translated W03}
        'W04'{
            & (Join-Path $PSScriptRoot 'Invoke-Materialization.ps1') -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot (Join-Path $EvidenceRoot 'w04-materialization') -CaseId W02 -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath
            [void](Invoke-TranslatedLifecycle W04 unicode_space_different_cwd (Get-DefaultAppRoot) ([IO.Path]::GetPathRoot($TestRoot)) -Pollute);Complete-Translated W04
        }
        'W05'{
            $longPathsValue=0
            try{$longPathsValue=[int](Get-ItemPropertyValue -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction Stop)}catch{$longPathsValue=0}
            if($longPathsValue-ne1){
                $blocked=@{long_paths_enabled=$false;longest_materialized_path_length=0;fixed_python_long_path_io=$false;powershell_materialization_passed=$false;lifecycle_passed=$false;execution_context_long_path_enabled=$false;execution_context_standard_non_admin_user=$true;fixture_candidate_handoff=$true}
                Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W05 -SubcheckId long_path_materialization -Result BLOCKED -Code ENV1B3_LONG_PATHS_DISABLED -Evidence $blocked|Out-Null
                Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W05 -SubcheckId long_path_lifecycle -Result BLOCKED -Code ENV1B3_LONG_PATHS_DISABLED -Evidence $blocked|Out-Null
                $blockedResult=Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W05 -Result BLOCKED -Code ENV1B3_LONG_PATHS_DISABLED -Evidence @{long_paths_enabled=$false;reason='windows_long_paths_disabled'} -NoOverwrite
                $blockedResult|ConvertTo-Json -Depth 8 -Compress
                exit 2
            }
            & (Join-Path $PSScriptRoot 'Invoke-Materialization.ps1') -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot (Join-Path $EvidenceRoot 'w05-materialization') -CaseId W05 -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath
            $root=Get-DefaultAppRoot;$longest=@(Get-ChildItem -LiteralPath $root -File -Recurse|Sort-Object {$_.FullName.Length} -Descending|Select-Object -First 1)
            $longestLength=if($longest.Count){$longest[0].FullName.Length}else{0}
            $python=Join-Path $root 'python\python.exe';$ioPass=$false
            if($longestLength-gt260){
                $io=Invoke-ENV1B3ManagedProcess -FileName $python -Arguments ('-I -B -c "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.open(''rb'').read(1)" "'+$longest[0].FullName+'"') -WorkingDirectory ([IO.Path]::GetPathRoot($root)) -TimeoutSeconds 60
                $ioPass=$io.exit_code-eq0-and-not$io.timed_out
            }
            $materializedPass=$longestLength-gt260-and$ioPass
            $common=@{long_paths_enabled=$true;longest_materialized_path_length=$longestLength;fixed_python_long_path_io=$ioPass;powershell_materialization_passed=$true;execution_context_long_path_enabled=$true;execution_context_standard_non_admin_user=$true;fixture_candidate_handoff=$true}
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W05 -SubcheckId long_path_materialization -Result $(if($materializedPass){'PASS'}else{'FAIL'}) -Code $(if($materializedPass){'ENV1B3_LONG_PATH_MATERIALIZATION_PASS'}else{'ENV1B3_MATERIALIZATION_FAILED'}) -Evidence $common|Out-Null
            $lifeTemp=Join-Path $EvidenceRoot ('w05-lifecycle-'+[Guid]::NewGuid().ToString('N'))
            try{
                & (Join-Path $PSScriptRoot 'Invoke-LifecycleMatrix.ps1') -AppRoot $root -EvidenceRoot $lifeTemp -CaseId W05 -DifferentCwd ([IO.Path]::GetPathRoot($TestRoot)) -PolluteEnvironment
                $life=Read-ENV1B3Json (Join-Path $lifeTemp 'W05.json');$lifeEvidence=$life.evidence
                $lifeEvidence|Add-Member -NotePropertyName lifecycle_passed -NotePropertyValue ($life.result-eq'PASS') -Force
                $lifeEvidence|Add-Member -NotePropertyName long_paths_enabled -NotePropertyValue $true -Force
                Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W05 -SubcheckId long_path_lifecycle -Result ([string]$life.result) -Code ([string]$life.code) -Evidence $lifeEvidence|Out-Null
            }finally{if(Test-Path -LiteralPath $lifeTemp){Remove-Item -LiteralPath $lifeTemp -Recurse -Force}}
            Complete-Translated W05
        }
        'W06'{& (Join-Path $PSScriptRoot 'Invoke-PermissionMatrix.ps1') -AppRoot $AppRoot -EvidenceRoot $EvidenceRoot -DeniedRoot $DeniedRoot -ContractPath $ContractPath}
        'W07'{if([string]::IsNullOrWhiteSpace($AppRoot)){$AppRoot=Get-DefaultAppRoot};& (Join-Path $PSScriptRoot 'Invoke-LifecycleMatrix.ps1') -AppRoot $AppRoot -EvidenceRoot $EvidenceRoot -CaseId W07 -DifferentCwd $TestRoot -PolluteEnvironment -RequireOffline -SubcheckId offline_polluted_environment;Complete-Translated W07}
        'W08'{& (Join-Path $PSScriptRoot 'Invoke-TamperMatrix.ps1') -SourceInstallRoot $SourceInstallRoot -CaseRoot $CaseRoot -EvidenceRoot $EvidenceRoot -Mode All -ContractPath $ContractPath}
        'W09'{& (Join-Path $PSScriptRoot 'Invoke-TamperMatrix.ps1') -SourceInstallRoot $SourceInstallRoot -CaseRoot $CaseRoot -EvidenceRoot $EvidenceRoot -Mode CombinedW09 -ContractPath $ContractPath}
        'W10'{
            $temporary=Join-Path $EvidenceRoot ('w10-'+[Guid]::NewGuid().ToString('N'));try{& (Join-Path $PSScriptRoot 'Invoke-ResourceInterferenceMatrix.ps1') -Mode PortConflict -EvidenceRoot $temporary -AppRoot $AppRoot -Port $Port;$r=Read-ENV1B3Json (Join-Path $temporary 'W10.json')}finally{if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary -Recurse -Force}}
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W10 -SubcheckId foreign_port_conflict -Result ([string]$r.result) -Code ([string]$r.code) -Evidence $r.evidence|Out-Null;Complete-Translated W10
        }
        {$_-like'W11*'}{$phase=$Mode.Substring(3);& (Join-Path $PSScriptRoot 'Invoke-RebootResume.ps1') -Mode $phase -EvidenceRoot $EvidenceRoot -CandidateId $CandidateId -AppRoot $AppRoot -ContractPath $ContractPath -RebootKind $RebootKind}
        'W12'{& (Join-Path $PSScriptRoot 'Invoke-ResourceInterferenceMatrix.ps1') -Mode W12Full -EvidenceRoot $EvidenceRoot -HandoffRoot $HandoffRoot -TestRoot $TestRoot -IsolatedLowDiskRoot $IsolatedLowDiskRoot -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath -ContractPath $ContractPath}
        'W13'{& (Join-Path $PSScriptRoot 'Invoke-ResourceInterferenceMatrix.ps1') -Mode W13Full -EvidenceRoot $EvidenceRoot -HandoffRoot $HandoffRoot -TestRoot $TestRoot -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath -ContractPath $ContractPath}
        'W14Prepare'{& (Join-Path $PSScriptRoot 'Invoke-FinalIdentityMatrix.ps1') -Mode Prepare -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot $EvidenceRoot -ContractPath $ContractPath -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath}
        'W14Validate'{& (Join-Path $PSScriptRoot 'Invoke-FinalIdentityMatrix.ps1') -Mode Validate -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot $EvidenceRoot -ContractPath $ContractPath -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath}
        'M01'{& (Join-Path $PSScriptRoot 'Invoke-MaterializationAtomicityProbe.ps1') -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot $EvidenceRoot -ProbeManifestPath $DiagnosticProbeManifestPath}
    }
    if(-not$?){exit 2}
}catch{
    $code='ENV1B3_MATRIX_CASE_EXECUTION_FAILED';if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{schema_version='env-1b3-matrix-case-error-v1';status='blocked';code=$code;mode=$Mode;exit_code=2}|ConvertTo-Json -Compress;exit 2
}
