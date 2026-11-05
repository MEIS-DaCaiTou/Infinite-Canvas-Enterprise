"""Real file and HTTP-pool boundaries; isolated bytes, no providers/devices."""
import asyncio
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from enterprise.canvas_metadata import CanvasMetadata
from enterprise.local_json import atomic_write_json, read_json
from enterprise.runtime import performance
from enterprise.proxy_transport import streaming_response, needs_body_filter
from enterprise.tests.test_convergence_resources import main_functions
from enterprise.tests.test_convergence_data import data_scope


def test_metadata_reads_only_on_revision_change_and_never_retains_nodes(tmp_path):
    path=tmp_path/'board.json';cache=CanvasMetadata(capacity=2);reads=[]
    atomic_write_json(path, {'id':'board','updated_at':1,'nodes':[{'text':'x'*20000}]*30})
    def load():
        reads.append(1);data=read_json(path)
        if data.get('deleted_at'):raise HTTPException(404)
        return data
    first=cache.get(str(path),load)
    for _ in range(100):assert cache.get(str(path),load)==first
    assert len(reads)==1 and 'nodes' not in next(iter(cache.entries.values()))[1]
    atomic_write_json(path, {'id':'board','updated_at':2})
    assert cache.get(str(path),load)['updated_at']==2 and len(reads)==2
    atomic_write_json(path, {'id':'board','updated_at':3,'deleted_at':1})
    with pytest.raises(HTTPException):cache.get(str(path),load)
    path.write_text('{truncated')
    with pytest.raises(ValueError):cache.get(str(path),load)
    path.unlink()
    with pytest.raises(FileNotFoundError):cache.get(str(path),load)


def test_locked_canvas_save_leaves_loop_free_and_rejects_second_old_base(tmp_path):
    scope=data_scope(tmp_path);scope['save_canvas']({'id':'board','nodes':[]})
    base=scope['load_canvas']('board')['updated_at']
    payload=SimpleNamespace(base_updated_at=base,title='Saved',icon='layers',nodes=[{'kept':1}],
        connections=[],viewport={},logs=[],settings={},client_id='test')
    entered,release=threading.Event(),threading.Event();load=scope['load_canvas']
    def held(*args):
        entered.set();assert release.wait(2);return load(*args)
    scope['load_canvas']=held
    async def check():
        tasks=[asyncio.create_task(scope['update_canvas']('board',payload)) for _ in range(2)]
        try:
            assert await asyncio.to_thread(entered.wait,1)
            await asyncio.sleep(.01)
            assert not any(t.done() for t in tasks)
        finally:release.set()
        result=await asyncio.gather(*tasks,return_exceptions=True)
        assert sum(isinstance(r,dict) for r in result)==1
        failures=[r for r in result if isinstance(r,HTTPException)]
        assert len(failures)==1 and failures[0].status_code==409
    asyncio.run(check())
    assert load('board')['nodes']==[{'kept':1}]


def test_startup_phase_waits_for_work_and_only_logs_numeric_counts(caplog):
    entered,release=threading.Event(),threading.Event()
    def work():
        entered.set();assert release.wait(2);return {'files_seen':12,'secret_file':'do-not-log.png'}
    async def check():
        task=asyncio.create_task(performance.startup_stage('fixture',work))
        try:
            assert await asyncio.to_thread(entered.wait,1)
            assert not task.done()
        finally:release.set()
        assert (await task)['files_seen']==12
    with caplog.at_level('INFO',logger='uvicorn.error'):asyncio.run(check())
    assert 'files_seen' in caplog.text and 'do-not-log' not in caplog.text


def test_real_gateway_dispatch_reports_held_pool_wait_without_changing_limit():
    performance.drain()
    scope=main_functions({'_forward'},source='enterprise/gateway.py',httpx=httpx,time=time,
        performance=performance,streaming_response=streaming_response,needs_body_filter=needs_body_filter,
        JSONResponse=JSONResponse)
    async def check():
        release=asyncio.Event()
        async def serve(reader,writer):
            line=await reader.readline()
            while await reader.readline() not in (b'\r\n',b''):pass
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: 1\r\nConnection: close\r\n\r\n')
            await writer.drain()
            if b'/held ' in line:await release.wait()
            writer.write(b'x');await writer.drain();writer.close()
        server=await asyncio.start_server(serve,'127.0.0.1',0)
        port=server.sockets[0].getsockname()[1]
        try:
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}',limits=httpx.Limits(max_connections=1),trust_env=False) as client:
                scope['_http_client']=client
                held=await client.send(client.build_request('GET','/held'),stream=True)
                request=SimpleNamespace(headers={},query_params={},method='GET',url=SimpleNamespace(query=''))
                task=asyncio.create_task(scope['_forward']('api/app-info',request,None,True,b''))
                await asyncio.sleep(.05);assert not task.done()
                release.set();await held.aread();await held.aclose()
                response=await task
                assert b''.join([part async for part in response.body_iterator])==b'x'
        finally:release.set();server.close();await server.wait_closed()
    asyncio.run(check())
    row=performance.drain()['gateway.dispatch_wait.control']
    assert row['calls']==1 and row['max_ms']>=30
