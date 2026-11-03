"""Read-only pages over existing history/library files; grants belong to callers.

Only two parsed documents are retained, invalidated by filesystem metadata.
Large documents remain queryable without caching. This is not a new fact store.
"""
import base64
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
from threading import RLock

from enterprise.local_json import read_json


class QueryError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def file_revision(path):
    stat = Path(path).stat()
    return [stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


class QuerySnapshots:
    def __init__(self, max_cached_bytes=8 * 1024 * 1024):
        self.max_cached_bytes = max_cached_bytes
        self._entries = {}
        self._lock = RLock()

    def read(self, path, source):
        path = Path(path)
        with self._lock:
            try:
                revision = file_revision(path)
                cached = self._entries.get(source)
                if cached and cached[:2] == (str(path), revision):
                    return cached[2], revision
                self._entries.pop(source, None)
                data = read_json(path)
                if source == 'history':
                    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                        raise ValueError('invalid history')
                elif not isinstance(data, dict):
                    raise ValueError('invalid library')
                else:
                    libraries = data.get('libraries', [])
                    if not isinstance(libraries, list):
                        raise ValueError('invalid libraries')
                    if not libraries:
                        libraries = [{'categories': data.get('categories', [])}]
                    for library in libraries:
                        if not isinstance(library, dict) or not isinstance(library.get('categories', []), list):
                            raise ValueError('invalid categories')
                        for category in library.get('categories', []):
                            if (not isinstance(category, dict) or not isinstance(category.get('items', []), list)
                                    or any(not isinstance(item, dict) for item in category.get('items', []))):
                                raise ValueError('invalid items')
                if revision != file_revision(path):
                    raise QueryError(409, '列表已更新，请刷新后继续。')
                if revision[1] <= self.max_cached_bytes:
                    self._entries[source] = (str(path), revision, data)
                return data, revision
            except FileNotFoundError:
                self._entries.pop(source, None)
                return ([] if source == 'history' else {}), []
            except (OSError, ValueError, TypeError) as exc:
                self._entries.pop(source, None)
                raise QueryError(503, '列表暂不可读，原文件保留；请重试或联系管理员。') from exc

    def history_ids(self, document, identify):
        """Cache derived identities with their immutable document, never owners."""
        with self._lock:
            cached = self._entries.get('history')
            if cached and cached[2] is document:
                if len(cached) == 3:
                    cached = (*cached, [identify(row) for row in document])
                    self._entries['history'] = cached
                return cached[3]
            return [identify(row) for row in document]

    def library_lookup(self, document, resource_url):
        """Derived positions only; every request still obtains current grants."""
        with self._lock:
            cached = self._entries.get('library')
            if cached and cached[2] is document and len(cached) > 3:
                return cached[3]
            lookup = LibraryLookup(document, resource_url)
            if cached and cached[2] is document:
                self._entries['library'] = (*cached, lookup)
            return lookup


class LibraryLookup:
    """Immutable-document navigation; no identity, ownership or saved state."""
    def __init__(self, document, resource_url):
        self.document = document
        self.libraries = document.get('libraries')
        self.explicit_libraries = isinstance(self.libraries, list)
        if not self.explicit_libraries:
            self.libraries = [{'id': 'default', 'categories': document.get('categories', [])}]
        self.entries, self.by_id, self.by_resource, self.containers = [], {}, {}, set()
        for li, library in enumerate(self.libraries):
            self.containers.add(('library', str(library.get('id') or '')))
            for ci, category in enumerate(library.get('categories') or []):
                self.containers.add(('category', str(category.get('id') or '')))
                for item in category.get('items') or []:
                    identifier, url = str(item.get('id') or '').strip(), resource_url(item)
                    position = len(self.entries)
                    self.entries.append((li, ci, identifier, url, item))
                    if identifier:
                        self.by_id.setdefault(identifier, []).append(position)
                    if url:
                        self.by_resource.setdefault(url, []).append(position)

    def subset(self, positions):
        """Preserve original container/order semantics for the existing policy."""
        groups = {}
        for position in sorted(positions):
            li, ci, _identifier, _url, item = self.entries[position]
            groups.setdefault((li, ci), []).append(item)
        libraries = [{**library, 'categories': [
            {**category, 'items': groups.get((li, ci), [])}
            for ci, category in enumerate(library.get('categories') or [])]}
            for li, library in enumerate(self.libraries)]
        if self.explicit_libraries:
            return {**self.document, 'libraries': libraries}
        return {**self.document, 'categories': libraries[0]['categories']}


def created_time(row):
    value = row.get('timestamp') or row.get('created_at') or 0
    try:
        result = float(value)
        if result > 1e11:
            result /= 1000
        return result if math.isfinite(result) else 0
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
        except ValueError:
            return 0


def library_items(root):
    libraries = root.get('libraries') or [{'id': 'default', 'categories': root.get('categories', [])}]
    for library in libraries:
        for category in library.get('categories') or []:
            for item in category.get('items') or []:
                if isinstance(item, dict):
                    yield {**item, 'library_id': library.get('id', ''), 'category_id': category.get('id', '')}


def library_catalog(root):
    """Call after authorization: preserve navigation, omit full item arrays."""
    result = {key: value for key, value in root.items() if key not in {'libraries', 'categories', 'items'}}
    libraries = root.get('libraries') or [{'id': 'default', 'categories': root.get('categories', [])}]
    if 'libraries' in root:
        libraries = root['libraries']
    result['libraries'] = []
    for library in libraries:
        entry = {key: value for key, value in library.items() if key not in {'categories', 'items'}}
        entry['categories'] = []
        for category in library.get('categories') or []:
            items = category.get('items') or []
            entry['categories'].append({
                **{key: value for key, value in category.items() if key != 'items'},
                'item_count': len(items), 'preview_items': items[-2:],
            })
        entry['item_count'] = sum(row['item_count'] for row in entry['categories'])
        result['libraries'].append(entry)
    return result


@dataclass(frozen=True)
class PageOptions:
    size: int
    search: str
    sort: str
    selectors: tuple
    signature: list


def query_options(params, *, actor, source):
    try:
        size = int(params.get('page_size', 24))
    except (TypeError, ValueError) as exc:
        raise QueryError(400, 'page_size须为1至100的整数。') from exc
    if not 1 <= size <= 100:
        raise QueryError(400, 'page_size须为1至100的整数。')
    query = str(params.get('q') or '').strip().casefold()
    sort = str(params.get('sort') or 'newest')
    if len(query) > 200 or sort not in {'newest', 'oldest'}:
        raise QueryError(400, '查询文本过长或排序参数无效。')
    selectors = [str(params.get(name) or '') for name in ('type', 'kind', 'library_id', 'category_id')]
    if selectors[1] not in {'', 'image', 'video', 'audio', 'workflow'}:
        raise QueryError(400, '媒体类型无效。')
    signature = [str(actor), source, size, query, sort, *selectors]
    if source == 'library' and (params.get('item_id') or params.get('match_url')):
        signature.extend([str(params.get('item_id') or ''), str(params.get('match_url') or '')])
    return PageOptions(size, query, sort, tuple(selectors), signature)


def cursor_position(cursor, options, revision):
    if not cursor:
        return None
    try:
        if len(cursor) > 4096:
            raise ValueError('long cursor')
        token = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
        if token['query'] != options.signature:
            raise ValueError('different query')
        if token['revision'] != revision:
            raise QueryError(409, '列表已更新，请刷新后继续。')
        last = token['after']
        if (not isinstance(last, list) or len(last) != 3 or not isinstance(last[0], (int, float))
                or not math.isfinite(last[0]) or not isinstance(last[1], str) or not isinstance(last[2], int)):
            raise ValueError('bad position')
        return last
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise QueryError(400, '分页游标无效，请刷新列表。') from exc


def next_cursor(options, revision, last):
    # JSON and SQLite must issue the same token, including missing timestamps.
    last = [float(last[0]) if last[0] else 0.0, *last[1:]]
    token = {'query': options.signature, 'revision': revision, 'after': last}
    return base64.urlsafe_b64encode(json.dumps(token, separators=(',', ':')).encode()).decode().rstrip('=')


def searchable_text(row):
    return ' '.join(str(row.get(k) or '') for k in ('name', 'prompt', 'tags')).casefold()


def page(rows, params, *, actor, source, revision):
    """Call only after current authorization. Cursor is navigation, never a grant."""
    options = query_options(params, actor=actor, source=source)
    size, query, sort, selectors = options.size, options.search, options.sort, options.selectors
    matches = []
    for position, row in enumerate(rows):
        if source == 'library':
            if params.get('item_id') and str(row.get('id') or '') != str(params['item_id']):
                continue
            if params.get('match_url') and params['match_url'] not in (row.get('url'), row.get('collected_from')):
                continue
        if selectors[0] and row.get('type', 'zimage') != selectors[0]:
            continue
        if selectors[1] and row.get('kind', row.get('type')) != selectors[1]:
            continue
        if any(wanted and str(row.get(name) or '') != wanted for name, wanted in zip(('library_id', 'category_id'), selectors[2:])):
            continue
        if query and query not in searchable_text(row):
            continue
        identity = str(row.get('enterprise_history_id') or row.get('id') or '')
        key = [created_time(row) * (-1 if sort == 'newest' else 1), identity, row.get('_query_position', position)]
        matches.append((key, row))
    matches.sort(key=lambda pair: pair[0])
    cursor = str(params.get('cursor') or '')
    last = cursor_position(cursor, options, revision)
    if last is not None:
        remaining = [pair for pair in matches if pair[0] > last]
    else:
        remaining = matches
    selected = remaining[:size]
    following = None
    if len(remaining) > size:
        following = next_cursor(options, revision, selected[-1][0])
    items = [{k: v for k, v in row.items() if k != '_query_position'} for _key, row in selected]
    return {'items': items, 'next_cursor': following, 'total': len(matches), 'page_size': size}
