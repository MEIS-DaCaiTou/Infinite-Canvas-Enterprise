[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Prepare','Resume')][string]$Mode,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][string]$CandidateId,
    [string]$NextCaseId='W11'
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
$path=Join-Path $EvidenceRoot 'REBOOT-RESUME.json'
try {
    [void](Assert-ENV1B3AbsoluteSafePath $EvidenceRoot -AllowMissingLeaf)
    [IO.Directory]::CreateDirectory($EvidenceRoot)|Out-Null
    if($Mode -eq 'Prepare'){
        $document=[ordered]@{schema_version='env-1b3-reboot-resume-v1';overall_task_id='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE';candidate_id=$CandidateId;next_case_id=$NextCaseId;prepared_at_utc=[DateTime]::UtcNow.ToString('o');resume_action='rerun with -Mode Resume';user_reboot_approval_required=$true}
        [IO.File]::WriteAllText($path,($document|ConvertTo-Json -Compress)+"`n",[Text.UTF8Encoding]::new($false))
        Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W11-pre-reboot' -Result 'PASS' -Code 'ENV1B3_REBOOT_PREPARED' -Evidence @{candidate_id=$CandidateId;user_reboot_approval_required=$true}|ConvertTo-Json -Compress
        exit 0
    }
    $document=Read-ENV1B3Json $path
    $valid=$document.overall_task_id -eq 'ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE' -and $document.candidate_id -eq $CandidateId
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W11' -Result ($(if($valid){'PASS'}else{'FAIL'})) -Code ($(if($valid){'ENV1B3_REBOOT_RESUME_PASS'}else{'ENV1B3_REBOOT_RESUME_INVALID'})) -Evidence @{candidate_id=$CandidateId;resume_identity_valid=$valid}|ConvertTo-Json -Compress
    if(-not $valid){exit 2}
} catch { Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W11' -Result 'FAIL' -Code 'ENV1B3_REBOOT_RESUME_FAILED' -Evidence @{}|ConvertTo-Json -Compress; exit 2 }
