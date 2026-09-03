"""Incident regressions. All databases/process state are temporary or mocked."""
import asyncio
import json
import sqlite3
import threading
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from enterprise.resource_index import ResourceReferenceIndex
from enterprise.runtime import health
from enterprise.tests.test_stab_1_supervisor_logging import build_supervisor, _configure_failed_health_probe


def test_gateway_bootstrap_does_not_bypass_restart_deadline(tmp_path):
    supervisor = build_supervisor(tmp_path / "runtime")
    supervisor.roles["upstream"].state = "healthy"
    gateway = supervisor.roles["gateway"]
    gateway.state = "restarting"
    gateway.restart_at = time.monotonic() + 30
    with patch.object(supervisor, "_handle_commands"), patch.object(supervisor, "_persist_state"), \
         patch.object(supervisor, "_check_role_health"), patch.object(supervisor, "_start_role") as start:
        supervisor._tick()
        start.assert_not_called()
        gateway.restart_at = time.monotonic() - 1
        supervisor._tick()
        start.assert_called_once_with("gateway")


def test_direct_start_also_respects_backoff(tmp_path):
    supervisor = build_supervisor(tmp_path / "runtime")
    supervisor.roles["gateway"].restart_at = time.monotonic() + 30
    with patch("enterprise.runtime.supervisor.start_process") as start:
        supervisor._start_role("gateway")
        start.assert_not_called()


@pytest.mark.parametrize("state", ["degraded", "crash_loop", "restarting"])
def test_gateway_bootstrap_does_not_restart_blocked_role(tmp_path, state):
    supervisor = build_supervisor(tmp_path / "runtime")
    supervisor.roles["upstream"].state = "healthy"
    supervisor.roles["gateway"].state = state
    with patch.object(supervisor, "_handle_commands"), patch.object(supervisor, "_persist_state"), \
         patch.object(supervisor, "_check_role_health"), patch.object(supervisor, "_start_role") as start:
        supervisor._tick()
        start.assert_not_called()


def test_readiness_timeout_is_not_a_liveness_failure(tmp_path):
    supervisor = build_supervisor(tmp_path / "runtime")
    _configure_failed_health_probe(supervisor, state="healthy", health_failures=0)
    with patch.object(supervisor, "_health_for", return_value=health.HealthResult(False, "readiness_timeout")), \
         patch.object(supervisor, "_stop_role") as stop:
        for _ in range(10):
            supervisor._check_role_health("gateway")
        stop.assert_not_called()
    assert supervisor.roles["gateway"].state == "degraded"
    assert supervisor.roles["gateway"].health_failures == 0


def test_startup_grace_is_not_shortened_by_steady_state_threshold(tmp_path):
    supervisor = build_supervisor(tmp_path / "runtime")
    _configure_failed_health_probe(supervisor, state="starting", health_failures=0)
    supervisor.roles["gateway"].started_at_monotonic = time.monotonic()
    with patch.object(supervisor, "_health_for", return_value=health.HealthResult(False, "listener_missing")), \
         patch.object(supervisor, "_stop_role") as stop:
        for _ in range(supervisor.config.health_failure_threshold + 2):
            supervisor._check_role_health("gateway")
        stop.assert_not_called()
    assert supervisor.roles["gateway"].state == "starting"


@pytest.mark.parametrize("alive", [True, False])
def test_health_probe_distinguishes_readiness_delay_from_hang(alive):
    timeout = (health.HealthResult(False, "read_timeout"), b"")
    live = (health.HealthResult(True, "http_ok", 200), b'{"gateway":"ok"}') if alive else timeout
    with patch.object(health, "_http_check", side_effect=[timeout, live]):
        result = health.gateway_health("127.0.0.1", 12345)
    assert result.category == ("readiness_timeout" if alive else "read_timeout")


def test_health_has_independent_pool_total_deadline_and_auth_bypass(monkeypatch):
    from enterprise import gateway
    async def run():
        async def slow(request):
            await asyncio.sleep(2)
            return httpx.Response(200)
        monkeypatch.setattr(gateway, "HEALTH_UPSTREAM_DEADLINE_SECONDS", 0.05)
        monkeypatch.setattr(gateway, "verify_token", MagicMock(side_effect=AssertionError("health used auth DB")))
        monkeypatch.setattr(gateway, "_http_client", MagicMock())
        async with httpx.AsyncClient(transport=httpx.MockTransport(slow), base_url="http://upstream") as probe:
            monkeypatch.setattr(gateway, "_health_client", probe)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://gateway") as client:
                live = await client.get("/enterprise/live", headers={"Authorization": "Bearer invalid"})
                assert live.status_code == 200
                degraded = await asyncio.wait_for(client.get("/enterprise/health"), timeout=0.5)
                assert degraded.status_code == 503
                assert degraded.json()["gateway"] == "ok"
                gateway._http_client.get.assert_not_called()
    asyncio.run(run())


