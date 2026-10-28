"""Single-Upstream dispatch of durable, never-started canvas requests.

Inputs are private DATA_ROOT artifacts, separate from public receipts/history.
The existing runner claims the journal before any submission. Claimed/unknown
work is never replayed here; accepted recovery remains query-only.
"""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
import hmac
import json
import logging

from enterprise.canvas_task_journal import CanvasTaskJournal, pending_dispatch
from enterprise.interceptors import _is_sensitive_settings_key

MAX_INPUT_BYTES = 64 * 1024 * 1024

def _sensitive_key(key):
    name = str(key).lower().replace("-", "_").split(".")[-1]
    return _is_sensitive_settings_key(name) or name in {"accesstoken", "authorization", "headers"}


def configuration_binding(secret, configuration):
    """Opaque binding prevents queued work moving to a changed billing account.

    No credential/header/configuration body is saved. Rotating the installation
    signing secret also deliberately invalidates old unsubmitted requests.
    """
    raw = json.dumps(configuration, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf8")
    return hmac.new(secret.encode("utf8"), raw, "sha256").hexdigest()


def _contains_credentials(value):
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key).lower().replace("-", "_").split(".")[-1]
            if _sensitive_key(key):
                return True
            # Comfy field definitions name the actual input in a value.
            if name in {"input", "key"} and isinstance(item, str) and _sensitive_key(item):
                return True
            if _contains_credentials(item):
                return True
    elif isinstance(value, list):
        return any(_contains_credentials(item) for item in value)
    return False


