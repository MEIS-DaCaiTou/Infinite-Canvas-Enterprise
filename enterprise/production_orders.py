"""Production order facts for a single Windows installation."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import time
from uuid import uuid4

from enterprise.local_json import atomic_write_json, document_lock, read_json
from enterprise.paths import _assert_no_reparse


SLOTS = ("main", "detail")


class ProductionConflict(ValueError):
    pass


class ProductionOrders:
    def __init__(self, data_root):
        self.root = Path(data_root) / "production_orders"

    def _owner_root(self, user_id):
        return self.root / sha256(user_id.encode("utf-8")).hexdigest()

    def _load(self, path, user_id):
        _assert_no_reparse(path, "PRODUCTION_ORDER")
        record = read_json(path)
        if (record.get("schema_version") != 1 or record.get("id") != path.stem
                or record.get("owner") != user_id):
            raise ValueError("Invalid production order")
        return record

    def list(self, user_id):
        directory = self._owner_root(user_id)
        _assert_no_reparse(directory, "PRODUCTION_ORDER_ROOT")
        rows = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        results = []
        for path in rows[:50]:
            record = self._load(path, user_id)
            results.append({key: record[key] for key in ("id", "style", "title", "updated_at", "canvas_id")})
        return results

    def get(self, user_id, order_id):
        return self._load(self._owner_root(user_id) / (order_id + ".json"), user_id)

    def create(self, user_id, order_id, spec):
        path = self._owner_root(user_id) / (order_id + ".json")
        _assert_no_reparse(path, "PRODUCTION_ORDER")
        with document_lock(path):
            try:
                current = self._load(path, user_id)
            except FileNotFoundError:
                current = None
            if current is not None:
                if current["spec"] != spec:
                    raise ProductionConflict("此新建编号已使用，请重新打开表单")
                return current
            record = {
                "schema_version": 1, "id": order_id, "owner": user_id,
                "style": spec["style"], "title": spec["title"], "canvas_id": spec["canvas_id"], "spec": spec,
                "revision": 1, "created_at": time(), "updated_at": time(),
                "colors": [
                    {**color, "slots": {name: {"attempts": [], "approved": None} for name in SLOTS}}
                    for color in spec["colors"]
                ],
            }
            atomic_write_json(path, record)
            return record

    def _mutate(self, user_id, order_id, change):
        path = self._owner_root(user_id) / (order_id + ".json")
        _assert_no_reparse(path, "PRODUCTION_ORDER")
        if not path.is_file():
            raise FileNotFoundError(path)
        with document_lock(path):
            record = self._load(path, user_id)
            value, changed = change(record)
            if changed:
                record["revision"] += 1
                record["updated_at"] = time()
                atomic_write_json(path, record)
            return deepcopy(value), changed

    def reserve(self, user_id, order_id, color, name, operation_id, params, parent_id, versions):
        def change(record):
            slot = record["colors"][color]["slots"][name]
            attempts = slot["attempts"]
            for attempt in attempts:
                if attempt["operation_id"] == operation_id:
                    if attempt["params"] != params or attempt["parent_id"] != parent_id:
                        raise ProductionConflict("此操作编号已用于不同的制作请求")
                    return attempt, False
            representative = record["colors"][0]["slots"]
            if color and any(not item["approved"] for item in representative.values()):
                raise ProductionConflict("请先批准首色的主图和详情模块")
            expected = attempts[-1]["task_id"] if attempts else None
            if parent_id != expected:
                raise ProductionConflict("图位已更新，请刷新原任务后继续")
            request_id = uuid4().hex
            attempt = {
                "operation_id": operation_id, "task_id": "canvas_img_" + request_id,
                "created_at": time(), "parent_id": parent_id, "params": params,
                "dispatch": "reserved", "inputs": versions,
            }
            attempts.append(attempt)
            return attempt, True
        return self._mutate(user_id, order_id, change)

    def set_dispatch(self, user_id, order_id, color, name, task_id, state):
        def change(record):
            slot = record["colors"][color]["slots"][name]
            attempt = next(entry for entry in slot["attempts"] if entry["task_id"] == task_id)
            attempt["dispatch"] = state
            return attempt, True
        return self._mutate(user_id, order_id, change)[0]

    def approve(self, user_id, order_id, color, name, task_id, asset):
        def change(record):
            slot = record["colors"][color]["slots"][name]
            approved = slot["approved"]
            if approved and approved["task_id"] == task_id and approved["asset"] == asset:
                return record, False
            if not slot["attempts"] or slot["attempts"][-1]["task_id"] != task_id:
                raise ProductionConflict("请选择此图位最新任务的候选图")
            slot["approved"] = {"task_id": task_id, "asset": asset, "by": user_id, "at": time()}
            return record, True
        return self._mutate(user_id, order_id, change)[0]
