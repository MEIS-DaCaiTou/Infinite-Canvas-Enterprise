"""SEC-1C0 pre-bootstrap user-governance protections."""

import sqlite3
import time
import uuid
from typing import Any

from enterprise import db as edb
from enterprise.migrations.sec_1b1_role_auth import (
    ROLE_AUTH_READY,
    SCHEMA_LEGACY,
    classify_role_auth_schema,
)
from enterprise.roles import ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_USER, normalize_role
from enterprise.security_audit import (
    SECURITY_AUDIT_READY,
    SecurityAuditError,
    append_security_audit_event,
    inspect_security_audit_connection,
)


MAX_REASON_LENGTH = 2048
LAST_SUPER_ADMIN_REDUCTION_OPERATIONS = frozenset(
    {"disable", "soft_delete", "role_change"}
)


class UserGovernanceError(RuntimeError):
    status_code = 500
    code = "USER_GOVERNANCE_ERROR"
    public_message = "User governance operation failed"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.public_message)


class UserGovernanceValidationError(UserGovernanceError):
    status_code = 400
    code = "INVALID_GOVERNANCE_REQUEST"
    public_message = "Invalid user governance request"


class UserGovernancePolicyDenied(UserGovernanceError):
    status_code = 403
    code = "TRANSITIONAL_POLICY_DENIED"
    public_message = "User governance policy denied this operation"


class UserGovernanceNotFound(UserGovernanceError):
    status_code = 404
    code = "USER_NOT_FOUND"
    public_message = "User not found"


class UserGovernanceConflict(UserGovernanceError):
    status_code = 409
    code = "USER_GOVERNANCE_CONFLICT"
    public_message = "User governance state conflict"


class UserGovernanceIntegrityError(UserGovernanceError):
    status_code = 409
    code = "USER_GOVERNANCE_INTEGRITY_FAILED"
    public_message = "User governance integrity verification failed"


class UserGovernanceStaleSession(UserGovernanceError):
    status_code = 401
    code = "STALE_AUTHENTICATION"
    public_message = "Authentication is no longer current"


class UserGovernanceUnavailable(UserGovernanceError):
    status_code = 503
    code = "MANDATORY_AUDIT_UNAVAILABLE"
    public_message = "Mandatory security controls are unavailable"


class UserGovernanceInternalError(UserGovernanceError):
    status_code = 500
    code = "USER_GOVERNANCE_INTERNAL_ERROR"
    public_message = "User governance operation failed"


