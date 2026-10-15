"""Upstream catalog reads share its existing journal mutex with task writes."""
from fastapi import APIRouter, Header, HTTPException, Query
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from enterprise.generation_tasks import GenerationTaskRepository


def create_router(journal):
    router = APIRouter(prefix="/_enterprise_internal/generation-tasks")
    repository = GenerationTaskRepository(journal.root, journal=journal)

    def owner(user_id):
        # Same trusted loopback identity contract as existing task submission.
        # The public Gateway blocks this namespace and supplies this header.
        if not user_id:
            raise HTTPException(401, "请先登录")
        return user_id

    @router.get("")
    async def page(cursor: str = "", status: str = "", kind: str = "", limit: int = Query(30, ge=1, le=50),
                   x_enterprise_user_id: str = Header(default="")):
        try:
            value = await run_in_threadpool(repository.page, owner(x_enterprise_user_id),
                                           cursor=cursor, status=status, kind=kind, limit=limit)
            return JSONResponse(value, headers={"Cache-Control": "no-store"})
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "任务记录暂不可读，请稍后重试") from exc

    @router.get("/{task_id}")
    async def detail(task_id: str, x_enterprise_user_id: str = Header(default="")):
        user_id = owner(x_enterprise_user_id)
        try:
            value = await run_in_threadpool(repository.detail, user_id, task_id)
        except (OSError, ValueError, UnicodeError) as exc:
            raise HTTPException(503, "任务记录暂不可读，请保留原任务并稍后重试") from exc
        if value is None:
            raise HTTPException(404, "任务不存在或不可访问")
        from enterprise.interceptors import record_resource_urls_for_user
        # Only verified output references grant ownership. Text, errors and
        # names may themselves contain paths; they are never authorizations.
        output_urls = [item["url"] for item in value["items"]]
        await run_in_threadpool(record_resource_urls_for_user, user_id, "generation_task_detail", output_urls)
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    return router
