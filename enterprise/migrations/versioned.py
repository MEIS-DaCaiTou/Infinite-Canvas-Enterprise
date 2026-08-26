"""Versioned SQLite migration, backup, and restore primitives for DATA-MVP-1.

The module is deliberately not called from normal application startup or the
Update Center.  A future integration must supply an explicit registry, target
schema identity, operation id, and expected-current database identity.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from enterprise.migrations.sqlite_existing import open_existing_sqlite
from enterprise.path_safety import PathSafetyError, assert_no_reparse_ancestors, lexical_path_state


METADATA_SCHEMA_VERSION = "data-mvp-1-schema-metadata-v1"
BACKUP_SCHEMA_VERSION = "data-mvp-1-database-backup-v1"
BASELINE_SCHEMA_VERSION = 1
STATE_TABLE = "enterprise_schema_state"
LEDGER_TABLE = "enterprise_schema_migrations"
STATE_MISSING = "DATA_SCHEMA_METADATA_MISSING"
STATE_PARTIAL = "DATA_SCHEMA_METADATA_PARTIAL"
STATE_READY = "DATA_SCHEMA_METADATA_READY"
BACKUP_FILENAME = "enterprise.db.backup"
BACKUP_MANIFEST_FILENAME = "database-backup-manifest.json"
MAX_MANIFEST_BYTES = 128 * 1024
MAX_DATABASE_BYTES = 32 * 1024 * 1024 * 1024
MIGRATION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


STATE_TABLE_SQL = f"""
CREATE TABLE {STATE_TABLE} (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    metadata_schema_version TEXT NOT NULL
        CHECK (metadata_schema_version = '{METADATA_SCHEMA_VERSION}'),
    schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
    schema_sha256 TEXT NOT NULL
        CHECK (length(schema_sha256) = 64 AND schema_sha256 = lower(schema_sha256)),
    ledger_sha256 TEXT NOT NULL
        CHECK (length(ledger_sha256) = 64 AND ledger_sha256 = lower(ledger_sha256)),
    updated_at INTEGER NOT NULL CHECK (updated_at >= 0)
)
"""

LEDGER_TABLE_SQL = f"""
CREATE TABLE {LEDGER_TABLE} (
    migration_id TEXT PRIMARY KEY
        CHECK (length(migration_id) BETWEEN 1 AND 128 AND migration_id = trim(migration_id)),
    from_version INTEGER NOT NULL CHECK (from_version >= 1),
    to_version INTEGER NOT NULL CHECK (to_version = from_version + 1),
    checksum_sha256 TEXT NOT NULL
        CHECK (length(checksum_sha256) = 64 AND checksum_sha256 = lower(checksum_sha256)),
    applied_at INTEGER NOT NULL CHECK (applied_at >= 0),
    UNIQUE (from_version),
    UNIQUE (to_version)
)
"""


class DataMigrationError(RuntimeError):
    """Stable fail-closed DATA-MVP-1 error."""

    def __init__(
        self,
        code: str,
        *,
        database_may_have_changed: bool = False,
        reread_required: bool = False,
    ) -> None:
        self.code = code
        self.database_may_have_changed = database_may_have_changed
        self.reread_required = reread_required
        super().__init__(code)


MigrationApply = Callable[[sqlite3.Connection], None]
MigrationValidate = Callable[[sqlite3.Connection], bool]


@dataclass(frozen=True)
class MigrationStep:
    migration_id: str
    from_version: int
    to_version: int
    checksum_sha256: str
    apply_in_transaction: MigrationApply
    validate_in_transaction: MigrationValidate


@dataclass(frozen=True)
class MigrationPlan:
    current_version: int
    target_version: int
    source_schema_sha256: str
    registry_sha256: str
    steps: tuple[MigrationStep, ...]

    def public(self) -> dict[str, object]:
        return {
            "current_version": self.current_version,
            "target_version": self.target_version,
            "source_schema_sha256": self.source_schema_sha256,
            "registry_sha256": self.registry_sha256,
            "migration_ids": [step.migration_id for step in self.steps],
        }


@dataclass(frozen=True)
class DatabaseBackup:
    backup_path: Path
    manifest_path: Path
    manifest_sha256: str
    backup_sha256: str
    source_database_sha256: str
    source_schema_version: int
    source_schema_sha256: str
    source_ledger_sha256: str


@dataclass(frozen=True)
class MigrationResult:
    operation_id: str
    source_version: int
    target_version: int
    migration_ids: tuple[str, ...]
    source_schema_sha256: str
    target_schema_sha256: str
    post_migration_database_sha256: str
    backup: DatabaseBackup


@dataclass(frozen=True)
class RestoreResult:
    restored_database_sha256: str
    restored_schema_version: int
    restored_schema_sha256: str
    directory_sync: str


@dataclass(frozen=True)
class ReleaseValidationFinalization:
    validation_result: str
    database_restored: bool
    restore: RestoreResult | None


DEFAULT_MIGRATIONS: tuple[MigrationStep, ...] = ()


def _fail(
    code: str,
    cause: BaseException | None = None,
    *,
    database_may_have_changed: bool = False,
    reread_required: bool = False,
) -> None:
    error = DataMigrationError(
        code,
        database_may_have_changed=database_may_have_changed,
        reread_required=reread_required,
    )
    if cause is None:
        raise error
    raise error from cause


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_sha256(value: object, code: str = "DATA_SHA256_INVALID") -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail(code)
    return value


def _validate_operation_id(value: str) -> str:
    if not isinstance(value, str) or not OPERATION_ID_RE.fullmatch(value):
        _fail("DATA_OPERATION_ID_INVALID")
    return value


def _regular_file(path: Path, code: str) -> Path:
    path = Path(path)
    try:
        assert_no_reparse_ancestors(path)
        if lexical_path_state(path) != "regular" or not path.is_file():
            _fail(code)
    except DataMigrationError:
        raise
    except (OSError, PathSafetyError) as exc:
        _fail(code, exc)
    return path


def _new_path(path: Path, code: str) -> Path:
    path = Path(path)
    try:
        assert_no_reparse_ancestors(path, allow_missing=True)
        if lexical_path_state(path) != "missing":
            _fail(code)
    except DataMigrationError:
        raise
    except (OSError, PathSafetyError) as exc:
        _fail(code, exc)
    return path


def _sha256_file(path: Path, *, maximum: int = MAX_DATABASE_BYTES) -> tuple[str, int]:
    _regular_file(path, "DATA_DATABASE_INVALID")
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(min(1024 * 1024, maximum + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum:
                    _fail("DATA_DATABASE_TOO_LARGE")
                digest.update(chunk)
    except DataMigrationError:
        raise
    except OSError as exc:
        _fail("DATA_DATABASE_READ_FAILED", exc)
    return digest.hexdigest(), total


def _normalize_sql(value: str | None) -> str:
    return " ".join(str(value or "").split())


def _definition_matches(actual: str | None, expected: str) -> bool:
    return "".join(_normalize_sql(actual).split()).casefold().rstrip(";") == "".join(
        _normalize_sql(expected).split()
    ).casefold().rstrip(";")


def schema_objects(conn: sqlite3.Connection) -> list[dict[str, str]]:
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be a sqlite3.Connection")
    rows = conn.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM main.sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    return [
        {
            "type": str(row[0]),
            "name": str(row[1]),
            "table": str(row[2]),
            "sql": _normalize_sql(str(row[3] or "")),
        }
        for row in rows
    ]


def schema_snapshot_sha256(conn: sqlite3.Connection) -> str:
    return _sha256_bytes(_canonical_json(schema_objects(conn)))


def _ledger_records(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        f"""
        SELECT migration_id, from_version, to_version, checksum_sha256, applied_at
        FROM main.{LEDGER_TABLE}
        ORDER BY to_version, migration_id
        """
    ).fetchall()
    return [
        {
            "migration_id": str(row[0]),
            "from_version": int(row[1]),
            "to_version": int(row[2]),
            "checksum_sha256": str(row[3]),
            "applied_at": int(row[4]),
        }
        for row in rows
    ]


def ledger_sha256(records: Iterable[dict[str, object]]) -> str:
    return _sha256_bytes(_canonical_json(list(records)))


def inspect_schema_metadata_connection(conn: sqlite3.Connection) -> dict[str, object]:
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be a sqlite3.Connection")
    rows = conn.execute(
        "SELECT name, type, sql FROM main.sqlite_master WHERE name IN (?, ?)",
        (STATE_TABLE, LEDGER_TABLE),
    ).fetchall()
    objects = {str(row[0]): (str(row[1]), str(row[2] or "")) for row in rows}
    if not objects:
        return {"current_state": STATE_MISSING, "is_ready": False}
    reasons: list[str] = []
    state_object = objects.get(STATE_TABLE)
    ledger_object = objects.get(LEDGER_TABLE)
    if not state_object or state_object[0] != "table" or not _definition_matches(state_object[1], STATE_TABLE_SQL):
        reasons.append("state table definition mismatch")
    if not ledger_object or ledger_object[0] != "table" or not _definition_matches(ledger_object[1], LEDGER_TABLE_SQL):
        reasons.append("ledger table definition mismatch")
    if reasons:
        return {"current_state": STATE_PARTIAL, "is_ready": False, "reasons": reasons}
    try:
        state_rows = conn.execute(
            f"SELECT metadata_schema_version, schema_version, schema_sha256, ledger_sha256, updated_at FROM main.{STATE_TABLE}"
        ).fetchall()
        records = _ledger_records(conn)
    except (sqlite3.Error, TypeError, ValueError) as exc:
        return {"current_state": STATE_PARTIAL, "is_ready": False, "reasons": ["metadata rows invalid"]}
    if len(state_rows) != 1:
        reasons.append("state row count invalid")
        return {"current_state": STATE_PARTIAL, "is_ready": False, "reasons": reasons}
    state = state_rows[0]
    try:
        metadata_version = str(state[0])
        schema_version = int(state[1])
        stored_schema_sha = _validate_sha256(str(state[2]), "DATA_SCHEMA_METADATA_INVALID")
        stored_ledger_sha = _validate_sha256(str(state[3]), "DATA_SCHEMA_METADATA_INVALID")
        updated_at = int(state[4])
    except (DataMigrationError, TypeError, ValueError):
        return {"current_state": STATE_PARTIAL, "is_ready": False, "reasons": ["state row invalid"]}
    expected_from = BASELINE_SCHEMA_VERSION
    seen_ids: set[str] = set()
    for record in records:
        if (
            not MIGRATION_ID_RE.fullmatch(str(record["migration_id"]))
            or record["migration_id"] in seen_ids
            or int(record["from_version"]) != expected_from
            or int(record["to_version"]) != expected_from + 1
            or not SHA256_RE.fullmatch(str(record["checksum_sha256"]))
            or int(record["applied_at"]) < 0
        ):
            reasons.append("ledger sequence invalid")
            break
        seen_ids.add(str(record["migration_id"]))
        expected_from += 1
    actual_schema_sha = schema_snapshot_sha256(conn)
    actual_ledger_sha = ledger_sha256(records)
    if metadata_version != METADATA_SCHEMA_VERSION:
        reasons.append("metadata schema version invalid")
    if schema_version != expected_from or schema_version < BASELINE_SCHEMA_VERSION:
        reasons.append("schema version does not match ledger")
    if stored_schema_sha != actual_schema_sha:
        reasons.append("schema fingerprint mismatch")
    if stored_ledger_sha != actual_ledger_sha:
        reasons.append("ledger fingerprint mismatch")
    if updated_at < 0:
        reasons.append("updated timestamp invalid")
    if reasons:
        return {"current_state": STATE_PARTIAL, "is_ready": False, "reasons": reasons}
    return {
        "current_state": STATE_READY,
        "is_ready": True,
        "schema_version": schema_version,
        "schema_sha256": actual_schema_sha,
        "ledger_sha256": actual_ledger_sha,
        "migration_ids": [str(record["migration_id"]) for record in records],
        "migrations": records,
        "updated_at": updated_at,
    }


def inspect_schema_metadata(database_path: Path) -> dict[str, object]:
    try:
        with open_existing_sqlite(database_path, mode="ro", error_type=sqlite3.OperationalError) as conn:
            return inspect_schema_metadata_connection(conn)
    except sqlite3.Error as exc:
        _fail("DATA_SCHEMA_INSPECTION_FAILED", exc)


def initialize_schema_metadata_in_transaction(
    conn: sqlite3.Connection,
    *,
    schema_version: int = BASELINE_SCHEMA_VERSION,
) -> dict[str, object]:
    """Create the canonical metadata tables in an existing caller transaction."""
    if not isinstance(conn, sqlite3.Connection) or not conn.in_transaction:
        _fail("DATA_SCHEMA_TRANSACTION_REQUIRED")
    if type(schema_version) is not int or schema_version != BASELINE_SCHEMA_VERSION:
        _fail("DATA_SCHEMA_VERSION_INVALID")
    inspection = inspect_schema_metadata_connection(conn)
    if inspection.get("current_state") == STATE_READY:
        if inspection.get("schema_version") != schema_version:
            _fail("DATA_SCHEMA_VERSION_MISMATCH")
        return {**inspection, "metadata_created": False}
    if inspection.get("current_state") != STATE_MISSING:
        _fail("DATA_SCHEMA_METADATA_PARTIAL")
    try:
        conn.execute(LEDGER_TABLE_SQL)
        conn.execute(STATE_TABLE_SQL)
        current_schema_sha = schema_snapshot_sha256(conn)
        current_ledger_sha = ledger_sha256([])
        now = int(time.time() * 1000)
        inserted = conn.execute(
            f"""
            INSERT INTO main.{STATE_TABLE} (
                singleton_id, metadata_schema_version, schema_version,
                schema_sha256, ledger_sha256, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?)
            """,
            (METADATA_SCHEMA_VERSION, schema_version, current_schema_sha, current_ledger_sha, now),
        )
        if inserted.rowcount != 1:
            _fail("DATA_SCHEMA_METADATA_WRITE_FAILED")
    except DataMigrationError:
        raise
    except sqlite3.Error as exc:
        _fail("DATA_SCHEMA_METADATA_WRITE_FAILED", exc)
    result = inspect_schema_metadata_connection(conn)
    if result.get("current_state") != STATE_READY:
        _fail("DATA_SCHEMA_METADATA_VERIFICATION_FAILED")
    return {**result, "metadata_created": True}


def bootstrap_existing_schema_metadata(
    database_path: Path,
    *,
    expected_schema_sha256: str,
    schema_version: int = BASELINE_SCHEMA_VERSION,
) -> dict[str, object]:
    """Explicitly enroll one existing, exact-schema database into the ledger."""
    expected = _validate_sha256(expected_schema_sha256, "DATA_EXPECTED_SCHEMA_INVALID")
    _regular_file(database_path, "DATA_DATABASE_INVALID")
    try:
        with open_existing_sqlite(database_path, mode="rw", error_type=sqlite3.OperationalError) as conn:
            conn.execute("BEGIN EXCLUSIVE")
            try:
                if schema_snapshot_sha256(conn) != expected:
                    _fail("DATA_EXPECTED_SCHEMA_MISMATCH")
                result = initialize_schema_metadata_in_transaction(conn, schema_version=schema_version)
                conn.commit()
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
    except DataMigrationError:
        raise
    except sqlite3.Error as exc:
        _fail("DATA_SCHEMA_BOOTSTRAP_FAILED", exc)
    return result


def validate_registry(registry: Sequence[MigrationStep]) -> tuple[MigrationStep, ...]:
    steps = tuple(registry)
    seen_ids: set[str] = set()
    expected_from = BASELINE_SCHEMA_VERSION
    for step in steps:
        if not isinstance(step, MigrationStep):
            _fail("DATA_MIGRATION_REGISTRY_INVALID")
        if (
            not MIGRATION_ID_RE.fullmatch(step.migration_id)
            or step.migration_id in seen_ids
            or type(step.from_version) is not int
            or type(step.to_version) is not int
            or step.from_version != expected_from
            or step.to_version != step.from_version + 1
            or not SHA256_RE.fullmatch(step.checksum_sha256)
            or not callable(step.apply_in_transaction)
            or not callable(step.validate_in_transaction)
        ):
            _fail("DATA_MIGRATION_REGISTRY_INVALID")
        seen_ids.add(step.migration_id)
        expected_from = step.to_version
    return steps


def migration_registry_sha256(registry: Sequence[MigrationStep] = DEFAULT_MIGRATIONS) -> str:
    steps = validate_registry(registry)
    return _sha256_bytes(
        _canonical_json(
            [
                {
                    "migration_id": step.migration_id,
                    "from_version": step.from_version,
                    "to_version": step.to_version,
                    "checksum_sha256": step.checksum_sha256,
                }
                for step in steps
            ]
        )
    )


def plan_migrations(
    database_path: Path,
    *,
    target_version: int,
    registry: Sequence[MigrationStep] = DEFAULT_MIGRATIONS,
) -> MigrationPlan:
    if type(target_version) is not int or target_version < BASELINE_SCHEMA_VERSION:
        _fail("DATA_TARGET_SCHEMA_VERSION_INVALID")
    steps = validate_registry(registry)
    inspection = inspect_schema_metadata(database_path)
    if inspection.get("current_state") != STATE_READY:
        _fail("DATA_SCHEMA_METADATA_NOT_READY")
    current_version = int(inspection["schema_version"])
    if target_version < current_version:
        _fail("DATA_SCHEMA_DOWNGRADE_UNSUPPORTED")
    ledger = {str(item["migration_id"]): item for item in inspection.get("migrations", [])}
    registry_by_id = {step.migration_id: step for step in steps}
    for migration_id, record in ledger.items():
        step = registry_by_id.get(migration_id)
        if step is None or step.checksum_sha256 != record.get("checksum_sha256"):
            _fail("DATA_MIGRATION_LEDGER_REGISTRY_MISMATCH")
    selected = tuple(step for step in steps if current_version <= step.from_version < target_version)
    expected = current_version
    for step in selected:
        if step.from_version != expected:
            _fail("DATA_MIGRATION_PATH_UNAVAILABLE")
        expected = step.to_version
    if expected != target_version:
        _fail("DATA_MIGRATION_PATH_UNAVAILABLE")
    return MigrationPlan(
        current_version=current_version,
        target_version=target_version,
        source_schema_sha256=str(inspection["schema_sha256"]),
        registry_sha256=migration_registry_sha256(steps),
        steps=selected,
    )


def _integrity(conn: sqlite3.Connection) -> tuple[str, int]:
    integrity_row = conn.execute("PRAGMA main.integrity_check").fetchone()
    integrity = str(integrity_row[0]) if integrity_row else "missing"
    foreign_key_violations = len(conn.execute("PRAGMA main.foreign_key_check").fetchall())
    return integrity, foreign_key_violations


def _migration_statement_authorizer(
    action_code: int,
    _arg1: str | None,
    _arg2: str | None,
    _database_name: str | None,
    _trigger_name: str | None,
) -> int:
    forbidden = {
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_SAVEPOINT,
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
    }
    return sqlite3.SQLITE_DENY if action_code in forbidden else sqlite3.SQLITE_OK


def _runtime_sidecars_absent(database_path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        candidate = Path(os.fspath(database_path) + suffix)
        state = lexical_path_state(candidate)
        if state != "missing":
            _fail("DATA_DATABASE_RUNTIME_FILES_PRESENT")


def _write_new_file(path: Path, data: bytes, code: str) -> None:
    _new_path(path, code)
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        _fail(code, exc)


def _sync_directory(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {errno.EINVAL, errno.EACCES, errno.EPERM, getattr(errno, "ENOTSUP", 95)}:
            return "unsupported"
        _fail("DATA_DIRECTORY_SYNC_FAILED", exc)
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno in {errno.EINVAL, getattr(errno, "ENOTSUP", 95), getattr(errno, "EOPNOTSUPP", 95)}:
                return "unsupported"
            _fail("DATA_DIRECTORY_SYNC_FAILED", exc)
    finally:
        os.close(descriptor)
    return "synced"


def create_database_backup(
    database_path: Path,
    backup_root: Path,
    *,
    operation_id: str,
) -> DatabaseBackup:
    operation_id = _validate_operation_id(operation_id)
    database_path = _regular_file(Path(database_path), "DATA_DATABASE_INVALID")
    _runtime_sidecars_absent(database_path)
    backup_root = Path(backup_root)
    try:
        assert_no_reparse_ancestors(backup_root, allow_missing=True)
        backup_root.mkdir(parents=True, exist_ok=True)
        assert_no_reparse_ancestors(backup_root)
    except (OSError, PathSafetyError) as exc:
        _fail("DATA_BACKUP_ROOT_INVALID", exc)
    backup_dir = _new_path(backup_root / operation_id, "DATA_BACKUP_ALREADY_EXISTS")
    backup_path = backup_dir / BACKUP_FILENAME
    manifest_path = backup_dir / BACKUP_MANIFEST_FILENAME
    created_dir = False
    try:
        backup_dir.mkdir()
        created_dir = True
        assert_no_reparse_ancestors(backup_dir)
        source_sha_before, source_size = _sha256_file(database_path)
        with open_existing_sqlite(database_path, mode="ro", error_type=sqlite3.OperationalError) as source:
            source_inspection = inspect_schema_metadata_connection(source)
            if source_inspection.get("current_state") != STATE_READY:
                _fail("DATA_SCHEMA_METADATA_NOT_READY")
            source_integrity, source_fk = _integrity(source)
            if source_integrity != "ok" or source_fk != 0:
                _fail("DATA_SOURCE_DATABASE_INTEGRITY_FAILED")
            destination = sqlite3.connect(backup_path)
            try:
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
        source_sha_after, source_size_after = _sha256_file(database_path)
        if source_sha_before != source_sha_after or source_size != source_size_after:
            _fail("DATA_BACKUP_SOURCE_CHANGED")
        with open_existing_sqlite(backup_path, mode="ro", error_type=sqlite3.OperationalError) as backup_conn:
            backup_inspection = inspect_schema_metadata_connection(backup_conn)
            backup_integrity, backup_fk = _integrity(backup_conn)
        if (
            backup_inspection.get("current_state") != STATE_READY
            or backup_inspection.get("schema_version") != source_inspection.get("schema_version")
            or backup_inspection.get("schema_sha256") != source_inspection.get("schema_sha256")
            or backup_inspection.get("ledger_sha256") != source_inspection.get("ledger_sha256")
            or backup_integrity != "ok"
            or backup_fk != 0
        ):
            _fail("DATA_BACKUP_VERIFICATION_FAILED")
        with backup_path.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        backup_sha, backup_size = _sha256_file(backup_path)
        payload = {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "operation_id": operation_id,
            "created_at": int(time.time() * 1000),
            "database_filename": database_path.name,
            "backup_filename": BACKUP_FILENAME,
            "source_database_size_bytes": source_size,
            "source_database_sha256": source_sha_before,
            "backup_size_bytes": backup_size,
            "backup_sha256": backup_sha,
            "source_schema_version": int(source_inspection["schema_version"]),
            "source_schema_sha256": str(source_inspection["schema_sha256"]),
            "source_ledger_sha256": str(source_inspection["ledger_sha256"]),
            "integrity_check": backup_integrity,
            "foreign_key_violation_count": backup_fk,
        }
        _write_new_file(manifest_path, _canonical_json(payload), "DATA_BACKUP_MANIFEST_WRITE_FAILED")
        _sync_directory(backup_dir)
        manifest_sha, _ = _sha256_file(manifest_path, maximum=MAX_MANIFEST_BYTES)
        return DatabaseBackup(
            backup_path=backup_path,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha,
            backup_sha256=backup_sha,
            source_database_sha256=source_sha_before,
            source_schema_version=int(source_inspection["schema_version"]),
            source_schema_sha256=str(source_inspection["schema_sha256"]),
            source_ledger_sha256=str(source_inspection["ledger_sha256"]),
        )
    except DataMigrationError:
        for candidate in (manifest_path, backup_path):
            try:
                if lexical_path_state(candidate) == "regular" and candidate.is_file():
                    candidate.unlink()
            except OSError:
                pass
        if created_dir:
            try:
                backup_dir.rmdir()
            except OSError:
                pass
        raise
    except (OSError, sqlite3.Error) as exc:
        for candidate in (manifest_path, backup_path):
            try:
                if lexical_path_state(candidate) == "regular" and candidate.is_file():
                    candidate.unlink()
            except OSError:
                pass
        if created_dir:
            try:
                backup_dir.rmdir()
            except OSError:
                pass
        _fail("DATA_BACKUP_FAILED", exc)


def _read_bounded_json(path: Path) -> dict[str, object]:
    _regular_file(path, "DATA_BACKUP_MANIFEST_INVALID")
    content = bytearray()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(min(64 * 1024, MAX_MANIFEST_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > MAX_MANIFEST_BYTES:
                    _fail("DATA_BACKUP_MANIFEST_INVALID")
        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result
        value = json.loads(bytes(content).decode("utf-8"), object_pairs_hook=reject_duplicates)
    except DataMigrationError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        _fail("DATA_BACKUP_MANIFEST_INVALID", exc)
    if type(value) is not dict:
        _fail("DATA_BACKUP_MANIFEST_INVALID")
    return value


def verify_database_backup(manifest_path: Path) -> DatabaseBackup:
    manifest_path = _regular_file(Path(manifest_path), "DATA_BACKUP_MANIFEST_INVALID")
    payload = _read_bounded_json(manifest_path)
    expected_keys = {
        "schema_version", "operation_id", "created_at", "database_filename", "backup_filename",
        "source_database_size_bytes", "source_database_sha256", "backup_size_bytes", "backup_sha256",
        "source_schema_version", "source_schema_sha256", "source_ledger_sha256", "integrity_check",
        "foreign_key_violation_count",
    }
    if set(payload) != expected_keys or payload.get("schema_version") != BACKUP_SCHEMA_VERSION:
        _fail("DATA_BACKUP_MANIFEST_INVALID")
    operation_id = _validate_operation_id(str(payload.get("operation_id") or ""))
    if manifest_path.parent.name != operation_id or payload.get("backup_filename") != BACKUP_FILENAME:
        _fail("DATA_BACKUP_MANIFEST_INVALID")
    if not isinstance(payload.get("database_filename"), str) or Path(str(payload["database_filename"])).name != payload["database_filename"]:
        _fail("DATA_BACKUP_MANIFEST_INVALID")
    integer_fields = ("created_at", "source_database_size_bytes", "backup_size_bytes", "source_schema_version", "foreign_key_violation_count")
    if any(type(payload.get(field)) is not int or int(payload[field]) < 0 for field in integer_fields):
        _fail("DATA_BACKUP_MANIFEST_INVALID")
    source_sha = _validate_sha256(payload.get("source_database_sha256"), "DATA_BACKUP_MANIFEST_INVALID")
    backup_sha = _validate_sha256(payload.get("backup_sha256"), "DATA_BACKUP_MANIFEST_INVALID")
    schema_sha = _validate_sha256(payload.get("source_schema_sha256"), "DATA_BACKUP_MANIFEST_INVALID")
    ledger_hash = _validate_sha256(payload.get("source_ledger_sha256"), "DATA_BACKUP_MANIFEST_INVALID")
    if payload.get("integrity_check") != "ok" or payload.get("foreign_key_violation_count") != 0:
        _fail("DATA_BACKUP_MANIFEST_INVALID")
    backup_path = _regular_file(manifest_path.parent / BACKUP_FILENAME, "DATA_BACKUP_FILE_INVALID")
    actual_sha, actual_size = _sha256_file(backup_path)
    if actual_sha != backup_sha or actual_size != payload["backup_size_bytes"]:
        _fail("DATA_BACKUP_IDENTITY_MISMATCH")
    try:
        with open_existing_sqlite(backup_path, mode="ro", error_type=sqlite3.OperationalError) as conn:
            inspection = inspect_schema_metadata_connection(conn)
            integrity, foreign_keys = _integrity(conn)
    except (sqlite3.Error, DataMigrationError) as exc:
        _fail("DATA_BACKUP_VERIFICATION_FAILED", exc)
    if (
        inspection.get("current_state") != STATE_READY
        or inspection.get("schema_version") != payload["source_schema_version"]
        or inspection.get("schema_sha256") != schema_sha
        or inspection.get("ledger_sha256") != ledger_hash
        or integrity != "ok"
        or foreign_keys != 0
    ):
        _fail("DATA_BACKUP_VERIFICATION_FAILED")
    manifest_sha, _ = _sha256_file(manifest_path, maximum=MAX_MANIFEST_BYTES)
    return DatabaseBackup(
        backup_path=backup_path,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha,
        backup_sha256=backup_sha,
        source_database_sha256=source_sha,
        source_schema_version=int(payload["source_schema_version"]),
        source_schema_sha256=schema_sha,
        source_ledger_sha256=ledger_hash,
    )


def apply_versioned_migrations(
    database_path: Path,
    backup_root: Path,
    *,
    operation_id: str,
    target_version: int,
    expected_target_schema_sha256: str,
    registry: Sequence[MigrationStep] = DEFAULT_MIGRATIONS,
) -> MigrationResult:
    operation_id = _validate_operation_id(operation_id)
    expected_target = _validate_sha256(expected_target_schema_sha256, "DATA_EXPECTED_SCHEMA_INVALID")
    database_path = _regular_file(Path(database_path), "DATA_DATABASE_INVALID")
    plan = plan_migrations(database_path, target_version=target_version, registry=registry)
    if not plan.steps:
        _fail("DATA_MIGRATION_NOT_REQUIRED")
    backup = create_database_backup(database_path, backup_root, operation_id=operation_id)
    if backup.source_schema_sha256 != plan.source_schema_sha256:
        _fail("DATA_MIGRATION_SOURCE_CHANGED")
    current_sha, _ = _sha256_file(database_path)
    if current_sha != backup.source_database_sha256:
        _fail("DATA_MIGRATION_SOURCE_CHANGED")
    source_version = plan.current_version
    try:
        with open_existing_sqlite(database_path, mode="rw", error_type=sqlite3.OperationalError) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN EXCLUSIVE")
            try:
                inspection = inspect_schema_metadata_connection(conn)
                if (
                    inspection.get("current_state") != STATE_READY
                    or inspection.get("schema_version") != source_version
                    or inspection.get("schema_sha256") != plan.source_schema_sha256
                ):
                    _fail("DATA_MIGRATION_SOURCE_CHANGED")
                for step in plan.steps:
                    conn.set_authorizer(_migration_statement_authorizer)
                    try:
                        step.apply_in_transaction(conn)
                        if not conn.in_transaction:
                            _fail("DATA_MIGRATION_TRANSACTION_BROKEN")
                        if step.validate_in_transaction(conn) is not True:
                            _fail("DATA_MIGRATION_VALIDATION_FAILED")
                    finally:
                        conn.set_authorizer(None)
                    if not conn.in_transaction:
                        _fail("DATA_MIGRATION_TRANSACTION_BROKEN")
                    conn.execute(
                        f"""
                        INSERT INTO main.{LEDGER_TABLE} (
                            migration_id, from_version, to_version, checksum_sha256, applied_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (step.migration_id, step.from_version, step.to_version, step.checksum_sha256, int(time.time() * 1000)),
                    )
                    records = _ledger_records(conn)
                    new_schema_sha = schema_snapshot_sha256(conn)
                    updated = conn.execute(
                        f"""
                        UPDATE main.{STATE_TABLE}
                        SET schema_version = ?, schema_sha256 = ?, ledger_sha256 = ?, updated_at = ?
                        WHERE singleton_id = 1 AND schema_version = ?
                        """,
                        (step.to_version, new_schema_sha, ledger_sha256(records), int(time.time() * 1000), step.from_version),
                    )
                    if updated.rowcount != 1:
                        _fail("DATA_SCHEMA_METADATA_WRITE_FAILED")
                final_inspection = inspect_schema_metadata_connection(conn)
                integrity, foreign_keys = _integrity(conn)
                if (
                    final_inspection.get("current_state") != STATE_READY
                    or final_inspection.get("schema_version") != target_version
                    or final_inspection.get("schema_sha256") != expected_target
                    or integrity != "ok"
                    or foreign_keys != 0
                ):
                    _fail("DATA_MIGRATION_FINAL_VALIDATION_FAILED")
                conn.commit()
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
    except DataMigrationError:
        raise
    except Exception as exc:
        _fail("DATA_MIGRATION_FAILED", exc)
    post_sha, _ = _sha256_file(database_path)
    post_inspection = inspect_schema_metadata(database_path)
    if (
        post_inspection.get("current_state") != STATE_READY
        or post_inspection.get("schema_version") != target_version
        or post_inspection.get("schema_sha256") != expected_target
    ):
        _fail("DATA_MIGRATION_POST_COMMIT_VALIDATION_FAILED")
    return MigrationResult(
        operation_id=operation_id,
        source_version=source_version,
        target_version=target_version,
        migration_ids=tuple(step.migration_id for step in plan.steps),
        source_schema_sha256=plan.source_schema_sha256,
        target_schema_sha256=expected_target,
        post_migration_database_sha256=post_sha,
        backup=backup,
    )


