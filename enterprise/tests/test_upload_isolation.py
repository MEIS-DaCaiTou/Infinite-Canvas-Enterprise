"""
Non-destructive upload resource isolation checks.

This script uses a temporary SQLite database and temporary canvas/conversation
files. It does not read or write real runtime assets, databases, or outputs.

Run from the repository root:

    python .\\enterprise\\tests\\test_upload_isolation.py
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
    os.environ.setdefault("JWT_SECRET", "test-secret-for-upload-isolation-1234567890")
    os.environ.setdefault("ADMIN_USERNAME", "admin")
    os.environ.setdefault("ADMIN_PASSWORD", "change-me-in-tests")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


async def _post_json(path: str, method: str, status: int, payload, actor: dict, request_body=None):
    body, _headers = await interceptors.post_process(
        path,
        method,
        status,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "application/json",
        actor,
        json.dumps(request_body, ensure_ascii=False).encode("utf-8") if request_body is not None else None,
    )
    return json.loads(body.decode("utf-8"))


def _body(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


async def _run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-upload-") as raw_tmp:
        tmp = Path(raw_tmp)
        _prepare_env(tmp)

        from enterprise import db as edb
        from enterprise import interceptors as interceptors_module

        globals()["interceptors"] = interceptors_module

        canvas_dir = tmp / "canvases"
        conversation_dir = tmp / "conversations"
        canvas_dir.mkdir()
        conversation_dir.mkdir()
        interceptors._CANVAS_DATA_DIR = canvas_dir
        interceptors._CONVERSATION_DATA_DIR = conversation_dir
        interceptors._ASSET_LIBRARY_FILE = tmp / "asset_library.json"
        edb._conversation_root = lambda: str(conversation_dir)
        edb.CANVAS_DATA_DIR = str(canvas_dir)

        edb.init_db()
        user_a = edb.create_user("upload_a", "password-a", "Upload A", False)
        user_b = edb.create_user("upload_b", "password-b", "Upload B", False)
        admin = edb.get_user_by_username("admin")

        actor_a = {"user_id": user_a["id"], "username": "upload_a", "is_admin": False}
        actor_b = {"user_id": user_b["id"], "username": "upload_b", "is_admin": False}
        actor_admin = {"user_id": admin["id"], "username": "admin", "is_admin": True}

        # New upload owner recording.
        await _post_json("api/ai/upload", "POST", 200, {"files": [{"url": "/assets/input/ai-a.png"}]}, actor_a)
        await _post_json("api/ai/upload-base64", "POST", 200, {"files": [{"url": "/assets/input/base64-a.png"}]}, actor_a)
        await _post_json("api/ai/import-local-image", "POST", 200, {"files": [{"url": "/assets/input/import-a.png"}]}, actor_a)
        await _post_json("api/local-assets/upload", "POST", 200, {"files": [{"url": "/assets/uploads/local-a.png"}]}, actor_a)
        await _post_json("api/local-assets/import-urls", "POST", 200, {"files": [{"url": "/assets/uploads/import-a.png"}]}, actor_a)
        await _post_json(
            "api/canvas-workflows/import",
            "POST",
            200,
            {"resource_map": {"old": "/assets/input/workflow-a.png"}},
            actor_a,
        )
        await _post_json("api/upload", "POST", 200, {"files": [{"comfy_name": "comfy-a.png"}]}, actor_a)
        await _post_json("api/comfyui/upload-base64", "POST", 200, {"name": "comfy-base64-a.png"}, actor_a)
        await _post_json("api/local-assets/upload", "POST", 200, {"files": [{"url": "/assets/uploads/local-b.png"}]}, actor_b)

        expected_a = {
            "/assets/input/ai-a.png",
            "/assets/input/base64-a.png",
            "/assets/input/import-a.png",
            "/assets/uploads/local-a.png",
            "/assets/uploads/import-a.png",
            "/assets/input/workflow-a.png",
            "/assets/input/comfy-a.png",
            "/assets/input/comfy-base64-a.png",
        }
        for resource_url in expected_a:
            assert edb.get_resource_owner(resource_url) == user_a["id"], resource_url
            assert interceptors.can_access_resource(actor_a, resource_url) is True
            assert interceptors.can_access_resource(actor_b, resource_url) is False
            assert interceptors.can_access_resource(actor_admin, resource_url) is True
        assert edb.get_resource_owner("/assets/uploads/local-b.png") == user_b["id"]
        assert interceptors.can_access_resource(actor_b, "/assets/uploads/local-b.png") is True
        assert interceptors.can_access_resource(actor_a, "/assets/uploads/local-b.png") is False
        assert interceptors.can_access_resource(actor_a, "/assets/input/unowned-upload.png") is False
        assert interceptors.can_access_resource(actor_admin, "/assets/input/unowned-upload.png") is True

        # Direct preview/conversion access checks.
        assert await interceptors.pre_process(
            "api/media-preview",
            "GET",
            actor_a,
            query_params={"url": "/assets/uploads/local-a.png"},
        ) is None
        denied_preview = await interceptors.pre_process(
            "api/media-preview",
            "GET",
            actor_b,
            query_params={"url": "/assets/uploads/local-a.png"},
        )
        assert denied_preview is not None and denied_preview.status_code == 404
        denied_jpeg = await interceptors.pre_process(
            "api/image-jpeg",
            "GET",
            actor_b,
            query_params={"url": "/assets/input/ai-a.png"},
        )
        assert denied_jpeg is not None and denied_jpeg.status_code == 404
        denied_view = await interceptors.pre_process(
            "api/view",
            "GET",
            actor_b,
            query_params={"filename": "comfy-a.png", "type": "input"},
        )
        assert denied_view is not None and denied_view.status_code == 404

        # local-assets GET filters both items and tree counts by direct owner.
        local_assets_payload = {
            "items": [
                {"id": "a", "file": "local-a.png", "url": "/assets/uploads/local-a.png"},
                {"id": "b", "file": "local-b.png", "url": "/assets/uploads/local-b.png"},
                {"id": "legacy", "file": "legacy.png", "url": "/assets/uploads/legacy.png"},
            ],
            "tree": {
                "id": "__root__",
                "path": "",
                "name": "all",
                "count": 3,
                "items": [
                    {"id": "a", "file": "local-a.png", "url": "/assets/uploads/local-a.png"},
                    {"id": "b", "file": "local-b.png", "url": "/assets/uploads/local-b.png"},
                    {"id": "legacy", "file": "legacy.png", "url": "/assets/uploads/legacy.png"},
                ],
                "children": [
                    {
                        "id": "folder",
                        "path": "folder",
                        "name": "folder",
                        "count": 1,
                        "items": [
                            {"id": "nested", "file": "folder/nested-a.png", "url": "/assets/uploads/folder/nested-a.png"},
                        ],
                        "children": [],
                    }
                ],
            },
        }
        edb.record_resource_owner(user_a["id"], "/assets/uploads/folder/nested-a.png", "seed")
        visible_a = await _post_json("api/local-assets", "GET", 200, local_assets_payload, actor_a)
        assert [item["id"] for item in visible_a["items"]] == ["a"]
        assert visible_a["tree"]["count"] == 2
        assert [item["id"] for item in visible_a["tree"]["items"]] == ["a"]
        assert visible_a["tree"]["children"][0]["count"] == 1
        assert visible_a["tree"]["children"][0]["items"][0]["id"] == "nested"

        # local-assets path/name write operations require the true resource owner.
        for path, payload in [
            ("api/local-assets/delete", {"names": ["local-a.png"]}),
            ("api/local-assets/move", {"names": ["local-a.png"], "folder": "moved"}),
            ("api/local-assets/items", {"path": "local-a.png", "name": "renamed"}),
            ("api/local-assets/caption", {"names": ["local-a.png"], "prompt": "describe"}),
            ("api/local-assets/classify", {"names": ["local-a.png"]}),
        ]:
            denied = await interceptors.pre_process(path, "POST" if path != "api/local-assets/items" else "PATCH", actor_b, body=_body(payload))
            assert denied is not None and denied.status_code == 404, path
            allowed = await interceptors.pre_process(path, "POST" if path != "api/local-assets/items" else "PATCH", actor_a, body=_body(payload))
            assert allowed is None, path

        denied_unowned_delete = await interceptors.pre_process(
            "api/local-assets/delete",
            "POST",
            actor_a,
            body=_body({"names": ["legacy.png"]}),
        )
        assert denied_unowned_delete is not None and denied_unowned_delete.status_code == 404

        admin_delete = await interceptors.pre_process(
            "api/local-assets/delete",
            "POST",
            actor_admin,
            body=_body({"names": ["local-a.png"]}),
        )
        admin_move = await interceptors.pre_process(
            "api/local-assets/move",
            "POST",
            actor_admin,
            body=_body({"names": ["local-a.png"], "folder": "admin-moved"}),
        )
        assert admin_delete is None and admin_move is None
        logs, _total = edb.get_logs(limit=20)
        actions = [row["action"] for row in logs]
        assert "local_asset_deleted" in actions
        assert "local_asset_moved" in actions

        # Response ownership for renames/moves preserves the original true owner.
        await _post_json(
            "api/local-assets/items",
            "PATCH",
            200,
            {"item": {"url": "/assets/uploads/local-a-renamed.png"}},
            actor_a,
            request_body={"path": "local-a.png", "name": "local-a-renamed"},
        )
        assert edb.get_resource_owner("/assets/uploads/local-a-renamed.png") == user_a["id"]
        await _post_json(
            "api/local-assets/move",
            "POST",
            200,
            {"ok": True, "items": [{"url": "/assets/uploads/moved/local-a.png"}]},
            actor_a,
            request_body={"names": ["local-a.png"], "folder": "moved"},
        )
        assert edb.get_resource_owner("/assets/uploads/moved/local-a.png") == user_a["id"]

        # Asset-library is backed by data/asset_library.json and /assets/library/*.
        # The full material-library business model remains a later task, but normal
        # users must not see or manage another user's library files.
        asset_a = {
            "id": "asset_a",
            "name": "Library A",
            "url": "/assets/library/characters/lib-a.png",
            "kind": "image",
            "created_at": 1,
        }
        asset_b = {
            "id": "asset_b",
            "name": "Library B",
            "url": "/assets/library/characters/lib-b.png",
            "kind": "image",
            "created_at": 2,
        }
        asset_admin = {
            "id": "asset_admin",
            "name": "Library Admin",
            "url": "/assets/library/characters/lib-admin.png",
            "kind": "image",
            "created_at": 3,
        }
        asset_legacy = {
            "id": "asset_legacy",
            "name": "Library Legacy",
            "url": "/assets/library/characters/lib-legacy.png",
            "kind": "image",
            "created_at": 4,
        }

        await _post_json("api/asset-library/items", "POST", 200, {"item": asset_a, "library": {"libraries": []}}, actor_a)
        await _post_json("api/asset-library/items", "POST", 200, {"item": asset_admin, "library": {"libraries": []}}, actor_admin)
        await _post_json(
            "api/asset-library/items/batch",
            "POST",
            200,
            {
                "items": [asset_b],
                "library": {
                    "libraries": [
                        {"id": "default", "categories": [{"id": "characters", "items": [asset_a, asset_admin, asset_b, asset_legacy]}]}
                    ]
                },
            },
            actor_b,
        )
        assert edb.get_resource_owner("/assets/library/characters/lib-a.png") == user_a["id"]
        assert edb.get_resource_owner("/assets/library/characters/lib-b.png") == user_b["id"]
        assert edb.get_resource_owner("/assets/library/characters/lib-admin.png") == admin["id"]
        assert edb.get_resource_owner("/assets/library/characters/lib-legacy.png") is None

        asset_library_data = {
            "active_library_id": "default",
            "categories": [
                {"id": "characters", "name": "Characters", "type": "image", "items": [asset_a, asset_b, asset_admin, asset_legacy]},
                {"id": "empty", "name": "Empty", "type": "image", "items": []},
            ],
            "libraries": [
                {
                    "id": "default",
                    "name": "Default Library",
                    "type": "asset",
                    "categories": [
                        {"id": "characters", "name": "Characters", "type": "image", "items": [asset_a, asset_b, asset_admin, asset_legacy]},
                        {"id": "empty", "name": "Empty", "type": "image", "items": []},
                    ],
                }
            ],
            "updated_at": 10,
        }
        _write_json(interceptors._ASSET_LIBRARY_FILE, asset_library_data)

        def library_urls(payload: dict) -> list[str]:
            lib = payload.get("library") or payload
            urls = []
            for library in lib.get("libraries") or []:
                for category in library.get("categories") or []:
                    for item in category.get("items") or []:
                        if isinstance(item, dict) and item.get("url"):
                            urls.append(item["url"])
            return urls

        visible_a_assets = await _post_json("api/asset-library", "GET", 200, {"library": asset_library_data}, actor_a)
        visible_b_assets = await _post_json("api/asset-library", "GET", 200, {"library": asset_library_data}, actor_b)
        visible_admin_assets = await _post_json("api/asset-library", "GET", 200, {"library": asset_library_data}, actor_admin)
        assert library_urls(visible_a_assets) == ["/assets/library/characters/lib-a.png"]
        assert library_urls(visible_b_assets) == ["/assets/library/characters/lib-b.png"]
        assert set(library_urls(visible_admin_assets)) == {
            "/assets/library/characters/lib-a.png",
            "/assets/library/characters/lib-b.png",
            "/assets/library/characters/lib-admin.png",
            "/assets/library/characters/lib-legacy.png",
        }
        assert [
            item["url"]
            for item in visible_b_assets["library"]["categories"][0]["items"]
        ] == ["/assets/library/characters/lib-b.png"]

        for path, method, payload in [
            ("api/asset-library/items/asset_a", "PATCH", {"name": "rename"}),
            ("api/asset-library/items/asset_a", "DELETE", None),
            ("api/asset-library/items/delete", "POST", {"library_id": "default", "ids": ["asset_a"]}),
            ("api/asset-library/items/move", "POST", {"library_id": "default", "target_category_id": "empty", "ids": ["asset_a"]}),
            ("api/asset-library/items/classify", "POST", {"library_id": "default", "ids": ["asset_a"]}),
            ("api/asset-library/items/asset_legacy", "PATCH", {"name": "rename"}),
            ("api/asset-library/items/delete", "POST", {"library_id": "default", "ids": ["asset_legacy"]}),
        ]:
            denied = await interceptors.pre_process(path, method, actor_b, body=_body(payload) if payload is not None else None)
            assert denied is not None and denied.status_code == 404, path

        for path, method, payload in [
            ("api/asset-library/items/asset_b", "PATCH", {"name": "rename"}),
            ("api/asset-library/items/delete", "POST", {"library_id": "default", "ids": ["asset_b"]}),
            ("api/asset-library/items/move", "POST", {"library_id": "default", "target_category_id": "empty", "ids": ["asset_b"]}),
        ]:
            allowed = await interceptors.pre_process(path, method, actor_b, body=_body(payload) if payload is not None else None)
            assert allowed is None, path

        admin_asset_delete = await interceptors.pre_process(
            "api/asset-library/items/delete",
            "POST",
            actor_admin,
            body=_body({"library_id": "default", "ids": ["asset_a"]}),
        )
        admin_asset_move = await interceptors.pre_process(
            "api/asset-library/items/move",
            "POST",
            actor_admin,
            body=_body({"library_id": "default", "target_category_id": "empty", "ids": ["asset_a"]}),
        )
        assert admin_asset_delete is None and admin_asset_move is None
        logs, _total = edb.get_logs(limit=50)
        actions = [row["action"] for row in logs]
        assert "asset_library_deleted" in actions
        assert "asset_library_moved" in actions

        # Existing uploaded resources cannot be reused by another normal user as model inputs.
        for path, payload in [
            ("api/online-image", {"reference_images": [{"url": "/assets/input/ai-a.png"}]}),
            ("api/chat", {"message": "x", "reference_images": [{"url": "/assets/uploads/local-a.png"}]}),
            ("api/chat/stream", {"message": "x", "reference_images": [{"url": "/assets/uploads/local-a.png"}]}),
            ("api/generate", {"params": {"15": {"image": "comfy-a.png"}}}),
            ("api/canvas-comfy-tasks", {"params": {"15": {"image": "comfy-a.png"}}}),
            ("api/canvas-image-tasks", {"reference_images": [{"url": "/assets/input/ai-a.png"}]}),
            ("api/runninghub/upload-asset", {"url": "/assets/uploads/local-a.png"}),
            ("api/runninghub/submit", {"nodeInfoList": [{"fieldName": "image", "fieldValue": "/assets/uploads/local-a.png"}]}),
            ("api/runninghub/workflow-submit", {"nodeInfoList": [{"fieldName": "image", "fieldValue": "/assets/uploads/local-a.png"}]}),
        ]:
            denied = await interceptors.pre_process(path, "POST", actor_b, body=_body(payload))
            assert denied is not None and denied.status_code == 404, path
            allowed = await interceptors.pre_process(path, "POST", actor_a, body=_body(payload))
            assert allowed is None, path

        denied_unowned_input = await interceptors.pre_process(
            "api/online-image",
            "POST",
            actor_a,
            body=_body({"reference_images": [{"url": "/assets/input/unowned-upload.png"}]}),
        )
        assert denied_unowned_input is not None and denied_unowned_input.status_code == 404

        # Canvas transfer keeps true resource owner but allows the new canvas owner to render/run referenced resources.
        _write_json(canvas_dir / "transfer_canvas.json", {
            "id": "transfer_canvas",
            "title": "Transferred Canvas",
            "nodes": [
                {"image": "/assets/input/ai-a.png"},
                {"image": "/assets/input/comfy-a.png"},
                {"image": "/assets/uploads/local-a.png"},
            ],
        })
        edb.set_canvas_owner("transfer_canvas", user_a["id"])
        assert edb.get_resource_owner("/assets/input/ai-a.png") == user_a["id"]
        edb.set_canvas_owner("transfer_canvas", user_b["id"])
        assert edb.get_resource_owner("/assets/input/ai-a.png") == user_a["id"]
        assert interceptors.can_access_resource(actor_a, "/assets/input/ai-a.png") is True
        assert interceptors.can_access_resource(actor_b, "/assets/input/ai-a.png") is True
        assert interceptors.can_access_resource(actor_b, "/assets/input/comfy-a.png") is True
        assert interceptors.can_access_resource(actor_b, "/assets/uploads/local-a.png") is True

        transferred_generate = await interceptors.pre_process(
            "api/generate",
            "POST",
            actor_b,
            body=_body({"params": {"15": {"image": "comfy-a.png"}}}),
        )
        assert transferred_generate is None

        # The transferred canvas grants read/run access only; it does not let B manage A's upload.
        denied_transferred_delete = await interceptors.pre_process(
            "api/local-assets/delete",
            "POST",
            actor_b,
            body=_body({"names": ["local-a.png"]}),
        )
        assert denied_transferred_delete is not None and denied_transferred_delete.status_code == 404

    print("upload isolation checks passed")


if __name__ == "__main__":
    asyncio.run(_run_checks())
