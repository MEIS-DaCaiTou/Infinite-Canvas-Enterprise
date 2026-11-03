"""Real ASGI shutdown with a stalled download and a normally finishing request.

Binary fixture tests transport cleanup, not image/video performance.
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import socket
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import FileResponse
import httpx

from enterprise.runtime import child


def test_child_drains_or_cancels_http_before_application_cleanup(tmp_path,monkeypatch):
    media=tmp_path/'download.bin'
    with media.open('wb') as handle:
        for _ in range(32):handle.write(b'x'*(1024*1024))
    async def run():
        cleaned=asyncio.Event();started=asyncio.Event()
        @asynccontextmanager
        async def lifespan(app):
            yield
            cleaned.set()
        app=FastAPI(lifespan=lifespan)
        @app.get('/ready')
        async def ready():return {'ready':True}
        @app.get('/download')
        async def download():
            started.set()
            return FileResponse(media)
        monkeypatch.setattr(child,'_load_application',lambda *_:app)
        monkeypatch.setattr(child,'HTTP_DRAIN_TIMEOUT_SECONDS',.2)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        args=SimpleNamespace(runtime_mode='development',role='upstream',app_root=str(tmp_path),host='127.0.0.1',port=port,
                             runtime_stop_file=str(tmp_path/'stop'),shutdown_marker=str(tmp_path/'stopped'))
        serving=asyncio.create_task(child._serve(args));client=socket.socket()
        client.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4096);client.setblocking(False)
        try:
            async with httpx.AsyncClient() as http:
                for _ in range(100):
                    try:
                        await http.get(f'http://127.0.0.1:{port}/ready',timeout=.2);break
                    except httpx.HTTPError:await asyncio.sleep(.02)
                else:raise AssertionError('ASGI server not ready')
            loop=asyncio.get_running_loop();await loop.sock_connect(client,('127.0.0.1',port))
            await loop.sock_sendall(client,b'GET /download HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            head=await loop.sock_recv(client,512);assert b'200 OK' in head
            await started.wait();Path(args.runtime_stop_file).write_text('stop')
            assert await asyncio.wait_for(asyncio.shield(serving),timeout=3)==0
            assert cleaned.is_set() and Path(args.shutdown_marker).read_text().strip()=='graceful_shutdown'
        finally:
            client.close();Path(args.runtime_stop_file).touch()
            if not serving.done():await asyncio.wait_for(serving,timeout=3)
    asyncio.run(run())


def test_child_allows_short_inflight_request_to_finish(tmp_path,monkeypatch):
    async def run():
        started=asyncio.Event();cleaned=asyncio.Event()
        @asynccontextmanager
        async def lifespan(app):
            yield
            cleaned.set()
        app=FastAPI(lifespan=lifespan)
        @app.get('/short')
        async def short():
            started.set();await asyncio.sleep(.15);return {'finished':True}
        monkeypatch.setattr(child,'_load_application',lambda *_:app)
        monkeypatch.setattr(child,'HTTP_DRAIN_TIMEOUT_SECONDS',.6)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        args=SimpleNamespace(runtime_mode='development',role='upstream',app_root=str(tmp_path),host='127.0.0.1',port=port,
                             runtime_stop_file=str(tmp_path/'stop'),shutdown_marker=str(tmp_path/'stopped'))
        serving=asyncio.create_task(child._serve(args))
        try:
            async with httpx.AsyncClient() as http:
                async def get():
                    for _ in range(100):
                        try:return await http.get(f'http://127.0.0.1:{port}/short',timeout=2)
                        except httpx.ConnectError:await asyncio.sleep(.02)
                    raise AssertionError('ASGI server not ready')
                response=asyncio.create_task(get());await asyncio.wait_for(started.wait(),timeout=3)
                Path(args.runtime_stop_file).write_text('stop')
                assert (await response).json()=={'finished':True}
            assert await asyncio.wait_for(serving,timeout=3)==0 and cleaned.is_set()
        finally:
            Path(args.runtime_stop_file).touch()
            if not serving.done():await asyncio.wait_for(serving,timeout=3)
    asyncio.run(run())
