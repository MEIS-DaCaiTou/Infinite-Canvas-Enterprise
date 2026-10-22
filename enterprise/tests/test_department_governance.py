"""Isolated, actual SQLite/DPAPI tests; no customer data or paid requests."""
import json
import os
import shutil
import sqlite3
import time
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from enterprise import db
from enterprise.department_governance import DepartmentGovernance, GovernanceError
from enterprise.department_costs import DepartmentCosts
from enterprise.credential_vault import WindowsCredentialVault, VaultUnavailable
from enterprise.department_api import create_router
from enterprise.migrations.department_costs import candidate_registry
from enterprise.migrations.versioned import (
    DEFAULT_MIGRATIONS, _apply_steps_in_transaction, apply_versioned_migrations,
    initialize_schema_metadata_in_transaction, schema_snapshot_sha256,
    inspect_schema_metadata, restore_database_backup, MigrationStep, DataMigrationError, migration_registry_sha256,
)


def baseline(path):
    with closing(sqlite3.connect(path)) as conn:
        db.ensure_db_schema_in_connection(conn)
        conn.execute('BEGIN IMMEDIATE')
        initialize_schema_metadata_in_transaction(conn)
        _apply_steps_in_transaction(conn, DEFAULT_MIGRATIONS)
        for name, role in [('admin','super_admin'),('design','user'),('ops','user'),('employee','user'),('outsider','user')]:
            conn.execute('INSERT INTO users(id,username,password_hash,display_name,role,is_admin,created_at) '
                         'VALUES (?,?,?,?,?,?,?)', (name,name,'fixture-hash',name,role,role!='user',1))
        conn.commit()
    return path


