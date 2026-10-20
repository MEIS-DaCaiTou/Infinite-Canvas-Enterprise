"""Actual legacy routes + SQLite/DPAPI + controlled HTTP; no paid provider."""
import os
import subprocess
import sys

import pytest

from enterprise.tests.test_canvas_image_recovery_main import BOOTSTRAP, ROOT


def test_legacy_entries_use_the_same_receipts_credentials_and_costs(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows DPAPI')
    app = tmp_path/'install/releases/fixture'
    (app/'static').mkdir(parents=True)
    (app/'main.py').write_text('# isolated fixture', encoding='utf8')
    code = BOOTSTRAP.replace("main.api_headers = lambda **kwargs: {'Authorization':'Bearer fixture-only-key'}\n", '')
    code += r'''
import base64, io
from PIL import Image
from starlette.requests import Request
from fastapi import HTTPException
from enterprise import db
from enterprise.tests.test_department_governance import baseline,migrate
from enterprise.department_governance import DepartmentGovernance,GovernanceError
from enterprise.department_costs import DepartmentCosts
from enterprise.legacy_call_sources import adopt_shared_source
baseline(roots.DATA_ROOT/'enterprise.db')
provider['chat_models']=['fixture-chat']
main.save_api_providers([provider])
os.environ[main.provider_key_env('zhenzhen')]='fixture-old-shared'
db.can_use_feature=lambda *a,**kw:True
service=DepartmentGovernance()
admin={'user_id':'admin','auth_version':1}
employee={'user_id':'employee','auth_version':1}
req=Request({'type':'http','method':'POST','path':'/api/chat','headers':[], 'client':('127.0.0.1',1)})
trace=[];mode='success'
png=io.BytesIO();Image.new('RGB',(2,2),'blue').save(png,format='PNG')
def handler(request):
    body=json.loads(request.content)
    trace.append((str(request.url),request.headers.get('authorization'),body))
    if mode=='reject':
        return httpx.Response(401,text='rejected '+request.headers['authorization'].removeprefix('Bearer '),request=request)
    if request.url.path.endswith('/images/generations'):
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(png.getvalue()).decode()}],
            'cost':'.2','currency':'USD'},request=request)
    text='controlled text'
    if 'action 只能' in body['messages'][0]['content']:
        text=json.dumps({'action':'generate_image','prompt':'controlled image'})
    usage={'cost':'.2','currency':'USD'}
    if body.get('stream'):
        return httpx.Response(200,content=('data: '+json.dumps({'choices':[{'delta':{'content':text}}]})+
            '\n\ndata: '+json.dumps({'choices':[],'usage':usage,'cost':'.2','currency':'USD'})+'\n\ndata: [DONE]\n\n').replace('\\n','\n').encode(),
            headers={'content-type':'text/event-stream'},request=request)
    return httpx.Response(200,json={'choices':[{'message':{'content':text}}],'usage':usage,'cost':'.2','currency':'USD'},request=request)

async def scenario():
    # Old schema still uses the original configured key and conversation response.
    result=await main.chat(main.ChatRequest(message='old',provider='zhenzhen',model='fixture-chat'),req,'employee','employee')
    assert result['message']['content']=='controlled text'
    assert trace[-1][1]=='Bearer fixture-old-shared'
    assert not list(main.CANVAS_TASK_JOURNAL.root.glob('*.json'))
    migrate(roots.DATA_ROOT/'enterprise.db',roots.DATA_ROOT)
    dept=service.create_department(admin,'Design')['id']
    service.assign_member(admin,dept,'employee')
    metadata=dict(provider_id='zhenzhen',name='company',scope='company',department_id=None,
        procurement='company',account_ref='company-account')
    reads=[]
    try:
        adopt_shared_source(service,employee,metadata,lambda _p:reads.append(1))
    except GovernanceError as exc:
        assert exc.status_code==403
    else:raise AssertionError('employee adopted a shared key')
    assert not reads
    adopted=await main.adopt_call_source(main.AdoptCallSourceRequest(**metadata),'admin')
    assert 'fixture-old-shared' not in json.dumps(adopted)
    company=service.create_source(admin,**{**metadata,'name':'selected company'},secret='fixture-company-secret')
    department=service.create_source(admin,**{**metadata,'name':'department','scope':'department','department_id':dept,
        'procurement':'department','account_ref':'department-account'},secret='fixture-department-secret')
    for source in [company,department]:service.grant_source(admin,source['id'],'employee',True)
    result=await main.chat(main.ChatRequest(message='new',provider='zhenzhen',model='fixture-chat'),req,'employee','employee')
    assert trace[-1][1]=='Bearer fixture-department-secret'
    assert result['conversation']['messages'][-1]['content']=='controlled text'
    # Stream headers and receipt retain the accepted revision even after rotation.
    payload=main.ChatRequest(message='stream',provider='zhenzhen',model='fixture-chat',call_source_id=company['id'])
    response=await main.chat_stream(payload,req,'employee','employee')
    service.rotate_source(admin,company['id'],company['revision'],'fixture-company-new')
    chunks=[chunk async for chunk in response.body_iterator]
    assert 'controlled text' in ''.join(chunks) and '"type": "done"' in ''.join(chunks)
    assert trace[-1][1]=='Bearer fixture-company-secret'
    # Online and chat-image both reuse the existing durable image runner.
    result=await main.online_image(main.OnlineImageRequest(prompt='image',provider_id='zhenzhen',model='nano-banana-2'),'employee')
    assert result['images'] and trace[-1][1]=='Bearer fixture-department-secret'
    result=await main.chat(main.ChatRequest(message='image',mode='image',provider='zhenzhen',image_model='nano-banana-2'),req,'employee','employee')
    assert result['message']['image_url'].startswith(('/output/','/assets/output/'))
    # Agent router and image tool independently select their sources.
    result=await main.chat_agent(main.ChatRequest(message='agent',mode='agent',provider='zhenzhen',model='fixture-chat',
        image_provider='zhenzhen',image_model='nano-banana-2',call_source_id=company['id'],image_call_source_id=department['id']),req,'employee','employee')
    assert result['message']['type']=='image'
    assert trace[-2][1]=='Bearer fixture-company-new' and trace[-1][1]=='Bearer fixture-department-secret'
    before=len(trace)
    try:
        await main.chat(main.ChatRequest(message='denied',provider='zhenzhen',call_source_id=company['id']),req,'outsider','outsider')
    except HTTPException as exc:assert exc.status_code==403
    else:raise AssertionError('unauthorized source used')
    assert len(trace)==before
    # Explicit rejection is terminal, sanitized, and never changes the key/retries.
    global mode
    mode='reject'
    response=await main.chat_stream(main.ChatRequest(message='reject',provider='zhenzhen',call_source_id=company['id']),req,'employee','employee')
    chunks=[chunk async for chunk in response.body_iterator]
    assert 'fixture-company-new' not in ''.join(chunks)
    assert len(trace)==before+1
    records=[main.CANVAS_TASK_JOURNAL.get(p.stem) for p in main.CANVAS_TASK_JOURNAL.root.glob('*.json')]
    rejected=max(records,key=lambda r:r['created_at'])
    assert rejected['status']=='failed' and not rejected['recovery_required']
    assert all('secret' not in json.dumps(r) and 'fixture-old-shared' not in json.dumps(r) for r in records)
    assert len(records)==7
    costs=DepartmentCosts(service).summary(employee)
    from decimal import Decimal
    assert sum(Decimal(g['actual']) for g in costs['groups'])==Decimal('1.2')
    assert costs['pending_reconciliation']==1
    assert len(trace)==8  # one old-schema call + seven managed legs, no retry
    mode='success'
    # Closing a partially consumed stream leaves the original task for review.
    response=await main.chat_stream(main.ChatRequest(message='cancel',provider='zhenzhen'),req,'employee','employee')
    await anext(response.body_iterator)  # metadata, before supplier submission
    await anext(response.body_iterator)  # first received delta
    await response.body_iterator.aclose()
    records=[main.CANVAS_TASK_JOURNAL.get(p.stem) for p in main.CANVAS_TASK_JOURNAL.root.glob('*.json')]
    interrupted=max(records,key=lambda r:r['created_at'])
    assert interrupted['status']=='failed' and interrupted['recovery_required']
    before=len(trace)
    assert (await main.CANVAS_LLM_TASKS.restore(interrupted['id']))['status']=='failed'
    assert len(trace)==before
    # Received text survives a local archive failure; restore never calls HTTP.
    archive=main.CANVAS_LLM_TASKS.archive
    main.CANVAS_LLM_TASKS.archive=lambda text:(_ for _ in ()).throw(OSError('controlled disk failure'))
    try:
        await main.chat(main.ChatRequest(message='archive',provider='zhenzhen'),req,'employee','employee')
    except HTTPException as exc:assert exc.status_code==502
    else:raise AssertionError('archive error was hidden')
    main.CANVAS_LLM_TASKS.archive=archive
    records=[main.CANVAS_TASK_JOURNAL.get(p.stem) for p in main.CANVAS_TASK_JOURNAL.root.glob('*.json')]
    received=max(records,key=lambda r:r['created_at'])
    assert received['llm_result']['text']=='controlled text'
    before=len(trace)
    assert (await main.CANVAS_LLM_TASKS.restore(received['id']))['status']=='succeeded'
    assert len(trace)==before
    await main.CANVAS_TASK_DISPATCH.stop()
asyncio.run(scenario())
print('legacy chat/stream/image/agent, explicit adoption, source isolation and receipts: PASS')
'''
    result = subprocess.run([sys.executable,'-B','-c',code,str(ROOT),str(tmp_path/'install'),str(tmp_path/'local')],
        cwd=ROOT,capture_output=True,text=True,encoding='utf8',timeout=90,
        env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'))
    assert result.returncode == 0, result.stdout+result.stderr


def test_shared_key_adoption_uses_existing_admin_settings_policy():
    from enterprise.interceptors import _settings_denial_for_normal_user
    from enterprise.route_policy import is_allowed_upstream_route
    assert _settings_denial_for_normal_user('api/call-sources/adopt', 'POST')
    assert is_allowed_upstream_route('POST', 'api/call-sources/adopt')
    assert not is_allowed_upstream_route('GET', 'api/call-sources/adopt')
