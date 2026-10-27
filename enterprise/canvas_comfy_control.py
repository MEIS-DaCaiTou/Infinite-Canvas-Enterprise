"""Owner-scoped controls for accepted ComfyUI jobs on their original backend."""
import asyncio

import requests
from fastapi import APIRouter, Header, HTTPException

from enterprise import db
from enterprise.canvas_comfy_recovery import public_comfy_task
from enterprise.generation_tasks import GenerationTaskRepository
from enterprise.providers.comfyui import ComfyClient, ComfyCancellationUnsupported


def summary(record):
    value = public_comfy_task(record)
    return {key: value.get(key) for key in (
        'id', 'status', 'phase', 'source', 'created_at', 'workflow_json', 'error', 'recovery_required', 'cancellation', 'can_cancel')}


def create_router(journal, validate, resume, *, cancel_waiting=None):
    router = APIRouter(prefix='/_enterprise_internal/comfy-tasks')
    repository = GenerationTaskRepository(journal.root, journal=journal)

    def owner(value):
        if not value:
            raise HTTPException(401, '请先登录')
        return value

    def canvas_tasks(user_id, canvas_id):
        result, before = [], None
        while True:
            rows = db.list_owned_canvas_tasks(user_id, before=before, task_type='canvas_comfy', limit=200)
            for row in rows:
                record = repository._mapped_record(user_id, row['task_id'], 'canvas_comfy')
                if record and (record.get('source') or {}).get('canvas_id') == canvas_id:
                    result.append(summary(record))
            if len(rows) < 200:
                return {'items': result}
            last = rows[-1]
            before = last['created_at'], last['task_type'], last['task_id']

    @router.get('')
    async def page(canvas_id: str, x_enterprise_user_id: str = Header(default='')):
        return await asyncio.to_thread(canvas_tasks, owner(x_enterprise_user_id), canvas_id)

    @router.post('/{task_id}/cancel')
    async def cancel(task_id: str, x_enterprise_user_id: str = Header(default='')):
        record = await asyncio.to_thread(repository.owned_record, owner(x_enterprise_user_id), task_id, 'canvas_comfy')
        if record is None:
            raise HTTPException(404, '任务不存在或不可访问')
        if record['status'] in {'succeeded', 'cancelled'} or (record['status'] == 'failed' and not record.get('recovery_required')):
            return {'task': summary(record), 'message': '原任务已结束'}
        if cancel_waiting and await cancel_waiting(task_id):
            return {'task': summary(await asyncio.to_thread(journal.get, task_id)), 'message': '已取消平台等待任务，未提交后端'}
        receipt = record.get('comfy_receipt') or {}
        if not receipt.get('prompt_id'):
            raise HTTPException(409, '任务尚未获得后端受理身份，请稍后重试')
        validate(receipt)
        try:
            acknowledged = await asyncio.to_thread(ComfyClient(receipt['backend']).cancel, receipt['prompt_id'])
        except ComfyCancellationUnsupported as exc:
            raise HTTPException(501, str(exc)) from exc
        except (requests.RequestException, ValueError) as exc:
            raise HTTPException(503, '取消结果尚未确认，请查看原任务状态；不会自动重发或取消其他任务') from exc
        await asyncio.to_thread(journal.record_comfy_cancellation, task_id, acknowledged)
        # Existing recovery and live workers query the same saved prompt ID.
        resume(task_id)
        return {'task': summary(await asyncio.to_thread(journal.get, task_id)),
                'message': '取消请求已发送，等待后端确认' if acknowledged else '后端未取消任务，正在核对原状态'}

    return router
