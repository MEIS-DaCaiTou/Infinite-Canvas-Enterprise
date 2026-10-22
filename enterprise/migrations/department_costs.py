"""Opt-in v2 -> v3 business schema; never invoked by ordinary startup.

The candidate registry is deliberately separate from the shipped registry. A
release must first stage that registry through the existing same-schema update
contract before activating v3. Existing users/projects/receipts are not adopted
into a department or charged by this migration.
"""
import hashlib
import sqlite3


DDL = (
    """CREATE TABLE departments (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)))""",
    """CREATE TABLE department_members (
        user_id TEXT PRIMARY KEY REFERENCES users(id),
        department_id TEXT NOT NULL REFERENCES departments(id),
        manager INTEGER NOT NULL DEFAULT 0 CHECK(manager IN (0,1)))""",
    """CREATE TABLE business_projects (
        id TEXT PRIMARY KEY, department_id TEXT NOT NULL REFERENCES departments(id),
        owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
        visibility TEXT NOT NULL DEFAULT 'private'
            CHECK(visibility IN ('private','department_readonly','company_readonly')),
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)))""",
    """CREATE TABLE business_project_members (
        project_id TEXT NOT NULL REFERENCES business_projects(id), user_id TEXT NOT NULL REFERENCES users(id),
        can_write INTEGER NOT NULL DEFAULT 0 CHECK(can_write IN (0,1)), PRIMARY KEY(project_id,user_id))""",
    """CREATE TABLE credential_sources (
        id TEXT PRIMARY KEY, provider_id TEXT NOT NULL, name TEXT NOT NULL,
        scope TEXT NOT NULL CHECK(scope IN ('company','department')),
        department_id TEXT REFERENCES departments(id),
        procurement TEXT NOT NULL CHECK(procurement IN ('company','department')),
        account_ref TEXT NOT NULL, current_revision TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
        CHECK((scope='company' AND department_id IS NULL AND procurement='company')
            OR (scope='department' AND department_id IS NOT NULL)))""",
    """CREATE TABLE credential_revisions (
        id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES credential_sources(id),
        sealed_secret BLOB NOT NULL, created_at INTEGER NOT NULL)""",
    """CREATE TABLE credential_grants (
        source_id TEXT NOT NULL REFERENCES credential_sources(id), user_id TEXT NOT NULL REFERENCES users(id),
        PRIMARY KEY(source_id,user_id))""",
    """CREATE TABLE generation_billing_context (
        task_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
        department_id TEXT REFERENCES departments(id), project_id TEXT REFERENCES business_projects(id),
        source_id TEXT NOT NULL REFERENCES credential_sources(id),
        revision_id TEXT NOT NULL REFERENCES credential_revisions(id),
        snapshot_json TEXT NOT NULL, created_at INTEGER NOT NULL)""",
    """CREATE TABLE generation_cost_entries (
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES generation_billing_context(task_id),
        attempt_index INTEGER NOT NULL CHECK(attempt_index>=0), event_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('estimate','charge','refund','adjustment','unknown')),
        amount TEXT, unit TEXT, receipt_ref TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,
        UNIQUE(task_id,attempt_index,event_id))""",
    """CREATE TABLE department_budgets (
        department_id TEXT NOT NULL REFERENCES departments(id), period TEXT NOT NULL,
        starts_at INTEGER NOT NULL, ends_at INTEGER NOT NULL CHECK(ends_at>starts_at),
        unit TEXT NOT NULL, amount TEXT NOT NULL,
        PRIMARY KEY(department_id,period,unit))""",
    "CREATE INDEX idx_billing_department ON generation_billing_context(department_id,created_at)",
    "CREATE INDEX idx_cost_task ON generation_cost_entries(task_id,created_at)",
)

DDL += tuple(
    f"CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} ON {table} "
    f"BEGIN SELECT RAISE(ABORT,'business facts are append-only'); END"
    for table in ('credential_revisions', 'generation_billing_context', 'generation_cost_entries')
    for operation in ('UPDATE', 'DELETE')
)


def apply_in_transaction(conn: sqlite3.Connection) -> None:
    if not conn.in_transaction:
        raise RuntimeError('DEPARTMENT_MIGRATION_TRANSACTION_REQUIRED')
    for sql in DDL:
        conn.execute(sql)


def validate_in_transaction(conn: sqlite3.Connection) -> bool:
    # Compare actual SQL, not just table presence. No IF NOT EXISTS adoption.
    for sql in DDL:
        name = sql.split()[2]
        row = conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        if not row or ' '.join(row[0].split()) != ' '.join(sql.split()):
            return False
    return conn.execute('PRAGMA foreign_key_check').fetchone() is None


def candidate_registry():
    from enterprise.migrations.versioned import DEFAULT_MIGRATIONS, MigrationStep
    step = MigrationStep('ice_department_costs_v3', 2, 3,
        hashlib.sha256('\n'.join(DDL).encode()).hexdigest(), apply_in_transaction, validate_in_transaction)
    return (*DEFAULT_MIGRATIONS, step)
