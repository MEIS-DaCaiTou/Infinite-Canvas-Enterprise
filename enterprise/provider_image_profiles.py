"""Built-in supplier capabilities with optional temporary profiles for new models."""
from math import gcd
import re
from enterprise.providers.suppliers import image_profile as builtin_image_profile

IMAGE_PROFILE_TEMPLATES = {
    "standard": {"label": "OpenAI 像素尺寸", "mode": "pixel", "supports_quality": True},
    "aspect-size": {
        "label": "比例 + 分辨率（临时兼容）", "mode": "aspect-size",
        "ratios": ["16:9", "1:1", "1:4", "1:8", "21:9", "2:3", "3:2", "3:4", "4:1", "4:3", "4:5", "5:4", "8:1", "9:16"],
        "resolutions": ["1K", "2K", "4K"], "max_references": 14,
        "supports_quality": False, "supports_mask": False,
    },
}


class ImageProfileError(ValueError):
    pass


def normalize_image_profile(value):
    if not isinstance(value, dict) or value.get("mode") not in {"pixel", "aspect-size"}:
        return {}
    profile = {"mode": value["mode"]}
    for key in ("template_id", "label", "fixed_resolution"):
        if isinstance(value.get(key), str):
            profile[key] = value[key]
    for key in ("ratios", "resolutions"):
        if isinstance(value.get(key), list):
            values = [str(v).strip() for v in value[key] if str(v).strip()]
            profile[key] = list(dict.fromkeys(v.upper() if key == "resolutions" else v for v in values))
    for key in ("supports_quality", "supports_mask", "supports_image_size", "supports_background"):
        if isinstance(value.get(key), bool):
            profile[key] = value[key]
    if isinstance(value.get("max_references"), int) and not isinstance(value["max_references"], bool):
        profile["max_references"] = max(0, min(16, value["max_references"]))
    return profile


def normalize_model_image_profiles(value):
    if not isinstance(value, dict):
        return {}
    return {str(name): normalize_image_profile(profile) for name, profile in value.items() if isinstance(profile, dict)}


def image_profile_for(provider, model):
    builtin = builtin_image_profile(provider, model)
    if builtin:
        return builtin
    profiles = normalize_model_image_profiles((provider or {}).get("model_image_profiles"))
    return normalize_image_profile(profiles.get(model) or (provider or {}).get("image_profile"))


def validate_image_size(size, profile, requested=None):
    """Validate the maintained size contract before media preparation or HTTP.

    Consumes the same public profile as the original pages. It does not resize,
    choose another model, or apply new rules to already accepted task queries.
    """
    if (requested or {}).get("layer_options") is not None and profile.get("layer_profile"):
        profile = profile["layer_profile"]
    if not profile or profile.get("mode") == "aspect-size" or not any(key in profile for key in ("size_rules", "size_presets", "resolutions", "supports_auto_size")):
        return
    raw = str(size or "").strip().lower()
    resolution = str((requested or {}).get("resolution") or "").upper()
    if resolution and profile.get("resolutions") and resolution not in profile["resolutions"]:
        raise ImageProfileError("当前模型不支持分辨率 " + resolution + "；请选择 " + "、".join(profile["resolutions"]))
    if raw == "auto":
        if profile.get("supports_auto_size") is False:
            raise ImageProfileError("当前模型不支持自动尺寸，请选择已维护尺寸")
        return
    if raw.upper() in (profile.get("resolutions") or []):
        return
    match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", raw)
    if not match:
        raise ImageProfileError("图片尺寸应为宽×高像素，请检查尺寸设置")
    if profile.get("size_presets") and raw not in profile["size_presets"]:
        raise ImageProfileError("当前模型仅开放已维护尺寸：" + "、".join(profile["size_presets"]) + "；请修正原尺寸后生成")
    if profile.get("supports_custom_size") is False and not profile.get("size_presets"):
        raise ImageProfileError("当前模型不支持自定义像素尺寸，请选择已维护分辨率")
    width, height = map(int, match.groups())
    rules = profile.get("size_rules") or {}
    if rules.get("multiple") and (width % rules["multiple"] or height % rules["multiple"]):
        raise ImageProfileError(f"宽高必须都是 {rules['multiple']} 的倍数，当前尺寸 {raw}")
    if rules.get("max_edge") and max(width, height) > rules["max_edge"]:
        raise ImageProfileError(f"当前模型最长边不能超过 {rules['max_edge']}px，当前尺寸 {raw}")
    if rules.get("max_aspect") and max(width, height) > min(width, height) * rules["max_aspect"]:
        raise ImageProfileError(f"当前模型长短边比例不能超过 {rules['max_aspect']}:1，当前尺寸 {raw}")
    pixels = width * height
    if (rules.get("min_pixels") and pixels < rules["min_pixels"]) or (rules.get("max_pixels") and pixels > rules["max_pixels"]):
        raise ImageProfileError(f"当前模型像素总数应为 {rules.get('min_pixels', 1)}–{rules.get('max_pixels', '不限')}，当前尺寸 {raw}")


def build_aspect_parameters(size, profile, inferred, requested=None):
    """Preserve explicit user choices; old clients can supply inferred pixel dimensions."""
    raw = str(size or "").strip().lower()
    aspect, resolution = inferred
    if raw in {"", "auto", "default"}:
        aspect = "auto"
    elif ":" in raw:
        aspect = raw.replace(" ", "")
    if (requested or {}).get("aspect_ratio"):
        aspect = str(requested["aspect_ratio"]).strip()
    if (requested or {}).get("resolution"):
        resolution = str(requested["resolution"]).strip()
    # Preserve equivalent ratios, and the <=16px rounding in legacy presets.
    # Arbitrary custom dimensions must not become a nearest supported ratio.
    ratio_value = aspect
    pixels = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", raw)
    if pixels and not (requested or {}).get("aspect_ratio"):
        ratio_value = ":".join(pixels.groups())
        iw, ih = map(int, pixels.groups())
        inferred_parts = re.fullmatch(r"([1-9]\d*):([1-9]\d*)", aspect)
        if inferred_parts:
            rw, rh = map(int, inferred_parts.groups())
            if abs(iw * rh - ih * rw) <= 16 * max(rw, rh):
                ratio_value = aspect
    parts = re.fullmatch(r"([1-9]\d*):([1-9]\d*)", ratio_value)
    if parts:
        width, height = map(int, parts.groups())
        common = gcd(width, height)
        aspect = f"{width // common}:{height // common}"
        for candidate in profile.get("ratios") or []:
            cw, ch = map(int, candidate.split(":"))
            if width * ch == height * cw:
                aspect = candidate
                break
    ratios = profile.get("ratios") or []
    if ratios and aspect != "auto" and aspect not in ratios:
        original = f"（原值 {ratio_value}）" if ratio_value != aspect else ""
        raise ImageProfileError("当前模型不支持画幅 " + aspect + original + "；请选择 auto 或 " + ", ".join(ratios))
    if profile.get("supports_image_size") is False:
        return {"aspect_ratio": aspect}
    resolutions = profile.get("resolutions") or []
    if resolutions and resolution.upper() not in resolutions:
        raise ImageProfileError("当前模型不支持分辨率 " + resolution.upper())
    return {"aspect_ratio": aspect, "image_size": resolution.upper()}
