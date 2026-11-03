"""OpenAI-compatible speech on the existing owned journal/dispatcher/key binding."""
import asyncio
import time
import uuid
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import Field
from enterprise.task_credentials import CallSourceSelection, task_error
from enterprise.canvas_task_journal import create_task_receipt


class CharacterVoiceRequest(CallSourceSelection):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    provider_id: str = Field(min_length=1, max_length=200)
    model: Literal['tts-1', 'tts-1-hd', 'gpt-4o-mini-tts'] = 'tts-1'
    voice: Literal['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'] = 'alloy'
    input: str = Field(min_length=1, max_length=2000)
    speed: float = Field(default=1, ge=0.25, le=4)
    instructions: str = Field(default='', max_length=1000)


class CharacterVoiceTasks:
    def __init__(self, journal, provider, headers, prepare_binding, save, publish, enqueue, client=None):
        self.journal, self.provider, self.headers = journal, provider, headers
        self.prepare_binding, self.save, self.publish, self.enqueue = prepare_binding, save, publish, enqueue
        self.client = client or (lambda: httpx.AsyncClient(timeout=180, follow_redirects=False))
        self.lock = asyncio.Lock()

    async def create(self, payload, owner):
        if not owner:
            raise HTTPException(401, '请先登录')
        selected = self.provider(payload.provider_id)
        if selected.get('protocol', 'openai') != 'openai':
            raise HTTPException(400, '该平台不是兼容语音协议，请选择OpenAI兼容平台')
        task_id = 'canvas_audio_' + payload.request_id
        async with self.lock:
            existing = await asyncio.to_thread(self.journal.get, task_id)
            if existing:
                if existing.get('enterprise_user_id') != owner or existing.get('type') != 'audio':
                    raise HTTPException(404, '语音任务不存在或不可访问')
                return {'task_id': task_id, 'status': existing['status']}
            binding = await asyncio.to_thread(self.prepare_binding, task_id, payload, owner)
            await asyncio.to_thread(create_task_receipt, self.journal, {
                'id': task_id, 'type': 'audio', 'status': 'queued', 'created_at': time.time(),
                'updated_at': time.time(), 'provider_id': payload.provider_id, 'model': payload.model,
                'provider_receipts': [{'index': 0, 'state': 'started'}], 'result': None, 'error': '',
                **({'billing_context': binding} if binding else {}),
            }, owner)
            await self.enqueue(task_id, payload)
        return {'task_id': task_id, 'status': 'queued'}

    async def run(self, task_id, payload):
        if not await asyncio.to_thread(self.journal.mark_running, task_id):
            return
        submitted = False
        try:
            selected = self.provider(payload.provider_id)
            headers = self.headers(provider=selected, model=payload.model)
            body = {'model': payload.model, 'voice': payload.voice, 'input': payload.input,
                    'speed': payload.speed, 'response_format': 'mp3'}
            if payload.instructions and payload.model == 'gpt-4o-mini-tts':
                body['instructions'] = payload.instructions
            await asyncio.to_thread(self.journal.finish, task_id,
                {'provider_receipts': [{'index': 0, 'state': 'submitting'}]})
            async with self.client() as client:
                submitted = True
                async with client.stream('POST', selected['base_url'].rstrip('/') + '/audio/speech',
                                         headers=headers, json=body) as response:
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 20 * 1024 * 1024:
                            raise ValueError('语音结果超过20MB，请核对供应商结果')
                    if not data or not (bytes(data[:3]) == b'ID3' or data[0] == 255 and len(data) > 1 and data[1] & 224 == 224):
                        raise ValueError('供应商未返回有效MP3；请核对原任务')
            url = await asyncio.to_thread(self.save, bytes(data))
            record = await asyncio.to_thread(self.journal.get, task_id)
            await asyncio.to_thread(self.publish, record['enterprise_user_id'], [url])
            changes = {'status': 'succeeded', 'result': {'audios': [url]}, 'error': '',
                       'provider_receipts': [{'index': 0, 'state': 'succeeded'}]}
        except Exception as exc:
            unknown = submitted and not (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500)
            changes = {'status': 'failed', 'error': ('语音请求结果待核对，未自动重提。' if unknown else '语音请求失败：') + task_error(str(exc))[:500],
                       'recovery_required': unknown, 'provider_receipts': [{'index': 0, 'state': 'unknown' if unknown else 'failed'}]}
        await asyncio.to_thread(self.journal.finish, task_id, changes)
