from __future__ import annotations

import os
from pathlib import Path

import pytest

from enterprise.runtime.control import RuntimeController
from enterprise.runtime.ownership import PortListenerSnapshot, ProcessIdentity
from enterprise.runtime.preflight import StartupPreflightResult
from enterprise.runtime.process import default_commands
from enterprise.runtime.readiness import classify_portable_readiness
from enterprise.runtime.state import RuntimeStateStore, initial_state
from enterprise.runtime.supervisor import RuntimeStartBlocked, SupervisorConfig


def _preflight() -> StartupPreflightResult:
    return StartupPreflightResult(
        result="pass",
        mode="portable-release",
        release_id="release-A",
        app_root_relative="releases/release-A",
        path_roots_identity="a" * 64,
        current_release_sha256="b" * 64,
        runtime_manifest_sha256="c" * 64,
        python_executable_sha256="d" * 64,
        python_implementation="CPython",
        python_version="3.10.11",
        python_abi="cp310",
        architecture="x64",
        bytecode_policy="disabled-no-user-site",
        writable_roots_verified=("DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"),
    )


def _identity(context_identity: str) -> dict[str, str]:
    return {
        "runtime_mode": "portable-release",
        "release_id": "release-A",
        "runtime_manifest_sha256": "c" * 64,
        "startup_preflight_sha256": _preflight().identity,
        "launch_context_identity": context_identity,
    }


def _portable_config(tmp_path: Path) -> SupervisorConfig:
    preflight = _preflight()
    return SupervisorConfig(
        app_root=tmp_path / "install" / "releases" / "release-A",
        runtime_root=tmp_path / "runtime",
        log_root=tmp_path / "logs",
        mode="service-host",
        runtime_mode="portable-release",
        release_id="release-A",
        runtime_manifest_sha256=preflight.runtime_manifest_sha256,
        startup_preflight_sha256=preflight.identity,
        python_executable=str(tmp_path / "install" / "releases" / "release-A" / "python" / "python.exe"),
    )


def _controller_snapshot(
    *, ownership: bool = True, mismatch: bool = False, ready: bool = True, generation: int = 1
) -> dict[str, object]:
    return {
        "state": "healthy",
        "start_disposition": "complete_healthy_instance",
        "runtime_state": {"supervisor_instance_id": "a" * 32, "state_generation": generation},
        "supervisor_identity_current": True,
        "portable_ownership_valid": ownership,
        "running_release_mismatch": mismatch,
        "launch_context_identity": "b" * 64,
        "readiness": {"ready": ready},
    }


def test_existing_lock_reservation_and_adoption_carry_one_portable_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RuntimeStateStore(tmp_path / "runtime")
    owner = ProcessIdentity(100, 200, "python.exe")
    supervisor = ProcessIdentity(101, 201, "python.exe")
    identity = _identity("e" * 64)
    assert store.reserve_lock(instance_id="f" * 32, owner=owner, runtime_identity=identity)
    lock = store.read_lock()
    assert lock is not None and all(lock[name] == value for name, value in identity.items())
    monkeypatch.setattr("enterprise.runtime.state.process_identity", lambda pid: owner if pid == owner.pid else supervisor)
    assert not store.adopt_lock(
        instance_id="f" * 32,
        owner=owner,
        supervisor=supervisor,
        expected_runtime_identity={**identity, "release_id": "release-B"},
    )
    assert store.adopt_lock(
        instance_id="f" * 32,
        owner=owner,
        supervisor=supervisor,
        expected_runtime_identity=identity,
    )
    assert store.read_lock()["lock_phase"] == "adopted"


def test_runtime_state_splits_runtime_mode_from_host_style() -> None:
    supervisor = ProcessIdentity(1, 2, "python.exe")
    state = initial_state(
        instance_id="a" * 32,
        supervisor=supervisor,
        mode="service-host",
        runtime_mode="portable-release",
        runtime_identity=_identity("e" * 64),
    )
    assert state["runtime_mode"] == "portable-release"
    assert state["host_style"] == "service-host"
    assert state["mode"] == "service-host"
    assert state["launch_context_identity"] == "e" * 64


def test_portable_control_document_is_context_bound(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path / "runtime")
    request_id = store.submit_command(
        command="stop",
        supervisor_instance_id="a" * 32,
        expected_state_generation=1,
        launch_context_identity="b" * 64,
    )
    assert request_id
    assert store.consume_commands(
        "a" * 32,
        expected_launch_context_identity="c" * 64,
    ) == []
    # A mismatched request is consumed and discarded, never replayed under a
    # later instance/context.
    assert store.consume_commands(
        "a" * 32,
        expected_launch_context_identity="b" * 64,
    ) == []


