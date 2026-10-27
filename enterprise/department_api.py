"""Department/member and credential administration; no project or cost views."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from enterprise.credential_vault import VaultUnavailable
from enterprise.department_governance import DepartmentGovernance, GovernanceError


async def _body(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 32768:
            raise HTTPException(413, '业务请求过大')
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, UnicodeError):
        raise HTTPException(400, '业务请求格式无效') from None


def create_router(governance=None):
    service = governance or DepartmentGovernance()
    router = APIRouter(prefix='/api/business')

    async def call(request, function, **kwargs):
        principal = getattr(request.state, 'user', None)
        if not isinstance(principal, dict) or not principal.get('user_id'):
            raise HTTPException(401, '请先登录')
        try:
            value = await run_in_threadpool(function, principal, **kwargs)
            if isinstance(value, Response):
                return value
            return JSONResponse(value, headers={'Cache-Control':'no-store'})
        except GovernanceError as exc:
            raise HTTPException(exc.status_code, {'code':exc.code}) from None
        except VaultUnavailable:
            raise HTTPException(503, {'code':'CREDENTIAL_VAULT_UNAVAILABLE'}) from None
        except (TypeError, ValueError):
            # Do not echo validation inputs: a write may contain a secret.
            raise HTTPException(400, {'code':'INVALID_BUSINESS_REQUEST'}) from None

    async def fields(request, allowed, required):
        body = await _body(request)
        if set(body) - set(allowed) or not set(required).issubset(body):
            raise HTTPException(400, {'code':'INVALID_BUSINESS_FIELDS'})
        return body

    @router.get('/context')
    async def workspace(request: Request):
        return await call(request, service.management_context)

    @router.get('/directory')
    async def directory(request: Request):
        return await call(request, service.directory)

    @router.get('/sources/{source_id}/grants')
    async def source_grants(request: Request, source_id: str):
        return await call(request, service.source_grants, source_id=source_id)

    @router.get('/departments')
    async def departments(request: Request):
        return await call(request, service.departments)

    @router.post('/departments')
    async def create_department(request: Request):
        return await call(request, service.create_department, **await fields(request, ['name'], ['name']))

    @router.get('/departments/{department_id}/members')
    async def members(request: Request, department_id: str):
        return await call(request, service.members, department_id=department_id)

    @router.put('/departments/{department_id}/members/{user_id}')
    async def assign_member(request: Request, department_id: str, user_id: str):
        return await call(request, service.assign_member, department_id=department_id, user_id=user_id,
                          **await fields(request, ['manager'], ['manager']))

    @router.delete('/departments/{department_id}/members/{user_id}')
    async def remove_member(request: Request, department_id: str, user_id: str):
        return await call(request, service.remove_member, department_id=department_id, user_id=user_id)

    @router.get('/sources')
    async def sources(request: Request, manage: bool = False):
        return await call(request, service.sources, manage=manage)

    @router.post('/sources')
    async def create_source(request: Request):
        names = ['provider_id', 'name', 'scope', 'department_id', 'procurement', 'account_ref', 'secret']
        return await call(request, service.create_source, **await fields(request, names, names))

    @router.put('/sources/{source_id}/secret')
    async def rotate(request: Request, source_id: str):
        return await call(request, service.rotate_source, source_id=source_id,
                          **await fields(request, ['expected_revision', 'secret'], ['expected_revision', 'secret']))

    @router.put('/sources/{source_id}/grants/{user_id}')
    async def grant(request: Request, source_id: str, user_id: str):
        return await call(request, service.grant_source, source_id=source_id, user_id=user_id,
                          **await fields(request, ['allowed'], ['allowed']))

    @router.put('/sources/{source_id}/enabled')
    async def enable(request: Request, source_id: str):
        return await call(request, service.enable_source, source_id=source_id,
                          **await fields(request, ['enabled'], ['enabled']))

    @router.get('/member-workspace')
    async def member_workspace(request: Request):
        return await call(request, service.member_workspace)

    return router
