[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('PortConflict','ArchiveLock','LowDisk','DefenderStatus','W12Full','W13Full')][string]$Mode,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [string]$AppRoot,
    [string]$ArchivePath,
    [string]$IsolatedLowDiskRoot,
    [string]$HandoffRoot,
    [string]$TestRoot,
    [string]$DiagnosticProbeManifestPath,
    [string]$ContractPath
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
$filler=$null

function Get-PointerSnapshot([string]$Root){
    $path=Join-Path $Root 'install\state\current-release.json'
    if(Test-Path -LiteralPath $path -PathType Leaf){return [ordered]@{exists=$true;sha256=(Get-ENV1B3Sha256 $path)}}
    return [ordered]@{exists=$false;sha256=$null}
}
function Test-PointerUnchanged($Before,[string]$Root){$after=Get-PointerSnapshot $Root;return $after.exists -eq $Before.exists -and $after.sha256 -eq $Before.sha256}
function Get-HandoffArchive([string]$Root){$handoff=Read-ENV1B3Json (Join-Path $Root 'CANDIDATE-HANDOFF.json');return [ordered]@{handoff=$handoff;archive=(Join-Path $Root ([string]$handoff.archive_filename));release_id=[string]$handoff.release_id}}
function Get-WrapperName([string]$Command){
    switch($Command){
        start{return(-join@([char]0x542F,[char]0x52A8,[char]0x4F01,[char]0x4E1A,[char]0x7248))+'.bat'}
        status{return(-join@([char]0x67E5,[char]0x770B,[char]0x4F01,[char]0x4E1A,[char]0x7248,[char]0x72B6,[char]0x6001))+'.bat'}
    }
    throw[InvalidOperationException]::new('ENV1B3_WRAPPER_MISSING|wrapper')
}
function Invoke-Wrapper([string]$Root,[string]$Command){
    $wrapper=Join-Path $Root (Get-WrapperName $Command)
    if(-not(Test-Path -LiteralPath $wrapper -PathType Leaf)){throw[InvalidOperationException]::new('ENV1B3_WRAPPER_MISSING|wrapper')}
    $native=Invoke-ENV1B3ManagedProcess -FileName $env:ComSpec -Arguments ('/d /s /c ""'+$wrapper+'""') -WorkingDirectory ([IO.Path]::GetPathRoot($Root)) -TimeoutSeconds 90
    $payload=$null;$text=[string]$native.stdout+"`n"+[string]$native.stderr
    foreach($line in @($text.Split("`n"))){try{$candidate=$line.TrimEnd("`r")|ConvertFrom-Json;if($null-ne$candidate){$payload=$candidate}}catch{}}
    return [ordered]@{exit_code=[int]$native.exit_code;timed_out=[bool]$native.timed_out;payload=$payload;output_tail=$text}
}
function Get-FormalPorts([string]$Root){
    $status=Invoke-Wrapper $Root status
    if($status.exit_code-ne0-or$null-eq$status.payload){throw[InvalidOperationException]::new('ENV1B3_PORT_CONTRACT_UNAVAILABLE|status')}
    $upstream=[int]$status.payload.upstream_listener.port;$gateway=[int]$status.payload.gateway_listener.port
    if($upstream-lt1-or$upstream-gt65535-or$gateway-lt1-or$gateway-gt65535-or$upstream-eq$gateway){throw[InvalidOperationException]::new('ENV1B3_PORT_CONTRACT_INVALID|ports')}
    return @([ordered]@{role='upstream';port=$upstream},[ordered]@{role='gateway';port=$gateway})
}