def migrate(path, root, registry=None):
    registry = registry or candidate_registry()
    probe = root / 'probe.db'
    shutil.copyfile(path, probe)
    with closing(sqlite3.connect(probe)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        candidate_registry()[-1].apply_in_transaction(conn)
        target = schema_snapshot_sha256(conn)
        conn.rollback()
    return apply_versioned_migrations(path, root/'backups', operation_id='business-candidate',
        target_version=3, expected_target_schema_sha256=target, registry=registry)


@pytest.fixture
def business(tmp_path):
    if os.name != 'nt':
        pytest.skip('DPAPI credentials require Windows; migration tests are platform independent')
    path = baseline(tmp_path/'enterprise.db')
    migrate(path, tmp_path)
    service = DepartmentGovernance(connect=lambda:sqlite3.connect(path))
    people = {name:{'user_id':name,'auth_version':1} for name in ['admin','design','ops','employee','outsider']}
    design = service.create_department(people['admin'], '设计部')['id']
    ops = service.create_department(people['admin'], '运营部')['id']
    for name, dept, manager in [('design',design,True),('employee',design,False),('ops',ops,True),('outsider',ops,False)]:
        service.assign_member(people['admin'], dept, name, manager)
    return service, people, design, ops, path


def source(service, people, department=None, procurement='company', name='company', account='account-company'):
    result = service.create_source(people['admin'], provider_id='comfly', name=name,
        scope='department' if department else 'company', department_id=department,
        procurement=procurement, account_ref=account, secret='fixture-secret-'+name)
    service.grant_source(people['admin'], result['id'], 'employee', True)
    return result


def context(service, people, task='task-one', source_id=None, project=None):
    return service.accept_context(people['employee'], task_id=task, provider_id='comfly',
                                   model='gpt-image-2', source_id=source_id, project_id=project)


def test_single_department_and_no_manager_privilege_escalation(business):
    service, p, design, ops, path = business
    assert len(service.departments(p['employee'])) == 1
    with pytest.raises(GovernanceError):
        service.assign_member(p['design'], design, 'outsider')
    with pytest.raises(GovernanceError):
        service.assign_member(p['design'], design, 'employee', True)
    service.assign_member(p['admin'], ops, 'employee')
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM department_members WHERE user_id='employee'").fetchone()[0] == 1
    with pytest.raises(GovernanceError):
        service.members(p['design'], ops)


def test_private_project_and_explicit_readonly_never_authorizes_generation(business):
    service, p, design, ops, path = business
    project = service.create_project(p['employee'], design, '秋季新品')['id']
    assert service.projects(p['outsider']) == []
    service.share_project(p['employee'], project, 'company_readonly')
    assert service.projects(p['outsider'])[0]['can_write'] is False
    with pytest.raises(GovernanceError):
        service.share_project(p['outsider'], project, 'private')
    key = source(service, p)
    service.grant_source(p['admin'], key['id'], 'outsider', True)
    with pytest.raises(GovernanceError):
        service.accept_context(p['outsider'], task_id='forbidden', provider_id='comfly',model='m',project_id=project)
    assert context(service, p, project=project)['project_id'] == project


def test_department_preference_explicit_company_and_immutable_identity(business):
    service, p, design, ops, path = business
    company = source(service, p)
    department = source(service, p, design, 'company', 'design')
    first = context(service, p)
    assert first['source_id'] == department['id']
    assert first['procurement'] == 'company' and first['scope'] == 'department'
    assert context(service, p, 'company-task', company['id'])['source_id'] == company['id']
    assert service.sources(p['outsider']) == []
    assert 'sealed_secret' not in json.dumps(service.sources(p['employee']))
    service.rotate_source(p['design'], department['id'], department['revision'], 'fixture-rotated')
    assert service.bound_secret('task-one') == 'fixture-secret-design'
    service.assign_member(p['admin'], ops, 'employee')
    assert context(service, p)['department_id'] == design
    assert context(service, p, 'new-after-transfer')['source_id'] == company['id']
    service.enable_source(p['admin'], company['id'], False)
    assert service.bound_secret('company-task') == 'fixture-secret-company'
    with pytest.raises(GovernanceError, match='NO_AUTHORIZED_CALL_SOURCE'):
        context(service, p, 'must-not-fallback')


def test_credential_permissions_rotation_cas_and_no_plaintext(business):
    service, p, design, ops, path = business
    key = source(service, p, design, 'department', 'design-own', 'account-design')
    with pytest.raises(GovernanceError):
        service.rotate_source(p['ops'], key['id'], key['revision'], 'fixture-wrong')
    new = service.rotate_source(p['design'], key['id'], key['revision'], 'fixture-new')
    with pytest.raises(GovernanceError, match='CREDENTIAL_REVISION_CONFLICT'):
        service.rotate_source(p['design'], key['id'], key['revision'], 'fixture-race')
    context(service, p)
    assert service.bound_secret('task-one') == 'fixture-new'
    assert new['revision'] != key['revision']
    assert b'fixture-secret' not in path.read_bytes() and b'fixture-new' not in path.read_bytes()
    assert 'fixture' not in json.dumps(service.sources(p['design'],manage=True))


def test_stale_session_and_disabled_users_cannot_use_or_manage_sources(business):
    service,p,design,ops,path = business
    source(service,p)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE users SET auth_version=2 WHERE id='employee'")
    with pytest.raises(GovernanceError, match='STALE_AUTHENTICATION'):
        service.sources(p['employee'])
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE users SET is_active=0 WHERE id='design'")
    with pytest.raises(GovernanceError, match='STALE_AUTHENTICATION'):
        service.members(p['design'],design)


def test_mandatory_audit_failure_rolls_back_business_write(business):
    service,p,design,ops,path = business
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER fail_business_audit BEFORE INSERT ON security_audit_events "
                     "BEGIN SELECT RAISE(ABORT,'fixture audit unavailable'); END")
    with pytest.raises(GovernanceError, match='DEPARTMENT_STORAGE_UNAVAILABLE'):
        service.create_department(p['admin'],'must rollback')
    assert len(service.departments(p['admin'])) == 2


def test_receipt_idempotency_units_refunds_unknown_and_nonblocking_budget(business):
    service,p,design,ops,path = business
    source(service,p)
    context(service,p)
    costs = DepartmentCosts(service)
    event = costs.record_fact('task-one',0,'unknown',kind='unknown')
    assert costs.summary(p['employee'])['pending_reconciliation'] == 1
    actual = costs.record_fact('task-one',0,'charged',kind='charge',amount='1.25',unit='platform_units')
    assert costs.record_fact('task-one',0,'charged',kind='charge',amount='1.25',unit='platform_units') == actual
    with pytest.raises(GovernanceError, match='COST_RECEIPT_CONFLICT'):
        costs.record_fact('task-one',0,'charged',kind='charge',amount='2',unit='platform_units')
    costs.record_fact('task-one',0,'estimate',kind='estimate',amount='2',unit='platform_units')
    costs.record_fact('task-one',0,'refund',kind='refund',amount='0.25',unit='platform_units')
    costs.record_fact('task-one',0,'dollar',kind='charge',amount='0.1',unit='USD')
    summary = costs.summary(p['design'],scope='department')
    assert summary['pending_reconciliation'] == 0 and summary['budget_enforced'] is False
    assert {(g['unit'],g['actual'],g['estimated']) for g in summary['groups']} == {
        ('platform_units','1.00','2'),('USD','0.1','0')}
    now = int(time.time())
    costs.set_budget(p['design'],design,'本期',now-100,now+100,'platform_units','0.5')
    assert costs.budgets(p['design'],design)[0]['exceeded'] is True
    assert costs.budgets(p['design'],design)[0]['blocking'] is False
    assert context(service,p,'after-budget')['source_id']
    assert costs.summary(p['outsider'])['groups'] == []
    with pytest.raises(GovernanceError):
        costs.summary(p['ops'],scope='department',department_id=design)
    with pytest.raises(GovernanceError):
        costs.summary(p['employee'],scope='company')


