"""
企业层管理员 API
挂载到 /enterprise 路径下，仅管理员可访问
"""
import json
import sqlite3

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from enterprise import db as edb
from enterprise import security_user_governance as user_governance
from enterprise.migrations.sec_1b1_role_auth import ROLE_AUTH_READY

router = APIRouter()


def _raise_governance_http(exc: user_governance.UserGovernanceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.public_message},
    ) from exc


def _role_auth_ready() -> bool:
    try:
        return user_governance.get_role_auth_schema_state() == ROLE_AUTH_READY
    except user_governance.UserGovernanceError as exc:
        _raise_governance_http(exc)
    return False


def _require_admin(request: Request) -> dict:
    """从 request.state 获取当前用户，确认是管理员"""
    user = getattr(request.state, "user", None)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def _require_ready_principal(request: Request) -> dict:
    """Accept only the minimal verified-principal facts used by READY governance."""
    user = getattr(request.state, "user", None)
    if not isinstance(user, dict) or not isinstance(user.get("user_id"), str) or not user["user_id"]:
        raise HTTPException(
            status_code=401,
            detail={"code": "STALE_AUTHENTICATION", "message": "Authentication is no longer current"},
        )
    auth_version = user.get("auth_version")
    if isinstance(auth_version, bool) or not isinstance(auth_version, int) or auth_version < 0:
        raise HTTPException(
            status_code=401,
            detail={"code": "STALE_AUTHENTICATION", "message": "Authentication is no longer current"},
        )
    return user


def _audit_user_action(actor: dict, action: str, target: dict, summary: str, extra: dict | None = None) -> None:
    """记录管理员用户管理操作。"""
    detail = {
        "target_user_id": target.get("id"),
        "target_username": target.get("username"),
        "summary": summary,
    }
    if extra:
        detail.update(extra)
    edb.log_action(actor["user_id"], action, json.dumps(detail, ensure_ascii=False))


def _audit_permission_action(actor: dict, action: str, detail: dict) -> None:
    payload = dict(detail)
    payload["updated_by"] = actor["user_id"]
    edb.log_action(actor["user_id"], action, json.dumps(payload, ensure_ascii=False))
    edb.log_action(
        actor["user_id"],
        "permission_policy_updated",
        json.dumps({"source_action": action, **payload}, ensure_ascii=False),
    )


def _target_user_or_404(user_id: str) -> dict:
    target = edb.get_user_by_id_any_status(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    return target


def _is_active_admin(user: dict) -> bool:
    return bool(user.get("is_admin")) and bool(user.get("is_active"))


def _ensure_not_last_active_admin(target: dict, action: str) -> None:
    if _is_active_admin(target) and edb.count_active_admins() <= 1:
        raise HTTPException(status_code=400, detail=f"Cannot {action} the last active administrator")


async def _confirmed_user_action_body(request: Request, target: dict) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict) or not body:
        raise HTTPException(status_code=400, detail="confirm_username is required")
    confirm_username = str(body.get("confirm_username") or "").strip()
    if not confirm_username:
        raise HTTPException(status_code=400, detail="confirm_username is required")
    if confirm_username != str(target.get("username") or ""):
        raise HTTPException(status_code=400, detail="confirm_username does not match target username")
    return {
        "confirm_username": confirm_username,
        "reason": str(body.get("reason") or "").strip(),
    }


# ── 用户管理 ──────────────────────────────────────────────

@router.get("/api/users")
async def list_users(request: Request):
    _require_admin(request)
    users = edb.list_users()
    # 不返回密码哈希
    for u in users:
        u.pop("password_hash", None)
    return users


@router.get("/api/users/{user_id}/delete-impact")
async def user_delete_impact(user_id: str, request: Request):
    current = _require_admin(request)
    raw_limit = request.query_params.get("sample_limit", "20")
    try:
        sample_limit = int(raw_limit)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="sample_limit must be an integer")
    if sample_limit < 0:
        raise HTTPException(status_code=400, detail="sample_limit must be greater than or equal to 0")
    sample_limit = min(sample_limit, 100)

    target = _target_user_or_404(user_id)
    impact = edb.get_user_delete_impact(user_id, sample_limit=sample_limit)
    if not impact:
        raise HTTPException(status_code=404, detail="User not found")

    edb.log_action(
        current["user_id"],
        "user_delete_dry_run",
        json.dumps(
            {
                "target_user_id": target.get("id"),
                "target_username": target.get("username"),
                "counts": impact.get("counts", {}),
                "sample_limit": sample_limit,
            },
            ensure_ascii=False,
        ),
    )
    return impact


