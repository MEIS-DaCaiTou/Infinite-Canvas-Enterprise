"""Read-only query contracts using temporary JSON/SQLite; no provider calls."""
import asyncio
import base64
from copy import deepcopy
import json

import pytest

from enterprise import collection_query as query
from enterprise.local_json import atomic_write_json


@pytest.fixture
def env(tmp_path, monkeypatch):
    from enterprise import db, interceptors
    from enterprise.tests.ready_user_fixture import insert_ready_user_fixture
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path/'enterprise.db'))
    db.init_db()
    actors=[]
    for name in ('qa-a', 'qa-b'):
        user=insert_ready_user_fixture(db.DB_PATH, username=name, password_hash='unused-fixture', display_name=name)
        actors.append({'user_id': user['id'], 'username': name, 'is_admin': False})
    monkeypatch.setattr(interceptors, '_HISTORY_FILE', tmp_path/'history.json')
    monkeypatch.setattr(interceptors, '_ASSET_LIBRARY_FILE', tmp_path/'asset_library.json')
    monkeypatch.setattr(interceptors, '_COLLECTION_QUERIES', query.QuerySnapshots())
    monkeypatch.setattr(interceptors, '_HISTORY_QUERIES', None)
    return db, interceptors, actors


def payload(response):
    assert response.status_code == 200, response.body
    return json.loads(response.body)


def test_history_authorized_before_page_and_current_owner_rechecked(env):
    db, api, (a,b)=env
    rows=[{'timestamp': i, 'images':[f'/output/qa-{i}.png'], 'type':'online', 'prompt':'query sample'} for i in range(8)]
    atomic_write_json(api._HISTORY_FILE, rows)
    for i,row in enumerate(rows):
        db.record_history_owner(a['user_id'] if i%2 else b['user_id'], api.history_id_for_record(row), 'online')
    args={'page_size':'2', 'type':'online'}
    first=payload(api.handle_collection_query(a,'api/history',args))
    assert [r['timestamp'] for r in first['items']]==[7,5]
    assert first['total']==4 and first['next_cursor']
    # Same cached JSON, new ownership. A cursor cannot retain a revoked grant.
    db.remove_history_mapping(api.history_id_for_record(rows[3]))
    second=payload(api.handle_collection_query(a,'api/history',{**args,'cursor':first['next_cursor']}))
    assert [r['timestamp'] for r in second['items']]==[1]
    assert all('_query_position' not in r for r in first['items'])
    other=payload(api.handle_collection_query(b,'api/history',args))
    assert [r['timestamp'] for r in other['items']]==[6,4] and other['total']==4
    assert api.handle_collection_query(b,'api/history',{**args,'cursor':first['next_cursor']}).status_code==400
    assert payload(api.handle_collection_query({'user_id':'admin','is_admin':True},'api/history',args))['total']==8
    # Original unpaged filter remains equivalent, and original route is not intercepted.
    legacy=deepcopy(rows);api.filter_history_list(a,legacy)
    assert {r['timestamp'] for r in legacy}=={7,5,1}
    assert asyncio.run(api.pre_process('api/history','GET',a,{'type':'online'})) is None
    assert payload(asyncio.run(api.pre_process('api/history','GET',a,args)))['total']==3


