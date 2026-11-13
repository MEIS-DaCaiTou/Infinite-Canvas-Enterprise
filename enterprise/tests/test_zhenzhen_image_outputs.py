"""Exact image edit/layer contracts and durable multi-result metadata; no paid calls."""
import asyncio
import json
import os
import subprocess
import sys

import httpx
import pytest
from fastapi import HTTPException

from enterprise.providers.image_outputs import layer_metadata
from enterprise.providers.zhenzhen import async_image_submit_url, image_body, submit_image
from enterprise.tests.test_canvas_image_recovery_main import BOOTSTRAP, ROOT


def test_async_opt_in_requires_submit_and_query_to_share_origin_and_route():
    query = "https://supplier.example/tenant/v1/images/tasks/_"
    assert async_image_submit_url("https://supplier.example/tenant/v1/images/edits?route=existing&async=false", query) == (
        "https://supplier.example/tenant/v1/images/edits?route=existing&async=true")
    assert async_image_submit_url("https://supplier.example/tenant/v1/images/generations", query).endswith("?async=true")
    assert async_image_submit_url("https://supplier.example/v1/images/edits", query) is None
    assert async_image_submit_url("https://other.example/tenant/v1/images/edits", query) is None
    assert async_image_submit_url("https://supplier.example/tenant/v1/images/edits",
                                  "https://supplier.example/tenant/v1/videos/_") is None


def test_layer_requires_one_source_and_sends_scalar_image_png_without_quality():
    for refs in ([], ["one", "two"]):
        with pytest.raises(HTTPException):
            image_body("seedream-v5-flash/layer-decomposition", "split", "1024x1024", "high", refs, None)
    assert image_body("seedream-v5-flash/layer-decomposition", "split", "1024x1024", "high", ["data:image/png;base64,owned"], None) == {
        "model": "seedream-v5-flash/layer-decomposition", "prompt": "split", "size": "1024x1024",
        "response_format": "url", "output_format": "png", "image": "data:image/png;base64,owned"}


@pytest.mark.parametrize("failure", [400, 404, 405, 503, "timeout"])
def test_json_edit_selects_one_path_and_does_not_repeat_submission(failure):
    async def run():
        calls = []
        def reply(request):
            calls.append(request)
            if failure == "timeout":
                raise httpx.ReadTimeout("owned lost response", request=request)
            return httpx.Response(failure, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            try:
                result = await submit_image(client, "https://supplier.invalid/proxy/v1/images/generations", {},
                    model="gpt-image-2-all", prompt="owned", size="1024x1024", quality="low",
                    references=["https://media.invalid/a.png", "https://media.invalid/b.png"], aspect_parameters=None,
                    edit_endpoint="https://supplier.invalid/proxy/custom-edit")
                result.raise_for_status()
            except httpx.HTTPError:
                pass
        assert len(calls) == 1 and calls[0].url.path == "/proxy/custom-edit"
        assert json.loads(calls[0].content)["image"] == ["https://media.invalid/a.png", "https://media.invalid/b.png"]
    asyncio.run(run())


@pytest.mark.parametrize("query_failure", ["http", "supplier"])
def test_tracked_edit_keeps_reference_and_queries_only_saved_id(tmp_path, query_failure):
    app = tmp_path / "install/releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = BOOTSTRAP.replace("main.api_headers = lambda **kwargs: {'Authorization':'Bearer fixture-only-key'}\n", "") + r'''
import base64, io
from PIL import Image
from enterprise.generation_tasks import describe_task
buffer=io.BytesIO(); Image.new('RGB',(32,32),'white').save(buffer,format='PNG')
encoded=base64.b64encode(buffer.getvalue()).decode()
reference='data:image/png;base64,'+encoded
failure=sys.argv[4]
task_id='canvas_img_'+'c'*32
provider['image_edit_endpoint']='/v1/images/edits?route=existing&async=false'
provider['protocol']='gemini'  # A shared catalog may also offer native Gemini.
main.save_api_providers([provider])
provider=main.get_api_provider_exact('zhenzhen')
assert provider['protocol']=='gemini'
main.provider_env_key_value=lambda _:'fixture-only-key'
def reply(request):
    calls.append((request.method,request.url.path))
    assert request.headers['authorization']=='Bearer fixture-only-key' and 'x-goog-api-key' not in request.headers
    if request.method == 'POST':
        assert request.url.path == '/v1/images/edits'
        assert dict(request.url.params) == {'route':'existing','async':'true'}
        assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
        assert b'name="image"; filename="reference-1.png"' in request.content
        assert buffer.getvalue() in request.content
        assert b'name="model"\r\n\r\ngpt-image-2-all\r\n' in request.content
        return httpx.Response(200, json={'data':{'task_id':'fixture-edit-accepted'}},
                              headers={'x-request-id':'fixture-edit-request'})
    assert request.method == 'GET' and request.url.path == '/v1/images/tasks/fixture-edit-accepted'
    saved=main.CANVAS_TASK_JOURNAL.get(task_id)['provider_receipts'][0]
    assert saved['upstream_task_id']=='fixture-edit-accepted' and saved['provider_request_id']=='fixture-edit-request'
    if failure == 'http':
        return httpx.Response(503, json={'message':'fixture temporarily unavailable'})
    if failure == 'supplier':
        return httpx.Response(200, json={'data':{'status':'FAILURE','fail_reason':'fixture supplier job failed'}})
    return httpx.Response(200, json={'data':{'status':'SUCCESS','data':{'data':[{'b64_json':encoded}]}}})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(reply),**kw)
