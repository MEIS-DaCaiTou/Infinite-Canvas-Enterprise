import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from enterprise import db
from enterprise.canvas_comfy_control import create_router
from enterprise.canvas_comfy_recovery import CanvasComfyRecovery
from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.providers.comfyui import ComfyClient, ComfyCancelledError, ComfyExecutionError, history_result


@pytest.fixture
def backend():
    calls, response = [], {'code': 200, 'body': {'cancelled': True}}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append((self.command, self.path, json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')))
            self.send_response(response['code']); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps(response['body']).encode())
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True);worker.start()
    yield f'http://127.0.0.1:{server.server_port}', calls, response
    server.shutdown();worker.join();server.server_close()


def test_owned_single_job_controls_never_interrupt_other_jobs(tmp_path, monkeypatch, backend):
    base, calls, response = backend
    journal = CanvasTaskJournal(tmp_path / 'tasks')
    owners = {'running': 'alice', 'queued': 'alice', 'foreign': 'bob', 'finished': 'alice'}
    for key, user in owners.items():
        journal.create({'id': key, 'type': 'comfy', 'status': 'succeeded' if key == 'finished' else 'running',
            'enterprise_user_id': user, 'source': {'canvas_id': 'canvas-a', 'node_id': 'node-a'},
            'comfy_receipt': {'backend': base, 'prompt_id': key, 'phase': 'queued' if key == 'queued' else 'running'}})
    monkeypatch.setattr(db, 'get_task_owner', lambda kind, key: owners.get(key))
    monkeypatch.setattr(db, 'list_owned_canvas_tasks', lambda user, **_: [
        {'task_id': key, 'task_type': 'canvas_comfy', 'created_at': 1} for key in owners if owners[key] == user])
    resumed = []
    app = FastAPI();app.include_router(create_router(journal, lambda _: None, resumed.append))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            headers = {'X-Enterprise-User-ID': 'alice'}
            assert (await client.post('/_enterprise_internal/comfy-tasks/running/cancel')).status_code == 401
            assert (await client.post('/_enterprise_internal/comfy-tasks/foreign/cancel', headers=headers)).status_code == 404
            assert not calls
            page = (await client.get('/_enterprise_internal/comfy-tasks', params={'canvas_id': 'canvas-a'}, headers=headers)).json()
            assert {t['id'] for t in page['items']} == {'running', 'queued', 'finished'}
            assert all('comfy_receipt' not in t for t in page['items'])
            for key in ['running', 'queued']:
                value = await client.post(f'/_enterprise_internal/comfy-tasks/{key}/cancel', headers=headers)
                assert value.status_code == 200
                assert value.json()['task']['status'] == 'running', 'acknowledgement is not terminal confirmation'
                assert journal.get(key)['cancellation']['acknowledged']
            count = len(calls)
            assert (await client.post('/_enterprise_internal/comfy-tasks/finished/cancel', headers=headers)).status_code == 200
            assert len(calls) == count
            response['code'] = 404
            assert (await client.post('/_enterprise_internal/comfy-tasks/running/cancel', headers=headers)).status_code == 501
    asyncio.run(run())
    assert resumed == ['running', 'queued']
    assert [path for _, path, _ in calls] == ['/api/jobs/running/cancel', '/api/jobs/queued/cancel', '/api/jobs/running/cancel']
    assert all(body == {} for _, _, body in calls)


def test_removed_original_backend_cannot_redirect_cancel(tmp_path, monkeypatch):
    journal = CanvasTaskJournal(tmp_path / 'tasks')
    journal.create({'id': 'original', 'type': 'comfy', 'status': 'running',
                    'comfy_receipt': {'backend': 'http://removed.invalid', 'prompt_id': 'job'}})
    monkeypatch.setattr(db, 'get_task_owner', lambda *_: 'alice')
    def validate(_): raise HTTPException(409, 'original backend removed')
    monkeypatch.setattr(ComfyClient, 'cancel', lambda *_: pytest.fail('must not cancel on an alternative backend'))
    app = FastAPI();app.include_router(create_router(journal, validate, lambda _: None))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            assert (await client.post('/_enterprise_internal/comfy-tasks/original/cancel', headers={'X-Enterprise-User-ID':'alice'})).status_code == 409
    asyncio.run(run())


def test_external_interruption_is_cancellation_not_execution_failure():
    with pytest.raises(ComfyCancelledError):
        history_result({'job': {'status': {'status_str':'error', 'messages': [['execution_interrupted', {'prompt_id':'job'}]]}}}, 'job')
    with pytest.raises(ComfyExecutionError, match='real error'):
        history_result({'job': {'status': {'status_str':'error', 'messages': [['execution_error', {'exception_message':'real error'}]]}}}, 'job')


@pytest.mark.parametrize('completed', [False, True])
def test_cancelled_queue_disappearance_checks_completion_race(tmp_path, completed):
    journal = CanvasTaskJournal(tmp_path / 'tasks')
    journal.create({'id':'original', 'type':'comfy', 'status':'failed', 'recovery_required':True,
        'comfy_receipt':{'backend':'http://fixture.invalid', 'prompt_id':'job'}, 'cancellation':{'acknowledged':True}})
    reads = []
    async def inspect(*_):
        reads.append(1)
        return ('retrieving', {'outputs':{}}) if completed and len(reads) == 2 else ('unknown', None)
    recovery = CanvasComfyRecovery(journal, inspect, lambda *_: {'images':['/output/complete.png']}, lambda _:None)
    outcome = asyncio.run(recovery.reconcile('original'))
    assert outcome['status'] == ('succeeded' if completed else 'cancelled')
    assert not journal.get('original')['recovery_required']
    assert len(reads) == 2


def test_live_wait_detects_acknowledged_removed_queue_without_resubmit():
    client = ComfyClient('http://fixture.invalid')
    client.inspect = lambda _: ('unknown', None)
    with pytest.raises(ComfyCancelledError): client.wait('original', cancelled=lambda:True)


def test_public_gateway_supplies_authenticated_owner_for_cancel(monkeypatch):
    from enterprise import gateway
    calls = []
    monkeypatch.setattr(gateway, 'verify_token', lambda token: {'user_id':'alice','username':'alice','role':'user','is_admin':False,'auth_version':1} if token=='alice' else None)
    def handle(request):
        calls.append((request.method, request.url.path, request.headers['X-Enterprise-User-ID']))
        return httpx.Response(501, json={'detail':'per-job cancellation unsupported'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://upstream') as upstream, httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url='http://testserver') as client:
            monkeypatch.setattr(gateway.app.state,'upstream_client',upstream,raising=False)
            path='/enterprise/api/me/comfy-tasks/original/cancel'
            assert (await client.post(path)).status_code==401
            response=await client.post(path,headers={'Cookie':'enterprise_token=alice','X-Enterprise-User-ID':'bob','Origin':'http://testserver'})
            assert response.status_code==501 and response.headers['cache-control']=='no-store'
            assert (await client.post('/_enterprise_internal/comfy-tasks/original/cancel',headers={'Cookie':'enterprise_token=alice','Origin':'http://testserver'})).status_code==404
    asyncio.run(run())
    assert calls==[('POST','/_enterprise_internal/comfy-tasks/original/cancel','alice')]
