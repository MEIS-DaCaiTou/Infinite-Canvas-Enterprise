"""Persist accepted image identities and reconcile by querying, never submitting.

Reuses the single-writer canvas journal. Provider credentials are resolved at
query time; saved scope prevents sending an old task to a changed supplier.
This is a receipt recovery boundary, not a task scheduler or cost ledger.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import logging
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException


def provider_scope(provider):
    base = str(provider.get("base_url") or "").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(409, "供应商地址不能安全绑定任务查询；请先核对平台配置")
    return {"provider_id": provider["id"], "provider_base_url": base,
            "provider_protocol": str(provider.get("protocol") or ""),
            "image_request_mode": str(provider.get("image_request_mode") or "")}


def can_reconcile(record):
    return record.get("type") == "online-image" and record.get("status") == "failed" and any(
        (receipt.get("upstream_task_id") and receipt.get("provider_base_url")) or (receipt.get("result") or {}).get("images")
        for receipt in record.get("provider_receipts") or []
    )


def public_receipt(record):
    # Internal query binding is not frontend configuration or a credential.
    return {**{key: value for key, value in record.items() if key != "provider_receipts"},
            "can_reconcile": can_reconcile(record)}


class ImageReceiptSink:
    def __init__(self, journal, task_id, index):
        self.journal, self.task_id, self.index = journal, task_id, index

    async def accepted(self, upstream_task_id, provider):
        if not isinstance(upstream_task_id, str) or not 1 <= len(upstream_task_id) <= 240:
            raise ValueError("Invalid provider task identity")
        await asyncio.to_thread(self.journal.record_image_request, self.task_id, self.index,
                                {**provider_scope(provider), "state": "accepted", "upstream_task_id": upstream_task_id})

    async def completed(self, images, image_items):
        if not images:
            raise HTTPException(502, "未取得可保存的图片结果；请核对原任务")
        await asyncio.to_thread(self.journal.record_image_request, self.task_id, self.index,
                                {"state": "succeeded", "result": {"images": images, "image_items": image_items}})

    async def interrupted(self, exc):
        ambiguous = getattr(exc, "submission_unknown", False) or getattr(exc, "status_code", 0) >= 500 or isinstance(exc, httpx.HTTPError)
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            ambiguous = False
        if getattr(exc, "provider_task_failed", False):
            ambiguous = False
        await asyncio.to_thread(self.journal.record_image_request, self.task_id, self.index,
                                {"state": "unknown" if ambiguous else "failed"})


class CanvasImageRecovery:
    def __init__(self, journal, resolve_provider, query, publish):
        self.journal, self.resolve_provider, self.query, self.publish = journal, resolve_provider, query, publish
        self._active = {}

    async def reconcile(self, task_id):
        # Single flight only for active read queries; no in-memory task facts.
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
        if not record or record.get("type") != "online-image":
            raise HTTPException(404, "画布图像任务不存在")
        if record.get("status") == "succeeded":
            return {**record["result"], "status": "succeeded"}
        if (record.get("result") or {}).get("status") == "partial":
            return record["result"]
        if record.get("status") != "failed":
            return {"status": "running", "message": "原任务仍在跟踪，请稍后查询", "task_id": task_id}
        if not can_reconcile(record):
            raise HTTPException(409, "没有可续查的已绑定任务回执；请核对供应商任务与账单，不要自动重新生成")

        # Validate all bindings before any supplier request. Key rotation is
        # allowed, endpoint/protocol reassignment is not.
        providers = {}
        for receipt in record["provider_receipts"]:
            if receipt.get("upstream_task_id") and receipt["state"] not in {"succeeded", "failed"}:
                provider = self.resolve_provider(receipt["provider_id"])
                if any(receipt.get(key) != value for key, value in provider_scope(provider).items()):
                    raise HTTPException(409, "供应商地址或查询协议已改变；请核对原任务，不会向新地址发送旧任务 ID")
                providers[receipt["index"]] = provider

        pending, query_unknown, query_http_status = False, False, None
        for receipt in record["provider_receipts"]:
            index = receipt["index"]
            if index not in providers:
                continue
            try:
                result = await self.query(providers[index], receipt["upstream_task_id"])
            except (HTTPException, httpx.HTTPError, ValueError, OSError) as exc:
                query_unknown = True
                if isinstance(exc, HTTPException):
                    query_http_status = exc.status_code
                continue
            if result.get("status") == "succeeded" and result.get("images"):
                await asyncio.to_thread(self.journal.record_image_request, task_id, index,
                                        {"state": "succeeded", "result": {
                                            "images": result["images"], "image_items": result.get("image_items") or []}}, recovering=True)
            elif result.get("status") == "failed":
                await asyncio.to_thread(self.journal.record_image_request, task_id, index,
                                        {"state": "failed"}, recovering=True)
            else:
                pending = True
        if query_unknown or pending:
            reason = f"（HTTP {query_http_status}，请检查平台配置或供应商状态）" if query_http_status else ""
            return {"status": "unknown" if query_unknown else "running", "task_id": task_id,
                    "message": f"原任务查询暂未确认{reason}，请稍后再查；没有重新生成" if query_unknown else "原任务仍在生成中，请稍后再查询"}

        record = await asyncio.to_thread(self.journal.get, task_id)
        receipts = record["provider_receipts"]
        images = [url for item in receipts for url in (item.get("result") or {}).get("images", [])]
        items = [meta for item in receipts for meta in (item.get("result") or {}).get("image_items", [])]
        all_succeeded = all(item["state"] == "succeeded" for item in receipts)
        message = "" if all_succeeded else "部分请求未确认或已失败；已找回的结果已保留，其余请核对供应商任务与账单，不要自动重新生成"
        result = {"status": "succeeded" if all_succeeded else ("partial" if images else "failed"),
                  "task_id": task_id, "images": images, "image_items": items, "message": message,
                  "provider_id": record.get("provider_id"), "model": record.get("model"), "type": "online", "timestamp": time.time()}
        await asyncio.to_thread(self.journal.finish_image_recovery, task_id, result)
        if images:
            try:
                await asyncio.to_thread(self.publish, deepcopy(result))
            except OSError:
                # The journal remains the result fact; do not query or generate
                # again just because the history projection could not be saved.
                logging.getLogger(__name__).error("Recovered canvas result history unavailable")
        return result
