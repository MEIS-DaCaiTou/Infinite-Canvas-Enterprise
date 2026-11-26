"""Maintained Zhenzhen image contracts, not user-authored request templates.

Sources: https://gpt-best.apifox.cn/llms.txt and T8mars/Comfyui-zhenzhen.
GPT Image 2.5 sync/size/reference limits also follow T8-penguin-canvas
6181ef59, backend/src/routes/proxy.js (the ai.t8star.org workshop route).
Generations accepts reference images as JSON for these documented families.
Native Gemini, multipart masked editing and advanced layer outputs retain their
existing routes; this module does not speculate about unknown model names.
"""
import base64
from copy import deepcopy
from urllib.parse import urlsplit, quote
from httpx import URL
import httpx
from fastapi import HTTPException
from enterprise.providers.image_task_protocol import SUCCESS_STATUSES, FAILED_STATUSES, task_status
from enterprise.providers.image_execution import complete_image_submission
from enterprise.providers.submission import provider_submission_unknown
from enterprise.seedream_capabilities import image_profile as seedream_profile, validate_request as validate_seedream_request


RATIOS = ["4:3", "3:4", "16:9", "9:16", "2:3", "3:2", "1:1", "4:5", "5:4", "21:9"]
EXTENDED_RATIOS = RATIOS + ["1:4", "4:1", "8:1", "1:8"]


def _aspect(ratios=RATIOS, resolutions=None, **extra):
    return {
        "mode": "aspect-size", "ratios": list(ratios),
        "supports_image_size": resolutions is not None,
        "resolutions": list(resolutions or []),
        "supports_quality": False, "supports_mask": False,
        "supports_auto_size": True, "supports_custom_size": False,
        **extra,
    }


def _gpt(**extra):
    return {"mode": "pixel", "supports_quality": True, "supports_mask": True,
            "supports_auto_size": True, "supports_custom_size": True,
            "size_rules": {"max_edge": 3840, "multiple": 16, "max_aspect": 3,
                           "min_pixels": 655360, "max_pixels": 8294400}, **extra}


# Aliases share a documented request family. Parameter differences stay here,
# rather than growing model-name branches in main.py or the canvas UI.
IMAGE_FAMILIES = [
    (("nano-banana",), _aspect()),
    (("nano-banana-hd",), _aspect(fixed_resolution="4K")),
    (("nano-banana-2", "nano-banana-pro"), _aspect(resolutions=["1K", "2K", "4K"], max_references=14)),
    (("nano-banana-pro-2k",), _aspect(fixed_resolution="2K", max_references=14)),
    (("nano-banana-pro-4k",), _aspect(fixed_resolution="4K", max_references=14)),
    (("nano-banana-2-2k",), _aspect(fixed_resolution="2K", max_references=14)),
    (("nano-banana-2-4k",), _aspect(fixed_resolution="4K", max_references=14)),
    (("gemini-nano-banana-2.1",), _aspect(EXTENDED_RATIOS, ["1K", "2K", "4K"], max_references=14)),
    (("gemini-nano-banana-2.1-2k",), _aspect(EXTENDED_RATIOS, fixed_resolution="2K", max_references=14)),
    (("gemini-nano-banana-2.1-4k",), _aspect(EXTENDED_RATIOS, fixed_resolution="4K", max_references=14)),
    (("gemini-3.1-flash-image", "gemini-3.1-flash-image-preview"), _aspect(EXTENDED_RATIOS, ["512", "1K", "2K", "4K"])),
    (("gemini-3.1-flash-lite-image",), _aspect(EXTENDED_RATIOS)),
    (("gpt-image-2",), _gpt()),
    (("gpt-image-2-all",), _gpt(supports_mask=False, reference_endpoint="edits")),
    (("gpt-image-2.5-flare", "gpt-image-2.5-sunburst"),
        _gpt(reference_endpoint="edits", reference_encoding="multipart", supports_auto_size=False,
             max_references=14, supports_async=False)),
    (("gpt-image-2.6-flare", "gpt-image-2.6-sunburst"),
        _gpt(reference_endpoint="edits", reference_encoding="multipart")),
    # Supplier SDK offers these concrete sizes, but no complete custom-size
    # contract. Keep its confirmed presets distinct from arbitrary dimensions.
    (("seedream-v5-pro",), {"mode": "pixel", "supports_quality": False, "supports_mask": False,
        "supports_auto_size": False, "supports_custom_size": False, "max_references": 10,
        "size_presets": ["1024x1024", "1536x1024", "1024x1536", "2048x2048", "4096x4096"]}),
    # 2026-11-19 supplier catalog: native background and PNG output. The layer
    # API still links its single-source contract; do not inherit the old name.
    # 2026-11-26: both async and native sync requests returned RGB despite
    # background=transparent and an RGBA input on this maintained channel.
    # This does not remove Ark's native RGBA capability or layer decomposition.
    (("seedream-v5.5",), {**seedream_profile(), "supports_layer_options": False,
        "supports_transparent_background": False}),
    # The Images async wrapper flattens this model's layer objects to URLs,
    # discarding placement and OCR. New decompositions need the synchronous
    # response; existing accepted async tasks keep their original query route.
    (("seedream-v5.5/layer-decomposition",), {**seedream_profile(layers=True), "supports_async": False,
        "supports_layer_limit": False, "supports_layer_text_recognition": False,
        "supports_empty_layer_prompt": False}),
    (("seedream-v5-flash/layer-decomposition",), {"mode": "pixel", "supports_quality": False,
        "supports_mask": False, "min_references": 1, "max_references": 1, "layer_output": True}),
]
IMAGE_MODELS = {name: profile for names, profile in IMAGE_FAMILIES for name in names}

