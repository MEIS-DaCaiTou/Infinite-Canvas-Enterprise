"""
History type consistency checks for cloud Z-Image, Klein, and Enhance flows.

This script uses a temporary SQLite database and temporary history file. It
does not read or write real runtime history, databases, assets, or outputs.

Run from the repository root:

    python .\enterprise\tests\test_history_type_consistency.py
"""
import ast
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAIN = ROOT / "main.py"
ZIMAGE = ROOT / "static" / "zimage.html"
KLEIN = ROOT / "static" / "klein.html"
ENHANCE = ROOT / "static" / "enhance.html"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _require(source: str, needle: str, label: str) -> None:
    assert needle in source, f"missing {label}: {needle}"


def _load_normalize_history_type():
    tree = ast.parse(_source(MAIN), filename=str(MAIN))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ALLOWED_HISTORY_TYPES"
            for target in node.targets
        ):
            nodes.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "normalize_history_type":
            nodes.append(node)
    assert len(nodes) == 2, "normalize_history_type helper or allowed type set not found"
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(MAIN), "exec"), namespace)
    return namespace["normalize_history_type"]


def _check_static_contracts() -> None:
    main = _source(MAIN)
    zimage = _source(ZIMAGE)
    klein = _source(KLEIN)
    enhance = _source(ENHANCE)

    _require(main, 'record = {\n                        "timestamp": time.time(),', "expanded /generate history record")
    _require(main, '"type": normalize_history_type(req.type, "zimage")', "/generate zimage history type")
    _require(main, 'type: str = "klein"', "MsGenerateRequest type field")
    _require(main, '"type": normalize_history_type(req.type, "klein")', "/api/ms/generate history type")

    _require(zimage, 'type: "zimage"', "zimage cloud request type")
    _require(zimage, "type: 'zimage'", "zimage immediate cloud card type")
    _require(zimage, "/api/history?type=zimage", "zimage refresh history type")

    _require(klein, "type: 'klein'", "klein ModelScope request type")
    _require(klein, "/api/history?type=klein", "klein refresh history type")

    _require(enhance, "type: 'enhance'", "enhance ModelScope request/history type")
    _require(enhance, "/api/history?type=enhance", "enhance refresh history type")


async def _post_json(interceptors, path: str, payload: list[dict], actor: dict) -> list[dict]:
    body, _headers = await interceptors.post_process(
        path,
        "GET",
        200,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "application/json",
        actor,
    )
    return json.loads(body.decode("utf-8"))


async def _check_enterprise_owner_maps() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-history-types-") as raw_tmp:
        tmp = Path(raw_tmp)
        os.environ["DB_PATH"] = str(tmp / "enterprise.db")
        os.environ.setdefault("JWT_SECRET", "test-secret-for-history-type-consistency-1234567890")
        os.environ.setdefault("ADMIN_USERNAME", "admin")
        os.environ.setdefault("ADMIN_PASSWORD", "change-me-in-tests")

        from enterprise import db as edb
        from enterprise import interceptors

        history_path = tmp / "history.json"
        output_dir = tmp / "assets" / "output"
        output_dir.mkdir(parents=True)
        interceptors.ROOT_DIR = str(tmp)
        interceptors._HISTORY_FILE = history_path

        edb.init_db()
        user_a = edb.create_user("type_a", "password-a", "History Type A", False)
        user_b = edb.create_user("type_b", "password-b", "History Type B", False)
        admin = edb.get_user_by_username("admin")

        actor_a = {"user_id": user_a["id"], "username": "type_a", "is_admin": False}
        actor_b = {"user_id": user_b["id"], "username": "type_b", "is_admin": False}
        actor_admin = {"user_id": admin["id"], "username": "admin", "is_admin": True}

        records = [
            {
                "timestamp": 100.0,
                "type": "zimage",
                "prompt": "zimage cloud",
                "images": ["/assets/output/zimage-cloud.png"],
            },
            {
                "timestamp": 200.0,
                "type": "enhance",
                "prompt": "enhance cloud",
                "images": ["/assets/output/enhance-cloud.png"],
            },
            {
                "timestamp": 300.0,
                "type": "klein",
                "prompt": "klein cloud",
                "images": ["/assets/output/klein-cloud.png"],
            },
        ]
        history_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        for record in records:
            Path(tmp / record["images"][0].lstrip("/")).write_bytes(b"image")
            interceptors.record_history_payload_for_user_id(user_a["id"], "history-type-test", record)

        owner_map = edb.get_all_history_owner_map()
        assert len(owner_map) == 3
        for record in records:
            history_id = interceptors.history_id_for_record(record)
            assert owner_map[history_id] == user_a["id"]
            assert edb.get_resource_owner(record["images"][0]) == user_a["id"]

        visible_a = await _post_json(interceptors, "api/history", records, actor_a)
        visible_b = await _post_json(interceptors, "api/history", records, actor_b)
        visible_admin = await _post_json(interceptors, "api/history", records, actor_admin)

        assert [item["type"] for item in visible_a] == ["zimage", "enhance", "klein"]
        assert visible_b == []
        assert [item["type"] for item in visible_admin] == ["zimage", "enhance", "klein"]


def _run_checks() -> None:
    normalize_history_type = _load_normalize_history_type()
    assert normalize_history_type("zimage") == "zimage"
    assert normalize_history_type("enhance") == "enhance"
    assert normalize_history_type("klein") == "klein"
    assert normalize_history_type("cloud", "zimage") == "zimage"
    assert normalize_history_type("../../secret", "klein") == "klein"
    assert normalize_history_type("<script>", "enhance") == "enhance"
    assert normalize_history_type("unknown", "not-allowed") == "zimage"

    _check_static_contracts()
    asyncio.run(_check_enterprise_owner_maps())


if __name__ == "__main__":
    _run_checks()
    print("history type consistency checks passed")
