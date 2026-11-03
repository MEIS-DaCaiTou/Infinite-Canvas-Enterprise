"""Picker query boundaries, real temporary files and current SQLite ownership."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import urllib

import pytest
from fastapi import HTTPException

from enterprise import local_uploads, collection_query
from enterprise.local_json import atomic_write_json, read_json
from enterprise.resource_index import ResourceReferenceIndex
from enterprise.tests.test_collection_query import env, payload
from enterprise.tests.test_convergence_resources import main_functions


def actual_queries(tmp_path):
    canvases = tmp_path/'canvases'; canvases.mkdir(exist_ok=True)
    uploads = tmp_path/'uploads'; uploads.mkdir(exist_ok=True)
    values = main_functions({'canvas_asset_context', 'upload_picker_index', 'character_asset_urls',
                             'extract_canvas_assets', 'iter_canvas_asset_values', 'iter_canvas_media_entries', 'canvas_asset_url_value',
                             'canvas_asset_downloadable_url', 'canvas_asset_kind', 'canvas_node_title',
                             'asset_library_media_kind', 'canvas_record', 'canvas_asset_name'},
        CANVAS_DIR=str(canvases), LOCAL_UPLOAD_DIR=str(uploads), _CANVAS_ASSET_CONTEXT=ResourceReferenceIndex(),
        local_upload_metadata_items=local_uploads.metadata_items, read_json=read_json, hashlib=hashlib,
        normalize_canvas_kind=lambda value:value or 'classic', normalize_canvas_color=lambda value:value or '',
        DEFAULT_PROJECT_ID='default', filename_from_media_url=lambda url,fallback:Path(url).name,
        sanitize_asset_name=lambda name,fallback:name or fallback)
    return values, canvases, uploads


def test_upload_metadata_keeps_supported_names_without_decoding_or_sidecars(tmp_path,monkeypatch):
    (tmp_path/'款式').mkdir()
    image=tmp_path/'款式'/'up_123456abcdef_衬衫.png';image.write_bytes(b'not decoded in this query')
    (tmp_path/'movie.mp4').write_bytes(b'movie')
    (tmp_path/'voice.wav').write_bytes(b'audio')
    (tmp_path/'caption.txt').write_text('private caption')
    (tmp_path/'.hidden.png').write_bytes(b'hidden')
    rows=local_uploads.metadata_items(tmp_path)
    assert len(rows)==3 and {r['kind'] for r in rows}=={'image','video','audio'}
    row=next(r for r in rows if r['kind']=='image')
    assert row['name']=='衬衫.png' and row['folder']=='款式' and row['size']==image.stat().st_size
    assert 'caption' not in row and 'width' not in row
    assert '%E8' in row['url'] and row['_query_position']==0
    def fail(*args,**kwargs):raise PermissionError('controlled folder error')
    monkeypatch.setattr(local_uploads.os,'scandir',fail)
    with pytest.raises(PermissionError):local_uploads.metadata_items(tmp_path)
    original_stat=Path.stat
    def unreadable_root(path,*args,**kwargs):
        if path==tmp_path:raise PermissionError('controlled root error')
        return original_stat(path,*args,**kwargs)
    monkeypatch.setattr(Path,'stat',unreadable_root)
    with pytest.raises(PermissionError):local_uploads.metadata_items(tmp_path)
    scope=main_functions({'list_local_assets'},upload_picker_index=lambda:(_ for _ in ()).throw(PermissionError('controlled')))
    with pytest.raises(HTTPException) as error:
        asyncio.run(scope['list_local_assets'](SimpleNamespace(query_params={'page_size':'24'},headers={})))
    assert error.value.status_code==503


def test_context_is_page_scoped_reuses_reference_cache_and_invalidates_saves(tmp_path):
    scope,directory,_=actual_queries(tmp_path)
    for name,project in [('one','p1'),('two','p2')]:
        atomic_write_json(directory/(name+'.json'),{'id':name,'project':project,'nodes':[
            {'id':'image','type':'image','url':'/assets/input/shared.png'},
            {'id':'secret','type':'image','url':'/assets/input/unrequested.png'},
            {'id':'unicode','type':'image','url':'/assets/input/服装.png'},
            {'type':'api','settings':{'url':'/assets/input/not-a-node-reference.png'}}]})
    original=scope['read_json'];scope['read_json']=MagicMock(side_effect=original)
    query=SimpleNamespace(urls=['http://localhost/assets/input/shared.png?cache=1'],canvas_id='one')
    first=scope['canvas_asset_context'](query,'http://localhost')
    assert len(first['items'])==2 and {r['url'] for r in first['items']}=={'/assets/input/shared.png'}
    assert {c['project'] for c in first['canvases']}=={'p1','p2'}
    assert scope['canvas_asset_context'](query,'http://localhost')==first
    assert scope['read_json'].call_count==2,'warm batch must not parse every canvas again'
    encoded=scope['canvas_asset_context'](SimpleNamespace(urls=['http://localhost/assets/input/%E6%9C%8D%E8%A3%85.png'],canvas_id=''), 'http://localhost')
    assert len(encoded['items'])==2 and all('%E6' in r['url'] for r in encoded['items'])
    remote=scope['canvas_asset_context'](SimpleNamespace(urls=['https://other.test/assets/input/shared.png'],canvas_id=''), 'http://localhost')
    assert remote['items']==[], 'remote paths must not borrow local project membership'
    atomic_write_json(directory/'two.json',{'id':'two','project':'changed','nodes':[]})
    updated=scope['canvas_asset_context'](query,'http://localhost')
    assert len(updated['items'])==1 and scope['read_json'].call_count==3
    atomic_write_json(directory/'one.json',{'id':'one','deleted_at':1,'nodes':[]})
    assert scope['canvas_asset_context'](query,'http://localhost')['canvases']==[]


def test_uploaded_picker_preserves_both_managed_uploads_and_canvas_inputs(tmp_path):
    scope,directory,uploads=actual_queries(tmp_path)
    (uploads/'local.png').write_bytes(b'no image decode needed')
    atomic_write_json(directory/'one.json',{'id':'one','project':'p1','nodes':[
        {'type':'image','url':'/assets/input/old-reference.png'},
        {'type':'image','url':'/assets/output/generated.png'},
        {'type':'video','url':'/assets/input/video.mp4'},
        {'type':'text','url':'/assets/input/document.txt'}]})
    result=scope['upload_picker_index']()
    assert {r['url'] for r in result['items']}=={'/assets/uploads/local.png','/assets/input/old-reference.png'}
    assert result['projection']=='upload-picker'


def test_upload_grants_use_direct_paths_without_enumerating_other_uploads(tmp_path,monkeypatch):
    (tmp_path/'款式').mkdir()
    own=tmp_path/'款式'/'up_123456abcdef_衬衫.png';own.write_bytes(b'metadata only')
    (tmp_path/'foreign.mp4').write_bytes(b'not granted')
    def forbidden(*args,**kwargs):raise AssertionError('ordinary picker must not enumerate the upload tree')
    monkeypatch.setattr(local_uploads.os,'scandir',forbidden)
    url='/assets/uploads/%E6%AC%BE%E5%BC%8F/up_123456abcdef_%E8%A1%AC%E8%A1%AB.png'
    rows=local_uploads.metadata_items(tmp_path,{url,'/assets/input/old.png','/assets/uploads/missing.png',
        '/assets/uploads/../outside.png','/assets/uploads/C:/outside.png','/assets/uploads/.hidden.png'})
    assert len(rows)==1 and rows[0]['url']==url and rows[0]['size']==own.stat().st_size
    assert local_uploads.metadata_items(tmp_path,set())==[]


def test_internal_upload_response_skips_enumeration_and_keeps_canvas_inputs(tmp_path):
    scope,directory,_=actual_queries(tmp_path)
    atomic_write_json(directory/'one.json',{'id':'one','nodes':[{'type':'image','url':'/assets/input/old.png'}]})
    def forbidden(*args,**kwargs):raise AssertionError('internal response must not enumerate uploads')
    scope['local_upload_metadata_items']=forbidden
    response=scope['upload_picker_index'](include_uploads=False)
    assert response['source']=='canvas-inputs-v1'
    assert [row['url'] for row in response['items']]==['/assets/input/old.png']


def test_gateway_upload_merge_rechecks_grants_before_pagination_and_fails_visibly(env,tmp_path,monkeypatch):
    db,api,(a,b)=env
    monkeypatch.setattr(api,'PATH_ROOTS',SimpleNamespace(UPLOAD_ROOT=tmp_path))
    root=tmp_path/'assets'/'uploads';root.mkdir(parents=True)
    for name in ['own.png','foreign.mp4']:(root/name).write_bytes(b'no decoding')
    db.record_resource_owner(a['user_id'],'/assets/uploads/own.png')
    db.record_resource_owner(b['user_id'],'/assets/uploads/foreign.mp4')
    db.record_canvas_owner(a['user_id'],'one');db.record_canvas_owner(b['user_id'],'two')
    data={'projection':'upload-picker','source':'canvas-inputs-v1','items':[
        {'id':c,'canvas_id':c,'url':'/assets/input/'+c+'.png','kind':'image','created_at':1} for c in ['one','two']]}
    args={'page_size':'24'}
    first=post(api,a,'api/local-assets',data,args)
    assert first['total']==2 and {row['url'] for row in first['items']}=={'/assets/uploads/own.png','/assets/input/one.png'}
    other=post(api,b,'api/local-assets',data,args)
    assert other['total']==2 and any(row['kind']=='video' for row in other['items'])
    admin=post(api,{'user_id':'admin','is_admin':True},'api/local-assets',data,args)
    assert admin['total']==4
    connection=db.get_db()
    try:
        connection.execute('UPDATE user_resource_map SET user_id=? WHERE resource_url=?',(b['user_id'],'/assets/uploads/own.png'))
        connection.commit()
    finally:connection.close()
    assert post(api,a,'api/local-assets',data,args)['total']==1
    def fail(*args,**kwargs):raise PermissionError('controlled error')
    monkeypatch.setattr(local_uploads,'metadata_items',fail)
    with pytest.raises(HTTPException) as error:post(api,a,'api/local-assets',data,args)
    assert error.value.status_code==503
    # Old upstreams still return the original full upload-picker envelope.
    assert post(api,a,'api/local-assets',{**data,'source':'legacy'},args)['total']==1


@pytest.mark.parametrize('paged',[True,False])
def test_gateway_sets_own_upload_hint_and_keeps_legacy_request(env,monkeypatch,paged):
    import httpx
    from starlette.requests import Request
    from enterprise import gateway
    db,api,(a,_)=env
    async def run():
        def reply(request):
            assert request.headers.get('x-enterprise-upload-source')==('canvas-inputs-v1' if paged else None)
            return httpx.Response(200,json={'ok':True})
        async with httpx.AsyncClient(base_url='http://upstream',transport=httpx.MockTransport(reply)) as client:
            monkeypatch.setattr(gateway,'_http_client',client)
            async def passthrough(**kwargs):return kwargs['response_body'],{}
            monkeypatch.setattr(gateway,'post_process',passthrough)
            request=Request({'type':'http','method':'GET','scheme':'http','path':'/api/local-assets',
                'query_string':b'page_size=24' if paged else b'',
                'headers':[(b'host',b'localhost'),(b'x-enterprise-upload-source',b'caller-value')]})
            response=await gateway._forward('api/local-assets',request,a,body=b'')
            assert response.status_code==200
    asyncio.run(run())


def post(api,user,path,data,params=None,method='GET',request_body=None):
    body,_=asyncio.run(api.post_process(path,method,200,json.dumps(data).encode(),'application/json',user,
                                       query_params=params or {},request_body=request_body))
    return json.loads(body)


def test_upload_pages_filter_current_owners_and_keep_live_cursor_stable(env):
    db,api,(a,b)=env
    db.record_canvas_owner(a['user_id'],'one');db.record_canvas_owner(b['user_id'],'two')
    rows=[]
    for i in range(7):
        url=f'/assets/uploads/{i}.png';db.record_resource_owner(a['user_id'] if i%2 else b['user_id'],url)
        rows.append({'id':str(i),'url':url,'kind':'image','created_at':i,'_query_position':0})
    rows.extend([{'id':'linked','canvas_id':'one','url':'/assets/input/linked.png','kind':'image','created_at':10,'_query_position':0},
                 {'id':'hidden','canvas_id':'two','url':'/assets/input/hidden.png','kind':'image','created_at':11,'_query_position':0}])
    data={'projection':'upload-picker','items':rows}
    args={'page_size':'2','kind':'image'}
    first=post(api,a,'api/local-assets',data,args)
    assert first['total']==4 and [r['id'] for r in first['items']]==['linked','5']
    # A newer upload before the cursor appears on refresh, not as a duplicate next-page item.
    db.record_resource_owner(a['user_id'],'/assets/uploads/new.png')
    data['items'].insert(0,{'id':'new','url':'/assets/uploads/new.png','kind':'image','created_at':20,'_query_position':0})
    second=post(api,a,'api/local-assets',data,{**args,'cursor':first['next_cursor']})
    assert [r['id'] for r in second['items']]==['3','1'] and second['next_cursor'] is None
    db.set_canvas_owner('one',b['user_id'])
    refreshed=post(api,a,'api/local-assets',data,args)
    assert refreshed['total']==4 and 'linked' not in {r['id'] for r in refreshed['items']}
    assert asyncio.run(api.pre_process('api/local-assets','GET',a,{'page_size':'0'})).status_code==400
    assert asyncio.run(api.pre_process('api/local-assets','GET',b,{**args,'cursor':first['next_cursor']})).status_code==400
    assert post(api,b,'api/local-assets',data,args)['total']==6


def test_context_response_rechecks_current_canvas_ownership(env):
    db,api,(a,b)=env
    db.record_canvas_owner(a['user_id'],'one');db.record_canvas_owner(b['user_id'],'two')
    data={'canvases':[{'id':'one','project':'p1'},{'id':'two','project':'p2'}],
          'items':[{'url':'/assets/input/shared.png','canvas_id':name} for name in ('one','two')]}
    result=post(api,a,'api/canvas-assets/context',data,method='POST')
    assert result['canvases']==[{'id':'one','project':'p1'}] and len(result['items'])==1
    assert db.get_user_resource_urls(a['user_id'])==set(), 'read-only context must not register resource ownership'
    db.set_canvas_owner('one',b['user_id'])
    assert post(api,a,'api/canvas-assets/context',data,method='POST')=={'canvases':[],'items':[]}


def test_exact_lookup_is_authorized_category_scoped_and_not_substring_match(env):
    db,api,(a,b)=env
    rows=[{'id':name,'url':'/assets/library/'+name+'.png','collected_from':'/assets/input/'+name+'.png'} for name in ('a','ab','b')]
    root={'libraries':[{'id':'default','categories':[{'id':'characters','items':rows}]}]}
    atomic_write_json(api._ASSET_LIBRARY_FILE,root)
    for row in rows:db.record_asset_object_owner(a['user_id'] if row['id']!='b' else b['user_id'],'item',row['id'])
    args={'page_size':'1','library_id':'default','category_id':'characters','match_url':'/assets/input/a.png'}
    result=payload(api.handle_collection_query(a,'api/asset-library',args))
    assert result['total']==1 and result['items'][0]['id']=='a'
    assert payload(api.handle_collection_query(b,'api/asset-library',args))['total']==0
    assert payload(api.handle_collection_query(a,'api/asset-library',{**args,'category_id':'other'}))['total']==0
    assert payload(api.handle_collection_query(a,'api/asset-library',{'page_size':1,'item_id':'b'}))['total']==0


@pytest.mark.parametrize('nodes,expected',[
    ([{'id':'one','type':'image','url':'/assets/input/one.png','width':2048,'height':4096},
      {'id':'two','url':'/assets/input/one.png'}, {'type':'video','url':'/assets/input/movie.mp4'},
      {'settings':{'url':'/assets/input/excluded.png'}}], ['/assets/input/one.png']),
    ([{'type':'smart-group','images':[{'url':'/assets/input/a.png'}, {'url':'https://other.test/b.png'}],
       'outputs':{'image':{'url':'/assets/input/c.png'}},'runs':[{'url':'/assets/input/excluded.png'}]}],
     ['/assets/input/a.png','https://other.test/b.png','/assets/input/c.png']),
    ([None,2,{'kind':'workflow','url':'/assets/input/reused.png'},
      {'kind':'image','url':'/assets/input/reused.png'},{'url':'javascript:bad'},
      {'type':'image','url':'/assets/input/good.png'}],['/assets/input/good.png']),
])
def test_url_only_scan_matches_full_extraction_without_building_asset_records(tmp_path,nodes,expected):
    scope,_,_=actual_queries(tmp_path)
    canvas={'id':'canvas','nodes':nodes}
    full=scope['extract_canvas_assets'](canvas)
    assert [r['url'] for r in full if r['kind']=='image']==expected
    def forbidden(*args,**kwargs):raise AssertionError('URL query must not build names, records or IDs')
    scope['canvas_record']=forbidden;scope['canvas_asset_name']=forbidden
    scope['hashlib']=SimpleNamespace(sha1=forbidden)
    assert list(scope['character_asset_urls'](canvas))==expected


def test_write_catalog_preserves_owner_registration_and_legacy_full_response(env):
    db,api,(a,b)=env
    own={'id':'own','url':'/assets/library/own.png'};foreign={'id':'foreign','url':'/assets/library/foreign.png'}
    created={'id':'created','url':'/assets/library/created.png','kind':'image'}
    db.record_asset_object_owner(a['user_id'],'item','own')
    db.record_asset_object_owner(b['user_id'],'item','foreign')
    data={'library':{'libraries':[{'id':'default','categories':[{'id':'characters','items':[own,foreign,created]}]}]},'item':created}
    request_body=json.dumps({'library_id':'default','category_id':'characters','url':'/assets/input/original.png'}).encode()
    result=post(api,a,'api/asset-library/items',data,{'catalog':'1'},'POST',request_body)
    assert result['item']==created and result['projection']=='catalog'
    category=result['library']['libraries'][0]['categories'][0]
    assert category['item_count']==2 and 'items' not in category
    assert {r['id'] for r in category['preview_items']}=={'own','created'}
    assert db.get_resource_owner(created['url'])==a['user_id']
    stored=db.get_asset_object('item','created')
    assert stored['parent_library_id']=='default' and stored['parent_category_id']=='characters'
    legacy=post(api,a,'api/asset-library/items',data,method='POST',request_body=request_body)
    assert 'projection' not in legacy
    assert {r['id'] for r in legacy['library']['libraries'][0]['categories'][0]['items']}=={'own','created'}
    aliased={**data,'asset_library':data['library']['libraries'][0],
             'category':data['library']['libraries'][0]['categories'][0]}
    trimmed=post(api,a,'api/asset-library/items',aliased,{'catalog':'1'},'POST',request_body)
    assert 'items' not in trimmed['asset_library']['categories'][0] and 'items' not in trimmed['category']