def restore_database_backup(
    database_path: Path,
    manifest_path: Path,
    *,
    expected_current_database_sha256: str,
) -> RestoreResult:
    expected_current = _validate_sha256(expected_current_database_sha256, "DATA_EXPECTED_DATABASE_INVALID")
    database_path = _regular_file(Path(database_path), "DATA_DATABASE_INVALID")
    _runtime_sidecars_absent(database_path)
    current_sha, _ = _sha256_file(database_path)
    if current_sha != expected_current:
        _fail("DATA_RESTORE_EXPECTED_CURRENT_MISMATCH")
    backup = verify_database_backup(manifest_path)
    temporary = database_path.parent / f".{database_path.name}.restore-{uuid.uuid4().hex}.new"
    _new_path(temporary, "DATA_RESTORE_TEMP_INVALID")
    replaced = False
    try:
        with backup.backup_path.open("rb") as source, temporary.open("xb") as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        temp_sha, _ = _sha256_file(temporary)
        if temp_sha != backup.backup_sha256:
            _fail("DATA_RESTORE_COPY_MISMATCH")
        # ``verify_database_backup`` already validates the source file's SQLite
        # integrity, foreign keys, metadata, and ledger.  The byte-for-byte hash
        # comparison above proves the staged replacement is that exact verified
        # file, without opening a SQLite handle that can block Windows replace.
        os.replace(temporary, database_path)
        replaced = True
        try:
            sync_result = _sync_directory(database_path.parent)
        except DataMigrationError as exc:
            _fail(
                "DATA_RESTORE_DIRECTORY_SYNC_FAILED",
                exc,
                database_may_have_changed=True,
                reread_required=True,
            )
        restored_sha, _ = _sha256_file(database_path)
        if restored_sha != backup.backup_sha256:
            _fail(
                "DATA_RESTORE_POST_REPLACE_MISMATCH",
                database_may_have_changed=True,
                reread_required=True,
            )
        return RestoreResult(
            restored_database_sha256=restored_sha,
            restored_schema_version=backup.source_schema_version,
            restored_schema_sha256=backup.source_schema_sha256,
            directory_sync=sync_result,
        )
    except DataMigrationError:
        raise
    except (OSError, sqlite3.Error) as exc:
        _fail(
            "DATA_RESTORE_FAILED",
            exc,
            database_may_have_changed=replaced,
            reread_required=replaced,
        )
    finally:
        if not replaced:
            try:
                if lexical_path_state(temporary) == "regular" and temporary.is_file():
                    temporary.unlink()
            except OSError:
                pass


