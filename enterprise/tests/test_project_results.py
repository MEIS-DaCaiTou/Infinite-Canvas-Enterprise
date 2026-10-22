"""Shared creative context, revoked reads and private reuse on real SQLite/files."""
import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from enterprise import db
from enterprise.department_api import create_router
from enterprise.department_governance import GovernanceError
from enterprise.project_results import ProjectResults
from enterprise.shared_canvases import SharedCanvases
from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.tests.test_department_governance import business, source, context
from enterprise.tests.test_canvas_workspace import migrate_workspace, seed_workspace


@pytest.fixture
def results(business,tmp_path,monkeypatch):
    service,p,design,ops,path=business;migrate_workspace(path,tmp_path)
    roots=SimpleNamespace(DATA_ROOT=tmp_path/'data',UPLOAD_ROOT=tmp_path/'uploads')
    workspace,project=seed_workspace(service,p,design,roots.DATA_ROOT)
    (roots.UPLOAD_ROOT/'assets/output').mkdir(parents=True)
    (roots.UPLOAD_ROOT/'assets/uploads').mkdir(parents=True)
    (roots.UPLOAD_ROOT/'assets/output/result.png').write_bytes(b'controlled result')
    (roots.UPLOAD_ROOT/'assets/uploads/reference.png').write_bytes(b'controlled original reference')
    doc=json.loads((roots.DATA_ROOT/'canvases/video.json').read_text())
    doc['nodes']=[{'id':'prompt','type':'prompt','text':'将羽绒服改成蓝色'},
                  {'id':'ref','type':'image','url':'/assets/uploads/reference.png'},
                  {'id':'api','type':'api','apiSettings':{'apiKey':'fixture-private-key','max_tokens':200,'businessProjectId':project,'callSources':{'comfly':'original-source'}},
                   '_pending':[{'canvasTaskId':'original'}],'running':True}]
    doc['connections']=[{'from':'prompt','to':'api'},{'from':'ref','to':'api'}]
    doc['nodes'][2]['jimengPending']={'submitId':'fixture-original-submission','kind':'image'}
    (roots.DATA_ROOT/'canvases/video.json').write_text(json.dumps(doc),encoding='utf8')
    def connect():
        c=service.connect();c.row_factory=sqlite3.Row;return c
    monkeypatch.setattr(db,'get_db',connect)
    key=source(service,p,design);context(service,p,task='task',source_id=key['id'],project=project)
    journal=CanvasTaskJournal(roots.DATA_ROOT/'canvas-tasks')
    journal.create({'id':'task','type':'online-image','enterprise_user_id':'employee','status':'succeeded',
        'created_at':100,'model':'fixture-model','result':{'images':['/assets/output/result.png']},
        'error':'private diagnostic','billing_context':{'snapshot':{'account_ref':'private-account'}},
        'source':{'canvas_id':'video','node_id':'api'}})
    db.record_task_owner('employee','canvas_image','task')
    return service,p,design,ops,workspace,project,roots,journal


def test_shared_task_results_and_costs_remain_separate(results):
    service,p,design,_,_,project,roots,journal=results;catalog=ProjectResults(service,roots,journal)
    assert not catalog.page(p['outsider'],scope='company')['tasks']
    service.share_project(p['employee'],project,'company_readonly')
    page=catalog.page(p['outsider'],scope='company')
    assert [t['id'] for t in page['tasks']]==['task']
    detail=catalog.detail(p['outsider'],'task')
    assert detail['items'][0]['url'].endswith('/outputs/0') and 'readonly=1' in detail['source']['url']
    assert not any(word in json.dumps(detail) for word in ['private diagnostic','private-account','billing_context','upstream_task_id'])
    with pytest.raises(GovernanceError):catalog.page(p['outsider'],scope='company',member_id='employee')
    assert catalog.output(p['outsider'],'task',0).read_bytes()==b'controlled result'
    service.share_project(p['employee'],project,'private')
    with pytest.raises(GovernanceError):catalog.output(p['outsider'],'task',0)


def test_full_canvas_context_and_private_copy_survive_unsharing(results):
    service,p,_,_,_,project,roots,_=results;shared=SharedCanvases(service,roots)
    service.share_project(p['employee'],project,'company_readonly')
    preview=shared.detail(p['outsider'],'video')['canvas']
    assert preview['nodes'][0]['text']=='将羽绒服改成蓝色' and len(preview['connections'])==2
    assert preview['nodes'][2]['apiSettings']['max_tokens']==200
    assert 'fixture-private-key' not in json.dumps(preview)
    assert preview['nodes'][1]['url'].startswith('/enterprise/api/business/workspace/canvases/video/resources/')
    assert shared.resource(p['outsider'],'video',0).read_bytes()==b'controlled original reference'
    copied=shared.reuse(p['outsider'],'video')['canvas']
    assert not copied['nodes'][2]['running'] and '_pending' not in copied['nodes'][2]
    assert 'jimengPending' not in copied['nodes'][2]
    assert 'businessProjectId' not in copied['nodes'][2]['apiSettings']
    assert 'apiKey' not in copied['nodes'][2]['apiSettings']
    url=copied['nodes'][1]['url'];assert db.get_resource_owner(url)=='outsider'
    service.share_project(p['employee'],project,'private')
    with pytest.raises(GovernanceError):shared.resource(p['outsider'],'video',0)
    assert (roots.UPLOAD_ROOT/url.lstrip('/')).read_bytes()==b'controlled original reference'
    assert db.get_canvas_owner('video')=='employee'
    with service.connect() as conn:assert conn.execute('SELECT count(*) FROM generation_cost_entries').fetchone()[0]==0


