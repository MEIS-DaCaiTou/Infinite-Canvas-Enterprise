"""Authenticated personal task reads; execution remains behind existing owned routes."""
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from enterprise.config import PATH_ROOTS
from enterprise.generation_tasks import GenerationTaskRepository
from enterprise.user_model_api import current_user_id

router = APIRouter()


def repository():
    return GenerationTaskRepository(PATH_ROOTS.DATA_ROOT / "canvas-tasks")


@router.get('/api/me/generation-tasks')
async def generation_tasks(request: Request, cursor: str = "", status: str = "", kind: str = "", limit: int = Query(30, ge=1, le=50)):
    user_id = current_user_id(request)
    try:
        value = await run_in_threadpool(repository().page, user_id, cursor=cursor, status=status, kind=kind, limit=limit)
        return JSONResponse(value, headers={"Cache-Control": "no-store"})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, "任务记录暂不可读，请稍后重试") from exc


@router.get('/api/me/generation-tasks/{task_id}')
async def generation_task(request: Request, task_id: str):
    user_id = current_user_id(request)
    try:
        value = await run_in_threadpool(repository().detail, user_id, task_id)
    except (OSError, ValueError, UnicodeError) as exc:
        raise HTTPException(503, "任务记录暂不可读，请保留原任务并稍后重试") from exc
    if value is None:
        raise HTTPException(404, "任务不存在或不可访问")
    # Completion can happen after the browser disconnects, before the old task
    # polling route projected result ownership. Reuse that projection only
    # after verifying the persisted task owner. Existing owners are immutable.
    from enterprise.interceptors import record_resource_urls_for_user
    await run_in_threadpool(record_resource_urls_for_user, user_id, "generation_task_detail", value)
    return JSONResponse(value, headers={"Cache-Control": "no-store"})
