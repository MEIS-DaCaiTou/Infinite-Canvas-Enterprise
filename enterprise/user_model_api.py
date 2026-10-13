"""Authenticated personal preferences. Provider configuration remains administrator-only."""
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from enterprise.config import PATH_ROOTS
from enterprise.user_model_preferences import load_preferences, save_preferences

router = APIRouter()


def current_user_id(request):
    user = getattr(request.state, 'user', None)
    if not isinstance(user, dict) or not user.get('user_id'):
        raise HTTPException(status_code=401, detail='请先登录')
    return user['user_id']


@router.get('/api/me/model-preferences')
async def get_model_preferences(request: Request):
    user_id = current_user_id(request)
    try:
        return await run_in_threadpool(load_preferences, PATH_ROOTS.DATA_ROOT, user_id)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail='暂时无法读取个人模型设置') from exc


@router.put('/api/me/model-preferences')
async def put_model_preferences(request: Request):
    user_id = current_user_id(request)
    try:
        body = await request.json()
        return await run_in_threadpool(save_preferences, PATH_ROOTS.DATA_ROOT, user_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail='个人模型设置未能保存，请重试') from exc
