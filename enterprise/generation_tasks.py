"""Read-only task catalog over existing owned receipts; never submits provider work."""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from enterprise import db
from enterprise.canvas_image_recovery import can_reconcile
from enterprise.canvas_video_tasks import can_reconcile_video
from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.accepted_task_recovery import recovery_candidate
from enterprise.runtime.logging import redact_text

TYPES = {"canvas_image": "online-image", "canvas_comfy": "comfy", "canvas_video": "video", "canvas_llm": "llm"}
STATES = {"queued", "running", "succeeded", "failed", "cancelled", "unknown", "partial", "unavailable"}


def task_state(record):
    state = record.get("status")
    if state in {"succeeded", "cancelled"}:
        return state
    if state in {"queued", "running", "jimeng_pending"}:
        return "queued" if state == "queued" else "running"
    receipts = record.get("provider_receipts") or []
    if any((item.get("result") or {}).get("images") or (item.get("result") or {}).get("videos") for item in receipts):
        return "partial"
    if receipts and all(item.get("state") == "failed" for item in receipts):
        return "failed"
    query, automatic = record.get("reconciliation") or {}, record.get("auto_recovery") or {}
    if (recovery_candidate(record) and automatic.get("status") in {"waiting", "querying"}
            and query.get("started_at", 0) >= automatic.get("last_query_at", float("inf"))
            and query.get("status") in {"queued", "running"}):
        return query["status"]
    if record.get("recovery_required") or any(item.get("state") in {"accepted", "unknown", "generated", "submitting"} for item in receipts):
        return "unknown"
    return "failed"


def result_items(record):
    from enterprise.providers.image_outputs import layer_metadata
    result = record.get("result") or {}
    items = list(result.get("items") or [])
    if not items:
        items.extend(result.get("image_items") or [])
        for key, kind in (("images", "image"), ("videos", "video"), ("audios", "audio"), ("texts", "text"), ("files", "file")):
            items.extend({"url": item, "kind": kind} if isinstance(item, str) else {"kind": kind, **item}
                         for item in result.get(key) or [])
        if not items and isinstance(result.get("image"), str):
            items.append({"url": result["image"], "kind": "image"})
    for attempt in record.get("provider_receipts") or []:
        items.extend((attempt.get("result") or {}).get("image_items") or [])
        for key, kind in (("images", "image"), ("videos", "video")):
            items.extend({"url": value, "kind": kind} for value in (attempt.get("result") or {}).get(key, []))
    unique = {}
    for item in items:
        if isinstance(item, str):
            item = {"url": item, "kind": "image"}
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        parsed = urlsplit(url)
        path = unquote(parsed.path).replace("\\", "/")
        if parsed.scheme or parsed.netloc or not path.startswith(("/assets/output/", "/output/")) or ".." in path.split("/"):
            continue
        unique.setdefault(url, {**{key: item[key] for key in ("url", "kind", "name", "text", "result_id", "run_id", "created_at") if key in item}, **layer_metadata(item)})
    return list(unique.values())


