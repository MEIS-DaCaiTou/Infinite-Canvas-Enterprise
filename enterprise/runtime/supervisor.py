"""Role-isolated, locally controlled supervision for the enterprise runtime."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .health import HealthResult, gateway_health, tcp_check, upstream_health
from .logging import RuntimeLogs, utc_now
from .ownership import ProcessIdentity, inspect_port_listeners, process_identity, same_process
from .process import (
    CommandSpec,
    ManagedProcess,
    ProcessControlError,
    default_commands,
    exit_code_snapshot,
    force_stop,
    graceful_stop,
    start_process,
)
from .state import STARTUP_LOCK_GRACE_SECONDS, RuntimeStateStore, initial_state
from .windows import JobObjectError, ProcessJob


ROLES = ("upstream", "gateway")
DEFAULT_BACKOFF_SECONDS = (1, 2, 5, 10, 30)


class RuntimeSupervisorError(RuntimeError):
    code = "RUNTIME_SUPERVISOR_ERROR"


class RuntimeStartBlocked(RuntimeSupervisorError):
    code = "RUNTIME_START_BLOCKED"


@dataclass(frozen=True)
class SupervisorConfig:
    app_root: Path
    runtime_root: Path
    mode: str
    upstream_port: int = 3001
    gateway_port: int = 8000
    startup_timeout_seconds: int = 60
    health_interval_seconds: int = 5
    health_failure_threshold: int = 3
    crash_window_seconds: int = 5 * 60
    max_abnormal_restarts: int = 5
    backoff_seconds: tuple[int, ...] = DEFAULT_BACKOFF_SECONDS
    log_max_bytes: int = 10 * 1024 * 1024
    log_backups: int = 5
    command_specs: dict[str, CommandSpec] | None = None
    secret_values: tuple[str, ...] = field(default=(), repr=False, compare=False)
    fixture_child_wrapper: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"foreground", "service-host"}:
            raise ValueError("runtime mode is invalid")
        for name, value, minimum, maximum in (
            ("startup timeout", self.startup_timeout_seconds, 5, 300),
            ("health interval", self.health_interval_seconds, 1, 60),
            ("health failure threshold", self.health_failure_threshold, 1, 10),
            ("crash window", self.crash_window_seconds, 60, 3600),
            ("max restarts", self.max_abnormal_restarts, 1, 10),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} is outside its safe range")
        if not self.backoff_seconds or len(self.backoff_seconds) > 5 or any(
            type(value) is not int or not 1 <= value <= 30 for value in self.backoff_seconds
        ):
            raise ValueError("restart backoff is invalid")
        if self.command_specs is not None and set(self.command_specs) != set(ROLES):
            raise ValueError("runtime command roles are invalid")
        if any(not isinstance(value, str) or not value for value in self.secret_values):
            raise ValueError("runtime secret values are invalid")


@dataclass
class RoleRuntime:
    role: str
    process: ManagedProcess | None = None
    state: str = "stopped"
    health: str = "unknown"
    health_failures: int = 0
    restart_count: int = 0
    restart_events: deque[float] = field(default_factory=deque)
    restart_at: float | None = None
    started_at_monotonic: float | None = None
    last_exit_code: int | None = None
    last_exit_at: str | None = None


class RuntimeSupervisor:
    """Own and supervise exactly two fixed child roles in one Windows Job."""

    def __init__(self, config: SupervisorConfig, *, instance_id: str | None = None) -> None:
        self.config = config
        self.instance_id = instance_id or uuid.uuid4().hex
        self.store = RuntimeStateStore(config.runtime_root)
        self.logs = RuntimeLogs(
            config.runtime_root,
            max_bytes=config.log_max_bytes,
            backups=config.log_backups,
            foreground=config.mode == "foreground",
            secret_values=config.secret_values,
        )
        self.commands = config.command_specs or default_commands(
            config.app_root,
            upstream_port=config.upstream_port,
            gateway_port=config.gateway_port,
            fixture_child_wrapper=config.fixture_child_wrapper,
        )
        identity = process_identity(os.getpid())
        if identity is None:
            raise RuntimeSupervisorError("supervisor identity is unavailable")
        self.supervisor_identity = identity
        self.roles = {role: RoleRuntime(role=role) for role in ROLES}
        self.state = initial_state(instance_id=self.instance_id, supervisor=identity, mode=config.mode)
        self._job: ProcessJob | None = None
        self._acquired = False
        self._stopping = False
        self._stop_request: dict[str, Any] | None = None
        self._restart_request: dict[str, Any] | None = None
        self._restart_in_progress: dict[str, Any] | None = None
        self._restart_before: dict[str, ProcessIdentity | None] = {}
        self._last_health_at = 0.0
        self._last_state_fingerprint: str | None = None
        self._wake = threading.Event()

    @staticmethod
    def _identity_from_state(value: object) -> ProcessIdentity | None:
        if type(value) is not dict:
            return None
        pid = value.get("pid")
        created = value.get("process_created_at")
        executable = value.get("executable")
        if type(pid) is not int or type(created) is not int or not isinstance(executable, str) or not executable:
            return None
        return ProcessIdentity(pid=pid, created_at=created, executable=executable)

    def _refresh_role_state(self, role: str) -> None:
        runtime = self.roles[role]
        payload = self.state[role]
        payload["state"] = runtime.state
        payload["health"] = runtime.health
        payload["restart_count"] = runtime.restart_count
        decimal, hexadecimal = exit_code_snapshot(runtime.last_exit_code)
        payload["last_exit_code_decimal"] = decimal
        payload["last_exit_code_hex"] = hexadecimal
        payload["last_exit_at"] = runtime.last_exit_at
        if runtime.process is None:
            payload["pid"] = None
            payload["process_created_at"] = None
            payload["executable"] = None
            return
        payload["pid"] = runtime.process.identity.pid
        payload["parent_pid"] = runtime.process.parent_pid
        payload["process_created_at"] = runtime.process.identity.created_at
        payload["executable"] = runtime.process.identity.executable

    def _overall_state(self) -> str:
        states = {runtime.state for runtime in self.roles.values()}
        if self._stopping:
            return "stopping"
        if "crash_loop" in states:
            return "crash_loop"
        if all(runtime.state == "healthy" for runtime in self.roles.values()):
            return "healthy"
        if "restarting" in states or self._restart_in_progress is not None:
            return "restarting"
        if "starting" in states:
            return "starting"
        if states == {"stopped"}:
            return "stopped"
        return "degraded"

    def _persist_state(self) -> None:
        for role in ROLES:
            self._refresh_role_state(role)
        self.state["state"] = self._overall_state()
        material_state = {key: value for key, value in self.state.items() if key not in {"state_generation", "updated_at"}}
        fingerprint = json.dumps(material_state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        generation = self.state.get("state_generation")
        if self._last_state_fingerprint != fingerprint:
            self.state["state_generation"] = generation + 1 if type(generation) is int and generation >= 0 else 1
            self._last_state_fingerprint = fingerprint
        self.store.write_state(self.state)

    def _log(self, event: str, **fields: object) -> None:
        self.logs.write(
            "supervisor.log",
            event,
            supervisor_instance_id=self.instance_id,
            supervisor_pid=self.supervisor_identity.pid,
            state=self._overall_state(),
            **fields,
        )

    def _inspect_start_gate(self) -> str:
        """Classify state/ports without terminating any process."""
        existing = self.store.read_state()
        upstream_snapshot = inspect_port_listeners(self.config.upstream_port)
        gateway_snapshot = inspect_port_listeners(self.config.gateway_port)
        if upstream_snapshot.inspection_failed or gateway_snapshot.inspection_failed:
            return "port_inspection_failed"
        if upstream_snapshot.unresolved_listener_pids or gateway_snapshot.unresolved_listener_pids:
            return "unresolved_port_occupant"
        upstream = upstream_snapshot.resolved_identities
        gateway = gateway_snapshot.resolved_identities
        if not upstream_snapshot.has_listeners and not gateway_snapshot.has_listeners:
            if existing:
                if existing.get("state") == "stopped":
                    return "stale_runtime_state"
                state_upstream = self._identity_from_state(existing.get("upstream"))
                state_gateway = self._identity_from_state(existing.get("gateway"))
                supervisor = self._supervisor_identity_from_state(existing)
                if any(identity and same_process(identity, process_identity(identity.pid)) for identity in (state_upstream, state_gateway)):
                    return "owned_orphan_process"
                if supervisor and same_process(supervisor, process_identity(supervisor.pid)):
                    return "startup_in_progress"
                return "stale_runtime_state"
            return "stopped"
        if upstream_snapshot.has_listeners != gateway_snapshot.has_listeners:
            return "upstream_only" if upstream_snapshot.has_listeners else "gateway_only"
        if existing:
            state_upstream = self._identity_from_state(existing.get("upstream"))
            state_gateway = self._identity_from_state(existing.get("gateway"))
            supervisor = self._supervisor_identity_from_state(existing)
            if (
                state_upstream
                and state_gateway
                and supervisor
                and any(same_process(state_upstream, identity) for identity in upstream)
                and any(same_process(state_gateway, identity) for identity in gateway)
                and same_process(supervisor, process_identity(supervisor.pid))
            ):
                upstream_ok = upstream_health("127.0.0.1", self.config.upstream_port).ok
                gateway_result = gateway_health("127.0.0.1", self.config.gateway_port)
                return "complete_healthy_instance" if upstream_ok and gateway_result.ok else "complete_unhealthy_instance"
        return "foreign_port_occupant"

    @staticmethod
    def _supervisor_identity_from_state(state: object) -> ProcessIdentity | None:
        if type(state) is not dict:
            return None
        pid = state.get("supervisor_pid")
        created = state.get("supervisor_process_created_at")
        executable = state.get("supervisor_executable")
        if type(pid) is not int or type(created) is not int or not isinstance(executable, str) or not executable:
            return None
        return ProcessIdentity(pid=pid, created_at=created, executable=executable)

    def prepare_start(self) -> str:
        return self._inspect_start_gate()

    def _acquire(self) -> None:
        disposition = self.prepare_start()
        if disposition == "complete_healthy_instance":
            raise RuntimeStartBlocked("runtime service is already running")
        if disposition not in {"stopped", "stale_runtime_state"}:
            raise RuntimeStartBlocked(f"runtime start blocked: {disposition}")
        if self.config.mode == "service-host":
            lock = self.store.read_lock()
            owner = self.store.lock_owner_identity(lock)
            if owner is None or not self.store.adopt_lock(
                instance_id=self.instance_id,
                owner=owner,
                supervisor=self.supervisor_identity,
                grace_seconds=STARTUP_LOCK_GRACE_SECONDS,
            ):
                raise RuntimeStartBlocked("runtime startup reservation could not be adopted")
        elif not self.store.acquire_foreground_lock(instance_id=self.instance_id, supervisor=self.supervisor_identity):
            raise RuntimeStartBlocked("runtime startup is already in progress")
        try:
            self._job = ProcessJob()
            self._acquired = True
        except JobObjectError as exc:
            self.store.release_lock(self.instance_id)
            raise RuntimeSupervisorError("runtime process ownership is unavailable") from exc

    def _control_path(self, prefix: str, role: str, suffix: str) -> Path:
        return self.config.runtime_root / "control" / f"{prefix}-{self.instance_id[:12]}-{role}.{suffix}"

    def _start_role(self, role: str) -> None:
        runtime = self.roles[role]
        if self._stopping or runtime.state == "crash_loop" or runtime.process is not None:
            return
        try:
            process = start_process(
                self.commands[role],
                app_root=self.config.app_root,
                logs=self.logs,
                foreground=self.config.mode == "foreground",
                shutdown_file=self._control_path("child-stop", role, "request"),
                shutdown_marker=self._control_path("child-stop", role, "complete"),
            )
            if self._job is not None:
                self._job.add(process.process)
        except (ProcessControlError, JobObjectError):
            self._schedule_restart(role, reason="start_failure", exit_code=None)
            self._log("role_start_failed", role=role, failure_category="start_failure")
            return
        runtime.process = process
        runtime.state = "starting"
        runtime.health = "unknown"
        runtime.health_failures = 0
        runtime.restart_at = None
        runtime.started_at_monotonic = time.monotonic()
        self._log(
            "role_started",
            role=role,
            pid=process.identity.pid,
            parent_pid=process.parent_pid,
            process_created_at=process.identity.created_at,
            executable=process.identity.executable,
        )

    def _stop_role(self, role: str, *, reason: str) -> dict[str, object]:
        runtime = self.roles[role]
        managed = runtime.process
        runtime.restart_at = None
        if managed is None:
            runtime.state = "stopped"
            return {"role": role, "result": "already_stopped", "graceful_timeout": False, "pid": None}
        try:
            result = graceful_stop(managed)
            timed_out = result == "graceful_timeout"
            marker_present = bool(managed.shutdown_marker and managed.shutdown_marker.is_file())
            if not timed_out:
                managed.close_pumps()
                runtime.last_exit_code = managed.poll()
                runtime.last_exit_at = utc_now()
                runtime.process = None
                runtime.state = "stopped"
                runtime.health = "unknown"
            self._log(
                "role_stop_requested",
                role=role,
                pid=managed.identity.pid,
                stop_result=result,
                graceful_marker_present=marker_present,
                reason=reason,
            )
            return {
                "role": role,
                "result": result,
                "graceful_timeout": timed_out,
                "graceful_marker_present": marker_present,
                "pid": managed.identity.pid,
            }
        except ProcessControlError:
            runtime.state = "degraded"
            self._log("role_stop_ownership_failed", role=role, failure_category="ownership")
            return {"role": role, "result": "ownership_failed", "graceful_timeout": False, "pid": managed.identity.pid}

    def _stop_children(self, *, reason: str) -> tuple[list[dict[str, object]], bool]:
        self._stopping = True
        self._persist_state()
        results = [self._stop_role(role, reason=reason) for role in ("gateway", "upstream")]
        job_termination_required = any(item.get("graceful_timeout") is True for item in results)
        if job_termination_required and self._job is not None:
            self._job.terminate()
            self._log("forced_job_termination", reason=reason, failure_category="graceful_timeout")
            # Some nested Windows Job configurations can report a successful
            # job termination while a direct child remains alive.  The saved
            # process identity lets us close that precise project child without
            # ever targeting a listener or an arbitrary PID.
            result_by_role = {str(item["role"]): item for item in results}
            for role in ROLES:
                runtime = self.roles[role]
                managed = runtime.process
                if managed is None or not same_process(managed.identity, process_identity(managed.identity.pid)):
                    continue
                try:
                    forced_result = force_stop(managed)
                    managed.close_pumps()
                    runtime.last_exit_code = managed.poll()
                    runtime.last_exit_at = utc_now()
                    runtime.process = None
                    runtime.state = "stopped"
                    runtime.health = "unknown"
                    result_by_role[role]["forced_owned_process_result"] = forced_result
                    self._log(
                        "forced_owned_process_termination",
                        role=role,
                        pid=managed.identity.pid,
                        failure_category="job_descendant_remaining",
                    )
                except ProcessControlError:
                    result_by_role[role]["forced_owned_process_result"] = "ownership_failed"
        return results, job_termination_required

    def _schedule_restart(self, role: str, *, reason: str, exit_code: int | None) -> None:
        runtime = self.roles[role]
        if self._stopping:
            runtime.state = "stopped"
            return
        now = time.monotonic()
        runtime.restart_events.append(now)
        while runtime.restart_events and now - runtime.restart_events[0] > self.config.crash_window_seconds:
            runtime.restart_events.popleft()
        runtime.last_exit_code = exit_code
        runtime.last_exit_at = utc_now()
        runtime.restart_count += 1
        if len(runtime.restart_events) >= self.config.max_abnormal_restarts:
            runtime.state = "crash_loop"
            runtime.restart_at = None
            runtime.health = "failed"
            self.logs.crash_event(
                supervisor_instance_id=self.instance_id,
                role=role,
                crash_event_type="crash_loop",
                state="crash_loop",
                restart_count=runtime.restart_count,
                crash_window_seconds=self.config.crash_window_seconds,
                last_exit_code_decimal=exit_code_snapshot(exit_code)[0],
                last_exit_code_uint32_hex=exit_code_snapshot(exit_code)[1],
                failure_category=reason,
            )
            self._log("role_crash_loop", role=role, restart_count=runtime.restart_count, failure_category=reason)
            return
        delay = self.config.backoff_seconds[min(runtime.restart_count - 1, len(self.config.backoff_seconds) - 1)]
        runtime.restart_at = now + delay
        runtime.state = "restarting"
        runtime.health = "failed"
        self.logs.crash_event(
            supervisor_instance_id=self.instance_id,
            role=role,
            crash_event_type="restart_scheduled",
            state="restarting",
            restart_count=runtime.restart_count,
            backoff_seconds=delay,
            last_exit_code_decimal=exit_code_snapshot(exit_code)[0],
            last_exit_code_uint32_hex=exit_code_snapshot(exit_code)[1],
            failure_category=reason,
        )
        self._log("role_restart_scheduled", role=role, restart_count=runtime.restart_count, backoff_seconds=delay, failure_category=reason)

    def _record_exit(self, role: str, code: int) -> None:
        runtime = self.roles[role]
        managed = runtime.process
        if managed is not None:
            managed.close_pumps()
            runtime.process = None
        runtime.last_exit_code = code
        runtime.last_exit_at = utc_now()
        if self._stopping or (managed is not None and managed.graceful_stop_requested):
            runtime.state = "stopped"
            runtime.health = "unknown"
            return
        self._schedule_restart(role, reason="unexpected_exit", exit_code=code)

    def _health_for(self, role: str) -> HealthResult:
        spec = self.commands[role]
        return upstream_health(spec.host, spec.port) if role == "upstream" else gateway_health(spec.host, spec.port)

    def _check_role_health(self, role: str) -> None:
        runtime = self.roles[role]
        if runtime.process is None or runtime.state in {"crash_loop", "stopped", "restarting"}:
            return
        result = self._health_for(role)
        self.logs.write(
            "health.log",
            "health_check",
            supervisor_instance_id=self.instance_id,
            role=role,
            pid=runtime.process.identity.pid,
            health_category=result.category,
            status_code=result.status_code,
        )
        if result.ok:
            runtime.state = "healthy"
            runtime.health = "ok"
            runtime.health_failures = 0
            return
        if role == "gateway" and result.category == "upstream_unavailable":
            runtime.state = "degraded"
            runtime.health = "upstream_unavailable"
            runtime.health_failures = 0
            return
        runtime.health = result.category
        runtime.health_failures += 1
        startup_expired = (
            runtime.started_at_monotonic is not None
            and time.monotonic() - runtime.started_at_monotonic >= self.config.startup_timeout_seconds
        )
        if startup_expired or runtime.health_failures >= self.config.health_failure_threshold:
            self._stop_role(role, reason="health_failure")
            self._schedule_restart(role, reason="startup_timeout" if startup_expired else "health_failure", exit_code=None)

    def _ack(self, command: dict[str, Any], *, result: str, before: dict[str, Any], after: dict[str, Any]) -> None:
        self.store.write_ack(
            {
                "request_id": command["request_id"],
                "command": command["command"],
                "supervisor_instance_id": self.instance_id,
                "accepted_at": command["accepted_at"],
                "completed_at": utc_now(),
                "result": result,
                "before_generation": before["generation"],
                "after_generation": after["generation"],
                "upstream_before_pid": before["upstream_pid"],
                "upstream_after_pid": after["upstream_pid"],
                "gateway_before_pid": before["gateway_pid"],
                "gateway_after_pid": after["gateway_pid"],
                "upstream_before_process_created_at": before["upstream_process_created_at"],
                "upstream_after_process_created_at": after["upstream_process_created_at"],
                "gateway_before_process_created_at": before["gateway_process_created_at"],
                "gateway_after_process_created_at": after["gateway_process_created_at"],
                **after.get("stop_report", {}),
            }
        )

    def _command_snapshot(self) -> dict[str, Any]:
        return {
            "generation": self.state.get("state_generation", 0),
            "upstream_pid": self.roles["upstream"].process.identity.pid if self.roles["upstream"].process else None,
            "gateway_pid": self.roles["gateway"].process.identity.pid if self.roles["gateway"].process else None,
            "upstream_process_created_at": (
                self.roles["upstream"].process.identity.created_at if self.roles["upstream"].process else None
            ),
            "gateway_process_created_at": (
                self.roles["gateway"].process.identity.created_at if self.roles["gateway"].process else None
            ),
        }

    def _handle_commands(self) -> None:
        current_generation = self.state.get("state_generation", 0)
        for command in self.store.consume_commands(self.instance_id):
            command["accepted_at"] = utc_now()
            expected = command.get("expected_state_generation")
            if type(expected) is not int or expected != current_generation:
                before = self._command_snapshot()
                self._ack(command, result="rejected_stale_generation", before=before, after=before)
                continue
            value = command["command"]
            self._log("control_command_accepted", command=value, request_id=command["request_id"])
            if value == "stop":
                if self._stop_request is None:
                    self._stop_request = command
                    self._stopping = True
                    self.state["active_control_request"] = command["request_id"]
                    self.state["active_control_command"] = "stop"
                    self.state["active_control_request_id"] = command["request_id"]
                    self.state["stop_phase"] = "requested"
                    self._persist_state()
            elif value == "restart" and self._restart_request is None and self._restart_in_progress is None:
                self._restart_request = command
            else:
                before = self._command_snapshot()
                self._ack(command, result="rejected_busy", before=before, after=before)

    def _perform_restart(self) -> None:
        request = self._restart_request
        self._restart_request = None
        if request is None:
            return
        self._restart_in_progress = request
        self._restart_before = {
            role: self.roles[role].process.identity if self.roles[role].process else None for role in ROLES
        }
        self._stopping = True
        self._stop_children(reason="explicit_restart")
        self._stopping = False
        for runtime in self.roles.values():
            runtime.restart_events.clear()
            runtime.restart_count = 0
            runtime.restart_at = None
            runtime.state = "stopped"
            runtime.health = "unknown"
            runtime.process = None
        self._start_role("upstream")
        self._log("explicit_restart_started", request_id=request["request_id"])

    def _complete_restart_if_ready(self) -> None:
        command = self._restart_in_progress
        if command is None or self._overall_state() != "healthy":
            return
        current = {role: self.roles[role].process.identity if self.roles[role].process else None for role in ROLES}
        if any(current[role] is None or same_process(current[role], self._restart_before.get(role)) for role in ROLES):
            return
        before = {
            "generation": command.get("expected_state_generation", 0),
            "upstream_pid": self._restart_before["upstream"].pid if self._restart_before.get("upstream") else None,
            "gateway_pid": self._restart_before["gateway"].pid if self._restart_before.get("gateway") else None,
            "upstream_process_created_at": (
                self._restart_before["upstream"].created_at if self._restart_before.get("upstream") else None
            ),
            "gateway_process_created_at": (
                self._restart_before["gateway"].created_at if self._restart_before.get("gateway") else None
            ),
        }
        after = self._command_snapshot()
        self._ack(command, result="restarted", before=before, after=after)
        self._restart_in_progress = None
        self._restart_before = {}
        self._log("explicit_restart_completed", request_id=command["request_id"])

    def _tick(self) -> None:
        self._handle_commands()
        if self._stop_request is not None:
            self._persist_state()
            return
        if self._restart_request is not None and not self._stopping:
            self._perform_restart()
        for role in ROLES:
            runtime = self.roles[role]
            if runtime.process is not None:
                code = runtime.process.poll()
                if code is not None:
                    self._record_exit(role, code)
        now = time.monotonic()
        for role in ROLES:
            runtime = self.roles[role]
            if runtime.restart_at is not None and now >= runtime.restart_at:
                self._start_role(role)
        upstream = self.roles["upstream"]
        gateway = self.roles["gateway"]
        if gateway.process is None and gateway.state != "crash_loop" and upstream.state == "healthy":
            self._start_role("gateway")
        if now - self._last_health_at >= self.config.health_interval_seconds:
            self._last_health_at = now
            self._check_role_health("upstream")
            self._check_role_health("gateway")
        self._persist_state()
        self._complete_restart_if_ready()

    def _wait_for_port_release(self, port: int, expected: ProcessIdentity | None) -> tuple[str, bool]:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            listeners = inspect_port_listeners(port)
            if listeners.inspection_failed:
                return "port_inspection_failed", True
            if listeners.unresolved_listener_pids:
                return "unresolved_port_occupant", True
            if not listeners.has_listeners:
                return "released", False
            if expected is None or all(not same_process(expected, item) for item in listeners.resolved_identities):
                return "foreign_port_occupant", True
            time.sleep(0.1)
        listeners = inspect_port_listeners(port)
        if listeners.inspection_failed:
            return "port_inspection_failed", True
        if listeners.unresolved_listener_pids:
            return "unresolved_port_occupant", True
        if not listeners.has_listeners:
            return "released", False
        if expected is None or all(not same_process(expected, item) for item in listeners.resolved_identities):
            return "foreign_port_occupant", True
        return "owned_listener_remaining", False

    def _finalize_stop(self, *, request: dict[str, Any] | None, reason: str) -> dict[str, Any]:
        before = self._command_snapshot()
        # Preserve the identities that were actually owned before requesting
        # shutdown.  Successful graceful shutdown clears ``runtime.process``;
        # using the post-stop state would turn a reused listener into a false
        # "released" result instead of the required foreign-listener result.
        expected = {
            role: self.roles[role].process.identity if self.roles[role].process is not None else None for role in ROLES
        }
        self._stopping = True
        self.state["stop_phase"] = "stopping_children"
        self._persist_state()
        child_results, job_termination_required = self._stop_children(reason=reason)
        self.state["stop_phase"] = "closing_job"
        self._persist_state()
        if self._job is not None:
            self._job.close()
            self._job = None
        self.state["stop_phase"] = "verifying_pids"
        self._persist_state()
        for role in ROLES:
            runtime = self.roles[role]
            if runtime.process is not None:
                runtime.last_exit_code = runtime.process.poll()
                runtime.last_exit_at = utc_now()
                runtime.process.close_pumps()
                runtime.process = None
            runtime.state = "stopped"
            runtime.health = "unknown"
            runtime.restart_at = None
        self.state["stop_phase"] = "verifying_ports"
        self._persist_state()
        upstream_release, upstream_foreign = self._wait_for_port_release(self.config.upstream_port, expected["upstream"])
        gateway_release, gateway_foreign = self._wait_for_port_release(self.config.gateway_port, expected["gateway"])
        owned_pid_release_complete = all(
            identity is None or not same_process(identity, process_identity(identity.pid)) for identity in expected.values()
        )
        report = {
            "child_stop_results": child_results,
            "job_termination_required": job_termination_required,
            "owned_pid_release_complete": owned_pid_release_complete,
            "supervisor_exit_confirmed": False,
            "upstream_port_release": upstream_release,
            "gateway_port_release": gateway_release,
            "foreign_listener_detected": upstream_foreign or gateway_foreign,
        }
        result = "foreign_port_occupant" if report["foreign_listener_detected"] else "stopped"
        if "unresolved_port_occupant" in {upstream_release, gateway_release}:
            result = "unresolved_port_occupant"
        elif "port_inspection_failed" in {upstream_release, gateway_release}:
            result = "stop_incomplete"
        if not owned_pid_release_complete or "owned_listener_remaining" in {upstream_release, gateway_release}:
            result = "stop_incomplete"
        self.state["stop_phase"] = "publishing_ack"
        self._persist_state()
        if request is not None:
            after = {**self._command_snapshot(), "stop_report": report}
            self._ack(request, result=result, before=before, after=after)
        self.state["stop_phase"] = "exiting_supervisor"
        self._persist_state()
        self._log("supervisor_stop_completed", reason=reason, result=result, **report)
        return report

    def _best_effort_failure_cleanup(self, reason: str) -> None:
        try:
            self._stopping = True
            self._finalize_stop(request=None, reason=reason)
        except Exception:
            try:
                if self._job is not None:
                    self._job.terminate()
                    self._job.close()
                    self._job = None
            except Exception:
                pass

    def run(self) -> int:
        return_code = 2
        try:
            self._acquire()
            self.logs.write("launcher.log", "service_host_started", supervisor_instance_id=self.instance_id, mode=self.config.mode)
            self._start_role("upstream")
            if self.roles["upstream"].process is None:
                raise RuntimeSupervisorError("initial upstream child could not be started")
            while self._stop_request is None and not self._stopping:
                self._tick()
                self._wake.wait(timeout=0.2)
                self._wake.clear()
            self._finalize_stop(request=self._stop_request, reason="manual_stop")
            return_code = 0
        except KeyboardInterrupt:
            self._best_effort_failure_cleanup("foreground_interrupt")
            return_code = 0
        except Exception:
            try:
                self._log("supervisor_unhandled_failure", failure_category="internal")
            except Exception:
                pass
            self._best_effort_failure_cleanup("supervisor_failure")
            return_code = 2
        finally:
            if self._job is not None:
                try:
                    self._job.close()
                except Exception:
                    pass
                self._job = None
            # The stop acknowledgement has already been durably published.
            # Leave a final stopped state without an active request while this
            # process is still alive; controllers still require the full
            # supervisor identity to disappear before reporting completion.
            self._stopping = False
            self.state["active_control_request"] = None
            self.state["active_control_command"] = None
            self.state["active_control_request_id"] = None
            self.state["stop_phase"] = None
            try:
                self._persist_state()
            except Exception:
                pass
            if self._acquired:
                self.store.release_lock(self.instance_id)
            try:
                self.logs.write("launcher.log", "service_host_stopped", supervisor_instance_id=self.instance_id, mode=self.config.mode)
            except Exception:
                pass
        return return_code

    def status_snapshot(self) -> dict[str, object]:
        state = self.store.read_state()
        disposition = self._inspect_start_gate()
        return {
            "schema_version": "runtime-supervisor-status-v1",
            "state": state.get("state") if state else "stopped",
            "start_disposition": disposition,
            "runtime_state": state,
            "upstream_tcp": tcp_check("127.0.0.1", self.config.upstream_port).snapshot(),
            "gateway_tcp": tcp_check("127.0.0.1", self.config.gateway_port).snapshot(),
            "upstream_health": upstream_health("127.0.0.1", self.config.upstream_port).snapshot(),
            "gateway_health": gateway_health("127.0.0.1", self.config.gateway_port).snapshot(),
        }
