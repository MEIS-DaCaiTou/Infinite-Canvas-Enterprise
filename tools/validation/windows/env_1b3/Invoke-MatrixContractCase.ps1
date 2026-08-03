[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('W02','W03','W04','W05','W06','W07','W08PrepareHealthy','W08','W09','W10','W11StoppedPrepare','W11StoppedResume','W11RunningPrepare','W11RunningResume','W12','W13','W14Prepare','W14Validate','M01')][string]$Mode,
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][string]$ContractPath,
    [string]$DiagnosticProbeManifestPath,
    [string]$AppRoot,[string]$SourceInstallRoot,[string]$CaseRoot,[string]$DeniedRoot,[string]$IsolatedLowDiskRoot,[int]$Port=18000,[string]$CandidateId
    ,[ValidateSet('graceful_guest_reboot','hyperv_hard_reset')][string]$RebootKind='graceful_guest_reboot'
    ,[Nullable[int]]$LongPathsEnabledOverride
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

function Quote-NativeArgument([string]$Value){return '"'+$Value.Replace('"','\"')+'"'}
function Invoke-ValidationChild([string]$ScriptName,[hashtable]$Parameters){
    $arguments=@('-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot $ScriptName))
    foreach($key in @($Parameters.Keys|Sort-Object)){
        $value=$Parameters[$key]
        if($value-is[bool]){if($value){$arguments+=('-'+$key)};continue}
        $arguments+=('-'+$key);$arguments+=([string]$value)
    }
    $encoded=@($arguments|ForEach-Object{Quote-NativeArgument ([string]$_)})-join' '
    return Invoke-ENV1B3ManagedProcess -FileName (Join-Path $PSHOME 'powershell.exe') -Arguments $encoded -WorkingDirectory ([IO.Path]::GetPathRoot($TestRoot)) -TimeoutSeconds 600
}
function Get-BoundedText([string]$Value){if($null-eq$Value){return''};if($Value.Length-gt8192){return$Value.Substring($Value.Length-8192)};return$Value}

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
            if($null-ne$LongPathsEnabledOverride){$longPathsValue=[int]$LongPathsEnabledOverride}else{try{$longPathsValue=[int](Get-ItemPropertyValue -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction Stop)}catch{$longPathsValue=0}}
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
            $python=Join-Path $root 'python\python.exe';$ioPass=$false;$ioCode='ENV1B3_FIXED_PYTHON_LONG_PATH_IO_FAILED'
            if($longestLength-gt260){
                $io=Invoke-ENV1B3ManagedProcess -FileName $python -Arguments ('-I -B -c "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.open(''rb'').read(1)" "'+$longest[0].FullName+'"') -WorkingDirectory ([IO.Path]::GetPathRoot($root)) -TimeoutSeconds 60
                $ioPass=$io.exit_code-eq0-and-not$io.timed_out
            }
            $materializedPass=$longestLength-gt260-and$ioPass
            $materializedCode=if($longestLength-le260){'ENV1B3_MATERIALIZATION_FAILED'}elseif(-not$ioPass){$ioCode}else{'ENV1B3_LONG_PATH_MATERIALIZATION_PASS'}
            $common=@{long_paths_enabled=$true;longest_materialized_path_length=$longestLength;fixed_python_long_path_io=$ioPass;powershell_materialization_passed=$true;execution_context_long_path_enabled=$true;execution_context_standard_non_admin_user=$true;fixture_candidate_handoff=$true}
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W05 -SubcheckId long_path_materialization -Result $(if($materializedPass){'PASS'}else{'FAIL'}) -Code $materializedCode -Evidence $common|Out-Null
            $lifeTemp=Join-Path $EvidenceRoot ('w05-lifecycle-'+[Guid]::NewGuid().ToString('N'))
            $differentCwd=Join-Path $TestRoot 'different-cwd';[IO.Directory]::CreateDirectory($differentCwd)|Out-Null
            try{
                & (Join-Path $PSScriptRoot 'Invoke-LifecycleMatrix.ps1') -AppRoot $root -EvidenceRoot $lifeTemp -CaseId W05 -DifferentCwd $differentCwd -PolluteEnvironment
                $life=Read-ENV1B3Json (Join-Path $lifeTemp 'W05.json');$lifeEvidence=$life.evidence
                $lifeEvidence|Add-Member -NotePropertyName lifecycle_passed -NotePropertyValue ($life.result-eq'PASS') -Force
                $lifeEvidence|Add-Member -NotePropertyName long_paths_enabled -NotePropertyValue $true -Force
                $lifeCode=if($life.result-ne'PASS'){'ENV1B3_LIFECYCLE_FAILED'}elseif($lifeEvidence.app_root_tree_unchanged-ne$true){'ENV1B3_APP_ROOT_CHANGED'}else{'ENV1B3_LIFECYCLE_PASS'}
                Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W05 -SubcheckId long_path_lifecycle -Result $(if($lifeCode-eq'ENV1B3_LIFECYCLE_PASS'){'PASS'}else{'FAIL'}) -Code $lifeCode -Evidence $lifeEvidence|Out-Null
            }finally{if(Test-Path -LiteralPath $lifeTemp){Remove-Item -LiteralPath $lifeTemp -Recurse -Force}}
            Complete-Translated W05
        }
        'W06'{& (Join-Path $PSScriptRoot 'Invoke-PermissionMatrix.ps1') -AppRoot $AppRoot -EvidenceRoot $EvidenceRoot -DeniedRoot $DeniedRoot -ContractPath $ContractPath}
        'W07'{if([string]::IsNullOrWhiteSpace($AppRoot)){$AppRoot=Get-DefaultAppRoot};& (Join-Path $PSScriptRoot 'Invoke-LifecycleMatrix.ps1') -AppRoot $AppRoot -EvidenceRoot $EvidenceRoot -CaseId W07 -DifferentCwd $TestRoot -PolluteEnvironment -RequireOffline -SubcheckId offline_polluted_environment;Complete-Translated W07}
        'W08PrepareHealthy'{
            $failureStage='artifact_verify';$artifact=Test-ENV1B3Handoff -HandoffRoot $HandoffRoot
            $failureStage='materialization';$materialEvidence=Join-Path $EvidenceRoot 'w08-prepare-materialization'
            $materialParameters=@{HandoffRoot=$HandoffRoot;TestRoot=$TestRoot;EvidenceRoot=$materialEvidence;CaseId='W02'}
            if(-not[String]::IsNullOrWhiteSpace($DiagnosticProbeManifestPath)){$materialParameters.DiagnosticProbeManifestPath=$DiagnosticProbeManifestPath}
            $materialChild=Invoke-ValidationChild 'Invoke-Materialization.ps1' $materialParameters
            $w02Path=Join-Path $materialEvidence 'W02.json';$w02=if(Test-Path -LiteralPath $w02Path){Read-ENV1B3Json $w02Path}else{$null};$root=Get-DefaultAppRoot
            $differentCwd=Join-Path $TestRoot 'w08-different-cwd';[IO.Directory]::CreateDirectory($differentCwd)|Out-Null
            $failureStage='lifecycle';$lifeEvidence=Join-Path $EvidenceRoot 'w08-prepare-lifecycle'
            $lifeChild=$null;$w03=$null
            if($materialChild.exit_code-eq0-and-not$materialChild.timed_out-and$null-ne$w02-and$w02.result-eq'PASS'){
                $lifeChild=Invoke-ValidationChild 'Invoke-LifecycleMatrix.ps1' @{AppRoot=$root;EvidenceRoot=$lifeEvidence;CaseId='W03';DifferentCwd=$differentCwd;PolluteEnvironment=$true}
                $w03Path=Join-Path $lifeEvidence 'W03.json';if(Test-Path -LiteralPath $w03Path){$w03=Read-ENV1B3Json $w03Path}
            }
            $runtimeRoot=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'InfiniteCanvasEnterprise\runtime'
            $lock=Join-Path $runtimeRoot 'runtime-supervisor.lock';$state=Join-Path $runtimeRoot 'runtime-state.json'
            $processes=@(Get-CimInstance Win32_Process -ErrorAction Stop|Where-Object{$p=$_.PSObject.Properties['CommandLine'];$null-ne$p-and[string]$p.Value-like('*'+$root+'*')}|ForEach-Object{[int]$_.ProcessId})
            $listeners=@(Get-NetTCPConnection -State Listen -ErrorAction Stop|Where-Object{$_.LocalPort-in@(3001,8000)})
            $tree=if(Test-Path -LiteralPath $root -PathType Container){Get-ENV1B3DirectoryTree $root}else{$null}
            $runtimeClean=(-not(Test-Path -LiteralPath $lock))-and(-not(Test-Path -LiteralPath $state))
            $w02Pass=$null-ne$w02-and$w02.result-eq'PASS';$w03Pass=$null-ne$w03-and$w03.result-eq'PASS'
            $checkpoint=$w02Pass-and$w03Pass-and$runtimeClean-and$processes.Count-eq0-and$listeners.Count-eq0
            $failureStage=if(-not$w02Pass){'materialization'}elseif(-not$w03Pass){'lifecycle'}elseif(-not$runtimeClean){'runtime_cleanup'}elseif($processes.Count){'process_cleanup'}elseif($listeners.Count){'port_release'}else{'complete'}
            $childText=$(if($null-ne$lifeChild){([string]$lifeChild.stdout+[string]$lifeChild.stderr)}else{[string]$materialChild.stdout+[string]$materialChild.stderr})
            $record=[ordered]@{schema_version='env-1b3-w08-healthy-pre-target-v1';overall_task_id='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE';candidate_id=[string]$artifact.candidate_id;release_id=[string]$artifact.release_id;app_root=$root;app_root_tree_sha256=$(if($null-ne$tree){[string]$tree.tree_sha256}else{$null});w02_result=$(if($null-ne$w02){[string]$w02.result}else{'FAIL'});w03_result=$(if($null-ne$w03){[string]$w03.result}else{'FAIL'});runtime_clean=$runtimeClean;process_absent=($processes.Count-eq0);ports_free=($listeners.Count-eq0);checkpoint_ready=$checkpoint;failure_stage=$failureStage;wrapper_role=$(if($null-ne$w03){[string]$w03.evidence.wrapper_role}else{$null});wrapper_exit=$(if($null-ne$lifeChild){[int]$lifeChild.exit_code}else{$null});stdout_stderr_tail=(Get-BoundedText $childText);different_cwd_exists=(Test-Path -LiteralPath $differentCwd -PathType Container);app_root_exists=(Test-Path -LiteralPath $root -PathType Container);runtime_summary=@{lock_present=(Test-Path -LiteralPath $lock);state_present=(Test-Path -LiteralPath $state)}}
            [IO.File]::WriteAllText((Join-Path $EvidenceRoot 'W08-HEALTHY-PRE-TARGET.json'),($record|ConvertTo-Json -Depth 8 -Compress)+"`n",[Text.UTF8Encoding]::new($false))
            $record|ConvertTo-Json -Depth 8 -Compress;if(-not$checkpoint){exit 2}
        }
        'W08'{& (Join-Path $PSScriptRoot 'Invoke-TamperMatrix.ps1') -SourceInstallRoot $SourceInstallRoot -CaseRoot $CaseRoot -EvidenceRoot $EvidenceRoot -Mode All -ContractPath $ContractPath}
        'W09'{& (Join-Path $PSScriptRoot 'Invoke-TamperMatrix.ps1') -SourceInstallRoot $SourceInstallRoot -CaseRoot $CaseRoot -EvidenceRoot $EvidenceRoot -Mode CombinedW09 -ContractPath $ContractPath}
        'W10'{
            $temporary=Join-Path $EvidenceRoot ('w10-'+[Guid]::NewGuid().ToString('N'));try{& (Join-Path $PSScriptRoot 'Invoke-ResourceInterferenceMatrix.ps1') -Mode PortConflict -EvidenceRoot $temporary -AppRoot $AppRoot;$r=Read-ENV1B3Json (Join-Path $temporary 'W10.json')}finally{if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary -Recurse -Force}}
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
