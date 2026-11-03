"""Current scoped ownership must match the original full policy, not replace it."""
import json
from copy import deepcopy

import pytest

from enterprise import collection_query as query
from enterprise.local_json import atomic_write_json
from enterprise.tests.test_collection_query import env, payload


def original_page(api, user, document, params):
    data={'library':deepcopy(document)}
    api.filter_asset_library(user,data)
    if 'catalog' in params:
        return {'library':query.library_catalog(data['library']),'projection':'catalog'}
    return query.page(list(query.library_items(data['library'])),params,actor=user['user_id'],source='library',
                      revision=query.file_revision(api._ASSET_LIBRARY_FILE))


@pytest.mark.parametrize('shape',['libraries','legacy','empty-libraries'])
def test_scoped_pages_and_catalog_match_original_policy_and_tokens(env,shape):
    db,api,(a,b)=env
    items=[]
    for i in range(32):
        item={'id':f'i{i}','name':'款式 shirt '+str(i),'tags':['summer'],'kind':'image','created_at':1,
              'url':f'/assets/library/{i}.png','collected_from':f'/assets/input/{i}.png'}
        owner=a if i%2 else b
        if i%4==0:db.record_asset_object_owner(owner['user_id'],'item',item['id'])
        elif i%4==1:db.record_resource_owner(owner['user_id'],item['url'])
        elif i%4==2:db.record_asset_object_owner(owner['user_id'],'item','old-'+item['id'],resource_url=item['url'])
        items.append(item)
    for suffix in ['one','two']:
        item={'id':'','url':f'/assets/library/no-id-{suffix}.png','created_at':1,'kind':'image'}
        db.record_resource_owner(a['user_id'],item['url']);items.append(item)
    items.append({**items[1],'name':'duplicate ID','url':'/assets/library/duplicate.png'})
    db.record_resource_owner(a['user_id'],items[-1]['url'])
    default={'id':'default','categories':[{'id':'characters','items':items}]}
    root={'updated_at':1,'libraries':[default,
        {'id':'own-lib','categories':[{'id':'own-cat','items':deepcopy(items)}, {'id':'foreign-cat','items':deepcopy(items)}]},
        {'id':'foreign-lib','categories':[{'id':'delegated-cat','items':deepcopy(items)}]}]}
    db.record_asset_object_owner(a['user_id'],'library','own-lib')
    db.record_asset_object_owner(b['user_id'],'library','foreign-lib')
    db.record_asset_object_owner(b['user_id'],'category','foreign-cat')
    db.record_asset_object_owner(a['user_id'],'category','delegated-cat')
    if shape=='legacy':root={'updated_at':1,'categories':default['categories']}
    if shape=='empty-libraries':root={'libraries':[],'categories':default['categories']}
    atomic_write_json(api._ASSET_LIBRARY_FILE,root);before=api._ASSET_LIBRARY_FILE.read_bytes()
    for user in [a,b,{'user_id':'admin','is_admin':True}]:
        for params in [{'page_size':3},{'page_size':3,'sort':'oldest'},{'page_size':3,'q':'款式'},
                       {'page_size':3,'library_id':'default','category_id':'characters','kind':'image'},
                       {'page_size':3,'item_id':'i1'},{'page_size':3,'match_url':'/assets/input/1.png'}, {'catalog':'1'}]:
            request=dict(params)
            while True:
                expected=original_page(api,user,root,request)
                actual=payload(api.handle_collection_query(user,'api/asset-library',request))
                assert actual==expected,(shape,params,user['user_id'])
                if not actual.get('next_cursor'):break
                request={**params,'cursor':actual['next_cursor']}
    assert api._ASSET_LIBRARY_FILE.read_bytes()==before


def test_precedence_current_transfer_and_lookup_invalidation(env):
    db,api,(a,b)=env
    rows=[{'id':'explicit','url':'/assets/library/priority.png','kind':'image'},
          {'id':'missing-current','url':'/assets/library/legacy.png','kind':'image'},
          {'id':'resource-first','url':'/assets/library/resource.png','kind':'image'}]
    root={'libraries':[{'id':'default','categories':[{'id':'characters','items':rows}]}]}
    atomic_write_json(api._ASSET_LIBRARY_FILE,root)
    db.record_resource_owner(a['user_id'],rows[0]['url'])
    db.record_asset_object_owner(b['user_id'],'item','explicit')
    db.record_asset_object_owner(a['user_id'],'item','old-early',resource_url=rows[1]['url'])
    db.record_asset_object_owner(b['user_id'],'item','old-later',resource_url=rows[1]['url'])
    db.record_resource_owner(b['user_id'],rows[2]['url'])
    db.record_asset_object_owner(a['user_id'],'item','old-resource',resource_url=rows[2]['url'])
    with db.get_db() as connection:
        connection.execute("UPDATE user_asset_object_map SET updated_at=1 WHERE object_id='old-early'")
        connection.execute("UPDATE user_asset_object_map SET updated_at=2 WHERE object_id='old-later'")
    params={'page_size':24}
    assert payload(api.handle_collection_query(a,'api/asset-library',params))['total']==0
    first_lookup=api._COLLECTION_QUERIES.library_lookup(api._COLLECTION_QUERIES.read(api._ASSET_LIBRARY_FILE,'library')[0],api._asset_library_item_resource_url)
    with db.get_db() as connection:
        connection.execute("UPDATE user_asset_object_map SET user_id=? WHERE object_id='explicit'",(a['user_id'],))
        connection.execute("UPDATE user_resource_map SET user_id=? WHERE resource_url=?",(a['user_id'],rows[2]['url']))
    actual=payload(api.handle_collection_query(a,'api/asset-library',params))
    assert actual['total']==2
    assert actual==original_page(api,a,root,params)
    # A new file revision invalidates only navigation, not ownership facts.
    root['libraries'][0]['categories'][0]['items']=rows[:1];atomic_write_json(api._ASSET_LIBRARY_FILE,root)
    doc,_=api._COLLECTION_QUERIES.read(api._ASSET_LIBRARY_FILE,'library')
    assert api._COLLECTION_QUERIES.library_lookup(doc,api._asset_library_item_resource_url) is not first_lookup
    assert payload(api.handle_collection_query(a,'api/asset-library',params))['total']==1


