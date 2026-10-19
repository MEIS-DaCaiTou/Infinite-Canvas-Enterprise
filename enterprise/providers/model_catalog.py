"""Model-list classification, independent of credentials and submission."""


def known_model_kind(model):
    name = str(model or "").strip().lower()
    if name.startswith(("kling-image", "kling-multi-image2image", "kling-kolors")):
        return "image"
    if name == "minimax-h3":
        return "video"
    return ""


def classify_model(model):
    known = known_model_kind(model)
    if known:
        return known
    name = str(model or "").lower()
    if any(key in name for key in ("veo", "sora", "wan2", "wanx", "doubao-seedance", "doubao-1", "kling", "hailuo", "video", "t2v-", "i2v-", "s2v")):
        return "video"
    if any(key in name for key in ("banana", "image", "dalle", "dall-e", "imagen", "flux", "stable", "sdxl", "midjourney", "ideogram", "fal-ai", "z-image", "klein", "seedream", "text-to-image", "image-to-image")):
        return "image"
    return "chat"


def correct_known_groups(groups):
    """Repair only known misclassifications; preserve manual lists and IDs."""
    result = {kind: [] for kind in ("chat", "image", "video")}
    for kind in result:
        for model in groups.get(kind) or []:
            target = known_model_kind(model) or kind
            if model not in result[target]:
                result[target].append(model)
    return result
