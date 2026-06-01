"""
企业层管理员 API
挂载到 /enterprise 路径下，仅管理员可访问
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from enterprise import db as edb
from enterprise.auth import create_token

router = APIRouter()


def _require_admin(request: Request) -> dict:
    """从 request.state 获取当前用户，确认是管理员"""
    user = getattr(request.state, "user", None)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ── 用户管理 ──────────────────────────────────────────────

@router.get("/api/users")
async def list_users(request: Request):
    _require_admin(request)
    users = edb.list_users()
    # 不返回密码哈希
    for u in users:
        u.pop("password_hash", None)
    return users


@router.post("/api/users")
async def create_user(request: Request):
    _require_admin(request)
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    display_name = (body.get("display_name") or "").strip()
    is_admin = bool(body.get("is_admin", False))

    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")

    try:
        result = edb.create_user(username, password, display_name, is_admin)
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=409, detail="用户名已存在")
        raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse({"success": True, "user": result}, status_code=201)


@router.put("/api/users/{user_id}/password")
async def reset_password(user_id: str, request: Request):
    _require_admin(request)
    body = await request.json()
    new_password = (body.get("password") or "").strip()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")
    edb.update_user_password(user_id, new_password)
    return {"success": True}


@router.put("/api/users/{user_id}/role")
async def update_user_role(user_id: str, request: Request):
    current = _require_admin(request)
    if user_id == current["user_id"]:
        raise HTTPException(status_code=400, detail="不能修改自己的权限")
    body = await request.json()
    is_admin = bool(body.get("is_admin", False))
    edb.update_user_role(user_id, is_admin)
    return {"success": True, "is_admin": is_admin}


@router.delete("/api/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    current = _require_admin(request)
    if user_id == current["user_id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    edb.delete_user(user_id)
    return {"success": True}


# ── 画布归属查询（管理员专用）────────────────────────────

@router.get("/api/canvas-owners")
async def canvas_owners(request: Request):
    """返回 {canvas_id: {user_id, username}} 的全量映射"""
    _require_admin(request)
    owner_map = edb.get_all_canvas_owner_map()   # {canvas_id: user_id}
    users = {u["id"]: u for u in edb.list_users()}

    result = {}
    for canvas_id, uid in owner_map.items():
        u = users.get(uid, {})
        result[canvas_id] = {
            "user_id": uid,
            "username": u.get("username", "未知"),
            "display_name": u.get("display_name", ""),
        }
    return result


@router.put("/api/canvases/{canvas_id}/owner")
async def assign_canvas_owner(canvas_id: str, request: Request):
    """管理员手动分配画布归属"""
    _require_admin(request)
    body = await request.json()
    user_id = (body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id 不能为空")
    # 验证目标用户存在
    target = edb.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    edb.assign_canvas_owner(canvas_id, user_id)
    edb.log_action(user_id, "canvas_assigned", canvas_id)
    return {"success": True, "canvas_id": canvas_id, "user_id": user_id}


# ── 自身信息 ──────────────────────────────────────────────

@router.get("/api/me")
async def get_me(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    u = edb.get_user_by_id(user["user_id"]) or {}
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "display_name": u.get("display_name", user["username"]),
        "is_admin": user.get("is_admin", False),
    }


@router.put("/api/me/password")
async def change_my_password(request: Request):
    """当前登录用户修改自己的密码"""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    body = await request.json()
    old_password = (body.get("old_password") or "").strip()
    new_password = (body.get("new_password") or "").strip()
    if not old_password or not new_password:
        raise HTTPException(status_code=400, detail="旧密码和新密码不能为空")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6位")

    db_user = edb.get_user_by_id(user["user_id"])
    if not db_user or not edb.verify_password(old_password, db_user["password_hash"]):
        raise HTTPException(status_code=400, detail="旧密码不正确")

    edb.update_user_password(user["user_id"], new_password)
    edb.log_action(user["user_id"], "password_changed", None)
    return {"success": True}


# ── 审计日志 ──────────────────────────────────────────────

@router.get("/api/logs")
async def list_logs(request: Request):
    """管理员查看操作审计日志，支持分页和过滤"""
    _require_admin(request)
    params = request.query_params
    limit = min(int(params.get("limit", 50)), 200)
    offset = int(params.get("offset", 0))
    user_id = params.get("user_id") or None
    action = params.get("action") or None
    rows, total = edb.get_logs(limit=limit, offset=offset, user_id=user_id, action=action)
    return {"total": total, "offset": offset, "limit": limit, "items": rows}