def test_portable_child_commands_require_fixed_python_and_context(tmp_path: Path) -> None:
    app = tmp_path / "release"
    commands = default_commands(
        app,
        upstream_port=3001,
        gateway_port=8000,
        python_executable=str(app / "python" / "python.exe"),
        runtime_mode="portable-release",
        runtime_root=tmp_path / "runtime",
        instance_id="a" * 32,
        launch_context_identity="b" * 64,
    )
    for command in commands.values():
        assert command.arguments[:3] == (str(app / "python" / "python.exe"), "-I", "-B")
        assert "--runtime-mode" in command.arguments
        assert "--launch-context-identity" in command.arguments
        assert "-m" not in command.arguments
    with pytest.raises(Exception):
        default_commands(app, upstream_port=3001, gateway_port=8000, runtime_mode="portable-release")


def test_portable_start_reserves_then_publishes_context_then_starts_existing_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "install" / "releases" / "release-A"
    host = app / "enterprise" / "runtime" / "host.py"
    host.parent.mkdir(parents=True)
    host.write_text("# fixture\n", encoding="utf-8")
    runtime = tmp_path / "runtime"
    python = app / "python" / "python.exe"
    python.parent.mkdir()
    python.write_bytes(b"fixture")
    preflight = _preflight()
    config = SupervisorConfig(
        app_root=app,
        runtime_root=runtime,
        log_root=tmp_path / "logs",
        mode="service-host",
        runtime_mode="portable-release",
        release_id="release-A",
        runtime_manifest_sha256=preflight.runtime_manifest_sha256,
        startup_preflight_sha256=preflight.identity,
        python_executable=str(python),
    )
    controller = RuntimeController(config)
    events: list[str] = []
    real_reserve = controller.store.reserve_lock

    class FixedUUID:
        hex = "a" * 32

    def create_instance():
        events.append("instance")
        return FixedUUID()

    monkeypatch.setattr("enterprise.runtime.control.uuid.uuid4", create_instance)

    def reserve(**kwargs):
        events.append("reserve")
        return real_reserve(**kwargs)

    controller.store.reserve_lock = reserve  # type: ignore[method-assign]
    monkeypatch.setattr("enterprise.runtime.control.process_identity", lambda _pid: ProcessIdentity(os.getpid(), 1, str(python)))
    monkeypatch.setattr("enterprise.runtime.control.publish_launch_context", lambda *a, **k: events.append("publish"))

    def inspect(_config):
        events.append("inspect")
        lock = controller.store.read_lock()
        if not lock:
            return {"state": "stopped", "start_disposition": "stopped", "runtime_state": None, "lock": None}
        return {
            "state": "healthy",
            "start_disposition": "complete_healthy_instance",
            "runtime_state": {"supervisor_instance_id": lock["supervisor_instance_id"]},
            "lock": lock,
            "supervisor_identity_current": True,
            "readiness": {"ready": True},
        }

    monkeypatch.setattr("enterprise.runtime.control.inspect_runtime", inspect)

    class Host:
        pid = 999

        def poll(self):
            return None

    def popen(*args, **kwargs):
        events.append("host")
        return Host()

    monkeypatch.setattr("enterprise.runtime.control.subprocess.Popen", popen)
    result = controller.start(preflight=preflight, wait_seconds=1)
    assert result["result"] == "started"
    assert events == ["instance", "inspect", "reserve", "publish", "host", "inspect"]


@pytest.mark.parametrize(
    "snapshot",
    (
        _controller_snapshot(ownership=False),
        _controller_snapshot(ready=False),
        _controller_snapshot(mismatch=True),
    ),
)
def test_portable_start_fast_path_requires_ownership_readiness_and_current_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, object],
) -> None:
    controller = RuntimeController(_portable_config(tmp_path))
    monkeypatch.setattr("enterprise.runtime.control.inspect_runtime", lambda _config: snapshot)
    with pytest.raises(RuntimeStartBlocked):
        controller.start(preflight=_preflight())


def test_portable_command_rechecks_ownership_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = RuntimeController(_portable_config(tmp_path))
    snapshots = iter((_controller_snapshot(), _controller_snapshot(ownership=False)))
    monkeypatch.setattr("enterprise.runtime.control.inspect_runtime", lambda _config: next(snapshots))
    submitted: list[str] = []
    monkeypatch.setattr(controller.store, "submit_command", lambda **_kwargs: submitted.append("written") or "request")
    result = controller.send_command("stop", wait_seconds=0)
    assert result["result"] == "ownership_unavailable"
    assert submitted == []


