"""One-time controlled 09.6 security-variant migration, from verified target code.

Only the separately verified bootstrap may launch this module.  Normal UI
updates never opt in to the exceptional 28-object source identity.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[3]))

from enterprise.migrations.sqlite_existing import open_existing_sqlite
from enterprise.ops.update.legacy_security_variant import (
    SOURCE_MANIFEST_SHA256,
    SOURCE_RELEASE_ID,
    inspect_096_security_variant,
)
from enterprise.ops.update.mvp import (
    UpdateJobStore,
    UpdateMvpService,
    _database_evidence,
    _run_launcher,
    execute_update_job,
)
from enterprise.paths import install_path_roots_for_process
from enterprise.release.current_release import read_current_release_result_from_state_root
from enterprise.release.release_manifest_v2 import (
    read_release_manifest_v2,
    verify_materialized_release,
)
from enterprise.runtime.portable import build_portable_preflight


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _code(exc: Exception) -> str:
    code = str(getattr(exc, "code", str(exc)))
    return code if 0 < len(code) <= 96 and all(c.isupper() or c.isdigit() or c == "_" for c in code) else "SECURITY_BRIDGE_FAILED"


def _source_identity_intact(roots, source_manifest) -> bool:
    try:
        pointer = read_current_release_result_from_state_root(roots.STATE_ROOT)
        if pointer.release.release_id != SOURCE_RELEASE_ID or pointer.release.manifest_sha256 != SOURCE_MANIFEST_SHA256:
            return False
        evidence = _database_evidence(roots.APP_ROOT, source_manifest)
        with open_existing_sqlite(roots.DATA_ROOT / "enterprise.db", mode="ro", error_type=sqlite3.OperationalError) as conn:
            inspect_096_security_variant(
                conn,
                baseline_objects=evidence["objects"],
                source_release_id=source_manifest.release_id,
                source_manifest_sha256=source_manifest.raw_sha256,
            )
        return True
    except Exception:
        return False


def run(*, install_root: Path, staged_target_root: Path, manifest: Path, archive: Path, inventory: Path) -> int:
    job_id: str | None = None
    source_stopped = False
    roots = None
    source_manifest = None
    source_root = install_root / "releases" / SOURCE_RELEASE_ID
    try:
        staged_target_root = staged_target_root.resolve(strict=True)
        if Path(__file__).resolve() != staged_target_root / "enterprise" / "ops" / "update" / "bridge_worker_096.py":
            raise ValueError("SECURITY_BRIDGE_CODE_ROOT_MISMATCH")
        target_manifest = read_release_manifest_v2(manifest)
        staged_manifest = read_release_manifest_v2(staged_target_root / "release-manifest.json")
        if (
            staged_manifest.raw_sha256 != target_manifest.raw_sha256
            or str(target_manifest.section("identity")["release_version"]) != "2026.09.9"
            or target_manifest.release_id != staged_manifest.release_id
        ):
            raise ValueError("SECURITY_BRIDGE_TARGET_IDENTITY_MISMATCH")
        verify_materialized_release(
            staged_target_root,
            inventory_path=staged_target_root / str(staged_manifest.section("release_payload")["inventory_path"]),
        )
        preflight = build_portable_preflight(source_root, verify_full_payload=True)
        roots = install_path_roots_for_process(preflight.roots)
        source_manifest = preflight.release_manifest
        if source_manifest.release_id != SOURCE_RELEASE_ID or source_manifest.raw_sha256 != SOURCE_MANIFEST_SHA256:
            raise ValueError("SECURITY_BRIDGE_SOURCE_IDENTITY_MISMATCH")
        if not _source_identity_intact(roots, source_manifest):
            raise ValueError("SECURITY_BRIDGE_SOURCE_DATABASE_MISMATCH")
        prepared = UpdateMvpService(roots, allow_096_security_variant=True).prepare_from_artifacts(
            actor_user_id="offline-096-security-bridge",
            manifest_path=manifest,
            archive_path=archive,
            inventory_path=inventory,
        )
        job_id = prepared.job_id
        if prepared.source_release_id != SOURCE_RELEASE_ID or prepared.target_release_id != target_manifest.release_id:
            raise ValueError("SECURITY_BRIDGE_PREPARED_IDENTITY_MISMATCH")
        stop_exit, stop_payload = _run_launcher(source_root, "stop")
        if stop_exit != 0 or stop_payload.get("result") not in {"stopped", "already_stopped"}:
            raise ValueError("SECURITY_BRIDGE_CONTROLLED_STOP_FAILED")
        source_stopped = True
        store = UpdateJobStore(roots)
        store.reserve_execution(job_id)
        store.write_status(
            job_id, "UPDATING", actor_user_id="offline-096-security-bridge",
            result_code="SYSTEM_UPDATE_STARTED", source_release_id=SOURCE_RELEASE_ID,
            target_release_id=prepared.target_release_id,
        )
        store.append_event(job_id, "UPDATING", "SYSTEM_UPDATE_STARTED")
        exit_code = execute_update_job(roots, job_id, allow_096_security_variant=True)
        terminal = store.read_status(job_id)
        _emit({
            "result": "succeeded" if exit_code == 0 else "failed_safe",
            "job_id": job_id,
            "source_release_id": SOURCE_RELEASE_ID,
            "target_release_id": prepared.target_release_id,
            "terminal_state": terminal.get("state"),
            "result_code": terminal.get("result_code"),
        })
        return 0 if exit_code == 0 else 2
    except Exception as exc:
        source_recovery = "not_needed"
        if source_stopped and roots is not None and source_manifest is not None:
            if _source_identity_intact(roots, source_manifest):
                start_exit, _ = _run_launcher(source_root, "start")
                health_exit, _ = _run_launcher(source_root, "health") if start_exit == 0 else (2, {})
                source_recovery = "healthy" if start_exit == 0 and health_exit == 0 else "failed"
            else:
                source_recovery = "blocked_identity_changed"
        _emit({"result": "blocked", "code": _code(exc), "job_id": job_id, "source_recovery": source_recovery})
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute a verified 09.6 security-variant bridge")
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--staged-target-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    return run(**vars(args))


if __name__ == "__main__":
    raise SystemExit(main())
