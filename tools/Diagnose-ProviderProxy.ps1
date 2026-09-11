[CmdletBinding()]
param(
    [int[]]$ProxyPorts = @(15490, 10808),
    [uri]$ProviderBaseUri
)

$ErrorActionPreference = 'Stop'
$result = [ordered]@{
    captured_at = (Get-Date).ToString('o')
    winhttp = (& netsh winhttp show proxy | Out-String).Trim()
    current_user_proxy = $null
    listeners = @()
    local_runtime = [ordered]@{}
    provider_tcp = $null
}

$internet = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$result.current_user_proxy = [ordered]@{
    enabled = [bool]$internet.ProxyEnable
    server = [string]$internet.ProxyServer
}

foreach ($port in $ProxyPorts) {
    $connections = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
    foreach ($connection in $connections) {
        $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        $result.listeners += [ordered]@{
            address = $connection.LocalAddress
            port = $connection.LocalPort
            pid = $connection.OwningProcess
            process = if ($process) { $process.ProcessName } else { $null }
        }
    }
}

foreach ($probe in @(
    @{ name = 'gateway_live'; uri = 'http://127.0.0.1:8000/enterprise/live' },
    @{ name = 'gateway_health'; uri = 'http://127.0.0.1:8000/enterprise/health' },
    @{ name = 'upstream'; uri = 'http://127.0.0.1:3001/api/app-info' }
)) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $probe.uri -TimeoutSec 5
        $result.local_runtime[$probe.name] = [ordered]@{ ok = $true; status = [int]$response.StatusCode }
    } catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { $null }
        $result.local_runtime[$probe.name] = [ordered]@{ ok = $false; status = $status; error = $_.Exception.GetType().Name }
    }
}

if ($ProviderBaseUri) {
    $result.provider_tcp = Test-NetConnection -ComputerName $ProviderBaseUri.DnsSafeHost -Port 443 -InformationLevel Detailed |
        Select-Object ComputerName, RemoteAddress, RemotePort, TcpTestSucceeded
}

$result | ConvertTo-Json -Depth 6
