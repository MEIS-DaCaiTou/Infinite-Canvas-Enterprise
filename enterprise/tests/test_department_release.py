"""Department release staging, verified fresh activation and real SQLite recovery."""
import hashlib
from contextlib import closing
import json
import sqlite3
from pathlib import Path

import pytest

from enterprise.migrations.canvas_workspace import release_registry
from enterprise.migrations.versioned import DEFAULT_MIGRATIONS, inspect_schema_metadata, migration_registry_sha256
from enterprise.ops.update.mvp import _database_update_plan, execute_update_job, UpdateMvpError
from enterprise.release.release_builder_v2 import _versioned_database_snapshot
from enterprise.tests.test_department_governance import baseline
from enterprise.tests.test_update_mvp_1 import _execution_fixture


@pytest.fixture(scope='module')
def snapshots(tmp_path_factory):
    root=tmp_path_factory.mktemp('department-release')
    repo=Path(__file__).resolve().parents[2]
    return {v:json.loads(_versioned_database_snapshot(repo,root/('v'+str(v)+'.json'),schema_version=v)) for v in (2,4)}


class Manifest:
    def __init__(self,evidence,forward=False):
        self.evidence=evidence;self.forward=forward
    def section(self,name):
        assert name=='database_contract'
        return {'schema_id':self.evidence['schema_id'],'migration_ids':self.evidence['migration_ids'],
                'ops3b_activation_eligible':True,
                'migration_compatibility':'versioned-forward-migration' if self.forward else 'same-schema-no-migration',
                'rollback_classification':'database-backup-restore' if self.forward else 'code-release-pointer',
                'schema_snapshot_path':'release-evidence/database-schema.json',
                'schema_snapshot_sha256':hashlib.sha256(json.dumps(self.evidence).encode()).hexdigest()}


def plan(root,database,source,target,*,forward=False,registry=None):
    for name,value in [('source',source),('target',target)]:
        path=root/name/'release-evidence/database-schema.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf8')
    return _database_update_plan(source_root=root/'source',target_root=root/'target',
        source_manifest=Manifest(source,forward),target_manifest=Manifest(target,forward),
        database_path=database,registry=release_registry() if registry is None else registry,operation_id='department-release')


def test_staging_keeps_v2_and_requires_pre_staged_registry_for_activation(tmp_path,snapshots):
    database=baseline(tmp_path/'enterprise.db');original=database.read_bytes()
    old={**snapshots[2],'migration_registry_sha256':migration_registry_sha256(DEFAULT_MIGRATIONS),
         'versioned_migration_ids':[s.migration_id for s in DEFAULT_MIGRATIONS]}
    # Both the immutable old controller and the new controller can stage the
    # same v2 package; neither creates department tables or changes old data.
    for registry in (DEFAULT_MIGRATIONS,release_registry()):
        assert plan(tmp_path,database,old,snapshots[2],registry=registry)['registry_staged']
    assert database.read_bytes()==original
    with pytest.raises(UpdateMvpError,match='SYSTEM_UPDATE_DATABASE_SOURCE_IDENTITY_MISMATCH'):
        plan(tmp_path,database,old,snapshots[4],forward=True)
    ready=plan(tmp_path,database,snapshots[2],snapshots[4],forward=True)
    assert ready['migration_ids']==['ice_department_costs_v3','ice_canvas_workspace_v4']
    assert ready['source_schema_version']==2 and ready['target_schema_version']==4
    assert database.read_bytes()==original
    corrupt={**snapshots[2],'migration_registry_sha256':'0'*64}
    with pytest.raises(UpdateMvpError,match='SYSTEM_UPDATE_DATABASE_SOURCE_IDENTITY_MISMATCH'):
        plan(tmp_path,database,corrupt,snapshots[4],forward=True)


