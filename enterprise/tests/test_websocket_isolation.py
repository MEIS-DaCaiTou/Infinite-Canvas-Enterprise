"""
Enterprise WebSocket broadcast isolation checks.

The test uses a temporary SQLite database and fake WebSocket objects.  It does
not start the gateway, touch static files, or write runtime assets.

Run from the repository root:

    python .\\enterprise\\tests\\test_websocket_isolation.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _prepare_env(tmp: Path) -> None:
    os.environ["DB_PATH"] = str(tmp / "enterprise.db")
    os.environ.setdefault("JWT_SECRET", "test-secret-for-websocket-isolation-1234567890")
    os.environ.setdefault("ADMIN_USERNAME", "admin")
    os.environ.setdefault("ADMIN_PASSWORD", "change-me-in-tests")


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_text(self, text: str) -> None:
        self.messages.append(text)

    def decoded(self) -> list[dict]:
        out = []
        for message in self.messages:
            out.append(json.loads(message))
        return out

    def clear(self) -> None:
        self.messages.clear()


class ClosedFakeWebSocket(FakeWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.send_attempts = 0

    async def send_text(self, text: str) -> None:
        self.send_attempts += 1
        raise RuntimeError(
            "Unexpected ASGI message 'websocket.send', "
            "after sending 'websocket.close' or response already completed."
        )


def _actor(user: dict, is_admin: bool = False) -> dict:
    return {
        "user_id": user["id"],
        "username": user["username"],
        "is_admin": is_admin,
    }


def _json_body(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


async def _post_process_json(interceptors, path: str, method: str, actor: dict, payload: dict, request_body=None):
    body, _headers = await interceptors.post_process(
        path,
        method,
        200,
        _json_body(payload),
        "application/json",
        actor,
        _json_body(request_body) if request_body is not None else None,
    )
    return json.loads(body.decode("utf-8"))


async def _run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-websocket-") as raw_tmp:
        tmp = Path(raw_tmp)
        _prepare_env(tmp)

        from enterprise import db as edb
        from enterprise.tests.ready_user_fixture import insert_ready_user_fixture
        from enterprise import interceptors
        from enterprise import ws as ews

        ews.reset_for_tests()
        interceptors._HISTORY_FILE = tmp / "history.json"
        interceptors._CANVAS_DATA_DIR = tmp / "canvases"
        interceptors._CONVERSATION_DATA_DIR = tmp / "conversations"
        interceptors._ASSET_LIBRARY_FILE = tmp / "asset_library.json"
        interceptors._CANVAS_DATA_DIR.mkdir()
        interceptors._CONVERSATION_DATA_DIR.mkdir()
        edb.CANVAS_DATA_DIR = str(interceptors._CANVAS_DATA_DIR)
        edb._conversation_root = lambda: str(interceptors._CONVERSATION_DATA_DIR)

        edb.init_db()
        user_a = insert_ready_user_fixture(edb.DB_PATH, username="ws_a", password_hash=edb._hash_password("password-a"), display_name="WS A")
        user_b = insert_ready_user_fixture(edb.DB_PATH, username="ws_b", password_hash=edb._hash_password("password-b"), display_name="WS B")
        admin = edb.get_user_by_username("admin")

        actor_a = _actor(user_a)
        actor_b = _actor(user_b)
        actor_admin = _actor(admin, True)

        ws_a = FakeWebSocket()
        ws_b = FakeWebSocket()
        ws_admin = FakeWebSocket()
        conn_a = ews.register_connection(ws_a, actor_a, "stats", "client-a")
        conn_b = ews.register_connection(ws_b, actor_b, "stats", "client-b")
        conn_admin = ews.register_connection(ws_admin, actor_admin, "stats", "admin-client")

        snapshot = ews.connection_snapshot()
        assert {item["user_id"] for item in snapshot} == {user_a["id"], user_b["id"], admin["id"]}
        assert any(item["client_id"] == "client-a" and not item["is_admin"] for item in snapshot)

        assert ews.build_upstream_ws_url(
            "http://127.0.0.1:3001",
            "stats",
            "client_id=client-a&x=1",
        ) == "ws://127.0.0.1:3001/ws/stats?client_id=client-a&x=1"

        assert ews.should_forward_ws_event(conn_a, {"type": "pong"}) is True
        assert ews.should_forward_ws_event(conn_b, {"type": "stats", "online_count": 2}) is True
        assert ews.visible_online_count() == 3

        assert await ews.send_to_connection(conn_a, {"type": "stats", "online_count": 3}) is True
        assert await ews.send_to_connection(conn_a, {"type": "stats", "online_count": 3}) is True
        assert [msg["type"] for msg in ws_a.decoded()] == ["stats", "stats"]
        ws_a.clear()

        closed_ws = ClosedFakeWebSocket()
        conn_closed = ews.register_connection(closed_ws, actor_a, "stats", "client-closed")
        assert ews.visible_online_count() == 4
        assert await ews.send_to_connection(conn_closed, {"type": "stats", "online_count": 4}) is False
        assert conn_closed.closed_at > 0
        assert all(item["connection_id"] != conn_closed.connection_id for item in ews.connection_snapshot())
        assert ews.visible_online_count() == 3
        assert closed_ws.send_attempts == 1
        ews.forget_connection(conn_closed)
        ews.forget_connection(conn_closed)
        ws_a.clear()
        ws_b.clear()
        ws_admin.clear()
        assert await ews.broadcast_stats() == 3
        assert closed_ws.send_attempts == 1
        assert [msg["type"] for msg in ws_a.decoded()] == ["stats"]
        assert [msg["type"] for msg in ws_b.decoded()] == ["stats"]
        assert [msg["type"] for msg in ws_admin.decoded()] == ["stats"]
        ws_a.clear()
        ws_b.clear()
        ws_admin.clear()

        edb.record_canvas_owner(user_a["id"], "canvas-a")
        canvas_msg = {"type": "canvas_updated", "canvas_id": "canvas-a", "updated_at": 123, "client_id": "client-a"}
        assert ews.should_forward_ws_event(conn_a, canvas_msg) is True
        assert ews.should_forward_ws_event(conn_b, canvas_msg) is False
        assert ews.should_forward_ws_event(conn_admin, canvas_msg) is True

        # Upstream global asset-library updates are ownerless; normal users do
        # not receive them.  The enterprise layer sends a safe synthetic event
        # after the current user's HTTP write succeeds.
        upstream_asset_msg = {"type": "asset_library_updated", "updated_at": 111}
        assert ews.should_forward_ws_event(conn_a, upstream_asset_msg) is False
        assert ews.should_forward_ws_event(conn_b, upstream_asset_msg) is False
        assert ews.should_forward_ws_event(conn_admin, upstream_asset_msg) is True

        await _post_process_json(
            interceptors,
            "api/asset-library/items",
            "POST",
            actor_a,
            {
                "item": {
                    "id": "item-a",
                    "name": "A Item",
                    "url": "/assets/library/a/item-a.png",
                    "kind": "image",
                },
                "library": {
                    "updated_at": 222,
                    "libraries": [
                        {
                            "id": "lib-a",
                            "categories": [
                                {
                                    "id": "cat-a",
                                    "items": [
                                        {
                                            "id": "item-a",
                                            "name": "A Item",
                                            "url": "/assets/library/a/item-a.png",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            },
            {"library_id": "lib-a", "category_id": "cat-a"},
        )
        assert any(msg["type"] == "asset_library_updated" for msg in ws_a.decoded())
        assert not ws_b.messages
        assert any(msg["type"] == "asset_library_updated" for msg in ws_admin.decoded())
        ws_a.clear()
        ws_admin.clear()

        # Upstream new_image is only forwarded when the payload owner can be
        # proven.  Unknown/unowned sensitive payloads are denied to normal users.
        ownerless_new_image = {
            "type": "new_image",
            "data": {
                "timestamp": 1,
                "type": "zimage",
                "prompt": "ownerless",
                "images": ["/assets/output/legacy.png"],
            },
        }
        assert ews.should_forward_ws_event(conn_a, ownerless_new_image) is False
        assert ews.should_forward_ws_event(conn_admin, ownerless_new_image) is False

        generated = {
            "timestamp": 2,
            "type": "zimage",
            "prompt": "A prompt",
            "images": ["/assets/output/a-result.png"],
            "task_id": "task-a",
        }
        raw_generated_message = {"type": "new_image", "data": generated}
        assert ews.should_forward_ws_event(conn_a, raw_generated_message) is False
        assert ews.should_forward_ws_event(conn_b, raw_generated_message) is False
        assert ews.should_forward_ws_event(conn_admin, raw_generated_message) is False

        await _post_process_json(interceptors, "api/online-image", "POST", actor_a, generated)
        assert edb.get_resource_owner("/assets/output/a-result.png") == user_a["id"]
        assert any(msg["type"] == "new_image" and msg["data"]["prompt"] == "A prompt" for msg in ws_a.decoded())
        assert not ws_b.messages
        assert any(msg["type"] == "new_image" and msg["data"]["prompt"] == "A prompt" for msg in ws_admin.decoded())

        admin_count = len(ws_admin.messages)
        duplicate_synthetic = {
            "type": "new_image",
            "data": dict(generated, timestamp=999),
            "enterprise_synthetic": True,
            "enterprise_user_id": user_a["id"],
        }
        assert await ews.send_to_connection(conn_admin, duplicate_synthetic) is False
        assert len(ws_admin.messages) == admin_count
        ws_a.clear()
        ws_admin.clear()

        owned_new_image = {
            "type": "new_image",
            "data": generated,
            "enterprise_synthetic": True,
            "enterprise_user_id": user_a["id"],
        }
        assert ews.should_forward_ws_event(conn_a, owned_new_image) is True
        assert ews.should_forward_ws_event(conn_b, owned_new_image) is False
        assert ews.should_forward_ws_event(conn_admin, owned_new_image) is True

        # cloud_status is client-routed but not owner-trusted.  A forged client
        # id shared by two users becomes ambiguous and is not delivered to a
        # normal user.
        assert ews.should_forward_ws_event(conn_a, {"type": "cloud_status", "task_id": "task-a", "status": "RUNNING"}) is True
        ws_b_spoof = FakeWebSocket()
        conn_b_spoof = ews.register_connection(ws_b_spoof, actor_b, "stats", "client-a")
        assert ews.should_forward_ws_event(conn_b_spoof, {"type": "cloud_status", "task_id": "task-a", "status": "RUNNING"}) is False
        assert ews.should_forward_ws_event(conn_a, {"type": "cloud_status", "task_id": "task-a", "status": "RUNNING"}) is False

        assert ews.should_forward_ws_event(conn_a, {"type": "task_updated", "task_id": "unknown"}) is False
        assert ews.should_forward_ws_event(conn_admin, {"type": "task_updated", "task_id": "unknown"}) is True

        ews.forget_connection(conn_b_spoof)
        ews.forget_connection(conn_a)
        ews.forget_connection(conn_b)
        ews.forget_connection(conn_admin)
        assert ews.connection_snapshot() == []


if __name__ == "__main__":
    asyncio.run(_run_checks())
    print("test_websocket_isolation: OK")
