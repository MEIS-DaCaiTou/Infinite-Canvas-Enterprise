"""STAB-1 runtime supervision tests using only temporary fixture processes.

Run from the repository root:

    python .\\enterprise\\tests\\test_stab_1_supervisor_logging.py
"""

from __future__ import annotations

import json
import argparse
import contextlib
import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import ctypes
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enterprise.runtime import cli as runtime_cli
from enterprise.runtime.control import RuntimeControlError, RuntimeController, inspect_runtime, validate_runtime_root
from enterprise.runtime.health import tcp_check
from enterprise.runtime.logging import RotatingTextLog, RuntimeLogs, StreamPump, redact_text
from enterprise.runtime.ownership import PortListenerSnapshot, ProcessIdentity, inspect_port_listeners, pid_exists, port_identities, process_identity
from enterprise.runtime.process import CommandSpec, default_commands, exit_code_snapshot
from enterprise.runtime.state import RuntimeStateStore, initial_state
from enterprise.runtime.supervisor import RuntimeStartBlocked, RuntimeSupervisor, SupervisorConfig
import enterprise.runtime.ownership as runtime_ownership


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fixture_spec(
    role: str,
    port: int,
    *,
    emit_secret: bool = False,
    upstream_down_file: Path | None = None,
    ignore_runtime_stop: bool = False,
) -> CommandSpec:
    arguments = [
        sys.executable,
        str(ROOT / "enterprise" / "tests" / "runtime_fixture_service.py"),
        "--role",
        role,
        "--port",
        str(port),
    ]
    if emit_secret:
        arguments.append("--emit-secret")
    if upstream_down_file is not None:
        arguments.extend(("--upstream-down-file", str(upstream_down_file)))
    if ignore_runtime_stop:
        arguments.append("--ignore-runtime-stop")
    return CommandSpec(role=role, arguments=tuple(arguments), host="127.0.0.1", port=port)


def build_supervisor(
    runtime_root: Path,
    *,
    max_restarts: int = 5,
    emit_secret: bool = False,
    ignore_upstream_stop: bool = False,
) -> RuntimeSupervisor:
    upstream_port = free_port()
    gateway_port = free_port()
    upstream_down_file = runtime_root.parent / "fixture-upstream-down"
    config = SupervisorConfig(
        app_root=ROOT,
        runtime_root=runtime_root,
        mode="service-host",
        upstream_port=upstream_port,
        gateway_port=gateway_port,
        startup_timeout_seconds=10,
        health_interval_seconds=1,
        health_failure_threshold=2,
        crash_window_seconds=60,
        max_abnormal_restarts=max_restarts,
        backoff_seconds=(1,),
        log_max_bytes=64 * 1024,
        log_backups=2,
        command_specs={
            "upstream": fixture_spec(
                "upstream",
                upstream_port,
                emit_secret=emit_secret,
                ignore_runtime_stop=ignore_upstream_stop,
            ),
            "gateway": fixture_spec("gateway", gateway_port, upstream_down_file=upstream_down_file),
        },
    )
    supervisor = RuntimeSupervisor(config)
    supervisor.fixture_upstream_down_file = upstream_down_file  # type: ignore[attr-defined]
    return supervisor


def start_supervisor(supervisor: RuntimeSupervisor) -> threading.Thread:
    if supervisor.store.read_lock() is None:
        owner = process_identity(os.getpid())
        assert owner is not None
        assert supervisor.store.reserve_lock(instance_id=supervisor.instance_id, owner=owner)
    thread = threading.Thread(target=supervisor.run, daemon=True)
    thread.start()
    return thread


def wait_for(predicate, *, seconds: float = 15.0, message: str = "condition timed out") -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(message)


def stop_supervisor(supervisor: RuntimeSupervisor, thread: threading.Thread) -> None:
    supervisor.store.submit_command(
        command="stop",
        supervisor_instance_id=supervisor.instance_id,
        expected_state_generation=supervisor.state["state_generation"],
    )
    thread.join(timeout=15)
    assert not thread.is_alive(), "supervisor did not stop"


def run_cli(command: str, *, runtime_root: Path, upstream_port: int, gateway_port: int, timeout: float = 25.0) -> dict[str, object]:
    output_path = runtime_root.parent / f"cli-{command}-{time.time_ns()}.jsonl"
    arguments = [
        sys.executable,
        "-m",
        "enterprise.runtime.cli",
        command,
        "--app-root",
        str(ROOT),
        "--runtime-root",
        str(runtime_root),
        "--upstream-port",
        str(upstream_port),
        "--gateway-port",
        str(gateway_port),
        "--fixture-child-wrapper",
    ]
    with output_path.open("x", encoding="utf-8", newline="") as handle:
        result = subprocess.run(
            arguments,
            cwd=ROOT,
            text=True,
            stdout=handle,
            stderr=handle,
            timeout=timeout,
            shell=False,
        )
    output = output_path.read_text(encoding="utf-8", errors="replace")
    output_path.unlink()
    assert result.returncode == 0, f"runtime CLI {command} failed"
    payload = json.loads(next(line for line in reversed(output.splitlines()) if line.startswith("{")))
    assert type(payload) is dict
    return payload


def _write_lifecycle_report(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f"lifecycle-{time.time_ns()}.tmp")
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    with temporary.open("x", encoding="utf-8", newline="") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _worker_flags() -> int:
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_BREAKAWAY_FROM_JOB


