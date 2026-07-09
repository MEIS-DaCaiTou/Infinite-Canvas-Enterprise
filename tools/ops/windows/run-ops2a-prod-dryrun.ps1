[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AppRoot,

    [Parameter(Mandatory = $true)]
    [string]$ToolsRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [string]$Operator = "aidan-prod-dry-run"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ExistingDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathValue,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $PathValue -PathType Container)) {
        throw "$Label does not exist or is not a directory: $PathValue"
    }
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Resolve-ExistingFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathValue,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $PathValue -PathType Leaf)) {
        throw "$Label does not exist or is not a file: $PathValue"
    }
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Ensure-Directory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathValue
    )

    if (-not (Test-Path -LiteralPath $PathValue -PathType Container)) {
        New-Item -ItemType Directory -Path $PathValue -Force | Out-Null
    }
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Invoke-OpsRunner {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName,

        [string[]]$ExtraArgs = @()
    )

    Write-Host ""
    Write-Host "Running OPS command: $CommandName"
    & $script:PythonPath $script:RunnerPath $CommandName `
        --app-root $script:AppRoot `
        --output-dir $script:OutputRoot `
        --log-file $script:LogFile `
        --operator $script:Operator `
        @ExtraArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "OPS command failed: $CommandName exited with code $exitCode"
    }
}

function Write-LatestReport {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Pattern,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $report = Get-ChildItem -LiteralPath $script:OutputRoot -Filter $Pattern -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime |
        Select-Object -Last 1
    if ($null -eq $report) {
        Write-Warning "$Label report not found with pattern $Pattern"
        return
    }
    Write-Host "$Label report: $($report.FullName)"
}

try {
    chcp 65001 | Out-Null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8

    $script:AppRoot = Resolve-ExistingDirectory -PathValue $AppRoot -Label "AppRoot"
    $script:ToolsRoot = Resolve-ExistingDirectory -PathValue $ToolsRoot -Label "ToolsRoot"
    $script:OutputRoot = Ensure-Directory -PathValue $OutputRoot
    $script:PythonPath = Resolve-ExistingFile -PathValue (Join-Path $script:AppRoot "python\python.exe") -Label "Bundled Python"
    $script:RunnerPath = Resolve-ExistingFile -PathValue (Join-Path $script:ToolsRoot "enterprise\ops\runner.py") -Label "OPS runner"
    $script:LogFile = Join-Path $script:OutputRoot "jobs.jsonl"
    $script:Operator = $Operator

    Write-Host "OPS-2A production dry-run wrapper"
    Write-Host "This script does not upgrade production."
    Write-Host "This script does not update the Git worktree."
    Write-Host "This script does not stop services."
    Write-Host "This script does not delete data."
    Write-Host "This script runs backup in dry-run mode only."
    Write-Host "AppRoot: $script:AppRoot"
    Write-Host "ToolsRoot: $script:ToolsRoot"
    Write-Host "OutputRoot: $script:OutputRoot"
    Write-Host "PythonPath: $script:PythonPath"
    Write-Host "RunnerPath: $script:RunnerPath"
    Write-Host "LogFile: $script:LogFile"

    Invoke-OpsRunner -CommandName "inventory"
    Invoke-OpsRunner -CommandName "check-data"
    Invoke-OpsRunner -CommandName "backup"

    Write-Host ""
    Write-Host "Generated reports:"
    Write-LatestReport -Pattern "inventory-*.json" -Label "inventory"
    Write-LatestReport -Pattern "data-check-*.json" -Label "data-check"
    Write-LatestReport -Pattern "backup-manifest-*.json" -Label "backup manifest"
    Write-Host "OPS job log: $script:LogFile"
    exit 0
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
