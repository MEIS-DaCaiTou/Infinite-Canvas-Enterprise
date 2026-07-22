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
import json
from typing import Optional

from enterprise.config import DB_PATH, ADMIN_USERNAME, ADMIN_PASSWORD, PATH_ROOTS, ROOT_DIR
from enterprise.migrations.sec_1b1_role_auth import (
    ROLE_AUTH_READY,
    SCHEMA_LEGACY,
    classify_role_auth_schema,
    get_user_columns,
)
from enterprise.roles import (
    LEGACY_AUTH_VERSION,
    ROLE_ADMIN,
    ROLE_USER,
    is_admin_role,
    normalize_auth_version,
    normalize_role,
    role_from_legacy_is_admin,
)


FEATURE_FLAG_DEFINITIONS = {
    "api_settings_access": {
        "default_enabled": False,
        "title": "API 设置访问",
        "description": "允许访问 API Provider、Key、Base URL、Provider 测试等高风险设置。",
    },
    "workflow_settings_access": {
        "default_enabled": False,
        "title": "工作流设置访问",
        "description": "允许访问工作流、ComfyUI 实例、RunningHub 工作流和相关全局配置。",
    },
    "runninghub_generation": {
        "default_enabled": True,
        "title": "RunningHub 生成功能",
        "description": "允许提交 RunningHub 生成任务。",
    },
    "video_generation": {
        "default_enabled": True,
        "title": "视频生成功能",
        "description": "允许提交视频生成任务。",
    },
    "image_tools_generation": {
        "default_enabled": True,
        "title": "图片工具生成功能",
        "description": "允许提交在线生图、ZImage、Angle、ModelScope 等图片工具任务。",
    },
    "asset_library_manage": {
        "default_enabled": True,
        "title": "素材库管理",
        "description": "允许新增、编辑、移动、删除、分类、裁剪、注册或导入素材库对象。",
    },
    "history_batch_delete": {
        "default_enabled": True,
        "title": "历史记录删除",
        "description": "允许通过历史记录删除接口删除生成历史。",
    },
    "local_asset_manage": {
        "default_enabled": True,
        "title": "本地资源管理",
        "description": "允许移动、重命名、删除、标注、分类或通过 URL 导入本地资源。",
    },
    "system_update": {
        "default_enabled": False,
        "title": "系统更新",
        "description": "允许使用企业版受控的项目更新接口和更新入口。",
    },
}

FEATURE_OVERRIDE_MODES = {"inherit", "allow", "deny"}


class SecureUserGovernanceRequiredError(RuntimeError):
    """Raised when a legacy mutator is unsafe for ROLE_AUTH_READY."""


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _user_schema_state(conn: sqlite3.Connection) -> str:
    columns = get_user_columns(conn)
    if "is_admin" not in columns:
        raise RuntimeError("users compatibility schema is incomplete")
    state = classify_role_auth_schema(columns)
    if state not in {SCHEMA_LEGACY, ROLE_AUTH_READY}:
        raise RuntimeError("unsupported users role/auth schema state")
    return state


def normalize_user_record(row: sqlite3.Row | dict, schema_state: str) -> dict:
    """Normalize legacy and migrated users into one fail-closed record."""
    record = dict(row)
    if schema_state == SCHEMA_LEGACY:
        role = role_from_legacy_is_admin(record.get("is_admin"))
        auth_version = LEGACY_AUTH_VERSION
    elif schema_state == ROLE_AUTH_READY:
        role = normalize_role(record.get("role"))
        auth_version = normalize_auth_version(record.get("auth_version"))
    else:
        raise ValueError("unsupported users role/auth schema state")
    record["role"] = role
    record["auth_version"] = auth_version
    record["is_admin"] = is_admin_role(role)
    record["is_active"] = bool(record.get("is_active"))
    record["_role_auth_schema_state"] = schema_state
    return record


