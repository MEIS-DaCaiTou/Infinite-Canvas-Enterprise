param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$failures = New-Object System.Collections.Generic.List[string]

function Check($Name, [scriptblock]$Body) {
    try {
        & $Body
        Write-Host "[PASS] $Name"
    } catch {
        Write-Host "[FAIL] $Name - $($_.Exception.Message)"
        $failures.Add($Name)
    }
}

Check "enterprise health is ok" {
    $res = Invoke-RestMethod -Uri "$BaseUrl/enterprise/health" -TimeoutSec 5
    if ($res.status -ne "ok") { throw "status=$($res.status)" }
    if ($res.gateway -ne "ok") { throw "gateway=$($res.gateway)" }
    if ($res.upstream -ne "ok") { throw "upstream=$($res.upstream)" }
}

Check "login page loads" {
    $res = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/enterprise/login" -TimeoutSec 5
    if ($res.StatusCode -ne 200) { throw "status=$($res.StatusCode)" }
    if ($res.Content -notmatch "login|登录|用户名|password|密码") { throw "login form marker not found" }
}

Check "admin page requires authentication" {
    $res = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/enterprise/admin" -MaximumRedirection 0 -TimeoutSec 5 -ErrorAction SilentlyContinue
    if ($res.StatusCode -notin 302,303,307,308) { throw "expected redirect, got $($res.StatusCode)" }
}

Check "root requires authentication or redirects to enterprise login" {
    $res = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/" -MaximumRedirection 0 -TimeoutSec 5 -ErrorAction SilentlyContinue
    if ($res.StatusCode -notin 302,303,307,308) { throw "expected redirect, got $($res.StatusCode)" }
}

if ($failures.Count -gt 0) {
    Write-Host ""
    Write-Host "Smoke failed: $($failures -join ', ')"
    exit 1
}

Write-Host ""
Write-Host "Smoke passed."
