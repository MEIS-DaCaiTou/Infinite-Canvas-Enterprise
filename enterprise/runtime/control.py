"""Fixed local lifecycle control with full supervisor identity checks."""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from .health import gateway_health, tcp_check, upstream_health
from .logging import RuntimeLogs
from .ownership import ProcessIdentity, port_identities, process_identity, same_process
from .process import bundled_python
from .state import STARTUP_LOCK_GRACE_SECONDS, RuntimeStateStore
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


def _identity_from_mapping(value: object, *, pid_key: str, created_key: str, executable_key: str) -> ProcessIdentity | None:
    if type(value) is not dict:
        return None
    pid = value.get(pid_key)
    created = value.get(created_key)
    executable = value.get(executable_key)
    if type(pid) is not int or type(created) is not int or not isinstance(executable, str) or not executable:
        return None
    return ProcessIdentity(pid=pid, created_at=created, executable=executable)


def _identity_from_role(value: object) -> ProcessIdentity | None:
    return _identity_from_mapping(value, pid_key="pid", created_key="process_created_at", executable_key="executable")


def _supervisor_identity_from_state(state: object) -> ProcessIdentity | None:
    return _identity_from_mapping(
        state,
        pid_key="supervisor_pid",
        created_key="supervisor_process_created_at",
        executable_key="supervisor_executable",
    )


def _current(identity: ProcessIdentity | None) -> bool:
    return identity is not None and same_process(identity, process_identity(identity.pid))


def _role_owned_by_state(state: dict[str, Any] | None, role: str, identities: list[ProcessIdentity]) -> bool:
    expected = _identity_from_role(state.get(role)) if state else None
    return expected is not None and any(same_process(expected, identity) for identity in identities)


def _state_has_owned_child(state: dict[str, Any] | None) -> bool:
    return bool(state) and any(_current(_identity_from_role(state.get(role))) for role in ("upstream", "gateway"))


def inspect_runtime(config: SupervisorConfig) -> dict[str, Any]:
    """Read-only state, lock, listener ownership, and bounded HTTP health snapshot."""
    store = RuntimeStateStore(config.runtime_root)
    state = store.read_state()
    lock = store.read_lock()
    lock_age = store.lock_age_seconds(lock)
    supervisor = _supervisor_identity_from_state(state)
    supervisor_current = _current(supervisor)
    owned_child_current = _state_has_owned_child(state)
    upstream_listeners = port_identities(config.upstream_port)
    gateway_listeners = port_identities(config.gateway_port)
    if not upstream_listeners and not gateway_listeners:
        if state and (supervisor_current or owned_child_current):
            disposition = "startup_in_progress" if state.get("state") in {"starting", "stopped"} else "owned_orphan_process"
        elif lock and lock.get("lock_phase") in {"reserved", "adopted"}:
            disposition = "startup_in_progress"
        elif state:
            disposition = "stale_runtime_state"
        else:
            disposition = "stopped"
    elif bool(upstream_listeners) != bool(gateway_listeners):
        disposition = "upstream_only" if upstream_listeners else "gateway_only"
    elif (
        state
        and supervisor_current
        and _role_owned_by_state(state, "upstream", upstream_listeners)
        and _role_owned_by_state(state, "gateway", gateway_listeners)
    ):
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
        "lock": lock,
        "lock_age_seconds": lock_age,
        "supervisor_identity_current": supervisor_current,
        "owned_child_current": owned_child_current,
        "upstream_tcp": upstream_tcp,
        "gateway_tcp": gateway_tcp,
        "upstream_health": upstream_result,
        "gateway_health": gateway_result,
    }


