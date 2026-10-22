"""Actual main + two processes + DPAPI; controlled runner, zero upstream calls."""
import os
import subprocess
import sys

import pytest

from enterprise.tests.test_canvas_image_recovery_main import BOOTSTRAP, ROOT


def test_new_source_without_global_key_is_durable_and_runs_after_restart(tmp_path):
    if os.name!='nt':
        pytest.skip('Windows credential adapter')
    app=tmp_path/'install/releases/fixture'
    (app/'static').mkdir(parents=True)
    (app/'main.py').write_text('# isolated fixture',encoding='utf8')
    setup=BOOTSTRAP.replace("main.api_headers = lambda **kwargs: {'Authorization':'Bearer fixture-only-key'}\n",'')
    setup+=r'''
from enterprise.tests.test_department_governance import baseline,migrate
from enterprise.department_governance import DepartmentGovernance
from enterprise.department_costs import DepartmentCosts
from enterprise import db
db.can_use_feature=lambda *args,**kwargs:True
service=DepartmentGovernance()
admin={'user_id':'admin','auth_version':1}
employee={'user_id':'employee','auth_version':1}
trace=roots.DATA_ROOT/'credential-execution.json'
'''
    writer=setup+r'''
baseline(roots.DATA_ROOT/'enterprise.db')
migrate(roots.DATA_ROOT/'enterprise.db',roots.DATA_ROOT)
department=service.create_department(admin,'fixture department')['id']
service.assign_member(admin,department,'employee')
key=service.create_source(admin,provider_id='zhenzhen',name='fixture department source',scope='department',
    department_id=department,procurement='department',account_ref='fixture-account',secret='fixture-department-secret')
service.grant_source(admin,key['id'],'employee',True)
main.CANVAS_TASK_DISPATCH.paused=lambda:True
async def scenario():
    from fastapi import HTTPException
    invalid={'canvas_id':'unowned-fixture','node_id':'not-saved'}
    requests=[
        (main.create_canvas_image_task,main.OnlineImageRequest(prompt='rejected',provider_id='zhenzhen',source=invalid)),
        (main.create_canvas_video_task,main.CanvasVideoRequest(prompt='rejected',provider_id='zhenzhen',source=invalid)),
        (main.create_canvas_llm_task,main.CanvasLLMTaskRequest(message='rejected',provider='zhenzhen',source=invalid)),
    ]
    for create,rejected in requests:
        try:
            await create(rejected,'employee')
        except HTTPException as exc:
            assert exc.status_code==403
        else:
            raise AssertionError('inaccessible source must be rejected')
    assert not list(main.CANVAS_TASK_JOURNAL.root.glob('*.json'))
    assert DepartmentCosts(service).summary(employee)['pending_reconciliation']==0
    assert not trace.exists()
    payload=main.OnlineImageRequest(prompt='fixture private prompt',provider_id='zhenzhen',model='nano-banana-2')
    task=await main.create_canvas_image_task(payload,'employee')
    id_path.write_text(task['task_id'])
    receipt=main.CANVAS_TASK_JOURNAL.get(task['task_id'])
    assert receipt['dispatch_version']==1 and receipt['status']=='queued'
    assert receipt['billing_context']['snapshot']['source_id']==key['id']
    assert 'fixture-department-secret' not in json.dumps(receipt)
    assert 'fixture-department-secret' not in main.CANVAS_TASK_DISPATCH.inputs._path(task['task_id']).read_text()
    await main.CANVAS_TASK_DISPATCH.stop()
asyncio.run(scenario())
'''
    reader=setup+r'''
async def controlled_generation(payload,receipt_task_id):
    hdrs=main.api_headers(provider=main.get_api_provider_exact('zhenzhen'),model=payload.model)
    assert hdrs['Authorization']=='Bearer fixture-department-secret'
    assert not trace.exists(),'the original queued request must execute once'
    trace.write_text(json.dumps({'task_id':receipt_task_id,'kind':'controlled-generation'}))
    sink=main.ImageReceiptSink(main.CANVAS_TASK_JOURNAL,receipt_task_id,0)
    await sink.started(provider,payload.model)
    await sink.accepted('fixture-upstream-original',provider)
    await sink.generated({'cost':'0.5','currency':'USD'})
    await sink.completed(['/output/controlled.png'],[])
    return {'images':['/output/controlled.png']}
main.build_online_image_result=controlled_generation
async def scenario():
    await main.CANVAS_TASK_DISPATCH.start()
    async with asyncio.timeout(8):
        while main.CANVAS_TASK_JOURNAL.get(id_path.read_text())['status']!='succeeded':
            await asyncio.sleep(.02)
    await main.CANVAS_TASK_DISPATCH.stop()
    report=DepartmentCosts(service).summary(employee)
    assert report['groups'][0]['actual']=='0.5'
    assert report['groups'][0]['procurement']=='department'
    assert 'fixture-department-secret' not in trace.read_text()
asyncio.run(scenario())
'''
    for code in (writer,reader):
        result=subprocess.run([sys.executable,'-B','-c',code,str(ROOT),str(tmp_path/'install'),str(tmp_path/'local')],
            cwd=ROOT,capture_output=True,text=True,encoding='utf8',timeout=60,
            env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'))
        assert result.returncode==0,(result.stdout,result.stderr)