def _public_user_record(user: dict) -> dict:
    public = dict(user)
    public.pop("password_hash", None)
    public.pop("_role_auth_schema_state", None)
    return public


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
                role        TEXT NOT NULL DEFAULT 'user'
                            CHECK (role IN ('user', 'admin', 'super_admin')),
                auth_version INTEGER NOT NULL DEFAULT 1
                             CHECK (auth_version >= 0),
                role_updated_at INTEGER,
                role_updated_by TEXT,
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

            CREATE TABLE IF NOT EXISTS user_project_map (
                user_id           TEXT NOT NULL,
                project_id        TEXT NOT NULL,
                parent_project_id TEXT,
                visibility        TEXT NOT NULL DEFAULT 'private',
                created_at        INTEGER NOT NULL,
                PRIMARY KEY (project_id)
            );

            CREATE TABLE IF NOT EXISTS user_conversation_map (
                user_id         TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                created_at      INTEGER NOT NULL,
                PRIMARY KEY (conversation_id)
            );

            CREATE TABLE IF NOT EXISTS user_resource_map (
                user_id      TEXT NOT NULL,
                resource_url TEXT NOT NULL,
                source       TEXT,
                created_at   INTEGER NOT NULL,
                PRIMARY KEY (resource_url)
            );

            CREATE TABLE IF NOT EXISTS user_canvas_task_map (
                user_id    TEXT NOT NULL,
                task_id    TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (task_id)
            );

            CREATE TABLE IF NOT EXISTS user_task_map (
                task_type        TEXT NOT NULL,
                task_id          TEXT NOT NULL,
                user_id          TEXT NOT NULL,
                source           TEXT,
                canvas_id        TEXT,
                workflow_id      TEXT,
                upstream_task_id TEXT,
                resource_url     TEXT,
                status           TEXT,
                created_at       INTEGER NOT NULL,
                updated_at       INTEGER NOT NULL,
                PRIMARY KEY (task_type, task_id)
            );

            CREATE INDEX IF NOT EXISTS idx_user_task_owner
                ON user_task_map (user_id, task_type);

            CREATE INDEX IF NOT EXISTS idx_user_task_upstream
                ON user_task_map (upstream_task_id);

            CREATE TABLE IF NOT EXISTS user_history_map (
                history_id   TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                type         TEXT,
                resource_url TEXT,
                task_id      TEXT,
                created_at   INTEGER NOT NULL,
                source       TEXT
            );

            CREATE TABLE IF NOT EXISTS user_asset_object_map (
                object_type        TEXT NOT NULL,
                object_id          TEXT NOT NULL,
                user_id            TEXT NOT NULL,
                parent_library_id  TEXT,
                parent_category_id TEXT,
                resource_url       TEXT,
                source             TEXT,
                created_at         INTEGER NOT NULL,
                updated_at         INTEGER NOT NULL,
                PRIMARY KEY (object_type, object_id)
            );

            CREATE INDEX IF NOT EXISTS idx_user_asset_object_owner
                ON user_asset_object_map (user_id, object_type);

            CREATE INDEX IF NOT EXISTS idx_user_asset_object_resource
                ON user_asset_object_map (resource_url);

            CREATE TABLE IF NOT EXISTS usage_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                action      TEXT NOT NULL,
                detail      TEXT,
                ts          INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS enterprise_feature_flags (
                feature_key TEXT PRIMARY KEY,
                enabled     INTEGER NOT NULL,
                description TEXT,
                updated_by  TEXT,
                updated_at  INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS enterprise_user_feature_overrides (
                user_id     TEXT NOT NULL,
                feature_key TEXT NOT NULL,
                mode        TEXT NOT NULL,
                updated_by  TEXT,
                updated_at  INTEGER NOT NULL,
                PRIMARY KEY (user_id, feature_key)
            );

            CREATE INDEX IF NOT EXISTS idx_enterprise_user_feature_overrides_feature
                ON enterprise_user_feature_overrides (feature_key);
        """)
        for column in ("parent_library_id", "parent_category_id"):
            try:
                conn.execute(f"ALTER TABLE user_asset_object_map ADD COLUMN {column} TEXT")
            except sqlite3.OperationalError:
                pass
        user_schema_state = _user_schema_state(conn)
        if user_schema_state == ROLE_AUTH_READY:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_role_active ON users (role, is_active)"
            )
        conn.commit()

        # 如果管理员不存在则创建
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
        ).fetchone()
        if not existing:
            uid = uuid.uuid4().hex
            ph = _hash_password(ADMIN_PASSWORD)
            now = int(time.time() * 1000)
            if user_schema_state == ROLE_AUTH_READY:
                conn.execute(
                    """
                    INSERT INTO users (
                        id, username, password_hash, display_name,
                        is_admin, role, auth_version, created_at
                    ) VALUES (?, ?, ?, ?, 1, ?, 1, ?)
                    """,
                    (uid, ADMIN_USERNAME, ph, "管理员", ROLE_ADMIN, now),
                )
            else:
                conn.execute(
                    "INSERT INTO users (id, username, password_hash, display_name, is_admin, created_at) "
                    "VALUES (?, ?, ?, ?, 1, ?)",
                    (uid, ADMIN_USERNAME, ph, "管理员", now),
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
        schema_state = _user_schema_state(conn)
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
        ).fetchone()
        return normalize_user_record(row, schema_state) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        schema_state = _user_schema_state(conn)
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)
        ).fetchone()
        return normalize_user_record(row, schema_state) if row else None
    finally:
        conn.close()


def get_user_by_id_any_status(user_id: str) -> Optional[dict]:
    """按 ID 查询用户，包含已禁用账号，供管理员操作使用。"""
    conn = get_db()
    try:
        schema_state = _user_schema_state(conn)
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return normalize_user_record(row, schema_state) if row else None
    finally:
        conn.close()


def list_users() -> list:
    conn = get_db()
    try:
        schema_state = _user_schema_state(conn)
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at ASC"
        ).fetchall()
        return [
            _public_user_record(normalize_user_record(row, schema_state))
            for row in rows
        ]
    finally:
        conn.close()


def count_active_admins() -> int:
    conn = get_db()
    try:
        schema_state = _user_schema_state(conn)
        rows = conn.execute(
            "SELECT role, auth_version, is_admin, is_active FROM users WHERE is_active = 1"
            if schema_state == ROLE_AUTH_READY
            else "SELECT is_admin, is_active FROM users WHERE is_active = 1"
        ).fetchall()
        return sum(
            1
            for row in rows
            if normalize_user_record(row, schema_state)["is_admin"]
        )
    finally:
        conn.close()


def get_user_delete_impact(user_id: str, sample_limit: int = 20) -> Optional[dict]:
    """Return a read-only dry-run summary for user deletion/cleanup planning."""
    user_id = (user_id or "").strip()
    if not user_id:
        return None
    try:
        sample_limit = int(sample_limit)
    except Exception:
        sample_limit = 20
    sample_limit = max(0, min(100, sample_limit))

    table_specs = {
        "projects": (
            "user_project_map",
            "user_id",
            "project_id, parent_project_id, visibility, created_at",
            "created_at DESC",
        ),
        "canvases": (
            "user_canvas_map",
            "user_id",
            "canvas_id, created_at",
            "created_at DESC",
        ),
        "conversations": (
            "user_conversation_map",
            "user_id",
            "conversation_id, created_at",
            "created_at DESC",
        ),
        "resources": (
            "user_resource_map",
            "user_id",
            "resource_url, source, created_at",
            "created_at DESC",
        ),
        "history": (
            "user_history_map",
            "user_id",
            "history_id, type, resource_url, task_id, source, created_at",
            "created_at DESC",
        ),
        "asset_objects": (
            "user_asset_object_map",
            "user_id",
            "object_type, object_id, parent_library_id, parent_category_id, resource_url, source, created_at, updated_at",
            "updated_at DESC",
        ),
        "canvas_tasks": (
            "user_canvas_task_map",
            "user_id",
            "task_id, created_at",
            "created_at DESC",
        ),
        "tasks": (
            "user_task_map",
            "user_id",
            "task_type, task_id, source, canvas_id, workflow_id, upstream_task_id, resource_url, status, created_at, updated_at",
            "updated_at DESC",
        ),
        "feature_overrides": (
            "enterprise_user_feature_overrides",
            "user_id",
            "feature_key, mode, updated_by, updated_at",
            "updated_at DESC",
        ),
    }

    conn = get_db()
    try:
        schema_state = _user_schema_state(conn)
        user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user_row:
            return None

        counts: dict[str, int] = {}
        samples: dict[str, list] = {}
        for key, (table, owner_column, columns, order_by) in table_specs.items():
            counts[key] = int(conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {owner_column} = ?",
                (user_id,),
            ).fetchone()[0])
            rows = conn.execute(
                f"""
                SELECT {columns}
                FROM {table}
                WHERE {owner_column} = ?
                ORDER BY {order_by}
                LIMIT ?
                """,
                (user_id, sample_limit),
            ).fetchall()
            samples[key] = [dict(row) for row in rows]

        audit_like = f"%{user_id}%"
        counts["audit_logs"] = int(conn.execute(
            """
            SELECT COUNT(*)
            FROM usage_logs
            WHERE user_id = ? OR detail LIKE ?
            """,
            (user_id, audit_like),
        ).fetchone()[0])

        user = _public_user_record(normalize_user_record(user_row, schema_state))
        return {
            "user": user,
            "counts": counts,
            "samples": samples,
            "warnings": [
                "Runtime files are not deleted by this operation.",
                "Audit logs are retained.",
                "This is a read-only dry-run preview.",
            ],
        }
    finally:
        conn.close()


def create_user(username: str, password: str, display_name: str = "", is_admin: bool = False) -> dict:
    conn = get_db()
    try:
        schema_state = _user_schema_state(conn)
        if schema_state == ROLE_AUTH_READY:
            raise SecureUserGovernanceRequiredError(
                "ROLE_AUTH_READY user creation requires secure governance"
            )
        uid = uuid.uuid4().hex
        ph = _hash_password(password)
        now = int(time.time() * 1000)
        legacy_is_admin = 1 if is_admin else 0
        conn.execute(
            "INSERT INTO users (id, username, password_hash, display_name, is_admin, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uid, username, ph, display_name or username, legacy_is_admin, now),
        )
        conn.commit()
        return {"id": uid, "username": username}
    finally:
        conn.close()


def update_user_password(user_id: str, new_password: str) -> bool:
    password_hash = _hash_password(new_password)
    conn = get_db()
    try:
        schema_state = _user_schema_state(conn)
        if schema_state == ROLE_AUTH_READY:
            raise SecureUserGovernanceRequiredError(
                "ROLE_AUTH_READY password changes require secure governance"
            )
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            conn.rollback()
            return False
        user = normalize_user_record(row, schema_state)
        if schema_state == ROLE_AUTH_READY:
            cur = conn.execute(
                "UPDATE users SET password_hash = ?, auth_version = ? WHERE id = ?",
                (password_hash, user["auth_version"] + 1, user_id),
            )
        else:
            cur = conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, user_id),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_user_role(user_id: str, is_admin: bool, updated_by: Optional[str] = None) -> bool:
    """修改用户管理员权限"""
    conn = get_db()
    try:
        schema_state = _user_schema_state(conn)
        if schema_state == ROLE_AUTH_READY:
            raise SecureUserGovernanceRequiredError(
                "ROLE_AUTH_READY role changes are closed online"
            )
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            conn.rollback()
            return False
        user = normalize_user_record(row, schema_state)
        legacy_is_admin = 1 if is_admin else 0
        if schema_state == ROLE_AUTH_READY:
            target_role = ROLE_ADMIN if is_admin else ROLE_USER
            role_changed = user["role"] != target_role
            next_version = user["auth_version"] + (1 if role_changed else 0)
            cur = conn.execute(
                """
                UPDATE users
                SET role = ?, is_admin = ?, auth_version = ?,
                    role_updated_at = ?, role_updated_by = ?
                WHERE id = ?
                """,
                (
                    target_role,
                    legacy_is_admin,
                    next_version,
                    int(time.time() * 1000) if role_changed else user.get("role_updated_at"),
                    updated_by if role_changed else user.get("role_updated_by"),
                    user_id,
                ),
            )
        else:
            cur = conn.execute(
                "UPDATE users SET is_admin = ? WHERE id = ?",
                (legacy_is_admin, user_id),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_user_profile(user_id: str, display_name: str) -> bool:
    """更新用户展示名。空展示名由调用方决定是否回退。"""
    conn = get_db()
    try:
        if _user_schema_state(conn) == ROLE_AUTH_READY:
            raise SecureUserGovernanceRequiredError(
                "ROLE_AUTH_READY profile changes require secure governance"
            )
        cur = conn.execute(
            "UPDATE users SET display_name = ? WHERE id = ?",
            (display_name, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_user_active(user_id: str, is_active: bool) -> bool:
    """启用或禁用账号。"""
    conn = get_db()
    try:
        schema_state = _user_schema_state(conn)
        if schema_state == ROLE_AUTH_READY:
            raise SecureUserGovernanceRequiredError(
                "ROLE_AUTH_READY active changes require secure governance"
            )
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            conn.rollback()
            return False
        user = normalize_user_record(row, schema_state)
        next_active = bool(is_active)
        state_changed = user["is_active"] != next_active
        if schema_state == ROLE_AUTH_READY:
            cur = conn.execute(
                "UPDATE users SET is_active = ?, auth_version = ? WHERE id = ?",
                (
                    1 if next_active else 0,
                    user["auth_version"] + (1 if state_changed else 0),
                    user_id,
                ),
            )
        else:
            cur = conn.execute(
                "UPDATE users SET is_active = ? WHERE id = ?",
                (1 if next_active else 0, user_id),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_user(user_id: str) -> None:
    """软删除（禁用）用户"""
    set_user_active(user_id, False)


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

def record_canvas_owner(user_id: str, canvas_id: str) -> bool:
    """记录新画布归属。已有归属时不覆盖，返回是否写入。"""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO user_canvas_map (user_id, canvas_id, created_at) VALUES (?, ?, ?)",
            (user_id, canvas_id, int(time.time() * 1000))
        )
        conn.commit()
        return cur.rowcount > 0
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


def set_canvas_owner(canvas_id: str, user_id: str) -> bool:
    """设置画布归属（覆盖旧归属）。"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM user_canvas_map WHERE canvas_id = ?", (canvas_id,))
        cur = conn.execute(
            "INSERT INTO user_canvas_map (user_id, canvas_id, created_at) VALUES (?, ?, ?)",
            (user_id, canvas_id, int(time.time() * 1000))
        )
        conn.commit()
        return cur.rowcount > 0
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
    set_canvas_owner(canvas_id, user_id)


