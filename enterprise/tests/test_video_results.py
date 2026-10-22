"""Completed video results exclude previews; accepted tasks keep their identity."""
import asyncio
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest

from enterprise.providers.video_outputs import video_output_urls
from enterprise.providers.video_tasks import video_task_result
from enterprise.providers.video_generation import generate_json_video, poll_video
from enterprise.tests.test_canvas_image_recovery_main import BOOTSTRAP, ROOT


def test_result_retains_only_videos_in_legacy_nesting_and_original_order():
    raw = {'status':'completed','data':{'result':{'videos':[
        {'url':'https://media.invalid/one.mp4'},
        {'type':'image','url':'https://media.invalid/opaque-cover'},
        {'url':'https://media.invalid/two?signature=fixture'},
        {'url':'https://media.invalid/one.mp4'},
    ], 'last_frame_url':'https://media.invalid/last', 'preview_url':'https://media.invalid/cover.jpg?sig=fixture',
        'remixed_from_video_id':'https://media.invalid/original.mp4'}}}
    assert video_output_urls(raw) == ['https://media.invalid/one.mp4','https://media.invalid/two?signature=fixture']
    assert video_output_urls({'video_url':'/output/saved.webm'}) == ['/output/saved.webm']
    assert video_output_urls({'preview_url':'https://media.invalid/preview.mp4'}) == ['https://media.invalid/preview.mp4']
    assert video_output_urls({'video_url':'https://media.invalid/final.mp4',
        'preview_url':'https://media.invalid/opaque-cover'}) == ['https://media.invalid/final.mp4']


@pytest.mark.parametrize('status,expected',[('queued','queued'),('RUNNING','running'),('IN_PROGRESS','running')])
def test_pending_task_with_a_preview_is_not_a_completed_video(status,expected):
    raw={'status':status,'video_url':'https://media.invalid/incomplete-preview.mp4'}
    assert video_task_result(raw,video_output_urls,str) == {'status':expected}


def test_cover_and_last_frame_alone_do_not_count_as_completed_video():
    for state in ('running','completed'):
        raw={'status':state,'preview_url':'https://media.invalid/cover.png','last_frame_url':'https://media.invalid/last.png'}
        assert video_output_urls(raw) == []
        assert video_task_result(raw,video_output_urls,str)['status'] == ('running' if state=='running' else 'manual')
    assert video_task_result({'status':'failed','video_url':'https://media.invalid/result.mp4'},video_output_urls,str)['status']=='failed'


def test_accepted_preview_keeps_polling_the_original_task_until_completed(monkeypatch):
    from enterprise.providers import video_generation
    async def no_wait(_):pass
    monkeypatch.setattr(video_generation,'asyncio',SimpleNamespace(sleep=no_wait))
    async def run():
        events=[]; replies=iter([
            {'id':'original','status':'queued','preview_url':'https://media.invalid/preview.mp4'},
            {'status':'running','preview_url':'https://media.invalid/cover.jpg'},
            {'status':'completed','video_url':'https://media.invalid/result.mp4','last_frame_url':'https://media.invalid/last.png'},
        ])
        def respond(request):
            events.append((request.method,request.url.path))
            return httpx.Response(200,json=next(replies))
        async def accepted(task_id,url):events.append(('SAVED',task_id))
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            async def poll(task_id,url):
                assert events[-1]==('SAVED','original')
                return await poll_video(client,['https://supplier.invalid/v1/videos/'+task_id],{},video_output_urls,str,timeout=5,initial_delay=0)
            task,raw,urls=await generate_json_video(client,['https://supplier.invalid/v1/videos'],{}, {},
                extract_task_id=lambda raw:raw.get('id'),output_urls=video_output_urls,accepted=accepted,poll=poll)
        assert task=='original' and raw['status']=='completed' and urls==['https://media.invalid/result.mp4']
        assert events==[('POST','/v1/videos'),('SAVED','original'),('GET','/v1/videos/original'),('GET','/v1/videos/original')]
    asyncio.run(run())


def test_actual_main_does_not_save_an_opaque_image_download_as_mp4(tmp_path):
    install=tmp_path/'install';app=install/'releases/fixture'
    (app/'static').mkdir(parents=True);(app/'main.py').write_text('# owned fixture',encoding='utf8')
    script=BOOTSTRAP+r'''
def reply(request):
    calls.append((request.method,request.url.path))
    return httpx.Response(200,content=b'fixture video' if request.url.path=='/video' else b'fixture cover',
        headers={'Content-Type':'video/mp4' if request.url.path=='/video' else 'image/png'})
main.httpx.AsyncClient=lambda **kwargs:original_client(transport=httpx.MockTransport(reply),**kwargs)
async def check():
    try:await main.save_remote_video_to_output('https://supplier.example/opaque')
    except main.HTTPException as e:
        assert e.status_code==502 and '原任务' in e.detail
    else:raise AssertionError('non-video response was accepted')
    assert not list(Path(main.OUTPUT_OUTPUT_DIR).glob('*.mp4'))
    url=await main.save_remote_video_to_output('https://supplier.example/video')
    assert url.startswith('/assets/output/') and url.endswith('.mp4')
    assert len(list(Path(main.OUTPUT_OUTPUT_DIR).glob('*.mp4')))==1
    assert calls==[('GET','/opaque'),('GET','/video')]
asyncio.run(check())
print('VIDEO_DOWNLOAD_TYPE_PASS')
'''
    run=subprocess.run([sys.executable,'-B','-c',script,str(ROOT),str(install),str(tmp_path/'local')],cwd=ROOT,
        env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=40)
    assert run.returncode==0,run.stdout+run.stderr
    assert 'VIDEO_DOWNLOAD_TYPE_PASS' in run.stdout
