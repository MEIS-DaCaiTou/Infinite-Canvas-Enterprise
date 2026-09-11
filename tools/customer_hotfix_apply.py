"""Offline, same-schema code-release update for one exact customer baseline.

This script is intentionally executed by the bundled Python of the currently
active Release.  It stages and verifies the immutable target before stopping
the owned Runtime, then delegates pointer switching/start/health/automatic
rollback to the repository's UPDATE-MVP-1 implementation.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any


EXPECTED_SOURCE_RELEASE_ID = "ice-2026.08.5-ee4281022d01"
EXPECTED_TARGET_VERSION = "2026.09.4"
TERMINAL_STATES = frozenset({"SUCCEEDED", "ROLLED_BACK", "FAILED"})


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _absolute_regular_file(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeError(f"{label}_NOT_ABSOLUTE")
    path = Path(os.path.abspath(os.path.normpath(os.fspath(path))))
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"{label}_NOT_REGULAR")
    return path


def _absolute_install_root(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeError("INSTALL_ROOT_NOT_ABSOLUTE")
    path = Path(os.path.abspath(os.path.normpath(os.fspath(path))))
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise RuntimeError("INSTALL_ROOT_INVALID")
    return path


def _read_pointer_release_id(install_root: Path) -> str:
    pointer = install_root / "state" / "current-release.json"
    if os.lstat(pointer).st_size > 16 * 1024:
        raise RuntimeError("CURRENT_RELEASE_INVALID")
    with pointer.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    release_id = value.get("release_id") if type(value) is dict else None
    if not isinstance(release_id, str):
        raise RuntimeError("CURRENT_RELEASE_INVALID")
    return release_id


def _recover_source(source_root: Path, launcher: Any) -> dict[str, object]:
    start_exit, start_payload = launcher(source_root, "start")
    health_exit, health_payload = launcher(source_root, "health")
    return {
        "source_restart_exit": start_exit,
        "source_restart_result": start_payload.get("result") or start_payload.get("code"),
        "source_health_exit": health_exit,
        "source_health_result": health_payload.get("state") or health_payload.get("code"),
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply the 2026.09.4 customer Runtime hotfix offline")
    parser.add_argument("--install-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--confirm-no-active-tasks", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if not args.confirm_no_active_tasks:
        _emit({"result": "blocked", "code": "ACTIVE_TASK_DRAIN_CONFIRMATION_REQUIRED"})
        return 2

    source_stopped = False
    source_root: Path | None = None
    launcher = None
    prepared_job_id: str | None = None
    try:
        install_root = _absolute_install_root(args.install_root)
        manifest = _absolute_regular_file(args.manifest, "MANIFEST")
        archive = _absolute_regular_file(args.archive, "ARCHIVE")
        inventory = _absolute_regular_file(args.inventory, "INVENTORY")
        source_release_id = _read_pointer_release_id(install_root)
        if source_release_id != EXPECTED_SOURCE_RELEASE_ID:
            raise RuntimeError("SOURCE_RELEASE_ID_MISMATCH")
        source_root = install_root / "releases" / source_release_id
        expected_python = source_root / "python" / "python.exe"
        if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(os.path.abspath(expected_python)):
            raise RuntimeError("SOURCE_PYTHON_IDENTITY_MISMATCH")

        sys.path.insert(0, os.fspath(source_root))
        from enterprise.paths import install_path_roots_for_process
        from enterprise.release.release_manifest_v2 import read_release_manifest_v2
        from enterprise.runtime.portable import build_portable_preflight
        from enterprise.ops.update.mvp import (
            UpdateJobStore,
            UpdateMvpService,
            _run_launcher,
            execute_update_job,
        )

        launcher = _run_launcher
        preflight = build_portable_preflight(source_root, verify_full_payload=True)
        roots = install_path_roots_for_process(preflight.roots)
        target_manifest = read_release_manifest_v2(manifest)
        target_version = str(target_manifest.section("identity")["release_version"])
        if target_version != EXPECTED_TARGET_VERSION:
            raise RuntimeError("TARGET_VERSION_MISMATCH")

        prepared = UpdateMvpService(roots).prepare_from_artifacts(
            actor_user_id="offline-customer-hotfix",
            manifest_path=manifest,
            archive_path=archive,
            inventory_path=inventory,
        )
        prepared_job_id = prepared.job_id
        if prepared.source_release_id != EXPECTED_SOURCE_RELEASE_ID:
            raise RuntimeError("PREPARED_SOURCE_RELEASE_ID_MISMATCH")
        if prepared.target_release_id != target_manifest.release_id:
            raise RuntimeError("PREPARED_TARGET_RELEASE_ID_MISMATCH")

        stop_exit, stop_payload = launcher(source_root, "stop")
        stop_result = stop_payload.get("result")
        if stop_exit != 0 or stop_result not in {"stopped", "already_stopped"}:
            raise RuntimeError(str(stop_payload.get("code") or "SOURCE_CONTROLLED_STOP_FAILED"))
        source_stopped = True

        store = UpdateJobStore(roots)
        store.reserve_execution(prepared.job_id)
        store.write_status(
            prepared.job_id,
            "UPDATING",
            actor_user_id="offline-customer-hotfix",
            result_code="SYSTEM_UPDATE_STARTED",
            source_release_id=prepared.source_release_id,
            target_release_id=prepared.target_release_id,
        )
        store.append_event(prepared.job_id, "UPDATING", "SYSTEM_UPDATE_STARTED")
        exit_code = execute_update_job(roots, prepared.job_id)
        terminal = store.read_status(prepared.job_id)
        if terminal.get("state") not in TERMINAL_STATES:
            raise RuntimeError("SYSTEM_UPDATE_TERMINAL_STATE_INVALID")

        recovery: dict[str, object] = {}
        if exit_code != 0 and _read_pointer_release_id(install_root) == EXPECTED_SOURCE_RELEASE_ID:
            recovery = _recover_source(source_root, launcher)
        _emit(
            {
                "result": "succeeded" if exit_code == 0 else "failed_safe",
                "job_id": prepared.job_id,
                "source_release_id": prepared.source_release_id,
                "target_release_id": prepared.target_release_id,
                "terminal_state": terminal.get("state"),
                "result_code": terminal.get("result_code"),
                **recovery,
            }
        )
        return 0 if exit_code == 0 else 2
    except Exception as exc:
        recovery: dict[str, object] = {}
        if source_stopped and source_root is not None and launcher is not None:
            try:
                recovery = _recover_source(source_root, launcher)
            except Exception:
                recovery = {"source_recovery": "failed"}
        code = str(exc)
        if not code or len(code) > 96 or not all(ch.isupper() or ch.isdigit() or ch == "_" for ch in code):
            code = str(getattr(exc, "code", "CUSTOMER_HOTFIX_APPLY_FAILED"))
        _emit({"result": "blocked", "code": code, "job_id": prepared_job_id, **recovery})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
