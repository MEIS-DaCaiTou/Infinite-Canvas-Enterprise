"""Exercise real HTTP encoding and paid-submit boundaries without vendor calls."""
import asyncio
import ast
from contextlib import asynccontextmanager
import json
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from enterprise.providers.openai_images import submit_image, submit_json_image


def exercise(reply, *, references=False, **options):
    calls, material_reads = [], []
    closed=[False]

    @asynccontextmanager
    async def parts():
        try:
            yield [('image',('one.png',b'first','image/png'))]
        finally:
            closed[0]=True

    async def urls():
        assert closed[0], 'legacy file handles must close before the JSON alternative'
        material_reads.append(True)
        return ['data:image/png;base64,YQ==', 'data:image/png;base64,Yg==']

    def tracked(request):
        calls.append(request)
        return reply(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(tracked)) as client:
            return await submit_image(client, 'https://supplier.invalid/v1/images/generations',
                'https://supplier.invalid/v1/images/edits', headers={'Authorization':'Bearer synthetic'},
                edit_headers={'Authorization':'Bearer synthetic'}, model='existing-image', prompt='keep the product',
                size='1024x1024', quality='high', edit_files=parts() if references else None,
                reference_urls=urls if references else None, **options)
    return run, calls, material_reads


def success(request):
    return httpx.Response(200, json={'data':[{'url':'https://media.invalid/result.png'}]}, request=request)


@pytest.mark.parametrize('gpt2', [False, True])
def test_text_generation_fields_keep_protocol_family(gpt2):
    run,calls,reads=exercise(success,gpt2=gpt2,background={'background':'transparent','output_format':'png'})
    assert asyncio.run(run()).status_code==200
    body=json.loads(calls[0].content)
    assert len(calls)==1 and not reads and body['size']=='1024x1024' and body['quality']=='high'
    assert body['background']=='transparent' and body['output_format']=='png'
    assert ('response_format' in body)==(not gpt2) and ('n' in body)==(not gpt2)


def test_multipart_uses_supplied_file_parts_and_keeps_material_lazy():
    run,calls,reads=exercise(success,references=True)
    asyncio.run(run())
    assert len(calls)==1 and calls[0].url.path.endswith('/edits') and not reads
    assert calls[0].headers['content-type'].startswith('multipart/form-data; boundary=')
    assert b'name="image"; filename="one.png"' in calls[0].content
    assert b'name="quality"\r\n\r\nhigh' in calls[0].content


@pytest.mark.parametrize('status,text',[(401,'invalid token'),(429,'saturated'),(503,'images api is not supported'),
    (400,'unsupported size'),(404,'not found')])
def test_unproven_rejection_does_not_switch_or_rebuild_material(status,text):
    run,calls,reads=exercise(lambda req:httpx.Response(status,text=text,request=req),references=True)
    assert asyncio.run(run()).status_code==status
    assert len(calls)==1 and not reads


def test_lost_edit_reply_keeps_unknown_and_one_post():
    def lost(request):
        raise httpx.ReadTimeout('synthetic interrupted response',request=request)
    run,calls,reads=exercise(lost,references=True)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(run())
    assert failure.value.submission_unknown and len(calls)==1 and not reads


def test_proven_unsupported_edit_switches_once_to_existing_json_format():
    def reply(request):
        if request.url.path.endswith('/edits'):
            return httpx.Response(404,text='images api is not supported',request=request)
        return success(request)
    run,calls,reads=exercise(reply,references=True)
    asyncio.run(run())
    assert [r.url.path.rsplit('/',1)[-1] for r in calls]==['edits','generations'] and len(reads)==1
    body=json.loads(calls[1].content)
    assert body['image']==['data:image/png;base64,YQ==','data:image/png;base64,Yg=='] and body['n']==1


@pytest.mark.parametrize('options',[{'gpt2':True},{'aspect':{'aspect_ratio':'1:1','image_size':'2K'}},
                                  {'allow_edit_fallback':False}])
def test_protocols_without_edit_switch_do_not_repost(options):
    run,calls,reads=exercise(lambda req:httpx.Response(404,text='images api is not supported',request=req),references=True,**options)
    if options.get('allow_edit_fallback') is False:
        assert asyncio.run(run()).status_code==404
    else:
        with pytest.raises(HTTPException) as failure:
            asyncio.run(run())
        assert failure.value.status_code==502
    assert len(calls)==1 and not reads


@pytest.mark.parametrize('allow', [False,True])
def test_generation_switch_requires_existing_policy_and_explicit_rejection(allow):
    run,calls,_=exercise(lambda req:httpx.Response(404,text='images api is not supported',request=req),allow_generation_fallback=allow)
    asyncio.run(run())
    assert len(calls)==(2 if allow else 1)
    if allow:assert calls[1].url.path.endswith('/edits')


@pytest.mark.parametrize('references',[[],['data:image/png;base64,YQ==','https://media.invalid/two.png']])
def test_extra_body_json_does_not_acquire_standard_top_level_fields(references):
    calls=[]
    async def run():
        def tracked(request):
            calls.append(request);return success(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(tracked)) as client:
            await submit_json_image(client,'https://supplier.invalid/v1/images/generations',{},
                model='agnes-image-existing',prompt='keep product',size='1024x1024',references=references)
    asyncio.run(run());body=json.loads(calls[0].content)
    assert len(calls)==1 and set(body)=={'model','prompt','size','extra_body'}
    assert body['extra_body']['response_format']=='url'
    assert body['extra_body'].get('image',[])==references


def test_adapter_has_no_application_storage_or_credential_dependency():
    source=Path(__file__).parents[1]/'providers/openai_images.py'
    imports=[]
    for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
        if isinstance(node,ast.Import):imports.extend(alias.name for alias in node.names)
        if isinstance(node,ast.ImportFrom):imports.append(node.module)
    assert set(imports)=={'contextlib','httpx','fastapi','enterprise.providers.submission'}
