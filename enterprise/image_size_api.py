"""Personal size HTTP adapter; authenticated identity comes from the Gateway."""
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from enterprise.config import PATH_ROOTS
from enterprise.image_size_presets import ImageSizePresets, SizePresetInput
from enterprise.user_model_api import current_user_id


def create_router(service=None):
    service = service or ImageSizePresets(PATH_ROOTS.DATA_ROOT)
    router = APIRouter(prefix='/api/me/image-size-presets')

    async def call(request, method, *args):
        owner = current_user_id(request)
        try:
            return await run_in_threadpool(method, owner, *args)
        except KeyError:
            raise HTTPException(404, '尺寸预设不存在') from None
        except (OSError, ValueError):
            raise HTTPException(503, '个人尺寸未能读取或保存，请保留当前内容并重试') from None

    @router.get('')
    async def list_presets(request: Request):
        return {'presets': await call(request, service.list)}

    @router.post('')
    async def create_preset(value: SizePresetInput, request: Request):
        return await call(request, service.save, value)

    @router.put('/{preset_id}')
    async def update_preset(preset_id: str, value: SizePresetInput, request: Request):
        return await call(request, service.save, value, preset_id)

    @router.delete('/{preset_id}')
    async def delete_preset(preset_id: str, request: Request):
        await call(request, service.delete, preset_id)
        return {'ok': True}

    return router

