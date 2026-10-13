"""Image parameter templates and capabilities. Pure data, independent of HTTP/OS/runtime."""

IMAGE_PROFILE_TEMPLATES = {
    "standard": {"label": "OpenAI 像素尺寸", "mode": "pixel", "supports_quality": True},
    "aspect-size": {
        "label": "比例 + 分辨率（Zhenzhen / Nano Banana）", "mode": "aspect-size",
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
    for key in ("template_id", "label"):
        if isinstance(value.get(key), str):
            profile[key] = value[key]
    for key in ("ratios", "resolutions"):
        if isinstance(value.get(key), list):
            values = [str(v).strip() for v in value[key] if str(v).strip()]
            profile[key] = list(dict.fromkeys(v.upper() if key == "resolutions" else v for v in values))
    for key in ("supports_quality", "supports_mask"):
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
    profiles = normalize_model_image_profiles((provider or {}).get("model_image_profiles"))
    return normalize_image_profile(profiles.get(model) or (provider or {}).get("image_profile"))


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
    ratios = profile.get("ratios") or []
    if ratios and aspect != "auto" and aspect not in ratios:
        raise ImageProfileError("当前模型不支持画幅 " + aspect + "；请选择 auto 或 " + ", ".join(ratios))
    resolutions = profile.get("resolutions") or []
    if resolutions and resolution.upper() not in resolutions:
        raise ImageProfileError("当前模型不支持分辨率 " + resolution.upper())
    return {"aspect_ratio": aspect, "image_size": resolution.upper()}
