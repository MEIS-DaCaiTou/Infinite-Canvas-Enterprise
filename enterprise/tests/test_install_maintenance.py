"""Pending offline installation must refuse business mutations, including WS."""
import asyncio
import json

import pytest

from enterprise.runtime.install_maintenance import InstallMaintenanceMiddleware


@pytest.mark.parametrize("scope", [
    {"type": "http", "method": "POST", "path": "/api/generate"},
    {"type": "http", "method": "GET", "path": "/api/assets"},
    {"type": "http", "method": "POST", "path": "/enterprise/health"},
    {"type": "websocket", "path": "/ws"},
])
def test_pending_operation_never_reaches_business_handler(tmp_path, scope):
    (tmp_path / "install-upgrade-active.json").write_bytes(b"even an unreadable marker blocks")
    events, calls = [], []
    async def handler(*args):
        calls.append(args)
    async def receive():
        return {"type": "http.request", "body": b""}
    async def send(value):
        events.append(value)
    asyncio.run(InstallMaintenanceMiddleware(handler, state_root=tmp_path)(scope, receive, send))
    assert not calls
    if scope["type"] == "websocket":
        assert events == [{"type": "websocket.close", "code": 1013, "reason": "installation maintenance"}]
    else:
        assert events[0]["status"] == 503
        assert (b"cache-control", b"no-store") in events[0]["headers"]
        assert json.loads(events[1]["body"])["code"] == "INSTALL_UPGRADE_MAINTENANCE"


@pytest.mark.parametrize("active,path", [(True, "/enterprise/health"), (True, "/enterprise/live"), (False, "/api/generate")])
def test_health_and_post_finalization_business_access_reach_existing_handler(tmp_path, active, path):
    if active:
        (tmp_path / "install-upgrade-active.json").write_bytes(b"pending")
    calls = []
    async def handler(scope, *_):
        calls.append(scope)
    scope = {"type": "http", "method": "GET", "path": path}
    asyncio.run(InstallMaintenanceMiddleware(handler, state_root=tmp_path)(scope, None, None))
    assert calls == [scope]
