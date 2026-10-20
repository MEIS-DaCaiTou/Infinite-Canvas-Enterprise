"""Durable video lifecycle over the existing journal and accepted-task scheduler."""
import asyncio
from contextvars import ContextVar
import logging
import time
import uuid

import httpx
from fastapi import HTTPException

from enterprise.canvas_image_recovery import ImageReceiptSink, provider_scope
from enterprise.canvas_task_journal import create_task_receipt
from enterprise.providers.submission import reported_usage
from enterprise.runtime.logging import redact_text

_receipt = ContextVar("canvas_video_receipt", default=None)


async def record_video_acceptance(task_id, provider, submit_url, mode):
    sink = _receipt.get()
    if sink and task_id:
        if not 1 <= len(task_id) <= 240:
            raise ValueError("Invalid provider task identity")
        # Identity and query binding commit together before polling or archiving.
        await asyncio.to_thread(sink.journal.record_provider_request, sink.task_id, 0,
            {**provider_scope(provider), "upstream_task_id": task_id, "state": "accepted",
             "accepted_at": time.time(), "video_query_mode": mode, "video_v2": "/v2/" in submit_url})


def can_reconcile_video(record):
    return record.get("type") == "video" and record.get("status") == "failed" and any(
        (r.get("state") in {"succeeded", "failed"} and r.get("result") and not record.get("result")) or
        (r.get("upstream_task_id") and r.get("video_query_mode") and r.get("state") not in {"succeeded", "failed"})
        for r in record.get("provider_receipts") or []
    )


def public_video_task(record):
    data = {key: value for key, value in record.items() if key != "provider_receipts"}
    data["can_reconcile"] = can_reconcile_video(record)
    if data["can_reconcile"] and (record.get("auto_recovery") or {}).get("status") in {"waiting", "querying"}:
        data.update(status="running", error="")
    return data


