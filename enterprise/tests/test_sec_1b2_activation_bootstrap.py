"""SEC-1B2 controlled activation and local bootstrap rehearsal checks.

Every database, backup manifest, password, token, and super-admin row in this
script is temporary test data.  It never opens a production database.
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("JWT_SECRET", "sec-1b2-temporary-secret-at-least-32-bytes")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "temporary-admin-password")


def _assert_raises(error_type, func):
    try:
        func()
    except error_type as exc:
        return exc
    raise AssertionError(f"expected {error_type.__name__}")


def _sha256(path: Path) -> str:
    from enterprise.security_bootstrap import _sha256_file

    return _sha256_file(path)


def _legacy_database(path: Path, *, include_null_is_admin_user: bool = False) -> None:
    from enterprise import db as edb

    now = int(time.time() * 1000)
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
    users = [
        ("admin-id", "admin", edb._hash_password("admin-password"), "Admin", 1, 1, now, None),
        ("admin-two-id", "admin-two", edb._hash_password("admin-two-password"), "Admin Two", 1, 1, now, None),
        ("user-id", "user", edb._hash_password("user-password"), "User", 0, 1, now, None),
    ]
    if include_null_is_admin_user:
        users.append(
            (
                "null-user-id",
                "null-user",
                edb._hash_password("null-user-password"),
                "NULL User",
                None,
                1,
                now,
                321,
            )
        )
    conn.executemany(
        """
        INSERT INTO users (
            id, username, password_hash, display_name,
            is_admin, is_active, created_at, last_login
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        users,
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


def _manifest(tmp: Path, source_db: Path, *, now_ms: int, **changes) -> Path:
    backup_db = tmp / f"backup-{len(list(tmp.glob('backup-*.db')))}.db"
    with sqlite3.connect(source_db) as source_conn:
        source_journal_mode = str(source_conn.execute("PRAGMA main.journal_mode").fetchone()[0]).casefold()
        with sqlite3.connect(backup_db) as backup_conn:
            source_conn.backup(backup_conn)
    payload = {
        "kind": "backup-manifest",
        "backup_id": "temporary-backup",
        "status": "pass",
        "dry_run": False,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ms / 1000)),
        "sqlite_backup_status": "success",
        "sqlite_backup_path": backup_db.as_posix(),
        "sqlite_backup_size_bytes": backup_db.stat().st_size,
        "sqlite_backup_sha256": _sha256(backup_db),
        "source_database_relative_path": "data/enterprise.db",
        "source_database_size_bytes": source_db.stat().st_size,
        "source_database_sha256": _sha256(source_db),
        "source_database_journal_mode": source_journal_mode,
        "warnings": [],
    }
    payload.update(changes)
    manifest = tmp / f"manifest-{len(list(tmp.glob('manifest-*.json')))}.json"
    manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return manifest


