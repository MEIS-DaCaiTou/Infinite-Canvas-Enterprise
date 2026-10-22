"""Project results over existing task receipts, ownership and frozen attribution.

Task details share outputs and link to authorized full source canvases. Reads
recheck access; explicit reuse copies bytes without submitting AI work.
"""
import json
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

from enterprise.config import PATH_ROOTS
from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.department_governance import GovernanceError, _company, _manages, _member, _require, _audit, identifier
from enterprise.generation_tasks import TYPES, describe_task, result_items


class ProjectResults:
    def __init__(self, service, roots=None, journal=None):
        self.service, self.roots = service, roots or PATH_ROOTS
        self.journal = journal or CanvasTaskJournal(self.roots.DATA_ROOT / 'canvas-tasks')

    @staticmethod
    def _project(conn, project_id):
        return conn.execute('SELECT * FROM business_projects WHERE id=?', (project_id,)).fetchone() if project_id else None

    def _readable(self, conn, actor, row):
        return (row['user_id'] == actor['id'] or _company(actor)
                or (row['department_id'] and _manages(conn, actor, row['department_id']))
                or self.service._project_access(conn, actor, self._project(conn, row['project_id'])))

    @staticmethod
    def _query():
        return ('SELECT t.task_id,t.task_type,t.user_id,c.department_id,c.project_id,u.display_name '
                'FROM user_task_map t JOIN users u ON u.id=t.user_id '
                'LEFT JOIN generation_billing_context c ON c.task_id=t.task_id AND c.user_id=t.user_id ')

    def _record(self, row):
        try:
            record = self.journal.get(row['task_id'])
        except (OSError, ValueError):
            return None
        if not record or record.get('type') != TYPES.get(row['task_type']) or record.get('enterprise_user_id', row['user_id']) != row['user_id']:
            return None
        return record

    def _metadata(self, row, record):
        summary = describe_task(record) if record else {'id':row['task_id'], 'status':'unavailable'}
        # Do not expose billing snapshots, provider receipts/errors or private inputs.
        return {**{k:summary.get(k) for k in ('id','type','status','created_at','updated_at','provider','model','output_count')},
                'owner_id':row['user_id'], 'owner_name':row['display_name'], 'project_id':row['project_id']}

    def page(self, principal, scope='me', department_id=None, project_id=None, member_id=None, before=None, canvas_id=None):
        if before is not None:
            before = identifier(before)
        with self.service.session(principal) as (conn, actor):
            member = _member(conn, actor['id'])
            if scope == 'department':
                department_id = department_id or (member['department_id'] if member else None)
                _require(department_id and (_company(actor) or (member and member['department_id'] == department_id)))
            _require(scope in {'me','department','company'}, 'INVALID_WORKSPACE_SCOPE', 400)
            clauses, params = ["t.task_type IN ('canvas_image','canvas_comfy','canvas_video','canvas_llm')"], []
            if project_id:
                project = self._project(conn, identifier(project_id))
                _require(self.service._project_access(conn, actor, project))
                clauses.append('c.project_id=?');params.append(project_id)
            elif scope == 'me':
                clauses.append('t.user_id=?');params.append(actor['id'])
            elif scope == 'department':
                clauses.append('c.department_id=?');params.append(department_id)
            if member_id:
                _require(_company(actor) or (scope == 'department' and _manages(conn, actor, department_id)))
                clauses.append('t.user_id=?');params.append(identifier(member_id))
            if before:
                clauses.append('t.rowid<(SELECT rowid FROM user_task_map WHERE task_id=? LIMIT 1)');params.append(before)
            # Permission filtering happens before paging, including public project readers.
            projects = [r['id'] for r in conn.execute('SELECT * FROM business_projects WHERE active=1')
                        if self.service._project_access(conn, actor, r) and (scope != 'company' or r['visibility'] == 'company_readonly')]
            if scope == 'company' and not _company(actor):
                clauses.append('c.project_id IN ('+','.join('?' for _ in projects)+')');params.extend(projects)
            elif scope == 'department' and not _manages(conn, actor, department_id):
                clauses.append('(t.user_id=? OR c.project_id IN ('+','.join('?' for _ in projects)+'))');params.extend([actor['id'], *projects])
            rows = conn.execute(self._query()+'WHERE '+' AND '.join(clauses)+' ORDER BY t.rowid DESC LIMIT 51', params).fetchall()
            results = []
            for row in rows[:50]:
                if not self._readable(conn, actor, row):
                    continue
                record = self._record(row)
                if canvas_id and (not record or (record.get('source') or {}).get('canvas_id') != canvas_id):
                    continue
                results.append(self._metadata(row, record))
            return {'tasks':results, 'next_cursor':rows[49]['task_id'] if len(rows)>50 else None}

    def _authorized(self, conn, actor, task_id):
        rows = conn.execute(self._query()+'WHERE t.task_id=?', (identifier(task_id),)).fetchall()
        for row in rows:
            if row['task_type'] in TYPES and self._readable(conn, actor, row):
                record = self._record(row)
                _require(record, 'RESULT_RECEIPT_UNAVAILABLE', 503)
                return row, record
        raise GovernanceError('PROJECT_RESULT_NOT_FOUND', 404)

    def detail(self, principal, task_id):
        with self.service.session(principal) as (conn, actor):
            row, record = self._authorized(conn, actor, task_id)
            items = result_items(record)
            data = self._metadata(row, record)
            data['items'] = [{**{k:v for k,v in item.items() if k in {'kind','name','text','result_id','run_id'}},
                'index':i, 'key':item.get('result_id') or item['url'],
                'url':f'/enterprise/api/business/workspace/tasks/{task_id}/outputs/{i}'} for i,item in enumerate(items)]
            data['source'] = {'available':False}
            if row['user_id'] == actor['id'] or _company(actor):
                from enterprise.task_canvas_context import describe_source
                data['source'] = describe_source(record.get('source'), actor['id'], self.roots.DATA_ROOT/'canvases')
            elif record.get('source'):
                from enterprise.shared_canvases import SharedCanvases
                from urllib.parse import urlencode
                try:
                    canvas = SharedCanvases(self.service,self.roots)._document(conn,actor,record['source']['canvas_id'])
                    page = 'smart-canvas' if canvas.get('kind') == 'smart' else 'canvas'
                    data['source'] = {'available':True,'url':f'/static/{page}.html?'+urlencode({'id':canvas['id'],'readonly':'1'})}
                except GovernanceError:
                    pass  # A project result does not publish its unassociated personal source canvas.
            return data

    def _output(self, item):
        path = unquote(urlsplit(item['url']).path).replace('\\','/')
        if path.startswith('/assets/output/'):
            root, name = self.roots.UPLOAD_ROOT/'assets'/'output', path[len('/assets/output/'):]
        elif path.startswith('/output/'):
            root, name = self.roots.UPLOAD_ROOT/'output', path[len('/output/'):]
        else:
            raise GovernanceError('RESULT_FILE_UNAVAILABLE', 404)
        root = root.resolve(); file = (root/name).resolve()
        _require(file.is_relative_to(root) and file.is_file(), 'RESULT_FILE_UNAVAILABLE', 404)
        return file

    def output(self, principal, task_id, index):
        with self.service.session(principal) as (conn, actor):
            _, record = self._authorized(conn, actor, task_id)
            items = result_items(record)
            _require(type(index) is int and 0 <= index < len(items), 'RESULT_FILE_UNAVAILABLE', 404)
            return self._output(items[index])

    def reuse(self, principal, task_id, keys):
        _require(isinstance(keys,list) and 0 < len(keys) <= 50
                 and all(isinstance(key,str) for key in keys), 'INVALID_RESULT_SELECTION', 400)
        copies = []
        try:
            with self.service.session(principal, write=True) as (conn, actor):
                _, record = self._authorized(conn, actor, task_id)
                items = {item.get('result_id') or item['url']:item for item in result_items(record)}
                _require(all(key in items for key in keys), 'INVALID_RESULT_SELECTION', 400)
                target = self.roots.UPLOAD_ROOT/'assets'/'output'/'reused';target.mkdir(parents=True, exist_ok=True)
                output = []
                for key in dict.fromkeys(keys):
                    item = items[key];source = self._output(item)
                    _require(item.get('kind') in {'image','video','audio','text'} and source.suffix.lower() in
                             {'.png','.jpg','.jpeg','.webp','.gif','.bmp','.mp4','.webm','.mov','.mp3','.wav','.ogg','.txt'},
                             'RESULT_REUSE_UNSUPPORTED', 400)
                    dest = target/(uuid.uuid4().hex+source.suffix.lower());copies.append(dest)
                    shutil.copyfile(source,dest)
                    url = '/assets/output/reused/'+dest.name
                    conn.execute('INSERT INTO user_resource_map(user_id,resource_url,source,created_at) VALUES (?,?,?,?)',
                                 (actor['id'],url,'project_result_reuse',int(time.time()*1000)))
                    output.append({**item, 'url':url, 'sourceTaskId':task_id,
                                   **({'text':dest.read_text(encoding='utf8')} if item.get('kind') == 'text' else {})})
                _audit(conn, actor, 'project_result_reused', task_id)
                return {'items':output, 'task_id':task_id}
        except Exception:
            for file in copies:
                file.unlink(missing_ok=True)
            raise
