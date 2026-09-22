"""SEC-P0 browser/request boundary regression tests.

All HTTP calls stay in-process through ASGITransport.  Files are temporary and
no production database, network endpoint, or installed Runtime is touched.
"""
from __future__ import annotations

import ast
import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.responses import JSONResponse

from enterprise import gateway
from enterprise import interceptors
from enterprise import route_policy
from enterprise import ws as enterprise_ws


ADMIN = {
    "id": "admin-id",
    "user_id": "admin-id",
    "username": "admin",
    "role": "admin",
    "is_admin": True,
}
USER = {
    "id": "user-b",
    "user_id": "user-b",
    "username": "user-b",
    "role": "user",
    "is_admin": False,
}


def _run(coro):
    return asyncio.run(coro)


def _request_stub(*, address: str = "127.0.0.1"):
    return SimpleNamespace(client=SimpleNamespace(host=address))


def _main_route_inventory() -> set[tuple[str, str]]:
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "main.py").read_text(encoding="utf-8"))
    inventory: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
            ):
                continue
            inventory.add((decorator.func.attr.upper(), str(decorator.args[0].value).lstrip("/")))
    return inventory


def test_route_registry_is_exactly_bound_to_main_decorators() -> None:
    assert set(route_policy.registered_upstream_routes()) == _main_route_inventory()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "api/app-info"),
        ("HEAD", "api/app-info"),
        ("GET", "api/canvases/canvas-1/meta"),
        ("PUT", "api/workflows/folder/name/config"),
        ("GET", ""),
    ],
)
def test_registered_routes_are_allowed(method: str, path: str) -> None:
    assert route_policy.is_allowed_upstream_route(method, path) is True


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "api/not-real"),
        ("POST", "api/app-info"),
        ("GET", "api/not-real.js"),
        ("GET", "api//app-info"),
        ("GET", "api/../app-info"),
        ("GET", "api/%2e%2e/app-info"),
        ("GET", "api/%252e%252e/app-info"),
        ("GET", "api\\app-info"),
        ("OPTIONS", "api/app-info"),
    ],
)
def test_unknown_or_ambiguous_routes_fail_closed(method: str, path: str) -> None:
    assert route_policy.is_allowed_upstream_route(method, path) is False


def test_only_reviewed_public_static_and_protected_resource_namespaces_are_allowed() -> None:
    assert route_policy.is_allowed_public_static_path("static/js/app.js") is True
    assert route_policy.is_allowed_public_static_path("vendor/lib.js") is True
    assert route_policy.is_allowed_public_static_path("api/future.js") is False
    assert route_policy.is_allowed_public_static_path("static/%2e%2e/main.py") is False
    assert route_policy.is_allowed_protected_resource_path("GET", "assets/input/a.png") is True
    assert route_policy.is_allowed_protected_resource_path("POST", "assets/input/a.png") is False
    assert route_policy.is_allowed_protected_resource_path("GET", "assets/unknown/a.png") is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/", "/"),
        ("/enterprise/profile?tab=security#password", "/enterprise/profile?tab=security#password"),
        ("//evil.example", "/"),
        ("https://evil.example", "/"),
        ("javascript:alert(1)", "/"),
        ("\\evil.example", "/"),
        ("/%2f%2fevil.example", "/"),
        ("/%252f%252fevil.example", "/"),
        ("/ok\r\nLocation: https://evil.example", "/"),
    ],
)
def test_login_next_url_is_local_and_bounded(value: str, expected: str) -> None:
    assert gateway._safe_next_url(value) == expected


def test_origin_policy_is_exact_and_does_not_trust_forwarded_headers() -> None:
    same = {"host": "canvas.example:8443", "origin": "https://canvas.example:8443"}
    cross = {"host": "canvas.example:8443", "origin": "https://evil.example"}
    forged = {
        "host": "canvas.example:8443",
        "origin": "https://evil.example",
        "x-forwarded-host": "evil.example",
        "x-forwarded-proto": "https",
    }
    assert gateway._same_origin(same, "https", allow_missing=False) is True
    assert gateway._same_origin(cross, "https", allow_missing=False) is False
    assert gateway._same_origin(forged, "https", allow_missing=False) is False
    assert gateway._same_origin({"host": "canvas.example"}, "https", allow_missing=False) is False


def test_websocket_boundary_allows_only_stats_same_origin_and_ping() -> None:
    websocket = SimpleNamespace(
        headers={"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"},
        url=SimpleNamespace(scheme="ws"),
    )
    cross_site = SimpleNamespace(
        headers={"host": "127.0.0.1:8000", "origin": "https://evil.example"},
        url=SimpleNamespace(scheme="ws"),
    )
    assert route_policy.is_allowed_websocket_path("stats") is True
    assert route_policy.is_allowed_websocket_path("future") is False
    assert gateway._websocket_origin_allowed(websocket) is True
    assert gateway._websocket_origin_allowed(cross_site) is False
    assert enterprise_ws.should_forward_client_message("ping") == (True, "ping")
    assert enterprise_ws.should_forward_client_message("admin") == (False, "admin")


