"""Recover an owned half-alive customer Runtime and execute one prepared update.

This is a narrow recovery entry point for the 2026.08.5 customer baseline.  It
does not terminate a process directly and it never removes a lock.  It proves
the retained portable identities, sends the existing Supervisor control
command through the runtime control directory, waits for quiescence, and only
then executes the already prepared UPDATE-MVP-1 job.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


SOURCE_RELEASE_ID = "ice-2026.08.5-ee4281022d01"
TARGET_RELEASE_ID = "ice-2026.09.4-a0d1ccf7c2c3"
DEFAULT_JOB_ID = "95264aa64b9a47ba8bb119596ccf7ce1"
STOP_WAIT_SECONDS = 90
MAX_GENERATION_RETRIES = 3


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def absolute_directory(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeError(f"{label}_NOT_ABSOLUTE")
    path = Path(os.path.abspath(os.path.normpath(os.fspath(path))))
    if not path.is_dir():
        raise RuntimeError(f"{label}_INVALID")
    return path


def identity_tuple(value: object) -> tuple[int, int, str] | None:
    if type(value) is not dict:
        return None
    pid = value.get("pid")
    created = value.get("created_at", value.get("process_created_at"))
    executable = value.get("executable")
    if type(pid) is not int or type(created) is not int or not isinstance(executable, str) or not executable:
        return None
    return pid, created, executable


def role_identity(value: object) -> tuple[int, int, str] | None:
    return identity_tuple(value)


def supervisor_identity(value: object) -> tuple[int, int, str] | None:
    if type(value) is not dict:
        return None
    return identity_tuple(
        {
            "pid": value.get("supervisor_pid"),
            "created_at": value.get("supervisor_process_created_at"),
            "executable": value.get("supervisor_executable"),
        }
    )


def process_matches(expected: tuple[int, int, str] | None, actual: object) -> bool:
    if expected is None:
        return False
    actual_id = identity_tuple(actual)
    if actual_id is None:
        return False
    return (
        expected[0] == actual_id[0]
        and expected[1] == actual_id[1]
        and os.path.normcase(os.path.abspath(expected[2])) == os.path.normcase(os.path.abspath(actual_id[2]))
    )


def _expected_release_python(source_root: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(source_root / "python" / "python.exe")))


def validate_recovery_snapshot(snapshot: dict[str, Any], *, source_root: Path) -> None:
    """Fail closed unless the exact known half-alive topology is present."""

    from enterprise.runtime.ownership import process_identity

    if snapshot.get("start_disposition") != "upstream_only":
        raise RuntimeError("RECOVERY_TOPOLOGY_NOT_UPSTREAM_ONLY")
    if snapshot.get("running_release_id") != SOURCE_RELEASE_ID:
        raise RuntimeError("RECOVERY_RUNNING_RELEASE_MISMATCH")
    if snapshot.get("running_release_mismatch") is not False:
        raise RuntimeError("RECOVERY_RELEASE_MISMATCH")
    if snapshot.get("supervisor_identity_current") is not True:
        raise RuntimeError("RECOVERY_SUPERVISOR_IDENTITY_UNTRUSTED")
    if snapshot.get("owned_child_current") is not True:
        raise RuntimeError("RECOVERY_UPSTREAM_OWNERSHIP_UNTRUSTED")

    state = snapshot.get("runtime_state")
    lock = snapshot.get("lock")
    if type(state) is not dict or type(lock) is not dict:
        raise RuntimeError("RECOVERY_RUNTIME_STATE_MISSING")
    if state.get("release_id") != SOURCE_RELEASE_ID or lock.get("release_id") != SOURCE_RELEASE_ID:
        raise RuntimeError("RECOVERY_STATE_RELEASE_MISMATCH")
    if state.get("runtime_mode") != "portable-release" or lock.get("runtime_mode") != "portable-release":
        raise RuntimeError("RECOVERY_RUNTIME_MODE_MISMATCH")
    if lock.get("lock_phase") != "adopted":
        raise RuntimeError("RECOVERY_LOCK_NOT_ADOPTED")
    if state.get("supervisor_instance_id") != lock.get("supervisor_instance_id"):
        raise RuntimeError("RECOVERY_INSTANCE_MISMATCH")
    for field in (
        "launch_context_identity",
        "enterprise_commit",
        "enterprise_tree",
        "runtime_manifest_sha256",
        "release_manifest_sha256",
        "release_payload_tree_sha256",
        "startup_preflight_sha256",
        "supervisor_command_identity",
    ):
        if state.get(field) != lock.get(field):
            raise RuntimeError(f"RECOVERY_{field.upper()}_MISMATCH")

    supervisor = supervisor_identity(state)
    lock_supervisor = supervisor_identity(lock)
    if supervisor is None or lock_supervisor is None or supervisor != lock_supervisor:
        raise RuntimeError("RECOVERY_SUPERVISOR_LOCK_IDENTITY_MISMATCH")
    supervisor_actual = process_identity(supervisor[0])
    if (
        supervisor_actual is None
        or supervisor_actual.pid != supervisor[0]
        or supervisor_actual.created_at != supervisor[1]
        or os.path.normcase(os.path.abspath(supervisor_actual.executable))
        != os.path.normcase(os.path.abspath(supervisor[2]))
    ):
        raise RuntimeError("RECOVERY_SUPERVISOR_PID_REUSED")

    upstream = role_identity(state.get("upstream"))
    if upstream is None:
        raise RuntimeError("RECOVERY_UPSTREAM_STATE_MISSING")
    upstream_actual = process_identity(upstream[0])
    if (
        upstream_actual is None
        or upstream_actual.pid != upstream[0]
        or upstream_actual.created_at != upstream[1]
        or os.path.normcase(os.path.abspath(upstream_actual.executable))
        != os.path.normcase(os.path.abspath(upstream[2]))
    ):
        raise RuntimeError("RECOVERY_UPSTREAM_PID_REUSED")
    if state.get("upstream", {}).get("parent_pid") != supervisor[0]:
        raise RuntimeError("RECOVERY_UPSTREAM_PARENT_MISMATCH")

    upstream_listener = snapshot.get("upstream_listener")
    gateway_listener = snapshot.get("gateway_listener")
    if type(upstream_listener) is not dict or type(gateway_listener) is not dict:
        raise RuntimeError("RECOVERY_LISTENER_SNAPSHOT_MISSING")
    if (
        upstream_listener.get("inspection_failed") is not False
        or upstream_listener.get("unresolved_listener_pids") != []
        or upstream_listener.get("listener_pids") != [upstream[0]]
        or len(upstream_listener.get("resolved_identities", [])) != 1
        or not process_matches(upstream, upstream_listener["resolved_identities"][0])
    ):
        raise RuntimeError("RECOVERY_UPSTREAM_LISTENER_IDENTITY_MISMATCH")
    if (
        gateway_listener.get("inspection_failed") is not False
        or gateway_listener.get("listener_pids") != []
        or gateway_listener.get("unresolved_listener_pids") != []
        or gateway_listener.get("resolved_identities") != []
    ):
        raise RuntimeError("RECOVERY_GATEWAY_PORT_NOT_CLEAR")
    if _expected_release_python(source_root) != os.path.normcase(os.path.abspath(upstream[2])):
        raise RuntimeError("RECOVERY_UPSTREAM_EXECUTABLE_MISMATCH")
    if snapshot.get("upstream_health", {}).get("ok") is not True:
        raise RuntimeError("RECOVERY_UPSTREAM_NOT_HEALTHY")


def build_config(source_root: Path):
    sys.path.insert(0, os.fspath(source_root))
    from enterprise import config as enterprise_config
    from enterprise.paths import install_path_roots_for_process
    from enterprise.runtime.portable import build_portable_preflight
    from enterprise.runtime.supervisor import SupervisorConfig

    preflight = build_portable_preflight(source_root, verify_full_payload=True)
    roots = install_path_roots_for_process(preflight.roots)
    result = preflight.result
    secrets = tuple(
        value
        for value in (
            getattr(enterprise_config, "JWT_SECRET", None),
            getattr(enterprise_config, "ADMIN_PASSWORD", None),
        )
        if isinstance(value, str) and len(value.strip()) >= 8
    )
    config = SupervisorConfig(
        app_root=roots.APP_ROOT,
        runtime_root=roots.RUNTIME_ROOT,
        log_root=roots.LOG_ROOT / "runtime",
        mode="service-host",
        runtime_mode="portable-release",
        release_id=result.release_id,
        runtime_manifest_sha256=result.runtime_manifest_sha256,
        release_manifest_sha256=result.release_manifest_sha256,
        release_payload_tree_sha256=result.release_payload_tree_sha256,
        enterprise_commit=result.enterprise_commit,
        enterprise_tree=result.enterprise_tree,
        startup_preflight_sha256=result.identity,
        python_executable=str(roots.PYTHON_RUNTIME / "python.exe"),
        upstream_port=int(getattr(enterprise_config, "UPSTREAM_PORT", 3001)),
        gateway_port=int(getattr(enterprise_config, "GATEWAY_PORT", 8000)),
        secret_values=secrets,
    )
    return roots, config


def controlled_stop(config, *, source_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    from enterprise.runtime.control import inspect_runtime
    from enterprise.runtime.state import RuntimeStateStore

    store = RuntimeStateStore(config.runtime_root)
    last_snapshot: dict[str, Any] | None = None
    for _ in range(MAX_GENERATION_RETRIES):
        snapshot = inspect_runtime(config)
        validate_recovery_snapshot(snapshot, source_root=source_root)
        last_snapshot = snapshot
        state = snapshot["runtime_state"]
        request_id = store.submit_command(
            command="stop",
            supervisor_instance_id=state["supervisor_instance_id"],
            expected_state_generation=state["state_generation"],
            launch_context_identity=snapshot.get("launch_context_identity"),
        )
        deadline = time.monotonic() + STOP_WAIT_SECONDS
        while time.monotonic() < deadline:
            ack = store.read_ack(request_id, instance_id=state["supervisor_instance_id"])
            current = inspect_runtime(config)
            if ack is not None:
                if ack.get("result") == "rejected_stale_generation":
                    break
                if ack.get("result") not in {"stopped", "already_stopped"}:
                    return {"result": "blocked", "code": "RECOVERY_STOP_REJECTED", "ack": ack}, current
                if (
                    current.get("supervisor_identity_current") is not True
                    and current.get("owned_child_current") is not True
                    and current.get("upstream_listener", {}).get("listener_pids") == []
                    and current.get("gateway_listener", {}).get("listener_pids") == []
                ):
                    store.remove_ack(request_id, instance_id=state["supervisor_instance_id"])
                    return {"result": "stopped", "request_id": request_id, "ack": ack}, current
            if (
                current.get("supervisor_identity_current") is not True
                and current.get("owned_child_current") is not True
                and current.get("upstream_listener", {}).get("listener_pids") == []
                and current.get("gateway_listener", {}).get("listener_pids") == []
            ):
                return {"result": "stopped", "request_id": request_id, "ack": ack}, current
            time.sleep(0.2)
        else:
            return {"result": "blocked", "code": "RECOVERY_STOP_TIMEOUT", "request_id": request_id}, inspect_runtime(config)
    return {"result": "blocked", "code": "RECOVERY_STATE_CHANGED"}, last_snapshot or {}


def execute_prepared_job(roots, job_id: str) -> dict[str, object]:
    from enterprise.ops.update.mvp import UpdateJobStore, execute_update_job

    store = UpdateJobStore(roots)
    status = store.read_status(job_id)
    if status.get("state") == "SUCCEEDED":
        return {"result": "already_succeeded", "status": status}
    if status.get("state") != "READY":
        return {"result": "blocked", "code": "UPDATE_JOB_NOT_READY", "status": status}
    plan = store.read_plan(job_id)
    if plan.get("source_release_id") != SOURCE_RELEASE_ID or plan.get("target_release_id") != TARGET_RELEASE_ID:
        return {"result": "blocked", "code": "UPDATE_JOB_IDENTITY_MISMATCH", "plan": plan, "status": status}
    store.reserve_execution(job_id)
    store.write_status(
        job_id,
        "UPDATING",
        actor_user_id=str(plan.get("actor_user_id") or "offline-customer-hotfix-recovery"),
        result_code="SYSTEM_UPDATE_STARTED",
        source_release_id=SOURCE_RELEASE_ID,
        target_release_id=TARGET_RELEASE_ID,
    )
    store.append_event(job_id, "UPDATING", "SYSTEM_UPDATE_STARTED")
    exit_code = execute_update_job(roots, job_id)
    final_status = store.read_status(job_id)
    return {
        "result": "succeeded" if exit_code == 0 else "failed_safe",
        "exit_code": exit_code,
        "status": final_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover the owned 2026.08.5 Runtime and apply the prepared 2026.09.4 job")
    parser.add_argument("--install-root", required=True)
    parser.add_argument("--job-id", default=DEFAULT_JOB_ID)
    args = parser.parse_args()
    try:
        install_root = absolute_directory(args.install_root, "INSTALL_ROOT")
        source_root = install_root / "releases" / SOURCE_RELEASE_ID
        if not source_root.is_dir():
            raise RuntimeError("SOURCE_RELEASE_NOT_FOUND")
        if not isinstance(args.job_id, str) or len(args.job_id) != 32 or any(ch not in "0123456789abcdef" for ch in args.job_id):
            raise RuntimeError("UPDATE_JOB_ID_INVALID")
        roots, config = build_config(source_root)
        stop_result, stop_snapshot = controlled_stop(config, source_root=source_root)
        if stop_result.get("result") != "stopped":
            emit({"result": "blocked", "stop": stop_result, "status": stop_snapshot})
            return 2
        update_result = execute_prepared_job(roots, args.job_id)
        emit({"result": update_result.get("result"), "stop": stop_result, "update": update_result})
        return 0 if update_result.get("result") in {"succeeded", "already_succeeded"} else 2
    except Exception as exc:
        code = str(exc)
        if not code or len(code) > 96 or not all(ch.isupper() or ch.isdigit() or ch == "_" for ch in code):
            code = "RECOVERY_APPLY_FAILED"
        emit({"result": "blocked", "code": code})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
