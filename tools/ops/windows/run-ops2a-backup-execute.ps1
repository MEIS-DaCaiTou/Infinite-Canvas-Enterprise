[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AppRoot,

    [Parameter(Mandatory = $true)]
    [string]$ToolsRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [Parameter(Mandatory = $true)]
    [string]$BackupRoot,

    [string]$Operator = "aidan-prod-backup-execute",

    [switch]$ConfirmProductionBackup
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

function Write-CDriveFreeSpace {
    try {
        $drive = Get-PSDrive -Name C -ErrorAction Stop
        $freeGb = [Math]::Round(($drive.Free / 1GB), 2)
        Write-Host "C drive free space: $freeGb GB"
    }
    catch {
        Write-Warning "Could not determine C drive free space: $($_.Exception.Message)"
    }
}

function Get-LatestBackupManifest {
    $manifest = Get-ChildItem -LiteralPath $script:BackupRoot -Filter "backup-manifest.json" -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime |
        Select-Object -Last 1
    return $manifest
}

function Write-BackupSummary {
    $manifest = Get-LatestBackupManifest
    if ($null -eq $manifest) {
        Write-Warning "Backup manifest not found under $script:BackupRoot"
        return
    }

    Write-Host "Backup manifest: $($manifest.FullName)"
    try {
        $data = Get-Content -LiteralPath $manifest.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Host "Backup directory: $($data.backup_dir)"
        Write-Host "sqlite_backup_status: $($data.sqlite_backup_status)"
        Write-Host "dry_run: $($data.dry_run)"
    }
    catch {
        Write-Warning "Could not read backup manifest summary: $($_.Exception.Message)"
    }
}

try {
    chcp 65001 | Out-Null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8

    if (-not $ConfirmProductionBackup) {
        Write-Error "ConfirmProductionBackup is required for production backup execution."
        exit 2
    }

    $script:AppRoot = Resolve-ExistingDirectory -PathValue $AppRoot -Label "AppRoot"
    $script:ToolsRoot = Resolve-ExistingDirectory -PathValue $ToolsRoot -Label "ToolsRoot"
    $script:OutputRoot = Ensure-Directory -PathValue $OutputRoot
    $script:BackupRoot = Ensure-Directory -PathValue $BackupRoot
    $script:PythonPath = Resolve-ExistingFile -PathValue (Join-Path $script:AppRoot "python\python.exe") -Label "Bundled Python"
    $script:RunnerPath = Resolve-ExistingFile -PathValue (Join-Path $script:ToolsRoot "enterprise\ops\runner.py") -Label "OPS runner"
    $script:LogFile = Join-Path $script:OutputRoot "jobs.jsonl"
    $script:Operator = $Operator

    Write-Host "OPS-2A production backup execution wrapper"
    Write-Host "This script performs the confirmed backup command only."
    Write-Host "This script does not run inventory or data check."
    Write-Host "This script does not validate a release package."
    Write-Host "This script does not prepare an upgrade plan."
    Write-Host "This script does not upgrade production."
    Write-Host "This script does not update the Git worktree."
    Write-Host "This script does not stop or start services."
    Write-Host "This script does not repair data."
    Write-Host "This script does not delete files."
    Write-Host "AppRoot: $script:AppRoot"
    Write-Host "ToolsRoot: $script:ToolsRoot"
    Write-Host "OutputRoot: $script:OutputRoot"
    Write-Host "BackupRoot: $script:BackupRoot"
    Write-Host "PythonPath: $script:PythonPath"
    Write-Host "RunnerPath: $script:RunnerPath"
    Write-Host "LogFile: $script:LogFile"
    Write-CDriveFreeSpace

    & $script:PythonPath $script:RunnerPath backup `
        --app-root $script:AppRoot `
        --output-dir $script:OutputRoot `
        --log-file $script:LogFile `
        --operator $script:Operator `
        --backup-root $script:BackupRoot `
        --execute
    $exitCode = $LASTEXITCODE

    Write-BackupSummary

    if ($exitCode -ne 0) {
        Write-Error "Backup command failed with code $exitCode"
        exit $exitCode
    }

    exit 0
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
