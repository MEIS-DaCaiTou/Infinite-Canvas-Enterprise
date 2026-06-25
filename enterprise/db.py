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

from enterprise.config import DB_PATH, ADMIN_USERNAME, ADMIN_PASSWORD, ROOT_DIR


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


def get_user_by_id_any_status(user_id: str) -> Optional[dict]:
    """按 ID 查询用户，包含已禁用账号，供管理员操作使用。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
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


def update_user_password(user_id: str, new_password: str) -> bool:
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash_password(new_password), user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_user_role(user_id: str, is_admin: bool) -> bool:
    """修改用户管理员权限"""
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (1 if is_admin else 0, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_user_profile(user_id: str, display_name: str) -> bool:
    """更新用户展示名。空展示名由调用方决定是否回退。"""
    conn = get_db()
    try:
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
        cur = conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id)
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
CANVAS_DATA_DIR = os.path.join(str(ROOT_DIR), "data", "canvases")


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
    path = os.path.join(str(ROOT_DIR), "data", "projects.json")
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
    return os.path.join(str(ROOT_DIR), "data", "conversations")


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

