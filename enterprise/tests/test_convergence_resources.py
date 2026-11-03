"""Current media/import boundaries. Temporary files and fake transports only."""
import ast
import asyncio
import json
import os
import re
import shutil
import time
import urllib.parse
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from fastapi import HTTPException, UploadFile, File
from fastapi.responses import FileResponse, Response, StreamingResponse
from enterprise import media_download as net
from enterprise.media_response import media_response_headers
from enterprise.path_safety import assert_path_within_root, assert_no_reparse_ancestors, PathSafetyError
from enterprise.workflow_archive import MAX_UPLOAD, MAX_WORKFLOW, inspect_archive, copy_resource

ROOT = Path(__file__).parents[2]


def main_functions(names, source='main.py', **values):
    tree = ast.parse((ROOT/source).read_text(encoding='utf-8'))
    tree.body = [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    for n in tree.body:
        n.decorator_list=[];n.returns=None
        for a in [*n.args.args,*n.args.kwonlyargs]: a.annotation=None
    scope = dict(globals(), **values)
    exec(compile(tree,'actual-main-functions','exec'),scope)
    return scope


def media_scope(tmp_path):
    assets=tmp_path/'assets';assets.mkdir()
    output=tmp_path/'output';output.mkdir()
    inp=assets/'input';inp.mkdir()
    return main_functions({'output_file_from_url','download_output','fetch_remote_media_bytes',
        'download_canvas_assets','filename_from_media_url','sanitize_export_filename',
        'smart_group_export_folder','export_smart_canvas_group','import_canvas_workflow'},
        OUTPUT_DIR=str(output),ASSETS_DIR=str(assets),OUTPUT_INPUT_DIR=str(inp),
        rewrite_runninghub_file_url=lambda x:x, open_media=net.open_media,
        content_type_for_path=lambda _: 'image/png',
        canvas_workflow_replace_strings=lambda value,mapping:json.loads(replace_refs(json.dumps(value),mapping)),
        canvas_workflow_payload=lambda nodes,connections,resources:{'nodes':nodes,'connections':connections,'resources':resources})


def replace_refs(text,mapping):
    for old,new in mapping.items(): text=text.replace(old,new)
    return text


@pytest.mark.parametrize('url', ['http://127.0.0.1:18001/api/config/token','http://[::1]/',
    'http://2130706433/','http://127.1/','http://10.0.0.1/','http://169.254.169.254/',
    'http://[::ffff:127.0.0.1]/','http://user:password@public.example/'])
def test_private_addresses_and_aliases_rejected(url):
    with pytest.raises(HTTPException) as e: net.public_destination(url)
    assert e.value.status_code==403


def test_mixed_dns_and_redirect_rechecked(monkeypatch):
    def dns(host,port,**kw):
        return [(2,1,6,'',('93.184.216.34',port)),(2,1,6,'',('127.0.0.1',port))]
    with pytest.raises(HTTPException): net.public_destination('https://public.example/a',dns)
    calls=[];closed=[]
    monkeypatch.setattr(net,'public_destination',lambda url: (_ for _ in ()).throw(HTTPException(403,'private'))
        if 'private' in url else (urllib.parse.urlsplit(url),'public.example',443,'93.184.216.34'))
    class Pool:
        def urlopen(self,*args,**kw):
            calls.append((args,kw));return SimpleNamespace(status=302,headers={'location':'http://private/secret'},close=lambda:closed.append(1))
        def close(self):closed.append(1)
    monkeypatch.setattr(net,'_pool_for',lambda *a:Pool())
    with pytest.raises(HTTPException):net.open_media('https://public.example/a')
    assert len(calls)==1 and len(closed)==2


def test_socket_pinned_and_tls_hostname_preserved(monkeypatch):
    calls=[]
    monkeypatch.setattr(net.socket,'create_connection',lambda address,*args:calls.append(address) or object())
    pool=net._pool_for(urllib.parse.urlsplit('https://public.example/a'),'public.example',443,'93.184.216.34')
    conn=pool._new_conn();conn._new_conn()
    assert calls==[('93.184.216.34',443)] and conn.host=='public.example'
    assert pool.cert_reqs=='CERT_REQUIRED'
    pool.close()


def test_range_and_public_stream_control(monkeypatch):
    seen=[];closed=[]
    monkeypatch.setattr(net,'public_destination',lambda url:(urllib.parse.urlsplit(url),'public.example',443,'93.184.216.34'))
    class Pool:
        def urlopen(self,*a,**kw):
            seen.append(kw);return SimpleNamespace(status=206,headers={'Content-Range':'bytes 0-2/3'},
                stream=lambda *a,**k:iter([b'abc']),close=lambda:closed.append('response'))
        def close(self):closed.append('pool')
    monkeypatch.setattr(net,'_pool_for',lambda *a:Pool())
    with net.open_media('https://public.example/movie',headers={'Range':'bytes=0-2','Cookie':'secret'}) as response:
        assert response.status_code==206 and b''.join(response.iter_content())==b'abc'
    assert seen[0]['headers']['Range']=='bytes=0-2' and 'Cookie' not in seen[0]['headers']
    assert seen[0]['redirect'] is False and closed==['response','pool']


def test_compressed_media_decodes_without_forwarding_stale_length():
    import gzip
    import urllib3
    raw=b'normal image fixture'
    encoded=gzip.compress(raw)
    response=urllib3.HTTPResponse(BytesIO(encoded),status=200,preload_content=False,
        headers={'content-encoding':'gzip','content-length':str(len(encoded)),'content-type':'image/png'})
    with net.MediaResponse(response,SimpleNamespace(close=lambda:None)) as media:
        assert b''.join(media.iter_content())==raw
        assert 'content-length' not in media.headers and 'content-encoding' not in media.headers


def test_foreign_basename_never_returns_other_local_file(tmp_path):
    scope=media_scope(tmp_path)
    (tmp_path/'output/bob.png').write_bytes(b'private bob')
    def blocked(*a,**k):raise HTTPException(403,'blocked target')
    scope['open_media']=blocked
    request=SimpleNamespace(headers={})
    with pytest.raises(HTTPException):scope['download_output'](request,'http://127.0.0.1/bob.png','',False)
    payload=SimpleNamespace(items=[],urls=['http://127.0.0.1/bob.png'],filename='export.zip')
    with pytest.raises(HTTPException) as e:asyncio.run(scope['download_canvas_assets'](payload))
    assert e.value.status_code==404
    response=scope['download_output'](request,'/output/bob.png','',False)
    assert isinstance(response,FileResponse) and response.path.endswith('bob.png')
    from enterprise.config import GATEWAY_PORT
    absolute=scope['download_output'](request,f'http://127.0.0.1:{GATEWAY_PORT}/output/bob.png','',False)
    assert isinstance(absolute,FileResponse) and absolute.path==response.path
    assert scope['output_file_from_url']('/assets/input/%2e%2e/other.png') is None


def test_managed_export_unique_and_cannot_overwrite(tmp_path,monkeypatch):
    scope=media_scope(tmp_path);root=tmp_path/'managed';monkeypatch.setenv('CANVAS_EXPORT_ROOT',str(root))
    forbidden=tmp_path/'program';forbidden.mkdir();(forbidden/'keep.txt').write_text('original')
    with pytest.raises(HTTPException):scope['smart_group_export_folder'](str(forbidden),'group','alice')
    payload=SimpleNamespace(folder='',group_name='group',items=[SimpleNamespace(kind='text',text='new',name='keep.txt')])
    req=SimpleNamespace(headers={'x-enterprise-user-id':'alice'})
    first=asyncio.run(scope['export_smart_canvas_group'](payload,req));second=asyncio.run(scope['export_smart_canvas_group'](payload,req))
    assert first['folder']!=second['folder'] and first['count']==1
    assert (forbidden/'keep.txt').read_text()=='original'
    assert Path(first['folder']).is_relative_to(root/'alice')
    before=set((root/'alice').iterdir())
    (tmp_path/'output/own.png').write_bytes(b'own fixture')
    payload.items=[SimpleNamespace(kind='image',url='/output/own.png',name='own.png')]
    monkeypatch.setattr(shutil,'copyfileobj',lambda *a:(_ for _ in ()).throw(OSError('copy failed')))
    with pytest.raises(OSError):asyncio.run(scope['export_smart_canvas_group'](payload,req))
    assert set((root/'alice').iterdir())==before


@pytest.mark.parametrize('mime',['text/html; charset=utf-8','application/xhtml+xml','image/svg+xml'])
def test_active_content_attachment_and_sandbox(mime):
    h=media_response_headers(mime,'file.html')
    assert h['Content-Disposition'].startswith('attachment') and h['X-Content-Type-Options']=='nosniff'
    assert 'allow-scripts' not in h['Content-Security-Policy']


@pytest.mark.parametrize('mime',['image/png','image/webp','video/mp4','audio/mpeg'])
def test_normal_media_keeps_inline_preview(mime):
    assert 'Content-Disposition' not in media_response_headers(mime)


def test_gateway_mutable_html_is_not_injected_or_executed(monkeypatch):
    import httpx
    from starlette.requests import Request
    from enterprise import gateway
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'<html><body>untrusted</body></html>'
    async def run():
        async with httpx.AsyncClient(base_url='http://upstream',transport=httpx.MockTransport(
                lambda request:httpx.Response(200,stream=Body(),headers={'content-type':'text/html'}))) as client:
            monkeypatch.setattr(gateway,'_http_client',client)
            request=Request({'type':'http','method':'GET','path':'/assets/input/user.html','query_string':b'',
                'headers':[(b'host',b'app')],'scheme':'http','server':('app',80)})
            response=await gateway._forward('assets/input/user.html',request,user=None,skip_intercept=True,body=b'')
            assert response.headers['content-disposition'].startswith('attachment')
            assert response.headers['x-content-type-options']=='nosniff'
            body=b''.join([chunk async for chunk in response.body_iterator])
            assert body==b'<html><body>untrusted</body></html>'
    asyncio.run(run())


def make_zip(workflow, entries=None):
    data=BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('workflow.json',json.dumps(workflow))
        for name,value in (entries or {}).items():z.writestr(name,value)
    data.seek(0);return UploadFile(data,filename='workflow.zip')


def test_zip_normal_duplicate_reference_is_copied_once_and_failure_cleans(tmp_path):
    scope=media_scope(tmp_path)
    workflow={'nodes':[],'connections':[],'resources':[{'archive':'image.png','url':'old'}]*2}
    result=asyncio.run(scope['import_canvas_workflow'](make_zip(workflow,{'image.png':b'png fixture'})))
    assert 'old' in result['resource_map'] and len(list((tmp_path/'assets/input').rglob('*.png')))==1
    before=set((tmp_path/'assets/input').iterdir())
    with pytest.raises(HTTPException):asyncio.run(scope['import_canvas_workflow'](make_zip({'resources':[{'archive':'a'}]},{'a':b'x'})))
    assert set((tmp_path/'assets/input').iterdir())==before


def test_zip_advertised_and_actual_expansion_limits(tmp_path,monkeypatch):
    from enterprise import workflow_archive as wa
    data=BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('bomb',b'0'*1000000)
    data.seek(0)
    with zipfile.ZipFile(data) as z,pytest.raises(HTTPException):inspect_archive(z)
    monkeypatch.setattr(wa,'MAX_EXPANDED',4)
    with pytest.raises(HTTPException):copy_resource(BytesIO(b'12345'),BytesIO(),0)


def test_server_image_import_denies_employee_and_preserves_authorized_admin():
    copied=[]
    scope=main_functions({'import_local_ai_reference','ensure_same_origin_request','origin_from_url','normalize_local_image_path'},
        import_local_image_file=lambda path:copied.append(path) or {'url':'/assets/input/authorized.png'})
    payload=SimpleNamespace(path='C:/authorized/reference.png',paths=[])
    headers={'host':'127.0.0.1:18001','origin':'http://127.0.0.1:18000',
        'x-enterprise-origin':'http://127.0.0.1:18000','x-enterprise-user-id':'employee','x-enterprise-is-admin':'false'}
    request=SimpleNamespace(headers=headers,url=SimpleNamespace(scheme='http'))
    with pytest.raises(HTTPException) as e:asyncio.run(scope['import_local_ai_reference'](payload,request))
    assert e.value.status_code==403 and not copied
    headers['x-enterprise-is-admin']='true'
    assert asyncio.run(scope['import_local_ai_reference'](payload,request))['files'][0]['url'].endswith('authorized.png')
    assert len(copied)==1
