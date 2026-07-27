"""Fixed local lifecycle control with full supervisor identity checks."""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from .health import gateway_health, tcp_check, upstream_health
from .logging import RuntimeLogs
from .ownership import ProcessIdentity, PortListenerSnapshot, inspect_port_listeners, process_identity, same_process
from .process import bundled_python
from .launch_context import (
    LAUNCH_CONTEXT_FILENAME,
    RuntimeLaunchContext,
    build_launch_context,
    publish_launch_context,
    read_launch_context,
)
from .preflight import StartupPreflightResult
from .readiness import classify_portable_readiness
from .state import STARTUP_LOCK_GRACE_SECONDS, RuntimeStateStore
from .supervisor import RuntimeStartBlocked, SupervisorConfig


class RuntimeControlError(RuntimeError):
    code = "RUNTIME_CONTROL_ERROR"

    def __init__(self, message: str, *, public_details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.public_details = dict(public_details or {})


class RuntimeServiceHostStartupError(RuntimeControlError):
    """A detached host exited before the controller observed healthy state."""

    code = "RUNTIME_SERVICE_HOST_EARLY_EXIT"

    def __init__(self, *, exit_code: int, failure_category: str) -> None:
        super().__init__(
            "runtime service host did not become healthy",
            public_details={
                "host_exit_code": exit_code,
                "bootstrap_failure_category": failure_category,
            },
        )


_BOOTSTRAP_FAILURE_NAME = "service-host-bootstrap.failure"
_BOOTSTRAP_FAILURE_CATEGORIES = frozenset(
    {
        "host_entry_unavailable",
        "host_import_failed",
        "host_entry_failed",
        "service_host_nonzero_exit",
        "module_not_found",
    }
)


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


def _bootstrap_failure_path(runtime_root: Path) -> Path:
    return runtime_root / _BOOTSTRAP_FAILURE_NAME


def _prepare_bootstrap_failure_path(runtime_root: Path) -> Path:
    """Reserve a single-use safe failure marker without opening an inherited handle."""
    path = _bootstrap_failure_path(runtime_root)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise RuntimeControlError("runtime service host bootstrap capture could not be prepared") from exc
    return path


def _bootstrap_failure_category(path: Path) -> str:
    """Read a host-authored fixed category without retaining raw stderr."""
    try:
        category = path.read_text(encoding="ascii", errors="strict").strip()
    except (OSError, UnicodeError):
        return "bootstrap_output_empty"
    return category if category in _BOOTSTRAP_FAILURE_CATEGORIES else "bootstrap_output_unclassified"


def _discard_bootstrap_failure(path: Path, *, logs: RuntimeLogs | None = None) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        # The marker is only an optional, bounded diagnostic.  A later startup
        # removes it after the old host has exited.
        if logs is not None:
            try:
                logs.write(
                    "launcher.log",
                    "service_host_bootstrap_cleanup_failed",
                    failure_category="bootstrap_marker_cleanup_failed",
                )
            except OSError:
                pass


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


def _role_owned_by_state(state: dict[str, Any] | None, role: str, identities: tuple[ProcessIdentity, ...]) -> bool:
    expected = _identity_from_role(state.get(role)) if state else None
    return expected is not None and any(same_process(expected, identity) for identity in identities)


def _state_has_owned_child(state: dict[str, Any] | None) -> bool:
    return bool(state) and any(_current(_identity_from_role(state.get(role))) for role in ("upstream", "gateway"))


def _port_snapshots(config: SupervisorConfig) -> tuple[PortListenerSnapshot, PortListenerSnapshot]:
    return inspect_port_listeners(config.upstream_port), inspect_port_listeners(config.gateway_port)


def _ports_are_confirmed_clear(upstream: PortListenerSnapshot, gateway: PortListenerSnapshot) -> bool:
    return upstream.is_empty and gateway.is_empty


def _port_failure_result(upstream: PortListenerSnapshot, gateway: PortListenerSnapshot) -> str | None:
    if upstream.inspection_failed or gateway.inspection_failed:
        return "port_inspection_failed"
    if upstream.unresolved_listener_pids or gateway.unresolved_listener_pids:
        return "unresolved_port_occupant"
    if upstream.has_listeners or gateway.has_listeners:
        return "foreign_port_occupant"
    return None


def inspect_runtime(config: SupervisorConfig) -> dict[str, Any]:
    """Read-only state, lock, listener ownership, and bounded HTTP health snapshot."""
    store = RuntimeStateStore(config.runtime_root)
    state = store.read_state()
    lock = store.read_lock()
    lock_age = store.lock_age_seconds(lock)
    supervisor = _supervisor_identity_from_state(state)
    supervisor_current = _current(supervisor)
    owned_child_current = _state_has_owned_child(state)
    upstream_listener, gateway_listener = _port_snapshots(config)
    upstream_listeners = upstream_listener.resolved_identities
    gateway_listeners = gateway_listener.resolved_identities
    port_failure = _port_failure_result(upstream_listener, gateway_listener)
    if port_failure in {"port_inspection_failed", "unresolved_port_occupant"}:
        disposition = port_failure
    elif not upstream_listener.has_listeners and not gateway_listener.has_listeners:
        if state and (supervisor_current or owned_child_current):
            disposition = "startup_in_progress" if state.get("state") in {"starting", "stopped"} else "owned_orphan_process"
        elif lock and lock.get("lock_phase") in {"reserved", "adopted"}:
            disposition = "startup_in_progress"
        elif state:
            disposition = "stale_runtime_state"
        else:
            disposition = "stopped"
    elif upstream_listener.has_listeners != gateway_listener.has_listeners:
        disposition = "upstream_only" if upstream_listener.has_listeners else "gateway_only"
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
    snapshot = {
        "schema_version": "runtime-supervisor-status-v1",
        "state": state.get("state") if state else "stopped",
        "start_disposition": disposition,
        "runtime_state": state,
        "lock": lock,
        "lock_age_seconds": lock_age,
        "supervisor_identity_current": supervisor_current,
        "owned_child_current": owned_child_current,
        "upstream_listener": upstream_listener.snapshot(),
        "gateway_listener": gateway_listener.snapshot(),
        "upstream_tcp": upstream_tcp,
        "gateway_tcp": gateway_tcp,
        "upstream_health": upstream_result,
        "gateway_health": gateway_result,
    }
    if config.runtime_mode == "portable-release":
        snapshot.update(_portable_identity_snapshot(config, snapshot, upstream_listener, gateway_listener))
    return snapshot


def _portable_identity_snapshot(
    config: SupervisorConfig,
    snapshot: dict[str, Any],
    upstream_listener: PortListenerSnapshot,
    gateway_listener: PortListenerSnapshot,
) -> dict[str, Any]:
    state = snapshot.get("runtime_state")
    lock = snapshot.get("lock")
    context: RuntimeLaunchContext | None = None
    try:
        context = read_launch_context(config.runtime_root / LAUNCH_CONTEXT_FILENAME)
    except Exception:
        context = None
    instance_present = bool(
        snapshot.get("supervisor_identity_current")
        or snapshot.get("owned_child_current")
        or type(lock) is dict and lock.get("lock_phase") in {"reserved", "adopted"}
        or type(state) is dict and state.get("state") not in {None, "stopped"}
    )
    running_release = context.release_id if context is not None and instance_present else None
    instance_id = context.instance_id if context is not None else None
    state_supervisor = _supervisor_identity_from_state(state)
    lock_supervisor = _supervisor_identity_from_state(lock)
    supervisor_lock_binding = bool(
        state_supervisor is not None
        and lock_supervisor is not None
        and same_process(state_supervisor, lock_supervisor)
        and same_process(state_supervisor, process_identity(state_supervisor.pid))
        and snapshot.get("supervisor_identity_current") is True
    )
    identity_fields_match = bool(
        context is not None
        and type(state) is dict
        and type(lock) is dict
        and supervisor_lock_binding
        and state.get("runtime_mode") == "portable-release"
        and lock.get("runtime_mode") == "portable-release"
        and state.get("supervisor_instance_id") == instance_id
        and lock.get("supervisor_instance_id") == instance_id
        and state.get("release_id") == context.release_id == lock.get("release_id")
        and state.get("runtime_manifest_sha256") == context.runtime_manifest_sha256 == lock.get("runtime_manifest_sha256")
        and state.get("startup_preflight_sha256") == context.startup_preflight_sha256 == lock.get("startup_preflight_sha256")
        and state.get("launch_context_identity") == context.identity == lock.get("launch_context_identity")
        and lock.get("lock_phase") == "adopted"
    )
    role_ownership = bool(
        type(state) is dict
        and supervisor_lock_binding
        and snapshot.get("owned_child_current") is True
        and _role_owned_by_state(state, "upstream", upstream_listener.resolved_identities)
        and _role_owned_by_state(state, "gateway", gateway_listener.resolved_identities)
    )
    executable_match = False
    if context is not None and type(state) is dict:
        expected = config.app_root.parent / context.release_id / "python" / "python.exe"
        expected_key = os.path.normcase(os.path.abspath(os.fspath(expected)))
        identities = [_supervisor_identity_from_state(state), _identity_from_role(state.get("upstream")), _identity_from_role(state.get("gateway"))]
        executable_match = all(
            identity is not None and os.path.normcase(os.path.abspath(identity.executable)) == expected_key
            for identity in identities
        )
    ownership_valid = identity_fields_match and role_ownership and executable_match
    role_health = bool(snapshot.get("upstream_health", {}).get("ok") and snapshot.get("gateway_health", {}).get("ok"))
    release_match = running_release is not None and running_release == config.release_id
    trust_match = bool(
        ownership_valid
        and context is not None
        and context.runtime_manifest_sha256 == config.runtime_manifest_sha256
        and context.startup_preflight_sha256 == config.startup_preflight_sha256
    )
    readiness = classify_portable_readiness(
        process_alive=role_ownership,
        role_health=role_health,
        instance_health=role_ownership and role_health,
        startup_ready=identity_fields_match and role_ownership and role_health,
        release_match=release_match,
        runtime_trust_ready=trust_match,
    )
    return {
        "running_release_id": running_release,
        "running_release_mismatch": running_release is not None and not release_match,
        "portable_ownership_valid": ownership_valid,
        "launch_context_identity": context.identity if context is not None else None,
        "readiness": readiness.snapshot(),
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
        upstream_listener, gateway_listener = _port_snapshots(self.config)
        no_project_ports = _ports_are_confirmed_clear(upstream_listener, gateway_listener)
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

    def start(
        self,
        *,
        wait_seconds: int = 60,
        preflight: StartupPreflightResult | None = None,
    ) -> dict[str, Any]:
        # Portable callers complete preflight before entering this method.  A
        # single lifecycle identity exists before stale/ownership inspection,
        # and that same identity is reserved in the existing STAB-1 lock.
        instance_id = uuid.uuid4().hex
        snapshot = inspect_runtime(self.config)
        disposition = snapshot["start_disposition"]
        if disposition == "complete_healthy_instance":
            if self.config.runtime_mode == "portable-release" and not (
                snapshot.get("portable_ownership_valid") is True
                and snapshot.get("running_release_mismatch") is False
                and type(snapshot.get("readiness")) is dict
                and snapshot["readiness"].get("ready") is True
            ):
                raise RuntimeStartBlocked("portable runtime ownership or readiness is untrusted")
            return {"result": "already_running", "status": snapshot}
        if disposition in {"stale_runtime_state", "startup_in_progress"}:
            if not self._clear_stale_if_safe(snapshot):
                raise RuntimeStartBlocked("runtime startup is already in progress")
        elif disposition != "stopped":
            raise RuntimeStartBlocked(f"runtime start blocked: {disposition}")
        owner = process_identity(os.getpid())
        if owner is None:
            raise RuntimeControlError("runtime launcher identity is unavailable")
        context: RuntimeLaunchContext | None = None
        expected_existing_context: str | None = None
        if self.config.runtime_mode == "portable-release":
            if not isinstance(preflight, StartupPreflightResult):
                raise RuntimeControlError("portable startup preflight is required")
            if (
                preflight.release_id != self.config.release_id
                or preflight.runtime_manifest_sha256 != self.config.runtime_manifest_sha256
                or preflight.identity != self.config.startup_preflight_sha256
            ):
                raise RuntimeControlError("portable startup preflight identity mismatch")
            context = build_launch_context(preflight, instance_id=instance_id)
            try:
                os.lstat(self.config.runtime_root / LAUNCH_CONTEXT_FILENAME)
            except FileNotFoundError:
                expected_existing_context = None
            except OSError as exc:
                raise RuntimeControlError("portable launch context could not be inspected") from exc
            else:
                expected_existing_context = read_launch_context(
                    self.config.runtime_root / LAUNCH_CONTEXT_FILENAME
                ).identity
            self.config = replace(self.config, launch_context_identity=context.identity)
        self.store.initialize()
        if not self.store.reserve_lock(
            instance_id=instance_id,
            owner=owner,
            runtime_identity=self.config.runtime_identity,
        ):
            raise RuntimeStartBlocked("runtime startup is already in progress")
        if context is not None:
            try:
                publish_launch_context(
                    self.config.runtime_root / LAUNCH_CONTEXT_FILENAME,
                    context,
                    expected_existing_identity=expected_existing_context,
                )
            except Exception as exc:
                if getattr(exc, "code", None) == "LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED":
                    # replace() has already made the target authoritative.  The
                    # B1 contract requires a reread, but never rollback/delete;
                    # retain the original stable uncertain-state error either
                    # way so the public caller knows another read is required.
                    try:
                        read_launch_context(self.config.runtime_root / LAUNCH_CONTEXT_FILENAME)
                    except Exception:
                        pass
                self.store.release_lock(instance_id)
                raise
        host: subprocess.Popen[bytes] | None = None
        bootstrap_path: Path | None = None
        logs = RuntimeLogs(self.config.log_root or self.config.runtime_root, secret_values=self.config.secret_values)
        try:
            logs.write(
                "launcher.log", "background_start_requested", supervisor_instance_id=instance_id, mode="service-host"
            )
            bootstrap_path = _prepare_bootstrap_failure_path(self.config.runtime_root)
            host_entry = self.config.app_root / "enterprise" / "runtime" / "host.py"
            if not host_entry.is_file():
                self.store.release_lock(instance_id)
                _discard_bootstrap_failure(bootstrap_path, logs=logs)
                raise RuntimeServiceHostStartupError(exit_code=2, failure_category="host_entry_unavailable")
            executable = self.config.python_executable or bundled_python(self.config.app_root)
            arguments = [
                executable,
            ]
            if self.config.runtime_mode == "portable-release":
                arguments.extend(["-I", "-B"])
            arguments.extend([
                str(host_entry),
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
                "--bootstrap-failure-path",
                str(bootstrap_path),
            ])
            if self.config.runtime_mode == "portable-release":
                arguments.extend(
                    [
                        "--runtime-mode",
                        "portable-release",
                        "--launch-context-identity",
                        str(self.config.launch_context_identity),
                    ]
                )
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
        except RuntimeServiceHostStartupError:
            raise
        except (OSError, RuntimeError) as exc:
            self.store.release_lock(instance_id)
            if bootstrap_path is not None:
                _discard_bootstrap_failure(bootstrap_path, logs=logs)
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
                and (
                    self.config.runtime_mode != "portable-release"
                    or type(current.get("readiness")) is dict
                    and current["readiness"].get("ready") is True
                )
            ):
                if bootstrap_path is not None:
                    _discard_bootstrap_failure(bootstrap_path, logs=logs)
                return {"result": "started", "status": current}
            host_exit_code = host.poll()
            if host_exit_code is not None:
                lock = self.store.read_lock()
                if lock and lock.get("supervisor_instance_id") == instance_id and lock.get("lock_phase") == "reserved":
                    self.store.release_lock(instance_id)
                failure_category = (
                    _bootstrap_failure_category(bootstrap_path)
                    if bootstrap_path is not None
                    else "bootstrap_capture_unavailable"
                )
                if bootstrap_path is not None:
                    _discard_bootstrap_failure(bootstrap_path, logs=logs)
                try:
                    logs.write(
                        "launcher.log",
                        "service_host_bootstrap_failure",
                        supervisor_instance_id=instance_id,
                        host_exit_code=host_exit_code,
                        bootstrap_failure_category=failure_category,
                    )
                except OSError:
                    pass
                raise RuntimeServiceHostStartupError(
                    exit_code=host_exit_code,
                    failure_category=failure_category,
                )
            time.sleep(0.25)
        lock = self.store.read_lock()
        if host.poll() is None:
            self._stop_owned_start_host(host)
        lock = self.store.read_lock()
        if host.poll() is not None and lock and lock.get("supervisor_instance_id") == instance_id:
            self.store.release_lock(instance_id)
        if bootstrap_path is not None:
            _discard_bootstrap_failure(bootstrap_path, logs=logs)
        raise RuntimeControlError("runtime service host startup timed out")

    def _stop_is_fully_quiescent(self, snapshot: dict[str, Any]) -> bool:
        state = snapshot.get("runtime_state")
        if type(state) is dict and state.get("state") not in {"stopped", None}:
            return False
        upstream_listener, gateway_listener = _port_snapshots(self.config)
        if not _ports_are_confirmed_clear(upstream_listener, gateway_listener):
            return False
        if snapshot.get("supervisor_identity_current") or snapshot.get("owned_child_current"):
            return False
        lock = snapshot.get("lock")
        if type(lock) is dict and lock.get("lock_phase") in {"reserved", "adopted"}:
            return False
        instance_id = state.get("supervisor_instance_id") if type(state) is dict else None
        if isinstance(instance_id, str) and instance_id and self.store.has_pending_control(
            instance_id, command="stop", pending_only=True
        ):
            return False
        if type(state) is dict and (
            state.get("active_control_command") == "stop"
            or state.get("stop_phase") not in {None, ""}
        ):
            return False
        return True

    def _wait_for_existing_stop(self, *, instance_id: str | None, wait_seconds: int) -> dict[str, Any]:
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            current = inspect_runtime(self.config)
            if self._stop_is_fully_quiescent(current):
                return {"result": "stopped", "joined_existing_stop": True, "status": current}
            disposition = current.get("start_disposition")
            if disposition in {"unresolved_port_occupant", "port_inspection_failed", "foreign_port_occupant"}:
                return {"result": disposition, "status": current}
            if isinstance(instance_id, str) and instance_id:
                state = current.get("runtime_state")
                active_id = state.get("active_control_request_id") if type(state) is dict else None
                if isinstance(active_id, str) and active_id:
                    ack = self.store.read_ack(active_id, instance_id=instance_id)
                    if ack is not None and ack.get("result") in {"foreign_port_occupant", "stop_incomplete"}:
                        return {"result": ack["result"], "ack": ack, "status": current}
            time.sleep(0.2)
        return {"result": "stop_in_progress", "status": inspect_runtime(self.config)}

    def send_command(self, command: str, *, wait_seconds: int = 60) -> dict[str, Any]:
        if command not in {"stop", "restart"}:
            raise RuntimeControlError("runtime command is invalid")
        snapshot = inspect_runtime(self.config)
        state = snapshot.get("runtime_state")
        disposition = snapshot.get("start_disposition")
        if command == "stop":
            if self._stop_is_fully_quiescent(snapshot):
                return {"result": "already_stopped", "status": snapshot}
            if type(state) is not dict:
                return {"result": str(disposition or "unresolved_port_occupant"), "status": snapshot}
            instance_id = state.get("supervisor_instance_id")
            if snapshot.get("state") == "stopped" or state.get("active_control_command") == "stop":
                return self._wait_for_existing_stop(
                    instance_id=instance_id if isinstance(instance_id, str) else None,
                    wait_seconds=wait_seconds,
                )
        elif not state or snapshot["state"] == "stopped":
            return {"result": "not_running", "status": snapshot}

        if self.config.runtime_mode == "portable-release":
            # Re-inspect immediately before publishing a command.  A valid
            # first snapshot cannot authorize a command after context/lock/
            # process ownership changes underneath the caller.
            verified = inspect_runtime(self.config)
            verified_state = verified.get("runtime_state")
            if verified.get("portable_ownership_valid") is not True:
                return {"result": "ownership_unavailable", "status": verified}
            if command == "restart" and verified.get("running_release_mismatch") is True:
                return {"result": "release_mismatch", "status": verified}
            if (
                type(state) is not dict
                or type(verified_state) is not dict
                or state.get("supervisor_instance_id") != verified_state.get("supervisor_instance_id")
                or state.get("state_generation") != verified_state.get("state_generation")
                or snapshot.get("launch_context_identity") != verified.get("launch_context_identity")
            ):
                return {"result": "ownership_unavailable", "status": verified}
            snapshot = verified
            state = verified_state

        instance_id = state.get("supervisor_instance_id") if type(state) is dict else None
        generation = state.get("state_generation") if type(state) is dict else None
        if (
            not isinstance(instance_id, str)
            or not instance_id
            or type(generation) is not int
            or generation < 0
            or not snapshot.get("supervisor_identity_current")
        ):
            return {"result": "ownership_unavailable", "status": snapshot}
        request_id = self.store.submit_command(
            command=command,
            supervisor_instance_id=instance_id,
            expected_state_generation=generation,
            launch_context_identity=snapshot.get("launch_context_identity")
            if self.config.runtime_mode == "portable-release"
            else None,
        )
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            ack = self.store.read_ack(request_id, instance_id=instance_id)
            if (
                ack is not None
                and self.config.runtime_mode == "portable-release"
                and ack.get("launch_context_identity") != snapshot.get("launch_context_identity")
            ):
                return {"result": "ownership_unavailable", "status": inspect_runtime(self.config)}
            if ack is not None:
                result = ack.get("result")
                if command == "restart" and result == "restarted":
                    current = inspect_runtime(self.config)
                    portable_ready = self.config.runtime_mode != "portable-release" or (
                        current.get("portable_ownership_valid") is True
                        and current.get("running_release_mismatch") is False
                        and type(current.get("readiness")) is dict
                        and current["readiness"].get("ready") is True
                    )
                    if (
                        current["state"] == "healthy"
                        and current.get("supervisor_identity_current")
                        and portable_ready
                    ):
                        self.store.remove_ack(request_id, instance_id=instance_id)
                        return {"result": "restarted", "ack": ack, "status": current}
                    if self.config.runtime_mode == "portable-release":
                        return {"result": "ownership_unavailable", "ack": ack, "status": current}
                if command == "stop" and result in {"stopped", "foreign_port_occupant", "unresolved_port_occupant", "stop_incomplete"}:
                    current = inspect_runtime(self.config)
                    if not current.get("supervisor_identity_current"):
                        final_ack = dict(ack)
                        final_ack["supervisor_exit_confirmed"] = True
                        self.store.remove_ack(request_id, instance_id=instance_id)
                        return {"result": result, "ack": final_ack, "status": current}
                if isinstance(result, str) and result.startswith("rejected_"):
                    self.store.remove_ack(request_id, instance_id=instance_id)
                    return {"result": result, "ack": ack, "status": inspect_runtime(self.config)}
            time.sleep(0.2)
        return {"result": "control_timeout", "status": inspect_runtime(self.config)}
