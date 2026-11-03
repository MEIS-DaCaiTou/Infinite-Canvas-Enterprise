"""Resolve only public bundled character images for outbound image references."""
from pathlib import Path, PurePosixPath


def public_character_image_path(value, static_root):
    if not isinstance(value, str) or not value.startswith('/static/characters/'):
        return None
    path = PurePosixPath(value)
    if (path.as_posix() != value or '..' in path.parts
            or any(char in value for char in ('\\', '%', '?', '#'))
            or any(ord(char) < 32 for char in value)
            or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}):
        return None
    root = (Path(static_root) / 'characters').resolve()
    target = (root / value.removeprefix('/static/characters/')).resolve()
    return str(target) if target.is_relative_to(root) and target.is_file() else None
