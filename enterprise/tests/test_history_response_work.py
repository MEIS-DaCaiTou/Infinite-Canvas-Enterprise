"""Actual history call sites and preview handler, no providers or production data."""
import ast
import asyncio
import logging
from pathlib import Path
import threading

from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageOps

from enterprise import history_records


ROOT = Path(__file__).parents[2]


def source_tree():
    return ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))


def test_async_history_completion_keeps_loop_free_and_original_atomic_append(tmp_path, monkeypatch):
    tree=source_tree()
    functions={node.name:node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
    call_sites=[]
    for fn in functions.values():
        if not isinstance(fn,ast.AsyncFunctionDef):continue
        for statement in ast.walk(fn):
            if not isinstance(statement,ast.Expr):continue
            value=statement.value
            if isinstance(value,ast.Call) and isinstance(value.func,ast.Name):
                assert value.func.id!='save_to_history',fn.name
            if isinstance(value,ast.Await) and isinstance(value.value,ast.Call):
                call=value.value
                if isinstance(call.func,ast.Attribute) and call.func.attr=='to_thread' and call.args and isinstance(call.args[0],ast.Name) and call.args[0].id=='save_to_history':
                    call_sites.append((fn.name,statement))
    assert len(call_sites)==7
    scope={'asyncio':asyncio,'logging':logging,'HISTORY_LOCK':threading.Lock(),
           'HISTORY_FILE':tmp_path/'history.json','history_records':history_records}
    exec(compile(ast.Module(body=[functions['save_to_history']],type_ignores=[]),'actual_history_writer','exec'),scope)
    # Execute the exact completion statement from the real online endpoint.
    statement=next(node for name,node in call_sites if name=='build_online_image_result')
    fn=ast.parse('async def complete(result):\n    pass\n    return result').body[0];fn.body[0]=statement
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'actual_online_completion','exec'),scope)
    entered,release=threading.Event(),threading.Event();append=history_records.append_record
    def delayed(*args,**kwargs):
        entered.set();assert release.wait(2);return append(*args,**kwargs)
    monkeypatch.setattr(history_records,'append_record',delayed)
    async def check():
        records=[{'timestamp':1},{'timestamp':2}]
        tasks=[asyncio.create_task(scope['complete'](row)) for row in records]
        try:
            assert await asyncio.to_thread(entered.wait,1)
            await asyncio.sleep(0.01)  # Other requests can run while disk work waits.
            assert not any(task.done() for task in tasks)
        finally:release.set()
        assert await asyncio.gather(*tasks)==records
        assert {row['timestamp'] for row in history_records.read_records(scope['HISTORY_FILE'])}=={1,2}
    asyncio.run(check())


def test_real_2k_4k_previews_bound_cold_decodes_and_keep_warm_hits_free(tmp_path, monkeypatch):
    paths={};originals={}
    for index,size in enumerate([(2048,2048),(4096,2160)]*2):
        path=tmp_path/f'{index}.png';Image.new('RGB',size,(45,93,159)).save(path)
        paths[str(index)]=path;originals[path]=path.read_bytes()
    endpoint=next(node for node in source_tree().body if isinstance(node,ast.AsyncFunctionDef) and node.name=='media_preview')
    endpoint.decorator_list=[]
    scope={'asyncio':asyncio,'time':__import__('time'),'performance':__import__('enterprise.runtime.performance',fromlist=['performance']), 'MEDIA_PREVIEW_PENDING':{},'os':__import__('os'),'tempfile':__import__('tempfile'),'Image':Image,'ImageOps':ImageOps,
           'HTTPException':HTTPException,'FileResponse':FileResponse,'MEDIA_PREVIEW_DIR':str(tmp_path/'cache'),
           'output_file_from_url':lambda url:str(paths[url]),'is_video_preview_file':lambda _:False,
           'image_has_alpha':lambda _:False,
           'media_preview_cache_paths':lambda path,width:(str(tmp_path/'cache'/f'{Path(path).stem}-{width}.webp'),str(tmp_path/'cache'/f'{Path(path).stem}-{width}.png'))}
    exec(compile(ast.Module(body=[endpoint],type_ignores=[]),'actual_preview_handler','exec'),scope)
    lock=threading.Lock();release=threading.Event();two=threading.Event();state={'started':0};open_image=Image.open
    def held_open(*args,**kwargs):
        with lock:
            state['started']+=1
            if state['started']==2:two.set()
        assert release.wait(2)
        return open_image(*args,**kwargs)
    monkeypatch.setattr(Image,'open',held_open)
    async def check():
        scope['MEDIA_PREVIEW_GATE']=asyncio.Semaphore(2)
        tasks=[asyncio.create_task(scope['media_preview'](str(i))) for i in range(4)]
        try:
            assert await asyncio.to_thread(two.wait,1)
            await asyncio.sleep(0.01)
            assert state['started']==2
        finally:release.set()
        replies=await asyncio.gather(*tasks)
        for reply in replies:
            with open_image(reply.path) as image:assert max(image.size)<=512
        assert not list((tmp_path/'cache').glob('*.tmp'))
        assert all(path.read_bytes()==data for path,data in originals.items())
        await scope['MEDIA_PREVIEW_GATE'].acquire();await scope['MEDIA_PREVIEW_GATE'].acquire()
        # Cache lookup bypasses a fully occupied decoder gate.
        await asyncio.wait_for(scope['media_preview']('0'),.2)
        scope['MEDIA_PREVIEW_GATE'].release();scope['MEDIA_PREVIEW_GATE'].release()
        # Same-image viewers share one decoder, not just one published path.
        before=state['started']
        await asyncio.gather(*(scope['media_preview']('0',513) for _ in range(8)))
        assert state['started']==before+1
        with open_image(tmp_path/'cache'/'0-513.webp') as image:image.load()
        monkeypatch.setattr(Image.Image,'save',lambda *a,**kw:(_ for _ in ()).throw(OSError('disk failure')))
        try:await scope['media_preview']('0',514)
        except HTTPException as exc:assert exc.status_code==415
        else:raise AssertionError('failed cache build succeeded')
        assert not list((tmp_path/'cache').glob('*.tmp'))
        assert not (tmp_path/'cache'/'0-514.webp').exists()
    asyncio.run(check())
