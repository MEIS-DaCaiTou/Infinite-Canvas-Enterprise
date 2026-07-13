"""Explicit SEC-1B1 role/auth-version migration foundation for SQLite.

The public apply function remains deliberately disconnected from application
startup, HTTP APIs, OPS, and command-line entry points.  SEC-1B2 may reuse the
connection-aware primitive while it owns the surrounding transaction.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from enterprise.roles import ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_USER, VALID_ROLES


MIGRATION_ID = "sec_1b1_role_auth"
SCHEMA_MISSING = "MISSING"
SCHEMA_LEGACY = "LEGACY"
SCHEMA_PARTIAL = "PARTIAL"
ROLE_AUTH_READY = "ROLE_AUTH_READY"

TARGET_COLUMNS = (
    "role",
    "auth_version",
    "role_updated_at",
    "role_updated_by",
)
TARGET_INDEX = "idx_users_role_active"


class RoleAuthMigrationError(RuntimeError):
    """Raised when a role/auth migration cannot be planned or applied safely."""


@contextmanager
def _open_connection(
    source: sqlite3.Connection | str | os.PathLike[str],
    *,
    mode: str,
) -> Iterator[sqlite3.Connection]:
    """Open only a caller connection or an existing SQLite file URI."""
    if isinstance(source, sqlite3.Connection):
        yield source
        return

    if mode not in {"ro", "rw"}:
        raise ValueError("SQLite connection mode must be ro or rw")

    path = Path(source).expanduser()
    try:
        if not path.exists():
            raise RoleAuthMigrationError("SQLite database file does not exist")
        if not path.is_file():
            raise RoleAuthMigrationError("SQLite database path is not a regular file")
        database_uri = f"{path.resolve(strict=True).as_uri()}?mode={mode}"
    except RoleAuthMigrationError:
        raise
    except (OSError, ValueError) as exc:
        raise RoleAuthMigrationError("SQLite database path could not be validated") from exc

    try:
        conn = sqlite3.connect(database_uri, uri=True)
    except sqlite3.Error as exc:
        raise RoleAuthMigrationError("existing SQLite database could not be opened") from exc
    try:
        yield conn
    finally:
        conn.close()


def _main_users_object(conn: sqlite3.Connection) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT type, sql FROM main.sqlite_master WHERE name = ?",
        ("users",),
    ).fetchone()
    if not row:
        return None
    return str(row[0]), str(row[1] or "")


def _users_schema_interference(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Detect TEMP shadowing and user-table triggers before any migration write."""
    temporary_objects = [
        f"{str(row[0])}:{str(row[1])}"
        for row in conn.execute(
            "SELECT type, name FROM sqlite_temp_master WHERE type IN ('table', 'view')"
        ).fetchall()
        if str(row[1]).casefold() == "users"
    ]
    users_names = {"users", "main.users"}
    temporary_triggers = [
        str(row[0])
        for row in conn.execute(
            "SELECT name, tbl_name FROM sqlite_temp_master WHERE type = 'trigger'"
        ).fetchall()
        if str(row[1]).casefold() in users_names
    ]
    main_triggers = [
        str(row[0])
        for row in conn.execute(
            "SELECT name, tbl_name FROM main.sqlite_master WHERE type = 'trigger'"
        ).fetchall()
        if str(row[1]).casefold() == "users"
    ]
    return {
        "temporary_shadow_objects": sorted(temporary_objects),
        "temporary_triggers": sorted(temporary_triggers),
        "main_user_triggers": sorted(main_triggers),
    }


def _assert_no_users_schema_interference(conn: sqlite3.Connection) -> None:
    interference = _users_schema_interference(conn)
    if any(interference.values()):
        raise RoleAuthMigrationError("users schema has unsupported trigger or temporary interference")


