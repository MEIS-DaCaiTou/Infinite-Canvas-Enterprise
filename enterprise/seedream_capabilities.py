"""Seedream 5.5 model rules, independent of suppliers, HTTP and task storage."""
from copy import deepcopy
import re

NATIVE_MODEL = "doubao-seedream-5-5-261028"
FAMILY = "seedream-5.5"
RESOLUTIONS = ["1K", "1.5K", "2K"]


def image_profile(*, layers=False):
    profile = {
        "model_family": FAMILY, "mode": "pixel", "supports_quality": False,
        "supports_mask": False, "supports_background": not layers,
        "supports_auto_size": layers, "supports_custom_size": not layers,
        "supports_layer_options": True, "resolutions": list(RESOLUTIONS),
        "supports_layer_limit": True, "supports_layer_text_recognition": True,
        "supports_empty_layer_prompt": True,
        "max_references": 1 if layers else 10,
    }
    if layers:
        profile.update(min_references=1, layer_output=True)
    else:
        profile["size_rules"] = {"min_pixels": 921600, "max_pixels": 4624220, "max_aspect": 16}
        profile["layer_profile"] = image_profile(layers=True)
    return deepcopy(profile)


def validate_request(size, references, *, layers=False):
    """Do not snap user dimensions, trim references or invent a layer count."""
    count = len(references)
    if layers and count != 1:
        raise ValueError("图层拆分需要一张原图")
    if not layers and count > 10:
        raise ValueError("Seedream 5.5 最多支持 10 张参考图")
    raw = str(size or "").strip()
    if raw.upper() in RESOLUTIONS or (layers and raw.lower() == "auto"):
        return raw.upper() if raw.lower() != "auto" else "auto"
    if layers:
        raise ValueError("图层拆分尺寸请选择 auto、1K、1.5K 或 2K")
    match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", raw)
    if not match:
        raise ValueError("Seedream 5.5 请选择 1K、1.5K、2K 或填写宽×高像素")
    width, height = map(int, match.groups())
    if not 921600 <= width * height <= 4624220:
        raise ValueError("Seedream 5.5 图片总像素须为 921600–4624220")
    if max(width, height) > min(width, height) * 16:
        raise ValueError("Seedream 5.5 图片长短边比例不能超过 16:1")
    return raw