DEFAULT_BASE_URL = "https://ai.t8star.org/v1"
DEFAULT_IMAGE_MODELS = [
    "gemini-nano-banana-2.1", "gemini-nano-banana-2.1-2k", "gemini-nano-banana-2.1-4k",
    "gpt-image-2", "gpt-image-2-all", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst",
    "gpt-image-2.6-flare", "gpt-image-2.6-sunburst", "nano-banana-2-2k", "nano-banana-2-4k",
    "nano-banana-pro", "nano-banana-pro-2k", "nano-banana-pro-4k", "seedream-v5-pro",
    "seedream-v5.5", "seedream-v5.5/layer-decomposition",
]


def provider_preset():
    """Public setup defaults; configured models and credentials remain user-owned."""
    return {"supplier": "zhenzhen", "name": "贞贞平台", "base_url": DEFAULT_BASE_URL,
            "protocol": "openai", "image_request_mode": "openai",
            "image_models": list(DEFAULT_IMAGE_MODELS)}


def configure_provider(provider):
    """Apply an explicitly selected supplier at settings save, never during recovery."""
    if provider.get("supplier") != "zhenzhen":
        return provider
    return {**provider, "base_url": provider.get("base_url") or DEFAULT_BASE_URL,
            "protocol": "openai", "image_request_mode": "openai", "model_protocols": {}}


def is_zhenzhen(provider):
    """Recognize selected suppliers and legacy IDs/hosts, including managed proxies."""
    provider = provider or {}
    if provider.get("supplier"):
        return provider["supplier"] == "zhenzhen"
    return (provider.get("supplier") == "zhenzhen"
            or str(provider.get("id") or "").lower() == "zhenzhen"
            or urlsplit(str(provider.get("base_url") or "")).hostname == "ai.t8star.org")


def image_profile(provider, model):
    if not is_zhenzhen(provider):
        return {}
    return deepcopy(IMAGE_MODELS.get(str(model or "").strip(), {}))


def public_image_profiles(provider):
    return {model: image_profile(provider, model) for model in (provider or {}).get("image_models", []) if image_profile(provider, model)}


def image_body(model, prompt, size, quality, references, aspect_parameters, background_options=None, layer_options=None):
    """Only fields supported by the selected maintained contract are sent."""
    profile = IMAGE_MODELS[model]
    if profile.get('supports_empty_layer_prompt') is False and not prompt.strip():
        raise HTTPException(400, "当前贞贞拆层渠道需要拆分说明")
    if profile.get("model_family") == "seedream-5.5":
        try:
            size = validate_seedream_request(size, references, layers=bool(profile.get("layer_output")))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if profile.get("layer_output") and background_options:
            raise HTTPException(400, "图层拆分不支持背景参数，请使用自动背景")
    if len(references) < profile.get("min_references", 0) or len(references) > profile.get("max_references", 16):
        raise HTTPException(400, f"当前模型需要 {profile.get('min_references', 0)}–{profile.get('max_references', 16)} 张参考图，未提交生成")
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
        if profile.get("model_family") == "seedream-5.5":
            body["watermark"] = False
        if layer_options is not None:
            from enterprise.image_layers import layer_parameters
            options = layer_parameters(layer_options)["layer_decomposition_options"]
            if (profile.get("supports_layer_limit") is False and options.get("max_images") is not None or
                    profile.get("supports_layer_text_recognition") is False and options.get("text_recognition")):
                raise HTTPException(400, "当前贞贞拆层渠道未落实层数上限和文字识别；请清空上限并关闭提取文字，或选择方舟官方")
            if profile.get("supports_layer_limit") is not False:
                body["layer_decomposition_options"] = options
            body["size"] = size
    if profile.get("supports_background"):
        body.update(background="auto", output_format="png", watermark=False)
        body.update(background_options or {})
    return body


