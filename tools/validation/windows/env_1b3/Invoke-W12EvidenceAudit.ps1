[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProbeManifestPath,
    [Parameter(Mandatory)][string]$ProbeV2EvidenceZip,
    [string]$W12EvidenceRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

$task = 'ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE'
$matrix = 'env-1b3-windows-validation-matrix-v1'
$candidateIdentityPath = 'CANDIDATE-05-IDENTITY.json'
$aggregatePath = 'cases/W12/W12.json'
$subcheckPaths = [ordered]@{
    archive_preflight_low_space = 'cases/W12/subchecks/W12/archive_preflight_low_space.json'
    materialization_low_space = 'cases/W12/subchecks/W12/materialization_low_space.json'
    writable_root_low_space = 'cases/W12/subchecks/W12/writable_root_low_space.json'
    pointer_atomicity = 'cases/W12/subchecks/W12/pointer_atomicity.json'
}
$recoveryPath = 'cases/W12/w12-recovery-materialization/W02.json'

function Get-BytesSha256 {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hasher.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
}

function Read-ZipEntryBytes {
    param([Parameter(Mandatory)]$Entry)
    if ([int64]$Entry.Length -lt 0 -or [int64]$Entry.Length -gt 16MB) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|entry-size')
    }
    $bytes = New-Object byte[] ([int]$Entry.Length)
    $stream = $Entry.Open()
    try {
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $read = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($read -eq 0) { throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|entry-read') }
            $offset += $read
        }
        if ($stream.ReadByte() -ne -1) { throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|entry-length') }
        return ,$bytes
    } finally { $stream.Dispose() }
}

function ConvertFrom-StrictJsonBytes {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|bom')
    }
    try { return ([Text.UTF8Encoding]::new($false, $true).GetString($Bytes) | ConvertFrom-Json) }
    catch { throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|json') }
}

function Get-CanonicalEvidenceSetSha256 {
    param([Parameter(Mandatory)][Collections.IDictionary]$Hashes)
    $lines = @()
    foreach ($key in @($Hashes.Keys | Sort-Object)) { $lines += ([string]$key + '=' + [string]$Hashes[$key]) }
    return Get-BytesSha256 ([Text.UTF8Encoding]::new($false).GetBytes(($lines -join "`n") + "`n"))
}

function Assert-W12Record {
    param($Record, [Parameter(Mandatory)][string]$CaseId, [string]$SubcheckId)
    if ($Record.schema_version -ne $(if ($SubcheckId) { 'env-1b3-subcheck-result-v1' } else { 'env-1b3-case-result-v1' }) -or
        $Record.overall_task_id -ne $task -or $Record.matrix_version -ne $matrix -or
        $Record.case_id -ne $CaseId -or $Record.result -ne 'PASS' -or
        [String]::IsNullOrWhiteSpace([string]$Record.code)) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_BINDING_INVALID|record')
    }
    if ($SubcheckId -and $Record.subcheck_id -ne $SubcheckId) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_BINDING_INVALID|subcheck')
    }
}

