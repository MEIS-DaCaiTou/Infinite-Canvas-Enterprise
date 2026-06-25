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
from types import SimpleNamespace

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


async def _async_value(value):
    return value


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
        edb.CANVAS_DATA_DIR = str(canvas_dir)

        edb.init_db()
        user_a = edb.create_user("user_a", "password-a", "User A", False)
        user_b = edb.create_user("user_b", "password-b", "User B", False)
        admin = edb.get_user_by_username("admin")

        actor_a = {"user_id": user_a["id"], "username": "user_a", "is_admin": False}
        actor_b = {"user_id": user_b["id"], "username": "user_b", "is_admin": False}
        actor_admin = {"user_id": admin["id"], "username": "admin", "is_admin": True}
        legacy_output_url = "http://127.0.0.1:8000/assets/output/legacy-owned-absolute.png"
        admin_output_url = "http://127.0.0.1:8000/assets/output/admin-in-user-canvas.png"

        _write_json(canvas_dir / "canvas_a.json", {
            "id": "canvas_a",
            "title": "Canvas A",
            "project": "project_a",
            "nodes": [{"image": "/assets/output/a.png"}],
        })
        _write_json(canvas_dir / "canvas_b.json", {
            "id": "canvas_b",
            "title": "Canvas B",
            "project": "project_b",
            "nodes": [{"image": "/assets/output/b.png"}],
        })
        _write_json(canvas_dir / "canvas_foreign.json", {
            "id": "canvas_foreign",
            "title": "Foreign Canvas In Project A",
            "project": "project_a",
            "nodes": [],
        })
        _write_json(canvas_dir / "legacy_canvas.json", {
            "id": "legacy_canvas",
            "title": "Legacy Canvas",
            "nodes": [{"image": "/assets/output/legacy.png"}],
        })
        _write_json(canvas_dir / "legacy_owned_canvas.json", {
            "id": "legacy_owned_canvas",
            "title": "Legacy Owned Canvas",
            "nodes": [{"images": [{"url": legacy_output_url}]}],
            "logs": [{"outputs": [legacy_output_url]}],
        })
        _write_json(canvas_dir / "admin_resource_canvas.json", {
            "id": "admin_resource_canvas",
            "title": "Admin Resource In User Canvas",
            "nodes": [{"images": [{"url": admin_output_url}]}],
            "logs": [{"outputs": [admin_output_url]}],
        })
        _write_json(canvas_dir / "canvas_move.json", {
            "id": "canvas_move",
            "title": "Move Canvas",
            "project": "project_move_a",
            "nodes": [],
        })
        _write_json(canvas_dir / "canvas_default_move.json", {
            "id": "canvas_default_move",
            "title": "Move Canvas To Default",
            "project": "project_move_a",
            "nodes": [],
        })
        _write_json(canvas_dir / "canvas_assign.json", {
            "id": "canvas_assign",
            "title": "Assign Canvas",
            "project": "project_assign_a",
            "nodes": [],
        })
        _write_json(canvas_dir / "project_reassign_canvas.json", {
            "id": "project_reassign_canvas",
            "title": "Project Reassign Canvas",
            "project": "project_reassign",
            "nodes": [],
        })

        edb.set_canvas_owner("canvas_a", user_a["id"])
        edb.set_canvas_owner("canvas_b", user_b["id"])
        edb.set_canvas_owner("canvas_foreign", user_b["id"])
        edb.set_canvas_owner("legacy_owned_canvas", user_a["id"])
        edb.set_canvas_owner("admin_resource_canvas", user_a["id"])
        edb.set_canvas_owner("canvas_move", user_a["id"])
        edb.set_canvas_owner("canvas_default_move", user_a["id"])
        edb.set_canvas_owner("canvas_assign", user_a["id"])
        edb.set_canvas_owner("project_reassign_canvas", user_a["id"])
        edb.set_project_owner("project_a", user_a["id"])
        edb.set_project_owner("project_b", user_b["id"])
        edb.set_project_owner("project_move_a", user_a["id"])
        edb.set_project_owner("project_move_b", user_b["id"])
        edb.set_project_owner("project_assign_a", user_a["id"])
        edb.set_project_owner("project_reassign", user_a["id"])
        edb.record_resource_owner(admin["id"], "/assets/output/admin-in-user-canvas.png", "admin_task")

        assert interceptors.can_access_project(actor_a, "default")
        assert interceptors.can_access_project(actor_a, "project_a")
        assert not interceptors.can_access_project(actor_a, "project_b")
        assert not interceptors.can_access_project(actor_a, "legacy_project")
        assert interceptors.can_access_project(actor_admin, "legacy_project")

        project_payload = {
            "projects": [
                {"id": "default", "name": "默认项目", "canvas_count": 99},
                {"id": "project_a", "name": "Project A", "canvas_count": 99},
                {"id": "project_b", "name": "Project B", "canvas_count": 99},
                {"id": "legacy_project", "name": "Legacy", "canvas_count": 99},
            ]
        }
        interceptors.filter_project_list(actor_a, project_payload)
        assert [item["id"] for item in project_payload["projects"]] == ["default", "project_a"]
        assert project_payload["projects"][1]["canvas_count"] == 1

        err = await interceptors.pre_process("api/projects/project_b", "POST", actor_a)
        assert err is not None and err.status_code == 404
        err = await interceptors.pre_process("api/projects/project_a", "POST", actor_a)
        assert err is None
        err = await interceptors.pre_process("api/projects/default", "POST", actor_a)
        assert err is not None and err.status_code == 404
        err = await interceptors.pre_process("api/projects/project_a", "DELETE", actor_a)
        assert err is not None and err.status_code == 404
        err = await interceptors.pre_process("api/projects/project_a", "DELETE", actor_admin)
        assert err is None
        err = await interceptors.pre_process(
            "api/canvases", "POST", actor_a, body=b'{"project":"project_b"}'
        )
        assert err is not None and err.status_code == 404
        err = await interceptors.pre_process(
            "api/canvases", "POST", actor_a, body=b'{"project":"project_a"}'
        )
        assert err is None
        err = await interceptors.pre_process(
            "api/canvases/canvas_a/meta", "POST", actor_a, body=b'{"project":"project_b"}'
        )
        assert err is not None and err.status_code == 404
        err = await interceptors.pre_process(
            "api/canvases/canvas_a/meta", "POST", actor_a, body=b'{"project":"project_a"}'
        )
        assert err is None

        project_create_body, _ = await interceptors.post_process(
            "api/projects",
            "POST",
            201,
            b'{"project":{"id":"project_created","name":"Created"}}',
            "application/json",
            actor_a,
        )
        assert json.loads(project_create_body.decode("utf-8"))["project"]["id"] == "project_created"
        assert edb.get_project_owner("project_created") == user_a["id"]
        await interceptors.post_process(
            "api/projects/project_created",
            "DELETE",
            200,
            b'{"ok":true}',
            "application/json",
            actor_a,
        )
        assert edb.get_project_owner("project_created") is None

        assert interceptors.can_access_canvas(actor_a, "canvas_a")
        assert not interceptors.can_access_canvas(actor_a, "canvas_b")
        assert not interceptors.can_access_canvas(actor_a, "legacy_canvas")
        assert interceptors.can_access_canvas(actor_a, "legacy_owned_canvas")
        assert interceptors.can_access_canvas(actor_admin, "legacy_canvas")

        canvas_payload = {
            "canvases": [
                {"id": "canvas_a", "title": "Canvas A", "project": "project_a"},
                {"id": "canvas_b", "title": "Canvas B", "project": "project_b"},
                {"id": "legacy_canvas", "title": "Legacy Canvas", "project": "legacy_project"},
            ]
        }
        interceptors.filter_canvas_list(actor_a, canvas_payload)
        assert [item["id"] for item in canvas_payload["canvases"]] == ["canvas_a"]
        assert canvas_payload["canvases"][0]["project"] == "project_a"

        legacy_project_response = {
            "canvas": {"id": "legacy_owned_canvas", "project": "legacy_project"}
        }
        assert interceptors._normalize_canvas_project_for_user(actor_a, legacy_project_response)
        assert legacy_project_response["canvas"]["project"] == "default"

        from enterprise import admin_api

        _write_json(canvas_dir / "canvas_move.json", {
            "id": "canvas_move",
            "title": "Move Canvas",
            "project": "project_move_b",
            "nodes": [],
        })
        await interceptors.post_process(
            "api/canvases/canvas_move/meta",
            "POST",
            200,
            b'{"canvas":{"id":"canvas_move","project":"project_move_b"}}',
            "application/json",
            actor_admin,
        )
        assert edb.get_canvas_owner("canvas_move") == user_b["id"]
        assert not interceptors.can_access_canvas(actor_a, "canvas_move")
        assert interceptors.can_access_canvas(actor_b, "canvas_move")
        moved_payload_a = {"canvases": [{"id": "canvas_move", "title": "Move Canvas", "project": "project_move_b"}]}
        interceptors.filter_canvas_list(actor_a, moved_payload_a)
        assert moved_payload_a["canvases"] == []
        moved_payload_b = {"canvases": [{"id": "canvas_move", "title": "Move Canvas", "project": "project_move_b"}]}
        interceptors.filter_canvas_list(actor_b, moved_payload_b)
        assert moved_payload_b["canvases"][0]["id"] == "canvas_move"
        owner_map = await admin_api.canvas_owners(SimpleNamespace(state=SimpleNamespace(user=actor_admin)))
        assert owner_map["canvas_move"]["user_id"] == user_b["id"]

        _write_json(canvas_dir / "canvas_default_move.json", {
            "id": "canvas_default_move",
            "title": "Move Canvas To Default",
            "project": "default",
            "nodes": [],
        })
        await interceptors.post_process(
            "api/canvases/canvas_default_move/meta",
            "POST",
            200,
            b'{"canvas":{"id":"canvas_default_move","project":"default"}}',
            "application/json",
            actor_admin,
        )
        assert edb.get_canvas_owner("canvas_default_move") == user_a["id"]
        assert interceptors.can_access_canvas(actor_a, "canvas_default_move")
        assert not interceptors.can_access_canvas(actor_b, "canvas_default_move")

        assign_canvas_request = SimpleNamespace(
            state=SimpleNamespace(user=actor_admin),
            json=lambda: _async_value({"user_id": user_b["id"]}),
        )
        assigned_canvas = await admin_api.assign_canvas_owner("canvas_assign", assign_canvas_request)
        assert assigned_canvas["success"] and assigned_canvas["user_id"] == user_b["id"]
        assert edb.get_canvas_owner("canvas_assign") == user_b["id"]
        assert edb.get_canvas_project("canvas_assign") == "default"
        assert not interceptors.can_access_canvas(actor_a, "canvas_assign")
        assert interceptors.can_access_canvas(actor_b, "canvas_assign")
        assigned_payload_b = {"canvases": [{"id": "canvas_assign", "title": "Assign Canvas", "project": "default"}]}
        interceptors.filter_canvas_list(actor_b, assigned_payload_b)
        assert assigned_payload_b["canvases"][0]["id"] == "canvas_assign"
        owner_map = await admin_api.canvas_owners(SimpleNamespace(state=SimpleNamespace(user=actor_admin)))
        assert owner_map["canvas_assign"]["user_id"] == user_b["id"]

        edb.project_exists = lambda project_id: project_id == "project_reassign"
        admin_request = SimpleNamespace(
            state=SimpleNamespace(user=actor_admin),
            json=lambda: _async_value({"user_id": user_b["id"]}),
        )
        assigned = await admin_api.assign_project_owner("project_reassign", admin_request)
        assert assigned["success"] and edb.get_project_owner("project_reassign") == user_b["id"]
        assert assigned["synced_canvas_count"] == 1
        assert edb.get_canvas_owner("project_reassign_canvas") == user_b["id"]
        owner_map = await admin_api.project_owners(SimpleNamespace(state=SimpleNamespace(user=actor_admin)))
        assert owner_map["project_reassign"]["user_id"] == user_b["id"]

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
        assert interceptors.can_access_resource(actor_a, "/api/download-output?url=/assets/output/a.png")
        assert not interceptors.can_access_resource(actor_b, "/api/download-output?url=/assets/output/a.png")
        assert interceptors.can_access_resource(actor_a, "/api/view?filename=a.png&type=output")
        assert not interceptors.can_access_resource(actor_b, "/api/view?filename=a.png&type=output")
        assert interceptors.normalize_resource_url("http://127.0.0.1:8000/assets/output/a.png") == "/assets/output/a.png"
        assert interceptors.normalize_resource_url("http://127.0.0.1:3001/assets/output/a.png") == "/assets/output/a.png"
        lan_view_url = "http://192.168.140.80:8000/api/view?filename=a.png&type=output"
        assert interceptors.normalize_resource_url(lan_view_url) == "/assets/output/a.png"
        assert interceptors.normalize_resource_url("https://example.com/assets/output/a.png") == ""
        assert interceptors.can_access_resource(actor_a, "http://127.0.0.1:8000/assets/output/a.png")
        assert not interceptors.can_access_resource(actor_b, "http://127.0.0.1:8000/assets/output/a.png")
        assert edb.get_resource_owner("/assets/output/legacy-owned-absolute.png") is None
        legacy_payload = {
            "canvas": {
                "id": "legacy_owned_canvas",
                "nodes": [{"images": [{"url": legacy_output_url}]}],
                "logs": [{"outputs": [legacy_output_url]}],
            }
        }
        await interceptors.post_process(
            "api/canvases/legacy_owned_canvas",
            "GET",
            200,
            json.dumps(legacy_payload).encode("utf-8"),
            "application/json",
            actor_a,
        )
        assert edb.get_resource_owner("/assets/output/legacy-owned-absolute.png") == user_a["id"]
        assert interceptors.can_access_resource(actor_a, legacy_output_url)
        assert interceptors.can_access_resource(actor_admin, legacy_output_url)
        assert not interceptors.can_access_resource(actor_b, legacy_output_url)
        err = await interceptors.pre_process("api/canvases/legacy_owned_canvas", "GET", actor_b)
        assert err is not None and err.status_code == 404
        legacy_save_body = json.dumps({
            "title": "Legacy Owned Canvas",
            "nodes": [{"images": [{"url": legacy_output_url}]}],
            "logs": [{"outputs": [legacy_output_url]}],
        }).encode("utf-8")
        err = await interceptors.pre_process("api/canvases/legacy_owned_canvas", "PUT", actor_a, body=legacy_save_body)
        assert err is None

        assert edb.get_resource_owner("/assets/output/admin-in-user-canvas.png") == admin["id"]
        assert interceptors.can_access_resource(actor_a, admin_output_url)
        assert interceptors.can_access_resource(actor_admin, admin_output_url)
        assert not interceptors.can_access_resource(actor_b, admin_output_url)
        err = await interceptors.pre_process("api/canvases/admin_resource_canvas", "PUT", actor_a, body=json.dumps({
            "title": "Admin Resource In User Canvas",
            "nodes": [{"images": [{"url": admin_output_url}]}],
            "logs": [{"outputs": [admin_output_url]}],
        }).encode("utf-8"))
        assert err is None

        edb.record_resource_owner(user_a["id"], "/assets/input/upload-a.png", "test")
        assert interceptors.can_access_resource(actor_a, "/assets/input/upload-a.png")
        assert not interceptors.can_access_resource(actor_b, "/assets/input/upload-a.png")

        task_create_body, task_create_headers = await interceptors.post_process(
            "api/canvas-image-tasks",
            "POST",
            200,
            b'{"task_id":"task_a","status":"queued"}',
            "application/json",
            actor_a,
        )
        assert json.loads(task_create_body.decode("utf-8"))["task_id"] == "task_a"
        assert task_create_headers == {}
        assert edb.get_canvas_image_task_owner("task_a") == user_a["id"]

        err = await interceptors.pre_process("api/canvas-image-tasks/task_a", "GET", actor_b)
        assert err is not None and err.status_code == 404
        err = await interceptors.pre_process("api/canvas-image-tasks/task_a", "GET", actor_a)
        assert err is None

        task_result = {
            "id": "task_a",
            "status": "succeeded",
            "result": {
                "images": [
                    "/assets/output/task-a.png",
                    "http://127.0.0.1:8000/assets/output/task-a-absolute.png",
                ],
                "items": [
                    {"url": "/api/download-output?url=/assets/output/task-a-download.png"},
                    {
                        "url": (
                            "http://127.0.0.1:8000/api/download-output?"
                            "url=http%3A%2F%2F127.0.0.1%3A8000%2Fassets%2Foutput%2Ftask-a-download-absolute.png"
                        )
                    },
                ],
            },
        }
        await interceptors.post_process(
            "api/canvas-image-tasks/task_a",
            "GET",
            200,
            json.dumps(task_result).encode("utf-8"),
            "application/json",
            actor_a,
        )
        assert edb.get_resource_owner("/assets/output/task-a.png") == user_a["id"]
        assert edb.get_resource_owner("/assets/output/task-a-absolute.png") == user_a["id"]
        assert edb.get_resource_owner("/assets/output/task-a-download.png") == user_a["id"]
        assert edb.get_resource_owner("/assets/output/task-a-download-absolute.png") == user_a["id"]
        assert interceptors.can_access_resource(actor_a, "/assets/output/task-a.png")
        assert interceptors.can_access_resource(actor_a, "http://127.0.0.1:8000/assets/output/task-a-absolute.png")
        assert not interceptors.can_access_resource(actor_b, "/assets/output/task-a.png")
        assert not interceptors.can_access_resource(actor_b, "http://127.0.0.1:8000/assets/output/task-a-absolute.png")
        assert interceptors.can_access_resource(actor_admin, "/assets/output/task-a.png")
        assert not interceptors.can_access_resource(actor_a, "/assets/output/unowned-task.png")

        save_body = json.dumps({
            "title": "Canvas A",
            "nodes": [{"images": [{"url": "http://127.0.0.1:8000/assets/output/task-a-absolute.png"}]}],
        }).encode("utf-8")
        err = await interceptors.pre_process("api/canvases/canvas_a", "PUT", actor_a, body=save_body)
        assert err is None
        err = await interceptors.pre_process("api/canvases/canvas_b", "PUT", actor_b, body=save_body)
        assert err is not None and err.status_code == 404

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
