"""Actual application startup/shutdown, private roots and query-only transport."""
import os
import subprocess
import sys

import pytest

from enterprise.tests.test_canvas_image_recovery_main import ROOT, BOOTSTRAP


def test_corrected_credentials_and_one_manual_query_resume_image_tracking(tmp_path):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = BOOTSTRAP + r'''
from enterprise import db
from enterprise.canvas_image_recovery import provider_scope
db.get_task_owner=lambda *_:'fixture-alice'
db.get_user_by_id=lambda uid:{'id':uid}
authorized=False
finished=False
def inspect(request):
    calls.append((request.method,request.url.path))
    assert request.method=='GET' and request.url.path=='/v1/images/tasks/accepted-before-process-exit'
    if not authorized:return httpx.Response(401,json={'error':'fixture authentication denied'})
    return httpx.Response(200,json={'status':'SUCCESS','data':[{'url':'https://supplier.example/result.png'}]} if finished else {'status':'IN_PROGRESS'})
main.httpx.AsyncClient=lambda **kwargs:original_client(transport=httpx.MockTransport(inspect),**kwargs)
async def archive(image,prefix=''):
    from PIL import Image
    Image.new('RGB',(1,1),'white').save(Path(main.OUTPUT_DIR)/'resumed.png')
    return '/output/resumed.png'
main.save_ai_image_to_output=archive
main.CANVAS_ACCEPTED_RECOVERY.poll_delay=.02
key='manual-resume-original'
main.CANVAS_TASK_JOURNAL.create({'id':key,'type':'online-image','status':'failed',
    'enterprise_user_id':'fixture-alice','recovery_required':True,
    'provider_receipts':[{'index':0,'state':'accepted','upstream_task_id':'accepted-before-process-exit',**provider_scope(provider)}],
    'auto_recovery':{'status':'manual','reason':'old credentials denied'}})
async def scenario():
    global authorized,finished
    await main.startup_event()
    try:
        assert (await main.reconcile_canvas_image_task(key))['http_status']==401
        assert main.CANVAS_TASK_JOURNAL.get(key)['auto_recovery']['status']=='manual'
        await asyncio.sleep(.06)
        assert len(calls)==1, calls
        authorized=True
        result=await main.reconcile_canvas_image_task(key)
        assert result['status']=='running',result
        assert main.CANVAS_TASK_JOURNAL.get(key)['auto_recovery']['status']=='waiting', 'manual query did not rearm automatic tracking'
        assert (await main.get_canvas_image_task(key))['status']=='running', 'canvas sees failed while original task is still running'
        finished=True
        async with asyncio.timeout(5):
            while main.CANVAS_TASK_JOURNAL.get(key)['status']!='succeeded':await asyncio.sleep(.01)
        assert (await main.get_canvas_image_task(key))['result']['images']==['/output/resumed.png']
        count=len(calls)
        await main.reconcile_canvas_image_task(key)
        assert len(calls)==count and count==3,calls
    finally:await main.shutdown_task_recovery()
asyncio.run(scenario())
'''
    result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(install), str(tmp_path / "local")],
        cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
        capture_output=True, text=True, encoding="utf-8", timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr


def test_actual_comfy_polling_survives_queued_running_and_backend_pause(tmp_path):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = BOOTSTRAP + r'''
main.COMFYUI_INSTANCES = ['https://comfy.example']
record={'id':'poll-original','type':'comfy','status':'failed','recovery_required':True,
        'comfy_receipt':{'backend':main.COMFYUI_INSTANCES[0],'prompt_id':'original-id'}}
main.CANVAS_TASK_JOURNAL.create(record)
phase = 'queued'
def handler(request):
    calls.append((request.method, request.url.path))
    assert request.method == 'GET'
    if request.url.path.startswith('/history/'):
        return httpx.Response(200,json={'original-id':{'status':{'completed':True},'outputs':{}}} if phase=='done' else {})
    return httpx.Response(200,json={'queue_pending' if phase=='queued' else 'queue_running':[[0,'original-id']]})
main.httpx.AsyncClient=lambda **kwargs: original_client(transport=httpx.MockTransport(handler),**kwargs)
main.CANVAS_COMFY_RECOVERY.archive=lambda *_:{'texts':['/output/fixture.txt']}
async def scenario():
    global phase
    for phase in ['queued','running','done']:
        first=await main.get_canvas_comfy_task('poll-original',resume=True)
        assert first['status']=='running',first
        await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
        following=await main.get_canvas_comfy_task('poll-original')
        assert following['status']==('succeeded' if phase=='done' else 'running'),following
    assert len(calls)==5 and all(method=='GET' for method,_ in calls),calls
    main.CANVAS_TASK_JOURNAL.create({**record,'id':'changed-backend','error_code':'runtime_interrupted'})
    main.COMFYUI_INSTANCES=['https://replacement.example']
    await main.get_canvas_comfy_task('changed-backend',resume=True)
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    paused=await main.get_canvas_comfy_task('changed-backend')
    assert paused['status']=='failed' and paused['auto_recovery']['status']=='manual',paused
    assert len(calls)==5
asyncio.run(scenario())
'''
    result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(install), str(tmp_path / "local")],
                            cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("kind", ["online-image", "comfy"])
