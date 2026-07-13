"""SEC-1B2 immutable bootstrap-lifecycle SQLite schema primitives.

This module owns only the marker schema.  It never decides who to promote and
never opens a remote or online execution path.
"""

import os
import sqlite3
from typing import Any

from enterprise.migrations.sqlite_existing import open_existing_sqlite


BOOTSTRAP_MIGRATION_ID = "sec_1b2_activation"
BOOTSTRAP_TABLE = "security_governance_bootstrap"
BOOTSTRAP_MISSING = "BOOTSTRAP_MISSING"
BOOTSTRAP_PARTIAL = "BOOTSTRAP_PARTIAL"
BOOTSTRAP_READY = "BOOTSTRAP_READY"

BOOTSTRAP_COLUMNS = (
    "singleton_id",
    "bootstrap_completed_at",
    "bootstrap_completed_by",
    "bootstrap_target_user_id",
    "bootstrap_operation_id",
    "bootstrap_actor_label",
    "created_at",
)

BOOTSTRAP_CREATE_TABLE_SQL = f"""
CREATE TABLE {BOOTSTRAP_TABLE} (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    bootstrap_completed_at INTEGER NOT NULL,
    bootstrap_completed_by TEXT NOT NULL,
    bootstrap_target_user_id TEXT NOT NULL,
    bootstrap_operation_id TEXT NOT NULL UNIQUE,
    bootstrap_actor_label TEXT NOT NULL,
    created_at INTEGER NOT NULL
)
"""

BOOTSTRAP_INDEX_DEFINITIONS = {
    "idx_security_governance_bootstrap_target": {
        "columns": ("bootstrap_target_user_id",),
        "sql": (
            f"CREATE INDEX idx_security_governance_bootstrap_target "
            f"ON {BOOTSTRAP_TABLE} (bootstrap_target_user_id)"
        ),
    },
}

BOOTSTRAP_TRIGGER_DEFINITIONS = {
    "trg_security_governance_bootstrap_no_update": f"""
    CREATE TRIGGER trg_security_governance_bootstrap_no_update
    BEFORE UPDATE ON {BOOTSTRAP_TABLE}
    BEGIN
        SELECT RAISE(ABORT, 'bootstrap lifecycle marker is immutable');
    END
    """,
    "trg_security_governance_bootstrap_no_delete": f"""
    CREATE TRIGGER trg_security_governance_bootstrap_no_delete
    BEFORE DELETE ON {BOOTSTRAP_TABLE}
    BEGIN
        SELECT RAISE(ABORT, 'bootstrap lifecycle marker is immutable');
    END
    """,
}


class BootstrapLifecycleMigrationError(RuntimeError):
    """Raised when the SEC-1B2 marker schema is unsafe or unavailable."""


def _canonicalize_schema_sql(value: str | None) -> str:
    """Normalize harmless whitespace/case while retaining the exact DDL meaning."""
    sql = str(value or "").strip()
    result: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote is not None:
            result.append(char)
            if char == quote:
                if quote in {"'", '"', "`"} and index + 1 < len(sql) and sql[index + 1] == char:
                    result.append(sql[index + 1])
                    index += 1
                else:
                    quote = None
        elif char.isspace():
            pass
        elif char in {"'", '"', "`"}:
            quote = char
            result.append(char)
        elif char == "[":
            quote = "]"
            result.append(char)
        else:
            result.append(char.casefold())
        index += 1
    return "".join(result).rstrip(";")


def _main_table_columns(conn: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        str(row[1])
        for row in conn.execute(
            f"PRAGMA main.table_info({BOOTSTRAP_TABLE})"
        ).fetchall()
    )


def _main_index_columns(conn: sqlite3.Connection, name: str) -> tuple[str, ...]:
    return tuple(
        str(row[2])
        for row in conn.execute(f"PRAGMA main.index_info({name})").fetchall()
    )