def _image_edit_files(references):
    extensions = {"data:image/png": "png", "data:image/jpeg": "jpg", "data:image/webp": "webp"}
    files = []
    for index, value in enumerate(references, 1):
        mime, separator, encoded = value.partition(";base64,")
        if not separator or mime not in extensions:
            raise HTTPException(400, "贞贞文件编辑需要 PNG、JPEG 或 WebP 图片文件。请先将远程图片导入素材库。")
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise HTTPException(400, "参考图片无法解码，请重新选择图片。") from exc
        if not content:
            raise HTTPException(400, "参考图片为空，请重新选择图片。")
        files.append(("image", (f"reference-{index}.{extensions[mime]}", content, mime.removeprefix("data:"))))
    return files


async def submit_image(client, endpoint, headers, *, model, prompt, size, quality, references, aspect_parameters,
                       edit_endpoint=None, multipart_edit=False, background_options=None, layer_options=None):
    # One chosen endpoint, one paid submission. No edits/generations probing.
    body = image_body(model, prompt, size, quality, references, aspect_parameters, background_options, layer_options)
    if references and IMAGE_MODELS[model].get("reference_endpoint") == "edits":
        endpoint = edit_endpoint or endpoint.removesuffix("/generations") + "/edits"
        if multipart_edit or IMAGE_MODELS[model].get("reference_encoding") == "multipart":
            # GPT 2.5 synchronous edits and the async edits handler both parse
            # files. HTTPX adds the multipart boundary.
            files = _image_edit_files(body.pop("image"))
            headers = {name: value for name, value in headers.items() if name.lower() != "content-type"}
            return await client.post(endpoint, headers=headers, data=body, files=files)
    return await client.post(endpoint, headers=headers, json=body)


def async_image_submit_url(endpoint, query_endpoint, *, model=""):
    """Opt in only when submission and original-task query share the Images route."""
    if IMAGE_MODELS.get(model, {}).get('supports_async') is False:
        return None
    url = URL(endpoint)
    query = URL(query_endpoint)
    image_path, separator, _ = query.path.rpartition("/images/tasks/")
    path = url.path.rstrip("/")
    if not separator or path not in {f"{image_path}/images/generations", f"{image_path}/images/edits"}:
        return None
    if url.copy_with(path=path, query=None, fragment=None) != query.copy_with(path=path, query=None, fragment=None):
        return None
    return str(url.copy_set_param("async", "true"))


def image_submission_task_id(payload):
    """A request ID is diagnostic metadata, not a queryable image task ID."""
    nested = payload.get("data")
    for source in (payload, nested):
        value = source.get("task_id") if isinstance(source, dict) else None
        if isinstance(value, str) and 0 < len(value.strip()) <= 240:
            return value.strip()
    return None


async def execute_image(client, endpoint, headers, *, provider, extract_image, extract_task_id,
                        wait_for_task, receipt_sink=None, async_endpoints=(), **parameters):
    """One selected endpoint and one POST, followed only by original-ID queries."""
    try:
        response = await submit_image(client, endpoint, headers, **parameters)
    except httpx.HTTPError as exc:
        raise provider_submission_unknown('图像请求的响应中断，是否已被供应商受理尚不确定') from exc
    image, raw = await complete_image_submission(response, client=client, provider=provider,
        extract_image=extract_image, extract_task_id=extract_task_id, wait_for_task=wait_for_task,
        receipt_sink=receipt_sink,
        async_task_id=image_submission_task_id if str(response.request.url) in async_endpoints else None)
    return image, normalize_layer_outputs(raw)


def normalize_layer_outputs(payload):
    """Map the supplier's observed layer fields to the shared image contract.

    Seedream 5.5 synchronous replies use zindex/boundingBox/outputType. Keep
    original fields and prefer an existing canonical value. Missing OCR or
    geometry remains missing; it cannot be reconstructed from a URL alone.
    """
    if isinstance(payload, list):
        return [normalize_layer_outputs(item) for item in payload]
    if not isinstance(payload, dict):
        return payload
    result = dict(payload)
    for original, canonical in (("zindex", "z_index"), ("boundingBox", "bounding_box"),
                                ("outputType", "output_format")):
        if original in result and canonical not in result:
            result[canonical] = result[original]
    for key in ("data", "result", "images", "image_items"):
        if key in result:
            result[key] = normalize_layer_outputs(result[key])
    return result


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
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Invalid Zhenzhen image task response")
    return normalize_layer_outputs(payload)


def image_query_status(payload, *, has_images):
    """Maintained async status contract; an unknown reply needs human review.

    The documented statuses include IN_PROGRESS, FAILURE and SUCCESS.
    A real async image query also returned NOT_START before completion.
    """
    status = task_status(payload)
    if status in FAILED_STATUSES:
        return "failed"
    if status in {"NOT_START", "IN_PROGRESS"}:
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