class RuntimeController:
    def __init__(self, config: SupervisorConfig) -> None:
        self.config = config
        self.store = RuntimeStateStore(config.runtime_root)

    def _clear_stale_if_safe(self, snapshot: dict[str, Any]) -> bool:
        lock = snapshot.get("lock")
        if not lock:
            return True
        owner = self.store.lock_owner_identity(lock)
        supervisor = self.store.lock_supervisor_identity(lock)
        owner_current = _current(owner)
        supervisor_current = _current(supervisor)
        no_project_ports = not port_identities(self.config.upstream_port) and not port_identities(self.config.gateway_port)
        no_owned_child = not bool(snapshot.get("owned_child_current"))
        age = snapshot.get("lock_age_seconds")
        state = snapshot.get("runtime_state")
        explicitly_failed = type(state) is dict and state.get("state") in {"blocked", "stopped"}
        stale_enough = isinstance(age, (int, float)) and age >= STARTUP_LOCK_GRACE_SECONDS
        if (
            not owner_current
            and not supervisor_current
            and no_owned_child
            and no_project_ports
            and (stale_enough or explicitly_failed)
        ):
            return self.store.clear_stale_lock(expected_instance_id=lock.get("supervisor_instance_id"))
        return False

    @staticmethod
    def _stop_owned_start_host(host: subprocess.Popen[bytes]) -> bool:
        """End only the host this launcher just created after startup failure."""
        identity = process_identity(host.pid)
        if identity is None or not same_process(identity, process_identity(host.pid)):
            return False
        try:
            host.terminate()
            host.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            return False
        return not _current(identity)

    def start(self, *, wait_seconds: int = 60) -> dict[str, Any]:
        snapshot = inspect_runtime(self.config)
        disposition = snapshot["start_disposition"]
        if disposition == "complete_healthy_instance":
            return {"result": "already_running", "status": snapshot}
        if disposition in {"stale_runtime_state", "startup_in_progress"}:
            if not self._clear_stale_if_safe(snapshot):
                raise RuntimeStartBlocked("runtime startup is already in progress")
        elif disposition != "stopped":
            raise RuntimeStartBlocked(f"runtime start blocked: {disposition}")
        owner = process_identity(os.getpid())
        if owner is None:
            raise RuntimeControlError("runtime launcher identity is unavailable")
        instance_id = uuid.uuid4().hex
        self.store.initialize()
        if not self.store.reserve_lock(instance_id=instance_id, owner=owner):
            raise RuntimeStartBlocked("runtime startup is already in progress")
        host: subprocess.Popen[bytes] | None = None
        try:
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
                "--upstream-port",
                str(self.config.upstream_port),
                "--gateway-port",
                str(self.config.gateway_port),
            ]
            if self.config.fixture_child_wrapper:
                arguments.append("--fixture-child-wrapper")
            flags = 0
            if os.name == "nt":
                # The service-host must not remain in a short-lived launcher's
                # inherited Job Object.  Its own Job Object owns only runtime
                # children after the detached host starts.
                flags = (
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_BREAKAWAY_FROM_JOB
                )
            host = subprocess.Popen(
                arguments,
                cwd=str(self.config.app_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=True,
                shell=False,
            )
        except (OSError, RuntimeError) as exc:
            self.store.release_lock(instance_id)
            raise RuntimeControlError("runtime service host could not be started") from exc
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            current = inspect_runtime(self.config)
            state = current.get("runtime_state")
            if (
                current["state"] == "healthy"
                and type(state) is dict
                and state.get("supervisor_instance_id") == instance_id
                and current.get("supervisor_identity_current") is True
            ):
                return {"result": "started", "status": current}
            if host.poll() is not None:
                lock = self.store.read_lock()
                if lock and lock.get("supervisor_instance_id") == instance_id and lock.get("lock_phase") == "reserved":
                    self.store.release_lock(instance_id)
                raise RuntimeControlError("runtime service host did not become healthy")
            time.sleep(0.25)
        lock = self.store.read_lock()
        if host.poll() is None:
            self._stop_owned_start_host(host)
        lock = self.store.read_lock()
        if host.poll() is not None and lock and lock.get("supervisor_instance_id") == instance_id:
            self.store.release_lock(instance_id)
        raise RuntimeControlError("runtime service host startup timed out")

    def send_command(self, command: str, *, wait_seconds: int = 60) -> dict[str, Any]:
        snapshot = inspect_runtime(self.config)
        state = snapshot.get("runtime_state")
        if not state or snapshot["state"] == "stopped":
            return {"result": "already_stopped" if command == "stop" else "not_running", "status": snapshot}
        instance_id = state.get("supervisor_instance_id") if type(state) is dict else None
        generation = state.get("state_generation") if type(state) is dict else None
        if (
            not isinstance(instance_id, str)
            or not instance_id
            or type(generation) is not int
            or generation < 0
            or not snapshot.get("supervisor_identity_current")
        ):
            raise RuntimeControlError("runtime service ownership is unavailable")
        request_id = self.store.submit_command(
            command=command,
            supervisor_instance_id=instance_id,
            expected_state_generation=generation,
        )
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            ack = self.store.read_ack(request_id, instance_id=instance_id)
            if ack is not None:
                result = ack.get("result")
                if command == "restart" and result == "restarted":
                    current = inspect_runtime(self.config)
                    if current["state"] == "healthy" and current.get("supervisor_identity_current"):
                        self.store.remove_ack(request_id, instance_id=instance_id)
                        return {"result": "restarted", "ack": ack, "status": current}
                if command == "stop" and result in {"stopped", "foreign_port_occupant", "stop_incomplete"}:
                    current = inspect_runtime(self.config)
                    if not current.get("supervisor_identity_current"):
                        final_ack = dict(ack)
                        final_ack["supervisor_exit_confirmed"] = True
                        self.store.remove_ack(request_id, instance_id=instance_id)
                        return {"result": result, "ack": final_ack, "status": current}
                if isinstance(result, str) and result.startswith("rejected_"):
                    raise RuntimeControlError("runtime control command was rejected")
            time.sleep(0.2)
        raise RuntimeControlError("runtime control command timed out")
