"""Account-owned model display preferences; no provider credentials or business schema."""
import json
import os
from pathlib import Path
import re
import tempfile


def normalize_preferences(value):
    if not isinstance(value, dict) or not isinstance(value.get('favorites', []), list):
        raise ValueError('模型偏好格式无效')
    if len(value.get('favorites', [])) > 2000:
        raise ValueError('个人模型列表过长')
    favorites = []
    seen = set()
    for item in value.get('favorites', []):
        if not isinstance(item, str):
            raise ValueError('模型偏好格式无效')
        try:
            parts = json.loads(item)
        except ValueError as exc:
            raise ValueError('模型偏好格式无效') from exc
        if not isinstance(parts, list) or len(parts) != 3 or parts[0] not in {'image','video','chat'} or not all(isinstance(x,str) and 0 < len(x) <= 256 for x in parts):
            raise ValueError('模型偏好格式无效')
        key = json.dumps(parts, ensure_ascii=False, separators=(',',':'))
        if key not in seen:
            seen.add(key)
            favorites.append(key)
    return {'schema_version':1, 'favorites':favorites, 'view':'favorites' if value.get('view') == 'favorites' else 'all'}


def preference_path(data_root: Path, user_id: str) -> Path:
    if not isinstance(user_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', user_id):
        raise ValueError('用户身份无效')
    return Path(data_root) / 'user-model-preferences' / f'{user_id}.json'


def load_preferences(data_root: Path, user_id: str):
    path = preference_path(data_root, user_id)
    if not path.exists():
        return normalize_preferences({})
    return normalize_preferences(json.loads(path.read_text(encoding='utf-8')))


def save_preferences(data_root: Path, user_id: str, value):
    preferences = normalize_preferences(value)
    path = preference_path(data_root, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix=f'.{user_id}-', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            json.dump(preferences, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return preferences
