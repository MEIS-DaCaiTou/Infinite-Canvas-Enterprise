"""Maintained per-model video contracts; no network, credentials or storage.

Supplier sources: api-472416532, api-495802284, api-505897644,
api-498242621/631 and api-498243130 at https://gpt-best.apifox.cn/.
Accepted legacy receipts keep their original query route. Unknown new workshop
models remain visible but cannot submit until their exact contract is adapted.
"""
from urllib.parse import urlsplit

from fastapi import HTTPException

from enterprise.providers.zhenzhen import is_zhenzhen, video_submit_endpoints
from enterprise.providers.zhenzhen_video_profiles import PROFILES, V1, XAI, V2, SEEDANCE, VIDU, QUERY_MODES, selected_profile


def video_profile(provider, model, channel=''):
    return selected_profile(str(model or "").strip(), channel) if is_zhenzhen(provider) else {}


def public_video_profiles(provider):
    if not is_zhenzhen(provider):
        return {}
    return {name: video_profile(provider, name) or {'supported': False,
        'message': '当前渠道尚未适配该视频型号，请选择已适配型号；未提交生成'}
        for name in provider.get('video_models', [])}


def request_id(raw):
    for node in (raw, raw.get("data")):
        if isinstance(node, dict):
            for key in ("task_id", "taskId", "id", "request_id"):
                value = node.get(key)
                if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
                    return str(value)
    return None


def submit_endpoints(base, model, channel='', *, multimodal=False):
    profile = selected_profile(model, channel)
    if not profile:
        return video_submit_endpoints(base)
    return [base.rstrip('/') + {XAI: '/xai/v1/videos/generations',
        V1: '/v1/videos', V2: '/v2/videos/generations',
        SEEDANCE: '/seedance/v3/contents/generations/tasks',
        VIDU: '/vidu/v2/reference2video' if multimodal else '/vidu/v2/img2video'}[profile['route']]]


def query_endpoints(base, task_id, *, mode="", submit_url=""):
    if not mode:
        path = urlsplit(submit_url).path.rstrip("/")
        mode = (VIDU if '/vidu/v2/' in path else XAI if path.endswith('/xai/v1/videos/generations') else
            SEEDANCE if path.endswith('/seedance/v3/contents/generations/tasks') else
            V2 if path.endswith('/v2/videos/generations') else V1 if path.endswith('/v1/videos') else '')
    if mode not in QUERY_MODES:
        return []
    path = {XAI: '/xai/v1/videos/', V1: '/v1/videos/', V2: '/v2/videos/generations/',
        SEEDANCE: '/seedance/v3/contents/generations/tasks/', VIDU: '/vidu/v2/tasks/'}[mode]
    return [base.rstrip('/') + path + task_id + ('/creations' if mode == VIDU else '')]


def _reject(message):
    raise HTTPException(400, message)


def validate_request(payload, model, *, image_refs=None, video_refs=None, audio_refs=None):
    profile = selected_profile(model, getattr(payload, 'video_channel', ''))
    if not profile:
        _reject('当前渠道尚未适配该视频型号，请选择已适配型号；未提交生成')
    if profile.get('channel_required') and getattr(payload, 'video_channel', '') not in profile['variants']:
        _reject('请按密钥分组选择 Sora 官方或兼容通道；未提交生成')
    if payload.duration not in profile['durations']:
        _reject(f"{model} 当前接入支持 {', '.join(map(str, profile['durations']))} 秒；未提交生成")
    ratio = payload.aspect_ratio or '16:9'
    if ratio not in profile['ratios']:
        _reject(f"{model} 不支持比例 {ratio}；请选择 {', '.join(profile['ratios'])}")
    resolution = str(payload.resolution or '')
    if resolution and resolution.lower() not in [value.lower() for value in profile['resolutions']]:
        _reject(f'{model} 不支持分辨率 {resolution}；未提交生成')
    images = image_refs if image_refs is not None else getattr(payload, 'images', [])
    videos = video_refs if video_refs is not None else getattr(payload, 'videos', [])
    audios = audio_refs if audio_refs is not None else getattr(payload, 'audios', [])
    for values, kind, limit in [(images, '图片', profile['max_images']),
            (videos, '视频', profile['max_videos']), (audios, '音频', profile['max_audios'])]:
        if len(values) > limit:
            _reject(f'{model} 当前最多支持 {limit} 个{kind}输入；未提交生成')
    if len(images) < profile.get('min_images', 0):
        _reject(f"{model} 需要 {profile['min_images']} 张参考图；未提交生成")
    if profile.get('max_media') and len(images) + len(videos) + len(audios) > profile['max_media']:
        _reject(f"参考素材总数不能超过 {profile['max_media']}；未提交生成")
    for field in ['enhance_prompt', 'enable_upsample', 'camerafixed', 'return_last_frame',
                  'watermark', 'generate_audio', 'multimodal', 'trusted_asset']:
        if getattr(payload, field, False) and field not in profile['toggles']:
            _reject(f'{model} 不支持选项 {field}，请取消；未提交生成')
    if getattr(payload, 'seed', None) is not None and 'seed' not in profile['toggles']:
        _reject(f'{model} 不支持 seed；未提交生成')
    roles = [ref.get('role', '') if isinstance(ref, dict) else getattr(ref, 'role', '') for ref in images]
    if any(roles) and 'frame_roles' not in profile['toggles']:
        _reject('当前模型不支持首尾帧角色，请取消首尾帧选项；未提交生成')
    if profile['family'] == 'seedance':
        if any(role not in {'', 'first_frame', 'last_frame', 'reference_image'} for role in roles):
            _reject('参考图角色不受当前视频模型支持；未提交生成')
        if roles.count('first_frame') > 1 or roles.count('last_frame') > 1:
            _reject('首帧与尾帧各只能选择一张；未提交生成')
        if 'last_frame' in roles and 'first_frame' not in roles:
            _reject('尾帧需要同时提供首帧；未提交生成')
        if getattr(payload, 'multimodal', False) and any(role in {'first_frame', 'last_frame'} for role in roles):
            _reject('全部参考与首尾帧不能同时使用；未提交生成')
        if len(images) > 1 and not getattr(payload, 'multimodal', False) and not any(roles):
            _reject('多张参考图请选择首尾帧或全部参考；未提交生成')
    if profile['family'] == 'vidu' and len(images) > 1 and not getattr(payload, 'multimodal', False):
        _reject('Vidu 多图输入请选择全部参考；未提交生成')
    if profile['family'] == 'xai' and (len(images) > 1 or getattr(payload, 'multimodal', False)) and payload.duration > 10:
        _reject('参考图模式最多 10 秒；未提交生成')
    if profile['family'] in {'grok', 'xai'} and len(images) > 1 and resolution.lower() == '1080p':
        _reject('多参考图模式最高支持 720p；未提交生成')
    return profile


