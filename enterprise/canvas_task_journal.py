"""Durable canvas task receipts and results for the single Upstream writer.

Each acknowledged task is atomically persisted before scheduling. We never
re-submit work on recovery: a provider may have accepted it before the local
process died. Incomplete records remain queryable with recovery_required=True.
Only task state/results are stored, not request payloads or provider settings.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from enterprise.paths import _assert_no_reparse


class CanvasTaskJournal:
    def __init__(self, root: Path):
        self.root = Path(root)
        if not self.root.is_absolute():
            raise ValueError("Canvas task root must be absolute")
        self._lock = threading.RLock()

    def _path(self, task_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", task_id):
            raise ValueError("Invalid canvas task identifier")
        _assert_no_reparse(self.root, "CANVAS_TASK_ROOT")
        path = self.root / (task_id + ".json")
        _assert_no_reparse(path, "CANVAS_TASK_RECORD")
        return path

    def _write(self, record: dict) -> None:
        path = self._path(record["id"])
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(record["id"])
        temporary = self.root / f".{record['id']}.{uuid.uuid4().hex}.tmp"
        try:
            # Exclusive temp creation + atomic replacement means readers and
            # file-level backups see a complete old or new JSON record.
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            self._path(record["id"])
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, task_id: str) -> dict | None:
        with self._lock:
            path = self._path(task_id)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None
            if not isinstance(data, dict) or data.get("id") != task_id or data.get("journal_version") != 1:
                raise ValueError("Invalid canvas task record")
            return data

    def create(self, record: dict) -> None:
        with self._lock:
            if self.get(record["id"]) is not None:
                raise ValueError("Canvas task already exists")
            self._write({**record, "journal_version": 1})

    def mark_running(self, task_id: str) -> bool:
        with self._lock:
            record = self.get(task_id)
            if record is None or record.get("status") != "queued":
                return False
            self._write({**record, "status": "running", "updated_at": time.time()})
            return True

    def finish(self, task_id: str, changes: dict) -> None:
        with self._lock:
            record = self.get(task_id)
            if record is None or record.get("status") != "running":
                raise ValueError("Canvas task is not running")
            self._write({**record, **changes, "id": task_id, "updated_at": time.time()})

    def recover(self) -> dict:
        """Startup-only, before accepting traffic; no provider/network calls."""
        counts = {"interrupted": 0, "corrupt": 0}
        with self._lock:
            _assert_no_reparse(self.root, "CANVAS_TASK_ROOT")
            for path in self.root.glob("*.json"):
                try:
                    record = self.get(path.stem)
                except (ValueError, UnicodeError):
                    # Preserve damaged evidence; GET fails, never invent success.
                    counts["corrupt"] += 1
                    continue
                if record is not None and record.get("status") in {"queued", "running"}:
                    previous = record["status"]
                    self._write({
                        **record, "status": "failed", "recovery_required": True,
                        "interrupted_status": previous,
                        "error_code": "runtime_interrupted",
                        "error": "服务重启中断了本地任务跟踪；请核对供应商结果后再决定是否重新提交。",
                        "updated_at": time.time(),
                    })
                    counts["interrupted"] += 1
        return counts


def create_task_receipt(journal: CanvasTaskJournal, record: dict, enterprise_user_id=None) -> None:
    """Commit owner mapping before dispatch, even if the gateway loses the reply.

The Upstream listener remains loopback-only. This identity is overwritten by
the authenticated gateway, not accepted from the public client unmodified.
No provider work may start if either the receipt or owner commit fails.
"""
    user_id = enterprise_user_id if isinstance(enterprise_user_id, str) else ""
    if user_id:
        from enterprise import db
        if db.get_user_by_id(user_id) is None:
            raise ValueError("Canvas task owner unavailable")
        journal.create({**record, "enterprise_user_id": user_id})
        db.record_canvas_image_task_owner(user_id, record["id"])
        db.record_task_owner(
            user_id, "canvas_image" if record["type"] == "online-image" else "canvas_comfy",
            record["id"], source="durable_canvas_task_receipt", status="queued",
        )
        if db.get_canvas_image_task_owner(record["id"]) != user_id:
            raise ValueError("Canvas task ownership conflict")
    else:
        journal.create(record)
