"""Mandatory append-only security audit primitives for SEC-1F0."""

import json
import math
import os
import re
import sqlite3
import time
import uuid
from typing import Any

from enterprise.migrations.sec_1b1_role_auth import (
    ROLE_AUTH_READY,
    SCHEMA_LEGACY,
    classify_role_auth_schema,
    get_user_columns,
)
from enterprise.migrations.sqlite_existing import open_existing_sqlite
from enterprise.roles import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    normalize_auth_version,
    normalize_role,
    role_from_legacy_is_admin,
)


SECURITY_AUDIT_MIGRATION_ID = "sec_1f0_security_audit"
SECURITY_AUDIT_TABLE = "security_audit_events"
SECURITY_AUDIT_MISSING = "SECURITY_AUDIT_MISSING"
SECURITY_AUDIT_PARTIAL = "SECURITY_AUDIT_PARTIAL"
SECURITY_AUDIT_READY = "SECURITY_AUDIT_READY"

SECURITY_AUDIT_COLUMNS = (
    "id",
    "event_id",
    "operation_id",
    "action",
    "risk_level",
    "result",
    "actor_type",
    "actor_user_id",
    "actor_role",
    "actor_label",
    "capability",
    "target_type",
    "target_id",
    "reason",
    "context_json",
    "created_at",
)

SECURITY_AUDIT_INDEXES = {
    "idx_security_audit_operation": ("operation_id", "id"),
    "idx_security_audit_action_created": ("action", "created_at"),
    "idx_security_audit_actor_created": ("actor_user_id", "created_at"),
}

SECURITY_AUDIT_TRIGGERS = {
    "trg_security_audit_no_update": "update",
    "trg_security_audit_no_delete": "delete",
}

VALID_RISK_LEVELS = frozenset({"L0", "L1", "L2", "L3"})
VALID_RESULTS = frozenset({"attempted", "success", "denied", "failed"})
VALID_ACTOR_TYPES = frozenset({"user", "system", "local_operator"})

ACTION_RISK_LEVELS = {
    "security.audit.foundation.initialize": frozenset({"L3"}),
    "security.audit.foundation.activate": frozenset({"L3"}),
    "security.role_auth.migration.activate": frozenset({"L3"}),
    "security.super_admin.bootstrap": frozenset({"L3"}),
    "security.super_admin.break_glass": frozenset({"L3"}),
    "security.role.change": frozenset({"L2", "L3"}),
    "security.user.password_reset": frozenset({"L2", "L3"}),
    "security.user.active_change": frozenset({"L2", "L3"}),
    "security.user.soft_delete": frozenset({"L2", "L3"}),
    "security.session.revoke_all": frozenset({"L2", "L3"}),
    "security.authorization.denied": frozenset({"L2", "L3"}),
}

MAX_CONTEXT_DEPTH = 4
MAX_CONTEXT_KEYS = 100
MAX_CONTEXT_STRING_LENGTH = 2048
MAX_CONTEXT_JSON_BYTES = 16 * 1024

FIELD_LIMITS = {
    "operation_id": 128,
    "actor_user_id": 128,
    "actor_label": 256,
    "capability": 256,
    "target_type": 128,
    "target_id": 512,
    "reason": 2048,
}

_PROHIBITED_CONTEXT_KEYS = frozenset(
    {
        "password",
        "passwordhash",
        "oldpassword",
        "newpassword",
        "token",
        "jwt",
        "cookie",
        "authorization",
        "apikey",
        "secret",
        "clientsecret",
        "accesstoken",
        "refreshtoken",
        "operationtoken",
        "env",
        "environmentsecret",
        "privatekey",
        "prompt",
        "userprompt",
        "requestbody",
        "canvasjson",
        "imagecontent",
        "assetcontent",
        "uploadcontent",
        "databasecontent",
    }
)

