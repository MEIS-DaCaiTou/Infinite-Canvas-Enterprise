"""Portable HTTP/WS pause for installation and multi-hop maintenance.

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
        self.sequence_marker = Path(state_root) / "upgrade-sequence-active.json"

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        try:
            offline = os.path.lexists(self.marker)
            sequence = os.path.lexists(self.sequence_marker)
            active = offline or sequence
        except OSError:
            active = True
            offline = True
            sequence = True
        path = scope.get("path", "")
        # Recovery UI remains authenticated by the existing Gateway/API gates.
        # Allow only its read/status surface and sequence continuation controls.
        sequence_control = (not offline and sequence and kind == "http" and (
            path in {"/enterprise/login", "/enterprise/logout"}
            or (scope.get("method") == "GET" and (
                path in {"/enterprise/admin", "/enterprise/api/me", "/enterprise/api/users", "/enterprise/api/feature-flags"}
                or path.startswith("/enterprise-static/")
                or path.startswith("/enterprise/api/update-mvp/")))
            or (scope.get("method") == "POST" and path.startswith("/enterprise/api/update-mvp/jobs/")
                and path.endswith(("/sequence-resume", "/sequence-stop", "/recovery-clearance")))))
        if sequence_control:
            return await self.app(scope, receive, send)
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
