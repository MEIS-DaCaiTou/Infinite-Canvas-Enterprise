#!/usr/bin/env python3
"""Reviewed native-tool worker using the existing DATA/update/recovery engine.

The shipping EXE verifies the worker bundle and source interpreter *before*
launching this script.  It is not imported from the old installed code and
does not modify that code.  The catalog and target assets are bundled/pinned.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from enterprise.ops.update.historical_install import inspect_historical_install, read_catalog
from enterprise.ops.update.mvp import UpdateJobStore, UpdateMvpService, _run_launcher, execute_update_job
from enterprise.paths import install_path_roots_for_process
from enterprise.release.current_release import read_current_release_result_from_state_root
from enterprise.release.release_manifest_v2 import read_release_manifest_v2

RESULT_SCHEMA = "enterprise-native-upgrade-result-v1"


def safe_code(exc: Exception) -> str:
    code = str(getattr(exc, "code", str(exc)))
    return code if 0 < len(code) <= 100 and all(c.isupper() or c.isdigit() or c == "_" for c in code) else "NATIVE_UPGRADE_FAILED"


def run(
    *, install_root: Path, catalog_path: Path, manifest_path: Path,
    archive_path: Path, inventory_path: Path, inspect_only: bool = False,
    confirm_no_active_tasks: bool = False, local_app_data_base: Path | None = None,
    launcher=_run_launcher,
) -> dict[str, object]:
    job_id = None
    roots = None
    source_stopped = False
    source_id = None
    original_pointer_sha = None
    reservation_owned = False
    execution_started = False
    try:
        catalog = read_catalog(catalog_path)
        summary, roots, source_manifest = inspect_historical_install(
            install_root, catalog, local_app_data_base=local_app_data_base)
        source_id = str(summary["source_release_id"])
        if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(os.fspath(roots.PYTHON_RUNTIME / "python.exe")):
            raise ValueError("NATIVE_UPGRADE_PYTHON_IDENTITY_MISMATCH")
        target = read_release_manifest_v2(manifest_path)
        target_record = catalog.get(target.release_id)
        if target_record is None or target.raw_sha256 != target_record["manifest_sha256"] or target_record["channel"] != "stable":
            raise ValueError("NATIVE_UPGRADE_TARGET_UNSUPPORTED")
        if inspect_only:
            return {"result": "inspected", **summary, "target_release_id": target.release_id,
                    "already_current": source_id == target.release_id}
        if not confirm_no_active_tasks:
            raise ValueError("ACTIVE_TASK_DRAIN_CONFIRMATION_REQUIRED")
        if source_id == target.release_id:
            return {"result": "already_current", **summary, "target_release_id": target.release_id}
        install_path_roots_for_process(roots)
        approval = ((source_id, source_manifest.raw_sha256)
                    if summary["database_variant"] == "legacy-security-activated" else None)
        service = UpdateMvpService(roots, approved_legacy_security_source=approval)
        prepared = service.prepare_from_artifacts(actor_user_id="local-native-upgrader",
            manifest_path=manifest_path, archive_path=archive_path, inventory_path=inventory_path)
        job_id = prepared.job_id
        original_pointer_sha = read_current_release_result_from_state_root(roots.STATE_ROOT).raw_sha256
        store = UpdateJobStore(roots)
        # Reserve BEFORE stopping: another updater's reservation always wins.
        store.reserve_execution(job_id)
        reservation_owned = True
        source_stopped = True  # A failed stop can also be partially completed.
        stop_exit, stop_payload = launcher(roots.APP_ROOT, "stop")
        if stop_exit != 0 or stop_payload.get("result") not in {"stopped", "already_stopped"}:
            raise ValueError("NATIVE_UPGRADE_CONTROLLED_STOP_FAILED")
        store.write_status(job_id, "UPDATING", actor_user_id="local-native-upgrader",
            result_code="SYSTEM_UPDATE_STARTED", source_release_id=source_id,
            target_release_id=prepared.target_release_id)
        store.append_event(job_id, "UPDATING", "SYSTEM_UPDATE_STARTED")
        execution_started = True
        exit_code = execute_update_job(roots, job_id, launcher=launcher, approved_legacy_security_source=approval)
        reservation_owned = False  # The worker releases its adopted lock.
        terminal = store.read_status(job_id)
        result = ("succeeded" if exit_code == 0 else
                  "recovery_required" if terminal["state"] == "RECOVERY_REQUIRED" else "failed_safe")
        return {"result": result, "job_id": job_id,
            "source_release_id": source_id, "target_release_id": prepared.target_release_id,
            "terminal_state": terminal["state"], "result_code": terminal.get("result_code")}
    except Exception as exc:
        if job_id is not None and roots is not None and not reservation_owned and not execution_started:
            # Preparation belongs to this invocation, but another updater may
            # own the reservation. Close only our unused job, never their lock.
            try:
                store = UpdateJobStore(roots)
                store.write_status(job_id, "FAILED", actor_user_id="local-native-upgrader",
                    result_code=safe_code(exc), source_release_id=source_id)
                store.append_event(job_id, "FAILED", safe_code(exc))
            except Exception:
                pass
        if reservation_owned and roots is not None and job_id is not None:
            # Only release our own pre-execution reservation. A crash during
            # migration is not a known rollback and must remain blocked.
            try:
                store = UpdateJobStore(roots)
                if not execution_started:
                    lock = store.acquire_execution_lock(job_id)
                    store.write_status(job_id, "FAILED", actor_user_id="local-native-upgrader",
                                       result_code=safe_code(exc))
                    store.append_event(job_id, "FAILED", safe_code(exc))
                    store.release_execution_lock(lock, job_id)
                elif store.read_status(job_id)["state"] not in {"SUCCEEDED", "ROLLED_BACK", "FAILED", "RECOVERY_REQUIRED"}:
                    store.write_status(job_id, "RECOVERY_REQUIRED", actor_user_id="local-native-upgrader",
                                       result_code="NATIVE_UPGRADE_WORKER_INTERRUPTED")
                    store.append_event(job_id, "RECOVERY_REQUIRED", "NATIVE_UPGRADE_WORKER_INTERRUPTED")
            except Exception:
                pass  # Do not remove an unverified lock or recovery warning.
        recovery = "not_needed"
        if source_stopped and roots is not None:
            # Never start an uncertain or partially migrated source after a
            # failed orchestration. Revalidate pointer AND physical schema.
            try:
                _, intact, _ = inspect_historical_install(install_root, catalog, local_app_data_base=local_app_data_base)
                current = read_current_release_result_from_state_root(intact.STATE_ROOT)
                if current.release.release_id != source_id or current.raw_sha256 != original_pointer_sha:
                    raise ValueError("NATIVE_UPGRADE_RECOVERY_IDENTITY_CHANGED")
                start_exit, _ = launcher(intact.APP_ROOT, "start")
                health_exit, _ = launcher(intact.APP_ROOT, "health") if start_exit == 0 else (2, {})
                recovery = "healthy" if start_exit == 0 and health_exit == 0 else "failed"
            except Exception:
                recovery = "blocked_identity_changed"
        return {"result": "blocked", "code": safe_code(exc), "job_id": job_id, "source_recovery": recovery}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--confirm-no-active-tasks", action="store_true")
    args = parser.parse_args()
    result = run(install_root=args.install_root, catalog_path=args.catalog,
        manifest_path=args.manifest, archive_path=args.archive, inventory_path=args.inventory,
        inspect_only=args.inspect_only, confirm_no_active_tasks=args.confirm_no_active_tasks)
    result["schema_version"] = RESULT_SCHEMA
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result["result"] in {"succeeded", "already_current", "inspected"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
