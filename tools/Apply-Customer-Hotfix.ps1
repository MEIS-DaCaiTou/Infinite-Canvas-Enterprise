[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,
    [switch]$ConfirmNoActiveTasks
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$packageRoot = $PSScriptRoot
$expectedSourceRelease = 'ice-2026.08.5-ee4281022d01'
$manifest = Join-Path $packageRoot 'ops-release-manifest-v2.json'
$archive = Join-Path $packageRoot 'release.zip'
$inventory = Join-Path $packageRoot 'release-payload-inventory.json'
$applyScript = Join-Path $packageRoot 'customer_hotfix_apply.py'
$checksums = Join-Path $packageRoot 'SHA256SUMS.txt'

foreach ($required in @($manifest, $archive, $inventory, $applyScript, $checksums)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required offline hotfix file is missing: $required"
    }
}

foreach ($line in Get-Content -LiteralPath $checksums) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $parts = $line -split '\s+', 2
    if ($parts.Count -ne 2) { throw 'SHA256SUMS.txt format is invalid' }
    $file = Join-Path $packageRoot $parts[1]
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Checksum target is missing: $($parts[1])" }
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $parts[0].ToLowerInvariant()) { throw "SHA-256 mismatch: $($parts[1])" }
}

$resolvedInstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
$pointerPath = Join-Path $resolvedInstallRoot 'state\current-release.json'
$pointer = Get-Content -LiteralPath $pointerPath -Raw | ConvertFrom-Json
if ($pointer.release_id -ne $expectedSourceRelease) {
    throw "The active Release is not the required customer baseline $expectedSourceRelease. No change was made."
}

if (-not $ConfirmNoActiveTasks) {
    $answer = Read-Host 'Stop new work and drain all active tasks. Type YES to continue'
    if ($answer -cne 'YES') { throw 'Task drain was not confirmed. No change was made.' }
}

$python = Join-Path $resolvedInstallRoot "releases\$expectedSourceRelease\python\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'The bundled Python for the required customer baseline is missing.' }

& $python -I -B $applyScript `
    --install-root $resolvedInstallRoot `
    --manifest $manifest `
    --archive $archive `
    --inventory $inventory `
    --confirm-no-active-tasks
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { throw "The hotfix was not activated or rolled back automatically. Exit code: $exitCode" }
Write-Host 'The customer Runtime hotfix is active and passed target health checks.' -ForegroundColor Green