@router.post("/api/users")
async def create_user(request: Request):
    ready = _role_auth_ready()
    current = _require_ready_principal(request) if ready else _require_admin(request)
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    display_name = (body.get("display_name") or "").strip()
    requested_is_admin = body.get("is_admin", False)
    is_admin = bool(requested_is_admin)

    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")

    try:
        if ready:
            result = user_governance.create_ordinary_user(
                actor_user_id=current["user_id"],
                expected_actor_auth_version=current["auth_version"],
                username=username,
                password=password,
                display_name=display_name,
                requested_is_admin=requested_is_admin,
                role_field_present="role" in body,
                requested_role=body.get("role"),
            )
            is_admin = False
        else:
            result = edb.create_user(username, password, display_name, is_admin)
    except user_governance.UserGovernanceError as exc:
        _raise_governance_http(exc)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "USERNAME_CONFLICT", "message": "Username already exists"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "USER_CREATE_FAILED", "message": "User creation failed"},
        ) from exc

    target = edb.get_user_by_id_any_status(result["id"]) or result
    _audit_user_action(
        current,
        "user_created",
        target,
        f"创建用户 {username}",
        {"is_admin": is_admin},
    )
    return JSONResponse({"success": True, "user": result}, status_code=201)


@router.put("/api/users/{user_id}/password")
async def reset_password(user_id: str, request: Request):
    ready = _role_auth_ready()
    current = _require_ready_principal(request) if ready else _require_admin(request)
    body = await request.json()
    new_password = (body.get("password") or "").strip()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")
    if ready:
        try:
            result = user_governance.reset_user_password(
                actor_user_id=current["user_id"],
                expected_actor_auth_version=current["auth_version"],
                target_user_id=user_id,
                new_password=new_password,
                reason=body.get("reason"),
            )
        except user_governance.UserGovernanceError as exc:
            _raise_governance_http(exc)
        target = result["user"]
    else:
        target = _target_user_or_404(user_id)
        edb.update_user_password(user_id, new_password)
    _audit_user_action(current, "user_password_reset", target, f"重置用户 {target['username']} 的密码")
    return {
        "success": True,
        "user_id": user_id,
        **({"operation_id": result["operation_id"]} if ready else {}),
    }


