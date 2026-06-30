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
import ipaddress
import hashlib
import socket
import re
import subprocess
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from fastapi.responses import JSONResponse

from enterprise import db as edb
from enterprise.config import (
    ENTERPRISE_HIDE_UPSTREAM_AUTHOR,
    ENTERPRISE_REPO_URL,
    ENTERPRISE_UPDATE_ENABLED,
    GATEWAY_PORT,
    ROOT_DIR,
    UPSTREAM_PORT,
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
_HISTORY_FILE = Path(ROOT_DIR) / "history.json"
_ASSET_LIBRARY_FILE = Path(ROOT_DIR) / "data" / "asset_library.json"
DEFAULT_PROJECT_ID = "default"

_HISTORY_GENERATION_PATHS = {
    "api/online-image",
    "api/image-task-query",
    "api/angle/generate",
    "api/angle/poll_status",
    "generate",
    "api/ms/generate",
    "api/generate",
}

_INPUT_REUSE_PATHS = {
    "api/online-image",
    "api/chat",
    "api/chat/stream",
    "api/generate",
    "api/canvas-image-tasks",
    "api/canvas-comfy-tasks",
    "api/runninghub/upload-asset",
    "api/runninghub/submit",
    "api/runninghub/workflow-submit",
}

_INPUT_REUSE_PREFIXES = (
    "api/canvas-image-tasks/",
    "api/canvas-comfy-tasks/",
)

_LOCAL_ASSET_MANAGE_PATHS = {
    "api/local-assets/delete",
    "api/local-assets/move",
    "api/local-assets/items",
    "api/local-assets/caption",
    "api/local-assets/classify",
}

_LOCAL_ASSET_RESPONSE_PATHS = {
    "api/local-assets/upload",
    "api/local-assets/import-urls",
    "api/local-assets/items",
    "api/local-assets/move",
}

_ASSET_LIBRARY_ITEM_ACTIONS = {"delete", "move", "classify", "crop"}
_ASSET_LIBRARY_NEW_ITEM_PATHS = {
    "api/asset-library/items",
    "api/asset-library/items/batch",
    "api/asset-library/items/crop",
    "api/asset-library/workflows/upload",
    "api/shared-folders/import",
    "api/canvas-workflows/export-to-library",
}

_COMFY_INPUT_RESPONSE_PATHS = {
    "api/upload",
    "api/comfyui/upload-base64",
}

_RUNTIME_MEDIA_KEY_PARTS = (
    "image",
    "images",
    "image_url",
    "image_urls",
    "reference_image",
    "reference_images",
    "video",
    "videos",
    "audio",
    "audios",
    "mask",
    "filename",
    "file",
    "url",
)

_RUNTIME_MEDIA_EXT_RE = re.compile(
    r"\.(png|jpe?g|webp|gif|bmp|tiff?|mp4|webm|mov|m4v|avi|mkv|mp3|wav|m4a|aac|ogg|flac)(?:\?|$)",
    re.I,
)

MANAGED_MODELSCOPE_TOKEN = "__enterprise_managed_modelscope_token__"

_SENSITIVE_SETTINGS_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_key",
    "secret",
    "credential",
    "wallet_key",
    "password",
    "cookie",
)

_SENSITIVE_SETTINGS_EXACT_KEYS = {
    "token",
    "api_token",
    "access_token",
    "refresh_token",
    "auth_token",
    "bearer_token",
    "ms_token",
    "modelscope_token",
    "base_url",
    "baseurl",
    "api_base",
    "api_base_url",
    "endpoint_url",
    "key_preview",
    "key_env",
    "wallet_key_preview",
    "wallet_key_env",
    "volcengine_access_key_preview",
    "volcengine_access_key_env",
    "volcengine_secret_key_preview",
    "volcengine_secret_key_env",
    "has_key",
    "has_api_key",
    "has_ms_key",
    "has_wallet_key",
    "has_volcengine_access_key",
    "has_volcengine_secret_key",
    "raw",
}


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


def can_access_project(user: dict, project_id: str) -> bool:
    """普通用户可访问自己的项目以及每人独立呈现的默认项目视图。"""
    project_id = str(project_id or "").strip()
    if not project_id:
        return False
    if _is_admin(user) or project_id == DEFAULT_PROJECT_ID:
        return True
    return edb.get_project_owner(project_id) == _user_id(user)


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


def rewrite_managed_modelscope_token_body(path: str, body: bytes | None) -> bytes | None:
    """Let legacy pages keep working without exposing the real ModelScope token."""
    if path not in {"generate", "api/angle/generate", "api/ms/generate"}:
        return body
    payload = _json_from_body(body)
    if not isinstance(payload, dict):
        return body
    if str(payload.get("api_key") or "") != MANAGED_MODELSCOPE_TOKEN:
        return body
    payload["api_key"] = ""
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _normalized_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")


def _is_sensitive_settings_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    if not normalized:
        return False
    if normalized in _SENSITIVE_SETTINGS_EXACT_KEYS:
        return True
    return any(part in normalized for part in _SENSITIVE_SETTINGS_KEY_PARTS)


def _sanitize_settings_data(value: Any) -> tuple[Any, bool]:
    if isinstance(value, dict):
        changed = False
        sanitized: dict = {}
        for key, item in value.items():
            normalized = _normalized_key(key)
            if normalized == "comfy_instances" and isinstance(item, list):
                sanitized[key] = ["configured" for entry in item if str(entry or "").strip()]
                changed = True
                continue
            if _is_sensitive_settings_key(key):
                changed = True
                continue
            child, child_changed = _sanitize_settings_data(item)
            sanitized[key] = child
            changed = changed or child_changed
        return sanitized, changed
    if isinstance(value, list):
        changed = False
        sanitized_list = []
        for item in value:
            child, child_changed = _sanitize_settings_data(item)
            sanitized_list.append(child)
            changed = changed or child_changed
        return sanitized_list, changed
    return value, False


def _is_runninghub_workflow_detail_get(path: str, method: str) -> bool:
    return (
        method.upper() == "GET"
        and path.startswith("api/runninghub/workflows/")
        and path != "api/runninghub/workflows/fetch"
    )


def _is_workflow_detail_get(path: str, method: str) -> bool:
    return method.upper() == "GET" and path.startswith("api/workflows/")


def _settings_response_should_be_sanitized(user: dict, path: str, method: str) -> bool:
    if _is_admin(user):
        return False
    if path in {"api/config", "api/models"} and method.upper() == "GET":
        return True
    if path == "api/workflows" and method.upper() == "GET":
        return True
    if _is_workflow_detail_get(path, method):
        return True
    if _is_runninghub_workflow_detail_get(path, method):
        return True
    return False


