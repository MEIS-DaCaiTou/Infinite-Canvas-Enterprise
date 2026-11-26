"""OpenAI-compatible Images request encoding and existing rejection policy.

Receives resolved endpoints, headers and prepared file parts. User permissions,
filesystem lookup, task persistence and result archival remain with callers.
"""
from contextlib import nullcontext

import httpx
from fastapi import HTTPException

from enterprise.providers.submission import image_api_explicitly_rejected, provider_submission_unknown


def generation_body(model, prompt, size, quality, *, background=None, aspect=None, gpt2=False, mask=False):
    if aspect is not None:
        body = {"model": model, "prompt": prompt, "response_format": "url", **aspect}
    else:
        body = {"model": model, "prompt": prompt, "size": size}
        if not gpt2 or mask:
            body.update(response_format="url", n=1)
        body.update(background or {})
    if quality:
        body["quality"] = quality
    return body


def edit_body(model, prompt, size, quality, *, background=None, aspect=None):
    body = {"model": model, "prompt": prompt, "size": size, **(background or {})}
    if aspect is not None:
        body.pop("size")
        body.update(aspect)
    if quality:
        body["quality"] = quality
    return body


async def submit_json_image(client, endpoint, headers, *, model, prompt, size, references):
    """Agnes-style generations: reference and response format inside extra_body."""
    extra = {"response_format": "url"}
    if references:
        extra["image"] = references
    return await client.post(endpoint, headers=headers,
        json={"model": model, "prompt": prompt, "size": size, "extra_body": extra})


async def submit_image(client, generation_endpoint, edit_endpoint, *, headers, edit_headers,
                       model, prompt, size, quality="", background=None, aspect=None,
                       gpt2=False, mask=False, edit_files=None, reference_urls=None,
                       allow_generation_fallback=True, allow_edit_fallback=True):
    """Encode one request, preserving only the existing explicit-rejection switch.

    edit_files scopes material resources to the edit POST. reference_urls is a
    lazy async material callback, used only after a proven unsupported edit.
    """
    async def post_edit():
        async with (edit_files if edit_files is not None else nullcontext({})) as files:
            return await client.post(edit_endpoint, headers=edit_headers,
                data=edit_body(model, prompt, size, quality, background=background, aspect=aspect), files=files)

    if reference_urls is None:
        response = await client.post(generation_endpoint, headers=headers,
            json=generation_body(model, prompt, size, quality,
                background=background, aspect=aspect, gpt2=gpt2, mask=mask))
        if allow_generation_fallback and image_api_explicitly_rejected(response):
            response = await post_edit()
        return response

    try:
        response = await post_edit()
    except httpx.HTTPError as exc:
        raise provider_submission_unknown("图像编辑请求的响应中断，是否已被供应商受理尚不确定") from exc
    if not allow_edit_fallback or not image_api_explicitly_rejected(response):
        return response
    failed_status, failed_text = response.status_code, response.text[:500]
    if gpt2 or aspect is not None:
        raise HTTPException(502,
            f"{model} 编辑接口 /images/edits 调用失败：{failed_text[:300] or failed_status}。已停止自动重试，避免上游可能已扣费后再次请求。")
    body = generation_body(model, prompt, size, quality, background=background)
    body["image"] = await reference_urls()
    response = await client.post(generation_endpoint, headers=headers, json=body)
    if image_api_explicitly_rejected(response):
        raise HTTPException(502,
            f"编辑接口 /images/edits 调用失败，且该平台不支持 /images/generations：{failed_text[:300] or failed_status}")
    return response
