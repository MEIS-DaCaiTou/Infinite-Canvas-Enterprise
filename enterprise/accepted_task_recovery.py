"""Single-Upstream recovery of accepted work. This module cannot submit work.

The journal is the fact source; the in-memory schedule is rebuilt on startup.
Only failed local tracking with a retained upstream identity enters this loop.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import HTTPException
from enterprise.providers.zhenzhen import is_zhenzhen
from enterprise.runtime.logging import redact_text


def recovery_candidate(record):
    if not record or record.get("status") != "failed":
        return False
    if record.get("type") == "comfy":
        return bool(record.get("recovery_required") and (record.get("comfy_receipt") or {}).get("prompt_id"))
    return record.get("type") == "online-image" and any(
        item.get("upstream_task_id") and item.get("state") not in {"succeeded", "failed"}
        for item in record.get("provider_receipts") or []
    )


def validate_owned_task(record, *, task_owner, user, provider, comfy):
    """Resolve existing ownership/configuration through application callbacks."""
    owner = record.get("enterprise_user_id")
    kind = "canvas_comfy" if record["type"] == "comfy" else "canvas_image"
    if not owner or task_owner(kind, record["id"]) != owner or not user(owner):
        return "任务缺少有效的本人归属；请管理员核对，不自动查询或变更归属"
    if record["type"] == "comfy":
        try:
            comfy(record["comfy_receipt"])
        except (HTTPException, ValueError, KeyError) as exc:
            return getattr(exc, "detail", None) or "ComfyUI 原任务回执不完整，请人工核对"
    else:
        for receipt in record.get("provider_receipts") or []:
            if receipt.get("upstream_task_id") and receipt.get("state") not in {"succeeded", "failed"}:
                try:
                    selected = provider(receipt["provider_id"])
                except (HTTPException, KeyError):
                    return "原供应商配置已移除，请人工核对"
                if not is_zhenzhen(selected):
                    return "此供应商暂未启用自动续查，可使用已有手动查询"
    return ""


class AcceptedTaskRecovery:
    def __init__(self, journal, query, validate, paused, *, concurrency=2,
                 poll_delay=5, retry_max=300, clock=time.time):
        self.journal, self.query, self.validate, self.paused = journal, query, validate, paused
        self.concurrency, self.poll_delay, self.retry_max, self.clock = concurrency, poll_delay, retry_max, clock
        self._pending = {}
        self._active = {}
        self._runner = None
        self._wake = asyncio.Event()
        self._closed = True

    async def start(self):
        if self._runner:
            return
        self._closed = False
        for record in await asyncio.to_thread(self.journal.recovery_candidates):
            if (record.get("auto_recovery") or {}).get("status") != "manual":
                self.notify(record["id"], (record.get("auto_recovery") or {}).get("next_query_at") or 0)
        self._runner = asyncio.create_task(self._run())
        self._runner.add_done_callback(self._stopped)

    def _stopped(self, future):
        if not future.cancelled() and future.exception():
            logging.getLogger(__name__).error("Automatic original-task scheduler stopped unexpectedly")

    def notify(self, task_id, due=0):
        # Called by the owning event loop after durable task completion.
        if not self._closed:
            self._pending.setdefault(task_id, due)
            self._wake.set()

    async def stop(self):
        self._closed = True
        self._wake.set()
        if self._runner:
            await asyncio.gather(self._runner, return_exceptions=True)
            self._runner = None
        # Queries are cancellable; no long provider wait thread is scheduled.
        for task in self._active.values():
            task.cancel()
        await asyncio.gather(*self._active.values(), return_exceptions=True)
        self._active.clear()
        self._pending.clear()

    async def _run(self):
        while not self._closed:
            self._wake.clear()
            if not self.paused():
                for task_id, due in list(self._pending.items()):
                    if len(self._active) >= self.concurrency:
                        break
                    if due > self.clock() or task_id in self._active:
                        continue
                    self._pending.pop(task_id)
                    task = asyncio.create_task(self._one(task_id))
                    self._active[task_id] = task
                    task.add_done_callback(lambda future, key=task_id: self._done(key, future))
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_delay)
            except TimeoutError:
                pass

    def _done(self, task_id, future):
        self._active.pop(task_id, None)
        if not future.cancelled() and future.exception():
            # The original receipt is preserved even when local storage fails.
            logging.getLogger(__name__).error("Accepted task recovery unavailable: %s", task_id)
            self.notify(task_id, self.clock() + self.retry_max)
        self._wake.set()

    async def _record(self, task_id, changes):
        await asyncio.to_thread(self.journal.record_auto_recovery, task_id, changes)

    async def _one(self, task_id):
        record = await asyncio.to_thread(self.journal.get, task_id)
        if not recovery_candidate(record):
            if record and record.get("auto_recovery"):
                await self._record(task_id, {"status": "complete", "next_query_at": None, "reason": ""})
            return
        if (record.get("auto_recovery") or {}).get("status") == "manual":
            return
        if self.paused():
            self.notify(task_id)
            return
        reason = await asyncio.to_thread(self.validate, record)
        if reason:
            await self._record(task_id, {"status": "manual", "next_query_at": None, "reason": reason})
            return
        if self.paused():
            self.notify(task_id)
            return
        previous = record.get("auto_recovery") or {}
        count = previous.get("count", 0) + 1
        await self._record(task_id, {"status": "querying", "count": count,
                                    "last_query_at": self.clock(), "next_query_at": None, "reason": ""})
        try:
            result = await self.query(record)
        except Exception as exc:
            result = {"status": "unknown", "http_status": getattr(exc, "status_code", None),
                      "message": getattr(exc, "detail", None) or str(exc)}
        state = result.get("status", "unknown")
        code = result.get("http_status")
        reason = redact_text(result.get("message") or "")[:1200]
        if state in {"succeeded", "partial", "failed"}:
            await self._record(task_id, {"status": "complete", "next_query_at": None, "reason": reason})
        elif state == "manual" or (code is not None and 300 <= code < 500 and code not in {408, 429}):
            await self._record(task_id, {"status": "manual", "next_query_at": None,
                                        "reason": reason or "原任务查询需要人工核对"})
        else:
            failures = 0 if state in {"queued", "running"} else previous.get("failures", 0) + 1
            delay = min(self.retry_max, self.poll_delay * (2 ** min(failures, 10)))
            due = self.clock() + delay
            await self._record(task_id, {"status": "waiting", "failures": failures,
                                        "next_query_at": due, "reason": reason})
            self.notify(task_id, due)
