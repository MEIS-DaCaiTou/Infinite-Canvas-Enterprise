[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Repository,
    [Parameter(Mandatory)][string]$BuildRoot,
    [Parameter(Mandatory)][string]$CandidateRoot,
    [Parameter(Mandatory)][ValidatePattern('^0[1-3]$')][string]$CandidateSequence,
    [Parameter(Mandatory)][string]$TestHostTaskbook
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
try {
    foreach($path in @($Repository,$BuildRoot,$TestHostTaskbook)){[void](Assert-ENV1B3AbsoluteSafePath $path)}
    [void](Assert-ENV1B3AbsoluteSafePath $CandidateRoot -AllowMissingLeaf)
    if(-not (Test-Path -LiteralPath $CandidateRoot)){[IO.Directory]::CreateDirectory($CandidateRoot)|Out-Null}
    $handoffRoot=Join-Path $CandidateRoot 'handoff'
    if((Test-Path -LiteralPath $handoffRoot) -or @(Get-ChildItem -LiteralPath $CandidateRoot -Force | Where-Object { $_.Name -ne 'release-build' }).Count -ne 0){throw [InvalidOperationException]::new('ENV1B3_CANDIDATE_OUTPUT_EXISTS|candidate')}
    $status=@(& git -C $Repository status --porcelain=v1 --untracked-files=all)
    if($LASTEXITCODE -ne 0 -or $status.Count -ne 0){throw [InvalidOperationException]::new('ENV1B3_GIT_NOT_CLEAN|repository')}
    $head=(& git -C $Repository rev-parse HEAD).Trim();$tree=(& git -C $Repository rev-parse 'HEAD^{tree}').Trim()
    if($head -notmatch '^[0-9a-f]{40}$' -or $tree -notmatch '^[0-9a-f]{40}$'){throw [InvalidOperationException]::new('ENV1B3_GIT_IDENTITY_INVALID|repository')}
    $manifestPath=Join-Path $BuildRoot 'ops-release-manifest-v2.json';$inventoryPath=Join-Path $BuildRoot 'release-payload-inventory.json'
    $manifest=Read-ENV1B3Json $manifestPath
    if($manifest.enterprise_source.commit -ne $head -or $manifest.enterprise_source.tree -ne $tree){throw [InvalidOperationException]::new('ENV1B3_BUILD_GIT_IDENTITY_MISMATCH|build')}
    $archivePath=Join-Path $BuildRoot ([string]$manifest.archive.filename)
    $verified=Test-ENV1B3ReleaseArtifacts -ManifestPath $manifestPath -ArchivePath $archivePath -InventoryPath $inventoryPath
    $releaseId=[string]$manifest.identity.release_id;$candidateId=$releaseId+'-candidate-'+$CandidateSequence
    [IO.Directory]::CreateDirectory($handoffRoot)|Out-Null
    foreach($source in @($archivePath,$manifestPath,$inventoryPath)){[IO.File]::Copy($source,(Join-Path $handoffRoot ([IO.Path]::GetFileName($source))),$false)}
    Copy-Item -LiteralPath $PSScriptRoot -Destination (Join-Path $handoffRoot 'validation-kit') -Recurse
    $taskbookName='ENV-1B3-INDEPENDENT-WINDOWS-TEST-HOST-CODEX-TASK.md';[IO.File]::Copy($TestHostTaskbook,(Join-Path $handoffRoot $taskbookName),$false)
    $taskbookHash=Get-ENV1B3Sha256 (Join-Path $handoffRoot $taskbookName)
    $document=[ordered]@{
        schema_version='env-1b3-candidate-handoff-v1';overall_task_id='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE';candidate_id=$candidateId;candidate_sequence=$CandidateSequence
        developer_head=$head;developer_tree=$tree;release_id=$releaseId
        archive_filename=[IO.Path]::GetFileName($archivePath);archive_size_bytes=(Get-Item -LiteralPath $archivePath).Length;archive_sha256=$verified.archive_sha256
        manifest_filename=[IO.Path]::GetFileName($manifestPath);manifest_sha256=$verified.manifest_sha256
        inventory_filename=[IO.Path]::GetFileName($inventoryPath);inventory_sha256=$verified.inventory_sha256
        payload_tree_sha256=[string]$manifest.release_payload.tree_sha256;runtime_tree_sha256=[string]$manifest.runtime.runtime_tree_sha256;static_tree_sha256=[string]$manifest.release_payload.static_tree_sha256
        validation_matrix_version='env-1b3-windows-validation-matrix-v1';expected_test_host_taskbook_sha256=$taskbookHash;production_approved=$false
    }
    [IO.File]::WriteAllText((Join-Path $handoffRoot 'CANDIDATE-HANDOFF.json'),($document|ConvertTo-Json -Depth 8 -Compress)+"`n",[Text.UTF8Encoding]::new($false))
    $readme=@"
# Read first

This immutable handoff is for candidate `$candidateId` under `ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE`.

1. Record the outer ZIP SHA-256 before extraction.
2. Read `CANDIDATE-HANDOFF.json` and the included independent test-host taskbook.
3. Keep this input copy read-only; use new test roots for materialization and tamper cases.
4. Start with `validation-kit\Invoke-ENV1B3Validation.ps1 -Mode Baseline`.

This is a Release Candidate, not a formal Release or production-approved payload.
"@
    [IO.File]::WriteAllText((Join-Path $handoffRoot 'README-FIRST.md'),$readme,[Text.UTF8Encoding]::new($false))
    $sumLines=@();foreach($file in @(Get-ChildItem -LiteralPath $handoffRoot -File -Recurse|Sort-Object FullName)){$relative=$file.FullName.Substring($handoffRoot.Length).TrimStart('\').Replace('\','/');$sumLines+=(Get-ENV1B3Sha256 $file.FullName)+'  '+$relative}
    [IO.File]::WriteAllText((Join-Path $handoffRoot 'SHA256SUMS'),($sumLines -join "`n")+"`n",[Text.UTF8Encoding]::new($false))
    $zip=Join-Path $CandidateRoot ('ENV-1B3-'+$candidateId+'-TEST-HOST-HANDOFF.zip')
    Compress-Archive -Path (Join-Path $handoffRoot '*') -DestinationPath $zip -CompressionLevel Optimal
    [ordered]@{result='pass';candidate_id=$candidateId;developer_head=$head;developer_tree=$tree;handoff_zip=[IO.Path]::GetFileName($zip);handoff_zip_sha256=(Get-ENV1B3Sha256 $zip);archive_sha256=$verified.archive_sha256;manifest_sha256=$verified.manifest_sha256}|ConvertTo-Json -Compress
} catch {
    $code='ENV1B3_HANDOFF_BUILD_FAILED';if($_.Exception.Message -match '^([A-Z0-9_]+)\|'){$code=$Matches[1]};[ordered]@{status='blocked';code=$code}|ConvertTo-Json -Compress;exit 2
}
