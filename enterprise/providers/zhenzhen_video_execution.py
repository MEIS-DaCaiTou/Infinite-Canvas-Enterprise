"""Workshop video execution; application injects scope, receipt and archival.

Validate every reference before uploading any file. A generation has exactly
one selected endpoint; ambiguous submission never changes model or credential.
"""
import mimetypes
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from enterprise.providers import zhenzhen_video as contract
from enterprise.providers.video_generation import generate_json_video
from enterprise.providers.video_outputs import video_output_urls
from enterprise.video_reference_preparation import VideoReferencePreparation


async def upload_reference(client, base, headers, media, index):
    if urlsplit(media.source).scheme in {'http', 'https'}:
        return media.source
    suffix = mimetypes.guess_extension(media.mime) or '.bin'
    authorization = {key: value for key, value in headers.items() if key.lower() != 'content-type'}
    try:
        response = await client.post(base.rstrip('/') + '/v1/files', headers=authorization,
            files={'file': (f'reference_{index}{suffix}', media.content, media.mime)})
    except httpx.HTTPError as exc:
        raise HTTPException(502, '贞贞素材上传连接失败；未提交视频生成') from exc
    if response.status_code >= 400:
        raise HTTPException(400, f'贞贞素材上传失败（HTTP {response.status_code}）；未提交视频生成')
    try:
        raw = response.json()
        data = raw.get('data') if isinstance(raw.get('data'), dict) else {}
        url = raw.get('url') or raw.get('file_url') or data.get('url') or data.get('file_url')
        if not isinstance(url, str) or urlsplit(url).scheme not in {'http', 'https'}:
            raise ValueError()
        return url
    except (ValueError, AttributeError) as exc:
        raise HTTPException(502, '贞贞素材上传没有返回可用地址；未提交视频生成') from exc


async def execute(client, provider, payload, *, base, headers, resolve_file,
                  accepted, poll, archive, preparation=None):
    profile = contract.validate_request(payload, payload.model)
    images = [ref if isinstance(ref, dict) else ref.model_dump() for ref in payload.images]
    prepared = await (preparation or VideoReferencePreparation(resolve_file)).prepare(
        images, payload.videos, payload.audios, profile)
    channel = getattr(payload, 'video_channel', '')
    urls = contract.submit_endpoints(base, payload.model, channel, multimodal=payload.multimodal)
    grouped = {kind: [] for kind in ['image', 'video', 'audio']}
    files = None
    if profile.get('encoding') == 'multipart':
        files = []
        for media in prepared:
            if profile['family'] == 'sora-official':
                expected = (720, 1280) if payload.aspect_ratio == '9:16' else (1280, 720)
                if (media.width, media.height) != expected:
                    raise HTTPException(400, f'官方 Sora 首帧需为 {expected[0]}×{expected[1]} 像素，请先裁剪；未提交生成')
            files.append(('input_reference', ('input_reference' + (mimetypes.guess_extension(media.mime) or '.png'),
                media.content, media.mime)))
            grouped[media.kind].append(media.source)
    else:
        for index, media in enumerate(prepared):
            grouped[media.kind].append(await upload_reference(client, base, headers, media, index))
    body = contract.video_body(payload, payload.model, grouped['image'], grouped['video'], grouped['audio'])
    key, result, outputs = await generate_json_video(client, urls, headers, body,
        extract_task_id=contract.request_id, output_urls=video_output_urls,
        accepted=lambda task_id, url: accepted(task_id, url, profile['route']),
        poll=poll, multipart_files=files)
    local = [await archive(url) for url in outputs]
    return {'videos': local, 'task_id': key, 'raw': result}
