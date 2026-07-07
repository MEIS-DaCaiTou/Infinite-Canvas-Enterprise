"""
Non-destructive API/workflow settings permission guard checks.

This script uses a temporary SQLite database and calls enterprise
interceptors directly. It does not read or write real provider settings,
workflow files, env files, runtime assets, or upstream data.

Run from the repository root:

    python .\enterprise\tests\test_settings_permission_guard.py
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
    os.environ.setdefault("JWT_SECRET", "test-secret-for-settings-guard-1234567890")
    os.environ.setdefault("ADMIN_USERNAME", "admin")
    os.environ.setdefault("ADMIN_PASSWORD", "change-me-in-tests")


def _json_body(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


async def _filtered_json(path: str, method: str, payload, actor: dict):
    body, _headers = await interceptors.post_process(
        path,
        method,
        200,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "application/json",
        actor,
    )
    return json.loads(body.decode("utf-8"))


async def _assert_forbidden(path: str, method: str, actor: dict, payload=None) -> None:
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    denied = await interceptors.pre_process(path, method, actor, body=body)
    assert denied is not None, f"{method} {path} should be denied"
    assert denied.status_code == 403, f"{method} {path} returned {denied.status_code}"


async def _assert_allowed(path: str, method: str, actor: dict, payload=None) -> None:
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    allowed = await interceptors.pre_process(path, method, actor, body=body)
    assert allowed is None, f"{method} {path} should be allowed, got {_json_body(allowed)}"


def _assert_no_sensitive_config(data) -> None:
    dumped = json.dumps(data, ensure_ascii=False).lower()
    forbidden = [
        "sk-secret",
        "ms-secret-token",
        "wallet-secret",
        "volc-secret",
        "https://sensitive.example",
        "https://provider.example",
        "api_key",
        "\"token\"",
        "api_token",
        "access_token",
        "secret",
        "credential",
        "base_url",
        "key_preview",
        "wallet_key",
        "access_key",
    ]
    for text in forbidden:
        assert text not in dumped, f"sensitive settings leaked: {text}"


async def _run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-settings-guard-") as raw_tmp:
        tmp = Path(raw_tmp)
        _prepare_env(tmp)

        from enterprise import db as edb
        from enterprise import interceptors as enterprise_interceptors

        globals()["interceptors"] = enterprise_interceptors

        edb.init_db()
        user_a = edb.create_user("settings_a", "password-a", "Settings A", False)
        user_b = edb.create_user("settings_b", "password-b", "Settings B", False)
        admin = edb.get_user_by_username("admin")

        actor_a = {"user_id": user_a["id"], "username": "settings_a", "is_admin": False}
        actor_b = {"user_id": user_b["id"], "username": "settings_b", "is_admin": False}
        actor_admin = {"user_id": admin["id"], "username": "admin", "is_admin": True}

        provider_payload = [
            {
                "id": "custom-api",
                "name": "Custom API",
                "base_url": "https://provider.example/v1",
                "api_key": "sk-secret",
                "image_models": ["gpt-image-2"],
                "chat_models": ["gpt-5.5"],
                "video_models": ["video-1"],
                "enabled": True,
            }
        ]

        token_response = await interceptors.pre_process("api/config/token", "GET", actor_a)
        assert token_response is not None and token_response.status_code == 200
        token_body = _json_body(token_response)
        assert token_body["enterprise_managed"] is True
        assert token_body["token"] == interceptors.MANAGED_MODELSCOPE_TOKEN
        assert "sk-" not in token_body["token"].lower()
        rewritten = interceptors.rewrite_managed_modelscope_token_body(
            "api/ms/generate",
            json.dumps({"api_key": token_body["token"], "prompt": "hello"}, ensure_ascii=False).encode("utf-8"),
        )
        assert json.loads(rewritten.decode("utf-8"))["api_key"] == ""

        await _assert_forbidden("api/providers", "GET", actor_a)
        await _assert_forbidden("api/providers", "GET", actor_b)
        await _assert_forbidden("api/providers", "PUT", actor_a, provider_payload)
        await _assert_forbidden("api/providers/custom-api", "DELETE", actor_a)
        await _assert_forbidden("api/providers/test-connection", "POST", actor_a, {"base_url": "https://provider.example/v1"})
        await _assert_forbidden("api/providers/probe-async", "POST", actor_a, {"provider_id": "custom-api"})
        await _assert_forbidden("api/providers/fetch-models", "POST", actor_a, {"api_key": "sk-secret"})
        await _assert_forbidden("api/providers/custom-api/fetch-models", "GET", actor_a)
        await _assert_forbidden("api/codex/status", "GET", actor_a)
        await _assert_forbidden("api/codex/help", "POST", actor_a, {"command": "codex --help"})
        await _assert_forbidden("api/gemini-cli/status", "GET", actor_a)
        await _assert_forbidden("api/gemini-cli/help", "POST", actor_a, {"command": "gemini --help"})

        config_payload = {
            "base_url": "https://sensitive.example/v1",
            "chat_model": "gpt-5.5",
            "image_model": "gpt-image-2",
            "chat_models": ["gpt-5.5"],
            "image_models": ["gpt-image-2"],
            "video_models": ["video-1"],
            "comfy_instances": ["127.0.0.1:8188"],
            "has_api_key": True,
            "has_ms_key": True,
            "token": "ms-secret-token",
            "api_token": "api-token-secret",
            "access_token": "access-token-secret",
            "max_tokens": 4096,
            "tokens": {"input": 12, "output": 34},
            "tokenizer": "cl100k_base",
            "api_providers": [
                {
                    "id": "custom-api",
                    "name": "Custom API",
                    "enabled": True,
                    "protocol": "openai",
                    "base_url": "https://provider.example/v1",
                    "key_preview": "sk-...cret",
                    "has_key": True,
                    "key_env": "API_PROVIDER_CUSTOM_API_KEY",
                    "image_models": ["gpt-image-2"],
                    "chat_models": ["gpt-5.5"],
                    "credential": "raw-credential",
                },
                {
                    "id": "runninghub",
                    "name": "RunningHub",
                    "wallet_key_preview": "wallet-secret",
                    "has_wallet_key": True,
                    "rh_workflows": [
                        {
                            "workflowId": "wf-1",
                            "title": "Workflow",
                            "raw": {"secret": "raw-secret"},
                        }
                    ],
                },
                {
                    "id": "volcengine",
                    "name": "Volcengine",
                    "volcengine_access_key_preview": "volc-ak",
                    "volcengine_secret_key_preview": "volc-secret",
                    "has_volcengine_secret_key": True,
                },
            ],
        }
        filtered_config = await _filtered_json("api/config", "GET", config_payload, actor_a)
        assert filtered_config["chat_models"] == ["gpt-5.5"]
        assert filtered_config["image_models"] == ["gpt-image-2"]
        assert filtered_config["max_tokens"] == 4096
        assert filtered_config["tokens"] == {"input": 12, "output": 34}
        assert filtered_config["tokenizer"] == "cl100k_base"
        assert filtered_config["comfy_instances"] == ["configured"]
        assert filtered_config["api_providers"][0]["id"] == "custom-api"
        assert "127.0.0.1:8188" not in json.dumps(filtered_config, ensure_ascii=False)
        _assert_no_sensitive_config(filtered_config)

        admin_config = await _filtered_json("api/config", "GET", config_payload, actor_admin)
        assert admin_config["base_url"] == "https://sensitive.example/v1"
        assert admin_config["api_providers"][0]["key_preview"] == "sk-...cret"

        workflow_payload = {
            "name": "custom/guarded.json",
            "workflow": {
                "1": {
                    "class_type": "MockNode",
                    "inputs": {
                        "prompt": "hello",
                        "api_key": "sk-secret",
                        "base_url": "https://provider.example/v1",
                    },
                }
            },
            "config": {
                "title": "Guarded Workflow",
                "fields": [{"id": "prompt", "label": "Prompt"}],
                "raw": {"token": "ms-secret-token"},
            },
        }
        await _assert_allowed("api/workflows", "GET", actor_a)
        await _assert_allowed("api/workflows/custom/guarded.json", "GET", actor_a)
        filtered_workflow = await _filtered_json("api/workflows/custom/guarded.json", "GET", workflow_payload, actor_a)
        assert filtered_workflow["name"] == "custom/guarded.json"
        assert filtered_workflow["workflow"]["1"]["inputs"]["prompt"] == "hello"
        _assert_no_sensitive_config(filtered_workflow)

        await _assert_forbidden("api/workflows", "POST", actor_a, workflow_payload)
        await _assert_forbidden("api/workflows/custom/guarded.json/config", "PUT", actor_a, {"title": "Blocked"})
        await _assert_forbidden("api/workflows/custom/guarded.json", "DELETE", actor_a)
        await _assert_forbidden("api/workflows/custom/guarded.json/run", "POST", actor_a, {"fields": {}})
        await _assert_allowed("api/generate", "POST", actor_a, {"workflow_json": "custom/guarded.json", "params": {}})
        await _assert_allowed("api/canvas-comfy-tasks", "POST", actor_a, {"workflow_json": "custom/guarded.json"})
        await _assert_forbidden("api/comfyui/instances", "GET", actor_a)
        await _assert_forbidden("api/comfyui/instances", "PUT", actor_a, {"instances": ["127.0.0.1:8188"]})

        await _assert_forbidden("api/runninghub/workflows", "GET", actor_a)
        await _assert_forbidden("api/runninghub/workflows/fetch", "POST", actor_a, {"workflowId": "wf-1"})
        await _assert_forbidden("api/runninghub/workflows/wf-1", "PUT", actor_a, {"workflowId": "wf-1"})
        await _assert_forbidden("api/runninghub/workflows/wf-1", "DELETE", actor_a)
        await _assert_forbidden("api/runninghub/app-info", "GET", actor_a)
        await _assert_forbidden("api/runninghub/workflow-info", "GET", actor_a)
        await _assert_allowed("api/runninghub/workflows/wf-1", "GET", actor_a)
        filtered_rh = await _filtered_json(
            "api/runninghub/workflows/wf-1",
            "GET",
            {"workflow": {"workflowId": "wf-1", "raw": {"secret": "raw-secret"}, "fields": [{"id": "prompt"}]}},
            actor_a,
        )
        assert filtered_rh["workflow"]["workflowId"] == "wf-1"
        _assert_no_sensitive_config(filtered_rh)

        await _assert_forbidden("api/jimeng/status", "GET", actor_a)
        await _assert_forbidden("api/jimeng/login/start", "POST", actor_a)
        await _assert_forbidden("api/jimeng/logout", "POST", actor_a)
        await _assert_allowed("api/jimeng/query-media", "POST", actor_a, {"submit_id": "task-1"})

        admin_paths = [
            ("api/providers", "PUT", provider_payload),
            ("api/providers/test-connection", "POST", {"provider_id": "custom-api", "api_key": "sk-secret"}),
            ("api/providers/probe-async", "POST", {"provider_id": "custom-api"}),
            ("api/providers/fetch-models", "POST", {"provider_id": "custom-api"}),
            ("api/providers/custom-api/fetch-models", "GET", None),
            ("api/codex/status", "GET", None),
            ("api/codex/help", "POST", {"command": "codex --help"}),
            ("api/gemini-cli/status", "GET", None),
            ("api/gemini-cli/help", "POST", {"command": "gemini --help"}),
            ("api/workflows", "POST", workflow_payload),
            ("api/workflows/custom/guarded.json/config", "PUT", {"title": "Allowed"}),
            ("api/workflows/custom/guarded.json", "DELETE", None),
            ("api/workflows/custom/guarded.json/run", "POST", {"fields": {}}),
            ("api/comfyui/instances", "PUT", {"instances": ["127.0.0.1:8188"]}),
            ("api/runninghub/workflows/fetch", "POST", {"workflowId": "wf-1"}),
            ("api/runninghub/workflows/wf-1", "PUT", {"workflowId": "wf-1"}),
            ("api/runninghub/workflows/wf-1", "DELETE", None),
            ("api/runninghub/app-info", "GET", None),
            ("api/runninghub/workflow-info", "GET", None),
            ("api/jimeng/login/start", "POST", None),
            ("api/jimeng/logout", "POST", None),
        ]
        for path, method, payload in admin_paths:
            await _assert_allowed(path, method, actor_admin, payload)

        logs, _total = edb.get_logs(limit=100)
        actions = {row["action"] for row in logs}
        expected_actions = {
            "settings_provider_saved",
            "settings_provider_tested",
            "settings_provider_probed",
            "settings_provider_models_fetched",
            "settings_cli_status_checked",
            "settings_cli_help_viewed",
            "settings_workflow_uploaded",
            "settings_workflow_config_saved",
            "settings_workflow_deleted",
            "settings_workflow_tested",
            "settings_comfy_instances_saved",
            "settings_runninghub_workflow_fetched",
            "settings_runninghub_workflow_saved",
            "settings_runninghub_workflow_deleted",
            "settings_runninghub_metadata_fetched",
            "settings_jimeng_accessed",
        }
        missing = expected_actions - actions
        assert not missing, f"missing audit actions: {sorted(missing)}"
        for row in logs:
            assert "sk-secret" not in str(row.get("detail") or "")
            assert "ms-secret-token" not in str(row.get("detail") or "")

    print("settings permission guard checks passed")


if __name__ == "__main__":
    asyncio.run(_run_checks())
