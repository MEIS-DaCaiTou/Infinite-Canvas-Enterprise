"""Keep existing creative entry points on the same credential and receipt services."""
import asyncio
from contextlib import contextmanager
import time
import uuid

import anyio
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from enterprise.canvas_llm_tasks import _attempt
from enterprise.canvas_task_journal import create_task_receipt
from enterprise.department_governance import GovernanceError, _company
from enterprise.providers.submission import reported_usage
from enterprise.task_credentials import (
    credential_scope, prepare_task_binding, project_record_costs,
)


def managed_selection(service, provider, selection):
    if selection.get('call_source_id') or selection.get('business_project_id'):
        return True
    conn = service.connect()
    try:
        return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='credential_sources'").fetchone()
                    and conn.execute('SELECT 1 FROM credential_sources WHERE provider_id=?', (provider['id'],)).fetchone())
    finally:
        conn.close()


def adopt_shared_source(service, principal, metadata, secret_loader):
    # Check authority before reading the old secret; create_source rechecks it.
    with service.session(principal) as (_conn, actor):
        if not _company(actor):
            raise GovernanceError('DEPARTMENT_PERMISSION_DENIED', 403)
    secret = secret_loader(metadata['provider_id'])
    if not secret:
        raise GovernanceError('LEGACY_SHARED_KEY_NOT_CONFIGURED')
    return service.create_source(principal, **metadata, secret=secret)


async def wait_image_result(journal, task_id):
    """Only wait for the existing durable job. Cancellation never resubmits it."""
    while True:
        record = await asyncio.to_thread(journal.get, task_id)
        if record['status'] == 'succeeded':
            return record['result']
        if record['status'] == 'failed':
            raise HTTPException(record.get('status_code') or 502,
                {'message':record.get('error') or '生成未完成', 'task_id':task_id,
                 'recovery_required':bool(record.get('recovery_required'))})
        await asyncio.sleep(.25)


class LegacyTextCalls:
    """No new queue: legacy chat executes once and uses the existing LLM journal."""
    def __init__(self, tasks, service):
        self.tasks, self.journal, self.service = tasks, tasks.journal, service

    async def begin(self, payload, owner, provider, model):
        owner = owner if isinstance(owner, str) else None
        if not owner and managed_selection(self.service, provider, payload.model_dump()):
            raise HTTPException(401, '调用来源需要登录')
        task_id = 'canvas_llm_' + uuid.uuid4().hex
        binding = await asyncio.to_thread(prepare_task_binding, self.service,
            {'id':task_id, 'model':model}, payload.model_dump(), owner, provider)
        if not binding:
            return None
        record = {'id':task_id, 'type':'llm', 'status':'queued', 'created_at':time.time(),
                  'updated_at':time.time(), 'provider_id':provider['id'], 'model':model,
                  'entrypoint':'chat', 'source':None, 'billing_context':binding,
                  'result':None, 'error':'', 'provider_receipts':[{'index':0, 'state':'started'}]}
        await asyncio.to_thread(create_task_receipt, self.journal, record, owner)
        await asyncio.to_thread(self.journal.mark_running, task_id)
        return LegacyTextRun(self, await asyncio.to_thread(self.journal.get, task_id))

    async def call(self, payload, owner, provider, model, invoke):
        run = await self.begin(payload, owner, provider, model)
        if not run:
            return await invoke()
        with run.scope():
            try:
                value = await invoke()
                await run.complete(value['text'], value.get('raw_usage'), value.get('reported_usage'))
                return value
            except Exception as exc:
                await run.interrupted()
                status = getattr(exc, 'status_code', None) or getattr(getattr(exc, 'response', None), 'status_code', 502)
                raise HTTPException(status, {'message':'文本调用未完成，请核对原生成任务',
                    'task_id':run.record['id']}) from None
            except BaseException:
                await run.interrupted()
                raise

    async def stream(self, payload, owner, provider, model, build):
        run = await self.begin(payload, owner, provider, model)
        if not run:
            return await build(None)
        with run.scope():
            try:
                response = await build(run)
            except BaseException:
                await run.interrupted()
                raise
        return TrackedTextResponse(response, run)


class TrackedTextResponse(StreamingResponse):
    def __init__(self, response, run):
        super().__init__(response.body_iterator, status_code=response.status_code,
                         media_type=response.media_type, background=response.background)
        self.raw_headers = response.raw_headers
        self.run = run

    async def stream_response(self, send):
        # The ASGI stream task owns both the ContextVar tokens and iterator close.
        with self.run.scope():
            try:
                await super().stream_response(send)
            finally:
                with anyio.CancelScope(shield=True):
                    try:
                        await self.body_iterator.aclose()
                    finally:
                        await self.run.interrupted()


class LegacyTextRun:
    def __init__(self, calls, record):
        self.calls, self.record, self.finished = calls, record, False
        self.reported = {}

    def observe(self, raw):
        self.reported.update(reported_usage(raw))

    @contextmanager
    def scope(self):
        with credential_scope(self.record, service=self.calls.service):
            token = _attempt.set((self.calls.journal, self.record['id']))
            try:
                yield
            finally:
                _attempt.reset(token)

    async def complete(self, text, usage, reported=None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('文本接口没有返回可确认的正文')
        journal, task_id = self.calls.journal, self.record['id']
        value = {'text':text, 'model':self.record['model']}
        await asyncio.to_thread(journal.record_llm_result, task_id, value)
        await asyncio.to_thread(journal.record_provider_request, task_id, 0,
            {'state':'generated', 'reported_usage':reported if reported is not None else
             {**reported_usage({'usage':usage}), **self.reported}})
        result = await self.calls.tasks._archive(task_id, value)
        await asyncio.to_thread(journal.record_provider_request, task_id, 0, {'state':'succeeded'})
        await self.finish({'status':'succeeded', 'result':result, 'recovery_required':False, 'error':''})

    async def finish(self, changes):
        await asyncio.to_thread(self.calls.journal.finish, self.record['id'], changes)
        self.finished = True
        await asyncio.to_thread(project_record_costs, await asyncio.to_thread(self.calls.journal.get, self.record['id']))

    async def interrupted(self):
        if self.finished:
            return
        record = await asyncio.to_thread(self.calls.journal.get, self.record['id'])
        state = record['provider_receipts'][0]['state']
        unknown = state not in {'started', 'failed'}
        message = '文本调用未完成；请从生成任务核对原记录，不会自动重新生成。'
        if state not in {'failed', 'succeeded'}:
            await asyncio.to_thread(self.calls.journal.record_provider_request, record['id'], 0,
                {'state':'unknown' if unknown else 'failed', 'error':message})
        await self.finish({'status':'failed', 'error':message, 'recovery_required':unknown})
