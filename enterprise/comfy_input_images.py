"""Optional preparation of ComfyUI upload bytes; never writes the source asset."""
from io import BytesIO
import asyncio

from PIL import Image, ImageOps, UnidentifiedImageError

_image_gate = asyncio.Semaphore(2)


async def prepare_upload(content, filename, content_type, *, max_edge=0, lossless=False):
    if not max_edge and not lossless:
        return content, filename, content_type, None
    # Image decoding/re-encoding is CPU and memory work; do not block request handling
    # or allow many users to decode full-resolution images simultaneously.
    async with _image_gate:
        return await asyncio.to_thread(prepare_image, content, filename, content_type,
                                       max_edge=max_edge, lossless=lossless)


def prepare_image(content, filename, content_type, *, max_edge=0, lossless=False):
    if not max_edge and not lossless:
        return content, filename, content_type, None
    image_ext = filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.gif'))
    if not image_ext and not (content_type or '').startswith('image/'):
        return content, filename, content_type, None
    try:
        with Image.open(BytesIO(content)) as source:
            if getattr(source, 'n_frames', 1) > 1:
                raise ValueError('动态图片暂不做输入优化，请关闭优化或选择静态图片')
            image = ImageOps.exif_transpose(source)
            original_size = image.size
            resized = bool(max_edge and max(image.size) > max_edge)
            if resized:
                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            if image.mode not in {'1', 'L', 'LA', 'P', 'RGB', 'RGBA', 'I', 'I;16'}:
                raise ValueError('该图片色彩模式暂不支持无损处理，请关闭优化或先转换为 RGB 图片')
            buffer = BytesIO()
            image.save(buffer, format='PNG', optimize=True, icc_profile=source.info.get('icc_profile'))
            prepared = buffer.getvalue()
            # A lossless-only pass must not increase transfer size.
            if not resized and len(prepared) >= len(content):
                prepared, new_name, mime = content, filename, content_type
            else:
                new_name, mime = filename.rsplit('.', 1)[0] + '.png', 'image/png'
            info = {'original_width': original_size[0], 'original_height': original_size[1],
                    'width': image.width, 'height': image.height, 'original_bytes': len(content),
                    'bytes': len(prepared), 'resized': resized}
            return prepared, new_name, mime, info
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('输入图片无法解码或尺寸过大，请检查图片，或关闭输入优化') from exc
