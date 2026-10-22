"""Existing JSON video transport used by Zhenzhen and compatible providers.

No credentials, database or filesystem access. The application owns media
conversion, durable acceptance and archival. Only explicit 404/405 permits
trying a compatibility submit path; unknown responses never resubmit.
"""
import asyncio
import re
import time

import httpx
from fastapi import HTTPException
from enterprise.providers.submission import provider_submission_unknown, submission_json
from enterprise.providers.video_tasks import read_video_task, video_task_result


def json_video_body(payload, model, image_payload):
    body = {
        "prompt": payload.prompt,
        "model": model,
        "duration": payload.duration,
        "watermark": payload.watermark,
    }
    if payload.aspect_ratio:
        body["aspect_ratio"] = payload.aspect_ratio
        body["ratio"] = payload.aspect_ratio
    if payload.size:
        body["size"] = payload.size
    if payload.resolution:
        body["resolution"] = payload.resolution
    if image_payload:
        body["images"] = image_payload
    if payload.videos:
        body["videos"] = [v for v in payload.videos if v]
    if payload.enhance_prompt:
        body["enhance_prompt"] = True
    if payload.enable_upsample:
        body["enable_upsample"] = True
    if payload.seed is not None:
        body["seed"] = payload.seed
    if payload.camerafixed:
        body["camerafixed"] = True
    if payload.return_last_frame:
        body["return_last_frame"] = True
    if payload.generate_audio:
        body["generate_audio"] = True
    return body


async def generate_json_video(client, urls, headers, body, *, extract_task_id, output_urls, accepted, poll):
    raw = None
    for index, submit_url in enumerate(urls):
        response = await client.post(submit_url, headers=headers, json=body)
        if response.status_code >= 400:
            if response.status_code in (404, 405) and index < len(urls) - 1:
                continue
            if response.status_code >= 500:
                raise provider_submission_unknown(f"视频提交接口返回 HTTP {response.status_code}，是否已受理任务尚不确定")
            response.raise_for_status()
        raw = submission_json(response, kind="视频")
        break
    task_id = extract_task_id(raw) or raw.get("task_id") or raw.get("id")
    await accepted(task_id, submit_url)
    result = raw
    if task_id and video_task_result(raw, output_urls, str)["status"] != "succeeded":
        try:
            result = await poll(task_id, submit_url)
        except (HTTPException, httpx.HTTPError, ValueError) as exc:
            if getattr(exc, "provider_task_failed", False):
                setattr(exc, "upstream_task_id", task_id)
                raise
            raise provider_submission_unknown("已受理的视频任务查询未能确认最终结果", upstream_task_id=task_id) from exc
    videos = output_urls(result)
    if not videos:
        raise provider_submission_unknown("视频提交已返回，但没有可核对的视频结果", upstream_task_id=task_id or "")
    return task_id, result, videos


async def poll_video(client, urls, headers, output_urls, failure_message, *, timeout, initial_delay):
    """Live Zhenzhen tracking uses the same one-query parser as restart recovery."""
    deadline = time.monotonic() + timeout
    delay = max(2.0, initial_delay)
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        raw = await read_video_task(client, urls, headers)
        result = video_task_result(raw, output_urls, failure_message)
        if result["status"] == "succeeded":
            return raw
        if result["status"] == "failed":
            error = HTTPException(502, result["message"])
            error.provider_task_failed = True
            raise error
        if result["status"] == "manual":
            raise HTTPException(502, result["message"])
        delay = min(delay * 1.6, 12)
    raise HTTPException(504, "视频原任务查询超时")


def video_error_detail(text, provider, requested_model):
    provider_name = provider.get('name') or provider['id']
    # 1) 模型名不在上游支持范围 → 从错误信息里抽取合法列表展示
    valid_models_match = re.search(r"not in\s*\[([^\]]+)\]", text)
    if valid_models_match:
        valid_models = [m.strip() for m in valid_models_match.group(1).split(",") if m.strip()]
        sample = valid_models[:30]
        more = f"（共 {len(valid_models)} 个，仅显示前 {len(sample)} 个）" if len(valid_models) > len(sample) else ""
        hint = (
            f"上游「{provider_name}」当前调用接口不接受模型「{requested_model}」。\n\n"
            f"该接口返回的型号清单{more}：\n  {', '.join(sample)}\n\n"
            f"这不是整个平台的完整模型目录。请核对该型号对应的接口适配，或选择已适配型号；不会自动换接口重新生成。"
        )
        return hint
    # 2) 模型名合法但账号没开通通道
    if "channel not found" in text or "model_not_found" in text:
        hint = (
            f"上游「{provider_name}」没有为模型「{requested_model}」返回可用通道。\n\n"
            f"可能涉及型号/接口不匹配、账号权限或上游通道状态；此错误本身不能证明充值就能解决。\n\n"
            f"请由管理员核对该型号的接口适配与账号通道，不要重复提交生成。"
        )
        return hint
    if "text.duration" in text or "specified duration is not supported" in text:
        hint = (
            f"上游「{provider_name}」模型「{requested_model}」不支持当前时长参数。\n\n"
            f"不同视频模型支持的时长不一样；如果选择了模型不支持的时长，上游可能报错，"
            f"也可能自动按平台默认时长生成，例如 5 秒。\n\n"
            f"请把视频时长切回该模型支持的值，或改用支持更长时长的视频模型。"
        )
        return hint
    if "audio duration" in text.lower():
        too_long = "less than or equal" in text.lower() or "15.2" in text
        bound_hint = "太长（超过 15.2 秒）" if too_long else "太短（不足 1.8 秒）"
        hint = (
            f"上游「{provider_name}」模型「{requested_model}」拒绝了参考音频：时长{bound_hint}。\n\n"
            f"方舟 Seedance 的参考音频时长必须在 1.8 ~ 15.2 秒之间，"
            f"请把音频裁剪到这个区间后再作为参考音频输入。"
        )
        return hint
    if "inputimagesensitivecontentdetected" in text.lower() or "privacyinformation" in text.lower() or "may contain real person" in text.lower():
        hint = (
            f"上游「{provider_name}」拦截了输入参考图，原因是图片里可能包含真人身份/隐私信息。\n\n"
            f"这不是代码协议错误，而是火山视频模型的内容安全策略。\n\n"
            f"建议你这样处理：\n"
            f"  1. 改用非真人参考图，例如插画、AI 头像、商品图、场景图；\n"
            f"  2. 先把真人脸做模糊、遮挡、裁掉，或转成明显的二次元/插画风；\n"
            f"  3. 如果只是想做文生视频，先去掉参考图只保留文字提示词测试。"
        )
        return hint
    return f"上游视频接口错误：{text}"
