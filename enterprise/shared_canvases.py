"""Read-only project canvases and explicit private copies; no generation calls."""
import json
import shutil
import time
import uuid
from urllib.parse import quote, unquote, urlsplit

from enterprise.canvas_workspace import CanvasWorkspace
from enterprise.config import PATH_ROOTS
from enterprise.department_governance import _require, _company, _audit, identifier
from enterprise.runtime.logging import redact_text


def public_document(value, *, copying=False):
    if isinstance(value, list):
        return [public_document(v, copying=copying) for v in value]
    if isinstance(value, dict):
        result = {}
        for key,item in value.items():
            normalized = str(key).strip().lower().replace('_','').replace('-','')
            if normalized in {'authorization','cookie','token','auth','credential','credentials','session','key'} or normalized.endswith(
                    ('apikey','apikeys','password','secret','accesstoken','refreshtoken')):
                if not copying:
                    result[key] = '[REDACTED]'
            elif copying and (key.startswith('_') or key in {'pendingTasks','llmTask','jimengPending','callSources','businessProjectId',
                    'canvasTaskId','upstreamTaskId','recoverTaskId','task_id','upstream_task_id','provider_receipts','billing_context'}):
                continue
            else:
                result[key] = False if copying and key in {'running','querying'} else public_document(item, copying=copying)
        return result
    return redact_text(value) if isinstance(value,str) else value


def resource_urls(value, parent=''):
    from enterprise.interceptors import normalize_resource_url
    found = set()
    if isinstance(value,dict):
        for key,child in value.items():
            found.update(resource_urls(child,key))
    elif isinstance(value,list):
        for child in value:
            found.update(resource_urls(child,parent))
    elif isinstance(value,str) and parent.lower() in {'url','src','preview','thumbnail','images','urls','refurls','refimages','image','video','audio'}:
        url=normalize_resource_url(value)
        if url.startswith(('/assets/','/output/')):
            found.add(url)
    return found


def replace_urls(value, mapping):
    from enterprise.interceptors import normalize_resource_url
    if isinstance(value,dict):
        return {k:replace_urls(v,mapping) for k,v in value.items()}
    if isinstance(value,list):
        return [replace_urls(v,mapping) for v in value]
    if isinstance(value,str):
        return mapping.get(normalize_resource_url(value),value)
    return value


class SharedCanvases:
    def __init__(self, service, roots=None):
        self.service,self.roots=service,roots or PATH_ROOTS
        self.workspace=CanvasWorkspace(service,self.roots.DATA_ROOT)

    def _document(self, conn, actor, canvas_id):
        canvas_id=identifier(canvas_id)
        owner=conn.execute('SELECT user_id FROM user_canvas_map WHERE canvas_id=?',(canvas_id,)).fetchone()
        _require(owner,'SHARED_CANVAS_NOT_FOUND',404)
        try:
            data=json.loads((self.roots.DATA_ROOT/'canvases'/(canvas_id+'.json')).read_text(encoding='utf8'))
        except (OSError,ValueError):
            _require(False,'SHARED_CANVAS_NOT_FOUND',404)
        _require(data.get('id')==canvas_id and not data.get('deleted_at'),'SHARED_CANVAS_NOT_FOUND',404)
        if owner[0]!=actor['id'] and not _company(actor):
            self.workspace._ready(conn)
            folders=self.workspace._folders(conn);folder=folders.get(data.get('project'))
            _require(folder and folder['owner_id']==owner[0],'SHARED_CANVAS_NOT_FOUND',404)
            project_id,_=self.workspace._effective(folders,folder['id'])
            project=conn.execute('SELECT * FROM business_projects WHERE id=?',(project_id,)).fetchone()
            _require(self.service._project_access(conn,actor,project),'SHARED_CANVAS_NOT_FOUND',404)
        return {k:data[k] for k in ('id','title','kind','nodes','connections','viewport','settings','created_at','updated_at') if k in data}

    def detail(self, principal, canvas_id):
        with self.service.session(principal) as (conn,actor):
            data=public_document(self._document(conn,actor,canvas_id))
            urls=sorted(resource_urls(data))
            mapping={url:f'/enterprise/api/business/workspace/canvases/{canvas_id}/resources/{i}/'+
                     quote(unquote(urlsplit(url).path).rsplit('/',1)[-1],safe='') for i,url in enumerate(urls)}
            return {'canvas':replace_urls(data,mapping),'readonly':True}

    def _file(self,url):
        # resource_urls already normalizes/decodes once. Do not decode a second
        # time, and keep every file inside its original media subtree.
        path=urlsplit(url).path.replace('\\','/')
        prefix=next((p for p in ('/assets/input/','/assets/output/','/assets/uploads/',
            '/assets/library/','/assets/images/','/output/') if path.startswith(p)),None)
        _require(prefix,'RESULT_FILE_UNAVAILABLE',404)
        root=(self.roots.UPLOAD_ROOT/prefix.lstrip('/')).resolve()
        file=(root/path[len(prefix):]).resolve()
        _require(file.is_relative_to(root) and file.is_file(),'RESULT_FILE_UNAVAILABLE',404)
        return file

    def resource(self, principal, canvas_id, index):
        with self.service.session(principal) as (conn,actor):
            data=public_document(self._document(conn,actor,canvas_id));urls=sorted(resource_urls(data))
            _require(0<=index<len(urls),'RESULT_FILE_UNAVAILABLE',404)
            return self._file(urls[index])

    def reuse(self,principal,canvas_id):
        copies=[]
        try:
            with self.service.session(principal,write=True) as (conn,actor):
                data=public_document(self._document(conn,actor,canvas_id),copying=True)
                target=self.roots.UPLOAD_ROOT/'assets'/'output'/'reused';target.mkdir(parents=True,exist_ok=True)
                mapping={}
                for url in sorted(resource_urls(data)):
                    source=self._file(url)
                    _require(source.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.gif','.bmp','.mp4','.webm','.mov',
                        '.mp3','.wav','.ogg','.txt','.pdf','.zip'},'RESULT_REUSE_UNSUPPORTED',400)
                    # Copy referenced assets; byte identity is independent of the source project grant.
                    dest=target/(uuid.uuid4().hex+source.suffix.lower());copies.append(dest);shutil.copyfile(source,dest)
                    new_url='/assets/output/reused/'+dest.name;mapping[url]=new_url
                    conn.execute('INSERT INTO user_resource_map(user_id,resource_url,source,created_at) VALUES (?,?,?,?)',
                        (actor['id'],new_url,'shared_canvas_reuse',int(time.time()*1000)))
                _audit(conn,actor,'shared_canvas_reused',canvas_id)
                return {'canvas':replace_urls(data,mapping)}
        except Exception:
            for path in copies:path.unlink(missing_ok=True)
            raise
