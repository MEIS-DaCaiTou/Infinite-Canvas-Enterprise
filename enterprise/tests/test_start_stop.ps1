param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"

function Get-EnterpriseListeners {
    Get-NetTCPConnection -LocalPort 8000,3001 -State Listen -ErrorAction SilentlyContinue
}

function Wait-Health {
    param([int]$Seconds = 60)

    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            $res = Invoke-RestMethod -Uri "http://127.0.0.1:8000/enterprise/health" -TimeoutSec 2
            if ($res.status -eq "ok" -and $res.gateway -eq "ok" -and $res.upstream -eq "ok") {
                return $true
            }
        } catch {
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

Set-Location $Root

if (Get-EnterpriseListeners) {
    throw "Ports 8000/3001 are already in use. This test refuses to stop an existing process."
}

$python = Join-Path $Root "python\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$outLog = Join-Path $env:TEMP "infinite_canvas_enterprise_launcher.out.log"
$errLog = Join-Path $env:TEMP "infinite_canvas_enterprise_launcher.err.log"
Remove-Item $outLog,$errLog -ErrorAction SilentlyContinue

Write-Host "Starting launcher..."
$launcher = Start-Process -FilePath $python `
    -ArgumentList @("-m", "enterprise.runtime.cli", "start", "--app-root", $Root) `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

try {
    if (-not (Wait-Health -Seconds 60)) {
        throw "Health did not become ok within 60 seconds."
    }
    Write-Host "[PASS] Health became ok."

    $ports = Get-EnterpriseListeners
    if (-not ($ports | Where-Object { $_.LocalPort -eq 8000 })) { throw "Port 8000 is not listening." }
    if (-not ($ports | Where-Object { $_.LocalPort -eq 3001 })) { throw "Port 3001 is not listening." }
    Write-Host "[PASS] Ports 8000 and 3001 are listening."
} finally {
    Write-Host "Requesting controlled runtime stop..."
    & $python -m enterprise.runtime.cli stop --app-root $Root
}

Start-Sleep -Seconds 5

if (Get-EnterpriseListeners) {
    Get-EnterpriseListeners | Select-Object LocalAddress,LocalPort,OwningProcess | Format-Table -AutoSize
    Write-Host ""
    Write-Host "Launcher stdout:"
    if (Test-Path $outLog) { Get-Content $outLog }
    Write-Host ""
    Write-Host "Launcher stderr:"
    if (Test-Path $errLog) { Get-Content $errLog }
    throw "Ports 8000/3001 are still listening after launcher stop."
}

Write-Host "[PASS] Ports 8000 and 3001 were released after launcher stop."
Write-Host "Lifecycle test passed."
