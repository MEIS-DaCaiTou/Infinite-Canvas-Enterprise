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
Import-Module (Join-Path $PSScriptRoot 'ENV1B3.Validation.psm1') -Force
$statePath=Join-Path $EvidenceRoot 'W14-PREPARE.json'
try{
    [void](Assert-ENV1B3AbsoluteSafePath $HandoffRoot);[void](Assert-ENV1B3AbsoluteSafePath $TestRoot -AllowMissingLeaf);[void](Assert-ENV1B3AbsoluteSafePath $EvidenceRoot -AllowMissingLeaf)
    [IO.Directory]::CreateDirectory($EvidenceRoot)|Out-Null
    $handoff=Read-ENV1B3Json (Join-Path $HandoffRoot 'CANDIDATE-HANDOFF.json')
    $appRoot=Join-Path $TestRoot ('install\releases\'+[string]$handoff.release_id)
    if($Mode-eq'Prepare'){
        $artifact=Test-ENV1B3Handoff -HandoffRoot $HandoffRoot
        & (Join-Path $PSScriptRoot 'Invoke-Materialization.ps1') -HandoffRoot $HandoffRoot -TestRoot $TestRoot -EvidenceRoot (Join-Path $EvidenceRoot 'prepare-materialization') -CaseId W02 -DiagnosticProbeManifestPath $DiagnosticProbeManifestPath
        if(-not$?){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_PREPARE_FAILED|materialization')}
        $tree=Get-ENV1B3DirectoryTree $appRoot
        $pointer=Join-Path $TestRoot 'install\state\current-release.json'
        $state=[ordered]@{schema_version='env-1b3-w14-prepare-v1';candidate_id=[string]$handoff.candidate_id;release_id=[string]$handoff.release_id;app_root=$appRoot;app_root_tree=$tree;pointer_sha256=(Get-ENV1B3Sha256 $pointer);payload_tree_sha256=[string]$artifact.artifact.payload_tree_sha256;next_action='set app root read-only for the application user, then run W14Validate'}
        [IO.File]::WriteAllText($statePath,($state|ConvertTo-Json -Depth 8 -Compress)+"`n",[Text.UTF8Encoding]::new($false))
        Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W14 -SubcheckId prepare -Result PASS -Code ENV1B3_FINAL_IDENTITY_PREPARE_PASS -Evidence @{candidate_id=$state.candidate_id;release_id=$state.release_id;app_root_tree_sha256=$tree.tree_sha256;pointer_sha256=$state.pointer_sha256;lifecycle_executed=$false}|ConvertTo-Json -Depth 8 -Compress
        exit 0
    }
    $state=Read-ENV1B3Json $statePath
    if($state.schema_version-ne'env-1b3-w14-prepare-v1'-or$state.candidate_id-ne[string]$handoff.candidate_id-or$state.app_root-ne$appRoot-or$state.pointer_sha256-ne(Get-ENV1B3Sha256 (Join-Path $TestRoot 'install\state\current-release.json'))){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|state')}
    $treeBefore=Get-ENV1B3DirectoryTree $appRoot
    if($treeBefore.tree_sha256-ne$state.app_root_tree.tree_sha256){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|tree')}
    $permissionEvidence=Join-Path $EvidenceRoot ('w14-permission-'+[Guid]::NewGuid().ToString('N'))
    try{
        & (Join-Path $PSScriptRoot 'Invoke-PermissionMatrix.ps1') -AppRoot $appRoot -EvidenceRoot $permissionEvidence -Mode VerifyReadOnly
        if(-not$?){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|readonly')}
        $permission=Read-ENV1B3Json (Join-Path $permissionEvidence 'W06.json')
    }finally{if(Test-Path -LiteralPath $permissionEvidence){Remove-Item -LiteralPath $permissionEvidence -Recurse -Force}}
    Write-ENV1B3SubcheckResult -EvidenceRoot $EvidenceRoot -CaseId W14 -SubcheckId readonly_app_root -Result PASS -Code ENV1B3_FINAL_IDENTITY_READONLY_PASS -Evidence @{app_root_write_denied=[bool]$permission.evidence.app_root_write_denied}|Out-Null
    $installRoot=Join-Path $TestRoot 'install';$externalRoots=@('config','data','logs','backups','state','staging')|ForEach-Object{Join-Path $installRoot $_}
    $pathRootsExternal=@($externalRoots|Where-Object{[IO.Path]::GetFullPath($_).StartsWith(([IO.Path]::GetFullPath($appRoot)+'\'),[StringComparison]::OrdinalIgnoreCase)}).Count-eq0
    if(-not$pathRootsExternal){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|path_roots')}
    & (Join-Path $PSScriptRoot 'Invoke-LifecycleMatrix.ps1') -AppRoot $appRoot -EvidenceRoot $EvidenceRoot -CaseId W14 -DifferentCwd ([IO.Path]::GetPathRoot($TestRoot)) -PolluteEnvironment -RequireOffline -RequireExternalPathRoots -SubcheckId offline_non_admin_lifecycle
    if(-not$?){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|lifecycle')}
    $lifecycle=Read-ENV1B3Json (Join-Path $EvidenceRoot 'subchecks\W14\offline_non_admin_lifecycle.json')
    if(-not$pathRootsExternal-or$lifecycle.evidence.path_roots_external-ne$true-or$lifecycle.evidence.fixed_python_all_roles-ne$true-or$lifecycle.evidence.app_root_tree_unchanged-ne$true){throw[InvalidOperationException]::new('ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED|identity')}
    $aggregate=Complete-ENV1B3CaseResult -EvidenceRoot $EvidenceRoot -CaseId W14 -ContractPath $ContractPath
    $aggregate|ConvertTo-Json -Depth 10 -Compress
    if($aggregate.result-ne'PASS'){exit 2}
}catch{
    $code=$(if($Mode-eq'Prepare'){'ENV1B3_FINAL_IDENTITY_PREPARE_FAILED'}else{'ENV1B3_FINAL_IDENTITY_VALIDATE_FAILED'})
    if($_.Exception.Message-match'^([A-Z0-9_]+)\|'){$code=$Matches[1]}
    [ordered]@{schema_version='env-1b3-w14-error-v1';result='FAIL';code=$code;phase=$Mode;exit_code=2}|ConvertTo-Json -Compress;exit 2
}
