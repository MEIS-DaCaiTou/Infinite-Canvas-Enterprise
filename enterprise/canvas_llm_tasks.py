"""Owned canvas text jobs over the existing journal; never replay paid chat calls."""
import asyncio
from contextvars import ContextVar
import time
import uuid

from fastapi import HTTPException

from enterprise.canvas_task_journal import create_task_receipt
from enterprise.providers.submission import reported_usage
from enterprise.runtime.logging import redact_text

_attempt = ContextVar('canvas_llm_attempt', default=None)


async def llm_submitting(model):
    """Called immediately before the existing HTTP/CLI submission boundary."""
    sink = _attempt.get()
    if sink:
        journal, task_id = sink
        await asyncio.to_thread(journal.record_provider_request, task_id, 0,
            {'state':'submitting', 'model':model, 'started_at':time.time()})


async def llm_response(status_code):
    sink = _attempt.get()
    if sink:
        journal, task_id = sink
        # An explicit rejection is distinct from a lost/malformed successful reply.
        rejected = status_code in {400, 401, 403, 404, 405, 415, 422, 429}
        await asyncio.to_thread(journal.record_provider_request, task_id, 0,
            {'state':'failed' if rejected else 'received', 'http_status':status_code})


def validate_llm_text(text):
    """Keep legacy display fallbacks out of durable successful results."""
    if _attempt.get() and (not isinstance(text, str) or not text.strip()):
        raise ValueError('文本接口没有返回可确认的正文')


def can_restore_llm(record):
    return record.get('type') == 'llm' and record.get('status') == 'failed' and bool(record.get('llm_result'))


class CanvasLLMTasks:
    def __init__(self, journal, generate, archive, publish, schedule, enqueue=None, prepare_binding=None):
        self.journal, self.generate, self.archive = journal, generate, archive
        self.publish, self.schedule = publish, schedule
        self.enqueue = enqueue
        self.prepare_binding = prepare_binding
        self.accept_lock, self.restore_lock = asyncio.Lock(), asyncio.Lock()

    async def create(self, payload, user_id):
        try:
            nonce = uuid.UUID(payload.request_id).hex if payload.request_id else uuid.uuid4().hex
        except ValueError as exc:
            raise HTTPException(400, '文本请求身份无效') from exc
        task_id, owner = 'canvas_llm_' + nonce, user_id or ''
        async with self.accept_lock:
            existing = await asyncio.to_thread(self.journal.get, task_id)
            if existing:
                if existing.get('type') != 'llm' or existing.get('enterprise_user_id', '') != owner:
                    raise HTTPException(403, 'Task owner mismatch')
                return {'task_id':task_id, 'status':existing['status']}
            binding = await asyncio.to_thread(self.prepare_binding, task_id, payload, owner) if self.prepare_binding else None
            await asyncio.to_thread(create_task_receipt, self.journal, {
                **({'billing_context':binding} if binding else {}),
                'id':task_id, 'type':'llm', 'status':'queued', 'created_at':time.time(),
                'updated_at':time.time(), 'provider_id':payload.provider, 'model':payload.model or payload.ms_model,
                'source':payload.source.model_dump() if payload.source else None,
                'result':None, 'error':'', 'provider_receipts':[{'index':0, 'state':'started'}],
            }, owner)
            if self.enqueue:
                await self.enqueue(task_id, payload)
            else:
                self.schedule(self.run(task_id, payload))
        return {'task_id':task_id, 'status':'queued'}

    async def _archive(self, task_id, value):
        url = await asyncio.to_thread(self.archive, value['text'])
        result = {'text':value['text'], 'model':value.get('model', ''), 'items':[
            {'url':url, 'kind':'text', 'text':value['text'], 'name':'LLM 文本.txt', 'result_id':task_id+':text'}]}
        record = await asyncio.to_thread(self.journal.get, task_id)
        if record.get('enterprise_user_id'):
            await asyncio.to_thread(self.publish, record['enterprise_user_id'], [url])
        return result

    async def run(self, task_id, payload):
        if not await asyncio.to_thread(self.journal.mark_running, task_id):
            return
        token = _attempt.set((self.journal, task_id))
        try:
            response = await self.generate(payload)
            text = response.get('text')
            if not isinstance(text, str) or not text.strip():
                raise ValueError('文本接口没有返回可确认的正文')
            value = {'text':text, 'model':response.get('model') or payload.model}
            # Save received text before file archival; no input/history/raw provider object.
            await asyncio.to_thread(self.journal.record_llm_result, task_id, value)
            await asyncio.to_thread(self.journal.record_provider_request, task_id, 0,
                {'state':'generated', 'reported_usage':reported_usage({'usage':response.get('raw_usage')} )})
            result = await self._archive(task_id, value)
            await asyncio.to_thread(self.journal.record_provider_request, task_id, 0, {'state':'succeeded'})
            changes = {'status':'succeeded', 'result':result, 'model':value['model'], 'error':'', 'recovery_required':False}
        except Exception as exc:
            from enterprise.task_credentials import task_error
            record = await asyncio.to_thread(self.journal.get, task_id)
            state = record['provider_receipts'][0]['state']
            unknown = state not in {'started', 'failed'}
            message = task_error(getattr(exc, 'detail', '') or exc)[:1000]
            if unknown:
                message += '；请核对原文本任务，不会自动重新生成。'
            if state not in {'succeeded', 'failed'}:
                await asyncio.to_thread(self.journal.record_provider_request, task_id, 0,
                    {'state':'unknown' if unknown else 'failed', 'error':message})
            changes = {'status':'failed', 'error':message, 'recovery_required':unknown}
        finally:
            _attempt.reset(token)
        await asyncio.to_thread(self.journal.finish, task_id, changes)

    async def restore(self, task_id):
        """Recover an already received body locally; this method cannot call generate."""
        async with self.restore_lock:
            record = await asyncio.to_thread(self.journal.get, task_id)
            if not record or record.get('type') != 'llm':
                raise HTTPException(404, '文本任务不存在')
            if can_restore_llm(record):
                try:
                    result = await self._archive(task_id, record['llm_result'])
                    await asyncio.to_thread(self.journal.finish_provider_recovery, task_id, {'status':'succeeded', **result})
                except OSError as exc:
                    raise HTTPException(503, '已接收的文本暂未归档，请保留原任务并稍后重试') from exc
                record = await asyncio.to_thread(self.journal.get, task_id)
            return public_llm_task(record)


def public_llm_task(record):
    return {key:value for key, value in record.items() if key not in {'provider_receipts', 'llm_result'}}