_TABLE_CONSTRAINT_MARKERS = (
    "idintegerprimarykeyautoincrement",
    "event_idtextnotnullunique",
    "operation_idtextnotnull",
    "actiontextnotnull",
    "check(risk_levelin('l0','l1','l2','l3'))",
    "check(resultin('attempted','success','denied','failed'))",
    "check(actor_typein('user','system','local_operator'))",
    "check(actor_roleisnulloractor_rolein('user','admin','super_admin'))",
    "context_jsontextnotnulldefault'{}'",
    "created_atintegernotnull",
)


class SecurityAuditError(RuntimeError):
    """Base exception for mandatory security audit failures."""


class SecurityAuditValidationError(SecurityAuditError):
    """Raised when an event fails strict validation."""


class SecurityAuditSchemaError(SecurityAuditError):
    """Raised when the audit schema is missing, partial, or inaccessible."""


class SecurityAuditWriteError(SecurityAuditError):
    """Raised when a mandatory event cannot be appended."""


def _normalize_sql(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _index_columns(conn: sqlite3.Connection, name: str) -> tuple[str, ...]:
    return tuple(str(row[2]) for row in conn.execute(f'PRAGMA index_info("{name}")').fetchall())


def inspect_security_audit_connection(conn: sqlite3.Connection) -> dict[str, Any]:
    """Inspect actual table, index, trigger, and constraint state without writes."""
    object_row = conn.execute(
        "SELECT type, sql FROM sqlite_master WHERE name = ?",
        (SECURITY_AUDIT_TABLE,),
    ).fetchone()
    object_type = str(object_row[0]) if object_row else None
    table_exists = object_type == "table"
    table_sql = str(object_row[1] or "") if object_row else ""

    columns = (
        tuple(str(row[1]) for row in conn.execute(f"PRAGMA table_info({SECURITY_AUDIT_TABLE})").fetchall())
        if table_exists
        else ()
    )
    missing_columns = [name for name in SECURITY_AUDIT_COLUMNS if name not in columns]

    index_rows = conn.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type = 'index'"
    ).fetchall()
    table_indexes = sorted(str(row[0]) for row in index_rows if str(row[1]) == SECURITY_AUDIT_TABLE)
    index_lookup = {str(row[0]): str(row[1]) for row in index_rows}
    missing_indexes = []
    for name, expected_columns in SECURITY_AUDIT_INDEXES.items():
        if index_lookup.get(name) != SECURITY_AUDIT_TABLE or _index_columns(conn, name) != expected_columns:
            missing_indexes.append(name)

    trigger_rows = conn.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger'"
    ).fetchall()
    table_triggers = sorted(str(row[0]) for row in trigger_rows if str(row[1]) == SECURITY_AUDIT_TABLE)
    trigger_lookup = {str(row[0]): (str(row[1]), str(row[2] or "")) for row in trigger_rows}
    missing_triggers = []
    for name, operation in SECURITY_AUDIT_TRIGGERS.items():
        trigger = trigger_lookup.get(name)
        normalized = _normalize_sql(trigger[1]) if trigger else ""
        marker = f"before{operation}on{SECURITY_AUDIT_TABLE}"
        if (
            not trigger
            or trigger[0] != SECURITY_AUDIT_TABLE
            or marker not in normalized
            or "raise(abort,'securityauditeventsareappend-only')" not in normalized
        ):
            missing_triggers.append(name)

    normalized_table_sql = _normalize_sql(table_sql)
    constraint_issues = [
        marker for marker in _TABLE_CONSTRAINT_MARKERS if marker not in normalized_table_sql
    ] if table_exists else []

    expected_names = set(SECURITY_AUDIT_INDEXES) | set(SECURITY_AUDIT_TRIGGERS)
    object_conflicts = sorted(
        name
        for name in expected_names
        if (name in index_lookup and index_lookup[name] != SECURITY_AUDIT_TABLE)
        or (name in trigger_lookup and trigger_lookup[name][0] != SECURITY_AUDIT_TABLE)
    )

    event_count: int | None = 0
    if table_exists:
        try:
            event_count = int(conn.execute(f"SELECT COUNT(*) FROM {SECURITY_AUDIT_TABLE}").fetchone()[0])
        except sqlite3.Error:
            event_count = None

    if not object_row and not object_conflicts:
        state = SECURITY_AUDIT_MISSING
    elif (
        table_exists
        and not missing_columns
        and not missing_indexes
        and not missing_triggers
        and not constraint_issues
        and not object_conflicts
        and event_count is not None
    ):
        state = SECURITY_AUDIT_READY
    else:
        state = SECURITY_AUDIT_PARTIAL

    warnings: list[str] = []
    if object_type and object_type != "table":
        warnings.append("security audit object exists but is not a table")
    if missing_columns:
        warnings.append("security audit table is missing required columns")
    if missing_indexes:
        warnings.append("security audit schema is missing required indexes")
    if missing_triggers:
        warnings.append("security audit schema is missing append-only triggers")
    if constraint_issues:
        warnings.append("security audit table constraints require manual review")
    if object_conflicts:
        warnings.append("security audit object names conflict with other schema objects")
    if event_count is None:
        warnings.append("security audit event count could not be read")

    return {
        "migration_id": SECURITY_AUDIT_MIGRATION_ID,
        "current_state": state,
        "table_exists": table_exists,
        "table_object_type": object_type,
        "columns": list(columns),
        "required_columns": list(SECURITY_AUDIT_COLUMNS),
        "missing_columns": missing_columns,
        "indexes": table_indexes,
        "missing_indexes": missing_indexes,
        "triggers": table_triggers,
        "missing_triggers": missing_triggers,
        "constraint_issues": constraint_issues,
        "object_conflicts": object_conflicts,
        "event_count": event_count,
        "is_ready": state == SECURITY_AUDIT_READY,
        "needs_migration": state == SECURITY_AUDIT_MISSING,
        "warnings": warnings,
    }


