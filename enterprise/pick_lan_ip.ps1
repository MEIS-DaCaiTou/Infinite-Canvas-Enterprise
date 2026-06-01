$configs = Get-NetIPConfiguration |
    Where-Object {
        $_.IPv4DefaultGateway -and
        ($_.IPv4Address | Where-Object {
            $_.IPAddress -notlike '127.*' -and
            $_.IPAddress -notlike '169.254.*'
        })
    } |
    Sort-Object InterfaceMetric, InterfaceIndex

$primary = $configs | Select-Object -First 1
if ($primary -and $primary.IPv4Address) {
    ($primary.IPv4Address |
        Where-Object {
            $_.IPAddress -notlike '127.*' -and
            $_.IPAddress -notlike '169.254.*'
        } |
        Select-Object -First 1).IPAddress
    exit 0
}

$fallback = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -notlike '127.*' -and
        $_.IPAddress -notlike '169.254.*'
    } |
    Sort-Object @{ Expression = { if ($_.AddressState -eq 'Preferred') { 0 } else { 1 } } }, InterfaceMetric, InterfaceIndex |
    Select-Object -First 1

if ($fallback) { $fallback.IPAddress } else { '127.0.0.1' }
