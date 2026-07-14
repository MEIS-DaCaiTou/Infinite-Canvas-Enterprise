"""Fixed local lifecycle control; no socket listener or arbitrary command path."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .health import gateway_health, tcp_check, upstream_health
from .logging import RuntimeLogs
from .ownership import ProcessIdentity, pid_exists, port_identities, same_process
from .process import bundled_python
from .state import RuntimeStateStore
from .supervisor import RuntimeStartBlocked, SupervisorConfig


class RuntimeControlError(RuntimeError):
    code = "RUNTIME_CONTROL_ERROR"


def default_runtime_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "InfiniteCanvasEnterprise" / "runtime"


def _inside(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_runtime_root(app_root: Path, runtime_root: Path) -> Path:
    app = app_root.resolve()
    root = runtime_root.resolve()
    forbidden = (app, app / "data", app / "assets", app / "output", app / "python", app / "logs")
    if any(_inside(root, item) for item in forbidden):
        raise RuntimeControlError("runtime root must be outside application and runtime-data directories")
    return root


def _identity_from_state(value: object) -> ProcessIdentity | None:
    if type(value) is not dict:
        return None
    pid = value.get("pid")
    created = value.get("process_created_at")
    executable = value.get("executable")
    if type(pid) is not int or type(created) is not int or not isinstance(executable, str) or not executable:
        return None
    return ProcessIdentity(pid=pid, created_at=created, executable=executable)


def _role_owned_by_state(state: dict[str, Any] | None, role: str, identities: list[ProcessIdentity]) -> bool:
    if not state:
        return False
    expected = _identity_from_state(state.get(role))
    return expected is not None and any(same_process(expected, identity) for identity in identities)


def inspect_runtime(config: SupervisorConfig) -> dict[str, Any]:
    """Read-only current-state/port/health snapshot used by status and health."""
    store = RuntimeStateStore(config.runtime_root)
    state = store.read_state()
    upstream_listeners = port_identities(config.upstream_port)
    gateway_listeners = port_identities(config.gateway_port)
    if not upstream_listeners and not gateway_listeners:
        if state:
            if state.get("state") == "stopped":
                disposition = "stale_runtime_state"
            else:
                role_pids = [_identity_from_state(state.get(role)) for role in ("upstream", "gateway")]
                if any(identity and pid_exists(identity.pid) for identity in role_pids) or pid_exists(state.get("supervisor_pid")):
                    disposition = "owned_orphan_process"
                else:
                    disposition = "stale_runtime_state"
        else:
            disposition = "stopped"
    elif bool(upstream_listeners) != bool(gateway_listeners):
        disposition = "upstream_only" if upstream_listeners else "gateway_only"
    elif _role_owned_by_state(state, "upstream", upstream_listeners) and _role_owned_by_state(state, "gateway", gateway_listeners) and state and pid_exists(state.get("supervisor_pid")):
        upstream_result = upstream_health("127.0.0.1", config.upstream_port)
        gateway_result = gateway_health("127.0.0.1", config.gateway_port)
        disposition = "complete_healthy_instance" if upstream_result.ok and gateway_result.ok else "complete_unhealthy_instance"
    else:
        disposition = "foreign_port_occupant"
    upstream_tcp = tcp_check("127.0.0.1", config.upstream_port).snapshot()
    gateway_tcp = tcp_check("127.0.0.1", config.gateway_port).snapshot()
    upstream_result = upstream_health("127.0.0.1", config.upstream_port).snapshot()
    gateway_result = gateway_health("127.0.0.1", config.gateway_port).snapshot()
    return {
        "schema_version": "runtime-supervisor-status-v1",
        "state": state.get("state") if state else "stopped",
        "start_disposition": disposition,
        "runtime_state": state,
        "upstream_tcp": upstream_tcp,
        "gateway_tcp": gateway_tcp,
        "upstream_health": upstream_result,
        "gateway_health": gateway_result,
    }


class RuntimeController:
    def __init__(self, config: SupervisorConfig) -> None:
        self.config = config
        self.store = RuntimeStateStore(config.runtime_root)

    def _clear_stale_if_safe(self, snapshot: dict[str, Any]) -> None:
        if snapshot["start_disposition"] != "stale_runtime_state":
            return
        self.store.clear_stale_lock()

    def start(self, *, wait_seconds: int = 60) -> dict[str, Any]:
        snapshot = inspect_runtime(self.config)
        disposition = snapshot["start_disposition"]
        if disposition == "complete_healthy_instance":
            return {"result": "already_running", "status": snapshot}
        if disposition == "stale_runtime_state":
            self._clear_stale_if_safe(snapshot)
        elif disposition != "stopped":
            raise RuntimeStartBlocked(f"runtime start blocked: {disposition}")
        instance_id = uuid.uuid4().hex
        self.store.initialize()
        if not self.store.acquire_lock(instance_id=instance_id, supervisor_pid=os.getpid()):
            raise RuntimeStartBlocked("runtime startup is already in progress")
        RuntimeLogs(self.config.runtime_root).write(
            "launcher.log", "background_start_requested", supervisor_instance_id=instance_id, mode="service-host"
        )
        arguments = [
            bundled_python(self.config.app_root),
            "-m",
            "enterprise.runtime.cli",
            "service-host",
            "--app-root",
            str(self.config.app_root),
            "--runtime-root",
            str(self.config.runtime_root),
            "--instance-id",
            instance_id,
        ]
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        try:
            subprocess.Popen(
                arguments,
                cwd=str(self.config.app_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=True,
                shell=False,
            )
        except OSError as exc:
            self.store.release_lock(instance_id)
            raise RuntimeControlError("runtime service host could not be started") from exc
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            current = inspect_runtime(self.config)
            if current["state"] == "healthy":
                return {"result": "started", "status": current}
            current_state = current.get("runtime_state")
            owned_startup = type(current_state) is dict and current_state.get("supervisor_instance_id") == instance_id
            if (
                (current["start_disposition"] == "complete_unhealthy_instance" or (current["start_disposition"] == "foreign_port_occupant" and not owned_startup))
                or current["state"] in {"stopped", "crash_loop"}
            ):
                raise RuntimeControlError("runtime service host did not become healthy")
            time.sleep(0.25)
        raise RuntimeControlError("runtime service host startup timed out")

    def send_command(self, command: str, *, wait_seconds: int = 60) -> dict[str, Any]:
        snapshot = inspect_runtime(self.config)
        state = snapshot.get("runtime_state")
        if not state or snapshot["state"] == "stopped":
            return {"result": "already_stopped" if command == "stop" else "not_running", "status": snapshot}
        instance_id = state.get("supervisor_instance_id")
        if not isinstance(instance_id, str) or not instance_id or not pid_exists(state.get("supervisor_pid")):
            raise RuntimeControlError("runtime service ownership is unavailable")
        self.store.submit_command(command=command, supervisor_instance_id=instance_id)
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            current = inspect_runtime(self.config)
            if command == "stop" and current["state"] == "stopped":
                if current["start_disposition"] in {"gateway_only", "upstream_only", "foreign_port_occupant", "complete_unhealthy_instance"}:
                    return {"result": "foreign_port_occupant", "status": current}
                return {"result": "stopped", "status": current}
            if command == "restart" and current["state"] == "healthy":
                return {"result": "restarted", "status": current}
            time.sleep(0.25)
        raise RuntimeControlError("runtime control command timed out")
