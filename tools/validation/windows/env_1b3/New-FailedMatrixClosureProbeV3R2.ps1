[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Repository,
    [Parameter(Mandatory)][string]$OutputRoot,
    [Parameter(Mandatory)][string]$ExpectedCandidateId,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedCandidateHandoffSha256,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedProbeV2EvidenceSha256,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedW12EvidenceSha256
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

try {
    $status = @(& git -C $Repository status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0 -or $status.Count -ne 0) { throw [InvalidOperationException]::new('ENV1B3_GIT_NOT_CLEAN|repository') }
    $head = (& git -C $Repository rev-parse HEAD).Trim()
    $tree = (& git -C $Repository rev-parse 'HEAD^{tree}').Trim()
    $name = 'ENV-1B3-FAILED-MATRIX-CLOSURE-PROBE-V3R2-' + $head
    $root = Join-Path $OutputRoot $name
    $zip = $root + '.zip'
    if ((Test-Path -LiteralPath $root) -or (Test-Path -LiteralPath $zip)) {
        throw [InvalidOperationException]::new('ENV1B3_PROBE_OUTPUT_EXISTS|probe')
    }
    [IO.Directory]::CreateDirectory((Join-Path $root 'validation-kit')) | Out-Null
    foreach ($file in @(Get-ChildItem -LiteralPath $PSScriptRoot -File | Where-Object {
        $_.Name -like 'Invoke-*.ps1' -or $_.Extension -eq '.psm1' -or
        $_.Name -in @('verify_materialized_release.py','matrix.json','matrix-contracts.json','README.md')
    })) {
        if ($file.Name -like 'Invoke-*Probe*.ps1') { continue }
        [IO.File]::Copy($file.FullName, (Join-Path $root ('validation-kit\' + $file.Name)), $false)
    }
    [IO.File]::Copy((Join-Path $PSScriptRoot 'Invoke-FailedMatrixClosureProbeV3R2.ps1'), (Join-Path $root 'Invoke-FailedMatrixClosureProbeV3R2.ps1'), $false)
    $contractRelative = 'validation-kit/matrix-contracts.json'
    $contractSha = Get-ENV1B3Sha256 (Join-Path $root ($contractRelative.Replace('/',[IO.Path]::DirectorySeparatorChar)))
    $guestCases = @(
        'W05','W08Pointer','W08ReleaseManifest','W08RuntimeManifest','W08Payload','W08PythonDll',
        'W09','W10','W11StoppedPrepare','W11StoppedResume','W11RunningPrepare','W11RunningResume','W13'
    )
    $hostCases = @('W08HostAggregate','W12EvidenceAudit','ContractAudit')
    $document = [ordered]@{
        schema_version='env-1b3-failed-matrix-closure-probe-v3r2'
        overall_task_id='ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE'
        developer_head=$head
        developer_tree=$tree
        expected_candidate_id=$ExpectedCandidateId
        expected_candidate_handoff_sha256=$ExpectedCandidateHandoffSha256
        expected_probe_v2_evidence_sha256=$ExpectedProbeV2EvidenceSha256
        expected_w12_evidence_sha256=$ExpectedW12EvidenceSha256
        matrix_contract_filename=$contractRelative
        matrix_contract_sha256=$contractSha
        guest_executable_cases=$guestCases
        host_only_cases=$hostCases
        diagnostic_only=$true
        not_a_release_candidate=$true
        cannot_support_final_acceptance=$true
        production_approved=$false
    }
    [IO.File]::WriteAllText((Join-Path $root 'PROBE-MANIFEST.json'), ($document | ConvertTo-Json -Depth 8 -Compress) + "`n", [Text.UTF8Encoding]::new($false))
    $readme = @(
        '# Failed Matrix Closure Probe v3R2','',
        ('Candidate: ' + $ExpectedCandidateId),'',
        'Guest modes and host-only modes are separately declared in PROBE-MANIFEST.json.',
        'For W08, restore the same pre-target checkpoint, run one Guest target, export its evidence, and restore again before the next target.',
        'Run W08HostAggregate only on the host after all five immutable target evidence roots are available. It reads evidence only and never runs the Candidate.',
        'W08Aggregate is deprecated and always returns BLOCKED. Read validation-kit/README.md before execution.',
        'This bundle is diagnostic-only, is not a Release Candidate, and cannot support final acceptance.'
    )
    [IO.File]::WriteAllText((Join-Path $root 'README-FIRST.md'), ($readme -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
    $lines = @()
    foreach ($file in @(Get-ChildItem -LiteralPath $root -File -Recurse | Where-Object { $_.Name -ne 'SHA256SUMS' } | Sort-Object FullName)) {
        $relative = $file.FullName.Substring($root.Length).TrimStart('\').Replace('\','/')
        $lines += (Get-ENV1B3Sha256 $file.FullName) + '  ' + $relative
    }
    [IO.File]::WriteAllText((Join-Path $root 'SHA256SUMS'), ($lines -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::Open($zip, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($file in @(Get-ChildItem -LiteralPath $root -File -Recurse | Sort-Object FullName)) {
            $relative = $file.FullName.Substring($root.Length).TrimStart('\').Replace('\','/')
            if (-not (Test-ENV1B3SafeRelativePath $relative)) { throw [InvalidOperationException]::new('ENV1B3_PROBE_ARCHIVE_PATH_INVALID|probe') }
            $entry = $archive.CreateEntry($relative, [IO.Compression.CompressionLevel]::Optimal)
            $input = [IO.File]::OpenRead($file.FullName)
            $output = $entry.Open()
            try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
        }
    } finally { $archive.Dispose() }
    [ordered]@{result='pass';developer_head=$head;developer_tree=$tree;probe_zip=$zip;probe_zip_sha256=(Get-ENV1B3Sha256 $zip);matrix_contract_sha256=$contractSha} | ConvertTo-Json -Compress
} catch {
    $code = 'ENV1B3_PROBE_BUILD_FAILED'
    if ($_.Exception.Message -match '(ENV1B3_[A-Z0-9_]+)\|') { $code = $Matches[1] }
    [ordered]@{status='blocked';code=$code} | ConvertTo-Json -Compress
    exit 2
}
