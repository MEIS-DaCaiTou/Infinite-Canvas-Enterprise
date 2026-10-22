"""Authenticated business metadata routes; never returns credential plaintext."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from starlette.concurrency import run_in_threadpool

from enterprise.credential_vault import VaultUnavailable
from enterprise.department_governance import DepartmentGovernance, GovernanceError
from enterprise.department_costs import DepartmentCosts


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
    costs = DepartmentCosts(service)
    router = APIRouter(prefix='/api/business')

    async def call(request, function, **kwargs):
        principal = getattr(request.state, 'user', None)
        if not isinstance(principal, dict) or not principal.get('user_id'):
            raise HTTPException(401, '请先登录')
        try:
            if function.__name__ in {'entries', 'summary', 'budgets', 'alerts'}:
                from enterprise.task_credentials import refresh_cost_projection
                from enterprise.canvas_task_journal import CanvasTaskJournal
                from enterprise.config import PATH_ROOTS
                journal_root = PATH_ROOTS.DATA_ROOT / 'canvas-tasks'
                if journal_root.is_dir():
                    scopes = [(kwargs.get('scope', 'department' if function.__name__ == 'budgets' else 'me'), kwargs.get('department_id'))]
                    if function.__name__ == 'alerts':
                        context = await run_in_threadpool(service.workspace, principal)
                        scopes = [('company', None)] if context.get('company_admin') else [
                            ('department', d['id']) for d in context.get('departments', []) if d['can_manage']]
                    for scope, department in scopes:
                        await run_in_threadpool(refresh_cost_projection, service, principal, scope, department, CanvasTaskJournal(journal_root))
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
        return await call(request, service.workspace)

    @router.get('/directory')
    async def directory(request: Request):
        return await call(request, service.directory)

    @router.get('/tasks')
    async def business_tasks(request: Request, scope: str = 'me', department_id: str | None = None,
                             before: str | None = None):
        def tasks(principal, **kwargs):
            from enterprise.business_workspace import task_summaries
            return task_summaries(service, principal, **kwargs)
        return await call(request, tasks, scope=scope, department_id=department_id, before=before)

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

    @router.get('/projects')
    async def projects(request: Request):
        return await call(request, service.projects)

    @router.get('/projects/{project_id}/members')
    async def project_members(request: Request, project_id: str):
        return await call(request, service.project_members, project_id=project_id)

    @router.delete('/departments/{department_id}/members/{user_id}')
    async def remove_member(request: Request, department_id: str, user_id: str):
        return await call(request, service.remove_member, department_id=department_id, user_id=user_id)

    @router.post('/projects')
    async def create_project(request: Request):
        return await call(request, service.create_project,
                          **await fields(request, ['department_id', 'name'], ['department_id', 'name']))

    @router.put('/projects/{project_id}/visibility')
    async def share(request: Request, project_id: str):
        return await call(request, service.share_project, project_id=project_id,
                          **await fields(request, ['visibility'], ['visibility']))

    @router.put('/projects/{project_id}/members/{user_id}')
    async def grant_project(request: Request, project_id: str, user_id: str):
        return await call(request, service.grant_project, project_id=project_id, user_id=user_id,
                          **await fields(request, ['can_write'], ['can_write']))

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

    @router.get('/costs')
    async def entries(request: Request, scope: str = 'me', department_id: str | None = None,
                      before: str | None = None, limit: int = 50):
        return await call(request, costs.entries, scope=scope, department_id=department_id, before=before, limit=limit)

    @router.get('/costs/summary')
    async def summary(request: Request, scope: str = 'me', department_id: str | None = None,
                      starts_at: int = 0, ends_at: int | None = None):
        return await call(request, costs.summary, scope=scope, department_id=department_id,
                          starts_at=starts_at, ends_at=ends_at)

    @router.get('/budget-alerts')
    async def budget_alerts(request: Request):
        return await call(request, costs.alerts)

    @router.get('/departments/{department_id}/budgets')
    async def budgets(request: Request, department_id: str):
        return await call(request, costs.budgets, department_id=department_id)

    @router.put('/departments/{department_id}/budgets')
    async def budget(request: Request, department_id: str):
        names = ['period', 'starts_at', 'ends_at', 'unit', 'amount']
        return await call(request, costs.set_budget, department_id=department_id, **await fields(request, names, names))

    from enterprise.canvas_workspace import CanvasWorkspace
    workspace_service = CanvasWorkspace(service)

    @router.get('/workspace/context')
    async def canvas_workspace_context(request: Request):
        return await call(request, workspace_service.context)

    @router.get('/workspace')
    async def canvas_workspace(request: Request, scope: str = 'me', department_id: str | None = None,
                               member_id: str | None = None):
        return await call(request, workspace_service.listing, scope=scope,
                          department_id=department_id, member_id=member_id)

    @router.put('/workspace/folders/{folder_id}')
    async def workspace_folder(request: Request, folder_id: str):
        names = ['parent_id', 'business_project_id', 'archived']
        return await call(request, workspace_service.update_folder, folder_id=folder_id,
                          **await fields(request, names, names))

    @router.put('/workspace/archive')
    async def workspace_archive(request: Request):
        return await call(request, workspace_service.archive,
                          **await fields(request, ['canvas_ids', 'archived'], ['canvas_ids', 'archived']))

    from enterprise.project_results import ProjectResults
    results = ProjectResults(service)

    @router.get('/workspace/tasks')
    async def project_tasks(request: Request, scope: str = 'me', department_id: str | None = None,
                            project_id: str | None = None, member_id: str | None = None,
                            before: str | None = None, canvas_id: str | None = None):
        return await call(request, results.page, scope=scope, department_id=department_id,
                          project_id=project_id, member_id=member_id, before=before, canvas_id=canvas_id)

    @router.get('/workspace/tasks/{task_id}')
    async def project_task(request: Request, task_id: str):
        return await call(request, results.detail, task_id=task_id)

    @router.get('/workspace/tasks/{task_id}/outputs/{index}')
    async def project_output(request: Request, task_id: str, index: int):
        def output(principal):
            import mimetypes
            file = results.output(principal, task_id, index)
            inline = file.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.gif','.bmp','.mp4','.webm','.mov','.mp3','.wav','.ogg','.txt'}
            return FileResponse(file, media_type=mimetypes.guess_type(file.name)[0] if inline else 'application/octet-stream',
                filename=None if inline else file.name,
                headers={'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff'})
        return await call(request, output)

    from enterprise.shared_canvases import SharedCanvases
    shared_canvases = SharedCanvases(service)

    @router.get('/workspace/canvases/{canvas_id}')
    async def shared_canvas(request: Request, canvas_id: str):
        return await call(request, shared_canvases.detail, canvas_id=canvas_id)

    @router.get('/workspace/canvases/{canvas_id}/resources/{index}')
    @router.get('/workspace/canvases/{canvas_id}/resources/{index}/{filename}')
    async def shared_canvas_resource(request: Request, canvas_id: str, index: int, filename: str = ''):
        def resource(principal):
            import mimetypes
            file = shared_canvases.resource(principal,canvas_id,index)
            inline = file.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.gif','.bmp','.mp4','.webm','.mov','.mp3','.wav','.ogg','.txt'}
            return FileResponse(file, media_type=mimetypes.guess_type(file.name)[0] if inline else 'application/octet-stream',
                filename=None if inline else file.name, headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
        return await call(request, resource)

    @router.post('/workspace/canvases/{canvas_id}/reuse')
    async def reuse_shared_canvas(request: Request, canvas_id: str):
        await fields(request, [], [])
        return await call(request, shared_canvases.reuse, canvas_id=canvas_id)

    @router.post('/workspace/tasks/{task_id}/reuse')
    async def reuse_project_result(request: Request, task_id: str):
        return await call(request, results.reuse, task_id=task_id,
                          **await fields(request, ['keys'], ['keys']))

    @router.get('/member-workspace')
    async def member_workspace(request: Request):
        return await call(request, service.member_workspace)

    return router
