"""Atomic, non-secret runtime state and local command-file transport."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .logging import redact_value, utc_now


STATE_SCHEMA = "runtime-supervisor-state-v1"
LOCK_FILENAME = "runtime-supervisor.lock"
STATE_FILENAME = "runtime-state.json"
VALID_COMMANDS = frozenset({"stop", "restart"})


class RuntimeStateError(RuntimeError):
    code = "RUNTIME_STATE_ERROR"


def _atomic_json_replace(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"state-{uuid.uuid4().hex[:12]}.tmp")
    encoded = json.dumps(redact_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise RuntimeStateError("runtime state could not be atomically published")
                time.sleep(0.025 * (attempt + 1))
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class RuntimeStateStore:
    def __init__(self, runtime_root: Path) -> None:
        self.root = runtime_root
        self.state_path = self.root / STATE_FILENAME
        self.lock_path = self.root / LOCK_FILENAME
        self.control_root = self.root / "control"

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.control_root.mkdir(exist_ok=True)

    def read_state(self) -> dict[str, Any] | None:
        try:
            raw = self.state_path.read_text(encoding="utf-8")
            state = json.loads(raw)
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if type(state) is not dict or state.get("schema_version") != STATE_SCHEMA:
            return None
        return state

    def write_state(self, state: dict[str, Any]) -> None:
        if type(state) is not dict or state.get("schema_version") != STATE_SCHEMA:
            raise RuntimeStateError("runtime state is invalid")
        state["updated_at"] = utc_now()
        _atomic_json_replace(self.state_path, state)

    def acquire_lock(self, *, instance_id: str, supervisor_pid: int) -> bool:
        self.initialize()
        payload = {
            "schema_version": STATE_SCHEMA,
            "supervisor_instance_id": instance_id,
            "supervisor_pid": supervisor_pid,
            "created_at": utc_now(),
        }
        try:
            with self.lock_path.open("x", encoding="utf-8", newline="") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                handle.flush()
                os.fsync(handle.fileno())
            return True
        except FileExistsError:
            return False

    def acquire_or_adopt_lock(self, *, instance_id: str, supervisor_pid: int) -> bool:
        """Acquire a new startup lock or safely adopt one reserved by `start`."""
        if self.acquire_lock(instance_id=instance_id, supervisor_pid=supervisor_pid):
            return True
        current = self.read_lock()
        if not current or current.get("supervisor_instance_id") != instance_id:
            return False
        payload = {
            "schema_version": STATE_SCHEMA,
            "supervisor_instance_id": instance_id,
            "supervisor_pid": supervisor_pid,
            "created_at": current.get("created_at") or utc_now(),
        }
        _atomic_json_replace(self.lock_path, payload)
        return True

    def read_lock(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if type(value) is dict else None

    def release_lock(self, instance_id: str) -> None:
        lock = self.read_lock()
        if lock and lock.get("supervisor_instance_id") != instance_id:
            return
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def clear_stale_lock(self) -> bool:
        """Delete only a malformed/stale lock after caller proved it is safe."""
        try:
            self.lock_path.unlink()
            return True
        except FileNotFoundError:
            return False

    def submit_command(self, *, command: str, supervisor_instance_id: str) -> str:
        if command not in VALID_COMMANDS or not isinstance(supervisor_instance_id, str) or not supervisor_instance_id:
            raise RuntimeStateError("runtime command is invalid")
        self.initialize()
        request_id = uuid.uuid4().hex
        payload = {
            "schema_version": STATE_SCHEMA,
            "request_id": request_id,
            "command": command,
            "supervisor_instance_id": supervisor_instance_id,
            "created_at": utc_now(),
        }
        path = self.control_root / f"cmd-{request_id[:16]}.json"
        _atomic_json_replace(path, payload)
        return request_id

    def consume_commands(self, instance_id: str) -> list[dict[str, Any]]:
        self.initialize()
        commands: list[dict[str, Any]] = []
        for path in sorted(self.control_root.glob("cmd-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            try:
                path.unlink()
            except OSError:
                continue
            if (
                type(payload) is dict
                and payload.get("schema_version") == STATE_SCHEMA
                and payload.get("supervisor_instance_id") == instance_id
                and payload.get("command") in VALID_COMMANDS
            ):
                commands.append(payload)
        return commands


def initial_state(*, instance_id: str, supervisor_pid: int, mode: str) -> dict[str, Any]:
    if mode not in {"foreground", "service-host"}:
        raise RuntimeStateError("runtime mode is invalid")
    now = utc_now()
    role = {
        "pid": None,
        "parent_pid": supervisor_pid,
        "process_created_at": None,
        "executable": None,
        "state": "stopped",
        "health": "unknown",
        "restart_count": 0,
        "last_exit_code_decimal": None,
        "last_exit_code_hex": None,
        "last_exit_at": None,
    }
    return {
        "schema_version": STATE_SCHEMA,
        "supervisor_instance_id": instance_id,
        "supervisor_pid": supervisor_pid,
        "mode": mode,
        "state": "starting",
        "started_at": now,
        "updated_at": now,
        "upstream": dict(role),
        "gateway": dict(role),
    }
