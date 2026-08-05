Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

function Invoke-ENV1B3MaterializedVerifier {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$PythonExecutable,
        [Parameter(Mandatory)][string]$VerifierPath,
        [Parameter(Mandatory)][string]$AppRoot,
        [Parameter(Mandatory)][string]$InventoryPath,
        [Parameter(Mandatory)][string]$ManifestPath,
        [Parameter(Mandatory)][string]$HandoffPath
    )
    $output = @()
    try {
        $output = @(& $PythonExecutable -I -B $VerifierPath --app-root $AppRoot --inventory $InventoryPath --manifest $ManifestPath --handoff $HandoffPath 2>&1)
        $exitCode = [int]$LASTEXITCODE
    } catch {
        return [ordered]@{exit_code=2;output='ENV1B3_MATERIALIZED_VERIFIER_EXECUTION_FAILED'}
    }
    $text = ($output | ForEach-Object {[string]$_}) -join "`n"
    if ($text.Length -gt 8192) { $text = $text.Substring($text.Length - 8192) }
    return [ordered]@{exit_code=$exitCode;output=$text}
}

function Remove-ENV1B3OwnedDirectory {
    param([Parameter(Mandatory)][string]$LiteralPath, [Parameter(Mandatory)][string]$RequiredParent)
    if (-not (Test-Path -LiteralPath $LiteralPath)) { return }
    $path = [IO.Path]::GetFullPath($LiteralPath)
    $parent = [IO.Path]::GetFullPath($RequiredParent).TrimEnd('\') + '\'
    if (-not $path.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase)) {
        throw [InvalidOperationException]::new('ENV1B3_MATERIALIZE_CLEANUP_SCOPE_INVALID|cleanup')
    }
    Remove-Item -LiteralPath $path -Recurse -Force
}

