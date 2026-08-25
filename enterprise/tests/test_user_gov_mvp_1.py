"""Focused contracts for USER-GOV-MVP-1 fixed three-role governance."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from enterprise import admin_api
from enterprise import auth
from enterprise import db as edb
from enterprise import security_user_governance as governance
from enterprise.migrations.sec_1f0_security_audit import apply_security_audit_migration
from enterprise.roles import ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_USER


SUPER_PASSWORD = "temporary-super-password"


class FakeRequest:
    def __init__(self, user: dict, body: dict | None = None):
        self.state = SimpleNamespace(user=user)
        self._body = body or {}
        self.query_params = {}

    async def json(self):
        return self._body


def _insert_user(path: Path, *, username: str, role: str, password: str) -> dict:
    user_id = uuid.uuid4().hex
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO users (
                id, username, password_hash, display_name, is_admin,
                role, auth_version, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?)
            """,
            (
                user_id,
                username,
                edb._hash_password(password),
                username,
                0 if role == ROLE_USER else 1,
                role,
                int(time.time() * 1000),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": user_id, "username": username, "role": role, "password": password}


def _principal(user: dict) -> dict:
    current = edb.get_user_by_id(user["id"])
    assert current is not None
    return {
        "user_id": current["id"],
        "username": current["username"],
        "role": current["role"],
        "is_admin": current["is_admin"],
        "auth_version": current["auth_version"],
    }


def _audit_events(path: Path, action: str) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM security_audit_events WHERE action = ? ORDER BY id",
                (action,),
            ).fetchall()
        ]
    finally:
        conn.close()


@pytest.fixture
def governance_db(tmp_path: Path, monkeypatch):
    path = tmp_path / "user-governance.db"
    monkeypatch.setattr(edb, "DB_PATH", str(path))
    edb.init_db()
    initial_admin = _insert_user(
        path,
        username="audit-foundation-admin",
        role=ROLE_ADMIN,
        password="temporary-audit-password",
    )
    apply_security_audit_migration(
        path,
        actor_user_id=initial_admin["id"],
        actor_label="temporary-user-gov-test",
        operation_id=f"audit-{uuid.uuid4().hex}",
        reason="temporary USER-GOV-MVP-1 fixture",
    )
    super_admin = _insert_user(
        path,
        username="fixed-super",
        role=ROLE_SUPER_ADMIN,
        password=SUPER_PASSWORD,
    )
    admin = _insert_user(
        path,
        username="fixed-admin",
        role=ROLE_ADMIN,
        password="temporary-admin-password",
    )
    user = _insert_user(
        path,
        username="fixed-user",
        role=ROLE_USER,
        password="temporary-user-password",
    )
    return path, super_admin, admin, user


def test_super_admin_creates_admin_with_atomic_role_audit(governance_db):
    path, super_admin, _admin, _user = governance_db
    result = governance.create_admin_user(
        actor_user_id=super_admin["id"],
        expected_actor_auth_version=1,
        username="created-admin",
        password="created-admin-password",
        display_name="Created Admin",
        current_password=SUPER_PASSWORD,
        reason="delegate ordinary business administration",
    )

    created = edb.get_user_by_id(result["user"]["id"])
    assert created is not None
    assert created["role"] == ROLE_ADMIN
    assert created["is_admin"] is True
    assert created["auth_version"] == 1
    event = _audit_events(path, "security.role.change")[-1]
    assert event["result"] == "success"
    assert event["actor_user_id"] == super_admin["id"]
    assert event["target_id"] == created["id"]
    assert event["reason"] == "delegate ordinary business administration"
    context = json.loads(event["context_json"])
    assert context["previous_role"] is None
    assert context["new_role"] == ROLE_ADMIN
    assert context["account_created"] is True
    assert SUPER_PASSWORD not in event["context_json"]


