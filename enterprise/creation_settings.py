"""Translate composer choices at the existing image provider boundary."""
from urllib.parse import urlsplit

from fastapi import HTTPException

from enterprise.provider_image_profiles import image_profile_for
from enterprise.providers.suppliers import image_profile as builtin_image_profile


def _supports_background(provider, model, mode):
    maintained = builtin_image_profile(provider, model)
    profile = maintained or image_profile_for(provider, model)
    protocol_mode = "openai" if maintained else provider.get("image_request_mode") or "openai"
    if profile.get("mode") == "aspect-size" or protocol_mode not in {"openai", "openai-responses"}:
        return False
    if mode == "transparent" and "supports_transparent_background" in profile:
        return profile["supports_transparent_background"]
    if "supports_background" in profile:
        return profile["supports_background"]
    return urlsplit(provider.get("base_url") or "").hostname == "api.openai.com" and str(model).startswith("gpt-image-")


def supports_transparent_background(provider, model):
    return _supports_background(provider, model, "transparent")


def background_prompt(prompt, mode):
    if mode == "preserve":
        return prompt + "\n背景要求：保留参考图原有背景、场景及空间关系，只修改用户指定的内容。"
    return prompt


def native_background_parameters(provider, model, mode):
    if mode not in {"transparent", "opaque"}:
        return {}
    if not _supports_background(provider, model, mode):
        label = "透明背景" if mode == "transparent" else "不透明背景"
        raise HTTPException(400, f"当前图像模型未声明{label}能力，请切换支持的图像模型或选择自动背景")
    return {"background": mode, "output_format": "png"}
