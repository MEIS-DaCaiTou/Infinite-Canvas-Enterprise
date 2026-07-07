"""
Non-destructive user deletion / cleanup dry-run checks.

This script uses a temporary SQLite database and temporary runtime folder. It
does not delete users, owner maps, runtime files, provider settings, databases,
env files, or upstream-owned files.

Run from the repository root:

    python .\\enterprise\\tests\\test_user_delete_cleanup.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _prepare_env(tmp: Path) -> None:
    os.environ["DB_PATH"] = str(tmp / "enterprise.db")
    os.environ.setdefault("JWT_SECRET", "test-secret-for-user-delete-cleanup-1234567890")
    os.environ.setdefault("ADMIN_USERNAME", "admin")
    os.environ.setdefault("ADMIN_PASSWORD", "change-me-in-tests")


class FakeRequest:
    def __init__(
        self,
        user: dict | None,
        query_params: dict | None = None,
        body: dict | None = None,
    ):
        self.state = SimpleNamespace(user=user)
        self.query_params = query_params or {}
        self._body = body or {}

    async def json(self):
        return self._body


async def _expect_http_error(coro, expected_status: set[int]) -> None:
    try:
        await coro
    except HTTPException as exc:
        assert exc.status_code in expected_status, f"expected {expected_status}, got {exc.status_code}"
        return
    raise AssertionError(f"expected HTTPException {expected_status}")


async def _run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-user-delete-cleanup-") as raw_tmp:
        tmp = Path(raw_tmp)
        _prepare_env(tmp)

        from enterprise import admin_api
        from enterprise import db as edb

        edb.init_db()
        user_a = edb.create_user("delete_a", "password-a", "Delete A", False)
        user_b = edb.create_user("delete_b", "password-b", "Delete B", False)
        admin = edb.get_user_by_username("admin")

        actor_a = {"user_id": user_a["id"], "username": "delete_a", "is_admin": False}
        actor_admin = {"user_id": admin["id"], "username": "admin", "is_admin": True}

        runtime_assets = tmp / "assets"
        runtime_assets.mkdir()
        runtime_marker = runtime_assets / "runtime-image.png"
        runtime_marker.write_bytes(b"runtime")
        runtime_mtime = runtime_marker.stat().st_mtime_ns

        edb.record_project_owner(user_a["id"], "project-a")
        edb.record_canvas_owner(user_a["id"], "canvas-a")
        edb.record_conversation_owner(user_a["id"], "conversation-a")
        for idx in range(3):
            edb.record_resource_owner(user_a["id"], f"/assets/uploads/a-{idx}.png", "test")
        edb.record_history_owner(
            user_a["id"],
            "history-a",
            history_type="online-image",
            resource_url="/assets/output/history-a.png",
            task_id="task-a",
            source="test",
        )
        edb.record_asset_object_owner(
            user_a["id"],
            "item",
            "asset-item-a",
            parent_library_id="library-a",
            parent_category_id="category-a",
            resource_url="/assets/library/a.png",
            source="test",
        )
        edb.record_canvas_image_task_owner(user_a["id"], "canvas-task-a")
        edb.record_task_owner(
            user_a["id"],
            "runninghub",
            "task-a",
            source="test",
            canvas_id="canvas-a",
            resource_url="/assets/output/task-a.png",
            status="SUCCESS",
        )
        edb.set_user_feature_override(user_a["id"], "system_update", "deny", admin["id"])
        edb.log_action(user_a["id"], "canvas_created", json.dumps({"canvas_id": "canvas-a"}))
        edb.log_action(
            admin["id"],
            "admin_note",
            json.dumps({"target_user_id": user_a["id"], "target_username": "delete_a"}),
        )

        await _expect_http_error(
            admin_api.user_delete_impact(user_a["id"], FakeRequest(actor_a)),
            {403},
        )
        await _expect_http_error(
            admin_api.user_delete_impact(user_a["id"], FakeRequest(None)),
            {401, 403},
        )
        await _expect_http_error(
            admin_api.user_delete_impact("missing-user", FakeRequest(actor_admin)),
            {404},
        )
        await _expect_http_error(
            admin_api.user_delete_impact(user_a["id"], FakeRequest(actor_admin, {"sample_limit": "bad"})),
            {400},
        )

        before = edb.get_user_delete_impact(user_a["id"], sample_limit=100)
        response = await admin_api.user_delete_impact(
            user_a["id"],
            FakeRequest(actor_admin, {"sample_limit": "2"}),
        )

        assert response["user"]["id"] == user_a["id"]
        assert response["user"]["username"] == "delete_a"
        assert response["user"]["is_admin"] is False
        assert response["user"]["is_active"] is True
        assert set(response["counts"]) == {
            "projects",
            "canvases",
            "conversations",
            "resources",
            "history",
            "asset_objects",
            "canvas_tasks",
            "tasks",
            "feature_overrides",
            "audit_logs",
        }
        assert response["counts"]["projects"] == 1
        assert response["counts"]["canvases"] == 1
        assert response["counts"]["conversations"] == 1
        assert response["counts"]["resources"] == 3
        assert response["counts"]["history"] == 1
        assert response["counts"]["asset_objects"] == 1
        assert response["counts"]["canvas_tasks"] == 1
        assert response["counts"]["tasks"] == 1
        assert response["counts"]["feature_overrides"] == 1
        assert response["counts"]["audit_logs"] == 2
        assert len(response["samples"]["resources"]) == 2
        assert response["samples"]["projects"][0]["project_id"] == "project-a"
        assert response["samples"]["canvases"][0]["canvas_id"] == "canvas-a"
        assert response["samples"]["conversations"][0]["conversation_id"] == "conversation-a"
        assert response["samples"]["history"][0]["history_id"] == "history-a"
        assert response["samples"]["asset_objects"][0]["object_id"] == "asset-item-a"
        assert response["samples"]["canvas_tasks"][0]["task_id"] == "canvas-task-a"
        assert response["samples"]["tasks"][0]["task_id"] == "task-a"
        assert response["samples"]["feature_overrides"][0]["feature_key"] == "system_update"
        assert any("read-only" in warning for warning in response["warnings"])
        assert any("Runtime files" in warning for warning in response["warnings"])

        after = edb.get_user_delete_impact(user_a["id"], sample_limit=100)
        for key in response["counts"]:
            if key == "audit_logs":
                continue
            assert after["counts"][key] == before["counts"][key] == response["counts"][key], key
        assert edb.get_user_by_id_any_status(user_a["id"])["is_active"] == 1
        assert edb.get_resource_owner("/assets/uploads/a-0.png") == user_a["id"]
        assert edb.get_user_feature_override(user_a["id"], "system_update")["mode"] == "deny"
        assert runtime_marker.exists()
        assert runtime_marker.read_bytes() == b"runtime"
        assert runtime_marker.stat().st_mtime_ns == runtime_mtime

        logs, _total = edb.get_logs(limit=20, action="user_delete_dry_run")
        assert logs, "dry-run audit log missing"
        audit_detail = json.loads(logs[0]["detail"])
        assert audit_detail["target_user_id"] == user_a["id"]
        assert audit_detail["target_username"] == "delete_a"
        assert audit_detail["counts"]["resources"] == 3
        assert audit_detail["sample_limit"] == 2
        assert "password" not in logs[0]["detail"].lower()
        assert "token" not in logs[0]["detail"].lower()
        assert "cookie" not in logs[0]["detail"].lower()
        assert "api key" not in logs[0]["detail"].lower()

        await _expect_http_error(
            admin_api.delete_user(admin["id"], FakeRequest(actor_admin)),
            {400},
        )
        await _expect_http_error(
            admin_api.update_user_active(
                admin["id"],
                FakeRequest(actor_admin, body={"is_active": False}),
            ),
            {400},
        )
        ghost_admin = {"user_id": "other-admin", "username": "other-admin", "is_admin": True}
        await _expect_http_error(
            admin_api.update_user_active(
                admin["id"],
                FakeRequest(ghost_admin, body={"is_active": False}),
            ),
            {400},
        )
        await _expect_http_error(
            admin_api.delete_user(admin["id"], FakeRequest(ghost_admin)),
            {400},
        )
        await _expect_http_error(
            admin_api.purge_user_feature_overrides(user_a["id"], FakeRequest(actor_a)),
            {403},
        )
        await _expect_http_error(
            admin_api.delete_user(user_a["id"], FakeRequest(actor_admin)),
            {400},
        )
        await _expect_http_error(
            admin_api.delete_user(
                user_a["id"],
                FakeRequest(actor_admin, body={"confirm_username": "wrong-user"}),
            ),
            {400},
        )
        await _expect_http_error(
            admin_api.purge_user_feature_overrides(user_a["id"], FakeRequest(actor_admin)),
            {400},
        )
        await _expect_http_error(
            admin_api.purge_user_feature_overrides(
                user_a["id"],
                FakeRequest(actor_admin, body={"confirm_username": "wrong-user"}),
            ),
            {400},
        )

        deleted = await admin_api.delete_user(
            user_a["id"],
            FakeRequest(actor_admin, body={"confirm_username": "delete_a", "reason": "offboarding"}),
        )
        assert deleted["success"] is True
        assert deleted["soft_deleted"] is True
        assert deleted["status"] == "disabled"
        assert edb.get_user_by_id_any_status(user_a["id"])["is_active"] == 0
        assert edb.get_user_by_id(user_a["id"]) is None
        assert edb.get_user_by_username("delete_a") is None
        assert edb.get_project_owner("project-a") == user_a["id"]
        assert edb.get_canvas_owner("canvas-a") == user_a["id"]
        assert edb.get_conversation_owner("conversation-a") == user_a["id"]
        assert edb.get_resource_owner("/assets/uploads/a-0.png") == user_a["id"]
        assert edb.get_history_owner("history-a") == user_a["id"]
        assert edb.get_asset_object_owner("item", "asset-item-a") == user_a["id"]
        assert edb.get_canvas_image_task_owner("canvas-task-a") == user_a["id"]
        assert edb.get_task_owner("runninghub", "task-a") == user_a["id"]
        assert edb.get_user_feature_override(user_a["id"], "system_update")["mode"] == "deny"
        assert runtime_marker.exists()
        assert runtime_marker.read_bytes() == b"runtime"
        assert runtime_marker.stat().st_mtime_ns == runtime_mtime

        deleted_logs, _ = edb.get_logs(limit=20, action="user_deleted")
        assert deleted_logs, "soft-delete audit log missing"
        deleted_detail = json.loads(deleted_logs[0]["detail"])
        assert deleted_detail["target_user_id"] == user_a["id"]
        assert deleted_detail["soft_delete"] is True
        assert deleted_detail["is_active"] is False
        assert deleted_detail["previous_is_active"] is True
        assert deleted_detail["reason"] == "offboarding"
        assert deleted_detail["owned_data_retained"] is True
        assert deleted_detail["runtime_files_deleted"] is False
        assert deleted_detail["owner_mappings_cleaned"] is False

        purge = await admin_api.purge_user_feature_overrides(
            user_a["id"],
            FakeRequest(actor_admin, body={"confirm_username": "delete_a", "reason": "cleanup overrides"}),
        )
        assert purge["success"] is True
        assert purge["cleared_count"] == 1
        assert edb.get_user_feature_override(user_a["id"], "system_update") is None
        impact_after_purge = edb.get_user_delete_impact(user_a["id"], sample_limit=10)
        assert impact_after_purge["counts"]["feature_overrides"] == 0
        assert impact_after_purge["counts"]["projects"] == 1
        assert edb.get_resource_owner("/assets/uploads/a-0.png") == user_a["id"]
        assert runtime_marker.exists()
        assert runtime_marker.read_bytes() == b"runtime"

        purge_logs, _ = edb.get_logs(limit=20, action="user_feature_overrides_cleared")
        assert purge_logs, "feature override purge audit log missing"
        purge_detail = json.loads(purge_logs[0]["detail"])
        assert purge_detail["target_user_id"] == user_a["id"]
        assert purge_detail["old_count"] == 1
        assert purge_detail["cleared_count"] == 1
        assert purge_detail["deleted_count"] == 1
        assert purge_detail["old_feature_keys"] == ["system_update"]
        assert purge_detail["old_values"] == [{"feature_key": "system_update", "mode": "deny"}]
        assert purge_detail["reason"] == "cleanup overrides"
        policy_logs, _ = edb.get_logs(limit=20, action="permission_policy_updated")
        assert any(
            json.loads(row["detail"]).get("source_action") == "user_feature_overrides_cleared"
            for row in policy_logs
        )

        missing = edb.get_user_delete_impact(user_b["id"], sample_limit=1)
        assert missing["counts"]["projects"] == 0
        assert missing["samples"]["projects"] == []

        logs_html = (ROOT / "enterprise-static" / "logs.html").read_text(encoding="utf-8")
        assert 'value="user_delete_dry_run"' in logs_html
        assert 'value="user_deleted"' in logs_html
        assert 'value="user_feature_overrides_cleared"' in logs_html

    print("user delete cleanup dry-run checks passed")


if __name__ == "__main__":
    asyncio.run(_run_checks())
