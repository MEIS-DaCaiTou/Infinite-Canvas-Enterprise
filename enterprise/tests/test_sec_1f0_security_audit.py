"""SEC-1F0 mandatory append-only security-audit checks.

Every database and identity in this script is a temporary test fixture.
"""

import inspect
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("JWT_SECRET", "sec-1f0-temporary-secret-at-least-32-bytes")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "temporary-admin-password")


def _legacy_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            is_admin INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at INTEGER NOT NULL,
            last_login INTEGER
        );
        CREATE TABLE usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT,
            ts INTEGER NOT NULL
        );
        CREATE TABLE user_canvas_map (
            user_id TEXT NOT NULL,
            canvas_id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL
        );
        """
    )
    now = int(time.time() * 1000)
    conn.executemany(
        """
        INSERT INTO users (
            id, username, password_hash, display_name,
            is_admin, is_active, created_at, last_login
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("admin-id", "admin", "hash-admin", "Admin", 1, 1, now, None),
            ("user-id", "user", "hash-user", "User", 0, 1, now, None),
            ("disabled-admin-id", "disabled", "hash-disabled", "Disabled", 1, 0, now, None),
        ],
    )
    conn.execute(
        "INSERT INTO usage_logs (user_id, action, detail, ts) VALUES (?, ?, ?, ?)",
        ("admin-id", "existing", "keep", now),
    )
    conn.execute(
        "INSERT INTO user_canvas_map (user_id, canvas_id, created_at) VALUES (?, ?, ?)",
        ("user-id", "canvas-keep", now),
    )
    conn.commit()
    conn.close()


def _ready_super_admin_database(path: Path) -> None:
    _legacy_database(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user' "
        "CHECK (role IN ('user', 'admin', 'super_admin'))"
    )
    conn.execute(
        "ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 1 "
        "CHECK (auth_version >= 0)"
    )
    conn.execute("ALTER TABLE users ADD COLUMN role_updated_at INTEGER")
    conn.execute("ALTER TABLE users ADD COLUMN role_updated_by TEXT")
    conn.execute(
        "UPDATE users SET role = CASE WHEN id = 'admin-id' THEN 'super_admin' ELSE 'user' END, "
        "auth_version = 1"
    )
    conn.commit()
    conn.close()


