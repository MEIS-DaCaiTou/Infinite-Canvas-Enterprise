"""
企业层认证 - JWT Token 生成与验证
"""
import time
from typing import Optional

import jwt

from enterprise.config import JWT_SECRET, JWT_EXPIRE_HOURS
from enterprise.db import get_user_by_username, get_user_by_id, verify_password, update_last_login


def create_token(user_id: str, username: str, is_admin: bool) -> str:
    """生成 JWT Token"""
    payload = {
        "user_id": user_id,
        "username": username,
        "is_admin": is_admin,
        "exp": int(time.time()) + JWT_EXPIRE_HOURS * 3600,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_token(token: str) -> Optional[dict]:
    """验证 JWT Token，返回 payload 或 None"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        # 验证用户仍然存在且激活
        user = get_user_by_id(payload["user_id"])
        if not user:
            return None
        return payload
    except Exception:
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
