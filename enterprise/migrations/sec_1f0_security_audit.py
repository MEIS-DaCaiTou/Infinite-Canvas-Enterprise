"""Explicit SEC-1F0 mandatory security-audit schema migration."""

import os
import sqlite3
from typing import Any

from enterprise.migrations.sqlite_existing import open_existing_sqlite
from enterprise.security_audit import (
    SECURITY_AUDIT_INDEXES,
    SECURITY_AUDIT_MIGRATION_ID,
    SECURITY_AUDIT_MISSING,
    SECURITY_AUDIT_PARTIAL,
    SECURITY_AUDIT_READY,
    SECURITY_AUDIT_TABLE,
    SECURITY_AUDIT_TRIGGERS,
    SecurityAuditError,
    append_security_audit_event,
    inspect_security_audit_connection,
    resolve_security_audit_activation_actor_role,
)


CREATE_TABLE_SQL = f"""
CREATE TABLE {SECURITY_AUDIT_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    operation_id TEXT NOT NULL,
    action TEXT NOT NULL,
    risk_level TEXT NOT NULL
        CHECK (risk_level IN ('L0', 'L1', 'L2', 'L3')),
    result TEXT NOT NULL
        CHECK (result IN ('attempted', 'success', 'denied', 'failed')),
    actor_type TEXT NOT NULL
        CHECK (actor_type IN ('user', 'system', 'local_operator')),
    actor_user_id TEXT,
    actor_role TEXT
        CHECK (actor_role IS NULL OR actor_role IN ('user', 'admin', 'super_admin')),
    actor_label TEXT,
    capability TEXT,
    target_type TEXT,
    target_id TEXT,
    reason TEXT,
    context_json TEXT NOT NULL DEFAULT '{{}}',
    created_at INTEGER NOT NULL
)
"""

CREATE_INDEX_SQL = (
    f"CREATE INDEX idx_security_audit_operation ON {SECURITY_AUDIT_TABLE} (operation_id, id)",
    f"CREATE INDEX idx_security_audit_action_created ON {SECURITY_AUDIT_TABLE} (action, created_at)",
    f"CREATE INDEX idx_security_audit_actor_created ON {SECURITY_AUDIT_TABLE} (actor_user_id, created_at)",
)

CREATE_TRIGGER_SQL = (
    f"""
    CREATE TRIGGER trg_security_audit_no_update
    BEFORE UPDATE ON {SECURITY_AUDIT_TABLE}
    BEGIN
        SELECT RAISE(ABORT, 'security audit events are append-only');
    END
    """,
    f"""
    CREATE TRIGGER trg_security_audit_no_delete
    BEFORE DELETE ON {SECURITY_AUDIT_TABLE}
    BEGIN
        SELECT RAISE(ABORT, 'security audit events are append-only');
    END
    """,
)


class SecurityAuditMigrationError(RuntimeError):
    """Raised when SEC-1F0 cannot be inspected or applied safely."""


def _inspect(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        return inspect_security_audit_connection(conn)
    except sqlite3.Error as exc:
        raise SecurityAuditMigrationError("security audit schema could not be inspected") from exc


def inspect_security_audit_schema(
    source: sqlite3.Connection | str | os.PathLike[str],
) -> dict[str, Any]:
    """Inspect SEC-1F0 using a caller connection or a read-only existing path."""
    with open_existing_sqlite(
        source,
        mode="ro",
        error_type=SecurityAuditMigrationError,
    ) as conn:
        return _inspect(conn)


def plan_security_audit_migration(
    source: sqlite3.Connection | str | os.PathLike[str],
) -> dict[str, Any]:
    """Return a read-only migration plan without repairing partial schemas."""
    inspection = inspect_security_audit_schema(source)
    state = inspection["current_state"]
    return {
        "migration_id": SECURITY_AUDIT_MIGRATION_ID,
        "current_state": state,
        "target_state": SECURITY_AUDIT_READY,
        "tables_to_create": [SECURITY_AUDIT_TABLE] if state == SECURITY_AUDIT_MISSING else [],
        "indexes_to_create": list(SECURITY_AUDIT_INDEXES) if state == SECURITY_AUDIT_MISSING else [],
        "triggers_to_create": list(SECURITY_AUDIT_TRIGGERS) if state == SECURITY_AUDIT_MISSING else [],
        "activation_event_action": (
            "security.audit.foundation.activate" if state == SECURITY_AUDIT_MISSING else None
        ),
        "can_apply": state in {SECURITY_AUDIT_MISSING, SECURITY_AUDIT_READY},
        "production_activation": False,
        "super_admin_to_create": 0,
        "warnings": list(inspection["warnings"]),
    }


def apply_security_audit_migration(
    source: sqlite3.Connection | str | os.PathLike[str],
    *,
    actor_user_id: object,
    actor_label: object,
    operation_id: object,
    reason: object,
) -> dict[str, Any]:
    """Create SEC-1F0 and its activation event in one explicit transaction."""
    with open_existing_sqlite(
        source,
        mode="rw",
        error_type=SecurityAuditMigrationError,
    ) as conn:
        if conn.in_transaction:
            raise SecurityAuditMigrationError("migration requires an idle SQLite connection")
        inspection = _inspect(conn)
        state = inspection["current_state"]
        if state == SECURITY_AUDIT_PARTIAL:
            raise SecurityAuditMigrationError("partial security audit schema requires manual review")
        if state == SECURITY_AUDIT_READY:
            return {**inspection, "activation_event_written": False}
        if state != SECURITY_AUDIT_MISSING:
            raise SecurityAuditMigrationError("security audit schema state is unsupported")

        started = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            started = True
            actor_role = resolve_security_audit_activation_actor_role(conn, actor_user_id)
            conn.execute(CREATE_TABLE_SQL)
            for statement in CREATE_INDEX_SQL:
                conn.execute(statement)
            for statement in CREATE_TRIGGER_SQL:
                conn.execute(statement)
            activation_event = append_security_audit_event(
                action="security.audit.foundation.activate",
                risk_level="L3",
                result="success",
                actor_type="local_operator",
                operation_id=operation_id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                actor_label=actor_label,
                reason=reason,
                context={"migration_id": SECURITY_AUDIT_MIGRATION_ID},
                connection=conn,
            )
            conn.commit()
            started = False
        except Exception as exc:
            if started and conn.in_transaction:
                conn.rollback()
            if isinstance(exc, SecurityAuditMigrationError):
                raise
            if isinstance(exc, SecurityAuditError):
                raise SecurityAuditMigrationError(
                    "security audit activation failed and was rolled back"
                ) from exc
            raise SecurityAuditMigrationError(
                "SEC-1F0 migration failed and was rolled back"
            ) from exc

        result = _inspect(conn)
        if result["current_state"] != SECURITY_AUDIT_READY:
            raise SecurityAuditMigrationError("SEC-1F0 migration did not reach the target schema")
        return {
            **result,
            "activation_event_written": True,
            "activation_event_id": activation_event["event_id"],
        }
