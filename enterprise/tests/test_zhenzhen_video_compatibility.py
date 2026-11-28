"""Production routing regression and no-charge preflight/transport scenarios."""
import ast
import asyncio
import base64
from io import BytesIO
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import HTTPException
from PIL import Image
import pytest

from enterprise.providers import zhenzhen_video as adapter
from enterprise.providers.zhenzhen import is_zhenzhen
from enterprise.providers.zhenzhen_video_execution import execute
from enterprise.providers.video_outputs import video_output_urls
from enterprise.providers.video_tasks import video_task_result
from enterprise.video_reference_preparation import VideoReferencePreparation, VideoReference

ROOT = Path(__file__).resolve().parents[2]


def payload(**changes):
    values = dict(model='doubao-seedance-2.0-mini', prompt='owned fixture', duration=4,
        aspect_ratio='16:9', resolution='', video_channel='', images=[], videos=[], audios=[],
        enhance_prompt=False, enable_upsample=False, camerafixed=False, return_last_frame=False,
        watermark=False, generate_audio=False, multimodal=False, seed=None)
    return SimpleNamespace(**(values | changes))


def png():
    stream = BytesIO()
    Image.new('RGBA', (64, 48), (100, 110, 120, 200)).save(stream, 'PNG')
    return stream.getvalue()


def reference(content=None):
    return {'url': 'data:image/png;base64,' + base64.b64encode(content or png()).decode()}


def test_workshop_host_with_legacy_async_protocol_cannot_enter_apimart():
    tree = ast.parse((ROOT/'main.py').read_text(encoding='utf-8'))
    names = {'provider_protocol', 'is_apimart_provider'}
    scope = {'is_zhenzhen': is_zhenzhen}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
        and n.name in names], type_ignores=[]), 'main.py', 'exec'), scope)
    assert not scope['is_apimart_provider']({'base_url': 'https://ai.t8star.org', 'protocol': 'apimart'})
    assert scope['is_apimart_provider']({'base_url': 'https://api.apimart.ai/v1', 'protocol': 'apimart'})


@pytest.mark.parametrize('change', [{'duration': 3}, {'duration': 5}, {'resolution': '1080p'},
    {'images': [reference()]*10}, {'multimodal': True, 'images': [{'url':'x','role':'first_frame'}]}])
def test_mini_invalid_choices_are_rejected_before_any_upload_or_generation(change):
    async def run():
        def forbidden(_): pytest.fail('invalid inputs must not make HTTP requests')
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
            with pytest.raises(HTTPException) as exc:
                await execute(client, {}, payload(**change), base='https://supplier.invalid', headers={},
                    resolve_file=lambda *_:None, accepted=None, poll=None, archive=None)
        assert exc.value.status_code == 400
    asyncio.run(run())


@pytest.mark.parametrize('bad', ['missing', 'corrupt-image', 'video-is-audio'])
def test_all_media_are_decoded_before_the_first_upload(tmp_path, bad):
    good = tmp_path/'good.png';good.write_bytes(png())
    broken = tmp_path/'broken.png'
    if bad != 'missing': broken.write_bytes(b'not an image or video')
    p = payload(model='doubao-seedance-2.5', duration=5, multimodal=True,
        images=[{'url':'/assets/good.png'}, {'url':'/assets/broken.png'}])
    if bad == 'video-is-audio':
        p.images = p.images[:1];p.videos = ['/assets/broken.png']
    resolve = lambda ref, kind: tmp_path/Path(ref['url']).name
    prep = VideoReferencePreparation(resolve, probe=lambda _: {
        'streams':[{'codec_type':'audio'}], 'format':{'duration':'3','format_name':'mp3'}})
    async def run():
        def forbidden(_): pytest.fail('no partial uploads when a later input is invalid')
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
            with pytest.raises(HTTPException):
                await execute(client, {}, p, base='https://supplier.invalid', headers={},
                    resolve_file=resolve, accepted=None, poll=None, archive=None, preparation=prep)
    asyncio.run(run())


def test_native_seedance_preserves_all_image_and_audio_slots_after_upload():
    p = payload(model='doubao-seedance-2.5', duration=5, multimodal=True,
        images=[reference() for _ in range(10)], audios=['/assets/audio.mp3']*5)
    prepared = [VideoReference('image','/assets/image.png',png(),'image.png','image/png') for _ in p.images]
    prepared += [VideoReference('audio','/assets/audio.mp3',b'audio','audio.mp3','audio/mpeg',duration=3) for _ in p.audios]
    async def prepare(*_): return prepared
    async def run():
        events=[]
        def reply(request):
            if request.url.path == '/v1/files':
                events.append('upload');return httpx.Response(200,json={'url':'https://media.invalid/input'})
            assert request.url.path == '/seedance/v3/contents/generations/tasks'
            body=json.loads(request.content)
            assert len([x for x in body['content'] if x['type']=='image_url']) == 10
            assert len([x for x in body['content'] if x['type']=='audio_url']) == 5
            assert all(x.get('role')=='reference_image' for x in body['content'] if x['type']=='image_url')
            events.append('generate');return httpx.Response(200,json={'id':'original'})
        async def accepted(task,url,mode):
            assert task=='original' and mode==adapter.SEEDANCE;events.append('saved')
        async def poll(task,url):
            assert events[-1]=='saved';events.append('query')
            return {'status':'succeeded','content':{'video_url':'https://media.invalid/output.mp4'}}
        async def archive(url):return '/output/result.mp4'
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            result=await execute(client,{},p,base='https://supplier.invalid',headers={'Authorization':'Bearer fixture'},
                resolve_file=lambda *_:None,accepted=accepted,poll=poll,archive=archive,
                preparation=SimpleNamespace(prepare=prepare))
        assert events.count('generate')==1 and result['videos']==['/output/result.mp4']
        assert events[-3:]==['generate','saved','query']
    asyncio.run(run())


