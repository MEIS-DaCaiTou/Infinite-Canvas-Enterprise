[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][ValidateSet('fresh_vm_snapshot','fresh_physical_image','dedicated_clean_test_host')][string]$Classification,
    [string]$FixturePath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force

if ([String]::IsNullOrWhiteSpace($FixturePath)) {
    try {
        & (Join-Path $PSScriptRoot 'Invoke-EnvironmentBaseline.ps1') -TestRoot $TestRoot -EvidenceRoot $EvidenceRoot -Classification $Classification
        if (-not $?) { exit 2 }
        exit 0
    } catch {
        [ordered]@{status='blocked';code='ENV1B3_W01_PROBE_EXECUTION_FAILED';exit_code=2} | ConvertTo-Json -Compress
        exit 2
    }
}

try {
    [void](Assert-ENV1B3AbsoluteSafePath $FixturePath)
    $fixture = Read-ENV1B3Json -LiteralPath $FixturePath -Maximum 16KB
    if ($fixture.schema_version -ne 'env-1b3-w01-probe-fixture-v1') { throw [InvalidOperationException]::new('ENV1B3_W01_PROBE_FIXTURE_INVALID') }
    $baselineClassification = Test-ENV1B3CleanRuntimeBaseline `
        -Classification $Classification `
        -ApplicationUserIsAdmin ([bool]$fixture.application_user_is_admin) `
        -InstallTimePresent ([bool]$fixture.install_time_present) `
        -PythonCommands @($fixture.python_commands) `
        -PythonRegistryPresent ([bool]$fixture.python_registry_present) `
        -MicrosoftStorePythonPresent ([bool]$fixture.microsoft_store_python_present) `
        -ProjectStatePreexisting ([bool]$fixture.project_state_preexisting) `
        -BypassNroRecorded ([bool]$fixture.bypass_nro_recorded)
    $evidence = @{
        diagnostic_fixture=$true
        usable_external_python_present=$baselineClassification.usable_external_python_present
        no_system_python_runtime=$baselineClassification.no_system_python_runtime
        recorded_oobe_deviation=$baselineClassification.recorded_oobe_deviation
        pristine_oobe_baseline=$baselineClassification.pristine_oobe_baseline
        clean_windows_runtime_baseline=$baselineClassification.clean_windows_runtime_baseline
    }
    $result = Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId 'W01' -Result $baselineClassification.result -Code ($(if($baselineClassification.result -eq 'PASS'){'ENV1B3_BASELINE_PASS'}else{'ENV1B3_BASELINE_INVALID'})) -Evidence $evidence
    $result | ConvertTo-Json -Depth 8 -Compress
    if ($baselineClassification.result -ne 'PASS') { exit 2 }
} catch {
    [ordered]@{status='blocked';code='ENV1B3_W01_PROBE_FIXTURE_INVALID';exit_code=2} | ConvertTo-Json -Compress
    exit 2
}
