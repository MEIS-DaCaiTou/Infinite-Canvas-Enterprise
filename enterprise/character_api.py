"""Personal character HTTP adapter; the Gateway supplies authenticated identity."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from enterprise.character_repository import CharacterError, CharacterRepository
from enterprise.characters import Characters
from enterprise.config import PATH_ROOTS
from enterprise.interceptors import normalize_resource_url, can_access_resource
from enterprise.user_model_api import current_user_id


def local_preview_available(root):
    """Optional local comparison files are deliberately absent from the PR."""
    return all((root / path).is_file() for path in (
        'static/js/character-generation-renderer.js',
        'static/characters/motion/midwam-human.glb',
        'static/characters/motion/draco/draco_wasm_wrapper.js',
        'static/characters/motion/draco/draco_decoder.wasm',
        'static/vendor/three-addons-r160/loaders/GLTFLoader.js',
        'static/vendor/three-addons-r160/loaders/DRACOLoader.js',
    ))


def create_router(service=None):
    service = service or Characters(CharacterRepository(PATH_ROOTS.DATA_ROOT, PATH_ROOTS.APP_ROOT / 'static/characters/catalog.json'), normalize_resource_url, can_access_resource)
    router = APIRouter(prefix='/api/me/characters')

    async def call(request, method, *args):
        current_user_id(request)
        principal = request.state.user
        try:
            value = await run_in_threadpool(method, principal, *args)
            return JSONResponse(value, headers={'Cache-Control': 'no-store'})
        except CharacterError as exc:
            raise HTTPException(exc.status, exc.message) from None
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(503, '角色库暂不可读写，请保留当前内容并稍后重试') from None

    async def body(request):
        current_user_id(request)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 32768:
                raise HTTPException(413, '角色资料过大')
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, UnicodeError):
            raise HTTPException(400, '角色资料格式无效') from None

    @router.get('')
    async def list_characters(request: Request):
        return await call(request, lambda user: {'characters': service.list(user), 'schema_version': 1, 'owner_id': user['user_id']})

    @router.get('/catalog')
    async def catalog(request: Request):
        return await call(request, lambda user: {'characters': service.catalog(user), 'schema_version': 1,
            'local_preview_available': local_preview_available(PATH_ROOTS.APP_ROOT)})

    @router.post('')
    async def create(request: Request):
        return await call(request, service.save, await body(request))

    @router.put('/{character_id}')
    async def update(request: Request, character_id: str):
        return await call(request, service.save, await body(request), character_id)

    @router.delete('/{character_id}')
    async def remove(request: Request, character_id: str):
        value = await body(request)
        if set(value) != {'expected_revision'}:
            raise HTTPException(400, '移除角色字段无效')
        return await call(request, service.remove, character_id, value['expected_revision'])

    return router
