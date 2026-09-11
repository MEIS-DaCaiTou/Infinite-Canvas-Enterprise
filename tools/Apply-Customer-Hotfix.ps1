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
        throw "缺少离线热修文件：$required"
    }
}

foreach ($line in Get-Content -LiteralPath $checksums) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $parts = $line -split '\s+', 2
    if ($parts.Count -ne 2) { throw 'SHA256SUMS.txt 格式无效' }
    $file = Join-Path $packageRoot $parts[1]
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "校验目标不存在：$($parts[1])" }
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $parts[0].ToLowerInvariant()) { throw "SHA-256 不匹配：$($parts[1])" }
}

$resolvedInstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
$pointerPath = Join-Path $resolvedInstallRoot 'state\current-release.json'
$pointer = Get-Content -LiteralPath $pointerPath -Raw | ConvertFrom-Json
if ($pointer.release_id -ne $expectedSourceRelease) {
    throw "当前活动版本不是客户准确基线 $expectedSourceRelease，已停止。"
}

if (-not $ConfirmNoActiveTasks) {
    $answer = Read-Host '请先停止新任务并确认没有执行中的任务；输入 YES 继续'
    if ($answer -cne 'YES') { throw '未确认任务排空，已停止。' }
}

$python = Join-Path $resolvedInstallRoot "releases\$expectedSourceRelease\python\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw '客户基线 bundled Python 不存在' }

& $python -I -B $applyScript `
    --install-root $resolvedInstallRoot `
    --manifest $manifest `
    --archive $archive `
    --inventory $inventory `
    --confirm-no-active-tasks
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { throw "热修未激活或已自动回退，退出码：$exitCode" }
Write-Host '客户 Runtime 热修已激活并通过目标版本健康检查。' -ForegroundColor Green