class CanvasVideoTasks:
    def __init__(self, journal, resolve_provider, generate, inspect, archive, archived, publish, schedule, notify,
                 query_mode=lambda provider, model: "generic", enqueue=None, prepare_binding=None):
        self.journal, self.resolve_provider, self.generate, self.inspect = journal, resolve_provider, generate, inspect
        self.archive, self.archived, self.publish = archive, archived, publish
        self.schedule, self.notify = schedule, notify
        self.query_mode = query_mode
        self.enqueue = enqueue
        self.prepare_binding = prepare_binding
        self.accept_lock = asyncio.Lock()
        self.active = {}

    async def create(self, payload, user_id):
        try:
            nonce = uuid.UUID(payload.request_id).hex if payload.request_id else uuid.uuid4().hex
        except ValueError as exc:
            raise HTTPException(400, "视频请求身份无效") from exc
        task_id = "canvas_video_" + nonce
        owner = user_id if isinstance(user_id, str) else ""
        async with self.accept_lock:
            existing = await asyncio.to_thread(self.journal.get, task_id)
            if existing:
                if existing.get("type") != "video" or existing.get("enterprise_user_id", "") != owner:
                    raise HTTPException(403, "Task owner mismatch")
                return {"task_id": task_id, "status": existing["status"]}
            binding = await asyncio.to_thread(self.prepare_binding, task_id, payload, owner) if self.prepare_binding else None
            await asyncio.to_thread(create_task_receipt, self.journal, {
                **({'billing_context':binding} if binding else {}),
                "id": task_id, "type": "video", "status": "queued", "created_at": time.time(),
                "updated_at": time.time(), "provider_id": payload.provider_id, "model": payload.model,
                "source": payload.source.model_dump() if getattr(payload, "source", None) else None,
                "result": None, "error": "", "provider_receipts": [{"index": 0, "state": "started"}],
            }, owner)
            if self.enqueue:
                await self.enqueue(task_id, payload)
            else:
                self.schedule(self.run(task_id, payload))
        return {"task_id": task_id, "status": "queued"}

    async def run(self, task_id, payload):
        if not await asyncio.to_thread(self.journal.mark_running, task_id):
            return
        sink = ImageReceiptSink(self.journal, task_id, 0)
        token = _receipt.set(sink)
        try:
            provider = self.resolve_provider(payload.provider_id)
            if self.query_mode(provider, payload.model):
                provider_scope(provider)  # HTTP query binding; local CLI has no HTTP origin.
            await sink.started(provider, payload.model)
            result = await self.generate(payload)
            if result.get("jimeng_pending"):
                await asyncio.to_thread(self.journal.finish, task_id, {
                    "status": "jimeng_pending", "result": result, "error": "",
                    "submit_id": result.get("submit_id"), "jimeng_pending": True})
                return
            videos = result.get("videos") or []
            usage = reported_usage(result.get("raw") or {})
            if not self.archived(videos):
                raise HTTPException(502, "视频结果未归档，请核对原任务，不要重新生成")
            result = {"videos": videos, "task_id": task_id, "provider_id": provider["id"],
                      "model": payload.model, "type": "video", "timestamp": time.time()}
            await asyncio.to_thread(self.journal.record_provider_request, task_id, 0,
                                    {"state": "succeeded", "finished_at": time.time(), "reported_usage": usage,
                                     "result": {**result, "status": "succeeded"}})
            changes = {"status": "succeeded", "result": result, "error": "", "recovery_required": False}
        except Exception as exc:
            from enterprise.task_credentials import task_error
            await sink.interrupted(exc)
            record = await asyncio.to_thread(self.journal.get, task_id)
            unknown = record["provider_receipts"][0]["state"] == "unknown"
            changes = {"status": "failed", "error": task_error(getattr(exc, "detail", None) or str(exc))[:1200],
                       "status_code": getattr(exc, "status_code", 500), "recovery_required": unknown}
        finally:
            _receipt.reset(token)
        await asyncio.to_thread(self.journal.finish, task_id, changes)
        if changes["status"] == "succeeded":
            await self._publish(changes["result"])
        self.notify(task_id)

    async def _publish(self, result):
        try:
            await asyncio.to_thread(self.publish, result)
        except OSError:
            logging.getLogger(__name__).error("Video history projection unavailable; durable result retained")

    async def shutdown(self):
        for task in self.active.values():
            task.cancel()
        await asyncio.gather(*self.active.values(), return_exceptions=True)

    async def reconcile(self, task_id):
        task = self.active.get(task_id)
        if task is None:
            task = asyncio.create_task(self._reconcile(task_id))
            self.active[task_id] = task
            def done(future):
                self.active.pop(task_id, None)
                if not future.cancelled():
                    future.exception()
            task.add_done_callback(done)
        return await asyncio.shield(task)

    async def _reconcile(self, task_id):
        record = await asyncio.to_thread(self.journal.get, task_id)
        if not record or record.get("type") != "video":
            raise HTTPException(404, "视频任务不存在")
        if record.get("status") == "succeeded":
            return {**record["result"], "status": "succeeded"}
        if record.get("status") in {"queued", "running"}:
            return {"status": record["status"]}
        if not can_reconcile_video(record):
            raise HTTPException(409, "没有可安全续查的视频回执，请核对供应商记录，不会重新生成")
        await asyncio.to_thread(self.journal.record_reconciliation, task_id, "querying")
        receipt = record["provider_receipts"][0]
        try:
            if receipt.get("state") in {"succeeded", "failed"} and receipt.get("result"):
                # A crash between the two atomic writes must not lose a terminal receipt.
                result = receipt["result"]
                await asyncio.to_thread(self.journal.finish_provider_recovery, task_id, result)
                await asyncio.to_thread(self.journal.record_reconciliation, task_id, result["status"])
                return result
            provider = self.resolve_provider(receipt["provider_id"])
            if any(receipt.get(key) != value for key, value in provider_scope(provider).items()):
                raise HTTPException(409, "视频供应商地址或协议已改变，请核对原任务")
            from enterprise.task_credentials import credential_scope
            with credential_scope(record):
                result = await self.inspect(provider, receipt)
                from enterprise.task_credentials import task_error
                result = {**result, **{key:task_error(result[key]) for key in ('message','error') if key in result}}
            if result["status"] == "succeeded":
                videos = []
                for url in result["remote_urls"]:
                    videos.append(await self.archive(url))
                if not self.archived(videos):
                    raise HTTPException(502, "原视频结果归档未完成，请稍后续查")
                result = {"status": "succeeded", "videos": videos, "task_id": task_id,
                          "provider_id": record["provider_id"], "model": record["model"],
                          "type": "video", "timestamp": time.time(), "reported_usage": result.get("reported_usage")}
            if result["status"] in {"succeeded", "failed"}:
                await asyncio.to_thread(self.journal.record_provider_request, task_id, 0,
                    {"state": result["status"], "finished_at": time.time(), "error": result.get("message", ""),
                     "reported_usage": result.get("reported_usage"), "result": result}, recovering=True)
                await asyncio.to_thread(self.journal.finish_provider_recovery, task_id, result)
                if result["status"] == "succeeded":
                    await self._publish(result)
        except (HTTPException, httpx.HTTPError, ValueError, OSError) as exc:
            code = getattr(exc, "status_code", None)
            if isinstance(exc, httpx.HTTPStatusError):
                code = exc.response.status_code
            result = {"status": "manual" if code and 300 <= code < 500 and code not in {408, 429} else "unknown",
                      "http_status": code, "message": "原视频查询或归档未完成；请核对供应商状态，未重新生成"}
        await asyncio.to_thread(self.journal.record_reconciliation, task_id, result["status"], result.get("message", ""))
        return result