# ── 项目归属映射 ──────────────────────────────────────────

DEFAULT_PROJECT_ID = "default"
CANVAS_DATA_DIR = str(PATH_ROOTS.DATA_ROOT / "canvases")


def _canvas_json_path(canvas_id: str) -> Optional[str]:
    canvas_id = str(canvas_id or "").strip()
    if not canvas_id or os.path.basename(canvas_id) != canvas_id:
        return None
    return os.path.join(CANVAS_DATA_DIR, f"{canvas_id}.json")


def read_canvas_json(canvas_id: str) -> Optional[dict]:
    """读取上游画布 JSON；企业层只用于归属一致性治理。"""
    path = _canvas_json_path(canvas_id)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def get_canvas_project(canvas_id: str) -> Optional[str]:
    data = read_canvas_json(canvas_id)
    if not data:
        return None
    return str(data.get("project") or DEFAULT_PROJECT_ID).strip() or DEFAULT_PROJECT_ID


def set_canvas_project(canvas_id: str, project_id: str) -> tuple[bool, Optional[str]]:
    """更新画布 JSON 的 project 字段，返回 (是否写入, 旧 project)。"""
    data = read_canvas_json(canvas_id)
    if not data:
        return False, None
    old_project = str(data.get("project") or DEFAULT_PROJECT_ID).strip() or DEFAULT_PROJECT_ID
    new_project = str(project_id or DEFAULT_PROJECT_ID).strip() or DEFAULT_PROJECT_ID
    if old_project == new_project:
        return False, old_project
    data["project"] = new_project
    path = _canvas_json_path(canvas_id)
    if not path:
        return False, old_project
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return True, old_project


