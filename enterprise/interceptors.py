"""
企业层拦截器 - 请求前置检查 & 响应后置过滤
核心逻辑：实现用户数据隔离，不修改任何上游文件

数据隔离策略：
  - 画布（canvases）：通过 user_canvas_map 表记录归属关系
  - 对话（conversations）：通过 user_conversation_map 表记录归属关系
  - 本地资源（/assets、/output、/api/view、/api/download-output）：
    优先使用 user_resource_map，必要时回溯画布/对话引用
  - 管理员可查看所有数据（is_admin=True 时跳过过滤）
  - 普通用户对无归属/未知归属默认拒绝
"""
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from fastapi.responses import JSONResponse

from enterprise import db as edb
from enterprise.config import (
    ENTERPRISE_HIDE_UPSTREAM_AUTHOR,
    ENTERPRISE_REPO_URL,
    ENTERPRISE_UPDATE_ENABLED,
    ROOT_DIR,
)


# ── 不需要过滤的静态资源后缀 ──────────────────────────────
_STATIC_EXTS = {
    ".js", ".css", ".ico", ".png", ".jpg", ".jpeg",
    ".gif", ".svg", ".woff", ".woff2", ".ttf", ".eot", ".map",
    ".webp", ".mp4", ".webm",
}

# ── 需要先鉴权再透传（不缓冲）的路径前缀 ──────────────────
_STREAM_PREFIXES = (
    "api/view",
    "api/download-output",
    "api/media-preview",
    "output/",
    "assets/",
)

_PUBLIC_ASSET_PREFIXES = (
    "/assets/images/",
)

_PROTECTED_LOCAL_RESOURCE_PREFIXES = (
    "/assets/input/",
    "/assets/output/",
    "/assets/uploads/",
    "/assets/library/",
    "/output/",
)

_CANVAS_DATA_DIR = Path(ROOT_DIR) / "data" / "canvases"
_CONVERSATION_DATA_DIR = Path(ROOT_DIR) / "data" / "conversations"


def is_static_asset(path: str) -> bool:
    suffix = PurePosixPath(path).suffix.lower()
    return suffix in _STATIC_EXTS


def is_public_asset_path(path: str) -> bool:
    normalized = "/" + path.lstrip("/")
    return any(normalized.startswith(prefix) for prefix in _PUBLIC_ASSET_PREFIXES)


def is_stream_path(path: str) -> bool:
    return not is_public_asset_path(path) and any(path.startswith(p) for p in _STREAM_PREFIXES)


# ── 权限判断基础函数 ──────────────────────────────────────

def _is_admin(user: dict) -> bool:
    return bool(user.get("is_admin"))


def _user_id(user: dict) -> str:
    return str(user.get("user_id") or "")


def _deny_not_found(message: str = "资源不存在或无权限访问") -> JSONResponse:
    return JSONResponse(
        {"error": message, "code": 404},
        status_code=404,
    )


def _deny_forbidden(message: str = "无权限访问") -> JSONResponse:
    return JSONResponse(
        {"error": message, "code": 403},
        status_code=403,
    )


def can_access_canvas(user: dict, canvas_id: str) -> bool:
    """管理员可访问全部；普通用户只允许访问归属自己的画布。"""
    if _is_admin(user):
        return True
    owner = edb.get_canvas_owner(canvas_id)
    return bool(owner and owner == _user_id(user))


def can_access_conversation(user: dict, conversation_id: str) -> bool:
    """管理员可访问全部；普通用户只允许访问归属自己的对话。"""
    if _is_admin(user):
        return True
    owner = edb.get_conversation_owner(conversation_id)
    return bool(owner and owner == _user_id(user))


def _query_get(query_params: Optional[Mapping[str, Any]], key: str) -> str:
    if not query_params:
        return ""
    value = query_params.get(key)
    if value is None:
        return ""
    return str(value)


def _json_from_body(body: bytes | None) -> Any:
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _clean_relative_path(value: str) -> str:
    parts = []
    for part in str(value or "").replace("\\", "/").split("/"):
        part = unquote(part).strip()
        if not part or part in {".", ".."}:
            continue
        parts.append(os.path.basename(part))
    return "/".join(parts)


