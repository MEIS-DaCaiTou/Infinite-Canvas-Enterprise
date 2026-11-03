"""Directory/history reads: bounded local fixtures, original permission boundary."""
import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from enterprise import local_json
from enterprise import history_records as history_store
from enterprise.tests.test_convergence_resources import main_functions


def listing_scope(tmp_path):
    reads = []
    def read(path):
        reads.append((Path(path).name, threading.get_ident()))
        return local_json.read_json(path)
    def history_read(path):
        reads.append((Path(path).name, threading.get_ident()))
        return history_store.read_records(path)
    scope = main_functions({
        '_read_canvas_for_listing', 'iter_canvas_records', 'cleanup_expired_canvas_trash',
        'canvas_record', 'normalize_canvas_kind', 'normalize_canvas_color', 'project_record',
        'list_projects', 'list_canvases', 'list_deleted_canvases', 'canvases', 'get_projects',
        'trashed_canvases', 'load_history_records', 'get_history_api',
    }, CANVAS_DIR=str(tmp_path), CANVAS_LOCK=threading.RLock(), document_lock=local_json.document_lock,
        read_json=read, now_ms=lambda:10000, CANVAS_TRASH_RETENTION_MS=1000,
        CANVAS_COLORS={'', 'red'}, DEFAULT_PROJECT_ID='default', HISTORY_FILE=str(tmp_path/'history.json'),
        ensure_default_project=lambda:[{'id':'default','name':'Default'},{'id':'mine','name':'Mine'}],
        history_records=SimpleNamespace(read_records=history_read,HistoryUnavailable=history_store.HistoryUnavailable))
    return scope, reads


def canvas_file(tmp_path, name, **values):
    path=tmp_path/(name+'.json')
    path.write_text(json.dumps({'id':name,'nodes':[],'updated_at':100,'project':'mine',**values}))
    return path


@pytest.mark.parametrize('deleted', [False, True])
def test_one_read_per_nonexpired_canvas_and_stable_projection(tmp_path, deleted):
    scope, reads=listing_scope(tmp_path)
    canvas_file(tmp_path, 'active', last_opened_at=200)
    canvas_file(tmp_path, 'trash', deleted_at=9500)
    records=scope['iter_canvas_records'](include_deleted=deleted)
    assert len(reads)==2 and len(records)==1
    assert records[0]['id']==('trash' if deleted else 'active')
    if not deleted:
        assert records[0]['updated_at']==200 and records[0]['content_updated_at']==100


def test_expired_trash_is_rechecked_and_only_expired_document_removed(tmp_path):
    scope, reads=listing_scope(tmp_path)
    expired=canvas_file(tmp_path,'expired',deleted_at=1000)
    active=canvas_file(tmp_path,'active')
    assert [x['id'] for x in scope['iter_canvas_records']()]==['active']
    assert not expired.exists() and active.exists()
    assert [name for name,_ in reads].count('expired.json')==2


def test_restore_during_expiration_scan_is_not_deleted(tmp_path):
    scope,_=listing_scope(tmp_path)
    path=canvas_file(tmp_path,'restored',deleted_at=1000)
    original=scope['read_json']; first=True
    def read(value):
        nonlocal first
        result=original(value)
        if first:
            first=False
            local_json.atomic_write_json(path,{**result,'deleted_at':0,'updated_at':101})
        return result
    scope['read_json']=read
    assert scope['iter_canvas_records']()[0]['id']=='restored'
    assert path.exists() and local_json.read_json(path)['deleted_at']==0


def test_project_counts_remain_default_but_can_be_omitted_without_scan(tmp_path):
    scope, reads=listing_scope(tmp_path)
    canvas_file(tmp_path,'one')
    records=scope['list_projects']()
    assert next(p for p in records if p['id']=='mine')['canvas_count']==1
    reads.clear()
    response=asyncio.run(scope['get_projects'](False))
    assert response['counts_included'] is False and not reads
    assert all('canvas_count' not in p for p in response['projects'])


@pytest.mark.parametrize('endpoint', ['canvases','trashed_canvases','get_projects'])
def test_directory_disk_reads_do_not_run_on_asgi_loop(tmp_path, endpoint):
    scope,reads=listing_scope(tmp_path)
    canvas_file(tmp_path,'one')
    loop_thread=threading.get_ident()
    asyncio.run(scope[endpoint]())
    assert reads and all(thread!=loop_thread for _,thread in reads)


