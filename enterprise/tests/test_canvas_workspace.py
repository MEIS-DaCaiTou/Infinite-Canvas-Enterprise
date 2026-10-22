"""Real SQLite directory boundaries and upgrade/restore; no paid requests."""
import json
import shutil
import sqlite3
from contextlib import closing

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from enterprise.canvas_workspace import CanvasWorkspace
from enterprise.department_governance import GovernanceError, DepartmentGovernance
from enterprise.department_api import create_router
from enterprise.migrations.canvas_workspace import candidate_registry
from enterprise.migrations.versioned import (apply_versioned_migrations, inspect_schema_metadata,
    schema_snapshot_sha256, restore_database_backup, MigrationStep, DataMigrationError)
from enterprise.tests.test_department_governance import business, baseline


def migrate_workspace(path, root, registry=None):
    registry = registry or candidate_registry()
    probe = root/'workspace-probe.db'
    shutil.copyfile(path, probe)
    with closing(sqlite3.connect(probe)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        current = inspect_schema_metadata(path)['schema_version']
        for step in candidate_registry():
            if step.to_version > current:
                step.apply_in_transaction(conn)
        target = schema_snapshot_sha256(conn)
        conn.rollback()
    return apply_versioned_migrations(path, root/'workspace-backups', operation_id='workspace-candidate',
        target_version=4, expected_target_schema_sha256=target, registry=registry)


def seed_workspace(service, people, department, root):
    project = service.create_project(people['employee'], department, '秋冬新品')['id']
    folders = [{'id':'old-root','name':'原有个人目录'},{'id':'down','name':'羽绒服'},{'id':'style-a','name':'款号A102'},
               {'id':'private-ops','name':'运营私人草稿'}]
    root.mkdir(exist_ok=True);(root/'canvases').mkdir(exist_ok=True)
    (root/'projects.json').write_text(json.dumps({'projects':folders}),encoding='utf8')
    with service.connect() as conn:
        for folder in folders:
            owner = 'outsider' if folder['id']=='private-ops' else 'employee'
            conn.execute('INSERT INTO user_project_map VALUES (?,?,NULL,?,?)',(owner,folder['id'],'private',1))
        for canvas,folder,owner in [('personal','old-root','employee'),('video','style-a','employee'),('smart','down','employee'),('ops-private','private-ops','outsider')]:
            conn.execute('INSERT INTO user_canvas_map VALUES (?,?,?)',(owner,canvas,1))
            (root/'canvases'/(canvas+'.json')).write_text(json.dumps({'id':canvas,'title':canvas,'project':folder,
                'kind':'smart' if canvas=='smart' else 'classic','nodes':[{'type':'prompt','text':'private input'}],
                'updated_at':10,'created_at':1}),encoding='utf8')
    workspace=CanvasWorkspace(service,root)
    workspace.update_folder(people['employee'],'down',business_project_id=project)
    workspace.update_folder(people['employee'],'style-a',parent_id='down',business_project_id=project)
    return workspace,project


def test_upgrade_from_v2_restore_and_no_implicit_adoption(tmp_path):
    path=baseline(tmp_path/'old.db');before=inspect_schema_metadata(path)
    service=DepartmentGovernance(connect=lambda:sqlite3.connect(path))
    assert not CanvasWorkspace(service,tmp_path).context({'user_id':'admin','auth_version':1})['enabled']
    assert inspect_schema_metadata(path)==before
    result=migrate_workspace(path,tmp_path)
    assert inspect_schema_metadata(path)['schema_version']==4
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('SELECT count(*) FROM canvas_workspace_projects').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM users').fetchone()[0]==5
    restore_database_backup(path,result.backup.manifest_path,
        expected_current_database_sha256=result.post_migration_database_sha256,
        expected_backup_manifest_sha256=result.backup.manifest_sha256)
    assert inspect_schema_metadata(path)==before


def test_migration_failure_restores_source(tmp_path):
    path=baseline(tmp_path/'old.db');before=inspect_schema_metadata(path);registry=candidate_registry()
    def fail(conn):
        registry[-1].apply_in_transaction(conn)
        raise RuntimeError('controlled interruption')
    step=registry[-1]
    broken=(*registry[:-1],MigrationStep(step.migration_id,3,4,step.checksum_sha256,fail,step.validate_in_transaction))
    with pytest.raises(DataMigrationError):migrate_workspace(path,tmp_path,broken)
    assert inspect_schema_metadata(path)==before


def test_update_center_plans_staged_v2_to_v4_without_writing_source(tmp_path):
    from enterprise.tests.test_update_mvp_1 import _Manifest
    from enterprise.ops.update.mvp import _database_update_plan
    from enterprise.migrations.versioned import migration_registry_sha256
    path=baseline(tmp_path/'old.db');before=inspect_schema_metadata(path);registry=candidate_registry()
    probe=tmp_path/'target.db';shutil.copyfile(path,probe)
    with closing(sqlite3.connect(probe)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        for step in registry:
            if step.to_version>2:step.apply_in_transaction(conn)
        target_hash=schema_snapshot_sha256(conn);conn.rollback()
    common={'migration_registry_sha256':migration_registry_sha256(registry),
            'versioned_migration_ids':[step.migration_id for step in registry]}
    source_root,target_root=tmp_path/'source',tmp_path/'target'
    for root,evidence in [(source_root,{**common,'schema_version':2,'schema_objects_sha256':before['schema_sha256']}),
                          (target_root,{**common,'schema_version':4,'schema_objects_sha256':target_hash})]:
        (root/'release-evidence').mkdir(parents=True)
        (root/'release-evidence/database-schema.json').write_text(json.dumps(evidence),encoding='utf8')
    plan=_database_update_plan(source_root=source_root,target_root=target_root,
        source_manifest=_Manifest('release-A','1'*64,True),target_manifest=_Manifest('release-B','2'*64,True),
        database_path=path,registry=registry,operation_id='workspace-plan')
    assert plan['migration_ids']==['ice_department_costs_v3','ice_canvas_workspace_v4']
    assert inspect_schema_metadata(path)==before


def test_scopes_tree_members_archive_and_owner_change(business,tmp_path):
    service,p,design,ops,path=business;migrate_workspace(path,tmp_path)
    root=tmp_path/'data';workspace,project=seed_workspace(service,p,design,root)
    personal=workspace.listing(p['employee'])
    assert {c['id'] for c in personal['canvases']}=={'personal','video','smart'}
    assert next(f for f in personal['folders'] if f['id']=='style-a')['parent_id']=='down'
    department=workspace.listing(p['design'],scope='department')
    assert {c['id'] for c in department['canvases']}=={'video','smart'}
    assert department['can_filter_members'] and not any(c['can_edit'] for c in department['canvases'])
    assert 'private input' not in json.dumps(department) and 'personal' not in {c['id'] for c in department['canvases']}
    assert workspace.listing(p['outsider'],scope='company')['canvases']==[]
    with pytest.raises(GovernanceError):workspace.listing(p['outsider'],scope='department',department_id=design)
    with pytest.raises(GovernanceError):workspace.listing(p['employee'],member_id='outsider')
    assert {c['id'] for c in workspace.listing(p['admin'],scope='company',member_id='outsider')['canvases']}=={'ops-private'}
    service.share_project(p['employee'],project,'company_readonly')
    shared=workspace.listing(p['outsider'],scope='company')
    assert {c['id'] for c in shared['canvases']}=={'video','smart'}
    assert not any(c['can_edit'] or c['thumbnail_url'] for c in shared['canvases'])
    with pytest.raises(GovernanceError):workspace.archive(p['outsider'],['video'],True)
    with pytest.raises(GovernanceError):workspace.update_folder(p['outsider'],'style-a',archived=True)
    with pytest.raises(GovernanceError,match='CYCLE'):workspace.update_folder(p['employee'],'down',parent_id='style-a',business_project_id=project)
    before=(root/'canvases/video.json').read_bytes()
    workspace.archive(p['employee'],['video'],True)
    assert (root/'canvases/video.json').read_bytes()==before
    assert next(c for c in workspace.listing(p['employee'])['canvases'] if c['id']=='video')['archived']
    workspace.archive(p['employee'],['video'],False)
    workspace.update_folder(p['employee'],'down',business_project_id=project,archived=True)
    assert all(c['archived'] for c in workspace.listing(p['employee'])['canvases'] if c['id'] in {'video','smart'})
    workspace.update_folder(p['employee'],'down',business_project_id=project,archived=False)
    # Reassigned ownership must not inherit an old owner's archive/grants.
    workspace.archive(p['employee'],['video'],True)
    with service.connect() as conn:conn.execute("UPDATE user_canvas_map SET user_id='outsider' WHERE canvas_id='video'")
    reassigned=workspace.listing(p['outsider'])['canvases']
    assert not next(c for c in reassigned if c['id']=='video')['archived']
    assert 'video' not in {c['id'] for c in workspace.listing(p['design'],scope='department')['canvases']}


def test_http_rejects_forged_owner_and_old_schema_stays_inactive(business,tmp_path):
    service,p,design,_,path=business
    app=FastAPI()
    @app.middleware('http')
    async def identity(request:Request,next):
        request.state.user=p.get(request.headers.get('x-fixture-user'));return await next(request)
    app.include_router(create_router(service),prefix='/enterprise')
    with TestClient(app) as client:
        assert client.get('/enterprise/api/business/workspace/context').status_code==401
        before=inspect_schema_metadata(path)
        assert not client.get('/enterprise/api/business/workspace/context',headers={'x-fixture-user':'employee'}).json()['enabled']
        assert inspect_schema_metadata(path)==before
        migrate_workspace(path,tmp_path)
        assert client.get('/enterprise/api/business/workspace/context',headers={'x-fixture-user':'employee'}).json()['enabled']
        response=client.put('/enterprise/api/business/workspace/archive',headers={'x-fixture-user':'employee'},
            json={'canvas_ids':['foreign'],'archived':True,'owner_id':'admin'})
        assert response.status_code==400


def test_original_routes_enforce_project_write_after_demotion(business,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from enterprise import db, interceptors, canvas_workspace
    service,p,design,_,path=business;migrate_workspace(path,tmp_path)
    root=tmp_path/'data';workspace,_=seed_workspace(service,p,design,root)
    managed=service.create_project(p['design'],design,'负责人项目')['id']
    service.grant_project(p['design'],managed,'employee',True)
    workspace.update_folder(p['employee'],'down',business_project_id=managed)
    service.grant_project(p['design'],managed,'employee',False)
    def connect():
        connection=service.connect();connection.row_factory=sqlite3.Row;return connection
    monkeypatch.setattr(db,'get_db',connect)
    monkeypatch.setattr(db,'CANVAS_DATA_DIR',str(root/'canvases'))
    monkeypatch.setattr(canvas_workspace,'PATH_ROOTS',SimpleNamespace(DATA_ROOT=root))
    monkeypatch.setattr(db,'can_use_feature',lambda *args,**kwargs:True)
    for route,body in [('api/canvases',{'project':'down'}),
                       ('api/canvases/personal/meta',{'project':'down'}),
                       ('api/canvases/video/meta',{'project':'old-root'}),
                       ('api/canvases/video/meta',{'project':'default'}),
                       ('api/canvases/video/meta',{'project':''}),
                       ('api/canvases/video/meta',{'project':' \t '})]:
        denial=interceptors._pre_process_sync(route,'POST',p['employee'],body=json.dumps(body).encode())
        assert denial.status_code==403
    # Editing the original canvas without changing its folder remains an owner operation.
    assert interceptors._pre_process_sync('api/canvases/video/meta','POST',p['employee'],
        body=json.dumps({'project':'style-a','title':'本人仍可编辑'}).encode()) is None
    assert interceptors._pre_process_sync('api/canvases/video/meta','POST',p['employee'],
        body=json.dumps({'project':None,'title':'保持原目录'}).encode()) is None
    # Original create always assigns the current user, so reject an admin's mismatching target.
    admin={**p['admin'],'is_admin':True}
    denial=interceptors._pre_process_sync('api/canvases','POST',admin,body=b'{"project":"down"}')
    assert denial.status_code==403 and b'WORKSPACE_CREATE_IN_OWN_FOLDER' in denial.body


def test_metadata_move_reads_latest_canvas_inside_existing_lock(tmp_path):
    import ast
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from types import SimpleNamespace
    source=Path(__file__).resolve().parents[2]/'main.py'
    function=next(n for n in ast.parse(source.read_text(encoding='utf8')).body
                  if isinstance(n,ast.AsyncFunctionDef) and n.name=='update_canvas_meta')
    function.decorator_list=[]
    module=ast.Module(body=[function],type_ignores=[])
    path=tmp_path/'canvas.json'
    path.write_text(json.dumps({'id':'canvas','project':'old','nodes':['initial'],'updated_at':1}))
    raw_lock=threading.Lock();entering=threading.Event()
    class ExistingLock:
        def __enter__(self):entering.set();raw_lock.acquire()
        def __exit__(self,*args):raw_lock.release()
    namespace={'CanvasMetaUpdate':object,'CANVAS_LOCK':ExistingLock(),
        'load_canvas':lambda _:json.loads(path.read_text()),'canvas_path':lambda _:path,
        'json':json,'canvas_record':lambda value:value}
    exec(compile(module,str(source),'exec'),namespace)
    payload=SimpleNamespace(title=None,icon=None,owner=None,color=None,pinned=None,project='new',board_x=None,board_y=None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        raw_lock.acquire()
        future=pool.submit(lambda:asyncio.run(namespace['update_canvas_meta']('canvas',payload)))
        assert entering.wait(3)
        path.write_text(json.dumps({'id':'canvas','project':'old','nodes':['latest saved work'],'updated_at':2}))
        raw_lock.release()
        result=future.result(timeout=3)['canvas']
    assert result['project']=='new' and result['nodes']==['latest saved work'] and result['updated_at']==2
