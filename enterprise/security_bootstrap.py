"""SEC-1B2 local-only controlled activation and first-bootstrap primitives.

Nothing in this module is wired to application startup or an HTTP route.  The
only intended caller is the explicitly invoked local runner after a human has
stopped the service and reviewed an executed backup.
"""

import hashlib
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from enterprise import db as enterprise_db
from enterprise.migrations.sec_1b1_role_auth import (
    MIGRATION_ID as ROLE_AUTH_MIGRATION_ID,
    ROLE_AUTH_READY,
    SCHEMA_LEGACY,
    SCHEMA_PARTIAL,
    apply_role_auth_migration_in_transaction,
    inspect_role_auth_schema,
)
from enterprise.migrations.sec_1b2_activation import (
    BOOTSTRAP_MISSING,
    BOOTSTRAP_PARTIAL,
    BOOTSTRAP_READY,
    BOOTSTRAP_TABLE,
    BootstrapLifecycleMigrationError,
    ensure_bootstrap_lifecycle_schema_in_transaction,
    inspect_bootstrap_lifecycle_connection,
)
from enterprise.migrations.sec_1f0_security_audit import (
    SecurityAuditMigrationError,
    apply_security_audit_migration_in_transaction,
)
from enterprise.migrations.sqlite_existing import open_existing_sqlite
from enterprise.roles import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
    normalize_auth_version,
    normalize_role,
    role_from_legacy_is_admin,
)
from enterprise.security_audit import (
    SECURITY_AUDIT_MISSING,
    SECURITY_AUDIT_PARTIAL,
    SECURITY_AUDIT_READY,
    SecurityAuditError,
    append_security_audit_event,
    inspect_security_audit_connection,
)


SEC_1B2_PLAN_VERSION = "sec-1b2-activation-plan-v1"
MAX_PLAN_AGE_MS = 24 * 60 * 60 * 1000
SAFE_JOURNAL_MODES = frozenset({"delete"})
LIFECYCLE_UNINITIALIZED = "UNINITIALIZED"
LIFECYCLE_ACTIVE = "ACTIVE"
LIFECYCLE_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
LIFECYCLE_SCHEMA_PARTIAL = "LIFECYCLE_SCHEMA_PARTIAL"


class SecurityBootstrapError(RuntimeError):
    """Base error for a controlled local bootstrap failure."""

    code = "SEC_1B2_FAILED"
    public_message = "Controlled activation failed"


class SecurityBootstrapValidationError(SecurityBootstrapError):
    code = "SEC_1B2_VALIDATION_FAILED"
    public_message = "Activation input validation failed"


class SecurityBootstrapPlanError(SecurityBootstrapError):
    code = "SEC_1B2_PLAN_INVALID"
    public_message = "Activation plan is invalid or stale"


class SecurityBootstrapBackupError(SecurityBootstrapError):
    code = "SEC_1B2_BACKUP_INVALID"
    public_message = "Executed backup verification failed"


class SecurityBootstrapLifecycleError(SecurityBootstrapError):
    code = "SEC_1B2_LIFECYCLE_BLOCKED"
    public_message = "Bootstrap lifecycle state does not allow activation"


class SecurityBootstrapLockError(SecurityBootstrapError):
    code = "SEC_1B2_EXCLUSIVE_LOCK_UNAVAILABLE"
    public_message = "Could not acquire the required exclusive database lock"


class SecurityBootstrapIntegrityError(SecurityBootstrapError):
    code = "SEC_1B2_INTEGRITY_FAILED"
    public_message = "Controlled activation integrity verification failed"


class SecurityBootstrapPasswordError(SecurityBootstrapError):
    code = "SEC_1B2_PASSWORD_REJECTED"
    public_message = "Local administrator password verification failed"


def _utc_now_ms() -> int:
    return int(time.time() * 1000)


def _required_text(name: str, value: object, *, maximum: int = 2048) -> str:
    if not isinstance(value, str) or not value or value.isspace() or len(value) > maximum:
        raise SecurityBootstrapValidationError(f"{name} is invalid")
    return value


def _required_identifier(name: str, value: object) -> str:
    return _required_text(name, value, maximum=128)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _plan_hash(plan_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(plan_without_hash).encode("utf-8")).hexdigest()


def _existing_regular_file(value: str | os.PathLike[str], *, label: str) -> Path:
    path = Path(value).expanduser()
    try:
        if not path.exists() or not path.is_file():
            raise SecurityBootstrapValidationError(f"{label} is not an existing regular file")
        return path.resolve(strict=True)
    except SecurityBootstrapError:
        raise
    except OSError as exc:
        raise SecurityBootstrapValidationError(f"{label} could not be validated") from exc


