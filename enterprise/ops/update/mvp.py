"""Minimal fail-closed online update orchestration for one portable Release hop.

The module deliberately builds on the existing Manifest v2, PathRoots and
Runtime lifecycle contracts.  It is not a generic package manager and it
never accepts an operator supplied command, URL, install root or executable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from enterprise.migrations.versioned import (
    DEFAULT_MIGRATIONS,
    MIGRATION_ID_RE,
    SHA256_RE,
    STATE_READY,
    DataMigrationError,
    MigrationResult,
    MigrationStep,
    apply_versioned_migrations,
    finalize_release_database_validation,
    inspect_schema_metadata,
    migration_registry_sha256,
    plan_migrations,
    validate_registry,
)
from enterprise.paths import PathRoots, validate_release_component
from enterprise.path_safety import PathSafetyError, assert_no_reparse_ancestors, assert_path_within_root
from enterprise.release.current_release import (
    SCHEMA_VERSION as CURRENT_RELEASE_SCHEMA,
    CurrentRelease,
    CurrentReleaseError,
    atomic_write_current_release,
    read_current_release_result_from_state_root,
)
from enterprise.release.release_manifest_v2 import (
    INVENTORY_MAX_BYTES,
    MANIFEST_MAX_BYTES,
    ReleaseManifestV2,
    ReleaseManifestV2Error,
    materialize_release_fixture,
    read_release_manifest_v2,
    sha256_file,
    verify_materialized_release,
    verify_release_manifest_v2,
)
from enterprise.runtime.logging import redact_value, utc_now
from enterprise.ops.update.versions import compare_versions


JOB_SCHEMA = "enterprise-update-mvp-job-v1"
PLAN_SCHEMA = "enterprise-update-mvp-plan-v1"
EVENT_SCHEMA = "enterprise-update-mvp-event-v1"
LOCK_SCHEMA = "enterprise-update-mvp-lock-v1"
DATABASE_RESULT_SCHEMA = "enterprise-update-database-result-v1"
RECOVERY_CLEARANCE_SCHEMA = "enterprise-update-recovery-clearance-v1"
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
CLEARANCE_FILE_RE = re.compile(r"^recovery-clearance-[0-9a-f]{32}\.json$")
STATES = frozenset(
    {
        "PREPARING",
        "READY",
        "UPDATING",
        "MIGRATING",
        "RESTARTING",
        "VERIFYING",
        "SUCCEEDED",
        "ROLLING_BACK",
        "ROLLED_BACK",
        "FAILED",
        "RECOVERY_REQUIRED",
        "RECOVERY_CLEARED",
    }
)
TERMINAL_STATES = frozenset({"SUCCEEDED", "ROLLED_BACK", "FAILED", "RECOVERY_REQUIRED", "RECOVERY_CLEARED"})
MAX_STATUS_BYTES = 64 * 1024
MAX_PLAN_BYTES = 128 * 1024
MAX_EVENT_BYTES = 64 * 1024
MAX_DATABASE_RESULT_BYTES = 64 * 1024
MAX_RECOVERY_CLEARANCE_BYTES = 64 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024


class UpdateMvpError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _canonical(payload: object) -> bytes:
    return (json.dumps(redact_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _bounded_json(path: Path, maximum: int, *, missing: str, invalid: str) -> dict[str, Any]:
    data = bytearray()
    try:
        with path.open("rb") as handle:
            while len(data) < maximum + 1:
                chunk = handle.read(min(64 * 1024, maximum + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
    except FileNotFoundError as exc:
        raise UpdateMvpError(missing, status_code=404) from exc
    except OSError as exc:
        raise UpdateMvpError(invalid) from exc
    if not data or len(data) > maximum or data.startswith(b"\xef\xbb\xbf"):
        raise UpdateMvpError(invalid)
    try:
        payload = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateMvpError(invalid) from exc
    if type(payload) is not dict:
        raise UpdateMvpError(invalid)
    return payload


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = _canonical(payload)
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise UpdateMvpError("SYSTEM_UPDATE_STATE_WRITE_FAILED", status_code=500) from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _copy_bounded(source: Path, destination: Path, maximum: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    received = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        while True:
            chunk = reader.read(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > maximum:
                raise UpdateMvpError("SYSTEM_UPDATE_ARTIFACT_SIZE_INVALID")
            digest.update(chunk)
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    return digest.hexdigest(), received


def _remove_owned_tree(path: Path, identity: tuple[int, int] | None) -> None:
    if identity is None:
        return
    try:
        current = path.stat(follow_symlinks=False)
    except OSError:
        return
    if path.is_symlink() or (current.st_dev, current.st_ino) != identity:
        return
    shutil.rmtree(path, ignore_errors=True)


class UpdateJobStore:
    """Durable, bounded, non-secret job records under the existing STAGING_ROOT."""

    def __init__(self, roots: PathRoots) -> None:
        self.roots = roots
        self.root = roots.STAGING_ROOT / "update-mvp"
        self.jobs_root = self.root / "jobs"
        self.lock_path = roots.STATE_ROOT / "system-update-active.lock"

    def initialize(self) -> None:
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.roots.STATE_ROOT.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate_job_id(job_id: object) -> str:
        if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
            raise UpdateMvpError("SYSTEM_UPDATE_JOB_ID_INVALID")
        return job_id

    def job_root(self, job_id: str) -> Path:
        return self.jobs_root / self.validate_job_id(job_id)

    def create(self, actor_user_id: str) -> tuple[str, Path]:
        self.initialize()
        job_id = uuid.uuid4().hex
        root = self.job_root(job_id)
        try:
            root.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise UpdateMvpError("SYSTEM_UPDATE_JOB_COLLISION", status_code=409) from exc
        now = utc_now()
        self.write_status(job_id, "PREPARING", actor_user_id=actor_user_id, result_code="SYSTEM_UPDATE_PREPARING", created_at=now)
        self.append_event(job_id, "PREPARING", "SYSTEM_UPDATE_PREPARING")
        return job_id, root

    def write_plan(self, job_id: str, payload: dict[str, Any]) -> str:
        path = self.job_root(job_id) / "plan.json"
        encoded = _canonical({"schema_version": PLAN_SCHEMA, **payload})
        if len(encoded) > MAX_PLAN_BYTES:
            raise UpdateMvpError("SYSTEM_UPDATE_PLAN_INVALID")
        try:
            with path.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise UpdateMvpError("SYSTEM_UPDATE_PLAN_ALREADY_EXISTS", status_code=409) from exc
        except OSError as exc:
            raise UpdateMvpError("SYSTEM_UPDATE_PLAN_WRITE_FAILED", status_code=500) from exc
        return hashlib.sha256(encoded).hexdigest()

    def read_plan(self, job_id: str) -> dict[str, Any]:
        plan = _bounded_json(self.job_root(job_id) / "plan.json", MAX_PLAN_BYTES, missing="SYSTEM_UPDATE_PLAN_MISSING", invalid="SYSTEM_UPDATE_PLAN_INVALID")
        if plan.get("schema_version") != PLAN_SCHEMA or plan.get("job_id") != job_id:
            raise UpdateMvpError("SYSTEM_UPDATE_PLAN_INVALID")
        return plan

    def write_database_result(self, job_id: str, payload: dict[str, Any]) -> str:
        path = self.job_root(job_id) / "database-result.json"
        encoded = _canonical({"schema_version": DATABASE_RESULT_SCHEMA, "job_id": job_id, **payload})
        if len(encoded) > MAX_DATABASE_RESULT_BYTES:
            raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_RESULT_INVALID")
        try:
            with path.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_RESULT_ALREADY_EXISTS", status_code=409) from exc
        except OSError as exc:
            raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_RESULT_WRITE_FAILED", status_code=500) from exc
        return hashlib.sha256(encoded).hexdigest()

    def read_database_result(self, job_id: str) -> dict[str, Any]:
        payload = _bounded_json(
            self.job_root(job_id) / "database-result.json",
            MAX_DATABASE_RESULT_BYTES,
            missing="SYSTEM_UPDATE_DATABASE_RESULT_MISSING",
            invalid="SYSTEM_UPDATE_DATABASE_RESULT_INVALID",
        )
        if payload.get("schema_version") != DATABASE_RESULT_SCHEMA or payload.get("job_id") != job_id:
            raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_RESULT_INVALID")
        return payload

    def write_status(self, job_id: str, state: str, *, actor_user_id: str, result_code: str, created_at: str | None = None, **fields: Any) -> dict[str, Any]:
        if state not in STATES or not isinstance(result_code, str) or not result_code:
            raise UpdateMvpError("SYSTEM_UPDATE_STATE_INVALID")
        path = self.job_root(job_id) / "status.json"
        existing: dict[str, Any] = {}
        try:
            existing = _bounded_json(path, MAX_STATUS_BYTES, missing="SYSTEM_UPDATE_JOB_NOT_FOUND", invalid="SYSTEM_UPDATE_STATE_INVALID")
        except UpdateMvpError as exc:
            if exc.code != "SYSTEM_UPDATE_JOB_NOT_FOUND":
                raise
        payload = {
            "schema_version": JOB_SCHEMA,
            "job_id": job_id,
            "actor_user_id": actor_user_id,
            "state": state,
            "created_at": created_at or existing.get("created_at") or utc_now(),
            "updated_at": utc_now(),
            "result_code": result_code,
            **fields,
        }
        _atomic_json(path, payload)
        return payload

    def read_status(self, job_id: str) -> dict[str, Any]:
        payload = _bounded_json(self.job_root(job_id) / "status.json", MAX_STATUS_BYTES, missing="SYSTEM_UPDATE_JOB_NOT_FOUND", invalid="SYSTEM_UPDATE_STATE_INVALID")
        if payload.get("schema_version") != JOB_SCHEMA or payload.get("job_id") != job_id or payload.get("state") not in STATES:
            raise UpdateMvpError("SYSTEM_UPDATE_STATE_INVALID")
        return payload

    def append_event(self, job_id: str, state: str, code: str, **fields: Any) -> None:
        if state not in STATES:
            raise UpdateMvpError("SYSTEM_UPDATE_STATE_INVALID")
        event = _canonical({"schema_version": EVENT_SCHEMA, "job_id": job_id, "ts": utc_now(), "state": state, "code": code, **fields})
        if len(event) > MAX_EVENT_BYTES:
            raise UpdateMvpError("SYSTEM_UPDATE_EVENT_INVALID")
        try:
            with (self.job_root(job_id) / "events.jsonl").open("ab") as handle:
                handle.write(event)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise UpdateMvpError("SYSTEM_UPDATE_EVENT_WRITE_FAILED", status_code=500) from exc

    def pending_recovery_jobs(self) -> list[str]:
        """Return unresolved jobs, rejecting unverifiable historical job state."""
        self.initialize()
        pending: list[str] = []
        try:
            for root in self.jobs_root.iterdir():
                if not JOB_ID_RE.fullmatch(root.name):
                    continue
                assert_no_reparse_ancestors(root)
                if not root.is_dir():
                    raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED", status_code=409)
                try:
                    status = self.read_status(root.name)
                except UpdateMvpError as exc:
                    raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED", status_code=409) from exc
                if status["state"] == "RECOVERY_REQUIRED":
                    pending.append(root.name)
                elif status["state"] == "RECOVERY_CLEARED":
                    name = status.get("recovery_clearance_file")
                    digest = status.get("recovery_clearance_sha256")
                    if not isinstance(name, str) or not CLEARANCE_FILE_RE.fullmatch(name) or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED", status_code=409)
                    clearance_path = root / name
                    assert_no_reparse_ancestors(clearance_path)
                    try:
                        clearance = _bounded_json(
                            clearance_path, MAX_RECOVERY_CLEARANCE_BYTES,
                            missing="SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED",
                            invalid="SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED",
                        )
                    except UpdateMvpError as exc:
                        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED", status_code=409) from exc
                    if (
                        hashlib.sha256(_canonical(clearance)).hexdigest() != digest
                        or clearance.get("schema_version") != RECOVERY_CLEARANCE_SCHEMA
                        or clearance.get("job_id") != root.name
                        or clearance.get("actor_user_id") != status.get("actor_user_id")
                        or not isinstance(clearance.get("assessment"), dict)
                        or clearance["assessment"].get("current_release_id") != status.get("current_release_id")
                        or clearance["assessment"].get("assessment_sha256") != hashlib.sha256(
                            _canonical({key: value for key, value in clearance["assessment"].items() if key != "assessment_sha256"})
                        ).hexdigest()
                    ):
                        raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED", status_code=409)
        except (OSError, PathSafetyError) as exc:
            raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED", status_code=409) from exc
        return sorted(pending)

    def assert_no_unresolved_recovery(self) -> None:
        """A terminal recovery warning outlives the active-job lock."""
        if self.pending_recovery_jobs():
            raise UpdateMvpError("SYSTEM_UPDATE_RECOVERY_REQUIRED", status_code=409)

    def reserve_execution(self, job_id: str) -> None:
        """Create the sole API-side reservation; an existing lock always wins.

        The one-shot worker may later adopt this exact reservation through
        ``acquire_execution_lock``. API callers must not be allowed to adopt
        it, otherwise concurrent confirmations for one job could both enqueue
        a handoff.
        """
        self.initialize()
        self.assert_no_unresolved_recovery()
        try:
            handle = self.lock_path.open("x+b")
        except FileExistsError as exc:
            raise UpdateMvpError("SYSTEM_UPDATE_ALREADY_ACTIVE", status_code=409) from exc
        try:
            data = _canonical(
                {
                    "schema_version": LOCK_SCHEMA,
                    "job_id": self.validate_job_id(job_id),
                    "created_at": utc_now(),
                }
            )
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            handle.close()
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
            raise
        finally:
            if not handle.closed:
                handle.close()

    def acquire_execution_lock(self, job_id: str):
        self.initialize()
        try:
            handle = self.lock_path.open("x+b")
        except FileExistsError as exc:
            payload = _bounded_json(self.lock_path, 16 * 1024, missing="SYSTEM_UPDATE_LOCK_MISSING", invalid="SYSTEM_UPDATE_LOCK_INVALID")
            if payload.get("schema_version") != LOCK_SCHEMA or payload.get("job_id") != job_id:
                raise UpdateMvpError("SYSTEM_UPDATE_ALREADY_ACTIVE", status_code=409) from exc
            try:
                handle = self.lock_path.open("r+b")
                if (os.fstat(handle.fileno()).st_dev, os.fstat(handle.fileno()).st_ino) != (
                    os.stat(self.lock_path, follow_symlinks=False).st_dev,
                    os.stat(self.lock_path, follow_symlinks=False).st_ino,
                ):
                    handle.close()
                    raise UpdateMvpError("SYSTEM_UPDATE_LOCK_INVALID", status_code=409)
                return handle
            except OSError as open_exc:
                raise UpdateMvpError("SYSTEM_UPDATE_LOCK_INVALID", status_code=409) from open_exc
        try:
            data = _canonical({"schema_version": LOCK_SCHEMA, "job_id": job_id, "created_at": utc_now()})
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
            return handle
        except Exception:
            handle.close()
            try: self.lock_path.unlink()
            except FileNotFoundError: pass
            raise

    def release_execution_lock(self, handle: Any, job_id: str) -> None:
        identity = None
        try:
            stat_result = os.fstat(handle.fileno())
            identity = (stat_result.st_dev, stat_result.st_ino)
            handle.close()
        finally:
            try:
                payload = _bounded_json(self.lock_path, 16 * 1024, missing="SYSTEM_UPDATE_LOCK_MISSING", invalid="SYSTEM_UPDATE_LOCK_INVALID")
                current = os.stat(self.lock_path, follow_symlinks=False)
                if payload.get("job_id") == job_id and identity == (current.st_dev, current.st_ino):
                    self.lock_path.unlink()
            except (UpdateMvpError, OSError):
                pass


def _database_contract_mode(source: ReleaseManifestV2, target: ReleaseManifestV2) -> str | None:
    left = source.section("database_contract")
    right = target.section("database_contract")
    common = bool(
        right.get("ops3b_activation_eligible") is True
        and left.get("schema_id") == right.get("schema_id")
        and left.get("migration_ids") == right.get("migration_ids")
    )
    if not common:
        return None
    if (
        right.get("migration_compatibility") == "same-schema-no-migration"
        and right.get("rollback_classification") == "code-release-pointer"
    ):
        return "same-schema-no-migration"
    if (
        right.get("migration_compatibility") == "versioned-forward-migration"
        and right.get("rollback_classification") == "database-backup-restore"
        and left.get("schema_snapshot_sha256") != right.get("schema_snapshot_sha256")
    ):
        return "versioned-forward-migration"
    return None


def _database_contract_compatible(source: ReleaseManifestV2, target: ReleaseManifestV2) -> bool:
    return _database_contract_mode(source, target) is not None


def _database_evidence(app_root: Path, manifest: ReleaseManifestV2) -> dict[str, Any]:
    relative = str(manifest.section("database_contract")["schema_snapshot_path"])
    path = Path(app_root) / Path(*relative.split("/"))
    try:
        assert_path_within_root(path, Path(app_root))
    except PathSafetyError as exc:
        raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_EVIDENCE_INVALID") from exc
    payload = _bounded_json(
        path,
        MAX_PLAN_BYTES,
        missing="SYSTEM_UPDATE_DATABASE_EVIDENCE_MISSING",
        invalid="SYSTEM_UPDATE_DATABASE_EVIDENCE_INVALID",
    )
    required = {
        "schema_version",
        "schema_objects_sha256",
        "migration_registry_sha256",
        "versioned_migration_ids",
    }
    versioned_ids = payload.get("versioned_migration_ids")
    if (
        not required.issubset(payload)
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] < 1
        or not SHA256_RE.fullmatch(str(payload.get("schema_objects_sha256")))
        or not SHA256_RE.fullmatch(str(payload.get("migration_registry_sha256")))
        or type(versioned_ids) is not list
        or len(versioned_ids) > 128
        or len(versioned_ids) != len(set(versioned_ids))
        or any(not isinstance(item, str) or not MIGRATION_ID_RE.fullmatch(item) for item in versioned_ids)
    ):
        raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_EVIDENCE_INVALID")
    return payload


def _database_update_plan(
    *,
    source_root: Path,
    target_root: Path,
    source_manifest: ReleaseManifestV2,
    target_manifest: ReleaseManifestV2,
    database_path: Path,
    registry: tuple[MigrationStep, ...],
    operation_id: str,
) -> dict[str, Any]:
    mode = _database_contract_mode(source_manifest, target_manifest)
    if mode not in {"same-schema-no-migration", "versioned-forward-migration"}:
        raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_CONTRACT_UNSUPPORTED")

    steps = validate_registry(registry)
    source_evidence = _database_evidence(source_root, source_manifest)
    target_evidence = _database_evidence(target_root, target_manifest)
    inspection = inspect_schema_metadata(database_path)
    registry_sha = migration_registry_sha256(steps)
    registry_ids = [step.migration_id for step in steps]
    if (
        inspection.get("current_state") != STATE_READY
        or inspection.get("schema_version") != source_evidence.get("schema_version")
        or inspection.get("schema_sha256") != source_evidence.get("schema_objects_sha256")
        or source_evidence.get("migration_registry_sha256") != registry_sha
        or source_evidence.get("versioned_migration_ids") != registry_ids
    ):
        raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_SOURCE_IDENTITY_MISMATCH")
    if mode == "same-schema-no-migration":
        target_registry_ids = target_evidence["versioned_migration_ids"]
        if (
            target_evidence["schema_version"] != source_evidence["schema_version"]
            or target_evidence["schema_objects_sha256"] != source_evidence["schema_objects_sha256"]
            or target_registry_ids[: len(registry_ids)] != registry_ids
        ):
            raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_CONTRACT_UNSUPPORTED")
        return {
            "mode": mode,
            "registry_staged": target_registry_ids != registry_ids,
            "target_migration_registry_sha256": target_evidence["migration_registry_sha256"],
            "target_versioned_migration_ids": target_registry_ids,
        }
    if (
        target_evidence.get("migration_registry_sha256") != registry_sha
        or target_evidence.get("versioned_migration_ids") != registry_ids
    ):
        raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_MIGRATION_PLAN_INVALID")
    target_version = target_evidence.get("schema_version")
    target_schema_sha = target_evidence.get("schema_objects_sha256")
    if (
        type(target_version) is not int
        or target_version <= source_evidence["schema_version"]
        or not SHA256_RE.fullmatch(str(target_schema_sha))
        or target_schema_sha == source_evidence["schema_objects_sha256"]
    ):
        raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_EVIDENCE_INVALID")
    try:
        migration_plan = plan_migrations(
            database_path,
            target_version=target_version,
            registry=steps,
        )
    except DataMigrationError as exc:
        raise UpdateMvpError(exc.code) from exc
    migration_ids = [step.migration_id for step in migration_plan.steps]
    if not migration_ids or migration_plan.registry_sha256 != registry_sha:
        raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_MIGRATION_PLAN_INVALID")
    return {
        "mode": mode,
        "operation_id": operation_id,
        "source_schema_version": migration_plan.current_version,
        "target_schema_version": migration_plan.target_version,
        "source_schema_sha256": migration_plan.source_schema_sha256,
        "target_schema_sha256": target_schema_sha,
        "migration_registry_sha256": migration_plan.registry_sha256,
        "migration_ids": migration_ids,
    }


@dataclass(frozen=True)
class PreparedUpdate:
    job_id: str
    source_release_id: str
    target_release_id: str
    target_manifest_sha256: str
    target_payload_tree_sha256: str
    database_update_mode: str

    def public(self) -> dict[str, str]:
        return {
            "job_id": self.job_id,
            "source_release_id": self.source_release_id,
            "target_release_id": self.target_release_id,
            "target_manifest_sha256": self.target_manifest_sha256,
            "target_payload_tree_sha256": self.target_payload_tree_sha256,
            "database_update_mode": self.database_update_mode,
        }


class UpdateMvpService:
    def __init__(
        self,
        roots: PathRoots,
        *,
        database_path: Path | None = None,
        migration_registry: tuple[MigrationStep, ...] = DEFAULT_MIGRATIONS,
    ) -> None:
        self.roots = roots
        self.store = UpdateJobStore(roots)
        self.database_path = Path(database_path) if database_path is not None else roots.DATA_ROOT / "enterprise.db"
        self.migration_registry = validate_registry(migration_registry)

    def prepare_from_artifacts(self, *, actor_user_id: str, manifest_path: Path, archive_path: Path, inventory_path: Path) -> PreparedUpdate:
        job_id, job_root = self.store.create(actor_user_id)
        partial: Path | None = None
        partial_identity: tuple[int, int] | None = None
        try:
            manifest_copy = job_root / "ops-release-manifest-v2.json"
            inventory_copy = job_root / "release-payload-inventory.json"
            archive_copy = job_root / "release.zip"
            _copy_bounded(Path(manifest_path), manifest_copy, MANIFEST_MAX_BYTES)
            _copy_bounded(Path(inventory_path), inventory_copy, INVENTORY_MAX_BYTES)
            _copy_bounded(Path(archive_path), archive_copy, MAX_ARCHIVE_BYTES)
            verification = verify_release_manifest_v2(manifest_copy, archive_copy, inventory_copy)
            target_manifest = read_release_manifest_v2(manifest_copy)
            source_pointer = read_current_release_result_from_state_root(self.roots.STATE_ROOT)
            source_manifest = read_release_manifest_v2(self.roots.APP_ROOT / "release-manifest.json")
            if source_manifest.release_id != source_pointer.release.release_id:
                raise UpdateMvpError("SYSTEM_UPDATE_SOURCE_IDENTITY_MISMATCH")
            source_version = str(source_manifest.section("identity")["release_version"])
            target_version = str(target_manifest.section("identity")["release_version"])
            if compare_versions(source_version, target_version) != "newer":
                raise UpdateMvpError("SYSTEM_UPDATE_TARGET_NOT_NEWER")
            target_root = self.roots.RELEASE_ROOT / validate_release_component(target_manifest.release_id)
            try:
                assert_no_reparse_ancestors(target_root, allow_missing=True)
            except PathSafetyError as exc:
                raise UpdateMvpError("SYSTEM_UPDATE_TARGET_PATH_UNSAFE") from exc
            # Publication must be a same-volume rename. Artifacts and job
            # evidence remain in STAGING_ROOT, while the owned partial Release
            # is a hidden sibling of the final target under RELEASE_ROOT.
            partial = self.roots.RELEASE_ROOT / f".{target_manifest.release_id}.{job_id}.partial"
            assert_no_reparse_ancestors(partial, allow_missing=True)
            materialize_release_fixture(manifest_copy, archive_copy, inventory_copy, partial)
            partial_stat = partial.stat(follow_symlinks=False)
            partial_identity = (partial_stat.st_dev, partial_stat.st_ino)
            if target_root.exists():
                verify_materialized_release(
                    target_root,
                    manifest_path=target_root / "release-manifest.json",
                    inventory_path=target_root / str(target_manifest.section("release_payload")["inventory_path"]),
                )
                existing = read_release_manifest_v2(target_root / "release-manifest.json")
                if existing.raw_sha256 != target_manifest.raw_sha256:
                    raise UpdateMvpError("SYSTEM_UPDATE_TARGET_RELEASE_COLLISION", status_code=409)
                _remove_owned_tree(partial, partial_identity)
                partial_identity = None
            else:
                os.replace(partial, target_root)
                partial_identity = None
            database_update = _database_update_plan(
                source_root=self.roots.APP_ROOT,
                target_root=target_root,
                source_manifest=source_manifest,
                target_manifest=target_manifest,
                database_path=self.database_path,
                registry=self.migration_registry,
                operation_id=job_id,
            )
            plan = {
                "job_id": job_id,
                "actor_user_id": actor_user_id,
                "source_release_id": source_manifest.release_id,
                "source_pointer_sha256": source_pointer.raw_sha256,
                "source_manifest_sha256": source_manifest.raw_sha256,
                "target_release_id": target_manifest.release_id,
                "target_manifest_sha256": target_manifest.raw_sha256,
                "target_inventory_sha256": verification.inventory_sha256,
                "target_payload_tree_sha256": verification.payload_tree_sha256,
                "database_update": database_update,
                "created_at": utc_now(),
            }
            plan_sha = self.store.write_plan(job_id, plan)
            self.store.write_status(
                job_id,
                "READY",
                actor_user_id=actor_user_id,
                result_code="SYSTEM_UPDATE_READY",
                source_release_id=source_manifest.release_id,
                target_release_id=target_manifest.release_id,
                plan_sha256=plan_sha,
                database_update_mode=database_update["mode"],
            )
            self.store.append_event(job_id, "READY", "SYSTEM_UPDATE_READY", source_release_id=source_manifest.release_id, target_release_id=target_manifest.release_id)
            return PreparedUpdate(job_id, source_manifest.release_id, target_manifest.release_id, target_manifest.raw_sha256, verification.payload_tree_sha256, database_update["mode"])
        except Exception as exc:
            if partial is not None:
                _remove_owned_tree(partial, partial_identity)
            code = getattr(exc, "code", "SYSTEM_UPDATE_PREPARE_FAILED")
            self.store.write_status(job_id, "FAILED", actor_user_id=actor_user_id, result_code=str(code))
            self.store.append_event(job_id, "FAILED", str(code))
            raise


def _pointer_for(target: ReleaseManifestV2, previous_release_id: str | None) -> CurrentRelease:
    return CurrentRelease(
        schema_version=CURRENT_RELEASE_SCHEMA,
        release_id=target.release_id,
        app_root_relative=f"releases/{target.release_id}",
        manifest_sha256=target.raw_sha256,
        activated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        previous_release_id=previous_release_id,
    )


def _run_launcher(app_root: Path, command: str, *, timeout: int = 120) -> tuple[int, dict[str, Any]]:
    python = app_root / "python" / "python.exe"
    launcher = app_root / "enterprise" / "runtime" / "launcher.py"
    if not python.is_file() or not launcher.is_file():
        return 2, {"code": "SYSTEM_UPDATE_FORMAL_ENTRY_MISSING"}
    environment = dict(os.environ)
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT"):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"; environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [str(python), "-I", "-B", str(launcher), "portable", command],
            cwd=str(app_root), env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 2, {"code": "SYSTEM_UPDATE_FORMAL_ENTRY_FAILED"}
    lines = completed.stdout.decode("utf-8", errors="replace").splitlines()
    payload: dict[str, Any] = {}
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if type(value) is dict:
            payload = value; break
    if not payload:
        payload = {"code": "SYSTEM_UPDATE_FORMAL_ENTRY_OUTPUT_INVALID"}
    return int(completed.returncode), payload


def _database_result_record(roots: PathRoots, result: MigrationResult) -> dict[str, Any]:
    try:
        manifest_relative = result.backup.manifest_path.relative_to(roots.BACKUP_ROOT).as_posix()
    except ValueError as exc:
        raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_BACKUP_PATH_INVALID") from exc
    return {
        "operation_id": result.operation_id,
        "source_schema_version": result.source_version,
        "target_schema_version": result.target_version,
        "migration_ids": list(result.migration_ids),
        "source_schema_sha256": result.source_schema_sha256,
        "target_schema_sha256": result.target_schema_sha256,
        "post_migration_database_sha256": result.post_migration_database_sha256,
        "backup_manifest_relative_path": manifest_relative,
        "backup_manifest_sha256": result.backup.manifest_sha256,
        "backup_database_sha256": result.backup.backup_sha256,
    }


def execute_update_job(
    roots: PathRoots,
    job_id: str,
    *,
    launcher: Callable[[Path, str], tuple[int, dict[str, Any]]] = _run_launcher,
    database_path: Path | None = None,
    migration_registry: tuple[MigrationStep, ...] = DEFAULT_MIGRATIONS,
) -> int:
    """Execute one READY job after the source supervisor has handed off."""
    store = UpdateJobStore(roots)
    plan = store.read_plan(job_id)
    status = store.read_status(job_id)
    actor = str(plan.get("actor_user_id") or "")
    if status.get("state") != "UPDATING" or status.get("actor_user_id") != actor:
        raise UpdateMvpError("SYSTEM_UPDATE_JOB_NOT_EXECUTABLE", status_code=409)
    source_id = validate_release_component(plan.get("source_release_id"))
    target_id = validate_release_component(plan.get("target_release_id"))
    source_root = roots.RELEASE_ROOT / source_id
    target_root = roots.RELEASE_ROOT / target_id
    pointer_switched = False
    migration_result: MigrationResult | None = None
    database_result_sha: str | None = None
    database_path = Path(database_path) if database_path is not None else roots.DATA_ROOT / "enterprise.db"
    registry = validate_registry(migration_registry)
    database_update = plan.get("database_update") or {"mode": "same-schema-no-migration"}
    if type(database_update) is not dict:
        raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_MIGRATION_PLAN_INVALID")
    database_mode = database_update.get("mode")
    if database_mode not in {"same-schema-no-migration", "versioned-forward-migration"}:
        raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_MIGRATION_PLAN_INVALID")
    lock = store.acquire_execution_lock(job_id)
    validation_failure = "start_failed"
    try:
        source_manifest = read_release_manifest_v2(source_root / "release-manifest.json")
        if source_manifest.raw_sha256 != plan.get("source_manifest_sha256"):
            raise UpdateMvpError("SYSTEM_UPDATE_SOURCE_IDENTITY_MISMATCH")
        verify_materialized_release(
            source_root,
            inventory_path=source_root / str(source_manifest.section("release_payload")["inventory_path"]),
        )
        target_manifest = read_release_manifest_v2(target_root / "release-manifest.json")
        if target_manifest.raw_sha256 != plan.get("target_manifest_sha256"):
            raise UpdateMvpError("SYSTEM_UPDATE_TARGET_IDENTITY_MISMATCH")
        target_verification = verify_materialized_release(
            target_root,
            inventory_path=target_root / str(target_manifest.section("release_payload")["inventory_path"]),
        )
        if target_verification.payload_tree_sha256 != plan.get("target_payload_tree_sha256"):
            raise UpdateMvpError("SYSTEM_UPDATE_TARGET_IDENTITY_MISMATCH")
        if not _database_contract_compatible(source_manifest, target_manifest):
            raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_CONTRACT_UNSUPPORTED")
        expected_database_update = _database_update_plan(
            source_root=source_root,
            target_root=target_root,
            source_manifest=source_manifest,
            target_manifest=target_manifest,
            database_path=database_path,
            registry=registry,
            operation_id=job_id,
        )
        if database_update != expected_database_update:
            raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_MIGRATION_PLAN_INVALID")
        current = read_current_release_result_from_state_root(roots.STATE_ROOT)
        if current.release.release_id != source_id or current.raw_sha256 != plan.get("source_pointer_sha256"):
            raise UpdateMvpError("SYSTEM_UPDATE_EXPECTED_CURRENT_MISMATCH", status_code=409)
        if database_mode == "versioned-forward-migration":
            expected_registry_sha = migration_registry_sha256(registry)
            if (
                database_update.get("operation_id") != job_id
                or database_update.get("migration_registry_sha256") != expected_registry_sha
                or database_update.get("migration_ids")
                != [step.migration_id for step in plan_migrations(
                    database_path,
                    target_version=int(database_update.get("target_schema_version")),
                    registry=registry,
                ).steps]
            ):
                raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_MIGRATION_PLAN_INVALID")
            store.write_status(
                job_id,
                "MIGRATING",
                actor_user_id=actor,
                result_code="SYSTEM_UPDATE_DATABASE_MIGRATING",
                source_release_id=source_id,
                target_release_id=target_id,
                database_update_mode=database_mode,
            )
            store.append_event(job_id, "MIGRATING", "SYSTEM_UPDATE_DATABASE_MIGRATING")
            migration_result = apply_versioned_migrations(
                database_path,
                roots.BACKUP_ROOT / "system-update",
                operation_id=job_id,
                target_version=int(database_update["target_schema_version"]),
                expected_target_schema_sha256=str(database_update["target_schema_sha256"]),
                registry=registry,
            )
            if (
                migration_result.source_version != database_update.get("source_schema_version")
                or migration_result.target_version != database_update.get("target_schema_version")
                or list(migration_result.migration_ids) != database_update.get("migration_ids")
                or migration_result.source_schema_sha256 != database_update.get("source_schema_sha256")
                or migration_result.target_schema_sha256 != database_update.get("target_schema_sha256")
            ):
                raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_MIGRATION_RESULT_MISMATCH")
            database_result_sha = store.write_database_result(
                job_id,
                _database_result_record(roots, migration_result),
            )
            store.append_event(
                job_id,
                "MIGRATING",
                "SYSTEM_UPDATE_DATABASE_MIGRATED",
                database_result_sha256=database_result_sha,
            )
        store.write_status(job_id, "RESTARTING", actor_user_id=actor, result_code="SYSTEM_UPDATE_SWITCHING", source_release_id=source_id, target_release_id=target_id)
        atomic_write_current_release(
            roots,
            _pointer_for(target_manifest, source_id),
            expected_manifest_sha256=target_manifest.raw_sha256,
            expected_existing_raw_sha256=current.raw_sha256,
        )
        pointer_switched = True
        start_exit, start_payload = launcher(target_root, "start")
        if start_exit != 0:
            raise UpdateMvpError(str(start_payload.get("code") or "SYSTEM_UPDATE_TARGET_START_FAILED"))
        validation_failure = "health_failed"
        store.write_status(job_id, "VERIFYING", actor_user_id=actor, result_code="SYSTEM_UPDATE_VERIFYING", source_release_id=source_id, target_release_id=target_id)
        health_exit, health_payload = launcher(target_root, "health")
        if health_exit != 0:
            raise UpdateMvpError(str(health_payload.get("code") or "SYSTEM_UPDATE_TARGET_HEALTH_FAILED"))
        if migration_result is not None:
            finalize_release_database_validation(
                database_path,
                migration_result,
                validation_result="healthy",
            )
        success_fields: dict[str, Any] = {}
        if database_result_sha is not None:
            success_fields = {
                "database_update_mode": database_mode,
                "database_result_sha256": database_result_sha,
            }
        store.write_status(
            job_id,
            "SUCCEEDED",
            actor_user_id=actor,
            result_code="SYSTEM_UPDATE_SUCCEEDED",
            source_release_id=source_id,
            target_release_id=target_id,
            **success_fields,
        )
        store.append_event(job_id, "SUCCEEDED", "SYSTEM_UPDATE_SUCCEEDED", source_release_id=source_id, target_release_id=target_id)
        return 0
    except Exception as exc:
        failure_code = str(getattr(exc, "code", "SYSTEM_UPDATE_EXECUTION_FAILED"))
        database_may_have_changed = bool(getattr(exc, "database_may_have_changed", False))
        if not pointer_switched:
            try:
                pointer_switched = read_current_release_result_from_state_root(roots.STATE_ROOT).release.release_id == target_id
            except Exception:
                pointer_switched = False
        if database_mode == "versioned-forward-migration" and migration_result is None:
            # No MigrationResult does not prove that the transaction never
            # committed: post-commit hashing/inspection can still raise. Do
            # not boot the old release until both persisted identities prove
            # that its database contract is still intact.
            source_state_intact = False
            if not database_may_have_changed:
                try:
                    current_pointer = read_current_release_result_from_state_root(roots.STATE_ROOT)
                    schema = inspect_schema_metadata(database_path)
                    source_state_intact = (
                        current_pointer.release.release_id == source_id
                        and current_pointer.raw_sha256 == plan.get("source_pointer_sha256")
                        and schema.get("current_state") == STATE_READY
                        and schema.get("schema_version") == database_update.get("source_schema_version")
                        and schema.get("schema_sha256") == database_update.get("source_schema_sha256")
                    )
                except Exception:
                    source_state_intact = False
            if not source_state_intact:
                store.write_status(
                    job_id,
                    "RECOVERY_REQUIRED",
                    actor_user_id=actor,
                    result_code=failure_code,
                    source_release_id=source_id,
                    target_release_id=target_id,
                    recovery_required=True,
                    database_update_mode=database_mode,
                )
                store.append_event(job_id, "RECOVERY_REQUIRED", failure_code)
                return 2
            source_start, _ = launcher(source_root, "start")
            source_health, _ = launcher(source_root, "health") if source_start == 0 else (2, {})
            if source_start != 0 or source_health != 0:
                recovery_code = "SYSTEM_UPDATE_SOURCE_RECOVERY_FAILED"
                store.write_status(
                    job_id,
                    "RECOVERY_REQUIRED",
                    actor_user_id=actor,
                    result_code=recovery_code,
                    source_release_id=source_id,
                    target_release_id=target_id,
                    recovery_required=True,
                    database_update_mode=database_mode,
                )
                store.append_event(job_id, "RECOVERY_REQUIRED", recovery_code)
                return 2
            store.write_status(
                job_id,
                "FAILED",
                actor_user_id=actor,
                result_code=failure_code,
                source_release_id=source_id,
                target_release_id=target_id,
                database_update_mode=database_mode,
            )
            store.append_event(job_id, "FAILED", failure_code)
            return 2
        if migration_result is not None:
            try:
                if pointer_switched:
                    launcher(target_root, "stop")
                finalization = finalize_release_database_validation(
                    database_path,
                    migration_result,
                    validation_result=validation_failure,
                )
                if finalization.database_restored is not True:
                    raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_RESTORE_INCOMPLETE")
                current = read_current_release_result_from_state_root(roots.STATE_ROOT)
                if current.release.release_id == target_id:
                    atomic_write_current_release(
                        roots,
                        _pointer_for(source_manifest, target_id),
                        expected_manifest_sha256=source_manifest.raw_sha256,
                        expected_existing_raw_sha256=current.raw_sha256,
                    )
                elif current.release.release_id != source_id:
                    raise UpdateMvpError("SYSTEM_UPDATE_ROLLBACK_POINTER_MISMATCH")
                source_start, _ = launcher(source_root, "start")
                source_health, _ = launcher(source_root, "health") if source_start == 0 else (2, {})
                if source_start != 0 or source_health != 0:
                    raise UpdateMvpError("SYSTEM_UPDATE_ROLLBACK_HEALTH_FAILED")
                store.write_status(
                    job_id,
                    "ROLLED_BACK",
                    actor_user_id=actor,
                    result_code=failure_code,
                    source_release_id=source_id,
                    target_release_id=target_id,
                    database_restored=True,
                    database_update_mode=database_mode,
                    database_result_sha256=database_result_sha,
                )
                store.append_event(job_id, "ROLLED_BACK", failure_code, database_restored=True)
                return 2
            except Exception as restore_exc:
                recovery_code = str(getattr(restore_exc, "code", "SYSTEM_UPDATE_DATABASE_RESTORE_FAILED"))
                store.write_status(
                    job_id,
                    "RECOVERY_REQUIRED",
                    actor_user_id=actor,
                    result_code=recovery_code,
                    source_release_id=source_id,
                    target_release_id=target_id,
                    recovery_required=True,
                    database_update_mode=database_mode,
                    database_result_sha256=database_result_sha,
                )
                store.append_event(job_id, "RECOVERY_REQUIRED", recovery_code)
                return 2
        if not pointer_switched:
            store.write_status(job_id, "FAILED", actor_user_id=actor, result_code=failure_code, source_release_id=source_id, target_release_id=target_id)
            store.append_event(job_id, "FAILED", failure_code)
            return 2
        store.write_status(job_id, "ROLLING_BACK", actor_user_id=actor, result_code=failure_code, source_release_id=source_id, target_release_id=target_id)
        store.append_event(job_id, "ROLLING_BACK", failure_code)
        try:
            launcher(target_root, "stop")
            current = read_current_release_result_from_state_root(roots.STATE_ROOT)
            if current.release.release_id != target_id:
                raise UpdateMvpError("SYSTEM_UPDATE_ROLLBACK_POINTER_MISMATCH")
            atomic_write_current_release(
                roots,
                _pointer_for(source_manifest, target_id),
                expected_manifest_sha256=source_manifest.raw_sha256,
                expected_existing_raw_sha256=current.raw_sha256,
            )
            source_start, _ = launcher(source_root, "start")
            source_health, _ = launcher(source_root, "health")
            if source_start != 0 or source_health != 0:
                raise UpdateMvpError("SYSTEM_UPDATE_ROLLBACK_HEALTH_FAILED")
            store.write_status(job_id, "ROLLED_BACK", actor_user_id=actor, result_code=failure_code, source_release_id=source_id, target_release_id=target_id)
            store.append_event(job_id, "ROLLED_BACK", failure_code)
            return 2
        except Exception as rollback_exc:
            rollback_code = str(getattr(rollback_exc, "code", "SYSTEM_UPDATE_ROLLBACK_FAILED"))
            store.write_status(job_id, "FAILED", actor_user_id=actor, result_code=rollback_code, source_release_id=source_id, target_release_id=target_id)
            store.append_event(job_id, "FAILED", rollback_code)
            return 2
    finally:
        store.release_execution_lock(lock, job_id)
