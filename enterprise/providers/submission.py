"""Shared paid-submit boundaries and safe query retries.

No retry key is invented for suppliers that do not document idempotency.
Request construction and task/result parsing remain supplier responsibilities.
"""
import asyncio

import httpx
from fastapi import HTTPException


def image_api_explicitly_rejected(response):
    """Fallback only after an explicit unsupported API rejection."""
    text = str(getattr(response, "text", "") or "").lower()
    return getattr(response, "status_code", None) in {400, 404, 405, 415, 422} and (
        "images api is not supported" in text or "not supported for this platform" in text
    )


def provider_submission_unknown(detail, *, upstream_task_id=""):
    task_hint = f"，task_id={upstream_task_id}" if upstream_task_id else ""
    error = HTTPException(
        status_code=502,
        detail=f"PROVIDER_SUBMISSION_UNKNOWN：{detail}{task_hint}；请先核对供应商任务与账单，不要直接重新提交。",
    )
    error.submission_unknown = True
    error.upstream_task_id = upstream_task_id
    return error


def submission_json(response, *, kind):
    """A successful HTTP reply is not proof of a recognized task or result."""
    try:
        payload = response.json()
    except ValueError as exc:
        raise provider_submission_unknown(f"{kind}提交接口返回非 JSON 响应，是否已受理任务尚不确定") from exc
    if not isinstance(payload, dict):
        raise provider_submission_unknown(f"{kind}提交接口返回无法识别的响应，是否已受理任务尚不确定")
    return payload


async def httpx_request_with_transient_retries(client, method, url, attempts=2, retry_delay=1.2, **kwargs):
    attempts = max(1, int(attempts or 1))
    if attempts > 1 and str(method).upper() not in {"GET", "HEAD"}:
        raise ValueError("Non-idempotent provider requests must not be retried")
    for attempt in range(attempts):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code not in {502, 503, 504, 520, 522, 524} or attempt + 1 == attempts:
                return response
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError,
                httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout):
            if attempt + 1 == attempts:
                raise
        await asyncio.sleep(retry_delay * (attempt + 1))
