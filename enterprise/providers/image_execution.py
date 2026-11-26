"""HTTP image execution, independent of routes, storage and credential vaults.

The caller supplies prepared media, resolved headers and persistence callbacks.
Original API return values (first image, complete raw result) remain compatible.
"""
import asyncio
import json
import time

import httpx
from fastapi import HTTPException

from enterprise.providers.image_task_protocol import SUCCESS_STATUSES, FAILED_STATUSES, task_status, failure_reason
from enterprise.providers.submission import submission_json, provider_submission_unknown


async def complete_image_submission(response, *, client, provider, extract_image, extract_task_id,
                                    wait_for_task, receipt_sink=None, async_task_id=None, fallback_image=None):
    response.raise_for_status()
    if receipt_sink is not None:
        receipt_sink.identify(response.headers)
    raw = submission_json(response, kind='图像')
    if receipt_sink is not None:
        receipt_sink.identify(raw=raw)
    # For the async Images contract, task_id takes precedence over inline media.
    task_id = async_task_id(raw) if async_task_id else None
    if not task_id:
        try:
            return extract_image(raw), raw
        except HTTPException as exc:
            image = fallback_image(raw) if fallback_image else None
            if image:
                return image, raw
            task_id = None if async_task_id or fallback_image else extract_task_id(raw)
            if not task_id:
                raise provider_submission_unknown('图像提交已返回，但没有可核对的任务或图片结果') from exc
    if receipt_sink is not None:
        await receipt_sink.accepted(task_id, provider)
    try:
        result = await wait_for_task(client, task_id, provider)
        return extract_image(result), result
    except (HTTPException, httpx.HTTPError, ValueError) as exc:
        if getattr(exc, 'provider_task_failed', False):
            setattr(exc, 'upstream_task_id', task_id)
            raise
        raise provider_submission_unknown('已受理的图像任务查询未能确认最终结果', upstream_task_id=task_id) from exc


async def poll_image_task(client, task_id, provider, *, timeout, interval, initial_delay,
                          fetch_payload, extract_image):
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        if initial_delay:
            await asyncio.sleep(min(initial_delay, max(0.0, deadline - time.monotonic())))
            initial_delay = 0
            if time.monotonic() >= deadline:
                break
        last = await fetch_payload(client, task_id, provider)
        status = task_status(last)
        if not status:
            try:
                if extract_image(last):
                    return last
            except HTTPException:
                pass
        if status in SUCCESS_STATUSES:
            return last
        if status in FAILED_STATUSES:
            error = HTTPException(502, f'生图任务失败：{failure_reason(last)}')
            error.provider_task_failed = True
            raise error
        await asyncio.sleep(min(interval, max(0.0, deadline - time.monotonic())))
    raw_text = json.dumps(last, ensure_ascii=False)[:800] if last else ''
    extra = f'，最后响应：{raw_text}' if raw_text else ''
    raise HTTPException(504, f'生图任务超时（已等待 {int(timeout)} 秒），task_id={task_id}{extra}')
