"""Permission-filtered canvas directory over existing ownership and files.

This is directory metadata, not a new editor, task queue or content grant.
Joining a department project exposes directory metadata only. Full shared
canvas/result preview remains a separate, explicit content-authority path.
"""
import json
from contextlib import closing
from pathlib import Path

from enterprise.config import PATH_ROOTS
from enterprise.department_governance import GovernanceError, _audit, _company, _manages, _member, _require, flag, identifier


def _json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


class CanvasWorkspace:
    def __init__(self, governance, data_root=None):
        self.governance = governance
        self.root = Path(data_root or PATH_ROOTS.DATA_ROOT)

    @staticmethod
    def _ready(conn):
        _require(conn.execute("SELECT 1 FROM sqlite_master WHERE name='canvas_workspace_projects'").fetchone(),
                 'CANVAS_WORKSPACE_UPGRADE_REQUIRED', 503)

    def context(self, principal):
        context = self.governance.workspace(principal)
        if not context['enabled']:
            return context
        with self.governance.session(principal) as (conn, actor):
            ready = conn.execute("SELECT 1 FROM sqlite_master WHERE name='canvas_workspace_projects'").fetchone()
        return {**context, 'enabled':bool(ready), 'reason':'' if ready else 'CANVAS_WORKSPACE_UPGRADE_REQUIRED'}

    def check_canvas_target(self, principal, target_id, source_id=None, creating=False):
        """Apply project membership to new directory associations in old routes.

        Unchanged folder metadata/content edits retain original ownership rules.
        Old schemas do not activate this feature or change their contract.
        """
        with closing(self.governance.connect()) as conn:
            ready = conn.execute("SELECT 1 FROM sqlite_master WHERE name='canvas_workspace_projects'").fetchone()
        if not ready or (not creating and target_id == source_id):
            return
        with self.governance.session(principal) as (conn, actor):
            folders = self._folders(conn)
            target = folders.get(target_id)
            if creating and target:
                _require(target['owner_id'] == actor['id'], 'WORKSPACE_CREATE_IN_OWN_FOLDER')
            for folder_id in {target_id, source_id} - {None, '', 'default'}:
                folder = folders.get(folder_id)
                if not folder:
                    continue  # Existing route checks still govern ordinary ownership/existence.
                business_id, _ = self._effective(folders, folder_id)
                if business_id:
                    project = conn.execute('SELECT * FROM business_projects WHERE id=?', (business_id,)).fetchone()
                    _require(self.governance._project_access(conn, actor, project, write=True))

    def _folders(self, conn):
        raw = _json(self.root / 'projects.json', {})
        names = raw.get('projects', []) if isinstance(raw, dict) else raw
        names = {str(p['id']):p for p in names if isinstance(p, dict) and p.get('id')} if isinstance(names, list) else {}
        details = {r['project_id']:dict(r) for r in conn.execute('SELECT * FROM canvas_workspace_projects')}
        result = {}
        for row in conn.execute('SELECT * FROM user_project_map'):
            if row['project_id'] not in names or row['project_id'] == 'default':
                continue
            detail = details.get(row['project_id'], {})
            if detail.get('owner_id') != row['user_id']:
                detail = {}
            result[row['project_id']] = {
                'id':row['project_id'], 'owner_id':row['user_id'],
                'name':str(names[row['project_id']].get('name') or '未命名文件夹'),
                'parent_id':row['parent_project_id'],
                'business_project_id':detail.get('business_project_id'),
                'own_archived':bool(detail.get('archived')),
            }
        return result

    @staticmethod
    def _chain(folders, folder_id):
        chain, seen = [], set()
        while folder_id in folders:
            _require(folder_id not in seen, 'WORKSPACE_FOLDER_CYCLE', 409)
            seen.add(folder_id)
            folder = folders[folder_id]
            if chain and folder['owner_id'] != chain[0]['owner_id']:
                break
            chain.append(folder)
            folder_id = folder['parent_id']
        return chain

    def _effective(self, folders, folder_id):
        chain = self._chain(folders, folder_id)
        return (next((p['business_project_id'] for p in chain if p['business_project_id']), None),
                any(p['own_archived'] for p in chain))

    def listing(self, principal, scope='me', department_id=None, member_id=None):
        _require(scope in {'me','department','company'}, 'INVALID_WORKSPACE_SCOPE', 400)
        with self.governance.session(principal) as (conn, actor):
            self._ready(conn)
            member = _member(conn, actor['id'])
            if scope == 'department':
                department_id = department_id or (member['department_id'] if member else None)
                _require(department_id and (_company(actor) or
                         (member and member['department_id'] == department_id)))
            manages = _company(actor) or bool(scope == 'department' and _manages(conn, actor, department_id))
            if member_id:
                _require(manages)
                member_id = identifier(member_id)
            people = {r['id']:dict(r) for r in conn.execute(
                'SELECT u.id,u.display_name,m.department_id FROM users u LEFT JOIN department_members m ON m.user_id=u.id')}
            projects = {r['id']:dict(r) for r in conn.execute('SELECT * FROM business_projects WHERE active=1')}
            folders = self._folders(conn)

            def visible(owner, project_id):
                if member_id and owner != member_id:
                    return False
                if scope == 'me':
                    return owner == actor['id']
                project = projects.get(project_id)
                if scope == 'company' and _company(actor):
                    return True  # Existing administrator ownership authority, not a department grant.
                if not project or not self.governance._project_access(conn, actor, project):
                    return False
                return (project['department_id'] == department_id if scope == 'department'
                        else project['visibility'] == 'company_readonly')

            items, directory = [], []
            for folder in folders.values():
                business_id, archived = self._effective(folders, folder['id'])
                if not visible(folder['owner_id'], business_id):
                    continue
                project = projects.get(business_id)
                directory.append({**folder, 'business_project_id':business_id, 'archived':archived,
                    'can_manage':bool((folder['owner_id'] == actor['id'] or _company(actor)) and
                        (not project or self.governance._project_access(conn, actor, project, write=True)))})
            owners = {r['canvas_id']:r['user_id'] for r in conn.execute('SELECT * FROM user_canvas_map')}
            states = {r['canvas_id']:dict(r) for r in conn.execute('SELECT * FROM canvas_workspace_canvases')}
            for canvas_id, owner in owners.items():
                # IDs come from the ownership repository; validate before filesystem use.
                if Path(canvas_id).name != canvas_id or '/' in canvas_id or '\\' in canvas_id:
                    continue
                if scope == 'me' and owner != actor['id']:
                    continue
                data = _json(self.root / 'canvases' / (canvas_id + '.json'), {})
                if not isinstance(data, dict) or data.get('deleted_at'):
                    continue
                if not data or str(data.get('id') or canvas_id) != canvas_id:
                    continue
                folder_id = str(data.get('project') or 'default')
                folder = folders.get(folder_id)
                # A foreign/stale JSON project reference cannot confer business access.
                if folder and folder['owner_id'] != owner:
                    folder = None
                business_id, archived = self._effective(folders, folder['id']) if folder else (None, False)
                if not visible(owner, business_id):
                    continue
                state = states.get(canvas_id, {})
                own_archived = bool(state.get('archived') and state.get('owner_id') == owner)
                editable = bool(owner == actor['id'] or _company(actor))
                thumbnail = next((n.get('url') for n in data.get('nodes', []) if isinstance(n, dict)
                    and n.get('type') == 'image' and isinstance(n.get('url'), str)
                    and n['url'].startswith(('/assets/','/output/')) and not n['url'].lower().split('?')[0].endswith(('.mp4','.webm','.mov','.mp3','.wav'))), '') if editable else ''
                items.append({'id':canvas_id, 'title':str(data.get('title') or '未命名画布'),
                    'kind':'smart' if data.get('kind') == 'smart' else 'classic',
                    'folder_id':folder['id'] if folder else 'default:'+owner,
                    'project':folder_id, 'business_project_id':business_id,
                    'owner_id':owner, 'owner_name':people.get(owner, {}).get('display_name', owner),
                    'archived':bool(archived or own_archived), 'own_archived':own_archived,
                    'node_count':len(data.get('nodes', [])),
                    'updated_at':data.get('updated_at', 0), 'created_at':data.get('created_at', 0),
                    'can_edit':editable, 'thumbnail_url':thumbnail})
            roots = {r['owner_id'] for r in items if r['folder_id'].startswith('default:')}
            if scope == 'me':
                roots.add(actor['id'])
            directory.extend({'id':'default:'+owner,'name':'默认项目','owner_id':owner,'parent_id':None,
                'business_project_id':None,'archived':False,'own_archived':False,'can_manage':False}
                for owner in roots)
            for folder in directory:
                folder['owner_name'] = people.get(folder['owner_id'], {}).get('display_name', folder['owner_id'])
            allowed_projects = [dict(p, can_write=self.governance._project_access(conn, actor, p, write=True))
                for p in projects.values() if self.governance._project_access(conn, actor, p) and
                (scope == 'me' or (p['department_id'] == department_id if scope == 'department' else
                                  (_company(actor) or p['visibility'] == 'company_readonly')))]
            members = [p for p in people.values() if scope == 'company' or p['department_id'] == department_id] if manages and scope != 'me' else []
            return {'folders':directory,'canvases':items,'projects':allowed_projects,'members':members,
                    'can_filter_members':bool(manages and scope != 'me')}

    def update_folder(self, principal, folder_id, parent_id=None, business_project_id=None, archived=False):
        folder_id, archived = identifier(folder_id), flag(archived)
        with self.governance.session(principal, write=True) as (conn, actor):
            self._ready(conn)
            folders = self._folders(conn)
            folder = folders.get(folder_id)
            _require(folder and (folder['owner_id'] == actor['id'] or _company(actor)))
            if parent_id:
                parent_id = identifier(parent_id)
                parent = folders.get(parent_id)
                _require(parent and parent['owner_id'] == folder['owner_id'])
                _require(folder_id not in {p['id'] for p in self._chain(folders, parent_id)}, 'WORKSPACE_FOLDER_CYCLE', 409)
                inherited, _ = self._effective(folders, parent_id)
                _require(not business_project_id or business_project_id == inherited, 'WORKSPACE_PROJECT_PARENT_MISMATCH', 409)
                business_project_id = inherited
            if business_project_id:
                business_project_id = identifier(business_project_id)
                project = conn.execute('SELECT * FROM business_projects WHERE id=?', (business_project_id,)).fetchone()
                _require(self.governance._project_access(conn, actor, project, write=True))
                member = _member(conn, folder['owner_id'])
                _require(member and member['department_id'] == project['department_id'], 'WORKSPACE_OWNER_DEPARTMENT_MISMATCH', 409)
            # Check the previous target too; changing parents is not a way around revoked membership.
            previous, _ = self._effective(folders, folder_id)
            if previous:
                old = conn.execute('SELECT * FROM business_projects WHERE id=?', (previous,)).fetchone()
                _require(self.governance._project_access(conn, actor, old, write=True))
            conn.execute('UPDATE user_project_map SET parent_project_id=? WHERE project_id=?', (parent_id, folder_id))
            conn.execute('INSERT INTO canvas_workspace_projects VALUES (?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET '
                'owner_id=excluded.owner_id,business_project_id=excluded.business_project_id,archived=excluded.archived',
                (folder_id, folder['owner_id'], None if parent_id else business_project_id, archived))
            _audit(conn, actor, 'canvas_workspace_folder_updated', folder_id)
        return {'ok':True}

    def archive(self, principal, canvas_ids, archived):
        archived = flag(archived)
        _require(isinstance(canvas_ids, list) and 0 < len(canvas_ids) <= 100, 'INVALID_WORKSPACE_SELECTION', 400)
        canvas_ids = list(dict.fromkeys(identifier(value) for value in canvas_ids))
        with self.governance.session(principal, write=True) as (conn, actor):
            self._ready(conn)
            for canvas_id in canvas_ids:
                row = conn.execute('SELECT user_id FROM user_canvas_map WHERE canvas_id=?', (canvas_id,)).fetchone()
                _require(row and (row[0] == actor['id'] or _company(actor)))
                conn.execute('INSERT INTO canvas_workspace_canvases VALUES (?,?,?) ON CONFLICT(canvas_id) DO UPDATE SET '
                    'owner_id=excluded.owner_id,archived=excluded.archived', (canvas_id, row[0], archived))
            _audit(conn, actor, 'canvas_workspace_archive_changed', canvas_ids[0])
        return {'ok':True,'count':len(canvas_ids)}
