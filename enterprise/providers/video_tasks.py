"""Query an accepted video once using the application's existing provider URLs.

No submission capability. Unknown payloads require manual reconciliation.
"""
from urllib.parse import quote

from enterprise.providers.submission import reported_usage

FAILED = {"FAILURE", "FAILED", "FAIL", "ERROR", "ERRORED", "CANCELED", "CANCELLED", "TIMEOUT", "TIMEDOUT", "REJECTED", "EXPIRED"}
PENDING = {"QUEUED", "QUEUE", "PENDING", "SUBMITTED", "ACCEPTED", "PROCESSING", "RUNNING", "IN_PROGRESS", "IN_QUEUE", "CREATED", "WAITING"}


async def inspect_video(client, urls, headers, output_urls, failure_message):
    for index, url in enumerate(urls):
        response = await client.get(url, headers=headers)
        # Only explicit missing GET endpoints permit trying another query URL.
        if response.status_code in {404, 405} and index < len(urls) - 1:
            continue
        response.raise_for_status()
        raw = response.json()
        data = raw.get("data") if isinstance(raw, dict) else None
        data = data if isinstance(data, dict) else raw
        if not isinstance(data, dict):
            return {"status": "manual", "message": "视频原任务回包无法识别，请核对供应商记录"}
        state = str(data.get("status") or data.get("task_status") or raw.get("status") or raw.get("task_status") or "").upper()
        if state in FAILED:
            return {"status": "failed", "message": failure_message(data.get("error") or data.get("message") or data.get("fail_reason") or "视频原任务失败")}
        urls = output_urls(raw)
        if urls:
            return {"status": "succeeded", "remote_urls": urls, "reported_usage": reported_usage(raw)}
        if state in PENDING:
            return {"status": "queued" if state in {"QUEUED", "QUEUE", "PENDING", "IN_QUEUE", "WAITING"} else "running"}
        return {"status": "manual", "message": "视频原任务未返回可识别状态或可归档结果，请核对供应商记录"}
    return {"status": "manual", "message": "没有可用的视频原任务查询接口"}


def encoded_task_id(task_id):
    return quote(str(task_id), safe="")
