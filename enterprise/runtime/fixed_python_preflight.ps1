[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AppRoot,
    [Parameter(Mandatory)][ValidateSet('start','status','health','stop','restart')][string]$Command
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'

function Write-Result([string]$Status,[string]$Code,[int]$ExitCode,[hashtable]$Extra=@{}){
    $value=[ordered]@{schema_version='env-1b3-fixed-python-preflight-v1';status=$Status;code=$Code}
    foreach($name in $Extra.Keys){$value[$name]=$Extra[$name]}
    $value|ConvertTo-Json -Depth 8 -Compress
    exit $ExitCode
}
function Read-BoundedJson([string]$Path,[int]$Limit){
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try{
        if($stream.Length-le0-or$stream.Length-gt$Limit){throw[InvalidOperationException]::new('size')}
        $bytes=New-Object byte[] ([int]$stream.Length);$offset=0
        while($offset-lt$bytes.Length){$read=$stream.Read($bytes,$offset,$bytes.Length-$offset);if($read-le0){throw (New-Object IO.EndOfStreamException)};$offset+=$read}
    }finally{$stream.Dispose()}
    if($bytes.Length-ge3-and$bytes[0]-eq0xEF-and$bytes[1]-eq0xBB-and$bytes[2]-eq0xBF){throw[InvalidOperationException]::new('bom')}
    return [Text.UTF8Encoding]::new($false,$true).GetString($bytes)|ConvertFrom-Json
}
function Get-Sha256([string]$Path){
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $hash=[Security.Cryptography.SHA256]::Create()
    try{return([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}finally{$hash.Dispose();$stream.Dispose()}
}
function Test-ProcessIdentity($State,[string]$ExpectedPython,[string]$ExpectedHost,[string]$ExpectedAppRoot,[string]$ExpectedRuntimeRoot){
    $pid=[int]$State.supervisor_pid
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$pid) -ErrorAction Stop
    if($null-eq$process){return $false}
    $created=$process.PSObject.Properties['CreationDate'];$executable=$process.PSObject.Properties['ExecutablePath'];$line=$process.PSObject.Properties['CommandLine']
    if($null-eq$created-or$null-eq$executable-or$null-eq$line){return $false}
    $createdAt=$created.Value
    if($createdAt-isnot[DateTime]){$createdAt=[Management.ManagementDateTimeConverter]::ToDateTime([string]$createdAt)}
    $ticks=$createdAt.ToUniversalTime().ToFileTimeUtc()
    return $ticks-eq[int64]$State.supervisor_process_created_at-and
        [string]::Compare([IO.Path]::GetFullPath([string]$executable.Value),$ExpectedPython,$true)-eq0-and
        ([string]$line.Value).IndexOf($ExpectedHost,[StringComparison]::OrdinalIgnoreCase)-ge0-and
        ([string]$line.Value).IndexOf($ExpectedAppRoot,[StringComparison]::OrdinalIgnoreCase)-ge0-and
        ([string]$line.Value).IndexOf($ExpectedRuntimeRoot,[StringComparison]::OrdinalIgnoreCase)-ge0-and
        ([string]$line.Value).IndexOf([string]$State.supervisor_instance_id,[StringComparison]::Ordinal)-ge0-and
        ([string]$line.Value).IndexOf([string]$State.launch_context_identity,[StringComparison]::Ordinal)-ge0
}
function Invoke-OwnedStop([string]$Root){
    $runtimeRoot=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'InfiniteCanvasEnterprise\runtime'
    foreach($required in @('runtime-state.json','runtime-supervisor.lock','launch-context.json')){
        if(-not(Test-Path -LiteralPath (Join-Path $runtimeRoot $required) -PathType Leaf)){Write-Result blocked PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED 2}
    }
    $state=Read-BoundedJson (Join-Path $runtimeRoot 'runtime-state.json') 65536
    $lock=Read-BoundedJson (Join-Path $runtimeRoot 'runtime-supervisor.lock') 65536
    $contextPath=Join-Path $runtimeRoot 'launch-context.json';$context=Read-BoundedJson $contextPath 16384
    $contextSha=Get-Sha256 $contextPath
    $fields=@('supervisor_instance_id','release_id','release_manifest_sha256','release_payload_tree_sha256','enterprise_commit','enterprise_tree','runtime_manifest_sha256','startup_preflight_sha256','launch_context_identity','supervisor_command_identity')
    foreach($name in $fields){
        if($null-eq$state.PSObject.Properties[$name]-or$null-eq$lock.PSObject.Properties[$name]-or[string]$state.$name-ne[string]$lock.$name){Write-Result blocked PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED 2}
    }
    if(([string]$state.supervisor_command_identity)-notmatch'^[0-9a-f]{64}$'){Write-Result blocked PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED 2}
    if($lock.lock_phase-ne'adopted'-or$state.runtime_mode-ne'portable-release'-or$lock.runtime_mode-ne'portable-release'-or
        $context.instance_id-ne$state.supervisor_instance_id-or$context.release_id-ne$state.release_id-or$contextSha-ne$state.launch_context_identity){Write-Result blocked PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED 2}
    $python=[IO.Path]::GetFullPath((Join-Path $Root 'python\python.exe'));$host=[IO.Path]::GetFullPath((Join-Path $Root 'enterprise\runtime\host.py'))
    if(-not(Test-ProcessIdentity $state $python $host $Root $runtimeRoot)){Write-Result blocked PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED 2}
    $control=Join-Path $runtimeRoot 'control';if(-not(Test-Path -LiteralPath $control -PathType Container)){Write-Result blocked PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED 2}
    $request=[Guid]::NewGuid().ToString('N');$path=Join-Path $control ('cmd-'+$request.Substring(0,16)+'.json')
    $document=[ordered]@{schema_version='runtime-supervisor-state-v1';request_id=$request;command='stop';supervisor_instance_id=[string]$state.supervisor_instance_id;issued_at=[DateTime]::UtcNow.ToString('o');expected_state_generation=[int]$state.state_generation;launch_context_identity=[string]$state.launch_context_identity}
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($document|ConvertTo-Json -Depth 6 -Compress))
    $handle=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try{$handle.Write($bytes,0,$bytes.Length);$handle.Flush($true)}finally{$handle.Dispose()}
    $ack=Join-Path $control ('ack-'+$request.Substring(0,16)+'.json');$deadline=[DateTime]::UtcNow.AddSeconds(90)
    while([DateTime]::UtcNow-lt$deadline){
        if(Test-Path -LiteralPath $ack -PathType Leaf){
            $value=Read-BoundedJson $ack 65536
            if($value.request_id-eq$request-and$value.supervisor_instance_id-eq$state.supervisor_instance_id-and$value.result-eq'stopped'){
                Write-Result stopped PORTABLE_FIXED_PYTHON_TAMPER_OWNED_STOPPED 0 @{acknowledged=$true}
            }
            Write-Result blocked PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED 2
        }
        Start-Sleep -Milliseconds 200
    }
    Write-Result blocked PORTABLE_RUNTIME_CONTROL_TIMEOUT 2
}

try{
    $root=[IO.Path]::GetFullPath($AppRoot);$manifestPath=Join-Path $root 'runtime-manifest.json';$dllPath=Join-Path $root 'python\python314.dll'
    try{$manifest=Read-BoundedJson $manifestPath 1048576}catch{exit 0}
    $records=@($manifest.core_files|Where-Object{$_.filename-eq'python314.dll'})
    if($records.Count-ne1){exit 0}
    $record=$records[0]
    $valid=(Test-Path -LiteralPath $dllPath -PathType Leaf)-and([IO.FileInfo]$dllPath).Length-eq[int64]$record.size_bytes-and(Get-Sha256 $dllPath)-eq[string]$record.sha256
    if($valid){exit 0}
    # Exit 3 is private to the status wrapper: the diagnostic is complete and
    # the fixed interpreter must not be loaded.  The wrapper maps it to the
    # public status success exit 0.
    if($Command-eq'status'){Write-Result diagnostic PORTABLE_FIXED_PYTHON_INTEGRITY_INVALID 3 @{runtime_integrity_valid=$false}}
    if($Command-eq'stop'){Invoke-OwnedStop $root}
    Write-Result blocked PORTABLE_FIXED_PYTHON_INTEGRITY_INVALID 2 @{runtime_integrity_valid=$false}
}catch{Write-Result blocked PORTABLE_FIXED_PYTHON_PREFLIGHT_FAILED 2}
