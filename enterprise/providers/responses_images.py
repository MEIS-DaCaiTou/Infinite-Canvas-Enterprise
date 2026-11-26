"""Responses image encoding and background/SSE transport, independent of business storage.

The caller supplies material URLs, headers and an optional durable acceptance
callback. A known background ID is recorded before the first retrieval request.
"""
import asyncio
import json
import re
import time
import urllib.parse

import httpx

REJECT_STATUSES = {400, 404, 405, 415, 422}
POLL_INTERVAL = 5.0
POLL_MAX_SECONDS = 1500.0


def task_endpoint(endpoint, task_id):
    return f"{endpoint.rstrip('/')}/{urllib.parse.quote(task_id, safe='')}"


def query_state(payload):
    status = str(payload.get('status') or '').lower()
    if status == 'completed':
        return 'succeeded'
    if status in {'failed', 'cancelled', 'incomplete'}:
        return 'failed'
    if status in {'queued', 'in_progress', 'processing', 'pending', 'running'}:
        return 'running'
    return 'manual'


def image_body(model, prompt, size, quality, references, background=None):
    tool = {"type": "image_generation", **(background or {})}
    tool["action"] = "edit" if references else "generate"
    if size and str(size).strip().lower() != "auto":
        tool["size"] = tool_size(size)
    if quality:
        tool["quality"] = quality
    instruction = size_instruction(size)
    content = [{"type": "input_text", "text": f"{instruction}\n\n{prompt}" if instruction else prompt}]
    content.extend({"type": "input_image", "image_url": value} for value in references if value)
    return {"model": model, "input": [{"role": "user", "content": content}], "tools": [tool]}


def size_instruction(size: str) -> str:
    """保留既有 RS 模式的中英双语画幅提示；不作为所有 Responses 供应商的能力规则。"""
    match = re.match(r"^\s*(\d{2,5})\s*[xX*]\s*(\d{2,5})\s*$", str(size or ""))
    if not match:
        return ""
    width, height = int(match.group(1)), int(match.group(2))
    if width <= 0 or height <= 0:
        return ""
    if width == height:
        return "请生成正方形图片（宽高比 1:1）。Generate a SQUARE image (aspect ratio 1:1)."
    from fractions import Fraction
    ratio = Fraction(width, height).limit_denominator(32)
    rw, rh = ratio.numerator, ratio.denominator
    if width > height:
        zh_shape, en_shape = "横版（宽幅）", "LANDSCAPE (wide)"
    else:
        zh_shape, en_shape = "竖版（长幅）", "PORTRAIT (tall)"
    return (
        f"请生成{zh_shape}图片：宽高比 {rw}:{rh}，目标尺寸为宽 {width} × 高 {height} 像素，绝对不要输出正方形（1:1）。"
        f" Generate a {en_shape} image with aspect ratio {rw}:{rh}, target size {width}x{height} pixels (width x height)."
        f" Never output a square 1:1 image. Do not swap width and height."
    )


def tool_size(size: str) -> str:
    """部分 RS 中转把 image_generation.size 当成 height x width；这里只对 RS 模式做兼容翻转。"""
    match = re.match(r"^\s*(\d{2,5})\s*[xX*]\s*(\d{2,5})\s*$", str(size or ""))
    if not match:
        return str(size or "").strip()
    width, height = match.group(1), match.group(2)
    return f"{height}x{width}" if width != height else f"{width}x{height}"


def no_image_detail(data) -> str:
    if not isinstance(data, dict):
        return ""
    details = []
    error = data.get("error")
    if isinstance(error, dict):
        msg = error.get("message") or error.get("detail") or error.get("code")
        if msg:
            details.append(str(msg))
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        details.append(output_text.strip()[:300])
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "image_generation_call":
                continue
            status = item.get("status")
            if status:
                details.append(f"image_generation_call.status={status}")
            item_error = item.get("error")
            if isinstance(item_error, dict):
                msg = item_error.get("message") or item_error.get("detail") or item_error.get("code")
                if msg:
                    details.append(str(msg))
            elif isinstance(item_error, str) and item_error.strip():
                details.append(item_error.strip())
    joined = "；".join(dict.fromkeys(details))
    return f"RS / Responses 没有返回图片数据{f'：{joined}' if joined else ''}"


def output_text_image(raw):
    """兜底解析：部分 RS 中转不返回标准 image_generation_call，而是把生图结果
    以 output_text 里的 markdown 图片链接（![...](url)）或裸图片 URL 返回。"""
    texts = []
    def collect(value, depth=0):
        if depth > 6 or len(texts) > 40:
            return
        if isinstance(value, str):
            if value.strip():
                texts.append(value)
            return
        if isinstance(value, list):
            for item in value:
                collect(item, depth + 1)
            return
        if isinstance(value, dict):
            for key in ("output", "content", "text", "output_text", "message", "response"):
                if key in value:
                    collect(value[key], depth + 1)
    collect(raw)
    for text in texts:
        match = re.search(r"!\[[^\]]*\]\((https?://[^)\s]+)\)", text)
        if match:
            return {"type": "url", "value": match.group(1)}
        match = re.search(r"https?://[^\s)\"'<>]+\.(?:png|jpe?g|webp|gif)(?:\?[^\s)\"'<>]*)?", text, re.I)
        if match:
            return {"type": "url", "value": match.group(0)}
    return None