def _run_cli_lifecycle_stop_worker(
    *,
    runtime_root: Path,
    upstream_port: int,
    gateway_port: int,
    report_path: Path,
    phase_worker_identity: ProcessIdentity,
) -> int:
    try:
        wait_for(
            lambda: not runtime_ownership.same_process(
                phase_worker_identity, process_identity(phase_worker_identity.pid)
            ),
            seconds=20,
            message="CLI lifecycle phase worker remained alive",
        )
        stopped = run_cli("stop", runtime_root=runtime_root, upstream_port=upstream_port, gateway_port=gateway_port, timeout=45)
        ack = stopped.get("ack")
        if stopped.get("result") != "stopped" or type(ack) is not dict:
            raise AssertionError("controlled stop did not return a completion acknowledgement")
        required = {
            "result": "stopped",
            "owned_pid_release_complete": True,
            "supervisor_exit_confirmed": True,
            "upstream_port_release": "released",
            "gateway_port_release": "released",
            "foreign_listener_detected": False,
        }
        if any(ack.get(key) != value for key, value in required.items()):
            raise AssertionError("controlled stop acknowledgement is incomplete")
        if not all(item.get("graceful_marker_present") is True for item in ack.get("child_stop_results", [])):
            raise AssertionError("graceful child shutdown markers are missing")
        if tcp_check("127.0.0.1", upstream_port).ok or tcp_check("127.0.0.1", gateway_port).ok:
            raise AssertionError("controlled stop left a fixture listener")
        if (runtime_root / "runtime-supervisor.lock").exists():
            raise AssertionError("controlled stop left an instance lock")
        if list((runtime_root / "control").glob("cmd-*.json")) or list((runtime_root / "control").glob("ack-*.json")):
            raise AssertionError("controlled stop left a control request or acknowledgement")
        _write_lifecycle_report(report_path, {"result": "pass"})
        return 0
    except Exception as exc:
        _write_lifecycle_report(report_path, {"result": "fail", "phase": type(exc).__name__})
        return 2


def _run_cli_lifecycle_phase_worker(
    *, runtime_root: Path, upstream_port: int, gateway_port: int, report_path: Path
) -> int:
    phase = "start"
    try:
        started = run_cli("start", runtime_root=runtime_root, upstream_port=upstream_port, gateway_port=gateway_port)
        if started.get("result") != "started":
            raise AssertionError("short-lived start CLI did not report started")
        store = RuntimeStateStore(runtime_root)
        state = store.read_state()
        if state is None or state.get("state") != "healthy":
            raise AssertionError("service host did not survive short-lived start CLI")
        upstream_before = state["upstream"]["pid"]
        gateway_before = state["gateway"]["pid"]
        if not isinstance(upstream_before, int) or not isinstance(gateway_before, int):
            raise AssertionError("healthy roles have no PID")
        phase = "status"
        if run_cli("status", runtime_root=runtime_root, upstream_port=upstream_port, gateway_port=gateway_port).get("state") != "healthy":
            raise AssertionError("status was not healthy")
        phase = "health"
        if run_cli("health", runtime_root=runtime_root, upstream_port=upstream_port, gateway_port=gateway_port).get("state") != "healthy":
            raise AssertionError("health was not healthy")
        phase = "restart"
        restarted = run_cli("restart", runtime_root=runtime_root, upstream_port=upstream_port, gateway_port=gateway_port, timeout=45)
        ack = restarted.get("ack")
        if restarted.get("result") != "restarted" or type(ack) is not dict:
            raise AssertionError("restart did not return a completion acknowledgement")
        if ack.get("upstream_before_pid") != upstream_before or ack.get("gateway_before_pid") != gateway_before:
            raise AssertionError("restart acknowledgement has incorrect prior PID generations")
        if (
            ack.get("upstream_after_pid") == upstream_before
            and ack.get("upstream_after_process_created_at") == ack.get("upstream_before_process_created_at")
        ) or (
            ack.get("gateway_after_pid") == gateway_before
            and ack.get("gateway_after_process_created_at") == ack.get("gateway_before_process_created_at")
        ):
            raise AssertionError("restart did not replace both roles")
        phase = "stop_worker"
        identity = process_identity(os.getpid())
        if identity is None:
            raise AssertionError("lifecycle worker identity is unavailable")
        arguments = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--cli-stop-worker",
            "--runtime-root",
            str(runtime_root),
            "--upstream-port",
            str(upstream_port),
            "--gateway-port",
            str(gateway_port),
            "--report-path",
            str(report_path),
            "--phase-worker-pid",
            str(identity.pid),
            "--phase-worker-created-at",
            str(identity.created_at),
            "--phase-worker-executable",
            identity.executable,
        ]
        subprocess.Popen(
            arguments,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_worker_flags(),
            close_fds=True,
            shell=False,
        )
        return 0
    except Exception as exc:
        _write_lifecycle_report(report_path, {"result": "fail", "phase": phase, "error_type": type(exc).__name__})
        return 2


def test_role_isolation_and_stop() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-") as raw:
        supervisor = build_supervisor(Path(raw) / "runtime")
        thread = start_supervisor(supervisor)
        wait_for(lambda: supervisor.state["state"] == "healthy", message="fixture runtime did not become healthy")
        upstream_pid = supervisor.roles["upstream"].process.process.pid  # type: ignore[union-attr]
        gateway_pid = supervisor.roles["gateway"].process.process.pid  # type: ignore[union-attr]

        supervisor.fixture_upstream_down_file.write_text("down", encoding="utf-8")  # type: ignore[attr-defined]
        supervisor.roles["upstream"].process.process.kill()  # type: ignore[union-attr]
        wait_for(
            lambda: supervisor.roles["gateway"].health == "upstream_unavailable",
            message="gateway did not classify upstream outage separately",
        )
        wait_for(
            lambda: supervisor.roles["upstream"].process is not None
            and supervisor.roles["upstream"].process.process.pid != upstream_pid
            and supervisor.roles["upstream"].state == "healthy",
            message="upstream was not independently restarted",
        )
        assert supervisor.roles["gateway"].process is not None
        assert supervisor.roles["gateway"].process.process.pid == gateway_pid
        supervisor.fixture_upstream_down_file.unlink()  # type: ignore[attr-defined]
        wait_for(lambda: supervisor.roles["gateway"].state == "healthy")

        supervisor.roles["gateway"].process.process.kill()  # type: ignore[union-attr]
        wait_for(
            lambda: supervisor.roles["gateway"].process is not None
            and supervisor.roles["gateway"].process.process.pid != gateway_pid
            and supervisor.roles["gateway"].state == "healthy",
            message="gateway was not independently restarted",
        )
        assert supervisor.roles["upstream"].process is not None
        restarted_upstream_pid = supervisor.roles["upstream"].process.process.pid

        stop_supervisor(supervisor, thread)
        assert not pid_exists(restarted_upstream_pid)
        assert supervisor.state["state"] == "stopped"
        assert (Path(raw) / "runtime" / "runtime-state.json").exists()
        assert not (Path(raw) / "runtime" / "runtime-supervisor.lock").exists()
        second = build_supervisor(Path(raw) / "runtime")
        second_thread = start_supervisor(second)
        wait_for(lambda: second.state["state"] == "healthy", message="start-stop-start left stale state")
        stop_supervisor(second, second_thread)


