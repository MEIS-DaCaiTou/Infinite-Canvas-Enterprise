[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [ValidateSet('W02','W05')][string]$CaseId = 'W02'
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
try {
    $verified = Test-ENV1B3Handoff -HandoffRoot $HandoffRoot
    $handoff = Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json')
    $test = Assert-ENV1B3AbsoluteSafePath $TestRoot -AllowMissingLeaf
    $installRoot = Join-Path $test 'install'
    $releaseRoot = Join-Path $installRoot 'releases'
    $appRoot = Join-Path $releaseRoot ([string]$handoff.release_id)
    if (Test-Path -LiteralPath $appRoot) { throw [InvalidOperationException]::new('ENV1B3_MATERIALIZE_DESTINATION_EXISTS|app_root') }
    [IO.Directory]::CreateDirectory($releaseRoot) | Out-Null
    $manifestPath = Join-Path $HandoffRoot ([string]$handoff.manifest_filename)
    $inventoryPath = Join-Path $HandoffRoot ([string]$handoff.inventory_filename)
    $archivePath = Join-Path $HandoffRoot ([string]$handoff.archive_filename)
    $manifest = Read-ENV1B3Json $manifestPath
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Directory]::CreateDirectory($appRoot) | Out-Null
    try {
        $zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
        try {
            $prefix = [string]$manifest.archive.root_prefix + '/'
            foreach ($entry in $zip.Entries) {
                if ($entry.FullName.EndsWith('/')) { continue }
                if (-not $entry.FullName.StartsWith($prefix, [StringComparison]::Ordinal)) { throw [InvalidOperationException]::new('ENV1B3_ARCHIVE_INVENTORY_MISMATCH|root') }
                $relative = $entry.FullName.Substring($prefix.Length)
                if (-not (Test-ENV1B3SafeRelativePath $relative)) { throw [InvalidOperationException]::new('ENV1B3_ARCHIVE_PATH_INVALID|entry') }
                $target = Join-Path $appRoot ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
                [IO.Directory]::CreateDirectory((Split-Path -Parent $target)) | Out-Null
                if (Test-Path -LiteralPath $target) { throw [InvalidOperationException]::new('ENV1B3_MATERIALIZE_COLLISION|file') }
                $input = $entry.Open()
                try {
                    $output = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
                    try { $input.CopyTo($output) } finally { $output.Dispose() }
                } finally { $input.Dispose() }
            }
        } finally { $zip.Dispose() }
        [IO.File]::Copy($manifestPath, (Join-Path $appRoot 'release-manifest.json'), $false)
        foreach ($directory in @('config','data\uploads','logs','backups','state','staging')) { [IO.Directory]::CreateDirectory((Join-Path $installRoot $directory)) | Out-Null }
        $pointer = [ordered]@{
            activated_at=[DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
            app_root_relative=('releases/' + [string]$handoff.release_id)
            manifest_sha256=[string]$handoff.manifest_sha256
            previous_release_id=$null
            release_id=[string]$handoff.release_id
            schema_version='env-1b1b-current-release-v1'
        }
        $pointerBytes = [Text.UTF8Encoding]::new($false).GetBytes(($pointer | ConvertTo-Json -Compress) + "`n")
        $pointerPath = Join-Path $installRoot 'state\current-release.json'
        $pointerTemp = $pointerPath + '.new'
        [IO.File]::WriteAllBytes($pointerTemp, $pointerBytes)
        [IO.File]::Move($pointerTemp, $pointerPath)
        $python = Join-Path $appRoot 'python\python.exe'
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw [InvalidOperationException]::new('ENV1B3_FIXED_PYTHON_MISSING|python') }
        $tool = Join-Path $appRoot 'tools\build_release_manifest_v2.py'
        $embeddedInventory = Join-Path $appRoot ([string]$manifest.release_payload.inventory_path)
        $output = & $python -I -B $tool verify-materialized --app-root $appRoot --inventory $embeddedInventory 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) { throw [InvalidOperationException]::new('ENV1B3_MATERIALIZED_VERIFY_FAILED|verifier') }
        $record = Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -Result 'PASS' -Code 'ENV1B3_MATERIALIZATION_PASS' -Evidence @{
            candidate_id=$verified.candidate_id
            release_id=$verified.release_id
            materialized_verify_exit=$exitCode
            fixed_python_basename=[IO.Path]::GetFileName($python)
            payload_tree_sha256=$verified.artifact.payload_tree_sha256
            app_root_symbol='<APP_ROOT>'
            install_root_symbol='<TEST_ROOT>/install'
        }
        $record | ConvertTo-Json -Depth 8 -Compress
    } catch {
        if (Test-Path -LiteralPath $appRoot) { Remove-Item -LiteralPath $appRoot -Recurse -Force -ErrorAction SilentlyContinue }
        throw
    }
} catch {
    $code = 'ENV1B3_MATERIALIZATION_FAILED'
    if ($_.Exception.Message -match '^([A-Z0-9_]+)\|') { $code = $Matches[1] }
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $CaseId -Result 'FAIL' -Code $code -Evidence @{} | ConvertTo-Json -Compress
    exit 2
}