def _resource_from_api_view(query: Mapping[str, Any] | dict[str, Any]) -> str:
    filename = os.path.basename(unquote(str(query.get("filename") or "")))
    media_type = str(query.get("type") or "input").strip().lower()
    subfolder = _clean_relative_path(str(query.get("subfolder") or ""))
    if not filename or media_type not in {"input", "output"}:
        return ""
    if subfolder:
        return f"/assets/{media_type}/{subfolder}/{filename}"
    return f"/assets/{media_type}/{filename}"


def normalize_resource_url(value: str) -> str:
    """将本地资源 URL 规范化到 /assets/... 或 /output/...，远程 URL 返回空。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("api/"):
        text = "/" + text
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"}:
        return ""
    path = unquote(parsed.path or text.split("?", 1)[0])
    query = parse_qs(parsed.query or "")
    simple_query = {key: values[-1] if values else "" for key, values in query.items()}

    if path == "/api/download-output" or path == "/api/media-preview":
        return normalize_resource_url(simple_query.get("url", ""))
    if path == "/api/view":
        return _resource_from_api_view(simple_query)
    if path.startswith("/assets/") or path.startswith("/output/"):
        clean = "/" + "/".join(
            part for part in path.replace("\\", "/").split("/") if part not in {"", ".", ".."}
        )
        return clean
    return ""


def _is_public_resource(resource_url: str) -> bool:
    return any(resource_url.startswith(prefix) for prefix in _PUBLIC_ASSET_PREFIXES)


def _is_protected_resource(resource_url: str) -> bool:
    if not resource_url or _is_public_resource(resource_url):
        return False
    return any(resource_url.startswith(prefix) for prefix in _PROTECTED_LOCAL_RESOURCE_PREFIXES)


def _extract_local_resource_urls(value: Any, found: Optional[set[str]] = None) -> set[str]:
    found = found if found is not None else set()
    if isinstance(value, str):
        resource_url = normalize_resource_url(value)
        if _is_protected_resource(resource_url):
            found.add(resource_url)
    elif isinstance(value, dict):
        for child in value.values():
            _extract_local_resource_urls(child, found)
    elif isinstance(value, list):
        for child in value:
            _extract_local_resource_urls(child, found)
    return found


def _load_json_file(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _canvas_ids_for_resource(resource_url: str) -> set[str]:
    canvas_ids: set[str] = set()
    if not _CANVAS_DATA_DIR.is_dir():
        return canvas_ids
    for path in _CANVAS_DATA_DIR.glob("*.json"):
        data = _load_json_file(path)
        if not isinstance(data, dict):
            continue
        if resource_url in _extract_local_resource_urls(data):
            canvas_id = str(data.get("id") or path.stem)
            if canvas_id:
                canvas_ids.add(canvas_id)
    return canvas_ids


def _conversation_ids_for_resource(resource_url: str) -> set[str]:
    conversation_ids: set[str] = set()
    if not _CONVERSATION_DATA_DIR.is_dir():
        return conversation_ids
    for path in _CONVERSATION_DATA_DIR.glob("*/*.json"):
        data = _load_json_file(path)
        if not isinstance(data, dict):
            continue
        if resource_url in _extract_local_resource_urls(data):
            conversation_id = str(data.get("id") or path.stem)
            if conversation_id:
                conversation_ids.add(conversation_id)
    return conversation_ids


def can_access_resource(user: dict, resource_url: str) -> bool:
    """判断本地资源是否属于当前用户可访问的画布/对话/资源归属。"""
    normalized = normalize_resource_url(resource_url)
    if not _is_protected_resource(normalized):
        return True
    if _is_admin(user):
        return True

    user_id = _user_id(user)
    owner = edb.get_resource_owner(normalized)
    if owner:
        return owner == user_id

    for canvas_id in _canvas_ids_for_resource(normalized):
        if edb.get_canvas_owner(canvas_id) == user_id:
            edb.record_resource_owner(user_id, normalized, "derived_from_canvas")
            return True

    for conversation_id in _conversation_ids_for_resource(normalized):
        if edb.get_conversation_owner(conversation_id) == user_id:
            edb.record_resource_owner(user_id, normalized, "derived_from_conversation")
            return True

    return False


def _resource_urls_from_request(
    path: str,
    method: str,
    query_params: Optional[Mapping[str, Any]],
    body: bytes | None,
) -> set[str]:
    urls: set[str] = set()
    normalized_path = "/" + path.lstrip("/")

    if path.startswith("assets/") or path.startswith("output/"):
        resource_url = normalize_resource_url(normalized_path)
        if _is_protected_resource(resource_url):
            urls.add(resource_url)
    elif path == "api/download-output" or path == "api/media-preview":
        resource_url = normalize_resource_url(_query_get(query_params, "url"))
        if _is_protected_resource(resource_url):
            urls.add(resource_url)
    elif path == "api/view":
        query = {
            "filename": _query_get(query_params, "filename"),
            "type": _query_get(query_params, "type"),
            "subfolder": _query_get(query_params, "subfolder"),
        }
        resource_url = _resource_from_api_view(query)
        if _is_protected_resource(resource_url):
            urls.add(resource_url)

    if method.upper() in {"POST", "PUT", "PATCH"} and path.startswith("api/"):
        data = _json_from_body(body)
        if data is not None:
            urls.update(_extract_local_resource_urls(data))

    return urls


def _conversation_id_from_path(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "conversations" and parts[2]:
        return parts[2]
    return ""


def _canvas_id_from_path(path: str) -> str:
    parts = path.split("/")
    if (
        len(parts) >= 3
        and parts[0] == "api"
        and parts[1] == "canvases"
        and parts[2] not in {"", "trash"}
    ):
        return parts[2]
    return ""


def _conversation_id_from_body(path: str, body: bytes | None) -> str:
    if path not in {"api/chat", "api/chat/agent", "api/chat/stream"}:
        return ""
    data = _json_from_body(body)
    if not isinstance(data, dict):
        return ""
    return str(data.get("conversation_id") or "").strip()


def upstream_conversation_user_id(path: str, body: bytes | None, user: dict) -> Optional[str]:
    """返回访问单个对话时应传给上游的真实文件目录 user_id。"""
    conversation_id = _conversation_id_from_path(path) or _conversation_id_from_body(path, body)
    if not conversation_id:
        return None
    if not can_access_conversation(user, conversation_id):
        return None
    return edb.get_conversation_file_owner(conversation_id) or edb.get_conversation_owner(conversation_id)


# ── 前置拦截：访问控制 ────────────────────────────────────

async def pre_process(
    path: str,
    method: str,
    user: dict,
    query_params: Optional[Mapping[str, Any]] = None,
    body: bytes | None = None,
) -> Optional[JSONResponse]:
    """
    返回 None 表示放行；返回 JSONResponse 表示拒绝并直接响应。
    """
    is_admin = _is_admin(user)

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
            return _deny_forbidden("企业版更新入口已关闭")
        if is_admin:
            return None
        return _deny_forbidden("需要管理员权限才能执行项目更新")

    canvas_id = _canvas_id_from_path(path)
    if canvas_id and not can_access_canvas(user, canvas_id):
        return _deny_not_found("画布不存在或无权限访问")

    conversation_id = _conversation_id_from_path(path) or _conversation_id_from_body(path, body)
    if conversation_id and not can_access_conversation(user, conversation_id):
        return _deny_not_found("对话不存在或无权限访问")

    for resource_url in _resource_urls_from_request(path, method, query_params, body):
        if not can_access_resource(user, resource_url):
            return _deny_not_found("资源不存在或无权限访问")

    return None


# ── 后置拦截：响应过滤 & 数据记录 ────────────────────────

def filter_canvas_list(user: dict, data: dict) -> bool:
    canvas_list = data.get("canvases") if isinstance(data, dict) else None
    if not isinstance(canvas_list, list) or _is_admin(user):
        return False
    owned = edb.get_user_canvas_ids(_user_id(user))
    filtered = [c for c in canvas_list if c.get("id") in owned]
    if len(filtered) == len(canvas_list):
        return False
    data["canvases"] = filtered
    return True


def _user_lookup() -> dict[str, dict]:
    return {u["id"]: u for u in edb.list_users()}


def _conversation_record_for_response(record: dict, owner_map: dict, users: dict) -> dict:
    owner_id = owner_map.get(record["id"])
    owner_user = users.get(owner_id or "", {})
    item = {
        "id": record["id"],
        "title": record.get("title") or "新对话",
        "created_at": record.get("created_at") or 0,
        "updated_at": record.get("updated_at") or 0,
        "messages": [],
        "message_count": record.get("message_count") or 0,
        "enterprise_owner_id": owner_id,
        "enterprise_owner_username": owner_user.get("username", ""),
        "enterprise_owner_display_name": owner_user.get("display_name", ""),
        "enterprise_unowned": owner_id is None,
    }
    return item


def conversation_list_for_user(user: dict) -> list[dict]:
    owner_map = edb.get_all_conversation_owner_map()
    users = _user_lookup()
    records = edb.list_conversation_records()
    if _is_admin(user):
        return [_conversation_record_for_response(record, owner_map, users) for record in records]
    user_id = _user_id(user)
    return [
        _conversation_record_for_response(record, owner_map, users)
        for record in records
        if owner_map.get(record["id"]) == user_id
    ]


def filter_conversation_list(user: dict, data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    data["user_id"] = _user_id(user)
    data["conversations"] = conversation_list_for_user(user)
    return True


def _filter_resource_item_list(user: dict, items: list) -> tuple[list, bool]:
    filtered = []
    changed = False
    for item in items:
        if isinstance(item, dict):
            url = item.get("url") or item.get("src") or item.get("path") or item.get("output")
            resource_url = normalize_resource_url(str(url or ""))
            if _is_protected_resource(resource_url) and not can_access_resource(user, resource_url):
                changed = True
                continue
        filtered.append(item)
    return filtered, changed


def _recount_canvas_asset_categories(data: dict) -> None:
    items = data.get("items") if isinstance(data.get("items"), list) else []
    canvases = data.get("canvases") if isinstance(data.get("canvases"), list) else []
    by_kind_items: dict[str, int] = {"all": len(items)}
    by_kind_canvases: dict[str, int] = {"all": len(canvases)}
    for item in items:
        kind = str(item.get("canvas_kind") or "classic") if isinstance(item, dict) else "classic"
        by_kind_items[kind] = by_kind_items.get(kind, 0) + 1
    for canvas in canvases:
        kind = str(canvas.get("kind") or "classic") if isinstance(canvas, dict) else "classic"
        by_kind_canvases[kind] = by_kind_canvases.get(kind, 0) + 1
    for category in data.get("categories") or []:
        if not isinstance(category, dict):
            continue
        cid = str(category.get("id") or "all")
        category["count"] = by_kind_items.get(cid, 0)
        category["canvas_count"] = by_kind_canvases.get(cid, 0)


def filter_canvas_assets(user: dict, data: dict) -> bool:
    if not isinstance(data, dict) or _is_admin(user):
        return False
    owned = edb.get_user_canvas_ids(_user_id(user))
    changed = False
    canvases = data.get("canvases")
    if isinstance(canvases, list):
        filtered = [c for c in canvases if isinstance(c, dict) and c.get("id") in owned]
        changed = changed or len(filtered) != len(canvases)
        data["canvases"] = filtered
    items = data.get("items")
    if isinstance(items, list):
        filtered = [
            item for item in items
            if isinstance(item, dict) and item.get("canvas_id") in owned
        ]
        changed = changed or len(filtered) != len(items)
        data["items"] = filtered
    if changed:
        _recount_canvas_asset_categories(data)
    return changed


def filter_resource_collections(user: dict, data: Any) -> bool:
    if _is_admin(user) or not isinstance(data, dict):
        return False
    changed = False
    for key in ("items", "assets", "files", "results", "data"):
        value = data.get(key)
        if isinstance(value, list):
            filtered, did_change = _filter_resource_item_list(user, value)
            if did_change:
                data[key] = filtered
                changed = True
    return changed


def record_resources_from_data(user: dict, path: str, method: str, data: Any) -> None:
    if method.upper() not in {"POST", "PUT", "PATCH"}:
        return
    for resource_url in _extract_local_resource_urls(data):
        try:
            edb.record_resource_owner(_user_id(user), resource_url, path)
        except Exception as exc:
            print(f"[企业版] 记录资源归属失败: user={_user_id(user)} resource={resource_url} error={exc}")


def record_event_stream_ownership(user: dict, path: str, method: str, response_body: bytes) -> None:
    """从上游 SSE 响应中提取新建对话归属；不修改响应体。"""
    if path != "api/chat/stream" or method.upper() != "POST":
        return
    try:
        text = response_body.decode("utf-8", errors="ignore")
    except Exception:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except Exception:
            continue
        conv_obj = event.get("conversation") if isinstance(event, dict) else None
        if isinstance(conv_obj, dict) and conv_obj.get("id"):
            try:
                edb.record_conversation_owner(_user_id(user), conv_obj["id"])
            except Exception as exc:
                print(f"[企业版] 记录流式对话归属失败: user={_user_id(user)} conversation={conv_obj.get('id')} error={exc}")
        record_resources_from_data(user, path, method, event)


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
    is_admin = _is_admin(user)

    # SSE 响应不改体，但仍可记录新建对话归属。
    if "text/event-stream" in content_type:
        record_event_stream_ownership(user, path, method, response_body)
        return response_body, {}

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
            try:
                edb.record_canvas_owner(_user_id(user), canvas_obj["id"])
                edb.log_action(_user_id(user), "create_canvas", canvas_obj["id"])
            except Exception as exc:
                print(f"[企业版] 记录画布归属失败: user={_user_id(user)} canvas={canvas_obj.get('id')} error={exc}")

    # ── 记录新对话的归属 ──────────────────────────────────
    # POST /api/conversations / api/chat* → {"conversation": {"id": "..."}}
    if path in {"api/conversations", "api/chat", "api/chat/agent"} and method == "POST" and status_code in (200, 201):
        conv_obj = data.get("conversation") if isinstance(data, dict) else None
        if isinstance(conv_obj, dict) and conv_obj.get("id"):
            try:
                edb.record_conversation_owner(_user_id(user), conv_obj["id"])
            except Exception as exc:
                print(f"[企业版] 记录对话归属失败: user={_user_id(user)} conversation={conv_obj.get('id')} error={exc}")

    if status_code in (200, 201):
        record_resources_from_data(user, path, method, data)

    # ── 过滤画布列表 ──────────────────────────────────────
    # GET /api/canvases → {"canvases": [...]}
    if path == "api/canvases" and method == "GET":
        modified = filter_canvas_list(user, data) or modified

    # ── 过滤回收站画布列表 ────────────────────────────────
    # GET /api/canvases/trash → {"canvases": [...], "retention_days": 30}
    elif path == "api/canvases/trash" and method == "GET":
        modified = filter_canvas_list(user, data) or modified

    # ── 过滤画布资产索引 ──────────────────────────────────
    elif path == "api/canvas-assets" and method == "GET":
        modified = filter_canvas_assets(user, data) or modified

    # ── 过滤对话列表 ──────────────────────────────────────
    elif path == "api/conversations" and method == "GET":
        modified = filter_conversation_list(user, data) or modified

    # ── 过滤通用素材/本地资源集合 ──────────────────────────
    elif path in {"api/asset-library", "api/local-assets"} and method == "GET":
        modified = filter_resource_collections(user, data) or modified

    if modified:
        new_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return new_body, {"content-length": str(len(new_body))}

    return response_body, {}