def test_crash_loop_and_explicit_stop() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-crash-") as raw:
        supervisor = build_supervisor(Path(raw) / "runtime", max_restarts=2)
        thread = start_supervisor(supervisor)
        wait_for(lambda: supervisor.state["state"] == "healthy")
        for _ in range(2):
            managed = supervisor.roles["upstream"].process
            assert managed is not None
            managed.process.kill()
            wait_for(lambda: supervisor.roles["upstream"].state in {"restarting", "crash_loop"}, seconds=5)
            if supervisor.roles["upstream"].state != "crash_loop":
                wait_for(lambda: supervisor.roles["upstream"].state == "healthy", seconds=8)
        wait_for(lambda: supervisor.roles["upstream"].state == "crash_loop", seconds=8)
        time.sleep(1.2)
        assert supervisor.roles["upstream"].state == "crash_loop"
        events = (Path(raw) / "runtime" / "crash-events.jsonl").read_text(encoding="utf-8").splitlines()
        assert any(json.loads(line)["state"] == "crash_loop" for line in events)
        supervisor.store.submit_command(
            command="restart",
            supervisor_instance_id=supervisor.instance_id,
            expected_state_generation=supervisor.state["state_generation"],
        )
        wait_for(lambda: supervisor.state["state"] == "healthy", seconds=12, message="explicit restart did not clear crash loop")
        stop_supervisor(supervisor, thread)


def test_logs_state_rotation_and_secret_redaction() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-logs-") as raw:
        root = Path(raw) / "runtime"
        supervisor = build_supervisor(root, emit_secret=True)
        thread = start_supervisor(supervisor)
        wait_for(lambda: supervisor.state["state"] == "healthy")
        wait_for(lambda: "[REDACTED]" in (root / "upstream.stdout.log").read_text(encoding="utf-8"))
        assert "fixture-marker" not in (root / "upstream.stdout.log").read_text(encoding="utf-8")
        state_text = (root / "runtime-state.json").read_text(encoding="utf-8")
        assert "fixture-secret-value" not in state_text
        rotating = RotatingTextLog(root / "rotation.log", max_bytes=64 * 1024, backups=2)
        rotating.write("x" * (64 * 1024))
        rotating.write("y" * 10)
        assert (root / "rotation.log.1").exists()
        stop_supervisor(supervisor, thread)


def test_start_gate_and_atomic_state() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-state-") as raw:
        root = Path(raw)
        runtime_root = root / "runtime"
        assert validate_runtime_root(root / "app", runtime_root) == runtime_root.resolve()
        try:
            validate_runtime_root(root / "app", root / "app" / "data" / "runtime")
        except Exception:
            pass
        else:
            raise AssertionError("runtime data path was accepted")
        store = RuntimeStateStore(runtime_root)
        store.initialize()
        identity = process_identity(os.getpid())
        assert identity is not None
        state = initial_state(instance_id="fixture", supervisor=identity, mode="service-host")
        state["state"] = "stopped"
        store.write_state(state)
        assert store.read_state() == state
        assert not list(runtime_root.glob("*.tmp"))

        port = free_port()
        foreign_stop = root / "foreign-stop.request"
        foreign_marker = root / "foreign-stop.complete"
        foreign = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "enterprise" / "tests" / "runtime_fixture_service.py"),
                "--role",
                "upstream",
                "--port",
                str(port),
                "--runtime-stop-file",
                str(foreign_stop),
                "--shutdown-marker",
                str(foreign_marker),
            ]
        )
        try:
            config = SupervisorConfig(
                app_root=ROOT,
                runtime_root=runtime_root,
                mode="service-host",
                upstream_port=port,
                gateway_port=free_port(),
                command_specs={"upstream": fixture_spec("upstream", port), "gateway": fixture_spec("gateway", free_port())},
            )
            wait_for(lambda: inspect_runtime(config)["start_disposition"] in {"upstream_only", "foreign_port_occupant"})
            assert inspect_runtime(config)["start_disposition"] in {"upstream_only", "foreign_port_occupant"}
        finally:
            foreign_stop.write_text("stop\n", encoding="utf-8")
            foreign.wait(timeout=5)