@pytest.mark.parametrize('version',[2,4])
def test_verified_fresh_install_uses_declared_schema_without_implicit_adoption(tmp_path,monkeypatch,snapshots,version):
    from enterprise.tests import test_install_mvp_1 as fixture
    from enterprise.department_governance import DepartmentGovernance
    monkeypatch.setattr(fixture._Manifest,'schema_version',version)
    monkeypatch.setattr(fixture,'_fixture_schema_bytes',lambda:json.dumps(snapshots[version]).encode())
    original_section=fixture._Manifest.section
    def section(self,name):
        result=original_section(self,name)
        if name=='database_contract':result['migration_ids']=snapshots[version]['migration_ids']
        return result
    monkeypatch.setattr(fixture._Manifest,'section',section)
    result,roots=fixture._install(monkeypatch,tmp_path)
    database=roots.DATA_ROOT/'enterprise.db'
    assert inspect_schema_metadata(database)['schema_version']==version
    assert result.pointer_published and result.active_super_admin_count==1
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT count(*) FROM users').fetchone()[0]==1
        if version==4:assert conn.execute('SELECT count(*) FROM departments').fetchone()[0]==0
    service=DepartmentGovernance(connect=lambda:sqlite3.connect(database))
    principal={'user_id':result.first_user_id,'auth_version':1,'role':'super_admin','is_admin':True}
    assert service.workspace(principal)['enabled']==(version==4)
    if version==4:assert service.create_department(principal,'设计部')['name']=='设计部'


@pytest.mark.parametrize('target_health_exit',[0,2])
def test_shared_updater_activates_v4_or_restores_v2_before_source_restart(tmp_path,monkeypatch,snapshots,target_health_exit):
    database=baseline(tmp_path/'original.db')
    with closing(sqlite3.connect(database)) as conn:users=conn.execute('SELECT * FROM users ORDER BY id').fetchall()
    ready=plan(tmp_path,database,snapshots[2],snapshots[4],forward=True)
    roots,store,job,pointer,calls,launcher=_execution_fixture(tmp_path,monkeypatch,
        target_health_exit=target_health_exit,database_update=ready,migration_target=True)
    # Launcher/pointer are controlled; actual DDL, backup, restore and durable
    # result handling are the same implementation used by the installed worker.
    assert execute_update_job(roots,job,database_path=database,launcher=launcher)==target_health_exit
    inspection=inspect_schema_metadata(database)
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT * FROM users ORDER BY id').fetchall()==users
    if target_health_exit:
        assert inspection['schema_version']==2 and pointer.release.release_id=='release-A'
        assert store.read_status(job)['state']=='ROLLED_BACK'
        assert store.read_status(job)['database_restored'] is True
        assert calls[-2:]==[('release-A','start'),('release-A','health')]
    else:
        assert inspection['schema_version']==4 and pointer.release.release_id=='release-B'
        assert store.read_status(job)['state']=='SUCCEEDED'


def test_new_controller_executes_an_older_exact_forward_registry(tmp_path,monkeypatch,snapshots):
    from enterprise import db
    from enterprise.migrations.versioned import initialize_schema_metadata_in_transaction
    database=tmp_path/'original.db'
    with closing(sqlite3.connect(database)) as conn:
        db.ensure_db_schema_in_connection(conn)
        conn.execute('BEGIN IMMEDIATE');initialize_schema_metadata_in_transaction(conn);conn.commit()
    source=inspect_schema_metadata(database)
    target={**snapshots[2],'migration_registry_sha256':migration_registry_sha256(DEFAULT_MIGRATIONS),
            'versioned_migration_ids':[s.migration_id for s in DEFAULT_MIGRATIONS]}
    original={**target,'schema_version':1,'schema_objects_sha256':source['schema_sha256']}
    ready=plan(tmp_path,database,original,target,forward=True)
    assert ready['migration_ids']==['ice_096_security_schema_v2']
    roots,store,job,_,_,launcher=_execution_fixture(tmp_path,monkeypatch,database_update=ready,migration_target=True)
    assert execute_update_job(roots,job,database_path=database,launcher=launcher)==0
    assert store.read_status(job)['state']=='SUCCEEDED'
    assert inspect_schema_metadata(database)['schema_version']==2
