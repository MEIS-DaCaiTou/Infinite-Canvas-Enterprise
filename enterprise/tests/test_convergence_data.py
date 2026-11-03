import asyncio
import json
import time
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from enterprise import local_json
from enterprise.tests.test_convergence_resources import main_functions


def data_scope(tmp_path):
    import threading
    scope=main_functions({'load_asset_library','save_asset_library','save_canvas','load_canvas','update_canvas','touch_canvas'},
        document_lock=local_json.document_lock,read_json=local_json.read_json,atomic_write_json=local_json.atomic_write_json,
        ASSET_LIBRARY_PATH=str(tmp_path/'library.json'),DATA_DIR=str(tmp_path),CANVAS_LOCK=threading.RLock(),
        now_ms=lambda:int(time.time()*1000),default_asset_library=lambda:{'libraries':[],'updated_at':0},
        normalize_asset_library=lambda x:x,sort_asset_library_items=lambda x:None,GLOBAL_LOOP=None,
        canvas_path=lambda cid:str(tmp_path/(cid+'.json')),normalize_canvas_kind=lambda x:x,canvas_record=lambda x:x)
    async def notify(*a):pass
    scope['manager']=SimpleNamespace(broadcast_canvas_updated=notify)
    return scope


def test_corrupt_directory_is_never_defaulted_or_overwritten(tmp_path):
    scope=data_scope(tmp_path);original=scope['load_asset_library']();old=dict(original)
    original['libraries']=['alice'];scope['save_asset_library'](original)
    with pytest.raises(HTTPException) as e:scope['save_asset_library'](old)
    assert e.value.status_code==409
    path=tmp_path/'library.json';path.write_bytes(b'{broken-original')
    for operation in [lambda:scope['load_asset_library'](),lambda:scope['save_asset_library'](original)]:
        with pytest.raises(HTTPException) as e:operation()
        assert e.value.status_code==503 and path.read_bytes()==b'{broken-original'


def test_corrupt_project_directory_cannot_be_reinitialized(tmp_path):
    path=tmp_path/'projects.json';path.write_bytes(b'{original-corrupt-project')
    scope=main_functions({'load_projects'},read_json=local_json.read_json,PROJECTS_PATH=str(path))
    with pytest.raises(HTTPException) as e:scope['load_projects']()
    assert e.value.status_code==503 and path.read_bytes()==b'{original-corrupt-project'


def test_directory_replace_failure_preserves_prior_bytes(tmp_path,monkeypatch):
    scope=data_scope(tmp_path);library=scope['load_asset_library']();before=(tmp_path/'library.json').read_bytes()
    monkeypatch.setattr(local_json.os,'replace',lambda *a:(_ for _ in ()).throw(OSError('injected')))
    with pytest.raises(OSError):scope['save_asset_library'](library)
    assert (tmp_path/'library.json').read_bytes()==before


def test_legacy_category_directory_without_revision_can_be_saved(tmp_path):
    scope=data_scope(tmp_path)
    normalize=main_functions({'normalize_asset_library'},default_asset_library=lambda:{'categories':[]},
        sanitize_asset_name=lambda value,fallback:value or fallback,sort_asset_library_items=lambda _:None,
        migrate_asset_item_registrations=lambda _:None,now_ms=lambda:1000)['normalize_asset_library']
    scope['normalize_asset_library']=normalize
    (tmp_path/'library.json').write_text(json.dumps({'categories':[{'id':'old','type':'image','items':[]}]}))
    library=scope['load_asset_library']();assert library['updated_at']==0
    scope['save_asset_library'](library)
    assert scope['load_asset_library']()['updated_at']>0


