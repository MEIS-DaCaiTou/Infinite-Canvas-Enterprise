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


def _clean_relative_path(value: str) -> str:
    parts = []
    for part in str(value or "").replace("\\", "/").split("/"):
        part = unquote(part).strip()
        if not part or part in {".", ".."}:
            continue
        parts.append(os.path.basename(part))
    return "/".join(parts)


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
    record_resource_urls_for_user(_user_id(user), path, data)


def record_resource_urls_for_user(user_id: str, source: str, data: Any) -> None:
    if not user_id:
        return
    for resource_url in _extract_local_resource_urls(data):
        try:
            edb.record_resource_owner(user_id, resource_url, source)
        except Exception as exc:
            print(f"[企业版] 记录资源归属失败: user={user_id} resource={resource_url} error={exc}")


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
        record_resources_from_data(user, path, method, data)
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

    # ── 过滤通用素材/本地资源集合 ──────────────────────────
    elif path in {"api/asset-library", "api/local-assets"} and method == "GET":
        modified = filter_resource_collections(user, data) or modified

    if modified:
        new_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return new_body, {"content-length": str(len(new_body))}

    return response_body, {}
