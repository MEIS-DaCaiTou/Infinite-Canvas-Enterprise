"""Maintained Zhenzhen image contracts, not user-authored request templates.

Sources: https://gpt-best.apifox.cn/llms.txt and T8mars/Comfyui-zhenzhen.
Generations accepts reference images as JSON for these documented families.
Native Gemini, multipart masked editing and advanced layer outputs retain their
existing routes; this module does not speculate about unknown model names.
"""
from copy import deepcopy
from urllib.parse import urlsplit


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
    (("seedream-v5-pro",), {"mode": "pixel", "supports_quality": False, "supports_mask": False}),
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
    body = {"model": model, "prompt": prompt, "response_format": "url"}
    if profile["mode"] == "aspect-size":
        body.update(aspect_parameters)
    else:
        body["size"] = size
        if quality and profile.get("supports_quality"):
            body["quality"] = quality
    if references:
        body["image"] = references
    return body


async def submit_image(client, endpoint, headers, *, model, prompt, size, quality, references, aspect_parameters):
    # One chosen endpoint, one paid submission. No edits/generations probing.
    return await client.post(endpoint, headers=headers, json=image_body(model, prompt, size, quality, references, aspect_parameters))
