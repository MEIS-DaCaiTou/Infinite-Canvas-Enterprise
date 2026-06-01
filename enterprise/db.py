"""
企业层数据库 - SQLite
存储用户账号、画布归属映射、对话归属映射
完全独立于上游 main.py 的数据存储
"""
import sqlite3
import hashlib
import secrets
import time
import uuid
import os
from typing import Optional

from enterprise.config import DB_PATH, ADMIN_USERNAME, ADMIN_PASSWORD


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """初始化数据库表结构，并创建默认管理员账号"""
    conn = get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          TEXT PRIMARY KEY,
                username    TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                is_admin    INTEGER DEFAULT 0,
                is_active   INTEGER DEFAULT 1,
                created_at  INTEGER NOT NULL,
                last_login  INTEGER
            );

            CREATE TABLE IF NOT EXISTS user_canvas_map (
                user_id     TEXT NOT NULL,
                canvas_id   TEXT NOT NULL,
                created_at  INTEGER NOT NULL,
                PRIMARY KEY (canvas_id)
            );

            CREATE TABLE IF NOT EXISTS user_conversation_map (
                user_id         TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                created_at      INTEGER NOT NULL,
                PRIMARY KEY (conversation_id)
            );

            CREATE TABLE IF NOT EXISTS usage_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                action      TEXT NOT NULL,
                detail      TEXT,
                ts          INTEGER NOT NULL
            );
        """)
        conn.commit()

        # 如果管理员不存在则创建
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
        ).fetchone()
        if not existing:
            uid = uuid.uuid4().hex
            ph = _hash_password(ADMIN_PASSWORD)
            conn.execute(
                "INSERT INTO users (id, username, password_hash, display_name, is_admin, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (uid, ADMIN_USERNAME, ph, "管理员", int(time.time() * 1000))
            )
            conn.commit()
            print(f"[企业版] 已创建管理员账号: {ADMIN_USERNAME}")
    finally:
        conn.close()


# ── 密码工具 ──────────────────────────────────────────────

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000
    ).hex()
    return f"{salt}:{hashed}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, hashed = password_hash.split(":", 1)
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000
        ).hex()
        return secrets.compare_digest(expected, hashed)
    except Exception:
        return False


# ── 用户 CRUD ─────────────────────────────────────────────

def get_user_by_username(username: str) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users() -> list:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, username, display_name, is_admin, is_active, created_at, last_login "
            "FROM users ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_user(username: str, password: str, display_name: str = "", is_admin: bool = False) -> dict:
    conn = get_db()
    try:
        uid = uuid.uuid4().hex
        ph = _hash_password(password)
        conn.execute(
            "INSERT INTO users (id, username, password_hash, display_name, is_admin, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uid, username, ph, display_name or username, 1 if is_admin else 0, int(time.time() * 1000))
        )
        conn.commit()
        return {"id": uid, "username": username}
    finally:
        conn.close()


def update_user_password(user_id: str, new_password: str) -> None:
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash_password(new_password), user_id)
        )
        conn.commit()
    finally:
        conn.close()


def update_user_role(user_id: str, is_admin: bool) -> None:
    """修改用户管理员权限"""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (1 if is_admin else 0, user_id)
        )
        conn.commit()
    finally:
        conn.close()


def delete_user(user_id: str) -> None:
    """软删除（禁用）用户"""
    conn = get_db()
    try:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def update_last_login(user_id: str) -> None:
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (int(time.time() * 1000), user_id)
        )
        conn.commit()
    finally:
        conn.close()


# ── 画布归属映射 ──────────────────────────────────────────

def record_canvas_owner(user_id: str, canvas_id: str) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO user_canvas_map (user_id, canvas_id, created_at) VALUES (?, ?, ?)",
            (user_id, canvas_id, int(time.time() * 1000))
        )
        conn.commit()
    finally:
        conn.close()


def get_canvas_owner(canvas_id: str) -> Optional[str]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id FROM user_canvas_map WHERE canvas_id = ?", (canvas_id,)
        ).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


def get_user_canvas_ids(user_id: str) -> set:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT canvas_id FROM user_canvas_map WHERE user_id = ?", (user_id,)
        ).fetchall()
        return {r["canvas_id"] for r in rows}
    finally:
        conn.close()


def remove_canvas_mapping(canvas_id: str) -> None:
    conn = get_db()
    try:
        conn.execute("DELETE FROM user_canvas_map WHERE canvas_id = ?", (canvas_id,))
        conn.commit()
    finally:
        conn.close()


def get_all_canvas_owner_map() -> dict:
    """返回 {canvas_id: user_id} 的全量映射（供管理员使用）"""
    conn = get_db()
    try:
        rows = conn.execute("SELECT canvas_id, user_id FROM user_canvas_map").fetchall()
        return {r["canvas_id"]: r["user_id"] for r in rows}
    finally:
        conn.close()


def assign_canvas_owner(canvas_id: str, user_id: str) -> None:
    """管理员手动分配画布归属（覆盖旧归属）"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM user_canvas_map WHERE canvas_id = ?", (canvas_id,))
        conn.execute(
            "INSERT INTO user_canvas_map (user_id, canvas_id, created_at) VALUES (?, ?, ?)",
            (user_id, canvas_id, int(time.time() * 1000))
        )
        conn.commit()
    finally:
        conn.close()


# ── 对话归属映射 ──────────────────────────────────────────

def record_conversation_owner(user_id: str, conversation_id: str) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO user_conversation_map (user_id, conversation_id, created_at) VALUES (?, ?, ?)",
            (user_id, conversation_id, int(time.time() * 1000))
        )
        conn.commit()
    finally:
        conn.close()


def get_user_conversation_ids(user_id: str) -> set:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT conversation_id FROM user_conversation_map WHERE user_id = ?", (user_id,)
        ).fetchall()
        return {r["conversation_id"] for r in rows}
    finally:
        conn.close()


# ── 使用日志 ──────────────────────────────────────────────

def log_action(user_id: str, action: str, detail: str = "") -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO usage_logs (user_id, action, detail, ts) VALUES (?, ?, ?, ?)",
            (user_id, action, detail, int(time.time() * 1000))
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def get_logs(limit: int = 100, offset: int = 0, user_id: str = None, action: str = None) -> list:
    """查询审计日志，支持按用户和操作类型过滤"""
    conn = get_db()
    try:
        conditions = []
        params = []
        if user_id:
            conditions.append("l.user_id = ?")
            params.append(user_id)
        if action:
            conditions.append("l.action = ?")
            params.append(action)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = conn.execute(
            f"""
            SELECT l.id, l.user_id, u.username, u.display_name,
                   l.action, l.detail, l.ts
            FROM usage_logs l
            LEFT JOIN users u ON u.id = l.user_id
            {where}
            ORDER BY l.ts DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset]
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM usage_logs l {where}", params
        ).fetchone()[0]
        return [dict(r) for r in rows], total
    finally:
        conn.close()

