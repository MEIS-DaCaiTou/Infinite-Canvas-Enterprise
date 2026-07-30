[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('StoppedPrepare','StoppedResume','RunningPrepare','RunningResume')][string]$Mode,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][string]$CandidateId,
    [Parameter(Mandatory)][string]$AppRoot,
    [Parameter(Mandatory)][string]$ContractPath
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
$statePath=Join-Path $EvidenceRoot 'REBOOT-RESUME.json'

function Get-WrapperName([string]$Command) {
    switch($Command){
        'start'{return(-join@([char]0x542F,[char]0x52A8,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat'}
        'status'{return(-join@([char]0x67E5,[char]0x770B,[char]0x4F01,[char]0x4E1A,[char]0x7248,[char]0x72B6,[char]0x6001))+'.bat'}
        'stop'{return(-join@([char]0x505C,[char]0x6B62,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat'}
    }
}
function Invoke-Wrapper([string]$Command){
    $wrapper=Join-Path $AppRoot (Get-WrapperName $Command)
    $si=[Diagnostics.ProcessStartInfo]::new();$si.FileName=$env:ComSpec;$si.Arguments='/d /s /c ""'+$wrapper+'""';$si.UseShellExecute=$false;$si.CreateNoWindow=$true;$si.RedirectStandardOutput=$true;$si.RedirectStandardError=$true
    $p=[Diagnostics.Process]::new();$p.StartInfo=$si
    try{if(-not$p.Start()){throw[InvalidOperationException]::new('ENV1B3_REBOOT_COMMAND_FAILED|process')};$text=$p.StandardOutput.ReadToEnd()+"`n"+$p.StandardError.ReadToEnd();$p.WaitForExit();$exit=[int]$p.ExitCode}finally{$p.Dispose()}
    $payload=$null;foreach($line in $text.Split("`n")){try{$value=$line.TrimEnd("`r")|ConvertFrom-Json;if($null-ne$value){$payload=$value}}catch{}}
    return [ordered]@{exit_code=$exit;payload=$payload}
}
function Get-PointerPath{
    $releaseRoot=Split-Path -Parent $AppRoot;$installRoot=Split-Path -Parent $releaseRoot;return Join-Path $installRoot 'state\current-release.json'
}
function New-State([string]$Phase,[hashtable]$Ownership){
    $pointer=Get-PointerPath
    return [ordered]@{schema_version='env-1b3-reboot-resume-v2';overall_task_id='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE';phase=$Phase;candidate_id=$CandidateId;app_root=$AppRoot;app_root_identity=(Get-ENV1B3DirectoryTree $AppRoot);pointer_path_label='<INSTALL_ROOT>/state/current-release.json';pointer_sha256=(Get-ENV1B3Sha256 $pointer);ownership_summary=$Ownership;updated_at_utc=[DateTime]::UtcNow.ToString('o');user_reboot_approval_required=$true}
}
function Write-State($Document){
    $json=($Document|ConvertTo-Json -Depth 12 -Compress)+"`n";$temp=$statePath+'.new'
    if(Test-Path -LiteralPath $temp){throw[InvalidOperationException]::new('ENV1B3_REBOOT_STATE_TEMP_EXISTS|state')}
    [IO.File]::WriteAllText($temp,$json,[Text.UTF8Encoding]::new($false));Move-Item -LiteralPath $temp -Destination $statePath -Force
}
function Read-State([string]$ExpectedPhase){
    $state=Read-ENV1B3Json $statePath
    if($state.schema_version-ne'env-1b3-reboot-resume-v2'-or$state.overall_task_id-ne'ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE'-or$state.candidate_id-ne$CandidateId-or$state.phase-ne$ExpectedPhase-or$state.app_root-ne$AppRoot){throw[InvalidOperationException]::new('ENV1B3_REBOOT_STATE_INVALID|identity')}
    if($state.pointer_sha256-ne(Get-ENV1B3Sha256 (Get-PointerPath))){throw[InvalidOperationException]::new('ENV1B3_REBOOT_STATE_INVALID|pointer')}
    return $state
}
function Test-PidAlive([int]$ProcessId){try{return $null -ne (Get-Process -Id $ProcessId -ErrorAction Stop)}catch{return $false}}

try{
    [void](Assert-ENV1B3AbsoluteSafePath $EvidenceRoot -AllowMissingLeaf);[void](Assert-ENV1B3AbsoluteSafePath $AppRoot)
    [IO.Directory]::CreateDirectory($EvidenceRoot)|Out-Null
    switch($Mode){
        'StoppedPrepare'{
            $stop=Invoke-Wrapper stop;$status=Invoke-Wrapper status
            $pass=$stop.exit_code-eq0-and$status.exit_code-eq0
            $summary=@{state='stopped';status_exit=$status.exit_code;stop_exit=$stop.exit_code;portable_ownership_valid=$false}
            Write-State (New-State 'stopped_prepare_waiting' $summary)
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W11 -SubcheckId stopped_prepare -Result $(if($pass){'PASS'}else{'FAIL'}) -Code $(if($pass){'ENV1B3_REBOOT_STOPPED_PREPARED'}else{'ENV1B3_REBOOT_STOPPED_PREPARE_FAILED'}) -Evidence @{candidate_id=$CandidateId;status_exit=$status.exit_code;stop_exit=$stop.exit_code;app_root_identity=(Get-ENV1B3DirectoryTree $AppRoot);pointer_sha256=(Get-ENV1B3Sha256 (Get-PointerPath));user_reboot_approval_required=$true}|ConvertTo-Json -Depth 8 -Compress
            if(-not$pass){exit 2}
        }
        'StoppedResume'{
            $state=Read-State 'stopped_prepare_waiting';$status=Invoke-Wrapper status
            $pass=$status.exit_code-eq0-and$status.payload.portable_ownership_valid-ne$true
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W11 -SubcheckId stopped_resume -Result $(if($pass){'PASS'}else{'FAIL'}) -Code $(if($pass){'ENV1B3_REBOOT_STOPPED_RESUME_PASS'}else{'ENV1B3_REBOOT_STOPPED_RESUME_FAILED'}) -Evidence @{candidate_id=$CandidateId;status_exit=$status.exit_code;stopped_state_stable=$pass;pointer_sha256=$state.pointer_sha256}|ConvertTo-Json -Depth 8 -Compress
            if(-not$pass){exit 2};Write-State (New-State 'stopped_resume_complete' @{state='stopped';status_exit=$status.exit_code})
        }
        'RunningPrepare'{
            [void](Read-State 'stopped_resume_complete');$start=Invoke-Wrapper start;$status=Invoke-Wrapper status
            $runtime=$status.payload.runtime_state;$pass=$start.exit_code-eq0-and$status.exit_code-eq0-and$status.payload.portable_ownership_valid-eq$true-and$null-ne$runtime
            $summary=@{state='running';instance_id=[string]$runtime.supervisor_instance_id;supervisor_pid=[int]$runtime.supervisor_pid;portable_ownership_valid=[bool]$status.payload.portable_ownership_valid}
            Write-State (New-State 'running_prepare_waiting' $summary)
            Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W11 -SubcheckId running_prepare -Result $(if($pass){'PASS'}else{'FAIL'}) -Code $(if($pass){'ENV1B3_REBOOT_RUNNING_PREPARED'}else{'ENV1B3_REBOOT_RUNNING_PREPARE_FAILED'}) -Evidence @{candidate_id=$CandidateId;instance_id=$summary.instance_id;supervisor_pid=$summary.supervisor_pid;ownership_valid=$summary.portable_ownership_valid;user_reboot_approval_required=$true}|ConvertTo-Json -Depth 8 -Compress
            if(-not$pass){exit 2}
        }
        'RunningResume'{
            $state=Read-State 'running_prepare_waiting';$staleStatus=Invoke-Wrapper status
            $foreign=[Diagnostics.Process]::Start($env:ComSpec,'/d /c ping.exe -t 127.0.0.1')
            $temporaryEvidence=Join-Path $EvidenceRoot ('w11-lifecycle-'+[Guid]::NewGuid().ToString('N'))
            try{
                & (Join-Path $PSScriptRoot 'Invoke-LifecycleMatrix.ps1') -AppRoot $AppRoot -EvidenceRoot $temporaryEvidence -CaseId W11 -DifferentCwd ([IO.Path]::GetPathRoot($AppRoot)) -PolluteEnvironment
                if(-not$?){throw[InvalidOperationException]::new('ENV1B3_REBOOT_LIFECYCLE_FAILED|lifecycle')}
                $lifecycle=Read-ENV1B3Json (Join-Path $temporaryEvidence 'W11.json')
                $foreignSurvived=Test-PidAlive $foreign.Id
                $pass=$staleStatus.exit_code-eq0-and$lifecycle.result-eq'PASS'-and$foreignSurvived
                Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W11 -SubcheckId running_resume -Result $(if($pass){'PASS'}else{'FAIL'}) -Code $(if($pass){'ENV1B3_REBOOT_RUNNING_RESUME_PASS'}else{'ENV1B3_REBOOT_RUNNING_RESUME_FAILED'}) -Evidence @{candidate_id=$CandidateId;prior_instance_id=[string]$state.ownership_summary.instance_id;stale_status_diagnostic=($staleStatus.exit_code-eq0);controlled_recovery_passed=($lifecycle.result-eq'PASS');foreign_process_survived=$foreignSurvived;fixed_python_all_roles=[bool]$lifecycle.evidence.fixed_python_all_roles;ports_released=[bool]$lifecycle.evidence.port_release_verified}|Out-Null
            }finally{if(Test-PidAlive $foreign.Id){$foreign.Kill()};$foreign.Dispose();if(Test-Path -LiteralPath $temporaryEvidence){Remove-Item -LiteralPath $temporaryEvidence -Recurse -Force}}
            $aggregate=Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W11 -ContractPath $ContractPath;$aggregate|ConvertTo-Json -Depth 10 -Compress
            if($aggregate.result-ne'PASS'){exit 2}
        }
    }
}catch{
    $code='ENV1B3_REBOOT_RESUME_FAILED';if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{schema_version='env-1b3-reboot-error-v1';result='FAIL';code=$code;phase=$Mode;exit_code=2}|ConvertTo-Json -Compress;exit 2
}
