"""Call-source integration without upstream generation or real credentials."""
import asyncio
import json
import sqlite3
import time
from contextlib import closing

import pytest
from fastapi import HTTPException

from enterprise import db
from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.canvas_image_recovery import CanvasImageRecovery
from enterprise.department_costs import DepartmentCosts
from enterprise.tests.test_department_governance import business, source
import enterprise.task_credentials as binding

PROVIDER={'id':'comfly','name':'Zhenzhen','base_url':'https://ai.t8star.org/v1',
          'protocol':'openai','image_request_mode':'openai'}


@pytest.fixture
def bound(business,monkeypatch,tmp_path):
    service,p,design,ops,path=business
    def user(user_id):
        with closing(sqlite3.connect(path)) as conn:
            conn.row_factory=sqlite3.Row
            row=conn.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
            return dict(row) if row else None
    monkeypatch.setattr(db,'get_user_by_id',user)
    monkeypatch.setattr(binding,'DepartmentGovernance',lambda:service)
    company=source(service,p)
    department=source(service,p,design,name='design')
    journal=CanvasTaskJournal(tmp_path/'canvas-tasks')
    def create(task_id='bound-task',source_id=None,attempts=1):
        record={'id':task_id,'type':'online-image','enterprise_user_id':'employee','provider_id':'comfly',
                'model':'gpt-image-2','status':'queued','created_at':time.time(),
                'expected_attempts':attempts,
                'provider_receipts':[{'index':index,'state':'started'} for index in range(attempts)]}
        record['billing_context']=binding.prepare_task_binding(service,record,{'call_source_id':source_id},'employee',PROVIDER)
        journal.create(record)
        return journal.get(task_id)
    return service,p,design,ops,journal,company,department,create


def test_binding_is_committed_before_task_and_never_contains_plaintext(bound):
    service,p,design,ops,journal,company,department,create=bound
    record=create()
    assert record['billing_context']['snapshot']['source_id']==department['id']
    assert 'fixture-secret' not in json.dumps(record)
    with binding.credential_scope(record,service=service):
        assert binding.scoped_api_key(PROVIDER)=='fixture-secret-design'
        assert 'fixture-secret-design' not in binding.task_error('upstream echoed fixture-secret-design')
        with pytest.raises(HTTPException):
            binding.scoped_api_key({**PROVIDER,'base_url':'https://other.example'})
    assert binding.scoped_api_key(PROVIDER) is None


def test_two_parallel_runners_keep_distinct_credentials(bound):
    service,p,design,ops,journal,company,department,create=bound
    create('department-task')
    create('company-task',company['id'])
    seen=[]
    async def runner(task_id,payload):
        await asyncio.sleep(0.01)
        seen.append((task_id,binding.scoped_api_key(PROVIDER)))
        assert journal.mark_running(task_id)
        journal.finish(task_id,{'status':'succeeded'})
    async def run():
        wrapped=binding.bound_runner(journal,runner,service=service)
        await asyncio.gather(wrapped('department-task',None),wrapped('company-task',None))
    asyncio.run(run())
    assert set(seen)=={('department-task','fixture-secret-design'),('company-task','fixture-secret-company')}
    assert not binding.credential_bound()


def test_revocation_stops_unsubmitted_task_without_company_fallback(bound):
    service,p,design,ops,journal,company,department,create=bound
    record=create()
    service.grant_source(p['design'],department['id'],'employee',False)
    calls=[]
    async def runner(*args):calls.append(args)
    asyncio.run(binding.bound_runner(journal,runner,service=service)(record['id'],None))
    assert not calls
    assert journal.get(record['id'])['status']=='failed'
    assert journal.get(record['id'])['billing_context']['snapshot']['source_id']==department['id']


def test_original_query_keeps_old_key_after_rotation_and_transfer(bound):
    service,p,design,ops,journal,company,department,create=bound
    record=create()
    assert journal.mark_running(record['id'])
    journal.record_provider_request(record['id'],0,{**record['billing_context']['provider'],
        'upstream_task_id':'accepted-original','state':'accepted'})
    journal.finish(record['id'],{'status':'failed'})
    service.rotate_source(p['design'],department['id'],department['revision'],'fixture-rotated')
    service.assign_member(p['admin'],ops,'employee')
    calls=[]
    async def query(provider,upstream_id):
        calls.append(('query',upstream_id,binding.scoped_api_key(provider)))
        return {'status':'running'}
    recovery=CanvasImageRecovery(journal,lambda _:PROVIDER,query,lambda _:None)
    assert asyncio.run(recovery.reconcile(record['id']))['status']=='running'
    assert calls==[('query','accepted-original','fixture-secret-design')]


