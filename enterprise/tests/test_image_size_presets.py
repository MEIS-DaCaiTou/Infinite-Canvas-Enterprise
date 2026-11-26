"""Personal preset persistence and real Gateway authorization; no model calls."""
import asyncio

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import ValidationError

from enterprise.image_size_api import create_router
from enterprise.image_size_presets import ImageSizePresets, SizePresetInput


def test_account_crud_and_reopen(tmp_path):
    store = ImageSizePresets(tmp_path)
    preset = store.save('alice', SizePresetInput(name='  服装主图  ', width=1200, height=1200))
    assert preset['name'] == '服装主图'
    assert ImageSizePresets(tmp_path).list('alice') == [preset]
    assert store.list('bob') == []
    with pytest.raises(KeyError):
        store.delete('bob', preset['id'])
    updated = store.save('alice', SizePresetInput(name='横屏', width=1920, height=1080), preset['id'])
    assert updated['id'] == preset['id']
    assert store.list('alice') == [updated]
    store.delete('alice', preset['id'])
    assert ImageSizePresets(tmp_path).list('alice') == []


@pytest.mark.parametrize('changes', [{'width': 0}, {'height': 2.5}, {'width': True}, {'name': '  '}, {'name': '字'*61}])
def test_dimensions_and_name_contract(changes):
    with pytest.raises(ValidationError):
        SizePresetInput(**({'name': '示例', 'width': 1200, 'height': 1200} | changes))


def test_replace_failure_keeps_saved_preset(tmp_path, monkeypatch):
    from enterprise import local_json
    store = ImageSizePresets(tmp_path)
    before = store.save('alice', SizePresetInput(name='原值', width=1200, height=1200))
    def failed(*args): raise OSError('fixture replacement failure')
    monkeypatch.setattr(local_json.os, 'replace', failed)
    with pytest.raises(OSError):
        store.save('alice', SizePresetInput(name='新值', width=1600, height=1200), before['id'])
    assert store.list('alice') == [before]


def test_http_identity_is_server_owned(tmp_path):
    app = FastAPI()
    @app.middleware('http')
    async def identity(request: Request, call_next):
        token = request.headers.get('x-test-user')
        if token in {'alice', 'bob'}: request.state.user = {'user_id': token}
        return await call_next(request)
    app.include_router(create_router(ImageSizePresets(tmp_path)), prefix='/enterprise')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            url = '/enterprise/api/me/image-size-presets'
            assert (await client.get(url)).status_code == 401
            saved = await client.post(url, headers={'x-test-user':'alice'}, json={
                'name':'主图', 'width':1200, 'height':1200, 'owner':'bob'})
            assert saved.status_code == 200
            preset_id = saved.json()['id']
            assert (await client.get(url, headers={'x-test-user':'bob'})).json() == {'presets':[]}
            assert (await client.delete(url+'/'+preset_id, headers={'x-test-user':'bob'})).status_code == 404
            assert len((await client.get(url, headers={'x-test-user':'alice'})).json()['presets']) == 1
    asyncio.run(run())


def test_real_gateway_cookie_origin_and_ordinary_permissions(tmp_path, monkeypatch):
    from enterprise import gateway
    monkeypatch.setattr(ImageSizePresets, 'path', lambda self, owner: tmp_path / (owner+'.json'))
    monkeypatch.setattr(gateway, 'verify_token', lambda token: {
        'user_id':token,'username':token,'role':'user','is_admin':False,'auth_version':1
    } if token in {'alice','bob'} else None)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url='http://testserver') as client:
            url='/enterprise/api/me/image-size-presets'
            body={'name':'服装竖图','width':1200,'height':1600,'user_id':'bob'}
            assert (await client.get(url)).status_code==401
            denied=await client.post(url,json=body,headers={'Cookie':'enterprise_token=alice','Origin':'http://unrelated.invalid'})
            assert denied.status_code==403
            saved=await client.post(url,json=body,headers={'Cookie':'enterprise_token=alice','Origin':'http://testserver'})
            assert saved.status_code==200
            assert (await client.get(url,headers={'Cookie':'enterprise_token=bob'})).json()=={'presets':[]}
            assert (await client.delete(url+'/'+saved.json()['id'],headers={'Cookie':'enterprise_token=bob','Origin':'http://testserver'})).status_code==404
    asyncio.run(run())