def get_user_columns(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Return main.users columns in schema order without modifying the database."""
    object_info = _main_users_object(conn)
    if object_info is None or object_info[0] != "table":
        return ()
    return tuple(
        str(row[1])
        for row in conn.execute("PRAGMA main.table_info(users)").fetchall()
    )


def classify_role_auth_schema(columns: set[str] | tuple[str, ...]) -> str:
    """Classify users by actual columns rather than a version or filename."""
    column_set = set(columns)
    if not column_set:
        return SCHEMA_MISSING
    present = column_set.intersection(TARGET_COLUMNS)
    if not present:
        return SCHEMA_LEGACY
    if set(TARGET_COLUMNS).issubset(column_set):
        return ROLE_AUTH_READY
    return SCHEMA_PARTIAL


def _index_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[1])
        for row in conn.execute("PRAGMA main.index_list(users)").fetchall()
    }


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def _raw_users(conn: sqlite3.Connection, *, state: str) -> list[sqlite3.Row | tuple[Any, ...]]:
    if state == ROLE_AUTH_READY:
        return conn.execute(
            """
            SELECT id, username, password_hash, display_name, is_admin, is_active,
                   role, auth_version, role_updated_at, role_updated_by
            FROM main.users ORDER BY id
            """
        ).fetchall()
    return conn.execute(
        """
        SELECT id, username, password_hash, display_name, is_admin, is_active
        FROM main.users ORDER BY id
        """
    ).fetchall()


def _invalid_integrity_counts(conn: sqlite3.Connection, columns: tuple[str, ...], state: str) -> dict[str, int]:
    counts = {
        "invalid_legacy_is_admin_count": 0,
        "invalid_ready_is_admin_count": 0,
        "invalid_is_active_count": 0,
        "invalid_role_count": 0,
        "invalid_auth_version_count": 0,
        "role_is_admin_mismatch_count": 0,
    }
    if "is_admin" in columns:
        counts["invalid_legacy_is_admin_count"] = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM main.users
            WHERE is_admin IS NOT NULL
              AND (typeof(is_admin) != 'integer' OR is_admin NOT IN (0, 1))
            """,
        )
        if state == ROLE_AUTH_READY:
            counts["invalid_ready_is_admin_count"] = _scalar(
                conn,
                """
                SELECT COUNT(*) FROM main.users
                WHERE is_admin IS NULL
                   OR typeof(is_admin) != 'integer'
                   OR is_admin NOT IN (0, 1)
                """,
            )
    if "is_active" in columns:
        counts["invalid_is_active_count"] = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM main.users
            WHERE is_active IS NULL
               OR typeof(is_active) != 'integer'
               OR is_active NOT IN (0, 1)
            """,
        )
    if state == ROLE_AUTH_READY:
        placeholders = ", ".join("?" for _ in VALID_ROLES)
        roles = tuple(sorted(VALID_ROLES))
        counts["invalid_role_count"] = _scalar(
            conn,
            f"""
            SELECT COUNT(*) FROM main.users
            WHERE role IS NULL OR typeof(role) != 'text' OR role NOT IN ({placeholders})
            """,
            roles,
        )
        counts["invalid_auth_version_count"] = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM main.users
            WHERE auth_version IS NULL
               OR typeof(auth_version) != 'integer'
               OR auth_version < 0
            """,
        )
        counts["role_is_admin_mismatch_count"] = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM main.users
            WHERE (role = ? AND is_admin != 0)
               OR (role IN (?, ?) AND is_admin != 1)
            """,
            (ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN),
        )
    return counts


def _inspect(conn: sqlite3.Connection) -> dict[str, Any]:
    object_info = _main_users_object(conn)
    columns = get_user_columns(conn)
    base_state = classify_role_auth_schema(columns)
    interference = _users_schema_interference(conn)
    state = SCHEMA_PARTIAL if base_state != SCHEMA_MISSING and any(interference.values()) else base_state
    missing_columns = [column for column in TARGET_COLUMNS if column not in columns]
    counts = _invalid_integrity_counts(conn, columns, base_state) if columns else {}
    result: dict[str, Any] = {
        "migration_id": MIGRATION_ID,
        "current_state": state,
        "base_state": base_state,
        "users_object_type": object_info[0] if object_info else None,
        "existing_columns": list(columns),
        "missing_columns": missing_columns,
        "user_count": 0,
        "legacy_user_to_user_count": 0,
        "legacy_admin_to_admin_count": 0,
        "super_admin_count": 0,
        "has_invalid_role": False,
        "invalid_role_count": counts.get("invalid_role_count", 0),
        "invalid_auth_version_count": counts.get("invalid_auth_version_count", 0),
        "invalid_legacy_is_admin_count": counts.get("invalid_legacy_is_admin_count", 0),
        "invalid_ready_is_admin_count": counts.get("invalid_ready_is_admin_count", 0),
        "invalid_is_active_count": counts.get("invalid_is_active_count", 0),
        "role_is_admin_mismatch_count": counts.get("role_is_admin_mismatch_count", 0),
        "is_migrated": state == ROLE_AUTH_READY,
        "needs_migration": state == SCHEMA_LEGACY,
        "existing_indexes": sorted(_index_names(conn)) if columns else [],
        **interference,
        "warnings": [],
    }
    if base_state == SCHEMA_MISSING:
        result["warnings"].append("main users table is missing")
        return result
    if object_info and object_info[0] != "table":
        result["warnings"].append("main users object is not a table")
        return result

    result["user_count"] = _scalar(conn, "SELECT COUNT(*) FROM main.users")
    if "is_admin" not in columns:
        result["warnings"].append("legacy is_admin compatibility column is missing")
    else:
        result["legacy_user_to_user_count"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM main.users WHERE is_admin IS NULL OR is_admin = 0",
        )
        result["legacy_admin_to_admin_count"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM main.users WHERE is_admin = 1",
        )
    if result["invalid_legacy_is_admin_count"]:
        result["warnings"].append("invalid legacy administrator flags require manual review")
    if result["invalid_ready_is_admin_count"]:
        result["warnings"].append("invalid ready administrator flags require manual review")
    if result["invalid_is_active_count"]:
        result["warnings"].append("invalid active flags require manual review")

    if "role" in columns:
        result["super_admin_count"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM main.users WHERE role = ?",
            (ROLE_SUPER_ADMIN,),
        )
        result["has_invalid_role"] = result["invalid_role_count"] > 0
        if result["has_invalid_role"]:
            result["warnings"].append("invalid role values require manual review")
        if result["role_is_admin_mismatch_count"]:
            result["warnings"].append("role and is_admin compatibility values disagree")
    if result["invalid_auth_version_count"]:
        result["warnings"].append("invalid auth_version values require manual review")
    if base_state == SCHEMA_PARTIAL:
        result["warnings"].append("partial SEC-1B1 schema requires manual review")
    if any(interference.values()):
        result["warnings"].append("users schema has unsupported trigger or temporary interference")
    return result


def inspect_role_auth_schema(source: sqlite3.Connection | str | os.PathLike[str]) -> dict[str, Any]:
    """Inspect role/auth readiness using main-schema reads only."""
    with _open_connection(source, mode="ro") as conn:
        return _inspect(conn)


def plan_role_auth_migration(source: sqlite3.Connection | str | os.PathLike[str]) -> dict[str, Any]:
    """Return a read-only, serializable SEC-1B1 migration plan."""
    inspection = inspect_role_auth_schema(source)
    state = inspection["current_state"]
    if state == SCHEMA_MISSING:
        raise RoleAuthMigrationError("users table is missing")
    if state == SCHEMA_PARTIAL:
        raise RoleAuthMigrationError("partial role/auth schema requires manual review")
    return {
        "migration_id": MIGRATION_ID,
        "current_state": state,
        "target_state": ROLE_AUTH_READY,
        "columns_to_add": list(inspection["missing_columns"]),
        "indexes_to_add": [] if TARGET_INDEX in inspection["existing_indexes"] else [TARGET_INDEX],
        "user_count": inspection["user_count"],
        "legacy_user_to_user_count": inspection["legacy_user_to_user_count"],
        "legacy_admin_to_admin_count": inspection["legacy_admin_to_admin_count"],
        "super_admin_to_create": 0,
        "production_activation": False,
        "warnings": list(inspection["warnings"]),
    }


def _validate_apply_preconditions(conn: sqlite3.Connection, inspection: dict[str, Any]) -> None:
    state = inspection["current_state"]
    if state == SCHEMA_MISSING:
        raise RoleAuthMigrationError("users table is missing")
    if state == SCHEMA_PARTIAL:
        raise RoleAuthMigrationError("partial role/auth schema requires manual review")
    if "is_admin" not in inspection["existing_columns"]:
        raise RoleAuthMigrationError("legacy administrator compatibility column is missing")
    if "is_active" not in inspection["existing_columns"]:
        raise RoleAuthMigrationError("user active compatibility column is missing")
    if any(
        inspection[key]
        for key in (
            "invalid_legacy_is_admin_count",
            "invalid_ready_is_admin_count",
            "invalid_is_active_count",
            "invalid_role_count",
            "invalid_auth_version_count",
            "role_is_admin_mismatch_count",
        )
    ):
        raise RoleAuthMigrationError("invalid role/auth user data requires manual review")
    _assert_no_users_schema_interference(conn)


def _verify_migrated_users(
    conn: sqlite3.Connection,
    *,
    before_state: str,
    before_rows: list[sqlite3.Row | tuple[Any, ...]],
) -> None:
    inspection = _inspect(conn)
    if inspection["current_state"] != ROLE_AUTH_READY:
        raise RoleAuthMigrationError("SEC-1B1 migration did not reach the target schema")
    if TARGET_INDEX not in inspection["existing_indexes"]:
        raise RoleAuthMigrationError("SEC-1B1 role index was not created")
    after_rows = _raw_users(conn, state=ROLE_AUTH_READY)
    if len(after_rows) != len(before_rows):
        raise RoleAuthMigrationError("SEC-1B1 migration changed the user count")
    before_by_id = {str(row[0]): tuple(row) for row in before_rows}
    for row in after_rows:
        raw = tuple(row)
        user_id = str(raw[0])
        before = before_by_id.get(user_id)
        if before is None:
            raise RoleAuthMigrationError("SEC-1B1 migration changed user identity")
        if before_state == SCHEMA_LEGACY:
            expected_role = ROLE_ADMIN if before[4] == 1 else ROLE_USER
            if raw[:6] != before[:6] or raw[6:] != (expected_role, 1, None, None):
                raise RoleAuthMigrationError("SEC-1B1 migration raw verification failed")
        elif raw != before:
            raise RoleAuthMigrationError("SEC-1B1 ready migration changed user data")
        if raw[6] == ROLE_SUPER_ADMIN:
            raise RoleAuthMigrationError("SEC-1B1 must not create super-admin users")


def apply_role_auth_migration_in_transaction(conn: sqlite3.Connection) -> dict[str, Any]:
    """Apply SEC-1B1 using the caller's active transaction only.

    This primitive never starts, commits, rolls back, or closes the connection.
    """
    if not isinstance(conn, sqlite3.Connection) or not conn.in_transaction:
        raise RoleAuthMigrationError("migration requires an active caller transaction")
    inspection = _inspect(conn)
    _validate_apply_preconditions(conn, inspection)
    state = inspection["current_state"]
    before_rows = _raw_users(conn, state=state)
    try:
        if state == SCHEMA_LEGACY:
            conn.execute(
                """
                ALTER TABLE main.users
                ADD COLUMN role TEXT NOT NULL DEFAULT 'user'
                CHECK (role IN ('user', 'admin', 'super_admin'))
                """
            )
            conn.execute(
                """
                ALTER TABLE main.users
                ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 1
                CHECK (auth_version >= 0)
                """
            )
            conn.execute("ALTER TABLE main.users ADD COLUMN role_updated_at INTEGER")
            conn.execute("ALTER TABLE main.users ADD COLUMN role_updated_by TEXT")
            cursor = conn.execute(
                """
                UPDATE main.users
                SET role = CASE WHEN is_admin = 1 THEN ? ELSE ? END,
                    auth_version = 1,
                    role_updated_at = NULL,
                    role_updated_by = NULL
                """,
                (ROLE_ADMIN, ROLE_USER),
            )
            if cursor.rowcount != len(before_rows):
                raise RoleAuthMigrationError("SEC-1B1 migration update was not confirmed")
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS main.{TARGET_INDEX} ON users (role, is_active)"
        )
        _verify_migrated_users(conn, before_state=state, before_rows=before_rows)
    except RoleAuthMigrationError:
        raise
    except sqlite3.Error as exc:
        raise RoleAuthMigrationError("SEC-1B1 migration could not complete") from exc

    result = _inspect(conn)
    return {
        **result,
        "migration_applied": state == SCHEMA_LEGACY,
        "event_id": None,
    }


def apply_role_auth_migration(source: sqlite3.Connection | str | os.PathLike[str]) -> dict[str, Any]:
    """Explicitly apply SEC-1B1 in one self-managed transaction.

    The application never invokes this function automatically. SEC-1B2 uses
    :func:`apply_role_auth_migration_in_transaction` instead.
    """
    with _open_connection(source, mode="rw") as conn:
        if conn.in_transaction:
            raise RoleAuthMigrationError("migration requires an idle SQLite connection")
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = apply_role_auth_migration_in_transaction(conn)
            conn.commit()
        except RoleAuthMigrationError:
            if conn.in_transaction:
                conn.rollback()
            raise
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.rollback()
            raise RoleAuthMigrationError("SEC-1B1 migration failed and was rolled back") from exc
        return result
