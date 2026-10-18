"""Optional task provenance over existing canvas files and access policy."""
import json
import re
from urllib.parse import urlencode

from fastapi import HTTPException
from pydantic import BaseModel, Field

from enterprise import db


class TaskCanvasSource(BaseModel):
    canvas_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")
    node_id: str = Field(min_length=1, max_length=200)


def accessible_canvas(root, user_id, canvas_id):
    from enterprise.interceptors import can_access_canvas
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", canvas_id):
        raise HTTPException(400, "画布标识无效")
    user = db.get_user_by_id(user_id)
    if not user or not can_access_canvas({**user, 'user_id':user_id}, canvas_id):
        raise HTTPException(403, "画布不存在或不可访问")
    try:
        data = json.loads((root / (canvas_id + '.json')).read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise HTTPException(404, "画布不存在或已删除") from exc
    if data.get('id') != canvas_id or data.get('deleted_at'):
        raise HTTPException(404, "画布不存在或已删除")
    return data


def accepted_source(source, user_id, root):
    # Unauthenticated legacy loopback callers retain their existing behavior.
    if not source or not user_id:
        return None
    source = TaskCanvasSource.model_validate(source).model_dump()
    canvas = accessible_canvas(root, user_id, source['canvas_id'])
    if not any(node.get('id') == source['node_id'] for node in canvas.get('nodes', [])):
        raise HTTPException(409, "来源节点尚未保存或已删除，请保存画布后再运行")
    return source


def describe_source(source, user_id, root):
    if not source:
        return {'available':False, 'message':'此历史任务未记录来源画布'}
    try:
        canvas = accessible_canvas(root, user_id, source['canvas_id'])
    except HTTPException:
        return {'available':False, 'message':'来源画布已删除或当前不可访问'}
    node_available = any(node.get('id') == source.get('node_id') for node in canvas.get('nodes', []))
    page = 'smart-canvas' if canvas.get('kind') == 'smart' else 'canvas'
    params = {'id':canvas['id']}
    if node_available:
        params['focus_node'] = source['node_id']
    return {'available':True, 'node_available':node_available, 'canvas_id':canvas['id'],
        'title':canvas.get('title') or '画布', 'url':f'/static/{page}.html?' + urlencode(params),
        'message':'' if node_available else '原节点已删除，可打开来源画布'}
