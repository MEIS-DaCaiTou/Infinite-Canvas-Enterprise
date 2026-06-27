"""
Non-destructive generation history isolation checks.

This script uses a temporary SQLite database, a temporary history.json, and
temporary output files. It does not read or write real runtime history,
databases, assets, or generated outputs.

Run from the repository root:

    python .\enterprise\tests\test_history_isolation.py
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
    os.environ.setdefault("JWT_SECRET", "test-secret-for-history-isolation-1234567890")
    os.environ.setdefault("ADMIN_USERNAME", "admin")
    os.environ.setdefault("ADMIN_PASSWORD", "change-me-in-tests")


def _write_history(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=4), encoding="utf-8")


def _read_history(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_body(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


class FakeRequest:
    def __init__(self, user: dict, body: dict):
        self.state = SimpleNamespace(user=user)
        self._body = body

    async def json(self):
        return self._body


async def _post_json(path: str, method: str, status: int, payload, actor: dict):
    body, _headers = await interceptors.post_process(
        path,
        method,
        status,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "application/json",
        actor,
    )
    return json.loads(body.decode("utf-8"))


async def _run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-history-") as raw_tmp:
        tmp = Path(raw_tmp)
        _prepare_env(tmp)

        from enterprise import db as edb
        from enterprise import interceptors
        from enterprise import admin_api

        globals()["interceptors"] = interceptors

        history_path = tmp / "history.json"
        output_dir = tmp / "assets" / "output"
        output_dir.mkdir(parents=True)
        interceptors.ROOT_DIR = str(tmp)
        interceptors._HISTORY_FILE = history_path

        edb.init_db()
        user_a = edb.create_user("hist_a", "password-a", "History A", False)
        user_b = edb.create_user("hist_b", "password-b", "History B", False)
        admin = edb.get_user_by_username("admin")

        actor_a = {"user_id": user_a["id"], "username": "hist_a", "is_admin": False}
        actor_b = {"user_id": user_b["id"], "username": "hist_b", "is_admin": False}
        actor_admin = {"user_id": admin["id"], "username": "admin", "is_admin": True}

        record_a = {
            "timestamp": 100.0,
            "type": "online",
            "prompt": "A private prompt",
            "images": ["/assets/output/history-a.png"],
            "provider_id": "mock",
            "model": "mock-image",
            "task_id": "task-a",
            "params": {"size": "1024x1024"},
        }
        record_b = {
            "timestamp": 200.0,
            "type": "zimage",
            "prompt": "B private prompt",
            "images": ["/assets/output/history-b.png"],
            "workflow_json": "Z-Image.json",
            "task_id": "task-b",
        }
        record_unowned = {
            "timestamp": 300.0,
            "type": "enhance",
            "prompt": "Legacy unowned",
            "images": ["/assets/output/history-unowned.png"],
        }
        _write_history(history_path, [record_a, record_b, record_unowned])
        (output_dir / "history-a.png").write_bytes(b"a")
        (output_dir / "history-b.png").write_bytes(b"b")
        (output_dir / "history-unowned.png").write_bytes(b"u")

        history_id_a = interceptors.history_id_for_record(record_a)
        history_id_b = interceptors.history_id_for_record(record_b)
        history_id_unowned = interceptors.history_id_for_record(record_unowned)
        edb.record_history_owner(user_a["id"], history_id_a, "online", "/assets/output/history-a.png", "task-a", "seed")
        edb.record_history_owner(user_b["id"], history_id_b, "zimage", "/assets/output/history-b.png", "task-b", "seed")

        visible_a = await _post_json("api/history", "GET", 200, [record_a, record_b, record_unowned], actor_a)
        assert [item["prompt"] for item in visible_a] == ["A private prompt"]
        assert visible_a[0]["enterprise_history_id"] == history_id_a
        assert visible_a[0]["enterprise_owner_id"] == user_a["id"]

        visible_b = await _post_json("api/history", "GET", 200, [record_a, record_b, record_unowned], actor_b)
        assert [item["prompt"] for item in visible_b] == ["B private prompt"]

        visible_admin = await _post_json("api/history", "GET", 200, [record_a, record_b, record_unowned], actor_admin)
        assert [item["prompt"] for item in visible_admin] == [
            "A private prompt",
            "B private prompt",
            "Legacy unowned",
        ]
        admin_unowned = next(item for item in visible_admin if item["prompt"] == "Legacy unowned")
        assert admin_unowned["enterprise_unowned"] is True

        generated_online = {
            "timestamp": 400.0,
            "type": "online",
            "prompt": "A generated online",
            "images": ["/assets/output/generated-online.png"],
            "provider_id": "mock",
            "model": "mock-image",
            "task_id": "task-generated-a",
        }
        await _post_json("api/online-image", "POST", 200, generated_online, actor_a)
        generated_id = interceptors.history_id_for_record(generated_online)
        assert edb.get_history_owner(generated_id) == user_a["id"]
        assert edb.get_resource_owner("/assets/output/generated-online.png") == user_a["id"]

        angle_record = {
            "timestamp": 500.0,
            "type": "angle",
            "prompt": "B angle",
            "images": ["/assets/output/generated-angle.png"],
            "task_id": "task-angle-b",
        }
        _write_history(history_path, [angle_record] + _read_history(history_path))
        await _post_json(
            "api/angle/generate",
            "POST",
            200,
            {"url": "/assets/output/generated-angle.png", "task_id": "task-angle-b"},
            actor_b,
        )
        angle_id = interceptors.history_id_for_record(angle_record)
        assert edb.get_history_owner(angle_id) == user_b["id"]
        assert edb.get_resource_owner("/assets/output/generated-angle.png") == user_b["id"]

        denied = await interceptors.pre_process(
            "api/history/delete",
            "POST",
            actor_b,
            body=json.dumps({"timestamp": 100.0}).encode("utf-8"),
        )
        assert denied is not None and denied.status_code == 404
        assert any(item["prompt"] == "A private prompt" for item in _read_history(history_path))
        assert (output_dir / "history-a.png").exists()

        deleted = await interceptors.pre_process(
            "api/history/delete",
            "POST",
            actor_a,
            body=json.dumps({"timestamp": 100.0}).encode("utf-8"),
        )
        assert deleted is not None and deleted.status_code == 200
        assert _json_body(deleted)["success"] is True
        assert not any(item["prompt"] == "A private prompt" for item in _read_history(history_path))
        assert not (output_dir / "history-a.png").exists()
        assert edb.get_history_owner(history_id_a) is None

        denied_unowned = await interceptors.pre_process(
            "api/history/delete",
            "POST",
            actor_a,
            body=json.dumps({"timestamp": 300.0}).encode("utf-8"),
        )
        assert denied_unowned is not None and denied_unowned.status_code == 404
        assert any(item["prompt"] == "Legacy unowned" for item in _read_history(history_path))

        duplicate_a = {
            "timestamp": 900.0,
            "type": "online",
            "prompt": "A duplicate timestamp",
            "images": ["/assets/output/dup-a.png"],
        }
        duplicate_b = {
            "timestamp": 900.0,
            "type": "online",
            "prompt": "B duplicate timestamp",
            "images": ["/assets/output/dup-b.png"],
        }
        _write_history(history_path, [duplicate_a, duplicate_b] + _read_history(history_path))
        dup_a_id = interceptors.history_id_for_record(duplicate_a)
        dup_b_id = interceptors.history_id_for_record(duplicate_b)
        edb.record_history_owner(user_a["id"], dup_a_id, "online", "/assets/output/dup-a.png", "", "seed")
        edb.record_history_owner(user_b["id"], dup_b_id, "online", "/assets/output/dup-b.png", "", "seed")
        denied_duplicate = await interceptors.pre_process(
            "api/history/delete",
            "POST",
            actor_a,
            body=json.dumps({"timestamp": 900.0}).encode("utf-8"),
        )
        assert denied_duplicate is not None and denied_duplicate.status_code == 404
        assert any(item["prompt"] == "A duplicate timestamp" for item in _read_history(history_path))
        assert any(item["prompt"] == "B duplicate timestamp" for item in _read_history(history_path))

        admin_deleted = await interceptors.pre_process(
            "api/history/delete",
            "POST",
            actor_admin,
            body=json.dumps({"timestamp": 300.0}).encode("utf-8"),
        )
        assert admin_deleted is not None and admin_deleted.status_code == 200
        assert _json_body(admin_deleted)["success"] is True
        assert not any(item["prompt"] == "Legacy unowned" for item in _read_history(history_path))

        migrated = {
            "timestamp": 1000.0,
            "type": "klein",
            "prompt": "Migrated history",
            "images": ["/assets/output/migrated.png"],
            "task_id": "task-migrated",
        }
        _write_history(history_path, [migrated] + _read_history(history_path))
        migrated_id = interceptors.history_id_for_record(migrated)
        result = await admin_api.assign_history_owner(
            migrated_id,
            FakeRequest(actor_admin, {"user_id": user_b["id"]}),
        )
        assert result["success"] is True
        assert edb.get_history_owner(migrated_id) == user_b["id"]
        assert edb.get_resource_owner("/assets/output/migrated.png") == user_b["id"]

        visible_b_after_migration = await _post_json("api/history", "GET", 200, [migrated], actor_b)
        assert [item["prompt"] for item in visible_b_after_migration] == ["Migrated history"]

        logs, _total = edb.get_logs(limit=50)
        actions = [row["action"] for row in logs]
        assert "history_deleted" in actions
        assert "history_assigned" in actions

    print("history isolation checks passed")


if __name__ == "__main__":
    asyncio.run(_run_checks())
