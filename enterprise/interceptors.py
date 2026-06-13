"""
企业层拦截器 - 请求前置检查 & 响应后置过滤
核心逻辑：实现用户数据隔离，不修改任何上游文件

数据隔离策略：
  - 画布（canvases）：通过 user_canvas_map 表记录归属关系
  - 对话（conversations）：通过 user_conversation_map 表记录归属关系
  - 管理员可查看所有数据（is_admin=True 时跳过过滤）
"""
import json
from typing import Optional, Tuple

from fastapi.responses import JSONResponse

from enterprise import db as edb
from enterprise.config import (
    ENTERPRISE_HIDE_UPSTREAM_AUTHOR,
    ENTERPRISE_REPO_URL,
    ENTERPRISE_UPDATE_ENABLED,
)


# ── 不需要过滤的静态资源后缀 ──────────────────────────────
_STATIC_EXTS = {
    ".js", ".css", ".ico", ".png", ".jpg", ".jpeg",
    ".gif", ".svg", ".woff", ".woff2", ".ttf", ".eot", ".map",
    ".webp", ".mp4", ".webm",
}

# ── 需要流式透传（不缓冲）的路径前缀 ──────────────────────
_STREAM_PREFIXES = (
    "api/view",
    "api/download-output",
    "output/",
    "assets/",
)


def is_static_asset(path: str) -> bool:
    from pathlib import PurePosixPath
    suffix = PurePosixPath(path).suffix.lower()
    return suffix in _STATIC_EXTS


def is_stream_path(path: str) -> bool:
    return any(path.startswith(p) for p in _STREAM_PREFIXES)


# ── 前置拦截：访问控制 ────────────────────────────────────

async def pre_process(
    path: str,
    method: str,
    user: dict,
) -> Optional[JSONResponse]:
    """
    返回 None 表示放行；返回 JSONResponse 表示拒绝并直接响应。
    """
    user_id = user["user_id"]
    is_admin = bool(user.get("is_admin"))

    # ── 上游更新接口：企业版只允许管理员操作 ─────────────────
    # 这些接口会写入 main.py / VERSION / static/，普通成员不能触发。
    update_paths = {
        "api/check-update",
        "api/update-connectivity",
        "api/update-backups",
        "api/update-from-github",
        "api/update-rollback",
    }
    if path in update_paths or path.startswith("api/update-"):
        if not ENTERPRISE_UPDATE_ENABLED:
            return JSONResponse(
                {"error": "企业版更新入口已关闭", "code": 403},
                status_code=403,
            )
        if is_admin:
            return None
        return JSONResponse(
            {"error": "需要管理员权限才能执行项目更新", "code": 403},
            status_code=403,
        )

    # 管理员直接放行其他请求
    if is_admin:
        return None

    # ── 单个画布的访问控制 ────────────────────────────────
    # 路径：api/canvases/{canvas_id}  且 canvas_id != 'trash'
    parts = path.split("/")
    if (
        len(parts) >= 3
        and parts[0] == "api"
        and parts[1] == "canvases"
        and parts[2] not in ("", "trash")
    ):
        canvas_id = parts[2]
        owner = edb.get_canvas_owner(canvas_id)
        if owner is None:
            # 尚未记录归属（可能是旧数据），临时允许但不记录
            pass
        elif owner != user_id:
            return JSONResponse(
                {"error": "无权限访问该画布", "code": 403},
                status_code=403,
            )

    # ── 单个对话的访问控制 ────────────────────────────────
    # 路径：api/conversations/{conversation_id}
    if (
        len(parts) >= 3
        and parts[0] == "api"
        and parts[1] == "conversations"
        and parts[2] != ""
    ):
        conv_id = parts[2]
        user_conv_ids = edb.get_user_conversation_ids(user_id)
        if user_conv_ids and conv_id not in user_conv_ids:
            return JSONResponse(
                {"error": "无权限访问该对话", "code": 403},
                status_code=403,
            )

    return None


# ── 后置拦截：响应过滤 & 数据记录 ────────────────────────