def test_unknown_server_events_fail_closed_for_user_and_admin() -> None:
    user_conn = enterprise_ws.EnterpriseWsConnection(None, "user-b", "user-b", False, "stats", "client-b")
    admin_conn = enterprise_ws.EnterpriseWsConnection(None, "admin-id", "admin", True, "stats", "client-admin")
    for connection in (user_conn, admin_conn):
        assert enterprise_ws.should_forward_ws_event(connection, {"type": "future_event"}) is False
        assert enterprise_ws.should_forward_ws_event(connection, {}) is False
        assert enterprise_ws.should_forward_raw_message(connection, "not-json")[0] is False


def test_invalid_websocket_client_message_cancels_peer_and_unregisters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBrowserWebSocket:
        headers = {"host": "canvas.local", "origin": "http://canvas.local"}
        url = SimpleNamespace(scheme="ws")
        cookies = {"enterprise_token": "fixture-token"}
        scope = {"query_string": b"client_id=browser-a"}
        query_params = {"client_id": "browser-a"}

        def __init__(self) -> None:
            self.accepted = False
            self.close_codes: list[int] = []

        async def accept(self) -> None:
            self.accepted = True

        async def close(self, code: int) -> None:
            self.close_codes.append(code)

        async def iter_text(self):
            yield "not-allowed"

    class FakeUpstream:
        def __init__(self) -> None:
            self.cancelled = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            raise StopAsyncIteration

        async def send(self, _message: str) -> None:
            raise AssertionError("invalid client message must not reach upstream")

    class FakeConnectContext:
        def __init__(self, upstream: FakeUpstream) -> None:
            self.upstream = upstream
            self.exited = False

        async def __aenter__(self):
            return self.upstream

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            self.exited = True

    async def no_stats() -> int:
        return 0

    import websockets

    enterprise_ws.reset_for_tests()
    browser = FakeBrowserWebSocket()
    upstream = FakeUpstream()
    context = FakeConnectContext(upstream)
    monkeypatch.setattr(gateway, "verify_token", lambda token: USER)
    monkeypatch.setattr(enterprise_ws, "broadcast_stats", no_stats)
    monkeypatch.setattr(websockets, "connect", lambda _url: context)

    _run(gateway.ws_proxy(browser, "stats"))

    assert browser.accepted is True
    assert browser.close_codes == [1008]
    assert upstream.cancelled is True
    assert context.exited is True
    assert enterprise_ws.active_connections() == []


