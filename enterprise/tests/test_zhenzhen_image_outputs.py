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
from enterprise.providers.zhenzhen import image_body, submit_image
from enterprise.tests.test_canvas_image_recovery_main import BOOTSTRAP, ROOT


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