def get_canvas_ids_by_project(project_id: str) -> list[str]:
    project_id = str(project_id or DEFAULT_PROJECT_ID).strip() or DEFAULT_PROJECT_ID
    try:
        filenames = os.listdir(CANVAS_DATA_DIR)
    except Exception:
        return []
    canvas_ids: list[str] = []
    for filename in filenames:
        if not filename.endswith(".json"):
            continue
        canvas_id = filename[:-5]
        data = read_canvas_json(canvas_id)
        if not data:
            continue
        canvas_project = str(data.get("project") or DEFAULT_PROJECT_ID).strip() or DEFAULT_PROJECT_ID
        if canvas_project == project_id:
            canvas_ids.append(str(data.get("id") or canvas_id))
    return canvas_ids


def record_project_owner(user_id: str, project_id: str) -> bool:
    """记录新项目归属。上游默认项目是每位用户的虚拟根，不写入全局映射。"""
    project_id = str(project_id or "").strip()
    if not user_id or not project_id or project_id == DEFAULT_PROJECT_ID:
        return False
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO user_project_map "
            "(user_id, project_id, parent_project_id, visibility, created_at) VALUES (?, ?, NULL, 'private', ?)",
            (user_id, project_id, int(time.time() * 1000)),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_project_owner(project_id: str) -> Optional[str]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id FROM user_project_map WHERE project_id = ?", (str(project_id or "").strip(),)
        ).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


def get_user_project_ids(user_id: str) -> set:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT project_id FROM user_project_map WHERE user_id = ?", (user_id,)
        ).fetchall()
        return {row["project_id"] for row in rows}
    finally:
        conn.close()


