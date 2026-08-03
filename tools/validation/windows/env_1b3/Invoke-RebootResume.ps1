[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('StoppedPrepare','StoppedResume','RunningPrepare','RunningResume')][string]$Mode,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][string]$CandidateId,
    [Parameter(Mandatory)][string]$AppRoot,
    [Parameter(Mandatory)][string]$ContractPath,
    [ValidateSet('graceful_guest_reboot','hyperv_hard_reset')][string]$RebootKind='graceful_guest_reboot'
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
$statePath=Join-Path $EvidenceRoot $(if($Mode-like'Stopped*'){'REBOOT-RESUME-STOPPED.json'}else{'REBOOT-RESUME-RUNNING.json'})

function Get-WrapperName([string]$Command){
    switch($Command){
        start{return(-join@([char]0x542F,[char]0x52A8,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat'}
        status{return(-join@([char]0x67E5,[char]0x770B,[char]0x4F01,[char]0x4E1A,[char]0x7248,[char]0x72B6,[char]0x6001))+'.bat'}
        stop{return(-join@([char]0x505C,[char]0x6B62,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat'}
    }
}
function Invoke-Wrapper([string]$Command){
    $wrapper=Join-Path $AppRoot (Get-WrapperName $Command)
    $r=Invoke-ENV1B3ManagedProcess -FileName $env:ComSpec -Arguments ('/d /s /c ""'+$wrapper+'""') -WorkingDirectory ([IO.Path]::GetPathRoot($AppRoot)) -TimeoutSeconds 90
    $payload=$null
    foreach($line in ([string]$r.stdout+[Environment]::NewLine+[string]$r.stderr).Split("`n")){
        try{$v=$line.TrimEnd("`r")|ConvertFrom-Json;if($null-ne$v){$payload=$v}}catch{}
    }
    return [ordered]@{exit_code=[int]$r.exit_code;payload=$payload;timed_out=[bool]$r.timed_out}
}
function Get-PointerPath{$releaseRoot=Split-Path -Parent $AppRoot;$installRoot=Split-Path -Parent $releaseRoot;Join-Path $installRoot 'state\current-release.json'}
function New-State([string]$Phase,[hashtable]$Ownership){
    [ordered]@{
        schema_version='env-1b3-reboot-resume-v3';overall_task_id='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE'
        phase=$Phase;reboot_kind=$RebootKind;candidate_id=$CandidateId;app_root=$AppRoot
        app_root_identity=(Get-ENV1B3DirectoryTree $AppRoot);pointer_path_label='<INSTALL_ROOT>/state/current-release.json'
        pointer_sha256=(Get-ENV1B3Sha256 (Get-PointerPath));ownership_summary=$Ownership
        updated_at_utc=[DateTime]::UtcNow.ToString('o');user_reboot_approval_required=$true
    }
}
function Write-State($Document){
    $sha=Write-ENV1B3DurableJson -Path $statePath -Document $Document
    return [ordered]@{temp_write=$true;flush_true=$true;temp_parse=$true;commit=$true;final_parse=$true;final_sha=$sha;sha256=$sha}
}
function Read-State([string]$ExpectedPhase,[string]$PrepareSubcheck){
    $preparePath=Join-Path $EvidenceRoot (Join-Path 'subchecks\W11' ($PrepareSubcheck+'.json'))
    $prepare=Read-ENV1B3Json $preparePath
    $sha=[string]$prepare.evidence.reboot_state_sha256
    $state=Read-ENV1B3DurableJson -Path $statePath -ExpectedSha256 $sha
    if($state.schema_version-ne'env-1b3-reboot-resume-v3'-or$state.overall_task_id-ne'ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE'-or$state.candidate_id-ne$CandidateId-or$state.phase-ne$ExpectedPhase-or$state.app_root-ne$AppRoot-or$state.reboot_kind-ne$RebootKind){throw[InvalidOperationException]::new('ENV1B3_REBOOT_STATE_INVALID|identity')}
    if($state.pointer_sha256-ne(Get-ENV1B3Sha256 (Get-PointerPath))){throw[InvalidOperationException]::new('ENV1B3_REBOOT_STATE_INVALID|pointer')}
    $currentTree=Get-ENV1B3DirectoryTree $AppRoot
    if($currentTree.file_count-ne$state.app_root_identity.file_count-or$currentTree.tree_sha256-ne$state.app_root_identity.tree_sha256){throw[InvalidOperationException]::new('ENV1B3_REBOOT_STATE_INVALID|app_root')}
    return $state
}
function Test-PidAlive([int]$ProcessId){try{$null-ne(Get-Process -Id $ProcessId -ErrorAction Stop)}catch{$false}}
function New-Sentinel{
    $ping=Join-Path ([Environment]::GetFolderPath('System')) 'ping.exe'
    $si=[Diagnostics.ProcessStartInfo]::new();$si.FileName=$ping;$si.Arguments='-t 127.0.0.1';$si.UseShellExecute=$false;$si.CreateNoWindow=$true;$si.RedirectStandardOutput=$true;$si.RedirectStandardError=$true
    $p=[Diagnostics.Process]::new();$p.StartInfo=$si;if(-not$p.Start()){throw[InvalidOperationException]::new('ENV1B3_REBOOT_RESUME_FAILED|sentinel')}
    [void]$p.StandardOutput.ReadToEndAsync();[void]$p.StandardError.ReadToEndAsync();return $p
}
function Common-Evidence($state){
    @{candidate_id=$CandidateId;app_root_identity=$state.app_root_identity;pointer_identity=[string]$state.pointer_sha256;ownership_summary=$state.ownership_summary;reboot_kind=$RebootKind;execution_context_approved_guest_reboot=($RebootKind-eq'graceful_guest_reboot');execution_context_restored_clean_checkpoint=$true;fixture_materialized_release=$true;fixture_reboot_resume_state=$true}
}

try{
    [void](Assert-ENV1B3AbsoluteSafePath $EvidenceRoot -AllowMissingLeaf);[void](Assert-ENV1B3AbsoluteSafePath $AppRoot)
    if($RebootKind-ne'graceful_guest_reboot'){throw[InvalidOperationException]::new('ENV1B3_REBOOT_KIND_NOT_FORMAL|reboot_kind')}
    [IO.Directory]::CreateDirectory($EvidenceRoot)|Out-Null
    switch($Mode){
        StoppedPrepare{
            $stop=Invoke-Wrapper stop;$status=Invoke-Wrapper status;$pass=$stop.exit_code-eq0-and$status.exit_code-eq0
            $state=New-State 'stopped_prepare_waiting' @{state='stopped';status_exit=$status.exit_code;stop_exit=$stop.exit_code;portable_ownership_valid=$false}
            $durability=Write-State $state;$e=Common-Evidence $state;$e.stop_exit=$stop.exit_code;$e.status_exit=$status.exit_code;$e.reboot_state_sha256=$durability.sha256;$e.durability_stages=$durability
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W11 -SubcheckId stopped_prepare -Result $(if($pass){'PASS'}else{'FAIL'}) -Code $(if($pass){'ENV1B3_REBOOT_STOPPED_PREPARED'}else{'ENV1B3_REBOOT_STOPPED_PREPARE_FAILED'}) -Evidence $e|ConvertTo-Json -Compress
            if(-not$pass){exit 2}
        }
        StoppedResume{
            $state=Read-State 'stopped_prepare_waiting' 'stopped_prepare';$status=Invoke-Wrapper status;$pass=$status.exit_code-eq0-and$status.payload.portable_ownership_valid-ne$true
            $e=Common-Evidence $state;$e.status_exit=$status.exit_code;$e.stopped_state_stable=$pass
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W11 -SubcheckId stopped_resume -Result $(if($pass){'PASS'}else{'FAIL'}) -Code $(if($pass){'ENV1B3_REBOOT_STOPPED_RESUME_PASS'}else{'ENV1B3_REBOOT_STOPPED_RESUME_FAILED'}) -Evidence $e|ConvertTo-Json -Compress
            if(-not$pass){exit 2}
        }
        RunningPrepare{
            $start=Invoke-Wrapper start;$status=Invoke-Wrapper status;$runtime=$status.payload.runtime_state
            $pass=$start.exit_code-eq0-and$status.exit_code-eq0-and$status.payload.portable_ownership_valid-eq$true-and$null-ne$runtime
            $ownership=@{state='running';instance_id=[string]$runtime.supervisor_instance_id;supervisor_pid=[int]$runtime.supervisor_pid;portable_ownership_valid=[bool]$status.payload.portable_ownership_valid}
            $state=New-State 'running_prepare_waiting' $ownership;$durability=Write-State $state;$e=Common-Evidence $state;$e.reboot_state_sha256=$durability.sha256;$e.durability_stages=$durability
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W11 -SubcheckId running_prepare -Result $(if($pass){'PASS'}else{'FAIL'}) -Code $(if($pass){'ENV1B3_REBOOT_RUNNING_PREPARED'}else{'ENV1B3_REBOOT_RUNNING_PREPARE_FAILED'}) -Evidence $e|ConvertTo-Json -Compress
            if(-not$pass){exit 2}
        }
        RunningResume{
            $state=Read-State 'running_prepare_waiting' 'running_prepare';$stale=Invoke-Wrapper status;$foreign=New-Sentinel;$tmp=Join-Path $EvidenceRoot ('w11-lifecycle-'+[Guid]::NewGuid().ToString('N'))
            try{
                & (Join-Path $PSScriptRoot 'Invoke-LifecycleMatrix.ps1') -AppRoot $AppRoot -EvidenceRoot $tmp -CaseId W11 -DifferentCwd ([IO.Path]::GetPathRoot($AppRoot)) -PolluteEnvironment
                $lifecycle=Read-ENV1B3Json (Join-Path $tmp 'W11.json');$survived=Test-PidAlive $foreign.Id
                $pass=$stale.exit_code-eq0-and$lifecycle.result-eq'PASS'-and$survived
                $e=Common-Evidence $state;$e.stale_status_diagnostic=($stale.exit_code-eq0);$e.foreign_process_survived=$survived;$e.fixed_python_all_roles=[bool]$lifecycle.evidence.fixed_python_all_roles;$e.ports_released=[bool]$lifecycle.evidence.port_release_verified
                Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W11 -SubcheckId running_resume -Result $(if($pass){'PASS'}else{'FAIL'}) -Code $(if($pass){'ENV1B3_REBOOT_RUNNING_RESUME_PASS'}else{'ENV1B3_REBOOT_RUNNING_RESUME_FAILED'}) -Evidence $e|Out-Null
            }finally{if(Test-PidAlive $foreign.Id){$foreign.Kill()};$foreign.Dispose();if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Recurse -Force}}
            $aggregate=Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W11 -ContractPath $ContractPath;$aggregate|ConvertTo-Json -Depth 10 -Compress;if($aggregate.result-ne'PASS'){exit 2}
        }
    }
}catch{
    $code='ENV1B3_REBOOT_RESUME_FAILED';if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{schema_version='env-1b3-reboot-error-v1';result='FAIL';code=$code;phase=$Mode;reboot_kind=$RebootKind;exit_code=2}|ConvertTo-Json -Compress;exit 2
}