def sanitize_settings_response(user: dict, path: str, method: str, data: Any) -> tuple[Any, bool]:
    if not _settings_response_should_be_sanitized(user, path, method):
        return data, False
    return _sanitize_settings_data(data)


def _settings_denial_for_normal_user(path: str, method: str) -> bool:
    method = method.upper()
    if path == "api/providers" or path.startswith("api/providers/"):
        return True
    if path == "api/comfyui/instances":
        return True
    if path in {
        "api/runninghub/app-info",
        "api/runninghub/workflow-info",
        "api/runninghub/workflows",
        "api/runninghub/workflows/fetch",
    }:
        return True
    if path.startswith("api/runninghub/workflows/") and method in {"POST", "PUT", "PATCH", "DELETE"}:
        return True
    if path == "api/workflows":
        return method != "GET"
    if path.startswith("api/workflows/"):
        return method in {"POST", "PUT", "PATCH", "DELETE"}
    if path.startswith("api/jimeng/") and path != "api/jimeng/query-media":
        return True
    return False


def _settings_audit_action(path: str, method: str) -> str:
    method = method.upper()
    if path == "api/providers" and method in {"POST", "PUT", "PATCH", "DELETE"}:
        return "settings_provider_saved"
    if path == "api/providers/test-connection" and method == "POST":
        return "settings_provider_tested"
    if path == "api/providers/probe-async" and method == "POST":
        return "settings_provider_probed"
    if path == "api/providers/fetch-models" and method == "POST":
        return "settings_provider_models_fetched"
    if path.startswith("api/providers/") and path.endswith("/fetch-models") and method == "GET":
        return "settings_provider_models_fetched"
    if path.startswith("api/providers/") and method in {"POST", "PUT", "PATCH", "DELETE"}:
        return "settings_provider_modified"
    if path == "api/comfyui/instances" and method in {"POST", "PUT", "PATCH", "DELETE"}:
        return "settings_comfy_instances_saved"
    if path == "api/workflows" and method == "POST":
        return "settings_workflow_uploaded"
    if path.startswith("api/workflows/") and path.endswith("/config") and method in {"POST", "PUT", "PATCH"}:
        return "settings_workflow_config_saved"
    if path.startswith("api/workflows/") and method == "DELETE":
        return "settings_workflow_deleted"
    if path.startswith("api/workflows/") and method == "POST":
        return "settings_workflow_tested"
    if path == "api/runninghub/workflows/fetch" and method == "POST":
        return "settings_runninghub_workflow_fetched"
    if path.startswith("api/runninghub/workflows/") and method in {"POST", "PUT", "PATCH"}:
        return "settings_runninghub_workflow_saved"
    if path.startswith("api/runninghub/workflows/") and method == "DELETE":
        return "settings_runninghub_workflow_deleted"
    if path in {"api/runninghub/app-info", "api/runninghub/workflow-info"} and method == "GET":
        return "settings_runninghub_metadata_fetched"
    if path.startswith("api/jimeng/") and path != "api/jimeng/query-media":
        return "settings_jimeng_accessed"
    return ""


def _settings_payload_summary(body: bytes | None) -> dict:
    payload = _json_from_body(body)
    if isinstance(payload, list):
        provider_ids = [
            str(item.get("id") or "")[:80]
            for item in payload
            if isinstance(item, dict) and item.get("id")
        ]
        return {
            "payload_type": "list",
            "item_count": len(payload),
            "provider_ids": provider_ids[:20],
            "contains_sensitive_fields": any(_payload_contains_sensitive_key(item) for item in payload),
        }
    if isinstance(payload, dict):
        keys = sorted(str(key)[:80] for key in payload.keys())[:40]
        return {
            "payload_type": "dict",
            "keys": keys,
            "contains_sensitive_fields": _payload_contains_sensitive_key(payload),
        }
    if payload is None:
        return {"payload_type": "empty"}
    return {"payload_type": type(payload).__name__}


def _payload_contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_sensitive_settings_key(key) or _payload_contains_sensitive_key(item):
                return True
    elif isinstance(value, list):
        return any(_payload_contains_sensitive_key(item) for item in value)
    return False


def audit_settings_operation(user: dict, path: str, method: str, body: bytes | None = None) -> None:
    action = _settings_audit_action(path, method)
    if not action:
        return
    try:
        detail = {
            "path": path,
            "method": method.upper(),
            **_settings_payload_summary(body),
        }
        edb.log_action(_user_id(user), action, json.dumps(detail, ensure_ascii=False))
    except Exception as exc:
        print(f"[enterprise] audit settings operation failed: user={_user_id(user)} path={path} error={exc}")


def _clean_relative_path(value: str) -> str:
    parts = []
    for part in str(value or "").replace("\\", "/").split("/"):
        part = unquote(part).strip()
        if not part or part in {".", ".."}:
            continue
        parts.append(os.path.basename(part))
    return "/".join(parts)


def _local_upload_resource_url(value: Any) -> str:
    rel = _clean_relative_path(str(value or ""))
    return f"/assets/uploads/{rel}" if rel else ""


def _input_resource_url_from_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    resource_url = normalize_resource_url(text)
    if _is_protected_resource(resource_url):
        return resource_url
    if re.match(r"^[a-z][a-z0-9+.-]*:", text, re.I) or text.startswith("//"):
        return ""
    rel = _clean_relative_path(text)
    if not rel or not _RUNTIME_MEDIA_EXT_RE.search(rel):
        return ""
    return f"/assets/input/{rel}"


def _looks_like_runtime_media_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    if not normalized:
        return False
    return any(part in normalized for part in _RUNTIME_MEDIA_KEY_PARTS)


def _path_uses_runtime_inputs(path: str) -> bool:
    return path in _INPUT_REUSE_PATHS or any(path.startswith(prefix) for prefix in _INPUT_REUSE_PREFIXES)


def _extract_runtime_input_resource_urls(value: Any, parent_key: str = "", found: Optional[set[str]] = None) -> set[str]:
    found = found if found is not None else set()
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str) and _looks_like_runtime_media_key(key):
                resource_url = _input_resource_url_from_name(child)
                if _is_protected_resource(resource_url):
                    found.add(resource_url)
            _extract_runtime_input_resource_urls(child, str(key), found)
    elif isinstance(value, list):
        for child in value:
            _extract_runtime_input_resource_urls(child, parent_key, found)
    elif isinstance(value, str) and _looks_like_runtime_media_key(parent_key):
        resource_url = _input_resource_url_from_name(value)
        if _is_protected_resource(resource_url):
            found.add(resource_url)
    return found


