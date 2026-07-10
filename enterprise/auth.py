"""
企业层认证 - JWT Token 生成与验证
"""
import time
import uuid
from typing import Optional

import jwt

from enterprise.config import JWT_SECRET, JWT_EXPIRE_HOURS
from enterprise.db import get_user_by_username, get_user_by_id, verify_password, update_last_login
from enterprise.migrations.sec_1b1_role_auth import ROLE_AUTH_READY
from enterprise.roles import LEGACY_AUTH_VERSION, normalize_auth_version


def create_token(user_id: str) -> str:
    """Generate a JWT from the current active database user."""
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("active user not found")
    now = int(time.time())
    payload = {
        "user_id": user_id,
        "auth_version": user["auth_version"],
        "jti": uuid.uuid4().hex,
        "exp": now + JWT_EXPIRE_HOURS * 3600,
        "iat": now,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_token(token: str) -> Optional[dict]:
    """Validate a JWT and return a principal built from current DB state."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            return None
        user = get_user_by_id(user_id)
        if not user:
            return None
        schema_ready = user.get("_role_auth_schema_state") == ROLE_AUTH_READY
        if schema_ready:
            if "auth_version" not in payload:
                return None
            token_auth_version = normalize_auth_version(payload.get("auth_version"))
            if token_auth_version != user["auth_version"]:
                return None
        elif "auth_version" in payload:
            token_auth_version = normalize_auth_version(payload.get("auth_version"))
            if token_auth_version != LEGACY_AUTH_VERSION:
                return None

        principal = {
            "user_id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "auth_version": user["auth_version"],
            "is_admin": user["is_admin"],
        }
        jti = payload.get("jti")
        if isinstance(jti, str) and jti:
            principal["jti"] = jti
        return principal
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


def authenticate(username: str, password: str) -> Optional[dict]:
    """用户名密码验证，成功返回用户数据，失败返回 None"""
    user = get_user_by_username(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    update_last_login(user["id"])
    return user