def _parse_utc_time(value: object) -> int:
    if not isinstance(value, str) or not value:
        raise SecurityBootstrapBackupError("backup timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SecurityBootstrapBackupError("backup timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise SecurityBootstrapBackupError("backup timestamp timezone is missing")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _is_hex_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value.casefold())


def _validate_backup_manifest(path_value: str | os.PathLike[str], *, now_ms: int) -> dict[str, Any]:
    """Validate the real OPS-2A executed-manifest fields without exposing paths."""
    manifest_path = _existing_regular_file(path_value, label="backup manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SecurityBootstrapBackupError("backup manifest could not be read") from exc
    if not isinstance(manifest, dict) or manifest.get("kind") != "backup-manifest":
        raise SecurityBootstrapBackupError("backup manifest format is not supported")
    if manifest.get("dry_run") is not False:
        raise SecurityBootstrapBackupError("backup manifest is not an executed backup")
    if manifest.get("status") not in {"pass", "success"}:
        raise SecurityBootstrapBackupError("backup manifest does not report success")
    if manifest.get("sqlite_backup_status") != "success":
        raise SecurityBootstrapBackupError("SQLite backup did not report success")
    warnings = manifest.get("warnings", [])
    if not isinstance(warnings, list) or any("critical" in str(item).casefold() for item in warnings):
        raise SecurityBootstrapBackupError("backup manifest contains critical warnings")
    created_at = _parse_utc_time(manifest.get("copied_at") or manifest.get("generated_at"))
    if created_at > now_ms or now_ms - created_at > MAX_PLAN_AGE_MS:
        raise SecurityBootstrapBackupError("backup manifest is outside the allowed freshness window")
    backup_path_value = manifest.get("sqlite_backup_path")
    if not isinstance(backup_path_value, str) or not backup_path_value:
        raise SecurityBootstrapBackupError("backup manifest lacks SQLite backup path")
    backup_path = Path(backup_path_value).expanduser()
    if not backup_path.is_absolute():
        backup_path = manifest_path.parent / backup_path
    try:
        backup_path = backup_path.resolve(strict=True)
        if not backup_path.is_file():
            raise SecurityBootstrapBackupError("backup database is not an existing regular file")
    except SecurityBootstrapError:
        raise
    except OSError as exc:
        raise SecurityBootstrapBackupError("backup database could not be validated") from exc
    expected_size = manifest.get("sqlite_backup_size_bytes")
    expected_hash = manifest.get("sqlite_backup_sha256")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 1:
        raise SecurityBootstrapBackupError("backup manifest lacks SQLite backup size")
    if not _is_hex_sha256(expected_hash):
        raise SecurityBootstrapBackupError("backup manifest lacks SQLite backup checksum")
    try:
        if backup_path.stat().st_size != expected_size or _sha256_file(backup_path) != expected_hash.casefold():
            raise SecurityBootstrapBackupError("backup database integrity verification failed")
    except SecurityBootstrapError:
        raise
    except OSError as exc:
        raise SecurityBootstrapBackupError("backup database integrity could not be verified") from exc
    backup_id = _required_identifier("backup_id", manifest.get("backup_id"))
    return {
        "backup_manifest_sha256": _sha256_file(manifest_path),
        "backup_id": backup_id,
        "backup_created_at": created_at,
        "sqlite_backup_sha256": expected_hash.casefold(),
        "sqlite_backup_size_bytes": expected_size,
    }


def _database_runtime_state(conn: sqlite3.Connection, database_path: Path) -> dict[str, Any]:
    try:
        journal_mode = str(conn.execute("PRAGMA main.journal_mode").fetchone()[0]).casefold()
    except (sqlite3.Error, IndexError, TypeError) as exc:
        raise SecurityBootstrapValidationError("SQLite journal mode could not be inspected") from exc
    sidecars = [
        suffix
        for suffix in ("-wal", "-shm")
        if Path(f"{database_path}{suffix}").exists()
    ]
    if journal_mode not in SAFE_JOURNAL_MODES or sidecars:
        raise SecurityBootstrapValidationError("SQLite journal or sidecar state is not safe for exclusive activation")
    try:
        return {
            "journal_mode": journal_mode,
            "database_size": database_path.stat().st_size,
            "database_sha256": _sha256_file(database_path),
            "sidecar_files": sidecars,
        }
    except OSError as exc:
        raise SecurityBootstrapValidationError("database fingerprint could not be calculated") from exc


def _raw_role_from_user(row: sqlite3.Row, role_auth_state: str) -> str:
    try:
        if role_auth_state == SCHEMA_LEGACY:
            if type(row["is_admin"]) is not int or row["is_admin"] not in {0, 1}:
                raise ValueError("legacy administrator flag is invalid")
            return role_from_legacy_is_admin(row["is_admin"])
        if role_auth_state == ROLE_AUTH_READY:
            if type(row["is_admin"]) is not int or row["is_admin"] not in {0, 1}:
                raise ValueError("administrator flag is invalid")
            role = normalize_role(row["role"])
            if (role == ROLE_USER and row["is_admin"] != 0) or (
                role in {ROLE_ADMIN, ROLE_SUPER_ADMIN} and row["is_admin"] != 1
            ):
                raise ValueError("role and administrator flag differ")
            normalize_auth_version(row["auth_version"])
            return role
    except (KeyError, ValueError) as exc:
        raise SecurityBootstrapIntegrityError("user role data is invalid") from exc
    raise SecurityBootstrapIntegrityError("user role/auth schema is unsupported")


def _find_raw_user(conn: sqlite3.Connection, user_id: str, role_auth_state: str) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    if role_auth_state == ROLE_AUTH_READY:
        return conn.execute(
            """
            SELECT id, username, password_hash, display_name, is_admin, is_active,
                   role, auth_version, role_updated_at, role_updated_by
            FROM main.users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    return conn.execute(
        """
        SELECT id, username, password_hash, display_name, is_admin, is_active
        FROM main.users WHERE id = ?
        """,
        (user_id,),
    ).fetchone()


def _validate_raw_active_admin(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    username: str,
    role_auth_state: str,
) -> sqlite3.Row:
    row = _find_raw_user(conn, user_id, role_auth_state)
    if row is None:
        raise SecurityBootstrapValidationError("bootstrap target does not exist")
    if row["username"] != username:
        raise SecurityBootstrapValidationError("bootstrap target username confirmation does not match")
    if type(row["is_active"]) is not int or row["is_active"] != 1:
        raise SecurityBootstrapValidationError("bootstrap target must be an active administrator")
    if _raw_role_from_user(row, role_auth_state) != ROLE_ADMIN:
        raise SecurityBootstrapValidationError("bootstrap target must be an existing active administrator")
    return row


def _lifecycle_from_connection(conn: sqlite3.Connection) -> dict[str, Any]:
    role_auth = inspect_role_auth_schema(conn)
    audit = inspect_security_audit_connection(conn)
    bootstrap = inspect_bootstrap_lifecycle_connection(conn)
    role_state = role_auth["current_state"]
    audit_state = audit["current_state"]
    bootstrap_state = bootstrap["current_state"]
    super_admin_count = 0
    active_super_admin_count = 0
    if role_state == ROLE_AUTH_READY:
        super_admin_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM main.users WHERE role = ?",
                (ROLE_SUPER_ADMIN,),
            ).fetchone()[0]
        )
        active_super_admin_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM main.users WHERE role = ? AND is_active = 1",
                (ROLE_SUPER_ADMIN,),
            ).fetchone()[0]
        )
    marker = bootstrap.get("marker") if bootstrap_state == BOOTSTRAP_READY else None
    marker_target: sqlite3.Row | None = None
    marker_target_role: str | None = None
    marker_target_is_active: bool | None = None
    audit_matches = False
    warnings = list(role_auth.get("warnings", [])) + list(audit.get("warnings", [])) + list(bootstrap.get("warnings", []))
    if marker:
        if role_state == ROLE_AUTH_READY:
            marker_target = _find_raw_user(conn, str(marker["bootstrap_target_user_id"]), role_state)
            if marker_target is not None:
                try:
                    marker_target_role = _raw_role_from_user(marker_target, role_state)
                    marker_target_is_active = type(marker_target["is_active"]) is int and marker_target["is_active"] == 1
                except SecurityBootstrapIntegrityError:
                    marker_target_role = None
                    marker_target_is_active = False
        if audit_state == SECURITY_AUDIT_READY:
            audit_matches = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM main.security_audit_events
                    WHERE operation_id = ?
                      AND action = 'security.super_admin.bootstrap'
                      AND result = 'success'
                    """,
                    (marker["bootstrap_operation_id"],),
                ).fetchone()[0]
            ) == 1

    if bootstrap_state == BOOTSTRAP_PARTIAL:
        lifecycle_state = LIFECYCLE_SCHEMA_PARTIAL
    elif marker is None:
        lifecycle_state = (
            LIFECYCLE_UNINITIALIZED if super_admin_count == 0 else LIFECYCLE_RECOVERY_REQUIRED
        )
    elif (
        role_state == ROLE_AUTH_READY
        and audit_state == SECURITY_AUDIT_READY
        and marker_target is not None
        and marker_target_role == ROLE_SUPER_ADMIN
        and marker_target_is_active is True
        and active_super_admin_count >= 1
        and audit_matches
    ):
        lifecycle_state = LIFECYCLE_ACTIVE
    else:
        lifecycle_state = LIFECYCLE_RECOVERY_REQUIRED

    if lifecycle_state == LIFECYCLE_RECOVERY_REQUIRED:
        warnings.append("bootstrap lifecycle requires future break-glass review")
    if lifecycle_state == LIFECYCLE_SCHEMA_PARTIAL:
        warnings.append("bootstrap lifecycle schema requires manual review")
    return {
        "lifecycle_state": lifecycle_state,
        "bootstrap_schema_state": bootstrap_state,
        "marker_exists": marker is not None,
        "target_user_id": marker.get("bootstrap_target_user_id") if marker else None,
        "operation_id": marker.get("bootstrap_operation_id") if marker else None,
        "super_admin_count": super_admin_count,
        "active_super_admin_count": active_super_admin_count,
        "marker_target_exists": marker_target is not None if marker else None,
        "marker_target_role": marker_target_role,
        "marker_target_is_active": marker_target_is_active,
        "bootstrap_audit_matches": audit_matches if marker else None,
        "role_auth_state": role_state,
        "audit_state": audit_state,
        "role_auth_inspection": role_auth,
        "audit_inspection": audit,
        "bootstrap_inspection": bootstrap,
        "warnings": sorted(set(warnings)),
        "can_plan_first_bootstrap": (
            lifecycle_state == LIFECYCLE_UNINITIALIZED
            and role_state in {SCHEMA_LEGACY, ROLE_AUTH_READY}
            and audit_state in {SECURITY_AUDIT_MISSING, SECURITY_AUDIT_READY}
        ),
        "requires_break_glass": lifecycle_state == LIFECYCLE_RECOVERY_REQUIRED,
    }


