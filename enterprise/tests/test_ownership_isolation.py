"""
Non-destructive ownership isolation checks.

This script uses a temporary SQLite database and temporary canvas/conversation
files. It does not read or write the real runtime database or user data.

Run from the repository root:

    python .\enterprise\tests\test_ownership_isolation.py
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
    os.environ.setdefault("JWT_SECRET", "test-secret-for-ownership-isolation-1234567890")
    os.environ.setdefault("ADMIN_USERNAME", "admin")
    os.environ.setdefault("ADMIN_PASSWORD", "change-me-in-tests")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


async def _run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-ownership-") as raw_tmp:
        tmp = Path(raw_tmp)
        _prepare_env(tmp)

        from enterprise import db as edb
        from enterprise import interceptors

        canvas_dir = tmp / "canvases"
        conversation_dir = tmp / "conversations"
        canvas_dir.mkdir()
        conversation_dir.mkdir()
        interceptors._CANVAS_DATA_DIR = canvas_dir
        interceptors._CONVERSATION_DATA_DIR = conversation_dir
        edb._conversation_root = lambda: str(conversation_dir)

        edb.init_db()
        user_a = edb.create_user("user_a", "password-a", "User A", False)
        user_b = edb.create_user("user_b", "password-b", "User B", False)
        admin = edb.get_user_by_username("admin")

        actor_a = {"user_id": user_a["id"], "username": "user_a", "is_admin": False}
        actor_b = {"user_id": user_b["id"], "username": "user_b", "is_admin": False}
        actor_admin = {"user_id": admin["id"], "username": "admin", "is_admin": True}

        _write_json(canvas_dir / "canvas_a.json", {
            "id": "canvas_a",
            "title": "Canvas A",
            "nodes": [{"image": "/assets/output/a.png"}],
        })
        _write_json(canvas_dir / "canvas_b.json", {
            "id": "canvas_b",
            "title": "Canvas B",
            "nodes": [{"image": "/assets/output/b.png"}],
        })
        _write_json(canvas_dir / "legacy_canvas.json", {
            "id": "legacy_canvas",
            "title": "Legacy Canvas",
            "nodes": [{"image": "/assets/output/legacy.png"}],
        })

        edb.set_canvas_owner("canvas_a", user_a["id"])
        edb.set_canvas_owner("canvas_b", user_b["id"])

        assert interceptors.can_access_canvas(actor_a, "canvas_a")
        assert not interceptors.can_access_canvas(actor_a, "canvas_b")
        assert not interceptors.can_access_canvas(actor_a, "legacy_canvas")
        assert interceptors.can_access_canvas(actor_admin, "legacy_canvas")

        canvas_payload = {
            "canvases": [
                {"id": "canvas_a", "title": "Canvas A"},
                {"id": "canvas_b", "title": "Canvas B"},
                {"id": "legacy_canvas", "title": "Legacy Canvas"},
            ]
        }
        interceptors.filter_canvas_list(actor_a, canvas_payload)
        assert [item["id"] for item in canvas_payload["canvases"]] == ["canvas_a"]

        _write_json(conversation_dir / user_a["id"] / "conv_a.json", {
            "id": "conv_a",
            "title": "Conversation A",
            "messages": [{"content": "a", "attachments": [{"url": "/assets/output/chat-a.png"}]}],
        })
        _write_json(conversation_dir / user_b["id"] / "conv_b.json", {
            "id": "conv_b",
            "title": "Conversation B",
            "messages": [{"content": "b"}],
        })
        _write_json(conversation_dir / "legacy-user" / "legacy_conv.json", {
            "id": "legacy_conv",
            "title": "Legacy Conversation",
            "messages": [{"content": "legacy"}],
        })

        edb.set_conversation_owner("conv_a", user_a["id"])
        edb.set_conversation_owner("conv_b", user_b["id"])

        assert interceptors.can_access_conversation(actor_a, "conv_a")
        assert not interceptors.can_access_conversation(actor_a, "conv_b")
        assert not interceptors.can_access_conversation(actor_a, "legacy_conv")
        assert interceptors.can_access_conversation(actor_admin, "legacy_conv")

        conversation_payload = {"conversations": [{"id": "conv_a"}, {"id": "conv_b"}, {"id": "legacy_conv"}]}
        interceptors.filter_conversation_list(actor_a, conversation_payload)
        assert [item["id"] for item in conversation_payload["conversations"]] == ["conv_a"]

        err = await interceptors.pre_process("api/canvases/canvas_b", "GET", actor_a)
        assert err is not None and err.status_code == 404
        err = await interceptors.pre_process("api/conversations/conv_b", "GET", actor_a)
        assert err is not None and err.status_code == 404

        assert interceptors.can_access_resource(actor_a, "/assets/output/a.png")
        assert not interceptors.can_access_resource(actor_a, "/assets/output/b.png")
        assert not interceptors.can_access_resource(actor_a, "/assets/output/unknown.png")
        assert interceptors.can_access_resource(actor_admin, "/assets/output/unknown.png")

        edb.record_resource_owner(user_a["id"], "/assets/input/upload-a.png", "test")
        assert interceptors.can_access_resource(actor_a, "/assets/input/upload-a.png")
        assert not interceptors.can_access_resource(actor_b, "/assets/input/upload-a.png")

        error_payload = b'{"error":"upstream denied","canvases":[{"id":"canvas_a"}]}'
        body, headers = await interceptors.post_process(
            "api/canvases",
            "GET",
            404,
            error_payload,
            "application/json",
            actor_a,
        )
        assert body == error_payload
        assert headers == {}


if __name__ == "__main__":
    asyncio.run(_run_checks())
    print("ownership isolation checks passed")
