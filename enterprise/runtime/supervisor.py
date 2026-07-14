"""Role-isolated child supervision for the local enterprise runtime."""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .health import HealthResult, gateway_health, tcp_check, upstream_health
from .logging import RuntimeLogs, utc_now
from .ownership import ProcessIdentity, pid_exists, port_identities, same_process
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
from .state import RuntimeStateStore, initial_state
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
    """One service-host-owned state machine for upstream and gateway.

    The class accepts no externally supplied shell command.  Public CLI paths
    construct fixed command specifications; tests may provide fixture specs by
    direct constructor injection.
    """

    def __init__(self, config: SupervisorConfig, *, instance_id: str | None = None) -> None:
        self.config = config
        self.instance_id = instance_id or uuid.uuid4().hex
        self.store = RuntimeStateStore(self.config.runtime_root)
        self.logs = RuntimeLogs(
            self.config.runtime_root,
            max_bytes=self.config.log_max_bytes,
            backups=self.config.log_backups,
            foreground=self.config.mode == "foreground",
        )
        self.commands = self.config.command_specs or default_commands(
            self.config.app_root,
            upstream_port=self.config.upstream_port,
            gateway_port=self.config.gateway_port,
        )
        self.roles = {role: RoleRuntime(role=role) for role in ROLES}
        self.state = initial_state(instance_id=self.instance_id, supervisor_pid=os.getpid(), mode=self.config.mode)
        self._job: ProcessJob | None = None
        self._stopping = False
        self._restart_requested = False
        self._last_health_at = 0.0
        self._wake = threading.Event()

    @staticmethod
    def _identity_from_state(role_state: object) -> ProcessIdentity | None:
        if type(role_state) is not dict:
            return None
        pid = role_state.get("pid")
        created = role_state.get("process_created_at")
        executable = role_state.get("executable")
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
        if "restarting" in states:
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
        self.store.write_state(self.state)

    def _log(self, event: str, **fields: object) -> None:
        self.logs.write(
            "supervisor.log",
            event,
            supervisor_instance_id=self.instance_id,
            supervisor_pid=os.getpid(),
            state=self._overall_state(),
            **fields,
        )

    def _inspect_start_gate(self) -> str:
        """Return only a safe start disposition; never kills an existing PID."""
        existing = self.store.read_state()
        upstream = port_identities(self.config.upstream_port)
        gateway = port_identities(self.config.gateway_port)
        if not upstream and not gateway:
            if existing:
                if existing.get("state") == "stopped":
                    return "stale_runtime_state"
                state_upstream = self._identity_from_state(existing.get("upstream"))
                state_gateway = self._identity_from_state(existing.get("gateway"))
                supervisor_pid = existing.get("supervisor_pid")
                if (state_upstream and pid_exists(state_upstream.pid)) or (state_gateway and pid_exists(state_gateway.pid)) or pid_exists(supervisor_pid):
                    return "owned_orphan_process"
                return "stale_runtime_state"
            return "stopped"
        if bool(upstream) != bool(gateway):
            return "upstream_only" if upstream else "gateway_only"
        if existing:
            state_upstream = self._identity_from_state(existing.get("upstream"))
            state_gateway = self._identity_from_state(existing.get("gateway"))
            if (
                state_upstream
                and state_gateway
                and any(same_process(state_upstream, identity) for identity in upstream)
                and any(same_process(state_gateway, identity) for identity in gateway)
                and pid_exists(existing.get("supervisor_pid"))
            ):
                upstream_ok = upstream_health("127.0.0.1", self.config.upstream_port).ok
                gateway_result = gateway_health("127.0.0.1", self.config.gateway_port)
                return "complete_healthy_instance" if upstream_ok and gateway_result.ok else "complete_unhealthy_instance"
        return "foreign_port_occupant"

    def prepare_start(self) -> str:
        disposition = self._inspect_start_gate()
        if disposition == "stale_runtime_state":
            self.store.clear_stale_lock()
            return "stopped"
        return disposition

    def _acquire(self) -> None:
        disposition = self.prepare_start()
        if disposition == "complete_healthy_instance":
            raise RuntimeStartBlocked("runtime service is already running")
        if disposition != "stopped":
            raise RuntimeStartBlocked(f"runtime start blocked: {disposition}")
        if not self.store.acquire_or_adopt_lock(instance_id=self.instance_id, supervisor_pid=os.getpid()):
            raise RuntimeStartBlocked("runtime startup is already in progress")
        try:
            self._job = ProcessJob()
        except JobObjectError as exc:
            self.store.release_lock(self.instance_id)
            raise RuntimeSupervisorError("runtime process ownership is unavailable") from exc

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
            )
            if self._job is not None:
                self._job.add(process.process)
        except (ProcessControlError, JobObjectError) as exc:
            if "process" in locals():
                try:
                    force_stop(process)
                except ProcessControlError:
                    pass
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
            return {"role": role, "result": "already_stopped", "graceful_timed_out": False}
        try:
            result = graceful_stop(managed)
            timed_out = result == "timeout"
            if result == "timeout":
                result = force_stop(managed)
            return_code = managed.poll()
            runtime.last_exit_code = return_code
            runtime.last_exit_at = utc_now()
            runtime.process = None
            runtime.state = "stopped"
            runtime.health = "unknown"
            self._log(
                "role_stopped",
                role=role,
                pid=managed.identity.pid,
                stop_result=result,
                graceful_timed_out=timed_out,
                reason=reason,
            )
            return {"role": role, "result": result, "graceful_timed_out": timed_out}
        except ProcessControlError:
            runtime.state = "degraded"
            self._log("role_stop_ownership_failed", role=role, failure_category="ownership")
            return {"role": role, "result": "ownership_failed", "graceful_timed_out": False}

    def _stop_children(self, *, reason: str) -> list[dict[str, object]]:
        self._stopping = True
        self._persist_state()
        results = [self._stop_role(role, reason=reason) for role in ("gateway", "upstream")]
        if any(item.get("graceful_timed_out") is True for item in results) and self._job is not None:
            self._job.terminate()
        return results

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
            managed = runtime.process
            if managed is not None:
                self._stop_role(role, reason="health_failure")
            self._schedule_restart(role, reason="startup_timeout" if startup_expired else "health_failure", exit_code=None)

    def _handle_commands(self) -> None:
        for command in self.store.consume_commands(self.instance_id):
            value = command["command"]
            self._log("control_command_received", command=value)
            if value == "stop":
                self._stopping = True
            elif value == "restart":
                self._restart_requested = True

    def _perform_restart(self) -> None:
        self._restart_requested = False
        self._stopping = True
        self._stop_children(reason="explicit_restart")
        self._stopping = False
        for runtime in self.roles.values():
            runtime.restart_events.clear()
            runtime.restart_count = 0
            runtime.restart_at = None
            runtime.state = "stopped"
            runtime.health = "unknown"
        self._start_role("upstream")
        self._log("explicit_restart_started")

    def _tick(self) -> None:
        self._handle_commands()
        if self._restart_requested and not self._stopping:
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

    def run(self) -> int:
        self._acquire()
        self.logs.write("launcher.log", "service_host_started", supervisor_instance_id=self.instance_id, mode=self.config.mode)
        self._start_role("upstream")
        try:
            while not self._stopping:
                self._tick()
                self._wake.wait(timeout=0.2)
                self._wake.clear()
            self._stop_children(reason="manual_stop")
            self._stopping = False
            self._persist_state()
            return 0
        except KeyboardInterrupt:
            self._stopping = True
            self._stop_children(reason="foreground_interrupt")
            self._stopping = False
            self._persist_state()
            return 0
        except Exception:
            self._log("supervisor_unhandled_failure", failure_category="internal")
            self._stopping = True
            self._stop_children(reason="supervisor_failure")
            self._stopping = False
            self._persist_state()
            return 2
        finally:
            if self._job is not None:
                self._job.close()
            self.store.release_lock(self.instance_id)
            self.logs.write("launcher.log", "service_host_stopped", supervisor_instance_id=self.instance_id, mode=self.config.mode)

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
