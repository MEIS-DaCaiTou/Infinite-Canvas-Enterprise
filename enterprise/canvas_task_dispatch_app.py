"""Connect dispatch to existing ownership, generation policies and configuration."""
import asyncio
import os
from pathlib import Path
from fastapi import HTTPException

from enterprise import db, interceptors
from enterprise.canvas_image_recovery import provider_scope
from enterprise.canvas_task_dispatch import CanvasTaskDispatch, configuration_binding
from enterprise.providers.zhenzhen import is_zhenzhen
from enterprise.task_canvas_context import accepted_source
from enterprise.runtime.install_maintenance import maintenance_active

ROUTES = {"online-image": "api/canvas-image-tasks", "comfy": "api/canvas-comfy-tasks",
          "video": "api/canvas-video-tasks", "llm": "api/canvas-llm-tasks"}
OWNER_TYPES = {"online-image": "canvas_image", "comfy": "canvas_comfy", "video": "canvas_video", "llm": "canvas_llm"}


def dispatch_paused(state_root):
    # A single-hop target can be healthy before its update worker commits.
    # Do not start new billed work during health verification or rollback.
    try:
        return maintenance_active(state_root) or os.path.lexists(Path(state_root) / "system-update-active.lock")
    except OSError:
        return True


def create_dispatch(journal, models, runners, schedule, paused, *, secret, provider, headers, workflow, backend, default_model):
    def binding(kind, payload):
        try:
            if kind == "comfy":
                configured = workflow(payload.workflow_json)
                if not configured["config"].get("enabled", True):
                    return None
                scope = {"backend": backend(payload.workflow_json, payload.backend),
                         "workflow": configured["workflow"], "config": configured["config"]}
            else:
                selected = provider(payload.provider if kind == "llm" else payload.provider_id)
                if not is_zhenzhen(selected):
                    return None  # CLI/other suppliers retain their current path.
                model = payload.model or (default_model(kind, selected) if kind in {"llm", "online-image"} else "veo3-fast")
                scope = {**provider_scope(selected), "model": model, "headers": headers(provider=selected, model=model),
                         "model_protocol": selected.get("model_protocols", {}).get(model)}
                if kind == "online-image":
                    scope.update({key: selected.get(key) for key in (
                        "image_generation_endpoint", "image_edit_endpoint", "image_profile")})
                    scope["model_image_profile"] = selected.get("model_image_profiles", {}).get(model)
            return configuration_binding(secret, scope)
        except (HTTPException, ValueError, KeyError, OSError):
            return None

    async def validate(record, payload):
        owner = record.get("enterprise_user_id")
        user = await asyncio.to_thread(db.get_user_by_id, owner)
        if (not user or await asyncio.to_thread(db.get_task_owner, OWNER_TYPES[record["type"]], record["id"]) != owner
                or await asyncio.to_thread(db.get_canvas_image_task_owner, record["id"]) != owner):
            return False
        if record.get("source"):
            await asyncio.to_thread(accepted_source, record["source"], owner, journal.root.parent / "canvases")
        # Reuse the actual Gateway feature/resource checks immediately before
        # execution; restored inputs do not inherit stale access permissions.
        denied = await interceptors.pre_process(ROUTES[record["type"]], "POST",
            {**user, "user_id": owner}, {}, payload.model_dump_json().encode("utf8"))
        return denied is None

    return CanvasTaskDispatch(journal, models, runners, binding, validate, paused, schedule)
