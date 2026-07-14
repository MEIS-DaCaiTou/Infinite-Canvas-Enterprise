"""STAB-1 runtime supervision tests using only temporary fixture processes.

Run from the repository root:

    python .\\enterprise\\tests\\test_stab_1_supervisor_logging.py
"""

from __future__ import annotations

import json
import argparse
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enterprise.runtime.control import inspect_runtime, validate_runtime_root
from enterprise.runtime.health import tcp_check
from enterprise.runtime.logging import RotatingTextLog
from enterprise.runtime.ownership import pid_exists
from enterprise.runtime.process import CommandSpec, exit_code_snapshot
from enterprise.runtime.state import RuntimeStateStore, initial_state
from enterprise.runtime.supervisor import RuntimeSupervisor, SupervisorConfig


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fixture_spec(role: str, port: int, *, emit_secret: bool = False, upstream_down_file: Path | None = None) -> CommandSpec:
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
    return CommandSpec(role=role, arguments=tuple(arguments), host="127.0.0.1", port=port)


def build_supervisor(runtime_root: Path, *, max_restarts: int = 5, emit_secret: bool = False) -> RuntimeSupervisor:
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
            "upstream": fixture_spec("upstream", upstream_port, emit_secret=emit_secret),
            "gateway": fixture_spec("gateway", gateway_port, upstream_down_file=upstream_down_file),
        },
    )
    supervisor = RuntimeSupervisor(config)
    supervisor.fixture_upstream_down_file = upstream_down_file  # type: ignore[attr-defined]
    return supervisor


def start_supervisor(supervisor: RuntimeSupervisor) -> threading.Thread:
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
    supervisor.store.submit_command(command="stop", supervisor_instance_id=supervisor.instance_id)
    thread.join(timeout=15)
    assert not thread.is_alive(), "supervisor did not stop"


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
        supervisor.store.submit_command(command="restart", supervisor_instance_id=supervisor.instance_id)
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
        state = initial_state(instance_id="fixture", supervisor_pid=999999, mode="service-host")
        state["state"] = "stopped"
        store.write_state(state)
        assert store.read_state() == state
        assert not list(runtime_root.glob("*.tmp"))

        port = free_port()
        foreign = subprocess.Popen([sys.executable, str(ROOT / "enterprise" / "tests" / "runtime_fixture_service.py"), "--role", "upstream", "--port", str(port)])
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
            foreign.terminate()
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
    foreground_script = (ROOT / "启动企业版前台.bat").read_text(encoding="utf-8")
    for script in (stop_script, start_script, foreground_script):
        assert "enterprise.runtime.cli" in script
    assert "taskkill" not in stop_script.lower()


CASES = {
    "role-isolation": test_role_isolation_and_stop,
    "crash-loop": test_crash_loop_and_explicit_stop,
    "logging-state": test_logs_state_rotation_and_secret_redaction,
    "start-gate": test_start_gate_and_atomic_state,
    "static-boundary": test_static_runtime_boundary,
    "detached-host": lambda: test_detached_service_host_lifecycle(),
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
        supervisor.store.submit_command(command="restart", supervisor_instance_id=supervisor.instance_id)
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
            store.submit_command(command="stop", supervisor_instance_id=state["supervisor_instance_id"])
            host.wait(timeout=15)
            assert tcp_check("127.0.0.1", upstream_port).ok is False
            assert tcp_check("127.0.0.1", gateway_port).ok is False
            assert not pid_exists(upstream_pid) and not pid_exists(gateway_pid)
        finally:
            if host.poll() is None:
                host.kill()
                host.wait(timeout=5)


def run_all() -> None:
    test_windows_process_smoke()
    test_start_gate_and_atomic_state()
    test_static_runtime_boundary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=tuple(CASES))
    arguments = parser.parse_args()
    if arguments.case:
        CASES[arguments.case]()
    else:
        run_all()
    print("STAB-1 supervisor and persistent logging checks passed")
