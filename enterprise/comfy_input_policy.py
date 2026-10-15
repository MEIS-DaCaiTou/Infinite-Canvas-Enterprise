"""Authorize mapped Comfy input filenames using the existing resource policy."""
from urllib.parse import urlsplit

from fastapi import HTTPException

from enterprise import db
from enterprise.providers.comfy_workflow import workflow_media_names


def authorize_workflow_media(user_id, workflow, config, values):
    # Empty identity is the existing trusted loopback/direct application mode.
    # Gateway always replaces this private execution identity from its session.
    if not user_id:
        return
    from enterprise.interceptors import can_access_resource, _input_resource_url_from_name, _clean_relative_path
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(403, "工作流调用身份不可用")
    actor = {**user, "user_id": user_id}
    for name in workflow_media_names(workflow, config, values):
        resource = _input_resource_url_from_name(name)
        if not resource:
            parsed = urlsplit(name)
            relative = _clean_relative_path(name)
            if parsed.scheme or parsed.netloc or not relative:
                raise HTTPException(403, "工作流输入素材不可访问")
            resource = "/assets/input/" + relative
        if not can_access_resource(actor, resource):
            raise HTTPException(403, "工作流输入素材不可访问")