def _required_text(name: str, value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or value.isspace():
        raise SecurityAuditValidationError(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise SecurityAuditValidationError(f"{name} exceeds its length limit")
    return value


def _optional_text(name: str, value: object | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _required_text(name, value, maximum=maximum)


def _canonical_context_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _validate_context_value(value: object, *, depth: int, stats: dict[str, int]) -> None:
    if depth > MAX_CONTEXT_DEPTH:
        raise SecurityAuditValidationError("context exceeds the nesting depth limit")
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SecurityAuditValidationError("context contains a non-finite number")
        return
    if isinstance(value, str):
        if len(value) > MAX_CONTEXT_STRING_LENGTH:
            raise SecurityAuditValidationError("context contains an overlong string")
        return
    if isinstance(value, list):
        for item in value:
            _validate_context_value(item, depth=depth + 1, stats=stats)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SecurityAuditValidationError("context object keys must be strings")
            if not key or key.isspace() or len(key) > MAX_CONTEXT_STRING_LENGTH:
                raise SecurityAuditValidationError("context object key is invalid")
            stats["keys"] += 1
            if stats["keys"] > MAX_CONTEXT_KEYS:
                raise SecurityAuditValidationError("context exceeds the key count limit")
            if _canonical_context_key(key) in _PROHIBITED_CONTEXT_KEYS:
                raise SecurityAuditValidationError("context contains a prohibited sensitive field")
            _validate_context_value(item, depth=depth + 1, stats=stats)
        return
    raise SecurityAuditValidationError("context contains a non-JSON-safe value")


def serialize_security_audit_context(context: object | None) -> str:
    """Validate and deterministically serialize a bounded, non-sensitive context."""
    if context is None:
        context = {}
    if not isinstance(context, dict):
        raise SecurityAuditValidationError("context must be a JSON object")
    _validate_context_value(context, depth=1, stats={"keys": 0})
    try:
        serialized = json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SecurityAuditValidationError("context could not be serialized safely") from exc
    if len(serialized.encode("utf-8")) > MAX_CONTEXT_JSON_BYTES:
        raise SecurityAuditValidationError("context exceeds the serialized size limit")
    return serialized


def resolve_security_audit_activation_actor_role(
    conn: sqlite3.Connection,
    actor_user_id: object,
) -> str:
    """Load an active activation operator role from current database state."""
    if not isinstance(actor_user_id, str) or not actor_user_id or actor_user_id.isspace():
        raise SecurityAuditValidationError("activation actor_user_id must be a non-empty string")
    try:
        columns = get_user_columns(conn)
    except sqlite3.Error as exc:
        raise SecurityAuditSchemaError("activation actor database state could not be read") from exc
    if "is_admin" not in columns or "is_active" not in columns:
        raise SecurityAuditSchemaError("users compatibility schema is incomplete")
    schema_state = classify_role_auth_schema(columns)
    if schema_state not in {SCHEMA_LEGACY, ROLE_AUTH_READY}:
        raise SecurityAuditSchemaError("users role/auth schema is not supported")

    if schema_state == ROLE_AUTH_READY:
        try:
            row = conn.execute(
                "SELECT role, auth_version, is_active FROM users WHERE id = ?",
                (actor_user_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise SecurityAuditSchemaError("activation actor database state could not be read") from exc
        if not row or row[2] != 1:
            raise SecurityAuditValidationError("activation actor must be an active administrator")
        try:
            role = normalize_role(row[0])
            normalize_auth_version(row[1])
        except ValueError as exc:
            raise SecurityAuditValidationError("activation actor role/auth state is invalid") from exc
    else:
        try:
            row = conn.execute(
                "SELECT is_admin, is_active FROM users WHERE id = ?",
                (actor_user_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise SecurityAuditSchemaError("activation actor database state could not be read") from exc
        if not row or row[1] != 1:
            raise SecurityAuditValidationError("activation actor must be an active administrator")
        try:
            role = role_from_legacy_is_admin(row[0])
        except ValueError as exc:
            raise SecurityAuditValidationError(
                "activation actor administrator state is invalid"
            ) from exc
    if role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        raise SecurityAuditValidationError("activation actor must be an active administrator")
    return role


def _validate_event(
    *,
    action: object,
    risk_level: object,
    result: object,
    actor_type: object,
    operation_id: object,
    actor_user_id: object | None,
    actor_role: object | None,
    actor_label: object | None,
    capability: object | None,
    target_type: object | None,
    target_id: object | None,
    reason: object | None,
    context: object | None,
) -> dict[str, Any]:
    if not isinstance(action, str) or action not in ACTION_RISK_LEVELS:
        raise SecurityAuditValidationError("action is not in the security audit catalog")
    if not isinstance(risk_level, str) or risk_level not in VALID_RISK_LEVELS:
        raise SecurityAuditValidationError("risk_level is invalid")
    if risk_level not in ACTION_RISK_LEVELS[action]:
        raise SecurityAuditValidationError("risk_level is not allowed for this action")
    if not isinstance(result, str) or result not in VALID_RESULTS:
        raise SecurityAuditValidationError("result is invalid")
    if not isinstance(actor_type, str) or actor_type not in VALID_ACTOR_TYPES:
        raise SecurityAuditValidationError("actor_type is invalid")

    operation = _required_text("operation_id", operation_id, maximum=FIELD_LIMITS["operation_id"])
    actor_id = _optional_text("actor_user_id", actor_user_id, maximum=FIELD_LIMITS["actor_user_id"])
    label = _optional_text("actor_label", actor_label, maximum=FIELD_LIMITS["actor_label"])
    capability_value = _optional_text("capability", capability, maximum=FIELD_LIMITS["capability"])
    target_type_value = _optional_text("target_type", target_type, maximum=FIELD_LIMITS["target_type"])
    target_id_value = _optional_text("target_id", target_id, maximum=FIELD_LIMITS["target_id"])
    reason_value = _optional_text("reason", reason, maximum=FIELD_LIMITS["reason"])

    normalized_actor_role: str | None = None
    if actor_role is not None:
        try:
            normalized_actor_role = normalize_role(actor_role)
        except ValueError as exc:
            raise SecurityAuditValidationError("actor_role is invalid") from exc

    if actor_type == "user":
        if actor_id is None or normalized_actor_role is None:
            raise SecurityAuditValidationError("user actor requires actor_user_id and actor_role")
    elif actor_type == "system":
        if actor_id is not None or normalized_actor_role is not None:
            raise SecurityAuditValidationError("system actor cannot include user identity or role")
    else:
        if label is None:
            raise SecurityAuditValidationError("local_operator actor requires actor_label")
        if (actor_id is None) != (normalized_actor_role is None):
            raise SecurityAuditValidationError("local_operator user identity and role must be provided together")
        if action == "security.audit.foundation.activate" and actor_id is None:
            raise SecurityAuditValidationError("security audit activation requires an authenticated operator")

    if risk_level == "L3" and reason_value is None:
        raise SecurityAuditValidationError("L3 security audit event requires reason")

    return {
        "action": action,
        "risk_level": risk_level,
        "result": result,
        "actor_type": actor_type,
        "operation_id": operation,
        "actor_user_id": actor_id,
        "actor_role": normalized_actor_role,
        "actor_label": label,
        "capability": capability_value,
        "target_type": target_type_value,
        "target_id": target_id_value,
        "reason": reason_value,
        "context_json": serialize_security_audit_context(context),
    }


def _append_with_connection(conn: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any]:
    try:
        inspection = inspect_security_audit_connection(conn)
    except sqlite3.Error as exc:
        raise SecurityAuditSchemaError("mandatory security audit schema could not be inspected") from exc
    if inspection["current_state"] != SECURITY_AUDIT_READY:
        raise SecurityAuditSchemaError("mandatory security audit schema is not ready")

    if event["action"] == "security.audit.foundation.activate":
        event = dict(event)
        event["actor_role"] = resolve_security_audit_activation_actor_role(
            conn,
            event["actor_user_id"],
        )

    event_id = uuid.uuid4().hex
    created_at = int(time.time() * 1000)
    try:
        conn.execute(
            f"""
            INSERT INTO {SECURITY_AUDIT_TABLE} (
                event_id, operation_id, action, risk_level, result,
                actor_type, actor_user_id, actor_role, actor_label,
                capability, target_type, target_id, reason, context_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event["operation_id"],
                event["action"],
                event["risk_level"],
                event["result"],
                event["actor_type"],
                event["actor_user_id"],
                event["actor_role"],
                event["actor_label"],
                event["capability"],
                event["target_type"],
                event["target_id"],
                event["reason"],
                event["context_json"],
                created_at,
            ),
        )
    except sqlite3.Error as exc:
        raise SecurityAuditWriteError("mandatory security audit event could not be written") from exc
    return {
        "event_id": event_id,
        "operation_id": event["operation_id"],
        "action": event["action"],
        "risk_level": event["risk_level"],
        "result": event["result"],
        "created_at": created_at,
    }


def append_security_audit_event(
    *,
    action: object,
    risk_level: object,
    result: object,
    actor_type: object,
    operation_id: object,
    actor_user_id: object | None = None,
    actor_role: object | None = None,
    actor_label: object | None = None,
    capability: object | None = None,
    target_type: object | None = None,
    target_id: object | None = None,
    reason: object | None = None,
    context: object | None = None,
    connection: sqlite3.Connection | None = None,
    database_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Append one mandatory event or raise; never fall back to a best-effort log."""
    if (connection is None) == (database_path is None):
        raise SecurityAuditValidationError("provide exactly one connection or database_path")
    event = _validate_event(
        action=action,
        risk_level=risk_level,
        result=result,
        actor_type=actor_type,
        operation_id=operation_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        actor_label=actor_label,
        capability=capability,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        context=context,
    )

    if connection is not None:
        return _append_with_connection(connection, event)

    assert database_path is not None
    with open_existing_sqlite(
        database_path,
        mode="rw",
        error_type=SecurityAuditSchemaError,
    ) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            result_record = _append_with_connection(conn, event)
            conn.commit()
            return result_record
        except SecurityAuditError:
            if conn.in_transaction:
                conn.rollback()
            raise
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.rollback()
            raise SecurityAuditWriteError("mandatory security audit transaction failed") from exc