def test_cost_history_keeps_department_after_transfer_and_company_procurement_separate(business):
    service,p,design,ops,path = business
    source(service,p,design,'department','self-buy','self-account')
    context(service,p)
    costs = DepartmentCosts(service)
    costs.record_fact('task-one',0,'receipt',kind='charge',amount='0.3',unit='CNY')
    service.assign_member(p['admin'],ops,'employee')
    group = costs.summary(p['admin'],scope='company')['groups'][0]
    assert group['department_id'] == design and group['procurement'] == 'department' and group['scope'] == 'department'
    assert costs.summary(p['ops'],scope='department')['groups'] == []
    assert costs.summary(p['employee'])['groups'][0]['department_id'] == design


def test_concurrent_receipt_ingestion_and_pagination(business):
    service,p,design,ops,path = business
    source(service,p)
    context(service,p)
    costs = DepartmentCosts(service)
    def write(_):
        return costs.record_fact('task-one',0,'receipt',kind='charge',amount='1',unit='USD')
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(set(pool.map(write,range(8)))) == 1
    for n in range(3):
        costs.record_fact('task-one',0,'refund-'+str(n),kind='refund',amount='0.1',unit='USD')
    page = costs.entries(p['employee'],limit=2)
    page2 = costs.entries(p['employee'],limit=2,before=page['next_cursor'])
    assert len({r['id'] for r in page['entries']+page2['entries']}) == 4


def test_api_does_not_accept_plaintext_reads_or_leak_rejected_input(business):
    service,p,design,ops,path = business
    app=FastAPI()
    @app.middleware('http')
    async def fixture_identity(request:Request, next):
        request.state.user=p.get(request.headers.get('x-fixture-user',''))
        return await next(request)
    app.include_router(create_router(service),prefix='/enterprise')
    client=TestClient(app)
    assert client.get('/enterprise/api/business/sources').status_code == 401
    response=client.post('/enterprise/api/business/sources',headers={'x-fixture-user':'admin'},json={'secret':'fixture-secret-echo'})
    assert response.status_code == 400 and 'fixture-secret-echo' not in response.text
    key=source(service,p)
    assert client.get('/enterprise/api/business/sources/'+key['id']+'/secret',headers={'x-fixture-user':'admin'}).status_code == 405
    assert client.get('/enterprise/api/business/costs/summary?scope=company',headers={'x-fixture-user':'employee'}).status_code == 403
    assert client.post('/enterprise/api/business/sources',headers={'x-fixture-user':'admin'},content=b'x'*32769).status_code == 413


def test_migration_is_explicit_preserves_old_users_and_can_restore(tmp_path):
    path=baseline(tmp_path/'enterprise.db')
    old=inspect_schema_metadata(path)
    service=DepartmentGovernance(connect=lambda:sqlite3.connect(path))
    with pytest.raises(GovernanceError,match='SCHEMA_UPGRADE_REQUIRED'):
        service.departments({'user_id':'admin','auth_version':1})
    assert inspect_schema_metadata(path)==old
    result=migrate(path,tmp_path)
    assert inspect_schema_metadata(path)['schema_version']==3
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('SELECT count(*) FROM users').fetchone()[0] == 5
        assert conn.execute('SELECT count(*) FROM department_members').fetchone()[0] == 0
    restore_database_backup(path,result.backup.manifest_path,
        expected_current_database_sha256=result.post_migration_database_sha256,
        expected_backup_manifest_sha256=result.backup.manifest_sha256)
    assert inspect_schema_metadata(path)['schema_version']==2


def test_dpapi_binding_and_tamper_protection():
    if os.name!='nt':
        pytest.skip('Windows DPAPI adapter')
    vault=WindowsCredentialVault()
    blob=vault.seal('fixture-only-not-real','source:revision')
    assert vault.open(blob,'source:revision')=='fixture-only-not-real'
    with pytest.raises(VaultUnavailable):
        vault.open(blob,'other:revision')
    with pytest.raises(VaultUnavailable):
        vault.open(blob[:-1]+bytes([blob[-1]^1]),'source:revision')


