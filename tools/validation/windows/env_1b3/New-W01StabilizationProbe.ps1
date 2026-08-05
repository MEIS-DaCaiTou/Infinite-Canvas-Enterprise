[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Repository,
    [Parameter(Mandatory)][string]$OutputRoot,
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9][a-z0-9._-]{1,127}$')][string]$ExpectedCandidateId,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedCandidateHead,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedCandidateTree
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

try {
    [void](Assert-ENV1B3AbsoluteSafePath $Repository)
    [void](Assert-ENV1B3AbsoluteSafePath $OutputRoot -AllowMissingLeaf)
    if (-not (Test-Path -LiteralPath $OutputRoot)) { [IO.Directory]::CreateDirectory($OutputRoot) | Out-Null }
    $status = @(& git -C $Repository status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0 -or $status.Count -ne 0) { throw [InvalidOperationException]::new('ENV1B3_PROBE_GIT_NOT_CLEAN') }
    $head = (& git -C $Repository rev-parse HEAD).Trim()
    $tree = (& git -C $Repository rev-parse 'HEAD^{tree}').Trim()
    if ($head -notmatch '^[0-9a-f]{40}$' -or $tree -notmatch '^[0-9a-f]{40}$') { throw [InvalidOperationException]::new('ENV1B3_PROBE_GIT_IDENTITY_INVALID') }

    $name = 'ENV-1B3-W01-STABILIZATION-PROBE-' + $head
    $staging = Join-Path $OutputRoot $name
    $zip = Join-Path $OutputRoot ($name + '.zip')
    if ((Test-Path -LiteralPath $staging) -or (Test-Path -LiteralPath $zip)) { throw [InvalidOperationException]::new('ENV1B3_PROBE_OUTPUT_EXISTS') }
    [IO.Directory]::CreateDirectory($staging) | Out-Null
    foreach ($file in @('ENV1B3.Validation.psm1','Invoke-EnvironmentBaseline.ps1','Invoke-W01StabilizationProbe.ps1')) {
        [IO.File]::Copy((Join-Path $PSScriptRoot $file),(Join-Path $staging $file),$false)
    }
    $manifest = [ordered]@{
        schema_version='env-1b3-w01-stabilization-probe-v1'
        overall_task_id='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE'
        developer_head=$head
        developer_tree=$tree
        expected_candidate_04_id=$ExpectedCandidateId
        expected_candidate_04_developer_head=$ExpectedCandidateHead
        expected_candidate_04_developer_tree=$ExpectedCandidateTree
        diagnostic_only=$true
        not_a_release_candidate=$true
        cannot_support_final_acceptance=$true
        production_approved=$false
    }
    [IO.File]::WriteAllText((Join-Path $staging 'PROBE-MANIFEST.json'),($manifest | ConvertTo-Json -Depth 6 -Compress)+"`n",[Text.UTF8Encoding]::new($false))
    $sumLines = @()
    foreach ($file in @(Get-ChildItem -LiteralPath $staging -File | Sort-Object Name)) {
        $sumLines += (Get-ENV1B3Sha256 $file.FullName) + '  ' + $file.Name
    }
    [IO.File]::WriteAllText((Join-Path $staging 'SHA256SUMS'),($sumLines -join "`n")+"`n",[Text.UTF8Encoding]::new($false))
    Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $zip -CompressionLevel Optimal
    [ordered]@{result='pass';developer_head=$head;developer_tree=$tree;probe_zip=$zip;probe_zip_sha256=(Get-ENV1B3Sha256 $zip)} | ConvertTo-Json -Compress
} catch {
    [ordered]@{status='blocked';code='ENV1B3_W01_PROBE_BUILD_FAILED'} | ConvertTo-Json -Compress
    exit 2
}
