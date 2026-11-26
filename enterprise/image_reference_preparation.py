"""Prepare submission copies once per image batch; never replace source assets.

1536px, 8MiB per prepared file and 32MiB encoded input are application policy,
not claimed supplier hard limits. Existing authorization and URL import remain
with the caller. Transparent images keep Alpha, including palette/LA sources.
"""
import asyncio
import base64
from contextlib import ExitStack, asynccontextmanager
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError


@asynccontextmanager
async def edit_reference_files(images, masks, *, preparation, resolve_image, resolve_mask, content_type, max_references):
    """File parts from prepared copies, or scoped handles for legacy callers.

    Authorized path resolution stays with existing caller services. Handles are
    released as soon as submission finishes, including interrupted requests.
    """
    if preparation is not None:
        yield [*(await preparation.files(images)), *(await preparation.files(masks[:1], field='mask'))]
        return
    with ExitStack() as stack:
        files = []
        for field, references, resolve in [('image', images[:max_references], resolve_image), ('mask', masks[:1], resolve_mask)]:
            for reference in references:
                path = resolve(reference)
                if path:
                    handle = stack.enter_context(open(path, 'rb'))
                    files.append((field, (Path(path).name, handle, content_type(path))))
        yield files


class ImageReferencePreparation:
    def __init__(self, references, resolve_file, *, observe=None, max_edge=1536,
                 max_file_bytes=8 * 1024 * 1024, max_encoded_bytes=32 * 1024 * 1024):
        self.references, self.resolve_file, self.observe = references, resolve_file, observe
        self.max_edge, self.max_file_bytes, self.max_encoded_bytes = max_edge, max_file_bytes, max_encoded_bytes
        self.lock = asyncio.Lock()
        self.prepared = None

    @staticmethod
    def key(reference):
        return (reference.get('url', ''), reference.get('role', ''))

    def _one(self, reference):
        url = reference.get('url', '')
        path = self.resolve_file(reference)
        if path:
            source = Path(path).read_bytes()
        elif url.startswith('data:image/') and ';base64,' in url:
            try:
                source = base64.b64decode(url.split(';base64,', 1)[1], validate=True)
            except ValueError as exc:
                raise HTTPException(400, '参考图无法解码，请重新选择；未提交生成') from exc
        else:
            # Public URLs retain the supplier's documented URL mode. Local-only
            # addresses must go through the existing material import operation.
            from urllib.parse import urlsplit
            import ipaddress
            parsed = urlsplit(url)
            try:
                address = ipaddress.ip_address(parsed.hostname or '')
            except ValueError:
                address = None
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.hostname == 'localhost' or address is not None and not address.is_global:
                raise HTTPException(400, '参考图需先导入素材库，供应商无法读取此本地地址；未提交生成')
            return {'data_url': url, 'content': None, 'mime': '', 'name': reference.get('name') or 'reference',
                    'meta': {'transport': 'url', 'source_bytes': 0, 'prepared_bytes': 0}}
        try:
            with Image.open(BytesIO(source)) as opened:
                image = ImageOps.exif_transpose(opened)
                image.load()
                source_size = image.size
                has_alpha = 'A' in image.getbands() or 'transparency' in image.info
                keep_original = (opened.format in {'PNG', 'JPEG', 'WEBP'} and opened.getexif().get(274, 1) == 1
                                 and max(source_size) <= self.max_edge and len(source) <= self.max_file_bytes)
                if keep_original:
                    content = source
                    mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}[opened.format]
                else:
                    image = image.convert('RGBA' if has_alpha else 'RGB')
                    image.thumbnail((self.max_edge, self.max_edge), Image.Resampling.LANCZOS)
                    while True:
                        buffer = BytesIO()
                        image.save(buffer, format='PNG' if has_alpha else 'JPEG', **({} if has_alpha else {'quality': 88, 'optimize': True}))
                        content = buffer.getvalue()
                        if len(content) <= self.max_file_bytes:
                            break
                        edge = int(max(image.size) * .85)
                        if edge < 32:
                            raise HTTPException(413, '参考图提交副本仍超过项目体积限制，请减少图片尺寸；未提交生成')
                        image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                    mime = 'image/png' if has_alpha else 'image/jpeg'
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise HTTPException(400, '参考图无法读取，请重新导入图片；未提交生成') from exc
        return {'content': content, 'mime': mime, 'name': 'reference.' + mime.split('/')[1],
                'data_url': f'data:{mime};base64,' + base64.b64encode(content).decode('ascii'),
                'meta': {'transport': 'file', 'source_bytes': len(source), 'prepared_bytes': len(content),
                         'source_width': source_size[0], 'source_height': source_size[1],
                         'width': image.width, 'height': image.height, 'alpha': has_alpha, 'mime': mime}}

    def _prepare(self):
        cache, items, encoded_size = {}, [], 0
        for index, reference in enumerate(self.references):
            key = self.key(reference)
            if key not in cache:
                cache[key] = self._one(reference)
            item = cache[key]
            encoded_size += len(item['data_url'].encode('utf-8'))
            items.append({'index': index, **item['meta']})
        if encoded_size > self.max_encoded_bytes:
            raise HTTPException(413, '参考图提交副本合计超过项目 32MiB 限制，请减少素材体积；未截断参考图或提交生成')
        summary = {'count': len(items), 'source_bytes': sum(item['source_bytes'] for item in items),
                   'prepared_bytes': sum(item['prepared_bytes'] for item in items), 'encoded_bytes': encoded_size,
                   'policy': {'max_edge': self.max_edge, 'max_file_bytes': self.max_file_bytes, 'max_encoded_bytes': self.max_encoded_bytes},
                   'items': items}
        if self.observe:
            self.observe(summary)
        return cache

    async def get(self, reference):
        async with self.lock:
            if self.prepared is None:
                self.prepared = await asyncio.to_thread(self._prepare)
        return self.prepared[self.key(reference)]

    async def urls(self, references):
        return [(await self.get(reference))['data_url'] for reference in references]

    async def files(self, references, *, field='image'):
        files = []
        for reference in references:
            item = await self.get(reference)
            if item['content'] is None:
                raise HTTPException(400, '此编辑接口需要图片文件，请先将远程图片导入素材库；未提交生成')
            files.append((field, (item['name'], item['content'], item['mime'])))
        return files

    def validate_request(self, request):
        length = request.headers.get('content-length')
        if request.method == 'POST' and length and int(length) > self.max_encoded_bytes:
            raise HTTPException(413, '图片请求体超过项目体积限制，请减少素材体积；未提交生成')
