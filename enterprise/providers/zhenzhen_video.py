"""Maintained per-model video contracts; no network, credentials or storage.

Supplier sources: api-472416532, api-495802284, api-505897644,
api-498242621/631 and api-498243130 at https://gpt-best.apifox.cn/.
The old unified contract remains unchanged for all other model IDs.
"""
from copy import deepcopy
from urllib.parse import urlsplit

from fastapi import HTTPException

from enterprise.providers.zhenzhen import is_zhenzhen, video_submit_endpoints


V1 = "zhenzhen-videos-v1"
XAI = "zhenzhen-xai-v1"
QUERY_MODES = {V1, XAI}
RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9", "5:2"]
PROFILES = {
    "grok-imagine-video-1.5": dict(route=V1, family="grok", duration_min=1, duration_max=15,
        resolutions=["480p", "720p", "1080p"], ratios=RATIOS, max_images=14, max_videos=0, max_audios=0, toggles=[]),
    "grok-imagine-video": dict(route=XAI, family="xai", duration_min=1, duration_max=15,
        resolutions=["480p", "720p"], ratios=RATIOS, max_images=7, max_videos=0, max_audios=0, toggles=["multimodal"]),
    "MiniMax-H3": dict(route=V1, family="minimax", duration_min=5, duration_max=15,
        resolutions=["768P", "2K"], ratios=["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
        max_images=9, max_videos=3, max_audios=3, toggles=["multimodal"]),
    **{model: dict(route=V1, family="wan", duration_min=1, duration_max=30,
        resolutions=["480P", "720P", "1080P"], ratios=["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16"],
        max_images=10, max_videos=5, max_audios=5, toggles=["enhance_prompt", "generate_audio", "watermark", "multimodal", "seed"])
       for model in ("wan3.0-video", "wan3.0-video-prime")},
}


def video_profile(provider, model):
    return deepcopy(PROFILES.get(str(model or "").strip(), {})) if is_zhenzhen(provider) else {}


def public_video_profiles(provider):
    return {name: video_profile(provider, name) for name in provider.get("video_models", []) if video_profile(provider, name)}


def request_id(raw):
    for node in (raw, raw.get("data")):
        if isinstance(node, dict):
            for key in ("request_id", "task_id", "taskId", "id"):
                value = node.get(key)
                if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
                    return str(value)
    return None


def submit_endpoints(base, model):
    profile = PROFILES.get(model)
    if not profile:
        return video_submit_endpoints(base)
    return [base.rstrip("/") + ("/xai/v1/videos/generations" if profile["route"] == XAI else "/v1/videos")]


def query_endpoints(base, task_id, *, mode="", submit_url=""):
    if not mode:
        path = urlsplit(submit_url).path.rstrip("/")
        mode = XAI if path.endswith("/xai/v1/videos/generations") else V1 if path.endswith("/v1/videos") else ""
    if mode not in QUERY_MODES:
        return []
    return [base.rstrip("/") + ("/xai/v1/videos/" if mode == XAI else "/v1/videos/") + task_id]


def _reject(message):
    raise HTTPException(400, message)


def video_body(payload, model, images, videos, audios):
    profile = PROFILES[model]
    family = profile["family"]
    duration = payload.duration
    if not profile["duration_min"] <= duration <= profile["duration_max"]:
        _reject(f"{model} 当前接入支持 {profile['duration_min']}–{profile['duration_max']} 秒，请调整时长")
    ratio = payload.aspect_ratio or "16:9"
    if ratio not in profile["ratios"]:
        _reject(f"{model} 不支持比例 {ratio}；请选择 {', '.join(profile['ratios'])}")
    resolution = next((value for value in profile["resolutions"] if value.lower() == str(payload.resolution).lower()), "")
    if payload.resolution and not resolution:
        _reject(f"{model} 不支持分辨率 {payload.resolution}；请选择 {', '.join(profile['resolutions'])}")
    for values, kind, limit in ((images, "图片", profile["max_images"]), (videos, "视频", profile["max_videos"]), (audios, "音频", profile["max_audios"])):
        if len(values) > limit:
            _reject(f"{model} 当前接入最多支持 {limit} 个{kind}输入；请调整输入，未提交生成")
        if any(not isinstance(value, str) or not value.startswith(("https://", "http://", "data:")) for value in values):
            _reject(f"{model} 的{kind}需要可供上游读取的网址或数据；请先使用现有云端上传/输入网址功能")
    for field in ("enhance_prompt", "enable_upsample", "camerafixed", "return_last_frame", "watermark", "generate_audio", "multimodal"):
        if getattr(payload, field, False) and field not in profile["toggles"]:
            _reject(f"{model} 当前协议不支持选项 {field}，请取消该选项；未提交生成")
    if payload.seed is not None and "seed" not in profile["toggles"]:
        _reject(f"{model} 当前协议不支持 seed；未提交生成")
    if family == "xai" and (len(images) > 1 or payload.multimodal) and duration > 10:
        _reject(f"{model} 参考图模式最多 10 秒；未提交生成")
    if family in {"grok", "xai"} and len(images) > 1 and resolution.lower() == "1080p":
        _reject(f"{model} 多参考图模式最高支持 720p；未提交生成")
    body = {"model": model, "prompt": payload.prompt, "aspect_ratio": ratio}
    body["seconds" if family in {"grok", "minimax"} else "duration"] = str(duration) if family in {"grok", "minimax"} else duration
    body["resolution"] = resolution or profile["resolutions"][0]
    if family == "minimax":
        body["resolution"] = resolution or "768P"
        for key, values in (("imageUrls", images), ("videoUrls", videos), ("audioUrls", audios)):
            if values:
                body[key] = values
        if payload.multimodal:
            body["mode"] = "multimodal-to-video"
    elif family == "wan":
        for key, values in (("image_urls", images), ("video_urls", videos), ("audio_urls", audios)):
            if values:
                body[key] = values
        body.update(prompt_extend=payload.enhance_prompt, audio=payload.generate_audio, watermark=payload.watermark)
        if payload.multimodal:
            body["mode"] = "reference-to-video"
        if payload.seed is not None:
            body["seed"] = payload.seed
    elif family == "xai":
        if images:
            if len(images) > 1 or payload.multimodal:
                body["reference_images"] = [{"url": value} for value in images]
            else:
                body["image"] = {"url": images[0]}
    elif images:
        body["images"] = images
    return body