try {
    $manifest = Read-ENV1B3Json $ProbeManifestPath
    [void](Assert-ENV1B3AbsoluteSafePath $ProbeV2EvidenceZip)
    $probeSha = Get-ENV1B3Sha256 $ProbeV2EvidenceZip
    if ($probeSha -ne [string]$manifest.expected_probe_v2_evidence_sha256) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_BINDING_INVALID|outer-zip')
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($ProbeV2EvidenceZip)
    $entries = @{}
    $entryNames = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $totalBytes = [int64]0
    try {
        foreach ($entry in $archive.Entries) {
            $normalized = ([string]$entry.FullName).Replace('\', '/')
            $isDirectory = $normalized.EndsWith('/')
            $safeName = if ($isDirectory) { $normalized.TrimEnd('/') } else { $normalized }
            if ([String]::IsNullOrWhiteSpace($safeName) -or -not (Test-ENV1B3SafeRelativePath $safeName)) {
                throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|path')
            }
            $mode = ([int64]$entry.ExternalAttributes -shr 16) -band 0xF000
            if ($mode -eq 0xA000) { throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|symlink') }
            $identityName = if ($isDirectory) { $safeName + '/' } else { $safeName }
            if (-not $entryNames.Add($identityName)) {
                throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|casefold-collision')
            }
            if ($isDirectory) { continue }
            $totalBytes += [int64]$entry.Length
            if ($totalBytes -gt 64MB) { throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|total-size') }
            $bytes = Read-ZipEntryBytes $entry
            $entries[$safeName.ToLowerInvariant()] = [ordered]@{name=$safeName;bytes=$bytes;sha256=(Get-BytesSha256 $bytes)}
        }
    } finally { $archive.Dispose() }

    if (-not $entries.ContainsKey('sha256sums')) { throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|sums-missing') }
    $sumBytes = [byte[]]$entries['sha256sums'].bytes
    try { $sumText = [Text.UTF8Encoding]::new($false, $true).GetString($sumBytes) }
    catch { throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|sums-encoding') }
    $sums = @{}
    foreach ($line in $sumText.Split("`n")) {
        $line = $line.TrimEnd("`r")
        if ([String]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -notmatch '^([0-9a-fA-F]{64}) (?: |\*)([^\r\n]+)$') {
            throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|sums-line')
        }
        $relative = $Matches[2].Replace('\', '/')
        if (-not (Test-ENV1B3SafeRelativePath $relative)) {
            throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|sums-path')
        }
        $key = $relative.ToLowerInvariant()
        if ($sums.ContainsKey($key)) { throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|sums-duplicate') }
        $sums[$key] = $Matches[1].ToLowerInvariant()
    }
    if ($sums.Count -ne 57 -or $entries.Count -ne 58) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|closure-count')
    }
    foreach ($key in @($entries.Keys | Where-Object { $_ -ne 'sha256sums' })) {
        if (-not $sums.ContainsKey($key) -or [string]$sums[$key] -ne [string]$entries[$key].sha256) {
            throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|sums-mismatch')
        }
    }
    if (@($sums.Keys | Where-Object { -not $entries.ContainsKey($_) }).Count -ne 0) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_ZIP_INVALID|unbound-entry')
    }

    $requiredPaths = @($candidateIdentityPath, $aggregatePath, $recoveryPath) + @($subcheckPaths.Values)
    foreach ($path in $requiredPaths) {
        if (-not $entries.ContainsKey($path.ToLowerInvariant())) {
            throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_BINDING_INVALID|missing')
        }
    }
    $identity = ConvertFrom-StrictJsonBytes ([byte[]]$entries[$candidateIdentityPath.ToLowerInvariant()].bytes)
    if ($identity.schema_version -ne 'env-1b3-probe-v2-candidate-binding-v1' -or
        $identity.candidate_id -ne [string]$manifest.expected_candidate_id -or
        ([string]$identity.zip_sha256).ToLowerInvariant() -ne [string]$manifest.expected_candidate_handoff_sha256 -or
        $identity.modified -ne $false) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_BINDING_INVALID|candidate')
    }

    $aggregate = ConvertFrom-StrictJsonBytes ([byte[]]$entries[$aggregatePath.ToLowerInvariant()].bytes)
    Assert-W12Record $aggregate -CaseId W12
    $listed = @($aggregate.evidence.subchecks)
    $expectedIds = @($subcheckPaths.Keys)
    $listedIds = @($listed | ForEach-Object { [string]$_.subcheck_id })
    if ($listed.Count -ne $expectedIds.Count -or
        @($listed | Where-Object { $_.result -ne 'PASS' -or $_.subcheck_id -notin $expectedIds }).Count -ne 0 -or
        @($listedIds | Group-Object { $_.ToLowerInvariant() } | Where-Object { $_.Count -ne 1 }).Count -ne 0 -or
        @($expectedIds | Where-Object { $_ -notin $listedIds }).Count -ne 0) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_BINDING_INVALID|aggregate')
    }
    if ($entries[$aggregatePath.ToLowerInvariant()].sha256 -ne [string]$manifest.expected_w12_evidence_sha256) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_BINDING_INVALID|aggregate-sha')
    }

    $subcheckHashes = [ordered]@{}
    $subchecks = @{}
    foreach ($id in $expectedIds) {
        $path = [string]$subcheckPaths[$id]
        $record = ConvertFrom-StrictJsonBytes ([byte[]]$entries[$path.ToLowerInvariant()].bytes)
        Assert-W12Record $record -CaseId W12 -SubcheckId $id
        $subchecks[$id] = $record
        $subcheckHashes[$id] = [string]$entries[$path.ToLowerInvariant()].sha256
    }
    $recovery = ConvertFrom-StrictJsonBytes ([byte[]]$entries[$recoveryPath.ToLowerInvariant()].bytes)
    Assert-W12Record $recovery -CaseId W02
    if ($recovery.evidence.candidate_id -ne [string]$manifest.expected_candidate_id) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_BINDING_INVALID|recovery-candidate')
    }
    if ($subchecks['materialization_low_space'].evidence.no_final_app_root -ne $true -or
        $subchecks['materialization_low_space'].evidence.pointer_unchanged -ne $true -or
        $subchecks['materialization_low_space'].evidence.pointer_temp_absent -ne $true -or
        $subchecks['pointer_atomicity'].evidence.pointer_unchanged -ne $true -or
        $subchecks['pointer_atomicity'].evidence.pointer_temp_absent -ne $true) {
        throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_BINDING_INVALID|atomicity')
    }

    if (-not [String]::IsNullOrWhiteSpace($W12EvidenceRoot)) {
        [void](Assert-ENV1B3AbsoluteSafePath $W12EvidenceRoot)
        foreach ($zipPath in @($aggregatePath, $recoveryPath) + @($subcheckPaths.Values)) {
            $relative = $zipPath.Substring('cases/W12/'.Length).Replace('/', [IO.Path]::DirectorySeparatorChar)
            $mirrorPath = Join-Path $W12EvidenceRoot $relative
            if ((Get-ENV1B3Sha256 $mirrorPath) -ne [string]$entries[$zipPath.ToLowerInvariant()].sha256) {
                throw [InvalidOperationException]::new('ENV1B3_W12_EVIDENCE_BINDING_INVALID|mirror')
            }
        }
    }

    $evidenceHashes = [ordered]@{}
    foreach ($path in @($aggregatePath) + @($subcheckPaths.Values) + @($recoveryPath)) {
        $evidenceHashes[$path] = [string]$entries[$path.ToLowerInvariant()].sha256
    }
    $document = [ordered]@{
        schema_version='env-1b3-w12-evidence-audit-v3'
        overall_task_id=$task
        matrix_version=$matrix
        case_id='W12'
        result='PASS'
        code='ENV1B3_W12_EVIDENCE_AUDIT_PASS'
        source_probe_v2_zip_sha256=$probeSha
        candidate_id=[string]$identity.candidate_id
        candidate_handoff_sha256=([string]$identity.zip_sha256).ToLowerInvariant()
        candidate_modified=[bool]$identity.modified
        w12_aggregate_sha256=[string]$entries[$aggregatePath.ToLowerInvariant()].sha256
        w12_subcheck_sha256s=$subcheckHashes
        recovery_evidence_sha256=[string]$entries[$recoveryPath.ToLowerInvariant()].sha256
        w12_evidence_set_sha256=(Get-CanonicalEvidenceSetSha256 $evidenceHashes)
        retry_after_cleanup_passed=$true
        internal_sha256s_verified=57
        exit_code=0
    }
    [void](Assert-ENV1B3AbsoluteSafePath $EvidenceRoot -AllowMissingLeaf)
    [IO.Directory]::CreateDirectory($EvidenceRoot) | Out-Null
    [IO.File]::WriteAllText((Join-Path $EvidenceRoot 'W12-EVIDENCE-AUDIT.json'), ($document | ConvertTo-Json -Depth 12 -Compress) + "`n", [Text.UTF8Encoding]::new($false))
    $document | ConvertTo-Json -Depth 12 -Compress
} catch {
    $code = 'ENV1B3_W12_EVIDENCE_AUDIT_FAILED'
    $diagnostic = 'unclassified'
    if ($_.Exception.Message -match '(ENV1B3_[A-Z0-9_]+)\|([a-z0-9-]+)') { $code = $Matches[1]; $diagnostic = $Matches[2] }
    [ordered]@{schema_version='env-1b3-w12-evidence-audit-v3';result='FAIL';code=$code;diagnostic=$diagnostic;exit_code=2} | ConvertTo-Json -Compress
    exit 2
}
