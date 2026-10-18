"""Actual video submit -> hard process exit -> startup GET-only recovery."""
import os
import subprocess
import sys

from enterprise.tests.test_canvas_image_recovery_main import ROOT, BOOTSTRAP


def test_video_receipt_survives_process_exit_and_startup_queries_original_id(tmp_path):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    setup = BOOTSTRAP + r'''
from enterprise import db
db.get_user_by_id = lambda _: {'id':'fixture-alice'}
db.get_task_owner = lambda *_: 'fixture-alice'
db.record_canvas_image_task_owner = lambda *_: None
db.record_task_owner = lambda *args, **kwargs: None
db.get_canvas_image_task_owner = lambda _: 'fixture-alice'
main.provider_env_key_value = lambda _: 'fixture-only-key'
'''
    writer = setup + r'''
async def exit_after_acceptance(client, selected, upstream_id, submit_url=''):
    record = main.CANVAS_TASK_JOURNAL.get(id_path.read_text())
    receipt = record['provider_receipts'][0]
    assert upstream_id == receipt['upstream_task_id'] == 'accepted-before-process-exit'
    assert receipt['video_v2'] and receipt['video_query_mode'] == 'generic' and receipt['provider_base_url'] == provider['base_url']
    assert 'private-prompt' not in json.dumps(record) and 'fixture-only-key' not in json.dumps(record)
    assert calls == [('POST','/v2/videos/generations')], calls
    os._exit(17)
main.wait_for_video_task = exit_after_acceptance
async def create():
    task = await main.create_canvas_video_task(main.CanvasVideoRequest(prompt='private-prompt',provider_id='zhenzhen',model='veo3-fast'), 'fixture-alice')
    id_path.write_text(task['task_id'])
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
asyncio.run(create())
'''
    reader = setup + r'''
phase = 0
def query_handler(request):
    global phase
    calls.append((request.method,request.url.path))
    assert request.method == 'GET', 'recovery must never submit'
    assert request.url.path == '/v2/videos/generations/accepted-before-process-exit'
    phase += 1
    return httpx.Response(200,json={'status':'QUEUED' if phase == 1 else 'SUCCESS', **({} if phase==1 else {'videos':['https://supplier.example/paid.mp4']})})
main.httpx.AsyncClient = lambda **kwargs: original_client(transport=httpx.MockTransport(query_handler), **kwargs)
async def archive(url):
    assert url == 'https://supplier.example/paid.mp4'
    (Path(main.OUTPUT_DIR)/'recovered.mp4').write_bytes(b'isolated-fixture-video')
    return '/output/recovered.mp4'
main.CANVAS_VIDEO_TASKS.archive = archive
main.CANVAS_ACCEPTED_RECOVERY.poll_delay = .02
async def scenario():
    await main.startup_event()
    try:
        task_id = id_path.read_text()
        async with asyncio.timeout(8):
            while (await main.get_canvas_video_task(task_id))['status'] != 'succeeded':
                await asyncio.sleep(.01)
        record = await main.get_canvas_video_task(task_id)
        assert record['result']['videos'] == ['/output/recovered.mp4']
        assert len(calls)==2 and all(method=='GET' for method,_ in calls),calls
        assert (await main.reconcile_canvas_video_task(task_id))['status']=='succeeded'
        assert len(calls)==2
    finally:
        await main.shutdown_task_recovery()
asyncio.run(scenario())
print('video hard-exit recovered: 2 GET, 0 submit POST after restart')
'''
    args = [str(ROOT), str(install), str(tmp_path / "local")]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    first = subprocess.run([sys.executable, "-c", writer, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=40)
    assert first.returncode == 17, first.stdout + first.stderr
    second = subprocess.run([sys.executable, "-c", reader, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=40)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "2 GET, 0 submit POST" in second.stdout


def test_actual_video_query_families_and_v2_first_path(tmp_path):
    install=tmp_path/'install'
    app=install/'releases/fixture'
    (app/'static').mkdir(parents=True)
    (app/'main.py').write_text('# fixture',encoding='utf-8')
    script=BOOTSTRAP+r'''
main.provider_env_key_value=lambda _: 'fixture-only-key'
async def check():
    # Existing local Jimeng CLI has an intentionally empty HTTP Base URL.
    local_provider=main.normalize_provider({'id':'jimeng','protocol':'jimeng','base_url':''})
    main.CANVAS_VIDEO_TASKS.resolve_provider=lambda _:local_provider
    generated=[]
    async def local_generate(payload):
        generated.append(payload.prompt)
        return {'jimeng_pending':True,'submit_id':'existing-cli-submit','kind':'video','message':'queued'}
    main.CANVAS_VIDEO_TASKS.generate=local_generate
    local=await main.create_canvas_video_task(main.CanvasVideoRequest(prompt='local-cli-fixture',provider_id='jimeng'),None)
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    assert generated==['local-cli-fixture']
    local_record=await main.get_canvas_video_task(local['task_id'])
    assert local_record['status']=='jimeng_pending' and local_record['result']['submit_id']=='existing-cli-submit'
    cases=[
      ({'id':'zhenzhen','base_url':'https://supplier.example/v1','protocol':'gemini'},'generic',False,'/v1/videos/generations/original'),
      ({'id':'zhenzhen','base_url':'https://supplier.example/v1','protocol':'gemini'},'generic',True,'/v2/videos/generations/original'),
      ({'id':'fixture','base_url':'https://supplier.example/v1','protocol':'openai'},'generic',True,'/v2/videos/generations/original'),
      ({'id':'fixture','base_url':'https://apihub.agnes-ai.com','protocol':'openai'},'agnes',False,'/agnesapi'),
      ({'id':'fixture','base_url':'https://supplier.example','protocol':'apimart'},'apimart',False,'/v1/tasks/original'),
      ({'id':'fixture','base_url':'https://supplier.example','protocol':'volcengine'},'volcengine',False,'/api/v3/contents/generations/tasks/original'),
      ({'id':'fixture','base_url':'https://yuli.host','protocol':'openai'},'yuli',False,'/v1/videos/original')]
    for selected,mode,v2,path in cases:
        seen=[]
        def reply(request):
            seen.append((request.method,request.url.path))
            assert seen==[('GET',path)],seen
            return httpx.Response(200,json={'status':'SUCCESS','videos':['https://supplier.example/paid.mp4']})
        main.httpx.AsyncClient=lambda **kwargs: original_client(transport=httpx.MockTransport(reply),**kwargs)
        result=await main.inspect_saved_video_task(selected,{'upstream_task_id':'original','model':'video-fixture','video_query_mode':mode,'video_v2':v2})
        assert result['status']=='succeeded' and seen==[('GET',path)]
asyncio.run(check())
'''
    result=subprocess.run([sys.executable,'-c',script,str(ROOT),str(install),str(tmp_path/'local')],cwd=ROOT,
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1'),capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
