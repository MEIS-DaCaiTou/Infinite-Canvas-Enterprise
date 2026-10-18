"""Actual HTTP submit, hard exit and a new process reading/restoring original text."""
import os
import subprocess
import sys

import pytest
from enterprise.tests.test_canvas_image_recovery_main import ROOT, BOOTSTRAP


@pytest.mark.parametrize('phase,exit_code',[('lost',17),('received',18),('complete',0)])
def test_actual_text_http_boundary_and_restart_never_resubmits(tmp_path,phase,exit_code):
    install=tmp_path/'install';app=install/'releases/fixture'
    (app/'static').mkdir(parents=True);(app/'main.py').write_text('# private fixture',encoding='utf-8')
    writer=BOOTSTRAP+r'''
phase=sys.argv[4]
provider['chat_models']=['text-fixture']
def text_handler(request):
    calls.append((request.method,request.url.path))
    assert calls==[('POST','/v1/chat/completions')],calls
    record=main.CANVAS_TASK_JOURNAL.get(id_path.read_text())
    assert record['provider_receipts'][0]['state']=='submitting'
    if phase=='lost':os._exit(17)
    return httpx.Response(200,json={'choices':[{'message':{'content':'durable text'}}],
        'usage':{'prompt_tokens':3,'completion_tokens':5}})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(text_handler),**kw)
if phase=='received':main.CANVAS_LLM_TASKS.archive=lambda text:os._exit(18)
async def write():
    accepted=await main.create_canvas_llm_task(main.CanvasLLMTaskRequest(
        request_id='1'*32,message='private-input',model='text-fixture',provider='zhenzhen'),None)
    id_path.write_text(accepted['task_id'])
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    record=main.CANVAS_TASK_JOURNAL.get(accepted['task_id'])
    assert record['status']=='succeeded' and record['result']['text']=='durable text'
    assert record['provider_receipts'][0]['reported_usage']=={'prompt_tokens':3,'completion_tokens':5}
    assert 'private-input' not in json.dumps(record) and 'fixture-only-key' not in json.dumps(record)
asyncio.run(write())
'''
    reader=BOOTSTRAP+r'''
phase=sys.argv[4]
def never_submit(request):raise AssertionError('restart attempted a provider request')
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(never_submit),**kw)
async def read():
    await main.startup_event()
    try:
        record=await main.get_canvas_llm_task(id_path.read_text())
        if phase=='lost':
            assert record['status']=='failed' and record['recovery_required']
            assert record['result'] is None
        else:
            assert record['status']=='succeeded' and record['result']['text']=='durable text'
            path=main.output_file_from_url(record['result']['items'][0]['url'])
            assert Path(path).read_text(encoding='utf-8')=='durable text'
        assert not calls
    finally:await main.shutdown_task_recovery()
asyncio.run(read())
'''
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
    args=[str(ROOT),str(install),str(tmp_path/'local'),phase]
    first=subprocess.run([sys.executable,'-B','-c',writer,*args],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=40)
    assert first.returncode==exit_code,first.stdout+first.stderr
    second=subprocess.run([sys.executable,'-B','-c',reader,*args],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=40)
    assert second.returncode==0,second.stdout+second.stderr