def test_enterprise_static_stays_within_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "enterprise-static"
    root.mkdir()
    allowed = root / "safe.css"
    allowed.write_text("body{}", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(gateway, "ENTERPRISE_STATIC_DIR", root)

    ok = _run(gateway.enterprise_static("safe.css"))
    assert ok.status_code == 200
    for escape in ("../secret.txt", "%2e%2e/secret.txt", "%252e%252e/secret.txt", "..\\secret.txt"):
        denied = _run(gateway.enterprise_static(escape))
        assert denied.status_code == 404


def test_login_rate_limit_uses_username_and_address_with_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(gateway, "_login_clock", lambda: now[0])
    gateway._LOGIN_RATE_EVENTS.clear()
    request = _request_stub(address="10.0.0.9")
    for _ in range(gateway._LOGIN_USERNAME_FAILURE_LIMIT):
        retry_after, reserved_at = gateway._reserve_login_attempt(request, "Alice")
        assert retry_after == 0 and reserved_at is not None
    assert gateway._login_retry_after(request, "alice") > 0
    assert "Alice" not in repr(gateway._LOGIN_RATE_EVENTS)
    now[0] += gateway._LOGIN_RATE_WINDOW_SECONDS + 1
    assert gateway._login_retry_after(request, "alice") == 0


def test_login_rate_limit_reservation_is_atomic_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway._LOGIN_RATE_EVENTS.clear()
    auth_calls = 0
    auth_lock = threading.Lock()
    admitted = threading.Event()

    def fail_auth(_username: str, _password: str):
        nonlocal auth_calls
        with auth_lock:
            auth_calls += 1
            if auth_calls == gateway._LOGIN_USERNAME_FAILURE_LIMIT:
                admitted.set()
        assert admitted.wait(timeout=2)
        return None

    monkeypatch.setattr(gateway, "authenticate", fail_auth)

    async def exercise():
        transport = httpx.ASGITransport(app=gateway.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://canvas.local") as client:
            return await asyncio.gather(*(
                client.post(
                    "/enterprise/login",
                    headers={"Origin": "http://canvas.local"},
                    json={"username": "same-user", "password": "wrong"},
                )
                for _ in range(gateway._LOGIN_USERNAME_FAILURE_LIMIT * 2)
            ))

    responses = _run(exercise())
    assert auth_calls == gateway._LOGIN_USERNAME_FAILURE_LIMIT
    assert [response.status_code for response in responses].count(401) == gateway._LOGIN_USERNAME_FAILURE_LIMIT
    assert [response.status_code for response in responses].count(429) == gateway._LOGIN_USERNAME_FAILURE_LIMIT


def test_login_response_sanitizes_next_and_sets_secure_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway._LOGIN_RATE_EVENTS.clear()
    monkeypatch.setattr(gateway, "authenticate", lambda username, password: ADMIN)
    monkeypatch.setattr(gateway, "create_token", lambda user_id: "fixture-token")
    monkeypatch.setattr(gateway, "log_action", lambda *args, **kwargs: None)

    async def exercise():
        transport = httpx.ASGITransport(app=gateway.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://canvas.example") as client:
            response = await client.post(
                "/enterprise/login?next=%2F%2Fevil.example",
                headers={"Origin": "https://canvas.example"},
                json={"username": "admin", "password": "fixture"},
            )
            return response

    response = _run(exercise())
    assert response.status_code == 200
    assert response.json()["next"] == "/"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" in cookie


def test_post_logout_uses_see_other_and_clears_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway, "verify_token", lambda token: ADMIN)

    async def exercise():
        transport = httpx.ASGITransport(app=gateway.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://canvas.local",
            follow_redirects=False,
        ) as client:
            client.cookies.set(
                "enterprise_token",
                "fixture-token",
                domain="canvas.local",
                path="/",
            )
            response = await client.post(
                "/enterprise/logout",
                headers={"Origin": "http://canvas.local"},
            )
            login_page = await client.get(response.headers["location"])
            return response, login_page

    response, login_page = _run(exercise())
    assert response.status_code == 303
    assert response.headers["location"] == "/enterprise/login"
    assert "enterprise_token=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert login_page.status_code == 200


def test_cross_site_login_and_cookie_write_are_rejected_but_bearer_cli_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded: list[tuple[str, str]] = []
    monkeypatch.setattr(gateway, "verify_token", lambda token: ADMIN)

    async def allow_pre_process(*args, **kwargs):
        return None

    async def fake_forward(path, request, user, **kwargs):
        forwarded.append((request.method, path))
        return JSONResponse({"forwarded": True})

    monkeypatch.setattr(gateway, "pre_process", allow_pre_process)
    monkeypatch.setattr(gateway, "_forward", fake_forward)

    async def exercise():
        transport = httpx.ASGITransport(app=gateway.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://canvas.local") as client:
            cross_login = await client.post(
                "/enterprise/login",
                headers={"Origin": "https://evil.example"},
                json={"username": "x", "password": "y"},
            )
            client.cookies.set("enterprise_token", "cookie-token")
            missing_origin = await client.post("/api/projects", json={})
            cross_cookie = await client.post(
                "/api/projects", headers={"Origin": "https://evil.example"}, json={}
            )
            client.cookies.clear()
            bearer = await client.post(
                "/api/projects",
                headers={"Authorization": "Bearer cli-token", "Origin": "https://evil.example"},
                json={},
            )
            return cross_login, missing_origin, cross_cookie, bearer

    cross_login, missing_origin, cross_cookie, bearer = _run(exercise())
    assert cross_login.status_code == 403
    assert missing_origin.status_code == 403
    assert cross_cookie.status_code == 403
    assert bearer.status_code == 200
    assert forwarded == [("POST", "api/projects")]


def test_unknown_route_never_forwards_and_known_admin_route_does(monkeypatch: pytest.MonkeyPatch) -> None:
    forwarded: list[str] = []
    monkeypatch.setattr(gateway, "verify_token", lambda token: ADMIN)

    async def allow_pre_process(*args, **kwargs):
        return None

    async def fake_forward(path, request, user, **kwargs):
        forwarded.append(path)
        return JSONResponse({"forwarded": True})

    monkeypatch.setattr(gateway, "pre_process", allow_pre_process)
    monkeypatch.setattr(gateway, "_forward", fake_forward)

    async def exercise():
        transport = httpx.ASGITransport(app=gateway.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://canvas.local") as client:
            headers = {"Authorization": "Bearer fixture"}
            unknown = await client.get("/api/future-route", headers=headers)
            disguised = await client.get("/api/future-route.js", headers=headers)
            known = await client.get("/api/providers", headers=headers)
            return unknown, disguised, known

    unknown, disguised, known = _run(exercise())
    assert unknown.status_code == 404
    assert disguised.status_code == 404
    assert known.status_code == 200
    assert forwarded == ["api/providers"]


def test_existing_project_owner_guard_still_blocks_normal_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(interceptors.edb, "get_project_owner", lambda project_id: "user-a")
    denied = interceptors._pre_process_sync("api/projects/project-a", "DELETE", USER)
    assert denied is not None and denied.status_code == 404
    allowed = interceptors._pre_process_sync("api/projects/project-a", "DELETE", ADMIN)
    assert allowed is None
