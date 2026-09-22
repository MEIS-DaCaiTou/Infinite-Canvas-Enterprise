"""Explicit HTTP/WebSocket ingress registry for the enterprise gateway.

The upstream application is intentionally not imported here: importing ``main``
would execute application bootstrap code inside the gateway process.  Instead,
the gateway owns a small, auditable method/path registry.  A repository test
compares this registry with the decorators in ``main.py`` so newly added routes
remain unavailable until they are deliberately classified.
"""
from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import unquote


_EXACT_ROUTES: dict[str, frozenset[str]] = {
    "GET": frozenset({
        "", "api/app-info", "api/asset-library", "api/canvas-assets",
        "api/canvases", "api/canvases/trash", "api/check-update",
        "api/codex/status", "api/comfyui/instances", "api/config",
        "api/config/token", "api/conversations", "api/download-output",
        "api/gemini-cli/status", "api/history", "api/image-jpeg",
        "api/image-params", "api/jimeng/credit", "api/jimeng/login/status",
        "api/jimeng/status", "api/local-assets", "api/media-preview",
        "api/models", "api/projects", "api/prompt-libraries",
        "api/providers", "api/queue_status", "api/runninghub/app-info",
        "api/runninghub/query", "api/runninghub/workflow-info",
        "api/runninghub/workflows", "api/shared-folders",
        "api/smart-canvas/prompt-templates", "api/update-backups",
        "api/update-connectivity", "api/update-connectivity/probe",
        "api/view", "api/workflows",
    }),
    "PATCH": frozenset({
        "api/local-assets/caption", "api/local-assets/folders",
        "api/local-assets/items",
    }),
    "POST": frozenset({
        "api/ai/import-local-image", "api/ai/upload", "api/ai/upload-base64",
        "api/angle/generate", "api/angle/poll_status",
        "api/asset-library/categories", "api/asset-library/items",
        "api/asset-library/items/batch", "api/asset-library/items/classify",
        "api/asset-library/items/crop", "api/asset-library/items/delete",
        "api/asset-library/items/move", "api/asset-library/libraries",
        "api/asset-library/workflows/upload", "api/canvas-assets/check",
        "api/canvas-assets/download", "api/canvas-comfy-tasks",
        "api/canvas-image-tasks", "api/canvas-llm", "api/canvas-video",
        "api/canvas-workflows/export", "api/canvas-workflows/export-to-library",
        "api/canvas-workflows/import", "api/canvases", "api/chat",
        "api/chat/agent", "api/chat/stream", "api/cloud-video/upload",
        "api/codex/help", "api/comfyui/upload-base64", "api/conversations",
        "api/gemini-cli/help", "api/generate", "api/history/delete",
        "api/image-task-query", "api/jimeng/help", "api/jimeng/login/start",
        "api/jimeng/logout", "api/jimeng/query-media",
        "api/local-assets/caption", "api/local-assets/classify",
        "api/local-assets/delete", "api/local-assets/folders",
        "api/local-assets/import-urls", "api/local-assets/move",
        "api/local-assets/upload", "api/ms/generate", "api/online-image",
        "api/projects", "api/prompt-libraries",
        "api/prompt-libraries/categories", "api/prompt-libraries/items",
        "api/prompt-libraries/items/delete", "api/providers/fetch-models",
        "api/providers/probe-async", "api/providers/test-connection",
        "api/runninghub/submit", "api/runninghub/upload-asset",
        "api/runninghub/workflow-submit", "api/runninghub/workflows/fetch",
        "api/shared-folders", "api/shared-folders/import",
        "api/smart-canvas/group-export", "api/temp-sh/upload",
        "api/update-from-github", "api/update-rollback", "api/upload",
        "api/workflows", "generate",
    }),
    "PUT": frozenset({"api/comfyui/instances", "api/providers"}),
}

