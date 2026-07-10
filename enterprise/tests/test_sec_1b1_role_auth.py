"""SEC-1B1 role, migration, auth-version, and current-state JWT checks.

All databases and credentials in this test are temporary test fixtures. The
script never opens the repository or production enterprise database.
"""

import asyncio
import inspect
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import jwt
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_SECRET = "sec-1b1-temporary-jwt-secret-at-least-32-bytes"
TEST_ADMIN_PASSWORD = "temporary-admin-password"


def _prepare_env(tmp: Path) -> None:
    os.environ["DB_PATH"] = str(tmp / "initial.db")
    os.environ["JWT_SECRET"] = TEST_SECRET
    os.environ["JWT_EXPIRE_HOURS"] = "1"
    os.environ["ADMIN_USERNAME"] = "admin"
    os.environ["ADMIN_PASSWORD"] = TEST_ADMIN_PASSWORD


def _legacy_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
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
        )
        """
    )
    return conn


def _insert_legacy_users(conn: sqlite3.Connection, password_hash: str) -> None:
    now = int(time.time() * 1000)
    conn.executemany(
        """
        INSERT INTO users (
            id, username, password_hash, display_name,
            is_admin, is_active, created_at, last_login
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("legacy-user", "legacy_user", password_hash, "Legacy User", 0, 1, now, None),
            ("legacy-admin", "legacy_admin", password_hash, "Legacy Admin", 1, 1, now, 123),
            ("legacy-disabled", "legacy_disabled", password_hash, "Disabled", 0, 0, now, None),
        ],
    )
    conn.commit()