def test_history_missing_and_corrupt_are_distinct_and_never_rewritten(tmp_path):
    scope,_=listing_scope(tmp_path)
    assert asyncio.run(scope['get_history_api']())==[]
    path=tmp_path/'history.json'; path.write_bytes(b'{original broken data')
    with pytest.raises(HTTPException) as failure:
        asyncio.run(scope['get_history_api']())
    assert failure.value.status_code==503 and path.read_bytes()==b'{original broken data'


def test_history_filter_order_and_read_thread_are_preserved(tmp_path):
    scope,reads=listing_scope(tmp_path)
    (tmp_path/'history.json').write_text(json.dumps([
        {'timestamp':2,'type':'online','images':['/output/new.png']},
        {'timestamp':1,'type':'online','images':['/output/old.png']},
        {'timestamp':3,'type':'online','images':[]},
        {'timestamp':4,'type':'zimage','images':['/output/other.png']},
    ]))
    result=asyncio.run(scope['get_history_api']('online'))
    assert [x['timestamp'] for x in result]==[2,1]
    assert reads[0][1]!=threading.get_ident()


def test_light_project_listing_keeps_both_users_permission_filter(tmp_path):
    def no_scan(_): raise AssertionError('light project listing must not scan canvases')
    scope=main_functions({'filter_project_list'},source='enterprise/interceptors.py',
        _is_admin=lambda u:u.get('is_admin',False), _user_id=lambda u:u['id'],
        edb=SimpleNamespace(get_user_project_ids=lambda uid:{'p-'+uid}),
        DEFAULT_PROJECT_ID='default', _owned_canvas_counts_by_project=no_scan)
    for uid in ['a','b']:
        payload={'counts_included':False,'projects':[{'id':'p-a','canvas_count':99},{'id':'p-b','canvas_count':99}]}
        assert scope['filter_project_list']({'id':uid},payload)
        assert [p['id'] for p in payload['projects']]==['default','p-'+uid]
        assert all('canvas_count' not in p for p in payload['projects'])


def test_legacy_user_project_counts_do_not_include_trash(tmp_path):
    canvas_file(tmp_path,'a')
    canvas_file(tmp_path,'b')
    canvas_file(tmp_path,'trashed',deleted_at=9500)
    scope=main_functions({'_owned_canvas_counts_by_project'},source='enterprise/interceptors.py',
        _CANVAS_DATA_DIR=tmp_path,_load_json_file=local_json.read_json,DEFAULT_PROJECT_ID='default',
        edb=SimpleNamespace(get_canvas_owner=lambda cid:'b' if cid=='b' else 'a',get_project_owner=lambda _:'a'))
    assert scope['_owned_canvas_counts_by_project']('a')=={'mine':1}


def test_unreadable_canvas_is_preserved_and_reported_separately(tmp_path):
    scope,_=listing_scope(tmp_path)
    path=tmp_path/'broken.json';path.write_bytes(b'{original broken canvas')
    canvas_file(tmp_path,'good')
    result=asyncio.run(scope['canvases']())
    assert [c['id'] for c in result['canvases']]==['good']
    assert result['unreadable_canvas_ids']==['broken']
    assert path.read_bytes()==b'{original broken canvas'


def test_unreadable_canvas_count_is_filtered_by_current_ownership():
    scope=main_functions({'filter_canvas_list'},source='enterprise/interceptors.py',
        _is_admin=lambda u:u.get('admin',False),_user_id=lambda u:u['id'],
        edb=SimpleNamespace(get_user_canvas_ids=lambda uid:{uid+'-broken',uid+'-good'}),
        DEFAULT_PROJECT_ID='default',can_access_project=lambda *_:True)
    for actor,expected in [({'id':'a'},1),({'id':'b'},1),({'id':'c'},0),({'id':'admin','admin':True},3)]:
        payload={'canvases':[], 'unreadable_canvas_ids':['a-broken','b-broken','unowned']}
        assert scope['filter_canvas_list'](actor,payload)
        assert payload['unreadable_canvas_count']==expected
        assert 'unreadable_canvas_ids' not in payload
