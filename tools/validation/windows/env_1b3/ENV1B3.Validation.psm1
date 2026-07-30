Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:TaskId = 'ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE'
$script:MatrixVersion = 'env-1b3-windows-validation-matrix-v1'
$script:MaxJsonBytes = 16MB

function Throw-ENV1B3Error {
    param([Parameter(Mandatory)][string]$Code, [string]$Message = '')
    throw [InvalidOperationException]::new("$Code|$Message")
}

function Get-ENV1B3Sha256 {
    param([Parameter(Mandatory)][string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        Throw-ENV1B3Error 'ENV1B3_FILE_MISSING' 'file'
    }
    $stream = [IO.File]::Open($LiteralPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $hasher = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
        finally { $hasher.Dispose() }
    } finally { $stream.Dispose() }
}

function Test-ENV1B3SafeRelativePath {
    param([Parameter(Mandatory)][string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value.Length -gt 240) { return $false }
    if ($Value.Contains('\') -or $Value.StartsWith('/') -or $Value.Contains(':') -or $Value.Contains('*') -or $Value.Contains('?')) { return $false }
    $parts = $Value.Split('/')
    if ($parts.Count -eq 0) { return $false }
    $devices = @('CON','PRN','AUX','NUL','COM1','COM2','COM3','COM4','COM5','COM6','COM7','COM8','COM9','LPT1','LPT2','LPT3','LPT4','LPT5','LPT6','LPT7','LPT8','LPT9')
    foreach ($part in $parts) {
        if ([string]::IsNullOrWhiteSpace($part) -or $part -eq '.' -or $part -eq '..' -or $part.EndsWith('.') -or $part.EndsWith(' ')) { return $false }
        $stem = $part.Split('.')[0].ToUpperInvariant()
        if ($devices -contains $stem) { return $false }
    }
    return $true
}

function Assert-ENV1B3AbsoluteSafePath {
    param(
        [Parameter(Mandatory)][string]$LiteralPath,
        [switch]$AllowMissingLeaf
    )
    if (-not [IO.Path]::IsPathRooted($LiteralPath) -or $LiteralPath.StartsWith('\\') -or $LiteralPath.StartsWith('\\?\')) {
        Throw-ENV1B3Error 'ENV1B3_PATH_INVALID' 'path'
    }
    $full = [IO.Path]::GetFullPath($LiteralPath)
    $cursor = $full
    if ($AllowMissingLeaf -and -not (Test-Path -LiteralPath $cursor)) { $cursor = Split-Path -Parent $cursor }
    while (-not [string]::IsNullOrWhiteSpace($cursor) -and (Test-Path -LiteralPath $cursor)) {
        $item = Get-Item -LiteralPath $cursor -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Throw-ENV1B3Error 'ENV1B3_REPARSE_FORBIDDEN' 'path'
        }
        $parent = Split-Path -Parent $cursor
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
    return $full
}

function Read-ENV1B3BoundedBytes {
    param([Parameter(Mandatory)][string]$LiteralPath, [int64]$Maximum = $script:MaxJsonBytes)
    $stream = $null
    try {
        $stream = [IO.File]::Open($LiteralPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        if ($stream.Length -lt 1 -or $stream.Length -gt $Maximum) { Throw-ENV1B3Error 'ENV1B3_FILE_SIZE_INVALID' 'file' }
        $bytes = New-Object byte[] ([int]$stream.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $count = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($count -eq 0) { Throw-ENV1B3Error 'ENV1B3_FILE_READ_FAILED' 'file' }
            $offset += $count
        }
        return $bytes
    } catch [InvalidOperationException] { throw } catch { Throw-ENV1B3Error 'ENV1B3_FILE_READ_FAILED' 'file' } finally { if ($null -ne $stream) { $stream.Dispose() } }
}

function Read-ENV1B3Json {
    param([Parameter(Mandatory)][string]$LiteralPath, [int64]$Maximum = $script:MaxJsonBytes)
    $bytes = Read-ENV1B3BoundedBytes -LiteralPath $LiteralPath -Maximum $Maximum
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        Throw-ENV1B3Error 'ENV1B3_JSON_INVALID' 'bom'
    }
    try {
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        return ($utf8.GetString($bytes) | ConvertFrom-Json)
    } catch { Throw-ENV1B3Error 'ENV1B3_JSON_INVALID' 'json' }
}

function Read-ENV1B3Sums {
    param([Parameter(Mandatory)][string]$LiteralPath, [Parameter(Mandatory)][string]$Root)
    $records = @{}
    try { $text = [Text.UTF8Encoding]::new($false, $true).GetString((Read-ENV1B3BoundedBytes -LiteralPath $LiteralPath)) }
    catch [InvalidOperationException] { throw }
    catch { Throw-ENV1B3Error 'ENV1B3_SUMS_INVALID' 'encoding' }
    foreach ($line in $text.Split("`n")) {
        $line = $line.TrimEnd("`r")
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -notmatch '^([0-9a-fA-F]{64})  ([^\r\n]+)$') { Throw-ENV1B3Error 'ENV1B3_SUMS_INVALID' 'line' }
        $expectedHash = $Matches[1].ToLowerInvariant()
        $relative = $Matches[2]
        if (-not (Test-ENV1B3SafeRelativePath $relative)) { Throw-ENV1B3Error 'ENV1B3_SUMS_INVALID' 'path' }
        $key = $relative.ToLowerInvariant()
        if ($records.ContainsKey($key)) { Throw-ENV1B3Error 'ENV1B3_SUMS_INVALID' 'duplicate' }
        $target = Join-Path $Root ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { Throw-ENV1B3Error 'ENV1B3_SUMS_MISSING_FILE' 'file' }
        $actual = Get-ENV1B3Sha256 $target
        if ($actual -ne $expectedHash) { Throw-ENV1B3Error 'ENV1B3_SUMS_MISMATCH' 'file' }
        $records[$key] = $actual
    }
    return $records
}

function Get-ENV1B3InventoryTree {
    param([Parameter(Mandatory)]$Entries)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        # The strict inventory validator already requires ordinal path order.
        # Re-sorting with PowerShell's culture-sensitive comparer would change
        # the canonical byte stream for some real Unicode/case combinations.
        foreach ($entry in @($Entries)) {
            $line = "{0}`0{1}`0{2}`n" -f [string]$entry.path, [int64]$entry.size_bytes, [string]$entry.sha256
            $bytes = [Text.Encoding]::UTF8.GetBytes($line)
            [void]$sha.TransformBlock($bytes, 0, $bytes.Length, $bytes, 0)
        }
        [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
        return ([BitConverter]::ToString($sha.Hash)).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Get-ENV1B3DirectoryTree {
    param([Parameter(Mandatory)][string]$LiteralPath)
    $root = Assert-ENV1B3AbsoluteSafePath $LiteralPath
    $entries = @()
    foreach ($file in @(Get-ChildItem -LiteralPath $root -File -Recurse -Force | Sort-Object FullName)) {
        $relative = $file.FullName.Substring($root.Length).TrimStart('\').Replace('\','/')
        if (-not (Test-ENV1B3SafeRelativePath $relative)) { Throw-ENV1B3Error 'ENV1B3_TREE_PATH_INVALID' 'file' }
        $entries += [ordered]@{path=$relative;size_bytes=[int64]$file.Length;sha256=(Get-ENV1B3Sha256 $file.FullName)}
    }
    return [ordered]@{file_count=$entries.Count;tree_sha256=(Get-ENV1B3InventoryTree $entries)}
}

function Assert-ENV1B3Inventory {
    param([Parameter(Mandatory)]$Inventory)
    if ($Inventory.schema_version -ne 'ops-release-payload-inventory-v1') { Throw-ENV1B3Error 'ENV1B3_INVENTORY_INVALID' 'schema' }
    $entries = @($Inventory.entries)
    if ($entries.Count -ne [int]$Inventory.file_count) { Throw-ENV1B3Error 'ENV1B3_INVENTORY_INVALID' 'count' }
    $seen = @{}
    $total = [int64]0
    $previous = $null
    foreach ($entry in $entries) {
        $path = [string]$entry.path
        if (-not (Test-ENV1B3SafeRelativePath $path)) { Throw-ENV1B3Error 'ENV1B3_INVENTORY_INVALID' 'path' }
        $key = $path.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { Throw-ENV1B3Error 'ENV1B3_INVENTORY_INVALID' 'duplicate' }
        if ($null -ne $previous -and [string]::CompareOrdinal($previous, $path) -ge 0) { Throw-ENV1B3Error 'ENV1B3_INVENTORY_INVALID' 'order' }
        if ([string]$entry.sha256 -notmatch '^[0-9a-f]{64}$' -or [int64]$entry.size_bytes -lt 0) { Throw-ENV1B3Error 'ENV1B3_INVENTORY_INVALID' 'record' }
        $seen[$key] = $entry
        $total += [int64]$entry.size_bytes
        $previous = $path
    }
    if ($total -ne [int64]$Inventory.total_size_bytes -or (Get-ENV1B3InventoryTree $entries) -ne [string]$Inventory.tree_sha256) {
        Throw-ENV1B3Error 'ENV1B3_INVENTORY_INVALID' 'binding'
    }
    return $seen
}

function Test-ENV1B3ZipEntryUnsafe {
    param([Parameter(Mandatory)]$Entry)
    $name = [string]$Entry.FullName
    if ($name.EndsWith('/')) { return $false }
    if (-not (Test-ENV1B3SafeRelativePath $name)) { return $true }
    $mode = ([int64]$Entry.ExternalAttributes -shr 16) -band 0xF000
    return $mode -eq 0xA000
}

function Test-ENV1B3ReleaseArtifacts {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ManifestPath,
        [Parameter(Mandatory)][string]$ArchivePath,
        [Parameter(Mandatory)][string]$InventoryPath
    )
    foreach ($path in @($ManifestPath, $ArchivePath, $InventoryPath)) { [void](Assert-ENV1B3AbsoluteSafePath $path) }
    $manifest = Read-ENV1B3Json $ManifestPath
    $inventory = Read-ENV1B3Json $InventoryPath
    $inventoryMap = Assert-ENV1B3Inventory $inventory
    $manifestHash = Get-ENV1B3Sha256 $ManifestPath
    $inventoryHash = Get-ENV1B3Sha256 $InventoryPath
    $archiveHash = Get-ENV1B3Sha256 $ArchivePath
    if ($manifest.schema_version -ne 'ops-release-manifest-v2' -or $manifest.release_payload.inventory_sha256 -ne $inventoryHash -or $manifest.archive.inventory_sha256 -ne $inventoryHash) { Throw-ENV1B3Error 'ENV1B3_MANIFEST_BINDING_INVALID' 'inventory' }
    if ($manifest.archive.filename -ne [IO.Path]::GetFileName($ArchivePath) -or [int64]$manifest.archive.size_bytes -ne (Get-Item -LiteralPath $ArchivePath).Length -or $manifest.archive.sha256 -ne $archiveHash) { Throw-ENV1B3Error 'ENV1B3_MANIFEST_BINDING_INVALID' 'archive' }
    if ($manifest.release_payload.tree_sha256 -ne $inventory.tree_sha256 -or $manifest.release_payload.file_count -ne $inventory.file_count -or $manifest.release_payload.total_size_bytes -ne $inventory.total_size_bytes) { Throw-ENV1B3Error 'ENV1B3_MANIFEST_BINDING_INVALID' 'payload' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $seen = @{}
        $root = [string]$manifest.archive.root_prefix
        $prefix = $root + '/'
        foreach ($entry in $archive.Entries) {
            if ($entry.FullName.EndsWith('/')) { continue }
            if (Test-ENV1B3ZipEntryUnsafe $entry) { Throw-ENV1B3Error 'ENV1B3_ARCHIVE_PATH_INVALID' 'entry' }
            if (-not $entry.FullName.StartsWith($prefix, [StringComparison]::Ordinal)) { Throw-ENV1B3Error 'ENV1B3_ARCHIVE_INVENTORY_MISMATCH' 'root' }
            $relative = $entry.FullName.Substring($prefix.Length)
            $key = $relative.ToLowerInvariant()
            if ($seen.ContainsKey($key)) { Throw-ENV1B3Error 'ENV1B3_ARCHIVE_INVENTORY_MISMATCH' 'duplicate' }
            $seen[$key] = $true
            if ($relative -eq [string]$manifest.release_payload.inventory_path) {
                if ($entry.Length -ne (Get-Item -LiteralPath $InventoryPath).Length) { Throw-ENV1B3Error 'ENV1B3_ARCHIVE_INVENTORY_MISMATCH' 'embedded-inventory' }
                continue
            }
            if (-not $inventoryMap.ContainsKey($key)) { Throw-ENV1B3Error 'ENV1B3_ARCHIVE_INVENTORY_MISMATCH' 'extra' }
            $expected = $inventoryMap[$key]
            if ($entry.Length -ne [int64]$expected.size_bytes) { Throw-ENV1B3Error 'ENV1B3_ARCHIVE_INVENTORY_MISMATCH' 'size' }
            $stream = $entry.Open()
            try {
                $hasher = [Security.Cryptography.SHA256]::Create()
                try { $actual = ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() } finally { $hasher.Dispose() }
            } finally { $stream.Dispose() }
            if ($actual -ne [string]$expected.sha256) { Throw-ENV1B3Error 'ENV1B3_ARCHIVE_INVENTORY_MISMATCH' 'hash' }
        }
        if ($seen.Count -ne $inventoryMap.Count + 1) { Throw-ENV1B3Error 'ENV1B3_ARCHIVE_INVENTORY_MISMATCH' 'closure' }
    } finally { $archive.Dispose() }
    return [ordered]@{result='pass'; manifest_sha256=$manifestHash; inventory_sha256=$inventoryHash; archive_sha256=$archiveHash; release_id=[string]$manifest.identity.release_id; payload_tree_sha256=[string]$inventory.tree_sha256; file_count=[int]$inventory.file_count}
}

function Test-ENV1B3Handoff {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$HandoffRoot)
    $root = Assert-ENV1B3AbsoluteSafePath $HandoffRoot
    $handoff = Read-ENV1B3Json (Join-Path $root 'CANDIDATE-HANDOFF.json')
    if ($handoff.overall_task_id -ne $script:TaskId -or $handoff.production_approved -ne $false -or $handoff.validation_matrix_version -ne $script:MatrixVersion) { Throw-ENV1B3Error 'ENV1B3_HANDOFF_IDENTITY_INVALID' 'identity' }
    $sums = Read-ENV1B3Sums -LiteralPath (Join-Path $root 'SHA256SUMS') -Root $root
    $actualFiles = @{}
    foreach ($file in @(Get-ChildItem -LiteralPath $root -File -Recurse -Force)) {
        $relative = $file.FullName.Substring($root.Length).TrimStart('\').Replace('\','/')
        if ($relative -eq 'SHA256SUMS') { continue }
        $actualFiles[$relative.ToLowerInvariant()] = $true
    }
    if ($actualFiles.Count -ne $sums.Count -or @($actualFiles.Keys | Where-Object { -not $sums.ContainsKey($_) }).Count -ne 0) { Throw-ENV1B3Error 'ENV1B3_SUMS_CLOSURE_INVALID' 'files' }
    $taskbook = Join-Path $root 'ENV-1B3-INDEPENDENT-WINDOWS-TEST-HOST-CODEX-TASK.md'
    if ((Get-ENV1B3Sha256 $taskbook) -ne [string]$handoff.expected_test_host_taskbook_sha256) { Throw-ENV1B3Error 'ENV1B3_TASKBOOK_IDENTITY_MISMATCH' 'taskbook' }
    foreach ($binding in @(
        @('archive_filename','archive_sha256'),
        @('manifest_filename','manifest_sha256'),
        @('inventory_filename','inventory_sha256')
    )) {
        $name = [string]$handoff.($binding[0]); $hash = [string]$handoff.($binding[1])
        if (-not (Test-ENV1B3SafeRelativePath $name) -or (Get-ENV1B3Sha256 (Join-Path $root $name)) -ne $hash) { Throw-ENV1B3Error 'ENV1B3_HANDOFF_ARTIFACT_MISMATCH' $binding[0] }
    }
    $verifierNameProperty = $handoff.PSObject.Properties['materialized_verifier_filename']
    $verifierHashProperty = $handoff.PSObject.Properties['materialized_verifier_sha256']
    if (($null -eq $verifierNameProperty) -xor ($null -eq $verifierHashProperty)) {
        Throw-ENV1B3Error 'ENV1B3_HANDOFF_ARTIFACT_MISMATCH' 'materialized_verifier'
    }
    if ($null -ne $verifierNameProperty) {
        $verifierName = [string]$verifierNameProperty.Value
        $verifierHash = [string]$verifierHashProperty.Value
        $verifierPath = Join-Path $root ($verifierName.Replace('/',[IO.Path]::DirectorySeparatorChar))
        $actualVerifierHash = Get-ENV1B3Sha256 $verifierPath
        if ($verifierName -ne 'validation-kit/verify_materialized_release.py' -or
            $verifierHash -notmatch '^[0-9a-f]{64}$' -or
            $actualVerifierHash -ne $verifierHash) {
            Throw-ENV1B3Error 'ENV1B3_HANDOFF_ARTIFACT_MISMATCH' 'materialized_verifier'
        }
    }
    $artifact = Test-ENV1B3ReleaseArtifacts -ManifestPath (Join-Path $root $handoff.manifest_filename) -ArchivePath (Join-Path $root $handoff.archive_filename) -InventoryPath (Join-Path $root $handoff.inventory_filename)
    if ($artifact.release_id -ne $handoff.release_id -or $artifact.payload_tree_sha256 -ne $handoff.payload_tree_sha256) { Throw-ENV1B3Error 'ENV1B3_HANDOFF_ARTIFACT_MISMATCH' 'release' }
    return [ordered]@{result='pass'; candidate_id=[string]$handoff.candidate_id; candidate_sequence=[string]$handoff.candidate_sequence; release_id=[string]$handoff.release_id; artifact=$artifact; sums_count=$sums.Count}
}

function Write-ENV1B3CaseResult {
    param(
        [Parameter(Mandatory)][string]$EvidenceRoot,
        [Parameter(Mandatory)][string]$CaseId,
        [Parameter(Mandatory)][ValidateSet('PASS','FAIL','BLOCKED')][string]$Result,
        [Parameter(Mandatory)][string]$Code,
        [hashtable]$Evidence = @{}
    )
    [void](Assert-ENV1B3AbsoluteSafePath $EvidenceRoot -AllowMissingLeaf)
    [IO.Directory]::CreateDirectory($EvidenceRoot) | Out-Null
    $document = [ordered]@{schema_version='env-1b3-case-result-v1'; overall_task_id=$script:TaskId; matrix_version=$script:MatrixVersion; case_id=$CaseId; result=$Result; code=$Code; timestamp_utc=[DateTime]::UtcNow.ToString('o'); evidence=$Evidence}
    $json = $document | ConvertTo-Json -Depth 12 -Compress
    $path = Join-Path $EvidenceRoot ($CaseId + '.json')
    [IO.File]::WriteAllText($path, $json + "`n", [Text.UTF8Encoding]::new($false))
    return $document
}

function ConvertTo-ENV1B3UtcIso8601 {
    [CmdletBinding()]
    param([AllowNull()][object]$Value)

    if ($null -eq $Value -or ($Value -is [string] -and [String]::IsNullOrWhiteSpace($Value))) {
        return [ordered]@{value=$null; diagnostic='missing'}
    }

    if ($Value -is [DateTime]) {
        return [ordered]@{value=$Value.ToUniversalTime().ToString('o', [Globalization.CultureInfo]::InvariantCulture); diagnostic='datetime'}
    }

    if ($Value -isnot [string]) {
        return [ordered]@{value=$null; diagnostic='invalid_type'}
    }

    try {
        $converted = [Management.ManagementDateTimeConverter]::ToDateTime($Value)
        return [ordered]@{value=$converted.ToUniversalTime().ToString('o', [Globalization.CultureInfo]::InvariantCulture); diagnostic='dmtf'}
    } catch {
        return [ordered]@{value=$null; diagnostic='invalid_format'}
    }
}

function ConvertTo-ENV1B3WhereDiscoveryResult {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][int]$ExitCode,
        [AllowNull()][string]$Stdout,
        [AllowNull()][string]$Stderr
    )
    if ($ExitCode -notin @(0, 1)) {
        Throw-ENV1B3Error 'ENV1B3_WHERE_DIAGNOSTIC_FAILED' 'where'
    }
    $stdoutText = if ($null -eq $Stdout) { '' } else { [string]$Stdout }
    $stderrText = if ($null -eq $Stderr) { '' } else { [string]$Stderr }
    if ($stdoutText.Length -gt 8192) { $stdoutText = $stdoutText.Substring(0, 8192) }
    if ($stderrText.Length -gt 8192) { $stderrText = $stderrText.Substring(0, 8192) }
    return [ordered]@{
        exit_code=$ExitCode
        found=($ExitCode -eq 0)
        diagnostic_failed=$false
        stdout=$stdoutText
        stderr=$stderrText
    }
}

function Invoke-ENV1B3WhereLookup {
    [CmdletBinding()]
    param([Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9._-]{1,64}$')][string]$Name)

    $wherePath = Join-Path ([Environment]::GetFolderPath('System')) 'where.exe'
    if (-not (Test-Path -LiteralPath $wherePath -PathType Leaf)) {
        Throw-ENV1B3Error 'ENV1B3_WHERE_DIAGNOSTIC_FAILED' 'where'
    }
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $wherePath
    $startInfo.Arguments = $Name
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { Throw-ENV1B3Error 'ENV1B3_WHERE_DIAGNOSTIC_FAILED' 'where' }
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        return ConvertTo-ENV1B3WhereDiscoveryResult -ExitCode $process.ExitCode -Stdout $stdout -Stderr $stderr
    } catch [InvalidOperationException] {
        throw
    } catch {
        Throw-ENV1B3Error 'ENV1B3_WHERE_DIAGNOSTIC_FAILED' 'where'
    } finally {
        $process.Dispose()
    }
}

function Get-ENV1B3DisplayNames {
    [CmdletBinding()]
    param([AllowNull()][object[]]$Items)
    $names = @()
    foreach ($item in @($Items)) {
        if ($null -eq $item) { continue }
        $property = $item.PSObject.Properties['DisplayName']
        if ($null -eq $property -or $null -eq $property.Value) { continue }
        try { $text = [Convert]::ToString($property.Value, [Globalization.CultureInfo]::InvariantCulture) }
        catch { continue }
        if (-not [String]::IsNullOrWhiteSpace($text)) { $names += $text }
    }
    return $names
}

function Test-ENV1B3WindowsAppsAliasPath {
    param([AllowNull()][string]$Value)
    if ([String]::IsNullOrWhiteSpace($Value)) { return $false }
    return $Value.Replace('/', '\') -match '(?i)\\Microsoft\\WindowsApps\\(?:python|python3|py)(?:\.exe)?$'
}

function Test-ENV1B3CleanRuntimeBaseline {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateSet('fresh_vm_snapshot','fresh_physical_image','dedicated_clean_test_host')][string]$Classification,
        [Parameter(Mandatory)][bool]$ApplicationUserIsAdmin,
        [Parameter(Mandatory)][bool]$InstallTimePresent,
        [Parameter(Mandatory)][object[]]$PythonCommands,
        [Parameter(Mandatory)][bool]$PythonRegistryPresent,
        [Parameter(Mandatory)][bool]$MicrosoftStorePythonPresent,
        [Parameter(Mandatory)][bool]$ProjectStatePreexisting,
        [Parameter(Mandatory)][bool]$BypassNroRecorded
    )
    $usable = @($PythonCommands | Where-Object {
        if ($_ -is [Collections.IDictionary]) { return $_.Contains('usable') -and $_['usable'] -eq $true }
        $property = $_.PSObject.Properties['usable']
        return $null -ne $property -and $property.Value -eq $true
    }).Count -gt 0
    $aliasStubs = @($PythonCommands | Where-Object {
        if ($_ -is [Collections.IDictionary]) { return $_.Contains('alias_stub') -and $_['alias_stub'] -eq $true }
        $property = $_.PSObject.Properties['alias_stub']
        return $null -ne $property -and $property.Value -eq $true
    }).Count -gt 0
    $noSystemPython = (-not $usable) -and (-not $PythonRegistryPresent) -and (-not $MicrosoftStorePythonPresent)
    $clean = $InstallTimePresent -and (-not $ApplicationUserIsAdmin) -and $noSystemPython -and (-not $ProjectStatePreexisting)
    return [ordered]@{
        result=$(if ($clean) { 'PASS' } else { 'FAIL' })
        clean_host_classification=$Classification
        usable_external_python_present=$usable
        python_alias_stubs_present=$aliasStubs
        no_system_python_runtime=$noSystemPython
        recorded_oobe_deviation=$BypassNroRecorded
        pristine_oobe_baseline=(-not $BypassNroRecorded)
        clean_windows_runtime_baseline=$clean
    }
}

Export-ModuleMember -Function Get-ENV1B3Sha256,Test-ENV1B3SafeRelativePath,Assert-ENV1B3AbsoluteSafePath,Read-ENV1B3Json,Read-ENV1B3Sums,Get-ENV1B3InventoryTree,Get-ENV1B3DirectoryTree,Assert-ENV1B3Inventory,Test-ENV1B3ZipEntryUnsafe,Test-ENV1B3ReleaseArtifacts,Test-ENV1B3Handoff,Write-ENV1B3CaseResult,ConvertTo-ENV1B3UtcIso8601,ConvertTo-ENV1B3WhereDiscoveryResult,Invoke-ENV1B3WhereLookup,Get-ENV1B3DisplayNames,Test-ENV1B3WindowsAppsAliasPath,Test-ENV1B3CleanRuntimeBaseline
