"""Character contracts use temporary metadata/media identities; no suppliers or live DB."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json

import httpx
import pytest
from fastapi import FastAPI, Request

from enterprise.character_api import create_router, local_preview_available
from enterprise.character_repository import CharacterError, CharacterRepository
from enterprise.characters import Characters

ALICE = {'user_id': 'alice'}
BOB = {'user_id': 'bob'}


def test_public_checkout_does_not_require_local_reference_assets(tmp_path):
    assert not local_preview_available(tmp_path)
    assert Characters(CharacterRepository(tmp_path), lambda value:value, lambda *_:True).catalog(ALICE) == []


def payload(**changes):
    return {'name': '角色A', 'description': '参考图', 'images': ['/assets/input/alice.png'], **changes}


@pytest.fixture
def domain(tmp_path):
    allowed = {'/assets/input/alice.png'}
    service = Characters(CharacterRepository(tmp_path), lambda value: value,
        lambda user, ref: user['user_id'] == 'alice' and ref in allowed)
    return service, allowed


def test_persistence_isolation_and_reference_reuse(domain, tmp_path):
    service, _ = domain
    row = service.save(ALICE, payload())
    assert row['revision'] == 1
    assert service.list(BOB) == []
    assert service.repository.list('alice')[0]['images'] == ['/assets/input/alice.png']
    assert CharacterRepository(tmp_path).list('alice') == service.repository.list('alice')
    assert list(tmp_path.rglob('*.png')) == [], 'metadata does not copy media bytes'
    with pytest.raises(CharacterError) as error:
        service.save(BOB, payload(images=['/assets/input/alice.png']))
    assert error.value.status == 403


@pytest.mark.parametrize('body', [payload(name=''), payload(name='x'*81), payload(images=[]),
    payload(images=['/assets/input/alice.png']*13), payload(images=['https://external.invalid/x.png']),
    payload(images=['/assets/input/code.svg']), payload(gender='unknown'), payload(user_id='bob')])
def test_invalid_profiles_never_write(domain, body):
    service, _ = domain
    with pytest.raises(CharacterError) as error:
        service.save(ALICE, body)
    assert error.value.status == 400
    assert service.repository.list('alice') == []


def test_compare_and_write_has_one_winner(domain):
    service, _ = domain
    row = service.save(ALICE, payload())
    def edit(name):
        try:
            return service.save(ALICE, payload(name=name, expected_revision=1), row['id'])['revision']
        except CharacterError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, ['edit A', 'edit B'])) == [2, 409]
    assert service.repository.list('alice')[0]['revision'] == 2


def test_creation_receipt_is_idempotent_and_conflicting_retry_cannot_overwrite(domain):
    service, _ = domain
    nonce = 'a' * 32
    first = service.save(ALICE, payload(create_request_id=nonce))
    again = service.save(ALICE, payload(create_request_id=nonce))
    assert first == again and first['id'] == nonce
    assert len(service.list(ALICE)) == 1
    with pytest.raises(CharacterError) as error:
        service.save(ALICE, payload(create_request_id=nonce, name='changed'))
    assert error.value.status == 409
    assert service.list(ALICE)[0]['name'] == '角色A'
    with pytest.raises(CharacterError):
        service.save(ALICE, payload(create_request_id='../other'))
    with pytest.raises(CharacterError):
        service.save(ALICE, payload(create_request_id=nonce, expected_revision=1), first['id'])


def test_creation_retry_remains_account_scoped_and_rechecks_media_permissions(domain):
    service, allowed = domain
    nonce = 'b' * 32
    service.save(ALICE, payload(create_request_id=nonce))
    with pytest.raises(CharacterError) as error:
        service.save(BOB, payload(create_request_id=nonce))
    assert error.value.status == 403 and service.list(BOB) == []
    allowed.clear()
    with pytest.raises(CharacterError) as error:
        service.save(ALICE, payload(create_request_id=nonce))
    assert error.value.status == 403


def test_failed_atomic_replace_retains_previous_profile(domain, monkeypatch):
    from enterprise import local_json
    service, _ = domain
    row = service.save(ALICE, payload())
    def fail(*args):
        raise OSError('fixture replace failure')
    monkeypatch.setattr(local_json.os, 'replace', fail)
    with pytest.raises(OSError):
        service.save(ALICE, payload(name='new', expected_revision=1), row['id'])
    assert service.repository.list('alice')[0]['name'] == '角色A'
    assert not list(service.repository.root.glob('*.tmp'))


def test_archive_restore_and_revoked_reference(domain):
    service, allowed = domain
    row = service.save(ALICE, payload())
    service.remove(ALICE, row['id'], 1)
    archived = service.list(ALICE)[0]
    assert archived['archived'] and archived['revision'] == 2
    restored = service.save(ALICE, payload(expected_revision=2, archived=False), row['id'])
    assert not restored['archived'] and restored['revision'] == 3
    allowed.clear()
    assert service.list(ALICE)[0]['images'] == []
    assert service.list(ALICE)[0]['unavailable_images'] == 1
    assert service.repository.list('alice')[0]['images'] == ['/assets/input/alice.png']


@pytest.mark.parametrize('data', ['broken JSON', '{"schema_version":2,"characters":[]}'])
def test_unknown_or_damaged_format_is_not_overwritten(domain, data):
    service, _ = domain
    service.repository.root.mkdir(parents=True)
    path = service.repository.path('alice')
    path.write_text(data, encoding='utf8')
    with pytest.raises((ValueError, CharacterError)):
        service.save(ALICE, payload())
    assert path.read_text(encoding='utf8') == data


def test_http_auth_account_scope_limits_and_errors(domain):
    service, _ = domain
    app = FastAPI()
    @app.middleware('http')
    async def identity(request: Request, next_handler):
        user = request.headers.get('x-fixture-user')
        request.state.user = {'user_id':user} if user else None
        return await next_handler(request)
    app.include_router(create_router(service), prefix='/enterprise')
    async def run():
        url = '/enterprise/api/me/characters'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            assert (await client.get(url)).status_code == 401
            client.headers['x-fixture-user'] = 'alice'
            created = await client.post(url,json=payload())
            assert created.status_code == 200 and created.headers['cache-control'] == 'no-store'
            record = created.json()
            assert (await client.put(url+'/'+record['id'],json=payload(expected_revision=9))).status_code == 409
            assert (await client.post(url,content=b'x'*32769)).status_code == 413
            assert (await client.post(url,content=b'bad')).status_code == 400
            client.headers['x-fixture-user'] = 'bob'
            assert (await client.get(url)).json()['characters'] == []
            assert (await client.delete(url+'/'+record['id'],headers={'x-fixture-user':'bob'},
                params={})).status_code == 400
            denied = await client.request('DELETE',url+'/'+record['id'],json={'expected_revision':1})
            assert denied.status_code == 404
    asyncio.run(run())


def test_catalog_is_read_only_and_copy_gets_personal_identity(tmp_path):
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'schema_version':1,'characters':[
        {'id':'official-demo','name':'Example','images':['/static/characters/example.png']}]}),encoding='utf8')
    service = Characters(CharacterRepository(tmp_path, path), lambda value:value, lambda *_:True)
    before = path.read_bytes()
    example = service.catalog(ALICE)[0]
    copied = service.save(ALICE, payload(name=example['name'],images=example['images']))
    assert copied['id'] != example['id']
    assert service.list(BOB) == []
    assert path.read_bytes() == before


def test_catalog_never_publishes_private_references(tmp_path):
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'schema_version':1,'characters':[
        {'id':'bad','name':'Bad','images':['/assets/input/private.png']}]}),encoding='utf8')
    service = Characters(CharacterRepository(tmp_path,path),lambda value:value,lambda *_:True)
    with pytest.raises(CharacterError) as error:
        service.catalog(ALICE)
    assert error.value.status == 503


def test_bundled_catalog_uses_real_media_normalizer(tmp_path):
    from enterprise.interceptors import normalize_resource_url, can_access_resource
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'schema_version':1,'characters':[
        {'id':'official-demo','name':'Example','images':['/static/characters/example.png']}]}),encoding='utf8')
    service = Characters(CharacterRepository(tmp_path,path),normalize_resource_url,can_access_resource)
    example = service.catalog(ALICE)[0]
    assert service.save(ALICE,payload(images=example['images']))['images'] == example['images']
    for unsafe in ('../private.png','%2e%2e/private.png','file.png?owner=other','sub/../../private.png'):
        with pytest.raises(CharacterError):
            service.save(ALICE,payload(images=['/static/characters/'+unsafe]))


def test_cover_is_authorized_separately_and_revocation_does_not_rewrite(domain):
    service,allowed=domain
    with pytest.raises(CharacterError) as error:
        service.save(ALICE,payload(cover_url='/assets/input/other.png'))
    assert error.value.status==403
    allowed.add('/assets/input/cover.png')
    row=service.save(ALICE,payload(cover_url='/assets/input/cover.png',age_group='teen'))
    allowed.remove('/assets/input/cover.png')
    assert service.list(ALICE)[0]['cover_url']==''
    assert service.repository.list('alice')[0]['cover_url']==row['cover_url']


def test_old_profiles_without_cover_remain_readable(domain):
    service,_=domain
    row=service.save(ALICE,payload(age_group='middle'))
    service.repository.mutate('alice',lambda rows:rows[0].pop('cover_url'))
    assert service.list(ALICE)[0]['cover_url']==row['images'][0]
    with pytest.raises(CharacterError) as error:
        service.save(ALICE,payload(cover_url=False))
    assert error.value.status==400