def test_library_page_matches_legacy_policy_and_uses_one_db_connection(env, monkeypatch):
    db, api, (a,b)=env
    items=[{'id':f'i{i}', 'name':f'Style {i}', 'type':'image', 'url':f'/assets/library/{i}.png', 'created_at':i} for i in range(6)]
    library={'libraries':[{'id':'default','categories':[{'id':'characters','items':items}]}]}
    atomic_write_json(api._ASSET_LIBRARY_FILE,library)
    # Explicit item owner, original resource-owner fallback, latest item/resource fallback.
    db.record_asset_object_owner(a['user_id'],'item','i5',resource_url=items[5]['url'])
    db.record_resource_owner(a['user_id'],items[3]['url'])
    db.record_asset_object_owner(a['user_id'],'item','historical-id',resource_url=items[1]['url'])
    for i in (0,2,4): db.record_asset_object_owner(b['user_id'],'item',f'i{i}')
    db.record_resource_owner(a['user_id'],items[0]['url'])  # explicit object owner takes precedence
    db.record_asset_object_owner(b['user_id'],'library','private')
    db.record_asset_object_owner(b['user_id'],'category','private-cat')
    db.record_asset_object_owner(a['user_id'],'item','hidden-in-private')
    library['libraries'].append({'id':'private','categories':[{'id':'private-cat','items':[
        {'id':'hidden-in-private','url':'/assets/library/hidden.png','type':'image'}]}]})
    atomic_write_json(api._ASSET_LIBRARY_FILE,library)
    legacy={'library':deepcopy(library)};api.filter_asset_library(a,legacy)
    expected=[r['id'] for r in query.library_items(legacy['library'])]
    calls=[];original=db.get_db
    def counted():
        calls.append(1);return original()
    monkeypatch.setattr(db,'get_db',counted)
    first=payload(api.handle_collection_query(a,'api/asset-library',{'page_size':'2','kind':'image'}))
    assert len(calls)==1, 'batch authorization must not open a connection per item'
    assert first['total']==3 and [r['id'] for r in first['items']]==['i5','i3']
    second=payload(api.handle_collection_query(a,'api/asset-library',{'page_size':'2','kind':'image','cursor':first['next_cursor']}))
    assert set(expected)=={r['id'] for r in first['items']+second['items']}
    other=payload(api.handle_collection_query(b,'api/asset-library',{'page_size':'2'}))
    assert other['total']==3 and {r['id'] for r in other['items']}=={'i4','i2'}
    # A direct hidden-library filter cannot reveal item count or metadata.
    assert payload(api.handle_collection_query(a,'api/asset-library',{'page_size':'2','library_id':'foreign'}))['total']==0
    conn=original()
    try:
        conn.execute('UPDATE user_asset_object_map SET user_id=? WHERE object_type=? AND object_id=?',(b['user_id'],'item','i5'));conn.commit()
    finally:conn.close()
    assert payload(api.handle_collection_query(a,'api/asset-library',{'page_size':'2'}))['total']==2


def test_snapshot_reuses_parse_but_invalidates_atomic_replacement(tmp_path, monkeypatch):
    path=tmp_path/'history.json';atomic_write_json(path,[{'timestamp':1}])
    calls=[];reader=query.read_json
    def counted(p):calls.append(1);return reader(p)
    monkeypatch.setattr(query,'read_json',counted)
    store=query.QuerySnapshots()
    old,rev=store.read(path,'history');assert store.read(path,'history')==(old,rev)
    assert len(calls)==1
    identified=[]
    def identify(row):identified.append(row['timestamp']);return str(row['timestamp'])
    assert store.history_ids(old,identify)==['1'] and store.history_ids(old,identify)==['1']
    assert identified==[1], 'derived identities can be reused; current owners must not be cached'
    atomic_write_json(path,[{'timestamp':2}])
    new,next_rev=store.read(path,'history');assert new==[{'timestamp':2}] and rev!=next_rev
    assert store.history_ids(new,identify)==['2'] and identified==[1,2]
    path.write_text('{bad original');before=path.read_bytes()
    with pytest.raises(query.QueryError) as error:store.read(path,'history')
    assert error.value.status==503 and path.read_bytes()==before
    path.unlink();assert store.read(path,'history')==([],[])
    atomic_write_json(path,[{'timestamp':3}])
    assert store.read(path,'history')[0]==[{'timestamp':3}]
    uncached=query.QuerySnapshots(max_cached_bytes=1)
    before=len(calls);uncached.read(path,'history');uncached.read(path,'history')
    assert len(calls)==before+2, 'cache budget is not a data-count limit'


@pytest.mark.parametrize('params',[{'page_size':0},{'page_size':101},{'page_size':'abc'},{'page_size':1,'sort':'bad'},
    {'page_size':1,'q':'x'*201},{'page_size':1,'cursor':'bad'},{'page_size':1,'kind':'bad'}])
def test_invalid_queries_are_explicit(params):
    with pytest.raises(query.QueryError) as error:query.page([],params,actor='a',source='history',revision=[])
    assert error.value.status==400


def test_cursor_revision_and_filters_and_equal_time_order():
    rows=[{'id':str(i),'timestamp':1,'name':'shirt','tags':['summer']} for i in range(5)]
    args={'page_size':2,'q':'summer','sort':'oldest'}
    first=query.page(rows,args,actor='a',source='library',revision=[1])
    second=query.page(rows,{**args,'cursor':first['next_cursor']},actor='a',source='library',revision=[1])
    assert [r['id'] for r in first['items']+second['items']]==['0','1','2','3']
    with pytest.raises(query.QueryError) as error:query.page(rows,{**args,'cursor':first['next_cursor']},actor='a',source='library',revision=[2])
    assert error.value.status==409
    with pytest.raises(query.QueryError) as error:query.page(rows,{**args,'q':'different','cursor':first['next_cursor']},actor='a',source='library',revision=[1])
    assert error.value.status==400


