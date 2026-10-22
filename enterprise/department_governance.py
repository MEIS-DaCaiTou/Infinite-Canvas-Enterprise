"""Department, project and credential policy over one transactional repository.

No provider endpoints are configured here. Public methods return metadata only;
the internal task binding resolves one immutable credential revision. Budget
and cost operations live in the same database, never in a second task queue.
"""
from contextlib import contextmanager
import json
import re
import sqlite3
import time
import uuid

from enterprise import db
from enterprise.credential_vault import WindowsCredentialVault, VaultUnavailable
from enterprise.security_audit import append_security_audit_event, SecurityAuditError


class GovernanceError(RuntimeError):
    def __init__(self, code, status=400):
        self.code, self.status_code = code, status
        super().__init__(code)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', value):
        raise GovernanceError('INVALID_IDENTIFIER')
    return value


def label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 160 or any(ord(c) < 32 for c in value):
        raise GovernanceError('INVALID_LABEL')
    return value.strip()


def flag(value):
    if type(value) is not bool:
        raise GovernanceError('INVALID_BOOLEAN')
    return int(value)


def _member(conn, user_id):
    return conn.execute('SELECT m.* FROM department_members m JOIN departments d ON d.id=m.department_id '
                        'WHERE m.user_id=? AND d.active=1', (user_id,)).fetchone()


def _company(actor):
    return actor['role'] in {'admin', 'super_admin'}


def _manages(conn, actor, department_id):
    member = _member(conn, actor['id'])
    return _company(actor) or bool(member and member['department_id'] == department_id and member['manager'])


def _require(condition, code='DEPARTMENT_PERMISSION_DENIED', status=403):
    if not condition:
        raise GovernanceError(code, status)


def _audit(conn, actor, action, target_id):
    append_security_audit_event(connection=conn, action='business.governance.change', risk_level='L2', result='success',
        actor_type='user', actor_user_id=actor['id'], actor_role=actor['role'],
        operation_id=uuid.uuid4().hex, target_type='department_governance', target_id=target_id,
        context={'schema_version':3, 'operation':action})


