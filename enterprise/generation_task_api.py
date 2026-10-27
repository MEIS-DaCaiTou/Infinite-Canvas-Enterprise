"""Authenticated personal task reads through the existing loopback client."""
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import JSONResponse

from enterprise.user_model_api import current_user_id

router = APIRouter()


async def read_catalog(request, suffix="", **params):
    user_id = current_user_id(request)
    client = getattr(request.app.state, "upstream_client", None)
    if client is None:
        raise HTTPException(503, "业务服务暂不可用，请稍后重试读取原任务")
    try:
        response = await client.get("/_enterprise_internal/generation-tasks" + suffix,
            params=params, headers={"X-Enterprise-User-ID": user_id})
        if response.status_code not in {200, 400, 403, 404, 422, 503}:
            raise ValueError("Unexpected catalog response")
        return JSONResponse(response.json(), status_code=response.status_code, headers={"Cache-Control": "no-store"})
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "任务记录暂不可读，请保留原任务并稍后重试") from exc


@router.get('/api/me/generation-tasks')
async def generation_tasks(request: Request, cursor: str = "", status: str = "", kind: str = "", limit: int = Query(30, ge=1, le=50)):
    return await read_catalog(request, cursor=cursor, status=status, kind=kind, limit=limit)


@router.get('/api/me/generation-tasks/{task_id}')
async def generation_task(request: Request, task_id: str, target_canvas_id: str = ""):
    return await read_catalog(request, "/" + quote(task_id, safe=""), target_canvas_id=target_canvas_id)


async def comfy_control(request, suffix='', *, cancel=False, **params):
    user_id = current_user_id(request)
    client = getattr(request.app.state, 'upstream_client', None)
    if client is None:
        raise HTTPException(503, '业务服务暂不可用')
    try:
        response = await client.request('POST' if cancel else 'GET', '/_enterprise_internal/comfy-tasks' + suffix,
            params=params, headers={'X-Enterprise-User-ID': user_id}, timeout=45)
        if response.status_code not in {200, 400, 401, 403, 404, 409, 422, 501, 503}:
            raise ValueError('Unexpected task control response')
        return JSONResponse(response.json(), status_code=response.status_code, headers={'Cache-Control': 'no-store'})
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, '原任务状态暂不可读，请稍后核对；不会自动重新生成') from exc


@router.get('/api/me/comfy-tasks')
async def canvas_comfy_tasks(request: Request, canvas_id: str):
    return await comfy_control(request, canvas_id=canvas_id)


@router.post('/api/me/comfy-tasks/{task_id}/cancel')
async def cancel_comfy_task(request: Request, task_id: str):
    return await comfy_control(request, '/' + quote(task_id, safe='') + '/cancel', cancel=True)
