"""Exact workshop video contracts. Public controls and submission share this data.

Sources: gpt-best.apifox.cn api-440251336/513301405/515548387,
472416532/495802284/505897644/343590061/358024351; T8-penguin-canvas
c3292f0f routes/proxy.js. A catalog name alone never enables generation.
"""
from copy import deepcopy

V1 = 'zhenzhen-videos-v1'
XAI = 'zhenzhen-xai-v1'
V2 = 'zhenzhen-unified-v2'
SEEDANCE = 'zhenzhen-seedance-v3'
VIDU = 'zhenzhen-vidu-v2'
RATIOS = ['16:9', '9:16', '1:1', '4:3', '3:4', '3:2', '2:3', '21:9', '5:2']


def profile(route, family, durations, resolutions, *, ratios=RATIOS,
            images=0, videos=0, audios=0, toggles=(), min_images=0, **extra):
    times = list(durations)
    return dict(route=route, family=family, supported=True,
        duration_min=min(times), duration_max=max(times), durations=times,
        duration_default=5 if 5 in times else times[0],
        resolutions=list(resolutions), ratios=list(ratios),
        min_images=min_images, max_images=images, max_videos=videos,
        max_audios=audios, toggles=list(toggles), **extra)


PROFILES = {
    'grok-imagine-video-1.5': profile(V1, 'grok', range(1, 16), ['480p', '720p', '1080p'], images=14),
    'grok-imagine-video': profile(XAI, 'xai', range(1, 16), ['480p', '720p'], images=7, toggles=['multimodal']),
    'MiniMax-H3': profile(V1, 'minimax', range(5, 16), ['768P', '2K'],
        ratios=['adaptive', '21:9', '16:9', '4:3', '1:1', '3:4', '9:16'],
        images=9, videos=3, audios=3, toggles=['multimodal']),
    **{model: profile(V1, 'wan', range(1, 31), ['480P', '720P', '1080P'],
        ratios=['adaptive', '16:9', '4:3', '1:1', '3:4', '9:16'],
        images=10, videos=5, audios=5,
        toggles=['enhance_prompt', 'generate_audio', 'watermark', 'multimodal', 'seed'])
       for model in ['wan3.0-video', 'wan3.0-video-prime']},
    **{f'grok-1.5-video-{seconds}s': profile(V1, 'grok-new', [seconds], ['720p'],
        ratios=['16:9', '9:16'], images=1, min_images=1, encoding='multipart')
       for seconds in [6, 10, 15]},
}

SEEDANCE_TOGGLES = ['generate_audio', 'watermark', 'camerafixed', 'return_last_frame',
                    'multimodal', 'frame_roles', 'seed']
for model in ['doubao-seedance-2-0-260128', 'doubao-seedance-2-0-fast-260128',
              'doubao-seedance-2.0-mini', 'doubao-seedance-2.5']:
    mini, latest = model.endswith('mini'), model.endswith('2.5')
    PROFILES[model] = profile(SEEDANCE, 'seedance', [4, 10, 15] if mini else range(4, 31 if latest else 16),
        ['480p', '720p'] if mini else ['480p', '720p', '1080p'],
        ratios=['adaptive', '21:9', '16:9', '4:3', '1:1', '3:4', '9:16'],
        images=30 if latest else 9, videos=10 if latest else 3, audios=10 if latest else 3,
        toggles=SEEDANCE_TOGGLES, max_media=50 if latest else 12,
        media_duration_min=2 if latest else 1.8,
        media_duration_max=30 if latest else 15.2,
        media_duration_total=30 if latest else 15.2,
        resolution_notes={'1080p': '1080p 由 720p 放大，渠道另计费用'} if latest else {})

# Workshop Veo supplies its own duration/output resolution. Do not send the
# unrelated generic knobs or silently upgrade to a more expensive model ID.
for model in ['veo3', 'veo3-fast', 'veo3-pro', 'veo3-pro-frames', 'veo3-fast-frames',
              'veo3.1', 'veo3.1-fast', 'veo3.1-pro', 'veo3.1-components', 'veo3.1-fast-components']:
    frames, components = model.endswith('frames') or model in {'veo3.1', 'veo3.1-pro', 'veo3.1-fast'}, 'components' in model
    PROFILES[model] = profile(V2, 'veo', [8], [], ratios=['16:9', '9:16'],
        images=3 if components else 2 if frames else 1,
        toggles=['enhance_prompt', 'enable_upsample'] + (['frame_roles'] if frames else []),
        duration_note='时长由模型确定（8 秒档）', resolution_note='分辨率由模型确定')

# Identical Sora IDs use incompatible contracts in different supplier groups.
# An explicit node choice is required; never infer a paid route from the ID.
for model in ['sora-2', 'sora-2-pro']:
    pro = model.endswith('-pro')
    official = profile(V1, 'sora-official', [4, 8, 12], ['720p'],
        ratios=['16:9', '9:16'], images=1, encoding='multipart')
    compatible = profile(V2, 'sora', [15, 25] if pro else [10, 15], ['720p', '1080p'] if pro else ['720p'],
        ratios=['16:9', '9:16'], images=1, toggles=['watermark'])
    PROFILES[model] = {**compatible, 'variants': {'official': official, 'compatible': compatible},
        'channel_required': True,
        'channel_labels': {'official': '官方分组', 'compatible': '兼容分组'},
        'channel_note': '按密钥所属分组选择通道；两种通道的时长与计费方式不同'}

# api-374481658 documents Q2; its current example and the workshop catalog
# explicitly include Q4 preview. Keep Q4 to that documented 5s/720p combination.
for model in ['viduq2-pro', 'viduq2-turbo', 'viduq4-preview']:
    reference = model == 'viduq2-pro'
    PROFILES[model] = profile(VIDU, 'vidu', [5] if model == 'viduq4-preview' else range(1, 9),
        ['540p', '720p', '1080p'] if model == 'viduq2-pro' else ['720p'],
        ratios=['adaptive'], min_images=1, images=7 if reference else 1,
        toggles=['seed'] + (['multimodal'] if reference else []))


def selected_profile(model, channel=''):
    result = deepcopy(PROFILES.get(model, {}))
    if result.get('variants') and channel in result['variants']:
        return {**result, **result['variants'][channel], 'channel': channel}
    return result


QUERY_MODES = {V1, XAI, V2, SEEDANCE, VIDU}
