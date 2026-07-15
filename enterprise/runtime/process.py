"""Fixed-command child process creation and owned-only termination."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .logging import RuntimeLogs, StreamPump
from .ownership import ProcessIdentity, process_identity, same_process


ROLES = frozenset({"upstream", "gateway"})


class ProcessControlError(RuntimeError):
    code = "RUNTIME_PROCESS_ERROR"


@dataclass(frozen=True)
class CommandSpec:
    role: str
    arguments: tuple[str, ...]
    host: str
    port: int

    def __post_init__(self) -> None:
        if self.role not in ROLES or not self.arguments or any(not isinstance(item, str) or not item for item in self.arguments):
            raise ValueError("runtime command specification is invalid")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("runtime port is invalid")


@dataclass
class ManagedProcess:
    spec: CommandSpec
    process: subprocess.Popen[bytes]
    identity: ProcessIdentity
    parent_pid: int
    started_monotonic: float
    stdout_pump: StreamPump | None = None
    stderr_pump: StreamPump | None = None
    graceful_stop_requested: bool = False
    forced_stop: bool = False
    shutdown_file: Path | None = None
    shutdown_marker: Path | None = None
    _exit_callback: Callable[[int], None] | None = field(default=None, repr=False)

    def poll(self) -> int | None:
        return self.process.poll()

    def close_pumps(self) -> None:
        if self.stdout_pump:
            self.stdout_pump.join()
        if self.stderr_pump:
            self.stderr_pump.join()


def bundled_python(app_root: Path) -> str:
    candidate = app_root / "python" / "python.exe"
    return str(candidate.resolve()) if candidate.is_file() else str(Path(sys.executable).resolve())


def default_commands(
    app_root: Path,
    *,
    upstream_port: int,
    gateway_port: int,
    python_executable: str | None = None,
    fixture_child_wrapper: bool = False,
) -> dict[str, CommandSpec]:
    executable = python_executable or bundled_python(app_root)
    if fixture_child_wrapper:
        fixture = app_root / "enterprise" / "tests" / "runtime_fixture_service.py"
        return {
            role: CommandSpec(
                role=role,
                arguments=(executable, str(fixture), "--role", role, "--port", str(port)),
                host="127.0.0.1",
                port=port,
            )
            for role, port in (("upstream", upstream_port), ("gateway", gateway_port))
        }
    child_wrapper = app_root / "enterprise" / "runtime" / "child.py"
    return {
        "upstream": CommandSpec(
            role="upstream",
            arguments=(
                executable,
                str(child_wrapper),
                "--role",
                "upstream",
                "--app-root",
                str(app_root),
                "--host",
                "127.0.0.1",
                "--port",
                str(upstream_port),
            ),
            host="127.0.0.1",
            port=upstream_port,
        ),
        "gateway": CommandSpec(
            role="gateway",
            arguments=(
                executable,
                str(child_wrapper),
                "--role",
                "gateway",
                "--app-root",
                str(app_root),
                "--host",
                "0.0.0.0",
                "--port",
                str(gateway_port),
            ),
            host="127.0.0.1",
            port=gateway_port,
        ),
    }


def start_process(
    spec: CommandSpec,
    *,
    app_root: Path,
    logs: RuntimeLogs,
    foreground: bool,
    shutdown_file: Path,
    shutdown_marker: Path,
) -> ManagedProcess:
    stdout_log, stderr_log = logs.stream_pumps(spec.role)
    shutdown_file.parent.mkdir(parents=True, exist_ok=True)
    for path in (shutdown_file, shutdown_marker):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    arguments = [*spec.arguments, "--runtime-stop-file", str(shutdown_file), "--shutdown-marker", str(shutdown_marker)]
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        process = subprocess.Popen(
            arguments,
            cwd=str(app_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=flags,
            close_fds=True,
            shell=False,
        )
    except OSError as exc:
        raise ProcessControlError("runtime child could not be started") from exc
    identity = process_identity(process.pid)
    if identity is None:
        try:
            process.terminate()
        except OSError:
            pass
        raise ProcessControlError("runtime child identity could not be verified")
    managed = ManagedProcess(
        spec=spec,
        process=process,
        identity=identity,
        parent_pid=os.getpid(),
        started_monotonic=time.monotonic(),
        shutdown_file=shutdown_file,
        shutdown_marker=shutdown_marker,
    )
    if process.stdout is not None:
        managed.stdout_pump = StreamPump(process.stdout, stdout_log, mirror=foreground)
        managed.stdout_pump.start()
    if process.stderr is not None:
        managed.stderr_pump = StreamPump(process.stderr, stderr_log, mirror=foreground)
        managed.stderr_pump.start()
    return managed


def exit_code_snapshot(returncode: int | None) -> tuple[int | None, str | None]:
    if returncode is None:
        return None, None
    unsigned = returncode & 0xFFFFFFFF
    return int(returncode), f"0x{unsigned:08X}"


def owned_process_is_current(managed: ManagedProcess) -> bool:
    return same_process(managed.identity, process_identity(managed.process.pid))


def graceful_stop(managed: ManagedProcess, *, timeout_seconds: float = 10.0) -> str:
    """Request a wrapper-owned Uvicorn shutdown without signaling a console."""
    if managed.poll() is not None:
        managed.close_pumps()
        return "already_exited"
    if not owned_process_is_current(managed):
        raise ProcessControlError("runtime process ownership could not be verified")
    if managed.shutdown_file is None:
        raise ProcessControlError("runtime child has no graceful shutdown channel")
    managed.graceful_stop_requested = True
    try:
        with managed.shutdown_file.open("x", encoding="utf-8", newline="") as handle:
            handle.write("stop\n")
            handle.flush()
            os.fsync(handle.fileno())
        managed.process.wait(timeout=timeout_seconds)
        managed.close_pumps()
        return "graceful_shutdown"
    except subprocess.TimeoutExpired:
        return "graceful_timeout"
    except FileExistsError:
        try:
            managed.process.wait(timeout=timeout_seconds)
            managed.close_pumps()
            return "graceful_shutdown"
        except subprocess.TimeoutExpired:
            return "graceful_timeout"


def force_stop(managed: ManagedProcess, *, timeout_seconds: float = 5.0) -> str:
    if managed.poll() is not None:
        managed.close_pumps()
        return "already_exited"
    if not owned_process_is_current(managed):
        raise ProcessControlError("runtime process ownership could not be verified")
    managed.forced_stop = True
    try:
        managed.process.kill()
        managed.process.wait(timeout=timeout_seconds)
        managed.close_pumps()
        return "forced_stop"
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProcessControlError("runtime process could not be stopped") from exc
