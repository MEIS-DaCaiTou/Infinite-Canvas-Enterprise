"""
Non-destructive async task owner isolation checks.

The script uses a temporary SQLite database and temporary data folders. It does
not read or write the real runtime database, API config, images, or cache.

Run from the repository root:

    python .\enterprise\tests\test_task_history_isolation.py
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
    os.environ.setdefault("JWT_SECRET", "test-secret-for-task-history-isolation-1234567890")
    os.environ.setdefault("ADMIN_USERNAME", "admin")
    os.environ.setdefault("ADMIN_PASSWORD", "change-me-in-tests")


def _json_body(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


async def _post_process_json(
    interceptors,
    path: str,
    method: str,
    actor: dict,
    payload: dict,
    request_body: dict | None = None,
    query_params: dict | None = None,
) -> dict:
    body, _headers = await interceptors.post_process(
        path,
        method,
        200,
        _json_body(payload),
        "application/json",
        actor,
        _json_body(request_body) if request_body is not None else None,
        query_params=query_params,
    )
    return json.loads(body.decode("utf-8"))


async def _run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-task-history-") as raw_tmp:
        tmp = Path(raw_tmp)
        _prepare_env(tmp)

        from enterprise import db as edb
        from enterprise import interceptors

        interceptors._HISTORY_FILE = tmp / "history.json"
        interceptors._CANVAS_DATA_DIR = tmp / "canvases"
        interceptors._CONVERSATION_DATA_DIR = tmp / "conversations"
        interceptors._ASSET_LIBRARY_FILE = tmp / "asset_library.json"
        interceptors._CANVAS_DATA_DIR.mkdir()
        interceptors._CONVERSATION_DATA_DIR.mkdir()
        edb.CANVAS_DATA_DIR = str(interceptors._CANVAS_DATA_DIR)
        edb._conversation_root = lambda: str(interceptors._CONVERSATION_DATA_DIR)

        edb.init_db()
        user_a = edb.create_user("task_a", "password-a", "Task A", False)
        user_b = edb.create_user("task_b", "password-b", "Task B", False)
        admin = edb.get_user_by_username("admin")

        actor_a = {"user_id": user_a["id"], "username": "task_a", "is_admin": False}
        actor_b = {"user_id": user_b["id"], "username": "task_b", "is_admin": False}
        actor_admin = {"user_id": admin["id"], "username": "admin", "is_admin": True}

        # RunningHub submit -> task owner -> query owner check.
        await _post_process_json(
            interceptors,
            "api/runninghub/submit",
            "POST",
            actor_a,
            {"success": True, "data": {"taskId": "rh-task-a", "raw": {}}},
            {"webappId": "webapp-a"},
        )
        assert edb.get_task_owner("runninghub", "rh-task-a") == user_a["id"]
        assert await interceptors.pre_process("api/runninghub/query", "GET", actor_a, {"taskId": "rh-task-a"}) is None
        denied = await interceptors.pre_process("api/runninghub/query", "GET", actor_b, {"taskId": "rh-task-a"})
        assert denied is not None and denied.status_code == 404
        assert await interceptors.pre_process("api/runninghub/query", "GET", actor_admin, {"taskId": "rh-task-a"}) is None
        denied = await interceptors.pre_process("api/runninghub/query", "GET", actor_a, {"taskId": "legacy-rh-task"})
        assert denied is not None and denied.status_code == 404
        assert await interceptors.pre_process("api/runninghub/query", "GET", actor_admin, {"taskId": "legacy-rh-task"}) is None

        await _post_process_json(
            interceptors,
            "api/runninghub/query",
            "GET",
            actor_a,
            {"success": True, "data": {"status": "SUCCESS", "urls": ["/assets/output/rh-task-a.png"]}},
            query_params={"taskId": "rh-task-a"},
        )
        assert edb.get_resource_owner("/assets/output/rh-task-a.png") == user_a["id"]
        assert interceptors.can_access_resource(actor_a, "/assets/output/rh-task-a.png")
        assert not interceptors.can_access_resource(actor_b, "/assets/output/rh-task-a.png")
        assert interceptors.can_access_resource(actor_admin, "/assets/output/rh-task-a.png")

        # Provider task query is conservative: only owner/admin may query known task ids.
        edb.record_task_owner(user_a["id"], "provider_image", "provider-task-a", source="test")
        assert await interceptors.pre_process(
            "api/image-task-query",
            "POST",
            actor_a,
            body=_json_body({"provider_id": "comfly", "task_id": "provider-task-a"}),
        ) is None
        denied = await interceptors.pre_process(
            "api/image-task-query",
            "POST",
            actor_b,
            body=_json_body({"provider_id": "comfly", "task_id": "provider-task-a"}),
        )
        assert denied is not None and denied.status_code == 404
        denied = await interceptors.pre_process(
            "api/image-task-query",
            "POST",
            actor_a,
            body=_json_body({"provider_id": "comfly", "task_id": "unknown-provider-task"}),
        )
        assert denied is not None and denied.status_code == 404
        assert await interceptors.pre_process(
            "api/image-task-query",
            "POST",
            actor_admin,
            body=_json_body({"provider_id": "comfly", "task_id": "provider-task-a"}),
        ) is None

        await _post_process_json(
            interceptors,
            "api/image-task-query",
            "POST",
            actor_admin,
            {
                "status": "succeeded",
                "task_id": "provider-task-a",
                "images": ["/assets/output/provider-task-a.png"],
            },
            {"provider_id": "comfly", "task_id": "provider-task-a"},
        )
        assert edb.get_resource_owner("/assets/output/provider-task-a.png") == user_a["id"]
        assert not interceptors.can_access_resource(actor_b, "/assets/output/provider-task-a.png")

        # Angle generate records owner; poll/status is blocked for other users.
        await _post_process_json(
            interceptors,
            "api/angle/generate",
            "POST",
            actor_a,
            {"url": "/assets/output/angle-a.png", "task_id": "angle-task-a"},
        )
        assert edb.get_task_owner("angle", "angle-task-a") == user_a["id"]
        assert await interceptors.pre_process(
            "api/angle/poll_status",
            "POST",
            actor_a,
            body=_json_body({"task_id": "angle-task-a"}),
        ) is None
        denied = await interceptors.pre_process(
            "api/angle/poll_status",
            "POST",
            actor_b,
            body=_json_body({"task_id": "angle-task-a"}),
        )
        assert denied is not None and denied.status_code == 404
        denied = await interceptors.pre_process(
            "api/angle/poll_status",
            "POST",
            actor_a,
            body=_json_body({"task_id": "legacy-angle-task"}),
        )
        assert denied is not None and denied.status_code == 404
        await _post_process_json(
            interceptors,
            "api/angle/poll_status",
            "POST",
            actor_admin,
            {"url": "/assets/output/angle-polled-a.png"},
            {"task_id": "angle-task-a"},
        )
        assert edb.get_resource_owner("/assets/output/angle-polled-a.png") == user_a["id"]

        # Existing Smart Canvas local task owner checks continue to work.
        await _post_process_json(
            interceptors,
            "api/canvas-image-tasks",
            "POST",
            actor_a,
            {"task_id": "canvas-img-a", "status": "queued"},
        )
        assert edb.get_canvas_image_task_owner("canvas-img-a") == user_a["id"]
        assert edb.get_task_owner("canvas_image", "canvas-img-a") == user_a["id"]
        assert await interceptors.pre_process("api/canvas-image-tasks/canvas-img-a", "GET", actor_a) is None
        denied = await interceptors.pre_process("api/canvas-image-tasks/canvas-img-a", "GET", actor_b)
        assert denied is not None and denied.status_code == 404

        await _post_process_json(
            interceptors,
            "api/canvas-image-tasks/canvas-img-a",
            "GET",
            actor_a,
            {"status": "failed", "upstream_task_id": "canvas-upstream-a"},
        )
        assert edb.get_task_owner("provider_image", "canvas-upstream-a") == user_a["id"]
        assert await interceptors.pre_process(
            "api/image-task-query",
            "POST",
            actor_a,
            body=_json_body({"provider_id": "comfly", "task_id": "canvas-upstream-a"}),
        ) is None
        denied = await interceptors.pre_process(
            "api/image-task-query",
            "POST",
            actor_b,
            body=_json_body({"provider_id": "comfly", "task_id": "canvas-upstream-a"}),
        )
        assert denied is not None and denied.status_code == 404

        await _post_process_json(
            interceptors,
            "api/canvas-comfy-tasks",
            "POST",
            actor_a,
            {"task_id": "canvas-comfy-a", "status": "queued"},
        )
        assert edb.get_canvas_image_task_owner("canvas-comfy-a") == user_a["id"]
        assert edb.get_task_owner("canvas_comfy", "canvas-comfy-a") == user_a["id"]

        # Video tasks record task owner and output resource owner from the response.
        await _post_process_json(
            interceptors,
            "api/canvas-video",
            "POST",
            actor_a,
            {"task_id": "video-task-a", "videos": ["/assets/output/video-task-a.mp4"]},
        )
        assert edb.get_task_owner("canvas_video", "video-task-a") == user_a["id"]
        assert edb.get_resource_owner("/assets/output/video-task-a.mp4") == user_a["id"]
        assert not interceptors.can_access_resource(actor_b, "/assets/output/video-task-a.mp4")


if __name__ == "__main__":
    asyncio.run(_run_checks())
    print("enterprise task history isolation checks passed")