def test_static_runtime_boundary() -> None:
    runtime_files = list((ROOT / "enterprise" / "runtime").glob("*.py"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
    assert "shell=True" not in combined
    assert "input(" not in combined
    assert "webbrowser" not in combined
    assert exit_code_snapshot(-1073741819) == (-1073741819, "0xC0000005")
    stop_script = (ROOT / "停止企业版.bat").read_text(encoding="utf-8")
    start_script = (ROOT / "启动企业版.bat").read_text(encoding="utf-8")
    restart_script = (ROOT / "重启企业版.bat").read_text(encoding="utf-8")
    status_script = (ROOT / "查看企业版状态.bat").read_text(encoding="utf-8")
    foreground_script = (ROOT / "启动企业版前台.bat").read_text(encoding="utf-8")
    for script in (stop_script, start_script, restart_script, status_script, foreground_script):
        assert "enterprise.runtime.cli" in script
        assert "exit /b %errorlevel%" in script.lower()
    assert "taskkill" not in stop_script.lower()
    commands = default_commands(ROOT, upstream_port=13001, gateway_port=18000)
    for command in commands.values():
        assert command.arguments[1].endswith("enterprise\\runtime\\child.py") or command.arguments[1].endswith(
            "enterprise/runtime/child.py"
        )
        assert "-m" not in command.arguments
    host_entry = (ROOT / "enterprise" / "runtime" / "host.py").read_text(encoding="utf-8")
    assert "sys.path.insert" in host_entry and "enterprise.runtime.cli" in host_entry


def _cli_args(command: str, runtime_root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        command=command,
        app_root=str(ROOT),
        runtime_root=str(runtime_root),
        upstream_port=free_port(),
        gateway_port=free_port(),
        fixture_child_wrapper=True,
        instance_id="fixture-instance",
    )


def _run_cli_with_result(command: str, result: str) -> tuple[int, dict[str, object]]:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-cli-result-") as raw:
        runtime_root = Path(raw) / "runtime"
        config = SupervisorConfig(app_root=ROOT, runtime_root=runtime_root, mode="service-host")
        args = _cli_args(command, runtime_root)
        output = io.StringIO()
        with patch.object(runtime_cli, "_config", return_value=config), patch.object(
            runtime_cli, "RuntimeController"
        ) as controller_type, contextlib.redirect_stdout(output):
            controller = controller_type.return_value
            if command == "start":
                controller.start.return_value = {"result": result}
            elif command == "stop":
                controller.send_command.return_value = {"result": result}
            elif command == "restart":
                controller.send_command.return_value = {"result": result}
            else:
                raise AssertionError("unsupported test command")
            exit_code = runtime_cli.run(args)
        return exit_code, json.loads(output.getvalue())


def test_cli_exit_code_contract() -> None:
    for command, result in (
        ("start", "started"),
        ("start", "already_running"),
        ("stop", "stopped"),
        ("stop", "already_stopped"),
        ("restart", "restarted"),
    ):
        exit_code, payload = _run_cli_with_result(command, result)
        assert exit_code == 0 and payload["result"] == result
    for command, result in (
        ("stop", "stop_incomplete"),
        ("stop", "foreign_port_occupant"),
        ("stop", "unresolved_port_occupant"),
        ("restart", "not_running"),
        ("restart", "rejected_busy"),
    ):
        exit_code, payload = _run_cli_with_result(command, result)
        assert exit_code == 2 and payload["result"] == result

    with tempfile.TemporaryDirectory(prefix="ice-stab1-cli-health-") as raw:
        args = _cli_args("status", Path(raw) / "runtime")
        config = SupervisorConfig(app_root=ROOT, runtime_root=Path(raw) / "runtime", mode="service-host")
        for state in ("healthy", "degraded", "crash_loop"):
            snapshot = {
                "state": state,
                "upstream_health": {"ok": state == "healthy"},
                "gateway_health": {"ok": state == "healthy"},
            }
            with patch.object(runtime_cli, "_config", return_value=config), patch.object(
                runtime_cli, "inspect_runtime", return_value=snapshot
            ), contextlib.redirect_stdout(io.StringIO()):
                assert runtime_cli.run(args) == 0
        args.command = "health"
        healthy = {"state": "healthy", "upstream_health": {"ok": True}, "gateway_health": {"ok": True}}
        with patch.object(runtime_cli, "_config", return_value=config), patch.object(
            runtime_cli, "inspect_runtime", return_value=healthy
        ), contextlib.redirect_stdout(io.StringIO()):
            assert runtime_cli.run(args) == 0
        for state in ("degraded", "crash_loop", "stopped"):
            unhealthy = {"state": state, "upstream_health": {"ok": False}, "gateway_health": {"ok": False}}
            with patch.object(runtime_cli, "_config", return_value=config), patch.object(
                runtime_cli, "inspect_runtime", return_value=unhealthy
            ), contextlib.redirect_stdout(io.StringIO()):
                assert runtime_cli.run(args) == 2


def test_unresolved_listener_is_fail_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-unresolved-") as raw:
        root = Path(raw)
        upstream_port, gateway_port = free_port(), free_port()
        config = SupervisorConfig(app_root=ROOT, runtime_root=root / "runtime", mode="service-host", upstream_port=upstream_port, gateway_port=gateway_port)
        unresolved = PortListenerSnapshot(upstream_port, (12345,), (), (12345,), False)
        clear = PortListenerSnapshot(gateway_port, (), (), (), False)
        with patch("enterprise.runtime.control.inspect_port_listeners", side_effect=(unresolved, clear)):
            snapshot = inspect_runtime(config)
        assert snapshot["start_disposition"] == "unresolved_port_occupant"
        assert snapshot["upstream_listener"]["unresolved_listener_pids"] == [12345]

        controller = RuntimeController(config)
        with patch("enterprise.runtime.control.inspect_port_listeners", side_effect=(unresolved, clear)), patch(
            "enterprise.runtime.control.subprocess.Popen"
        ) as popen:
            try:
                controller.start()
            except RuntimeStartBlocked:
                pass
            else:
                raise AssertionError("unresolved listener was accepted as a free port")
            popen.assert_not_called()
        with patch("enterprise.runtime.control.inspect_port_listeners", side_effect=(unresolved, clear) * 2):
            stopped = controller.send_command("stop", wait_seconds=0)
        assert stopped["result"] == "unresolved_port_occupant"

        result = type("Netstat", (), {"stdout": "", "returncode": 1})()
        with patch.object(runtime_ownership.subprocess, "run", return_value=result):
            failed = inspect_port_listeners(upstream_port)
        assert failed.inspection_failed is True and failed.listener_pids == ()

        netstat = type("Netstat", (), {"stdout": f"  TCP    0.0.0.0:{upstream_port}    0.0.0.0:0    LISTENING    23456\n", "returncode": 0})()
        with patch.object(runtime_ownership.subprocess, "run", return_value=netstat), patch.object(
            runtime_ownership, "process_identity", return_value=None
        ):
            raw_snapshot = inspect_port_listeners(upstream_port)
        assert raw_snapshot.listener_pids == (23456,)
        assert raw_snapshot.unresolved_listener_pids == (23456,)


def test_stopped_state_requires_full_quiescence() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-stop-race-") as raw:
        root = Path(raw)
        config = SupervisorConfig(app_root=ROOT, runtime_root=root / "runtime", mode="service-host", upstream_port=free_port(), gateway_port=free_port())
        controller = RuntimeController(config)
        identity = process_identity(os.getpid())
        assert identity is not None
        state = initial_state(instance_id="fixture-stop-race", supervisor=identity, mode="service-host")
        state["state"] = "stopped"
        controller.store.write_state(state)
        clear_upstream = PortListenerSnapshot(config.upstream_port, (), (), (), False)
        clear_gateway = PortListenerSnapshot(config.gateway_port, (), (), (), False)
        with patch("enterprise.runtime.control.inspect_port_listeners", side_effect=(clear_upstream, clear_gateway) * 8), patch.object(
            controller.store, "submit_command"
        ) as submit:
            result = controller.send_command("stop", wait_seconds=0)
        assert result["result"] == "stop_in_progress"
        submit.assert_not_called()

        state["supervisor_pid"] = 999999
        state["supervisor_process_created_at"] = 1
        state["supervisor_executable"] = "C:\\missing.exe"
        controller.store.write_state(state)
        with patch("enterprise.runtime.control.inspect_port_listeners", side_effect=(clear_upstream, clear_gateway) * 4):
            completed = controller.send_command("stop", wait_seconds=0)
        assert completed["result"] == "already_stopped"


def test_lock_cleanup_identity_and_early_failure_paths() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-lock-") as raw:
        root = Path(raw)
        runtime_root = root / "runtime"
        supervisor = build_supervisor(runtime_root)
        owner = process_identity(os.getpid())
        assert owner is not None
        assert supervisor.store.reserve_lock(instance_id=supervisor.instance_id, owner=owner)
        with patch.object(supervisor.logs, "write", side_effect=OSError("fixture log failure")):
            assert supervisor.run() == 2
        assert not supervisor.store.lock_path.exists()
        assert not port_identities(supervisor.config.upstream_port)
        assert not port_identities(supervisor.config.gateway_port)

        failing = build_supervisor(runtime_root)
        owner = process_identity(os.getpid())
        assert owner is not None
        assert failing.store.reserve_lock(instance_id=failing.instance_id, owner=owner)
        failing.commands["upstream"] = CommandSpec(
            role="upstream",
            arguments=(str(root / "missing-python.exe"), "-c", "pass"),
            host="127.0.0.1",
            port=failing.config.upstream_port,
        )
        assert failing.run() == 2
        assert not failing.store.lock_path.exists()

        store = RuntimeStateStore(runtime_root)
        stale = ProcessIdentity(pid=999999, created_at=1, executable="C:\\missing.exe")
        assert store.reserve_lock(instance_id="stale-reserved", owner=stale)
        lock = store.read_lock()
        assert lock is not None
        lock["created_at"] = "2000-01-01T00:00:00.000Z"
        lock["updated_at"] = lock["created_at"]
        store.lock_path.write_text(json.dumps(lock), encoding="utf-8")
        controller = RuntimeController(supervisor.config)
        assert controller._clear_stale_if_safe(inspect_runtime(supervisor.config))
        assert not store.lock_path.exists()

        assert store.reserve_lock(instance_id="stale-adopted", owner=stale)
        adopted = store.read_lock()
        assert adopted is not None
        adopted.update(
            {
                "lock_phase": "adopted",
                "supervisor_pid": 999998,
                "supervisor_process_created_at": 1,
                "supervisor_executable": "C:\\missing-supervisor.exe",
                "created_at": "2000-01-01T00:00:00.000Z",
                "updated_at": "2000-01-01T00:00:00.000Z",
            }
        )
        store.lock_path.write_text(json.dumps(adopted), encoding="utf-8")
        assert controller._clear_stale_if_safe(inspect_runtime(supervisor.config))
        assert not store.lock_path.exists()

        identity = process_identity(os.getpid())
        assert identity is not None
        state = initial_state(instance_id="reused", supervisor=identity, mode="service-host")
        state["supervisor_process_created_at"] = identity.created_at + 1
        state["state"] = "starting"
        store.write_state(state)
        snapshot = inspect_runtime(supervisor.config)
        assert snapshot["supervisor_identity_current"] is False
        assert snapshot["start_disposition"] == "stale_runtime_state"

        class ExitedHost:
            def poll(self) -> int:
                return 1

        stopped_snapshot = {"start_disposition": "stopped"}
        startup_snapshot = {"start_disposition": "startup_in_progress", "state": "starting", "runtime_state": None}
        with patch("enterprise.runtime.control.inspect_runtime", side_effect=(stopped_snapshot, startup_snapshot)), patch(
            "enterprise.runtime.control.subprocess.Popen", return_value=ExitedHost()
        ):
            try:
                controller.start(wait_seconds=5)
            except RuntimeControlError:
                pass
            else:
                raise AssertionError("exited service host was accepted")
        assert not store.lock_path.exists()

        timeout_host = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], shell=False)
        startup_snapshots = [stopped_snapshot] + [startup_snapshot] * 30
        try:
            with patch("enterprise.runtime.control.inspect_runtime", side_effect=startup_snapshots), patch(
                "enterprise.runtime.control.subprocess.Popen", return_value=timeout_host
            ):
                try:
                    controller.start(wait_seconds=5)
                except RuntimeControlError:
                    pass
                else:
                    raise AssertionError("startup timeout was accepted")
            assert timeout_host.poll() is not None
            assert not store.lock_path.exists()
        finally:
            if timeout_host.poll() is None:
                timeout_host.kill()
                timeout_host.wait(timeout=5)


