"""Read and validate video-input media before any generation request.

Scope resolution is injected by the existing application. Remote reads reuse
the existing public-media downloader, without provider keys or app cookies.
50 MiB is the application's existing upload bound, not a supplier-wide limit.
"""
import asyncio
import base64
from dataclasses import dataclass
from io import BytesIO
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from enterprise.media_download import open_media


def invalid(message):
    raise HTTPException(400, message + '；未提交视频生成')


@dataclass
class VideoReference:
    kind: str
    source: str
    content: bytes
    name: str
    mime: str
    role: str = ''
    width: int = 0
    height: int = 0
    duration: float = 0


def probe_media(path):
    executable = shutil.which('ffprobe')
    if not executable:
        invalid('当前设备缺少 ffprobe，无法核实参考视频／音频，请先补齐媒体工具')
    try:
        result = subprocess.run([executable, '-v', 'error', '-show_streams', '-show_format',
            '-of', 'json', str(path)], capture_output=True, timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            invalid('参考视频／音频无法解码，请重新导出素材')
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise HTTPException(400, '无法读取参考视频／音频信息；未提交视频生成') from exc


class VideoReferencePreparation:
    def __init__(self, resolve_file, *, probe=probe_media, download=open_media,
                 max_bytes=50 * 1024 * 1024):
        self.resolve_file, self.probe, self.download = resolve_file, probe, download
        self.max_bytes = max_bytes

    def _read(self, reference, kind):
        source = str(reference.get('url') or '').strip()
        if not source:
            invalid('输入素材地址为空')
        path = self.resolve_file(reference, kind)
        name = reference.get('name') or Path(urlsplit(source).path).name or 'reference'
        if path:
            file = Path(path)
            if not file.is_file():
                invalid('输入素材文件不存在，请重新选择')
            if file.stat().st_size > self.max_bytes:
                invalid('输入素材超过当前应用的 50MB 上传范围')
            return source, name, file.read_bytes(), str(file)
        if source.startswith(('/assets/', '/output/')):
            invalid('输入素材文件不存在或当前账号无权读取')
        if source.startswith('data:'):
            try:
                header, encoded = source.split(';base64,', 1)
                if len(encoded) > (self.max_bytes + 2) // 3 * 4:
                    invalid('输入素材超过当前应用的 50MB 上传范围')
                return source, name, base64.b64decode(encoded, validate=True), None
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, '输入素材 Base64 无法解码；未提交视频生成') from exc
        if urlsplit(source).scheme not in {'http', 'https'}:
            invalid('当前视频通道需要可读取的图片／视频素材，请先导入素材库')
        try:
            with self.download(source, timeout=(10, 30)) as response:
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_content(256 * 1024):
                    data.extend(chunk)
                    if len(data) > self.max_bytes:
                        invalid('输入素材超过当前应用的 50MB 上传范围')
                return source, name, bytes(data), None
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, '输入素材网址无法读取，请先导入有效素材；未提交视频生成') from exc

    def _one(self, reference, kind):
        source, name, content, path = self._read(reference, kind)
        if not content:
            invalid('输入素材为空文件')
        if kind == 'image':
            try:
                with Image.open(BytesIO(content)) as image:
                    image.load()
                    if image.format not in {'PNG', 'JPEG', 'WEBP'}:
                        invalid('参考图请使用 PNG、JPEG 或 WebP')
                    mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}[image.format]
                    return VideoReference(kind, source, content, name, mime,
                        reference.get('role') or '', *image.size)
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
                raise HTTPException(400, '参考图无法解码，请重新导出图片；未提交视频生成') from exc
        temp = None
        try:
            if path is None:
                with tempfile.NamedTemporaryFile(suffix=Path(name).suffix, delete=False) as handle:
                    handle.write(content)
                    path = temp = handle.name
            info = self.probe(path)
            streams = [stream for stream in info.get('streams', [])
                       if stream.get('codec_type') == kind and not stream.get('disposition', {}).get('attached_pic')]
            if not streams:
                invalid('输入素材类型与视频／音频插槽不符')
            stream = streams[0]
            try:
                duration = float(info.get('format', {}).get('duration') or stream.get('duration') or 0)
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, '无法核实参考素材时长；未提交视频生成') from exc
            if not math.isfinite(duration) or duration <= 0:
                invalid('无法核实参考素材时长')
            formats = info.get('format', {}).get('format_name', '')
            if kind == 'video':
                if not any(value in formats.split(',') for value in ['mov', 'mp4', 'webm', 'matroska']):
                    invalid('当前接入的参考视频请使用 MP4、MOV 或 WebM')
                mime = 'video/webm' if 'webm' in formats or 'matroska' in formats else 'video/mp4'
            else:
                mime = next((mime for value, mime in [('wav', 'audio/wav'), ('mp3', 'audio/mpeg'),
                    ('flac', 'audio/flac'), ('aac', 'audio/aac'), ('ogg', 'audio/ogg'),
                    ('mov', 'audio/mp4'), ('mp4', 'audio/mp4')] if value in formats.split(',')), '')
                if not mime:
                    invalid('当前参考音频格式无法确认，请使用 MP3、WAV、M4A、AAC、FLAC 或 OGG')
            return VideoReference(kind, source, content, name, mime,
                reference.get('role') or '', int(stream.get('width') or 0),
                int(stream.get('height') or 0), duration)
        finally:
            if temp:
                Path(temp).unlink(missing_ok=True)

    async def prepare(self, images, videos, audios, profile):
        entries = [(dict(ref), 'image') for ref in images]
        entries += [({'url': url}, 'video') for url in videos]
        entries += [({'url': url}, 'audio') for url in audios]
        # Complete all decoding/duration checks before the caller uploads or
        # submits. Keep order and duplicate reference slots intentionally.
        prepared = []
        for reference, kind in entries:
            prepared.append(await asyncio.to_thread(self._one, reference, kind))
        timed = [item for item in prepared if item.kind != 'image']
        for item in timed:
            if (profile.get('media_duration_min') and item.duration < profile['media_duration_min'] or
                    profile.get('media_duration_max') and item.duration > profile['media_duration_max']):
                invalid(f'参考素材时长 {item.duration:g} 秒不在当前模型支持范围内')
        if profile.get('media_duration_total') and sum(item.duration for item in timed) > profile['media_duration_total']:
            invalid(f"参考视频和音频总时长不能超过 {profile['media_duration_total']:g} 秒")
        return prepared
