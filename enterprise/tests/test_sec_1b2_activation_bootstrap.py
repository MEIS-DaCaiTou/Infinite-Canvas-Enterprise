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


def _legacy_database(path: Path) -> None:
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
    conn.executemany(
        """
        INSERT INTO users (
            id, username, password_hash, display_name,
            is_admin, is_active, created_at, last_login
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("admin-id", "admin", edb._hash_password("admin-password"), "Admin", 1, 1, now, None),
            ("admin-two-id", "admin-two", edb._hash_password("admin-two-password"), "Admin Two", 1, 1, now, None),
            ("user-id", "user", edb._hash_password("user-password"), "User", 0, 1, now, None),
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


def _manifest(tmp: Path, *, now_ms: int, **changes) -> Path:
    backup_db = tmp / f"backup-{len(list(tmp.glob('backup-*.db')))}.db"
    backup_conn = sqlite3.connect(backup_db)
    backup_conn.execute("CREATE TABLE backup_proof (id INTEGER PRIMARY KEY, value TEXT)")
    backup_conn.execute("INSERT INTO backup_proof (value) VALUES ('temporary')")
    backup_conn.commit()
    backup_conn.close()
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
        BOOTSTRAP_PARTIAL,
        BOOTSTRAP_READY,
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
        SecurityBootstrapBackupError,
        SecurityBootstrapIntegrityError,
        SecurityBootstrapLifecycleError,
        SecurityBootstrapLockError,
        SecurityBootstrapPasswordError,
        SecurityBootstrapPlanError,
        SecurityBootstrapValidationError,
        execute_sec_1b2_activation,
        inspect_super_admin_lifecycle,
        plan_sec_1b2_activation,
    )
    from enterprise.security_audit import SECURITY_AUDIT_MISSING, SECURITY_AUDIT_READY
    from tools import sec_1b2_local_runner as runner

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

            # C. Read-only plan and executed-backup gates.
            plan_db = tmp / "plan.db"
            _legacy_database(plan_db)
            manifest = _manifest(tmp, now_ms=now)
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
            for changes in (
                {"dry_run": True},
                {"status": "fail"},
                {"sqlite_backup_status": "failed"},
                {"sqlite_backup_sha256": "0" * 64},
                {"generated_at": "2000-01-01T00:00:00Z"},
            ):
                invalid_manifest = _manifest(tmp, now_ms=now, **changes)
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

            # D. Complete LEGACY -> ACTIVE activation and session invalidation.
            edb.DB_PATH = str(plan_db)
            auth.JWT_SECRET = "sec-1b2-token-test-secret-at-least-32-bytes"
            legacy_target_token = auth.create_token("admin-id")
            legacy_user_token = auth.create_token("user-id")
            assert auth.verify_token(legacy_target_token) is not None
            # The application helper uses WAL; model a stopped-service window
            # explicitly in this temporary fixture. SEC-1B2 never checkpoints
            # or removes sidecars by itself.
            conn = sqlite3.connect(plan_db)
            assert str(conn.execute("PRAGMA journal_mode = DELETE").fetchone()[0]).casefold() == "delete"
            conn.close()
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
            _assert_raises(SecurityBootstrapPlanError, lambda: _execute(plan_db, manifest, plan, now + 2))
            _assert_raises(SecurityBootstrapLifecycleError, lambda: _plan(plan_db, manifest, now + 2))
            assert _schema_rows(plan_db) == snapshot_after_active

            # E. Wrong password and stale plan rollback without committed schema or users.
            rollback_db = tmp / "rollback.db"
            _legacy_database(rollback_db)
            rollback_manifest = _manifest(tmp, now_ms=now)
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

            # E2. Inject a late L3 audit failure: all earlier DDL and promotion
            # must roll back with the same exclusive transaction.
            import enterprise.security_bootstrap as bootstrap_module
            from enterprise.security_audit import SecurityAuditWriteError

            injected_db = tmp / "injected-rollback.db"
            _legacy_database(injected_db)
            injected_manifest = _manifest(tmp, now_ms=now)
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

            # E3. Supported resume states do not duplicate prior activation events.
            resume_audit_db = tmp / "resume-audit.db"
            _legacy_database(resume_audit_db)
            resume_audit_manifest = _manifest(tmp, now_ms=now)
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
            resume_audit_plan = _plan(resume_audit_db, resume_audit_manifest, now)
            resume_audit_report = _execute(resume_audit_db, resume_audit_manifest, resume_audit_plan, now + 1)
            assert resume_audit_report["event_ids"]["foundation"] is None
            assert resume_audit_report["event_ids"]["role_auth_migration"]
            assert len(_audit_rows(resume_audit_db, "preexisting-foundation")) == 1

            resume_ready_db = tmp / "resume-ready.db"
            _legacy_database(resume_ready_db)
            resume_ready_manifest = _manifest(tmp, now_ms=now)
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
            resume_ready_plan = _plan(resume_ready_db, resume_ready_manifest, now)
            resume_ready_report = _execute(resume_ready_db, resume_ready_manifest, resume_ready_plan, now + 1)
            assert resume_ready_report["event_ids"]["foundation"] is None
            assert resume_ready_report["event_ids"]["role_auth_migration"] is None
            assert resume_ready_report["event_ids"]["bootstrap"]

            # F. RECOVERY_REQUIRED is separate from schema partial and cannot re-bootstrap.
            recovery_db = tmp / "recovery.db"
            _legacy_database(recovery_db)
            recovery_manifest = _manifest(tmp, now_ms=now)
            recovery_plan = _plan(recovery_db, recovery_manifest, now)
            _execute(recovery_db, recovery_manifest, recovery_plan, now + 1)
            conn = sqlite3.connect(recovery_db)
            conn.execute("UPDATE main.users SET is_active = 0 WHERE id = 'admin-id'")
            conn.commit()
            conn.close()
            assert inspect_super_admin_lifecycle(recovery_db)["lifecycle_state"] == LIFECYCLE_RECOVERY_REQUIRED
            _assert_raises(SecurityBootstrapLifecycleError, lambda: _plan(recovery_db, recovery_manifest, now + 2))

            # G. Exclusive lock fails closed without indefinite waiting.
            lock_db = tmp / "lock.db"
            _legacy_database(lock_db)
            lock_manifest = _manifest(tmp, now_ms=now)
            lock_plan = _plan(lock_db, lock_manifest, now)
            lock_conn = sqlite3.connect(lock_db)
            lock_conn.execute("BEGIN EXCLUSIVE")
            try:
                _assert_raises(SecurityBootstrapLockError, lambda: _execute(lock_db, lock_manifest, lock_plan, now + 1))
            finally:
                lock_conn.rollback()
                lock_conn.close()

            # H. Runner surface contains only local status/plan/execute and no password option.
            parser = runner.build_parser()
            help_text = parser.format_help().casefold()
            assert "status" in help_text and "plan" in help_text and "execute" in help_text
            assert "--password" not in help_text and "break-glass" not in help_text and "--force" not in help_text
        finally:
            edb.DB_PATH = original_db_path
            auth.JWT_SECRET = original_jwt_secret


if __name__ == "__main__":
    _run_checks()
    print("SEC-1B2 controlled activation and bootstrap checks passed")
