"""Character profiles reuse authorized media references; no generation or credentials."""
from pathlib import PurePosixPath
import time
import uuid
import re

from enterprise.character_repository import CharacterError

GENDERS = ('unspecified', 'female', 'male', 'neutral', 'other')
AGES = ('unspecified', 'child', 'teen', 'young', 'adult', 'middle', 'senior')
REGIONS = ('unspecified', 'east_asia', 'south_asia', 'europe', 'africa', 'americas', 'middle_east', 'other')
FIELDS = {'name', 'description', 'gender', 'age_group', 'region', 'images', 'cover_url', 'expected_revision', 'archived', 'create_request_id'}
PREFIXES = ('/assets/input/', '/assets/output/', '/assets/library/', '/assets/uploads/', '/output/', '/static/characters/')


class Characters:
    def __init__(self, repository, normalize_resource, can_access):
        self.repository, self.normalize, self.can_access = repository, normalize_resource, can_access

    def catalog(self, principal):
        rows = []
        for entry in self.repository.catalog():
            if not isinstance(entry, dict) or not isinstance(entry.get('id'), str):
                raise CharacterError(503, '官方角色库记录无效')
            profile = self._profile(principal, {key:entry[key] for key in FIELDS if key in entry})
            if any(not ref.startswith('/static/characters/') for ref in [*profile['images'],profile['cover_url']]):
                raise CharacterError(503, '官方角色库只能引用内置公开素材')
            asset_labels = entry.get('asset_labels', [])
            if not isinstance(asset_labels,list) or len(asset_labels)>12 or any(not isinstance(label,str) or len(label)>40 for label in asset_labels):
                raise CharacterError(503, '官方角色资产标签无效')
            rows.append({**profile, 'asset_labels':asset_labels, 'id':entry['id'], 'revision':1, 'created_at':0, 'updated_at':0})
        return rows

    def _images(self, principal, values):
        if not isinstance(values, list) or not 1 <= len(values) <= 12:
            raise CharacterError(400, '请选择1至12张角色参考图')
        images = []
        for value in values:
            if not isinstance(value, str) or len(value) > 2048:
                raise CharacterError(400, '角色参考图格式无效')
            resource = self.normalize(value)
            # The shared normalizer covers private media, not bundled static
            # content. Accept only canonical paths in this public catalog tree.
            if not resource and value.startswith('/static/characters/'):
                path = PurePosixPath(value)
                if (path.as_posix() == value and '..' not in path.parts
                        and not any(char in value for char in ('\\', '%', '?', '#'))
                        and all(ord(char) >= 32 for char in value)):
                    resource = value
            if not resource.startswith(PREFIXES) or PurePosixPath(resource).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
                raise CharacterError(400, '仅支持项目内的图片素材')
            if not self.can_access(principal, resource):
                raise CharacterError(403, '参考图不可访问，请重新选择自己的素材')
            if resource not in images:
                images.append(resource)
        return images

    def _profile(self, principal, body):
        if not isinstance(body, dict) or set(body) - FIELDS:
            raise CharacterError(400, '角色字段无效')
        def text(key, maximum, required=False):
            value = body.get(key, '')
            if not isinstance(value, str) or len(value.strip()) > maximum or required and not value.strip():
                raise CharacterError(400, '角色名称或描述长度无效')
            return value.strip()
        profile = {'name': text('name', 80, True), 'description': text('description', 2000)}
        for key, allowed in (('gender', GENDERS), ('age_group', AGES), ('region', REGIONS)):
            value = body.get(key, 'unspecified')
            if value not in allowed:
                raise CharacterError(400, '角色筛选属性无效')
            profile[key] = value
        profile['images'] = self._images(principal, body.get('images'))
        if 'cover_url' in body and not isinstance(body['cover_url'],str):
            raise CharacterError(400, '角色封面格式无效')
        cover = body.get('cover_url') or profile['images'][0]
        profile['cover_url'] = self._images(principal,[cover])[0]
        if type(body.get('archived', False)) is not bool:
            raise CharacterError(400, '归档状态无效')
        profile['archived'] = body.get('archived', False)
        return profile

    def list(self, principal):
        rows = self.repository.list(principal['user_id'])
        for row in rows:
            original = row['images']
            row['images'] = [ref for ref in original if isinstance(ref, str)
                and ref.startswith(PREFIXES) and self.can_access(principal, ref)]
            row['unavailable_images'] = len(original) - len(row['images'])
            cover = row.get('cover_url') or (original[0] if original else '')
            row['cover_url'] = cover if isinstance(cover,str) and cover.startswith(PREFIXES) and self.can_access(principal,cover) else ''
        return sorted(rows, key=lambda row: row['updated_at'], reverse=True)

    def save(self, principal, body, character_id=None):
        profile = self._profile(principal, body)
        nonce = body.get('create_request_id')
        if nonce is not None and (character_id or not isinstance(nonce, str) or not re.fullmatch(r'[a-f0-9]{32}', nonce)):
            raise CharacterError(400, '创建角色请求编号无效')
        expected = body.get('expected_revision')
        if character_id and (type(expected) is not int or expected < 1):
            raise CharacterError(400, '修改角色需要当前版本号')
        def apply(rows):
            now = int(time.time() * 1000)
            if character_id:
                row = next((item for item in rows if item['id'] == character_id), None)
                if row is None:
                    raise CharacterError(404, '角色不存在')
                if row['revision'] != expected:
                    raise CharacterError(409, '角色已在其他页面修改，请刷新后核对；本次内容未覆盖')
                row.update(profile, revision=row['revision'] + 1, updated_at=now)
            else:
                # A lost HTTP response must not create a second profile on retry.
                # The nonce is account-local; it never grants media access.
                existing = next((item for item in rows if item['id'] == nonce), None) if nonce else None
                if existing:
                    if any(existing.get(key) != value for key, value in profile.items()):
                        raise CharacterError(409, '该创建请求已保存其他内容，请刷新角色库核对')
                    return existing
                if len(rows) >= 500:
                    raise CharacterError(409, '角色库已达到500个，请先整理')
                row = {**profile, 'id': nonce or uuid.uuid4().hex, 'revision': 1, 'created_at': now, 'updated_at': now}
                rows.append(row)
            return row
        return self.repository.mutate(principal['user_id'], apply)

    def remove(self, principal, character_id, expected):
        if type(expected) is not int or expected < 1:
            raise CharacterError(400, '移除角色需要当前版本号')
        def apply(rows):
            row = next((item for item in rows if item['id'] == character_id), None)
            if row is None:
                raise CharacterError(404, '角色不存在')
            if row['revision'] != expected:
                raise CharacterError(409, '角色已在其他页面修改，请刷新后核对')
            row.update(archived=True, revision=row['revision'] + 1, updated_at=int(time.time() * 1000))
            return {'archived': True}
        return self.repository.mutate(principal['user_id'], apply)
