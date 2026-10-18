"""Maintained video transport with MockTransport only; no paid calls or keys."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from enterprise.providers import video_generation as transport
from enterprise.providers.video_tasks import inspect_video
from enterprise.providers.zhenzhen import video_headers, video_submit_endpoints
from enterprise.tests.test_canvas_image_recovery_main import BOOTSTRAP, ROOT


def test_request_preserves_existing_fields_without_mutating_sources():
    payload = SimpleNamespace(prompt='fixture', duration=8, watermark=False, aspect_ratio='9:16',
        size='720x1280', resolution='720p', videos=['https://media.invalid/ref.mp4', ''],
        enhance_prompt=True, enable_upsample=True, seed=0, camerafixed=True,
        return_last_frame=True, generate_audio=True)
    images = ['data:image/png;base64,fixture']
    body = transport.json_video_body(payload, 'veo3-fast', images)
    assert body == {'prompt':'fixture', 'model':'veo3-fast', 'duration':8, 'watermark':False,
        'aspect_ratio':'9:16', 'ratio':'9:16', 'size':'720x1280', 'resolution':'720p', 'images':images,
        'videos':['https://media.invalid/ref.mp4'], 'enhance_prompt':True, 'enable_upsample':True,
        'seed':0, 'camerafixed':True, 'return_last_frame':True, 'generate_audio':True}
    assert payload.videos[-1] == '' and len(images) == 1
    assert video_headers('Bearer fixture-key') == {'Accept':'application/json',
        'Content-Type':'application/json', 'Authorization':'Bearer fixture-key'}
    assert video_submit_endpoints('https://supplier.invalid/proxy/') == [
        'https://supplier.invalid/proxy/v2/videos/generations',
        'https://supplier.invalid/proxy/v1/videos/generations']


@pytest.mark.parametrize('reply', ['timeout', 503, 429, '<html>gateway</html>', [], {}])
def test_unknown_submit_never_tries_a_second_paid_endpoint(reply):
    async def run():
        calls = []
        def handler(request):
            calls.append(request)
            if reply == 'timeout':
                raise httpx.ReadTimeout('fixture response lost', request=request)
            if type(reply) is int:
                return httpx.Response(reply, text='fixture rejection')
            if isinstance(reply, str):
                return httpx.Response(200, text=reply)
            return httpx.Response(200, json=reply)
        async def accepted(*_): pass
        async def poll(*_): raise AssertionError('no accepted task')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises((HTTPException, httpx.HTTPError)):
                await transport.generate_json_video(client, video_submit_endpoints('https://supplier.invalid'), {}, {},
                    extract_task_id=lambda raw:raw.get('task_id'), output_urls=lambda raw:raw.get('videos', []),
                    accepted=accepted, poll=poll)
        assert len(calls) == 1 and calls[0].url.path == '/v2/videos/generations'
    asyncio.run(run())


@pytest.mark.parametrize('missing', [404, 405])
def test_explicit_legacy_rejection_keeps_actual_endpoint_and_accepts_before_poll(missing):
    async def run():
        events = []
        def handler(request):
            events.append(('POST', request.url.path))
            return httpx.Response(missing) if len(events) == 1 else httpx.Response(200, json={'task_id':'original'})
        async def accepted(task_id, url): events.append(('SAVED', task_id, url))
        async def poll(task_id, url):
            assert events[-1] == ('SAVED', task_id, url)
            assert url.endswith('/v1/videos/generations')
            return {'videos':['https://media.invalid/result.mp4']}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            key, raw, urls = await transport.generate_json_video(client, video_submit_endpoints('https://supplier.invalid'), {}, {},
                extract_task_id=lambda raw:raw.get('task_id'), output_urls=lambda raw:raw.get('videos', []),
                accepted=accepted, poll=poll)
        assert key == 'original' and urls == raw['videos']
        assert [event[0] for event in events] == ['POST', 'POST', 'SAVED']
    asyncio.run(run())


def test_not_start_is_queued_in_live_poll_and_restart_inspection(monkeypatch):
    async def no_wait(_): pass
    monkeypatch.setattr(transport, 'asyncio', SimpleNamespace(sleep=no_wait))
    async def run():
        replies = iter([{'status':'NOT_START'}, {'status':'IN_PROGRESS'},
            {'status':'SUCCESS', 'data':{'output':'https://media.invalid/result.mp4'}}])
        calls = []
        def handler(request):
            calls.append((request.method, request.url.path))
            return httpx.Response(200, json=next(replies))
        output_urls = lambda raw: [raw['data']['output']] if raw.get('data', {}).get('output') else []
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            raw = await transport.poll_video(client, ['https://supplier.invalid/v2/videos/generations/original'], {},
                output_urls, str, timeout=10, initial_delay=2)
        assert output_urls(raw) == ['https://media.invalid/result.mp4']
        assert calls == [('GET','/v2/videos/generations/original')] * 3
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'status':'NOT_START'}))) as client:
            assert (await inspect_video(client, ['https://supplier.invalid/original'], {}, output_urls, str))['status'] == 'queued'
    asyncio.run(run())


def test_actual_main_uses_bearer_v2_and_persists_before_not_start_query(tmp_path):
    install = tmp_path/'install'
    app = install/'releases/fixture'
    (app/'static').mkdir(parents=True)
    (app/'main.py').write_text('# fixture', encoding='utf-8')
    script = BOOTSTRAP + r'''
from types import SimpleNamespace
from enterprise.providers import video_generation
from enterprise import db
provider['protocol']='gemini'  # Image/chat protocol must not change unified video auth.
main.provider_env_key_value=lambda _: 'fixture-only-key'
db.record_canvas_image_task_owner=lambda *_:None
db.record_task_owner=lambda *args, **kwargs:None
async def no_wait(_):pass
video_generation.asyncio=SimpleNamespace(sleep=no_wait)
step=0
def reply(request):
    global step
    calls.append((request.method, request.url.path))
    assert request.headers['authorization']=='Bearer fixture-only-key'
    assert 'x-goog-api-key' not in request.headers
    if request.method=='POST':
        assert request.url.path=='/v2/videos/generations'
        body=json.loads(request.content)
        assert body['model']=='veo3-fast' and body['seed']==0
        return httpx.Response(200,json={'task_id':'accepted-video'})
    receipt=main.CANVAS_TASK_JOURNAL.get(id_path.read_text())['provider_receipts'][0]
    assert receipt['upstream_task_id']=='accepted-video' and receipt['video_v2']
    assert receipt['video_query_mode']=='generic'
    assert 'fixture-only-key' not in json.dumps(receipt)
    assert request.url.path=='/v2/videos/generations/accepted-video'
    step+=1
    return httpx.Response(200,json={'status':'NOT_START'} if step==1 else
        {'status':'SUCCESS','data':{'output':'https://supplier.example/result.mp4'}})
main.httpx.AsyncClient=lambda **kwargs: original_client(transport=httpx.MockTransport(reply), **kwargs)
async def archive(url):
    assert url=='https://supplier.example/result.mp4'
    (Path(main.OUTPUT_DIR)/'fixture.mp4').write_bytes(b'fixture')
    return '/output/fixture.mp4'
main.save_remote_video_to_output=archive
async def run():
    task=await main.create_canvas_video_task(main.CanvasVideoRequest(prompt='private-prompt',provider_id='zhenzhen',model='veo3-fast',seed=0),None)
    id_path.write_text(task['task_id'])
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    record=main.CANVAS_TASK_JOURNAL.get(task['task_id'])
    assert record['status']=='succeeded',record
    assert record['result']['videos']==['/output/fixture.mp4']
    assert calls==[('POST','/v2/videos/generations'),('GET','/v2/videos/generations/accepted-video'),('GET','/v2/videos/generations/accepted-video')]
asyncio.run(run())
print('one v2 submit, durable acceptance, NOT_START -> success, local archive')
'''
    result = subprocess.run([sys.executable,'-c',script,str(ROOT),str(install),str(tmp_path/'local')],
        cwd=ROOT,env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'),
        capture_output=True,text=True,encoding='utf-8',timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
