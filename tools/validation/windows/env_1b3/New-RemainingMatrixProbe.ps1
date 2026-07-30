[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Repository,
    [Parameter(Mandatory)][string]$OutputRoot,
    [Parameter(Mandatory)][string]$ExpectedCandidateId,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedCandidateHandoffSha256
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
try{
    foreach($path in @($Repository)){[void](Assert-ENV1B3AbsoluteSafePath $path)}
    [void](Assert-ENV1B3AbsoluteSafePath $OutputRoot -AllowMissingLeaf)
    $status=@(& git -C $Repository status --porcelain=v1 --untracked-files=all)
    if($LASTEXITCODE -ne 0 -or $status.Count -ne 0){throw [InvalidOperationException]::new('ENV1B3_GIT_NOT_CLEAN|repository')}
    $head=(& git -C $Repository rev-parse HEAD).Trim();$tree=(& git -C $Repository rev-parse 'HEAD^{tree}').Trim()
    $name='ENV-1B3-REMAINING-MATRIX-PROBE-'+$head
    $root=Join-Path $OutputRoot $name;$zip=$root+'.zip'
    if((Test-Path -LiteralPath $root) -or (Test-Path -LiteralPath $zip)){throw [InvalidOperationException]::new('ENV1B3_PROBE_OUTPUT_EXISTS|probe')}
    [IO.Directory]::CreateDirectory((Join-Path $root 'validation-kit'))|Out-Null
    foreach($file in @(Get-ChildItem -LiteralPath $PSScriptRoot -File|Where-Object{
        $_.Name -like 'Invoke-*.ps1' -or $_.Extension -eq '.psm1' -or $_.Name -in @('verify_materialized_release.py','matrix.json','README.md')
    })){
        if($file.Name -eq 'Invoke-RemainingMatrixProbe.ps1'){continue}
        [IO.File]::Copy($file.FullName,(Join-Path $root ('validation-kit\'+$file.Name)),$false)
    }
    [IO.File]::Copy((Join-Path $PSScriptRoot 'Invoke-RemainingMatrixProbe.ps1'),(Join-Path $root 'Invoke-RemainingMatrixProbe.ps1'),$false)
    $verifierRelative='validation-kit/verify_materialized_release.py'
    $verifierHash=Get-ENV1B3Sha256 (Join-Path $root ($verifierRelative.Replace('/',[IO.Path]::DirectorySeparatorChar)))
    $document=[ordered]@{
        schema_version='env-1b3-remaining-matrix-probe-v1';overall_task_id='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE'
        developer_head=$head;developer_tree=$tree;expected_candidate_id=$ExpectedCandidateId;expected_candidate_handoff_sha256=$ExpectedCandidateHandoffSha256
        materialized_verifier_filename=$verifierRelative;materialized_verifier_sha256=$verifierHash
        diagnostic_only=$true;not_a_release_candidate=$true;cannot_support_final_acceptance=$true;production_approved=$false
        executable_cases=@('W02','W03','W04','W05','W06','W07','W08','W09','W10','W11','W14','M01')
    }
    [IO.File]::WriteAllText((Join-Path $root 'PROBE-MANIFEST.json'),($document|ConvertTo-Json -Depth 8 -Compress)+"`n",[Text.UTF8Encoding]::new($false))
    $lines=@();foreach($file in @(Get-ChildItem -LiteralPath $root -File -Recurse|Where-Object{$_.Name -ne 'SHA256SUMS'}|Sort-Object FullName)){
        $relative=$file.FullName.Substring($root.Length).TrimStart('\').Replace('\','/');$lines+=(Get-ENV1B3Sha256 $file.FullName)+'  '+$relative
    }
    [IO.File]::WriteAllText((Join-Path $root 'SHA256SUMS'),($lines -join "`n")+"`n",[Text.UTF8Encoding]::new($false))
    Compress-Archive -Path (Join-Path $root '*') -DestinationPath $zip -CompressionLevel Optimal
    [ordered]@{result='pass';developer_head=$head;developer_tree=$tree;probe_zip=$zip;probe_zip_sha256=(Get-ENV1B3Sha256 $zip);materialized_verifier_sha256=$verifierHash}|ConvertTo-Json -Compress
}catch{
    $code='ENV1B3_PROBE_BUILD_FAILED';if($_.Exception.Message -match '^([A-Z0-9_]+)\|'){$code=$Matches[1]};[ordered]@{status='blocked';code=$code}|ConvertTo-Json -Compress;exit 2
}
