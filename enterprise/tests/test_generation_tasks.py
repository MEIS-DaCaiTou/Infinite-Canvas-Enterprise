"""Personal task catalog over real temporary SQLite mappings and durable receipts."""
import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from enterprise import db, generation_task_api
from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.generation_tasks import GenerationTaskRepository, describe_task
from enterprise.generation_task_routes import create_router


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    database = tmp_path / 'owners.db'
    def connect():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        return connection
    with connect() as connection:
        connection.executescript('''
            CREATE TABLE user_task_map(task_type TEXT, task_id TEXT, user_id TEXT, created_at INTEGER,
                PRIMARY KEY(task_type, task_id));
            CREATE INDEX task_owner ON user_task_map(user_id, task_type);
            CREATE TABLE user_resource_map(user_id TEXT, resource_url TEXT UNIQUE, source TEXT, created_at INTEGER);
        ''')
    monkeypatch.setattr(db, 'get_db', connect)
    repository = GenerationTaskRepository(tmp_path / 'canvas-tasks')
    def add(task_id, owner='alice', created_at=1000, **changes):
        record = {'id':task_id, 'type':'online-image', 'status':'failed', 'created_at':created_at/1000,
                  'provider_id':'zhenzhen', 'model':'fixture-model', 'result':None, **changes}
        with connect() as connection:
            connection.execute('INSERT INTO user_task_map VALUES(?,?,?,?)',
                ({'comfy':'canvas_comfy','video':'canvas_video'}.get(record['type'],'canvas_image'), task_id, owner, created_at))
        repository.journal.create(record)
        return record
    return repository, add, connect


def test_owner_first_page_cursor_filters_and_restart(catalog, monkeypatch):
    repository, add, _ = catalog
    add('alice-new', created_at=3000, status='succeeded', result={'images':['/output/a.png']})
    add('alice-mid', created_at=2000, recovery_required=True)
    add('alice-old', created_at=1000, type='comfy', status='succeeded')
    add('bob-secret', owner='bob', created_at=4000)
    reads = []
    original = repository.journal.get
    monkeypatch.setattr(repository.journal, 'get', lambda key: (reads.append(key), original(key))[1])
    monkeypatch.setattr(db, 'get_task_owner', lambda *_: pytest.fail('list repeated owner lookups'))
    first = repository.page('alice', limit=2)
    assert [item['id'] for item in first['items']] == ['alice-new', 'alice-mid']
    second = repository.page('alice', cursor=first['next_cursor'], limit=2)
    assert [item['id'] for item in second['items']] == ['alice-old']
    assert not second['next_cursor'] and 'bob-secret' not in reads
    fresh = GenerationTaskRepository(repository.journal.root)
    assert fresh.page('alice', status='unknown')['items'][0]['id'] == 'alice-mid'
    assert fresh.page('alice', kind='canvas_comfy')['items'][0]['id'] == 'alice-old'
    with pytest.raises(ValueError): fresh.page('alice', cursor='../escape')


def test_corrupt_receipt_is_visible_without_hiding_other_owned_tasks(catalog):
    repository, add, _ = catalog
    add('broken', created_at=2000)
    add('valid', created_at=1000)
    path = repository.journal.root / 'broken.json'
    path.write_text('{"id":', encoding='utf-8')
    page = repository.page('alice')
    assert [(item['id'],item['status']) for item in page['items']] == [('broken','unavailable'),('valid','failed')]
    assert path.read_text() == '{"id":'