def test_actual_startup_recovers_without_browser_or_new_submission(tmp_path, kind):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = BOOTSTRAP + r'''
from enterprise import db
from enterprise.canvas_image_recovery import provider_scope
kind = sys.argv[4]
db.get_task_owner = lambda task_type, task_id: 'fixture-alice'
db.get_user_by_id = lambda user_id: {'id':user_id}
main.COMFYUI_INSTANCES = ['https://comfy.example/prefix']
def recovered_handler(request):
    calls.append((request.method,request.url.path))
    assert request.method == 'GET', 'automatic recovery submitted work'
    if kind == 'online-image':
        assert request.url.path == '/v1/images/tasks/accepted-before-process-exit'
        return httpx.Response(200,json={'data':{'status':'SUCCESS','data':{
            'data':[{'url':'https://supplier.example/result.png'}], 'usage':{'total_tokens':27}}}})
    assert request.url.path == '/prefix/history/accepted-comfy-id'
    return httpx.Response(200,json={'accepted-comfy-id':{'status':{'completed':True},
        'outputs':{'9':{'text':['Recovered original prompt']}}}})
main.httpx.AsyncClient = lambda **kwargs: original_client(transport=httpx.MockTransport(recovered_handler), **kwargs)
async def archive_image(image,prefix=''):
    from PIL import Image
    Image.new('RGB',(1,1),'white').save(Path(main.OUTPUT_DIR)/'auto-recovered.png')
    return '/output/auto-recovered.png'
main.save_ai_image_to_output = archive_image
record={'id':'startup-original','type':kind,'status':'running','result':None,
        'enterprise_user_id':'fixture-alice','created_at':1,'updated_at':1}
if kind == 'online-image':
    record.update(provider_id='zhenzhen',model='nano-banana-2',provider_receipts=[
        {'index':0,'state':'accepted','upstream_task_id':'accepted-before-process-exit',**provider_scope(provider)}])
else:
    record['comfy_receipt']={'backend':main.COMFYUI_INSTANCES[0],'prompt_id':'accepted-comfy-id',
        'output_type':'comfy','seed':27,'workflow_json':'custom/fixture.json',
        'workflow_classes':{'9':{'class_type':'SaveText'}}}
main.CANVAS_TASK_JOURNAL.create(record)
async def scenario():
    await main.startup_event()
    try:
        async with asyncio.timeout(8):
            while (main.CANVAS_TASK_JOURNAL.get(record['id']).get('auto_recovery') or {}).get('status') != 'complete':
                await asyncio.sleep(.02)
        finished=main.CANVAS_TASK_JOURNAL.get(record['id'])
        assert finished['status']=='succeeded', finished
        if kind=='online-image':
            assert finished['provider_receipts'][0]['reported_usage']['total_tokens']==27
            assert Path(main.output_file_from_url(finished['result']['images'][0])).is_file()
        else:
            assert finished['result']['items'][0]['text']=='Recovered original prompt'
            assert Path(main.output_file_from_url(finished['result']['texts'][0])).is_file()
        assert len(calls)==1 and all(method=='GET' for method,_ in calls), calls
    finally:
        await main.shutdown_task_recovery()
    # The next application startup sees durable completion and issues no query.
    await main.startup_event()
    await asyncio.sleep(.03)
    await main.shutdown_task_recovery()
    assert len(calls)==1
asyncio.run(scenario())
print('actual startup original identity completed without browser or POST')
'''
    result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(install), str(tmp_path / "local"), kind],
        cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"),
        capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mismatch", ["provider", "owner"])
def test_actual_runtime_failure_wakes_scheduler_and_binding_change_pauses_query(tmp_path, mismatch):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = BOOTSTRAP + r'''
from enterprise import db
from enterprise.canvas_image_recovery import provider_scope
db.get_task_owner=lambda *_:'fixture-bob' if sys.argv[4]=='owner' else 'fixture-alice'
db.get_user_by_id=lambda user_id:{'id':user_id}
async def fail_after_acceptance(payload,receipt_task_id=None):
    from enterprise.canvas_image_recovery import ImageReceiptSink
    await ImageReceiptSink(main.CANVAS_TASK_JOURNAL,receipt_task_id,0).accepted('accepted-before-process-exit',provider)
    raise httpx.ReadTimeout('fixture query connection lost')
main.build_online_image_result=fail_after_acceptance
main.get_api_provider_exact=lambda _:{**provider,'base_url':'https://changed.example/v1'}
main.CANVAS_IMAGE_RECOVERY.resolve_provider=main.get_api_provider_exact
async def scenario():
    await main.startup_event()
    main.CANVAS_TASK_JOURNAL.create({'id':'runtime-original','type':'online-image','status':'queued',
        'enterprise_user_id':'fixture-alice','provider_receipts':[{'index':0,'state':'started'}]})
    await main.run_canvas_image_task('runtime-original',main.OnlineImageRequest(prompt='fixture',provider_id='zhenzhen',model='nano-banana-2'))
    try:
        async with asyncio.timeout(8):
            while (main.CANVAS_TASK_JOURNAL.get('runtime-original').get('auto_recovery') or {}).get('status')!='manual':
                await asyncio.sleep(.02)
        record=main.CANVAS_TASK_JOURNAL.get('runtime-original')
        assert record['provider_receipts'][0]['upstream_task_id']=='accepted-before-process-exit'
        assert calls==[],calls
        assert record['recovery_required'] if 'recovery_required' in record else record['status']=='failed'
    finally:
        await main.shutdown_task_recovery()
asyncio.run(scenario())
'''
    result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(install), str(tmp_path / "local"), mismatch],
        cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"),
        capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