def video_body(payload, model, images, videos, audios):
    profile = validate_request(payload, model, image_refs=getattr(payload, 'images', images),
        video_refs=videos, audio_refs=audios)
    family = profile["family"]
    duration = payload.duration
    ratio = payload.aspect_ratio or "16:9"
    resolution = next((value for value in profile["resolutions"] if value.lower() == str(payload.resolution).lower()), "")
    for values, kind in ((images, "图片"), (videos, "视频"), (audios, "音频")):
        if any(not isinstance(value, str) or not value.startswith(("https://", "http://", "data:")) for value in values):
            _reject(f"{model} 的{kind}需要可供上游读取的网址或数据；请先使用现有云端上传/输入网址功能")
    if family == 'seedance':
        content = [{'type': 'text', 'text': payload.prompt}]
        refs = getattr(payload, 'images', [])
        for index, url in enumerate(images):
            ref = refs[index]
            role = ref.get('role', '') if isinstance(ref, dict) else getattr(ref, 'role', '')
            if payload.multimodal:
                role = 'reference_image'
            content.append({'type': 'image_url', 'image_url': {'url': url}, **({'role': role} if role else {})})
        for values, kind in [(videos, 'video'), (audios, 'audio')]:
            content += [{'type': kind + '_url', kind + '_url': {'url': url}, 'role': 'reference_' + kind} for url in values]
        body = dict(model=model, content=content, duration=duration, ratio=ratio,
            resolution=resolution or profile['resolutions'][0], generate_audio=payload.generate_audio,
            watermark=payload.watermark, return_last_frame=payload.return_last_frame)
        if payload.camerafixed:
            body['camera_fixed'] = True
        if payload.seed is not None:
            body['seed'] = payload.seed
        return body
    if family in {'grok-new', 'sora-official'}:
        width, height = (720, 1280) if ratio == '9:16' else (1280, 720)
        body = dict(model=model, prompt=payload.prompt, size=f'{width}x{height}')
        if family == 'sora-official':
            body['seconds'] = str(duration)
        return body
    if family == 'veo':
        body = dict(model=model, prompt=payload.prompt, aspect_ratio=ratio)
        if images:
            body['images'] = images
        if payload.enhance_prompt:
            body['enhance_prompt'] = True
        if payload.enable_upsample:
            body['enable_upsample'] = True
        return body
    if family == 'sora':
        body = dict(model=model, prompt=payload.prompt, duration=str(duration), aspect_ratio=ratio,
            watermark=payload.watermark, private=True)
        if images:
            body['images'] = images
        if resolution == '1080p':
            body['hd'] = True
        return body
    if family == 'vidu':
        return dict(model=model, prompt=payload.prompt, images=images, duration=duration,
            resolution=resolution or '720p', seed=payload.seed if payload.seed is not None else 0,
            movement_amplitude='auto', off_peak=False)
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
