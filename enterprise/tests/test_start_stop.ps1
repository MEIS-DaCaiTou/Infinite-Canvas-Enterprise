param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$RuntimeRoot = "",
    [int]$UpstreamPort = 3001,
    [int]$GatewayPort = 8000,
    [switch]$FixtureChildWrapper,
    [switch]$CleanupRuntimeRoot
)

$ErrorActionPreference = "Stop"

function Get-EnterpriseListeners {
    Get-NetTCPConnection -LocalPort $UpstreamPort,$GatewayPort -State Listen -ErrorAction SilentlyContinue
}

function Wait-Health {
    param([int]$Seconds = 60)

    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            $res = Invoke-RestMethod -Uri "http://127.0.0.1:$GatewayPort/enterprise/health" -TimeoutSec 2
            if ($res.status -eq "ok" -and $res.gateway -eq "ok" -and $res.upstream -eq "ok") {
                return $true
            }
        } catch {
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Invoke-RuntimeCli {
    param(
        [string[]]$Arguments,
        [string]$Operation
    )

    $operationOut = Join-Path $env:TEMP ("infinite_canvas_enterprise_{0}_{1}.out.log" -f $Operation,[guid]::NewGuid().ToString("N"))
    $operationErr = Join-Path $env:TEMP ("infinite_canvas_enterprise_{0}_{1}.err.log" -f $Operation,[guid]::NewGuid().ToString("N"))
    try {
        $process = Start-Process -FilePath $python `
            -ArgumentList $Arguments `
            -WorkingDirectory $Root `
            -RedirectStandardOutput $operationOut `
            -RedirectStandardError $operationErr `
            -WindowStyle Hidden `
            -PassThru
        $process.WaitForExit(65000) | Out-Null
        if (-not $process.HasExited -or [int]$process.ExitCode -ne 0) {
            throw ("The {0} CLI did not complete successfully (exit={1}, exited={2})." -f $Operation,$process.ExitCode,$process.HasExited)
        }
    } finally {
        Remove-Item $operationOut,$operationErr -ErrorAction SilentlyContinue
    }
}

Set-Location $Root
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "InfiniteCanvasEnterprise\runtime"
}

if (Get-EnterpriseListeners) {
    throw "Requested test ports are already in use. This test refuses to stop an existing process."
}

$python = Join-Path $Root "python\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$startArgs = @("-m", "enterprise.runtime.cli", "start", "--app-root", $Root, "--runtime-root", $RuntimeRoot, "--upstream-port", $UpstreamPort, "--gateway-port", $GatewayPort)
$restartArgs = @("-m", "enterprise.runtime.cli", "restart", "--app-root", $Root, "--runtime-root", $RuntimeRoot, "--upstream-port", $UpstreamPort, "--gateway-port", $GatewayPort)
$stopArgs = @("-m", "enterprise.runtime.cli", "stop", "--app-root", $Root, "--runtime-root", $RuntimeRoot, "--upstream-port", $UpstreamPort, "--gateway-port", $GatewayPort)
if ($FixtureChildWrapper) {
    $startArgs += "--fixture-child-wrapper"
    $restartArgs += "--fixture-child-wrapper"
    $stopArgs += "--fixture-child-wrapper"
}

$serviceStarted = $false
$serviceStopped = $false

try {
    Write-Host "Starting service-host through the fixed CLI..."
    Invoke-RuntimeCli -Arguments $startArgs -Operation "start"
    if (-not (Wait-Health -Seconds 60)) {
        throw "Health did not become ok within 60 seconds."
    }
    $serviceStarted = $true
    Write-Host "[PASS] Start CLI exited and the detached service-host became healthy."

    $beforeUpstreamPid = @(Get-EnterpriseListeners | Where-Object { $_.LocalPort -eq $UpstreamPort } | Select-Object -First 1 -ExpandProperty OwningProcess)[0]
    $beforeGatewayPid = @(Get-EnterpriseListeners | Where-Object { $_.LocalPort -eq $GatewayPort } | Select-Object -First 1 -ExpandProperty OwningProcess)[0]
    if ($null -eq $beforeUpstreamPid -or $null -eq $beforeGatewayPid) { throw "Expected runtime listeners were not present before restart." }
    Invoke-RuntimeCli -Arguments $restartArgs -Operation "restart"
    if (-not (Wait-Health -Seconds 60)) { throw "Controlled restart did not complete." }
    $afterUpstreamPid = @(Get-EnterpriseListeners | Where-Object { $_.LocalPort -eq $UpstreamPort } | Select-Object -First 1 -ExpandProperty OwningProcess)[0]
    $afterGatewayPid = @(Get-EnterpriseListeners | Where-Object { $_.LocalPort -eq $GatewayPort } | Select-Object -First 1 -ExpandProperty OwningProcess)[0]
    if ($null -eq $afterUpstreamPid -or $null -eq $afterGatewayPid) { throw "Expected runtime listeners were not present after restart." }
    if ($beforeUpstreamPid -eq $afterUpstreamPid) { throw "Upstream PID did not change after restart." }
    if ($beforeGatewayPid -eq $afterGatewayPid) { throw "Gateway PID did not change after restart." }
    Write-Host "[PASS] Restart completion changed both role PID generations."

    Invoke-RuntimeCli -Arguments $stopArgs -Operation "stop"
    $serviceStopped = $true
    Start-Sleep -Milliseconds 500
    if (Get-EnterpriseListeners) {
        throw "Requested project ports are still listening after controlled stop."
    }
    Write-Host "[PASS] Controlled stop released both requested ports."
} finally {
    if ($serviceStarted -and -not $serviceStopped) {
        try {
            Invoke-RuntimeCli -Arguments $stopArgs -Operation "cleanup-stop"
            $serviceStopped = $true
        } catch {
            $serviceStopped = $false
        }
    }
    if ($CleanupRuntimeRoot -and $serviceStopped -and (Test-Path -LiteralPath $RuntimeRoot)) {
        Remove-Item -LiteralPath $RuntimeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Lifecycle test passed."