def test_old_owned_release_stop_is_allowed_but_restart_is_blocked_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = RuntimeController(_portable_config(tmp_path))
    old = _controller_snapshot(mismatch=True)
    monkeypatch.setattr("enterprise.runtime.control.inspect_runtime", lambda _config: old)
    submitted: list[str] = []

    def submit(**_kwargs):
        submitted.append("written")
        return "request"

    monkeypatch.setattr(controller.store, "submit_command", submit)
    assert controller.send_command("stop", wait_seconds=0)["result"] == "control_timeout"
    assert submitted == ["written"]
    submitted.clear()
    assert controller.send_command("restart", wait_seconds=0)["result"] == "release_mismatch"
    assert submitted == []


def test_portable_restart_ack_requires_final_ownership_readiness_and_release_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = RuntimeController(_portable_config(tmp_path))
    snapshots = iter((_controller_snapshot(), _controller_snapshot(), _controller_snapshot(ready=False)))
    monkeypatch.setattr("enterprise.runtime.control.inspect_runtime", lambda _config: next(snapshots))
    monkeypatch.setattr(controller.store, "submit_command", lambda **_kwargs: "request")
    monkeypatch.setattr(
        controller.store,
        "read_ack",
        lambda *_args, **_kwargs: {"result": "restarted", "launch_context_identity": "b" * 64},
    )
    result = controller.send_command("restart", wait_seconds=1)
    assert result["result"] == "ownership_unavailable"


def test_context_publish_failure_before_replace_does_not_reread_or_start_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from enterprise.runtime.error_contract import RuntimeContractError

    controller = RuntimeController(_portable_config(tmp_path))
    monkeypatch.setattr("enterprise.runtime.control.inspect_runtime", lambda _config: {"start_disposition": "stopped"})
    monkeypatch.setattr(
        "enterprise.runtime.control.process_identity",
        lambda _pid: ProcessIdentity(os.getpid(), 1, str(controller.config.python_executable)),
    )
    monkeypatch.setattr(
        "enterprise.runtime.control.publish_launch_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeContractError("LAUNCH_CONTEXT_WRITE_FAILED")),
    )
    monkeypatch.setattr(
        "enterprise.runtime.control.read_launch_context",
        lambda *_args, **_kwargs: pytest.fail("pre-replace failure must not reread target"),
    )
    monkeypatch.setattr(
        "enterprise.runtime.control.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("host must not start"),
    )
    with pytest.raises(RuntimeContractError) as exc:
        controller.start(preflight=_preflight())
    assert exc.value.code == "LAUNCH_CONTEXT_WRITE_FAILED"
    assert controller.store.read_lock() is None


@pytest.mark.parametrize("reread_matches", (True, False))
def test_context_post_replace_sync_failure_rereads_without_rollback_or_host_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reread_matches: bool,
) -> None:
    from enterprise.runtime.error_contract import RuntimeContractError
    from enterprise.runtime.launch_context import build_launch_context, read_launch_context

    controller = RuntimeController(_portable_config(tmp_path))
    monkeypatch.setattr("enterprise.runtime.control.inspect_runtime", lambda _config: {"start_disposition": "stopped"})
    monkeypatch.setattr(
        "enterprise.runtime.control.process_identity",
        lambda _pid: ProcessIdentity(os.getpid(), 1, str(controller.config.python_executable)),
    )
    published: list[str] = []

    def publish(target: Path, context, **_kwargs):
        target.parent.mkdir(parents=True, exist_ok=True)
        replacement = context if reread_matches else build_launch_context(_preflight(), instance_id="f" * 32)
        target.write_bytes(replacement.canonical_json())
        published.append(replacement.identity)
        raise RuntimeContractError("LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED")

    reread: list[str] = []

    def inspect_target(target: Path):
        context = read_launch_context(target)
        reread.append(context.identity)
        return context

    monkeypatch.setattr("enterprise.runtime.control.publish_launch_context", publish)
    monkeypatch.setattr("enterprise.runtime.control.read_launch_context", inspect_target)
    monkeypatch.setattr(
        "enterprise.runtime.control.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("host must not start after uncertain context publish"),
    )
    with pytest.raises(RuntimeContractError) as exc:
        controller.start(preflight=_preflight())
    assert exc.value.code == "LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED"
    assert exc.value.payload.pointer_or_context_may_have_changed is True
    assert exc.value.payload.reread_state_required is True
    assert reread == published
    assert (controller.config.runtime_root / "launch-context.json").is_file()
    assert controller.store.read_lock() is None


def test_readiness_requires_all_six_independent_fields() -> None:
    ready = classify_portable_readiness(
        process_alive=True,
        role_health=True,
        instance_health=True,
        startup_ready=True,
        release_match=True,
        runtime_trust_ready=True,
    )
    assert ready.ready is True
    for field in (
        "process_alive", "role_health", "instance_health", "startup_ready", "release_match", "runtime_trust_ready"
    ):
        values = {name: True for name in ready.snapshot() if name != "ready"}
        values[field] = False
        assert classify_portable_readiness(**values).ready is False


