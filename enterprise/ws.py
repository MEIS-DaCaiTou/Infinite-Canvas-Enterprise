"""
Enterprise WebSocket visibility controls.

This module keeps the enterprise user binding for proxied upstream WebSocket
connections and decides which upstream realtime events may be delivered to a
normal user.  It intentionally stays independent from enterprise.interceptors to
avoid import cycles.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlparse

from enterprise import db as edb


_PROTECTED_RESOURCE_PREFIXES = (
    "/assets/input/",
    "/assets/output/",
    "/assets/uploads/",
    "/assets/library/",
    "/output/",
)

_SENSITIVE_EVENT_TYPES = {
    "new_image",
    "asset_library_updated",
    "canvas_updated",
    "cloud_status",
    "history_updated",
    "task_updated",
    "comfy_task_updated",
    "runninghub_task_updated",
    "generation_progress",
    "generation_completed",
    "generation_failed",
}

_HISTORY_IDENTITY_KEYS = (
    "type",
    "timestamp",
    "resource_url",
    "task_id",
    "request_id",
    "prompt_id",
    "prompt",
    "model",
)

_GENERATION_RESPONSE_PATHS = {
    "api/online-image",
    "api/image-task-query",
    "api/angle/generate",
    "api/angle/poll_status",
    "generate",
    "api/ms/generate",
    "api/generate",
}

_ASSET_LIBRARY_WRITE_PREFIXES = (
    "api/asset-library",
)

_ASSET_LIBRARY_WRITE_PATHS = {
    "api/shared-folders/import",
    "api/canvas-workflows/export-to-library",
}


@dataclass
class EnterpriseWsConnection:
    websocket: Any
    user_id: str
    username: str
    is_admin: bool
    path: str
    client_id: str
    connection_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    connected_at: int = field(default_factory=lambda: int(time.time() * 1000))
    last_seen_at: int = field(default_factory=lambda: int(time.time() * 1000))
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    recent_event_ids: dict[str, int] = field(default_factory=dict)


_CONNECTIONS: dict[str, EnterpriseWsConnection] = {}
_CLIENT_USERS: dict[str, set[str]] = {}


def user_id_from_user(user: Mapping[str, Any] | None) -> str:
    return str((user or {}).get("user_id") or (user or {}).get("id") or "").strip()


def is_admin_user(user: Mapping[str, Any] | None) -> bool:
    return bool((user or {}).get("is_admin"))


def normalize_resource_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        parsed = None
    if parsed and parsed.scheme in {"http", "https"}:
        text = parsed.path or ""
        if parsed.query:
            text = f"{text}?{parsed.query}"
    if text.startswith("output/"):
        text = "/" + text
    if text.startswith("/output/"):
        return text
    if text.startswith("assets/"):
        text = "/" + text
    return text


def is_protected_resource(resource_url: str) -> bool:
    normalized = normalize_resource_url(resource_url)
    return any(normalized.startswith(prefix) for prefix in _PROTECTED_RESOURCE_PREFIXES)


def protected_resource_urls(value: Any, found: set[str] | None = None) -> set[str]:
    found = found if found is not None else set()
    if isinstance(value, str):
        resource_url = normalize_resource_url(value)
        if is_protected_resource(resource_url):
            found.add(resource_url)
    elif isinstance(value, Mapping):
        for child in value.values():
            protected_resource_urls(child, found)
    elif isinstance(value, list):
        for child in value:
            protected_resource_urls(child, found)
    return found


def history_timestamp_key(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.6f}"
    text = str(value or "").strip()
    try:
        return f"{float(text):.6f}"
    except Exception:
        return text


def history_id_for_record(record: Mapping[str, Any]) -> str:
    urls = sorted(protected_resource_urls(record))
    identity = {
        "type": str(record.get("type") or "zimage"),
        "timestamp": history_timestamp_key(record.get("timestamp")),
        "resource_url": urls[0] if urls else "",
        "task_id": str(record.get("task_id") or ""),
        "request_id": str(record.get("request_id") or ""),
        "prompt_id": str(record.get("prompt_id") or ""),
        "prompt": str(record.get("prompt") or ""),
        "model": str(record.get("model") or ""),
    }
    raw = json.dumps(
        {key: identity.get(key, "") for key in _HISTORY_IDENTITY_KEYS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "hist_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def build_upstream_ws_url(upstream_url: str, path: str, query_string: str = "") -> str:
    base = upstream_url.replace("http://", "ws://").replace("https://", "wss://").rstrip("/")
    target = f"{base}/ws/{str(path or '').lstrip('/')}"
    query = str(query_string or "").lstrip("?")
    if query:
        target += f"?{query}"
    return target


def register_connection(websocket: Any, user: Mapping[str, Any], path: str, client_id: str = "") -> EnterpriseWsConnection:
    user_id = user_id_from_user(user)
    conn = EnterpriseWsConnection(
        websocket=websocket,
        user_id=user_id,
        username=str(user.get("username") or ""),
        is_admin=is_admin_user(user),
        path=str(path or ""),
        client_id=str(client_id or "").strip(),
    )
    _CONNECTIONS[conn.connection_id] = conn
    if conn.client_id and conn.user_id:
        _CLIENT_USERS.setdefault(conn.client_id, set()).add(conn.user_id)
    return conn


def forget_connection(connection: EnterpriseWsConnection | str | None) -> None:
    connection_id = connection.connection_id if isinstance(connection, EnterpriseWsConnection) else str(connection or "")
    conn = _CONNECTIONS.pop(connection_id, None)
    if not conn or not conn.client_id:
        return
    users = _CLIENT_USERS.get(conn.client_id)
    if not users:
        return
    still_active = any(
        item.client_id == conn.client_id and item.user_id == conn.user_id
        for item in _CONNECTIONS.values()
    )
    if not still_active:
        users.discard(conn.user_id)
    if not users:
        _CLIENT_USERS.pop(conn.client_id, None)


def active_connections() -> list[EnterpriseWsConnection]:
    return list(_CONNECTIONS.values())


def connection_snapshot() -> list[dict[str, Any]]:
    return [
        {
            "connection_id": conn.connection_id,
            "user_id": conn.user_id,
            "username": conn.username,
            "is_admin": conn.is_admin,
            "path": conn.path,
            "client_id": conn.client_id,
            "connected_at": conn.connected_at,
            "last_seen_at": conn.last_seen_at,
        }
        for conn in active_connections()
    ]


def reset_for_tests() -> None:
    _CONNECTIONS.clear()
    _CLIENT_USERS.clear()


def parse_ws_message(raw: Any) -> tuple[dict[str, Any] | None, str]:
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)
    try:
        data = json.loads(text)
    except Exception:
        return None, text
    return data if isinstance(data, dict) else None, text


def _resource_owner_allows(user_id: str, payload: Any) -> bool:
    urls = protected_resource_urls(payload)
    if not urls:
        return False
    saw_owned = False
    for resource_url in urls:
        owner = edb.get_resource_owner(resource_url)
        if owner != user_id:
            return False
        saw_owned = True
    return saw_owned


def _history_owner_allows(user_id: str, payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    return edb.get_history_owner(history_id_for_record(payload)) == user_id


def _task_owner_allows(user_id: str, payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    task_id = str(payload.get("task_id") or payload.get("request_id") or payload.get("prompt_id") or "").strip()
    if not task_id:
        return False
    return edb.get_canvas_image_task_owner(task_id) == user_id


def _client_id_unique_to_user(client_id: str, user_id: str) -> bool:
    if not client_id or not user_id:
        return False
    users = _CLIENT_USERS.get(client_id) or set()
    return users == {user_id}


def should_forward_ws_event(connection: EnterpriseWsConnection, message: Mapping[str, Any]) -> bool:
    event_type = str(message.get("type") or "").strip()
    if not event_type:
        return bool(connection.is_admin)

    if event_type in {"pong", "stats"}:
        return True

    if connection.is_admin:
        return True

    user_id = connection.user_id
    if not user_id:
        return False

    if event_type == "canvas_updated":
        canvas_id = str(message.get("canvas_id") or "").strip()
        return bool(canvas_id and edb.get_canvas_owner(canvas_id) == user_id)

    if event_type == "asset_library_updated":
        return str(message.get("enterprise_user_id") or "") == user_id

    if event_type == "new_image":
        if str(message.get("enterprise_user_id") or "") == user_id:
            return True
        payload = message.get("data")
        if _resource_owner_allows(user_id, payload):
            return True
        if _history_owner_allows(user_id, payload):
            return True
        if _task_owner_allows(user_id, payload):
            return True
        return False

    if event_type == "cloud_status":
        return _client_id_unique_to_user(connection.client_id, user_id)

    if event_type in _SENSITIVE_EVENT_TYPES:
        return False

    return True


def should_forward_raw_message(connection: EnterpriseWsConnection, raw: Any) -> tuple[bool, str]:
    message, text = parse_ws_message(raw)
    if message is None:
        return bool(connection.is_admin), text
    return should_forward_ws_event(connection, message), text


def _event_fingerprint(message: Mapping[str, Any]) -> str:
    event_type = str(message.get("type") or "").strip()
    if not event_type:
        return ""
    if event_type == "new_image":
        data = message.get("data")
        if isinstance(data, Mapping):
            return f"new_image:{history_id_for_record(data)}"
    if event_type == "canvas_updated":
        return f"canvas_updated:{message.get('canvas_id') or ''}:{message.get('updated_at') or ''}"
    if event_type == "asset_library_updated":
        return f"asset_library_updated:{message.get('updated_at') or ''}"
    if event_type == "cloud_status":
        return f"cloud_status:{message.get('task_id') or ''}:{message.get('status') or ''}:{message.get('progress') or ''}"
    return f"{event_type}:{json.dumps(message, ensure_ascii=False, sort_keys=True, default=str)[:500]}"


def _remember_event(connection: EnterpriseWsConnection, message: Mapping[str, Any]) -> bool:
    fingerprint = _event_fingerprint(message)
    if not fingerprint:
        return True
    now = int(time.time() * 1000)
    cutoff = now - 10000
    for key, ts in list(connection.recent_event_ids.items()):
        if ts < cutoff:
            connection.recent_event_ids.pop(key, None)
    if fingerprint in connection.recent_event_ids:
        return False
    connection.recent_event_ids[fingerprint] = now
    return True


async def send_to_connection(connection: EnterpriseWsConnection, message: Mapping[str, Any] | str) -> bool:
    if isinstance(message, str):
        text = message
        parsed, _raw = parse_ws_message(text)
        if parsed is not None and not _remember_event(connection, parsed):
            return False
    else:
        if not _remember_event(connection, message):
            return False
        text = json.dumps(message, ensure_ascii=False)
    try:
        async with connection.lock:
            await connection.websocket.send_text(text)
        connection.last_seen_at = int(time.time() * 1000)
        return True
    except Exception as exc:
        print(f"[enterprise-ws] send failed user={connection.user_id} client={connection.client_id} error={exc}")
        forget_connection(connection)
        return False


async def send_to_user(
    user_id: str,
    message: Mapping[str, Any],
    *,
    include_admin: bool = True,
    client_id: str = "",
) -> int:
    wanted_user_id = str(user_id or "").strip()
    wanted_client_id = str(client_id or "").strip()
    if not wanted_user_id:
        return 0
    sent = 0
    for conn in active_connections():
        if conn.user_id == wanted_user_id or (include_admin and conn.is_admin):
            if wanted_client_id and conn.client_id != wanted_client_id and not conn.is_admin:
                continue
            if await send_to_connection(conn, message):
                sent += 1
    return sent


async def broadcast_asset_library_updated(user: Mapping[str, Any], updated_at: Any = 0) -> int:
    user_id = user_id_from_user(user)
    message = {
        "type": "asset_library_updated",
        "updated_at": int(float(updated_at or 0)) or int(time.time() * 1000),
        "enterprise_synthetic": True,
        "enterprise_user_id": user_id,
    }
    return await send_to_user(user_id, message, include_admin=True)


async def broadcast_new_image(user: Mapping[str, Any], payload: Any) -> int:
    if not isinstance(payload, Mapping):
        return 0
    user_id = user_id_from_user(user)
    message = {
        "type": "new_image",
        "data": dict(payload),
        "enterprise_synthetic": True,
        "enterprise_user_id": user_id,
    }
    return await send_to_user(user_id, message, include_admin=True)


def is_asset_library_write(path: str, method: str) -> bool:
    if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    normalized = str(path or "").strip().lstrip("/")
    return normalized in _ASSET_LIBRARY_WRITE_PATHS or any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _ASSET_LIBRARY_WRITE_PREFIXES
    )


def is_generation_response(path: str, method: str, data: Any) -> bool:
    if method.upper() not in {"POST", "GET"} or not isinstance(data, Mapping):
        return False
    normalized = str(path or "").strip().lstrip("/")
    if normalized in _GENERATION_RESPONSE_PATHS:
        return bool(data.get("images") or data.get("videos") or data.get("outputs") or protected_resource_urls(data))
    if normalized.startswith("api/canvas-image-tasks/") or normalized.startswith("api/canvas-comfy-tasks/"):
        return str(data.get("status") or "").lower() == "succeeded"
    return False
