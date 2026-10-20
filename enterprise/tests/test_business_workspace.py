"""Permission-filtered UI contracts over isolated SQLite, never real supplier calls."""
import json
import sqlite3

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from enterprise.business_workspace import task_summaries
from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.department_api import create_router
from enterprise.department_governance import DepartmentGovernance, GovernanceError
from enterprise.tests.test_department_governance import business, baseline, source, context
from enterprise.migrations.versioned import inspect_schema_metadata


def test_old_schema_context_does_not_activate_or_modify(tmp_path):
    path=baseline(tmp_path/'old.db');before=inspect_schema_metadata(path)
    service=DepartmentGovernance(connect=lambda:sqlite3.connect(path))
    assert service.workspace({'user_id':'employee','auth_version':1}) == {
        'enabled':False,'reason':'DEPARTMENT_SCHEMA_UPGRADE_REQUIRED'}
    assert inspect_schema_metadata(path)==before


def test_workspace_only_exposes_authorized_metadata_and_shared_projects(business):
    service,p,design,ops,_=business
    a=source(service,p,design,name='design')
    b=service.create_source(p['ops'],provider_id='comfly',name='ops',scope='department',department_id=ops,procurement='department',account_ref='ops-account',secret='fixture-secret-ops')
    project=service.create_project(p['ops'],ops,'公开成果')['id']
    service.share_project(p['ops'],project,'company_readonly')
    data=service.workspace(p['employee'])
    assert [s['id'] for s in data['sources']]==[a['id']]
    assert [d['id'] for d in data['departments']]==[design]
    assert not data['departments'][0]['can_manage'] and not data['company_admin']
    assert data['projects'][0]['id']==project and not data['projects'][0]['can_write']
    assert b['id'] not in json.dumps(data) and 'fixture-secret' not in json.dumps(data)
    with pytest.raises(GovernanceError):service.source_grants(p['design'],b['id'])
    with pytest.raises(GovernanceError):service.directory(p['employee'])
    assert {u['id'] for u in service.directory(p['design'])}=={'design','employee'}


def test_owner_can_manage_own_project_without_global_directory(business):
    service,p,design,_,_=business
    project=service.create_project(p['employee'],design,'本人项目')['id']
    assert {u['id'] for u in service.project_members(p['employee'],project)}=={'design','employee'}
    with pytest.raises(GovernanceError):service.project_members(p['outsider'],project)
    service.grant_project(p['employee'],project,'design',True)
    assert next(u for u in service.project_members(p['employee'],project) if u['id']=='design')['can_write']==1


def test_department_task_view_uses_frozen_attribution_and_never_public_project_access(business,tmp_path):
    service,p,design,ops,_=business;key=source(service,p,design)
    project=service.create_project(p['employee'],design,'共享项目')['id']
    service.share_project(p['employee'],project,'company_readonly')
    context(service,p,task='original',source_id=key['id'],project=project)
    journal=CanvasTaskJournal(tmp_path/'tasks')
    journal.create({'id':'original','type':'llm','enterprise_user_id':'employee','status':'succeeded',
        'created_at':100,'model':'fixture','result':{'text':'private full text'}})
    service.assign_member(p['admin'],ops,'employee')
    old=task_summaries(service,p['design'],scope='department',department_id=design,journal=journal)
    assert [r['id'] for r in old['tasks']]==['original']
    assert old['tasks'][0]['context']['department_id']==design
    assert 'private full text' not in json.dumps(old)
    assert task_summaries(service,p['outsider'],journal=journal)['tasks']==[]
    with pytest.raises(GovernanceError):
        task_summaries(service,p['ops'],scope='department',department_id=design,journal=journal)
    assert not service.workspace(p['outsider'])['projects'][0]['can_write']


def test_http_workspace_auth_and_metadata_endpoints(business):
    service,p,design,ops,_=business;key=source(service,p,design)
    app=FastAPI()
    @app.middleware('http')
    async def identity(request:Request,next):
        request.state.user=p.get(request.headers.get('x-fixture-user'));return await next(request)
    app.include_router(create_router(service),prefix='/enterprise')
    with TestClient(app) as client:
        assert client.get('/enterprise/api/business/context').status_code==401
        data=client.get('/enterprise/api/business/context',headers={'x-fixture-user':'employee'})
        assert data.status_code==200 and data.json()['enabled']
        assert client.get('/enterprise/api/business/directory',headers={'x-fixture-user':'employee'}).status_code==403
        grants=client.get('/enterprise/api/business/sources/'+key['id']+'/grants',headers={'x-fixture-user':'design'})
        assert grants.status_code==200 and grants.json()[0]['user_id']=='employee'
        assert client.get('/enterprise/api/business/sources/'+key['id']+'/grants',headers={'x-fixture-user':'ops'}).status_code==403
        assert client.get('/enterprise/api/business/costs/summary?scope=company',headers={'x-fixture-user':'design'}).status_code==403
