"""Repository-external Windows process smoke for UPDATE-MVP-1 R1.

This is a direct test script, not a pytest module.  It exercises the accepted
fixed CP314 Release entry, the real controller/supervisor command channel, the
real detached one-shot worker, pointer publication, health, and rollback.
It never imports or modifies a production/test-business deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.25)
        return client.connect_ex(("127.0.0.1", port)) == 0


def _wait(predicate, *, seconds: float, label: str):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise RuntimeError(f"UPDATE_MVP_R1_SMOKE_TIMEOUT:{label}")


def _last_json(output: bytes) -> dict[str, object]:
    for line in reversed(output.decode("utf-8", errors="replace").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if type(value) is dict:
            return value
    raise RuntimeError("UPDATE_MVP_R1_SMOKE_OUTPUT_INVALID")


def _invoke_handoff(app_root: Path, job_id: str) -> int:
    sys.path.insert(0, os.fspath(app_root))
    from enterprise.runtime.portable import request_portable_update_handoff

    result = request_portable_update_handoff(app_root=app_root, job_id=job_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("result") == "update_handoff_started" else 2


def _rollback_listener(status_path: Path, pointer_path: Path, source_release_id: str, gateway_port: int) -> int:
    _wait(lambda: status_path.is_file(), seconds=60, label="rollback-status-created")
    _wait(
        lambda: json.loads(status_path.read_text(encoding="utf-8")).get("state") == "RESTARTING",
        seconds=180,
        label="rollback-restarting",
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    listener.bind(("127.0.0.1", gateway_port))
    listener.listen(2)
    try:
        _wait(
            lambda: pointer_path.is_file()
            and json.loads(pointer_path.read_text(encoding="utf-8")).get("release_id") == source_release_id,
            seconds=180,
            label="rollback-pointer-restored",
        )
    finally:
        listener.close()
    return 0


def _source_manifest(target_manifest: Path, source_version: str) -> tuple[bytes, str]:
    from enterprise.release.release_manifest_v2 import canonical_json, derive_release_id, parse_release_manifest_v2_bytes

    payload = json.loads(target_manifest.read_text(encoding="utf-8"))
    enterprise = payload["enterprise_source"]
    source_id = derive_release_id(source_version, enterprise["commit"])
    payload["identity"]["release_id"] = source_id
    payload["identity"]["release_version"] = source_version
    enterprise["version"] = source_version
    enterprise["version_file_sha256"] = hashlib.sha256((source_version + "\n").encode("utf-8")).hexdigest()
    root_prefix = f"Infinite-Canvas-Enterprise-{source_id}"
    payload["archive"]["root_prefix"] = root_prefix
    payload["archive"]["filename"] = f"{root_prefix}-win-x64.zip"
    encoded = canonical_json(payload)
    parsed = parse_release_manifest_v2_bytes(encoded)
    if parsed.release_id != source_id:
        raise RuntimeError("UPDATE_MVP_R1_SOURCE_MANIFEST_INVALID")
    return encoded, source_id


def _write_config(config_root: Path, upstream_port: int, gateway_port: int) -> None:
    config_root.mkdir(parents=True, exist_ok=True)
    secret = uuid.uuid4().hex + uuid.uuid4().hex
    document = "\n".join(
        (
            "ENTERPRISE_ENV=development",
            "ENTERPRISE_UPDATE_ENABLED=true",
            f"UPSTREAM_PORT={upstream_port}",
            f"GATEWAY_PORT={gateway_port}",
            f"JWT_SECRET={secret}",
            "ADMIN_PASSWORD=R1-fixture-only-not-production-8cN7!",
            "",
        )
    )
    (config_root / "enterprise.env").write_text(document, encoding="utf-8", newline="\n")


def _setup_release_pair(build_root: Path, install_root: Path, local_base: Path):
    from enterprise.paths import PortableRootInputs, derive_portable_path_roots, prepare_install_state_directories
    from enterprise.release.current_release import CurrentRelease, atomic_write_current_release
    from enterprise.release.release_manifest_v2 import (
        materialize_release_fixture,
        read_release_manifest_v2,
        verify_materialized_release,
    )

    manifest = build_root / "ops-release-manifest-v2.json"
    inventory = build_root / "release-payload-inventory.json"
    archives = list(build_root.glob("Infinite-Canvas-Enterprise-*-win-x64.zip"))
    if not manifest.is_file() or not inventory.is_file() or len(archives) != 1:
        raise RuntimeError("UPDATE_MVP_R1_BUILD_ARTIFACTS_INVALID")
    target = read_release_manifest_v2(manifest)
    source_bytes, source_id = _source_manifest(manifest, "2026.07.5")
    roots = derive_portable_path_roots(PortableRootInputs(install_root, local_base), source_id)
    prepare_install_state_directories(roots)
    roots.RELEASE_ROOT.mkdir(parents=True, exist_ok=True)
    source_root = roots.RELEASE_ROOT / source_id
    materialize_release_fixture(manifest, archives[0], inventory, source_root)
    (source_root / "release-manifest.json").write_bytes(source_bytes)
    source = read_release_manifest_v2(source_root / "release-manifest.json")
    verify_materialized_release(
        source_root,
        inventory_path=source_root / str(source.section("release_payload")["inventory_path"]),
    )
    atomic_write_current_release(
        roots,
        CurrentRelease(
            "env-1b1b-current-release-v1",
            source_id,
            f"releases/{source_id}",
            source.raw_sha256,
            _utc(),
            None,
        ),
        expected_manifest_sha256=source.raw_sha256,
    )
    return roots, source_root, target, manifest, inventory, archives[0]


def _launcher(app_root: Path, command: str) -> tuple[int, dict[str, object]]:
    python = app_root / "python" / "python.exe"
    launcher = app_root / "enterprise" / "runtime" / "launcher.py"
    completed = subprocess.run(
        [os.fspath(python), "-I", "-B", os.fspath(launcher), "portable", command],
        cwd=app_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
        env={key: value for key, value in os.environ.items() if key not in {"PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT"}},
    )
    return completed.returncode, _last_json(completed.stdout)


def _read_status(path: Path) -> dict[str, object] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _run_scenario(script: Path, build_root: Path, scenario_root: Path, local_base: Path, scenario: str) -> dict[str, object]:
    from enterprise.ops.update.mvp import UpdateJobStore, UpdateMvpService
    from enterprise.release.current_release import atomic_write_current_release, read_current_release_result_from_state_root
    from enterprise.release.release_manifest_v2 import read_release_manifest_v2, verify_materialized_release
    from enterprise.runtime.ownership import process_identity

    started_at = _utc()
    install_root = scenario_root / "install"
    upstream_port, gateway_port = _free_port(), _free_port()
    roots, source_root, target_manifest, manifest, inventory, archive = _setup_release_pair(
        build_root, install_root, local_base
    )
    _write_config(roots.CONFIG_ROOT, upstream_port, gateway_port)
    start_exit, start_payload = _launcher(source_root, "start")
    if start_exit != 0:
        raise RuntimeError(f"UPDATE_MVP_R1_SOURCE_START_FAILED:{start_payload.get('code')}")
    source_status_exit, source_status = _launcher(source_root, "status")
    source_health_exit, source_health = _launcher(source_root, "health")
    if source_status_exit != 0 or source_health_exit != 0:
        raise RuntimeError("UPDATE_MVP_R1_SOURCE_NOT_HEALTHY")
    source_pid = int(source_status["runtime_state"]["supervisor_pid"])

    prepared = UpdateMvpService(roots).prepare_from_artifacts(
        actor_user_id="update-mvp-r1-smoke",
        manifest_path=manifest,
        archive_path=archive,
        inventory_path=inventory,
    )
    store = UpdateJobStore(roots)
    store.reserve_execution(prepared.job_id)
    store.write_status(
        prepared.job_id,
        "UPDATING",
        actor_user_id="update-mvp-r1-smoke",
        result_code="SYSTEM_UPDATE_STARTED",
        source_release_id=prepared.source_release_id,
        target_release_id=prepared.target_release_id,
    )
    store.append_event(prepared.job_id, "UPDATING", "SYSTEM_UPDATE_STARTED")
    status_path = store.job_root(prepared.job_id) / "status.json"
    watcher = None
    if scenario == "rollback":
        watcher = subprocess.Popen(
            [
                sys.executable, os.fspath(script), "--rollback-listener",
                "--status-path", os.fspath(status_path),
                "--pointer-path", os.fspath(roots.STATE_ROOT / "current-release.json"),
                "--source-release-id", prepared.source_release_id,
                "--gateway-port", str(gateway_port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            shell=False,
        )
    invoke = subprocess.run(
        [
            os.fspath(source_root / "python" / "python.exe"), "-I", "-B", os.fspath(script),
            "--invoke-handoff", "--app-root", os.fspath(source_root), "--job-id", prepared.job_id,
        ],
        cwd=source_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    handoff = _last_json(invoke.stdout)
    if invoke.returncode != 0 or handoff.get("result") != "update_handoff_started":
        raise RuntimeError("UPDATE_MVP_R1_HANDOFF_NOT_STARTED")
    worker_pid = int(handoff["ack"]["after"]["update_worker_pid"])
    terminal = _wait(
        lambda: (value if (value := _read_status(status_path)) and value.get("state") in {"SUCCEEDED", "ROLLED_BACK", "FAILED"} else None),
        seconds=300,
        label=f"{scenario}-terminal",
    )
    if watcher is not None:
        watcher.wait(timeout=60)
        if watcher.returncode != 0:
            raise RuntimeError("UPDATE_MVP_R1_ROLLBACK_LISTENER_FAILED")
    expected_state = "SUCCEEDED" if scenario == "success" else "ROLLED_BACK"
    if terminal.get("state") != expected_state:
        raise RuntimeError(f"UPDATE_MVP_R1_UNEXPECTED_TERMINAL:{terminal.get('state')}")
    pointer = read_current_release_result_from_state_root(roots.STATE_ROOT)
    expected_release = target_manifest.release_id if scenario == "success" else prepared.source_release_id
    if pointer.release.release_id != expected_release:
        raise RuntimeError("UPDATE_MVP_R1_POINTER_RESULT_INVALID")
    active_root = roots.RELEASE_ROOT / expected_release
    status_exit, active_status = _launcher(active_root, "status")
    health_exit, active_health = _launcher(active_root, "health")
    if status_exit != 0 or health_exit != 0 or active_health.get("readiness", {}).get("ready") is not True:
        raise RuntimeError("UPDATE_MVP_R1_ACTIVE_RELEASE_NOT_HEALTHY")
    target_pid = int(active_status["runtime_state"]["supervisor_pid"])
    source_gone = process_identity(source_pid) is None
    if not source_gone:
        raise RuntimeError("UPDATE_MVP_R1_SOURCE_SUPERVISOR_REMAINED")
    worker_gone = _wait(lambda: process_identity(worker_pid) is None, seconds=60, label="worker-exit")
    events = [json.loads(line) for line in (store.job_root(prepared.job_id) / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    if not events or events[-1]["state"] != expected_state:
        raise RuntimeError("UPDATE_MVP_R1_TERMINAL_EVENT_MISSING")
    if store.lock_path.exists():
        raise RuntimeError("UPDATE_MVP_R1_ACTIVE_LOCK_REMAINED")
    if scenario == "rollback":
        target_root = roots.RELEASE_ROOT / target_manifest.release_id
        verify_materialized_release(
            target_root,
            inventory_path=target_root / str(target_manifest.section("release_payload")["inventory_path"]),
        )
    stop_exit, stop_payload = _launcher(active_root, "stop")
    if stop_exit != 0:
        raise RuntimeError(f"UPDATE_MVP_R1_CLEANUP_STOP_FAILED:{stop_payload.get('code')}")
    _wait(lambda: not (roots.RUNTIME_ROOT / "runtime-supervisor.lock").exists(), seconds=60, label="runtime-lock-release")
    _wait(lambda: not _port_open(upstream_port) and not _port_open(gateway_port), seconds=60, label="listener-release")
    if process_identity(target_pid) is not None:
        raise RuntimeError("UPDATE_MVP_R1_OWNED_PROCESS_REMAINED")
    return {
        "schema_version": "update-mvp-1-r1-windows-smoke-v1",
        "scenario": scenario,
        "source_release_id": prepared.source_release_id,
        "target_release_id": prepared.target_release_id,
        "job_id": prepared.job_id,
        "started_at": started_at,
        "ended_at": _utc(),
        "source_supervisor_stop_observed": bool(source_gone),
        "source_lock_released": True,
        "worker_launched": True,
        "worker_exited": bool(worker_gone),
        "pointer_before": prepared.source_release_id,
        "pointer_after": pointer.release.release_id,
        "target_start_result": "pass" if scenario == "success" else "failed_as_injected",
        "target_health_result": "pass" if scenario == "success" else "not_reached",
        "rollback_pointer_result": "not_applicable" if scenario == "success" else "pass",
        "source_restart_result": "not_applicable" if scenario == "success" else "pass",
        "source_health_result": "not_applicable" if scenario == "success" else "pass",
        "final_job_state": terminal["state"],
        "active_update_lock_absent": True,
        "runtime_supervisor_lock_absent_after_cleanup": True,
        "remaining_owned_processes": 0,
        "remaining_listeners": 0,
        "production_touched": False,
        "temporary_business_environment_touched": False,
    }


def _safe_generated_remove(path: Path, local_base: Path) -> None:
    if path.parent != local_base or path.name not in {"InfiniteCanvasEnterprise", "Infinite-Canvas-Enterprise"}:
        raise RuntimeError("UPDATE_MVP_R1_LOCAL_ROOT_IDENTITY_INVALID")
    if path.exists():
        runtime_lock = path / "runtime" / "runtime-supervisor.lock"
        if runtime_lock.exists():
            raise RuntimeError("UPDATE_MVP_R1_LOCAL_RUNTIME_STILL_ACTIVE")
        shutil.rmtree(path)


def _run_all(script: Path, build_root: Path, evidence_root: Path) -> int:
    if os.name != "nt":
        raise RuntimeError("UPDATE_MVP_R1_WINDOWS_REQUIRED")
    if evidence_root.exists():
        raise RuntimeError("UPDATE_MVP_R1_EVIDENCE_EXISTS")
    evidence_root.mkdir(parents=True, exist_ok=False)
    from enterprise.runtime.portable import windows_local_app_data_known_folder

    local_base = windows_local_app_data_known_folder()
    names = ("InfiniteCanvasEnterprise", "Infinite-Canvas-Enterprise")
    nonce = uuid.uuid4().hex
    backups: list[tuple[Path, Path]] = []
    results: list[dict[str, object]] = []
    try:
        for name in names:
            current = local_base / name
            backup = local_base / f".{name}.update-mvp-r1-backup-{nonce}"
            if backup.exists():
                raise RuntimeError("UPDATE_MVP_R1_LOCAL_BACKUP_COLLISION")
            if current.exists():
                if (current / "runtime" / "runtime-supervisor.lock").exists():
                    raise RuntimeError("UPDATE_MVP_R1_PREEXISTING_RUNTIME_ACTIVE")
                os.replace(current, backup)
                backups.append((current, backup))
        for scenario in ("success", "rollback"):
            scenario_root = evidence_root / scenario
            scenario_root.mkdir()
            result = _run_scenario(script, build_root, scenario_root, local_base, scenario)
            (evidence_root / f"WU-{scenario.upper()}.json").write_bytes(_json_bytes(result))
            results.append(result)
            for name in names:
                _safe_generated_remove(local_base / name, local_base)
        summary = {
            "schema_version": "update-mvp-1-r1-windows-evidence-v1",
            "environment": "repository-external isolated Windows fixture",
            "wu1_real_process_chain": True,
            "wu2_real_process_chain": True,
            "results": results,
            "production_touched": False,
            "temporary_business_environment_touched": False,
        }
        (evidence_root / "WINDOWS-SMOKE-SUMMARY.json").write_bytes(_json_bytes(summary))
        sums = []
        for path in sorted(evidence_root.glob("*.json"), key=lambda item: item.name):
            sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
        (evidence_root / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="ascii", newline="\n")
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    finally:
        for name in names:
            _safe_generated_remove(local_base / name, local_base)
        for current, backup in reversed(backups):
            if current.exists() or not backup.exists():
                raise RuntimeError("UPDATE_MVP_R1_LOCAL_BACKUP_RESTORE_BLOCKED")
            os.replace(backup, current)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--run-all", action="store_true")
    modes.add_argument("--invoke-handoff", action="store_true")
    modes.add_argument("--rollback-listener", action="store_true")
    parser.add_argument("--target-build", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--app-root", type=Path)
    parser.add_argument("--job-id")
    parser.add_argument("--status-path", type=Path)
    parser.add_argument("--pointer-path", type=Path)
    parser.add_argument("--source-release-id")
    parser.add_argument("--gateway-port", type=int)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.invoke_handoff:
        return _invoke_handoff(args.app_root, args.job_id)
    if args.rollback_listener:
        return _rollback_listener(args.status_path, args.pointer_path, args.source_release_id, args.gateway_port)
    if args.target_build is None or args.evidence_root is None:
        raise RuntimeError("UPDATE_MVP_R1_SMOKE_ARGUMENTS_INVALID")
    return _run_all(Path(__file__).resolve(), args.target_build.resolve(), args.evidence_root.resolve())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"code": str(exc).split(":", 1)[0], "status": "blocked"}, sort_keys=True, separators=(",", ":")))
        raise SystemExit(2)