def test_redaction_and_windows_identity_declarations() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-redact-") as raw:
        root = Path(raw)
        secret = "fixture-secret-unlabelled"
        logs = RuntimeLogs(root, secret_values=(secret,))
        payload = (
            "Authorization: Bearer bearer-value\\n"
            "Cookie: session=cookie-value\\n"
            "https://example.invalid/a?token=query-token&access_token=access&refresh_token=refresh&signature=sig-value\\n"
            "https://example.invalid/a?X-Amz-Credential=amz-credential-value&X-Amz-Signature=amz-signed-value&X-Amz-Security-Token=amz-security-value\\n"
            '{"credential":"json-credential","auth":"json-auth","session":"json-session"}\\n'
            + secret
        )
        logs.write("supervisor.log", "fixture", traceback=payload)
        logs.crash_event(detail=payload)
        logs.stream_pumps("upstream")[0].write(payload)
        logs.stream_pumps("gateway")[1].write(payload)
        mirrored = io.StringIO()
        upstream_stdout, _ = logs.stream_pumps("upstream")
        with contextlib.redirect_stdout(mirrored):
            pump = StreamPump(io.StringIO(secret + "\n"), upstream_stdout, mirror=True)
            pump.start()
            pump.join()
        assert secret not in mirrored.getvalue()
        assert "[REDACTED]" in mirrored.getvalue()
        state = initial_state(instance_id="redaction", supervisor=process_identity(os.getpid()) or ProcessIdentity(1, 1, "python"), mode="foreground")
        RuntimeStateStore(root).write_state(state)
        combined = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*") if path.is_file())
        for value in (
            "bearer-value",
            "cookie-value",
            "query-token",
            "access",
            "refresh",
            "sig-value",
            "amz-credential-value",
            "amz-signed-value",
            "amz-security-value",
            "json-credential",
            "json-auth",
            "json-session",
            secret,
        ):
            assert value not in combined
        assert "[REDACTED]" in combined
        assert "query-token" not in redact_text("?token=query-token")
    assert process_identity(-1) is None
    if os.name == "nt":
        assert runtime_ownership._kernel32.OpenProcess.argtypes is not None
        assert runtime_ownership._kernel32.WaitForSingleObject.argtypes is not None
        assert runtime_ownership._kernel32.GetProcessTimes.argtypes is not None
        assert runtime_ownership._kernel32.QueryFullProcessImageNameW.argtypes is not None
        assert ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(runtime_ownership.wintypes.HANDLE)
        runtime_ownership.process_identity(4)