def _portable_ownership_case(tmp_path: Path):
    from enterprise.runtime.control import _portable_identity_snapshot
    from enterprise.runtime.launch_context import build_launch_context, publish_launch_context

    preflight = _preflight()
    context = build_launch_context(preflight, instance_id="a" * 32)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    publish_launch_context(runtime / "launch-context.json", context, expected_existing_identity=None)
    python = tmp_path / "install" / "releases" / "release-A" / "python" / "python.exe"
    supervisor = ProcessIdentity(10, 100, str(python))
    upstream = ProcessIdentity(11, 101, str(python))
    gateway = ProcessIdentity(12, 102, str(python))
    identity = {
        "runtime_mode": "portable-release",
        "release_id": "release-A",
        "runtime_manifest_sha256": preflight.runtime_manifest_sha256,
        "startup_preflight_sha256": preflight.identity,
        "launch_context_identity": context.identity,
    }
    state = {
        **identity,
        "supervisor_instance_id": context.instance_id,
        "supervisor_pid": supervisor.pid,
        "supervisor_process_created_at": supervisor.created_at,
        "supervisor_executable": supervisor.executable,
        "state": "healthy",
        "upstream": {"pid": upstream.pid, "process_created_at": upstream.created_at, "executable": upstream.executable},
        "gateway": {"pid": gateway.pid, "process_created_at": gateway.created_at, "executable": gateway.executable},
    }
    lock = {
        **identity,
        "supervisor_instance_id": context.instance_id,
        "supervisor_pid": supervisor.pid,
        "supervisor_process_created_at": supervisor.created_at,
        "supervisor_executable": supervisor.executable,
        "lock_phase": "adopted",
    }
    snapshot = {
        "runtime_state": state,
        "lock": lock,
        "supervisor_identity_current": True,
        "owned_child_current": True,
        "upstream_health": {"ok": True},
        "gateway_health": {"ok": True},
    }
    config = SupervisorConfig(
        app_root=tmp_path / "install" / "releases" / "release-A",
        runtime_root=runtime,
        mode="service-host",
        runtime_mode="portable-release",
        release_id="release-A",
        runtime_manifest_sha256=preflight.runtime_manifest_sha256,
        startup_preflight_sha256=preflight.identity,
        python_executable=str(python),
    )
    upstream_ports = PortListenerSnapshot(3001, (11,), (upstream,), ())
    gateway_ports = PortListenerSnapshot(8000, (12,), (gateway,), ())
    return config, snapshot, upstream_ports, gateway_ports, supervisor


def test_portable_identity_snapshot_binds_context_lock_state_processes_and_listeners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from enterprise.runtime.control import _portable_identity_snapshot

    config, snapshot, upstream_ports, gateway_ports, supervisor = _portable_ownership_case(tmp_path)
    monkeypatch.setattr(
        "enterprise.runtime.control.process_identity",
        lambda pid: supervisor if pid == supervisor.pid else None,
    )
    result = _portable_identity_snapshot(config, snapshot, upstream_ports, gateway_ports)
    assert result["portable_ownership_valid"] is True
    assert result["running_release_mismatch"] is False
    assert result["readiness"]["ready"] is True
    snapshot["runtime_state"]["launch_context_identity"] = "f" * 64
    result = _portable_identity_snapshot(config, snapshot, upstream_ports, gateway_ports)
    assert result["portable_ownership_valid"] is False
    assert result["readiness"]["ready"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("supervisor_pid", None),
        ("supervisor_pid", 999),
        ("supervisor_process_created_at", 999),
        ("supervisor_executable", "other-python.exe"),
    ),
)
def test_portable_ownership_rejects_missing_or_mismatched_lock_supervisor_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    from enterprise.runtime.control import _portable_identity_snapshot

    config, snapshot, upstream_ports, gateway_ports, supervisor = _portable_ownership_case(tmp_path)
    monkeypatch.setattr(
        "enterprise.runtime.control.process_identity",
        lambda pid: supervisor if pid == supervisor.pid else None,
    )
    snapshot["lock"][field] = value
    result = _portable_identity_snapshot(config, snapshot, upstream_ports, gateway_ports)
    assert result["portable_ownership_valid"] is False
    assert result["readiness"]["ready"] is False


def test_host_and_child_gate_portable_identity_before_application_import() -> None:
    root = Path(__file__).resolve().parents[2]
    host = (root / "enterprise" / "runtime" / "host.py").read_text(encoding="utf-8")
    child = (root / "enterprise" / "runtime" / "child.py").read_text(encoding="utf-8")
    assert host.index("validate_portable_process_binding") < host.index("from enterprise.runtime.cli import main")
    assert child.index("validate_portable_process_binding") < child.index("import uvicorn")
