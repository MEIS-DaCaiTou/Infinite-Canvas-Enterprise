"""SEC-1C0 transitional super-admin protection checks.

All databases, users, passwords, and super-admin rows are temporary fixtures.
"""

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("JWT_SECRET", "sec-1c0-temporary-secret-at-least-32-bytes")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "temporary-admin-password")


class FakeRequest:
    def __init__(self, user: dict | None, body: dict | None = None):
        self.state = SimpleNamespace(user=user)
        self._body = body or {}
        self.query_params = {}

    async def json(self):
        return self._body


def _assert_raises(error_type, func):
    try:
        func()
    except error_type as exc:
        return exc
    raise AssertionError(f"expected {error_type.__name__}")


async def _assert_http_status(awaitable, status: int):
    from fastapi import HTTPException

    try:
        await awaitable
    except HTTPException as exc:
        assert exc.status_code == status, (exc.status_code, exc.detail)
        return exc
    raise AssertionError(f"expected HTTP {status}")


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
        """
    )
    conn.commit()
    conn.close()


def _apply_audit(path: Path, actor_id: str) -> None:
    from enterprise.migrations.sec_1f0_security_audit import apply_security_audit_migration

    apply_security_audit_migration(
        path,
        actor_user_id=actor_id,
        actor_label="temporary-sec-1c0-operator",
        operation_id=f"op-audit-{uuid.uuid4().hex}",
        reason="temporary SEC-1C0 audit fixture",
    )


def _add_ready_user(
    path: Path,
    *,
    username: str,
    role: str,
    is_active: bool = True,
    password: str = "temporary-user-password",
) -> dict:
    from enterprise import db as edb

    user_id = uuid.uuid4().hex
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO main.users (
            id, username, password_hash, display_name, is_admin,
            role, auth_version, is_active, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            user_id,
            username,
            edb._hash_password(password),
            username,
            0 if role == "user" else 1,
            role,
            1 if is_active else 0,
            int(time.time() * 1000),
        ),
    )
    conn.commit()
    conn.close()
    return {"id": user_id, "username": username, "role": role, "password": password}


def _user_row(path: Path, user_id: str) -> dict:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM main.users WHERE id = ?", (user_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def _audit_rows(path: Path, operation_id: str | None = None) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if operation_id:
            rows = conn.execute(
                "SELECT * FROM main.security_audit_events WHERE operation_id = ? ORDER BY id",
                (operation_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM main.security_audit_events ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _audit_count(path: Path, action: str | None = None) -> int:
    conn = sqlite3.connect(path)
    try:
        if action is None:
            return int(
                conn.execute("SELECT COUNT(*) FROM main.security_audit_events").fetchone()[0]
            )
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM main.security_audit_events WHERE action = ?",
                (action,),
            ).fetchone()[0]
        )
    finally:
        conn.close()


def _latest_audit(path: Path, action: str) -> dict:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM main.security_audit_events WHERE action = ? ORDER BY id DESC LIMIT 1",
            (action,),
        ).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def _usage_count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM main.usage_logs").fetchone()[0])
    finally:
        conn.close()


def _auth_version(path: Path, user_id: str) -> int:
    return int(_user_row(path, user_id)["auth_version"])


def _principal(user: dict, *, forged_role: str | None = None) -> dict:
    role = forged_role or user["role"]
    return {
        "user_id": user["id"],
        "username": user["username"],
        "role": role,
        "is_admin": role in {"admin", "super_admin"},
        "is_active": True,
        "auth_version": user.get("auth_version", 1),
    }


def _run_checks() -> None:
    from enterprise import admin_api
    from enterprise import auth
    from enterprise import db as edb
    from enterprise import security_user_governance as governance
    from enterprise.migrations.sec_1b1_role_auth import ROLE_AUTH_READY, SCHEMA_LEGACY
    from enterprise.roles import ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_USER
    from enterprise.security_audit import SecurityAuditWriteError

    with tempfile.TemporaryDirectory(prefix="ice-sec-1c0-") as raw_tmp:
        tmp = Path(raw_tmp)
        original_db_path = edb.DB_PATH
        try:
            # A. LEGACY remains compatible and does not gain role/audit schema.
            legacy_db = tmp / "legacy.db"
            _legacy_database(legacy_db)
            edb.DB_PATH = str(legacy_db)
            legacy_admin = edb.create_user(
                "legacy-admin", "legacy-password", "Legacy Admin", True
            )
            legacy_user = edb.create_user(
                "legacy-user", "legacy-password", "Legacy User", False
            )
            assert governance.get_role_auth_schema_state() == SCHEMA_LEGACY
            assert edb.update_user_password(legacy_user["id"], "legacy-password-2") is True
            assert edb.update_user_role(legacy_user["id"], True, updated_by=legacy_admin["id"])
            assert edb.set_user_active(legacy_user["id"], False)
            assert edb.update_user_profile(legacy_user["id"], "Legacy Renamed")
            edb.log_action(legacy_admin["id"], "legacy_user_governance", "kept")
            conn = sqlite3.connect(legacy_db)
            legacy_columns = {
                row[1] for row in conn.execute("PRAGMA main.table_info(users)").fetchall()
            }
            assert "role" not in legacy_columns and "auth_version" not in legacy_columns
            assert conn.execute(
                "SELECT 1 FROM main.sqlite_master "
                "WHERE type = 'table' AND name = 'security_audit_events'"
            ).fetchone() is None
            assert conn.execute("SELECT COUNT(*) FROM main.usage_logs").fetchone()[0] == 1
            conn.close()

            legacy_duplicate = asyncio.run(
                _assert_http_status(
                    admin_api.create_user(
                        FakeRequest(
                            {
                                "user_id": legacy_admin["id"],
                                "username": "legacy-admin",
                                "is_admin": True,
                            },
                            {
                                "username": "legacy-user",
                                "password": "legacy-duplicate-password",
                                "display_name": "Legacy Duplicate",
                                "is_admin": False,
                            },
                        )
                    ),
                    409,
                )
            )
            assert "sqlite" not in json.dumps(legacy_duplicate.detail).lower()

            # B/C. READY without a READY audit schema fails closed for sensitive paths.
            missing_audit_db = tmp / "ready-audit-missing.db"
            edb.DB_PATH = str(missing_audit_db)
            edb.init_db()
            missing_admin = edb.get_user_by_username("admin")
            missing_user = edb.create_user(
                "missing-user", "temporary-password", "Missing User", False
            )
            assert governance.get_role_auth_schema_state() == ROLE_AUTH_READY
            before_missing = _user_row(missing_audit_db, missing_user["id"])
            before_missing_usage = _usage_count(missing_audit_db)
            sensitive_missing_calls = (
                lambda: governance.reset_user_password(
                    actor_user_id=missing_admin["id"],
                    expected_actor_auth_version=_auth_version(missing_audit_db, missing_admin["id"]),
                    target_user_id=missing_user["id"],
                    new_password="replacement-password",
                    reason="temporary reset",
                ),
                lambda: governance.set_user_active(
                    actor_user_id=missing_admin["id"],
                    expected_actor_auth_version=_auth_version(missing_audit_db, missing_admin["id"]),
                    target_user_id=missing_user["id"],
                    is_active=False,
                    reason="temporary disable",
                ),
                lambda: governance.soft_delete_user(
                    actor_user_id=missing_admin["id"],
                    expected_actor_auth_version=_auth_version(missing_audit_db, missing_admin["id"]),
                    target_user_id=missing_user["id"],
                    confirm_username="missing-user",
                    reason="temporary deletion",
                ),
                lambda: governance.deny_online_role_change(
                    actor_user_id=missing_admin["id"],
                    expected_actor_auth_version=_auth_version(missing_audit_db, missing_admin["id"]),
                    target_user_id=missing_user["id"],
                    role_field_present=False,
                    requested_role=None,
                    is_admin_field_present=False,
                    requested_is_admin=None,
                ),
                lambda: governance.check_session_revoke_policy(
                    actor_user_id=missing_admin["id"],
                    expected_actor_auth_version=_auth_version(missing_audit_db, missing_admin["id"]),
                    target_user_id=missing_user["id"],
                ),
            )
            for call in sensitive_missing_calls:
                _assert_raises(governance.UserGovernanceUnavailable, call)
            assert _user_row(missing_audit_db, missing_user["id"]) == before_missing
            assert _usage_count(missing_audit_db) == before_missing_usage
            assert not any(tmp.glob("*.log"))
            conn = sqlite3.connect(missing_audit_db)
            assert conn.execute(
                "SELECT 1 FROM main.sqlite_master "
                "WHERE type = 'table' AND name = 'security_audit_events'"
            ).fetchone() is None
            conn.execute("CREATE TABLE main.security_audit_events (id INTEGER PRIMARY KEY)")
            conn.commit()
            partial_schema = conn.execute(
                "SELECT type, name, sql FROM main.sqlite_master ORDER BY type, name"
            ).fetchall()
            conn.close()
            _assert_raises(
                governance.UserGovernanceUnavailable,
                sensitive_missing_calls[0],
            )
            conn = sqlite3.connect(missing_audit_db)
            assert conn.execute(
                "SELECT type, name, sql FROM main.sqlite_master ORDER BY type, name"
            ).fetchall() == partial_schema
            conn.close()
            assert _user_row(missing_audit_db, missing_user["id"]) == before_missing

            # D-H. READY + audit READY role matrix.
            ready_db = tmp / "ready.db"
            edb.DB_PATH = str(ready_db)
            edb.init_db()
            default_admin = edb.get_user_by_username("admin")
            _apply_audit(ready_db, default_admin["id"])
            admin = {
                "id": default_admin["id"],
                "username": default_admin["username"],
                "role": ROLE_ADMIN,
            }
            prebootstrap_user = _add_ready_user(
                ready_db, username="prebootstrap-user", role=ROLE_USER
            )
            conn = sqlite3.connect(ready_db)
            assert conn.execute(
                "SELECT COUNT(*) FROM main.users "
                "WHERE role = 'super_admin' AND is_active = 1"
            ).fetchone()[0] == 0
            conn.close()
            prebootstrap_reset = governance.reset_user_password(
                actor_user_id=admin["id"],
                expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                target_user_id=prebootstrap_user["id"],
                new_password="prebootstrap-new-password",
                reason="temporary pre-bootstrap governance",
            )
            assert prebootstrap_reset["auth_version"] == 2
            user_a = _add_ready_user(ready_db, username="user-a", role=ROLE_USER)
            user_b = _add_ready_user(ready_db, username="user-b", role=ROLE_USER)
            admin_b = _add_ready_user(ready_db, username="admin-b", role=ROLE_ADMIN)
            super_a = _add_ready_user(ready_db, username="super-a", role=ROLE_SUPER_ADMIN)
            super_b = _add_ready_user(ready_db, username="super-b", role=ROLE_SUPER_ADMIN)

            _assert_raises(
                governance.UserGovernancePolicyDenied,
                lambda: governance.reset_user_password(
                    actor_user_id=user_b["id"],
                    expected_actor_auth_version=_auth_version(ready_db, user_b["id"]),
                    target_user_id=user_a["id"],
                    new_password="user-cannot-govern",
                    reason="temporary user denial",
                ),
            )

            token = auth.create_token(user_a["id"])
            reset = governance.reset_user_password(
                actor_user_id=admin["id"],
                expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                target_user_id=user_a["id"],
                new_password="replacement-password-a",
                reason="temporary password reset",
            )
            assert reset["auth_version"] == 2
            assert auth.verify_token(token) is None
            reset_audit = _audit_rows(ready_db, reset["operation_id"])
            assert len(reset_audit) == 1
            assert reset_audit[0]["action"] == "security.user.password_reset"
            assert reset_audit[0]["actor_role"] == ROLE_ADMIN
            assert "replacement-password-a" not in reset_audit[0]["context_json"]
            version_after_reset = _user_row(ready_db, user_a["id"])["auth_version"]
            for invalid_reason in ("   ", "x" * 2049):
                _assert_raises(
                    governance.UserGovernanceValidationError,
                    lambda invalid_reason=invalid_reason: governance.reset_user_password(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        target_user_id=user_a["id"],
                        new_password="must-not-change-for-invalid-reason",
                        reason=invalid_reason,
                    ),
                )
            assert _user_row(ready_db, user_a["id"])["auth_version"] == version_after_reset

            for target in (admin_b, super_a):
                before = _user_row(ready_db, target["id"])
                _assert_raises(
                    governance.UserGovernancePolicyDenied,
                    lambda target=target: governance.reset_user_password(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        target_user_id=target["id"],
                        new_password="must-not-be-written",
                        reason="temporary denied reset",
                    ),
                )
                assert _user_row(ready_db, target["id"]) == before
                denied = _latest_audit(ready_db, "security.authorization.denied")
                assert denied["risk_level"] == (
                    "L3" if target["role"] == ROLE_SUPER_ADMIN else "L2"
                )
                assert denied["actor_role"] == ROLE_ADMIN
                assert "must-not-be-written" not in denied["context_json"]

            super_reset_admin = governance.reset_user_password(
                actor_user_id=super_a["id"],
                expected_actor_auth_version=_auth_version(ready_db, super_a["id"]),
                target_user_id=admin_b["id"],
                new_password="super-reset-admin-password",
                reason="temporary super-admin reset",
            )
            assert super_reset_admin["auth_version"] == 2
            _assert_raises(
                governance.UserGovernancePolicyDenied,
                lambda: governance.reset_user_password(
                    actor_user_id=super_a["id"],
                    expected_actor_auth_version=_auth_version(ready_db, super_a["id"]),
                    target_user_id=super_b["id"],
                    new_password="must-not-change-super",
                    reason="temporary denied super reset",
                ),
            )

            # Active transitions increment only on actual changes.
            first_disable = governance.set_user_active(
                actor_user_id=admin["id"],
                expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                target_user_id=user_b["id"],
                is_active=False,
                reason="temporary disable",
            )
            assert first_disable["state_changed"] is True and first_disable["auth_version"] == 2
            second_disable = governance.set_user_active(
                actor_user_id=admin["id"],
                expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                target_user_id=user_b["id"],
                is_active=False,
                reason="temporary repeated disable",
            )
            assert second_disable["state_changed"] is False and second_disable["auth_version"] == 2
            enabled = governance.set_user_active(
                actor_user_id=admin["id"],
                expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                target_user_id=user_b["id"],
                is_active=True,
                reason="temporary enable",
            )
            assert enabled["state_changed"] is True and enabled["auth_version"] == 3
            for actor_id, target in (
                (admin["id"], admin_b),
                (admin["id"], super_a),
                (super_a["id"], super_b),
            ):
                before = _user_row(ready_db, target["id"])
                _assert_raises(
                    governance.UserGovernancePolicyDenied,
                    lambda actor_id=actor_id, target=target: governance.set_user_active(
                        actor_user_id=actor_id,
                        expected_actor_auth_version=_auth_version(ready_db, actor_id),
                        target_user_id=target["id"],
                        is_active=False,
                        reason="temporary denied active change",
                    ),
                )
                assert _user_row(ready_db, target["id"]) == before
            super_disable_admin = governance.set_user_active(
                actor_user_id=super_a["id"],
                expected_actor_auth_version=_auth_version(ready_db, super_a["id"]),
                target_user_id=admin_b["id"],
                is_active=False,
                reason="temporary disable admin",
            )
            assert super_disable_admin["state_changed"] is True
            governance.set_user_active(
                actor_user_id=super_a["id"],
                expected_actor_auth_version=_auth_version(ready_db, super_a["id"]),
                target_user_id=admin_b["id"],
                is_active=True,
                reason="temporary enable admin",
            )

            delete_target = _add_ready_user(ready_db, username="delete-user", role=ROLE_USER)
            deleted = governance.soft_delete_user(
                actor_user_id=admin["id"],
                expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                target_user_id=delete_target["id"],
                confirm_username="delete-user",
                reason="temporary offboarding",
            )
            assert deleted["state_changed"] is True
            assert _user_row(ready_db, delete_target["id"])["is_active"] == 0
            for actor_id, target in (
                (admin["id"], admin_b),
                (admin["id"], super_a),
                (super_a["id"], super_b),
            ):
                before = _user_row(ready_db, target["id"])
                _assert_raises(
                    governance.UserGovernancePolicyDenied,
                    lambda actor_id=actor_id, target=target: governance.soft_delete_user(
                        actor_user_id=actor_id,
                        expected_actor_auth_version=_auth_version(ready_db, actor_id),
                        target_user_id=target["id"],
                        confirm_username=target["username"],
                        reason="temporary denied delete",
                    ),
                )
                assert _user_row(ready_db, target["id"]) == before
            super_delete_admin = _add_ready_user(
                ready_db, username="delete-admin", role=ROLE_ADMIN
            )
            governance.soft_delete_user(
                actor_user_id=super_a["id"],
                expected_actor_auth_version=_auth_version(ready_db, super_a["id"]),
                target_user_id=super_delete_admin["id"],
                confirm_username="delete-admin",
                reason="temporary admin offboarding",
            )
            assert _user_row(ready_db, super_delete_admin["id"])["is_active"] == 0

            profile_user = governance.update_user_profile(
                actor_user_id=admin["id"],
                expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                target_user_id=user_a["id"],
                display_name="User A Renamed",
            )
            assert profile_user["user"]["display_name"] == "User A Renamed"
            _assert_raises(
                governance.UserGovernancePolicyDenied,
                lambda: governance.update_user_profile(
                    actor_user_id=admin["id"],
                    expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                    target_user_id=admin_b["id"],
                    display_name="Denied Admin Rename",
                ),
            )
            _assert_raises(
                governance.UserGovernancePolicyDenied,
                lambda: governance.update_user_profile(
                    actor_user_id=admin["id"],
                    expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                    target_user_id=super_a["id"],
                    display_name="Denied Super Rename By Admin",
                ),
            )
            governance.update_user_profile(
                actor_user_id=super_a["id"],
                expected_actor_auth_version=_auth_version(ready_db, super_a["id"]),
                target_user_id=admin_b["id"],
                display_name="Admin B Renamed",
            )
            governance.update_user_profile(
                actor_user_id=super_a["id"],
                expected_actor_auth_version=_auth_version(ready_db, super_a["id"]),
                target_user_id=super_a["id"],
                display_name="Super A Renamed",
            )
            _assert_raises(
                governance.UserGovernancePolicyDenied,
                lambda: governance.update_user_profile(
                    actor_user_id=super_a["id"],
                    expected_actor_auth_version=_auth_version(ready_db, super_a["id"]),
                    target_user_id=super_b["id"],
                    display_name="Denied Super Rename",
                ),
            )

            # Online role changes and elevated create fields are closed for everyone.
            for actor_id, target in (
                (admin["id"], user_a),
                (admin["id"], super_a),
                (super_a["id"], admin_b),
                (super_a["id"], super_a),
            ):
                before = _user_row(ready_db, target["id"])
                _assert_raises(
                    governance.UserGovernancePolicyDenied,
                    lambda actor_id=actor_id, target=target: governance.deny_online_role_change(
                        actor_user_id=actor_id,
                        expected_actor_auth_version=_auth_version(ready_db, actor_id),
                        target_user_id=target["id"],
                        role_field_present=False,
                        requested_role=None,
                        is_admin_field_present=False,
                        requested_is_admin=None,
                    ),
                )
                assert _user_row(ready_db, target["id"]) == before

            ordinary_created = governance.create_ordinary_user(
                actor_user_id=admin["id"],
                expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                username="created-user",
                password="created-user-password",
                display_name="Created User",
                requested_is_admin=False,
                role_field_present=False,
            )
            assert _user_row(ready_db, ordinary_created["id"])["role"] == ROLE_USER
            for suffix, requested_is_admin, role_present, requested_role in (
                ("is-admin", True, False, None),
                ("numeric-admin", 1, False, None),
                ("admin-role", False, True, ROLE_ADMIN),
                ("super-role", False, True, ROLE_SUPER_ADMIN),
                ("user-role", False, True, ROLE_USER),
            ):
                username = f"denied-create-{suffix}"
                _assert_raises(
                    governance.UserGovernancePolicyDenied,
                    lambda username=username, requested_is_admin=requested_is_admin,
                    role_present=role_present, requested_role=requested_role: governance.create_ordinary_user(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        username=username,
                        password="must-not-be-stored",
                        display_name=username,
                        requested_is_admin=requested_is_admin,
                        role_field_present=role_present,
                        requested_role=requested_role,
                    ),
                )
                conn = sqlite3.connect(ready_db)
                assert conn.execute(
                    "SELECT 1 FROM main.users WHERE username = ?", (username,)
                ).fetchone() is None
                conn.close()
                denied = _latest_audit(ready_db, "security.authorization.denied")
                assert "must-not-be-stored" not in denied["context_json"]

            # Session-revoke policy primitive is not exposed as an API.
            assert governance.check_session_revoke_policy(
                actor_user_id=admin["id"],
                expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                target_user_id=user_a["id"],
            )["target_role"] == ROLE_USER
            _assert_raises(
                governance.UserGovernancePolicyDenied,
                lambda: governance.check_session_revoke_policy(
                    actor_user_id=admin["id"],
                    expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                    target_user_id=admin_b["id"],
                ),
            )
            _assert_raises(
                governance.UserGovernancePolicyDenied,
                lambda: governance.check_session_revoke_policy(
                    actor_user_id=admin["id"],
                    expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                    target_user_id=super_a["id"],
                ),
            )
            assert governance.check_session_revoke_policy(
                actor_user_id=super_a["id"],
                expected_actor_auth_version=_auth_version(ready_db, super_a["id"]),
                target_user_id=admin_b["id"],
            )["target_role"] == ROLE_ADMIN
            _assert_raises(
                governance.UserGovernancePolicyDenied,
                lambda: governance.check_session_revoke_policy(
                    actor_user_id=super_a["id"],
                    expected_actor_auth_version=_auth_version(ready_db, super_a["id"]),
                    target_user_id=super_b["id"],
                ),
            )

            # J. Last active super-admin helper and lock-time recount.
            single_super_db = tmp / "single-super.db"
            edb.DB_PATH = str(single_super_db)
            edb.init_db()
            single_admin = edb.get_user_by_username("admin")
            _apply_audit(single_super_db, single_admin["id"])
            single_super = _add_ready_user(
                single_super_db, username="single-super", role=ROLE_SUPER_ADMIN
            )
            conn = sqlite3.connect(single_super_db)
            conn.execute("BEGIN IMMEDIATE")
            assert governance.count_active_super_admins(conn) == 1
            for operation in ("disable", "soft_delete", "role_change"):
                _assert_raises(
                    governance.UserGovernanceConflict,
                    lambda operation=operation: governance.ensure_active_super_admin_remains(
                        conn, single_super["id"], operation
                    ),
                )
            conn.rollback()
            assert _user_row(single_super_db, single_super["id"])["auth_version"] == 1
            conn.close()

            two_super_db = tmp / "two-super.db"
            edb.DB_PATH = str(two_super_db)
            edb.init_db()
            two_admin = edb.get_user_by_username("admin")
            first_super = _add_ready_user(
                two_super_db, username="first-super", role=ROLE_SUPER_ADMIN
            )
            second_super = _add_ready_user(
                two_super_db, username="second-super", role=ROLE_SUPER_ADMIN
            )
            conn1 = sqlite3.connect(two_super_db, timeout=0.1)
            conn2 = sqlite3.connect(two_super_db, timeout=0.1)
            conn1.execute("BEGIN IMMEDIATE")
            assert governance.count_active_super_admins(conn1) == 2
            governance.ensure_active_super_admin_remains(conn1, first_super["id"], "disable")
            conn1.execute(
                "UPDATE main.users SET is_active = 0 WHERE id = ?", (first_super["id"],)
            )
            _assert_raises(sqlite3.OperationalError, lambda: conn2.execute("BEGIN IMMEDIATE"))
            conn1.commit()
            conn2.execute("BEGIN IMMEDIATE")
            assert governance.count_active_super_admins(conn2) == 1
            _assert_raises(
                governance.UserGovernanceConflict,
                lambda: governance.ensure_active_super_admin_remains(
                    conn2, second_super["id"], "disable"
                ),
            )
            conn2.rollback()
            conn1.close()
            conn2.close()
            assert _user_row(two_super_db, second_super["id"])["is_active"] == 1
            assert two_admin["role"] == ROLE_ADMIN

            # L/M. Audit failure rolls back mutation and denied decisions.
            edb.DB_PATH = str(ready_db)
            atomic_target = _add_ready_user(
                ready_db, username="atomic-user", role=ROLE_USER
            )
            before_atomic = _user_row(ready_db, atomic_target["id"])
            usage_before_atomic = _usage_count(ready_db)
            original_append = governance.append_security_audit_event

            def fail_audit(**_kwargs):
                raise SecurityAuditWriteError("temporary injected audit failure")

            governance.append_security_audit_event = fail_audit
            try:
                _assert_raises(
                    governance.UserGovernanceUnavailable,
                    lambda: governance.reset_user_password(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        target_user_id=atomic_target["id"],
                        new_password="atomic-new-password",
                        reason="temporary atomicity test",
                    ),
                )
                _assert_raises(
                    governance.UserGovernanceUnavailable,
                    lambda: governance.reset_user_password(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        target_user_id=super_a["id"],
                        new_password="denied-atomic-password",
                        reason="temporary denied atomicity test",
                    ),
                )
            finally:
                governance.append_security_audit_event = original_append
            assert _user_row(ready_db, atomic_target["id"]) == before_atomic
            assert _usage_count(ready_db) == usage_before_atomic

            # N. main.users writes fail closed on silent no-ops and post-write tampering.
            integrity_target = _add_ready_user(
                ready_db, username="integrity-target", role=ROLE_USER
            )

            def install_users_trigger(name: str, definition: str) -> None:
                conn = sqlite3.connect(ready_db)
                try:
                    conn.execute(definition)
                    conn.commit()
                finally:
                    conn.close()

            def drop_users_trigger(name: str) -> None:
                conn = sqlite3.connect(ready_db)
                try:
                    conn.execute(f"DROP TRIGGER main.{name}")
                    conn.commit()
                finally:
                    conn.close()

            before_create_audit = _audit_count(ready_db)
            before_create_usage = _usage_count(ready_db)
            install_users_trigger(
                "sec1c0_ignore_create",
                """
                CREATE TRIGGER sec1c0_ignore_create
                BEFORE INSERT ON users
                WHEN NEW.username = 'integrity-ignored-create'
                BEGIN
                    SELECT RAISE(IGNORE);
                END
                """,
            )
            try:
                _assert_raises(
                    governance.UserGovernanceIntegrityError,
                    lambda: governance.create_ordinary_user(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        username="integrity-ignored-create",
                        password="temporary-integrity-password",
                        display_name="Ignored Create",
                        requested_is_admin=False,
                        role_field_present=False,
                    ),
                )
            finally:
                drop_users_trigger("sec1c0_ignore_create")
            conn = sqlite3.connect(ready_db)
            assert conn.execute(
                "SELECT 1 FROM main.users WHERE username = 'integrity-ignored-create'"
            ).fetchone() is None
            conn.close()
            assert _audit_count(ready_db) == before_create_audit
            assert _usage_count(ready_db) == before_create_usage

            install_users_trigger(
                "sec1c0_ignore_create_api",
                """
                CREATE TRIGGER sec1c0_ignore_create_api
                BEFORE INSERT ON users
                WHEN NEW.username = 'integrity-ignored-create-api'
                BEGIN
                    SELECT RAISE(IGNORE);
                END
                """,
            )
            try:
                asyncio.run(
                    _assert_http_status(
                        admin_api.create_user(
                            FakeRequest(
                                _principal(admin),
                                {
                                    "username": "integrity-ignored-create-api",
                                    "password": "temporary-integrity-api-password",
                                    "display_name": "Ignored API Create",
                                    "is_admin": False,
                                },
                            )
                        ),
                        409,
                    )
                )
            finally:
                drop_users_trigger("sec1c0_ignore_create_api")
            assert _usage_count(ready_db) == before_create_usage

            integrity_cases = (
                (
                    "sec1c0_ignore_password",
                    "BEFORE UPDATE OF password_hash ON users",
                    lambda: governance.reset_user_password(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        target_user_id=integrity_target["id"],
                        new_password="ignored-password-update",
                        reason="temporary integrity password",
                    ),
                ),
                (
                    "sec1c0_ignore_active",
                    "BEFORE UPDATE OF is_active ON users",
                    lambda: governance.set_user_active(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        target_user_id=integrity_target["id"],
                        is_active=False,
                        reason="temporary integrity active",
                    ),
                ),
                (
                    "sec1c0_ignore_delete",
                    "BEFORE UPDATE OF is_active ON users",
                    lambda: governance.soft_delete_user(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        target_user_id=integrity_target["id"],
                        confirm_username="integrity-target",
                        reason="temporary integrity delete",
                    ),
                ),
                (
                    "sec1c0_ignore_profile",
                    "BEFORE UPDATE OF display_name ON users",
                    lambda: governance.update_user_profile(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        target_user_id=integrity_target["id"],
                        display_name="Ignored Profile",
                    ),
                ),
            )
            for trigger_name, trigger_event, call in integrity_cases:
                before_target = _user_row(ready_db, integrity_target["id"])
                before_audit = _audit_count(ready_db)
                install_users_trigger(
                    trigger_name,
                    f"""
                    CREATE TRIGGER {trigger_name}
                    {trigger_event}
                    WHEN OLD.id = '{integrity_target["id"]}'
                    BEGIN
                        SELECT RAISE(IGNORE);
                    END
                    """,
                )
                try:
                    _assert_raises(governance.UserGovernanceIntegrityError, call)
                finally:
                    drop_users_trigger(trigger_name)
                assert _user_row(ready_db, integrity_target["id"]) == before_target
                assert _audit_count(ready_db) == before_audit

            before_tamper = _user_row(ready_db, integrity_target["id"])
            before_tamper_audit = _audit_count(ready_db)
            install_users_trigger(
                "sec1c0_tamper_target",
                f"""
                CREATE TRIGGER sec1c0_tamper_target
                AFTER UPDATE OF password_hash ON users
                WHEN NEW.id = '{integrity_target["id"]}'
                BEGIN
                    UPDATE users SET role = 'admin', is_admin = 1 WHERE id = NEW.id;
                END
                """,
            )
            try:
                _assert_raises(
                    governance.UserGovernanceIntegrityError,
                    lambda: governance.reset_user_password(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        target_user_id=integrity_target["id"],
                        new_password="tampered-password-update",
                        reason="temporary target tamper",
                    ),
                )
            finally:
                drop_users_trigger("sec1c0_tamper_target")
            assert _user_row(ready_db, integrity_target["id"]) == before_tamper
            assert _audit_count(ready_db) == before_tamper_audit

            before_actor_tamper = _user_row(ready_db, integrity_target["id"])
            before_admin_tamper = _user_row(ready_db, admin["id"])
            install_users_trigger(
                "sec1c0_tamper_actor",
                f"""
                CREATE TRIGGER sec1c0_tamper_actor
                AFTER UPDATE OF display_name ON users
                WHEN NEW.id = '{integrity_target["id"]}'
                BEGIN
                    UPDATE users SET auth_version = auth_version + 1
                    WHERE id = '{admin["id"]}';
                END
                """,
            )
            try:
                _assert_raises(
                    governance.UserGovernanceIntegrityError,
                    lambda: governance.update_user_profile(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        target_user_id=integrity_target["id"],
                        display_name="Actor Tamper",
                    ),
                )
            finally:
                drop_users_trigger("sec1c0_tamper_actor")
            assert _user_row(ready_db, integrity_target["id"]) == before_actor_tamper
            assert _user_row(ready_db, admin["id"]) == before_admin_tamper

            # N2. The governance transaction rejects a principal revoked after middleware.
            stale_actor = _add_ready_user(ready_db, username="stale-admin", role=ROLE_ADMIN)
            stale_target = _add_ready_user(ready_db, username="stale-target", role=ROLE_USER)
            conn = sqlite3.connect(ready_db)
            conn.execute(
                "UPDATE main.users SET auth_version = 2 WHERE id = ?",
                (stale_actor["id"],),
            )
            conn.commit()
            conn.close()
            stale_before = _user_row(ready_db, stale_target["id"])
            stale_calls = (
                lambda: governance.reset_user_password(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=stale_target["id"],
                    new_password="stale-password",
                    reason="temporary stale password",
                ),
                lambda: governance.set_user_active(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=stale_target["id"],
                    is_active=False,
                    reason="temporary stale active",
                ),
                lambda: governance.soft_delete_user(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=stale_target["id"],
                    confirm_username="stale-target",
                    reason="temporary stale delete",
                ),
                lambda: governance.update_user_profile(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=stale_target["id"],
                    display_name="Stale Rename",
                ),
                lambda: governance.create_ordinary_user(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    username="stale-create",
                    password="stale-create-password",
                    display_name="Stale Create",
                    requested_is_admin=False,
                    role_field_present=False,
                ),
                lambda: governance.deny_online_role_change(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=stale_target["id"],
                    role_field_present=True,
                    requested_role=ROLE_ADMIN,
                    is_admin_field_present=True,
                    requested_is_admin=True,
                ),
                lambda: governance.check_session_revoke_policy(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=stale_target["id"],
                ),
            )
            for call in stale_calls:
                _assert_raises(governance.UserGovernanceStaleSession, call)
            assert _user_row(ready_db, stale_target["id"]) == stale_before
            stale_denied = _latest_audit(ready_db, "security.authorization.denied")
            assert stale_denied["actor_user_id"] == stale_actor["id"]
            assert json.loads(stale_denied["context_json"])["policy_code"] == "stale_actor_auth_version"
            governance.update_user_profile(
                actor_user_id=stale_actor["id"],
                expected_actor_auth_version=2,
                target_user_id=stale_target["id"],
                display_name="Fresh Rename",
            )
            fresh_create = governance.create_ordinary_user(
                actor_user_id=stale_actor["id"],
                expected_actor_auth_version=2,
                username="fresh-after-stale",
                password="fresh-create-password",
                display_name="Fresh Create",
                requested_is_admin=False,
                role_field_present=False,
            )
            assert _user_row(ready_db, fresh_create["id"])["role"] == ROLE_USER

            # N3. Active ordinary users enter the policy layer and produce denied audit.
            user_actor_version = _auth_version(ready_db, user_b["id"])
            ordinary_user_denials = (
                (
                    "L2",
                    lambda: governance.reset_user_password(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=user_actor_version,
                        target_user_id=user_a["id"],
                        new_password="ordinary-user-denied",
                        reason="temporary ordinary denial",
                    ),
                ),
                (
                    "L2",
                    lambda: governance.set_user_active(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=user_actor_version,
                        target_user_id=user_a["id"],
                        is_active=False,
                        reason="temporary ordinary denial",
                    ),
                ),
                (
                    "L2",
                    lambda: governance.soft_delete_user(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=user_actor_version,
                        target_user_id=user_a["id"],
                        confirm_username="user-a",
                        reason="temporary ordinary denial",
                    ),
                ),
                (
                    "L2",
                    lambda: governance.update_user_profile(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=user_actor_version,
                        target_user_id=user_a["id"],
                        display_name="Denied Ordinary Profile",
                    ),
                ),
                (
                    "L3",
                    lambda: governance.deny_online_role_change(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=user_actor_version,
                        target_user_id=user_a["id"],
                        role_field_present=True,
                        requested_role=ROLE_SUPER_ADMIN,
                        is_admin_field_present=False,
                        requested_is_admin=None,
                    ),
                ),
                (
                    "L3",
                    lambda: governance.check_session_revoke_policy(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=user_actor_version,
                        target_user_id=super_a["id"],
                    ),
                ),
                (
                    "L2",
                    lambda: governance.create_ordinary_user(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=user_actor_version,
                        username="ordinary-user-create-denied",
                        password="ordinary-user-create-password",
                        display_name="Denied Create",
                        requested_is_admin=False,
                        role_field_present=False,
                    ),
                ),
            )
            before_ordinary_target = _user_row(ready_db, user_a["id"])
            for expected_risk, call in ordinary_user_denials:
                _assert_raises(governance.UserGovernancePolicyDenied, call)
                denied = _latest_audit(ready_db, "security.authorization.denied")
                assert denied["actor_role"] == ROLE_USER
                assert denied["risk_level"] == expected_risk
                assert "ordinary-user-denied" not in denied["context_json"]
            assert _user_row(ready_db, user_a["id"]) == before_ordinary_target

            # N4. Authenticate actor before a missing target becomes observable.
            missing_target_id = f"missing-target-{uuid.uuid4().hex}"
            stale_missing_calls = (
                lambda: governance.reset_user_password(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=missing_target_id,
                    new_password="stale-missing-password",
                    reason="temporary stale missing target",
                ),
                lambda: governance.set_user_active(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=missing_target_id,
                    is_active=False,
                    reason="temporary stale missing target",
                ),
                lambda: governance.soft_delete_user(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=missing_target_id,
                    confirm_username="not-reached",
                    reason="temporary stale missing target",
                ),
                lambda: governance.update_user_profile(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=missing_target_id,
                    display_name="Stale Missing Target",
                ),
                lambda: governance.deny_online_role_change(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=missing_target_id,
                    role_field_present=True,
                    requested_role=ROLE_ADMIN,
                    is_admin_field_present=True,
                    requested_is_admin=True,
                ),
                lambda: governance.check_session_revoke_policy(
                    actor_user_id=stale_actor["id"],
                    expected_actor_auth_version=1,
                    target_user_id=missing_target_id,
                ),
            )
            for call in stale_missing_calls:
                _assert_raises(governance.UserGovernanceStaleSession, call)
                denied = _latest_audit(ready_db, "security.authorization.denied")
                assert denied["actor_user_id"] == stale_actor["id"]
                assert json.loads(denied["context_json"])["policy_code"] == "stale_actor_auth_version"

            ordinary_missing_calls = (
                (
                    "L2",
                    lambda: governance.reset_user_password(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=_auth_version(ready_db, user_b["id"]),
                        target_user_id=missing_target_id,
                        new_password="ordinary-missing-password",
                        reason="temporary ordinary missing target",
                    ),
                ),
                (
                    "L2",
                    lambda: governance.set_user_active(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=_auth_version(ready_db, user_b["id"]),
                        target_user_id=missing_target_id,
                        is_active=False,
                        reason="temporary ordinary missing target",
                    ),
                ),
                (
                    "L2",
                    lambda: governance.soft_delete_user(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=_auth_version(ready_db, user_b["id"]),
                        target_user_id=missing_target_id,
                        confirm_username="not-reached",
                        reason="temporary ordinary missing target",
                    ),
                ),
                (
                    "L2",
                    lambda: governance.update_user_profile(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=_auth_version(ready_db, user_b["id"]),
                        target_user_id=missing_target_id,
                        display_name="Ordinary Missing Target",
                    ),
                ),
                (
                    "L3",
                    lambda: governance.deny_online_role_change(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=_auth_version(ready_db, user_b["id"]),
                        target_user_id=missing_target_id,
                        role_field_present=True,
                        requested_role=ROLE_SUPER_ADMIN,
                        is_admin_field_present=False,
                        requested_is_admin=None,
                    ),
                ),
                (
                    "L2",
                    lambda: governance.check_session_revoke_policy(
                        actor_user_id=user_b["id"],
                        expected_actor_auth_version=_auth_version(ready_db, user_b["id"]),
                        target_user_id=missing_target_id,
                    ),
                ),
            )
            for expected_risk, call in ordinary_missing_calls:
                _assert_raises(governance.UserGovernancePolicyDenied, call)
                denied = _latest_audit(ready_db, "security.authorization.denied")
                assert denied["actor_role"] == ROLE_USER
                assert denied["risk_level"] == expected_risk

            fresh_missing_calls = (
                lambda: governance.reset_user_password(
                    actor_user_id=admin["id"],
                    expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                    target_user_id=missing_target_id,
                    new_password="fresh-missing-password",
                    reason="temporary fresh missing target",
                ),
                lambda: governance.set_user_active(
                    actor_user_id=admin["id"],
                    expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                    target_user_id=missing_target_id,
                    is_active=False,
                    reason="temporary fresh missing target",
                ),
                lambda: governance.soft_delete_user(
                    actor_user_id=admin["id"],
                    expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                    target_user_id=missing_target_id,
                    confirm_username="not-reached",
                    reason="temporary fresh missing target",
                ),
                lambda: governance.update_user_profile(
                    actor_user_id=admin["id"],
                    expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                    target_user_id=missing_target_id,
                    display_name="Fresh Missing Target",
                ),
                lambda: governance.deny_online_role_change(
                    actor_user_id=admin["id"],
                    expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                    target_user_id=missing_target_id,
                    role_field_present=True,
                    requested_role=ROLE_ADMIN,
                    is_admin_field_present=True,
                    requested_is_admin=True,
                ),
                lambda: governance.check_session_revoke_policy(
                    actor_user_id=admin["id"],
                    expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                    target_user_id=missing_target_id,
                ),
            )
            for call in fresh_missing_calls:
                _assert_raises(governance.UserGovernanceNotFound, call)

            for invalid_version in (None, True, False, "1", 1.0, -1):
                _assert_raises(
                    governance.UserGovernanceStaleSession,
                    lambda invalid_version=invalid_version: governance.update_user_profile(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=invalid_version,
                        target_user_id=user_a["id"],
                        display_name="Invalid Version",
                    ),
                )

            # O. Legacy mutators cannot bypass READY protections.
            direct_target = _add_ready_user(
                ready_db, username="direct-target", role=ROLE_SUPER_ADMIN
            )
            before_direct = _user_row(ready_db, direct_target["id"])
            for call in (
                lambda: edb.update_user_password(direct_target["id"], "direct-password"),
                lambda: edb.update_user_role(direct_target["id"], False, updated_by=admin["id"]),
                lambda: edb.set_user_active(direct_target["id"], False),
                lambda: edb.delete_user(direct_target["id"]),
                lambda: edb.update_user_profile(direct_target["id"], "Direct Rename"),
                lambda: edb.create_user("direct-admin", "direct-password", "Direct", True),
            ):
                _assert_raises(edb.SecureUserGovernanceRequiredError, call)
            assert _user_row(ready_db, direct_target["id"]) == before_direct
            conn = sqlite3.connect(ready_db)
            assert conn.execute(
                "SELECT 1 FROM main.users WHERE username = 'direct-admin'"
            ).fetchone() is None
            conn.close()

            # P. TEMP users cannot influence actor, target, count, policy, or audit role.
            temp_target = _add_ready_user(ready_db, username="temp-target", role=ROLE_SUPER_ADMIN)
            prepared_conn = edb.get_db()
            prepared_conn.executescript(
                """
                CREATE TEMP TABLE users AS SELECT * FROM main.users WHERE 0;
                INSERT INTO temp.users SELECT * FROM main.users;
                """
            )
            prepared_conn.execute(
                "UPDATE temp.users SET role = 'super_admin', is_admin = 1 WHERE id = ?",
                (admin["id"],),
            )
            prepared_conn.execute(
                "UPDATE temp.users SET role = 'user', is_admin = 0 WHERE id = ?",
                (temp_target["id"],),
            )
            prepared_conn.commit()
            original_get_db = governance.edb.get_db
            governance.edb.get_db = lambda: prepared_conn
            try:
                _assert_raises(
                    governance.UserGovernancePolicyDenied,
                    lambda: governance.reset_user_password(
                        actor_user_id=admin["id"],
                        expected_actor_auth_version=_auth_version(ready_db, admin["id"]),
                        target_user_id=temp_target["id"],
                        new_password="temp-shadow-password",
                        reason="temporary shadow test",
                    ),
                )
            finally:
                governance.edb.get_db = original_get_db
            denied = _latest_audit(ready_db, "security.authorization.denied")
            denied_context = json.loads(denied["context_json"])
            assert denied["actor_role"] == ROLE_ADMIN
            assert denied["risk_level"] == "L3"
            assert denied_context["target_role"] == ROLE_SUPER_ADMIN
            assert _user_row(ready_db, temp_target["id"])["auth_version"] == 1
            count_conn = sqlite3.connect(ready_db)
            count_conn.execute(
                "CREATE TEMP TABLE users AS SELECT * FROM main.users WHERE 0"
            )
            count_conn.execute("BEGIN IMMEDIATE")
            assert governance.count_active_super_admins(count_conn) >= 1
            count_conn.rollback()
            count_conn.close()

            # Q. API mapping and stale request principal cannot override main role.
            forged_super_principal = _principal(admin, forged_role=ROLE_SUPER_ADMIN)
            before_api_admin = _user_row(ready_db, admin_b["id"])
            api_denied = asyncio.run(
                _assert_http_status(
                    admin_api.reset_password(
                        admin_b["id"],
                        FakeRequest(
                            forged_super_principal,
                            {
                                "password": "api-must-not-change",
                                "reason": "temporary API denial",
                            },
                        ),
                    ),
                    403,
                )
            )
            assert _user_row(ready_db, admin_b["id"]) == before_api_admin
            assert "sql" not in json.dumps(api_denied.detail).lower()
            assert "password_hash" not in json.dumps(api_denied.detail).lower()
            assert str(ready_db).lower() not in json.dumps(api_denied.detail).lower()

            # READY APIs pass the verified principal version and do not trust stale snapshots.
            stale_principal = _principal({**stale_actor, "auth_version": 1})
            stale_api_before = _user_row(ready_db, stale_target["id"])
            stale_api = asyncio.run(
                _assert_http_status(
                    admin_api.reset_password(
                        stale_target["id"],
                        FakeRequest(
                            stale_principal,
                            {
                                "password": "api-stale-password",
                                "reason": "temporary stale API request",
                            },
                        ),
                    ),
                    401,
                )
            )
            stale_api_detail = json.dumps(stale_api.detail).lower()
            assert "sql" not in stale_api_detail
            assert "password" not in stale_api_detail
            assert str(ready_db).lower() not in stale_api_detail
            assert _user_row(ready_db, stale_target["id"]) == stale_api_before
            missing_version_principal = dict(stale_principal)
            missing_version_principal.pop("auth_version")
            asyncio.run(
                _assert_http_status(
                    admin_api.update_user_profile(
                        stale_target["id"],
                        FakeRequest(missing_version_principal, {"display_name": "No Version"}),
                    ),
                    401,
                )
            )
            bool_version_principal = {**stale_principal, "auth_version": True}
            asyncio.run(
                _assert_http_status(
                    admin_api.update_user_profile(
                        stale_target["id"],
                        FakeRequest(bool_version_principal, {"display_name": "Bool Version"}),
                    ),
                    401,
                )
            )

            for invalid_version in (None, False, "1", 1.0, -1):
                invalid_principal = {
                    **_principal(admin),
                    "auth_version": invalid_version,
                }
                asyncio.run(
                    _assert_http_status(
                        admin_api.update_user_profile(
                            user_a["id"],
                            FakeRequest(invalid_principal, {"display_name": "Invalid API Version"}),
                        ),
                        401,
                )
            )

            ordinary_api_principal = _principal(
                {**user_b, "auth_version": _auth_version(ready_db, user_b["id"])}
            )
            stale_missing_api = asyncio.run(
                _assert_http_status(
                    admin_api.reset_password(
                        missing_target_id,
                        FakeRequest(
                            stale_principal,
                            {
                                "password": "stale-missing-api-password",
                                "reason": "temporary stale missing API target",
                            },
                        ),
                    ),
                    401,
                )
            )
            assert "not found" not in json.dumps(stale_missing_api.detail).lower()
            ordinary_missing_api = asyncio.run(
                _assert_http_status(
                    admin_api.reset_password(
                        missing_target_id,
                        FakeRequest(
                            ordinary_api_principal,
                            {
                                "password": "ordinary-missing-api-password",
                                "reason": "temporary ordinary missing API target",
                            },
                        ),
                    ),
                    403,
                )
            )
            assert "not found" not in json.dumps(ordinary_missing_api.detail).lower()
            asyncio.run(
                _assert_http_status(
                    admin_api.reset_password(
                        missing_target_id,
                        FakeRequest(
                            _principal(admin),
                            {
                                "password": "fresh-missing-api-password",
                                "reason": "temporary fresh missing API target",
                            },
                        ),
                    ),
                    404,
                )
            )

            asyncio.run(
                _assert_http_status(
                    admin_api.create_user(
                        FakeRequest(
                            ordinary_api_principal,
                            {
                                "username": "ordinary-api-create-denied",
                                "password": "ordinary-api-password",
                                "display_name": "Ordinary API Denied",
                                "is_admin": False,
                            },
                        )
                    ),
                    403,
                )
            )
            denied = _latest_audit(ready_db, "security.authorization.denied")
            assert denied["actor_role"] == ROLE_USER and denied["risk_level"] == "L2"

            role_before = _user_row(ready_db, user_a["id"])
            asyncio.run(
                _assert_http_status(
                    admin_api.update_user_role(
                        user_a["id"],
                        FakeRequest(_principal(admin), {"role": ROLE_SUPER_ADMIN}),
                    ),
                    403,
                )
            )
            role_denied = _latest_audit(ready_db, "security.authorization.denied")
            assert role_denied["risk_level"] == "L3"
            assert _user_row(ready_db, user_a["id"]) == role_before

            asyncio.run(
                _assert_http_status(
                    admin_api.update_user_role(
                        user_a["id"],
                        FakeRequest(_principal(admin), {"is_admin": True}),
                    ),
                    403,
                )
            )
            asyncio.run(
                _assert_http_status(
                    admin_api.create_user(
                        FakeRequest(
                            _principal(admin),
                            {
                                "username": "api-admin",
                                "password": "api-admin-password",
                                "is_admin": True,
                            },
                        )
                    ),
                    403,
                )
            )
            conn = sqlite3.connect(ready_db)
            assert conn.execute(
                "SELECT 1 FROM main.users WHERE username = 'api-admin'"
            ).fetchone() is None
            conn.close()

            before_unexpected_create_usage = _usage_count(ready_db)
            original_create_ordinary_user = governance.create_ordinary_user

            def raise_unexpected_create_error(**_kwargs):
                raise RuntimeError("temporary-secret-create-error sqlite /private/test.db")

            governance.create_ordinary_user = raise_unexpected_create_error
            try:
                unexpected_create = asyncio.run(
                    _assert_http_status(
                        admin_api.create_user(
                            FakeRequest(
                                _principal(admin),
                                {
                                    "username": "unexpected-create-error",
                                    "password": "unexpected-create-password",
                                    "display_name": "Unexpected Create",
                                    "is_admin": False,
                                },
                            )
                        ),
                        500,
                    )
                )
            finally:
                governance.create_ordinary_user = original_create_ordinary_user
            unexpected_detail = json.dumps(unexpected_create.detail).lower()
            assert "temporary-secret-create-error" not in unexpected_detail
            assert "sqlite" not in unexpected_detail
            assert "/private/test.db" not in unexpected_detail
            assert "runtimeerror" not in unexpected_detail
            assert _usage_count(ready_db) == before_unexpected_create_usage

            created_response = asyncio.run(
                admin_api.create_user(
                    FakeRequest(
                        _principal(admin),
                        {
                            "username": "api-user",
                            "password": "api-user-password",
                            "display_name": "API User",
                            "is_admin": False,
                        },
                    )
                )
            )
            assert created_response.status_code == 201
            api_user_id = json.loads(created_response.body)["user"]["id"]
            assert _user_row(ready_db, api_user_id)["role"] == ROLE_USER
            ready_duplicate = asyncio.run(
                _assert_http_status(
                    admin_api.create_user(
                        FakeRequest(
                            _principal(admin),
                            {
                                "username": "api-user",
                                "password": "ready-duplicate-password",
                                "display_name": "Ready Duplicate",
                                "is_admin": False,
                            },
                        )
                    ),
                    409,
                )
            )
            assert "sqlite" not in json.dumps(ready_duplicate.detail).lower()
            password_response = asyncio.run(
                admin_api.reset_password(
                    api_user_id,
                    FakeRequest(
                        _principal(admin),
                        {
                            "password": "api-replacement-password",
                            "reason": "temporary API reset",
                        },
                    ),
                )
            )
            assert password_response["operation_id"]
            active_response = asyncio.run(
                admin_api.update_user_active(
                    api_user_id,
                    FakeRequest(
                        _principal(admin),
                        {"is_active": False, "reason": "temporary API disable"},
                    ),
                )
            )
            assert active_response["is_active"] is False
            profile_response = asyncio.run(
                admin_api.update_user_profile(
                    api_user_id,
                    FakeRequest(_principal(admin), {"display_name": "API Renamed"}),
                )
            )
            assert profile_response["display_name"] == "API Renamed"
            delete_response = asyncio.run(
                admin_api.delete_user(
                    api_user_id,
                    FakeRequest(
                        _principal(admin),
                        {
                            "confirm_username": "api-user",
                            "reason": "temporary API offboarding",
                        },
                    ),
                )
            )
            assert delete_response["soft_deleted"] is True
            self_token = auth.create_token(user_a["id"])
            self_password_response = asyncio.run(
                admin_api.change_my_password(
                    FakeRequest(
                        _principal(
                            {
                                **user_a,
                                "auth_version": _auth_version(ready_db, user_a["id"]),
                            }
                        ),
                        {
                            "old_password": "replacement-password-a",
                            "new_password": "self-service-password",
                        },
                    )
                )
            )
            assert self_password_response["operation_id"]
            assert auth.verify_token(self_token) is None

            # Missing audit maps to stable 503 without leaking internals.
            edb.DB_PATH = str(missing_audit_db)
            unavailable = asyncio.run(
                _assert_http_status(
                    admin_api.reset_password(
                        missing_user["id"],
                        FakeRequest(
                            _principal(
                                {
                                    "id": missing_admin["id"],
                                    "username": missing_admin["username"],
                                    "role": ROLE_ADMIN,
                                }
                            ),
                            {"password": "missing-audit-password", "reason": "temporary"},
                        ),
                    ),
                    503,
                )
            )
            unavailable_text = json.dumps(unavailable.detail).lower()
            assert "sql" not in unavailable_text
            assert "password_hash" not in unavailable_text
            assert str(missing_audit_db).lower() not in unavailable_text
        finally:
            edb.DB_PATH = original_db_path


if __name__ == "__main__":
    _run_checks()
    print("SEC-1C0 transitional super-admin protection checks passed")