class DepartmentGovernance:
    def __init__(self, connect=db.get_db, vault=None):
        self.connect, self.vault = connect, vault or WindowsCredentialVault()

    @contextmanager
    def session(self, principal, *, write=False):
        conn = self.connect()
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            # No implicit migration/adoption on a user request.
            ready = conn.execute("SELECT 1 FROM sqlite_master WHERE name='generation_billing_context'").fetchone()
            _require(ready, 'DEPARTMENT_SCHEMA_UPGRADE_REQUIRED', 503)
            user_id = principal.get('user_id') if isinstance(principal, dict) else None
            actor = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            version = principal.get('auth_version') if isinstance(principal, dict) else None
            _require(actor and actor['is_active'] and type(version) is int
                     and actor['auth_version'] == version, 'STALE_AUTHENTICATION', 401)
            yield conn, actor
            conn.commit()
        except (sqlite3.Error, SecurityAuditError) as exc:
            conn.rollback()
            raise GovernanceError('DEPARTMENT_STORAGE_UNAVAILABLE', 503) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def departments(self, principal):
        with self.session(principal) as (conn, actor):
            member = _member(conn, actor['id'])
            rows = conn.execute('SELECT * FROM departments WHERE active=1 ORDER BY name').fetchall()
            return [dict(row) for row in rows if _company(actor) or (member and row['id'] == member['department_id'])]

    def create_department(self, principal, name):
        name, department_id = label(name), uuid.uuid4().hex
        with self.session(principal, write=True) as (conn, actor):
            _require(_company(actor))
            conn.execute('INSERT INTO departments(id,name) VALUES (?,?)', (department_id, name))
            _audit(conn, actor, 'department_created', department_id)
        return {'id':department_id, 'name':name}

    def members(self, principal, department_id):
        with self.session(principal) as (conn, actor):
            _require(_manages(conn, actor, department_id))
            return [dict(row) for row in conn.execute(
                'SELECT m.user_id,m.department_id,m.manager,u.display_name,u.is_active FROM department_members m '
                'JOIN users u ON u.id=m.user_id WHERE department_id=? ORDER BY u.display_name', (department_id,))]

    def assign_member(self, principal, department_id, user_id, manager=False):
        department_id, user_id, manager = identifier(department_id), identifier(user_id), flag(manager)
        with self.session(principal, write=True) as (conn, actor):
            current = _member(conn, user_id)
            _require(_manages(conn, actor, department_id))
            # Transfers and manager appointments remain company administration.
            if not _company(actor):
                _require(current and current['department_id'] == department_id and current['manager'] == manager)
            _require(conn.execute('SELECT 1 FROM departments WHERE id=? AND active=1', (department_id,)).fetchone(),
                     'DEPARTMENT_NOT_FOUND', 404)
            _require(conn.execute('SELECT 1 FROM users WHERE id=? AND is_active=1', (user_id,)).fetchone(),
                     'MEMBER_NOT_FOUND', 404)
            conn.execute('DELETE FROM credential_grants WHERE user_id=? AND source_id IN '
                         "(SELECT id FROM credential_sources WHERE scope='department' AND department_id<>?)",
                         (user_id, department_id))
            conn.execute('INSERT INTO department_members(user_id,department_id,manager) VALUES (?,?,?) '
                         'ON CONFLICT(user_id) DO UPDATE SET department_id=excluded.department_id,manager=excluded.manager',
                         (user_id, department_id, manager))
            _audit(conn, actor, 'department_member_assigned', user_id)

    def remove_member(self, principal, department_id, user_id):
        with self.session(principal, write=True) as (conn, actor):
            member = _member(conn, user_id)
            _require(member and member['department_id'] == department_id and _manages(conn, actor, department_id))
            _require(_company(actor) or (not member['manager'] and user_id != actor['id']))
            conn.execute('DELETE FROM credential_grants WHERE user_id=? AND source_id IN '
                         "(SELECT id FROM credential_sources WHERE scope='department')", (user_id,))
            conn.execute('DELETE FROM department_members WHERE user_id=?', (user_id,))
            _audit(conn, actor, 'department_member_removed', user_id)

    def _project_access(self, conn, actor, project, *, write=False):
        if not project or not project['active']:
            return False
        if _company(actor):
            return True
        member = _member(conn, actor['id'])
        same = bool(member and member['department_id'] == project['department_id'])
        if same and (member['manager'] or project['owner_id'] == actor['id']):
            return True
        grant = conn.execute('SELECT can_write FROM business_project_members WHERE project_id=? AND user_id=?',
                             (project['id'], actor['id'])).fetchone()
        if same and grant and (not write or grant['can_write']):
            return True
        return not write and (project['visibility'] == 'company_readonly'
                              or (same and project['visibility'] == 'department_readonly'))

    def projects(self, principal):
        with self.session(principal) as (conn, actor):
            return [{**dict(row), 'can_write':self._project_access(conn, actor, row, write=True)}
                    for row in conn.execute('SELECT * FROM business_projects WHERE active=1 ORDER BY name')
                    if self._project_access(conn, actor, row)]

    def create_project(self, principal, department_id, name):
        department_id, name, project_id = identifier(department_id), label(name), uuid.uuid4().hex
        with self.session(principal, write=True) as (conn, actor):
            member = _member(conn, actor['id'])
            _require(_company(actor) or (member and member['department_id'] == department_id))
            _require(conn.execute('SELECT 1 FROM departments WHERE id=? AND active=1', (department_id,)).fetchone(),
                     'DEPARTMENT_NOT_FOUND', 404)
            conn.execute('INSERT INTO business_projects(id,department_id,owner_id,name) VALUES (?,?,?,?)',
                         (project_id, department_id, actor['id'], name))
            _audit(conn, actor, 'business_project_created', project_id)
        return {'id':project_id, 'name':name, 'visibility':'private'}

    def share_project(self, principal, project_id, visibility):
        if visibility not in {'private', 'department_readonly', 'company_readonly'}:
            raise GovernanceError('INVALID_PROJECT_VISIBILITY')
        with self.session(principal, write=True) as (conn, actor):
            row = conn.execute('SELECT * FROM business_projects WHERE id=? AND active=1', (project_id,)).fetchone()
            _require(row and (_manages(conn, actor, row['department_id']) or
                     (row['owner_id'] == actor['id'] and self._project_access(conn, actor, row, write=True))))
            conn.execute('UPDATE business_projects SET visibility=? WHERE id=?', (visibility, project_id))
            _audit(conn, actor, 'business_project_shared', project_id)

    def grant_project(self, principal, project_id, user_id, can_write):
        can_write = flag(can_write)
        with self.session(principal, write=True) as (conn, actor):
            project = conn.execute('SELECT * FROM business_projects WHERE id=? AND active=1', (project_id,)).fetchone()
            _require(project and (_manages(conn, actor, project['department_id']) or
                     (project['owner_id'] == actor['id'] and self._project_access(conn, actor, project, write=True))))
            member = _member(conn, user_id)
            _require(member and member['department_id'] == project['department_id'])
            conn.execute('INSERT INTO business_project_members(project_id,user_id,can_write) VALUES (?,?,?) '
                         'ON CONFLICT(project_id,user_id) DO UPDATE SET can_write=excluded.can_write',
                         (project_id, user_id, can_write))
            _audit(conn, actor, 'business_project_member_changed', project_id)

    def _source_access(self, conn, actor, source):
        if not source['enabled']:
            return False
        member = _member(conn, actor['id'])
        if source['scope'] == 'department' and (not member or member['department_id'] != source['department_id']):
            return False
        return bool(conn.execute('SELECT 1 FROM credential_grants WHERE source_id=? AND user_id=?',
                                 (source['id'], actor['id'])).fetchone())

    def sources(self, principal, *, manage=False):
        with self.session(principal) as (conn, actor):
            rows = conn.execute('SELECT * FROM credential_sources ORDER BY scope DESC,name').fetchall()
            if manage:
                return [dict(row) for row in rows if _company(actor) or
                        (row['scope'] == 'department' and _manages(conn, actor, row['department_id']))]
            return [dict(row) for row in rows if self._source_access(conn, actor, row)]

    def create_source(self, principal, *, provider_id, name, scope, department_id, procurement, account_ref, secret):
        provider_id, name, account_ref = identifier(provider_id), label(name), identifier(account_ref)
        if scope not in {'company', 'department'} or procurement not in {'company', 'department'}:
            raise GovernanceError('INVALID_CREDENTIAL_SCOPE')
        if scope == 'company' and (department_id is not None or procurement != 'company'):
            raise GovernanceError('INVALID_COMPANY_SOURCE')
        if scope == 'department':
            department_id = identifier(department_id)
        source_id, revision = uuid.uuid4().hex, uuid.uuid4().hex
        with self.session(principal, write=True) as (conn, actor):
            _require(_company(actor) if scope == 'company' else _manages(conn, actor, department_id))
            encrypted = self.vault.seal(secret, source_id + ':' + revision)
            conn.execute('INSERT INTO credential_sources '
                         '(id,provider_id,name,scope,department_id,procurement,account_ref,current_revision) '
                         'VALUES (?,?,?,?,?,?,?,?)',
                         (source_id, provider_id, name, scope, department_id, procurement, account_ref, revision))
            conn.execute('INSERT INTO credential_revisions VALUES (?,?,?,?)',
                         (revision, source_id, encrypted, int(time.time())))
            _audit(conn, actor, 'credential_source_created', source_id)
        return {'id':source_id, 'revision':revision, 'has_secret':True}

    def _managed_source(self, conn, actor, source_id):
        row = conn.execute('SELECT * FROM credential_sources WHERE id=?', (source_id,)).fetchone()
        _require(row and (_company(actor) if row['scope'] == 'company' else _manages(conn, actor, row['department_id'])))
        return row

    def rotate_source(self, principal, source_id, expected_revision, secret):
        revision = uuid.uuid4().hex
        with self.session(principal, write=True) as (conn, actor):
            source = self._managed_source(conn, actor, source_id)
            _require(source['current_revision'] == expected_revision, 'CREDENTIAL_REVISION_CONFLICT', 409)
            encrypted = self.vault.seal(secret, source_id + ':' + revision)
            conn.execute('INSERT INTO credential_revisions VALUES (?,?,?,?)',
                         (revision, source_id, encrypted, int(time.time())))
            conn.execute('UPDATE credential_sources SET current_revision=? WHERE id=?', (revision, source_id))
            _audit(conn, actor, 'credential_source_rotated', source_id)
        return {'id':source_id, 'revision':revision}

    def grant_source(self, principal, source_id, user_id, allowed):
        allowed = flag(allowed)
        with self.session(principal, write=True) as (conn, actor):
            source = self._managed_source(conn, actor, source_id)
            user = conn.execute('SELECT 1 FROM users WHERE id=? AND is_active=1', (user_id,)).fetchone()
            _require(user, 'MEMBER_NOT_FOUND', 404)
            member = _member(conn, user_id)
            if source['scope'] == 'department':
                _require(member and member['department_id'] == source['department_id'])
            if allowed:
                conn.execute('INSERT OR IGNORE INTO credential_grants VALUES (?,?)', (source_id, user_id))
            else:
                conn.execute('DELETE FROM credential_grants WHERE source_id=? AND user_id=?', (source_id, user_id))
            _audit(conn, actor, 'credential_grant_changed', source_id)

    def enable_source(self, principal, source_id, enabled):
        enabled = flag(enabled)
        with self.session(principal, write=True) as (conn, actor):
            self._managed_source(conn, actor, source_id)
            conn.execute('UPDATE credential_sources SET enabled=? WHERE id=?', (enabled, source_id))
            _audit(conn, actor, 'credential_source_enabled_changed', source_id)

    def accept_context(self, principal, *, task_id, provider_id, model, source_id=None, project_id=None, pricing_version=None, expected_attempts=1):
        task_id, provider_id, model = identifier(task_id), identifier(provider_id), label(model)
        if type(expected_attempts) is not int or not 1 <= expected_attempts <= 8:
            raise GovernanceError('INVALID_EXPECTED_ATTEMPTS')
        if pricing_version is not None:
            pricing_version = identifier(pricing_version)
        with self.session(principal, write=True) as (conn, actor):
            old = conn.execute('SELECT * FROM generation_billing_context WHERE task_id=?', (task_id,)).fetchone()
            if old:
                _require(old['user_id'] == actor['id'])
                snap = json.loads(old['snapshot_json'])
                _require(snap['provider_id'] == provider_id and snap['model'] == model
                         and (source_id is None or source_id == old['source_id']) and project_id == old['project_id']
                         and pricing_version == snap['pricing_version']
                         and expected_attempts == snap.get('expected_attempts',1),
                         'TASK_BILLING_CONTEXT_CONFLICT', 409)
                return snap
            member = _member(conn, actor['id'])
            if project_id:
                project = conn.execute('SELECT * FROM business_projects WHERE id=?', (identifier(project_id),)).fetchone()
                _require(self._project_access(conn, actor, project, write=True))
                # Company admins also need the matching business department when executing a project.
                _require(member and member['department_id'] == project['department_id'])
            sources = [r for r in conn.execute('SELECT * FROM credential_sources WHERE provider_id=? '
                       'ORDER BY scope DESC,name,id', (provider_id,)) if self._source_access(conn, actor, r)]
            chosen = next((r for r in sources if r['id'] == source_id), None) if source_id else next(iter(sources), None)
            _require(chosen, 'NO_AUTHORIZED_CALL_SOURCE', 403)
            revision = conn.execute('SELECT 1 FROM credential_revisions WHERE id=? AND source_id=?',
                                    (chosen['current_revision'], chosen['id'])).fetchone()
            _require(revision, 'CREDENTIAL_REVISION_UNAVAILABLE', 503)
            snap = {'task_id':task_id, 'user_id':actor['id'],
                    'department_id':member['department_id'] if member else None, 'project_id':project_id,
                    'provider_id':provider_id, 'model':model, 'source_id':chosen['id'],
                    'source_name':chosen['name'], 'scope':chosen['scope'], 'procurement':chosen['procurement'],
                    'account_ref':chosen['account_ref'], 'revision_id':chosen['current_revision']}
            snap['pricing_version'] = pricing_version  # Unknown pricing stays explicit; no guessed rate.
            snap['expected_attempts'] = expected_attempts
            conn.execute('INSERT INTO generation_billing_context VALUES (?,?,?,?,?,?,?,?)',
                (task_id, actor['id'], snap['department_id'], project_id, chosen['id'], chosen['current_revision'],
                 json.dumps(snap, ensure_ascii=False), int(time.time())))
            return snap

    def bound_secret(self, task_id):
        """Internal only: lookup by the persisted task, never by a caller's key ID.

        New-call permission is checked in accept_context. Querying an accepted
        task intentionally retains its original revision after rotation,
        transfer, or disabling the source. No HTTP route exposes this method.
        """
        conn = self.connect()
        try:
            row = conn.execute('SELECT c.source_id,c.revision_id,r.sealed_secret FROM generation_billing_context c '
                               'JOIN credential_revisions r ON r.id=c.revision_id AND r.source_id=c.source_id '
                               'WHERE c.task_id=?', (identifier(task_id),)).fetchone()
            _require(row, 'TASK_CREDENTIAL_BINDING_REQUIRED', 409)
            return self.vault.open(bytes(row[2]), row[0] + ':' + row[1])
        except VaultUnavailable as exc:
            raise GovernanceError('TASK_CREDENTIAL_UNAVAILABLE', 503) from exc
        finally:
            conn.close()