def test_admin_cannot_create_admin_or_change_roles(governance_db):
    _path, _super_admin, admin, user = governance_db
    with pytest.raises(governance.UserGovernancePolicyDenied):
        governance.create_admin_user(
            actor_user_id=admin["id"],
            expected_actor_auth_version=1,
            username="forbidden-admin",
            password="forbidden-admin-password",
            display_name="Forbidden Admin",
            current_password=admin["password"],
            reason="must be denied",
        )
    assert edb.get_user_by_username("forbidden-admin") is None

    with pytest.raises(governance.UserGovernancePolicyDenied):
        governance.change_user_role(
            actor_user_id=admin["id"],
            expected_actor_auth_version=1,
            target_user_id=user["id"],
            expected_target_auth_version=1,
            expected_target_role=ROLE_USER,
            requested_role=ROLE_ADMIN,
            current_password=admin["password"],
            reason="must be denied",
        )
    assert edb.get_user_by_id(user["id"])["role"] == ROLE_USER


def test_role_change_revokes_sessions_and_rejects_stale_target(governance_db):
    _path, super_admin, _admin, user = governance_db
    old_token = auth.create_token(user["id"])
    assert auth.verify_token(old_token)["role"] == ROLE_USER

    promoted = governance.change_user_role(
        actor_user_id=super_admin["id"],
        expected_actor_auth_version=1,
        target_user_id=user["id"],
        expected_target_auth_version=1,
        expected_target_role=ROLE_USER,
        requested_role=ROLE_ADMIN,
        current_password=SUPER_PASSWORD,
        reason="approved administrator promotion",
    )
    assert promoted["role"] == ROLE_ADMIN
    assert promoted["auth_version"] == 2
    assert auth.verify_token(old_token) is None

    with pytest.raises(governance.UserGovernanceConflict):
        governance.change_user_role(
            actor_user_id=super_admin["id"],
            expected_actor_auth_version=1,
            target_user_id=user["id"],
            expected_target_auth_version=1,
            expected_target_role=ROLE_USER,
            requested_role=ROLE_USER,
            current_password=SUPER_PASSWORD,
            reason="stale concurrent request",
        )
    assert edb.get_user_by_id(user["id"])["role"] == ROLE_ADMIN

    demoted = governance.change_user_role(
        actor_user_id=super_admin["id"],
        expected_actor_auth_version=1,
        target_user_id=user["id"],
        expected_target_auth_version=2,
        expected_target_role=ROLE_ADMIN,
        requested_role=ROLE_USER,
        current_password=SUPER_PASSWORD,
        reason="administrator duties ended",
    )
    assert demoted["role"] == ROLE_USER
    assert demoted["auth_version"] == 3


def test_super_admin_accounts_are_not_governed_online(governance_db):
    _path, super_admin, _admin, _user = governance_db
    with pytest.raises(governance.UserGovernancePolicyDenied):
        governance.change_user_role(
            actor_user_id=super_admin["id"],
            expected_actor_auth_version=1,
            target_user_id=super_admin["id"],
            expected_target_auth_version=1,
            expected_target_role=ROLE_SUPER_ADMIN,
            requested_role=ROLE_ADMIN,
            current_password=SUPER_PASSWORD,
            reason="self demotion must be denied",
        )
    assert edb.get_user_by_id(super_admin["id"])["role"] == ROLE_SUPER_ADMIN


def test_wrong_current_password_is_denied_and_redacted(governance_db):
    path, super_admin, _admin, user = governance_db
    attempted_password = "must-not-appear-in-audit"
    with pytest.raises(governance.UserGovernancePasswordInvalid):
        governance.change_user_role(
            actor_user_id=super_admin["id"],
            expected_actor_auth_version=1,
            target_user_id=user["id"],
            expected_target_auth_version=1,
            expected_target_role=ROLE_USER,
            requested_role=ROLE_ADMIN,
            current_password=attempted_password,
            reason="denied password confirmation",
        )
    denied = _audit_events(path, "security.authorization.denied")[-1]
    assert json.loads(denied["context_json"])["policy_code"] == "current_password_invalid"
    assert attempted_password not in json.dumps(denied)
    assert edb.get_user_by_id(user["id"])["role"] == ROLE_USER


