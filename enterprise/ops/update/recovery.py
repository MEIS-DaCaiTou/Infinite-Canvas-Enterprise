"""Read-only recovery assessment and explicitly audited update-unblock action.

This does not repair a database, switch a release, or dismiss an uncertain
result.  An operator must first restore a coherent running release by an
independent procedure; only then can this module verify and record it.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Callable

from enterprise.migrations.sqlite_existing import open_existing_sqlite
from enterprise.migrations.versioned import (
    STATE_MISSING,
    STATE_READY,
    inspect_schema_metadata_connection,
    schema_objects,
    schema_snapshot_sha256,
)
from enterprise.path_safety import PathSafetyError, assert_no_reparse_ancestors, assert_path_within_root, lexical_path_state
from enterprise.paths import PathRoots, validate_release_component
from enterprise.release.current_release import read_current_release_result_from_state_root
from enterprise.release.release_manifest_v2 import read_release_manifest_v2, verify_materialized_release
from enterprise.runtime.logging import utc_now
from enterprise.security_audit import append_security_audit_event

from .mvp import (
    LOCK_SCHEMA,
    MAX_PLAN_BYTES,
    MAX_RECOVERY_CLEARANCE_BYTES,
    RECOVERY_CLEARANCE_SCHEMA,
    UpdateJobStore,
    UpdateMvpError,
    _bounded_json,
    _canonical,
    _run_launcher,
)


def _database_identity(database_path: Path, app_root: Path, manifest: Any) -> dict[str, object]:
    relative = str(manifest.section("database_contract")["schema_snapshot_path"])
    evidence_path = app_root.joinpath(*relative.split("/"))
    try:
        assert_path_within_root(evidence_path, app_root)
        assert_no_reparse_ancestors(evidence_path)
    except PathSafetyError as exc:
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED", status_code=409) from exc
    evidence = _bounded_json(
        evidence_path, MAX_PLAN_BYTES,
        missing="SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED",
        invalid="SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED",
    )
    versioned_evidence = "schema_version" in evidence
    if not versioned_evidence and evidence.get("schema_id") != manifest.section("database_contract")["schema_id"]:
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED", status_code=409)
    try:
        assert_no_reparse_ancestors(database_path)
        with open_existing_sqlite(database_path, mode="ro", error_type=sqlite3.OperationalError) as conn:
            if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED", status_code=409)
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED", status_code=409)
            objects = schema_objects(conn)
            actual_schema_sha = schema_snapshot_sha256(conn)
            inspection = inspect_schema_metadata_connection(conn)
    except (OSError, sqlite3.Error, PathSafetyError) as exc:
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED", status_code=409) from exc
    if versioned_evidence:
        if (
            type(evidence.get("schema_version")) is not int
            or not isinstance(evidence.get("schema_objects_sha256"), str)
            or actual_schema_sha != evidence.get("schema_objects_sha256")
            or inspection.get("current_state") != STATE_READY
            or inspection.get("schema_version") != evidence.get("schema_version")
            or inspection.get("schema_sha256") != evidence.get("schema_objects_sha256")
        ):
            raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED", status_code=409)
        return {
            "mode": "versioned",
            "schema_version": inspection["schema_version"],
            "schema_sha256": inspection["schema_sha256"],
            "ledger_sha256": inspection["ledger_sha256"],
        }
    if evidence.get("objects") != objects:
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED", status_code=409)
    if inspection.get("current_state") != STATE_MISSING:
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED", status_code=409)
    if evidence.get("migration_ids") != manifest.section("database_contract")["migration_ids"]:
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED", status_code=409)
    return {
        "mode": "legacy-exact-schema",
        "schema_sha256": hashlib.sha256(_canonical(objects)).hexdigest(),
    }


def assess_recovery(
    roots: PathRoots,
    job_id: str,
    *,
    database_path: Path,
    launcher: Callable[[Path, str], tuple[int, dict[str, Any]]] = _run_launcher,
    lock_held: bool = False,
) -> dict[str, object]:
    """Prove one current code/database/health identity without mutating it."""
    store = UpdateJobStore(roots)
    status = store.read_status(job_id)
    plan = store.read_plan(job_id)
    if status.get("state") != "RECOVERY_REQUIRED" or plan.get("job_id") != job_id:
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_NOT_REQUIRED", status_code=409)
    if (
        status.get("actor_user_id") != plan.get("actor_user_id")
        or status.get("source_release_id") != plan.get("source_release_id")
        or status.get("target_release_id") != plan.get("target_release_id")
    ):
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED", status_code=409)
    if not lock_held and lexical_path_state(store.lock_path) != "missing":
        raise UpdateMvpError("SYSTEM_UPDATE_ALREADY_ACTIVE", status_code=409)
    source_id = validate_release_component(plan.get("source_release_id"))
    target_id = validate_release_component(plan.get("target_release_id"))
    pointer = read_current_release_result_from_state_root(roots.STATE_ROOT)
    current_id = pointer.release.release_id
    if current_id not in {source_id, target_id}:
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_POINTER_UNVERIFIED", status_code=409)
    app_root = roots.RELEASE_ROOT / current_id
    manifest = read_release_manifest_v2(app_root / "release-manifest.json")
    expected_sha = plan.get("source_manifest_sha256" if current_id == source_id else "target_manifest_sha256")
    if (
        manifest.release_id != current_id
        or manifest.raw_sha256 != expected_sha
        or pointer.release.manifest_sha256 != manifest.raw_sha256
    ):
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_RELEASE_UNVERIFIED", status_code=409)
    verify_materialized_release(
        app_root,
        inventory_path=app_root / str(manifest.section("release_payload")["inventory_path"]),
    )
    database = _database_identity(Path(database_path), app_root, manifest)
    health_exit, _ = launcher(app_root, "health")
    if health_exit != 0:
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_HEALTH_UNVERIFIED", status_code=409)
    identity: dict[str, object] = {
        "job_id": job_id,
        "job_updated_at": status.get("updated_at"),
        "current_release_id": current_id,
        "current_manifest_sha256": manifest.raw_sha256,
        "current_pointer_sha256": pointer.raw_sha256,
        "database": database,
        "health": "healthy",
        "plan_sha256": hashlib.sha256(_canonical(plan)).hexdigest(),
    }
    return {**identity, "assessment_sha256": hashlib.sha256(_canonical(identity)).hexdigest()}


def write_recovery_security_audit(
    database_path: Path, *, actor_user_id: str, job_id: str,
    current_release_id: str, assessment_sha256: str,
    clearance_sha256: str, manual_evidence_note: str,
) -> None:
    """Require an immutable security audit row before unblocking updates."""
    append_security_audit_event(
        action="security.system_update.recovery_clearance",
        risk_level="L3",
        result="success",
        actor_type="user",
        actor_user_id=actor_user_id,
        actor_role="super_admin",
        operation_id=job_id,
        capability="system_update",
        target_type="update_job",
        target_id=job_id,
        reason=manual_evidence_note,
        context={
            "current_release_id": current_release_id,
            "assessment_sha256": assessment_sha256,
            "clearance_sha256": clearance_sha256,
        },
        database_path=database_path,
    )


def clear_recovery(
    roots: PathRoots,
    job_id: str,
    *,
    database_path: Path,
    actor_user_id: str,
    expected_release_id: str,
    expected_assessment_sha256: str,
    manual_evidence_note: str,
    audit: Callable[..., None] = write_recovery_security_audit,
    launcher: Callable[[Path, str], tuple[int, dict[str, Any]]] = _run_launcher,
) -> dict[str, Any]:
    """Clear only after a fresh matching assessment, with durable audit first."""
    if not isinstance(manual_evidence_note, str) or not (12 <= len(manual_evidence_note.strip()) <= 500):
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_CONFIRMATION_INVALID")
    store = UpdateJobStore(roots)
    store.initialize()
    lock_id = uuid.uuid4().hex
    try:
        assert_no_reparse_ancestors(store.lock_path.parent)
        if lexical_path_state(store.lock_path) != "missing":
            raise UpdateMvpError("SYSTEM_UPDATE_ALREADY_ACTIVE", status_code=409)
        lock = store.lock_path.open("x+b")
    except FileExistsError as exc:
        raise UpdateMvpError("SYSTEM_UPDATE_ALREADY_ACTIVE", status_code=409) from exc
    except (OSError, PathSafetyError) as exc:
        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_LOCK_FAILED", status_code=409) from exc
    try:
        encoded_lock = _canonical({"schema_version": LOCK_SCHEMA, "job_id": lock_id, "created_at": utc_now()})
        lock.write(encoded_lock)
        lock.flush()
        os.fsync(lock.fileno())
        report = assess_recovery(
            roots, job_id, database_path=database_path, launcher=launcher,
            lock_held=True,
        )
        if (
            report["current_release_id"] != expected_release_id
            or report["assessment_sha256"] != expected_assessment_sha256
        ):
            raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_ASSESSMENT_CHANGED", status_code=409)
        record = {
            "schema_version": RECOVERY_CLEARANCE_SCHEMA,
            "job_id": job_id,
            "actor_user_id": actor_user_id,
            "verified_at": utc_now(),
            "assessment": report,
            "manual_evidence_note": manual_evidence_note.strip(),
        }
        encoded = _canonical(record)
        if len(encoded) > MAX_RECOVERY_CLEARANCE_BYTES:
            raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_RECORD_INVALID", status_code=409)
        filename = f"recovery-clearance-{uuid.uuid4().hex}.json"
        record_path = store.job_root(job_id) / filename
        with record_path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        record_sha = hashlib.sha256(encoded).hexdigest()
        audit(
            Path(database_path), actor_user_id=actor_user_id, job_id=job_id,
            current_release_id=expected_release_id,
            assessment_sha256=expected_assessment_sha256,
            clearance_sha256=record_sha,
            manual_evidence_note=manual_evidence_note.strip(),
        )
        store.append_event(
            job_id, "RECOVERY_CLEARED", "SYSTEM_UPDATE_RECOVERY_CLEARED",
            actor_user_id=actor_user_id,
            current_release_id=expected_release_id,
            recovery_clearance_sha256=record_sha,
        )
        return store.write_status(
            job_id, "RECOVERY_CLEARED", actor_user_id=actor_user_id,
            result_code="SYSTEM_UPDATE_RECOVERY_CLEARED",
            source_release_id=store.read_plan(job_id).get("source_release_id"),
            target_release_id=store.read_plan(job_id).get("target_release_id"),
            current_release_id=expected_release_id,
            recovery_clearance_file=filename,
            recovery_clearance_sha256=record_sha,
        )
    finally:
        store.release_execution_lock(lock, lock_id)
