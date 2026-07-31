[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Repository,[Parameter(Mandatory)][string]$OutputRoot,
    [Parameter(Mandatory)][string]$ExpectedCandidateId,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedCandidateHandoffSha256,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedProbeV2EvidenceSha256,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedW12EvidenceSha256
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
try{
    $status=@(& git -C $Repository status --porcelain=v1 --untracked-files=all);if($LASTEXITCODE-ne0-or$status.Count-ne0){throw[InvalidOperationException]::new('ENV1B3_GIT_NOT_CLEAN|repository')}
    $head=(& git -C $Repository rev-parse HEAD).Trim();$tree=(& git -C $Repository rev-parse 'HEAD^{tree}').Trim()
    $name='ENV-1B3-FAILED-MATRIX-CLOSURE-PROBE-V3R1-'+$head;$root=Join-Path $OutputRoot $name;$zip=$root+'.zip'
    if((Test-Path -LiteralPath $root)-or(Test-Path -LiteralPath $zip)){throw[InvalidOperationException]::new('ENV1B3_PROBE_OUTPUT_EXISTS|probe')}
    [IO.Directory]::CreateDirectory((Join-Path $root 'validation-kit'))|Out-Null
    foreach($file in @(Get-ChildItem -LiteralPath $PSScriptRoot -File|Where-Object{$_.Name-like'Invoke-*.ps1'-or$_.Extension-eq'.psm1'-or$_.Name-in@('verify_materialized_release.py','matrix.json','matrix-contracts.json','README.md')})){
        if($file.Name-like'Invoke-*Probe*.ps1'){continue};[IO.File]::Copy($file.FullName,(Join-Path $root ('validation-kit\'+$file.Name)),$false)
    }
    [IO.File]::Copy((Join-Path $PSScriptRoot 'Invoke-FailedMatrixClosureProbeV3R1.ps1'),(Join-Path $root 'Invoke-FailedMatrixClosureProbeV3R1.ps1'),$false)
    $contractRel='validation-kit/matrix-contracts.json';$contractSha=Get-ENV1B3Sha256 (Join-Path $root ($contractRel.Replace('/',[IO.Path]::DirectorySeparatorChar)))
    $cases=@('W05','W08Pointer','W08ReleaseManifest','W08RuntimeManifest','W08Payload','W08PythonDll','W09','W10','W11StoppedPrepare','W11StoppedResume','W11RunningPrepare','W11RunningResume','W12EvidenceAudit','W13','ContractAudit')
    $doc=[ordered]@{schema_version='env-1b3-failed-matrix-closure-probe-v3r1';overall_task_id='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE';developer_head=$head;developer_tree=$tree;expected_candidate_id=$ExpectedCandidateId;expected_candidate_handoff_sha256=$ExpectedCandidateHandoffSha256;expected_probe_v2_evidence_sha256=$ExpectedProbeV2EvidenceSha256;expected_w12_evidence_sha256=$ExpectedW12EvidenceSha256;matrix_contract_filename=$contractRel;matrix_contract_sha256=$contractSha;diagnostic_only=$true;not_a_release_candidate=$true;cannot_support_final_acceptance=$true;production_approved=$false;executable_cases=$cases}
    [IO.File]::WriteAllText((Join-Path $root 'PROBE-MANIFEST.json'),($doc|ConvertTo-Json -Depth 8 -Compress)+"`n",[Text.UTF8Encoding]::new($false))
    $readme=@(
        '# Failed Matrix Closure Probe v3R1','',
        ('Candidate: '+$ExpectedCandidateId),'',
        'For every W08 target: restore the same Probe pre-target checkpoint, run exactly one public W08 target mode, export that target evidence, and restore the checkpoint again before the next target.',
        'Do not use W08Aggregate as the Guest diagnostic entry. After all five independent target runs, merge the five exclusive subcheck files on the host and run ContractAudit.',
        'Read validation-kit/README.md before execution. This bundle is diagnostic-only, is not a Release Candidate, and cannot support final acceptance.'
    )
    [IO.File]::WriteAllText((Join-Path $root 'README-FIRST.md'),($readme-join"`n")+"`n",[Text.UTF8Encoding]::new($false))
    $lines=@();foreach($file in @(Get-ChildItem -LiteralPath $root -File -Recurse|Where-Object{$_.Name-ne'SHA256SUMS'}|Sort-Object FullName)){$rel=$file.FullName.Substring($root.Length).TrimStart('\').Replace('\','/');$lines+=(Get-ENV1B3Sha256 $file.FullName)+'  '+$rel};[IO.File]::WriteAllText((Join-Path $root 'SHA256SUMS'),($lines-join"`n")+"`n",[Text.UTF8Encoding]::new($false))
    Add-Type -AssemblyName System.IO.Compression;Add-Type -AssemblyName System.IO.Compression.FileSystem;$archive=[IO.Compression.ZipFile]::Open($zip,[IO.Compression.ZipArchiveMode]::Create)
    try{foreach($file in @(Get-ChildItem -LiteralPath $root -File -Recurse|Sort-Object FullName)){$rel=$file.FullName.Substring($root.Length).TrimStart('\').Replace('\','/');if(-not(Test-ENV1B3SafeRelativePath $rel)){throw[InvalidOperationException]::new('ENV1B3_PROBE_ARCHIVE_PATH_INVALID|probe')};$entry=$archive.CreateEntry($rel,[IO.Compression.CompressionLevel]::Optimal);$i=[IO.File]::OpenRead($file.FullName);$o=$entry.Open();try{$i.CopyTo($o)}finally{$o.Dispose();$i.Dispose()}}}finally{$archive.Dispose()}
    [ordered]@{result='pass';developer_head=$head;developer_tree=$tree;probe_zip=$zip;probe_zip_sha256=(Get-ENV1B3Sha256 $zip);matrix_contract_sha256=$contractSha}|ConvertTo-Json -Compress
}catch{$code='ENV1B3_PROBE_BUILD_FAILED';if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]};[ordered]@{status='blocked';code=$code}|ConvertTo-Json -Compress;exit 2}