def _local_asset_resource_urls_from_body(path: str, body: bytes | None) -> set[str]:
    data = _json_from_body(body)
    if not isinstance(data, dict):
        return set()
    urls: set[str] = set()

    def add_name(value: Any) -> None:
        resource_url = _local_upload_resource_url(value)
        if resource_url:
            urls.add(resource_url)

    if path in {"api/local-assets/delete", "api/local-assets/move", "api/local-assets/classify"}:
        names = data.get("names")
        if isinstance(names, list):
            for name in names:
                add_name(name)
    elif path == "api/local-assets/items":
        add_name(data.get("path"))
    elif path == "api/local-assets/caption":
        names = data.get("names")
        if isinstance(names, list):
            for name in names:
                add_name(name)
        add_name(data.get("name"))
    return urls


def _can_manage_resource(user: dict, resource_url: str) -> bool:
    normalized = normalize_resource_url(resource_url)
    if not _is_protected_resource(normalized):
        return False
    if _is_admin(user):
        return True
    return edb.get_resource_owner(normalized) == _user_id(user)


def _audit_local_asset_operation(user: dict, path: str, method: str, resources: set[str]) -> None:
    if not _is_admin(user) or path not in _LOCAL_ASSET_MANAGE_PATHS:
        return
    action_map = {
        "api/local-assets/delete": "local_asset_deleted",
        "api/local-assets/move": "local_asset_moved",
        "api/local-assets/items": "local_asset_renamed",
        "api/local-assets/caption": "local_asset_captioned",
        "api/local-assets/classify": "local_asset_classified",
    }
    action = action_map.get(path)
    if not action:
        return
    try:
        edb.log_action(
            _user_id(user),
            action,
            json.dumps({
                "path": path,
                "method": method.upper(),
                "resource_count": len(resources),
                "resources": sorted(resources)[:50],
            }, ensure_ascii=False),
        )
    except Exception as exc:
        print(f"[enterprise] audit local asset operation failed: user={_user_id(user)} path={path} error={exc}")


def _asset_library_data() -> dict:
    data = _load_json_file(_ASSET_LIBRARY_FILE)
    return data if isinstance(data, dict) else {}


