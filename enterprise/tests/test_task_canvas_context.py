"""Task provenance/reuse with private SQLite and canvas files; no provider work."""
import asyncio
import json
import sqlite3
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from enterprise import db, interceptors
from enterprise.canvas_task_journal import CanvasTaskJournal, create_task_receipt
from enterprise.generation_task_routes import create_router
from enterprise.generation_tasks import GenerationTaskRepository
from enterprise.task_canvas_context import accepted_source, describe_source


def test_canvas_client_source_and_typed_reuse():
    script = Path(__file__).with_suffix('.js')
    result = subprocess.run(['node', str(script)], capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def context(tmp_path, monkeypatch):
    def connect():
        conn=sqlite3.connect(tmp_path/'owners.db');conn.row_factory=sqlite3.Row;return conn
    with connect() as conn:
        conn.executescript('''
        CREATE TABLE user_task_map(task_type TEXT,task_id TEXT,user_id TEXT,source TEXT,canvas_id TEXT,
            workflow_id TEXT,upstream_task_id TEXT,resource_url TEXT,status TEXT,created_at INTEGER,updated_at INTEGER,
            PRIMARY KEY(task_type,task_id));
        CREATE TABLE user_canvas_task_map(user_id TEXT,task_id TEXT PRIMARY KEY,created_at INTEGER);
        CREATE TABLE user_canvas_map(user_id TEXT,canvas_id TEXT PRIMARY KEY,created_at INTEGER);
        CREATE TABLE user_resource_map(user_id TEXT,resource_url TEXT UNIQUE,source TEXT,created_at INTEGER);
        INSERT INTO user_canvas_map VALUES('alice','classic',1),('alice','smart',1),('bob','foreign',1);
        ''')
    monkeypatch.setattr(db,'get_db',connect)
    monkeypatch.setattr(db,'get_user_by_id',lambda uid:{'id':uid,'role':'admin' if uid=='admin' else 'user',
        'is_admin':uid=='admin'} if uid in {'alice','bob','admin'} else None)
    monkeypatch.setattr(db,'get_asset_item_owner_by_resource',lambda _:None)
    monkeypatch.setattr(interceptors,'_resource_in_user_canvas_scope',lambda *_:False)
    monkeypatch.setattr(interceptors,'_resource_in_user_conversation_scope',lambda *_:False)
    root=tmp_path/'canvases';root.mkdir()
    for cid in ['classic','smart','foreign']:
        (root/(cid+'.json')).write_text(json.dumps({'id':cid,'title':cid+' title','kind':'smart' if cid=='smart' else 'classic','nodes':[{'id':'generator'}]}),encoding='utf-8')
    journal=CanvasTaskJournal(tmp_path/'canvas-tasks')
    return root,journal,connect


def test_new_receipt_retains_verified_origin_after_restart_and_legacy_stays_readable(context):
    root,journal,_=context
    record={'id':'task','type':'online-image','status':'queued','source':{'canvas_id':'classic','node_id':'generator'}}
    create_task_receipt(journal,record,'alice')
    restarted=GenerationTaskRepository(journal.root)
    result=restarted.detail('alice','task')
    assert result['source']['url']=='/static/canvas.html?id=classic&focus_node=generator'
    assert result['source']['node_available']
    assert restarted.detail('bob','task') is None
    record.update(id='legacy');record.pop('source')
    create_task_receipt(journal,record,'alice')
    assert restarted.detail('alice','legacy')['source']=={'available':False,'message':'此历史任务未记录来源画布'}
    assert 'source' not in journal.get('legacy')


def test_invalid_foreign_or_unsaved_source_prevents_task_receipt(context):
    root,journal,_=context
    for source,status in [({'canvas_id':'foreign','node_id':'generator'},403),
                          ({'canvas_id':'classic','node_id':'missing'},409)]:
        with pytest.raises(HTTPException) as exc:
            create_task_receipt(journal,{'id':'denied','type':'video','source':source},'alice')
        assert exc.value.status_code==status and journal.get('denied') is None
    assert accepted_source({'canvas_id':'foreign','node_id':'generator'},'admin',root)
    create_task_receipt(journal,{'id':'local','type':'comfy','source':{'canvas_id':'foreign','node_id':'generator'}})
    assert 'source' not in journal.get('local')  # Legacy anonymous loopback does not gain an origin assertion.


def test_source_rechecks_current_access_deleted_canvas_and_missing_node(context):
    root,_,connect=context
    source={'canvas_id':'smart','node_id':'generator'}
    assert 'smart-canvas.html' in describe_source(source,'alice',root)['url']
    path=root/'smart.json';data=json.loads(path.read_text());data['nodes']=[];path.write_text(json.dumps(data))
    info=describe_source(source,'alice',root)
    assert info['available'] and not info['node_available'] and 'focus_node' not in info['url']
    with connect() as conn:conn.execute("UPDATE user_canvas_map SET user_id='bob' WHERE canvas_id='smart'")
    info=describe_source(source,'alice',root)
    assert not info['available'] and 'title' not in info and 'url' not in info
    data['deleted_at']=123;path.write_text(json.dumps(data))
    assert not describe_source(source,'admin',root)['available']


def test_reuse_is_owned_task_plus_current_target_access_and_resource_access(context):
    root,journal,connect=context
    create_task_receipt(journal,{'id':'result','type':'video','status':'succeeded','result':{'items':[
        {'url':'/output/owned.mp4','kind':'video'}, {'url':'/output/foreign.png','kind':'image'},
        {'url':'https://foreign.invalid/a.png','kind':'image'}]}},'alice')
    with connect() as conn:conn.execute("INSERT INTO user_resource_map VALUES('bob','/output/foreign.png','fixture',1)")
    before=(root/'classic.json').read_bytes()
    app=FastAPI();app.include_router(create_router(journal))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            path='/_enterprise_internal/generation-tasks/result'
            headers={'X-Enterprise-User-ID':'alice'}
            assert (await client.get(path+'?target_canvas_id=foreign',headers=headers)).status_code==403
            value=(await client.get(path+'?target_canvas_id=classic',headers=headers)).json()
            assert value['reuse_allowed'] and value['items']==[{'url':'/output/owned.mp4','kind':'video'}]
            assert (await client.get(path+'?target_canvas_id=classic',headers={'X-Enterprise-User-ID':'bob'})).status_code==404
            assert (await client.get(path)).status_code==401
    asyncio.run(run())
    assert (root/'classic.json').read_bytes()==before  # Client's normal save owns the mutation.
    assert db.get_resource_owner('/output/foreign.png')=='bob'
