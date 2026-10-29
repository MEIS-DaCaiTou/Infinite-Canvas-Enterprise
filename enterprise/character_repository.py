"""Single-Gateway storage for account-owned character metadata, never media/tasks."""
from copy import deepcopy
from pathlib import Path
import re
from threading import RLock

from enterprise.local_json import read_json, atomic_write_json
from enterprise.paths import _assert_no_reparse


class CharacterError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


class CharacterRepository:
    """Versioned local adapter; one shared instance owns compare-and-write."""
    def __init__(self, data_root, catalog_path=None):
        self.root = Path(data_root) / 'characters'
        self.catalog_path = Path(catalog_path) if catalog_path else None
        self.lock = RLock()

    def catalog(self):
        if not self.catalog_path or not self.catalog_path.exists():
            return []
        value = read_json(self.catalog_path)
        if not isinstance(value, dict) or value.get('schema_version') != 1 or not isinstance(value.get('characters'), list):
            raise CharacterError(503, '官方角色库暂不可读')
        return value['characters']

    def path(self, user_id):
        if not isinstance(user_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', user_id):
            raise CharacterError(401, '用户身份无效')
        path = self.root / (user_id + '.json')
        _assert_no_reparse(self.root, 'CHARACTER_ROOT')
        _assert_no_reparse(path, 'CHARACTER_FILE')
        return path

    def _load(self, user_id):
        path = self.path(user_id)
        if not path.exists():
            return {'schema_version': 1, 'characters': []}
        value = read_json(path)
        if not isinstance(value, dict) or value.get('schema_version') != 1 or not isinstance(value.get('characters'), list):
            raise CharacterError(503, '角色库格式不可读，请保留数据并联系管理员')
        rows = value['characters']
        if len(rows) > 500 or any(not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not isinstance(row.get('revision'), int) or row['revision'] < 1
                or not isinstance(row.get('images'), list) for row in rows):
            raise CharacterError(503, '角色库记录不可读，请保留数据并联系管理员')
        if len({row['id'] for row in rows}) != len(rows):
            raise CharacterError(503, '角色库记录重复，请保留数据并联系管理员')
        return value

    def list(self, user_id):
        with self.lock:
            return deepcopy(self._load(user_id)['characters'])

    def mutate(self, user_id, operation):
        with self.lock:
            value = self._load(user_id)
            result = operation(value['characters'])
            path = self.path(user_id)
            atomic_write_json(path, value, create_parent=True)
            return deepcopy(result)