def test_cli_config_exact_secret_wiring() -> None:
    """The real CLI config path supplies explicit values only to log redaction."""
    with tempfile.TemporaryDirectory(prefix="ice-stab1-cli-secrets-") as raw:
        root = Path(raw)
        runtime_root = root / "runtime"
        values_path = root / "fixture-values.txt"
        values_path.write_text("stab1-config-jwt-value\nstab1-config-admin-password\n", encoding="utf-8")
        args = _cli_args("start", runtime_root)
        args.upstream_port = free_port()
        args.gateway_port = free_port()
        import enterprise.config as enterprise_config

        with patch.object(enterprise_config, "JWT_SECRET", "stab1-config-jwt-value"), patch.object(
            enterprise_config, "ADMIN_PASSWORD", "stab1-config-admin-password"
        ):
            cli_config = runtime_cli._config(args, mode="service-host")
        assert len(cli_config.secret_values) == 2
        assert "stab1-config" not in repr(cli_config)

        upstream = fixture_spec("upstream", args.upstream_port)
        upstream = replace(upstream, arguments=(*upstream.arguments, "--emit-values-file", str(values_path)))
        gateway = fixture_spec("gateway", args.gateway_port)
        config = replace(cli_config, command_specs={"upstream": upstream, "gateway": gateway})
        supervisor = RuntimeSupervisor(config)
        thread = start_supervisor(supervisor)
        try:
            wait_for(lambda: supervisor.state["state"] == "healthy")
            wait_for(lambda: "[REDACTED]" in (runtime_root / "upstream.stdout.log").read_text(encoding="utf-8"))
            stop_supervisor(supervisor, thread)
        finally:
            if thread.is_alive():
                stop_supervisor(supervisor, thread)

        foreground = RuntimeLogs(root / "foreground", foreground=True, secret_values=cli_config.secret_values)
        mirrored = io.StringIO()
        destination, _ = foreground.stream_pumps("upstream")
        with contextlib.redirect_stdout(mirrored):
            pump = StreamPump(io.StringIO("stab1-config-jwt-value\n"), destination, mirror=True)
            pump.start()
            pump.join()
        assert "stab1-config" not in mirrored.getvalue()
        assert "[REDACTED]" in mirrored.getvalue()

        for path in list(runtime_root.rglob("*")) + list((root / "foreground").rglob("*")):
            if not path.is_file() or path == values_path:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            assert "stab1-config-jwt-value" not in content
            assert "stab1-config-admin-password" not in content


def test_forced_job_termination_and_stop_during_backoff() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-stop-") as raw:
        supervisor = build_supervisor(Path(raw) / "runtime", max_restarts=2, ignore_upstream_stop=True)
        thread = start_supervisor(supervisor)
        wait_for(lambda: supervisor.state["state"] == "healthy")
        request_id = supervisor.store.submit_command(
            command="stop",
            supervisor_instance_id=supervisor.instance_id,
            expected_state_generation=supervisor.state["state_generation"],
        )
        thread.join(timeout=20)
        assert not thread.is_alive()
        ack = supervisor.store.read_ack(request_id, instance_id=supervisor.instance_id)
        assert ack is not None and ack["job_termination_required"] is True
        assert ack["owned_pid_release_complete"] is True
        assert any(item["result"] == "graceful_timeout" for item in ack["child_stop_results"])
        assert not pid_exists(ack["upstream_before_pid"])


def test_instance_bound_command_acknowledgements() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-ack-") as raw:
        supervisor = build_supervisor(Path(raw) / "runtime")
        thread = start_supervisor(supervisor)
        try:
            wait_for(lambda: supervisor.state["state"] == "healthy")
            generation = supervisor.state["state_generation"]
            upstream_pid = supervisor.roles["upstream"].process.process.pid  # type: ignore[union-attr]
            rejected_request = supervisor.store.submit_command(
                command="restart",
                supervisor_instance_id=supervisor.instance_id,
                expected_state_generation=generation - 1,
            )
            wait_for(
                lambda: supervisor.store.read_ack(rejected_request, instance_id=supervisor.instance_id) is not None,
                message="stale command acknowledgement was not written",
            )
            rejected = supervisor.store.read_ack(rejected_request, instance_id=supervisor.instance_id)
            assert rejected is not None and rejected["result"] == "rejected_stale_generation"
            assert supervisor.roles["upstream"].process is not None
            assert supervisor.roles["upstream"].process.process.pid == upstream_pid

            current_generation = supervisor.state["state_generation"]
            accepted_request = supervisor.store.submit_command(
                command="restart",
                supervisor_instance_id=supervisor.instance_id,
                expected_state_generation=current_generation,
            )
            wait_for(
                lambda: (supervisor.store.read_ack(accepted_request, instance_id=supervisor.instance_id) or {}).get("result")
                == "restarted",
                seconds=15,
                message="current-generation restart acknowledgement was not written",
            )
            accepted = supervisor.store.read_ack(accepted_request, instance_id=supervisor.instance_id)
            assert accepted is not None
            assert accepted["upstream_before_pid"] == upstream_pid
            assert accepted["upstream_after_pid"] != upstream_pid
        finally:
            if thread.is_alive():
                stop_supervisor(supervisor, thread)