def set_project_owner(project_id: str, user_id: str) -> bool:
    """管理员设置项目归属（覆盖旧归属）；全局默认项目不能被单独分配。"""
    project_id = str(project_id or "").strip()
    if not user_id or not project_id or project_id == DEFAULT_PROJECT_ID:
        return False
    conn = get_db()
    try:
        conn.execute("DELETE FROM user_project_map WHERE project_id = ?", (project_id,))
        cur = conn.execute(
            "INSERT INTO user_project_map "
            "(user_id, project_id, parent_project_id, visibility, created_at) VALUES (?, ?, NULL, 'private', ?)",
            (user_id, project_id, int(time.time() * 1000)),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def remove_project_mapping(project_id: str) -> None:
    conn = get_db()
    try:
        conn.execute("DELETE FROM user_project_map WHERE project_id = ?", (str(project_id or "").strip(),))
        conn.commit()
    finally:
        conn.close()


def get_all_project_owner_map() -> dict:
    """返回 {project_id: user_id} 的全量映射（供管理员使用）。"""
    conn = get_db()
    try:
        rows = conn.execute("SELECT project_id, user_id FROM user_project_map").fetchall()
        return {row["project_id"]: row["user_id"] for row in rows}
    finally:
        conn.close()


def project_exists(project_id: str) -> bool:
    """只读检查上游项目文件，避免管理员为不存在的项目创建幽灵映射。"""
    project_id = str(project_id or "").strip()
    if not project_id:
        return False
    if project_id == DEFAULT_PROJECT_ID:
        return True
    path = str(PATH_ROOTS.DATA_ROOT / "projects.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    projects = data.get("projects") if isinstance(data, dict) else data
    return isinstance(projects, list) and any(
        isinstance(item, dict) and str(item.get("id") or "") == project_id for item in projects
    )


# ── 对话归属映射 ──────────────────────────────────────────

def record_conversation_owner(user_id: str, conversation_id: str) -> bool:
    """记录新对话归属。已有归属时不覆盖，返回是否写入。"""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO user_conversation_map (user_id, conversation_id, created_at) VALUES (?, ?, ?)",
            (user_id, conversation_id, int(time.time() * 1000))
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_conversation_owner(conversation_id: str) -> Optional[str]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id FROM user_conversation_map WHERE conversation_id = ?",
            (conversation_id,)
        ).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


def set_conversation_owner(conversation_id: str, user_id: str) -> bool:
    """设置对话归属（覆盖旧归属）。"""
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM user_conversation_map WHERE conversation_id = ?",
            (conversation_id,)
        )
        cur = conn.execute(
            "INSERT INTO user_conversation_map (user_id, conversation_id, created_at) VALUES (?, ?, ?)",
            (user_id, conversation_id, int(time.time() * 1000))
        )
        conn.commit()
        return cur.rowcount > 0
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


def get_all_conversation_owner_map() -> dict:
    """返回 {conversation_id: user_id} 的全量映射（供管理员使用）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT conversation_id, user_id FROM user_conversation_map"
        ).fetchall()
        return {r["conversation_id"]: r["user_id"] for r in rows}
    finally:
        conn.close()


def assign_conversation_owner(conversation_id: str, user_id: str) -> None:
    """管理员手动分配对话归属（覆盖旧归属）。"""
    set_conversation_owner(conversation_id, user_id)


def _conversation_root() -> str:
    return str(PATH_ROOTS.DATA_ROOT / "conversations")


def list_conversation_records() -> list[dict]:
    """扫描上游对话文件，供管理员查看全量/未归属历史数据。"""
    root = _conversation_root()
    if not os.path.isdir(root):
        return []

    records = []
    for file_user_id in sorted(os.listdir(root)):
        user_folder = os.path.join(root, file_user_id)
        if not os.path.isdir(user_folder):
            continue
        for filename in sorted(os.listdir(user_folder)):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(user_folder, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            conversation_id = str(data.get("id") or os.path.splitext(filename)[0])
            if not conversation_id:
                continue
            messages = data.get("messages") if isinstance(data.get("messages"), list) else []
            records.append({
                "id": conversation_id,
                "title": data.get("title") or "新对话",
                "created_at": data.get("created_at") or 0,
                "updated_at": data.get("updated_at") or 0,
                "message_count": len(messages),
                "file_user_id": file_user_id,
            })
    records.sort(key=lambda item: int(item.get("updated_at") or item.get("created_at") or 0), reverse=True)
    return records


def get_conversation_file_owner(conversation_id: str) -> Optional[str]:
    """返回上游真实文件所在用户目录，用于网关访问已重新分配的历史对话。"""
    root = _conversation_root()
    if not os.path.isdir(root):
        return None
    safe_id = "".join(ch for ch in str(conversation_id or "") if ch.isalnum() or ch in "_-")
    if not safe_id:
        return None
    filename = f"{safe_id}.json"
    for file_user_id in os.listdir(root):
        path = os.path.join(root, file_user_id, filename)
        if os.path.isfile(path):
            return file_user_id
    return None


# ── 资源归属映射 ──────────────────────────────────────────

def record_resource_owner(user_id: str, resource_url: str, source: str = "") -> bool:
    """记录上传、生成或保存过程中产生的本地资源 URL。已有归属时不覆盖。"""
    resource_url = (resource_url or "").strip()
    if not resource_url:
        return False
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO user_resource_map (user_id, resource_url, source, created_at) VALUES (?, ?, ?, ?)",
            (user_id, resource_url, source, int(time.time() * 1000))
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_resource_owner(resource_url: str) -> Optional[str]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id FROM user_resource_map WHERE resource_url = ?",
            ((resource_url or "").strip(),)
        ).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


def get_user_resource_urls(user_id: str) -> set:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT resource_url FROM user_resource_map WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        return {r["resource_url"] for r in rows}
    finally:
        conn.close()


# ── 素材库业务对象归属映射 ─────────────────────────────────

def record_asset_object_owner(
    user_id: str,
    object_type: str,
    object_id: str,
    parent_library_id: str = "",
    parent_category_id: str = "",
    resource_url: str = "",
    source: str = "",
) -> bool:
    """记录素材库 library/category/item 业务对象归属；已有归属时不覆盖 owner。"""
    user_id = (user_id or "").strip()
    object_type = (object_type or "").strip()
    object_id = (object_id or "").strip()
    if not user_id or not object_type or not object_id:
        return False
    now = int(time.time() * 1000)
    conn = get_db()
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO user_asset_object_map
                (object_type, object_id, user_id, parent_library_id, parent_category_id,
                 resource_url, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                object_type,
                object_id,
                user_id,
                parent_library_id or "",
                parent_category_id or "",
                resource_url or "",
                source or "",
                now,
                now,
            ),
        )
        if cur.rowcount == 0 and (parent_library_id or parent_category_id or resource_url or source):
            conn.execute(
                """
                UPDATE user_asset_object_map
                   SET parent_library_id = COALESCE(NULLIF(?, ''), parent_library_id),
                       parent_category_id = COALESCE(NULLIF(?, ''), parent_category_id),
                       resource_url = COALESCE(NULLIF(?, ''), resource_url),
                       source = COALESCE(NULLIF(?, ''), source),
                       updated_at = ?
                 WHERE object_type = ? AND object_id = ?
                """,
                (
                    parent_library_id or "",
                    parent_category_id or "",
                    resource_url or "",
                    source or "",
                    now,
                    object_type,
                    object_id,
                ),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_asset_object_owner(
    user_id: str,
    object_type: str,
    object_id: str,
    parent_library_id: str = "",
    parent_category_id: str = "",
    resource_url: str = "",
    source: str = "",
) -> bool:
    return record_asset_object_owner(
        user_id,
        object_type,
        object_id,
        parent_library_id=parent_library_id,
        parent_category_id=parent_category_id,
        resource_url=resource_url,
        source=source,
    )


def get_asset_object_owner(object_type: str, object_id: str) -> Optional[str]:
    object_type = (object_type or "").strip()
    object_id = (object_id or "").strip()
    if not object_type or not object_id:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id FROM user_asset_object_map WHERE object_type = ? AND object_id = ?",
            (object_type, object_id),
        ).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


def get_asset_object(object_type: str, object_id: str) -> Optional[dict]:
    object_type = (object_type or "").strip()
    object_id = (object_id or "").strip()
    if not object_type or not object_id:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM user_asset_object_map WHERE object_type = ? AND object_id = ?",
            (object_type, object_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_asset_item_owner_by_resource(resource_url: str) -> Optional[str]:
    resource_url = (resource_url or "").strip()
    if not resource_url:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT user_id
              FROM user_asset_object_map
             WHERE object_type = 'item' AND resource_url = ?
             ORDER BY updated_at DESC
             LIMIT 1
            """,
            (resource_url,),
        ).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