_TEMPLATE_ROUTES: tuple[tuple[str, str], ...] = (
    ("DELETE", "api/asset-library/categories/{category_id}"),
    ("DELETE", "api/asset-library/items/{item_id}"),
    ("DELETE", "api/asset-library/libraries/{library_id}"),
    ("DELETE", "api/canvases/{canvas_id}"),
    ("DELETE", "api/canvases/{canvas_id}/purge"),
    ("DELETE", "api/conversations/{conversation_id}"),
    ("DELETE", "api/projects/{project_id}"),
    ("DELETE", "api/prompt-libraries/categories/{category_id}"),
    ("DELETE", "api/prompt-libraries/items/{item_id}"),
    ("DELETE", "api/prompt-libraries/{library_id}"),
    ("DELETE", "api/runninghub/workflows/{workflow_id:path}"),
    ("DELETE", "api/shared-folders/{folder_id}"),
    ("DELETE", "api/workflows/{name:path}"),
    ("GET", "api/canvas-comfy-tasks/{task_id}"),
    ("GET", "api/canvas-image-tasks/{task_id}"),
    ("GET", "api/canvases/{canvas_id}"),
    ("GET", "api/canvases/{canvas_id}/meta"),
    ("GET", "api/conversations/{conversation_id}"),
    ("GET", "api/providers/{provider_id}/fetch-models"),
    ("GET", "api/runninghub/workflows/{workflow_id:path}"),
    ("GET", "api/shared-folders/{folder_id}/file"),
    ("GET", "api/shared-folders/{folder_id}/tree"),
    ("GET", "api/workflows/{name:path}"),
    ("PATCH", "api/asset-library/categories/{category_id}"),
    ("PATCH", "api/asset-library/items/{item_id}"),
    ("PATCH", "api/asset-library/libraries/{library_id}"),
    ("PATCH", "api/prompt-libraries/categories/{category_id}"),
    ("PATCH", "api/prompt-libraries/items/{item_id}"),
    ("PATCH", "api/prompt-libraries/{library_id}"),
    ("POST", "api/asset-library/items/{item_id}/avatar-status"),
    ("POST", "api/asset-library/items/{item_id}/register-avatar"),
    ("POST", "api/canvases/{canvas_id}/meta"),
    ("POST", "api/canvases/{canvas_id}/restore"),
    ("POST", "api/canvases/{canvas_id}/touch"),
    ("POST", "api/projects/{project_id}"),
    ("POST", "api/workflows/{name:path}/run"),
    ("PUT", "api/canvases/{canvas_id}"),
    ("PUT", "api/runninghub/workflows/{workflow_id:path}"),
    ("PUT", "api/workflows/{name:path}/config"),
)

_ALLOWED_WEBSOCKET_PATHS = frozenset({"stats"})
_PUBLIC_STATIC_PREFIXES = ("static/", "vendor/", "assets/images/")
_PROTECTED_RESOURCE_PREFIXES = (
    "assets/input/", "assets/output/", "assets/uploads/", "assets/library/", "output/",
)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _template_regex(template: str) -> re.Pattern[str]:
    parts: list[str] = []
    cursor = 0
    for match in re.finditer(r"\{[^{}:]+(?::(path))?\}", template):
        parts.append(re.escape(template[cursor:match.start()]))
        parts.append(r".+" if match.group(1) == "path" else r"[^/]+")
        cursor = match.end()
    parts.append(re.escape(template[cursor:]))
    return re.compile("^" + "".join(parts) + "$")


@lru_cache(maxsize=1)
def _compiled_templates() -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((method, _template_regex(template)) for method, template in _TEMPLATE_ROUTES)


def _decoded_path_is_safe(path: str) -> bool:
    value = str(path or "")
    for _ in range(3):
        if _CONTROL_RE.search(value) or "\\" in value or value.startswith("/") or "//" in value:
            return False
        if any(part in {".", ".."} for part in value.split("/")):
            return False
        decoded = unquote(value)
        if decoded == value:
            return True
        value = decoded
    return False


def is_allowed_upstream_route(method: str, path: str) -> bool:
    """Return True only for a reviewed upstream method/path pair."""
    normalized_method = str(method or "").upper()
    normalized_path = str(path or "")
    if normalized_method == "HEAD":
        normalized_method = "GET"
    if not _decoded_path_is_safe(normalized_path):
        return False
    if normalized_path in _EXACT_ROUTES.get(normalized_method, frozenset()):
        return True
    return any(
        route_method == normalized_method and pattern.fullmatch(normalized_path)
        for route_method, pattern in _compiled_templates()
    )


def is_allowed_websocket_path(path: str) -> bool:
    normalized = str(path or "").strip("/")
    return _decoded_path_is_safe(normalized) and normalized in _ALLOWED_WEBSOCKET_PATHS


def is_allowed_public_static_path(path: str) -> bool:
    normalized = str(path or "")
    if not _decoded_path_is_safe(normalized):
        return False
    return (
        normalized == "favicon.ico"
        or any(normalized.startswith(prefix) for prefix in _PUBLIC_STATIC_PREFIXES)
    )


def is_allowed_protected_resource_path(method: str, path: str) -> bool:
    normalized = str(path or "")
    return (
        str(method or "").upper() in {"GET", "HEAD"}
        and _decoded_path_is_safe(normalized)
        and any(normalized.startswith(prefix) for prefix in _PROTECTED_RESOURCE_PREFIXES)
    )


def registered_upstream_routes() -> tuple[tuple[str, str], ...]:
    """Expose the reviewed inventory for the source-drift contract test."""
    exact = tuple(
        (method, path)
        for method, paths in _EXACT_ROUTES.items()
        for path in paths
    )
    return tuple(sorted((*exact, *_TEMPLATE_ROUTES)))