def test_task_states_and_outputs_do_not_expose_internal_provider_configuration():
    record = {'id':'fixture', 'type':'online-image', 'status':'failed', 'recovery_required':True,
              'provider_receipts':[{'state':'succeeded', 'upstream_task_id':'original-id',
                'provider_base_url':'https://private.invalid', 'result':{'images':['/output/kept.png']}}],
              'result':{'items':[{'kind':'text','url':'/assets/output/a.txt','text':'safe <script> text'},
                                 {'url':'https://remote.invalid/private'}, {'url':'/output/%2e%2e/secret'}]}}
    data = describe_task(record, detail=True)
    assert data['status']=='partial' and data['output_count']==2
    assert data['items'][0]['text']=='safe <script> text'
    assert 'private.invalid' not in str(data)
    assert data['attempts'][0]['upstream_task_id']=='original-id'
    record.update(result=None,provider_receipts=[{'state':'failed'}])
    assert describe_task(record)['status']=='failed'


def test_gateway_auth_owner_checks_and_disconnected_result_projection(catalog, monkeypatch):
    from enterprise import gateway
    from fastapi import FastAPI
    repository, add, _ = catalog
    add('finished', status='succeeded', result={'images':['/output/finished.png']})
    add('foreign', owner='bob', status='succeeded', result={'images':['/output/foreign.png']})
    add('mismatch', enterprise_user_id='bob')
    monkeypatch.setattr(gateway,'verify_token',lambda token: {'user_id':token,'username':token,'role':'user','is_admin':False,'auth_version':1} if token in {'alice','bob'} else None)
    upstream=FastAPI()
    upstream.include_router(create_router(repository.journal))
    before = {path.name:path.read_bytes() for path in repository.journal.root.glob('*.json')}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream),base_url='http://upstream') as transport, httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://testserver') as client:
            path='/enterprise/api/me/generation-tasks'
            assert (await client.get(path)).status_code==401
            headers={'Cookie':'enterprise_token=alice'}
            monkeypatch.setattr(gateway.app.state,'upstream_client',None,raising=False)
            assert (await client.get(path,headers=headers)).status_code==503
            monkeypatch.setattr(gateway.app.state,'upstream_client',transport)
            page=await client.get(path,headers=headers)
            assert page.status_code==200 and 'foreign' not in page.text
            assert page.headers['cache-control']=='no-store'
            assert (await client.get(path+'/foreign',headers=headers)).status_code==404
            spoofed={**headers,'X-Enterprise-User-ID':'bob'}
            assert (await client.get(path+'/foreign',headers=spoofed)).status_code==404
            assert (await client.get('/_enterprise_internal/generation-tasks',headers=spoofed)).status_code==404
            assert (await client.get(path+'/mismatch',headers=headers)).status_code==404
            assert db.get_resource_owner('/output/finished.png') is None
            detail=await client.get(path+'/finished?user_id=bob',headers=headers)
            assert detail.status_code==200 and detail.json()['status']=='succeeded'
            assert db.get_resource_owner('/output/finished.png')=='alice'
            assert db.get_resource_owner('/output/foreign.png') is None
            assert (await client.get(path+'?status=nonsense',headers=headers)).status_code==400
    asyncio.run(scenario())
    assert before=={path.name:path.read_bytes() for path in repository.journal.root.glob('*.json')}


def test_catalog_readers_share_the_single_writer_journal_lock(catalog):
    repository,add,_=catalog
    add('shared',status='running')
    catalog_reader=GenerationTaskRepository(repository.journal.root,journal=repository.journal)
    def write():
        for _ in range(30):repository.journal.record_reconciliation('shared','querying')
    def read():
        for _ in range(30):assert catalog_reader.page('alice')['items'][0]['id']=='shared'
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures=[pool.submit(write),*(pool.submit(read) for _ in range(4))]
        for future in futures:future.result()
    assert repository.journal.get('shared')['reconciliation']['count']==30


def test_existing_resource_owner_is_never_reassigned_by_task_detail(catalog):
    repository, add, _ = catalog
    add('finished', status='succeeded', result={'images':['/output/existing.png']})
    db.record_resource_owners('bob',['/output/existing.png'],'fixture')
    from enterprise.interceptors import record_resource_urls_for_user
    record_resource_urls_for_user('alice','generation_task_detail',repository.detail('alice','finished'))
    assert db.get_resource_owner('/output/existing.png')=='bob'