def update_asset_object_parent(
    object_type: str,
    object_id: str,
    parent_library_id: str = "",
    parent_category_id: str = "",
    resource_url: str = "",
) -> bool:
    object_type = (object_type or "").strip()
    object_id = (object_id or "").strip()
    if not object_type or not object_id:
        return False
    conn = get_db()
    try:
        cur = conn.execute(
            """
            UPDATE user_asset_object_map
               SET parent_library_id = COALESCE(NULLIF(?, ''), parent_library_id),
                   parent_category_id = COALESCE(NULLIF(?, ''), parent_category_id),
                   resource_url = COALESCE(NULLIF(?, ''), resource_url),
                   updated_at = ?
             WHERE object_type = ? AND object_id = ?
            """,
            (
                parent_library_id or "",
                parent_category_id or "",
                resource_url or "",
                int(time.time() * 1000),
                object_type,
                object_id,
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_asset_object_owners(object_type: str = "", user_id: str = "") -> list[dict]:
    conditions = []
    params = []
    if object_type:
        conditions.append("object_type = ?")
        params.append(object_type)
    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT * FROM user_asset_object_map {where} ORDER BY updated_at DESC",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def asset_object_belongs_to_user(object_type: str, object_id: str, user_id: str) -> bool:
    return bool(user_id and get_asset_object_owner(object_type, object_id) == user_id)


def remove_asset_object_mapping(object_type: str, object_id: str) -> None:
    object_type = (object_type or "").strip()
    object_id = (object_id or "").strip()
    if not object_type or not object_id:
        return
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM user_asset_object_map WHERE object_type = ? AND object_id = ?",
            (object_type, object_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_asset_object_owner(object_type: str, object_id: str) -> None:
    remove_asset_object_mapping(object_type, object_id)


def record_canvas_image_task_owner(user_id: str, task_id: str) -> bool:
    user_id = (user_id or "").strip()
    task_id = (task_id or "").strip()
    if not user_id or not task_id:
        return False
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO user_canvas_task_map (user_id, task_id, created_at) VALUES (?, ?, ?)",
            (user_id, task_id, int(time.time() * 1000))
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_canvas_image_task_owner(task_id: str) -> Optional[str]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id FROM user_canvas_task_map WHERE task_id = ?",
            ((task_id or "").strip(),)
        ).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


# ── 历史记录归属映射 ──────────────────────────────────────

def record_task_owner(
    user_id: str,
    task_type: str,
    task_id: str,
    source: str = "",
    canvas_id: str = "",
    workflow_id: str = "",
    upstream_task_id: str = "",
    resource_url: str = "",
    status: str = "",
) -> bool:
    """Record an enterprise owner for a provider or workflow task id."""
    user_id = (user_id or "").strip()
    task_type = (task_type or "").strip()
    task_id = (task_id or "").strip()
    if not user_id or not task_type or not task_id:
        return False
    now = int(time.time() * 1000)
    conn = get_db()
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO user_task_map
                (task_type, task_id, user_id, source, canvas_id, workflow_id,
                 upstream_task_id, resource_url, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_type,
                task_id,
                user_id,
                (source or "").strip(),
                (canvas_id or "").strip(),
                (workflow_id or "").strip(),
                (upstream_task_id or "").strip(),
                (resource_url or "").strip(),
                (status or "").strip(),
                now,
                now,
            ),
        )
        if cur.rowcount == 0:
            conn.execute(
                """
                UPDATE user_task_map
                   SET source = COALESCE(NULLIF(?, ''), source),
                       canvas_id = COALESCE(NULLIF(?, ''), canvas_id),
                       workflow_id = COALESCE(NULLIF(?, ''), workflow_id),
                       upstream_task_id = COALESCE(NULLIF(?, ''), upstream_task_id),
                       resource_url = COALESCE(NULLIF(?, ''), resource_url),
                       status = COALESCE(NULLIF(?, ''), status),
                       updated_at = ?
                 WHERE task_type = ? AND task_id = ?
                """,
                (
                    (source or "").strip(),
                    (canvas_id or "").strip(),
                    (workflow_id or "").strip(),
                    (upstream_task_id or "").strip(),
                    (resource_url or "").strip(),
                    (status or "").strip(),
                    now,
                    task_type,
                    task_id,
                ),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_task_owner(task_type: str, task_id: str) -> Optional[str]:
    task_type = (task_type or "").strip()
    task_id = (task_id or "").strip()
    if not task_type or not task_id:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id FROM user_task_map WHERE task_type = ? AND task_id = ?",
            (task_type, task_id),
        ).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


def get_task_owner_any(task_id: str, task_types: Optional[list[str]] = None) -> Optional[str]:
    task_id = (task_id or "").strip()
    if not task_id:
        return None
    conn = get_db()
    try:
        if task_types:
            clean_types = [(item or "").strip() for item in task_types if (item or "").strip()]
            if not clean_types:
                return None
            placeholders = ",".join("?" for _ in clean_types)
            row = conn.execute(
                f"""
                SELECT user_id FROM user_task_map
                 WHERE task_id = ? AND task_type IN ({placeholders})
                 ORDER BY updated_at DESC
                 LIMIT 1
                """,
                [task_id, *clean_types],
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT user_id FROM user_task_map
                 WHERE task_id = ?
                 ORDER BY updated_at DESC
                 LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


def get_task(task_type: str, task_id: str) -> Optional[dict]:
    task_type = (task_type or "").strip()
    task_id = (task_id or "").strip()
    if not task_type or not task_id:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM user_task_map WHERE task_type = ? AND task_id = ?",
            (task_type, task_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_task_owner_map() -> dict[tuple[str, str], str]:
    conn = get_db()
    try:
        rows = conn.execute("SELECT task_type, task_id, user_id FROM user_task_map").fetchall()
        return {(row["task_type"], row["task_id"]): row["user_id"] for row in rows}
    finally:
        conn.close()


def record_task_resource_owner(
    task_type: str,
    task_id: str,
    resource_url: str,
    source: str = "",
) -> bool:
    owner = get_task_owner(task_type, task_id)
    if not owner:
        return False
    return record_resource_owner(owner, resource_url, source or f"task:{task_type}:{task_id}")


def record_history_owner(
    user_id: str,
    history_id: str,
    history_type: str = "",
    resource_url: str = "",
    task_id: str = "",
    source: str = "",
) -> bool:
    """记录生成历史归属。已有归属时不覆盖，返回是否写入。"""
    user_id = (user_id or "").strip()
    history_id = (history_id or "").strip()
    if not user_id or not history_id:
        return False
    conn = get_db()
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO user_history_map
            (history_id, user_id, type, resource_url, task_id, created_at, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                history_id,
                user_id,
                (history_type or "").strip(),
                (resource_url or "").strip(),
                (task_id or "").strip(),
                int(time.time() * 1000),
                (source or "").strip(),
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_history_owner(history_id: str) -> Optional[str]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id FROM user_history_map WHERE history_id = ?",
            ((history_id or "").strip(),),
        ).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


def set_history_owner(
    history_id: str,
    user_id: str,
    history_type: str = "",
    resource_url: str = "",
    task_id: str = "",
    source: str = "",
) -> bool:
    """管理员迁移历史记录归属（覆盖旧归属）。"""
    history_id = (history_id or "").strip()
    user_id = (user_id or "").strip()
    if not history_id or not user_id:
        return False
    conn = get_db()
    try:
        conn.execute("DELETE FROM user_history_map WHERE history_id = ?", (history_id,))
        cur = conn.execute(
            """
            INSERT INTO user_history_map
            (history_id, user_id, type, resource_url, task_id, created_at, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                history_id,
                user_id,
                (history_type or "").strip(),
                (resource_url or "").strip(),
                (task_id or "").strip(),
                int(time.time() * 1000),
                (source or "").strip(),
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def remove_history_mapping(history_id: str) -> None:
    conn = get_db()
    try:
        conn.execute("DELETE FROM user_history_map WHERE history_id = ?", ((history_id or "").strip(),))
        conn.commit()
    finally:
        conn.close()


def get_user_history_ids(user_id: str) -> set:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT history_id FROM user_history_map WHERE user_id = ?",
            ((user_id or "").strip(),),
        ).fetchall()
        return {row["history_id"] for row in rows}
    finally:
        conn.close()


def get_all_history_owner_map() -> dict:
    conn = get_db()
    try:
        rows = conn.execute("SELECT history_id, user_id FROM user_history_map").fetchall()
        return {row["history_id"]: row["user_id"] for row in rows}
    finally:
        conn.close()


# ── 使用日志 ──────────────────────────────────────────────

# ─── Feature flags ──────────────────────────────────────────────────────────

def is_known_feature_key(feature_key: str) -> bool:
    return str(feature_key or "").strip() in FEATURE_FLAG_DEFINITIONS


def _normalize_feature_key(feature_key: str) -> str:
    key = str(feature_key or "").strip()
    if key not in FEATURE_FLAG_DEFINITIONS:
        raise ValueError(f"unknown feature key: {feature_key}")
    return key


def _normalize_override_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized not in FEATURE_OVERRIDE_MODES:
        raise ValueError(f"invalid feature override mode: {mode}")
    return normalized


def _feature_default_enabled(feature_key: str) -> bool:
    key = _normalize_feature_key(feature_key)
    return bool(FEATURE_FLAG_DEFINITIONS[key]["default_enabled"])


def _feature_row(key: str, row: Optional[sqlite3.Row]) -> dict:
    definition = FEATURE_FLAG_DEFINITIONS[key]
    if row:
        enabled = bool(row["enabled"])
        description = definition["description"]
        updated_by = row["updated_by"]
        updated_at = row["updated_at"]
        configured = True
    else:
        enabled = bool(definition["default_enabled"])
        description = definition["description"]
        updated_by = None
        updated_at = None
        configured = False
    return {
        "feature_key": key,
        "title": definition["title"],
        "enabled": enabled,
        "default_enabled": bool(definition["default_enabled"]),
        "description": description,
        "updated_by": updated_by,
        "updated_at": updated_at,
        "configured": configured,
    }


def list_feature_flags() -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT feature_key, enabled, description, updated_by, updated_at FROM enterprise_feature_flags"
        ).fetchall()
        row_map = {row["feature_key"]: row for row in rows}
        return [_feature_row(key, row_map.get(key)) for key in FEATURE_FLAG_DEFINITIONS]
    finally:
        conn.close()


def get_feature_flag(feature_key: str) -> dict:
    key = _normalize_feature_key(feature_key)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT feature_key, enabled, description, updated_by, updated_at "
            "FROM enterprise_feature_flags WHERE feature_key = ?",
            (key,),
        ).fetchone()
        return _feature_row(key, row)
    finally:
        conn.close()


def set_feature_flag(feature_key: str, enabled: bool, updated_by: str) -> tuple[dict, dict]:
    key = _normalize_feature_key(feature_key)
    old = get_feature_flag(key)
    definition = FEATURE_FLAG_DEFINITIONS[key]
    now = int(time.time() * 1000)
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO enterprise_feature_flags (feature_key, enabled, description, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(feature_key) DO UPDATE SET
                enabled = excluded.enabled,
                description = excluded.description,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (key, 1 if enabled else 0, definition["description"], updated_by, now),
        )
        conn.commit()
    finally:
        conn.close()
    return old, get_feature_flag(key)


def get_user_feature_overrides(user_id: str) -> list[dict]:
    uid = str(user_id or "").strip()
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT user_id, feature_key, mode, updated_by, updated_at
            FROM enterprise_user_feature_overrides
            WHERE user_id = ?
            ORDER BY feature_key
            """,
            (uid,),
        ).fetchall()
        return [dict(row) for row in rows if is_known_feature_key(row["feature_key"])]
    finally:
        conn.close()


def get_user_feature_override(user_id: str, feature_key: str) -> Optional[dict]:
    uid = str(user_id or "").strip()
    key = _normalize_feature_key(feature_key)
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT user_id, feature_key, mode, updated_by, updated_at
            FROM enterprise_user_feature_overrides
            WHERE user_id = ? AND feature_key = ?
            """,
            (uid, key),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_user_feature_override(
    user_id: str,
    feature_key: str,
    mode: str,
    updated_by: str,
) -> tuple[Optional[dict], Optional[dict]]:
    uid = str(user_id or "").strip()
    key = _normalize_feature_key(feature_key)
    normalized_mode = _normalize_override_mode(mode)
    old = get_user_feature_override(uid, key)
    if normalized_mode == "inherit":
        return old, clear_user_feature_override(uid, key, updated_by)[1]
    now = int(time.time() * 1000)
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO enterprise_user_feature_overrides (user_id, feature_key, mode, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, feature_key) DO UPDATE SET
                mode = excluded.mode,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (uid, key, normalized_mode, updated_by, now),
        )
        conn.commit()
    finally:
        conn.close()
    return old, get_user_feature_override(uid, key)


def clear_user_feature_override(
    user_id: str,
    feature_key: str,
    updated_by: str = "",
) -> tuple[Optional[dict], Optional[dict]]:
    uid = str(user_id or "").strip()
    key = _normalize_feature_key(feature_key)
    old = get_user_feature_override(uid, key)
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM enterprise_user_feature_overrides WHERE user_id = ? AND feature_key = ?",
            (uid, key),
        )
        conn.commit()
    finally:
        conn.close()
    return old, None


def clear_all_user_feature_overrides(user_id: str, updated_by: str = "") -> list[dict]:
    uid = str(user_id or "").strip()
    old = get_user_feature_overrides(uid)
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM enterprise_user_feature_overrides WHERE user_id = ?",
            (uid,),
        )
        conn.commit()
    finally:
        conn.close()
    return old


def get_effective_feature_value(user: dict, feature_key: str) -> dict:
    key = _normalize_feature_key(feature_key)
    flag = get_feature_flag(key)
    if user and bool(user.get("is_admin")):
        return {
            "feature_key": key,
            "allowed": True,
            "mode": "admin",
            "source": "admin",
            "global_enabled": bool(flag["enabled"]),
            "default_enabled": bool(flag["default_enabled"]),
        }
    uid = str((user or {}).get("user_id") or (user or {}).get("id") or "").strip()
    override = get_user_feature_override(uid, key) if uid else None
    if override and override.get("mode") == "allow":
        allowed = True
        source = "user_override"
    elif override and override.get("mode") == "deny":
        allowed = False
        source = "user_override"
    else:
        allowed = bool(flag["enabled"])
        source = "global"
    return {
        "feature_key": key,
        "allowed": allowed,
        "mode": override.get("mode") if override else "inherit",
        "source": source,
        "global_enabled": bool(flag["enabled"]),
        "default_enabled": bool(flag["default_enabled"]),
        "updated_by": override.get("updated_by") if override else flag.get("updated_by"),
        "updated_at": override.get("updated_at") if override else flag.get("updated_at"),
    }


def can_use_feature(user: dict, feature_key: str) -> bool:
    try:
        return bool(get_effective_feature_value(user, feature_key)["allowed"])
    except Exception:
        return False


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