function Invoke-ENV1B3AtomicMaterialization {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$HandoffRoot,
        [Parameter(Mandatory)][string]$TestRoot,
        [Parameter(Mandatory)][string]$VerifierPath,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedVerifierSha256,
        [ValidateSet('None','Extraction','Verifier','FinalMove','PointerWrite')][string]$FaultInjection='None',
        [scriptblock]$VerifierInvoker
    )
    $verified = Test-ENV1B3Handoff -HandoffRoot $HandoffRoot
    $handoff = Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json')
    $test = Assert-ENV1B3AbsoluteSafePath $TestRoot -AllowMissingLeaf
    $verifier = Assert-ENV1B3AbsoluteSafePath $VerifierPath
    if ((Get-ENV1B3Sha256 $verifier) -ne $ExpectedVerifierSha256) {
        throw [InvalidOperationException]::new('ENV1B3_MATERIALIZED_VERIFIER_HASH_MISMATCH|verifier')
    }

    $installRoot = Join-Path $test 'install'
    $stagingRoot = Join-Path $installRoot 'staging'
    $releaseRoot = Join-Path $installRoot 'releases'
    $stateRoot = Join-Path $installRoot 'state'
    $releaseId = [string]$handoff.release_id
    $partialRoot = Join-Path $stagingRoot ($releaseId + '.partial')
    $appRoot = Join-Path $releaseRoot $releaseId
    $pointerPath = Join-Path $stateRoot 'current-release.json'
    $pointerTemp = $pointerPath + '.new'
    foreach ($root in @($installRoot,$stagingRoot,$releaseRoot,$stateRoot)) {
        [void](Assert-ENV1B3AbsoluteSafePath $root -AllowMissingLeaf)
    }
    if ((Test-Path -LiteralPath $partialRoot) -or (Test-Path -LiteralPath $appRoot)) {
        throw [InvalidOperationException]::new('ENV1B3_MATERIALIZE_DESTINATION_EXISTS|app_root')
    }
    if (Test-Path -LiteralPath $pointerTemp) {
        throw [InvalidOperationException]::new('ENV1B3_POINTER_TEMP_EXISTS|pointer')
    }
    [IO.Directory]::CreateDirectory($stagingRoot) | Out-Null
    [IO.Directory]::CreateDirectory($releaseRoot) | Out-Null
    [IO.Directory]::CreateDirectory($stateRoot) | Out-Null
    foreach ($root in @($installRoot,$stagingRoot,$releaseRoot,$stateRoot)) { [void](Assert-ENV1B3AbsoluteSafePath $root) }

    $manifestPath = Join-Path $HandoffRoot ([string]$handoff.manifest_filename)
    $archivePath = Join-Path $HandoffRoot ([string]$handoff.archive_filename)
    $manifest = Read-ENV1B3Json $manifestPath
    $partialOwned = $false
    $finalOwned = $false
    $pointerTempOwned = $false
    $pointerCommitted = $false
    $written = 0
    try {
        [IO.Directory]::CreateDirectory($partialRoot) | Out-Null
        $partialOwned = $true
        [void](Assert-ENV1B3AbsoluteSafePath $partialRoot)
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
        try {
            $prefix = [string]$manifest.archive.root_prefix + '/'
            $seen = @{}
            foreach ($entry in $zip.Entries) {
                if ($entry.FullName.EndsWith('/')) { continue }
                if (Test-ENV1B3ZipEntryUnsafe $entry) { throw [InvalidOperationException]::new('ENV1B3_ARCHIVE_PATH_INVALID|entry') }
                if (-not $entry.FullName.StartsWith($prefix, [StringComparison]::Ordinal)) { throw [InvalidOperationException]::new('ENV1B3_ARCHIVE_INVENTORY_MISMATCH|root') }
                $relative = $entry.FullName.Substring($prefix.Length)
                if (-not (Test-ENV1B3SafeRelativePath $relative)) { throw [InvalidOperationException]::new('ENV1B3_ARCHIVE_PATH_INVALID|entry') }
                $key = $relative.ToLowerInvariant()
                if ($seen.ContainsKey($key)) { throw [InvalidOperationException]::new('ENV1B3_MATERIALIZE_COLLISION|file') }
                $seen[$key] = $true
                $target = Join-Path $partialRoot ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
                $targetParent = Split-Path -Parent $target
                [IO.Directory]::CreateDirectory($targetParent) | Out-Null
                [void](Assert-ENV1B3AbsoluteSafePath $targetParent)
                if (Test-Path -LiteralPath $target) { throw [InvalidOperationException]::new('ENV1B3_MATERIALIZE_COLLISION|file') }
                $input = $entry.Open()
                try {
                    $output = [IO.File]::Open($target,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
                    try { $input.CopyTo($output); $output.Flush($true) } finally { $output.Dispose() }
                } finally { $input.Dispose() }
                $written++
                if ($FaultInjection -eq 'Extraction') { throw [InvalidOperationException]::new('ENV1B3_MATERIALIZE_INJECTED_EXTRACTION_FAILURE|fixture') }
            }
        } finally { $zip.Dispose() }
        [IO.File]::Copy($manifestPath,(Join-Path $partialRoot 'release-manifest.json'),$false)
        [void](Assert-ENV1B3AbsoluteSafePath $partialRoot)

        $python = Join-Path $partialRoot 'python\python.exe'
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw [InvalidOperationException]::new('ENV1B3_FIXED_PYTHON_MISSING|python') }
        $embeddedInventory = Join-Path $partialRoot ([string]$manifest.release_payload.inventory_path)
        if ($FaultInjection -eq 'Verifier') { throw [InvalidOperationException]::new('ENV1B3_MATERIALIZE_INJECTED_VERIFIER_FAILURE|fixture') }
        if ($null -eq $VerifierInvoker) {
            $verification = Invoke-ENV1B3MaterializedVerifier -PythonExecutable $python -VerifierPath $verifier -AppRoot $partialRoot -InventoryPath $embeddedInventory -ManifestPath (Join-Path $partialRoot 'release-manifest.json') -HandoffPath (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json')
        } else {
            $verification = & $VerifierInvoker $python $verifier $partialRoot $embeddedInventory (Join-Path $partialRoot 'release-manifest.json') (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json')
        }
        if ([int]$verification.exit_code -ne 0) { throw [InvalidOperationException]::new('ENV1B3_MATERIALIZED_VERIFY_FAILED|verifier') }
        try { $verificationPayload = [string]$verification.output | ConvertFrom-Json } catch { throw [InvalidOperationException]::new('ENV1B3_MATERIALIZED_VERIFY_FAILED|verifier') }
        if ($verificationPayload.result -ne 'pass' -or [string]$verificationPayload.payload_tree_sha256 -ne [string]$handoff.payload_tree_sha256) {
            throw [InvalidOperationException]::new('ENV1B3_MATERIALIZED_VERIFY_FAILED|verifier')
        }

        if ($FaultInjection -eq 'FinalMove') { throw [InvalidOperationException]::new('ENV1B3_MATERIALIZE_INJECTED_FINAL_MOVE_FAILURE|fixture') }
        [IO.Directory]::Move($partialRoot,$appRoot)
        $partialOwned = $false
        $finalOwned = $true
        [void](Assert-ENV1B3AbsoluteSafePath $appRoot)

        # These are the portable profile's mutable roots.  They are never
        # placed in APP_ROOT and are created only after the staged Release has
        # passed the external verifier.
        $localBase=[Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
        if([String]::IsNullOrWhiteSpace($localBase)){throw [InvalidOperationException]::new('ENV1B3_LOCALAPPDATA_UNAVAILABLE|root')}
        $mutableRoots=@(
            (Join-Path $installRoot 'config'),(Join-Path $installRoot 'data'),(Join-Path $installRoot 'data\uploads'),
            (Join-Path $installRoot 'logs'),(Join-Path $installRoot 'backups'),
            (Join-Path $localBase 'InfiniteCanvasEnterprise\runtime'),
            (Join-Path $localBase 'Infinite-Canvas-Enterprise\cache'),
            (Join-Path $localBase 'Infinite-Canvas-Enterprise\temp')
        )
        foreach($mutable in $mutableRoots){
            [void](Assert-ENV1B3AbsoluteSafePath $mutable -AllowMissingLeaf)
            [IO.Directory]::CreateDirectory($mutable)|Out-Null
            [void](Assert-ENV1B3AbsoluteSafePath $mutable)
        }

        $pointer = [ordered]@{
            activated_at=[DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
            app_root_relative=('releases/' + $releaseId)
            manifest_sha256=[string]$handoff.manifest_sha256
            previous_release_id=$null
            release_id=$releaseId
            schema_version='env-1b1b-current-release-v1'
        }
        $pointerBytes = [Text.UTF8Encoding]::new($false).GetBytes(($pointer | ConvertTo-Json -Compress) + "`n")
        $stream = [IO.File]::Open($pointerTemp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $pointerTempOwned = $true
        try { $stream.Write($pointerBytes,0,$pointerBytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        if ($FaultInjection -eq 'PointerWrite') { throw [InvalidOperationException]::new('ENV1B3_MATERIALIZE_INJECTED_POINTER_FAILURE|fixture') }
        if (Test-Path -LiteralPath $pointerPath) { [IO.File]::Replace($pointerTemp,$pointerPath,$null,$true) }
        else { [IO.File]::Move($pointerTemp,$pointerPath) }
        $pointerTempOwned = $false
        $pointerCommitted = $true
        return [ordered]@{
            result='pass';candidate_id=$verified.candidate_id;release_id=$releaseId;payload_tree_sha256=$verified.artifact.payload_tree_sha256
            app_root=$appRoot;install_root=$installRoot;pointer_path=$pointerPath;materialized_verify_exit=0;archive_entries_written=$written
        }
    } catch {
        $original = $_
        if (-not $pointerCommitted) {
            if ($pointerTempOwned -and (Test-Path -LiteralPath $pointerTemp)) { Remove-Item -LiteralPath $pointerTemp -Force -ErrorAction SilentlyContinue }
            if ($finalOwned -and (Test-Path -LiteralPath $appRoot)) { Remove-ENV1B3OwnedDirectory -LiteralPath $appRoot -RequiredParent $releaseRoot }
            if ($partialOwned -and (Test-Path -LiteralPath $partialRoot)) { Remove-ENV1B3OwnedDirectory -LiteralPath $partialRoot -RequiredParent $stagingRoot }
        }
        throw $original
    }
}

Export-ModuleMember -Function Invoke-ENV1B3AtomicMaterialization,Invoke-ENV1B3MaterializedVerifier
