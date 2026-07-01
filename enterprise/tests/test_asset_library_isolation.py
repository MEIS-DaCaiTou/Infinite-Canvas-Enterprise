"""
Asset-library business owner isolation checks.

This script uses a temporary SQLite database and temporary asset-library JSON.
It does not read or write real runtime assets, databases, outputs, or secrets.

Run from the repository root:

    python .\\enterprise\\tests\\test_asset_library_isolation.py
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
    os.environ.setdefault("JWT_SECRET", "test-secret-for-asset-library-isolation")
    os.environ.setdefault("ADMIN_USERNAME", "admin")
    os.environ.setdefault("ADMIN_PASSWORD", "change-me-in-tests")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _body(payload: dict | None) -> bytes | None:
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


async def _post_json(path: str, method: str, status: int, payload, actor: dict, request_body=None):
    body, _headers = await interceptors.post_process(
        path,
        method,
        status,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "application/json",
        actor,
        _body(request_body),
    )
    return json.loads(body.decode("utf-8"))


def _item(item_id: str, name: str, url: str, created_at: int = 1) -> dict:
    return {
        "id": item_id,
        "name": name,
        "url": url,
        "kind": "image",
        "created_at": created_at,
    }


def _library_urls(payload: dict) -> list[str]:
    lib = payload.get("library") or payload
    urls = []
    for library in lib.get("libraries") or []:
        for category in library.get("categories") or []:
            for item in category.get("items") or []:
                if isinstance(item, dict) and item.get("url"):
                    urls.append(item["url"])
    return urls


def _library_ids(payload: dict) -> set[str]:
    lib = payload.get("library") or payload
    return {str(item.get("id") or "") for item in (lib.get("libraries") or []) if isinstance(item, dict)}


def _category_ids(payload: dict) -> set[str]:
    lib = payload.get("library") or payload
    ids = set()
    for library in lib.get("libraries") or []:
        for category in library.get("categories") or []:
            if isinstance(category, dict):
                ids.add(str(category.get("id") or ""))
    return ids


async def _assert_denied(path: str, method: str, actor: dict, payload=None, query_params=None) -> None:
    response = await interceptors.pre_process(path, method, actor, query_params=query_params, body=_body(payload))
    assert response is not None and response.status_code in {403, 404}, path


async def _assert_allowed(path: str, method: str, actor: dict, payload=None, query_params=None) -> None:
    response = await interceptors.pre_process(path, method, actor, query_params=query_params, body=_body(payload))
    assert response is None, path


async def _run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-asset-library-") as raw_tmp:
        tmp = Path(raw_tmp)
        _prepare_env(tmp)

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
        user_a = edb.create_user("asset_a", "password-a", "Asset A", False)
        user_b = edb.create_user("asset_b", "password-b", "Asset B", False)
        admin = edb.get_user_by_username("admin")

        actor_a = {"user_id": user_a["id"], "username": "asset_a", "is_admin": False}
        actor_b = {"user_id": user_b["id"], "username": "asset_b", "is_admin": False}
        actor_admin = {"user_id": admin["id"], "username": "admin", "is_admin": True}

        default_a = _item("default_a", "Default A", "/assets/library/characters/default-a.png", 1)
        default_b = _item("default_b", "Default B", "/assets/library/characters/default-b.png", 2)
        default_admin = _item("default_admin", "Default Admin", "/assets/library/characters/default-admin.png", 3)
        legacy = _item("legacy", "Legacy", "/assets/library/characters/legacy.png", 4)
        item_a = _item("item_a", "Item A", "/assets/library/a/item-a.png", 5)
        item_b = _item("item_b", "Item B", "/assets/library/b/item-b.png", 6)

        lib_a = {
            "id": "lib_a",
            "name": "A Library",
            "type": "asset",
            "categories": [
                {"id": "cat_a", "name": "A Category", "type": "image", "items": [item_a]},
                {"id": "cat_a_empty", "name": "A Empty", "type": "image", "items": []},
            ],
        }
        lib_b = {
            "id": "lib_b",
            "name": "B Library",
            "type": "asset",
            "categories": [
                {"id": "cat_b", "name": "B Category", "type": "image", "items": [item_b]},
                {"id": "cat_b_empty", "name": "B Empty", "type": "image", "items": []},
            ],
        }
        library_data = {
            "active_library_id": "lib_a",
            "libraries": [
                {
                    "id": "default",
                    "name": "默认资产库",
                    "type": "asset",
                    "categories": [
                        {"id": "characters", "name": "角色", "type": "image", "items": [default_a, default_b, default_admin, legacy]},
                        {"id": "legacy_custom", "name": "旧未归属分类", "type": "image", "items": []},
                        {"id": "workflows", "name": "工作流", "type": "workflow", "items": []},
                    ],
                },
                lib_a,
                lib_b,
            ],
            "categories": [],
            "updated_at": 1,
        }
        library_data["categories"] = library_data["libraries"][0]["categories"]

        # Response owner recording for new libraries/categories/items.
        await _post_json("api/asset-library/libraries", "POST", 200, {"library": library_data, "asset_library": lib_a}, actor_a)
        await _post_json("api/asset-library/libraries", "POST", 200, {"library": library_data, "asset_library": lib_b}, actor_b)
        await _post_json(
            "api/asset-library/categories",
            "POST",
            200,
            {"library": library_data, "category": lib_a["categories"][1]},
            actor_a,
            request_body={"library_id": "lib_a", "name": "A Empty", "type": "image"},
        )
        await _post_json(
            "api/asset-library/items",
            "POST",
            200,
            {"library": library_data, "item": default_a},
            actor_a,
            request_body={"library_id": "default", "category_id": "characters", "url": "/assets/output/a.png"},
        )
        await _post_json(
            "api/asset-library/items",
            "POST",
            200,
            {"library": library_data, "item": item_a},
            actor_a,
            request_body={"library_id": "lib_a", "category_id": "cat_a", "url": "/assets/output/a2.png"},
        )
        await _post_json(
            "api/asset-library/items/batch",
            "POST",
            200,
            {"library": library_data, "items": [default_b, item_b]},
            actor_b,
            request_body={"library_id": "default", "category_id": "characters", "items": [{"url": "/assets/output/b.png"}]},
        )
        await _post_json(
            "api/asset-library/items",
            "POST",
            200,
            {"library": library_data, "item": default_admin},
            actor_admin,
            request_body={"library_id": "default", "category_id": "characters", "url": "/assets/output/admin.png"},
        )
        _write_json(interceptors._ASSET_LIBRARY_FILE, library_data)

        assert edb.get_asset_object_owner("library", "lib_a") == user_a["id"]
        assert edb.get_asset_object_owner("library", "lib_b") == user_b["id"]
        assert edb.get_asset_object_owner("category", "cat_a") == user_a["id"]
        assert edb.get_asset_object_owner("category", "cat_b") == user_b["id"]
        assert edb.get_asset_object_owner("item", "item_a") == user_a["id"]
        assert edb.get_asset_object_owner("item", "item_b") == user_b["id"]
        assert edb.get_resource_owner("/assets/library/a/item-a.png") == user_a["id"]

        # Main material page and canvas side panel both rely on this same GET.
        visible_a = await _post_json("api/asset-library", "GET", 200, {"library": library_data}, actor_a)
        visible_a_side_panel = await _post_json("api/asset-library", "GET", 200, {"library": library_data}, actor_a)
        visible_b = await _post_json("api/asset-library", "GET", 200, {"library": library_data}, actor_b)
        visible_admin = await _post_json("api/asset-library", "GET", 200, {"library": library_data}, actor_admin)

        assert _library_urls(visible_a) == _library_urls(visible_a_side_panel)
        assert "/assets/library/a/item-a.png" in _library_urls(visible_a)
        assert "/assets/library/characters/default-a.png" in _library_urls(visible_a)
        assert "/assets/library/b/item-b.png" not in _library_urls(visible_a)
        assert "/assets/library/characters/default-admin.png" not in _library_urls(visible_a)
        assert "/assets/library/characters/legacy.png" not in _library_urls(visible_a)
        assert "lib_a" in _library_ids(visible_a)
        assert "lib_b" not in _library_ids(visible_a)
        assert "legacy_custom" not in _category_ids(visible_a)

        assert "/assets/library/b/item-b.png" in _library_urls(visible_b)
        assert "/assets/library/characters/default-b.png" in _library_urls(visible_b)
        assert "/assets/library/a/item-a.png" not in _library_urls(visible_b)
        assert "lib_b" in _library_ids(visible_b)
        assert "lib_a" not in _library_ids(visible_b)

        assert set(_library_urls(visible_admin)) == {
            "/assets/library/characters/default-a.png",
            "/assets/library/characters/default-b.png",
            "/assets/library/characters/default-admin.png",
            "/assets/library/characters/legacy.png",
            "/assets/library/a/item-a.png",
            "/assets/library/b/item-b.png",
        }

        # Cross-user and unowned management is denied, including id-based bypasses.
        await _assert_denied("api/asset-library/libraries/lib_a", "PATCH", actor_b, {"name": "steal"})
        await _assert_denied("api/asset-library/categories/cat_a", "PATCH", actor_b, {"library_id": "lib_a", "name": "steal"})
        await _assert_denied("api/asset-library/categories", "POST", actor_b, {"library_id": "lib_a", "name": "bad"})
        await _assert_denied("api/asset-library/items/item_a", "PATCH", actor_b, {"library_id": "lib_a", "name": "steal"})
        await _assert_denied("api/asset-library/items/item_a/register-avatar", "POST", actor_b, {"library_id": "lib_a", "provider_id": "volcengine"})
        await _assert_denied("api/asset-library/items/item_a/avatar-status", "POST", actor_b, {"library_id": "lib_a", "provider_id": "volcengine"})
        await _assert_denied("api/asset-library/items/legacy", "PATCH", actor_b, {"library_id": "default", "name": "legacy"})
        await _assert_denied("api/asset-library/items/delete", "POST", actor_b, {"library_id": "default", "ids": ["default_b", "default_a"]})
        await _assert_denied(
            "api/asset-library/items/move",
            "POST",
            actor_b,
            {"library_id": "default", "ids": ["default_b"], "target_library_id": "lib_a", "target_category_id": "cat_a"},
        )
        await _assert_denied(
            "api/asset-library/items/move",
            "POST",
            actor_b,
            {"library_id": "lib_a", "ids": ["item_a"], "target_library_id": "lib_b", "target_category_id": "cat_b"},
        )
        await _assert_denied(
            "api/asset-library/items",
            "POST",
            actor_b,
            {"library_id": "lib_b", "category_id": "cat_b", "url": "/assets/library/a/item-a.png", "name": "bad"},
        )

        # Own objects remain usable and manageable.
        await _assert_allowed("api/asset-library/libraries/lib_b", "PATCH", actor_b, {"name": "B2"})
        await _assert_allowed("api/asset-library/categories/cat_b", "PATCH", actor_b, {"library_id": "lib_b", "name": "B2"})
        await _assert_allowed("api/asset-library/items/item_b", "PATCH", actor_b, {"library_id": "lib_b", "name": "B2"})
        await _assert_allowed("api/asset-library/items/item_b/register-avatar", "POST", actor_b, {"library_id": "lib_b", "provider_id": "volcengine"})
        await _assert_allowed("api/asset-library/items/item_b/avatar-status", "POST", actor_b, {"library_id": "lib_b", "provider_id": "volcengine"})
        await _assert_allowed(
            "api/asset-library/items/move",
            "POST",
            actor_b,
            {"library_id": "lib_b", "ids": ["item_b"], "target_library_id": "lib_b", "target_category_id": "cat_b_empty"},
        )

        # Resource use follows file owner or item owner. Others and unowned stay blocked.
        await _assert_allowed("api/online-image", "POST", actor_a, {"reference_images": [{"url": "/assets/library/a/item-a.png"}]})
        await _assert_denied("api/online-image", "POST", actor_b, {"reference_images": [{"url": "/assets/library/a/item-a.png"}]})
        await _assert_denied("api/online-image", "POST", actor_a, {"reference_images": [{"url": "/assets/library/characters/legacy.png"}]})
        assert interceptors.can_access_resource(actor_admin, "/assets/library/characters/legacy.png") is True

        # If an item business owner differs from the resource owner, the item owner can still render/use it.
        edb.record_resource_owner(user_a["id"], "/assets/library/shared/business-owned.png", "test")
        edb.record_asset_object_owner(
            user_b["id"],
            "item",
            "business_b_resource_a",
            parent_library_id="lib_b",
            parent_category_id="cat_b",
            resource_url="/assets/library/shared/business-owned.png",
            source="test",
        )
        assert interceptors.can_access_resource(actor_b, "/assets/library/shared/business-owned.png") is True

        # Non-empty category delete is blocked to avoid upstream physical deletion of /assets/library files.
        await _assert_denied("api/asset-library/categories/cat_b", "DELETE", actor_b, query_params={"library_id": "lib_b"})
        await _assert_allowed("api/asset-library/categories/cat_b_empty", "DELETE", actor_b, query_params={"library_id": "lib_b"})
        await _assert_denied("api/asset-library/libraries/lib_a", "DELETE", actor_b)

        # Admin can manage cross-user objects and writes audit logs.
        await _assert_allowed("api/asset-library/items/item_a/register-avatar", "POST", actor_admin, {"library_id": "lib_a", "provider_id": "volcengine"})
        await _assert_allowed("api/asset-library/items/delete", "POST", actor_admin, {"library_id": "lib_a", "ids": ["item_a"]})
        await _assert_allowed(
            "api/asset-library/items/move",
            "POST",
            actor_admin,
            {"library_id": "lib_b", "ids": ["item_b"], "target_library_id": "lib_a", "target_category_id": "cat_a"},
        )
        logs, _total = edb.get_logs(limit=100)
        actions = [row["action"] for row in logs]
        assert "asset_library_avatar_updated" in actions
        assert "asset_library_deleted" in actions
        assert "asset_library_moved" in actions

        # Shared folders are admin-only in the minimal 3G-4B guard.
        await _assert_denied("api/shared-folders", "GET", actor_a)
        await _assert_denied("api/shared-folders", "POST", actor_a, {"path": "C:/sensitive", "name": "bad"})
        await _assert_denied("api/shared-folders/shared_a/tree", "GET", actor_a)
        await _assert_denied("api/shared-folders/shared_a/file", "GET", actor_a, query_params={"path": "a.png"})
        await _assert_allowed("api/shared-folders", "POST", actor_admin, {"path": "C:/approved", "name": "admin"})

    print("asset library isolation checks passed")


if __name__ == "__main__":
    asyncio.run(_run_checks())