def test_stop_during_startup_backoff_and_crash_loop() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-stab1-stop-startup-") as raw:
        supervisor = build_supervisor(Path(raw) / "runtime")
        thread = start_supervisor(supervisor)
        wait_for(lambda: supervisor.roles["upstream"].process is not None, message="upstream did not begin startup")
        # A real controller only submits an instance-bound command after the
        # supervisor has atomically published its current state generation.
        wait_for(
            lambda: supervisor.state["state"] == "starting" and supervisor.state["state_generation"] >= 1,
            message="startup state was not published",
        )
        stop_supervisor(supervisor, thread)
        assert supervisor.state["state"] == "stopped"
        assert not tcp_check("127.0.0.1", supervisor.config.upstream_port).ok

    with tempfile.TemporaryDirectory(prefix="ice-stab1-stop-backoff-") as raw:
        supervisor = build_supervisor(Path(raw) / "runtime")
        thread = start_supervisor(supervisor)
        wait_for(lambda: supervisor.state["state"] == "healthy")
        managed = supervisor.roles["upstream"].process
        assert managed is not None
        managed.process.kill()
        wait_for(lambda: supervisor.roles["upstream"].state == "restarting", message="upstream did not enter backoff")
        stop_supervisor(supervisor, thread)
        time.sleep(1.2)
        assert supervisor.roles["upstream"].process is None
        assert supervisor.state["state"] == "stopped"

    with tempfile.TemporaryDirectory(prefix="ice-stab1-stop-crash-") as raw:
        supervisor = build_supervisor(Path(raw) / "runtime", max_restarts=1)
        thread = start_supervisor(supervisor)
        wait_for(lambda: supervisor.state["state"] == "healthy")
        managed = supervisor.roles["upstream"].process
        assert managed is not None
        managed.process.kill()
        wait_for(lambda: supervisor.roles["upstream"].state == "crash_loop", message="upstream did not enter crash loop")
        stop_supervisor(supervisor, thread)
        assert supervisor.state["state"] == "stopped"
        assert not tcp_check("127.0.0.1", supervisor.config.gateway_port).ok


def test_real_cli_lifecycle_and_acknowledgements() -> None:
    """Exercise actual lifecycle CLI calls across two short-lived sessions."""
    with tempfile.TemporaryDirectory(prefix="ice-stab1-cli-") as raw:
        runtime_root = Path(raw) / "runtime"
        upstream_port = free_port()
        gateway_port = free_port()
        report_path = Path(raw) / "lifecycle-report.json"
        worker = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--cli-phase-worker",
                "--runtime-root",
                str(runtime_root),
                "--upstream-port",
                str(upstream_port),
                "--gateway-port",
                str(gateway_port),
                "--report-path",
                str(report_path),
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_worker_flags(),
            close_fds=True,
            shell=False,
        )
        worker.wait(timeout=60)
        if worker.returncode != 0:
            failure = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
            raise AssertionError(f"CLI lifecycle phase worker failed: {failure.get('phase', 'unreported')}")
        wait_for(lambda: report_path.is_file(), seconds=60, message="CLI lifecycle stop worker produced no report")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report == {"result": "pass"}, "CLI lifecycle worker failed"
        assert not tcp_check("127.0.0.1", upstream_port).ok
        assert not tcp_check("127.0.0.1", gateway_port).ok
        assert not (runtime_root / "runtime-supervisor.lock").exists()
        assert not list((runtime_root / "control").glob("cmd-*.json"))
        assert not list((runtime_root / "control").glob("ack-*.json"))


CASES = {
    "role-isolation": test_role_isolation_and_stop,
    "crash-loop": test_crash_loop_and_explicit_stop,
    "logging-state": test_logs_state_rotation_and_secret_redaction,
    "start-gate": test_start_gate_and_atomic_state,
    "static-boundary": test_static_runtime_boundary,
    "cli-exit-codes": test_cli_exit_code_contract,
    "unresolved-listener": test_unresolved_listener_is_fail_closed,
    "stop-race": test_stopped_state_requires_full_quiescence,
    "lock-lifecycle": test_lock_cleanup_identity_and_early_failure_paths,
    "redaction": test_redaction_and_windows_identity_declarations,
    "cli-secret-wiring": test_cli_config_exact_secret_wiring,
    "forced-stop": test_forced_job_termination_and_stop_during_backoff,
    "command-ack": test_instance_bound_command_acknowledgements,
    "stop-transitions": test_stop_during_startup_backoff_and_crash_loop,
    "cli-lifecycle": test_real_cli_lifecycle_and_acknowledgements,
    "windows-smoke": lambda: test_windows_process_smoke(),
    "detached-host": lambda: test_detached_service_host_lifecycle(),
    "dependency-manifest": lambda: test_auth_jwt_dependency_is_declared(),
}


def test_windows_process_smoke() -> None:
    """One real Job Object smoke covers the role/recovery/log lifecycle together."""
    with tempfile.TemporaryDirectory(prefix="ice-stab1-smoke-") as raw:
        root = Path(raw) / "runtime"
        supervisor = build_supervisor(root, max_restarts=5, emit_secret=True)
        thread = start_supervisor(supervisor)
        wait_for(lambda: supervisor.state["state"] == "healthy")
        wait_for(lambda: "[REDACTED]" in (root / "upstream.stdout.log").read_text(encoding="utf-8"))
        assert "fixture-marker" not in (root / "upstream.stdout.log").read_text(encoding="utf-8")

        upstream_pid = supervisor.roles["upstream"].process.process.pid  # type: ignore[union-attr]
        gateway_pid = supervisor.roles["gateway"].process.process.pid  # type: ignore[union-attr]
        supervisor.fixture_upstream_down_file.write_text("down", encoding="utf-8")  # type: ignore[attr-defined]
        supervisor.roles["upstream"].process.process.kill()  # type: ignore[union-attr]
        wait_for(lambda: supervisor.roles["gateway"].health == "upstream_unavailable")
        wait_for(
            lambda: supervisor.roles["upstream"].process is not None
            and supervisor.roles["upstream"].process.process.pid != upstream_pid
            and supervisor.roles["upstream"].state == "healthy"
        )
        assert supervisor.roles["gateway"].process.process.pid == gateway_pid  # type: ignore[union-attr]
        supervisor.fixture_upstream_down_file.unlink()  # type: ignore[attr-defined]
        wait_for(lambda: supervisor.roles["gateway"].state == "healthy")

        supervisor.roles["gateway"].process.process.kill()  # type: ignore[union-attr]
        wait_for(
            lambda: supervisor.roles["gateway"].process is not None
            and supervisor.roles["gateway"].process.process.pid != gateway_pid
            and supervisor.roles["gateway"].state == "healthy"
        )
        stable_upstream_pid = supervisor.roles["upstream"].process.process.pid  # type: ignore[union-attr]
        assert stable_upstream_pid != upstream_pid

        # One prior upstream restart already occurred. Four further crashes hit
        # the five-event role-local limit without affecting the gateway role.
        for attempt in range(4):
            managed = supervisor.roles["upstream"].process
            assert managed is not None
            previous_pid = managed.process.pid
            managed.process.kill()
            wait_for(
                lambda: supervisor.roles["upstream"].state in {"restarting", "crash_loop"},
                seconds=5,
                message="upstream exit was not observed",
            )
            if attempt == 3:
                wait_for(lambda: supervisor.roles["upstream"].state == "crash_loop", seconds=8)
            else:
                wait_for(
                    lambda: supervisor.roles["upstream"].process is not None
                    and supervisor.roles["upstream"].process.process.pid != previous_pid
                    and supervisor.roles["upstream"].state == "healthy",
                    seconds=8,
                )
        assert supervisor.roles["gateway"].process is not None
        supervisor.store.submit_command(
            command="restart",
            supervisor_instance_id=supervisor.instance_id,
            expected_state_generation=supervisor.state["state_generation"],
        )
        wait_for(lambda: supervisor.state["state"] == "healthy", seconds=12)

        rotating = RotatingTextLog(root / "rotation.log", max_bytes=64 * 1024, backups=2)
        rotating.write("x" * (64 * 1024))
        rotating.write("y")
        assert (root / "rotation.log.1").exists()
        final_upstream = supervisor.roles["upstream"].process.process.pid  # type: ignore[union-attr]
        final_gateway = supervisor.roles["gateway"].process.process.pid  # type: ignore[union-attr]
        stop_supervisor(supervisor, thread)
        assert not pid_exists(final_upstream)
        assert not pid_exists(final_gateway)
        assert supervisor.state["state"] == "stopped"
        assert not (root / "runtime-supervisor.lock").exists()


