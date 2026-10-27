"""Single-Upstream Comfy admission and fair dispatch over the existing journal.

Inputs and accepted identities remain owned by CanvasTaskDispatch/recovery.
Only never-started tasks enter this gate; no vendor submission is retried.
"""
import asyncio
from contextlib import asynccontextmanager
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from enterprise.canvas_task_journal import CanvasTaskJournal, pending_dispatch
from enterprise.providers.comfyui import base_url, endpoint


def unfinished(record):
    return record.get('status') in {'queued', 'running'} or bool(record.get('recovery_required'))


def executing(record):
    receipt = record.get('comfy_receipt') or {}
    return unfinished(record) and receipt.get('phase') != 'retrieving' and record.get('status') != 'queued'


async def read_backend_queue(backend):
    async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
        response = await client.get(endpoint(backend, '/queue'))
        response.raise_for_status()
        value = response.json()
    if not isinstance(value, dict) or any(not isinstance(value.get(key), list) for key in ('queue_running', 'queue_pending')):
        raise ValueError('Invalid ComfyUI queue')
    rows = value['queue_running'] + value['queue_pending']
    if any(not isinstance(row, list) or len(row) < 2 or not isinstance(row[1], str) for row in rows):
        raise ValueError('Invalid ComfyUI queue identity')
    return {row[1] for row in rows}


