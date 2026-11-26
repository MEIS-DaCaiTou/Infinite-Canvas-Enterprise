"""Ark image encoding/execution; credentials and media are supplied by callers.

Seedream 5.5 is synchronous. request_id is diagnostic, never a pollable task ID.
Source: https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh
"""
from urllib.parse import urlsplit
import re

import httpx
from fastapi import HTTPException

from enterprise.image_layers import layer_parameters
from enterprise.seedream_capabilities import NATIVE_MODEL, image_profile as seedream_profile, validate_request
from enterprise.providers.image_execution import complete_image_submission
from enterprise.providers.submission import provider_submission_unknown

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
IMAGE_TASK_QUERY_SUPPORTED = False


def is_seedream_model(model):
    value = str(model or "").strip().lower()
    return "seedream" in value or "doubao-seedream" in value


def normalize_legacy_size(size, model=""):
    """Keep pre-5.5 requests unchanged; 5.5 uses its exact model contract."""
    match = re.fullmatch(r"\s*(\d+)\s*[xX*]\s*(\d+)\s*", str(size or ""))
    width, height = map(int, match.groups()) if match else (0, 0)
    raw = str(size or "").strip().lower()
    if not width or not height:
        if raw == "4k":
            return "4096x4096"
        if raw == "2k":
            return "2048x2048"
        return "2048x2048" if is_seedream_model(model) else (size or "1024x1024")
    if not is_seedream_model(model):
        return f"{width}x{height}"
    ratios = [(1, 1), (4, 3), (3, 4), (16, 9), (9, 16), (21, 9), (9, 21),
              (3, 2), (2, 3), (5, 4), (4, 5)]
    rw, rh = min(ratios, key=lambda item: abs(width / max(1, height) - item[0] / item[1]))
    scale = max((3686400 / max(1, rw * rh)) ** .5, 1536 / max(1, min(rw, rh)))
    target_w, target_h = rw * scale, rh * scale
    cap = min(1.0, 4096 / max(target_w, target_h))
    target_w, target_h = target_w * cap, target_h * cap
    snapped_w, snapped_h = max(64, int(target_w // 16) * 16), max(64, int(target_h // 16) * 16)
    while snapped_w * snapped_h < 3686400:
        if snapped_w <= snapped_h:
            snapped_w += 16
        else:
            snapped_h += 16
        if max(snapped_w, snapped_h) > 4096:
            break
    return f"{snapped_w}x{snapped_h}"


def is_provider(provider):
    provider = provider or {}
    if provider.get("supplier"):
        return provider["supplier"] == "volcengine"
    return (provider.get("protocol") == "volcengine" or provider.get("id") == "volcengine"
            or urlsplit(provider.get("base_url") or "").hostname == "ark.cn-beijing.volces.com")


def provider_preset():
    return {"supplier": "volcengine", "name": "火山方舟", "base_url": DEFAULT_BASE_URL,
            "protocol": "volcengine", "image_request_mode": "openai", "image_models": [NATIVE_MODEL]}


def configure_provider(provider):
    if provider.get("supplier") != "volcengine":
        return provider
    return {**provider, "base_url": provider.get("base_url") or DEFAULT_BASE_URL,
            "protocol": "volcengine", "image_request_mode": "openai", "model_protocols": {}}


def image_profile(provider, model):
    return {**seedream_profile(), "supports_async": False} if is_provider(provider) and model == NATIVE_MODEL else {}


def image_body(model, prompt, size, references, *, layer_options=None, background_options=None):
    layers = layer_options is not None
    if model != NATIVE_MODEL:
        body = {"model": model, "prompt": prompt, "response_format": "url",
                "size": size if layers else normalize_legacy_size(size, model)}
        if references:
            body["image"] = list(references)
        if layers:
            if len(references) != 1:
                raise HTTPException(400, "图层拆分需要一张原图")
            body.update(layer_decomposition=True, image=references[0], output_format="png",
                        size=size if size in {"auto", "1K", "1.5K", "2K"} else "auto",
                        **layer_parameters(layer_options))
        return body
    try:
        size = validate_request(size, references, layers=layers)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    body = {"model": model, "prompt": prompt, "size": size, "response_format": "url",
            "output_format": "png", "watermark": False}
    if layers:
        if background_options:
            raise HTTPException(400, "图层拆分不支持背景参数，请使用自动背景")
        body.update(layer_decomposition=True, image=references[0], **layer_parameters(layer_options))
        if not prompt.strip():
            body.pop("prompt")
    else:
        if references:
            body["image"] = list(references)
        body["background"] = "auto"
        body.update(background_options or {})
    return body


async def execute_image(client, endpoint, headers, *, provider, model, prompt, size, references,
                        extract_image, receipt_sink=None, layer_options=None, background_options=None):
    body = image_body(model, prompt, size, references, layer_options=layer_options,
                      background_options=background_options)
    try:
        response = await client.post(endpoint, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise provider_submission_unknown("方舟图像响应中断，是否完成尚不确定；请核对原调用记录") from exc
    if response.is_error:
        try:
            raw = response.json()
        except ValueError:
            raw = {}
        error = raw.get("error", {}) if isinstance(raw, dict) else {}
        if receipt_sink is not None:
            receipt_sink.identify(response.headers, raw=raw)
        code = error.get("code", "") if isinstance(error, dict) else ""
        messages = {
            "SetLimitExceeded": "方舟模型用量上限已触发，模型服务已暂停；请管理员在方舟开通管理页调整用量上限或安心体验模式",
            "AccountQuotaExceeded": "方舟账号额度不足；请管理员在方舟控制台核对账户额度",
        }
        overdue = response.status_code == 403 and isinstance(error, dict) and "overdue balance" in str(error.get("message", "")).lower()
        if overdue or response.status_code == 429 and code in messages:
            request_id = raw.get("request_id") or response.headers.get("x-request-id", "")
            detail = "方舟账号欠费，当前模型调用被暂停；请管理员在方舟费用中心核对并处理欠费" if overdue else messages[code]
            if code:
                detail += f"（{code}）"
            if request_id:
                detail += f"；request_id={request_id}"
            raise HTTPException(response.status_code, detail)
    return await complete_image_submission(response, client=client, provider=provider,
        extract_image=extract_image, extract_task_id=lambda _: None, wait_for_task=None,
        receipt_sink=receipt_sink, async_task_id=lambda _: None)