def describe_task(record, *, detail=False):
    state = task_state(record)
    comfy = record.get("comfy_receipt") or {}
    can_query = (can_reconcile_video(record) if record.get("type") == "video" else
                 can_reconcile(record) if record.get("type") == "online-image" else
                 bool(comfy.get("prompt_id") and record.get("status") == "failed" and record.get("recovery_required")))
    if record.get("type") == "llm":
        from enterprise.canvas_llm_tasks import can_restore_llm
        can_query = can_restore_llm(record)
    items = result_items(record)
    first = next(iter(record.get("provider_receipts") or []), {})
    data = {"id": record["id"], "type": record.get("type"), "status": state,
            "created_at": record.get("created_at"), "updated_at": record.get("updated_at"),
            "provider": record.get("provider_id") or first.get("provider_id") or ("ComfyUI" if record.get("type") == "comfy" else ""),
            "model": record.get("model") or first.get("model") or "", "workflow": record.get("workflow_json") or "",
            "output_count": len(items), "can_query": can_query,
            "error": redact_text(record.get("error") or "")[:1200]}
    automatic = record.get("auto_recovery") or {}
    if automatic:
        data["auto_recovery"] = {key: automatic[key] for key in (
            "status", "count", "last_query_at", "next_query_at", "reason") if key in automatic}
        if state in {"succeeded", "failed", "partial", "cancelled"} and not recovery_candidate(record):
            data["auto_recovery"].update(status="complete", next_query_at=None, reason="")
    if detail:
        snapshot = (record.get('billing_context') or {}).get('snapshot')
        if snapshot:
            data['call_source'] = {key:snapshot.get(key) for key in (
                'source_id','source_name','scope','procurement','department_id','project_id','account_ref','pricing_version')}
        receipts = record.get("provider_receipts") or ([comfy] if comfy else [])
        data["attempts"] = [{"id": f"{record['id']}:{index}", "index": index,
            "status": state if record.get("type") == "comfy" and state not in {"queued", "running"} else item.get("state") or item.get("phase") or state,
            "upstream_task_id": item.get("upstream_task_id") or item.get("prompt_id") or "",
            "started_at": item.get("started_at"), "accepted_at": item.get("accepted_at"),
            "finished_at": item.get("finished_at"), "reported_usage": item.get("reported_usage"),
            "provider": item.get("provider_id") or data["provider"], "model": item.get("model") or data["model"],
            "error": redact_text(item.get("error") or "")[:1200]}
            for index, item in enumerate(receipts)]
        data.update(items=items, reconciliation=record.get("reconciliation"),
                    cost_note="供应商未提供已核实金额时不估算结算费用")
    return data


class GenerationTaskRepository:
    def __init__(self, root, *, journal=None):
        self.journal = journal if journal is not None else CanvasTaskJournal(root)

    def owned_record(self, user_id, task_id, task_type):
        if task_type not in TYPES or db.get_task_owner(task_type, task_id) != user_id:
            return None
        return self._mapped_record(user_id, task_id, task_type)

    def _mapped_record(self, user_id, task_id, task_type):
        # Caller has already selected this user's immutable ownership mapping.
        record = self.journal.get(task_id)
        if not record or record.get("type") != TYPES[task_type] or record.get("enterprise_user_id", user_id) != user_id:
            return None
        return record

    def detail(self, user_id, task_id):
        for task_type in TYPES:
            record = self.owned_record(user_id, task_id, task_type)
            if record:
                data = describe_task(record, detail=True)
                from enterprise.task_canvas_context import describe_source
                data['source'] = describe_source(record.get('source'), user_id, self.journal.root.parent / 'canvases')
                return data
        return None

    def page(self, user_id, *, cursor="", status="", kind="", limit=30):
        before = None
        if cursor:
            match = re.fullmatch(r"(\d{1,16})\|(canvas_image|canvas_comfy|canvas_video|canvas_llm)\|([A-Za-z0-9_-]{1,160})", cursor)
            if not match:
                raise ValueError("任务分页位置无效")
            before = (int(match[1]), match[2], match[3])
        if status and status not in STATES:
            raise ValueError("任务状态无效")
        if kind and kind not in TYPES:
            raise ValueError("任务类型无效")
        limit = max(1, min(50, limit))
        items, scanned, next_cursor = [], 0, None
        while len(items) < limit and scanned < 1000:
            rows = db.list_owned_canvas_tasks(user_id, before=before, task_type=kind, limit=100)
            if not rows:
                next_cursor = None
                break
            for row in rows:
                scanned += 1
                before = (row["created_at"], row["task_type"], row["task_id"])
                next_cursor = "|".join(map(str, before))
                try:
                    record = self._mapped_record(user_id, row["task_id"], row["task_type"])
                except (OSError, ValueError, UnicodeError):
                    record = None
                data = describe_task(record) if record else {"id": row["task_id"], "status": "unavailable", "error": "任务记录暂不可读；不会自动重新生成", "created_at": row["created_at"] / 1000}
                if not status or data["status"] == status:
                    items.append(data)
                if len(items) >= limit:
                    break
            if len(rows) < 100 and len(items) < limit:
                next_cursor = None
                break
        return {"items": items, "next_cursor": next_cursor, "scan_limited": scanned >= 1000}