def _asset_library_item_resource_url(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("url", "src", "path", "output"):
        resource_url = normalize_resource_url(str(item.get(key) or ""))
        if _is_protected_resource(resource_url):
            return resource_url
    return ""


def _asset_library_item_id_from_path(path: str) -> str:
    parts = path.split("/")
    if len(parts) < 4 or parts[:3] != ["api", "asset-library", "items"]:
        return ""
    item_id = parts[3]
    if not item_id or item_id in _ASSET_LIBRARY_ITEM_ACTIONS or item_id == "batch":
        return ""
    return item_id


def _iter_asset_library_items(data: Any):
    if not isinstance(data, dict):
        return
    for library in data.get("libraries") or []:
        if not isinstance(library, dict):
            continue
        library_id = str(library.get("id") or "")
        for category in library.get("categories") or []:
            if not isinstance(category, dict):
                continue
            category_id = str(category.get("id") or "")
            for item in category.get("items") or []:
                if isinstance(item, dict):
                    yield library_id, category_id, item


def _asset_library_urls_for_item_ids(ids: set[str], library_id: str = "") -> set[str]:
    if not ids:
        return set()
    urls: set[str] = set()
    for lib_id, _cat_id, item in _iter_asset_library_items(_asset_library_data()):
        if library_id and lib_id != library_id:
            continue
        if str(item.get("id") or "") in ids:
            resource_url = _asset_library_item_resource_url(item)
            if resource_url:
                urls.add(resource_url)
    return urls


def _asset_library_urls_for_category(category_id: str, library_id: str = "") -> set[str]:
    if not category_id:
        return set()
    urls: set[str] = set()
    for lib_id, cat_id, item in _iter_asset_library_items(_asset_library_data()):
        if library_id and lib_id != library_id:
            continue
        if cat_id == category_id:
            resource_url = _asset_library_item_resource_url(item)
            if resource_url:
                urls.add(resource_url)
    return urls


def _asset_library_urls_for_library(library_id: str) -> set[str]:
    if not library_id:
        return set()
    urls: set[str] = set()
    for lib_id, _cat_id, item in _iter_asset_library_items(_asset_library_data()):
        if lib_id == library_id:
            resource_url = _asset_library_item_resource_url(item)
            if resource_url:
                urls.add(resource_url)
    return urls


def _asset_library_manage_urls_from_request(
    path: str,
    method: str,
    query_params: Optional[Mapping[str, Any]],
    body: bytes | None,
) -> set[str]:
    if not path.startswith("api/asset-library/"):
        return set()
    method = method.upper()
    data = _json_from_body(body)
    payload = data if isinstance(data, dict) else {}
    library_id = str(payload.get("library_id") or _query_get(query_params, "library_id") or "").strip()

    item_id = _asset_library_item_id_from_path(path)
    if item_id and method in {"PATCH", "DELETE", "POST"}:
        return _asset_library_urls_for_item_ids({item_id}, library_id)

    if path in {
        "api/asset-library/items/delete",
        "api/asset-library/items/move",
        "api/asset-library/items/classify",
        "api/asset-library/items/crop",
    } and method == "POST":
        ids = {str(item) for item in (payload.get("ids") or []) if str(item)}
        return _asset_library_urls_for_item_ids(ids, library_id)

    parts = path.split("/")
    if len(parts) >= 4 and parts[:3] == ["api", "asset-library", "categories"] and method == "DELETE":
        return _asset_library_urls_for_category(parts[3], library_id)

    if len(parts) >= 4 and parts[:3] == ["api", "asset-library", "libraries"] and method == "DELETE":
        return _asset_library_urls_for_library(parts[3])

    return set()


def _audit_asset_library_operation(user: dict, path: str, method: str, resources: set[str]) -> None:
    if not _is_admin(user) or not resources:
        return
    action = "asset_library_managed"
    if path.endswith("/delete") or method.upper() == "DELETE":
        action = "asset_library_deleted"
    elif path.endswith("/move"):
        action = "asset_library_moved"
    elif path.endswith("/classify"):
        action = "asset_library_classified"
    elif path.endswith("/crop"):
        action = "asset_library_cropped"
    elif method.upper() == "PATCH":
        action = "asset_library_renamed"
    elif path.endswith("/register-avatar") or path.endswith("/avatar-status"):
        action = "asset_library_avatar_updated"
    try:
        edb.log_action(
            _user_id(user),
            action,
            json.dumps({
                "path": path,
                "method": method.upper(),
                "resource_count": len(resources),
                "resources": sorted(resources)[:50],
            }, ensure_ascii=False),
        )
    except Exception as exc:
        print(f"[enterprise] audit asset library operation failed: user={_user_id(user)} path={path} error={exc}")


@lru_cache(maxsize=1)
def _local_resource_hosts() -> set[str]:
    hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    try:
        hostname = socket.gethostname()
        if hostname:
            hosts.add(hostname.lower())
            for info in socket.getaddrinfo(hostname, None):
                if info and info[4]:
                    hosts.add(str(info[4][0]).lower())
    except Exception:
        pass

    sock = None
    try:
        # UDP connect does not send traffic; it only asks the OS for the
        # preferred local address used for outbound LAN access.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        hosts.add(str(sock.getsockname()[0]).lower())
    except Exception:
        pass
    finally:
        if sock:
            sock.close()

    if os.name == "nt":
        try:
            output = subprocess.run(
                ["ipconfig"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=2,
                check=False,
            ).stdout
            for match in re.finditer(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", output):
                hosts.add(match.group(0).lower())
        except Exception:
            pass

    return {host.strip("[]").lower() for host in hosts if host}


def _is_local_resource_host(hostname: str) -> bool:
    host = str(hostname or "").strip("[]").lower()
    if not host:
        return False
    if host in _local_resource_hosts():
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _is_local_absolute_resource(parsed) -> bool:
    if parsed.scheme not in {"http", "https"} and not parsed.netloc:
        return True
    if not _is_local_resource_host(parsed.hostname or ""):
        return False
    if parsed.port is None:
        return True
    return parsed.port in {GATEWAY_PORT, UPSTREAM_PORT}


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
    if (parsed.scheme in {"http", "https"} or parsed.netloc) and not _is_local_absolute_resource(parsed):
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


def _load_history_records() -> list[dict]:
    data = _load_json_file(_HISTORY_FILE)
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _write_history_records(records: list[dict]) -> None:
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(records[:5000], f, ensure_ascii=False, indent=4)


def _history_timestamp_key(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.6f}"
    text = str(value or "").strip()
    try:
        return f"{float(text):.6f}"
    except Exception:
        return text


def _history_resource_urls(record: Any, found: Optional[list[str]] = None) -> list[str]:
    found = found if found is not None else []
    if isinstance(record, str):
        resource_url = normalize_resource_url(record)
        if _is_protected_resource(resource_url) and resource_url not in found:
            found.append(resource_url)
    elif isinstance(record, dict):
        for child in record.values():
            _history_resource_urls(child, found)
    elif isinstance(record, list):
        for child in record:
            _history_resource_urls(child, found)
    return found


def history_id_for_record(record: Mapping[str, Any]) -> str:
    """Return a stable enterprise history identifier without rewriting history.json."""
    urls = _history_resource_urls(record)
    identity = {
        "type": str(record.get("type") or "zimage"),
        "timestamp": _history_timestamp_key(record.get("timestamp")),
        "resource_url": urls[0] if urls else "",
        "task_id": str(record.get("task_id") or ""),
        "request_id": str(record.get("request_id") or ""),
        "prompt_id": str(record.get("prompt_id") or ""),
        "prompt": str(record.get("prompt") or ""),
        "model": str(record.get("model") or ""),
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "hist_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _history_record_type(record: Mapping[str, Any]) -> str:
    return str(record.get("type") or "zimage")


def _history_record_task_id(record: Mapping[str, Any]) -> str:
    return str(record.get("task_id") or record.get("request_id") or record.get("prompt_id") or "").strip()


def _history_record_primary_resource(record: Mapping[str, Any]) -> str:
    urls = _history_resource_urls(record)
    return urls[0] if urls else ""


def _timestamp_as_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _history_timestamp_matches(item_ts: Any, requested_ts: Any) -> bool:
    item_float = _timestamp_as_float(item_ts)
    requested_float = _timestamp_as_float(requested_ts)
    if item_float is not None and requested_float is not None:
        return abs(item_float - requested_float) < 0.001
    return str(item_ts) == str(requested_ts)


def _history_delete_timestamp_from_body(body: bytes | None) -> Any:
    data = _json_from_body(body)
    if not isinstance(data, dict):
        return None
    return data.get("timestamp")


def _history_candidates_for_timestamp(records: list[dict], requested_ts: Any) -> list[tuple[int, dict]]:
    return [
        (idx, item)
        for idx, item in enumerate(records)
        if _history_timestamp_matches(item.get("timestamp", 0), requested_ts)
    ]


def _annotate_history_record(record: dict, owner_map: dict, users: dict) -> dict:
    item = dict(record)
    history_id = history_id_for_record(item)
    owner_id = owner_map.get(history_id)
    owner = users.get(owner_id or "", {})
    item["enterprise_history_id"] = history_id
    item["enterprise_owner_id"] = owner_id
    item["enterprise_owner_username"] = owner.get("username", "")
    item["enterprise_owner_display_name"] = owner.get("display_name", "")
    item["enterprise_unowned"] = owner_id is None
    return item


def filter_history_list(user: dict, data: Any) -> bool:
    if not isinstance(data, list):
        return False
    owner_map = edb.get_all_history_owner_map()
    users = _user_lookup()
    user_id = _user_id(user)
    filtered = []
    for record in data:
        if not isinstance(record, dict):
            continue
        history_id = history_id_for_record(record)
        owner_id = owner_map.get(history_id)
        if _is_admin(user) or owner_id == user_id:
            filtered.append(_annotate_history_record(record, owner_map, users))
    data[:] = filtered
    return True


def _history_records_from_generation_payload(data: Any) -> list[dict]:
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("images"), list) and data.get("timestamp"):
        return [data]

    response_urls = set(_history_resource_urls(data))
    response_task_id = str(data.get("task_id") or data.get("request_id") or data.get("prompt_id") or "").strip()
    matches = []
    for record in _load_history_records():
        if response_task_id and _history_record_task_id(record) == response_task_id:
            matches.append(record)
            break
        if response_urls and response_urls.intersection(_history_resource_urls(record)):
            matches.append(record)
            break
    return matches


def _history_records_from_generation_response(path: str, data: Any) -> list[dict]:
    if path not in _HISTORY_GENERATION_PATHS:
        return []
    return _history_records_from_generation_payload(data)


def _record_history_record_for_user_id(user_id: str, record: Mapping[str, Any], source: str) -> None:
    history_id = history_id_for_record(record)
    primary_resource = _history_record_primary_resource(record)
    task_id = _history_record_task_id(record)
    try:
        edb.record_history_owner(
            user_id,
            history_id,
            _history_record_type(record),
            primary_resource,
            task_id,
            source,
        )
    except Exception as exc:
        print(f"[enterprise] record history owner failed: user={user_id} history={history_id} error={exc}")
    record_resource_urls_for_user(user_id, f"history:{history_id}", record)


def record_history_payload_for_user_id(user_id: str, source: str, data: Any) -> None:
    if not user_id:
        return
    for record in _history_records_from_generation_payload(data):
        _record_history_record_for_user_id(user_id, record, source)


def record_generated_history_for_user(user: dict, path: str, method: str, data: Any) -> None:
    if method.upper() != "POST" or path not in _HISTORY_GENERATION_PATHS:
        return
    user_id = _user_id(user)
    if not user_id:
        return
    for record in _history_records_from_generation_response(path, data):
        _record_history_record_for_user_id(user_id, record, path)


def record_history_resources_for_user(user_id: str, record: Mapping[str, Any], source: str) -> None:
    record_resource_urls_for_user(user_id, source, record)


def find_history_record_by_id(history_id: str) -> Optional[dict]:
    wanted = str(history_id or "").strip()
    if not wanted:
        return None
    for record in _load_history_records():
        if history_id_for_record(record) == wanted:
            return record
    return None


def handle_history_delete(user: dict, body: bytes | None) -> JSONResponse:
    requested_ts = _history_delete_timestamp_from_body(body)
    if requested_ts is None:
        return JSONResponse({"error": "timestamp 不能为空", "code": 400}, status_code=400)
    if not _HISTORY_FILE.exists():
        return JSONResponse({"success": False, "message": "History file not found"})

    records = _load_history_records()
    candidates = _history_candidates_for_timestamp(records, requested_ts)
    if not candidates:
        return JSONResponse({"success": False, "message": "Record not found"})

    is_admin = _is_admin(user)
    user_id = _user_id(user)
    candidate_ids = [history_id_for_record(record) for _idx, record in candidates]

    if not is_admin:
        if len(candidates) != 1:
            return _deny_not_found("历史记录不存在或无权限访问")
        owner = edb.get_history_owner(candidate_ids[0])
        if owner != user_id:
            return _deny_not_found("历史记录不存在或无权限访问")

    remove_indexes = {idx for idx, _record in candidates}
    remaining = [record for idx, record in enumerate(records) if idx not in remove_indexes]
    try:
        _write_history_records(remaining)
        for history_id in candidate_ids:
            edb.remove_history_mapping(history_id)
        edb.log_action(
            user_id,
            "history_deleted",
            json.dumps({
                "timestamp": requested_ts,
                "history_ids": candidate_ids,
                "deleted_count": len(candidate_ids),
                "is_admin": is_admin,
            }, ensure_ascii=False),
        )
    except Exception as exc:
        print(f"[enterprise] delete history failed: timestamp={requested_ts} error={exc}")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

    return JSONResponse({"success": True, "deleted_count": len(candidate_ids)})


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


def _resource_in_user_canvas_scope(user_id: str, resource_url: str) -> bool:
    for canvas_id in _canvas_ids_for_resource(resource_url):
        if edb.get_canvas_owner(canvas_id) == user_id:
            edb.record_resource_owner(user_id, resource_url, f"derived_from_canvas:{canvas_id}")
            return True
    return False


def _resource_in_user_conversation_scope(user_id: str, resource_url: str) -> bool:
    for conversation_id in _conversation_ids_for_resource(resource_url):
        if edb.get_conversation_owner(conversation_id) == user_id:
            edb.record_resource_owner(user_id, resource_url, f"derived_from_conversation:{conversation_id}")
            return True
    return False


def _reconcile_canvas_resource_ownership(canvas_id: str, data: Any, source: str) -> None:
    canvas_owner = edb.get_canvas_owner(canvas_id)
    if not canvas_owner:
        return
    canvas = data.get("canvas") if isinstance(data, dict) and isinstance(data.get("canvas"), dict) else data
    if not isinstance(canvas, dict):
        return
    for resource_url in _extract_local_resource_urls(canvas):
        if not _is_protected_resource(resource_url):
            continue
        if edb.get_resource_owner(resource_url):
            continue
        try:
            edb.record_resource_owner(canvas_owner, resource_url, source)
        except Exception as exc:
            print(f"[enterprise] reconcile canvas resource owner failed: canvas={canvas_id} resource={resource_url} error={exc}")


def can_access_resource(user: dict, resource_url: str) -> bool:
    """判断本地资源是否属于当前用户可访问的画布/对话/资源归属。"""
    normalized = normalize_resource_url(resource_url)
    if not _is_protected_resource(normalized):
        return True
    if _is_admin(user):
        return True

    user_id = _user_id(user)
    owner = edb.get_resource_owner(normalized)
    if owner == user_id:
        return True

    if _resource_in_user_canvas_scope(user_id, normalized):
        return True

    if _resource_in_user_conversation_scope(user_id, normalized):
        return True

    if owner:
        return False

    return False


def _canvas_image_task_id_from_path(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "canvas-image-tasks" and parts[2]:
        return parts[2]
    return ""


def can_access_canvas_image_task(user: dict, task_id: str) -> bool:
    if _is_admin(user):
        return True
    owner = edb.get_canvas_image_task_owner(task_id)
    return bool(owner and owner == _user_id(user))


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
    elif path in {"api/download-output", "api/media-preview", "api/image-jpeg"}:
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
            if _path_uses_runtime_inputs(path):
                urls.update(_extract_runtime_input_resource_urls(data))

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


def _project_id_from_path(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "projects" and parts[2]:
        return parts[2]
    return ""


def _project_id_from_body(body: bytes | None) -> str:
    data = _json_from_body(body)
    if not isinstance(data, dict):
        return ""
    project_id = data.get("project")
    if not project_id and isinstance(data.get("canvas"), dict):
        project_id = data["canvas"].get("project")
    return str(project_id or "").strip()


def _project_contains_foreign_canvas(user_id: str, project_id: str) -> bool:
    """阻止普通用户删除含其他 owner 或未归属画布的项目。"""
    if not _CANVAS_DATA_DIR.is_dir():
        return False
    for path in _CANVAS_DATA_DIR.glob("*.json"):
        data = _load_json_file(path)
        if not isinstance(data, dict) or str(data.get("project") or DEFAULT_PROJECT_ID) != project_id:
            continue
        canvas_id = str(data.get("id") or path.stem)
        if edb.get_canvas_owner(canvas_id) != user_id:
            return True
    return False


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

    if path == "api/config/token" and method.upper() == "GET" and not is_admin:
        return JSONResponse(
            {
                "token": MANAGED_MODELSCOPE_TOKEN,
                "enterprise_managed": True,
            },
            status_code=200,
        )

    if _settings_denial_for_normal_user(path, method):
        if not is_admin:
            return _deny_forbidden("需要管理员权限才能访问企业高风险设置")
        audit_settings_operation(user, path, method, body)

    if path == "api/history/delete" and method.upper() == "POST":
        return handle_history_delete(user, body)

    project_id = _project_id_from_path(path)
    if project_id:
        if project_id == DEFAULT_PROJECT_ID and not is_admin:
            return _deny_not_found("项目不存在或无权限访问")
        if not can_access_project(user, project_id):
            return _deny_not_found("项目不存在或无权限访问")
        if method.upper() == "DELETE" and not is_admin and _project_contains_foreign_canvas(_user_id(user), project_id):
            return _deny_not_found("项目不存在或无权限访问")

    requested_project_id = _project_id_from_body(body)
    if requested_project_id and not can_access_project(user, requested_project_id):
        return _deny_not_found("项目不存在或无权限访问")

    canvas_id = _canvas_id_from_path(path)
    if canvas_id and not can_access_canvas(user, canvas_id):
        return _deny_not_found("画布不存在或无权限访问")

    conversation_id = _conversation_id_from_path(path) or _conversation_id_from_body(path, body)
    if conversation_id and not can_access_conversation(user, conversation_id):
        return _deny_not_found("对话不存在或无权限访问")

    canvas_task_id = _canvas_image_task_id_from_path(path)
    if canvas_task_id and not can_access_canvas_image_task(user, canvas_task_id):
        return _deny_not_found("生成任务不存在或无权限访问")

    local_asset_manage_urls = _local_asset_resource_urls_from_body(path, body)
    for resource_url in local_asset_manage_urls:
        if not _can_manage_resource(user, resource_url):
            return _deny_not_found("资源不存在或无权限访问")
    if local_asset_manage_urls:
        _audit_local_asset_operation(user, path, method, local_asset_manage_urls)

    asset_library_manage_urls = _asset_library_manage_urls_from_request(path, method, query_params, body)
    for resource_url in asset_library_manage_urls:
        if not _can_manage_resource(user, resource_url):
            return _deny_not_found("资源不存在或无权限访问")
    if asset_library_manage_urls:
        _audit_asset_library_operation(user, path, method, asset_library_manage_urls)

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
    filtered = []
    for canvas in canvas_list:
        if not isinstance(canvas, dict) or canvas.get("id") not in owned:
            continue
        item = dict(canvas)
        project_id = str(item.get("project") or DEFAULT_PROJECT_ID)
        if not can_access_project(user, project_id):
            # 旧画布可能引用未归属的全局项目。把它安全地呈现为当前用户的默认项目，
            # 直到管理员完成项目归属分配或用户下一次保存时迁回默认项目。
            item["project"] = DEFAULT_PROJECT_ID
        filtered.append(item)
    data["canvases"] = filtered
    return len(filtered) != len(canvas_list) or filtered != canvas_list


def _owned_canvas_counts_by_project(user_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not _CANVAS_DATA_DIR.is_dir():
        return counts
    for path in _CANVAS_DATA_DIR.glob("*.json"):
        data = _load_json_file(path)
        if not isinstance(data, dict):
            continue
        canvas_id = str(data.get("id") or path.stem)
        if edb.get_canvas_owner(canvas_id) != user_id:
            continue
        project_id = str(data.get("project") or DEFAULT_PROJECT_ID)
        if edb.get_project_owner(project_id) != user_id and project_id != DEFAULT_PROJECT_ID:
            project_id = DEFAULT_PROJECT_ID
        counts[project_id] = counts.get(project_id, 0) + 1
    return counts


def filter_project_list(user: dict, data: dict) -> bool:
    """普通用户只看到自己的项目和按本人画布计数的虚拟默认项目。"""
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, list) or _is_admin(user):
        return False
    user_id = _user_id(user)
    owned_projects = edb.get_user_project_ids(user_id)
    counts = _owned_canvas_counts_by_project(user_id)
    filtered: list[dict] = []
    has_default = False
    for project in projects:
        if not isinstance(project, dict):
            continue
        project_id = str(project.get("id") or "")
        if project_id == DEFAULT_PROJECT_ID:
            item = dict(project)
            item["canvas_count"] = counts.get(DEFAULT_PROJECT_ID, 0)
            filtered.append(item)
            has_default = True
        elif project_id in owned_projects:
            item = dict(project)
            item["canvas_count"] = counts.get(project_id, 0)
            filtered.append(item)
    if not has_default:
        filtered.insert(0, {
            "id": DEFAULT_PROJECT_ID,
            "name": "默认项目",
            "order": 0,
            "created_at": 0,
            "updated_at": 0,
            "canvas_count": counts.get(DEFAULT_PROJECT_ID, 0),
        })
    data["projects"] = filtered
    return True


def _normalize_canvas_project_for_user(user: dict, data: Any) -> bool:
    if _is_admin(user) or not isinstance(data, dict):
        return False
    canvas = data.get("canvas") if isinstance(data.get("canvas"), dict) else None
    if not canvas:
        return False
    project_id = str(canvas.get("project") or DEFAULT_PROJECT_ID)
    if can_access_project(user, project_id):
        return False
    canvas["project"] = DEFAULT_PROJECT_ID
    return True


def _sync_admin_canvas_owner_from_persisted_project(
    user: dict,
    path: str,
    method: str,
) -> None:
    """管理员成功操作单个画布后，以落盘 JSON 的最终 project 同步 canvas owner。"""
    if not _is_admin(user) or method not in {"POST", "PUT"}:
        return
    canvas_id = _canvas_id_from_path(path)
    if not canvas_id:
        return
    if path not in {f"api/canvases/{canvas_id}/meta", f"api/canvases/{canvas_id}"}:
        return
    persisted_project_id = edb.get_canvas_project(canvas_id) or DEFAULT_PROJECT_ID
    if persisted_project_id == DEFAULT_PROJECT_ID:
        return
    target_owner = edb.get_project_owner(persisted_project_id)
    if not target_owner:
        return
    old_owner = edb.get_canvas_owner(canvas_id)
    if old_owner == target_owner:
        return
    try:
        edb.set_canvas_owner(canvas_id, target_owner)
        edb.log_action(
            _user_id(user),
            "admin_canvas_owner_synced_from_project",
            json.dumps({
                "canvas_id": canvas_id,
                "project_id": persisted_project_id,
                "old_owner": old_owner,
                "new_owner": target_owner,
            }, ensure_ascii=False),
        )
    except Exception as exc:
        print(
            "[enterprise] sync canvas owner to project failed: "
            f"canvas={canvas_id} project={persisted_project_id} error={exc}"
        )


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


def _is_owned_local_asset_item(user: dict, item: Any) -> bool:
    if _is_admin(user):
        return True
    if not isinstance(item, dict):
        return True
    url = item.get("url") or item.get("src") or item.get("path") or item.get("file")
    resource_url = normalize_resource_url(str(url or ""))
    if not resource_url:
        resource_url = _local_upload_resource_url(item.get("file") or item.get("path") or "")
    if not _is_protected_resource(resource_url):
        return True
    return edb.get_resource_owner(resource_url) == _user_id(user)


def _filter_local_asset_tree(user: dict, node: Any, keep_root: bool = False) -> tuple[Any, bool, int]:
    if not isinstance(node, dict):
        return node, False, 0
    changed = False
    source_items = node.get("items") if isinstance(node.get("items"), list) else []
    items = [item for item in source_items if _is_owned_local_asset_item(user, item)]
    changed = changed or len(items) != len(source_items)

    source_children = node.get("children") if isinstance(node.get("children"), list) else []
    children = []
    total = len(items)
    for child in source_children:
        filtered_child, child_changed, child_count = _filter_local_asset_tree(user, child, False)
        changed = changed or child_changed
        if child_count > 0:
            children.append(filtered_child)
            total += child_count
        else:
            changed = True

    next_node = dict(node)
    next_node["items"] = items
    next_node["children"] = children
    if next_node.get("count") != total:
        changed = True
    next_node["count"] = total
    if keep_root or total > 0:
        return next_node, changed, total
    return None, True, 0


def filter_local_assets(user: dict, data: Any) -> bool:
    if _is_admin(user) or not isinstance(data, dict):
        return False
    changed = False
    for key in ("items", "files", "assets", "results", "data"):
        value = data.get(key)
        if isinstance(value, list):
            filtered = [item for item in value if _is_owned_local_asset_item(user, item)]
            if len(filtered) != len(value):
                data[key] = filtered
                changed = True
    if isinstance(data.get("tree"), dict):
        filtered_tree, tree_changed, _count = _filter_local_asset_tree(user, data["tree"], True)
        data["tree"] = filtered_tree
        changed = changed or tree_changed
    return changed


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


def _is_owned_asset_library_item(user: dict, item: Any) -> bool:
    if _is_admin(user):
        return True
    resource_url = _asset_library_item_resource_url(item)
    if not _is_protected_resource(resource_url):
        return True
    return edb.get_resource_owner(resource_url) == _user_id(user)


def _filter_asset_library_categories(user: dict, categories: Any) -> bool:
    if _is_admin(user) or not isinstance(categories, list):
        return False
    changed = False
    for category in categories:
        if not isinstance(category, dict):
            continue
        items = category.get("items")
        if not isinstance(items, list):
            continue
        filtered = [item for item in items if _is_owned_asset_library_item(user, item)]
        if len(filtered) != len(items):
            category["items"] = filtered
            changed = True
    return changed


def filter_asset_library(user: dict, data: Any) -> bool:
    if _is_admin(user) or not isinstance(data, dict):
        return False
    root = data.get("library") if isinstance(data.get("library"), dict) else data
    if not isinstance(root, dict):
        return False
    changed = False
    libraries = root.get("libraries")
    if isinstance(libraries, list):
        for library in libraries:
            if isinstance(library, dict):
                changed = _filter_asset_library_categories(user, library.get("categories")) or changed
    changed = _filter_asset_library_categories(user, root.get("categories")) or changed
    return changed


def record_resource_urls_for_user(user_id: str, source: str, data: Any) -> None:
    if not user_id:
        return
    for resource_url in _extract_local_resource_urls(data):
        try:
            edb.record_resource_owner(user_id, resource_url, source)
        except Exception as exc:
            print(f"[企业版] 记录资源归属失败: user={user_id} resource={resource_url} error={exc}")


def _record_resource_owner_safe(user_id: str, resource_url: str, source: str) -> None:
    if not user_id:
        return
    normalized = normalize_resource_url(resource_url)
    if not _is_protected_resource(normalized):
        return
    try:
        edb.record_resource_owner(user_id, normalized, source)
    except Exception as exc:
        print(f"[enterprise] record resource owner failed: user={user_id} resource={normalized} error={exc}")


def _comfy_input_names_from_response(path: str, data: Any) -> set[str]:
    names: set[str] = set()
    if path == "api/upload" and isinstance(data, dict):
        files = data.get("files")
        if isinstance(files, list):
            for item in files:
                if isinstance(item, dict):
                    name = str(item.get("comfy_name") or item.get("name") or "").strip()
                    if name:
                        names.add(name)
    elif path == "api/comfyui/upload-base64" and isinstance(data, dict):
        name = str(data.get("name") or data.get("comfy_name") or "").strip()
        if name:
            names.add(name)
    return names


def _record_comfy_input_response_resources(user_id: str, path: str, data: Any) -> bool:
    if path not in _COMFY_INPUT_RESPONSE_PATHS:
        return False
    for name in _comfy_input_names_from_response(path, data):
        resource_url = _input_resource_url_from_name(name)
        _record_resource_owner_safe(user_id, resource_url, f"{path}:comfy_input")
    return True


def _owner_for_existing_resource(user: dict, resource_url: str) -> str:
    owner = edb.get_resource_owner(normalize_resource_url(resource_url))
    if owner:
        return owner
    return "" if _is_admin(user) else _user_id(user)


def _record_local_asset_response_resources(user: dict, path: str, body: bytes | None, data: Any) -> bool:
    if path not in _LOCAL_ASSET_RESPONSE_PATHS and not path.startswith("api/local-assets/"):
        return False
    user_id = _user_id(user)
    if path in {"api/local-assets/upload", "api/local-assets/import-urls"}:
        record_resource_urls_for_user(user_id, path, data)
        return True

    payload = _json_from_body(body)
    if not isinstance(payload, dict):
        return True

    if path == "api/local-assets/items":
        old_url = _local_upload_resource_url(payload.get("path"))
        owner = _owner_for_existing_resource(user, old_url)
        if owner and isinstance(data, dict):
            item = data.get("item")
            new_url = normalize_resource_url(str((item or {}).get("url") or "")) if isinstance(item, dict) else ""
            _record_resource_owner_safe(owner, new_url, f"{path}:rename")
        return True

    if path == "api/local-assets/move":
        names = payload.get("names")
        folder = _clean_relative_path(str(payload.get("folder") or ""))
        if isinstance(names, list):
            for name in names:
                old_url = _local_upload_resource_url(name)
                owner = _owner_for_existing_resource(user, old_url)
                if not owner:
                    continue
                base = os.path.basename(_clean_relative_path(str(name or "")))
                if not base:
                    continue
                new_rel = f"{folder}/{base}".lstrip("/") if folder else base
                _record_resource_owner_safe(owner, _local_upload_resource_url(new_rel), f"{path}:move")
        return True

    return True


def _asset_library_new_items_from_response(path: str, data: Any) -> list[dict]:
    if path not in _ASSET_LIBRARY_NEW_ITEM_PATHS or not isinstance(data, dict):
        return []
    if path in {"api/asset-library/items", "api/canvas-workflows/export-to-library"}:
        item = data.get("item")
        return [item] if isinstance(item, dict) else []
    items = data.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _record_asset_library_response_resources(user: dict, path: str, data: Any) -> bool:
    if not (
        path.startswith("api/asset-library/")
        or path in {"api/shared-folders/import", "api/canvas-workflows/export-to-library"}
    ):
        return False
    user_id = _user_id(user)
    for item in _asset_library_new_items_from_response(path, data):
        resource_url = _asset_library_item_resource_url(item)
        _record_resource_owner_safe(user_id, resource_url, f"{path}:asset_library")
    return True


def record_resources_from_data(user: dict, path: str, method: str, data: Any, request_body: bytes | None = None) -> None:
    if method.upper() not in {"POST", "PUT", "PATCH"}:
        return
    if _record_comfy_input_response_resources(_user_id(user), path, data):
        return
    if _record_local_asset_response_resources(user, path, request_body, data):
        return
    if _record_asset_library_response_resources(user, path, data):
        return
    record_resource_urls_for_user(_user_id(user), path, data)


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
    request_body: bytes | None = None,
) -> Tuple[bytes, dict]:
    """
    返回 (处理后的 body bytes, 需要覆盖的响应头 dict)
    """
    is_admin = _is_admin(user)
    is_success = 200 <= status_code < 300

    # SSE 响应不改体，但仍可记录新建对话归属。
    if "text/event-stream" in content_type:
        if is_success:
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

    if not is_success:
        return response_body, {}

    modified = False
    data, sanitized_settings = sanitize_settings_response(user, path, method, data)
    modified = sanitized_settings or modified

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

    if path == "api/projects" and method == "POST" and status_code in (200, 201):
        project_obj = data.get("project") if isinstance(data, dict) else None
        if isinstance(project_obj, dict) and project_obj.get("id"):
            try:
                edb.record_project_owner(_user_id(user), str(project_obj["id"]))
                edb.log_action(_user_id(user), "project_created", str(project_obj["id"]))
            except Exception as exc:
                print(f"[enterprise] record project owner failed: user={_user_id(user)} project={project_obj.get('id')} error={exc}")

    deleted_project_id = _project_id_from_path(path)
    if deleted_project_id and method == "DELETE" and status_code in (200, 201, 204):
        edb.remove_project_mapping(deleted_project_id)

    # ── 记录新对话的归属 ──────────────────────────────────
    # POST /api/conversations / api/chat* → {"conversation": {"id": "..."}}
    if path in {"api/conversations", "api/chat", "api/chat/agent"} and method == "POST" and status_code in (200, 201):
        conv_obj = data.get("conversation") if isinstance(data, dict) else None
        if isinstance(conv_obj, dict) and conv_obj.get("id"):
            try:
                edb.record_conversation_owner(_user_id(user), conv_obj["id"])
            except Exception as exc:
                print(f"[企业版] 记录对话归属失败: user={_user_id(user)} conversation={conv_obj.get('id')} error={exc}")

    if path == "api/canvas-image-tasks" and method == "POST" and status_code in (200, 201):
        task_id = str(data.get("task_id") or "") if isinstance(data, dict) else ""
        if task_id:
            try:
                edb.record_canvas_image_task_owner(_user_id(user), task_id)
            except Exception as exc:
                print(f"[enterprise] record canvas image task owner failed: user={_user_id(user)} task={task_id} error={exc}")

    canvas_task_id = _canvas_image_task_id_from_path(path)
    if canvas_task_id and method == "GET" and status_code == 200:
        task_owner = edb.get_canvas_image_task_owner(canvas_task_id)
        if task_owner:
            record_resource_urls_for_user(task_owner, path, data)
            if isinstance(data, dict) and str(data.get("status") or "").lower() == "succeeded":
                record_history_payload_for_user_id(task_owner, path, data)

    if status_code in (200, 201):
        record_resources_from_data(user, path, method, data, request_body)
        record_generated_history_for_user(user, path, method, data)

    _sync_admin_canvas_owner_from_persisted_project(user, path, method)

    canvas_id_for_reconcile = _canvas_id_from_path(path)
    if canvas_id_for_reconcile and path == f"api/canvases/{canvas_id_for_reconcile}" and method in {"GET", "PUT"}:
        _reconcile_canvas_resource_ownership(canvas_id_for_reconcile, data, f"{path}:{method.lower()}")

    # ── 过滤画布列表 ──────────────────────────────────────
    # GET /api/canvases → {"canvases": [...]}
    if path == "api/canvases" and method == "GET":
        modified = filter_canvas_list(user, data) or modified

    # ── 过滤项目列表及项目下画布计数 ───────────────────────
    elif path == "api/projects" and method == "GET":
        modified = filter_project_list(user, data) or modified

    # ── 过滤回收站画布列表 ────────────────────────────────
    # GET /api/canvases/trash → {"canvases": [...], "retention_days": 30}
    elif path == "api/canvases/trash" and method == "GET":
        modified = filter_canvas_list(user, data) or modified

    elif path.startswith("api/canvases/") and method in {"GET", "POST", "PUT"}:
        modified = _normalize_canvas_project_for_user(user, data) or modified

    # ── 过滤画布资产索引 ──────────────────────────────────
    elif path == "api/canvas-assets" and method == "GET":
        modified = filter_canvas_assets(user, data) or modified

    # ── 过滤对话列表 ──────────────────────────────────────
    elif path == "api/conversations" and method == "GET":
        modified = filter_conversation_list(user, data) or modified

    # ── 过滤生成历史列表 ──────────────────────────────────
    elif path == "api/history" and method == "GET":
        modified = filter_history_list(user, data) or modified

    # ── 过滤本地上传资源集合 ──────────────────────────────
    elif path == "api/local-assets" or path.startswith("api/local-assets/"):
        modified = filter_local_assets(user, data) or modified

    # ── 过滤通用素材集合 ──────────────────────────────────
    elif (
        path == "api/asset-library"
        or path.startswith("api/asset-library/")
        or path in {"api/shared-folders/import", "api/canvas-workflows/export-to-library"}
    ):
        modified = filter_asset_library(user, data) or modified

    if modified:
        new_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return new_body, {"content-length": str(len(new_body))}

    return response_body, {}
