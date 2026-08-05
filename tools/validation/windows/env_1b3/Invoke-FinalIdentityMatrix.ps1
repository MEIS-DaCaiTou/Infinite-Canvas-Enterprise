[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Prepare','Validate')][string]$Mode,
    [Parameter(Mandatory)][string]$HandoffRoot,
    [Parameter(Mandatory)][string]$TestRoot,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][string]$ContractPath,
    [string]$DiagnosticProbeManifestPath
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
$failureStage='module_import'
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
$statePath=Join-Path $EvidenceRoot 'W14-PREPARE.json'
$comparisonEvidence=$null

function Protect-ENV1B3DiagnosticPath([string]$Value){
    if([String]::IsNullOrWhiteSpace($Value)){return $Value}
    $profile=[Environment]::GetFolderPath('UserProfile')
    if(-not[String]::IsNullOrWhiteSpace($profile)-and$Value.StartsWith($profile,[StringComparison]::OrdinalIgnoreCase)){
        return '<USERPROFILE>'+$Value.Substring($profile.Length)
    }
    return $Value
}
function Get-ENV1B3PathShape([string]$Value){
    $namespace=$(if($Value.StartsWith('\\?\UNC\',[StringComparison]::OrdinalIgnoreCase)){'extended_unc'}elseif($Value.StartsWith('\\?\',[StringComparison]::OrdinalIgnoreCase)){'extended_drive'}else{'normal'})
    $trailing=$Value.EndsWith('\')-or$Value.EndsWith('/')
    $comparable=ConvertTo-ENV1B3ComparableProcessPath $Value
    $root=[IO.Path]::GetPathRoot($comparable)
    return [ordered]@{drive=$root;relative_suffix=(Protect-ENV1B3DiagnosticPath $comparable.Substring($root.Length));namespace=$namespace;trailing_separator=$trailing;canonical=(Protect-ENV1B3DiagnosticPath $comparable)}
}
function Assert-ENV1B3Comparison([string]$Name,[object]$Expected,[object]$Actual,[ValidateSet('ordinal','hash','path')][string]$Kind='ordinal'){
    $script:failureStage=$Name
    $expectedText=[string]$Expected;$actualText=[string]$Actual
    if($Kind-eq'path'){
        $expectedShape=Get-ENV1B3PathShape $expectedText;$actualShape=Get-ENV1B3PathShape $actualText
        $equal=[String]::Equals($expectedText,$actualText,[StringComparison]::OrdinalIgnoreCase)
        if(-not$equal){
            $script:comparisonEvidence=[ordered]@{comparison_name=$Name;expected=(Protect-ENV1B3DiagnosticPath $expectedText);actual=(Protect-ENV1B3DiagnosticPath $actualText);normalized_expected=$expectedShape.canonical;normalized_actual=$actualShape.canonical;expected_path=$expectedShape;actual_path=$actualShape}
        }
    }else{
        $comparison=$(if($Kind-eq'hash'){[StringComparison]::OrdinalIgnoreCase}else{[StringComparison]::Ordinal})
        $equal=[String]::Equals($expectedText,$actualText,$comparison)
        if(-not$equal){$script:comparisonEvidence=[ordered]@{comparison_name=$Name;expected=$expectedText;actual=$actualText;normalized_expected=$expectedText;normalized_actual=$actualText}}
    }
    if(-not$equal){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|comparison')}
}
try{
    $failureStage='app_root_path'
    [void](Assert-ENV1B3AbsoluteSafePath $HandoffRoot);[void](Assert-ENV1B3AbsoluteSafePath $TestRoot -AllowMissingLeaf);[void](Assert-ENV1B3AbsoluteSafePath $EvidenceRoot -AllowMissingLeaf)
    [IO.Directory]::CreateDirectory($EvidenceRoot)|Out-Null
    $handoff=Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json')
    $appRoot=Join-Path $TestRoot ('install\releases\'+[string]$handoff.release_id)
    if($Mode-eq'Prepare'){
        $failureStage='artifact_and_materialization'
        $artifact=Test-ENV1B3Handoff -HandoffRoot $HandoffRoot
        & (Join-Path $PSScriptRoot 'Invoke-Materialization.ps1') -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot (Join-Path $EvidenceRoot 'prepare-materialization') -CaseId W02 -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath
        if(-not$?){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_PREPARE_FAILED|materialization')}
        $tree=Get-ENV1B3DirectoryTree $appRoot
        $pointer=Join-Path $TestRoot 'install\state\current-release.json'
        $state=[ordered]@{schema_version='env-1b3-w14-prepare-v1';candidate_id=[string]$handoff.candidate_id;release_id=[string]$handoff.release_id;app_root=$appRoot;app_root_tree=$tree;pointer_sha256=(Get-ENV1B3Sha256 $pointer);payload_tree_sha256=[string]$artifact.artifact.payload_tree_sha256;next_action='apply read-and-execute (without write) to every APP_ROOT directory and file for the application user, verify a payload file remains readable, then run W14Validate'}
        [IO.File]::WriteAllText($statePath,($state|ConvertTo-Json -Depth 8 -Compress)+"`n",[Text.UTF8Encoding]::new($false))
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W14 -SubcheckId prepare -Result PASS -Code ENV1B3_FINAL_IDENTITY_PREPARE_PASS -Evidence @{candidate_id=$state.candidate_id;release_id=$state.release_id;app_root_tree_sha256=$tree.tree_sha256;pointer_sha256=$state.pointer_sha256;lifecycle_executed=$false}|ConvertTo-Json -Depth 8 -Compress
        exit 0
    }
    $state=Read-ENV1B3Json $statePath
    $failureStage='state_schema';Assert-ENV1B3Comparison state_schema 'env-1b3-w14-prepare-v1' $state.schema_version
    $failureStage='candidate_id';Assert-ENV1B3Comparison candidate_id ([string]$handoff.candidate_id) $state.candidate_id
    $failureStage='release_id';Assert-ENV1B3Comparison release_id ([string]$handoff.release_id) $state.release_id
    $failureStage='app_root_path';Assert-ENV1B3Comparison app_root_path $appRoot $state.app_root path
    $pointerPath=Join-Path $TestRoot 'install\state\current-release.json'
    $failureStage='pointer_sha256';Assert-ENV1B3Comparison pointer_sha256 $state.pointer_sha256 (Get-ENV1B3Sha256 $pointerPath) hash
    $failureStage='app_root_tree_read'
    try{$treeBefore=Get-ENV1B3DirectoryTree $appRoot}catch{
        $exceptionCursor=$_.Exception;$treeReadActual='read_failed'
        while($null-ne$exceptionCursor){
            if($exceptionCursor-is[UnauthorizedAccessException]){$treeReadActual='access_denied';break}
            if($exceptionCursor-is[IO.DirectoryNotFoundException]-or$exceptionCursor-is[IO.FileNotFoundException]){$treeReadActual='missing';break}
            $exceptionCursor=$exceptionCursor.InnerException
        }
        $comparisonEvidence=[ordered]@{comparison_name='app_root_tree_read';expected='readable_directory_tree';actual=$treeReadActual;normalized_expected='readable_directory_tree';normalized_actual=$treeReadActual}
        throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|tree_read')
    }
    $failureStage='app_root_tree_sha256';Assert-ENV1B3Comparison app_root_tree_sha256 $state.app_root_tree.tree_sha256 $treeBefore.tree_sha256 hash
    $permissionEvidence=Join-Path $EvidenceRoot ('w14-permission-'+[Guid]::NewGuid().ToString('N'))
    try{
        $failureStage='read_only_app_root'
        & (Join-Path $PSScriptRoot 'Invoke-PermissionMatrix.ps1') -AppRoot $appRoot -EvidenceRoot $permissionEvidence -Mode VerifyReadOnly
        if(-not$?){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|readonly')}
        $permission=Read-ENV1B3Json (Join-Path $permissionEvidence 'W06.json')
    }finally{if(Test-Path -LiteralPath $permissionEvidence){Remove-Item -LiteralPath $permissionEvidence -Recurse -Force}}
    Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W14 -SubcheckId readonly_app_root -Result PASS -Code ENV1B3_FINAL_IDENTITY_READONLY_PASS -Evidence @{app_root_write_denied=[bool]$permission.evidence.app_root_write_denied}|Out-Null
    $installRoot=Join-Path $TestRoot 'install';$externalRoots=@('config','data','logs','backups','state','staging')|ForEach-Object{Join-Path $installRoot $_}
    $failureStage='external_roots'
    $pathRootsExternal=@($externalRoots|Where-Object{[IO.Path]::GetFullPath($_).StartsWith(([IO.Path]::GetFullPath($appRoot)+'\'),[StringComparison]::OrdinalIgnoreCase)}).Count-eq0
    if(-not$pathRootsExternal){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|path_roots')}
    $differentCwd=[IO.Path]::GetPathRoot($TestRoot);$failureStage='different_cwd_path';[void](Assert-ENV1B3AbsoluteSafePath $differentCwd)
    $failureStage='offline_context'
    & (Join-Path $PSScriptRoot 'Invoke-LifecycleMatrix.ps1') -AppRoot $appRoot -EvidenceRoot $EvidenceRoot -CaseId W14 -DifferentCwd $differentCwd -PolluteEnvironment -RequireOffline -RequireExternalPathRoots -SubcheckId offline_non_admin_lifecycle
    if(-not$?){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|lifecycle')}
    $lifecycle=Read-ENV1B3Json (Join-Path $EvidenceRoot 'subchecks\W14\offline_non_admin_lifecycle.json')
    $failureStage='fixed_python'
    if(-not$pathRootsExternal-or$lifecycle.evidence.path_roots_external-ne$true-or$lifecycle.evidence.fixed_python_all_roles-ne$true){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|identity')}
    $failureStage='app_root_tree'
    if($lifecycle.evidence.app_root_tree_unchanged-ne$true){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|tree')}
    $failureStage='ports'
    if($lifecycle.evidence.port_release_verified-ne$true){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|ports')}
    $aggregate=Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W14 -ContractPath $ContractPath
    $aggregate|ConvertTo-Json -Depth 10 -Compress
    if($aggregate.result-ne'PASS'){exit 2}
}catch{
    $code=$(if($Mode-eq'Prepare'){'ENV1B3_FINAL_IDENTITY_PREPARE_FAILED'}else{'ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED'})
    if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    $errorPayload=[ordered]@{schema_version='env-1b3-w14-error-v1';result='FAIL';code=$code;phase=$Mode;failure_stage=$failureStage;exit_code=2}
    if($null-ne$comparisonEvidence){$errorPayload.comparison=$comparisonEvidence}
    $errorPayload|ConvertTo-Json -Depth 8 -Compress;exit 2
}