def test_canvas_admin_transfer_advances_revision_and_rejects_old_save(tmp_path):
    scope=data_scope(tmp_path);scope['save_canvas']({'id':'board','project':'old','nodes':['original'],'updated_at':1})
    first=scope['load_canvas']('board');base=first['updated_at']
    transfer=main_functions({'set_canvas_project'},source='enterprise/db.py',_canvas_json_path=scope['canvas_path'],DEFAULT_PROJECT_ID='default')
    assert transfer['set_canvas_project']('board','new')==(True,'old')
    after=scope['load_canvas']('board');assert after['nodes']==['original'] and after['updated_at']>base
    payload=SimpleNamespace(base_updated_at=base,title='stale',icon='',nodes=['stale'],connections=[],viewport={},logs=[],settings={},client_id='tab-b')
    with pytest.raises(HTTPException) as e:asyncio.run(scope['update_canvas']('board',payload))
    assert e.value.status_code==409 and scope['load_canvas']('board')==after
    payload.base_updated_at=0
    with pytest.raises(HTTPException):asyncio.run(scope['update_canvas']('board',payload))
    assert scope['load_canvas']('board')==after


def test_touch_waits_for_whole_document_mutation(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    scope=data_scope(tmp_path);scope['save_canvas']({'id':'board','project':'old','nodes':['old']})
    path=tmp_path/'board.json';started=threading.Event()
    with ThreadPoolExecutor() as pool:
        with local_json.document_lock(path):
            def touch():started.set();asyncio.run(scope['touch_canvas']('board'))
            task=pool.submit(touch);assert started.wait(2)
            latest=local_json.read_json(path);latest.update(project='new',nodes=['latest'])
            local_json.atomic_write_json(path,latest)
        task.result(timeout=5)
    assert scope['load_canvas']('board')['nodes']==['latest']
    assert scope['load_canvas']('board')['project']=='new'


def test_viewing_from_second_page_does_not_change_content_base(tmp_path):
    scope=data_scope(tmp_path);scope['save_canvas']({'id':'board','project':'old','nodes':['saved']})
    base=scope['load_canvas']('board')['updated_at']
    viewed=asyncio.run(scope['touch_canvas']('board'))
    assert viewed['updated_at']==base
    assert scope['load_canvas']('board')['last_opened_at']>=base


def test_admin_owner_failure_compensates_project_without_discarding_nodes(tmp_path):
    scope=data_scope(tmp_path);scope['save_canvas']({'id':'board','project':'old','nodes':['keep']})
    transfer=main_functions({'set_canvas_project'},source='enterprise/db.py',_canvas_json_path=scope['canvas_path'],DEFAULT_PROJECT_ID='default')['set_canvas_project']
    fake=SimpleNamespace(_canvas_json_path=scope['canvas_path'],DEFAULT_PROJECT_ID='default',
        get_user_by_id=lambda _: {'id':'bob'},get_canvas_owner=lambda _:'alice',get_canvas_project=lambda _:'old',
        project_exists=lambda _:True,get_project_owner=lambda _:'bob',set_canvas_project=transfer,
        assign_canvas_owner=lambda *a:(_ for _ in ()).throw(OSError('injected DB failure')))
    handler=main_functions({'assign_canvas_owner'},source='enterprise/admin_api.py',edb=fake,_require_admin=lambda _:{'user_id':'admin'})
    class Request:
        async def json(self):return {'user_id':'bob','target_project_id':'new'}
    with pytest.raises(OSError):asyncio.run(handler['assign_canvas_owner']('board',Request()))
    assert scope['load_canvas']('board')['project']=='old' and scope['load_canvas']('board')['nodes']==['keep']


def test_document_read_modify_write_serializes_two_processes(tmp_path):
    root=Path(__file__).parents[2]
    path=tmp_path/'counter.json';local_json.atomic_write_json(path,{'count':0})
    script="""
import sys,time
sys.path.insert(0,sys.argv[1])
from enterprise.local_json import document_lock,read_json,atomic_write_json
for _ in range(12):
    with document_lock(sys.argv[2]):
        value=read_json(sys.argv[2]);time.sleep(.003)
        value['count']+=1;atomic_write_json(sys.argv[2],value)
"""
    processes=[subprocess.Popen([sys.executable,'-B','-c',script,str(root),str(path)]) for _ in range(2)]
    try:
        for proc in processes:assert proc.wait(timeout=20)==0
    finally:
        for proc in processes:
            if proc.poll() is None:proc.kill();proc.wait()
    assert local_json.read_json(path)=={'count':24}


@pytest.mark.parametrize('principal',[None,{'user_id':'alice','is_admin':False,'auth_version':2}])
def test_ws_revocation_stops_cached_admin_broadcast(principal):
    from enterprise import ws
    class Socket:
        def __init__(self):self.messages=[];self.closed=False
        async def send_text(self,value):self.messages.append(value)
        async def close(self,code):self.closed=code==1008
    async def run():
        socket=Socket();state=[{'user_id':'alice','is_admin':True,'auth_version':1}]
        conn=ws.register_connection(socket,state[0],'/ws',validate_session=lambda:state[0])
        try:
            assert await ws.send_to_connection(conn,{'type':'fixture-control'})
            state[0]=principal
            assert not await ws.send_to_connection(conn,{'type':'new_image','prompt':'must not send'})
            assert len(socket.messages)==1 and socket.closed
        finally:ws.forget_connection(conn)
    asyncio.run(run())


def test_codex_timeout_reaps_owned_process(monkeypatch,tmp_path):
    from fastapi import HTTPException
    class Proc:
        pid=123456;returncode=None
        killed=False;waited=False
        async def communicate(self,**kw):await asyncio.sleep(2)
        def kill(self):self.killed=True;self.returncode=-9
        async def wait(self):self.waited=True;self.returncode=-9;return -9
    proc=Proc();calls=[]
    async def spawn(*args,**kw):
        calls.append(args)
        if args[0]=='taskkill':
            class Killer:
                async def wait(self):proc.killed=True;proc.returncode=-9;return 0
            return Killer()
        return proc
    scope=main_functions({'run_codex_cli'},BASE_DIR=str(tmp_path),OUTPUT_OUTPUT_DIR=str(tmp_path),
        codex_cli_executable=lambda:'fixture-cli',codex_model_for_exec=lambda _:None,codex_timeout=lambda:.01)
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    with pytest.raises(HTTPException) as e:asyncio.run(scope['run_codex_cli']('fixture',timeout=.01,output_last_message=False))
    assert e.value.status_code==504 and proc.killed and proc.waited
    assert all('123456' in args for args in calls if args[0]=='taskkill')


def test_ws_revocation_rechecked_after_waiting_for_send_lock():
    from enterprise import ws
    class Socket:
        messages=[]
        async def send_text(self,text):self.messages.append(text)
        async def close(self,code):pass
    async def run():
        current=[{'user_id':'alice','is_admin':True,'auth_version':1}]
        socket=Socket();conn=ws.register_connection(socket,current[0],'/ws',validate_session=lambda:current[0])
        try:
            await conn.lock.acquire()
            pending=asyncio.create_task(ws.send_to_connection(conn,{'type':'fixture-sensitive'}))
            await asyncio.sleep(.05)
            current[0]=None;conn.lock.release()
            assert await pending is False and socket.messages==[]
        finally:ws.forget_connection(conn)
    asyncio.run(run())


@pytest.mark.parametrize('kind',['classic','smart'])
def test_real_main_and_existing_editor_roundtrip(tmp_path,kind):
    from enterprise.tests.test_canvas_image_recovery_main import BOOTSTRAP,ROOT
    app=tmp_path/'install/releases/fixture';(app/'static').mkdir(parents=True)
    (app/'main.py').write_text('# isolated fixture')
    script=BOOTSTRAP+'''
import subprocess
from enterprise.paths import resolve_database_path
example=(Path(sys.argv[1])/'enterprise.env.example').read_text(encoding='utf-8')
configured=next(line.split('=',1)[1] for line in example.splitlines() if line.startswith('DB_PATH='))
assert resolve_database_path(roots,configured)==resolve_database_path(roots,None)
kind=sys.argv[4]
created=asyncio.run(main.create_canvas(main.CanvasCreateRequest(title='roundtrip',kind=kind)))
initial=roots.DATA_ROOT/'initial.json';initial.write_text(json.dumps(created))
payload_file=roots.DATA_ROOT/'payload.json'
driver=str(Path(sys.argv[1])/'enterprise/tests/test_canvas_persistence.js')
subprocess.run(['node',driver,'save',kind,str(initial),str(payload_file)],check=True)
payload=main.CanvasSaveRequest(**json.loads(payload_file.read_text(encoding='utf-8')))
saved=asyncio.run(main.update_canvas(created['canvas']['id'],payload))
reopened=asyncio.run(main.get_canvas(created['canvas']['id']))
initial.write_text(json.dumps(reopened))
subprocess.run(['node',driver,'reopen',kind,str(initial),str(payload_file)],check=True)
'''
    result=subprocess.run([sys.executable,'-B','-c',script,str(ROOT),str(tmp_path/'install'),str(tmp_path/'runtime'),kind],
        cwd=ROOT,capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stdout+result.stderr

@pytest.mark.parametrize('kind', ['batch', 'category', 'single'])
@pytest.mark.parametrize('failure', ['conflict', 'io'])
def test_asset_delete_failed_commit_preserves_files(tmp_path, kind, failure):
    from pathlib import Path
    library_dir=tmp_path/'library';library_dir.mkdir()
    media=library_dir/'image.png';media.write_bytes(b'original media')
    library={'updated_at':1,'libraries':[{'id':'lib','categories':[{'id':'cat','dir':'','type':'image','items':[{'id':'item','url':'/assets/library/image.png'}]}]}]}
    before=json.loads(json.dumps(library))
    def save(_):
        if failure=='conflict':raise HTTPException(409,'revision changed')
        raise OSError('injected directory write failure')
    scope=main_functions({'batch_delete_asset_library_items','delete_asset_library_category','delete_asset_library_item','remove_asset_library_file'},
        load_asset_library=lambda:json.loads(json.dumps(library)),save_asset_library=save,
        ASSET_LIBRARY_DIR=str(library_dir),output_file_from_url=lambda _:str(media),
        find_asset_category_with_library=lambda lib,*_: (lib['libraries'][0],lib['libraries'][0]['categories'][0]))
    call={'batch':lambda:scope['batch_delete_asset_library_items'](SimpleNamespace(ids=['item'],library_id='lib')),
          'category':lambda:scope['delete_asset_library_category']('cat','lib'),
          'single':lambda:scope['delete_asset_library_item']('item')}[kind]
    with pytest.raises((HTTPException,OSError)):asyncio.run(call())
    assert media.read_bytes()==b'original media'
    assert library==before


def test_asset_delete_success_and_concurrent_category_file_preserved(tmp_path):
    library_dir=tmp_path/'library';category_dir=library_dir/'folder';category_dir.mkdir(parents=True)
    media=category_dir/'image.png';media.write_bytes(b'media')
    concurrent_file=category_dir/'uncommitted-new.png';concurrent_file.write_bytes(b'new')
    library={'libraries':[{'id':'lib','categories':[{'id':'cat','dir':'folder','type':'image','items':[{'id':'item','url':'media'}]}]}]}
    events=[]
    scope=main_functions({'delete_asset_library_category','remove_asset_library_file'},load_asset_library=lambda:library,
        save_asset_library=lambda _:events.append('committed'),ASSET_LIBRARY_DIR=str(library_dir),
        output_file_from_url=lambda _:str(media),
        find_asset_category_with_library=lambda lib,*_: (lib['libraries'][0],lib['libraries'][0]['categories'][0]))
    original=scope['remove_asset_library_file']
    def remove(item):
        assert events==['committed'];original(item)
    scope['remove_asset_library_file']=remove
    asyncio.run(scope['delete_asset_library_category']('cat','lib'))
    assert not media.exists() and concurrent_file.read_bytes()==b'new'
    assert library['libraries'][0]['categories']==[]


def test_asset_cleanup_never_deletes_original_output(tmp_path):
    library_dir=tmp_path/'library';library_dir.mkdir()
    original=tmp_path/'output.png';original.write_bytes(b'original')
    scope=main_functions({'remove_asset_library_file'},ASSET_LIBRARY_DIR=str(library_dir),output_file_from_url=lambda _:str(original))
    scope['remove_asset_library_file']({'url':'/output/output.png'})
    assert original.read_bytes()==b'original'