async def post_process(
    path: str,
    method: str,
    status_code: int,
    response_body: bytes,
    content_type: str,
    user: dict,
) -> Tuple[bytes, dict]:
    """
    返回 (处理后的 body bytes, 需要覆盖的响应头 dict)
    """
    user_id = user["user_id"]
    is_admin = bool(user.get("is_admin"))

    # 非 JSON 响应直接透传
    if "application/json" not in content_type:
        return response_body, {}

    # 解析 JSON
    try:
        data = json.loads(response_body)
    except Exception:
        return response_body, {}

    modified = False

    # ── 企业首页项目信息治理 ───────────────────────────────
    # 上游 app-info 的 repo_url 指向上游仓库；企业版首页应默认指向企业仓库。
    # 普通用户不应获得上游更新源信息，避免前端兜底检测显示上游更新入口。
    if path == "api/app-info" and isinstance(data, dict):
        data["repo_url"] = ENTERPRISE_REPO_URL
        data["enterprise"] = {
            "repo_url": ENTERPRISE_REPO_URL,
            "update_enabled": bool(ENTERPRISE_UPDATE_ENABLED and is_admin),
            "hide_upstream_author": bool(ENTERPRISE_HIDE_UPSTREAM_AUTHOR or not is_admin),
            "is_admin": is_admin,
        }
        if not is_admin:
            data["version_url"] = ""
            data["tree_url"] = ""
            data["sources"] = {}
            data["update_notes"] = {}
        modified = True

    # ── 记录新画布的归属 ──────────────────────────────────
    # POST /api/canvases → {"canvas": {"id": "..."}}
    if path == "api/canvases" and method == "POST" and status_code in (200, 201):
        canvas_obj = data.get("canvas") if isinstance(data, dict) else None
        if isinstance(canvas_obj, dict) and "id" in canvas_obj:
            edb.record_canvas_owner(user_id, canvas_obj["id"])
            edb.log_action(user_id, "create_canvas", canvas_obj["id"])

    # ── 过滤画布列表 ──────────────────────────────────────
    # GET /api/canvases → {"canvases": [...]}
    elif path == "api/canvases" and method == "GET":
        canvas_list = data.get("canvases") if isinstance(data, dict) else None
        if isinstance(canvas_list, list) and not is_admin:
            owned = edb.get_user_canvas_ids(user_id)
            filtered = [c for c in canvas_list if c.get("id") in owned]
            if len(filtered) != len(canvas_list):
                data["canvases"] = filtered
                modified = True

    # ── 过滤回收站画布列表 ────────────────────────────────
    # GET /api/canvases/trash → {"canvases": [...], "retention_days": 30}
    elif path == "api/canvases/trash" and method == "GET":
        canvas_list = data.get("canvases") if isinstance(data, dict) else None
        if isinstance(canvas_list, list) and not is_admin:
            owned = edb.get_user_canvas_ids(user_id)
            filtered = [c for c in canvas_list if c.get("id") in owned]
            if len(filtered) != len(canvas_list):
                data["canvases"] = filtered
                modified = True

    # ── 记录新对话的归属 ──────────────────────────────────
    # POST /api/conversations → {"conversation": {"id": "..."}}
    elif path == "api/conversations" and method == "POST" and status_code in (200, 201):
        conv_obj = data.get("conversation") if isinstance(data, dict) else None
        if isinstance(conv_obj, dict) and "id" in conv_obj:
            edb.record_conversation_owner(user_id, conv_obj["id"])

    # ── 过滤对话列表 ──────────────────────────────────────
    # GET /api/conversations → {"user_id": "...", "conversations": [...]}
    elif path == "api/conversations" and method == "GET":
        conv_list = data.get("conversations") if isinstance(data, dict) else None
        if isinstance(conv_list, list) and not is_admin:
            owned = edb.get_user_conversation_ids(user_id)
            filtered = [c for c in conv_list if c.get("id") in owned]
            if len(filtered) != len(conv_list):
                data["conversations"] = filtered
                modified = True

    if modified:
        new_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return new_body, {"content-length": str(len(new_body))}

    return response_body, {}
