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
        $where = Invoke-ENV1B3WhereLookup $_
        $paths = @()
        foreach ($command in $found) {
            foreach ($propertyName in @('Path','Source','Definition')) {
                $property = $command.PSObject.Properties[$propertyName]
                if ($null -ne $property -and $property.Value -is [string] -and -not [String]::IsNullOrWhiteSpace($property.Value)) {
                    $paths += [string]$property.Value
                    break
                }
            }
        }
        if ($where.found) { $paths += @($where.stdout -split '[\r\n]+' | Where-Object { -not [String]::IsNullOrWhiteSpace($_) }) }
        $paths = @($paths | Select-Object -Unique)
        $aliasCount = @($paths | Where-Object { Test-ENV1B3WindowsAppsAliasPath $_ }).Count
        $usableCount = @($paths | Where-Object { -not (Test-ENV1B3WindowsAppsAliasPath $_) }).Count
        [ordered]@{name=$_;found=($paths.Count -gt 0);alias_stub=($aliasCount -gt 0 -and $usableCount -eq 0);usable=($usableCount -gt 0);command_count=$found.Count;where_count=($(if($where.found){@($where.stdout -split '[\r\n]+' | Where-Object { -not [String]::IsNullOrWhiteSpace($_) }).Count}else{0}))}
    }
    $pythonRegistryKeys = @(
        'HKCU:\Software\Python\PythonCore',
        'HKLM:\Software\Python\PythonCore',
        'HKLM:\Software\WOW6432Node\Python\PythonCore'
    )
    $pythonRegistryPresent = @($pythonRegistryKeys | Where-Object { Test-Path -LiteralPath $_ }).Count -gt 0
    $microsoftStorePythonPresent = @(Get-AppxPackage -ErrorAction SilentlyContinue | Where-Object {
        $property = $_.PSObject.Properties['Name']
        $null -ne $property -and [string]$property.Value -match '(?i)python'
    }).Count -gt 0
    $pyLauncherInventory = @()
    if (@($pythonCommands | Where-Object { $_.name -eq 'py' -and $_.usable }).Count -gt 0) {
        $pyLauncherInventory = @(& py -0p 2>$null | Select-Object -First 32)
    }
    $os = Get-CimInstance Win32_OperatingSystem
    $installTime = ConvertTo-ENV1B3UtcIso8601 $os.InstallDate
    $uninstallItems = @(Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue)
    $apps = @(Get-ENV1B3DisplayNames $uninstallItems)
    $defender = Get-MpComputerStatus -ErrorAction SilentlyContinue
    $localStateRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'InfiniteCanvasEnterprise'
    $preexistingProjectState = (Test-Path -LiteralPath (Join-Path $TestRoot 'install')) -or (Test-Path -LiteralPath (Join-Path $TestRoot 'runs')) -or (Test-Path -LiteralPath $localStateRoot)
    $bypassNroRecorded = $false
    $oobe = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\OOBE' -Name 'BypassNRO' -ErrorAction SilentlyContinue
    if ($null -ne $oobe) {
        $property = $oobe.PSObject.Properties['BypassNRO']
        if ($null -ne $property) { $bypassNroRecorded = ([Convert]::ToInt32($property.Value) -eq 1) }
    }
    $baselineClassification = Test-ENV1B3CleanRuntimeBaseline -Classification $Classification -ApplicationUserIsAdmin $isAdmin -InstallTimePresent ($null -ne $installTime.value) -PythonCommands $pythonCommands -PythonRegistryPresent $pythonRegistryPresent -MicrosoftStorePythonPresent $microsoftStorePythonPresent -ProjectStatePreexisting $preexistingProjectState -BypassNroRecorded $bypassNroRecorded
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
        microsoft_store_python_present=$microsoftStorePythonPresent
        python_alias_stubs_present=$baselineClassification.python_alias_stubs_present
        usable_external_python_present=$baselineClassification.usable_external_python_present
        no_system_python_runtime=$baselineClassification.no_system_python_runtime
        py_launcher_inventory_count=$pyLauncherInventory.Count
        project_state_preexisting=$preexistingProjectState
        recorded_oobe_deviation=$baselineClassification.recorded_oobe_deviation
        pristine_oobe_baseline=$baselineClassification.pristine_oobe_baseline
        clean_windows_runtime_baseline=$baselineClassification.clean_windows_runtime_baseline
        test_root_container_preexisting=(Test-Path -LiteralPath $TestRoot)
        defender_antivirus_enabled=($(if($null -eq $defender){$null}else{[bool]$defender.AntivirusEnabled}))
        defender_realtime_enabled=($(if($null -eq $defender){$null}else{[bool]$defender.RealTimeProtectionEnabled}))
    }
    $valid = $baselineClassification.clean_windows_runtime_baseline
    $result = Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W01' -Result ($(if($valid){'PASS'}else{'FAIL'})) -Code ($(if($valid){'ENV1B3_BASELINE_PASS'}else{'ENV1B3_BASELINE_INVALID'})) -Evidence $evidence
    $result | ConvertTo-Json -Depth 8 -Compress
    if (-not $valid) { exit 2 }
} catch {
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W01' -Result 'BLOCKED' -Code 'ENV1B3_BASELINE_COLLECTION_FAILED' -Evidence @{} | ConvertTo-Json -Compress
    exit 2
}
