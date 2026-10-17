"""Actual RunningHub video accepted -> process exit -> original query POST only."""
import os
from pathlib import Path
import subprocess
import sys

from enterprise.tests.test_canvas_image_recovery_main import ROOT, BOOTSTRAP


SETUP=BOOTSTRAP+r'''
from enterprise import db
provider={'id':'runninghub','name':'RunningHub fixture','base_url':'https://rh-fixture.invalid',
          'protocol':'runninghub','video_models':['video-fixture']}
main.save_api_providers([provider])
provider=main.get_api_provider_exact('runninghub')
main.get_api_provider=lambda _:provider
main.runninghub_api_key=lambda *args,**kwargs:'fixture-only-key'
async def definition(*args): return {'endpoint':'video-fixture','params':[]}
main.runninghub_model_definition=definition
db.get_user_by_id=lambda _:{'id':'fixture-alice'}
db.get_task_owner=lambda *_:'fixture-alice'
db.record_canvas_image_task_owner=lambda *_:None
db.record_task_owner=lambda *args,**kwargs:None
db.get_canvas_image_task_owner=lambda _:'fixture-alice'
'''


def private_install(tmp_path):
    install=tmp_path/'install'
    app=install/'releases/fixture'
    (app/'static').mkdir(parents=True)
    (app/'main.py').write_text('# fixture',encoding='utf-8')
    return [str(ROOT),str(install),str(tmp_path/'local')]


def process(script,args):
    return subprocess.run([sys.executable,'-c',script,*args],cwd=ROOT,
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1'),
        capture_output=True,text=True,timeout=40)


def test_runninghub_accepted_id_restart_and_archive_retry_never_recreate_task(tmp_path):
    args=private_install(tmp_path)
    writer=SETUP+r'''
def submit(request):
    calls.append((request.method,request.url.path))
    assert request.method=='POST' and request.url.path=='/openapi/v2/video-fixture'
    assert request.headers['authorization']=='Bearer fixture-only-key'
    return httpx.Response(200,json={'taskId':'original-paid-rh','status':'RUNNING','results':None})
main.httpx.AsyncClient=lambda **kwargs:original_client(transport=httpx.MockTransport(submit),**kwargs)
async def exit_after_acceptance(*args):
    record=main.CANVAS_TASK_JOURNAL.get(id_path.read_text())
    receipt=record['provider_receipts'][0]
    assert receipt['upstream_task_id']=='original-paid-rh' and receipt['video_query_mode']=='runninghub-v2'
    assert 'fixture-only-key' not in json.dumps(record) and 'private-prompt' not in json.dumps(record)
    assert calls==[('POST','/openapi/v2/video-fixture')]
    os._exit(17)
main.wait_for_runninghub_openapi_task=exit_after_acceptance
async def create():
    response=await main.create_canvas_video_task(main.CanvasVideoRequest(provider_id='runninghub',model='video-fixture',prompt='private-prompt'),'fixture-alice')
    id_path.write_text(response['task_id'])
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
asyncio.run(create())
'''
    first=process(writer,args)
    assert first.returncode==17,first.stdout+first.stderr
    reader=SETUP+r'''
phase=0
def query(request):
    global phase
    calls.append((request.method,request.url.path))
    assert request.method=='POST' and request.url.path=='/openapi/v2/query', 'recovery submitted a generation'
    assert json.loads(request.content)=={'taskId':'original-paid-rh'}
    phase+=1
    return httpx.Response(200,json={'taskId':'original-paid-rh','status':'QUEUED' if phase==1 else 'SUCCESS',
        'results':None if phase==1 else [{'url':'https://cdn.invalid/clip.mp4','outputType':'mp4'},
                                     {'url':'https://cdn.invalid/thumb.jpg','outputType':'jpg'}]})
main.httpx.AsyncClient=lambda **kwargs:original_client(transport=httpx.MockTransport(query),**kwargs)
archive_calls=[]
async def archive(url):
    archive_calls.append(url)
    assert url=='https://cdn.invalid/clip.mp4'
    if len(archive_calls)==1: raise OSError('fixture disk unavailable')
    (Path(main.OUTPUT_DIR)/'rh-recovered.mp4').write_bytes(b'fixture-video')
    return '/output/rh-recovered.mp4'
main.CANVAS_VIDEO_TASKS.archive=archive
main.CANVAS_ACCEPTED_RECOVERY.poll_delay=.02
async def recover():
    await main.startup_event()
    try:
        key=id_path.read_text()
        async with asyncio.timeout(8):
            while (await main.get_canvas_video_task(key))['status']!='succeeded': await asyncio.sleep(.01)
        result=(await main.get_canvas_video_task(key))['result']
        assert result['videos']==['/output/rh-recovered.mp4']
        assert len(calls)==3 and len(archive_calls)==2,calls
        assert (await main.reconcile_canvas_video_task(key))['videos']==result['videos']
        assert len(calls)==3
    finally: await main.shutdown_task_recovery()
asyncio.run(recover())
print('RunningHub restart: 3 query POST, 0 generation POST; archive retry succeeded')
'''
    second=process(reader,args)
    assert second.returncode==0,second.stdout+second.stderr
    assert '3 query POST, 0 generation POST' in second.stdout


def test_runninghub_http_auth_and_unknown_status_pause_without_new_generation(tmp_path):
    args=private_install(tmp_path)
    script=SETUP+r'''
from enterprise.canvas_image_recovery import provider_scope
from enterprise.canvas_task_journal import CanvasTaskJournal
case='auth'
def query(request):
    calls.append((request.method,request.url.path))
    assert request.url.path=='/openapi/v2/query'
    return httpx.Response(401) if case=='auth' else httpx.Response(200,json={'status':'FUTURE_STATE'})
main.httpx.AsyncClient=lambda **kwargs:original_client(transport=httpx.MockTransport(query),**kwargs)
async def scenario():
    global case
    for case in ['auth','unknown','changed']:
        key='rh-'+case
        record={'id':key,'type':'video','status':'failed','provider_id':'runninghub','model':'video-fixture','recovery_required':True,
                'provider_receipts':[{'index':0,'state':'accepted','upstream_task_id':'original-paid-rh',**provider_scope(provider),
                                     'video_query_mode':'runninghub-v2','video_v2':True}]}
        main.CANVAS_TASK_JOURNAL.create(record)
        if case=='changed': main.CANVAS_VIDEO_TASKS.resolve_provider=lambda _:{**provider,'base_url':'https://replacement.invalid'}
        result=await main.reconcile_canvas_video_task(key)
        assert result['status']=='manual',result
    assert calls==[('POST','/openapi/v2/query')]*2,calls
asyncio.run(scenario())
'''
    result=process(script,args)
    assert result.returncode==0,result.stdout+result.stderr
