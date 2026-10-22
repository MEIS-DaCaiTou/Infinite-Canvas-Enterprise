"""Real ledger pagination and current-period, role-scoped advisory budgets."""
import sqlite3
import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from enterprise.department_api import create_router
from enterprise.department_costs import DepartmentCosts
from enterprise.department_governance import DepartmentGovernance, GovernanceError
from enterprise.migrations.versioned import inspect_schema_metadata
from enterprise.tests.test_department_governance import business, baseline, source, context
from enterprise.tests.test_task_credentials import bound


def test_budget_notices_are_current_role_scoped_and_never_block(business,monkeypatch):
    service,p,design,ops,_=business;source(service,p);context(service,p)
    costs=DepartmentCosts(service);now=int(time.time())
    costs.record_fact('task-one',0,'charge',kind='charge',amount='1.000000000001',unit='CNY')
    costs.record_fact('task-one',1,'unknown',kind='unknown')
    costs.set_budget(p['design'],design,'本期',now-10,now+100,'CNY','1')
    costs.set_budget(p['design'],design,'美元单列',now-10,now+100,'USD','0')
    notice=costs.alerts(p['design'])['alerts'][0]
    assert notice['department_id']==design and notice['unit']=='CNY'
    assert notice['over_amount']=='1E-12' and notice['pending_reconciliation']==1
    assert notice['blocking'] is False
    assert costs.alerts(p['employee'])['alerts']==[]
    assert costs.alerts(p['ops'])['alerts']==[]
    assert [n['department_id'] for n in costs.alerts(p['admin'])['alerts']]==[design]
    context(service,p,task='allowed-after-budget')  # advisory never enters acceptance policy
    costs.set_budget(p['design'],design,'本期',now-10,now+100,'CNY','0.5')
    assert costs.alerts(p['design'])['alerts'][0]['id']!=notice['id']
    monkeypatch.setattr('enterprise.department_costs.time.time',lambda:now+200)
    assert costs.alerts(p['design'])['alerts']==[]


def test_cost_cursor_does_not_repeat_or_drop_older_rows_during_new_charge(business):
    service,p,design,_,_=business;source(service,p);context(service,p);costs=DepartmentCosts(service)
    for i in range(60):costs.record_fact('task-one',0,'charge-'+str(i),kind='charge',amount='0.1',unit='USD')
    first=costs.entries(p['employee']);assert len(first['entries'])==50 and first['next_cursor']
    costs.record_fact('task-one',0,'late-charge',kind='charge',amount='0.1',unit='USD')
    second=costs.entries(p['employee'],before=first['next_cursor'])
    assert len(second['entries'])==10 and second['next_cursor'] is None
    ids=[r['id'] for r in first['entries']+second['entries']];assert len(set(ids))==60
    assert costs.entries(p['employee'])['entries'][0]['event_id']=='late-charge'
    with pytest.raises(GovernanceError):costs.entries(p['employee'],scope='company')
    with pytest.raises(GovernanceError):costs.entries(p['ops'],scope='department',department_id=design)


def test_notice_http_auth_and_old_schema_read_never_migrates(business,tmp_path):
    service,p,_,_,_=business;app=FastAPI()
    @app.middleware('http')
    async def identity(request:Request,next):
        request.state.user=p.get(request.headers.get('x-user'));return await next(request)
    app.include_router(create_router(service),prefix='/enterprise')
    with TestClient(app) as client:
        assert client.get('/enterprise/api/business/budget-alerts').status_code==401
        response=client.get('/enterprise/api/business/budget-alerts',headers={'x-user':'employee'})
        assert response.status_code==200 and response.json()['alerts']==[]
    path=baseline(tmp_path/'old.db');before=inspect_schema_metadata(path)
    old=DepartmentCosts(DepartmentGovernance(connect=lambda:sqlite3.connect(path)))
    assert old.alerts(p['design'])=={'enabled':False,'alerts':[]}
    assert inspect_schema_metadata(path)==before


def test_notice_replays_received_cost_fact_once_without_new_generation(bound,tmp_path,monkeypatch):
    from types import SimpleNamespace
    import enterprise.task_credentials as binding
    service,p,design,_,journal,_,_,create=bound;record=create()
    assert journal.mark_running(record['id'])
    monkeypatch.setattr(binding,'project_record_costs',lambda _:None)
    journal.record_provider_request(record['id'],0,{'state':'generated',
        'reported_usage':{'reported_cost':'0.5','currency':'USD'}})
    costs=DepartmentCosts(service);assert not costs.entries(p['employee'])['entries']
    now=int(time.time());costs.set_budget(p['design'],design,'恢复费用',now-20,now+100,'USD','0.1')
    monkeypatch.setattr('enterprise.config.PATH_ROOTS',SimpleNamespace(DATA_ROOT=tmp_path))
    app=FastAPI()
    @app.middleware('http')
    async def identity(request:Request,next):
        request.state.user=p['design'];return await next(request)
    app.include_router(create_router(service),prefix='/enterprise')
    with TestClient(app) as client:
        for _ in range(2):
            data=client.get('/enterprise/api/business/budget-alerts').json()
            assert data['alerts'][0]['actual']=='0.5'
    assert len(costs.entries(p['employee'])['entries'])==1
    assert journal.get(record['id'])['provider_receipts'][0]['state']=='generated'