def test_update_center_plan_requires_staged_registry_and_does_not_write_database(tmp_path):
    from enterprise.tests.test_update_mvp_1 import _Manifest
    from enterprise.ops.update.mvp import _database_update_plan, UpdateMvpError
    path=baseline(tmp_path/'enterprise.db')
    registry=candidate_registry()
    probe=tmp_path/'probe.db'
    shutil.copyfile(path,probe)
    with closing(sqlite3.connect(probe)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        registry[-1].apply_in_transaction(conn)
        target_sha=schema_snapshot_sha256(conn)
        conn.rollback()
    source_root,target_root=tmp_path/'release-A',tmp_path/'release-B'
    source={'schema_version':2,'schema_objects_sha256':inspect_schema_metadata(path)['schema_sha256'],
            'migration_registry_sha256':migration_registry_sha256(registry),
            'versioned_migration_ids':[s.migration_id for s in registry]}
    target={**source,'schema_version':3,'schema_objects_sha256':target_sha}
    for root,evidence in [(source_root,source),(target_root,target)]:
        (root/'release-evidence').mkdir(parents=True)
        (root/'release-evidence'/'database-schema.json').write_text(json.dumps(evidence),encoding='utf8')
    params=dict(source_root=source_root,target_root=target_root,
        source_manifest=_Manifest('release-A','1'*64,True),target_manifest=_Manifest('release-B','2'*64,True),
        database_path=path,registry=registry,operation_id='candidate-v3')
    plan=_database_update_plan(**params)
    assert plan['source_schema_version']==2 and plan['target_schema_version']==3
    assert plan['migration_ids']==['ice_department_costs_v3']
    assert inspect_schema_metadata(path)['schema_version']==2
    # A released v2 source with only its original registry cannot skip staging.
    source.update(migration_registry_sha256=migration_registry_sha256(DEFAULT_MIGRATIONS),
                  versioned_migration_ids=[s.migration_id for s in DEFAULT_MIGRATIONS])
    (source_root/'release-evidence'/'database-schema.json').write_text(json.dumps(source),encoding='utf8')
    with pytest.raises(UpdateMvpError,match='SOURCE_IDENTITY_MISMATCH'):
        _database_update_plan(**params)


def test_business_migration_failure_rolls_back_and_preserves_source(tmp_path):
    path=baseline(tmp_path/'enterprise.db')
    source=inspect_schema_metadata(path)
    registry=candidate_registry()
    def fail(conn):
        registry[-1].apply_in_transaction(conn)
        raise RuntimeError('fixture interruption after DDL')
    broken=(*registry[:-1],MigrationStep(registry[-1].migration_id,2,3,registry[-1].checksum_sha256,
                                       fail,registry[-1].validate_in_transaction))
    with pytest.raises(DataMigrationError):
        migrate(path,tmp_path,broken)
    assert inspect_schema_metadata(path)==source
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='departments'").fetchone() is None
        assert conn.execute('SELECT count(*) FROM users').fetchone()[0]==5


def test_removal_revokes_new_department_calls_but_keeps_original_query(business):
    service,p,design,ops,path=business
    source(service,p,design,name='design')
    context(service,p)
    service.remove_member(p['design'],design,'employee')
    assert service.sources(p['employee'])==[]
    assert service.bound_secret('task-one')=='fixture-secret-design'
    with pytest.raises(GovernanceError):
        service.remove_member(p['design'],design,'design')


def test_frozen_billing_and_cost_facts_reject_in_place_changes(business):
    service,p,design,ops,path=business
    source(service,p)
    context(service,p)
    DepartmentCosts(service).record_fact('task-one',0,'charge',kind='charge',amount='0.1',unit='USD')
    with closing(sqlite3.connect(path)) as conn:
        for table in ['credential_revisions','generation_billing_context','generation_cost_entries']:
            with pytest.raises(sqlite3.IntegrityError,match='append-only'):
                conn.execute('DELETE FROM '+table)
            conn.rollback()


def test_cost_precision_is_preserved_across_sum_refund_and_budget(business):
    service,p,design,ops,path=business
    source(service,p)
    context(service,p)
    costs=DepartmentCosts(service)
    costs.record_fact('task-one',0,'charge',kind='charge',amount='999999999999999999.123456789123',unit='CNY')
    costs.record_fact('task-one',0,'refund',kind='refund',amount='0.000000000001',unit='CNY')
    assert costs.summary(p['employee'])['groups'][0]['actual']=='999999999999999999.123456789122'
    now=int(time.time())
    costs.set_budget(p['design'],design,'本期',now-5,now+100,'CNY','999999999999999999.123456789121')
    assert costs.budgets(p['design'],design)[0]['over_amount']=='1E-12'
