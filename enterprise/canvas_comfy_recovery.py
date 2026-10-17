"""One-shot original ComfyUI queries shared by manual and background recovery."""
from __future__ import annotations

import asyncio

import httpx

from enterprise.providers.comfyui import ComfyExecutionError
from enterprise.runtime.logging import redact_text


def public_comfy_task(record, *, resuming=False):
    """Expose accepted work still being queried as nonterminal to canvas pollers."""
    public = {key: value for key, value in record.items() if key != "comfy_receipt"}
    receipt = record.get("comfy_receipt") or {}
    automatic = (record.get("auto_recovery") or {}).get("status")
    tracking = (record.get("reconciliation") or {}).get("status")
    pending = resuming or (automatic != "manual" and (
        automatic in {"querying", "waiting"} or tracking in {"queued", "running"}))
    if record.get("status") == "failed" and record.get("recovery_required") and receipt.get("prompt_id") and pending:
        public.update(status="running", error="", error_code="")
    public["phase"] = receipt.get("phase", "preparing" if public["status"] == "running" else public["status"])
    return public


class CanvasComfyRecovery:
    def __init__(self, journal, inspect, archive, validate):
        self.journal, self.inspect, self.archive, self.validate = journal, inspect, archive, validate
        self._active = {}

    async def shutdown(self):
        for task in self._active.values():
            task.cancel()
        await asyncio.gather(*self._active.values(), return_exceptions=True)

    async def reconcile(self, task_id):
        task = self._active.get(task_id)
        if task is None:
            task = asyncio.create_task(self._reconcile(task_id))
            self._active[task_id] = task
            def completed(future):
                self._active.pop(task_id, None)
                if not future.cancelled():
                    future.exception()
            task.add_done_callback(completed)
        return await asyncio.shield(task)

    async def _reconcile(self, task_id):
        record = await asyncio.to_thread(self.journal.get, task_id)
        if not record or record.get("type") != "comfy":
            return {"status": "manual", "message": "ComfyUI 任务记录不存在"}
        if record.get("status") == "succeeded":
            return {"status": "succeeded", **record["result"]}
        receipt = record.get("comfy_receipt") or {}
        self.validate(receipt)
        claimed = await asyncio.to_thread(self.journal.claim_comfy_query, task_id)
        if not claimed:
            return {"status": "running", "message": "原任务正在跟踪"}
        code = None
        try:
            phase, history = await self.inspect(receipt["backend"], receipt["prompt_id"])
            await asyncio.to_thread(self.journal.record_comfy, task_id, {"phase": phase})
            if history is not None:
                # Archive I/O is bounded by the existing download timeout. Join
                # it on cancellation so a second query cannot write concurrently.
                archive = asyncio.create_task(asyncio.to_thread(self.archive, record, history))
                try:
                    result = await asyncio.shield(archive)
                except asyncio.CancelledError:
                    result = await archive
                changes = {"status": "succeeded", "result": result, "error": "", "recovery_required": False}
                outcome = {"status": "succeeded"}
            else:
                changes = {"status": "failed", "error": "原任务仍在排队或生成" if phase in {"queued", "running"} else "ComfyUI 队列和历史中暂未找到原任务",
                           "recovery_required": True}
                outcome = {"status": "manual" if phase == "unknown" else phase, "message": changes["error"]}
        except asyncio.CancelledError:
            # Keep the original ID eligible after cooperative shutdown/restart.
            await asyncio.to_thread(self.journal.finish, task_id, {"status": "failed", "recovery_required": True,
                "error": "本地续查已停止；下次启动继续查询原任务", "error_code": "runtime_interrupted"})
            raise
        except Exception as exc:
            code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else getattr(exc, "status_code", None)
            terminal = isinstance(exc, ComfyExecutionError)
            error = redact_text(getattr(exc, "detail", None) or str(exc))[:1200]
            changes = {"status": "failed", "error": error, "recovery_required": not terminal}
            outcome = {"status": "failed" if terminal else "unknown", "message": error, "http_status": code}
        await asyncio.to_thread(self.journal.finish, task_id, changes)
        await asyncio.to_thread(self.journal.record_reconciliation, task_id, outcome["status"], outcome.get("message", ""))
        return outcome
