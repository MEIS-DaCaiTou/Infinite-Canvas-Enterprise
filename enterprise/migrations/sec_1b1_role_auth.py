"""Explicit SEC-1B1 role/auth-version migration foundation for SQLite.

The apply function is intentionally not wired to application startup, an API,
OPS, or a command-line entry point. It exists for temporary-database tests and
the later SEC-1B2 controlled activation design.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

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


def get_user_columns(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Return users columns in schema order without modifying the database."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("users",),
    ).fetchone()
    if not exists:
        return ()
    return tuple(str(row[1]) for row in conn.execute("PRAGMA table_info(users)").fetchall())


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
    return {str(row[1]) for row in conn.execute("PRAGMA index_list(users)").fetchall()}


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def _inspect(conn: sqlite3.Connection) -> dict:
    columns = get_user_columns(conn)
    state = classify_role_auth_schema(columns)
    missing_columns = [column for column in TARGET_COLUMNS if column not in columns]
    result = {
        "migration_id": MIGRATION_ID,
        "current_state": state,
        "existing_columns": list(columns),
        "missing_columns": missing_columns,
        "user_count": 0,
        "legacy_user_to_user_count": 0,
        "legacy_admin_to_admin_count": 0,
        "super_admin_count": 0,
        "has_invalid_role": False,
        "invalid_role_count": 0,
        "invalid_auth_version_count": 0,
        "invalid_legacy_is_admin_count": 0,
        "is_migrated": state == ROLE_AUTH_READY,
        "needs_migration": state == SCHEMA_LEGACY,
        "existing_indexes": sorted(_index_names(conn)) if columns else [],
        "warnings": [],
    }
    if state == SCHEMA_MISSING:
        result["warnings"].append("users table is missing")
        return result

    result["user_count"] = _scalar(conn, "SELECT COUNT(*) FROM users")
    if "is_admin" not in columns:
        result["warnings"].append("legacy is_admin compatibility column is missing")
    else:
        result["legacy_user_to_user_count"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM users WHERE is_admin IS NULL OR is_admin = 0",
        )
        result["legacy_admin_to_admin_count"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM users WHERE is_admin = 1",
        )
        result["invalid_legacy_is_admin_count"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM users WHERE is_admin IS NOT NULL AND is_admin NOT IN (0, 1)",
        )
        if result["invalid_legacy_is_admin_count"]:
            result["warnings"].append("invalid legacy administrator flags require manual review")

    if "role" in columns:
        placeholders = ", ".join("?" for _ in VALID_ROLES)
        roles = tuple(sorted(VALID_ROLES))
        result["invalid_role_count"] = _scalar(
            conn,
            f"SELECT COUNT(*) FROM users WHERE role IS NULL OR typeof(role) != 'text' OR role NOT IN ({placeholders})",
            roles,
        )
        result["has_invalid_role"] = result["invalid_role_count"] > 0
        result["super_admin_count"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM users WHERE role = ?",
            (ROLE_SUPER_ADMIN,),
        )
        if result["has_invalid_role"]:
            result["warnings"].append("invalid role values require manual review")

    if "auth_version" in columns:
        result["invalid_auth_version_count"] = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM users
            WHERE auth_version IS NULL
               OR typeof(auth_version) != 'integer'
               OR auth_version < 0
            """,
        )
        if result["invalid_auth_version_count"]:
            result["warnings"].append("invalid auth_version values require manual review")

    if state == SCHEMA_PARTIAL:
        result["warnings"].append("partial SEC-1B1 schema requires manual review")
    return result


def inspect_role_auth_schema(
    source: sqlite3.Connection | str | os.PathLike[str],
) -> dict:
    """Inspect role/auth readiness using only SQLite schema and aggregate reads."""
    with _open_connection(source, mode="ro") as conn:
        return _inspect(conn)


def plan_role_auth_migration(
    source: sqlite3.Connection | str | os.PathLike[str],
) -> dict:
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


def apply_role_auth_migration(
    source: sqlite3.Connection | str | os.PathLike[str],
) -> dict:
    """Explicitly apply SEC-1B1 in one transaction.

    Callers must supply a specific temporary/test database or connection. The
    application never invokes this function automatically.
    """
    with _open_connection(source, mode="rw") as conn:
        if conn.in_transaction:
            raise RoleAuthMigrationError("migration requires an idle SQLite connection")
        inspection = _inspect(conn)
        state = inspection["current_state"]
        if state == SCHEMA_MISSING:
            raise RoleAuthMigrationError("users table is missing")
        if state == SCHEMA_PARTIAL:
            raise RoleAuthMigrationError("partial role/auth schema requires manual review")
        if "is_admin" not in inspection["existing_columns"]:
            raise RoleAuthMigrationError("legacy administrator compatibility column is missing")
        if inspection["invalid_legacy_is_admin_count"]:
            raise RoleAuthMigrationError("invalid legacy administrator flags require manual review")
        if inspection["has_invalid_role"] or inspection["invalid_auth_version_count"]:
            raise RoleAuthMigrationError("invalid role/auth data requires manual review")
        before_super_admin_count = inspection["super_admin_count"]

        started = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            started = True
            if state == SCHEMA_LEGACY:
                conn.execute(
                    """
                    ALTER TABLE users
                    ADD COLUMN role TEXT NOT NULL DEFAULT 'user'
                    CHECK (role IN ('user', 'admin', 'super_admin'))
                    """
                )
                conn.execute(
                    """
                    ALTER TABLE users
                    ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 1
                    CHECK (auth_version >= 0)
                    """
                )
                conn.execute("ALTER TABLE users ADD COLUMN role_updated_at INTEGER")
                conn.execute("ALTER TABLE users ADD COLUMN role_updated_by TEXT")
                conn.execute(
                    """
                    UPDATE users
                    SET role = CASE WHEN is_admin = 1 THEN ? ELSE ? END,
                        auth_version = 1,
                        role_updated_at = NULL,
                        role_updated_by = NULL
                    """,
                    (ROLE_ADMIN, ROLE_USER),
                )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {TARGET_INDEX} ON users (role, is_active)"
            )
            super_admin_count = _scalar(
                conn,
                "SELECT COUNT(*) FROM users WHERE role = ?",
                (ROLE_SUPER_ADMIN,),
            )
            if super_admin_count != before_super_admin_count:
                raise RoleAuthMigrationError("SEC-1B1 must not create super-admin users")
            conn.commit()
            started = False
        except Exception as exc:
            if started and conn.in_transaction:
                conn.rollback()
            if isinstance(exc, RoleAuthMigrationError):
                raise
            raise RoleAuthMigrationError("SEC-1B1 migration failed and was rolled back") from exc

        result = _inspect(conn)
        if result["current_state"] != ROLE_AUTH_READY:
            raise RoleAuthMigrationError("SEC-1B1 migration did not reach the target schema")
        return result
