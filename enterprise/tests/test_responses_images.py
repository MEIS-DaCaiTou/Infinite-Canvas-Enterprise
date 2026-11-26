"""Responses transport and durable acceptance boundary; no external service."""
import ast
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from enterprise.providers.responses_images import image_body, query_state, submit, task_endpoint


@pytest.mark.parametrize('size,tool_size,shape',[('1024x1536','1536x1024','PORTRAIT'),
    ('1536x1024','1024x1536','LANDSCAPE'),('1024x1024','1024x1024','SQUARE'),('auto',None,None)])
def test_image_body_preserves_existing_proxy_size_and_reference_order(size,tool_size,shape):
    refs=['data:image/png;base64,YQ==','https://media.invalid/two.png']
    body=image_body('existing-model','keep the product',size,'high',refs,{'background':'transparent'})
    tool=body['tools'][0];assert tool['action']=='edit' and tool['background']=='transparent' and tool['quality']=='high'
    assert tool.get('size')==tool_size
    content=body['input'][0]['content'];assert [item['image_url'] for item in content[1:]]==refs
    if shape:assert shape in content[0]['text']
    else:assert content[0]['text']=='keep the product'
    assert image_body('existing-model','own prompt','auto','',[])['tools'][0]['action']=='generate'


def test_background_acceptance_is_durable_before_first_get():
    events=[]
    async def accepted(task_id,query_endpoint,response):
        assert task_id=='resp-a' and query_endpoint=='https://supplier.invalid/custom/responses/resp-a'
        assert response.headers['x-request-id']=='request-a'
        events.append('saved')
    def reply(request):
        events.append(request.method)
        if request.method=='POST':return httpx.Response(200,json={'status':'queued','id':'resp-a'},headers={'x-request-id':'request-a'})
        assert events==['POST','saved','GET']
        return httpx.Response(200,json={'status':'completed','output':[{'type':'image_generation_call','result':'YQ=='}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            response=await submit(client,'https://supplier.invalid/custom/responses',{}, {},on_accepted=accepted,poll_interval=0)
            assert response.json()['status']=='completed'
    asyncio.run(run());assert events==['POST','saved','GET']


def test_acceptance_write_failure_does_not_query_or_submit_again():
    methods=[]
    async def unavailable(*args):raise OSError('synthetic unavailable receipt')
    def reply(request):
        methods.append(request.method)
        return httpx.Response(200,json={'status':'in_progress','id':'resp-kept'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            with pytest.raises(OSError):
                await submit(client,'https://supplier.invalid/v1/responses',{}, {},on_accepted=unavailable,poll_interval=0)
    asyncio.run(run());assert methods==['POST']


@pytest.mark.parametrize('payload,expected',[
    ({'status':'completed'},'succeeded'),({'status':'queued'},'running'),({'status':'in_progress','output':[{'result':'preview'}]},'running'),
    ({'status':'failed'},'failed'),({'status':'cancelled'},'failed'),({'status':'incomplete'},'failed'),({'output':[{'result':'unconfirmed'}]},'manual')])
def test_query_state_keeps_preview_and_unknown_separate_from_completion(payload,expected):
    assert query_state(payload)==expected


def test_original_response_id_is_encoded_as_one_path_component():
    assert task_endpoint('https://supplier.invalid/custom/responses/','resp/a?#')=='https://supplier.invalid/custom/responses/resp%2Fa%3F%23'


def test_transport_has_no_application_or_storage_dependency():
    path=Path(__file__).parents[1]/'providers/responses_images.py'
    imports=[]
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node,ast.Import):imports.extend(alias.name for alias in node.names)
        elif isinstance(node,ast.ImportFrom):imports.append(node.module)
    assert set(imports)<={'asyncio','json','re','time','urllib.parse','httpx','fractions'}