def _columns(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [str(row[1]) for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    finally:
        conn.close()


def _row(path: Path, username: str) -> dict:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def _jwt(payload: dict, secret: str = TEST_SECRET) -> str:
    return jwt.encode(payload, secret, algorithm="HS256")


def _assert_http_status(func, expected: int) -> None:
    try:
        func()
    except HTTPException as exc:
        assert exc.status_code == expected, (exc.status_code, expected)
        return
    raise AssertionError(f"expected HTTPException {expected}")


async def _login(gateway, username: str, password: str):
    class LoginRequest:
        query_params = {}

        async def json(self):
            return {"username": username, "password": password}

    return await gateway.do_login(LoginRequest())


def _run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-sec-1b1-") as raw_tmp:
        tmp = Path(raw_tmp)
        _prepare_env(tmp)

        from enterprise import admin_api
        from enterprise import auth
        from enterprise import db as edb
        from enterprise import gateway
        from enterprise.migrations.sec_1b1_role_auth import (
            MIGRATION_ID,
            ROLE_AUTH_READY,
            SCHEMA_LEGACY,
            RoleAuthMigrationError,
            apply_role_auth_migration,
            inspect_role_auth_schema,
            plan_role_auth_migration,
        )
        from enterprise.roles import (
            ROLE_ADMIN,
            ROLE_SUPER_ADMIN,
            ROLE_USER,
            is_admin_role,
            normalize_role,
        )

        auth.JWT_SECRET = TEST_SECRET
        auth.JWT_EXPIRE_HOURS = 1
        edb.ADMIN_USERNAME = "admin"
        edb.ADMIN_PASSWORD = TEST_ADMIN_PASSWORD

        # A. Missing paths fail without creating a SQLite file.
        missing_db = tmp / "missing role auth.db"
        for operation in (
            inspect_role_auth_schema,
            plan_role_auth_migration,
            apply_role_auth_migration,
        ):
            try:
                operation(missing_db)
            except RoleAuthMigrationError as exc:
                assert str(missing_db) not in str(exc)
            else:
                raise AssertionError(f"{operation.__name__} accepted a missing database")
            assert not missing_db.exists()

        # B. Legacy inspection and read-only planning.
        legacy_plan_db = tmp / "legacy-plan.db"
        conn = _legacy_connection(legacy_plan_db)
        legacy_hash = edb._hash_password("legacy-password")
        _insert_legacy_users(conn, legacy_hash)
        conn.close()
        before_columns = _columns(legacy_plan_db)
        before_bytes = legacy_plan_db.read_bytes()

        inspection = inspect_role_auth_schema(legacy_plan_db)
        assert inspection["current_state"] == SCHEMA_LEGACY
        assert inspection["user_count"] == 3
        assert inspection["legacy_user_to_user_count"] == 2
        assert inspection["legacy_admin_to_admin_count"] == 1
        assert inspection["is_migrated"] is False
        assert inspection["needs_migration"] is True
        assert inspection["has_invalid_role"] is False
        assert _columns(legacy_plan_db) == before_columns
        assert legacy_plan_db.read_bytes() == before_bytes

        plan = plan_role_auth_migration(legacy_plan_db)
        assert plan["migration_id"] == MIGRATION_ID
        assert plan["current_state"] == SCHEMA_LEGACY
        assert plan["target_state"] == ROLE_AUTH_READY
        assert plan["columns_to_add"] == [
            "role",
            "auth_version",
            "role_updated_at",
            "role_updated_by",
        ]
        assert plan["legacy_user_to_user_count"] == 2
        assert plan["legacy_admin_to_admin_count"] == 1
        assert plan["super_admin_to_create"] == 0
        assert plan["production_activation"] is False
        assert _columns(legacy_plan_db) == before_columns
        assert legacy_plan_db.read_bytes() == before_bytes

        # URI paths with Windows-compatible spaces and reserved characters work.
        windows_path_dir = tmp / "windows path compatibility"
        windows_path_dir.mkdir()
        windows_path_db = windows_path_dir / "role auth # legacy.db"
        conn = _legacy_connection(windows_path_db)
        _insert_legacy_users(conn, legacy_hash)
        conn.close()
        windows_columns = _columns(windows_path_db)
        windows_bytes = windows_path_db.read_bytes()
        assert inspect_role_auth_schema(windows_path_db)["current_state"] == SCHEMA_LEGACY
        assert plan_role_auth_migration(windows_path_db)["current_state"] == SCHEMA_LEGACY
        assert _columns(windows_path_db) == windows_columns
        assert windows_path_db.read_bytes() == windows_bytes
        assert apply_role_auth_migration(windows_path_db)["current_state"] == ROLE_AUTH_READY

        # Explicit sqlite3.Connection inputs retain inspect/plan/apply support.
        explicit_connection_db = tmp / "explicit-connection.db"
        conn = _legacy_connection(explicit_connection_db)
        _insert_legacy_users(conn, legacy_hash)
        assert inspect_role_auth_schema(conn)["current_state"] == SCHEMA_LEGACY
        assert plan_role_auth_migration(conn)["current_state"] == SCHEMA_LEGACY
        assert apply_role_auth_migration(conn)["current_state"] == ROLE_AUTH_READY
        conn.close()

        # init_db must keep a legacy users table untouched.
        edb.DB_PATH = str(legacy_plan_db)
        edb.init_db()
        assert _columns(legacy_plan_db) == before_columns
        legacy_admin = edb.get_user_by_username("legacy_admin")
        assert legacy_admin["role"] == ROLE_ADMIN
        assert legacy_admin["auth_version"] == 0
        assert legacy_admin["is_admin"] is True
        inserted_legacy_admin = edb.get_user_by_username("admin")
        assert inserted_legacy_admin["role"] == ROLE_ADMIN
        assert inserted_legacy_admin["auth_version"] == 0

        # C. Explicit migration, preservation, idempotency, and rollback.
        migration_db = tmp / "migration.db"
        conn = _legacy_connection(migration_db)
        _insert_legacy_users(conn, legacy_hash)
        conn.execute(
            "CREATE TABLE usage_logs (id INTEGER PRIMARY KEY, user_id TEXT, action TEXT, detail TEXT, ts INTEGER)"
        )
        conn.execute(
            "INSERT INTO usage_logs (id, user_id, action, detail, ts) VALUES (1, 'legacy-user', 'keep', 'keep', 1)"
        )
        conn.execute(
            "CREATE TABLE user_canvas_map (user_id TEXT NOT NULL, canvas_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL)"
        )
        conn.execute(
            "INSERT INTO user_canvas_map (user_id, canvas_id, created_at) VALUES ('legacy-user', 'keep-canvas', 1)"
        )
        conn.commit()
        conn.close()
        legacy_snapshot = {
            name: _row(migration_db, name)
            for name in ("legacy_user", "legacy_admin", "legacy_disabled")
        }

        applied = apply_role_auth_migration(migration_db)
        assert applied["current_state"] == ROLE_AUTH_READY
        assert applied["is_migrated"] is True
        assert set(("role", "auth_version", "role_updated_at", "role_updated_by")) <= set(_columns(migration_db))
        migrated_user = _row(migration_db, "legacy_user")
        migrated_admin = _row(migration_db, "legacy_admin")
        migrated_disabled = _row(migration_db, "legacy_disabled")
        assert migrated_user["role"] == ROLE_USER
        assert migrated_admin["role"] == ROLE_ADMIN
        assert migrated_disabled["role"] == ROLE_USER
        assert {migrated_user["auth_version"], migrated_admin["auth_version"], migrated_disabled["auth_version"]} == {1}
        for name, migrated in {
            "legacy_user": migrated_user,
            "legacy_admin": migrated_admin,
            "legacy_disabled": migrated_disabled,
        }.items():
            original = legacy_snapshot[name]
            assert migrated["id"] == original["id"]
            assert migrated["password_hash"] == original["password_hash"]
            assert migrated["is_active"] == original["is_active"]
        conn = sqlite3.connect(migration_db)
        try:
            assert conn.execute("SELECT COUNT(*) FROM users WHERE role = ?", (ROLE_SUPER_ADMIN,)).fetchone()[0] == 0
            assert conn.execute("SELECT action FROM usage_logs WHERE id = 1").fetchone()[0] == "keep"
            assert conn.execute("SELECT user_id FROM user_canvas_map WHERE canvas_id = 'keep-canvas'").fetchone()[0] == "legacy-user"
            assert any(row[1] == "idx_users_role_active" for row in conn.execute("PRAGMA index_list(users)"))
        finally:
            conn.close()
        second_apply = apply_role_auth_migration(migration_db)
        assert second_apply["current_state"] == ROLE_AUTH_READY
        assert _row(migration_db, "legacy_admin") == migrated_admin

        rollback_db = tmp / "rollback.db"
        conn = _legacy_connection(rollback_db)
        _insert_legacy_users(conn, legacy_hash)
        conn.execute(
            """
            CREATE TRIGGER reject_sec_1b1_update
            BEFORE UPDATE ON users
            BEGIN
                SELECT RAISE(ABORT, 'blocked for rollback test');
            END
            """
        )
        conn.commit()
        conn.close()
        rollback_columns = _columns(rollback_db)
        try:
            apply_role_auth_migration(rollback_db)
        except RoleAuthMigrationError:
            pass
        else:
            raise AssertionError("migration failure injection did not fail")
        assert _columns(rollback_db) == rollback_columns
        assert inspect_role_auth_schema(rollback_db)["current_state"] == SCHEMA_LEGACY

        # D. Fresh schema and legacy is_admin creation compatibility.
        fresh_db = tmp / "fresh.db"
        edb.DB_PATH = str(fresh_db)
        edb.init_db()
        fresh_columns = set(_columns(fresh_db))
        assert {"role", "auth_version", "role_updated_at", "role_updated_by"} <= fresh_columns
        default_admin = edb.get_user_by_username("admin")
        assert default_admin["role"] == ROLE_ADMIN
        assert default_admin["is_admin"] is True
        assert default_admin["auth_version"] == 1

        user = edb.create_user("sec_user", "password-user", "Sec User", False)
        created_admin = edb.create_user("sec_admin", "password-admin", "Sec Admin", True)
        user_row = edb.get_user_by_id(user["id"])
        admin_row = edb.get_user_by_id(created_admin["id"])
        assert user_row["role"] == ROLE_USER and user_row["is_admin"] is False
        assert admin_row["role"] == ROLE_ADMIN and admin_row["is_admin"] is True
        assert user_row["auth_version"] == admin_row["auth_version"] == 1
        assert is_admin_role(ROLE_SUPER_ADMIN) is True
        conn = sqlite3.connect(fresh_db)
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user["id"],))
        conn.commit()
        conn.close()
        inconsistent_compat = edb.get_user_by_id(user["id"])
        assert inconsistent_compat["role"] == ROLE_USER
        assert inconsistent_compat["is_admin"] is False
        conn = sqlite3.connect(fresh_db)
        conn.execute("UPDATE users SET is_admin = 0 WHERE id = ?", (user["id"],))
        conn.commit()
        conn.close()
        assert "role" not in inspect.signature(edb.create_user).parameters
        try:
            normalize_role("owner")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid role accepted")
        conn = sqlite3.connect(fresh_db)
        try:
            assert conn.execute("SELECT COUNT(*) FROM users WHERE role = ?", (ROLE_SUPER_ADMIN,)).fetchone()[0] == 0
        finally:
            conn.close()

        # E. JWT payload and current database state principal.
        token = auth.create_token(user["id"])
        payload = jwt.decode(token, TEST_SECRET, algorithms=["HS256"])
        assert payload["user_id"] == user["id"]
        assert payload["auth_version"] == 1
        assert isinstance(payload["jti"], str) and payload["jti"]
        assert isinstance(payload["iat"], int) and isinstance(payload["exp"], int)
        forbidden_claims = {
            "is_admin",
            "role",
            "password",
            "password_hash",
            "cookie",
            "api_key",
        }
        assert not forbidden_claims.intersection(payload)

        principal = auth.verify_token(token)
        assert principal == {
            "user_id": user["id"],
            "username": "sec_user",
            "role": ROLE_USER,
            "auth_version": 1,
            "is_admin": False,
            "jti": payload["jti"],
        }
        forged = _jwt({
            "user_id": user["id"],
            "auth_version": 1,
            "is_admin": True,
            "role": ROLE_SUPER_ADMIN,
            "jti": "forged-role-claims",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        })
        forged_principal = auth.verify_token(forged)
        assert forged_principal["role"] == ROLE_USER
        assert forged_principal["is_admin"] is False
        assert auth.verify_token(_jwt({"user_id": "missing", "auth_version": 1, "exp": int(time.time()) + 60})) is None
        assert auth.verify_token(_jwt({"user_id": user["id"], "auth_version": 1, "exp": int(time.time()) - 1})) is None
        assert auth.verify_token(_jwt({"user_id": user["id"], "auth_version": 1, "exp": int(time.time()) + 60}, "wrong-secret")) is None

        conn = sqlite3.connect(fresh_db)
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute("UPDATE users SET role = ? WHERE id = ?", ("invalid-role", user["id"]))
        conn.commit()
        conn.close()
        try:
            edb.get_user_by_id(user["id"])
        except ValueError:
            pass
        else:
            raise AssertionError("invalid migrated role did not fail closed")
        assert auth.verify_token(token) is None
        conn = sqlite3.connect(fresh_db)
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute("UPDATE users SET role = ?, auth_version = ? WHERE id = ?", (ROLE_USER, "bad", user["id"]))
        conn.commit()
        conn.close()
        try:
            edb.get_user_by_id(user["id"])
        except ValueError:
            pass
        else:
            raise AssertionError("invalid migrated auth_version did not fail closed")
        assert auth.verify_token(token) is None
        conn = sqlite3.connect(fresh_db)
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute("UPDATE users SET auth_version = 1 WHERE id = ?", (user["id"],))
        conn.commit()
        conn.close()

        # F. auth_version invalidation and no-op rules.
        edb.update_user_profile(user["id"], "Renamed User")
        assert auth.verify_token(token)["username"] == "sec_user"
        edb.update_last_login(user["id"])
        assert auth.verify_token(token) is not None

        assert edb.update_user_password(user["id"], "new-password-user") is True
        assert auth.verify_token(token) is None
        token_after_password = auth.create_token(user["id"])
        assert auth.verify_token(token_after_password) is not None

        assert edb.update_user_role(user["id"], True, updated_by=default_admin["id"]) is True
        assert auth.verify_token(token_after_password) is None
        promoted = edb.get_user_by_id(user["id"])
        assert promoted["role_updated_by"] == default_admin["id"]
        assert isinstance(promoted["role_updated_at"], int)
        admin_token = auth.create_token(user["id"])
        admin_principal = auth.verify_token(admin_token)
        assert admin_principal["role"] == ROLE_ADMIN
        assert admin_principal["is_admin"] is True
        assert admin_api._require_admin(SimpleNamespace(state=SimpleNamespace(user=admin_principal))) == admin_principal

        assert edb.update_user_role(user["id"], False, updated_by=default_admin["id"]) is True
        assert auth.verify_token(admin_token) is None
        user_token = auth.create_token(user["id"])
        _assert_http_status(
            lambda: admin_api._require_admin(SimpleNamespace(state=SimpleNamespace(user=auth.verify_token(user_token)))),
            403,
        )

        before_disable_version = edb.get_user_by_id(user["id"])["auth_version"]
        assert edb.set_user_active(user["id"], False) is True
        assert auth.verify_token(user_token) is None
        disabled = edb.get_user_by_id_any_status(user["id"])
        assert disabled["auth_version"] == before_disable_version + 1
        assert edb.set_user_active(user["id"], True) is True
        assert auth.verify_token(user_token) is None
        enabled = edb.get_user_by_id(user["id"])
        assert enabled["auth_version"] == before_disable_version + 2
        enabled_token = auth.create_token(user["id"])
        assert auth.verify_token(enabled_token) is not None

        stable_version = enabled["auth_version"]
        assert edb.set_user_active(user["id"], True) is True
        assert edb.get_user_by_id(user["id"])["auth_version"] == stable_version
        assert edb.update_user_role(user["id"], False, updated_by=default_admin["id"]) is True
        assert edb.get_user_by_id(user["id"])["auth_version"] == stable_version

        # G. Legacy tokens ignore cached privilege, then expire on migration.
        legacy_token_db = tmp / "legacy-token.db"
        conn = _legacy_connection(legacy_token_db)
        _insert_legacy_users(conn, legacy_hash)
        conn.close()
        edb.DB_PATH = str(legacy_token_db)
        old_token = _jwt({
            "user_id": "legacy-user",
            "username": "cached-name",
            "is_admin": True,
            "role": ROLE_SUPER_ADMIN,
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
        })
        old_principal = auth.verify_token(old_token)
        assert old_principal["role"] == ROLE_USER
        assert old_principal["is_admin"] is False
        conn = sqlite3.connect(legacy_token_db)
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", ("legacy-user",))
        conn.commit()
        conn.close()
        current_legacy_principal = auth.verify_token(old_token)
        assert current_legacy_principal["role"] == ROLE_ADMIN
        assert current_legacy_principal["is_admin"] is True
        apply_role_auth_migration(legacy_token_db)
        assert auth.verify_token(old_token) is None
        migrated_token = auth.create_token("legacy-user")
        assert auth.verify_token(migrated_token)["role"] == ROLE_ADMIN
        wrong_version = _jwt({
            "user_id": "legacy-user",
            "auth_version": 999,
            "jti": "wrong-version",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
        })
        assert auth.verify_token(wrong_version) is None

        # H. Existing API, feature, login, delete-impact, and WebSocket aliases.
        edb.DB_PATH = str(fresh_db)
        public_users = edb.list_users()
        assert public_users and all("password_hash" not in item for item in public_users)
        assert edb.get_user_delete_impact(user["id"])["user"]["role"] == ROLE_USER
        current_admin_token = auth.create_token(default_admin["id"])
        current_admin = auth.verify_token(current_admin_token)
        assert current_admin["is_admin"] is True
        assert edb.can_use_feature(current_admin, "system_update") is True
        assert gateway.verify_token(current_admin_token) == current_admin

        login_response = asyncio.run(_login(gateway, "admin", TEST_ADMIN_PASSWORD))
        login_body = json.loads(login_response.body.decode("utf-8"))
        assert login_response.status_code == 200
        assert login_body["is_admin"] is True
        assert login_body["role"] == ROLE_ADMIN
        assert "enterprise_token=" in login_response.headers.get("set-cookie", "")

    print("SEC-1B1 role/auth migration and JWT checks passed")


if __name__ == "__main__":
    _run_checks()