def _assert_role_auth_inspection_is_safe(inspection: dict[str, Any]) -> None:
    if inspection.get("current_state") not in {SCHEMA_LEGACY, ROLE_AUTH_READY}:
        raise SecurityBootstrapLifecycleError("role/auth schema is not eligible for controlled activation")
    invalid_keys = (
        "invalid_legacy_is_admin_count",
        "invalid_ready_is_admin_count",
        "invalid_is_active_count",
        "invalid_role_count",
        "invalid_auth_version_count",
        "role_is_admin_mismatch_count",
    )
    if any(inspection.get(key, 0) for key in invalid_keys):
        raise SecurityBootstrapLifecycleError("role/auth user data requires manual review")
    if any(
        inspection.get(key)
        for key in ("temporary_shadow_objects", "temporary_triggers", "main_user_triggers")
    ):
        raise SecurityBootstrapLifecycleError("role/auth schema has unsupported temporary or trigger state")


def inspect_super_admin_lifecycle(
    source: sqlite3.Connection | str | os.PathLike[str],
) -> dict[str, Any]:
    """Inspect lifecycle state read-only without creating schema or users."""
    with open_existing_sqlite(
        source,
        mode="ro",
        error_type=SecurityBootstrapValidationError,
    ) as conn:
        try:
            return _lifecycle_from_connection(conn)
        except (sqlite3.Error, BootstrapLifecycleMigrationError) as exc:
            raise SecurityBootstrapValidationError("bootstrap lifecycle could not be inspected") from exc


