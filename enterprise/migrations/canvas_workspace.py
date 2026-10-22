"""Workspace release registry; the verified payload decides its schema target.

Reuse user_project_map.parent_project_id; canvas bytes and billing facts stay
in their existing stores. Ordinary startup never invokes this migration.
"""
import hashlib

from enterprise.migrations.department_costs import candidate_registry as department_registry
from enterprise.migrations.versioned import MigrationStep


DDL = (
    """CREATE TABLE canvas_workspace_projects (
        project_id TEXT PRIMARY KEY REFERENCES user_project_map(project_id) ON DELETE CASCADE,
        owner_id TEXT NOT NULL REFERENCES users(id),
        business_project_id TEXT REFERENCES business_projects(id),
        archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)))""",
    """CREATE TABLE canvas_workspace_canvases (
        canvas_id TEXT PRIMARY KEY REFERENCES user_canvas_map(canvas_id) ON DELETE CASCADE,
        owner_id TEXT NOT NULL REFERENCES users(id),
        archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)))""",
)


def apply_in_transaction(conn):
    if not conn.in_transaction:
        raise RuntimeError('WORKSPACE_MIGRATION_TRANSACTION_REQUIRED')
    for sql in DDL:
        conn.execute(sql)


def validate_in_transaction(conn):
    for sql in DDL:
        row = conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (sql.split()[2],)).fetchone()
        if not row or ' '.join(row[0].split()) != ' '.join(sql.split()):
            return False
    return conn.execute('PRAGMA foreign_key_check').fetchone() is None


def release_registry():
    step = MigrationStep('ice_canvas_workspace_v4', 3, 4,
        hashlib.sha256('\n'.join(DDL).encode()).hexdigest(), apply_in_transaction, validate_in_transaction)
    return (*department_registry(), step)


def candidate_registry():
    return release_registry()
