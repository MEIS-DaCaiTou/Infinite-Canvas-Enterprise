"""Portable HTTP/WS pause for a pending offline installation transaction.

The marker is a signal to refuse business requests, never an authorization to
mutate files. Health probes remain available to the shared update engine.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class InstallMaintenanceMiddleware:
    def __init__(self, app, *, state_root):
        self.app = app
        self.marker = Path(state_root) / "install-upgrade-active.json"

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        try:
            active = os.path.lexists(self.marker)
        except OSError:
            active = True
        if not active or (kind == "http" and scope.get("method") == "GET"
                          and scope.get("path") in {"/enterprise/health", "/enterprise/live"}):
            return await self.app(scope, receive, send)
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1013, "reason": "installation maintenance"})
            return
        body = json.dumps({"code": "INSTALL_UPGRADE_MAINTENANCE", "message": "安装维护尚未完成，业务访问暂时暂停；请完成维护或显式恢复。"},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        await send({"type": "http.response.start", "status": 503,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"), (b"cache-control", b"no-store"), (b"retry-after", b"5")]})
        await send({"type": "http.response.body", "body": body})