def test_projection_replays_receipts_once_and_preserves_unknown_unit(bound):
    service,p,design,ops,journal,company,department,create=bound
    record=create()
    record['provider_receipts'][0].update(state='generated',reported_usage={'reported_cost':'0.5','currency':'USD'})
    binding.project_task_costs(service,record)
    binding.project_task_costs(service,record)
    costs=DepartmentCosts(service)
    assert costs.summary(p['employee'])['groups'][0]['actual']=='0.5'
    unknown=create('unknown-unit')
    unknown['provider_receipts'][0].update(state='generated',reported_usage={'reported_cost':'0.5','currency':None})
    binding.project_task_costs(service,unknown)
    summary=costs.summary(p['employee'])
    assert summary['pending_reconciliation']==1
    assert len(summary['groups'])==1


def test_legacy_receipt_does_not_touch_the_new_database():
    class Unavailable:
        def connect(self):raise AssertionError('legacy task must not require new schema')
    with binding.credential_scope({'id':'old-task'},service=Unavailable()):
        assert binding.scoped_api_key(PROVIDER) is None


def test_tampered_billing_snapshot_is_rejected_without_resolving_new_source(bound):
    service,p,design,ops,journal,company,department,create=bound
    record=create()
    record['billing_context']['snapshot']['source_id']=company['id']
    with pytest.raises(HTTPException,match='身份不可确认'):
        with binding.credential_scope(record,service=service):
            raise AssertionError('must not reach execution')


def test_foreign_source_and_disabled_default_do_not_silently_use_global_key(bound):
    service,p,design,ops,journal,company,department,create=bound
    with pytest.raises(HTTPException):
        binding.prepare_task_binding(service,{'id':'foreign','model':'m'},
            {'call_source_id':department['id']},'outsider',PROVIDER)
    service.enable_source(p['design'],department['id'],False)
    service.enable_source(p['admin'],company['id'],False)
    with pytest.raises(HTTPException):
        create()


def test_interrupted_projection_is_unknown_then_rebuilt_from_existing_receipt(bound,monkeypatch):
    service,p,design,ops,journal,company,department,create=bound
    record=create()
    costs=DepartmentCosts(service)
    assert costs.summary(p['employee'])['pending_reconciliation']==1
    assert journal.mark_running(record['id'])
    # Simulate process exit between an atomic receipt and its SQL projection.
    monkeypatch.setattr(binding,'project_record_costs',lambda _:None)
    journal.record_provider_request(record['id'],0,{'state':'generated',
        'reported_usage':{'reported_cost':'0.5','currency':'USD'}})
    binding.refresh_cost_projection(service,p['employee'],'me',None,journal)
    summary=costs.summary(p['employee'])
    assert summary['pending_reconciliation']==0 and summary['groups'][0]['actual']=='0.5'
    binding.refresh_cost_projection(service,p['employee'],'me',None,journal)
    assert len(costs.entries(p['employee'])['entries'])==1


def test_legacy_direct_generation_cannot_bypass_managed_sources(bound,monkeypatch):
    service,p,design,ops,journal,company,department,create=bound
    monkeypatch.setattr(db,'get_db',service.connect)
    with pytest.raises(HTTPException,match='持久任务入口'):
        binding.require_bound_generation(PROVIDER)
    with binding.credential_scope(create(),service=service):
        binding.require_bound_generation(PROVIDER)


def test_partial_batch_projection_does_not_hide_missing_attempt_costs(bound,monkeypatch):
    service,p,design,ops,journal,company,department,create=bound
    record=create(attempts=2)
    costs=DepartmentCosts(service)
    assert journal.mark_running(record['id'])
    monkeypatch.setattr(binding,'project_record_costs',lambda _:None)
    for index in range(2):
        journal.record_provider_request(record['id'],index,{'state':'generated',
            'reported_usage':{'reported_cost':'0.5','currency':'USD'}})
    costs.record_fact(record['id'],0,'supplier-charge',kind='charge',amount='0.5',unit='USD')
    partial=costs.summary(p['employee'])
    assert partial['groups'][0]['actual']=='0.5' and partial['pending_reconciliation']==1
    binding.refresh_cost_projection(service,p['employee'],'me',None,journal)
    complete=costs.summary(p['employee'])
    assert complete['groups'][0]['actual']=='1.0' and complete['pending_reconciliation']==0
    assert len(costs.entries(p['employee'])['entries'])==2