def inspect_bootstrap_lifecycle_connection(conn: sqlite3.Connection) -> dict[str, Any]:
    """Inspect main-only canonical marker DDL and TEMP schema interference."""
    object_row = conn.execute(
        "SELECT type, sql FROM main.sqlite_master WHERE name = ?",
        (BOOTSTRAP_TABLE,),
    ).fetchone()
    object_type = str(object_row[0]) if object_row else None
    table_exists = object_type == "table"
    table_sql = str(object_row[1] or "") if object_row else ""
    columns = _main_table_columns(conn) if table_exists else ()
    missing_columns = [name for name in BOOTSTRAP_COLUMNS if name not in columns]
    table_matches = (
        table_exists
        and _canonicalize_schema_sql(table_sql)
        == _canonicalize_schema_sql(BOOTSTRAP_CREATE_TABLE_SQL)
    )

    index_rows = conn.execute(
        "SELECT name, tbl_name, sql FROM main.sqlite_master WHERE type = 'index'"
    ).fetchall()
    index_lookup = {
        str(row[0]): (str(row[1]), str(row[2] or ""), row[2] is None)
        for row in index_rows
    }
    table_indexes = sorted(str(row[0]) for row in index_rows if str(row[1]) == BOOTSTRAP_TABLE)
    missing_indexes: list[str] = []
    mismatched_indexes: list[str] = []
    for name, definition in BOOTSTRAP_INDEX_DEFINITIONS.items():
        actual = index_lookup.get(name)
        if actual is None:
            missing_indexes.append(name)
        elif (
            actual[0] != BOOTSTRAP_TABLE
            or actual[2]
            or _main_index_columns(conn, name) != definition["columns"]
            or _canonicalize_schema_sql(actual[1])
            != _canonicalize_schema_sql(definition["sql"])
        ):
            mismatched_indexes.append(name)
    unexpected_indexes = sorted(
        str(row[0])
        for row in index_rows
        if str(row[1]) == BOOTSTRAP_TABLE
        and str(row[0]) not in BOOTSTRAP_INDEX_DEFINITIONS
        and row[2] is not None
    )

    trigger_rows = conn.execute(
        "SELECT name, tbl_name, sql FROM main.sqlite_master WHERE type = 'trigger'"
    ).fetchall()
    trigger_lookup = {
        str(row[0]): (str(row[1]), str(row[2] or "")) for row in trigger_rows
    }
    table_triggers = sorted(str(row[0]) for row in trigger_rows if str(row[1]) == BOOTSTRAP_TABLE)
    missing_triggers: list[str] = []
    mismatched_triggers: list[str] = []
    for name, expected_sql in BOOTSTRAP_TRIGGER_DEFINITIONS.items():
        actual = trigger_lookup.get(name)
        if actual is None:
            missing_triggers.append(name)
        elif (
            actual[0] != BOOTSTRAP_TABLE
            or _canonicalize_schema_sql(actual[1])
            != _canonicalize_schema_sql(expected_sql)
        ):
            mismatched_triggers.append(name)
    unexpected_triggers = sorted(
        str(row[0])
        for row in trigger_rows
        if str(row[1]) == BOOTSTRAP_TABLE
        and str(row[0]) not in BOOTSTRAP_TRIGGER_DEFINITIONS
    )

    temporary_rows = conn.execute(
        "SELECT type, name FROM sqlite_temp_master WHERE type IN ('table', 'view')"
    ).fetchall()
    temporary_shadow_objects = sorted(
        (
            {"type": str(row[0]), "name": str(row[1])}
            for row in temporary_rows
            if str(row[1]).casefold() == BOOTSTRAP_TABLE.casefold()
        ),
        key=lambda item: (item["type"], item["name"].casefold()),
    )
    table_names = {BOOTSTRAP_TABLE.casefold(), f"main.{BOOTSTRAP_TABLE}".casefold()}
    temporary_triggers = sorted(
        str(row[0])
        for row in conn.execute(
            "SELECT name, tbl_name FROM sqlite_temp_master WHERE type = 'trigger'"
        ).fetchall()
        if str(row[1]).casefold() in table_names
    )
    expected_object_names = set(BOOTSTRAP_INDEX_DEFINITIONS) | set(BOOTSTRAP_TRIGGER_DEFINITIONS)
    object_conflicts = sorted(
        name
        for name in expected_object_names
        if (name in index_lookup and index_lookup[name][0] != BOOTSTRAP_TABLE)
        or (name in trigger_lookup and trigger_lookup[name][0] != BOOTSTRAP_TABLE)
    )

    marker_count: int | None = 0
    marker: dict[str, Any] | None = None
    if table_exists:
        try:
            rows = conn.execute(
                f"SELECT {', '.join(BOOTSTRAP_COLUMNS)} FROM main.{BOOTSTRAP_TABLE} "
                "ORDER BY singleton_id"
            ).fetchall()
            marker_count = len(rows)
            if len(rows) == 1:
                marker = dict(zip(BOOTSTRAP_COLUMNS, tuple(rows[0])))
        except sqlite3.Error:
            marker_count = None

    if (
        not object_row
        and not object_conflicts
        and not temporary_shadow_objects
        and not temporary_triggers
    ):
        state = BOOTSTRAP_MISSING
    elif (
        table_exists
        and not missing_columns
        and table_matches
        and not missing_indexes
        and not mismatched_indexes
        and not unexpected_indexes
        and not missing_triggers
        and not mismatched_triggers
        and not unexpected_triggers
        and not temporary_shadow_objects
        and not temporary_triggers
        and not object_conflicts
        and marker_count is not None
        and marker_count <= 1
    ):
        state = BOOTSTRAP_READY
    else:
        state = BOOTSTRAP_PARTIAL

    warnings: list[str] = []
    if object_type and object_type != "table":
        warnings.append("bootstrap lifecycle object exists but is not a table")
    if missing_columns or not table_matches:
        warnings.append("bootstrap lifecycle table differs from canonical definition")
    if missing_indexes or mismatched_indexes or unexpected_indexes:
        warnings.append("bootstrap lifecycle indexes differ from canonical definition")
    if missing_triggers or mismatched_triggers or unexpected_triggers:
        warnings.append("bootstrap lifecycle triggers differ from canonical definition")
    if temporary_shadow_objects or temporary_triggers:
        warnings.append("bootstrap lifecycle has temporary schema interference")
    if object_conflicts:
        warnings.append("bootstrap lifecycle object names conflict with other schema objects")
    if marker_count is None or marker_count > 1:
        warnings.append("bootstrap lifecycle marker rows are invalid")

    return {
        "migration_id": BOOTSTRAP_MIGRATION_ID,
        "current_state": state,
        "table_exists": table_exists,
        "table_object_type": object_type,
        "columns": list(columns),
        "required_columns": list(BOOTSTRAP_COLUMNS),
        "missing_columns": missing_columns,
        "table_definition_matches": table_matches,
        "indexes": table_indexes,
        "missing_indexes": missing_indexes,
        "mismatched_indexes": mismatched_indexes,
        "unexpected_indexes": unexpected_indexes,
        "triggers": table_triggers,
        "missing_triggers": missing_triggers,
        "mismatched_triggers": mismatched_triggers,
        "unexpected_triggers": unexpected_triggers,
        "temporary_shadow_objects": temporary_shadow_objects,
        "temporary_triggers": temporary_triggers,
        "object_conflicts": object_conflicts,
        "marker_count": marker_count,
        "marker": marker,
        "is_ready": state == BOOTSTRAP_READY,
        "needs_migration": state == BOOTSTRAP_MISSING,
        "warnings": warnings,
    }


