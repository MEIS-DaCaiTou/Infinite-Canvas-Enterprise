"""RunningHub V2 video submission and original-task query protocol.

POST /query reads an existing task. It never calls a generation endpoint.
Credentials and request construction remain in the existing provider configuration.
"""
import asyncio
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from enterprise.providers.submission import provider_submission_unknown, reported_usage, submission_json
from enterprise.runtime.logging import redact_text

SUCCESS = {"SUCCESS", "SUCCEEDED", "COMPLETED", "COMPLETE", "FINISHED", "DONE", "3"}
FAILED = {"FAILED", "FAIL", "ERROR", "CANCEL", "CANCELED", "CANCELLED", "4"}
QUEUED = {"QUEUED", "QUEUE", "PENDING", "IN_QUEUE", "WAITING"}
RUNNING = {"RUNNING", "PROCESSING", "IN_PROGRESS", "SUBMITTED", "ACCEPTED"}
NON_VIDEO = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "image", "mp3", "wav", "aac", "audio", "json", "txt", "text"}
VIDEO = {"mp4", "webm", "mov", "mkv", "m4v", "avi", "flv", "video"}


def task_id(raw):
    if not isinstance(raw, dict):
        return ""
    sources = [raw, raw.get("data")]
    for data in sources:
        if isinstance(data, dict):
            for key in ("taskId", "task_id", "id"):
                value = data.get(key)
                if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
                    return str(value)
    return ""


def video_urls(raw):
    """V2 results may include thumbnails; they are not video outputs."""
    result = []
    def collect(value):
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            kind = str(value.get("outputType") or value.get("fileType") or "").lower().lstrip(".")
            if kind and kind not in VIDEO and not kind.startswith("video/"):
                return
            for key in ("results", "outputs", "videos", "data", "result"):
                collect(value.get(key))
            for key in ("url", "video_url", "videoUrl", "fileUrl", "file_url", "downloadUrl", "download_url"):
                collect(value.get(key))
        elif isinstance(value, str):
            parsed = urlsplit(value)
            suffix = parsed.path.rsplit(".", 1)[-1].lower()
            if suffix not in NON_VIDEO and (parsed.scheme in {"http", "https"} or value.startswith(("/output/", "/assets/"))):
                result.append(value)
    collect(raw)
    return list(dict.fromkeys(result))


def video_result(raw, expected_task_id=""):
    if not isinstance(raw, dict):
        return {"status": "manual", "message": "RunningHub 原任务回包无法识别，请人工核对"}
    identity = task_id(raw)
    if expected_task_id and identity and identity != expected_task_id:
        return {"status": "manual", "message": "RunningHub 返回的任务 ID 与原受理身份不一致，请人工核对"}
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    state = str(raw.get("status") or raw.get("state") or raw.get("taskStatus") or raw.get("task_status") or
                data.get("status") or data.get("state") or data.get("taskStatus") or data.get("task_status") or "").upper()
    error = raw.get("errorCode") or data.get("errorCode")
    if error and state not in FAILED:
        return {"status": "manual", "message": "RunningHub 查询返回错误码，请核对原任务与平台配置"}
    if state in FAILED:
        reason = raw.get("errorMessage") or data.get("errorMessage") or data.get("failReason") or data.get("failedReason") or raw.get("message") or "RunningHub 报告原任务失败"
        return {"status": "failed", "message": redact_text(str(reason))[:1200], "reported_usage": reported_usage(raw)}
    if state in SUCCESS:
        urls = video_urls(raw)
        if urls:
            return {"status": "succeeded", "remote_urls": urls, "reported_usage": reported_usage(raw)}
        return {"status": "manual", "message": "RunningHub 原任务已结束但未返回可归档视频，请核对供应商结果"}
    if state in QUEUED:
        return {"status": "queued"}
    if state in RUNNING:
        return {"status": "running"}
    return {"status": "manual", "message": "RunningHub 原任务状态未知，请核对供应商记录"}


def _task_failure(message, identity):
    error = HTTPException(502, message)
    error.provider_task_failed = True
    error.upstream_task_id = identity
    return error


async def submit_video(client, endpoint, headers, body, accepted):
    """One paid POST. Persist acceptance before any polling or result download."""
    try:
        response = await client.post(endpoint, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise provider_submission_unknown("RunningHub 视频提交响应中断，是否已受理尚不确定") from exc
    if response.status_code >= 500:
        raise provider_submission_unknown(f"RunningHub 视频提交返回 HTTP {response.status_code}，是否已受理尚不确定")
    response.raise_for_status()
    raw = submission_json(response, kind="RunningHub 视频")
    identity = task_id(raw)
    if identity:
        await accepted(identity)
    result = video_result(raw, identity)
    if identity and result["status"] == "failed":
        raise _task_failure(result["message"], identity)
    if not identity and result["status"] != "succeeded":
        raise provider_submission_unknown("RunningHub 视频提交没有返回可确认的 taskId 或视频结果")
    return raw


async def inspect_video(client, query_url, headers, identity):
    # This POST is a documented read operation, not a retry of submit_video.
    response = await client.post(query_url, headers=headers, json={"taskId": identity})
    response.raise_for_status()
    try:
        raw = response.json()
    except ValueError:
        return {"status": "manual", "message": "RunningHub 查询返回非 JSON 响应，请人工核对"}
    return {**video_result(raw, identity), "raw": raw}


async def wait_video(client, query_url, headers, identity, *, timeout=1800, interval=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(interval)
        result = await inspect_video(client, query_url, headers, identity)
        if result["status"] == "succeeded":
            return result["raw"]
        if result["status"] == "failed":
            raise _task_failure(result["message"], identity)
        if result["status"] == "manual":
            raise provider_submission_unknown(result["message"], upstream_task_id=identity)
    raise provider_submission_unknown("RunningHub 视频原任务查询超时，未重新生成", upstream_task_id=identity)