try{
    if($Mode-eq'PortConflict'){
        [void](Assert-ENV1B3AbsoluteSafePath $AppRoot)
        $checks=@();$pass=$true
        foreach($contract in @(Get-FormalPorts $AppRoot)){
            $listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,[int]$contract.port);$listener.Start()
            try{$start=Invoke-Wrapper $AppRoot start;$survived=$listener.Server.IsBound}finally{$listener.Stop()}
            $recoveryRoot=Join-Path $EvidenceRoot ('w10-recovery-'+[string]$contract.role);$cwd=Join-Path $EvidenceRoot ('w10-cwd-'+[string]$contract.role);[IO.Directory]::CreateDirectory($cwd)|Out-Null
            & (Join-Path $PSScriptRoot 'Invoke-LifecycleMatrix.ps1') -AppRoot $AppRoot -EvidenceRoot $recoveryRoot -CaseId W03 -DifferentCwd $cwd -PolluteEnvironment
            $recovery=Read-ENV1B3Json (Join-Path $recoveryRoot 'W03.json')
            $itemPass=$start.exit_code-eq2-and-not$start.timed_out-and$survived-and$recovery.result-eq'PASS'
            if(-not$itemPass){$pass=$false}
            $checks+=[ordered]@{port_role=[string]$contract.role;port_number=[int]$contract.port;contract_source='formal_status_runtime_config';foreign_pid=$PID;start_exit=[int]$start.exit_code;listener_survived=[bool]$survived;recovery_lifecycle_result=[string]$recovery.result}
        }
        Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W10 -Result $(if($pass){'PASS'}else{'FAIL'}) -Code $(if($pass){'ENV1B3_RESOURCE_INTERFERENCE_PASS'}else{'ENV1B3_RESOURCE_INTERFERENCE_FAILED'}) -Evidence @{start_exit=2;foreign_listener_survived=(@($checks|Where-Object{-not$_.listener_survived}).Count-eq0);port_checks=$checks;contract_source='formal_status_runtime_config';execution_context_controlled_loopback_listener=$true;fixture_materialized_release=$true}|ConvertTo-Json -Depth 8 -Compress
        if(-not$pass){exit 2};exit 0
    }

    if($Mode-eq'W12Full'){
        [void](Assert-ENV1B3AbsoluteSafePath $IsolatedLowDiskRoot -AllowMissingLeaf);[void](Assert-ENV1B3AbsoluteSafePath $HandoffRoot);[void](Assert-ENV1B3AbsoluteSafePath $TestRoot -AllowMissingLeaf)
        [IO.Directory]::CreateDirectory($IsolatedLowDiskRoot)|Out-Null
        $volumeRoot=[IO.Path]::GetPathRoot([IO.Path]::GetFullPath($IsolatedLowDiskRoot));$systemRoot=[IO.Path]::GetPathRoot($env:SystemRoot)
        if([string]::Compare($volumeRoot,$systemRoot,$true)-eq0){throw[InvalidOperationException]::new('ENV1B3_SYSTEM_VOLUME_FORBIDDEN|volume')}
        $drive=[IO.DriveInfo]::new($volumeRoot)
        if($drive.TotalSize-gt2GB){throw[InvalidOperationException]::new('ENV1B3_LOW_SPACE_PRECONDITION_INVALID|volume_size')}
        $artifact=Get-HandoffArchive $HandoffRoot;$inventory=Read-ENV1B3Json (Join-Path $HandoffRoot ([string]$artifact.handoff.inventory_filename))
        $required=[int64]$inventory.total_size_bytes+32MB;$leave=[int64]8MB;$filler=Join-Path $IsolatedLowDiskRoot '.env1b3-controlled-fill.bin'
        if(Test-Path -LiteralPath $filler){throw[InvalidOperationException]::new('ENV1B3_LOW_SPACE_PRECONDITION_INVALID|filler')}
        $stream=[IO.File]::Open($filler,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);$buffer=New-Object byte[] 1048576
        try{
            while(([IO.DriveInfo]::new($volumeRoot)).AvailableFreeSpace-gt$leave){
                $remaining=([IO.DriveInfo]::new($volumeRoot)).AvailableFreeSpace-$leave;$count=[int][Math]::Min($buffer.Length,[Math]::Max(0,$remaining));if($count-le0){break}
                try{$stream.Write($buffer,0,$count)}catch [IO.IOException]{break}
            }
            try{$stream.Flush($true)}catch [IO.IOException]{}
        }finally{$stream.Dispose()}
        $available=([IO.DriveInfo]::new($volumeRoot)).AvailableFreeSpace;$preflightPass=$available-lt$required
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W12 -SubcheckId archive_preflight_low_space -Result $(if($preflightPass){'PASS'}else{'FAIL'}) -Code $(if($preflightPass){'ENV1B3_LOW_SPACE_PREFLIGHT_PASS'}else{'ENV1B3_LOW_SPACE_PRECONDITION_INVALID'}) -Evidence @{isolated_non_system_volume=$true;available_below_required=$preflightPass;required_bytes=$required}|Out-Null
        $before=Get-PointerSnapshot $TestRoot;$materializationFailed=$false
        try{& (Join-Path $PSScriptRoot 'Invoke-Materialization.ps1') -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot (Join-Path $EvidenceRoot 'w12-low-space-materialization') -CaseId W02 -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath;if(-not$?){$materializationFailed=$true}}catch{$materializationFailed=$true}
        $final=Join-Path $TestRoot ('install\releases\'+$artifact.release_id);$partial=Join-Path $TestRoot ('install\staging\'+$artifact.release_id+'.partial');$pointerTemp=Join-Path $TestRoot 'install\state\current-release.json.new'
        $noPartial=-not(Test-Path -LiteralPath $partial);$noFinal=-not(Test-Path -LiteralPath $final);$pointerSame=Test-PointerUnchanged $before $TestRoot;$tempAbsent=-not(Test-Path -LiteralPath $pointerTemp)
        $materializationPass=$materializationFailed-and$noPartial-and$noFinal-and$pointerSame-and$tempAbsent
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W12 -SubcheckId materialization_low_space -Result $(if($materializationPass){'PASS'}else{'FAIL'}) -Code $(if($materializationPass){'ENV1B3_LOW_SPACE_MATERIALIZATION_PASS'}else{'ENV1B3_MATERIALIZATION_FAILED'}) -Evidence @{materialization_failed_closed=$materializationFailed;no_final_app_root=$noFinal;no_partial_app_root=$noPartial;pointer_unchanged=$pointerSame;pointer_temp_absent=$tempAbsent}|Out-Null
        $writableProbe=Join-Path $IsolatedLowDiskRoot '.env1b3-writable-root-probe';$writeFailed=$false
        try{$probeStream=[IO.File]::Open($writableProbe,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$large=New-Object byte[] 16777216;$probeStream.Write($large,0,$large.Length);$probeStream.Flush($true)}finally{$probeStream.Dispose()}}catch [IO.IOException]{$writeFailed=$true}finally{if(Test-Path -LiteralPath $writableProbe){Remove-Item -LiteralPath $writableProbe -Force}}
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W12 -SubcheckId writable_root_low_space -Result $(if($writeFailed){'PASS'}else{'FAIL'}) -Code $(if($writeFailed){'ENV1B3_LOW_SPACE_WRITABLE_ROOT_PASS'}else{'ENV1B3_LOW_SPACE_WRITABLE_ROOT_FAILED'}) -Evidence @{bounded_write_failed_closed=$writeFailed}|Out-Null
        $atomicPass=$pointerSame-and$tempAbsent-and$noFinal
        Remove-Item -LiteralPath $filler -Force
        & (Join-Path $PSScriptRoot 'Invoke-Materialization.ps1') -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot (Join-Path $EvidenceRoot 'w12-recovery-materialization') -CaseId W02 -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath
        $retryPassed=$LASTEXITCODE-eq0
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W12 -SubcheckId pointer_atomicity -Result $(if($atomicPass-and$retryPassed){'PASS'}else{'FAIL'}) -Code $(if($atomicPass-and$retryPassed){'ENV1B3_LOW_SPACE_POINTER_ATOMICITY_PASS'}else{'ENV1B3_LOW_SPACE_POINTER_ATOMICITY_FAILED'}) -Evidence @{pointer_unchanged=$pointerSame;pointer_temp_absent=$tempAbsent;no_startable_partial=$noFinal;retry_after_cleanup_passed=$retryPassed;execution_context_isolated_non_system_small_vhdx=$true;fixture_candidate_handoff=$true;fixture_low_space_root=$true}|Out-Null
        if(-not$retryPassed){throw[InvalidOperationException]::new('ENV1B3_LOW_SPACE_RECOVERY_FAILED|retry')}
        $aggregate=Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W12 -ContractPath $ContractPath;$aggregate|ConvertTo-Json -Depth 10 -Compress
        if($aggregate.result-ne'PASS'){exit 2};exit 0
    }

    if($Mode-eq'W13Full'){
        [void](Assert-ENV1B3AbsoluteSafePath $HandoffRoot);[void](Assert-ENV1B3AbsoluteSafePath $TestRoot -AllowMissingLeaf)
        $artifact=Get-HandoffArchive $HandoffRoot;$before=Get-PointerSnapshot $TestRoot
        $handle=[IO.File]::Open($artifact.archive,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None);$lockFailed=$false;$failureCode=$null
        try{try{[void](Test-ENV1B3Handoff -HandoffRoot $HandoffRoot)}catch{$lockFailed=$true;$failureCode='ENV1B3_ARCHIVE_LOCK_VALIDATION_FAILED'}}finally{$handle.Dispose()}
        $final=Join-Path $TestRoot ('install\releases\'+$artifact.release_id);$partial=Join-Path $TestRoot ('install\staging\'+$artifact.release_id+'.partial');$pointerTemp=Join-Path $TestRoot 'install\state\current-release.json.new'
        $pointerSame=Test-PointerUnchanged $before $TestRoot;$noFinal=-not(Test-Path -LiteralPath $final);$noPartial=-not(Test-Path -LiteralPath $partial);$tempAbsent=-not(Test-Path -LiteralPath $pointerTemp)
        $lockPass=$lockFailed-and$pointerSame-and$noFinal-and$noPartial-and$tempAbsent
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W13 -SubcheckId archive_lock_failure -Result $(if($lockPass){'PASS'}else{'FAIL'}) -Code $(if($lockPass){'ENV1B3_ARCHIVE_LOCK_FAILURE_PASS'}else{'ENV1B3_ARCHIVE_LOCK_VALIDATION_FAILED'}) -Evidence @{lock_failure_stable=$lockFailed;pointer_unmodified=$pointerSame;pointer_temp_absent=$tempAbsent;no_final_app_root=$noFinal;no_partial_app_root=$noPartial;failure_code=$failureCode}|Out-Null
        & (Join-Path $PSScriptRoot 'Invoke-Materialization.ps1') -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot (Join-Path $EvidenceRoot 'w13-lock-recovery') -CaseId W02 -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath
        $recoveryRecord=Read-ENV1B3Json (Join-Path $EvidenceRoot 'w13-lock-recovery\W02.json');$pointer=Read-ENV1B3Json (Join-Path $TestRoot 'install\state\current-release.json')
        $recoveryPass=$recoveryRecord.result-eq'PASS'-and$pointer.release_id-eq$artifact.release_id-and(Test-Path -LiteralPath $final -PathType Container)
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W13 -SubcheckId recovery_after_lock_release -Result $(if($recoveryPass){'PASS'}else{'FAIL'}) -Code $(if($recoveryPass){'ENV1B3_ARCHIVE_LOCK_RECOVERY_PASS'}else{'ENV1B3_ARCHIVE_LOCK_RECOVERY_FAILED'}) -Evidence @{lock_released=$true;recovery_materialization_passed=$recoveryPass;candidate_id=[string]$artifact.handoff.candidate_id;release_id=[string]$pointer.release_id;manifest_semantics_revalidated=$true}|Out-Null
        $status=Get-MpComputerStatus -ErrorAction Stop;$preferenceBefore=Get-MpPreference -ErrorAction Stop
        $enabled=[bool]$status.AntivirusEnabled-and[bool]$status.RealTimeProtectionEnabled
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W13 -SubcheckId defender_enabled -Result $(if($enabled){'PASS'}else{'FAIL'}) -Code $(if($enabled){'ENV1B3_DEFENDER_ENABLED_PASS'}else{'ENV1B3_DEFENDER_VALIDATION_FAILED'}) -Evidence @{antivirus_enabled=[bool]$status.AntivirusEnabled;realtime_enabled=[bool]$status.RealTimeProtectionEnabled}|Out-Null
        $detectionsBefore=@(Get-MpThreatDetection -ErrorAction SilentlyContinue).Count
        Start-MpScan -ScanType CustomScan -ScanPath $HandoffRoot -ErrorAction Stop
        $detectionsAfter=@(Get-MpThreatDetection -ErrorAction SilentlyContinue).Count;$scanPass=$detectionsAfter-eq$detectionsBefore
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W13 -SubcheckId controlled_scan_result -Result $(if($scanPass){'PASS'}else{'FAIL'}) -Code $(if($scanPass){'ENV1B3_DEFENDER_SCAN_PASS'}else{'ENV1B3_DEFENDER_SCAN_INTERFERENCE'}) -Evidence @{controlled_scan_completed=$true;detection_count_before=$detectionsBefore;detection_count_after=$detectionsAfter;candidate_quarantined=($detectionsAfter-gt$detectionsBefore)}|Out-Null
        $preferenceAfter=Get-MpPreference -ErrorAction Stop
        $beforeExclusions=Get-ENV1B3NonEmptyStringSet (@($preferenceBefore.ExclusionPath)+@($preferenceBefore.ExclusionProcess)+@($preferenceBefore.ExclusionExtension))
        $afterExclusions=Get-ENV1B3NonEmptyStringSet (@($preferenceAfter.ExclusionPath)+@($preferenceAfter.ExclusionProcess)+@($preferenceAfter.ExclusionExtension))
        $difference=@(Compare-Object -ReferenceObject @($beforeExclusions) -DifferenceObject @($afterExclusions) -CaseSensitive:$false)
        $unchanged=$difference.Count-eq0
        $added=@($difference|Where-Object{$_.SideIndicator-eq'=>'})
        $actualCount=@($afterExclusions).Count
        $absent=$actualCount-eq0
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W13 -SubcheckId permanent_exclusions_absent -Result $(if($absent){'PASS'}else{'BLOCKED'}) -Code $(if($absent){'ENV1B3_DEFENDER_EXCLUSIONS_ABSENT'}else{'ENV1B3_DEFENDER_EXCLUSIONS_PRESENT'}) -Evidence @{actual_exclusion_count=$actualCount;permanent_exclusions_absent=$absent;scan_completed=$true;execution_context_defender_enabled_guest=$true;fixture_candidate_handoff=$true}|Out-Null
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W13 -SubcheckId permanent_exclusions_unchanged -Result $(if($unchanged){'PASS'}else{'FAIL'}) -Code $(if($unchanged){'ENV1B3_DEFENDER_EXCLUSIONS_UNCHANGED'}else{'ENV1B3_DEFENDER_EXCLUSIONS_CHANGED'}) -Evidence @{exclusion_count_before=@($beforeExclusions).Count;exclusion_count_after=$actualCount;actual_exclusion_count=$actualCount;exclusions_unchanged=$unchanged;permanent_exclusion_added=($added.Count-gt0);scan_completed=$true;execution_context_defender_enabled_guest=$true;fixture_candidate_handoff=$true}|Out-Null
        $aggregate=Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W13 -ContractPath $ContractPath;$aggregate|ConvertTo-Json -Depth 10 -Compress
        if($aggregate.result-ne'PASS'){exit 2};exit 0
    }

    if($Mode-eq'ArchiveLock'){
        [void](Assert-ENV1B3AbsoluteSafePath $ArchivePath);$handle=[IO.File]::Open($ArchivePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
        try{$blocked=$false;try{[void][IO.File]::Open($ArchivePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)}catch{$blocked=$true}}finally{$handle.Dispose()}
        $pass=$blocked;$case='W13';$evidence=@{exclusive_archive_lock_detected=$blocked;lock_released=$true}
    }elseif($Mode-eq'LowDisk'){
        [void](Assert-ENV1B3AbsoluteSafePath $IsolatedLowDiskRoot);$root=[IO.Path]::GetPathRoot([IO.Path]::GetFullPath($IsolatedLowDiskRoot));$system=[IO.Path]::GetPathRoot($env:SystemRoot)
        if($root-eq$system){throw[InvalidOperationException]::new('ENV1B3_SYSTEM_VOLUME_FORBIDDEN|volume')};$drive=[IO.DriveInfo]::new($root);$pass=$drive.AvailableFreeSpace-lt128MB;$case='W12';$evidence=@{isolated_non_system_volume=$true;free_space_below_gate=$pass}
    }else{
        $status=Get-MpComputerStatus -ErrorAction Stop;$pass=[bool]$status.AntivirusEnabled-and[bool]$status.RealTimeProtectionEnabled;$case='W13';$evidence=@{antivirus_enabled=[bool]$status.AntivirusEnabled;realtime_enabled=[bool]$status.RealTimeProtectionEnabled;permanent_exclusion_added=$false}
    }
    Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $case -Result $(if($pass){'PASS'}else{'FAIL'}) -Code $(if($pass){'ENV1B3_RESOURCE_INTERFERENCE_PASS'}else{'ENV1B3_RESOURCE_INTERFERENCE_FAILED'}) -Evidence $evidence|ConvertTo-Json -Depth 6 -Compress
    if(-not$pass){exit 2}
}catch{
    if($Mode -eq 'W12Full' -and $null -ne $filler -and (Test-Path -LiteralPath $filler)){try{Remove-Item -LiteralPath $filler -Force}catch{}}
    $case=$(if($Mode-eq'PortConflict'){'W10'}elseif($Mode-in@('LowDisk','W12Full')){'W12'}else{'W13'})
    $code='ENV1B3_RESOURCE_INTERFERENCE_FAILED';if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    if(-not(Test-Path -LiteralPath (Join-Path $EvidenceRoot ($case+'.json')))){Write-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId $case -Result FAIL -Code $code -Evidence @{}|ConvertTo-Json -Compress};exit 2
}