def test_scope_excludes_unrelated_enterprise_facts_and_cache_budget(env,monkeypatch):
    db,api,(a,b)=env
    rows=[{'id':f'row-{i}','url':f'/assets/library/{i}.png','kind':'image'} for i in range(40)]
    root={'libraries':[{'id':'default','categories':[{'id':'characters','items':rows}]}]}
    atomic_write_json(api._ASSET_LIBRARY_FILE,root)
    for i,row in enumerate(rows):db.record_asset_object_owner(a['user_id'] if i<3 else b['user_id'],'item',row['id'],resource_url=row['url'])
    for i in range(50):db.record_resource_owner(b['user_id'],f'/assets/output/unrelated-{i}.png')
    doc,_=api._COLLECTION_QUERIES.read(api._ASSET_LIBRARY_FILE,'library')
    lookup=api._COLLECTION_QUERIES.library_lookup(doc,api._asset_library_item_resource_url)
    snapshot,positions=db.asset_library_query_snapshot(a['user_id'],lookup)
    assert len(positions)==3 and len(snapshot['objects'])==3 and snapshot['resources']=={}
    assert len(snapshot['item_resources'])==3
    assert api._COLLECTION_QUERIES.library_lookup(doc,api._asset_library_item_resource_url) is lookup
    # An oversized source is still queryable, without retaining the derived map.
    store=query.QuerySnapshots(max_cached_bytes=1);doc,_=store.read(api._ASSET_LIBRARY_FILE,'library')
    assert store.library_lookup(doc,api._asset_library_item_resource_url) is not store.library_lookup(doc,api._asset_library_item_resource_url)


def test_legacy_resource_timestamp_ties_match_existing_snapshot(env):
    db,api,(a,b)=env
    rows=[]
    for i in range(6):
        url=f'/assets/library/tie-{i}.png';rows.append({'id':f'current-{i}','url':url})
        for j,owner in enumerate([a,b,a]):db.record_asset_object_owner(owner['user_id'],'item',f'legacy-{j}-{i}',resource_url=url)
    with db.get_db() as connection:connection.execute('UPDATE user_asset_object_map SET updated_at=1')
    root={'libraries':[{'id':'default','categories':[{'id':'characters','items':rows}]}]}
    atomic_write_json(api._ASSET_LIBRARY_FILE,root)
    for user in [a,b]:assert payload(api.handle_collection_query(user,'api/asset-library',{'page_size':24}))==original_page(api,user,root,{'page_size':24})


def test_large_candidate_chunks_preserve_complete_counts_and_cursor(env):
    db,api,(a,b)=env
    rows=[{'id':f'chunk-{i}','url':f'/assets/library/chunk-{i}.png','kind':'image','created_at':i} for i in range(803)]
    root={'libraries':[{'id':'default','categories':[{'id':'characters','items':rows}]}]}
    atomic_write_json(api._ASSET_LIBRARY_FILE,root)
    with db.get_db() as connection:
        connection.executemany('INSERT INTO user_asset_object_map (object_type,object_id,user_id,resource_url,created_at,updated_at) VALUES (?,?,?,?,?,?)',
            [('item',row['id'],a['user_id'],row['url'],1,1) for row in rows])
    document,_=api._COLLECTION_QUERIES.read(api._ASSET_LIBRARY_FILE,'library')
    lookup=api._COLLECTION_QUERIES.library_lookup(document,api._asset_library_item_resource_url)
    snapshot,positions=db.asset_library_query_snapshot(a['user_id'],lookup)
    assert len(positions)==803 and len(snapshot['objects'])==803 and len(snapshot['item_resources'])==803
    params={'page_size':100}
    for _ in range(2):
        expected=original_page(api,a,root,params);actual=payload(api.handle_collection_query(a,'api/asset-library',params))
        assert actual==expected
        params={**params,'cursor':actual['next_cursor']}