def inspect_bootstrap_lifecycle_schema(
    source: sqlite3.Connection | str | os.PathLike[str],
) -> dict[str, Any]:
    """Read the marker schema through a caller connection or an existing path."""
    with open_existing_sqlite(
        source,
        mode="ro",
        error_type=BootstrapLifecycleMigrationError,
    ) as conn:
        try:
            return inspect_bootstrap_lifecycle_connection(conn)
        except sqlite3.Error as exc:
            raise BootstrapLifecycleMigrationError("bootstrap lifecycle schema could not be inspected") from exc


def ensure_bootstrap_lifecycle_schema_in_transaction(conn: sqlite3.Connection) -> dict[str, Any]:
    """Create only canonical marker DDL in the caller's current transaction."""
    if not isinstance(conn, sqlite3.Connection) or not conn.in_transaction:
        raise BootstrapLifecycleMigrationError("bootstrap lifecycle requires an active caller transaction")
    inspection = inspect_bootstrap_lifecycle_connection(conn)
    state = inspection["current_state"]
    if state == BOOTSTRAP_PARTIAL:
        raise BootstrapLifecycleMigrationError("partial bootstrap lifecycle schema requires manual review")
    if state == BOOTSTRAP_READY:
        return {**inspection, "schema_created": False}
    if state != BOOTSTRAP_MISSING:
        raise BootstrapLifecycleMigrationError("bootstrap lifecycle schema state is unsupported")
    try:
        conn.execute(BOOTSTRAP_CREATE_TABLE_SQL)
        for definition in BOOTSTRAP_INDEX_DEFINITIONS.values():
            conn.execute(definition["sql"])
        for statement in BOOTSTRAP_TRIGGER_DEFINITIONS.values():
            conn.execute(statement)
    except sqlite3.Error as exc:
        raise BootstrapLifecycleMigrationError("bootstrap lifecycle schema could not be created") from exc
    result = inspect_bootstrap_lifecycle_connection(conn)
    if result["current_state"] != BOOTSTRAP_READY:
        raise BootstrapLifecycleMigrationError("bootstrap lifecycle schema did not reach readiness")
    return {**result, "schema_created": True}