def _main_user_columns(conn: sqlite3.Connection) -> tuple[str, ...]:
    exists = conn.execute(
        "SELECT 1 FROM main.sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    if not exists:
        return ()
    return tuple(
        str(row[1])
        for row in conn.execute('PRAGMA main.table_info("users")').fetchall()
    )


def _schema_state(conn: sqlite3.Connection) -> str:
    columns = _main_user_columns(conn)
    if "is_admin" not in columns:
        raise UserGovernanceUnavailable()
    state = classify_role_auth_schema(columns)
    if state not in {SCHEMA_LEGACY, ROLE_AUTH_READY}:
        raise UserGovernanceUnavailable()
    return state


def get_role_auth_schema_state() -> str:
    conn = edb.get_db()
    try:
        return _schema_state(conn)
    except sqlite3.Error as exc:
        raise UserGovernanceUnavailable() from exc
    finally:
        conn.close()


def _require_ready_schema(conn: sqlite3.Connection) -> None:
    if _schema_state(conn) != ROLE_AUTH_READY:
        raise UserGovernanceUnavailable("ROLE_AUTH_READY schema is required")


def _require_audit_ready(conn: sqlite3.Connection) -> None:
    try:
        inspection = inspect_security_audit_connection(conn)
    except sqlite3.Error as exc:
        raise UserGovernanceUnavailable() from exc
    if inspection["current_state"] != SECURITY_AUDIT_READY:
        raise UserGovernanceUnavailable()


def _normalize_ready_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        return edb.normalize_user_record(row, ROLE_AUTH_READY)
    except (TypeError, ValueError) as exc:
        raise UserGovernanceUnavailable("Current role state is invalid") from exc


def _find_user(conn: sqlite3.Connection, user_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM main.users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return _normalize_ready_user(row)


def _load_user(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    user = _find_user(conn, user_id)
    if user is None:
        raise UserGovernanceNotFound()
    return user


def _load_actor(conn: sqlite3.Connection, actor_user_id: str) -> dict[str, Any]:
    try:
        actor = _load_user(conn, actor_user_id)
    except UserGovernanceNotFound as exc:
        raise UserGovernancePolicyDenied("Current actor is not authorized") from exc
    if not actor["is_active"]:
        raise UserGovernancePolicyDenied("Current actor is not authorized")
    return actor


def _required_actor_auth_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UserGovernanceStaleSession()
    return value


def _required_reason(value: object) -> str:
    if not isinstance(value, str) or not value or value.isspace():
        raise UserGovernanceValidationError("A non-empty reason is required")
    if len(value) > MAX_REASON_LENGTH:
        raise UserGovernanceValidationError("Reason exceeds its length limit")
    return value


def _safe_public_user(user: dict[str, Any]) -> dict[str, Any]:
    result = dict(user)
    result.pop("password_hash", None)
    result.pop("_role_auth_schema_state", None)
    return result


def _authenticate_actor(
    conn: sqlite3.Connection,
    *,
    actor_user_id: str,
    expected_actor_auth_version: object,
) -> tuple[dict[str, Any], bool]:
    expected_version = _required_actor_auth_version(expected_actor_auth_version)
    actor = _load_actor(conn, actor_user_id)
    return actor, actor["auth_version"] == expected_version


def _require_target(target: dict[str, Any] | None) -> dict[str, Any]:
    if target is None:
        raise UserGovernanceNotFound()
    return target


def _policy_allows_target(
    actor: dict[str, Any],
    target: dict[str, Any],
    *,
    operation: str,
) -> bool:
    if actor["role"] == ROLE_ADMIN:
        return target["role"] == ROLE_USER and actor["id"] != target["id"]
    if actor["role"] != ROLE_SUPER_ADMIN:
        return False
    if target["role"] in {ROLE_USER, ROLE_ADMIN}:
        return actor["id"] != target["id"]
    return operation == "profile_update" and actor["id"] == target["id"]


def _denied_risk_level(target_role: str | None, *, super_admin_request: bool = False) -> str:
    return "L3" if target_role == ROLE_SUPER_ADMIN or super_admin_request else "L2"


def _audit_context(
    *,
    policy_code: str,
    requested_operation: str,
    actor_role: str,
    target_role: str | None,
    requested_active_state: bool | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "policy_code": policy_code,
        "requested_operation": requested_operation,
        "actor_role": actor_role,
        "target_role": target_role,
        "role_auth_schema_state": ROLE_AUTH_READY,
    }
    if requested_active_state is not None:
        context["requested_active_state"] = requested_active_state
    return context


def _append_audit(
    conn: sqlite3.Connection,
    *,
    action: str,
    risk_level: str,
    result: str,
    actor: dict[str, Any],
    operation_id: str,
    target_id: str,
    reason: str | None,
    context: dict[str, Any],
) -> None:
    append_security_audit_event(
        action=action,
        risk_level=risk_level,
        result=result,
        actor_type="user",
        operation_id=operation_id,
        actor_user_id=actor["id"],
        actor_role=actor["role"],
        target_type="user",
        target_id=target_id,
        reason=reason,
        context=context,
        connection=conn,
    )


def _require_affected_row(cursor: sqlite3.Cursor) -> None:
    if cursor.rowcount != 1:
        raise UserGovernanceIntegrityError()


def _verify_user_fields(
    conn: sqlite3.Connection,
    user_id: str,
    expected_fields: dict[str, Any],
) -> dict[str, Any]:
    try:
        actual = _load_user(conn, user_id)
    except UserGovernanceNotFound as exc:
        raise UserGovernanceIntegrityError() from exc
    for field, expected_value in expected_fields.items():
        if actual.get(field) != expected_value:
            raise UserGovernanceIntegrityError()
    return actual


def _verify_actor_security_state(
    conn: sqlite3.Connection,
    actor: dict[str, Any],
    *,
    expected_auth_version: int | None = None,
) -> dict[str, Any]:
    return _verify_user_fields(
        conn,
        actor["id"],
        {
            "id": actor["id"],
            "role": actor["role"],
            "is_active": actor["is_active"],
            "auth_version": (
                actor["auth_version"]
                if expected_auth_version is None
                else expected_auth_version
            ),
        },
    )


def _commit_denied(
    conn: sqlite3.Connection,
    *,
    actor: dict[str, Any],
    target_id: str,
    target_role: str | None,
    operation: str,
    policy_code: str,
    requested_active_state: bool | None = None,
    super_admin_request: bool = False,
    error_type: type[UserGovernanceError] = UserGovernancePolicyDenied,
) -> UserGovernanceError:
    _require_audit_ready(conn)
    risk_level = _denied_risk_level(
        target_role,
        super_admin_request=super_admin_request,
    )
    _append_audit(
        conn,
        action="security.authorization.denied",
        risk_level=risk_level,
        result="denied",
        actor=actor,
        operation_id=uuid.uuid4().hex,
        target_id=target_id,
        reason="transitional_super_admin_protection" if risk_level == "L3" else None,
        context=_audit_context(
            policy_code=policy_code,
            requested_operation=operation,
            actor_role=actor["role"],
            target_role=target_role,
            requested_active_state=requested_active_state,
        ),
    )
    conn.commit()
    return error_type()


def _authorize_actor(
    conn: sqlite3.Connection,
    *,
    actor: dict[str, Any],
    auth_version_matches: bool,
    target_id: str,
    target_role: str | None,
    operation: str,
    super_admin_request: bool = False,
) -> dict[str, Any]:
    if not auth_version_matches:
        raise _commit_denied(
            conn,
            actor=actor,
            target_id=target_id,
            target_role=target_role,
            operation=operation,
            policy_code="stale_actor_auth_version",
            super_admin_request=super_admin_request,
            error_type=UserGovernanceStaleSession,
        )
    if actor["role"] not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        raise _commit_denied(
            conn,
            actor=actor,
            target_id=target_id,
            target_role=target_role,
            operation=operation,
            policy_code="actor_role_not_allowed",
            super_admin_request=super_admin_request,
        )
    return actor


def _rollback(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.rollback()


def _translate_transaction_error(conn: sqlite3.Connection, exc: Exception) -> None:
    _rollback(conn)
    if isinstance(exc, UserGovernanceError):
        raise exc
    if isinstance(exc, SecurityAuditError):
        raise UserGovernanceUnavailable() from exc
    if isinstance(exc, sqlite3.IntegrityError):
        raise UserGovernanceConflict() from exc
    if isinstance(exc, sqlite3.Error):
        raise UserGovernanceInternalError() from exc
    raise exc


def count_active_super_admins(conn: sqlite3.Connection) -> int:
    if not conn.in_transaction:
        raise UserGovernanceValidationError("An active write transaction is required")
    _require_ready_schema(conn)
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM main.users
            WHERE role = ? AND is_active = 1
            """,
            (ROLE_SUPER_ADMIN,),
        ).fetchone()[0]
    )


def ensure_active_super_admin_remains(
    conn: sqlite3.Connection,
    target_user_id: str,
    operation: str,
) -> None:
    if operation not in LAST_SUPER_ADMIN_REDUCTION_OPERATIONS:
        raise UserGovernanceValidationError("Unsupported super-admin reduction operation")
    if not conn.in_transaction:
        raise UserGovernanceValidationError("An active write transaction is required")
    _require_ready_schema(conn)
    row = conn.execute(
        "SELECT role, is_active FROM main.users WHERE id = ?",
        (target_user_id,),
    ).fetchone()
    if not row:
        raise UserGovernanceNotFound()
    try:
        role = normalize_role(row[0])
    except ValueError as exc:
        raise UserGovernanceUnavailable("Current role state is invalid") from exc
    if role == ROLE_SUPER_ADMIN and row[1] == 1 and count_active_super_admins(conn) <= 1:
        raise UserGovernanceConflict("Last active super administrator is protected")


def create_ordinary_user(
    *,
    actor_user_id: str,
    expected_actor_auth_version: object,
    username: str,
    password: str,
    display_name: str,
    requested_is_admin: object,
    role_field_present: bool,
    requested_role: object = None,
) -> dict[str, Any]:
    password_hash = edb._hash_password(password)
    candidate_user_id = uuid.uuid4().hex
    conn = edb.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _require_ready_schema(conn)
        requested_super_admin = requested_role == ROLE_SUPER_ADMIN
        actor, auth_version_matches = _authenticate_actor(
            conn,
            actor_user_id=actor_user_id,
            expected_actor_auth_version=expected_actor_auth_version,
        )
        actor = _authorize_actor(
            conn,
            actor=actor,
            auth_version_matches=auth_version_matches,
            target_id=candidate_user_id,
            target_role=None,
            operation="create_user",
            super_admin_request=requested_super_admin,
        )
        if requested_is_admin not in (False, None) or role_field_present:
            raise _commit_denied(
                conn,
                actor=actor,
                target_id=candidate_user_id,
                target_role=None,
                operation="create_user_with_role",
                policy_code="online_role_assignment_closed",
                super_admin_request=requested_super_admin,
            )
        expected_display_name = display_name or username
        cursor = conn.execute(
            """
            INSERT INTO main.users (
                id, username, password_hash, display_name,
                is_admin, role, auth_version, created_at
            ) VALUES (?, ?, ?, ?, 0, ?, 1, ?)
            """,
            (
                candidate_user_id,
                username,
                password_hash,
                expected_display_name,
                ROLE_USER,
                int(time.time() * 1000),
            ),
        )
        _require_affected_row(cursor)
        _verify_user_fields(
            conn,
            candidate_user_id,
            {
                "id": candidate_user_id,
                "username": username,
                "password_hash": password_hash,
                "display_name": expected_display_name,
                "is_admin": False,
                "role": ROLE_USER,
                "auth_version": 1,
                "is_active": True,
            },
        )
        _verify_actor_security_state(conn, actor)
        conn.commit()
        return {"id": candidate_user_id, "username": username}
    except Exception as exc:
        _translate_transaction_error(conn, exc)
    finally:
        conn.close()


def reset_user_password(
    *,
    actor_user_id: str,
    expected_actor_auth_version: object,
    target_user_id: str,
    new_password: str,
    reason: object,
) -> dict[str, Any]:
    validated_reason = _required_reason(reason)
    password_hash = edb._hash_password(new_password)
    conn = edb.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _require_ready_schema(conn)
        actor, auth_version_matches = _authenticate_actor(
            conn,
            actor_user_id=actor_user_id,
            expected_actor_auth_version=expected_actor_auth_version,
        )
        target = _find_user(conn, target_user_id)
        _require_audit_ready(conn)
        actor = _authorize_actor(
            conn,
            actor=actor,
            auth_version_matches=auth_version_matches,
            target_id=target_user_id,
            target_role=target["role"] if target else None,
            operation="password_reset",
        )
        target = _require_target(target)
        if not _policy_allows_target(actor, target, operation="password_reset"):
            raise _commit_denied(
                conn,
                actor=actor,
                target_id=target["id"],
                target_role=target["role"],
                operation="password_reset",
                policy_code="target_role_protected",
            )
        next_version = target["auth_version"] + 1
        cursor = conn.execute(
            """
            UPDATE main.users
            SET password_hash = ?, auth_version = ?
            WHERE id = ?
            """,
            (password_hash, next_version, target["id"]),
        )
        _require_affected_row(cursor)
        updated_target = _verify_user_fields(
            conn,
            target["id"],
            {
                "password_hash": password_hash,
                "auth_version": next_version,
                "role": target["role"],
                "is_admin": target["is_admin"],
                "is_active": target["is_active"],
                "role_updated_at": target.get("role_updated_at"),
                "role_updated_by": target.get("role_updated_by"),
            },
        )
        _verify_actor_security_state(conn, actor)
        operation_id = uuid.uuid4().hex
        _append_audit(
            conn,
            action="security.user.password_reset",
            risk_level="L2",
            result="success",
            actor=actor,
            operation_id=operation_id,
            target_id=target["id"],
            reason=validated_reason,
            context=_audit_context(
                policy_code="sec_1c0_password_reset",
                requested_operation="password_reset",
                actor_role=actor["role"],
                target_role=target["role"],
            ),
        )
        conn.commit()
        return {
            "user": _safe_public_user(updated_target),
            "operation_id": operation_id,
            "auth_version": next_version,
        }
    except Exception as exc:
        _translate_transaction_error(conn, exc)
    finally:
        conn.close()


def change_own_password(
    *,
    actor_user_id: str,
    expected_actor_auth_version: object,
    old_password: str,
    new_password: str,
) -> dict[str, Any]:
    password_hash = edb._hash_password(new_password)
    conn = edb.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _require_ready_schema(conn)
        _require_audit_ready(conn)
        actor = _load_user(conn, actor_user_id)
        expected_version = _required_actor_auth_version(expected_actor_auth_version)
        if not actor["is_active"]:
            raise UserGovernancePolicyDenied("Current password is incorrect")
        if actor["auth_version"] != expected_version:
            raise _commit_denied(
                conn,
                actor=actor,
                target_id=actor["id"],
                target_role=actor["role"],
                operation="self_password_change",
                policy_code="stale_actor_auth_version",
                error_type=UserGovernanceStaleSession,
            )
        if not edb.verify_password(old_password, actor["password_hash"]):
            raise UserGovernancePolicyDenied("Current password is incorrect")
        next_version = actor["auth_version"] + 1
        cursor = conn.execute(
            "UPDATE main.users SET password_hash = ?, auth_version = ? WHERE id = ?",
            (password_hash, next_version, actor["id"]),
        )
        _require_affected_row(cursor)
        _verify_user_fields(
            conn,
            actor["id"],
            {
                "password_hash": password_hash,
                "auth_version": next_version,
                "role": actor["role"],
                "is_admin": actor["is_admin"],
                "is_active": actor["is_active"],
                "role_updated_at": actor.get("role_updated_at"),
                "role_updated_by": actor.get("role_updated_by"),
            },
        )
        _verify_actor_security_state(
            conn,
            actor,
            expected_auth_version=next_version,
        )
        operation_id = uuid.uuid4().hex
        _append_audit(
            conn,
            action="security.user.password_reset",
            risk_level="L2",
            result="success",
            actor=actor,
            operation_id=operation_id,
            target_id=actor["id"],
            reason="self_password_change",
            context=_audit_context(
                policy_code="self_password_change",
                requested_operation="self_password_change",
                actor_role=actor["role"],
                target_role=actor["role"],
            ),
        )
        conn.commit()
        return {"operation_id": operation_id, "auth_version": next_version}
    except Exception as exc:
        _translate_transaction_error(conn, exc)
    finally:
        conn.close()


def set_user_active(
    *,
    actor_user_id: str,
    expected_actor_auth_version: object,
    target_user_id: str,
    is_active: bool,
    reason: object,
) -> dict[str, Any]:
    validated_reason = _required_reason(reason)
    conn = edb.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _require_ready_schema(conn)
        actor, auth_version_matches = _authenticate_actor(
            conn,
            actor_user_id=actor_user_id,
            expected_actor_auth_version=expected_actor_auth_version,
        )
        target = _find_user(conn, target_user_id)
        _require_audit_ready(conn)
        actor = _authorize_actor(
            conn,
            actor=actor,
            auth_version_matches=auth_version_matches,
            target_id=target_user_id,
            target_role=target["role"] if target else None,
            operation="active_change",
        )
        target = _require_target(target)
        if not _policy_allows_target(actor, target, operation="active_change"):
            raise _commit_denied(
                conn,
                actor=actor,
                target_id=target["id"],
                target_role=target["role"],
                operation="active_change",
                policy_code="target_role_protected",
                requested_active_state=is_active,
            )
        state_changed = target["is_active"] != is_active
        next_version = target["auth_version"] + (1 if state_changed else 0)
        if state_changed:
            cursor = conn.execute(
                "UPDATE main.users SET is_active = ?, auth_version = ? WHERE id = ?",
                (1 if is_active else 0, next_version, target["id"]),
            )
            _require_affected_row(cursor)
        updated_target = _verify_user_fields(
            conn,
            target["id"],
            {
                "is_active": is_active,
                "auth_version": next_version,
                "role": target["role"],
                "is_admin": target["is_admin"],
                "password_hash": target["password_hash"],
                "role_updated_at": target.get("role_updated_at"),
                "role_updated_by": target.get("role_updated_by"),
            },
        )
        _verify_actor_security_state(conn, actor)
        operation_id = uuid.uuid4().hex
        _append_audit(
            conn,
            action="security.user.active_change",
            risk_level="L2",
            result="success",
            actor=actor,
            operation_id=operation_id,
            target_id=target["id"],
            reason=validated_reason,
            context=_audit_context(
                policy_code="sec_1c0_active_change",
                requested_operation="active_change",
                actor_role=actor["role"],
                target_role=target["role"],
                requested_active_state=is_active,
            ),
        )
        conn.commit()
        return {
            "user": _safe_public_user(updated_target),
            "operation_id": operation_id,
            "is_active": is_active,
            "state_changed": state_changed,
            "auth_version": next_version,
        }
    except Exception as exc:
        _translate_transaction_error(conn, exc)
    finally:
        conn.close()


def soft_delete_user(
    *,
    actor_user_id: str,
    expected_actor_auth_version: object,
    target_user_id: str,
    confirm_username: object,
    reason: object,
) -> dict[str, Any]:
    validated_reason = _required_reason(reason)
    conn = edb.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _require_ready_schema(conn)
        actor, auth_version_matches = _authenticate_actor(
            conn,
            actor_user_id=actor_user_id,
            expected_actor_auth_version=expected_actor_auth_version,
        )
        target = _find_user(conn, target_user_id)
        _require_audit_ready(conn)
        actor = _authorize_actor(
            conn,
            actor=actor,
            auth_version_matches=auth_version_matches,
            target_id=target_user_id,
            target_role=target["role"] if target else None,
            operation="soft_delete",
        )
        target = _require_target(target)
        if not isinstance(confirm_username, str) or confirm_username != target["username"]:
            raise UserGovernanceValidationError("Confirmation username does not match")
        if not _policy_allows_target(actor, target, operation="soft_delete"):
            raise _commit_denied(
                conn,
                actor=actor,
                target_id=target["id"],
                target_role=target["role"],
                operation="soft_delete",
                policy_code="target_role_protected",
                requested_active_state=False,
            )
        state_changed = target["is_active"] is True
        next_version = target["auth_version"] + (1 if state_changed else 0)
        if state_changed:
            cursor = conn.execute(
                "UPDATE main.users SET is_active = 0, auth_version = ? WHERE id = ?",
                (next_version, target["id"]),
            )
            _require_affected_row(cursor)
        updated_target = _verify_user_fields(
            conn,
            target["id"],
            {
                "is_active": False,
                "auth_version": next_version,
                "role": target["role"],
                "is_admin": target["is_admin"],
                "password_hash": target["password_hash"],
                "role_updated_at": target.get("role_updated_at"),
                "role_updated_by": target.get("role_updated_by"),
            },
        )
        _verify_actor_security_state(conn, actor)
        operation_id = uuid.uuid4().hex
        _append_audit(
            conn,
            action="security.user.soft_delete",
            risk_level="L2",
            result="success",
            actor=actor,
            operation_id=operation_id,
            target_id=target_user_id,
            reason=validated_reason,
            context=_audit_context(
                policy_code="sec_1c0_soft_delete",
                requested_operation="soft_delete",
                actor_role=actor["role"],
                target_role=target["role"],
                requested_active_state=False,
            ),
        )
        conn.commit()
        return {
            "user": _safe_public_user(updated_target),
            "operation_id": operation_id,
            "state_changed": state_changed,
            "auth_version": next_version,
        }
    except Exception as exc:
        _translate_transaction_error(conn, exc)
    finally:
        conn.close()


def update_user_profile(
    *,
    actor_user_id: str,
    expected_actor_auth_version: object,
    target_user_id: str,
    display_name: str,
) -> dict[str, Any]:
    conn = edb.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _require_ready_schema(conn)
        actor, auth_version_matches = _authenticate_actor(
            conn,
            actor_user_id=actor_user_id,
            expected_actor_auth_version=expected_actor_auth_version,
        )
        target = _find_user(conn, target_user_id)
        actor = _authorize_actor(
            conn,
            actor=actor,
            auth_version_matches=auth_version_matches,
            target_id=target_user_id,
            target_role=target["role"] if target else None,
            operation="profile_update",
        )
        target = _require_target(target)
        if not _policy_allows_target(actor, target, operation="profile_update"):
            raise _commit_denied(
                conn,
                actor=actor,
                target_id=target["id"],
                target_role=target["role"],
                operation="profile_update",
                policy_code="target_role_protected",
            )
        next_display_name = display_name or target["username"]
        cursor = conn.execute(
            "UPDATE main.users SET display_name = ? WHERE id = ?",
            (next_display_name, target["id"]),
        )
        _require_affected_row(cursor)
        updated_target = _verify_user_fields(
            conn,
            target["id"],
            {
                "display_name": next_display_name,
                "role": target["role"],
                "is_admin": target["is_admin"],
                "auth_version": target["auth_version"],
                "is_active": target["is_active"],
                "password_hash": target["password_hash"],
                "role_updated_at": target.get("role_updated_at"),
                "role_updated_by": target.get("role_updated_by"),
            },
        )
        _verify_actor_security_state(conn, actor)
        conn.commit()
        return {"user": _safe_public_user(updated_target)}
    except Exception as exc:
        _translate_transaction_error(conn, exc)
    finally:
        conn.close()


def deny_online_role_change(
    *,
    actor_user_id: str,
    expected_actor_auth_version: object,
    target_user_id: str,
    role_field_present: bool,
    requested_role: object,
    is_admin_field_present: bool,
    requested_is_admin: object,
) -> None:
    conn = edb.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _require_ready_schema(conn)
        requested_super_admin = requested_role == ROLE_SUPER_ADMIN
        actor, auth_version_matches = _authenticate_actor(
            conn,
            actor_user_id=actor_user_id,
            expected_actor_auth_version=expected_actor_auth_version,
        )
        target = _find_user(conn, target_user_id)
        actor = _authorize_actor(
            conn,
            actor=actor,
            auth_version_matches=auth_version_matches,
            target_id=target_user_id,
            target_role=target["role"] if target else None,
            operation="role_change",
            super_admin_request=requested_super_admin,
        )
        _require_target(target)
        raise _commit_denied(
            conn,
            actor=actor,
            target_id=target["id"],
            target_role=target["role"],
            operation="role_change",
            policy_code="online_role_change_closed",
            super_admin_request=requested_super_admin,
        )
    except Exception as exc:
        _translate_transaction_error(conn, exc)
    finally:
        conn.close()


def check_session_revoke_policy(
    *,
    actor_user_id: str,
    expected_actor_auth_version: object,
    target_user_id: str,
) -> dict[str, str]:
    conn = edb.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _require_ready_schema(conn)
        actor, auth_version_matches = _authenticate_actor(
            conn,
            actor_user_id=actor_user_id,
            expected_actor_auth_version=expected_actor_auth_version,
        )
        target = _find_user(conn, target_user_id)
        _require_audit_ready(conn)
        actor = _authorize_actor(
            conn,
            actor=actor,
            auth_version_matches=auth_version_matches,
            target_id=target_user_id,
            target_role=target["role"] if target else None,
            operation="session_revoke_all",
        )
        target = _require_target(target)
        if not _policy_allows_target(actor, target, operation="session_revoke"):
            raise _commit_denied(
                conn,
                actor=actor,
                target_id=target["id"],
                target_role=target["role"],
                operation="session_revoke_all",
                policy_code="target_role_protected",
            )
        conn.rollback()
        return {"actor_role": actor["role"], "target_role": target["role"]}
    except Exception as exc:
        _translate_transaction_error(conn, exc)
    finally:
        conn.close()
