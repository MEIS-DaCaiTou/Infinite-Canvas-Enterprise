[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$W08PointerEvidenceRoot,
    [Parameter(Mandatory)][string]$W08ReleaseManifestEvidenceRoot,
    [Parameter(Mandatory)][string]$W08RuntimeManifestEvidenceRoot,
    [Parameter(Mandatory)][string]$W08PayloadEvidenceRoot,
    [Parameter(Mandatory)][string]$W08PythonDllEvidenceRoot,
    [Parameter(Mandatory)][string]$ContractPath,
    [Parameter(Mandatory)][string]$EvidenceRoot
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

$task = 'ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE'
$matrix = 'env-1b3-windows-validation-matrix-v1'
$inputs = [ordered]@{
    current_release = $W08PointerEvidenceRoot
    release_manifest = $W08ReleaseManifestEvidenceRoot
    runtime_manifest = $W08RuntimeManifestEvidenceRoot
    payload = $W08PayloadEvidenceRoot
    python314_dll = $W08PythonDllEvidenceRoot
}

function Get-CanonicalSetSha256 {
    param([Parameter(Mandatory)][Collections.IDictionary]$Hashes)
    $lines = @()
    foreach ($key in @($Hashes.Keys | Sort-Object)) { $lines += ([string]$key + '=' + [string]$Hashes[$key]) }
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($lines -join "`n") + "`n")
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hasher.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
}

function Copy-Exclusive {
    param([Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$Target)
    $input = [IO.File]::Open($Source, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $output = $null
    try {
        $output = [IO.File]::Open($Target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $input.CopyTo($output)
        $output.Flush($true)
    } finally {
        if ($null -ne $output) { $output.Dispose() }
        $input.Dispose()
    }
}

try {
    $contract = Read-ENV1B3MatrixContracts $ContractPath
    $w08 = $contract.cases['W08']
    $expected = @($w08.mandatory_subchecks | ForEach-Object { [string]$_ })
    if (@($inputs.Keys).Count -ne $expected.Count -or @($expected | Where-Object { -not $inputs.Contains($_) }).Count -ne 0) {
        throw [InvalidOperationException]::new('ENV1B3_W08_HOST_AGGREGATE_INVALID|targets')
    }

    $sourcePaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $validated = [ordered]@{}
    $hashes = [ordered]@{}
    foreach ($subcheckId in $expected) {
        $root = Assert-ENV1B3AbsoluteSafePath ([string]$inputs[$subcheckId])
        $source = Join-Path $root (Join-Path 'subchecks\W08' ($subcheckId + '.json'))
        [void](Assert-ENV1B3AbsoluteSafePath $source)
        if (-not $sourcePaths.Add([IO.Path]::GetFullPath($source))) {
            throw [InvalidOperationException]::new('ENV1B3_W08_HOST_AGGREGATE_INVALID|duplicate-source')
        }
        $jsonFiles = @(Get-ChildItem -LiteralPath $root -File -Filter '*.json' -Recurse -Force)
        if ($jsonFiles.Count -ne 1 -or [IO.Path]::GetFullPath($jsonFiles[0].FullName) -ne [IO.Path]::GetFullPath($source)) {
            throw [InvalidOperationException]::new('ENV1B3_W08_HOST_AGGREGATE_INVALID|unexpected-subcheck')
        }
        $record = Read-ENV1B3Json $source
        if ($record.schema_version -ne 'env-1b3-subcheck-result-v1' -or
            $record.overall_task_id -ne $task -or
            $record.matrix_version -ne $matrix -or
            $record.case_id -ne 'W08' -or
            $record.subcheck_id -ne $subcheckId -or
            $record.result -ne 'PASS' -or
            [String]::IsNullOrWhiteSpace([string]$record.code)) {
            throw [InvalidOperationException]::new('ENV1B3_W08_HOST_AGGREGATE_INVALID|record')
        }
        foreach ($field in @($w08.required_evidence_fields)) {
            $property = $record.evidence.PSObject.Properties[[string]$field]
            if ($null -eq $property -or $null -eq $property.Value -or
                ($property.Value -is [string] -and [String]::IsNullOrWhiteSpace([string]$property.Value))) {
                throw [InvalidOperationException]::new('ENV1B3_W08_HOST_AGGREGATE_INVALID|evidence')
            }
        }
        if ($record.evidence.execution_context_isolated_case_copies -ne $true -or
            $record.evidence.fixture_materialized_release -ne $true) {
            throw [InvalidOperationException]::new('ENV1B3_W08_HOST_AGGREGATE_INVALID|context')
        }
        $validated[$subcheckId] = $source
        $hashes[$subcheckId] = Get-ENV1B3Sha256 $source
    }

    [void](Assert-ENV1B3AbsoluteSafePath $EvidenceRoot -AllowMissingLeaf)
    $destination = Join-Path $EvidenceRoot 'subchecks\W08'
    [IO.Directory]::CreateDirectory($destination) | Out-Null
    foreach ($subcheckId in $expected) {
        Copy-Exclusive -Source ([string]$validated[$subcheckId]) -Target (Join-Path $destination ($subcheckId + '.json'))
        if ((Get-ENV1B3Sha256 (Join-Path $destination ($subcheckId + '.json'))) -ne [string]$hashes[$subcheckId]) {
            throw [InvalidOperationException]::new('ENV1B3_W08_HOST_AGGREGATE_INVALID|copy')
        }
    }
    $setSha = Get-CanonicalSetSha256 $hashes
    $aggregate = Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W08 -ContractPath $ContractPath -AdditionalEvidence @{
        aggregation_source='host_only_evidence_aggregator'
        source_evidence_sha256s=$hashes
        w08_evidence_set_sha256=$setSha
    }
    $aggregate | ConvertTo-Json -Depth 14 -Compress
    if ($aggregate.result -ne 'PASS') { exit 2 }
} catch {
    $code = 'ENV1B3_W08_HOST_AGGREGATE_FAILED'
    if ($_.Exception.Message -match '(ENV1B3_[A-Z0-9_]+)\|') { $code = $Matches[1] }
    [ordered]@{schema_version='env-1b3-case-result-v1';case_id='W08';result='FAIL';code=$code;exit_code=2} | ConvertTo-Json -Compress
    exit 2
}
