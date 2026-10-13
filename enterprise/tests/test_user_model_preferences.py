"""Only temporary files and in-process ASGI; no provider calls or deployed data."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from enterprise import user_model_api, user_model_preferences as prefs


def selection(model='fixture-model'):
    return {'favorites':[json.dumps(['image','fixture-provider',model],separators=(',',':'))], 'view':'favorites'}


def test_preferences_survive_reload_and_are_separate_for_accounts(tmp_path):
    prefs.save_preferences(tmp_path,'alice',selection())
    assert prefs.load_preferences(tmp_path,'alice')['favorites'] == selection()['favorites']
    assert prefs.load_preferences(tmp_path,'bob')['favorites'] == []


def test_failed_replace_preserves_previous_preferences(tmp_path, monkeypatch):
    prefs.save_preferences(tmp_path,'alice',selection('original'))
    def failed(*args): raise OSError('fixture replace failure')
    monkeypatch.setattr(prefs.os,'replace',failed)
    with pytest.raises(OSError): prefs.save_preferences(tmp_path,'alice',selection('replacement'))
    assert prefs.load_preferences(tmp_path,'alice')['favorites'] == selection('original')['favorites']
    assert not list((tmp_path/'user-model-preferences').glob('*.tmp'))


def test_preferences_reject_invalid_identity_and_model_keys(tmp_path):
    with pytest.raises(ValueError): prefs.save_preferences(tmp_path,'../other',selection())
    with pytest.raises(ValueError): prefs.save_preferences(tmp_path,'alice',{'favorites':['not a model key']})
    assert not (tmp_path/'user-model-preferences').exists()


def test_ordinary_user_can_save_only_their_preferences_with_cookie_origin_checks(tmp_path, monkeypatch):
    from enterprise import gateway
    monkeypatch.setattr(user_model_api,'PATH_ROOTS',SimpleNamespace(DATA_ROOT=tmp_path))
    monkeypatch.setattr(gateway,'verify_token',lambda token: {'user_id':token,'username':token,'role':'user','is_admin':False,'auth_version':1} if token in {'alice','bob'} else None)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://testserver') as client:
            path='/enterprise/api/me/model-preferences'
            assert (await client.get(path)).status_code == 401
            body={**selection(), 'user_id':'bob'}
            denied=await client.put(path,json=body,headers={'Cookie':'enterprise_token=alice','Origin':'http://unrelated.invalid'})
            assert denied.status_code == 403
            saved=await client.put(path,json=body,headers={'Cookie':'enterprise_token=alice','Origin':'http://testserver'})
            assert saved.status_code == 200
            assert (await client.get(path,headers={'Cookie':'enterprise_token=alice'})).json()['favorites'] == selection()['favorites']
            assert (await client.get(path,headers={'Cookie':'enterprise_token=bob'})).json()['favorites'] == []
    asyncio.run(scenario())
