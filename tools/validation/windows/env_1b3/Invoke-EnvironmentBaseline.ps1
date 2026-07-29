[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][ValidateSet('fresh_vm_snapshot','fresh_physical_image','dedicated_clean_test_host')][string]$Classification
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
try {
    [void](Assert-ENV1B3AbsoluteSafePath $TestRoot -AllowMissingLeaf)
    [void](Assert-ENV1B3AbsoluteSafePath $EvidenceRoot -AllowMissingLeaf)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $pythonCommands = @('python','python3','py') | ForEach-Object {
        $found = @(Get-Command $_ -All -ErrorAction SilentlyContinue)
        $where = @(& where.exe $_ 2>$null)
        [ordered]@{name=$_; discoverable=($found.Count -gt 0 -or $where.Count -gt 0); command_count=$found.Count; where_count=$where.Count}
    }
    $pythonRegistryKeys = @(
        'HKCU:\Software\Python\PythonCore',
        'HKLM:\Software\Python\PythonCore',
        'HKLM:\Software\WOW6432Node\Python\PythonCore'
    )
    $pythonRegistryPresent = @($pythonRegistryKeys | Where-Object { Test-Path -LiteralPath $_ }).Count -gt 0
    $pyLauncherInventory = @()
    if (@($pythonCommands | Where-Object { $_.name -eq 'py' -and $_.discoverable }).Count -gt 0) {
        $pyLauncherInventory = @(& py -0p 2>$null | Select-Object -First 32)
    }
    $os = Get-CimInstance Win32_OperatingSystem
    $installTime = ConvertTo-ENV1B3UtcIso8601 $os.InstallDate
    $apps = @(Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object DisplayName)
    $defender = Get-MpComputerStatus -ErrorAction SilentlyContinue
    $localStateRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'InfiniteCanvasEnterprise'
    $preexistingProjectState = (Test-Path -LiteralPath (Join-Path $TestRoot 'install')) -or (Test-Path -LiteralPath (Join-Path $TestRoot 'runs')) -or (Test-Path -LiteralPath $localStateRoot)
    $evidence = @{
        clean_host_classification=$Classification
        windows_edition=[string]$os.Caption
        windows_version=[string]$os.Version
        windows_build=[string]$os.BuildNumber
        architecture=$env:PROCESSOR_ARCHITECTURE
        install_time_utc=$installTime.value
        install_time_diagnostic=$installTime.diagnostic
        application_user_is_admin=$isAdmin
        elevation_used_for_application=$false
        installed_application_count=$apps.Count
        external_python_commands=$pythonCommands
        python_registry_present=$pythonRegistryPresent
        py_launcher_inventory_count=$pyLauncherInventory.Count
        project_state_preexisting=$preexistingProjectState
        test_root_container_preexisting=(Test-Path -LiteralPath $TestRoot)
        defender_antivirus_enabled=($(if($null -eq $defender){$null}else{[bool]$defender.AntivirusEnabled}))
        defender_realtime_enabled=($(if($null -eq $defender){$null}else{[bool]$defender.RealTimeProtectionEnabled}))
    }
    $valid = ($null -ne $installTime.value) -and (-not $isAdmin) -and -not ($pythonCommands | Where-Object discoverable) -and -not $pythonRegistryPresent -and -not $preexistingProjectState
    $result = Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W01' -Result ($(if($valid){'PASS'}else{'FAIL'})) -Code ($(if($valid){'ENV1B3_BASELINE_PASS'}else{'ENV1B3_BASELINE_INVALID'})) -Evidence $evidence
    $result | ConvertTo-Json -Depth 8 -Compress
    if (-not $valid) { exit 2 }
} catch {
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W01' -Result 'BLOCKED' -Code 'ENV1B3_BASELINE_COLLECTION_FAILED' -Evidence @{} | ConvertTo-Json -Compress
    exit 2
}