def _schema_rows(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT type, name, tbl_name, sql FROM main.sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        conn.close()


def _user(path: Path, user_id: str) -> dict:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM main.users WHERE id = ?", (user_id,)).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def _audit_rows(path: Path, operation_id: str) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM main.security_audit_events WHERE operation_id = ? ORDER BY id",
            (operation_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _table_exists(path: Path, table: str) -> bool:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT 1 FROM main.sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone() is not None
    finally:
        conn.close()


def _checkpoint_temporary_wal(path: Path) -> None:
    """Create the documented stopped-service precondition in a temporary fixture only."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    finally:
        conn.close()
    assert not Path(f"{path}-wal").exists()
    assert not Path(f"{path}-shm").exists()


def _plan(path: Path, manifest: Path, now_ms: int) -> dict:
    from enterprise.security_bootstrap import plan_sec_1b2_activation

    return plan_sec_1b2_activation(
        database_path=path,
        target_user_id="admin-id",
        target_username="admin",
        actor_label="temporary-local-operator",
        reason="temporary SEC-1B2 rehearsal",
        backup_manifest_path=manifest,
        now_ms=now_ms,
    )


def _execute(path: Path, manifest: Path, plan: dict, now_ms: int, password: str = "admin-password") -> dict:
    from enterprise.security_bootstrap import execute_sec_1b2_activation

    return execute_sec_1b2_activation(
        database_path=path,
        plan=plan,
        expected_plan_hash=plan["plan_hash"],
        backup_manifest_path=manifest,
        target_user_id="admin-id",
        target_username="admin",
        actor_label="temporary-local-operator",
        reason="temporary SEC-1B2 rehearsal",
        current_password=password,
        now_ms=now_ms,
    )


def _run_checks() -> None:
    from enterprise import auth
    from enterprise import db as edb
    from enterprise.migrations.sec_1b1_role_auth import (
        ROLE_AUTH_READY,
        SCHEMA_LEGACY,
        SCHEMA_PARTIAL,
        RoleAuthMigrationError,
        apply_role_auth_migration_in_transaction,
        inspect_role_auth_schema,
    )
    from enterprise.migrations.sec_1b2_activation import (
        BOOTSTRAP_CREATE_TABLE_SQL,
        BOOTSTRAP_INDEX_DEFINITIONS,
        BOOTSTRAP_PARTIAL,
        BOOTSTRAP_READY,
        BOOTSTRAP_TRIGGER_DEFINITIONS,
        BootstrapLifecycleMigrationError,
        ensure_bootstrap_lifecycle_schema_in_transaction,
        inspect_bootstrap_lifecycle_schema,
    )
    from enterprise.migrations.sec_1f0_security_audit import (
        SecurityAuditMigrationError,
        apply_security_audit_migration_in_transaction,
    )
    from enterprise.security_bootstrap import (
        LIFECYCLE_ACTIVE,
        LIFECYCLE_RECOVERY_REQUIRED,
        LIFECYCLE_UNINITIALIZED,
        SecurityBootstrapConcurrentDatabaseChange,
        SecurityBootstrapError,
        SecurityBootstrapBackupError,
        SecurityBootstrapIntegrityError,
        SecurityBootstrapLifecycleError,
        SecurityBootstrapLockError,
        SecurityBootstrapPasswordError,
        SecurityBootstrapPostCommitError,
        SecurityBootstrapPlanError,
        SecurityBootstrapValidationError,
        _plan_hash,
        execute_sec_1b2_activation,
        inspect_super_admin_lifecycle,
        plan_sec_1b2_activation,
        prepare_sec_1b2_journal,
        validate_sec_1b2_plan,
    )
    from enterprise.security_audit import SECURITY_AUDIT_MISSING, SECURITY_AUDIT_READY
    from tools import sec_1b2_local_runner as runner

    def seed_lifecycle_fixture(
        path: Path,
        *,
        marker_changes: dict | None = None,
        audit_changes: dict | None = None,
    ) -> None:
        _legacy_database(path)
        conn = sqlite3.connect(path)
        try:
            conn.execute("BEGIN")
            apply_role_auth_migration_in_transaction(conn)
            conn.commit()
            conn.execute("BEGIN")
            apply_security_audit_migration_in_transaction(
                conn,
                actor_user_id="admin-id",
                actor_label="temporary-operator",
                operation_id="fixture-foundation",
                reason="temporary lifecycle fixture",
            )
            conn.commit()
            conn.execute(
                """
                UPDATE main.users
                SET role = 'super_admin', is_admin = 1, auth_version = 2,
                    role_updated_at = 1, role_updated_by = 'admin-id'
                WHERE id = 'admin-id'
                """
            )
            conn.execute(BOOTSTRAP_CREATE_TABLE_SQL)
            marker = {
                "singleton_id": 1,
                "bootstrap_completed_at": 1,
                "bootstrap_completed_by": "admin-id",
                "bootstrap_target_user_id": "admin-id",
                "bootstrap_operation_id": "fixture-bootstrap",
                "bootstrap_actor_label": "temporary-operator",
                "created_at": 1,
            }
            marker.update(marker_changes or {})
            conn.execute("PRAGMA ignore_check_constraints = ON")
            conn.execute(
                """
                INSERT INTO main.security_governance_bootstrap (
                    singleton_id, bootstrap_completed_at, bootstrap_completed_by,
                    bootstrap_target_user_id, bootstrap_operation_id,
                    bootstrap_actor_label, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(marker[name] for name in (
                    "singleton_id", "bootstrap_completed_at", "bootstrap_completed_by",
                    "bootstrap_target_user_id", "bootstrap_operation_id",
                    "bootstrap_actor_label", "created_at",
                )),
            )
            conn.execute("PRAGMA ignore_check_constraints = OFF")
            for definition in BOOTSTRAP_INDEX_DEFINITIONS.values():
                conn.execute(definition["sql"])
            for statement in BOOTSTRAP_TRIGGER_DEFINITIONS.values():
                conn.execute(statement)
            audit = {
                "event_id": "fixture-bootstrap-event",
                "operation_id": marker["bootstrap_operation_id"],
                "action": "security.super_admin.bootstrap",
                "risk_level": "L3",
                "result": "success",
                "actor_type": "local_operator",
                "actor_user_id": "admin-id",
                "actor_role": "super_admin",
                "actor_label": marker["bootstrap_actor_label"],
                "capability": None,
                "target_type": "user",
                "target_id": "admin-id",
                "reason": "temporary lifecycle fixture",
                "context_json": json.dumps(
                    {
                        "lifecycle_before": "UNINITIALIZED",
                        "lifecycle_after": "ACTIVE",
                        "role_before": "admin",
                        "role_after": "super_admin",
                        "auth_version_incremented": True,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "created_at": 1,
            }
            audit.update(audit_changes or {})
            conn.execute(
                """
                INSERT INTO main.security_audit_events (
                    event_id, operation_id, action, risk_level, result, actor_type,
                    actor_user_id, actor_role, actor_label, capability, target_type,
                    target_id, reason, context_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(audit[name] for name in (
                    "event_id", "operation_id", "action", "risk_level", "result", "actor_type",
                    "actor_user_id", "actor_role", "actor_label", "capability", "target_type",
                    "target_id", "reason", "context_json", "created_at",
                )),
            )
            conn.commit()
        finally:
            conn.close()

    now = int(time.time() * 1000)
    with tempfile.TemporaryDirectory(prefix="ice-sec-1b2-") as raw_tmp:
        tmp = Path(raw_tmp)
        original_db_path = edb.DB_PATH
        original_jwt_secret = auth.JWT_SECRET
        try:
            # A. main qualification and caller-owned transaction primitives.
            primitive_db = tmp / "primitive.db"
            _legacy_database(primitive_db)
            conn = sqlite3.connect(primitive_db)
            conn.execute("BEGIN")
            role_result = apply_role_auth_migration_in_transaction(conn)
            assert role_result["current_state"] == ROLE_AUTH_READY
            conn.rollback()
            conn.close()
            assert inspect_role_auth_schema(primitive_db)["current_state"] == SCHEMA_LEGACY
            conn = sqlite3.connect(primitive_db)
            conn.execute("BEGIN")
            audit_result = apply_security_audit_migration_in_transaction(
                conn,
                actor_user_id="admin-id",
                actor_label="temporary-operator",
                operation_id="primitive-audit",
                reason="temporary transaction primitive",
            )
            assert audit_result["activation_event_written"] is True
            conn.rollback()
            conn.close()
            assert not _table_exists(primitive_db, "security_audit_events")
            conn = sqlite3.connect(primitive_db)
            conn.execute("CREATE TEMP TABLE users (id TEXT)")
            assert inspect_role_auth_schema(conn)["current_state"] == SCHEMA_PARTIAL
            conn.execute("BEGIN")
            _assert_raises(RoleAuthMigrationError, lambda: apply_role_auth_migration_in_transaction(conn))
            conn.rollback()
            conn.execute("DROP TABLE temp.users")
            conn.execute(
                "CREATE TEMP TRIGGER temp_users_block BEFORE UPDATE ON main.users "
                "BEGIN SELECT RAISE(IGNORE); END"
            )
            assert inspect_role_auth_schema(conn)["current_state"] == SCHEMA_PARTIAL
            conn.execute("BEGIN")
            _assert_raises(RoleAuthMigrationError, lambda: apply_role_auth_migration_in_transaction(conn))
            conn.rollback()
            conn.close()

            # A2. The caller-owned SEC-1B1 primitive treats NULL legacy
            # administrator flags as ordinary users, normalizes them on
            # commit, and leaves them untouched when the caller rolls back.
            null_primitive_commit_db = tmp / "null-primitive-commit.db"
            _legacy_database(null_primitive_commit_db, include_null_is_admin_user=True)
            conn = sqlite3.connect(null_primitive_commit_db)
            conn.execute("BEGIN")
            null_role_result = apply_role_auth_migration_in_transaction(conn)
            assert null_role_result["current_state"] == ROLE_AUTH_READY
            assert conn.in_transaction is True
            null_committed = conn.execute(
                "SELECT role, is_admin, typeof(is_admin), auth_version "
                "FROM main.users WHERE id = 'null-user-id'"
            ).fetchone()
            assert null_committed == ("user", 0, "integer", 1)
            conn.commit()
            conn.close()
            null_commit_inspection = inspect_role_auth_schema(null_primitive_commit_db)
            assert null_commit_inspection["current_state"] == ROLE_AUTH_READY
            assert null_commit_inspection["invalid_ready_is_admin_count"] == 0
            assert null_commit_inspection["role_is_admin_mismatch_count"] == 0

            null_primitive_rollback_db = tmp / "null-primitive-rollback.db"
            _legacy_database(null_primitive_rollback_db, include_null_is_admin_user=True)
            conn = sqlite3.connect(null_primitive_rollback_db)
            conn.execute("BEGIN")
            apply_role_auth_migration_in_transaction(conn)
            assert conn.in_transaction is True
            conn.rollback()
            assert conn.execute(
                "SELECT is_admin FROM main.users WHERE id = 'null-user-id'"
            ).fetchone()[0] is None
            conn.close()
            assert inspect_role_auth_schema(null_primitive_rollback_db)["current_state"] == SCHEMA_LEGACY

            # B. Canonical immutable lifecycle schema, including append-only behavior.
            lifecycle_db = tmp / "lifecycle.db"
            _legacy_database(lifecycle_db)
            conn = sqlite3.connect(lifecycle_db)
            conn.execute("BEGIN")
            created = ensure_bootstrap_lifecycle_schema_in_transaction(conn)
            assert created["current_state"] == BOOTSTRAP_READY
            conn.commit()
            conn.close()
            lifecycle_schema = inspect_bootstrap_lifecycle_schema(lifecycle_db)
            assert lifecycle_schema["current_state"] == BOOTSTRAP_READY
            conn = sqlite3.connect(lifecycle_db)
            conn.execute("INSERT INTO main.security_governance_bootstrap VALUES (1, 1, 'a', 'a', 'op', 'label', 1)")
            conn.commit()
            for sql in (
                "UPDATE main.security_governance_bootstrap SET bootstrap_actor_label = 'x'",
                "DELETE FROM main.security_governance_bootstrap",
            ):
                try:
                    conn.execute(sql)
                except sqlite3.DatabaseError:
                    pass
                else:
                    raise AssertionError("bootstrap marker must be append-only")
            conn.close()
            partial_db = tmp / "lifecycle-partial.db"
            _legacy_database(partial_db)
            conn = sqlite3.connect(partial_db)
            conn.execute("CREATE TABLE security_governance_bootstrap (singleton_id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()
            assert inspect_bootstrap_lifecycle_schema(partial_db)["current_state"] == BOOTSTRAP_PARTIAL
            temp_lifecycle_db = tmp / "lifecycle-temp.db"
            _legacy_database(temp_lifecycle_db)
            conn = sqlite3.connect(temp_lifecycle_db)
            conn.execute("CREATE TEMP TABLE security_governance_bootstrap (singleton_id INTEGER)")
            assert inspect_bootstrap_lifecycle_schema(conn)["current_state"] == BOOTSTRAP_PARTIAL
            conn.close()

            # B2. Canonical marker DDL alone is not enough: corrupted raw marker
            # values or a non-equivalent bootstrap event require recovery.
            valid_lifecycle_db = tmp / "lifecycle-valid.db"
            seed_lifecycle_fixture(valid_lifecycle_db)
            assert inspect_bootstrap_lifecycle_schema(valid_lifecycle_db)["current_state"] == BOOTSTRAP_READY
            assert inspect_super_admin_lifecycle(valid_lifecycle_db)["lifecycle_state"] == LIFECYCLE_ACTIVE
            marker_corruptions = (
                {"bootstrap_completed_by": "other-admin"},
                {"bootstrap_completed_at": -1},
                {"bootstrap_completed_at": "bad", "created_at": "bad"},
                {"bootstrap_operation_id": ""},
                {"bootstrap_actor_label": ""},
            )
            for index, change in enumerate(marker_corruptions):
                corrupted = tmp / f"lifecycle-marker-corrupt-{index}.db"
                seed_lifecycle_fixture(corrupted, marker_changes=change)
                assert inspect_bootstrap_lifecycle_schema(corrupted)["current_state"] == BOOTSTRAP_READY
                assert inspect_super_admin_lifecycle(corrupted)["lifecycle_state"] == LIFECYCLE_RECOVERY_REQUIRED
            audit_corruptions = (
                {"actor_user_id": "other-admin"},
                {"target_id": "other-admin"},
                {"risk_level": "L2"},
                {"actor_role": "admin"},
                {"context_json": "{}"},
                {
                    "context_json": json.dumps(
                        {
                            "lifecycle_before": "UNINITIALIZED",
                            "lifecycle_after": "ACTIVE",
                            "role_before": "admin",
                            "role_after": "super_admin",
                            "auth_version_incremented": 1,
                        }
                    )
                },
                {
                    "context_json": json.dumps(
                        {
                            "lifecycle_before": "UNINITIALIZED",
                            "lifecycle_after": "ACTIVE",
                            "role_before": "admin",
                            "role_after": "super_admin",
                            "auth_version_incremented": "true",
                        }
                    )
                },
                {
                    "context_json": json.dumps(
                        {
                            "lifecycle_before": "UNINITIALIZED",
                            "lifecycle_after": "ACTIVE",
                            "role_before": "admin",
                            "role_after": "super_admin",
                        }
                    )
                },
                {
                    "context_json": json.dumps(
                        {
                            "lifecycle_before": "UNINITIALIZED",
                            "lifecycle_after": "ACTIVE",
                            "role_before": "admin",
                            "role_after": "super_admin",
                            "auth_version_incremented": True,
                            "unexpected": "field",
                        }
                    )
                },
                {
                    "context_json": (
                        '{"lifecycle_before":"UNINITIALIZED","lifecycle_after":"ACTIVE",'
                        '"role_before":"admin","role_after":"user","role_after":"super_admin",'
                        '"auth_version_incremented":true}'
                    )
                },
                {
                    "context_json": (
                        '{"lifecycle_before":"UNINITIALIZED","lifecycle_after":"ACTIVE",'
                        '"role_before":"admin","role_after":"super_admin","role_after":"user",'
                        '"auth_version_incremented":true}'
                    )
                },
                {"context_json": json.dumps(["not", "a", "context"] )},
                {
                    "context_json": json.dumps(
                        {
                            "lifecycle_before": 1,
                            "lifecycle_after": "ACTIVE",
                            "role_before": "admin",
                            "role_after": "super_admin",
                            "auth_version_incremented": True,
                        }
                    )
                },
                {
                    "context_json": json.dumps(
                        {
                            "lifecycle_before": "UNINITIALIZED",
                            "lifecycle_after": "ACTIVE",
                            "role_before": "admin",
                            "role_after": ["super_admin"],
                            "auth_version_incremented": True,
                        }
                    )
                },
            )
            for index, change in enumerate(audit_corruptions):
                corrupted = tmp / f"lifecycle-audit-corrupt-{index}.db"
                seed_lifecycle_fixture(corrupted, audit_changes=change)
                assert inspect_super_admin_lifecycle(corrupted)["lifecycle_state"] == LIFECYCLE_RECOVERY_REQUIRED

            # An otherwise valid marker and bootstrap audit cannot make an
            # ACTIVE lifecycle out of raw READY compatibility corruption.
            ready_data_corrupt = tmp / "lifecycle-ready-data-corrupt.db"
            seed_lifecycle_fixture(ready_data_corrupt)
            conn = sqlite3.connect(ready_data_corrupt)
            conn.execute("UPDATE main.users SET is_admin = NULL WHERE id = 'user-id'")
            conn.commit()
            conn.close()
            assert inspect_role_auth_schema(ready_data_corrupt)["invalid_ready_is_admin_count"] == 1
            assert inspect_super_admin_lifecycle(ready_data_corrupt)["lifecycle_state"] == LIFECYCLE_RECOVERY_REQUIRED

            # C. Read-only plan and executed-backup gates.
            plan_db = tmp / "plan.db"
            _legacy_database(plan_db)
            manifest = _manifest(tmp, plan_db, now_ms=now)
            before_bytes = plan_db.read_bytes()
            before_schema = _schema_rows(plan_db)
            plan = _plan(plan_db, manifest, now)
            assert plan["role_auth_state_before"] == SCHEMA_LEGACY
            assert plan["audit_state_before"] == SECURITY_AUDIT_MISSING
            assert plan["lifecycle_state_before"] == LIFECYCLE_UNINITIALIZED
            assert plan["target_role_before"] == "admin"
            assert plan["target_auth_version_before"] == 0
            assert plan["plan_hash"]
            assert plan_db.read_bytes() == before_bytes
            assert _schema_rows(plan_db) == before_schema
            assert "admin-password" not in json.dumps(plan)

            # Plan identity and time bounds are validated before a runner can
            # prompt for a password or confirmation phrase.
            def resign_plan(candidate: dict) -> dict:
                unsigned = dict(candidate)
                unsigned.pop("plan_hash", None)
                candidate["plan_hash"] = _plan_hash(unsigned)
                return candidate

            actor_mismatch_plan = resign_plan(dict(plan, actor_user_id="different-admin"))
            _assert_raises(
                SecurityBootstrapPlanError,
                lambda: validate_sec_1b2_plan(
                    actor_mismatch_plan,
                    actor_mismatch_plan["plan_hash"],
                    now_ms=now,
                ),
            )
            future_plan = resign_plan(dict(plan, created_at=now + 1, expires_at=now + 2))
            _assert_raises(
                SecurityBootstrapPlanError,
                lambda: validate_sec_1b2_plan(
                    future_plan,
                    future_plan["plan_hash"],
                    now_ms=now,
                ),
            )
            equal_time_plan = resign_plan(dict(plan, created_at=now, expires_at=now))
            _assert_raises(
                SecurityBootstrapPlanError,
                lambda: validate_sec_1b2_plan(
                    equal_time_plan,
                    equal_time_plan["plan_hash"],
                    now_ms=now,
                ),
            )
            for changes in (
                {"dry_run": True},
                {"status": "fail"},
                {"sqlite_backup_status": "failed"},
                {"sqlite_backup_sha256": "0" * 64},
                {"generated_at": "2000-01-01T00:00:00Z"},
            ):
                invalid_manifest = _manifest(tmp, plan_db, now_ms=now, **changes)
                _assert_raises(SecurityBootstrapBackupError, lambda m=invalid_manifest: _plan(plan_db, m, now))
            _assert_raises(
                SecurityBootstrapValidationError,
                lambda: plan_sec_1b2_activation(
                    database_path=plan_db,
                    target_user_id="user-id",
                    target_username="user",
                    actor_label="temporary-local-operator",
                    reason="temporary SEC-1B2 rehearsal",
                    backup_manifest_path=manifest,
                    now_ms=now,
                ),
            )

            # C2. A successful backup must be a real sqlite3 backup of this
            # database, not merely a separately valid SQLite file.
            unrelated_db = tmp / "unrelated-source.db"
            _legacy_database(unrelated_db)
            unrelated_manifest = _manifest(tmp, unrelated_db, now_ms=now)
            _assert_raises(SecurityBootstrapBackupError, lambda: _plan(plan_db, unrelated_manifest, now))
            wrong_source_manifest = _manifest(
                tmp,
                plan_db,
                now_ms=now,
                source_database_sha256="0" * 64,
            )
            _assert_raises(SecurityBootstrapBackupError, lambda: _plan(plan_db, wrong_source_manifest, now))
            missing_source_manifest = _manifest(tmp, plan_db, now_ms=now, source_database_sha256=None)
            _assert_raises(SecurityBootstrapBackupError, lambda: _plan(plan_db, missing_source_manifest, now))

            # C3. WAL is intentionally not activation-safe until the local
            # preparation step completes; it changes no application rows.
            wal_db = tmp / "wal-prepare.db"
            _legacy_database(wal_db)
            edb.DB_PATH = str(wal_db)
            wal_conn = edb.get_db()
            wal_conn.close()
            _checkpoint_temporary_wal(wal_db)
            wal_manifest = _manifest(tmp, wal_db, now_ms=now)
            _assert_raises(SecurityBootstrapValidationError, lambda: _plan(wal_db, wal_manifest, now))
            before_wal_users = [_user(wal_db, user_id) for user_id in ("admin-id", "admin-two-id", "user-id")]
            journal_report = prepare_sec_1b2_journal(database_path=wal_db, now_ms=now)
            assert journal_report["journal_mode_before"] == "wal"
            assert journal_report["journal_mode_after"] == "delete"
            assert journal_report["database_label"] == wal_db.name
            assert _user(wal_db, "admin-id") == before_wal_users[0]
            assert _user(wal_db, "admin-two-id") == before_wal_users[1]
            assert _user(wal_db, "user-id") == before_wal_users[2]
            _plan(wal_db, _manifest(tmp, wal_db, now_ms=now), now)
            sidecar_db = tmp / "sidecar.db"
            _legacy_database(sidecar_db)
            sidecar_conn = sqlite3.connect(sidecar_db)
            sidecar_conn.execute("PRAGMA journal_mode = WAL")
            sidecar_conn.execute("CREATE TABLE sidecar_probe (id INTEGER PRIMARY KEY)")
            sidecar_conn.commit()
            assert Path(f"{sidecar_db}-wal").exists() or Path(f"{sidecar_db}-shm").exists()
            _assert_raises(SecurityBootstrapValidationError, lambda: prepare_sec_1b2_journal(database_path=sidecar_db, now_ms=now))
            assert Path(f"{sidecar_db}-wal").exists() or Path(f"{sidecar_db}-shm").exists()
            sidecar_conn.close()
            _checkpoint_temporary_wal(sidecar_db)
            lock_prepare_db = tmp / "prepare-lock.db"
            _legacy_database(lock_prepare_db)
            lock_prepare_conn = sqlite3.connect(lock_prepare_db)
            lock_prepare_conn.execute("BEGIN EXCLUSIVE")
            try:
                _assert_raises(SecurityBootstrapLockError, lambda: prepare_sec_1b2_journal(database_path=lock_prepare_db, now_ms=now))
            finally:
                lock_prepare_conn.rollback()
                lock_prepare_conn.close()

            # C3b. WAL -> DELETE must fail closed if another connection writes
            # during the transactionless switch gap. The runner report must not
            # claim that no database changes occurred when that writer commits.
            import enterprise.security_bootstrap as bootstrap_module

            def assert_window_change_rejected(label: str, mutate_external, *, after_switch: bool = False) -> None:
                window_db = tmp / f"journal-window-{label}.db"
                _legacy_database(window_db)
                conn = sqlite3.connect(window_db)
                conn.execute("PRAGMA journal_mode = WAL")
                conn.close()
                _checkpoint_temporary_wal(window_db)
                original_switch = bootstrap_module._switch_journal_mode_to_delete
                switch_calls = 0

                def mutate_then_switch(preparation_conn, **kwargs):
                    nonlocal switch_calls
                    switch_calls += 1
                    if after_switch:
                        original_switch(preparation_conn, **kwargs)
                    external = sqlite3.connect(window_db)
                    try:
                        mutate_external(external)
                        external.commit()
                    finally:
                        external.close()
                    if not after_switch:
                        return original_switch(preparation_conn, **kwargs)
                    return None

                bootstrap_module._switch_journal_mode_to_delete = mutate_then_switch
                report_path = tmp / f"journal-window-{label}-report.json"
                original_runner_input = getattr(runner, "input", None)
                runner.input = lambda _prompt: f"SEC-1B2 PREPARE-JOURNAL {window_db.name}"
                stderr = StringIO()
                try:
                    with redirect_stderr(stderr):
                        assert runner.main(
                            [
                                "prepare-journal",
                                "--database", str(window_db),
                                "--report-output", str(report_path),
                                "--confirm-service-stopped",
                            ]
                        ) == 2
                finally:
                    bootstrap_module._switch_journal_mode_to_delete = original_switch
                    if original_runner_input is None:
                        del runner.input
                    else:
                        runner.input = original_runner_input
                assert switch_calls == 1
                report = json.loads(report_path.read_text(encoding="utf-8"))
                assert report["success"] is False
                assert report["error_code"] == SecurityBootstrapConcurrentDatabaseChange.code
                assert report["execution_state"] == "database_changed_during_journal_preparation"
                assert report["database_transaction_rolled_back"] is False
                assert report["no_database_changes_committed"] is False
                assert report["database_changes_committed"] is after_switch
                assert report["external_database_changes_detected"] is True
                assert report["post_commit_verification_required"] is True
                assert report["do_not_rerun_until_status_verified"] is True
                assert report["journal_mode_changed"] is after_switch
                serialized_report = json.dumps(report, ensure_ascii=False)
                assert "temporary-window-secret" not in serialized_report
                assert "temporary-window-secret" not in stderr.getvalue()
                assert "database changed during preparation" in stderr.getvalue().casefold()
                assert "do not rerun" in stderr.getvalue().casefold()
                assert "run status" in stderr.getvalue().casefold()
                journal_conn = sqlite3.connect(window_db)
                try:
                    mode = str(journal_conn.execute("PRAGMA main.journal_mode").fetchone()[0]).casefold()
                finally:
                    journal_conn.close()
                assert mode == ("delete" if after_switch else "wal")

            assert_window_change_rejected(
                "canvas-map",
                lambda conn: conn.execute(
                    "INSERT INTO main.user_canvas_map (user_id, canvas_id, created_at) VALUES (?, ?, ?)",
                    ("user-id", "temporary-window-secret-canvas", now),
                ),
            )
            assert_window_change_rejected(
                "usage-logs",
                lambda conn: conn.execute(
                    "INSERT INTO main.usage_logs (user_id, action, detail, ts) VALUES (?, ?, ?, ?)",
                    ("user-id", "window-change", "temporary-window-secret-usage", now),
                ),
            )
            assert_window_change_rejected(
                "schema",
                lambda conn: conn.execute("CREATE TABLE journal_window_schema (id INTEGER PRIMARY KEY)"),
            )
            assert_window_change_rejected(
                "users",
                lambda conn: conn.execute(
                    "UPDATE main.users SET display_name = ? WHERE id = ?",
                    ("temporary-window-secret-users", "user-id"),
                ),
            )
            assert_window_change_rejected(
                "after-switch",
                lambda conn: conn.execute(
                    "INSERT INTO main.usage_logs (user_id, action, detail, ts) VALUES (?, ?, ?, ?)",
                    ("user-id", "after-switch", "temporary-window-secret-after", now),
                ),
                after_switch=True,
            )
            delete_journal_db = tmp / "delete-journal.db"
            _legacy_database(delete_journal_db)
            delete_report = prepare_sec_1b2_journal(database_path=delete_journal_db, now_ms=now)
            assert delete_report["journal_mode_before"] == "delete"
            assert delete_report["journal_mode_after"] == "delete"
            runner_prepare_db = tmp / "runner-prepare.db"
            _legacy_database(runner_prepare_db)
            conn = sqlite3.connect(runner_prepare_db)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.close()
            _checkpoint_temporary_wal(runner_prepare_db)
            runner_prepare_report = tmp / "runner-prepare-report.json"
            original_runner_input = getattr(runner, "input", None)
            runner.input = lambda _prompt: f"SEC-1B2 PREPARE-JOURNAL {runner_prepare_db.name}"
            try:
                assert runner.main(
                    [
                        "prepare-journal",
                        "--database", str(runner_prepare_db),
                        "--report-output", str(runner_prepare_report),
                        "--confirm-service-stopped",
                    ]
                ) == 0
            finally:
                if original_runner_input is None:
                    del runner.input
                else:
                    runner.input = original_runner_input
            prepared_report = json.loads(runner_prepare_report.read_text(encoding="utf-8"))
            assert prepared_report["success"] is True
            assert prepared_report["journal_mode_before"] == "wal"
            assert prepared_report["journal_mode_after"] == "delete"
            assert str(runner_prepare_db) not in json.dumps(prepared_report)

            # D. Complete LEGACY -> ACTIVE activation and session invalidation.
            edb.DB_PATH = str(plan_db)
            auth.JWT_SECRET = "sec-1b2-token-test-secret-at-least-32-bytes"
            legacy_target_token = auth.create_token("admin-id")
            legacy_user_token = auth.create_token("user-id")
            assert auth.verify_token(legacy_target_token) is not None
            # A stopped-service window uses the runner's explicit, tested WAL
            # preparation path. A fresh formal backup must follow that header
            # change before activation planning can bind it to the source DB.
            _checkpoint_temporary_wal(plan_db)
            journal_report = prepare_sec_1b2_journal(database_path=plan_db, now_ms=now)
            assert journal_report["journal_mode_before"] == "wal"
            assert journal_report["journal_mode_after"] == "delete"
            manifest = _manifest(tmp, plan_db, now_ms=now)
            plan = _plan(plan_db, manifest, now)
            report = _execute(plan_db, manifest, plan, now + 1)
            assert report["success"] is True
            assert report["target_auth_version_before"] == 1
            assert report["target_auth_version_after"] == 2
            assert all(report["event_ids"].values())
            lifecycle = inspect_super_admin_lifecycle(plan_db)
            assert lifecycle["lifecycle_state"] == LIFECYCLE_ACTIVE
            assert lifecycle["role_auth_state"] == ROLE_AUTH_READY
            assert lifecycle["audit_state"] == SECURITY_AUDIT_READY
            assert lifecycle["active_super_admin_count"] == 1
            assert _user(plan_db, "admin-id")["role"] == "super_admin"
            assert _user(plan_db, "admin-two-id")["role"] == "admin"
            assert _user(plan_db, "user-id")["role"] == "user"
            assert _user(plan_db, "admin-id")["auth_version"] == 2
            assert _user(plan_db, "admin-two-id")["auth_version"] == 1
            assert _user(plan_db, "user-id")["auth_version"] == 1
            assert auth.verify_token(legacy_target_token) is None
            assert auth.verify_token(legacy_user_token) is None
            assert auth.verify_token(auth.create_token("admin-id"))["role"] == "super_admin"
            events = _audit_rows(plan_db, plan["operation_id"])
            assert {row["action"] for row in events} == {
                "security.audit.foundation.activate",
                "security.role_auth.migration.activate",
                "security.super_admin.bootstrap",
            }
            assert {row["operation_id"] for row in events} == {plan["operation_id"]}
            conn = sqlite3.connect(plan_db)
            try:
                assert conn.execute("SELECT action FROM main.usage_logs WHERE id = 1").fetchone()[0] == "existing"
                assert conn.execute("SELECT user_id FROM main.user_canvas_map WHERE canvas_id = 'canvas-keep'").fetchone()[0] == "user-id"
            finally:
                conn.close()
            conn = sqlite3.connect(plan_db)
            assert str(conn.execute("PRAGMA journal_mode = DELETE").fetchone()[0]).casefold() == "delete"
            conn.close()
            snapshot_after_active = _schema_rows(plan_db)
            _assert_raises(SecurityBootstrapError, lambda: _execute(plan_db, manifest, plan, now + 2))
            _assert_raises(SecurityBootstrapError, lambda: _plan(plan_db, manifest, now + 2))
            assert _schema_rows(plan_db) == snapshot_after_active

            # D2. A complete LEGACY activation normalizes NULL is_admin to a
            # clean READY ordinary user before the marker can become ACTIVE.
            null_activation_db = tmp / "null-activation.db"
            _legacy_database(null_activation_db, include_null_is_admin_user=True)
            null_before = _user(null_activation_db, "null-user-id")
            null_prepare = prepare_sec_1b2_journal(database_path=null_activation_db, now_ms=now)
            assert null_prepare["journal_mode_after"] == "delete"
            null_manifest = _manifest(tmp, null_activation_db, now_ms=now)
            null_plan = _plan(null_activation_db, null_manifest, now)
            null_report = _execute(null_activation_db, null_manifest, null_plan, now + 1)
            assert null_report["success"] is True
            null_lifecycle = inspect_super_admin_lifecycle(null_activation_db)
            assert null_lifecycle["lifecycle_state"] == LIFECYCLE_ACTIVE
            assert null_lifecycle["active_super_admin_count"] == 1
            null_inspection = inspect_role_auth_schema(null_activation_db)
            assert null_inspection["current_state"] == ROLE_AUTH_READY
            for key in (
                "invalid_ready_is_admin_count",
                "invalid_is_active_count",
                "invalid_role_count",
                "invalid_auth_version_count",
                "role_is_admin_mismatch_count",
            ):
                assert null_inspection[key] == 0
            null_after = _user(null_activation_db, "null-user-id")
            for field in (
                "id",
                "username",
                "password_hash",
                "display_name",
                "is_active",
                "created_at",
                "last_login",
            ):
                assert null_after[field] == null_before[field]
                assert type(null_after[field]) is type(null_before[field])
            assert null_after["role"] == "user"
            assert type(null_after["is_admin"]) is int and null_after["is_admin"] == 0
            assert type(null_after["auth_version"]) is int and null_after["auth_version"] == 1
            assert _user(null_activation_db, "admin-id")["role"] == "super_admin"
            assert _user(null_activation_db, "admin-two-id")["role"] == "admin"
            conn = sqlite3.connect(null_activation_db)
            try:
                assert conn.execute(
                    "SELECT typeof(is_admin) FROM main.users WHERE id = 'null-user-id'"
                ).fetchone()[0] == "integer"
                assert conn.execute(
                    "SELECT action FROM main.usage_logs WHERE id = 1"
                ).fetchone()[0] == "existing"
                assert conn.execute(
                    "SELECT user_id FROM main.user_canvas_map WHERE canvas_id = 'canvas-keep'"
                ).fetchone()[0] == "user-id"
            finally:
                conn.close()
            null_events = _audit_rows(null_activation_db, null_plan["operation_id"])
            assert {event["action"] for event in null_events} == {
                "security.audit.foundation.activate",
                "security.role_auth.migration.activate",
                "security.super_admin.bootstrap",
            }

            # E. Wrong password and stale plan rollback without committed schema or users.
            rollback_db = tmp / "rollback.db"
            _legacy_database(rollback_db)
            rollback_manifest = _manifest(tmp, rollback_db, now_ms=now)
            rollback_plan = _plan(rollback_db, rollback_manifest, now)
            original_schema = _schema_rows(rollback_db)
            _assert_raises(
                SecurityBootstrapPasswordError,
                lambda: _execute(rollback_db, rollback_manifest, rollback_plan, now + 1, "wrong-password"),
            )
            assert _schema_rows(rollback_db) == original_schema
            assert not _table_exists(rollback_db, "security_audit_events")
            conn = sqlite3.connect(rollback_db)
            conn.execute("UPDATE main.users SET last_login = 1 WHERE id = 'user-id'")
            conn.commit()
            conn.close()
            _assert_raises(SecurityBootstrapPlanError, lambda: _execute(rollback_db, rollback_manifest, rollback_plan, now + 1))
            assert not _table_exists(rollback_db, "security_audit_events")

            backup_changed_db = tmp / "backup-changed.db"
            _legacy_database(backup_changed_db)
            backup_changed_manifest = _manifest(tmp, backup_changed_db, now_ms=now)
            backup_changed_plan = _plan(backup_changed_db, backup_changed_manifest, now)
            backup_path = Path(json.loads(backup_changed_manifest.read_text(encoding="utf-8"))["sqlite_backup_path"])
            backup_path.write_bytes(backup_path.read_bytes() + b"tampered")
            _assert_raises(
                SecurityBootstrapBackupError,
                lambda: _execute(backup_changed_db, backup_changed_manifest, backup_changed_plan, now + 1),
            )
            assert not _table_exists(backup_changed_db, "security_audit_events")

            # E2. Inject a late L3 audit failure: all earlier DDL and promotion
            # must roll back with the same exclusive transaction.
            import enterprise.security_bootstrap as bootstrap_module
            from enterprise.security_audit import SecurityAuditWriteError

            injected_db = tmp / "injected-rollback.db"
            _legacy_database(injected_db)
            injected_manifest = _manifest(tmp, injected_db, now_ms=now)
            injected_plan = _plan(injected_db, injected_manifest, now)
            original_append = bootstrap_module.append_security_audit_event

            def _fail_bootstrap_audit(**kwargs):
                if kwargs.get("action") == "security.super_admin.bootstrap":
                    raise SecurityAuditWriteError("temporary injected failure")
                return original_append(**kwargs)

            bootstrap_module.append_security_audit_event = _fail_bootstrap_audit
            try:
                _assert_raises(
                    SecurityBootstrapIntegrityError,
                    lambda: _execute(injected_db, injected_manifest, injected_plan, now + 1),
                )
            finally:
                bootstrap_module.append_security_audit_event = original_append
            assert not _table_exists(injected_db, "security_audit_events")
            assert not _table_exists(injected_db, "security_governance_bootstrap")
            assert "role" not in _user(injected_db, "admin-id")

            # E2b. A role/auth primitive failure is converted to a structured
            # rollback outcome instead of escaping without an activation error.
            role_error_db = tmp / "role-error.db"
            _legacy_database(role_error_db)
            role_error_manifest = _manifest(tmp, role_error_db, now_ms=now)
            role_error_plan = _plan(role_error_db, role_error_manifest, now)
            original_role_apply = bootstrap_module.apply_role_auth_migration_in_transaction

            def _fail_role_apply(_conn):
                raise RoleAuthMigrationError("temporary injected role migration failure")

            bootstrap_module.apply_role_auth_migration_in_transaction = _fail_role_apply
            try:
                role_error = _assert_raises(
                    SecurityBootstrapIntegrityError,
                    lambda: _execute(role_error_db, role_error_manifest, role_error_plan, now + 1),
                )
            finally:
                bootstrap_module.apply_role_auth_migration_in_transaction = original_role_apply
            assert role_error.database_transaction_rolled_back is True
            assert role_error.no_database_changes_committed is True
            assert role_error.database_changes_committed is False
            assert not _table_exists(role_error_db, "security_audit_events")

            # E2b2. SEC-1B2 repeats the raw READY gate after the SEC-1B1
            # primitive. A later mutation cannot leave a committed ACTIVE
            # lifecycle with a NULL or mismatched compatibility flag.
            null_gate_db = tmp / "null-ready-gate-rollback.db"
            _legacy_database(null_gate_db, include_null_is_admin_user=True)
            null_gate_manifest = _manifest(tmp, null_gate_db, now_ms=now)
            null_gate_plan = _plan(null_gate_db, null_gate_manifest, now)
            original_role_apply = bootstrap_module.apply_role_auth_migration_in_transaction

            def _apply_then_corrupt_ready_data(conn):
                result = original_role_apply(conn)
                conn.execute("UPDATE main.users SET is_admin = NULL WHERE id = 'null-user-id'")
                return result

            bootstrap_module.apply_role_auth_migration_in_transaction = _apply_then_corrupt_ready_data
            try:
                null_gate_error = _assert_raises(
                    SecurityBootstrapLifecycleError,
                    lambda: _execute(null_gate_db, null_gate_manifest, null_gate_plan, now + 1),
                )
            finally:
                bootstrap_module.apply_role_auth_migration_in_transaction = original_role_apply
            assert null_gate_error.database_transaction_rolled_back is True
            assert null_gate_error.no_database_changes_committed is True
            assert null_gate_error.database_changes_committed is False
            assert not _table_exists(null_gate_db, "security_audit_events")
            assert not _table_exists(null_gate_db, "security_governance_bootstrap")
            assert inspect_role_auth_schema(null_gate_db)["current_state"] == SCHEMA_LEGACY
            conn = sqlite3.connect(null_gate_db)
            try:
                assert conn.execute(
                    "SELECT is_admin FROM main.users WHERE id = 'null-user-id'"
                ).fetchone()[0] is None
            finally:
                conn.close()

            # E2c. Failure after commit is never reported as a rollback.
            post_commit_db = tmp / "post-commit.db"
            _legacy_database(post_commit_db)
            post_commit_manifest = _manifest(tmp, post_commit_db, now_ms=now)
            post_commit_plan = _plan(post_commit_db, post_commit_manifest, now)
            original_hash = bootstrap_module._sha256_file
            hash_calls = 0

            def _fail_only_post_commit_hash(value):
                nonlocal hash_calls
                hash_calls += 1
                if hash_calls == 4:
                    raise OSError("temporary post-commit fingerprint failure")
                return original_hash(value)

            bootstrap_module._sha256_file = _fail_only_post_commit_hash
            try:
                post_commit_error = _assert_raises(
                    SecurityBootstrapPostCommitError,
                    lambda: _execute(post_commit_db, post_commit_manifest, post_commit_plan, now + 1),
                )
            finally:
                bootstrap_module._sha256_file = original_hash
            assert post_commit_error.database_changes_committed is True
            assert post_commit_error.database_transaction_rolled_back is False
            assert post_commit_error.post_commit_verification_required is True
            assert inspect_super_admin_lifecycle(post_commit_db)["lifecycle_state"] == LIFECYCLE_ACTIVE
            assert "admin-password" not in json.dumps(post_commit_error.report, ensure_ascii=False)

            # E2d. Any post-commit Exception, not only OSError, carries the
            # committed-state result and forces later status verification.
            post_commit_runtime_db = tmp / "post-commit-runtime.db"
            _legacy_database(post_commit_runtime_db)
            post_commit_runtime_manifest = _manifest(tmp, post_commit_runtime_db, now_ms=now)
            post_commit_runtime_plan = _plan(post_commit_runtime_db, post_commit_runtime_manifest, now)
            original_hash = bootstrap_module._sha256_file
            hash_calls = 0

            def _fail_only_post_commit_runtime_hash(value):
                nonlocal hash_calls
                hash_calls += 1
                if hash_calls == 4:
                    raise RuntimeError("temporary post-commit runtime failure")
                return original_hash(value)

            bootstrap_module._sha256_file = _fail_only_post_commit_runtime_hash
            try:
                runtime_post_commit_error = _assert_raises(
                    SecurityBootstrapPostCommitError,
                    lambda: _execute(post_commit_runtime_db, post_commit_runtime_manifest, post_commit_runtime_plan, now + 1),
                )
            finally:
                bootstrap_module._sha256_file = original_hash
            assert runtime_post_commit_error.database_changes_committed is True
            assert runtime_post_commit_error.report["do_not_rerun_until_status_verified"] is True
            assert inspect_super_admin_lifecycle(post_commit_runtime_db)["lifecycle_state"] == LIFECYCLE_ACTIVE

            # E2e. Runner validation is read-only and happens before password,
            # confirmation, report reservation, or the execute service call.
            runner_validation_db = tmp / "runner-plan-validation.db"
            _legacy_database(runner_validation_db)
            runner_validation_manifest = _manifest(tmp, runner_validation_db, now_ms=now)
            runner_validation_plan = _plan(runner_validation_db, runner_validation_manifest, now)
            validated_copy = validate_sec_1b2_plan(
                runner_validation_plan,
                runner_validation_plan["plan_hash"],
                now_ms=now,
            )
            assert validated_copy == runner_validation_plan
            assert validated_copy is not runner_validation_plan

            def assert_invalid_runner_plan_is_prompt_free(
                label: str,
                mutate_plan,
                *,
                expected_hash: str | None = None,
                resign: bool = False,
            ) -> None:
                candidate = json.loads(json.dumps(runner_validation_plan))
                mutate_plan(candidate)
                if resign:
                    unsigned = dict(candidate)
                    unsigned.pop("plan_hash", None)
                    candidate["plan_hash"] = _plan_hash(unsigned)
                plan_path = tmp / f"runner-invalid-{label}.json"
                plan_path.write_text(json.dumps(candidate), encoding="utf-8")
                report_path = tmp / f"runner-invalid-{label}-report.json"
                calls = {"getpass": 0, "input": 0, "execute": 0}
                original_runner_getpass = runner.getpass.getpass
                original_runner_input = getattr(runner, "input", None)
                original_runner_execute = runner.execute_sec_1b2_activation

                def reject_getpass(_prompt):
                    calls["getpass"] += 1
                    raise AssertionError("getpass must not run for an invalid plan")

                def reject_input(_prompt):
                    calls["input"] += 1
                    raise AssertionError("confirmation must not run for an invalid plan")

                def reject_execute(**_kwargs):
                    calls["execute"] += 1
                    raise AssertionError("execute service must not run for an invalid plan")

                runner.getpass.getpass = reject_getpass
                runner.input = reject_input
                runner.execute_sec_1b2_activation = reject_execute
                stderr = StringIO()
                try:
                    with redirect_stderr(stderr):
                        assert runner.main(
                            [
                                "execute",
                                "--database", str(runner_validation_db),
                                "--plan", str(plan_path),
                                "--expected-plan-hash", expected_hash or candidate["plan_hash"],
                                "--backup-manifest", str(runner_validation_manifest),
                                "--target-user-id", "admin-id",
                                "--target-username", "admin",
                                "--actor-label", "temporary-local-operator",
                                "--reason", "temporary SEC-1B2 rehearsal",
                                "--report-output", str(report_path),
                                "--confirm-service-stopped",
                                "--confirm-backup-reviewed",
                                "--confirm-session-impact-reviewed",
                                "--confirm-first-bootstrap",
                            ]
                        ) == 1
                finally:
                    runner.getpass.getpass = original_runner_getpass
                    runner.execute_sec_1b2_activation = original_runner_execute
                    if original_runner_input is None:
                        del runner.input
                    else:
                        runner.input = original_runner_input
                assert calls == {"getpass": 0, "input": 0, "execute": 0}
                assert not report_path.exists()
                assert str(plan_path) not in stderr.getvalue()
                assert inspect_super_admin_lifecycle(runner_validation_db)["lifecycle_state"] == LIFECYCLE_UNINITIALIZED

            assert_invalid_runner_plan_is_prompt_free(
                "operation-id",
                lambda plan: plan.update({"operation_id": "tampered-operation"}),
            )
            assert_invalid_runner_plan_is_prompt_free(
                "session-scope",
                lambda plan: plan["session_impact"].update({"session_invalidation_scope": "bootstrap_target_only"}),
            )
            assert_invalid_runner_plan_is_prompt_free(
                "target",
                lambda plan: plan.update({"target_user_id": "other-admin"}),
            )
            assert_invalid_runner_plan_is_prompt_free(
                "actor-mismatch",
                lambda plan: plan.update({"actor_user_id": "other-admin"}),
                resign=True,
            )
            assert_invalid_runner_plan_is_prompt_free(
                "created-at-future",
                lambda plan: plan.update({"created_at": now + 1, "expires_at": now + 2}),
                resign=True,
            )
            assert_invalid_runner_plan_is_prompt_free(
                "expires-equals-created",
                lambda plan: plan.update({"created_at": now, "expires_at": now}),
                resign=True,
            )
            assert_invalid_runner_plan_is_prompt_free(
                "expires-at",
                lambda plan: plan.update({"expires_at": 0}),
            )
            assert_invalid_runner_plan_is_prompt_free(
                "stored-hash",
                lambda plan: plan.update({"plan_hash": "0" * 64}),
            )
            assert_invalid_runner_plan_is_prompt_free(
                "expected-hash",
                lambda _plan: None,
                expected_hash="f" * 64,
            )

            # E2f. The runner cannot enter execute if it cannot durably record
            # execution_in_progress before the database transaction starts.
            runner_pending_db = tmp / "runner-pending.db"
            _legacy_database(runner_pending_db)
            runner_pending_manifest = _manifest(tmp, runner_pending_db, now_ms=now)
            runner_pending_plan = _plan(runner_pending_db, runner_pending_manifest, now)
            runner_pending_plan_path = tmp / "runner-pending-plan.json"
            runner_pending_plan_path.write_text(json.dumps(runner_pending_plan), encoding="utf-8")
            runner_pending_report_path = tmp / "runner-pending-report.json"
            original_mark_in_progress = runner._mark_execution_in_progress
            original_runner_execute = runner.execute_sec_1b2_activation
            original_runner_getpass = runner.getpass.getpass
            original_runner_input = getattr(runner, "input", None)
            runner._mark_execution_in_progress = lambda **_kwargs: (_ for _ in ()).throw(OSError("temporary state write failure"))
            runner.execute_sec_1b2_activation = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("execute must not run"))
            runner.getpass.getpass = lambda _prompt: "admin-password"
            runner.input = lambda _prompt: (
                f"SEC-1B2 {runner_pending_plan['operation_id']} admin "
                f"{runner_pending_plan['session_impact']['session_invalidation_scope']}"
            )
            try:
                assert runner.main(
                    [
                        "execute",
                        "--database", str(runner_pending_db),
                        "--plan", str(runner_pending_plan_path),
                        "--expected-plan-hash", runner_pending_plan["plan_hash"],
                        "--backup-manifest", str(runner_pending_manifest),
                        "--target-user-id", "admin-id",
                        "--target-username", "admin",
                        "--actor-label", "temporary-local-operator",
                        "--reason", "temporary SEC-1B2 rehearsal",
                        "--report-output", str(runner_pending_report_path),
                        "--confirm-service-stopped",
                        "--confirm-backup-reviewed",
                        "--confirm-session-impact-reviewed",
                        "--confirm-first-bootstrap",
                    ]
                ) == 1
            finally:
                runner._mark_execution_in_progress = original_mark_in_progress
                runner.execute_sec_1b2_activation = original_runner_execute
                runner.getpass.getpass = original_runner_getpass
                if original_runner_input is None:
                    del runner.input
                else:
                    runner.input = original_runner_input
            assert inspect_super_admin_lifecycle(runner_pending_db)["lifecycle_state"] == LIFECYCLE_UNINITIALIZED
            pending_before_execute = json.loads(runner_pending_report_path.read_text(encoding="utf-8"))
            assert pending_before_execute["execution_state"] == "pending_manual_verification_required"
            assert pending_before_execute["do_not_rerun_until_status_verified"] is True

            # E2f. If the final report write fails after a real commit, the
            # runner returns a distinct status and leaves execution_in_progress
            # rather than a false transaction-not-started claim on disk.
            runner_report_db = tmp / "runner-report.db"
            _legacy_database(runner_report_db)
            runner_manifest = _manifest(tmp, runner_report_db, now_ms=now)
            runner_plan = _plan(runner_report_db, runner_manifest, now)
            runner_plan_path = tmp / "runner-plan.json"
            runner_plan_path.write_text(json.dumps(runner_plan), encoding="utf-8")
            runner_report_path = tmp / "runner-report.json"
            original_runner_write = runner._write_final_json
            original_runner_getpass = runner.getpass.getpass
            original_runner_input = getattr(runner, "input", None)

            def _fail_success_report(_path, payload):
                if payload.get("database_changes_committed") is True and payload.get("success") is True:
                    raise RuntimeError("temporary report write failure")
                return original_runner_write(_path, payload)

            runner._write_final_json = _fail_success_report
            runner.getpass.getpass = lambda _prompt: "admin-password"
            runner.input = lambda _prompt: (
                f"SEC-1B2 {runner_plan['operation_id']} admin "
                f"{runner_plan['session_impact']['session_invalidation_scope']}"
            )
            stderr = StringIO()
            try:
                with redirect_stderr(stderr):
                    exit_code = runner.main(
                        [
                            "execute",
                            "--database", str(runner_report_db),
                            "--plan", str(runner_plan_path),
                            "--expected-plan-hash", runner_plan["plan_hash"],
                            "--backup-manifest", str(runner_manifest),
                            "--target-user-id", "admin-id",
                            "--target-username", "admin",
                            "--actor-label", "temporary-local-operator",
                            "--reason", "temporary SEC-1B2 rehearsal",
                            "--report-output", str(runner_report_path),
                            "--confirm-service-stopped",
                            "--confirm-backup-reviewed",
                            "--confirm-session-impact-reviewed",
                            "--confirm-first-bootstrap",
                        ]
                    )
            finally:
                runner._write_final_json = original_runner_write
                runner.getpass.getpass = original_runner_getpass
                if original_runner_input is None:
                    del runner.input
                else:
                    runner.input = original_runner_input
            assert exit_code == 2
            assert "committed" in stderr.getvalue().casefold()
            assert inspect_super_admin_lifecycle(runner_report_db)["lifecycle_state"] == LIFECYCLE_ACTIVE
            pending_report = json.loads(runner_report_path.read_text(encoding="utf-8"))
            assert pending_report["database_changes_committed"] is None
            assert pending_report["execution_state"] == "execution_in_progress"
            assert pending_report["do_not_rerun_until_status_verified"] is True

            # E2g. A normal final report replaces the in-progress record only
            # after the committed activation report has been written safely.
            runner_success_db = tmp / "runner-success.db"
            _legacy_database(runner_success_db)
            runner_success_manifest = _manifest(tmp, runner_success_db, now_ms=now)
            runner_success_plan = _plan(runner_success_db, runner_success_manifest, now)
            runner_success_plan_path = tmp / "runner-success-plan.json"
            runner_success_plan_path.write_text(json.dumps(runner_success_plan), encoding="utf-8")
            runner_success_report_path = tmp / "runner-success-report.json"
            original_runner_getpass = runner.getpass.getpass
            original_runner_input = getattr(runner, "input", None)
            success_prompt_calls = {"getpass": 0, "input": 0}

            def success_getpass(_prompt):
                success_prompt_calls["getpass"] += 1
                return "admin-password"

            def success_input(prompt):
                success_prompt_calls["input"] += 1
                expected_phrase = (
                    f"SEC-1B2 {runner_success_plan['operation_id']} admin "
                    f"{runner_success_plan['session_impact']['session_invalidation_scope']}"
                )
                assert expected_phrase in prompt
                return expected_phrase

            runner.getpass.getpass = success_getpass
            runner.input = success_input
            try:
                assert runner.main(
                    [
                        "execute",
                        "--database", str(runner_success_db),
                        "--plan", str(runner_success_plan_path),
                        "--expected-plan-hash", runner_success_plan["plan_hash"],
                        "--backup-manifest", str(runner_success_manifest),
                        "--target-user-id", "admin-id",
                        "--target-username", "admin",
                        "--actor-label", "temporary-local-operator",
                        "--reason", "temporary SEC-1B2 rehearsal",
                        "--report-output", str(runner_success_report_path),
                        "--confirm-service-stopped",
                        "--confirm-backup-reviewed",
                        "--confirm-session-impact-reviewed",
                        "--confirm-first-bootstrap",
                    ]
                ) == 0
            finally:
                runner.getpass.getpass = original_runner_getpass
                if original_runner_input is None:
                    del runner.input
                else:
                    runner.input = original_runner_input
            success_report = json.loads(runner_success_report_path.read_text(encoding="utf-8"))
            assert success_report["success"] is True
            assert success_report["execution_state"] == "database_committed"
            assert success_report["do_not_rerun_until_status_verified"] is False
            assert success_prompt_calls == {"getpass": 1, "input": 1}

            # E3. Supported resume states do not duplicate prior activation events.
            resume_audit_db = tmp / "resume-audit.db"
            _legacy_database(resume_audit_db)
            resume_audit_manifest = _manifest(tmp, resume_audit_db, now_ms=now)
            conn = sqlite3.connect(resume_audit_db)
            conn.execute("BEGIN")
            apply_security_audit_migration_in_transaction(
                conn,
                actor_user_id="admin-id",
                actor_label="temporary-operator",
                operation_id="preexisting-foundation",
                reason="temporary audit-first fixture",
            )
            conn.commit()
            conn.close()
            resume_audit_manifest = _manifest(tmp, resume_audit_db, now_ms=now)
            resume_audit_plan = _plan(resume_audit_db, resume_audit_manifest, now)
            resume_audit_report = _execute(resume_audit_db, resume_audit_manifest, resume_audit_plan, now + 1)
            assert resume_audit_report["event_ids"]["foundation"] is None
            assert resume_audit_report["event_ids"]["role_auth_migration"]
            assert len(_audit_rows(resume_audit_db, "preexisting-foundation")) == 1

            resume_ready_db = tmp / "resume-ready.db"
            _legacy_database(resume_ready_db)
            resume_ready_manifest = _manifest(tmp, resume_ready_db, now_ms=now)
            conn = sqlite3.connect(resume_ready_db)
            conn.execute("BEGIN")
            apply_role_auth_migration_in_transaction(conn)
            conn.commit()
            conn.execute("BEGIN")
            apply_security_audit_migration_in_transaction(
                conn,
                actor_user_id="admin-id",
                actor_label="temporary-operator",
                operation_id="preexisting-ready-foundation",
                reason="temporary ready fixture",
            )
            conn.commit()
            conn.close()
            edb.DB_PATH = str(resume_ready_db)
            resume_target_token = auth.create_token("admin-id")
            resume_user_token = auth.create_token("user-id")
            assert auth.verify_token(resume_target_token) is not None
            assert auth.verify_token(resume_user_token) is not None
            _checkpoint_temporary_wal(resume_ready_db)
            prepare_sec_1b2_journal(database_path=resume_ready_db, now_ms=now)
            resume_ready_manifest = _manifest(tmp, resume_ready_db, now_ms=now)
            resume_ready_plan = _plan(resume_ready_db, resume_ready_manifest, now)
            resume_ready_report = _execute(resume_ready_db, resume_ready_manifest, resume_ready_plan, now + 1)
            assert resume_ready_report["event_ids"]["foundation"] is None
            assert resume_ready_report["event_ids"]["role_auth_migration"] is None
            assert resume_ready_report["event_ids"]["bootstrap"]
            assert resume_ready_report["session_impact"]["session_invalidation_scope"] == "bootstrap_target_only"
            assert resume_ready_report["old_tokens_invalidated"] is False
            assert auth.verify_token(resume_target_token) is None
            assert auth.verify_token(resume_user_token) is not None

            # F. RECOVERY_REQUIRED is separate from schema partial and cannot re-bootstrap.
            recovery_db = tmp / "recovery.db"
            _legacy_database(recovery_db)
            recovery_manifest = _manifest(tmp, recovery_db, now_ms=now)
            recovery_plan = _plan(recovery_db, recovery_manifest, now)
            _execute(recovery_db, recovery_manifest, recovery_plan, now + 1)
            conn = sqlite3.connect(recovery_db)
            conn.execute("UPDATE main.users SET is_active = 0 WHERE id = 'admin-id'")
            conn.commit()
            conn.close()
            assert inspect_super_admin_lifecycle(recovery_db)["lifecycle_state"] == LIFECYCLE_RECOVERY_REQUIRED
            recovery_manifest = _manifest(tmp, recovery_db, now_ms=now)
            _assert_raises(SecurityBootstrapLifecycleError, lambda: _plan(recovery_db, recovery_manifest, now + 2))

            # G. Exclusive lock fails closed without indefinite waiting.
            lock_db = tmp / "lock.db"
            _legacy_database(lock_db)
            lock_manifest = _manifest(tmp, lock_db, now_ms=now)
            lock_plan = _plan(lock_db, lock_manifest, now)
            lock_conn = sqlite3.connect(lock_db)
            lock_conn.execute("BEGIN EXCLUSIVE")
            try:
                _assert_raises(SecurityBootstrapLockError, lambda: _execute(lock_db, lock_manifest, lock_plan, now + 1))
            finally:
                lock_conn.rollback()
                lock_conn.close()

            # H. Runner surface is local-only, with the explicit journal preparation gate.
            parser = runner.build_parser()
            help_text = parser.format_help().casefold()
            subparsers_action = next(action for action in parser._actions if getattr(action, "choices", None))
            execute_help = subparsers_action.choices["execute"].format_help().casefold()
            assert all(command in help_text for command in ("status", "prepare-journal", "plan", "execute"))
            assert all(
                forbidden not in execute_help
                for forbidden in (
                    "--password",
                    "break-glass",
                    "--force",
                    "--skip",
                    "--repair",
                    "--checkpoint",
                    "--confirm-old-tokens-invalidated",
                )
            )
            assert "--confirm-session-impact-reviewed" in execute_help
        finally:
            edb.DB_PATH = original_db_path
            auth.JWT_SECRET = original_jwt_secret


if __name__ == "__main__":
    _run_checks()
    print("SEC-1B2 controlled activation and bootstrap checks passed")