def test_role_change_rolls_back_when_mandatory_audit_fails(governance_db, monkeypatch):
    _path, super_admin, _admin, user = governance_db

    def fail_audit(**_kwargs):
        raise sqlite3.OperationalError("temporary audit failure")

    monkeypatch.setattr(governance, "append_security_audit_event", fail_audit)
    with pytest.raises(governance.UserGovernanceInternalError):
        governance.change_user_role(
            actor_user_id=super_admin["id"],
            expected_actor_auth_version=1,
            target_user_id=user["id"],
            expected_target_auth_version=1,
            expected_target_role=ROLE_USER,
            requested_role=ROLE_ADMIN,
            current_password=SUPER_PASSWORD,
            reason="audit and role must commit together",
        )
    unchanged = edb.get_user_by_id(user["id"])
    assert unchanged["role"] == ROLE_USER
    assert unchanged["auth_version"] == 1


def test_admin_api_uses_fixed_role_contract(governance_db):
    _path, super_admin, admin, user = governance_db
    with pytest.raises(HTTPException) as denied:
        asyncio.run(
            admin_api.create_user(
                FakeRequest(
                    _principal(admin),
                    {
                        "username": "api-forbidden-admin",
                        "password": "api-forbidden-password",
                        "role": ROLE_ADMIN,
                        "current_password": admin["password"],
                        "reason": "must be denied",
                    },
                )
            )
        )
    assert denied.value.status_code == 403

    response = asyncio.run(
        admin_api.create_user(
            FakeRequest(
                _principal(super_admin),
                {
                    "username": "api-created-admin",
                    "display_name": "API Created Admin",
                    "password": "api-created-password",
                    "role": ROLE_ADMIN,
                    "current_password": SUPER_PASSWORD,
                    "reason": "approved API administrator creation",
                },
            )
        )
    )
    payload = json.loads(response.body)
    assert payload["user"]["role"] == ROLE_ADMIN

    changed = asyncio.run(
        admin_api.update_user_role(
            user["id"],
            FakeRequest(
                _principal(super_admin),
                {
                    "role": ROLE_ADMIN,
                    "expected_target_role": ROLE_USER,
                    "expected_target_auth_version": 1,
                    "current_password": SUPER_PASSWORD,
                    "reason": "approved API role change",
                },
            ),
        )
    )
    assert changed["role"] == ROLE_ADMIN
    assert changed["auth_version"] == 2

    me = asyncio.run(admin_api.get_me(FakeRequest(_principal(super_admin))))
    assert me["role"] == ROLE_SUPER_ADMIN
    assert me["is_admin"] is True


def test_historical_system_update_override_is_inert_hidden_and_preserved(governance_db):
    _path, super_admin, admin, _user = governance_db
    super_principal = _principal(super_admin)
    edb.set_feature_flag("system_update", True, super_admin["id"])
    edb.set_user_feature_override(admin["id"], "system_update", "allow", super_admin["id"])
    edb.set_user_feature_override(admin["id"], "workflow_settings_access", "deny", super_admin["id"])

    effective = edb.get_effective_feature_value(edb.get_user_by_id(admin["id"]), "system_update")
    assert effective["allowed"] is False
    assert effective["mode"] == "ignored"
    assert effective["override_ignored"] is True

    readback = asyncio.run(
        admin_api.list_user_feature_overrides(admin["id"], FakeRequest(super_principal))
    )
    assert "system_update" not in {item["feature_key"] for item in readback["features"]}

    for operation in (
        admin_api.update_user_feature_override(
            admin["id"],
            "system_update",
            FakeRequest(super_principal, {"mode": "deny"}),
        ),
        admin_api.delete_user_feature_override(
            admin["id"],
            "system_update",
            FakeRequest(super_principal),
        ),
    ):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(operation)
        assert denied.value.status_code == 403
        assert denied.value.detail["code"] == "SYSTEM_UPDATE_OVERRIDE_UNSUPPORTED"

    purged = asyncio.run(
        admin_api.purge_user_feature_overrides(
            admin["id"],
            FakeRequest(
                super_principal,
                {"confirm_username": admin["username"], "reason": "clear ordinary overrides"},
            ),
        )
    )
    assert purged["cleared_count"] == 1
    assert edb.get_user_feature_override(admin["id"], "workflow_settings_access") is None
    assert edb.get_user_feature_override(admin["id"], "system_update")["mode"] == "allow"