@router.put("/api/users/{user_id}/role")
async def update_user_role(user_id: str, request: Request):
    ready = _role_auth_ready()
    current = _require_ready_principal(request) if ready else _require_admin(request)
    if ready:
        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Invalid role update request")
        try:
            user_governance.deny_online_role_change(
                actor_user_id=current["user_id"],
                expected_actor_auth_version=current["auth_version"],
                target_user_id=user_id,
                role_field_present="role" in body,
                requested_role=body.get("role"),
                is_admin_field_present="is_admin" in body,
                requested_is_admin=body.get("is_admin"),
            )
        except user_governance.UserGovernanceError as exc:
            _raise_governance_http(exc)
    if user_id == current["user_id"]:
        raise HTTPException(status_code=400, detail="不能修改自己的权限")
    target = edb.get_user_by_id_any_status(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    body = await request.json()
    is_admin = bool(body.get("is_admin", False))
    edb.update_user_role(user_id, is_admin, updated_by=current["user_id"])
    _audit_user_action(
        current,
        "user_role_updated",
        target,
        f"{'授予' if is_admin else '撤销'}用户 {target['username']} 的管理员权限",
        {"is_admin": is_admin},
    )
    return {"success": True, "user_id": user_id, "is_admin": is_admin}


@router.put("/api/users/{user_id}/active")
async def update_user_active(user_id: str, request: Request):
    ready = _role_auth_ready()
    current = _require_ready_principal(request) if ready else _require_admin(request)
    body = await request.json()
    if "is_active" not in body or not isinstance(body.get("is_active"), bool):
        raise HTTPException(status_code=400, detail="is_active 必须是布尔值")
    is_active = body["is_active"]
    if ready:
        try:
            result = user_governance.set_user_active(
                actor_user_id=current["user_id"],
                expected_actor_auth_version=current["auth_version"],
                target_user_id=user_id,
                is_active=is_active,
                reason=body.get("reason"),
            )
        except user_governance.UserGovernanceError as exc:
            _raise_governance_http(exc)
        target = result["user"]
        action = "user_enabled" if is_active else "user_disabled"
        summary = f"{'启用' if is_active else '禁用'}用户 {target['username']}"
        _audit_user_action(current, action, target, summary, {"is_active": is_active})
        return {
            "success": True,
            "user_id": user_id,
            "is_active": is_active,
            "status": "enabled" if is_active else "disabled",
            "operation_id": result["operation_id"],
        }

    target = _target_user_or_404(user_id)
    if user_id == current["user_id"] and not is_active:
        raise HTTPException(status_code=400, detail="不能禁用自己")

    if not is_active:
        _ensure_not_last_active_admin(target, "disable")

    edb.set_user_active(user_id, is_active)
    action = "user_enabled" if is_active else "user_disabled"
    summary = f"{'启用' if is_active else '禁用'}用户 {target['username']}"
    _audit_user_action(current, action, target, summary, {"is_active": is_active})
    return {
        "success": True,
        "user_id": user_id,
        "is_active": is_active,
        "status": "enabled" if is_active else "disabled",
    }


@router.put("/api/users/{user_id}/profile")
async def update_user_profile(user_id: str, request: Request):
    ready = _role_auth_ready()
    current = _require_ready_principal(request) if ready else _require_admin(request)
    body = await request.json()
    display_name = (body.get("display_name") or "").strip()
    if ready:
        try:
            current_target = user_governance.update_user_profile(
                actor_user_id=current["user_id"],
                expected_actor_auth_version=current["auth_version"],
                target_user_id=user_id,
                display_name=display_name,
            )
        except user_governance.UserGovernanceError as exc:
            _raise_governance_http(exc)
        updated = current_target["user"]
        target = updated
        display_name = updated["display_name"]
    else:
        target = _target_user_or_404(user_id)
        display_name = display_name or target["username"]
        edb.update_user_profile(user_id, display_name)
        updated = {**target, "display_name": display_name}
    _audit_user_action(
        current,
        "user_profile_updated",
        updated,
        f"修改用户 {target['username']} 的展示名",
        {"display_name": display_name},
    )
    return {"success": True, "user_id": user_id, "display_name": display_name}


@router.delete("/api/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    ready = _role_auth_ready()
    current = _require_ready_principal(request) if ready else _require_admin(request)
    if ready:
        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="confirm_username is required")
        try:
            result = user_governance.soft_delete_user(
                actor_user_id=current["user_id"],
                expected_actor_auth_version=current["auth_version"],
                target_user_id=user_id,
                confirm_username=body.get("confirm_username"),
                reason=body.get("reason"),
            )
        except user_governance.UserGovernanceError as exc:
            _raise_governance_http(exc)
        target = result["user"]
        previous_is_active = bool(result["state_changed"])
        _audit_user_action(
            current,
            "user_deleted",
            target,
            f"删除/软禁用用户 {target['username']}",
            {
                "is_active": False,
                "soft_delete": True,
                "previous_is_active": previous_is_active,
                "reason": body.get("reason"),
                "owned_data_retained": True,
                "runtime_files_deleted": False,
                "owner_mappings_cleaned": False,
            },
        )
        return {
            "success": True,
            "user_id": user_id,
            "is_active": False,
            "status": "disabled",
            "soft_deleted": True,
            "operation_id": result["operation_id"],
        }

    if user_id == current["user_id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    target = edb.get_user_by_id_any_status(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    _ensure_not_last_active_admin(target, "soft delete")
    confirmation = await _confirmed_user_action_body(request, target)
    previous_is_active = bool(target.get("is_active"))
    edb.set_user_active(user_id, False)
    _audit_user_action(
        current,
        "user_deleted",
        target,
        f"删除/软禁用用户 {target['username']}",
        {
            "is_active": False,
            "soft_delete": True,
            "previous_is_active": previous_is_active,
            "reason": confirmation["reason"],
            "owned_data_retained": True,
            "runtime_files_deleted": False,
            "owner_mappings_cleaned": False,
        },
    )
    return {
        "success": True,
        "user_id": user_id,
        "is_active": False,
        "status": "disabled",
        "soft_deleted": True,
    }


# ── 画布归属查询（管理员专用）────────────────────────────

@router.get("/api/feature-flags")
async def list_feature_flags(request: Request):
    _require_admin(request)
    return {"features": edb.list_feature_flags()}


@router.put("/api/feature-flags/{feature_key}")
async def update_feature_flag(feature_key: str, request: Request):
    current = _require_admin(request)
    body = await request.json()
    if "enabled" not in body or not isinstance(body.get("enabled"), bool):
        raise HTTPException(status_code=400, detail="enabled 必须是布尔值")
    try:
        old, new = edb.set_feature_flag(feature_key, bool(body["enabled"]), current["user_id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit_permission_action(
        current,
        "feature_flag_changed",
        {
            "feature_key": new["feature_key"],
            "old_value": old.get("enabled"),
            "new_value": new.get("enabled"),
        },
    )
    return {"success": True, "feature": new}


@router.get("/api/users/{user_id}/feature-overrides")
async def list_user_feature_overrides(user_id: str, request: Request):
    _require_admin(request)
    target = _target_user_or_404(user_id)
    override_map = {
        item["feature_key"]: item
        for item in edb.get_user_feature_overrides(user_id)
    }
    actor = {
        "user_id": target["id"],
        "username": target.get("username", ""),
        "is_admin": bool(target.get("is_admin")),
    }
    features = []
    for feature in edb.list_feature_flags():
        key = feature["feature_key"]
        override = override_map.get(key)
        effective = edb.get_effective_feature_value(actor, key)
        features.append(
            {
                "feature_key": key,
                "title": feature.get("title", key),
                "description": feature.get("description", ""),
                "global_enabled": feature.get("enabled"),
                "default_enabled": feature.get("default_enabled"),
                "mode": override.get("mode") if override else "inherit",
                "effective_allowed": effective.get("allowed"),
                "effective_source": effective.get("source"),
                "updated_by": override.get("updated_by") if override else None,
                "updated_at": override.get("updated_at") if override else None,
            }
        )
    return {
        "user": {
            "id": target["id"],
            "username": target["username"],
            "display_name": target.get("display_name", ""),
            "is_admin": bool(target.get("is_admin")),
            "is_active": bool(target.get("is_active")),
        },
        "features": features,
    }


@router.put("/api/users/{user_id}/feature-overrides/{feature_key}")
async def update_user_feature_override(user_id: str, feature_key: str, request: Request):
    current = _require_admin(request)
    target = _target_user_or_404(user_id)
    body = await request.json()
    mode = str(body.get("mode") or "").strip().lower()
    try:
        old, new = edb.set_user_feature_override(user_id, feature_key, mode, current["user_id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit_permission_action(
        current,
        "user_feature_override_changed",
        {
            "feature_key": feature_key,
            "target_user_id": target["id"],
            "target_username": target["username"],
            "old_value": old.get("mode") if old else "inherit",
            "new_value": new.get("mode") if new else "inherit",
            "mode": new.get("mode") if new else "inherit",
        },
    )
    return {"success": True, "override": new, "mode": new.get("mode") if new else "inherit"}


@router.delete("/api/users/{user_id}/feature-overrides/{feature_key}")
async def delete_user_feature_override(user_id: str, feature_key: str, request: Request):
    current = _require_admin(request)
    target = _target_user_or_404(user_id)
    try:
        old, new = edb.clear_user_feature_override(user_id, feature_key, current["user_id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit_permission_action(
        current,
        "user_feature_override_changed",
        {
            "feature_key": feature_key,
            "target_user_id": target["id"],
            "target_username": target["username"],
            "old_value": old.get("mode") if old else "inherit",
            "new_value": "inherit",
            "mode": "inherit",
        },
    )
    return {"success": True, "override": new, "mode": "inherit"}


@router.post("/api/users/{user_id}/purge-overrides")
async def purge_user_feature_overrides(user_id: str, request: Request):
    current = _require_admin(request)
    target = _target_user_or_404(user_id)
    confirmation = await _confirmed_user_action_body(request, target)
    old = edb.clear_all_user_feature_overrides(user_id, current["user_id"])
    old_values = [
        {"feature_key": item.get("feature_key"), "mode": item.get("mode")}
        for item in old
    ]
    old_feature_keys = [item.get("feature_key") for item in old]
    _audit_permission_action(
        current,
        "user_feature_overrides_cleared",
        {
            "target_user_id": target["id"],
            "target_username": target["username"],
            "old_count": len(old),
            "cleared_count": len(old),
            "deleted_count": len(old),
            "old_feature_keys": old_feature_keys,
            "old_values": old_values,
            "reason": confirmation["reason"],
        },
    )
    return {
        "success": True,
        "user_id": user_id,
        "cleared_count": len(old),
    }


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
    current = _require_admin(request)
    body = await request.json()
    user_id = (body.get("user_id") or "").strip()
    target_project_id = (body.get("target_project_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id 不能为空")
    # 验证目标用户存在
    target = edb.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    old_owner = edb.get_canvas_owner(canvas_id)
    old_project = edb.get_canvas_project(canvas_id)
    new_project = old_project
    project_changed = False
    if target_project_id:
        if target_project_id != edb.DEFAULT_PROJECT_ID:
            if not edb.project_exists(target_project_id):
                raise HTTPException(status_code=404, detail="目标项目不存在")
            if edb.get_project_owner(target_project_id) != user_id:
                raise HTTPException(status_code=400, detail="目标项目不属于目标用户")
        project_changed, _ = edb.set_canvas_project(canvas_id, target_project_id)
        new_project = target_project_id
    elif old_project and old_project != edb.DEFAULT_PROJECT_ID:
        project_owner = edb.get_project_owner(old_project)
        if project_owner != user_id:
            project_changed, _ = edb.set_canvas_project(canvas_id, edb.DEFAULT_PROJECT_ID)
            new_project = edb.DEFAULT_PROJECT_ID
    edb.assign_canvas_owner(canvas_id, user_id)
    edb.log_action(
        current["user_id"],
        "canvas_assigned",
        json.dumps({
            "canvas_id": canvas_id,
            "old_owner": old_owner,
            "target_user_id": user_id,
            "target_username": target.get("username"),
            "old_project": old_project,
            "new_project": new_project,
            "project_normalized": bool(project_changed),
        }, ensure_ascii=False),
    )
    return {"success": True, "canvas_id": canvas_id, "user_id": user_id, "project": new_project}


# ── 项目归属查询（管理员专用）────────────────────────────

@router.get("/api/project-owners")
async def project_owners(request: Request):
    """返回 {project_id: {user_id, username}} 的全量映射；默认项目是每用户虚拟根。"""
    _require_admin(request)
    owner_map = edb.get_all_project_owner_map()
    users = {u["id"]: u for u in edb.list_users()}
    result = {}
    for project_id, uid in owner_map.items():
        user = users.get(uid, {})
        result[project_id] = {
            "user_id": uid,
            "username": user.get("username", "未知"),
            "display_name": user.get("display_name", ""),
        }
    return result


@router.put("/api/projects/{project_id}/owner")
async def assign_project_owner(project_id: str, request: Request):
    """管理员手动分配常规项目归属；全局默认项目不可分配给单一用户。"""
    current = _require_admin(request)
    if project_id == edb.DEFAULT_PROJECT_ID:
        raise HTTPException(status_code=400, detail="默认项目是每位用户的虚拟根，不能分配给单一用户")
    if not edb.project_exists(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    body = await request.json()
    user_id = (body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id 不能为空")
    target = edb.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    old_owner = edb.get_project_owner(project_id)
    edb.set_project_owner(project_id, user_id)
    synced_canvases = []
    for canvas_id in edb.get_canvas_ids_by_project(project_id):
        old_canvas_owner = edb.get_canvas_owner(canvas_id)
        if old_canvas_owner == user_id:
            continue
        edb.set_canvas_owner(canvas_id, user_id)
        synced_canvases.append({
            "canvas_id": canvas_id,
            "old_owner": old_canvas_owner,
            "new_owner": user_id,
        })
    edb.log_action(
        current["user_id"],
        "project_assigned",
        json.dumps({
            "project_id": project_id,
            "old_owner": old_owner,
            "target_user_id": user_id,
            "target_username": target.get("username"),
            "synced_canvas_count": len(synced_canvases),
            "synced_canvases": synced_canvases[:50],
        }, ensure_ascii=False),
    )
    return {
        "success": True,
        "project_id": project_id,
        "user_id": user_id,
        "synced_canvas_count": len(synced_canvases),
    }


# ── 对话归属查询（管理员专用）────────────────────────────

@router.get("/api/conversation-owners")
async def conversation_owners(request: Request):
    """返回上游对话文件和企业归属状态，包含未归属历史对话。"""
    _require_admin(request)
    owner_map = edb.get_all_conversation_owner_map()
    users = {u["id"]: u for u in edb.list_users()}

    result = []
    for record in edb.list_conversation_records():
        owner_id = owner_map.get(record["id"])
        owner = users.get(owner_id or "", {})
        file_user = users.get(record.get("file_user_id") or "", {})
        result.append({
            "id": record["id"],
            "title": record.get("title") or "新对话",
            "created_at": record.get("created_at") or 0,
            "updated_at": record.get("updated_at") or 0,
            "message_count": record.get("message_count") or 0,
            "file_user_id": record.get("file_user_id") or "",
            "file_username": file_user.get("username", record.get("file_user_id") or ""),
            "user_id": owner_id,
            "username": owner.get("username", "未分配"),
            "display_name": owner.get("display_name", ""),
            "unowned": owner_id is None,
        })
    return {"conversations": result}


@router.put("/api/conversations/{conversation_id}/owner")
async def assign_conversation_owner(conversation_id: str, request: Request):
    """管理员手动分配对话归属。"""
    current = _require_admin(request)
    body = await request.json()
    user_id = (body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id 不能为空")
    target = edb.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not edb.get_conversation_file_owner(conversation_id):
        raise HTTPException(status_code=404, detail="对话不存在")

    edb.assign_conversation_owner(conversation_id, user_id)
    edb.log_action(
        current["user_id"],
        "conversation_assigned",
        json.dumps({
            "conversation_id": conversation_id,
            "target_user_id": user_id,
            "target_username": target.get("username"),
        }, ensure_ascii=False),
    )
    return {"success": True, "conversation_id": conversation_id, "user_id": user_id}


# ── 历史记录归属迁移（管理员专用）──────────────────────────

@router.put("/api/history/{history_id}/owner")
async def assign_history_owner(history_id: str, request: Request):
    """管理员手动迁移生成历史归属；不改写上游 history.json。"""
    current = _require_admin(request)
    body = await request.json()
    user_id = (body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id 不能为空")
    target = edb.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    from enterprise import interceptors

    record = interceptors.find_history_record_by_id(history_id)
    if not record:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    old_owner = edb.get_history_owner(history_id)
    edb.set_history_owner(
        history_id,
        user_id,
        str(record.get("type") or ""),
        interceptors._history_record_primary_resource(record),
        interceptors._history_record_task_id(record),
        "admin_assign",
    )
    interceptors.record_history_resources_for_user(user_id, record, f"history:{history_id}:admin_assign")
    edb.log_action(
        current["user_id"],
        "history_assigned",
        json.dumps({
            "history_id": history_id,
            "old_owner": old_owner,
            "target_user_id": user_id,
            "target_username": target.get("username"),
            "history_type": record.get("type"),
            "timestamp": record.get("timestamp"),
        }, ensure_ascii=False),
    )
    return {"success": True, "history_id": history_id, "user_id": user_id}


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

    ready = _role_auth_ready()
    if ready:
        user = _require_ready_principal(request)
        try:
            result = user_governance.change_own_password(
                actor_user_id=user["user_id"],
                expected_actor_auth_version=user["auth_version"],
                old_password=old_password,
                new_password=new_password,
            )
        except user_governance.UserGovernanceError as exc:
            _raise_governance_http(exc)
        edb.log_action(user["user_id"], "password_changed", None)
        return {"success": True, "operation_id": result["operation_id"]}

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