def test_detail_projects_only_output_urls_not_paths_in_other_fields(catalog):
    from fastapi import FastAPI
    repository,add,_=catalog
    add('text-path',type='comfy',status='succeeded',error='/output/error-reference.png',
        result={'items':[{'url':'/output/actual-result.txt','kind':'text',
                          'text':'/output/unclaimed.png','name':'/output/name-reference.png'}]})
    application=FastAPI();application.include_router(create_router(repository.journal))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),base_url='http://upstream') as client:
            response=await client.get('/_enterprise_internal/generation-tasks/text-path',headers={'X-Enterprise-User-ID':'alice'})
            assert response.status_code==200 and response.json()['items'][0]['text']=='/output/unclaimed.png'
    asyncio.run(scenario())
    assert db.get_resource_owner('/output/actual-result.txt')=='alice'
    for name in ('unclaimed.png','error-reference.png','name-reference.png'):
        assert db.get_resource_owner('/output/'+name) is None


def test_placeholder_does_not_mean_submitted_but_interrupted_and_accepted_still_unknown():
    record={'id':'local-validation','type':'online-image','status':'failed','status_code':400,
            'provider_receipts':[{'index':0,'state':'started'}],'error':'API platform disabled'}
    assert describe_task(record)['status']=='failed'
    assert not describe_task(record)['can_query']
    record['recovery_required']=True
    assert describe_task(record)['status']=='unknown'
    record.pop('recovery_required')
    for stage in ('submitting','accepted','generated','unknown'):
        record['provider_receipts'][0]['state']=stage
        assert describe_task(record)['status']=='unknown'


def test_new_receipt_fields_remain_readable_by_v1_journal_after_restart(tmp_path):
    journal=CanvasTaskJournal(tmp_path)
    journal.create({'id':'accepted','type':'online-image','status':'queued','provider_receipts':[]})
    journal.mark_running('accepted')
    journal.record_reconciliation('accepted','querying')
    journal.record_reconciliation('accepted','running')
    restarted=CanvasTaskJournal(tmp_path)
    assert restarted.recover()['interrupted']==1
    record=restarted.get('accepted')
    assert record['journal_version']==1 and record['reconciliation']['count']==1
    assert describe_task(record)['status']=='unknown'


def test_automatic_task_state_requires_current_query_not_pre_restart_status():
    record={'id':'original','type':'comfy','status':'failed','recovery_required':True,
        'comfy_receipt':{'prompt_id':'original-27'},
        'auto_recovery':{'status':'waiting','last_query_at':20},
        'reconciliation':{'status':'queued','started_at':21}}
    assert describe_task(record)['status']=='queued'
    record['auto_recovery'].update(status='querying',last_query_at=30)
    assert describe_task(record)['status']=='unknown'
    record['reconciliation'].update(status='running',started_at=31)
    assert describe_task(record)['status']=='running'
    record.update(status='succeeded',result={'texts':['/output/kept.txt']})
    assert describe_task(record)['auto_recovery']['status']=='complete'


def test_video_filter_pagination_and_disconnected_result_projection(catalog):
    repository, add, _ = catalog
    add('video-new', type='video', created_at=3000, status='succeeded', result={'videos':['/output/video.mp4']})
    add('image-mid', created_at=2000)
    add('video-old', type='video', created_at=1000, recovery_required=True)
    add('bob-video', owner='bob', type='video', created_at=4000)
    page=repository.page('alice',kind='canvas_video',limit=1)
    assert [item['id'] for item in page['items']]==['video-new']
    following=repository.page('alice',kind='canvas_video',cursor=page['next_cursor'])
    assert [item['id'] for item in following['items']]==['video-old']
    detail=repository.detail('alice','video-new')
    assert detail['items']==[{'url':'/output/video.mp4','kind':'video'}]
    assert repository.detail('bob','video-new') is None
