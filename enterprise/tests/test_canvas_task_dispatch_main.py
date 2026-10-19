"""Actual main entry/claim/startup, isolated storage and controlled generation."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from enterprise.tests.test_canvas_image_recovery_main import BOOTSTRAP, ROOT

SETUP = BOOTSTRAP + r'''
from enterprise import db
db.get_user_by_id=lambda uid:{'id':uid,'user_id':uid,'is_admin':True,'role':'super_admin'} if uid=='alice' else None
db.get_task_owner=lambda *_:'alice'
db.get_canvas_image_task_owner=lambda *_:'alice'
db.record_canvas_image_task_owner=lambda *a,**k:None
db.record_task_owner=lambda *a,**k:None
db.can_use_feature=lambda *a,**k:True
main.provider_env_key_value=lambda _:'fixture-key-never-stored'
main.get_workflow=lambda name:{'workflow':{'1':{'class_type':'LoadImage','inputs':{'image':'fixture.png'}}},'config':{'fields':[],'enabled':True}}
main.workflow_backend=lambda name,override='':override or 'http://127.0.0.1:59999'
main.COMFYUI_INSTANCES=['http://127.0.0.1:59999']
trace=roots.DATA_ROOT/'dispatch-calls.jsonl'
exit_kind=os.environ.get('DISPATCH_EXIT_KIND','')
def generated(kind):
    with trace.open('a',encoding='utf8') as f:
        f.write(json.dumps({'kind':kind})+'\n');f.flush();os.fsync(f.fileno())
    if exit_kind==kind:os._exit(19)
async def image(payload,**kwargs):
    generated('online-image');return {'images':['/output/image.png']}
def comfy(payload,task_id):
    assert payload._workflow_config['fields'][0]['label']=='unsaved-preview-config'
    generated('comfy');return {'texts':['/output/comfy.txt']}
async def video(payload):
    generated('video');return {'videos':['/output/video.mp4']}
async def text(payload):
    generated('llm');return {'text':'restored: '+payload.message,'model':payload.model}
main.build_online_image_result=image
main.execute_comfy_generation=comfy
main.CANVAS_VIDEO_TASKS.generate=video
main.CANVAS_VIDEO_TASKS.archived=lambda _:True
main.CANVAS_VIDEO_TASKS.publish=lambda _:None
main.CANVAS_LLM_TASKS.generate=text
main.CANVAS_LLM_TASKS.archive=lambda _:'/output/text.txt'
main.CANVAS_LLM_TASKS.publish=lambda *a:None
async def create(kind):
    if kind=='online-image':return await main.create_canvas_image_task(main.OnlineImageRequest(prompt='image-input',provider_id='zhenzhen',model='fixture-image'),'alice')
    if kind=='comfy':
        payload=main.GenerateRequest(prompt='comfy-input',workflow_json='custom/test.json',workflow_values={'1.image':'/output/fixture.png'})
        payload._workflow_config={'fields':[{'node':'1','input':'image','label':'unsaved-preview-config'}]}
        return await main.create_canvas_comfy_task(payload,'alice')
    if kind=='video':return await main.create_canvas_video_task(main.CanvasVideoRequest(prompt='video-input',provider_id='zhenzhen',model='fixture-video'),'alice')
    return await main.create_canvas_llm_task(main.CanvasLLMTaskRequest(message='private-text-input',provider='zhenzhen',model='fixture-chat'),'alice')
'''


def invoke(tmp_path, code, *, exit_kind=""):
    install=tmp_path/'install';app=install/'releases/fixture'
    (app/'static').mkdir(parents=True,exist_ok=True)
    (app/'main.py').write_text('# isolated fixture',encoding='utf8')
    return subprocess.run([sys.executable,'-B','-c',SETUP+code,str(ROOT),str(install),str(tmp_path/'local')],
        cwd=ROOT,capture_output=True,text=True,encoding='utf8',timeout=60,
        env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',DISPATCH_EXIT_KIND=exit_kind))


def test_four_task_types_restart_after_durable_acceptance_before_dispatch(tmp_path):
    writer=r'''
main.CANVAS_TASK_DISPATCH.paused=lambda:True
async def write():
    ids={kind:(await create(kind))['task_id'] for kind in ['online-image','comfy','video','llm']}
    for kind,key in ids.items():
        record=main.CANVAS_TASK_JOURNAL.get(key)
        assert record.get('dispatch_version')==1,(kind,record)
        assert record['status']=='queued'
        assert 'private-text-input' not in json.dumps(record)
        assert 'fixture-key-never-stored' not in main.CANVAS_TASK_DISPATCH.inputs._path(key).read_text()
    (roots.DATA_ROOT/'ids.json').write_text(json.dumps(ids))
    assert not trace.exists()
    os._exit(17)
asyncio.run(write())
'''
    first=invoke(tmp_path,writer)
    assert first.returncode==17,first.stdout+first.stderr
    reader=r'''
async def restart():
    await main.startup_event()
    try:
        ids=json.loads((roots.DATA_ROOT/'ids.json').read_text())
        async with asyncio.timeout(10):
            while any(main.CANVAS_TASK_JOURNAL.get(key)['status']=='queued' for key in ids.values()):await asyncio.sleep(.02)
            while main.CANVAS_TASK_DISPATCH.active:await asyncio.sleep(.02)
        assert all(main.CANVAS_TASK_JOURNAL.get(key)['status']=='succeeded' for key in ids.values()),[main.CANVAS_TASK_JOURNAL.get(key) for key in ids.values()]
        actual=[json.loads(line)['kind'] for line in trace.read_text().splitlines()]
        assert sorted(actual)==sorted(ids),actual
        for key in ids.values():assert not main.CANVAS_TASK_DISPATCH.inputs._path(key).exists()
        await main.CANVAS_TASK_DISPATCH.start()
        await asyncio.sleep(.05)
        assert len(trace.read_text().splitlines())==4
        assert (await main.get_canvas_llm_task(ids['llm']))['result']['text']=='restored: private-text-input'
    finally:await main.shutdown_task_recovery()
asyncio.run(restart())
'''
    second=invoke(tmp_path,reader)
    assert second.returncode==0,second.stdout+second.stderr


@pytest.mark.parametrize('kind',['online-image','comfy','video','llm'])
def test_hard_exit_after_claim_never_generates_again_on_startup(tmp_path,kind):
    writer=r'''
async def write():
    result=await create(exit_kind)
    (roots.DATA_ROOT/'claimed-id').write_text(result['task_id'])
    await asyncio.gather(*list(main.CANVAS_TASK_RUNNERS))
asyncio.run(write())
'''
    first=invoke(tmp_path,writer,exit_kind=kind)
    assert first.returncode==19,first.stdout+first.stderr
    reader=r'''
async def restart():
    await main.startup_event()
    try:
        await asyncio.sleep(.1)
        record=main.CANVAS_TASK_JOURNAL.get((roots.DATA_ROOT/'claimed-id').read_text())
        assert record['status']=='failed' and record['recovery_required'],record
        assert record['dispatch_started_at']
        assert len(trace.read_text().splitlines())==1,'claimed request was generated again'
        assert not main.CANVAS_TASK_DISPATCH.active
    finally:await main.shutdown_task_recovery()
asyncio.run(restart())
'''
    second=invoke(tmp_path,reader)
    assert second.returncode==0,second.stdout+second.stderr


def test_queued_video_restart_uses_selected_protocol_once_and_retains_result(tmp_path):
    setup=r'''
provider['video_models']=['MiniMax-H3']
main.save_api_providers([provider])
main.CANVAS_VIDEO_TASKS.generate=main.canvas_video
'''
    writer=setup+r'''
main.CANVAS_TASK_DISPATCH.paused=lambda:True
async def write():
    result=await main.create_canvas_video_task(main.CanvasVideoRequest(
        prompt='owned queued video',provider_id='zhenzhen',model='MiniMax-H3',
        duration=5,resolution='768P'),'alice')
    id_path.write_text(result['task_id'])
    assert main.CANVAS_TASK_JOURNAL.get(result['task_id'])['status']=='queued'
    assert not calls
    os._exit(17)
asyncio.run(write())
'''
    first=invoke(tmp_path,writer)
    assert first.returncode==17,first.stdout+first.stderr
    reader=setup+r'''
def reply(request):
    calls.append((request.method,request.url.path))
    if request.method=='POST':
        assert request.url.path=='/v1/videos'
        body=json.loads(request.content)
        assert body['model']=='MiniMax-H3' and body['seconds']=='5' and body['resolution']=='768P',body
        return httpx.Response(200,json={'id':'original-video'})
    assert request.method=='GET' and request.url.path=='/v1/videos/original-video'
    return httpx.Response(200,json={'status':'done','video':{'url':'https://supplier.example/result.mp4'}})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(reply),**kw)
async def archive(url):
    assert url=='https://supplier.example/result.mp4'
    (Path(main.OUTPUT_DIR)/'queued-video.mp4').write_bytes(b'owned result')
    return '/output/queued-video.mp4'
main.save_remote_video_to_output=archive
main.CANVAS_VIDEO_TASKS.archive=archive
async def restart():
    await main.startup_event()
    try:
        task_id=id_path.read_text()
        async with asyncio.timeout(10):
            while main.CANVAS_TASK_JOURNAL.get(task_id)['status']=='queued' or main.CANVAS_TASK_DISPATCH.active:
                await asyncio.sleep(.02)
        record=main.CANVAS_TASK_JOURNAL.get(task_id)
        assert record['status']=='succeeded',record
        receipt=record['provider_receipts'][0]
        assert receipt['upstream_task_id']=='original-video' and receipt['video_query_mode']=='zhenzhen-videos-v1',receipt
        assert record['result']['videos']==['/output/queued-video.mp4'],record
        assert calls==[('POST','/v1/videos'),('GET','/v1/videos/original-video')],calls
        assert not main.CANVAS_TASK_DISPATCH.inputs._path(task_id).exists()
    finally:await main.shutdown_task_recovery()
asyncio.run(restart())
'''
    second=invoke(tmp_path,reader)
    assert second.returncode==0,second.stdout+second.stderr
    final=setup+r'''
def reject(request):
    raise AssertionError('completed video contacted supplier after reopening')
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(reject),**kw)
async def reopen():
    await main.startup_event()
    try:
        await asyncio.sleep(.1)
        result=await main.get_canvas_video_task(id_path.read_text())
        assert result['status']=='succeeded' and result['result']['videos']==['/output/queued-video.mp4'],result
        assert (Path(main.OUTPUT_DIR)/'queued-video.mp4').read_bytes()==b'owned result'
        assert not main.CANVAS_TASK_DISPATCH.active
    finally:await main.shutdown_task_recovery()
asyncio.run(reopen())
'''
    third=invoke(tmp_path,final)
    assert third.returncode==0,third.stdout+third.stderr