def test_detached_service_host_lifecycle() -> None:
    """The short-lived launcher process is not the Job Object owner."""
    with tempfile.TemporaryDirectory(prefix="ice-stab1-host-") as raw:
        root = Path(raw) / "runtime"
        upstream_port = free_port()
        gateway_port = free_port()
        arguments = [
            sys.executable,
            str(ROOT / "enterprise" / "tests" / "runtime_fixture_host.py"),
            "--runtime-root",
            str(root),
            "--upstream-port",
            str(upstream_port),
            "--gateway-port",
            str(gateway_port),
        ]
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        host = subprocess.Popen(
            arguments,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
            shell=False,
        )
        try:
            store = RuntimeStateStore(root)
            wait_for(lambda: (store.read_state() or {}).get("state") == "healthy", seconds=15)
            state = store.read_state()
            assert state is not None and host.poll() is None
            upstream_pid = state["upstream"]["pid"]
            gateway_pid = state["gateway"]["pid"]
            assert pid_exists(upstream_pid) and pid_exists(gateway_pid)
            # The launching test continues after the detached host has taken
            # ownership; no input(), browser, or foreground window is involved.
            store.submit_command(
                command="stop",
                supervisor_instance_id=state["supervisor_instance_id"],
                expected_state_generation=state["state_generation"],
            )
            host.wait(timeout=15)
            assert tcp_check("127.0.0.1", upstream_port).ok is False
            assert tcp_check("127.0.0.1", gateway_port).ok is False
            assert not pid_exists(upstream_pid) and not pid_exists(gateway_pid)
        finally:
            if host.poll() is None:
                host.kill()
                host.wait(timeout=5)


def test_auth_jwt_dependency_is_declared() -> None:
    """The enterprise gateway's direct JWT import must be installable from the manifest."""
    auth_source = (ROOT / "enterprise" / "auth.py").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    declared = {line.strip().split("=", 1)[0].split("[", 1)[0].casefold() for line in requirements if line.strip()}
    assert "import jwt" in auth_source
    assert "pyjwt" in declared


def run_all() -> None:
    test_auth_jwt_dependency_is_declared()
    test_windows_process_smoke()
    test_start_gate_and_atomic_state()
    test_static_runtime_boundary()
    test_cli_exit_code_contract()
    test_unresolved_listener_is_fail_closed()
    test_stopped_state_requires_full_quiescence()
    test_lock_cleanup_identity_and_early_failure_paths()
    test_redaction_and_windows_identity_declarations()
    test_cli_config_exact_secret_wiring()
    test_forced_job_termination_and_stop_during_backoff()
    test_instance_bound_command_acknowledgements()
    test_stop_during_startup_backoff_and_crash_loop()
    test_real_cli_lifecycle_and_acknowledgements()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=tuple(CASES))
    parser.add_argument("--cli-phase-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cli-stop-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--runtime-root", help=argparse.SUPPRESS)
    parser.add_argument("--upstream-port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--gateway-port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--report-path", help=argparse.SUPPRESS)
    parser.add_argument("--phase-worker-pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--phase-worker-created-at", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--phase-worker-executable", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.cli_phase_worker:
        if not all((arguments.runtime_root, arguments.upstream_port, arguments.gateway_port, arguments.report_path)):
            raise SystemExit(2)
        raise SystemExit(
            _run_cli_lifecycle_phase_worker(
                runtime_root=Path(arguments.runtime_root),
                upstream_port=arguments.upstream_port,
                gateway_port=arguments.gateway_port,
                report_path=Path(arguments.report_path),
            )
        )
    if arguments.cli_stop_worker:
        if not all(
            (
                arguments.runtime_root,
                arguments.upstream_port,
                arguments.gateway_port,
                arguments.report_path,
                arguments.phase_worker_pid,
                arguments.phase_worker_created_at,
                arguments.phase_worker_executable,
            )
        ):
            raise SystemExit(2)
        raise SystemExit(
            _run_cli_lifecycle_stop_worker(
                runtime_root=Path(arguments.runtime_root),
                upstream_port=arguments.upstream_port,
                gateway_port=arguments.gateway_port,
                report_path=Path(arguments.report_path),
                phase_worker_identity=ProcessIdentity(
                    pid=arguments.phase_worker_pid,
                    created_at=arguments.phase_worker_created_at,
                    executable=arguments.phase_worker_executable,
                ),
            )
        )
    if arguments.case:
        CASES[arguments.case]()
    else:
        run_all()
    print("STAB-1 supervisor and persistent logging checks passed")
