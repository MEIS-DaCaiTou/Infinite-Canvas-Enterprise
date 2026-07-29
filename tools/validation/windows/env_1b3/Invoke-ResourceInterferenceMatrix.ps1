[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('PortConflict','ArchiveLock','LowDisk','DefenderStatus')][string]$Mode,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [string]$AppRoot,
    [string]$ArchivePath,
    [string]$IsolatedLowDiskRoot,
    [int]$Port=18000
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
try {
    switch($Mode){
        'PortConflict' {
            [void](Assert-ENV1B3AbsoluteSafePath $AppRoot)
            $listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$Port); $listener.Start()
            try { $output=@(& $env:ComSpec /d /c ('"'+(Join-Path $AppRoot '启动企业版.bat')+'"') 2>&1); $exitCode=$LASTEXITCODE; $stillOwned=$listener.Server.IsBound } finally { $listener.Stop() }
            $pass=$exitCode -eq 2 -and $stillOwned; $case='W10'; $evidence=@{start_exit=$exitCode;foreign_listener_survived=$stillOwned;port_label='controlled-test-port'}
        }
        'ArchiveLock' {
            [void](Assert-ENV1B3AbsoluteSafePath $ArchivePath)
            $handle=[IO.File]::Open($ArchivePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
            try { $blocked=$false; try{[void][IO.File]::Open($ArchivePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)}catch{$blocked=$true} }finally{$handle.Dispose()}
            $pass=$blocked; $case='W13'; $evidence=@{exclusive_archive_lock_detected=$blocked;lock_released=$true}
        }
        'LowDisk' {
            [void](Assert-ENV1B3AbsoluteSafePath $IsolatedLowDiskRoot)
            $root=[IO.Path]::GetPathRoot([IO.Path]::GetFullPath($IsolatedLowDiskRoot)); $system=[IO.Path]::GetPathRoot($env:SystemRoot)
            if($root -eq $system){throw [InvalidOperationException]::new('ENV1B3_SYSTEM_VOLUME_FORBIDDEN|volume')}
            $drive=[IO.DriveInfo]::new($root); $pass=$drive.AvailableFreeSpace -lt 128MB; $case='W12'; $evidence=@{isolated_non_system_volume=$true;free_space_below_gate=$pass}
        }
        'DefenderStatus' {
            $status=Get-MpComputerStatus -ErrorAction Stop; $pass=[bool]$status.AntivirusEnabled -and [bool]$status.RealTimeProtectionEnabled; $case='W13'; $evidence=@{antivirus_enabled=[bool]$status.AntivirusEnabled;realtime_enabled=[bool]$status.RealTimeProtectionEnabled;permanent_exclusion_added=$false}
        }
    }
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $case -Result ($(if($pass){'PASS'}else{'FAIL'})) -Code ($(if($pass){'ENV1B3_RESOURCE_INTERFERENCE_PASS'}else{'ENV1B3_RESOURCE_INTERFERENCE_FAILED'})) -Evidence $evidence|ConvertTo-Json -Depth 6 -Compress
    if(-not $pass){exit 2}
} catch {
    $case=$(if($Mode -eq 'PortConflict'){'W10'}elseif($Mode -eq 'LowDisk'){'W12'}else{'W13'})
    $code='ENV1B3_RESOURCE_INTERFERENCE_FAILED'; if($_.Exception.Message -match '^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $case -Result 'FAIL' -Code $code -Evidence @{}|ConvertTo-Json -Compress; exit 2
}