@pytest.mark.parametrize('legacy_time', [-0.0, 0, 0.0])
def test_existing_cursor_numeric_formats_remain_accepted(legacy_time):
    # Issued before SQLite projection parity normalized the encoded time value.
    cursor = base64.urlsafe_b64encode(json.dumps({
        'query': ['a','history',1,'','newest','','','',''],
        'revision': [1], 'after': [legacy_time,'a',0],
    }).encode()).decode().rstrip('=')
    rows = [{'id':'a','timestamp':0}, {'id':'b','timestamp':0}]
    result = query.page(rows, {'page_size':1,'cursor':cursor}, actor='a', source='history', revision=[1])
    assert [row['id'] for row in result['items']] == ['b']
    assert result['next_cursor'] is None


@pytest.mark.parametrize('broken',[{'libraries':{}},{'libraries':[1]},{'categories':[{'items':[1]}]}])
def test_bad_library_schema_is_not_silently_empty(tmp_path,broken):
    path=tmp_path/'library.json';atomic_write_json(path,broken)
    with pytest.raises(query.QueryError):query.QuerySnapshots().read(path,'library')


def test_paged_history_keeps_existing_feature_guard(env,monkeypatch):
    from starlette.responses import JSONResponse
    _db,api,(a,_b)=env
    monkeypatch.setattr(api,'_request_feature_key',lambda *_:'controlled-feature')
    monkeypatch.setattr(api,'_feature_denial',lambda *_:JSONResponse({'message':'not allowed'},status_code=403))
    response=asyncio.run(api.pre_process('api/history','GET',a,{'page_size':'1'}))
    assert response.status_code==403 and not api._HISTORY_FILE.exists()


def test_catalog_is_authorized_before_counts_and_covers_without_mutating_source(env):
    db, api, (a,b) = env
    items=[{'id':f'i{i}','url':f'/assets/library/{i}.png','kind':'image','name':str(i)} for i in range(10)]
    root={'libraries':[{'id':'default','name':'款式','categories':[{'id':'characters','type':'image','items':items}]}]}
    atomic_write_json(api._ASSET_LIBRARY_FILE,root)
    before=api._ASSET_LIBRARY_FILE.read_bytes()
    for i,item in enumerate(items):
        db.record_asset_object_owner(a['user_id'] if i%2 else b['user_id'],'item',item['id'])
    db.record_asset_object_owner(b['user_id'],'library','foreign')
    db.record_asset_object_owner(a['user_id'],'item','hidden')
    root['libraries'].append({'id':'foreign','categories':[{'id':'other','items':[{'id':'hidden','url':'/assets/library/hidden.png'}]}]})
    atomic_write_json(api._ASSET_LIBRARY_FILE,root);before=api._ASSET_LIBRARY_FILE.read_bytes()
    for actor,expected in ((a,{'i1','i3','i5','i7','i9'}),(b,{'i0','i2','i4','i6','i8'})):
        catalog=payload(asyncio.run(api.pre_process('api/asset-library','GET',actor,{'catalog':'1'})))
        assert catalog['projection']=='catalog'
        own=next(row for row in catalog['library']['libraries'] if row['id']=='default')
        cat=next(row for row in own['categories'] if row['id']=='characters')
        assert 'items' not in cat and cat['item_count']==5
        assert len(cat['preview_items'])==2 and {row['id'] for row in cat['preview_items']}<=expected
        pages=payload(api.handle_collection_query(actor,'api/asset-library',{'page_size':2,'library_id':'default','category_id':'characters','kind':'image'}))
        assert pages['total']==5 and {row['id'] for row in pages['items']}<=expected
    assert api._ASSET_LIBRARY_FILE.read_bytes()==before
    assert api.handle_collection_query(a,'api/asset-library',{'catalog':'invalid'}).status_code==400
    assert asyncio.run(api.pre_process('api/asset-library','GET',a,{})) is None


def test_catalog_empty_and_legacy_shapes_keep_navigation_truthful():
    assert query.library_catalog({'libraries':[]})['libraries']==[]
    old={'categories':[{'id':'old','items':[{'id':'i','url':'/assets/library/i.png'}]}]}
    cat=query.library_catalog(old)['libraries'][0]['categories'][0]
    assert cat['item_count']==1 and cat['preview_items'][0]['id']=='i' and len(old['categories'][0]['items'])==1