async def run():
    global failure
    body=main.OnlineImageRequest(request_id='c'*32, provider_id='zhenzhen',model='gpt-image-2-all',
        prompt='owned edit',size='1024x1024',quality='low',reference_images=[{'url':reference,'kind':'image'}])
    initial=await main.create_canvas_image_task(body,None)
    assert initial['task_id']==task_id
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    record=main.CANVAS_TASK_JOURNAL.get(task_id)
    assert record['status']=='failed'
    detail=describe_task(record,detail=True)
    attempt=detail['attempts'][0]
    assert attempt['upstream_task_id']=='fixture-edit-accepted'
    if failure=='supplier':
        assert detail['status']=='failed' and not detail['can_query'] and attempt['status']=='failed'
        assert 'fixture supplier job failed' in detail['error']
        assert len(calls)==2
    else:
        assert detail['status']=='unknown' and detail['can_query'] and attempt['status']=='unknown'
        assert len(calls)==4
        failure=None
        result=await main.reconcile_canvas_image_task(task_id)
        assert result['status']=='succeeded'
        with Image.open(main.output_file_from_url(result['images'][0])) as output:
            assert output.size==(32,32)
        assert len(calls)==5
    assert [path for method,path in calls if method=='POST']==['/v1/images/edits']
asyncio.run(run())
'''
    result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(tmp_path / "install"),
                             str(tmp_path / "local"), query_failure], cwd=ROOT,
                            env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
                            capture_output=True, encoding="utf-8", timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr


def test_representative_models_keep_their_request_shapes_with_async_receipts(tmp_path):
    app = tmp_path / "install/releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = BOOTSTRAP + r'''
import base64, io
from PIL import Image
sample=io.BytesIO()
Image.new('RGB',(32,32),'white').save(sample,format='PNG')
encoded=base64.b64encode(sample.getvalue()).decode()
reference='data:image/png;base64,'+encoded
models={
    'gpt-image-2':{'size':'2048x2048','quality':'low'},
    'nano-banana-2':{'aspect_ratio':'16:9','image_size':'2K'},
    'nano-banana-pro':{'aspect_ratio':'16:9','image_size':'4K'},
    'seedream-v5-pro':{'size':'2048x2048'},
}
current=None
def reply(request):
    calls.append((request.method,request.url.path))
    if request.method=='POST':
        assert request.url.path=='/v1/images/generations' and request.url.params['async']=='true'
        body=json.loads(request.content)
        assert body=={'model':current,'prompt':'fixture model routing','response_format':'url',
            'image':[reference],**models[current]},body
        return httpx.Response(200,json={'task_id':'fixture-'+current})
    assert request.method=='GET' and request.url.path=='/v1/images/tasks/fixture-'+current
    return httpx.Response(200,json={'data':{'status':'SUCCESS','data':{'data':[{'b64_json':encoded}]}}})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(reply),**kw)