def test_interceptor_work_does_not_block_asgi_loop(monkeypatch):
    from enterprise import interceptors, gateway
    entered = threading.Event()
    release = threading.Event()
    loop_thread = threading.get_ident()
    def slow(*args):
        assert threading.get_ident() != loop_thread
        entered.set()
        assert release.wait(3)
        return None
    monkeypatch.setattr(interceptors, "_pre_process_sync", slow)
    async def run():
        pending = asyncio.create_task(interceptors.pre_process("api/canvases", "GET", {}))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.001)
            assert (await asyncio.wait_for(gateway.liveness_check(), 0.2)).status_code == 200
        finally:
            release.set()
            await pending
    asyncio.run(run())


def test_post_process_broadcast_runs_on_original_loop(monkeypatch):
    from enterprise import interceptors
    thread = threading.get_ident()
    calls = []
    def sync(*args):
        assert threading.get_ident() != thread
        args[-1].append(("generation", {"image": "fixture"}))
        return b"{}", {}
    async def broadcast(user, data):
        assert threading.get_ident() == thread
        calls.append(data)
    monkeypatch.setattr(interceptors, "_post_process_sync", sync)
    monkeypatch.setattr(interceptors.enterprise_ws, "broadcast_new_image", broadcast)
    assert asyncio.run(interceptors.post_process("api/online-image", "POST", 200, b"{}", "application/json", {})) == (b"{}", {})
    assert calls == [{"image": "fixture"}]


def test_reference_cache_invalidates_edits_deletes_and_is_bounded(tmp_path):
    index = ResourceReferenceIndex(max_files=1)
    first = tmp_path / "a.json"
    first.write_text('{"id":"a","urls":["/old"]}', encoding="utf-8")
    load = MagicMock(side_effect=lambda p: json.loads(p.read_text(encoding="utf-8")))
    def matches(url):
        return index.matching_ids(tmp_path.glob("*.json"), url, load, lambda d: d["urls"])
    assert matches("/old") == {"a"}
    assert matches("/old") == {"a"}
    assert load.call_count == 1
    first.write_text('{"id":"a","urls":["/new-longer"]}', encoding="utf-8")
    assert matches("/old") == set()
    assert matches("/new-longer") == {"a"}
    first.unlink()
    assert matches("/new-longer") == set()
    for n in range(3):
        (tmp_path / f"{n}.json").write_text(json.dumps({"id": str(n), "urls": ["/new"]}), encoding="utf-8")
    assert matches("/new") == {"0", "1", "2"}
    assert len(index._entries) == 1


def test_cached_reference_does_not_cache_authorization(tmp_path, monkeypatch):
    from enterprise import interceptors
    (tmp_path / "a.json").write_text('{"id":"a","image":"/assets/input/test.png"}', encoding="utf-8")
    monkeypatch.setattr(interceptors, "_CANVAS_DATA_DIR", tmp_path)
    monkeypatch.setattr(interceptors, "_RESOURCE_REFERENCES", ResourceReferenceIndex())
    monkeypatch.setattr(interceptors.edb, "record_resource_owner", MagicMock())
    with patch.object(interceptors.edb, "get_canvas_owner", return_value="alice"):
        assert interceptors._resource_in_user_canvas_scope("alice", "/assets/input/test.png")
    with patch.object(interceptors.edb, "get_canvas_owner", return_value="bob"):
        assert not interceptors._resource_in_user_canvas_scope("alice", "/assets/input/test.png")


def test_oversize_reference_is_checked_but_not_cached(tmp_path):
    index = ResourceReferenceIndex(max_reference_chars=4)
    path = tmp_path / "a.json"
    path.write_text('{"id":"a","urls":["/long-resource"]}', encoding="utf-8")
    assert index.matching_ids([path], "/long-resource", lambda p: json.loads(p.read_text()), lambda d: d["urls"]) == {"a"}
    assert not index._entries
    assert index._reference_chars == 0


def test_resource_batch_uses_one_transaction_and_never_steals_owner(tmp_path, monkeypatch):
    from enterprise import db
    path = tmp_path / "test.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE user_resource_map (user_id TEXT, resource_url TEXT UNIQUE, source TEXT, created_at INTEGER)")
    connect = MagicMock(side_effect=lambda: sqlite3.connect(path))
    monkeypatch.setattr(db, "get_db", connect)
    assert db.record_resource_owners("alice", ["/a", "/b", "/a"]) == 2
    assert connect.call_count == 1
    assert db.record_resource_owners("bob", ["/a", "/c"]) == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT user_id FROM user_resource_map WHERE resource_url='/a'").fetchone()[0] == "alice"
