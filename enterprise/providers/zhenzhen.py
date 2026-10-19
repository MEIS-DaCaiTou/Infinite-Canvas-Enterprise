"""Maintained Zhenzhen image contracts, not user-authored request templates.

Sources: https://gpt-best.apifox.cn/llms.txt and T8mars/Comfyui-zhenzhen.
Generations accepts reference images as JSON for these documented families.
Native Gemini, multipart masked editing and advanced layer outputs retain their
existing routes; this module does not speculate about unknown model names.
"""
from copy import deepcopy
from urllib.parse import urlsplit, quote
from fastapi import HTTPException
from enterprise.providers.image_task_protocol import SUCCESS_STATUSES, FAILED_STATUSES, task_status


RATIOS = ["4:3", "3:4", "16:9", "9:16", "2:3", "3:2", "1:1", "4:5", "5:4", "21:9"]
EXTENDED_RATIOS = RATIOS + ["1:4", "4:1", "8:1", "1:8"]


def _aspect(ratios=RATIOS, resolutions=None, **extra):
    return {
        "mode": "aspect-size", "ratios": list(ratios),
        "supports_image_size": resolutions is not None,
        "resolutions": list(resolutions or []),
        "supports_quality": False, "supports_mask": False,
        **extra,
    }


# Aliases share a documented request family. Parameter differences stay here,
# rather than growing model-name branches in main.py or the canvas UI.
IMAGE_FAMILIES = [
    (("nano-banana",), _aspect()),
    (("nano-banana-hd",), _aspect(fixed_resolution="4K")),
    (("nano-banana-2", "nano-banana-pro"), _aspect(resolutions=["1K", "2K", "4K"], max_references=14)),
    (("nano-banana-pro-2k",), _aspect(fixed_resolution="2K", max_references=14)),
    (("nano-banana-pro-4k",), _aspect(fixed_resolution="4K", max_references=14)),
    (("gemini-nano-banana-2.1",), _aspect(EXTENDED_RATIOS, ["1K", "2K", "4K"], max_references=14)),
    (("gemini-3.1-flash-image", "gemini-3.1-flash-image-preview"), _aspect(EXTENDED_RATIOS, ["512", "1K", "2K", "4K"])),
    (("gemini-3.1-flash-lite-image",), _aspect(EXTENDED_RATIOS)),
    (("gpt-image-2",), {"mode": "pixel", "supports_quality": True, "supports_mask": True}),
    (("gpt-image-2-all",), {"mode": "pixel", "supports_quality": True, "supports_mask": False,
                          "reference_endpoint": "edits"}),
    (("seedream-v5-pro",), {"mode": "pixel", "supports_quality": False, "supports_mask": False}),
    (("seedream-v5-flash/layer-decomposition",), {"mode": "pixel", "supports_quality": False,
        "supports_mask": False, "min_references": 1, "max_references": 1, "layer_output": True}),
]
IMAGE_MODELS = {name: profile for names, profile in IMAGE_FAMILIES for name in names}


def is_zhenzhen(provider):
    """An explicit supplier ID also supports enterprise-managed proxy addresses."""
    provider = provider or {}
    return str(provider.get("id") or "").lower() == "zhenzhen" or urlsplit(str(provider.get("base_url") or "")).hostname == "ai.t8star.org"


def image_profile(provider, model):
    if not is_zhenzhen(provider):
        return {}
    return deepcopy(IMAGE_MODELS.get(str(model or "").strip(), {}))


def public_image_profiles(provider):
    return {model: image_profile(provider, model) for model in (provider or {}).get("image_models", []) if image_profile(provider, model)}


def image_body(model, prompt, size, quality, references, aspect_parameters):
    """Only fields supported by the selected maintained contract are sent."""
    profile = IMAGE_MODELS[model]
    if len(references) < profile.get("min_references", 0) or len(references) > profile.get("max_references", 16):
        raise HTTPException(400, "当前模型需要指定数量的参考图；图层拆分需要且只接受一张原图，未提交生成")
    body = {"model": model, "prompt": prompt, "response_format": "url"}
    if profile["mode"] == "aspect-size":
        body.update(aspect_parameters)
    else:
        body["size"] = size
        if quality and profile.get("supports_quality"):
            body["quality"] = quality
    if references:
        body["image"] = references[0] if profile.get("layer_output") else references
    if profile.get("layer_output"):
        body["output_format"] = "png"
    return body


async def submit_image(client, endpoint, headers, *, model, prompt, size, quality, references, aspect_parameters, edit_endpoint=None):
    # One chosen endpoint, one paid submission. No edits/generations probing.
    if references and IMAGE_MODELS[model].get("reference_endpoint") == "edits":
        endpoint = edit_endpoint or endpoint.removesuffix("/generations") + "/edits"
    return await client.post(endpoint, headers=headers, json=image_body(model, prompt, size, quality, references, aspect_parameters))


def image_headers(authorization, *, json_body=True):
    """Credentials are resolved by the application, never read or persisted here."""
    headers = {"Accept": "application/json", "Authorization": authorization}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def image_task_endpoint(base_url, task_id):
    base = base_url.rstrip("/")
    return f"{base if base.endswith('/v1') else base + '/v1'}/images/tasks/{quote(str(task_id), safe='')}"


async def query_image(client, endpoint, headers, request):
    """Query the original accepted identity; safe GET retries reuse shared policy."""
    response = await request(client, "GET", endpoint, attempts=3, headers=headers)
    response.raise_for_status()
    return response.json()


def image_query_status(payload, *, has_images):
    """Maintained async status contract; an unknown reply needs human review.

    https://gpt-best.apifox.cn/api-356258956 documents IN_PROGRESS,
    FAILURE and SUCCESS. Retain existing terminal aliases for managed proxies.
    """
    status = task_status(payload)
    if status in FAILED_STATUSES:
        return "failed"
    if status == "IN_PROGRESS":
        return "running"
    if has_images and (not status or status in SUCCESS_STATUSES):
        return "succeeded"
    return "manual"


def video_submit_endpoints(base_url):
    """Official unified v2 first; managed legacy proxies retain explicit 404/405 fallback.

    https://gpt-best.apifox.cn/doc-7324259 documents the unified JSON video API.
    Existing receipts keep their actual v1/v2 binding for later queries.
    """
    base = base_url.rstrip("/")
    return [f"{base}/v2/videos/generations", f"{base}/v1/videos/generations"]


def video_headers(authorization):
    # Unified video always uses Bearer, independently of an image/chat protocol.
    return image_headers(authorization)