async def run():
    global current
    for current in models:
        receipt=await main.create_canvas_image_task(main.OnlineImageRequest(
            provider_id='zhenzhen', model=current, prompt='fixture model routing', size='2048x2048',
            quality='low', aspect_ratio='16:9',resolution='4K' if current=='nano-banana-pro' else '2K',
            reference_images=[{'url':reference,'kind':'image'}]),None)
        await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
        record=await main.get_canvas_image_task(receipt['task_id'])
        assert record['status']=='succeeded' and record['upstream_task_id']=='fixture-'+current,record
        assert Path(main.output_file_from_url(record['result']['images'][0])).is_file()
    assert [method for method,_ in calls]==['POST','GET']*len(models)
asyncio.run(run())
'''
    result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(tmp_path / "install"),
                             str(tmp_path / "local")], cwd=ROOT,
                            env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
                            capture_output=True, encoding="utf-8", timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr


def test_layer_metadata_is_bounded_and_ignores_arbitrary_upstream_fields():
    meta = layer_metadata({"z_index": 0, "name": "x" * 400, "description": "y" * 2000,
        "bounding_box": {"absolute": [0, 1, 3, 4], "normalized": [0, 0, 1, float("nan")], "private": "ignored"}, "api_key": "never-copy"})
    assert meta == {"z_index": 0, "name": "x" * 160, "description": "y" * 1000,
                    "bounding_box": {"absolute": [0, 1, 3, 4]}}
    assert layer_metadata({"z_index": True}) == {}


def test_actual_image_task_archives_all_layers_and_keeps_metadata_after_reopen(tmp_path):
    app = tmp_path / "install/releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# owned", encoding="utf-8")
    script = BOOTSTRAP + r'''
import base64, io
from PIL import Image
from enterprise.generation_tasks import describe_task
buf=io.BytesIO();Image.new('RGBA',(8,8),(255,0,0,80)).save(buf,format='PNG');encoded=base64.b64encode(buf.getvalue()).decode()
model='seedream-v5-flash/layer-decomposition'
provider['image_models']=[model]
main.provider_env_key_value=lambda _:'fixture-only-key'
wrapped=main.extract_images({'result':{'images':[{'url':'https://media.invalid/layer.png','b64_json':encoded,'z_index':0,'name':'layer 0'}]}})
assert len(wrapped)==1 and wrapped[0]['z_index']==0 and wrapped[0]['type']=='url',wrapped
listed=main.extract_images({'result':{'images':[{'url':['https://media.invalid/a.png','https://media.invalid/b.png']}]}})
assert len(listed)==2,listed
listed=main.extract_images({'result':{'images':[{'url':['https://media.invalid/a.png','https://media.invalid/b.png'],'z_index':0,'name':'layer 0'}]}})
assert len(listed)==2 and all(i.get('z_index')==0 for i in listed),listed
def response(request):
    calls.append((request.method,request.url.path))
    assert request.method=='POST' and request.url.path=='/v1/images/generations'
    body=json.loads(request.content)
    assert isinstance(body['image'],str) and body['output_format']=='png' and 'quality' not in body
    return httpx.Response(200,json={'data':[{'b64_json':encoded,'z_index':i,'name':'layer '+str(i),
        'bounding_box':{'absolute':[0,0,8,8],'normalized':[0,0,1,1]}} for i in range(2)]})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(response),**kw)
async def run():
    request=main.OnlineImageRequest(provider_id='zhenzhen',model=model,prompt='split',reference_images=[{'url':'data:image/png;base64,'+encoded,'kind':'image'}])
    task=await main.create_canvas_image_task(request,None)
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    record=main.CANVAS_TASK_JOURNAL.get(task['task_id'])
    assert record['status']=='succeeded',record
    # Identical pixel data can be distinct semantic layers, so both must survive.
    assert len(record['result']['images'])==2,record
    assert [i['z_index'] for i in record['result']['image_items']]==[0,1]
    assert [i['name'] for i in describe_task(record,detail=True)['items']]==['layer 0','layer 1']
    from enterprise.canvas_task_journal import CanvasTaskJournal
    reopened=CanvasTaskJournal(main.CANVAS_TASK_JOURNAL.root).get(task['task_id'])
    assert reopened['result']['image_items']==record['result']['image_items']
    assert len(calls)==1
    for url in record['result']['images']:
        with Image.open(main.output_file_from_url(url)) as image:assert image.mode=='RGBA'
asyncio.run(run())
'''
    result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(tmp_path / "install"), str(tmp_path / "local")],
        cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"), capture_output=True,
        text=True, encoding="utf-8", timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