def _schema_snapshot(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        conn.close()


def _table_exists(path: Path, name: str = "security_audit_events") -> bool:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone() is not None
    finally:
        conn.close()


def _rows(path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _assert_raises(error_type, func):
    try:
        func()
    except error_type as exc:
        return exc
    raise AssertionError(f"expected {error_type.__name__}")


def _apply(path: Path, actor_user_id: str = "admin-id") -> dict:
    from enterprise.migrations.sec_1f0_security_audit import apply_security_audit_migration

    return apply_security_audit_migration(
        path,
        actor_user_id=actor_user_id,
        actor_label="temporary-local-operator",
        operation_id="op-sec-1f0-activation",
        reason="temporary SEC-1F0 migration test",
    )


def _event_kwargs(operation_id: str, **overrides) -> dict:
    values = {
        "action": "security.role.change",
        "risk_level": "L2",
        "result": "attempted",
        "actor_type": "user",
        "operation_id": operation_id,
        "actor_user_id": "admin-id",
        "actor_role": "admin",
        "target_type": "user",
        "target_id": "user-id",
        "context": {"change": "role_review"},
    }
    values.update(overrides)
    return values


def _run_checks() -> None:
    from enterprise import db as edb
    from enterprise import security_audit as audit
    from enterprise.migrations import sec_1f0_security_audit as migration
    from enterprise.migrations.sec_1f0_security_audit import (
        SecurityAuditMigrationError,
        apply_security_audit_migration,
        inspect_security_audit_schema,
        plan_security_audit_migration,
    )

    with tempfile.TemporaryDirectory(prefix="ice-sec-1f0-") as raw_tmp:
        tmp = Path(raw_tmp)

        # A. Existing-path enforcement, MISSING/PARTIAL/READY, and read-only plan.
        missing_path = tmp / "missing audit.db"
        for operation in (
            lambda: inspect_security_audit_schema(missing_path),
            lambda: plan_security_audit_migration(missing_path),
            lambda: _apply(missing_path),
        ):
            exc = _assert_raises(SecurityAuditMigrationError, operation)
            assert str(missing_path) not in str(exc)
            assert not missing_path.exists()

        directory_path = tmp / "database-directory"
        directory_path.mkdir()
        for operation in (
            lambda: inspect_security_audit_schema(directory_path),
            lambda: plan_security_audit_migration(directory_path),
            lambda: _apply(directory_path),
        ):
            _assert_raises(SecurityAuditMigrationError, operation)

        plan_db = tmp / "plan legacy.db"
        _legacy_database(plan_db)
        before_bytes = plan_db.read_bytes()
        before_schema = _schema_snapshot(plan_db)
        inspection = inspect_security_audit_schema(plan_db)
        assert inspection["current_state"] == audit.SECURITY_AUDIT_MISSING
        assert inspection["table_exists"] is False
        plan = plan_security_audit_migration(plan_db)
        assert plan["current_state"] == audit.SECURITY_AUDIT_MISSING
        assert plan["tables_to_create"] == [audit.SECURITY_AUDIT_TABLE]
        assert set(plan["indexes_to_create"]) == set(audit.SECURITY_AUDIT_INDEXES)
        assert set(plan["triggers_to_create"]) == set(audit.SECURITY_AUDIT_TRIGGERS)
        assert plan["production_activation"] is False
        assert plan["super_admin_to_create"] == 0
        assert plan_db.read_bytes() == before_bytes
        assert _schema_snapshot(plan_db) == before_schema

        partial_db = tmp / "partial.db"
        _legacy_database(partial_db)
        conn = sqlite3.connect(partial_db)
        conn.execute("CREATE TABLE security_audit_events (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        partial = inspect_security_audit_schema(partial_db)
        assert partial["current_state"] == audit.SECURITY_AUDIT_PARTIAL
        assert partial["missing_columns"]
        assert partial["missing_indexes"]
        assert partial["missing_triggers"]
        assert plan_security_audit_migration(partial_db)["can_apply"] is False
        partial_schema = _schema_snapshot(partial_db)
        _assert_raises(SecurityAuditMigrationError, lambda: _apply(partial_db))
        assert _schema_snapshot(partial_db) == partial_schema

        # B/C. Apply, actor validation, data preservation, super-admin compatibility.
        for filename, actor_id in (
            ("missing-actor.db", "missing-id"),
            ("disabled-actor.db", "disabled-admin-id"),
            ("normal-user-actor.db", "user-id"),
        ):
            actor_db = tmp / filename
            _legacy_database(actor_db)
            _assert_raises(SecurityAuditMigrationError, lambda p=actor_db, a=actor_id: _apply(p, a))
            assert not _table_exists(actor_db)

        apply_db = tmp / "apply.db"
        _legacy_database(apply_db)
        users_before = _rows(apply_db, "SELECT * FROM users ORDER BY id")
        usage_before = _rows(apply_db, "SELECT * FROM usage_logs ORDER BY id")
        owners_before = _rows(apply_db, "SELECT * FROM user_canvas_map ORDER BY canvas_id")
        applied = _apply(apply_db)
        assert applied["current_state"] == audit.SECURITY_AUDIT_READY
        assert applied["activation_event_written"] is True
        assert applied["event_count"] == 1
        ready = inspect_security_audit_schema(apply_db)
        assert ready["current_state"] == audit.SECURITY_AUDIT_READY
        assert set(ready["indexes"]) >= set(audit.SECURITY_AUDIT_INDEXES)
        assert set(ready["triggers"]) >= set(audit.SECURITY_AUDIT_TRIGGERS)
        activation = _rows(
            apply_db,
            "SELECT action, risk_level, result, actor_type, actor_user_id, actor_role, "
            "actor_label, operation_id, reason FROM security_audit_events",
        )
        assert activation == [(
            "security.audit.foundation.activate",
            "L3",
            "success",
            "local_operator",
            "admin-id",
            "admin",
            "temporary-local-operator",
            "op-sec-1f0-activation",
            "temporary SEC-1F0 migration test",
        )]
        assert _rows(apply_db, "SELECT * FROM users ORDER BY id") == users_before
        assert _rows(apply_db, "SELECT * FROM usage_logs ORDER BY id") == usage_before
        assert _rows(apply_db, "SELECT * FROM user_canvas_map ORDER BY canvas_id") == owners_before
        second_apply = _apply(apply_db)
        assert second_apply["activation_event_written"] is False
        assert second_apply["event_count"] == 1
        assert "actor_role" not in inspect.signature(apply_security_audit_migration).parameters

        super_db = tmp / "temporary-super-fixture.db"
        _ready_super_admin_database(super_db)
        super_result = _apply(super_db)
        assert super_result["current_state"] == audit.SECURITY_AUDIT_READY
        assert _rows(super_db, "SELECT actor_role FROM security_audit_events") == [("super_admin",)]

        # D. Inject activation writer failure and verify all DDL rolls back.
        rollback_db = tmp / "rollback.db"
        _legacy_database(rollback_db)
        rollback_schema = _schema_snapshot(rollback_db)
        rollback_users = _rows(rollback_db, "SELECT * FROM users ORDER BY id")
        original_append = migration.append_security_audit_event

        def fail_activation(**_kwargs):
            raise audit.SecurityAuditWriteError("injected mandatory audit failure")

        migration.append_security_audit_event = fail_activation
        try:
            _assert_raises(SecurityAuditMigrationError, lambda: _apply(rollback_db))
        finally:
            migration.append_security_audit_event = original_append
        assert _schema_snapshot(rollback_db) == rollback_schema
        assert _rows(rollback_db, "SELECT * FROM users ORDER BY id") == rollback_users
        assert not _table_exists(rollback_db)

        # E. Writer catalog, actor rules, server fields, and stable context.
        first = audit.append_security_audit_event(
            **_event_kwargs("op-writer-1", context={"中文": "审计", "a": 1}),
            database_path=apply_db,
        )
        second = audit.append_security_audit_event(
            **_event_kwargs("op-writer-2", result="success"),
            database_path=apply_db,
        )
        assert first["event_id"] != second["event_id"]
        assert isinstance(first["created_at"], int) and first["created_at"] > 0
        stored = _rows(
            apply_db,
            "SELECT operation_id, context_json FROM security_audit_events WHERE event_id = ?",
            (first["event_id"],),
        )[0]
        assert stored == ("op-writer-1", '{"a":1,"中文":"审计"}')
        forged_activation = audit.append_security_audit_event(
            action="security.audit.foundation.activate",
            risk_level="L3",
            result="success",
            actor_type="local_operator",
            operation_id="op-forged-activation-role",
            actor_user_id="admin-id",
            actor_role="super_admin",
            actor_label="temporary-local-operator",
            reason="verify current database role wins",
            database_path=apply_db,
        )
        assert _rows(
            apply_db,
            "SELECT actor_role FROM security_audit_events WHERE event_id = ?",
            (forged_activation["event_id"],),
        ) == [("admin",)]

        validation_cases = (
            _event_kwargs(""),
            _event_kwargs("op-unknown-action", action="security.unknown"),
            _event_kwargs("op-unknown-risk", risk_level="L9"),
            _event_kwargs("op-risk-mismatch", action="security.audit.foundation.activate"),
            _event_kwargs("op-unknown-result", result="complete"),
            _event_kwargs("op-unknown-actor", actor_type="browser"),
            _event_kwargs("op-invalid-role", actor_role=" admin "),
            _event_kwargs("op-user-no-role", actor_role=None),
            _event_kwargs(
                "op-system-user",
                actor_type="system",
                actor_user_id="admin-id",
                actor_role=None,
            ),
            _event_kwargs(
                "op-local-no-label",
                actor_type="local_operator",
                actor_user_id=None,
                actor_role=None,
                actor_label=None,
            ),
            _event_kwargs(
                "op-l3-no-reason",
                action="security.audit.foundation.initialize",
                risk_level="L3",
                actor_type="system",
                actor_user_id=None,
                actor_role=None,
            ),
        )
        for values in validation_cases:
            _assert_raises(
                audit.SecurityAuditValidationError,
                lambda event=values: audit.append_security_audit_event(
                    **event,
                    database_path=apply_db,
                ),
            )

        _assert_raises(
            audit.SecurityAuditSchemaError,
            lambda: audit.append_security_audit_event(
                **_event_kwargs("op-schema-missing"),
                database_path=plan_db,
            ),
        )
        writer_missing_path = tmp / "writer-missing.db"
        _assert_raises(
            audit.SecurityAuditSchemaError,
            lambda: audit.append_security_audit_event(
                **_event_kwargs("op-writer-missing-path"),
                database_path=writer_missing_path,
            ),
        )
        assert not writer_missing_path.exists()
        for values in (
            _event_kwargs("x" * 129),
            _event_kwargs(
                "op-overlong-reason",
                action="security.audit.foundation.initialize",
                risk_level="L3",
                actor_type="system",
                actor_user_id=None,
                actor_role=None,
                reason="x" * 2049,
            ),
            _event_kwargs(
                "op-overlong-label",
                actor_type="local_operator",
                actor_user_id=None,
                actor_role=None,
                actor_label="x" * 257,
            ),
        ):
            _assert_raises(
                audit.SecurityAuditValidationError,
                lambda event=values: audit.append_security_audit_event(
                    **event,
                    database_path=apply_db,
                ),
            )

        # F/G. Caller-owned transaction, rollback, and fail-closed write error.
        conn = sqlite3.connect(apply_db)
        conn.execute("CREATE TABLE transaction_probe (id TEXT PRIMARY KEY)")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO transaction_probe (id) VALUES ('rollback-business')")
        audit.append_security_audit_event(
            **_event_kwargs("op-transaction-rollback"),
            connection=conn,
        )
        assert conn.in_transaction is True
        conn.rollback()
        assert conn.execute(
            "SELECT COUNT(*) FROM transaction_probe WHERE id = 'rollback-business'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM security_audit_events WHERE operation_id = 'op-transaction-rollback'"
        ).fetchone()[0] == 0

        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO transaction_probe (id) VALUES ('commit-business')")
        audit.append_security_audit_event(
            **_event_kwargs("op-transaction-commit", result="success"),
            connection=conn,
        )
        assert conn.in_transaction is True
        conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) FROM transaction_probe WHERE id = 'commit-business'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM security_audit_events WHERE operation_id = 'op-transaction-commit'"
        ).fetchone()[0] == 1

        conn.execute(
            """
            CREATE TEMP TRIGGER fail_mandatory_audit
            BEFORE INSERT ON security_audit_events
            WHEN NEW.operation_id = 'op-injected-write-failure'
            BEGIN
                SELECT RAISE(ABORT, 'injected write failure');
            END
            """
        )
        conn.commit()
        usage_count = conn.execute("SELECT COUNT(*) FROM usage_logs").fetchone()[0]
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO transaction_probe (id) VALUES ('failed-business')")
        _assert_raises(
            audit.SecurityAuditWriteError,
            lambda: audit.append_security_audit_event(
                **_event_kwargs("op-injected-write-failure"),
                connection=conn,
            ),
        )
        assert conn.in_transaction is True
        conn.rollback()
        assert conn.execute(
            "SELECT COUNT(*) FROM transaction_probe WHERE id = 'failed-business'"
        ).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM usage_logs").fetchone()[0] == usage_count
        conn.execute("DROP TRIGGER fail_mandatory_audit")
        conn.commit()

        # H. Main-schema UPDATE/DELETE triggers preserve immutable rows.
        immutable = conn.execute(
            "SELECT event_id, action, result FROM security_audit_events ORDER BY id LIMIT 1"
        ).fetchone()
        _assert_raises(
            sqlite3.IntegrityError,
            lambda: conn.execute(
                "UPDATE security_audit_events SET result = 'failed' WHERE event_id = ?",
                (immutable[0],),
            ),
        )
        conn.rollback()
        _assert_raises(
            sqlite3.IntegrityError,
            lambda: conn.execute(
                "DELETE FROM security_audit_events WHERE event_id = ?",
                (immutable[0],),
            ),
        )
        conn.rollback()
        assert conn.execute(
            "SELECT event_id, action, result FROM security_audit_events WHERE event_id = ?",
            (immutable[0],),
        ).fetchone() == immutable
        inserted = audit.append_security_audit_event(
            **_event_kwargs("op-after-trigger-check"),
            connection=conn,
        )
        conn.commit()
        assert inserted["event_id"]
        conn.close()

        # I. Sensitive keys reject exact, case, separator, nested, and list forms.
        secret_value = "must-not-appear-in-errors"
        sensitive_keys = (
            "password",
            "password_hash",
            "token",
            "jwt",
            "cookie",
            "authorization",
            "api_key",
            "secret",
            "access_token",
            "refresh_token",
            "operation_token",
            "private_key",
        )
        contexts = [{key: secret_value} for key in sensitive_keys]
        contexts.extend(
            [
                {"Password-Hash": secret_value},
                {"APIKey": secret_value},
                {"nested": {"Client_Secret": secret_value}},
                {"items": [{"AUTHORIZATION": secret_value}]},
            ]
        )
        event_count_before = len(_rows(apply_db, "SELECT id FROM security_audit_events"))
        for index, context in enumerate(contexts):
            exc = _assert_raises(
                audit.SecurityAuditValidationError,
                lambda i=index, c=context: audit.append_security_audit_event(
                    **_event_kwargs(f"op-sensitive-{i}", context=c),
                    database_path=apply_db,
                ),
            )
            assert secret_value not in str(exc)
        assert len(_rows(apply_db, "SELECT id FROM security_audit_events")) == event_count_before

        # J. JSON-safe type, depth, key, string, and serialized size limits.
        json_invalid = (
            {"value": b"bytes"},
            {1: "non-string-key"},
            {"value": object()},
            {"value": float("nan")},
            {"value": float("inf")},
            {"a": {"b": {"c": {"d": {"e": 1}}}}},
            {f"key-{i}": i for i in range(101)},
            {"value": "x" * 2049},
            {f"chunk-{i}": "x" * 2000 for i in range(9)},
        )
        for index, context in enumerate(json_invalid):
            _assert_raises(
                audit.SecurityAuditValidationError,
                lambda i=index, c=context: audit.append_security_audit_event(
                    **_event_kwargs(f"op-json-invalid-{i}", context=c),
                    database_path=apply_db,
                ),
            )
        chinese_event = audit.append_security_audit_event(
            **_event_kwargs("op-chinese-context", context={"状态": "已拒绝", "数量": 2}),
            database_path=apply_db,
        )
        chinese_json = _rows(
            apply_db,
            "SELECT context_json FROM security_audit_events WHERE event_id = ?",
            (chinese_event["event_id"],),
        )[0][0]
        assert json.loads(chinese_json) == {"状态": "已拒绝", "数量": 2}

        # K/L. init_db remains unchanged; explicit activation and usage_logs coexist.
        fresh_app_db = tmp / "fresh-app.db"
        edb.DB_PATH = str(fresh_app_db)
        edb.ADMIN_USERNAME = "admin"
        edb.ADMIN_PASSWORD = "temporary-admin-password"
        edb.init_db()
        assert inspect_security_audit_schema(fresh_app_db)["current_state"] == audit.SECURITY_AUDIT_MISSING
        default_admin = edb.get_user_by_username("admin")
        assert default_admin and default_admin["role"] == "admin"
        apply_security_audit_migration(
            fresh_app_db,
            actor_user_id=default_admin["id"],
            actor_label="temporary-local-operator",
            operation_id="op-fresh-explicit-activation",
            reason="explicit temporary fresh database activation",
        )
        assert inspect_security_audit_schema(fresh_app_db)["current_state"] == audit.SECURITY_AUDIT_READY
        edb.log_action(default_admin["id"], "sec_1f0_usage_log_regression", "ordinary log")
        logs, total = edb.get_logs(action="sec_1f0_usage_log_regression")
        assert total == 1 and logs[0]["detail"] == "ordinary log"

    print("SEC-1F0 mandatory security audit checks passed")


if __name__ == "__main__":
    _run_checks()