def test_grok_new_uses_one_multipart_generation_and_no_apimart_upload():
    p=payload(model='grok-1.5-video-6s',duration=6,images=[reference()])
    async def run():
        calls=[]
        def reply(request):
            calls.append(request.url.path)
            assert request.url.path=='/v1/videos'
            assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
            assert b'name="input_reference"' in request.content and b'1280x720' in request.content
            return httpx.Response(200,json={'task_id':'new-grok'})
        async def accepted(*_): pass
        async def poll(*_):return {'status':'done','video':{'url':'https://media.invalid/out.mp4'}}
        async def archive(url):return '/output/out.mp4'
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            await execute(client,{},p,base='https://supplier.invalid',headers={'Content-Type':'application/json'},
                resolve_file=lambda *_:None,accepted=accepted,poll=poll,archive=archive)
        assert calls==['/v1/videos']
    asyncio.run(run())


def test_sora_group_is_explicit_and_keeps_incompatible_durations_separate():
    with pytest.raises(HTTPException,match='通道'):
        adapter.validate_request(payload(model='sora-2',duration=4), 'sora-2')
    assert adapter.validate_request(payload(model='sora-2',duration=4,video_channel='official'),'sora-2')['route']==adapter.V1
    assert adapter.validate_request(payload(model='sora-2',duration=15,video_channel='compatible'),'sora-2')['route']==adapter.V2
    with pytest.raises(HTTPException):
        adapter.validate_request(payload(model='sora-2',duration=15,video_channel='official'),'sora-2')


def test_vidu_state_and_creations_do_not_turn_cover_images_into_videos():
    assert video_task_result({'state':'queueing'},video_output_urls,str)['status']=='queued'
    result=video_task_result({'state':'success','creations':[{'url':'https://media.invalid/video.mp4',
        'cover_url':'https://media.invalid/cover.png'}]},video_output_urls,str)
    assert result['remote_urls']==['https://media.invalid/video.mp4']
    assert adapter.query_endpoints('https://supplier.invalid','original',mode=adapter.VIDU)==[
        'https://supplier.invalid/vidu/v2/tasks/original/creations']


def test_unsupported_model_is_visible_but_never_submitted():
    profile=adapter.public_video_profiles({'id':'zhenzhen','video_models':['undocumented-video']})
    assert profile['undocumented-video']['supported'] is False
    with pytest.raises(HTTPException,match='尚未适配'):
        adapter.validate_request(payload(model='undocumented-video'),'undocumented-video')


def test_frontend_uses_the_actual_python_capabilities():
    profiles = adapter.public_video_profiles({'id':'zhenzhen',
        'video_models':[*adapter.PROFILES, 'not-adapted']})
    result = subprocess.run(['node',str(ROOT/'enterprise/tests/test_video_model_choices.js')],
        input=json.dumps(profiles),capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_failed_workshop_file_upload_never_submits_generation():
    async def run():
        calls=[]
        def reply(request):
            calls.append(request.url.path)
            return httpx.Response(404,json={'error':'upload not found'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            with pytest.raises(HTTPException,match='未提交视频生成'):
                await execute(client,{},payload(images=[reference()]),base='https://supplier.invalid',headers={},
                    resolve_file=lambda *_:None,accepted=None,poll=None,archive=None)
        assert calls == ['/v1/files']
    asyncio.run(run())


@pytest.mark.parametrize('durations', [[31], [16,16]])
def test_real_media_duration_checks_precede_uploads(tmp_path, durations):
    files=[]
    for i,duration in enumerate(durations):
        file=tmp_path/f'clip-{i}.mp4';file.write_bytes(b'fixture-container');files.append(str(file))
    prep=VideoReferencePreparation(lambda ref,_:ref['url'],probe=lambda path:{
        'streams':[{'codec_type':'video','width':1280,'height':720}],
        'format':{'duration':durations[files.index(path)],'format_name':'mov,mp4'}})
    async def run():
        with pytest.raises(HTTPException,match='时长'):
            await prep.prepare([],files,[],adapter.PROFILES['doubao-seedance-2.5'])
    asyncio.run(run())


def test_reference_preparation_keeps_original_rgba_bytes():
    content=png()
    prepared=asyncio.run(VideoReferencePreparation(lambda *_:None).prepare([reference(content)],[],[],
        adapter.PROFILES['doubao-seedance-2.0-mini']))
    assert prepared[0].content == content and prepared[0].mime == 'image/png'
    with Image.open(BytesIO(prepared[0].content)) as image:
        assert image.mode == 'RGBA' and image.size == (64,48)
