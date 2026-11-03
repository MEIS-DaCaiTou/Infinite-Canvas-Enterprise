"""Existing upload naming plus a metadata-only listing for read-only pickers.

No image decoding, caption reads, writes or authorization decisions live here.
"""
import os
from pathlib import Path
import re
import stat as file_stat
from urllib.parse import quote, unquote


def kind_ext(filename, content_type):
    image_exts = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
    video_exts = {'.mp4', '.webm', '.mov', '.m4v', '.flv'}
    audio_exts = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac'}
    ext = os.path.splitext(filename or '')[1].lower()
    ct = (content_type or '').lower()
    if ext in video_exts or ct.startswith('video/'):
        if ext not in video_exts:
            ext = '.webm' if 'webm' in ct else '.mov' if 'quicktime' in ct else '.mp4'
        return 'video', ext
    if ext in audio_exts or ct.startswith('audio/'):
        if ext not in audio_exts:
            ext = '.wav' if 'wav' in ct else '.ogg' if 'ogg' in ct else '.m4a' if 'mp4' in ct else '.mp3'
        return 'audio', ext
    if ext in image_exts or ct.startswith('image/'):
        if ext not in image_exts:
            ext = '.jpg' if 'jpeg' in ct else '.webp' if 'webp' in ct else '.gif' if 'gif' in ct else '.png'
        return 'image', ext
    return None, ext


def display_name(filename):
    base = os.path.basename(str(filename or ''))
    match = re.match(r'^up_[0-9a-f]{12}_(.+)$', base)
    return match.group(1) if match else base


def is_picker_query(path, method, params):
    return (path == 'api/local-assets' and method.upper() == 'GET'
            and params is not None and ('page_size' in params or 'cursor' in params))


def _files(root, allowed_urls):
    if allowed_urls is not None:
        # A user's current resource grants are the candidates, not a reason to
        # enumerate every other employee's uploads. Never interpret a grant as
        # a server path outside this existing upload root.
        resolved_root = root.resolve()
        for url in sorted(allowed_urls):
            if not str(url).startswith('/assets/uploads/'):
                continue
            relative = unquote(str(url)[len('/assets/uploads/'):])
            parts = relative.replace('\\', '/').split('/')
            if any(not part or part.startswith('.') or ':' in part for part in parts):
                continue
            path = root.joinpath(*parts)
            if not kind_ext(path.name, '')[0] or not path.resolve().is_relative_to(resolved_root):
                continue
            try:
                info = path.stat()
            except FileNotFoundError:
                continue
            if file_stat.S_ISREG(info.st_mode):
                yield path, info
        return

    # DirEntry carries filesystem metadata on Windows; avoid discarding it in
    # os.walk then doing a fresh Path.stat for every administrator-visible file.
    with os.scandir(root) as scan:
        entries = sorted(scan, key=lambda entry: entry.name)
    directories = []
    for entry in entries:
        if entry.name.startswith('.'):
            continue
        if entry.is_dir(follow_symlinks=False):
            directories.append(Path(entry.path))
        elif kind_ext(entry.name, '')[0]:
            try:
                info = entry.stat()
            except FileNotFoundError:
                continue
            if file_stat.S_ISREG(info.st_mode):
                yield Path(entry.path), info
    for directory in directories:
        yield from _files(directory, None)


def metadata_items(root, allowed_urls=None):
    """Same supported uploads; current grants supplied by the Gateway caller."""
    root = Path(root)
    try:
        root.stat()
    except FileNotFoundError:
        return []
    items = []
    for path, info in _files(root, allowed_urls):
        relative = path.relative_to(root).as_posix()
        url = '/assets/uploads/' + quote(relative, safe='/')
        if allowed_urls is not None and url not in allowed_urls:
            continue
        kind, _ = kind_ext(path.name, '')
        items.append(dict(id=relative, file=relative, name=display_name(relative), url=url,
                          kind=kind, size=info.st_size, created_at=info.st_mtime,
                          folder='' if path.parent == root else path.parent.relative_to(root).as_posix(),
                          _query_position=0))
    return items