def response_wrap(url, status_code, payload):
    return httpx.Response(
        status_code,
        headers={"content-type": "application/json"},
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        request=httpx.Request("POST", url),
    )


async def submit(client, url, headers, body, *, on_accepted=None, poll_interval=POLL_INTERVAL, poll_max_seconds=POLL_MAX_SECONDS):
    """沿用 RS / Responses 的后台、SSE、直接返回顺序。

    仅在既有明确拒绝状态下切换形式；5xx 或响应丢失不重新 POST。
    后台模式得到 ID 后，调用上层持久受理回调再开始查询。
    """
    bg_body = dict(body)
    bg_body["background"] = True
    # A lost response may already have incurred a paid generation.
    resp = await client.post(url, headers=headers, json=bg_body)
    if resp.status_code in REJECT_STATUSES:
        print(f"RS background 模式被拒（{resp.status_code}），改走流式：{resp.text[:200]}")
        return await submit_stream(client, url, headers, body)
    if resp.status_code >= 400:
        if resp.status_code == 524:
            return response_wrap(url, 502, {"error": {"message": (
                "中转在 background 模式下仍然 524 超时：该渠道对 /v1/responses 的 background/stream 都不透传，"
                "无法完成超过 120 秒的图片编辑。请换支持 Responses 透传的渠道。上游原文："
                f"{resp.text[:300]}"
            )}})
        return resp
    try:
        data = resp.json()
    except ValueError:
        return resp
    status = str((data or {}).get("status") or "").lower()
    rid = str((data or {}).get("id") or "").strip()
    if status not in {"queued", "in_progress", "processing", "pending", "running"} or not rid:
        return resp  # 中转忽略 background 直接同步返回了结果（或未知结构），交给下游解析
    # 轮询后台任务
    retrieve_url = task_endpoint(url, rid)
    if on_accepted is not None:
        await on_accepted(rid, retrieve_url, resp)
    deadline = time.monotonic() + poll_max_seconds
    transient_failures = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(poll_interval)
        try:
            poll = await client.get(retrieve_url, headers=headers)
        except httpx.HTTPError as e:
            transient_failures += 1
            if transient_failures > 5:
                return response_wrap(url, 502, {"error": {"message": f"RS 后台任务轮询连续失败：{e}（任务 id={rid}）"}})
            continue
        if poll.status_code >= 400:
            transient_failures += 1
            if transient_failures > 5:
                return response_wrap(url, 502, {"error": {"message": f"RS 后台任务轮询失败（{poll.status_code}）：{poll.text[:200]}（任务 id={rid}）"}})
            continue
        transient_failures = 0
        try:
            data = poll.json()
        except ValueError:
            continue
        status = str((data or {}).get("status") or "").lower()
        if status == "completed":
            return response_wrap(url, 200, data)
        if status in {"failed", "cancelled", "incomplete"}:
            return response_wrap(url, 502, data)
    return response_wrap(url, 502, {"error": {"message": f"RS 后台任务超过 {int(poll_max_seconds)}s 仍未完成（任务 id={rid}）"}})


async def submit_stream(client, url, headers, body):
    """保留既有 SSE 事件解析及直接返回兼容，包装为原下游接收的 HTTP 响应。"""
    request = httpx.Request("POST", url)

    def wrap(status_code, payload):
        return response_wrap(url, status_code, payload)

    stream_body = dict(body)
    stream_body["stream"] = True
    try:
        async with client.stream("POST", url, headers=headers, json=stream_body) as resp:
            ctype = (resp.headers.get("content-type") or "").lower()
            if resp.status_code >= 400 or "text/event-stream" not in ctype:
                content = await resp.aread()
                # 个别中转不支持 responses 流式（对 stream 参数直接报错）→ 回退一次非流式。
                # 仅对“请求被拒绝”类状态码回退，5xx/超时不重试，避免上游已开始生成后重复扣费。
                if resp.status_code in {400, 404, 405, 415, 422}:
                    print(f"RS 流式请求被拒（{resp.status_code}），回退非流式：{content[:200]!r}")
                    return await client.post(url, headers=headers, json=body)
                return httpx.Response(resp.status_code, headers=resp.headers, content=content, request=request)
            completed = None
            error_payload = None
            partial_b64 = ""
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    event = json.loads(chunk)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                etype = str(event.get("type") or "")
                if etype in {"response.completed", "response.incomplete"} and isinstance(event.get("response"), dict):
                    completed = event["response"]
                elif etype == "response.failed":
                    failed = event.get("response")
                    error_payload = failed if isinstance(failed, dict) else {"error": {"message": "response.failed"}}
                elif etype == "error":
                    message = event.get("message") or event.get("error") or chunk[:300]
                    error_payload = {"error": {"message": str(message)}}
                elif etype.endswith("partial_image") and isinstance(event.get("partial_image_b64"), str):
                    partial_b64 = event["partial_image_b64"]
            if completed is None and error_payload is None and partial_b64:
                # 流被提前掐断但已收到分片图：用最后一张分片兜底
                completed = {"output": [{"type": "image_generation_call", "status": "completed", "result": partial_b64}]}
            if completed is not None:
                return wrap(200, completed)
            return wrap(502, error_payload or {"error": {"message": "RS 流式响应结束但没有 response.completed 事件"}})
    except httpx.HTTPError:
        # Keep the ambiguous submission with its original caller; do not POST again.
        raise

