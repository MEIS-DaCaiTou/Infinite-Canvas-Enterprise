"""Atomic runtime state, instance locks, and local command acknowledgements."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .logging import redact_value, utc_now
from .ownership import ProcessIdentity, process_identity, same_process


STATE_SCHEMA = "runtime-supervisor-state-v1"
LOCK_FILENAME = "runtime-supervisor.lock"
STATE_FILENAME = "runtime-state.json"
VALID_COMMANDS = frozenset({"stop", "restart"})
STARTUP_LOCK_GRACE_SECONDS = 75
CONTROL_TTL_SECONDS = 15 * 60


class RuntimeStateError(RuntimeError):
    code = "RUNTIME_STATE_ERROR"


def _atomic_json_replace(path: Path, payload: dict[str, Any]) -> None:
    """Publish a small JSON document without overwriting through a long path."""
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


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _identity_from_payload(payload: object, *, pid_key: str, created_key: str, executable_key: str) -> ProcessIdentity | None:
    if type(payload) is not dict:
        return None
    pid = payload.get(pid_key)
    created = payload.get(created_key)
    executable = payload.get(executable_key)
    if type(pid) is not int or pid < 1 or type(created) is not int or created < 0:
        return None
    if not isinstance(executable, str) or not executable:
        return None
    return ProcessIdentity(pid=pid, created_at=created, executable=executable)


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
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            return None
        if type(state) is not dict or state.get("schema_version") != STATE_SCHEMA:
            return None
        return state

    def write_state(self, state: dict[str, Any]) -> None:
        if type(state) is not dict or state.get("schema_version") != STATE_SCHEMA:
            raise RuntimeStateError("runtime state is invalid")
        state["updated_at"] = utc_now()
        _atomic_json_replace(self.state_path, state)

    def read_lock(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if type(value) is dict and value.get("schema_version") == STATE_SCHEMA else None

    @staticmethod
    def lock_owner_identity(lock: object) -> ProcessIdentity | None:
        return _identity_from_payload(
            lock,
            pid_key="owner_pid",
            created_key="owner_process_created_at",
            executable_key="owner_executable",
        )

    @staticmethod
    def lock_supervisor_identity(lock: object) -> ProcessIdentity | None:
        return _identity_from_payload(
            lock,
            pid_key="supervisor_pid",
            created_key="supervisor_process_created_at",
            executable_key="supervisor_executable",
        )

    @staticmethod
    def lock_age_seconds(lock: object, *, now: datetime | None = None) -> float | None:
        if type(lock) is not dict:
            return None
        created = _parse_utc(lock.get("created_at"))
        if created is None:
            return None
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - created).total_seconds())

    def reserve_lock(self, *, instance_id: str, owner: ProcessIdentity) -> bool:
        """Only the short-lived launcher may create a ``reserved`` lock."""
        self.initialize()
        now = utc_now()
        payload = {
            "schema_version": STATE_SCHEMA,
            "supervisor_instance_id": instance_id,
            "owner_pid": owner.pid,
            "owner_process_created_at": owner.created_at,
            "owner_executable": owner.executable,
            "supervisor_pid": None,
            "supervisor_process_created_at": None,
            "supervisor_executable": None,
            "lock_phase": "reserved",
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self.lock_path.open("x", encoding="utf-8", newline="") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                handle.flush()
                os.fsync(handle.fileno())
            return True
        except FileExistsError:
            return False

    def adopt_lock(
        self,
        *,
        instance_id: str,
        owner: ProcessIdentity,
        supervisor: ProcessIdentity,
        grace_seconds: int = STARTUP_LOCK_GRACE_SECONDS,
    ) -> bool:
        """Adopt a fresh reservation only after validating the launcher's identity."""
        lock = self.read_lock()
        age = self.lock_age_seconds(lock)
        if (
            not lock
            or lock.get("supervisor_instance_id") != instance_id
            or lock.get("lock_phase") != "reserved"
            or age is None
            or age > grace_seconds
            or not same_process(owner, self.lock_owner_identity(lock))
            or not same_process(owner, process_identity(owner.pid))
        ):
            return False
        payload = dict(lock)
        payload.update(
            {
                "supervisor_pid": supervisor.pid,
                "supervisor_process_created_at": supervisor.created_at,
                "supervisor_executable": supervisor.executable,
                "lock_phase": "adopted",
                "updated_at": utc_now(),
            }
        )
        _atomic_json_replace(self.lock_path, payload)
        return True

    def acquire_foreground_lock(self, *, instance_id: str, supervisor: ProcessIdentity) -> bool:
        """Foreground owns an already-adopted lock; it never creates reserved locks."""
        self.initialize()
        now = utc_now()
        payload = {
            "schema_version": STATE_SCHEMA,
            "supervisor_instance_id": instance_id,
            "owner_pid": supervisor.pid,
            "owner_process_created_at": supervisor.created_at,
            "owner_executable": supervisor.executable,
            "supervisor_pid": supervisor.pid,
            "supervisor_process_created_at": supervisor.created_at,
            "supervisor_executable": supervisor.executable,
            "lock_phase": "adopted",
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self.lock_path.open("x", encoding="utf-8", newline="") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                handle.flush()
                os.fsync(handle.fileno())
            return True
        except FileExistsError:
            return False

    def release_lock(self, instance_id: str) -> None:
        lock = self.read_lock()
        if lock and lock.get("supervisor_instance_id") != instance_id:
            return
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def clear_stale_lock(self, *, expected_instance_id: str | None = None) -> bool:
        """Caller must prove state, identity, ports, and age make removal safe."""
        lock = self.read_lock()
        if lock is None or (expected_instance_id and lock.get("supervisor_instance_id") != expected_instance_id):
            return False
        try:
            self.lock_path.unlink()
            return True
        except FileNotFoundError:
            return False

    def submit_command(
        self,
        *,
        command: str,
        supervisor_instance_id: str,
        expected_state_generation: int,
    ) -> str:
        if (
            command not in VALID_COMMANDS
            or not isinstance(supervisor_instance_id, str)
            or not supervisor_instance_id
            or type(expected_state_generation) is not int
            or expected_state_generation < 0
        ):
            raise RuntimeStateError("runtime command is invalid")
        self.initialize()
        self.purge_control()
        request_id = uuid.uuid4().hex
        payload = {
            "schema_version": STATE_SCHEMA,
            "request_id": request_id,
            "command": command,
            "supervisor_instance_id": supervisor_instance_id,
            "issued_at": utc_now(),
            "expected_state_generation": expected_state_generation,
        }
        path = self.control_root / f"cmd-{request_id[:16]}.json"
        _atomic_json_replace(path, payload)
        return request_id

    def consume_commands(self, instance_id: str) -> list[dict[str, Any]]:
        self.initialize()
        self.purge_control()
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
                and isinstance(payload.get("request_id"), str)
                and type(payload.get("expected_state_generation")) is int
            ):
                commands.append(payload)
        return commands

    def write_ack(self, payload: dict[str, Any]) -> None:
        required = {"request_id", "command", "supervisor_instance_id", "accepted_at", "completed_at", "result"}
        if type(payload) is not dict or not required.issubset(payload) or payload.get("command") not in VALID_COMMANDS:
            raise RuntimeStateError("runtime command acknowledgement is invalid")
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise RuntimeStateError("runtime command acknowledgement is invalid")
        complete = {"schema_version": STATE_SCHEMA, **payload}
        _atomic_json_replace(self.control_root / f"ack-{request_id[:16]}.json", complete)

    def read_ack(self, request_id: str, *, instance_id: str) -> dict[str, Any] | None:
        if not isinstance(request_id, str) or not request_id:
            return None
        path = self.control_root / f"ack-{request_id[:16]}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            return None
        if (
            type(payload) is not dict
            or payload.get("schema_version") != STATE_SCHEMA
            or payload.get("request_id") != request_id
            or payload.get("supervisor_instance_id") != instance_id
        ):
            return None
        return payload

    def remove_ack(self, request_id: str, *, instance_id: str) -> None:
        payload = self.read_ack(request_id, instance_id=instance_id)
        if payload is None:
            return
        try:
            (self.control_root / f"ack-{request_id[:16]}.json").unlink()
        except FileNotFoundError:
            pass

    def purge_control(self, *, max_age_seconds: int = CONTROL_TTL_SECONDS) -> None:
        if not self.control_root.exists():
            return
        cutoff = time.time() - max_age_seconds
        for path in self.control_root.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue


def initial_state(*, instance_id: str, supervisor: ProcessIdentity, mode: str) -> dict[str, Any]:
    if mode not in {"foreground", "service-host"}:
        raise RuntimeStateError("runtime mode is invalid")
    now = utc_now()
    role = {
        "pid": None,
        "parent_pid": supervisor.pid,
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
        "supervisor_pid": supervisor.pid,
        "supervisor_process_created_at": supervisor.created_at,
        "supervisor_executable": supervisor.executable,
        "mode": mode,
        "state": "starting",
        "state_generation": 0,
        "started_at": now,
        "updated_at": now,
        "upstream": dict(role),
        "gateway": dict(role),
    }
