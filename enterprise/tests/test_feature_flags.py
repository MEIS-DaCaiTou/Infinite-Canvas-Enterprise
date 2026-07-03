"""
Non-destructive enterprise feature-flag and audit checks.

This script uses a temporary SQLite database and calls enterprise modules
directly. It does not read or write real runtime assets, provider settings,
databases, env files, or upstream-owned files.

Run from the repository root:

    python .\\enterprise\\tests\\test_feature_flags.py
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
    os.environ.setdefault("JWT_SECRET", "test-secret-for-feature-flags-1234567890")
    os.environ.setdefault("ADMIN_USERNAME", "admin")
    os.environ.setdefault("ADMIN_PASSWORD", "change-me-in-tests")


def _body(payload: dict | None) -> bytes | None:
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _json_body(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


class FakeRequest:
    def __init__(self, user: dict, body: dict | None = None):
        self.state = SimpleNamespace(user=user)
        self._body = body or {}

    async def json(self):
        return self._body


async def _assert_allowed(path: str, method: str, actor: dict, payload: dict | None = None) -> None:
    response = await interceptors.pre_process(path, method, actor, body=_body(payload))
    assert response is None, f"{method} {path} should be allowed, got {_json_body(response) if response else None}"


async def _assert_forbidden(path: str, method: str, actor: dict, payload: dict | None = None) -> None:
    response = await interceptors.pre_process(path, method, actor, body=_body(payload))
    assert response is not None, f"{method} {path} should be denied"
    assert response.status_code == 403, f"{method} {path} returned {response.status_code}"


async def _run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-feature-flags-") as raw_tmp:
        tmp = Path(raw_tmp)
        _prepare_env(tmp)

        from enterprise import admin_api
        from enterprise import db as edb
        from enterprise import interceptors as interceptors_module

        globals()["interceptors"] = interceptors_module

        interceptors._ASSET_LIBRARY_FILE = tmp / "asset_library.json"
        interceptors._CANVAS_DATA_DIR = tmp / "canvases"
        interceptors._CONVERSATION_DATA_DIR = tmp / "conversations"
        interceptors._CANVAS_DATA_DIR.mkdir()
        interceptors._CONVERSATION_DATA_DIR.mkdir()
        edb.CANVAS_DATA_DIR = str(interceptors._CANVAS_DATA_DIR)
        edb._conversation_root = lambda: str(interceptors._CONVERSATION_DATA_DIR)

        edb.init_db()
        user_a = edb.create_user("feature_a", "password-a", "Feature A", False)
        user_b = edb.create_user("feature_b", "password-b", "Feature B", False)
        admin = edb.get_user_by_username("admin")

        actor_a = {"user_id": user_a["id"], "username": "feature_a", "is_admin": False}
        actor_b = {"user_id": user_b["id"], "username": "feature_b", "is_admin": False}
        actor_admin = {"user_id": admin["id"], "username": "admin", "is_admin": True}

        default_deny = {"api_settings_access", "workflow_settings_access", "system_update"}
        default_allow = {
            "runninghub_generation",
            "video_generation",
            "image_tools_generation",
            "asset_library_manage",
            "history_batch_delete",
            "local_asset_manage",
        }
        listed = {item["feature_key"]: item for item in edb.list_feature_flags()}
        assert default_deny | default_allow == set(listed)
        for key in default_deny:
            assert edb.can_use_feature(actor_a, key) is False, key
            assert listed[key]["enabled"] is False, key
            assert edb.can_use_feature(actor_admin, key) is True, key
        for key in default_allow:
            assert edb.can_use_feature(actor_a, key) is True, key
            assert listed[key]["enabled"] is True, key
            assert edb.can_use_feature(actor_admin, key) is True, key

        # Admin API writes global flags and audit logs.
        await admin_api.update_feature_flag(
            "runninghub_generation",
            FakeRequest(actor_admin, {"enabled": False}),
        )
        assert edb.can_use_feature(actor_a, "runninghub_generation") is False
        await _assert_forbidden("api/runninghub/submit", "POST", actor_a, {"nodeInfoList": []})
        await _assert_allowed("api/runninghub/submit", "POST", actor_admin, {"nodeInfoList": []})

        # User override allow can recover from global deny, then inherit returns to global.
        await admin_api.update_user_feature_override(
            user_a["id"],
            "runninghub_generation",
            FakeRequest(actor_admin, {"mode": "allow"}),
        )
        assert edb.can_use_feature(actor_a, "runninghub_generation") is True
        await _assert_allowed("api/runninghub/workflow-submit", "POST", actor_a, {"nodeInfoList": []})
        await admin_api.delete_user_feature_override(
            user_a["id"],
            "runninghub_generation",
            FakeRequest(actor_admin),
        )
        assert edb.can_use_feature(actor_a, "runninghub_generation") is False

        # User override deny can override a global allow without affecting B.
        await admin_api.update_feature_flag(
            "runninghub_generation",
            FakeRequest(actor_admin, {"enabled": True}),
        )
        await admin_api.update_user_feature_override(
            user_a["id"],
            "runninghub_generation",
            FakeRequest(actor_admin, {"mode": "deny"}),
        )
        assert edb.can_use_feature(actor_a, "runninghub_generation") is False
        assert edb.can_use_feature(actor_b, "runninghub_generation") is True
        await _assert_forbidden("api/runninghub/submit", "POST", actor_a, {"nodeInfoList": []})
        await _assert_allowed("api/runninghub/submit", "POST", actor_b, {"nodeInfoList": []})

        # Default-deny settings remain blocked, but an explicit allow works.
        await _assert_forbidden("api/providers", "GET", actor_a)
        await _assert_forbidden("api/workflows/test/config", "PUT", actor_a, {"title": "blocked"})
        await admin_api.update_user_feature_override(
            user_a["id"],
            "api_settings_access",
            FakeRequest(actor_admin, {"mode": "allow"}),
        )
        await admin_api.update_user_feature_override(
            user_a["id"],
            "workflow_settings_access",
            FakeRequest(actor_admin, {"mode": "allow"}),
        )
        await _assert_allowed("api/providers", "GET", actor_a)
        await _assert_allowed("api/workflows/test/config", "PUT", actor_a, {"title": "allowed"})

        # Submit gates deny high-risk generation classes without touching query owner checks.
        await admin_api.update_user_feature_override(
            user_a["id"],
            "video_generation",
            FakeRequest(actor_admin, {"mode": "deny"}),
        )
        await admin_api.update_user_feature_override(
            user_a["id"],
            "image_tools_generation",
            FakeRequest(actor_admin, {"mode": "deny"}),
        )
        await _assert_forbidden("api/canvas-video", "POST", actor_a, {"prompt": "video"})
        await _assert_forbidden("api/online-image", "POST", actor_a, {"prompt": "image"})
        await _assert_forbidden("api/generate", "POST", actor_a, {"prompt": "image"})
        await _assert_allowed("api/canvas-video", "POST", actor_b, {"prompt": "video"})
        await _assert_allowed("api/online-image", "POST", actor_b, {"prompt": "image"})

        edb.record_task_owner(user_b["id"], "runninghub", "rh-b", source="test")
        query_denial = await interceptors.pre_process(
            "api/runninghub/query",
            "GET",
            actor_a,
            query_params={"taskId": "rh-b"},
        )
        assert query_denial is not None and query_denial.status_code == 404

        # Asset-library writes can be disabled while GET remains readable/filterable.
        await admin_api.update_user_feature_override(
            user_a["id"],
            "asset_library_manage",
            FakeRequest(actor_admin, {"mode": "deny"}),
        )
        await _assert_allowed("api/asset-library", "GET", actor_a)
        await _assert_forbidden("api/asset-library/items", "POST", actor_a, {"library_id": "default"})
        await _assert_forbidden("api/canvas-workflows/export-to-library", "POST", actor_a, {"item": {}})

        # local-assets management can be disabled without changing resource ownership rules.
        edb.record_resource_owner(user_a["id"], "/assets/uploads/owned-a.png", "test")
        await admin_api.update_user_feature_override(
            user_a["id"],
            "local_asset_manage",
            FakeRequest(actor_admin, {"mode": "deny"}),
        )
        # Feature gates must block submits/management, not ordinary input uploads.
        for upload_path in [
            "api/upload",
            "api/comfyui/upload-base64",
            "api/ai/upload",
            "api/ai/upload-base64",
            "api/local-assets/upload",
        ]:
            await _assert_allowed(upload_path, "POST", actor_a, {"files": []})
        await interceptors.post_process(
            "api/upload",
            "POST",
            200,
            _body({"files": [{"comfy_name": "angle-input-a.png"}]}),
            "application/json",
            actor_a,
        )
        await interceptors.post_process(
            "api/local-assets/upload",
            "POST",
            200,
            _body({"files": [{"url": "/assets/uploads/enhance-input-a.png"}]}),
            "application/json",
            actor_a,
        )
        assert edb.get_resource_owner("/assets/input/angle-input-a.png") == user_a["id"]
        assert edb.get_resource_owner("/assets/uploads/enhance-input-a.png") == user_a["id"]
        await _assert_forbidden("api/local-assets/delete", "POST", actor_a, {"names": ["owned-a.png"]})
        await _assert_forbidden("api/local-assets/import-urls", "POST", actor_a, {"urls": ["https://example.test/a.png"]})
        assert interceptors.can_access_resource(actor_a, "/assets/uploads/owned-a.png") is True
        assert interceptors.can_access_resource(actor_b, "/assets/uploads/owned-a.png") is False

        # History delete and system update are gated independently.
        await admin_api.update_user_feature_override(
            user_a["id"],
            "history_batch_delete",
            FakeRequest(actor_admin, {"mode": "deny"}),
        )
        await _assert_forbidden("api/history/delete", "POST", actor_a, {"timestamp": 1})
        await _assert_forbidden("api/update-from-github", "POST", actor_a, {"auto_restart": False})
        await admin_api.update_user_feature_override(
            user_a["id"],
            "system_update",
            FakeRequest(actor_admin, {"mode": "allow"}),
        )
        await _assert_allowed("api/update-from-github", "POST", actor_a, {"auto_restart": False})

        # Admin API readback includes effective values.
        readback = await admin_api.list_user_feature_overrides(
            user_a["id"],
            FakeRequest(actor_admin),
        )
        readback_map = {item["feature_key"]: item for item in readback["features"]}
        assert readback_map["system_update"]["mode"] == "allow"
        assert readback_map["system_update"]["effective_allowed"] is True

        logs, _total = edb.get_logs(limit=200)
        actions = {row["action"] for row in logs}
        assert "feature_flag_changed" in actions
        assert "user_feature_override_changed" in actions
        assert "permission_policy_updated" in actions

        logs_html = (ROOT / "enterprise-static" / "logs.html").read_text(encoding="utf-8")
        assert 'value="feature_flag_changed"' in logs_html
        assert 'value="user_feature_override_changed"' in logs_html
        assert 'value="permission_policy_updated"' in logs_html

    print("feature flag checks passed")


if __name__ == "__main__":
    asyncio.run(_run_checks())