def finalize_release_database_validation(
    database_path: Path,
    migration_result: MigrationResult,
    *,
    validation_result: str,
) -> ReleaseValidationFinalization:
    """Keep a healthy migrated DB or restore it after target start/health failure.

    This function does not start, stop, or switch a Release.  The future update
    integrator must stop the failed target before reporting ``start_failed`` or
    ``health_failed`` and must recover the source Release after restore.
    """
    if validation_result not in {"healthy", "start_failed", "health_failed"}:
        _fail("DATA_RELEASE_VALIDATION_RESULT_INVALID")
    current_sha, _ = _sha256_file(Path(database_path))
    if current_sha != migration_result.post_migration_database_sha256:
        _fail("DATA_RESTORE_EXPECTED_CURRENT_MISMATCH")
    if validation_result == "healthy":
        inspection = inspect_schema_metadata(Path(database_path))
        if (
            inspection.get("current_state") != STATE_READY
            or inspection.get("schema_version") != migration_result.target_version
            or inspection.get("schema_sha256") != migration_result.target_schema_sha256
        ):
            _fail("DATA_MIGRATION_POST_COMMIT_VALIDATION_FAILED")
        return ReleaseValidationFinalization("healthy", False, None)
    restore = restore_database_backup(
        Path(database_path),
        migration_result.backup.manifest_path,
        expected_current_database_sha256=migration_result.post_migration_database_sha256,
    )
    return ReleaseValidationFinalization(validation_result, True, restore)
