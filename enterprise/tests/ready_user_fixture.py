"""Temporary SQLite fixtures for ROLE_AUTH_READY regression scripts only."""

import sqlite3
import time
import uuid
from os import PathLike


def insert_ready_user_fixture(
    database_path: str | PathLike[str],
    *,
    username: str,
    password_hash: str,
    display_name: str,
) -> dict[str, str]:
    """Insert a normal-user fixture into an explicit temporary READY database."""
    user_id = uuid.uuid4().hex
    conn = sqlite3.connect(database_path)
    try:
        conn.execute(
            """
            INSERT INTO main.users (
                id, username, password_hash, display_name,
                is_admin, role, auth_version, is_active, created_at
            ) VALUES (?, ?, ?, ?, 0, 'user', 1, 1, ?)
            """,
            (user_id, username, password_hash, display_name, int(time.time() * 1000)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": user_id, "username": username}