class CanvasTaskDispatch:
    def __init__(self, journal, models, runners, binding, validate, paused, schedule, *, concurrency=2, comfy_queue=None):
        self.journal, self.models, self.runners = journal, models, runners
        self.binding, self.validate, self.paused, self.schedule = binding, validate, paused, schedule
        self.inputs = CanvasTaskJournal(journal.root / "inputs")
        self.active = {}
        self.semaphore = asyncio.Semaphore(concurrency)
        self.closed = False
        self.comfy_queue = comfy_queue

    def check_comfy_input(self, payload):
        binding = self.binding('comfy', payload)
        data = payload.model_dump(mode='json')
        private = {'workflow_config': payload._workflow_config}
        if not binding:
            from fastapi import HTTPException
            raise HTTPException(409, '工作流配置不可用，请重新选择并保存配置')
        if _contains_credentials(data) or _contains_credentials(private):
            from fastapi import HTTPException
            raise HTTPException(400, '工作流包含不适合持久排队的凭据字段，请先调整工作流配置')
        if len(json.dumps({'payload': data, 'private': private}, ensure_ascii=False).encode('utf8')) > MAX_INPUT_BYTES:
            from fastapi import HTTPException
            raise HTTPException(413, '任务输入过大，请先上传素材再加入队列')

    async def enqueue(self, task_id, payload):
        record = await asyncio.to_thread(self.journal.get, task_id)
        kind = record["type"]
        # Anonymous legacy/CLI integrations keep their existing immediate path.
        # Only authenticated requests with a restorable model/config get opt-in.
        binding = await asyncio.to_thread(self.binding, kind, payload) if record.get("enterprise_user_id") or kind == 'comfy' and self.comfy_queue else None
        if not binding:
            self.schedule(self.runners[kind](task_id, payload))
            return
        data = payload.model_dump(mode="json")
        private = {"workflow_config": payload._workflow_config} if kind == "comfy" else {}
        raw = json.dumps({"payload": data, "private": private}, ensure_ascii=False, allow_nan=False).encode("utf8")
        if len(raw) > MAX_INPUT_BYTES or _contains_credentials(data) or _contains_credentials(private):
            self.schedule(self.runners[kind](task_id, payload))
            return
        await asyncio.to_thread(self.inputs.create, {
            "id": task_id, "type": kind, "owner": record["enterprise_user_id"],
            "payload": data, "private": private, "binding": binding,
        })
        # A crash before this marker preserves the old manual recovery rule.
        await asyncio.to_thread(self.journal.enable_dispatch, task_id)
        self._schedule(task_id)

    def _schedule(self, task_id, *, restored=False):
        if not self.closed and task_id not in self.active:
            task = self.schedule(self._one(task_id, restored=restored))
            self.active[task_id] = task
            def done(future):
                self.active.pop(task_id, None)
            task.add_done_callback(done)

    async def start(self):
        self.closed = False
        if self.comfy_queue:
            await self.comfy_queue.start()
        for record in await asyncio.to_thread(self.journal.pending_dispatches):
            if self.comfy_queue and record.get('type') == 'comfy' and not record.get('comfy_queue'):
                item = await asyncio.to_thread(self.inputs.get, record['id'])
                backend = (item or {}).get('payload', {}).get('backend')
                if backend:
                    await asyncio.to_thread(self.journal.attach_comfy_queue, record['id'], backend)
            self._schedule(record["id"], restored=True)
        await asyncio.to_thread(self._clean_inactive_inputs)

    def _remove_input(self, task_id):
        # Canonical task ID and no-reparse checks are the existing journal API.
        self.inputs._path(task_id).unlink(missing_ok=True)

    def _clean_inactive_inputs(self):
        # Startup before traffic. Never infer executable tasks from input files.
        self.inputs._path("startup-probe")
        for path in self.inputs.root.glob("*.json"):
            try:
                record = self.journal.get(path.stem)
                if not pending_dispatch(record):
                    self._remove_input(path.stem)
            except (ValueError, UnicodeError, OSError):
                # Corrupt evidence is retained; it cannot trigger a generation.
                continue

    async def _one(self, task_id, *, restored=False):
        record = await asyncio.to_thread(self.journal.get, task_id)
        if self.comfy_queue and record.get('type') == 'comfy' and record.get('comfy_queue'):
            async with self.comfy_queue.turn(task_id) as granted:
                if granted:
                    await self._dispatch_one(task_id)
                else:
                    await self._cleanup(task_id)
            return
        await self._dispatch_one(task_id, restored=restored)

    async def _dispatch_one(self, task_id, *, restored=False):
        # Bound restart bursts only; retain normal submission concurrency.
        async with self.semaphore if restored else nullcontext():
            while True:
                while not self.closed and self.paused():
                    await asyncio.sleep(.25)
                if self.closed:
                    return
                record = await asyncio.to_thread(self.journal.get, task_id)
                if not pending_dispatch(record):
                    return
                try:
                    item = await asyncio.to_thread(self._read_input, record)
                    model = self.models[record["type"]]
                    payload = model.model_validate(item["payload"])
                    if record["type"] == "comfy":
                        payload._workflow_config = item["private"]["workflow_config"]
                        payload._enterprise_user_id = record["enterprise_user_id"]
                    current = await asyncio.to_thread(self.binding, record["type"], payload)
                    if not current or not hmac.compare_digest(current, item["binding"]):
                        raise ValueError("Queued configuration changed")
                    if not await self.validate(record, payload):
                        raise ValueError("Queued ownership or access changed")
                except Exception:
                    await asyncio.to_thread(self.journal.reject_dispatch, task_id)
                    await self._cleanup(task_id)
                    return
                if self.closed:
                    return
                if not self.paused():
                    break
            try:
                await self.runners[record["type"]](task_id, payload)
            finally:
                latest = await asyncio.to_thread(self.journal.get, task_id)
                if not pending_dispatch(latest):
                    await self._cleanup(task_id)

    def _read_input(self, record):
        path = self.inputs._path(record["id"])
        if path.stat().st_size > MAX_INPUT_BYTES + 32768:
            raise ValueError("Queued input oversized")
        item = self.inputs.get(record["id"])
        if (not item or item.get("type") != record["type"]
                or item.get("owner") != record.get("enterprise_user_id")):
            raise ValueError("Queued input owner mismatch")
        return item

    async def _cleanup(self, task_id):
        try:
            await asyncio.to_thread(self._remove_input, task_id)
        except OSError:
            logging.getLogger(__name__).warning("Completed task input cleanup deferred")

    async def stop(self):
        self.closed = True
        tasks = list(self.active.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.active.clear()
        if self.comfy_queue:
            await self.comfy_queue.stop()
