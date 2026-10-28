"""Queue settings and personal usage; the Gateway never owns dispatch state."""
import asyncio

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from enterprise.admin_api import _require_admin
from enterprise.user_model_api import current_user_id


def create_internal_router(queue):
    router = APIRouter(prefix='/_enterprise_internal/comfy-queue')

    @router.get('')
    async def settings():
        return {'policy': await asyncio.to_thread(queue.policy), 'status': await asyncio.to_thread(queue.status)}

    @router.put('')
    async def save(request: Request):
        return {'policy': await queue.save_policy(await request.json()), 'status': await asyncio.to_thread(queue.status)}

    @router.get('/me')
    async def personal(x_enterprise_user_id: str = Header(default='')):
        if not x_enterprise_user_id:
            raise HTTPException(401, '请先登录')
        return await asyncio.to_thread(queue.status, x_enterprise_user_id)

    return router


router = APIRouter()


async def forward(request, suffix='', *, body=None):
    user_id = current_user_id(request)
    client = getattr(request.app.state, 'upstream_client', None)
    if client is None:
        raise HTTPException(503, '队列服务暂不可用')
    try:
        response = await client.request('PUT' if body is not None else 'GET', '/_enterprise_internal/comfy-queue' + suffix,
            json=body, headers={'X-Enterprise-User-ID': user_id}, timeout=15)
        if response.status_code not in {200, 400, 401, 403, 409, 422, 503}:
            raise ValueError('Unexpected queue response')
        data = response.json()
        if response.status_code == 200 and not suffix:
            from enterprise import db
            for row in data['status']['items']:
                user = await asyncio.to_thread(db.get_user_by_id, row.get('enterprise_user_id', ''))
                row['user_name'] = (user or {}).get('display_name') or (user or {}).get('username') or '本机用户'
        return JSONResponse(data, status_code=response.status_code, headers={'Cache-Control': 'no-store'})
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, '队列服务暂不可读，请稍后重试；已受理任务保持不变') from exc


@router.get('/api/admin/comfy-queue')
async def settings(request: Request):
    _require_admin(request)
    return await forward(request)


@router.put('/api/admin/comfy-queue')
async def save(request: Request):
    user = _require_admin(request)
    from enterprise.department_api import _body
    result = await forward(request, body=await _body(request))
    if result.status_code == 200:
        from enterprise import db
        await asyncio.to_thread(db.log_action, user['user_id'], 'comfy_queue_policy', '更新算力分组、用户和工作流队列限额')
    return result


@router.get('/api/me/comfy-queue')
async def usage(request: Request):
    return await forward(request, '/me')