def test_result_reuse_uses_new_ownership_and_rolls_back_partial_copy(results):
    service,p,_,_,_,project,roots,journal=results;catalog=ProjectResults(service,roots,journal)
    service.share_project(p['employee'],project,'company_readonly')
    copied=catalog.reuse(p['outsider'],'task',['/assets/output/result.png'])
    url=copied['items'][0]['url'];assert db.get_resource_owner(url)=='outsider'
    assert catalog.output(p['employee'],'task',0).read_bytes()==(roots.UPLOAD_ROOT/url.lstrip('/')).read_bytes()
    before=set((roots.UPLOAD_ROOT/'assets/output/reused').glob('*'))
    with pytest.raises(GovernanceError):catalog.reuse(p['outsider'],'task',['/assets/output/result.png','no-such-result'])
    assert set((roots.UPLOAD_ROOT/'assets/output/reused').glob('*'))==before


def test_private_and_unrelated_canvas_never_follows_project_visibility(results):
    service,p,_,_,workspace,project,roots,_=results;shared=SharedCanvases(service,roots)
    service.share_project(p['employee'],project,'company_readonly')
    with pytest.raises(GovernanceError):shared.detail(p['outsider'],'personal')
    with pytest.raises(GovernanceError):shared.detail(p['employee'],'ops-private')
    (roots.UPLOAD_ROOT/'assets/uploads/reference.png').unlink()
    with pytest.raises(GovernanceError):shared.reuse(p['outsider'],'video')
    assert db.get_canvas_owner('video')=='employee'


def test_result_selection_keeps_original_identity_when_outputs_reorder(results,monkeypatch):
    service,p,_,_,_,project,roots,journal=results;catalog=ProjectResults(service,roots,journal)
    service.share_project(p['employee'],project,'company_readonly')
    key=catalog.detail(p['outsider'],'task')['items'][0]['key']
    (roots.UPLOAD_ROOT/'assets/output/second.png').write_bytes(b'second result')
    reordered={**journal.get('task'),'result':{'images':['/assets/output/second.png','/assets/output/result.png']}}
    monkeypatch.setattr(journal,'get',lambda task_id:reordered)
    selected=catalog.reuse(p['outsider'],'task',[key])['items'][0]['url']
    assert (roots.UPLOAD_ROOT/selected.lstrip('/')).read_bytes()==b'controlled result'


def test_member_administration_filters_and_keeps_role_authority(results):
    service,p,design,ops,_,_,_,_=results
    assert {m['id'] for m in service.member_workspace(p['design'])['members']}=={'design','employee'}
    assert len(service.member_workspace(p['admin'])['members'])==5
    with pytest.raises(GovernanceError):service.member_workspace(p['employee'])
    with pytest.raises(GovernanceError):service.assign_member(p['design'],design,'outsider')
    with pytest.raises(GovernanceError):service.assign_member(p['design'],design,'employee',True)
    service.assign_member(p['admin'],ops,'employee')
    assert {m['id'] for m in service.member_workspace(p['design'])['members']}=={'design'}


def test_shared_resources_do_not_decode_outside_media_subtrees(results):
    service,p,_,_,_,project,roots,_=results;shared=SharedCanvases(service,roots)
    service.share_project(p['employee'],project,'company_readonly')
    (roots.UPLOAD_ROOT/'private-config.txt').write_text('synthetic private file',encoding='utf8')
    (roots.UPLOAD_ROOT/'assets/images').mkdir()
    path=roots.DATA_ROOT/'canvases/video.json';doc=json.loads(path.read_text())
    doc['nodes']=[{'id':'ref','type':'image','url':'/assets/images/%252e%252e/%252e%252e/private-config.txt'}]
    path.write_text(json.dumps(doc),encoding='utf8')
    with pytest.raises(GovernanceError,match='RESULT_FILE_UNAVAILABLE'):
        shared.resource(p['outsider'],'video',0)
    with pytest.raises(GovernanceError,match='RESULT_FILE_UNAVAILABLE'):
        shared.reuse(p['outsider'],'video')


def test_http_preview_range_revocation_and_fee_permissions(results,monkeypatch):
    service,p,design,_,_,project,roots,journal=results
    from enterprise import project_results, shared_canvases
    monkeypatch.setattr(project_results,'PATH_ROOTS',roots);monkeypatch.setattr(shared_canvases,'PATH_ROOTS',roots)
    app=FastAPI()
    @app.middleware('http')
    async def identity(request:Request,next):
        request.state.user=p.get(request.headers.get('x-user'));return await next(request)
    app.include_router(create_router(service),prefix='/enterprise')
    service.share_project(p['employee'],project,'company_readonly')
    with TestClient(app) as client:
        headers={'x-user':'outsider'}
        url='/enterprise/api/business/workspace/tasks/task/outputs/0'
        assert client.get(url).status_code==401
        response=client.get(url,headers={**headers,'range':'bytes=0-9'})
        assert response.status_code==206 and response.content==b'controlled'
        assert client.get('/enterprise/api/business/workspace/canvases/video',headers=headers).status_code==200
        assert client.get('/enterprise/api/business/costs?scope=company',headers=headers).status_code==403
        service.share_project(p['employee'],project,'private')
        assert client.get(url,headers=headers).status_code==404