class ComfyQueue:
    def __init__(self, journal, state_root, backends, workflows, *, probe=read_backend_queue, interval=2):
        self.journal, self.backends, self.workflows = journal, backends, workflows
        # Reuse the atomic local JSON store; this is configuration, not another task queue.
        self.store = CanvasTaskJournal(state_root / 'comfy-queue')
        self.probe, self.interval = probe, interval
        self.lock = asyncio.Lock()
        self.wake = asyncio.Event()
        self.waiters, self.reserved, self.health = {}, set(), {}
        self.turns = {}
        self.worker = None

    def policy(self):
        saved = self.store.get('policy') or {}
        urls = list(dict.fromkeys(base_url(url) for url in self.backends()))
        overrides = {row['url']: row for row in saved.get('backends', [])}
        limits = {row['name']: row['waiting_limit'] for row in saved.get('workflows', [])}
        default = saved.get('default_workflow_waiting', 6)
        return {'user_running': saved.get('user_running', 1), 'user_outstanding': saved.get('user_outstanding', 3),
            'default_workflow_waiting': default,
            'backends': [overrides.get(url, {'url': url, 'resource': urlsplit(url).netloc, 'capacity': 1}) for url in urls],
            'workflows': [{'name': name, 'waiting_limit': limits.get(name, default)} for name in self.workflows()]}

    def resource(self, backend, policy):
        url = base_url(backend)
        return next((row for row in policy['backends'] if row['url'] == url), None)

    def records(self):
        return self.journal.comfy_queue_records()

    def busy(self, row):
        return executing(row) or (row['id'] in self.reserved and unfinished(row) and (row.get('comfy_receipt') or {}).get('phase') != 'retrieving')

    def admission(self, payload, owner):
        """Called while holding lock through durable creation and enqueue."""
        policy, records = self.policy(), self.records()
        backend, workflow = base_url(payload.backend), payload.workflow_json
        resource = self.resource(backend, policy)
        if resource is None:
            raise HTTPException(409, '工作流后端已移除，请重新选择')
        mine = [row for row in records if row.get('enterprise_user_id', '') == owner and unfinished(row)]
        if len(mine) >= policy['user_outstanding']:
            running = sum(executing(row) for row in mine)
            raise HTTPException(429, f"你已有 {running} 个任务运行或核对中、{len(mine)-running} 个任务等待或归档，未结束上限为 {policy['user_outstanding']}；结束或取消后可继续提交")
        limit = next((row['waiting_limit'] for row in policy['workflows'] if row['name'] == workflow), policy['default_workflow_waiting'])
        waiting = sum(row.get('workflow_json') == workflow and row.get('status') == 'queued' and not executing(row) for row in records)
        if waiting >= limit:
            raise HTTPException(429, f'该工作流已有 {waiting} 个任务等待，排队上限为 {limit}；请稍后再提交')
        return {'backend': backend, 'resource': resource['resource']}

    async def save_policy(self, value):
        async with self.lock:
            current = self.policy()
            def number(value):
                if type(value) is not int or not 1 <= value <= 128:
                    raise HTTPException(400, '限额须为 1 到 128 的整数')
                return value
            if not isinstance(value, dict) or set(value) != set(current):
                raise HTTPException(400, '队列配置字段无效，请刷新后重试')
            for key in ('user_running', 'user_outstanding', 'default_workflow_waiting'):
                number(value[key])
            if value['user_running'] > value['user_outstanding']:
                raise HTTPException(400, '每人运行上限不能超过未结束总数上限')
            if not isinstance(value['backends'], list) or not isinstance(value['workflows'], list):
                raise HTTPException(400, '后端或工作流配置无效')
            groups = {}
            for row in value['backends']:
                if not isinstance(row, dict) or set(row) != {'url', 'resource', 'capacity'} or not isinstance(row['url'], str):
                    raise HTTPException(400, '后端配置无效')
                if not isinstance(row['resource'], str) or not 1 <= len(row['resource'].strip()) <= 128:
                    raise HTTPException(400, '请填写算力分组名称（最多128字）')
                row['resource'] = row['resource'].strip()
                capacity = number(row['capacity'])
                if groups.setdefault(row['resource'], capacity) != capacity:
                    raise HTTPException(400, '同一算力分组的执行上限须一致')
            for row in value['workflows']:
                if not isinstance(row, dict) or set(row) != {'name', 'waiting_limit'} or not isinstance(row['name'], str):
                    raise HTTPException(400, '工作流配置无效')
                number(row['waiting_limit'])
            for key, field in (('backends', 'url'), ('workflows', 'name')):
                supplied = [row[field] for row in value[key]]
                if len(set(supplied)) != len(supplied) or set(supplied) != {row[field] for row in current[key]}:
                    raise HTTPException(409, '后端或工作流列表已变化，请刷新后重试')
            for row in self.records():
                if not unfinished(row):
                    continue
                backend = (row.get('comfy_queue') or row.get('comfy_receipt') or {}).get('backend')
                if backend:
                    before, after = self.resource(backend, current), self.resource(backend, value)
                    if before and after and before['resource'] != after['resource']:
                        raise HTTPException(409, '该后端还有未结束任务，请结束后再调整算力分组；限额可直接调整')
            await asyncio.to_thread(self.store._write, {'id': 'policy', 'journal_version': 1, **value})
            self.wake.set()
            return self.policy()

    async def start(self):
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._run())

    async def stop(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None

    @asynccontextmanager
    async def turn(self, task_id):
        await self.start()
        future = asyncio.get_running_loop().create_future()
        self.waiters[task_id] = future
        self.wake.set()
        try:
            yield await future
        finally:
            self.waiters.pop(task_id, None)
            self.reserved.discard(task_id)
            self.wake.set()

    async def cancel_waiting(self, task_id):
        async with self.lock:
            row = await asyncio.to_thread(self.journal.get, task_id)
            if not row or not pending_dispatch(row) or not row.get('comfy_queue'):
                return False
            await asyncio.to_thread(self.journal.confirm_comfy_cancelled, task_id)
            future = self.waiters.get(task_id)
            if future and not future.done():
                future.set_result(False)
            self.wake.set()
            return True

    async def _run(self):
        while True:
            self.wake.clear()
            try:
                if any(not future.done() for future in self.waiters.values()):
                    await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Keep accepted waiters and inputs intact if a status read is unavailable.
                import logging
                logging.getLogger(__name__).exception('Comfy queue status read deferred')
            try:
                if any(not future.done() for future in self.waiters.values()):
                    await asyncio.wait_for(self.wake.wait(), self.interval)
                else:
                    await self.wake.wait()
            except asyncio.TimeoutError:
                pass

    async def _tick(self):
        async with self.lock:
            policy = await asyncio.to_thread(self.policy)
            records = await asyncio.to_thread(self.records)
            for row in records:
                future = self.waiters.get(row['id'])
                if future and not future.done() and not pending_dispatch(row):
                    future.set_result(False)
            waiting = [row for row in records if pending_dispatch(row) and row['id'] in self.waiters
                       and row['id'] not in self.reserved and not self.waiters[row['id']].done()]
            groups = {row['resource']: row['capacity'] for row in policy['backends']}
            def group(row):
                backend = (row.get('comfy_queue') or row.get('comfy_receipt') or {}).get('backend')
                return self.resource(backend, policy)['resource'] if backend and self.resource(backend, policy) else None
            for row in waiting:
                if group(row) is None:
                    # Let the existing binding validator reject removed backends without a POST.
                    self.waiters[row['id']].set_result(True)
            for resource, capacity in groups.items():
                candidates = [row for row in waiting if group(row) == resource]
                if not candidates:
                    continue
                running = [row for row in records if self.busy(row)]
                known = [row for row in running if group(row) == resource and (row['id'] in self.reserved or
                         (row.get('comfy_receipt') or {}).get('phase') in {'queued', 'running', 'reconnecting'})]
                if len(known) >= capacity:
                    continue
                urls = [row['url'] for row in policy['backends'] if row['resource'] == resource]
                try:
                    replies = await asyncio.gather(*(self.probe(url) for url in urls))
                    remote = set().union(*replies)
                    self.health[resource] = {'available': True, 'backend_jobs': len(remote)}
                except (httpx.HTTPError, ValueError, OSError):
                    self.health[resource] = {'available': False, 'backend_jobs': None}
                    continue
                # Count external jobs too. A local reservation precedes the vendor POST.
                local_ids = {(row.get('comfy_receipt') or {}).get('prompt_id') for row in known}
                occupied = len(known) + len(remote - local_ids)
                served = {}
                for row in records:
                    if group(row) == resource:
                        who = row.get('enterprise_user_id', '')
                        served[who] = max(served.get(who, 0), (row.get('comfy_queue') or {}).get('dispatched_at', 0))
                last = max(served, key=served.get) if served and max(served.values()) else None
                owners = list(dict.fromkeys(row.get('enterprise_user_id', '') for row in sorted(candidates, key=lambda row: (row.get('created_at', 0), row['id']))))
                if resource not in self.turns:
                    # Reconstruct after restart from the same durable grant facts.
                    self.turns[resource] = sorted(owners, key=lambda owner: served.get(owner, 0))
                ring = self.turns[resource]
                ring[:] = [owner for owner in ring if owner in owners or owner == last]
                if last is not None and last not in ring:
                    ring.append(last)
                for owner in owners:
                    if owner not in ring:
                        # Join the next round before the last-served marker, not
                        # ahead of users already waiting for their current turn.
                        ring.insert(ring.index(last) if last in ring else len(ring), owner)
                while occupied < capacity:
                    eligible = [row for row in candidates if sum(item.get('enterprise_user_id', '') == row.get('enterprise_user_id', '') for item in running) < policy['user_running']]
                    if not eligible:
                        break
                    row = min(eligible, key=lambda item: (ring.index(item.get('enterprise_user_id', '')), item.get('created_at', 0), item['id']))
                    granted = await asyncio.to_thread(self.journal.claim_comfy_dispatch, row['id'])
                    candidates.remove(row)
                    if not granted:
                        continue
                    self.reserved.add(row['id'])
                    self.waiters[row['id']].set_result(True)
                    owner = row.get('enterprise_user_id', '')
                    ring.remove(owner)
                    ring.append(owner)
                    running.append(granted)
                    occupied += 1

    def status(self, owner=None):
        policy, records = self.policy(), self.records()
        active = [row for row in records if unfinished(row)]
        mine = [row for row in active if owner is None or row.get('enterprise_user_id', '') == owner]
        return {'running': sum(executing(row) for row in mine),
            'waiting': sum(row.get('status') == 'queued' and not executing(row) for row in mine),
            'outstanding': len(mine), 'limits': {key: policy[key] for key in ('user_running', 'user_outstanding')},
            'resources': self.health.copy() if owner is None else {},
            'items': [self.public(row) for row in mine] if owner is None else []}

    def public(self, row):
        return {key: row.get(key) for key in ('id', 'enterprise_user_id', 'workflow_json', 'created_at', 'status')} | {
            'phase': 'platform_queued' if pending_dispatch(row) and row['id'] not in self.reserved else (row.get('comfy_receipt') or {}).get('phase', 'preparing')}

    def task_queue(self, row):
        if not row.get('comfy_queue'):
            return None
        backend = row['comfy_queue']['backend']
        resource = self.resource(backend, self.policy())
        health = self.health.get(resource['resource'], {}) if resource else {}
        return {'state': 'platform_queued' if pending_dispatch(row) and row['id'] not in self.reserved else 'submitted',
                'backend_available': health.get('available'), **{key: value for key, value in self.status(row.get('enterprise_user_id', '')).items() if key in {'running', 'waiting', 'outstanding', 'limits'}}}