def plan_sec_1b2_activation(
    *,
    database_path: str | os.PathLike[str],
    target_user_id: object,
    target_username: object,
    actor_label: object,
    reason: object,
    backup_manifest_path: str | os.PathLike[str],
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Create an in-memory, deterministic, read-only local activation plan."""
    target_id = _required_identifier("target_user_id", target_user_id)
    target_name = _required_text("target_username", target_username, maximum=128)
    label = _required_text("actor_label", actor_label, maximum=256)
    audit_reason = _required_text("reason", reason, maximum=2048)
    created_at = _utc_now_ms() if now_ms is None else now_ms
    if isinstance(created_at, bool) or not isinstance(created_at, int) or created_at < 0:
        raise SecurityBootstrapValidationError("plan time is invalid")
    path = _existing_regular_file(database_path, label="database")
    backup = _validate_backup_manifest(backup_manifest_path, now_ms=created_at)
    with open_existing_sqlite(path, mode="ro", error_type=SecurityBootstrapValidationError) as conn:
        runtime = _database_runtime_state(conn, path)
        lifecycle = _lifecycle_from_connection(conn)
        _assert_role_auth_inspection_is_safe(lifecycle["role_auth_inspection"])
        if lifecycle["lifecycle_state"] != LIFECYCLE_UNINITIALIZED:
            raise SecurityBootstrapLifecycleError("database is not eligible for first bootstrap")
        if lifecycle["role_auth_state"] == SCHEMA_PARTIAL or lifecycle["audit_state"] == SECURITY_AUDIT_PARTIAL:
            raise SecurityBootstrapLifecycleError("partial security schema blocks activation planning")
        if not lifecycle["can_plan_first_bootstrap"]:
            raise SecurityBootstrapLifecycleError("database cannot plan first bootstrap")
        target = _validate_raw_active_admin(
            conn,
            user_id=target_id,
            username=target_name,
            role_auth_state=lifecycle["role_auth_state"],
        )
        target_role = _raw_role_from_user(target, lifecycle["role_auth_state"])
        target_auth_version = 0 if lifecycle["role_auth_state"] == SCHEMA_LEGACY else int(target["auth_version"])

    operation_id = f"sec1b2-{uuid.uuid4().hex}"
    plan: dict[str, Any] = {
        "plan_version": SEC_1B2_PLAN_VERSION,
        "plan_id": f"plan-{uuid.uuid4().hex}",
        "operation_id": operation_id,
        "created_at": created_at,
        "expires_at": created_at + MAX_PLAN_AGE_MS,
        "database_size": runtime["database_size"],
        "database_sha256": runtime["database_sha256"],
        "backup_manifest_sha256": backup["backup_manifest_sha256"],
        "backup_id": backup["backup_id"],
        "backup_created_at": backup["backup_created_at"],
        "backup_database_sha256": backup["sqlite_backup_sha256"],
        "backup_database_size": backup["sqlite_backup_size_bytes"],
        "role_auth_state_before": lifecycle["role_auth_state"],
        "audit_state_before": lifecycle["audit_state"],
        "lifecycle_state_before": lifecycle["lifecycle_state"],
        "target_user_id": target_id,
        "target_username": target_name,
        "target_role_before": target_role,
        "target_auth_version_before": target_auth_version,
        "actor_user_id": target_id,
        "actor_label": label,
        "reason": audit_reason,
        "actions": [
            action
            for action, required in (
                ("security.audit.foundation.activate", lifecycle["audit_state"] == SECURITY_AUDIT_MISSING),
                ("security.role_auth.migration.activate", lifecycle["role_auth_state"] == SCHEMA_LEGACY),
                ("security.super_admin.bootstrap", True),
            )
            if required
        ],
        "expected_states_after": {
            "role_auth_state": ROLE_AUTH_READY,
            "audit_state": SECURITY_AUDIT_READY,
            "lifecycle_state": LIFECYCLE_ACTIVE,
            "active_super_admin_count": 1,
        },
        "session_impact": "all_existing_tokens_invalidated_and_reauthentication_required",
        "warnings": [],
    }
    plan["plan_hash"] = _plan_hash(plan)
    return plan


def _validated_plan(plan: object, expected_plan_hash: object, *, now_ms: int) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise SecurityBootstrapPlanError("activation plan is invalid")
    expected_hash = _required_text("expected_plan_hash", expected_plan_hash, maximum=64)
    stored_hash = plan.get("plan_hash")
    if not _is_hex_sha256(stored_hash) or stored_hash != expected_hash.casefold():
        raise SecurityBootstrapPlanError("activation plan hash does not match")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if _plan_hash(unsigned) != stored_hash:
        raise SecurityBootstrapPlanError("activation plan integrity verification failed")
    required = {
        "plan_version": SEC_1B2_PLAN_VERSION,
        "target_role_before": ROLE_ADMIN,
        "lifecycle_state_before": LIFECYCLE_UNINITIALIZED,
    }
    if any(plan.get(key) != value for key, value in required.items()):
        raise SecurityBootstrapPlanError("activation plan has unsupported values")
    expires_at = plan.get("expires_at")
    created_at = plan.get("created_at")
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or isinstance(created_at, bool)
        or not isinstance(created_at, int)
        or created_at < 0
        or expires_at < created_at
        or expires_at - created_at > MAX_PLAN_AGE_MS
        or now_ms > expires_at
    ):
        raise SecurityBootstrapPlanError("activation plan is expired")
    for key in ("database_sha256", "backup_manifest_sha256"):
        if not _is_hex_sha256(plan.get(key)):
            raise SecurityBootstrapPlanError("activation plan is missing an integrity fingerprint")
    for key in ("plan_id", "operation_id", "target_user_id", "target_username", "actor_user_id", "actor_label", "reason"):
        _required_text(key, plan.get(key))
    return plan


def _assert_plan_matches_runtime(
    *,
    plan: dict[str, Any],
    runtime: dict[str, Any],
    backup: dict[str, Any],
    target_user_id: str,
    target_username: str,
    actor_label: str,
    reason: str,
) -> None:
    if runtime["database_size"] != plan["database_size"] or runtime["database_sha256"] != plan["database_sha256"]:
        raise SecurityBootstrapPlanError("database changed after activation plan")
    if backup["backup_manifest_sha256"] != plan["backup_manifest_sha256"]:
        raise SecurityBootstrapPlanError("backup manifest changed after activation plan")
    if (
        plan["target_user_id"] != target_user_id
        or plan["target_username"] != target_username
        or plan["actor_user_id"] != target_user_id
        or plan["actor_label"] != actor_label
        or plan["reason"] != reason
    ):
        raise SecurityBootstrapPlanError("activation parameters do not match the approved plan")


def _verify_marker(conn: sqlite3.Connection, expected: dict[str, object]) -> None:
    rows = conn.execute(
        """
        SELECT singleton_id, bootstrap_completed_at, bootstrap_completed_by,
               bootstrap_target_user_id, bootstrap_operation_id,
               bootstrap_actor_label, created_at
        FROM main.security_governance_bootstrap WHERE singleton_id = 1
        """
    ).fetchall()
    if len(rows) != 1 or tuple(rows[0]) != tuple(expected[name] for name in (
        "singleton_id", "bootstrap_completed_at", "bootstrap_completed_by",
        "bootstrap_target_user_id", "bootstrap_operation_id",
        "bootstrap_actor_label", "created_at",
    )):
        raise SecurityBootstrapIntegrityError("bootstrap lifecycle marker was not confirmed")


def _verify_target_after_promotion(
    conn: sqlite3.Connection,
    *,
    target_id: str,
    before: sqlite3.Row,
    expected_auth_version: int,
    updated_at: int,
) -> sqlite3.Row:
    row = _find_raw_user(conn, target_id, ROLE_AUTH_READY)
    if row is None:
        raise SecurityBootstrapIntegrityError("bootstrap target was not found after promotion")
    expected = {
        "id": before["id"],
        "username": before["username"],
        "password_hash": before["password_hash"],
        "display_name": before["display_name"],
        "is_admin": 1,
        "is_active": 1,
        "role": ROLE_SUPER_ADMIN,
        "auth_version": expected_auth_version,
        "role_updated_at": updated_at,
        "role_updated_by": target_id,
    }
    for key, value in expected.items():
        if type(row[key]) is not type(value) or row[key] != value:
            raise SecurityBootstrapIntegrityError("bootstrap target promotion was not confirmed")
    return row


def execute_sec_1b2_activation(
    *,
    database_path: str | os.PathLike[str],
    plan: object,
    expected_plan_hash: object,
    backup_manifest_path: str | os.PathLike[str],
    target_user_id: object,
    target_username: object,
    actor_label: object,
    reason: object,
    current_password: object,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Execute the already approved first bootstrap in one BEGIN EXCLUSIVE transaction."""
    target_id = _required_identifier("target_user_id", target_user_id)
    target_name = _required_text("target_username", target_username, maximum=128)
    label = _required_text("actor_label", actor_label, maximum=256)
    audit_reason = _required_text("reason", reason, maximum=2048)
    if not isinstance(current_password, str) or not current_password:
        raise SecurityBootstrapPasswordError("local administrator password is required")
    started_at = _utc_now_ms() if now_ms is None else now_ms
    if isinstance(started_at, bool) or not isinstance(started_at, int) or started_at < 0:
        raise SecurityBootstrapValidationError("activation time is invalid")
    approved_plan = _validated_plan(plan, expected_plan_hash, now_ms=started_at)
    path = _existing_regular_file(database_path, label="database")
    backup = _validate_backup_manifest(backup_manifest_path, now_ms=started_at)
    event_ids: dict[str, str | None] = {
        "foundation": None,
        "role_auth_migration": None,
        "bootstrap": None,
    }
    before_states: dict[str, str] = {}
    after_states: dict[str, str] = {}
    target_before_auth_version: int | None = None
    target_after_auth_version: int | None = None
    database_sha256_before = ""
    transaction_started = False

    with open_existing_sqlite(path, mode="rw", error_type=SecurityBootstrapValidationError) as conn:
        try:
            conn.execute("PRAGMA busy_timeout = 250")
            conn.execute("BEGIN EXCLUSIVE")
            transaction_started = True
        except sqlite3.Error as exc:
            raise SecurityBootstrapLockError("required exclusive lock could not be acquired") from exc
        try:
            runtime = _database_runtime_state(conn, path)
            database_sha256_before = runtime["database_sha256"]
            _assert_plan_matches_runtime(
                plan=approved_plan,
                runtime=runtime,
                backup=backup,
                target_user_id=target_id,
                target_username=target_name,
                actor_label=label,
                reason=audit_reason,
            )
            lifecycle = _lifecycle_from_connection(conn)
            _assert_role_auth_inspection_is_safe(lifecycle["role_auth_inspection"])
            before_states = {
                "role_auth": lifecycle["role_auth_state"],
                "audit": lifecycle["audit_state"],
                "lifecycle": lifecycle["lifecycle_state"],
            }
            if lifecycle["lifecycle_state"] != LIFECYCLE_UNINITIALIZED:
                raise SecurityBootstrapLifecycleError("database is not eligible for first bootstrap")
            if lifecycle["role_auth_state"] == SCHEMA_PARTIAL or lifecycle["audit_state"] == SECURITY_AUDIT_PARTIAL:
                raise SecurityBootstrapLifecycleError("partial security schema blocks activation")
            actor_before = _validate_raw_active_admin(
                conn,
                user_id=target_id,
                username=target_name,
                role_auth_state=lifecycle["role_auth_state"],
            )
            if not enterprise_db.verify_password(current_password, actor_before["password_hash"]):
                raise SecurityBootstrapPasswordError("local administrator password was rejected")

            if lifecycle["audit_state"] == SECURITY_AUDIT_MISSING:
                audit_result = apply_security_audit_migration_in_transaction(
                    conn,
                    actor_user_id=target_id,
                    actor_label=label,
                    operation_id=approved_plan["operation_id"],
                    reason=audit_reason,
                )
                event_ids["foundation"] = audit_result["activation_event_id"]
            if lifecycle["role_auth_state"] == SCHEMA_LEGACY:
                role_result = apply_role_auth_migration_in_transaction(conn)
                migration_event = append_security_audit_event(
                    action="security.role_auth.migration.activate",
                    risk_level="L3",
                    result="success",
                    actor_type="local_operator",
                    operation_id=approved_plan["operation_id"],
                    actor_user_id=target_id,
                    actor_role=ROLE_ADMIN,
                    actor_label=label,
                    target_type="user",
                    target_id=target_id,
                    reason=audit_reason,
                    context={
                        "migration_id": ROLE_AUTH_MIGRATION_ID,
                        "legacy_user_count": role_result["legacy_user_to_user_count"],
                        "legacy_admin_count": role_result["legacy_admin_to_admin_count"],
                        "session_invalidation": "all_existing_tokens",
                    },
                    connection=conn,
                )
                event_ids["role_auth_migration"] = migration_event["event_id"]
            ensure_bootstrap_lifecycle_schema_in_transaction(conn)

            lifecycle_after_schema = _lifecycle_from_connection(conn)
            if (
                lifecycle_after_schema["role_auth_state"] != ROLE_AUTH_READY
                or lifecycle_after_schema["audit_state"] != SECURITY_AUDIT_READY
                or lifecycle_after_schema["lifecycle_state"] != LIFECYCLE_UNINITIALIZED
                or lifecycle_after_schema["super_admin_count"] != 0
            ):
                raise SecurityBootstrapIntegrityError("activation prerequisites changed inside transaction")
            target_before = _validate_raw_active_admin(
                conn,
                user_id=target_id,
                username=target_name,
                role_auth_state=ROLE_AUTH_READY,
            )
            target_before_auth_version = int(target_before["auth_version"])
            completed_at = _utc_now_ms()
            cursor = conn.execute(
                """
                UPDATE main.users
                SET role = ?, is_admin = 1, auth_version = ?,
                    role_updated_at = ?, role_updated_by = ?
                WHERE id = ? AND username = ? AND role = ? AND is_admin = 1
                  AND is_active = 1 AND auth_version = ?
                """,
                (
                    ROLE_SUPER_ADMIN,
                    target_before_auth_version + 1,
                    completed_at,
                    target_id,
                    target_id,
                    target_name,
                    ROLE_ADMIN,
                    target_before_auth_version,
                ),
            )
            if cursor.rowcount != 1:
                raise SecurityBootstrapIntegrityError("bootstrap target promotion update was not confirmed")
            target_after = _verify_target_after_promotion(
                conn,
                target_id=target_id,
                before=target_before,
                expected_auth_version=target_before_auth_version + 1,
                updated_at=completed_at,
            )
            target_after_auth_version = int(target_after["auth_version"])
            marker = {
                "singleton_id": 1,
                "bootstrap_completed_at": completed_at,
                "bootstrap_completed_by": target_id,
                "bootstrap_target_user_id": target_id,
                "bootstrap_operation_id": approved_plan["operation_id"],
                "bootstrap_actor_label": label,
                "created_at": completed_at,
            }
            marker_cursor = conn.execute(
                """
                INSERT INTO main.security_governance_bootstrap (
                    singleton_id, bootstrap_completed_at, bootstrap_completed_by,
                    bootstrap_target_user_id, bootstrap_operation_id,
                    bootstrap_actor_label, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(marker.values()),
            )
            if marker_cursor.rowcount != 1:
                raise SecurityBootstrapIntegrityError("bootstrap lifecycle marker insert was not confirmed")
            _verify_marker(conn, marker)
            bootstrap_event = append_security_audit_event(
                action="security.super_admin.bootstrap",
                risk_level="L3",
                result="success",
                actor_type="local_operator",
                operation_id=approved_plan["operation_id"],
                actor_user_id=target_id,
                actor_role=ROLE_SUPER_ADMIN,
                actor_label=label,
                target_type="user",
                target_id=target_id,
                reason=audit_reason,
                context={
                    "lifecycle_before": LIFECYCLE_UNINITIALIZED,
                    "lifecycle_after": LIFECYCLE_ACTIVE,
                    "role_before": ROLE_ADMIN,
                    "role_after": ROLE_SUPER_ADMIN,
                    "auth_version_incremented": True,
                },
                connection=conn,
            )
            event_ids["bootstrap"] = bootstrap_event["event_id"]
            final = _lifecycle_from_connection(conn)
            if (
                final["lifecycle_state"] != LIFECYCLE_ACTIVE
                or final["active_super_admin_count"] != 1
                or final["target_user_id"] != target_id
            ):
                raise SecurityBootstrapIntegrityError("bootstrap lifecycle final verification failed")
            expected_event_ids = [value for value in event_ids.values() if value]
            stored_event_ids = {
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT event_id FROM main.security_audit_events
                    WHERE operation_id = ? AND result = 'success'
                      AND action IN (
                        'security.audit.foundation.activate',
                        'security.role_auth.migration.activate',
                        'security.super_admin.bootstrap'
                      )
                    """,
                    (approved_plan["operation_id"],),
                ).fetchall()
            }
            if stored_event_ids != set(expected_event_ids):
                raise SecurityBootstrapIntegrityError("bootstrap security audit verification failed")
            after_states = {
                "role_auth": final["role_auth_state"],
                "audit": final["audit_state"],
                "lifecycle": final["lifecycle_state"],
            }
            conn.commit()
            transaction_started = False
        except SecurityBootstrapError:
            if transaction_started and conn.in_transaction:
                conn.rollback()
            raise
        except (SecurityAuditMigrationError, BootstrapLifecycleMigrationError, SecurityAuditError) as exc:
            if transaction_started and conn.in_transaction:
                conn.rollback()
            raise SecurityBootstrapIntegrityError("controlled activation transaction was rolled back") from exc
        except sqlite3.Error as exc:
            if transaction_started and conn.in_transaction:
                conn.rollback()
            raise SecurityBootstrapIntegrityError("controlled activation transaction was rolled back") from exc

    try:
        database_sha256_after = _sha256_file(path)
    except OSError as exc:
        raise SecurityBootstrapIntegrityError("database fingerprint could not be calculated after activation") from exc
    return {
        "success": True,
        "operation_id": approved_plan["operation_id"],
        "plan_id": approved_plan["plan_id"],
        "plan_hash": approved_plan["plan_hash"],
        "database_sha256_before": database_sha256_before,
        "database_sha256_after": database_sha256_after,
        "backup_manifest_sha256": backup["backup_manifest_sha256"],
        "started_at": started_at,
        "completed_at": _utc_now_ms(),
        "before_states": before_states,
        "after_states": after_states,
        "target_user_id": target_id,
        "target_username": target_name,
        "target_role_before": ROLE_ADMIN,
        "target_role_after": ROLE_SUPER_ADMIN,
        "target_auth_version_before": target_before_auth_version,
        "target_auth_version_after": target_after_auth_version,
        "event_ids": event_ids,
        "old_tokens_invalidated": True,
        "warnings": [],
    }
