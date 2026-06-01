param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Continue"

function Section($Name) {
    Write-Host ""
    Write-Host "== $Name =="
}

function Try-Web($Url) {
    try {
        $res = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
        [PSCustomObject]@{
            Url = $Url
            StatusCode = $res.StatusCode
            Content = if ($res.Content.Length -gt 300) { $res.Content.Substring(0, 300) } else { $res.Content }
        }
    } catch {
        [PSCustomObject]@{
            Url = $Url
            StatusCode = "ERROR"
            Content = $_.Exception.Message
        }
    }
}

function Try-CurlNoProxy($Url) {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curl) {
        [PSCustomObject]@{
            Url = $Url
            Mode = "curl --noproxy"
            StatusCode = "SKIP"
            Content = "curl.exe not found"
        }
        return
    }

    try {
        $raw = & curl.exe --noproxy "*" -s -m 5 -w "`nHTTP_STATUS:%{http_code}" $Url
        $text = ($raw -join "`n")
        $parts = $text -split "`nHTTP_STATUS:"
        [PSCustomObject]@{
            Url = $Url
            Mode = "curl --noproxy"
            StatusCode = if ($parts.Count -gt 1) { $parts[-1] } else { "UNKNOWN" }
            Content = if ($parts[0].Length -gt 300) { $parts[0].Substring(0, 300) } else { $parts[0] }
        }
    } catch {
        [PSCustomObject]@{
            Url = $Url
            Mode = "curl --noproxy"
            StatusCode = "ERROR"
            Content = $_.Exception.Message
        }
    }
}

Set-Location $Root

Section "Project"
$versionPath = Join-Path $Root "VERSION"
$version = if (Test-Path $versionPath) { (Get-Content $versionPath -Raw).Trim() } else { "missing" }
Write-Host "Root:    $Root"
Write-Host "Version: $version"
Write-Host "Python:  $(Join-Path $Root 'python\python.exe')"

Section "LAN IP"
$pickScript = Join-Path $Root "enterprise\pick_lan_ip.ps1"
if (Test-Path $pickScript) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $pickScript
} else {
    Write-Host "enterprise\pick_lan_ip.ps1 missing"
}

Section "IPv4 Addresses"
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" } |
    Select-Object IPAddress,AddressState,InterfaceIndex,InterfaceAlias |
    Format-Table -AutoSize

Section "Proxy"
$internetSettings = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
if (Test-Path $internetSettings) {
    Get-ItemProperty $internetSettings |
        Select-Object ProxyEnable,ProxyServer,ProxyOverride |
        Format-List
}

Section "Listening Ports"
$listeners = Get-NetTCPConnection -LocalPort 8000,3001 -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    $listeners | Select-Object LocalAddress,LocalPort,OwningProcess | Format-Table -AutoSize
    foreach ($processId in ($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        Get-Process -Id $processId -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,Path | Format-List
    }
} else {
    Write-Host "No listener on 8000 or 3001."
}

Section "Health"
$lanIp = if (Test-Path $pickScript) {
    (& powershell -NoProfile -ExecutionPolicy Bypass -File $pickScript | Select-Object -Last 1)
} else {
    "127.0.0.1"
}
Try-Web "http://127.0.0.1:8000/enterprise/health" | Format-List
if ($lanIp -and $lanIp -ne "127.0.0.1") {
    Try-Web "http://$lanIp`:8000/enterprise/health" | Format-List
    Try-CurlNoProxy "http://$lanIp`:8000/enterprise/health" | Format-List
}
Try-Web "http://127.0.0.1:3001/api/app-info" | Format-List
