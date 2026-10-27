"""Fairness, atomic quotas and recovery over real journals; no GPU submissions."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.comfy_queue import ComfyQueue
from enterprise.canvas_comfy_recovery import public_comfy_task


BACKEND = 'http://comfy.invalid:8188'
ALIAS = 'http://alias.invalid:9527'


class Rig:
    def __init__(self, root, backends=None):
        self.journal = CanvasTaskJournal(root / 'tasks')
        self.remote, self.calls, self.trace, self.events, self.tasks = set(), [], [], {}, []
        self.offline = False
        async def probe(url):
            self.calls.append(url)
            if self.offline:
                raise httpx.ConnectError('offline')
            return self.remote.copy()
        self.queue = ComfyQueue(self.journal, root, lambda: backends or [BACKEND],
            lambda: ['image.json', 'video.json'], probe=probe, interval=.01)

    async def admit(self, key, owner='alice', workflow='image.json', backend=BACKEND, run=False):
        async with self.queue.lock:
            meta = self.queue.admission(SimpleNamespace(backend=backend, workflow_json=workflow), owner)
            self.journal.create({'id': key, 'type': 'comfy', 'enterprise_user_id': owner, 'status': 'queued',
                'created_at': len(self.journal.comfy_queue_records()) + 1, 'dispatch_version': 1,
                'workflow_json': workflow, 'comfy_queue': meta})
        if run:
            self.events[key] = asyncio.Event()
            self.tasks.append(asyncio.create_task(self.execute(key)))
        return self.journal.get(key)

    async def execute(self, key):
        async with self.queue.turn(key) as granted:
            if not granted or not self.journal.mark_running(key):
                return
            self.trace.append(key)
            self.remote.add(key)
            self.journal.record_comfy(key, {'backend': (self.journal.get(key)['comfy_queue'])['backend'], 'prompt_id': key, 'phase': 'running'})
            await self.events[key].wait()
            self.remote.discard(key)
            self.journal.finish(key, {'status': 'succeeded'})

    async def until(self, condition):
        async with asyncio.timeout(3):
            while not condition():
                await asyncio.sleep(.005)

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.queue.stop()


def test_users_rotate_across_workflows_and_one_host_never_runs_two(tmp_path):
    async def scenario():
        rig = Rig(tmp_path)
        try:
            await rig.admit('a1', run=True)
            await rig.until(lambda: rig.trace == ['a1'])
            await rig.admit('a2', workflow='video.json', run=True)
            await rig.admit('a3', run=True)
            await rig.admit('b1', 'bob', run=True)
            await rig.admit('c1', 'carol', run=True)
            assert rig.queue.status('alice')['outstanding'] == 3
            assert public_comfy_task(rig.journal.get('a2'))['phase'] == 'platform_queued'
            assert rig.queue.status('bob')['items'] == []
            for key, next_key in [('a1','b1'), ('b1','c1'), ('c1','a2'), ('a2','a3')]:
                rig.events[key].set()
                await rig.until(lambda: next_key in rig.trace)
                assert rig.remote == {next_key}
            assert rig.trace == ['a1','b1','c1','a2','a3']
        finally:
            await rig.close()
    asyncio.run(scenario())


def test_concurrent_admission_caps_user_without_phantom_receipts(tmp_path):
    async def scenario():
        rig = Rig(tmp_path)
        async def attempt(i):
            try:
                await rig.admit(f'a{i}', workflow='image.json' if i % 2 else 'video.json')
                return 200
            except HTTPException as error:
                return error.status_code
        results = await asyncio.gather(*(attempt(i) for i in range(20)))
        assert results.count(200) == 3 and results.count(429) == 17
        assert len(list(rig.journal.root.glob('*.json'))) == 3
        await rig.queue.cancel_waiting('a0')
        await rig.admit('after-cancel')
        assert rig.queue.status('alice')['outstanding'] == 3
    asyncio.run(scenario())


def test_new_users_join_next_round_without_starving_an_existing_waiter(tmp_path):
    async def scenario():
        rig = Rig(tmp_path)
        try:
            await rig.admit('a1', run=True)
            await rig.until(lambda: rig.trace == ['a1'])
            await rig.admit('a2', run=True)
            await rig.admit('b1', 'bob', run=True)
            await rig.admit('c1', 'carol', run=True)
            rig.events['a1'].set()
            await rig.until(lambda: 'b1' in rig.trace)
            await rig.admit('d1', 'dave', run=True)
            rig.events['b1'].set()
            await rig.until(lambda: 'c1' in rig.trace)
            rig.events['c1'].set()
            await rig.until(lambda: len(rig.trace) == 4)
            assert rig.trace == ['a1', 'b1', 'c1', 'a2']
        finally:
            await rig.close()
    asyncio.run(scenario())


def test_workflow_limits_shared_by_users_and_lowering_does_not_cancel(tmp_path):
    async def scenario():
        rig = Rig(tmp_path)
        value = rig.queue.policy()
        value['workflows'][1]['waiting_limit'] = 3
        await rig.queue.save_policy(value)
        for i in range(3):
            await rig.admit(f'v{i}', str(i), 'video.json')
        with pytest.raises(HTTPException) as error:
            await rig.admit('v3', 'other', 'video.json')
        assert error.value.status_code == 429
        value['workflows'][1]['waiting_limit'] = 1
        await rig.queue.save_policy(value)
        assert rig.queue.status()['waiting'] == 3
        assert all(row['status'] == 'queued' for row in rig.journal.comfy_queue_records())
        reloaded = ComfyQueue(rig.journal, tmp_path, lambda: [BACKEND], lambda: ['image.json','video.json'])
        assert reloaded.policy()['workflows'][1]['waiting_limit'] == 1
    asyncio.run(scenario())


def test_aliases_share_capacity_external_jobs_and_outages_hold_waiters(tmp_path):
    async def scenario():
        rig = Rig(tmp_path, [BACKEND, ALIAS])
        value = rig.queue.policy()
        for row in value['backends']:
            row['resource'] = 'one-gpu'
        await rig.queue.save_policy(value)
        rig.offline = True
        try:
            await rig.admit('a', run=True)
            await rig.admit('b', 'bob', backend=ALIAS, run=True)
            await rig.until(lambda: bool(rig.queue.health))
            assert not rig.trace and rig.queue.health['one-gpu']['available'] is False
            rig.offline = False;rig.remote.add('external')
            await rig.until(lambda: rig.queue.health['one-gpu'].get('backend_jobs') == 1)
            assert not rig.trace
            rig.remote.clear()
            await rig.until(lambda: rig.trace == ['a'])
            await asyncio.sleep(.03)
            assert rig.trace == ['a']
            rig.events['a'].set()
            await rig.until(lambda: rig.trace == ['a','b'])
        finally:
            await rig.close()
    asyncio.run(scenario())


def test_archive_does_not_hold_gpu_slot_and_unconfirmed_work_uses_user_quota(tmp_path):
    async def scenario():
        rig = Rig(tmp_path)
        try:
            await rig.admit('a', run=True)
            await rig.until(lambda: 'a' in rig.trace)
            await rig.admit('b', 'bob', run=True)
            rig.remote.clear()
            rig.journal.record_comfy('a', {'phase': 'retrieving'})
            await rig.until(lambda: 'b' in rig.trace)
            assert rig.journal.get('a')['status'] == 'running'
            rig.journal.finish('a', {'status': 'failed', 'recovery_required': True})
            assert rig.queue.status('alice')['outstanding'] == 1
            assert rig.queue.status('alice')['running'] == 0
        finally:
            await rig.close()
    asyncio.run(scenario())


def test_restart_never_dispatches_accepted_original_and_cancel_waiting_is_local(tmp_path):
    async def scenario():
        rig = Rig(tmp_path)
        try:
            await rig.admit('original')
            rig.journal.mark_running('original')
            rig.journal.record_comfy('original', {'backend': BACKEND, 'prompt_id': 'original-vendor', 'phase': 'running'})
            rig.remote.add('original-vendor')
            await rig.admit('queued', 'bob', run=True)
            rig.journal.recover()
            assert rig.journal.get('original')['recovery_required']
            await asyncio.sleep(.03)
            assert not rig.trace
            assert await rig.queue.cancel_waiting('queued')
            await rig.until(lambda: all(task.done() for task in rig.tasks))
            row = rig.journal.get('queued')
            assert row['status'] == 'cancelled' and not row.get('comfy_receipt', {}).get('prompt_id')
            assert not rig.trace and rig.remote == {'original-vendor'}
        finally:
            await rig.close()
    asyncio.run(scenario())


def test_preparation_reservation_before_restart_is_not_a_running_task(tmp_path):
    async def scenario():
        rig = Rig(tmp_path)
        await rig.admit('prepared')
        rig.journal.claim_comfy_dispatch('prepared')
        # A crash before mark_running leaves a durable, never-started input.
        restarted = Rig(tmp_path)
        restarted.events['prepared'] = asyncio.Event()
        restarted.tasks.append(asyncio.create_task(restarted.execute('prepared')))
        try:
            await restarted.until(lambda: restarted.trace == ['prepared'])
            assert restarted.queue.status('alice')['running'] == 1
        finally:
            await restarted.close()
    asyncio.run(scenario())


def test_user_running_limit_applies_across_independent_backends(tmp_path):
    async def scenario():
        rig = Rig(tmp_path, [BACKEND, ALIAS])
        # Independent engines report their own queue; local user limit remains global.
        async def separate(url):
            return set()
        rig.queue.probe = separate
        try:
            await rig.admit('a1', run=True)
            await rig.until(lambda: rig.trace == ['a1'])
            await rig.admit('a2', backend=ALIAS, run=True)
            await asyncio.sleep(.04)
            assert rig.trace == ['a1']
            rig.events['a1'].set()
            await rig.until(lambda: rig.trace == ['a1','a2'])
        finally:
            await rig.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['bool','fraction','zero','inconsistent','unknown','moving-active'])
def test_invalid_policies_and_active_resource_moves_are_rejected(tmp_path, change):
    async def scenario():
        rig = Rig(tmp_path, [BACKEND, ALIAS])
        value = rig.queue.policy()
        if change == 'bool':value['user_running'] = True
        if change == 'fraction':value['user_outstanding'] = 1.5
        if change == 'zero':value['workflows'][0]['waiting_limit'] = 0
        if change == 'unknown':value['backends'][0]['url'] = 'http://unregistered.invalid'
        if change == 'inconsistent':
            value['backends'][1]['resource'] = value['backends'][0]['resource']
            value['backends'][1]['capacity'] = 2
        if change == 'moving-active':
            await rig.admit('a')
            value['backends'][0]['resource'] = 'another'
        with pytest.raises(HTTPException):
            await rig.queue.save_policy(value)
        assert not rig.queue.store._path('policy').exists()
    asyncio.run(scenario())


def test_gateway_queue_routes_require_admin_and_force_personal_owner(tmp_path):
    from enterprise.comfy_queue_api import router
    app = FastAPI();app.include_router(router)
    @app.middleware('http')
    async def principal(request: Request, call_next):
        role = request.headers.get('x-fixture-role')
        request.state.user = {'user_id':'alice','role':role} if role else None
        return await call_next(request)
    calls = []
    def upstream(request):
        calls.append(request)
        assert request.headers['X-Enterprise-User-ID'] == 'alice'
        return httpx.Response(200,json={'running':0,'waiting':0,'outstanding':0,'items':[]})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream),base_url='http://upstream') as upstream_client:
            app.state.upstream_client = upstream_client
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                assert (await client.get('/api/admin/comfy-queue')).status_code == 403
                assert (await client.get('/api/admin/comfy-queue',headers={'x-fixture-role':'user'})).status_code == 403
                assert not calls
                result = await client.get('/api/me/comfy-queue?user_id=bob',headers={'x-fixture-role':'user'})
                assert result.status_code == 200 and calls[-1].url.path.endswith('/me')
    asyncio.run(scenario())
