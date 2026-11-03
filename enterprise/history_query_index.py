"""Disposable history query projection and bounded Gateway maintenance.

JSON remains authoritative. Ownership is supplied fresh for each query and
kept only in a connection-local memory table; it is never stored in the index.
"""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import sqlite3
from threading import RLock
import time
from uuid import uuid4

from enterprise.collection_query import (
    QueryError, created_time, cursor_position, file_revision, next_cursor,
    query_options, searchable_text,
)
from enterprise.history_records import HistoryUnavailable, read_records
from enterprise.local_json import document_lock

APPLICATION_ID = 0x49434851
FORMAT_VERSION = 1
logger = logging.getLogger(__name__)


class IndexUnavailable(QueryError):
    """Projection failure permits the caller to read current authoritative JSON."""


def _open_readonly(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _require_projection(conn):
    if (conn.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
            or conn.execute('PRAGMA user_version').fetchone()[0] != FORMAT_VERSION):
        raise IndexUnavailable(409, '目标不是当前历史查询索引，保留原文件。')


class HistoryQueryIndex:
    def __init__(self, source, target):
        self.source = Path(source).resolve()
        self.target = Path(target).absolute()
        if (self.target.suffix != '.sqlite3' or self.target.resolve() == self.source
                or self.target.is_symlink()):
            raise ValueError('Use a separate .sqlite3 projection path.')

    def rebuild(self, identify, *, snapshot=None):
        """Build beside the target, then atomically publish a complete revision."""
        temporary = self.target.with_name('.' + self.target.name + '.' + uuid4().hex + '.tmp')
        try:
            if snapshot is None:
                revision = file_revision(self.source)
                records = read_records(self.source)
            else:
                records, revision = snapshot
            if file_revision(self.source) != revision:
                raise QueryError(409, '历史文件已更新，请重新构建查询索引。')
            self.target.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(temporary)) as conn:
                conn.executescript(f'''
                    PRAGMA application_id={APPLICATION_ID};
                    PRAGMA user_version={FORMAT_VERSION};
                    CREATE TABLE projection_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE history_rows (
                        position INTEGER PRIMARY KEY, history_id TEXT NOT NULL,
                        created REAL NOT NULL, newest REAL NOT NULL, record_type TEXT,
                        kind TEXT, library_id TEXT NOT NULL, category_id TEXT NOT NULL,
                        eligible INTEGER NOT NULL, search_text TEXT NOT NULL, payload TEXT NOT NULL
                    );
                ''')
                def projected():
                    for position, row in enumerate(records):
                        created = created_time(row)
                        record_type = row.get('type', 'zimage')
                        kind = row.get('kind', row.get('type'))
                        yield (position, identify(row), created, -created,
                               record_type if isinstance(record_type, str) else None,
                               kind if isinstance(kind, str) else None,
                               str(row.get('library_id') or ''), str(row.get('category_id') or ''),
                               int(bool(row.get('images'))), searchable_text(row),
                               json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
                conn.executemany('INSERT INTO history_rows VALUES (?,?,?,?,?,?,?,?,?,?,?)', projected())
                conn.executescript('''
                    CREATE INDEX history_newest ON history_rows(newest,history_id,position) WHERE eligible=1;
                    CREATE INDEX history_oldest ON history_rows(created,history_id,position) WHERE eligible=1;
                    CREATE INDEX history_type_newest ON history_rows(record_type,newest,history_id,position) WHERE eligible=1;
                    CREATE INDEX history_type_oldest ON history_rows(record_type,created,history_id,position) WHERE eligible=1;
                ''')
                meta = {'source': str(self.source), 'revision': revision, 'source_rows': len(records)}
                conn.executemany('INSERT INTO projection_meta VALUES (?,?)',
                                 [(key, json.dumps(value, ensure_ascii=False)) for key, value in meta.items()])
                conn.commit()
                if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise QueryError(503, '查询索引构建未通过完整性检查。')
            with temporary.open('r+b') as stream:
                os.fsync(stream.fileno())
            # Queries release their handles under this existing cross-process lock.
            # Source writers never take the projection lock.
            with document_lock(self.target):
                if self.target.exists():
                    with closing(_open_readonly(self.target)) as current:
                        _require_projection(current)
                if file_revision(self.source) != revision:
                    raise QueryError(409, '历史文件已更新，未替换旧查询索引。')
                os.replace(temporary, self.target)
            return meta
        except (OSError, sqlite3.Error, HistoryUnavailable, ValueError, TypeError) as exc:
            raise QueryError(503, '查询索引构建未完成；原历史和原索引保留。') from exc
        finally:
            temporary.unlink(missing_ok=True)

    def page(self, params, *, user_id, owners, admin, annotate):
        """Use the caller's current policy snapshot; this module grants no access."""
        options = query_options(params, actor=user_id, source='history')
        try:
            with document_lock(self.target), closing(_open_readonly(self.target)) as conn:
                _require_projection(conn)
                meta = {row['key']: json.loads(row['value']) for row in conn.execute('SELECT * FROM projection_meta')}
                revision = file_revision(self.source)
                if meta.get('source') != str(self.source) or meta.get('revision') != revision:
                    raise IndexUnavailable(409, '查询索引已过期，请按当前历史重新构建。')
                last = cursor_position(str(params.get('cursor') or ''), options, revision)
                conn.execute('PRAGMA temp_store=MEMORY')
                if not admin:
                    conn.execute('CREATE TEMP TABLE visible_history (history_id TEXT PRIMARY KEY) WITHOUT ROWID')
                    conn.executemany('INSERT INTO temp.visible_history VALUES (?)',
                                     [(key,) for key, owner in owners.items() if owner == user_id])
                conn.execute('PRAGMA query_only=ON')
                conditions = ['eligible=1']
                values = []
                if not admin:
                    conditions.append('EXISTS (SELECT 1 FROM temp.visible_history v WHERE v.history_id=history_rows.history_id)')
                for column, wanted in zip(('record_type', 'kind', 'library_id', 'category_id'), options.selectors):
                    if wanted:
                        conditions.append(column + '=?')
                        values.append(wanted)
                if options.search:
                    conditions.append('instr(search_text,?)>0')
                    values.append(options.search)
                where = ' AND '.join(conditions)
                total = conn.execute('SELECT COUNT(*) FROM history_rows WHERE ' + where, values).fetchone()[0]
                order = 'newest' if options.sort == 'newest' else 'created'
                if last is not None:
                    where += f' AND ({order},history_id,position)>(?,?,?)'
                    values = [*values, *last]
                rows = conn.execute(
                    f'SELECT position,history_id,{order} AS sort_time,payload FROM history_rows WHERE {where} '
                    f'ORDER BY {order},history_id,position LIMIT ?', [*values, options.size+1]).fetchall()
                more = len(rows) > options.size
                selected = rows[:options.size]
                items = [{key: value for key, value in annotate(json.loads(row['payload']), row['history_id']).items()
                          if key != '_query_position'} for row in selected]
                if file_revision(self.source) != revision:
                    raise IndexUnavailable(409, '历史文件已更新，请重新校对查询索引。')
                last_row = selected[-1] if more else None
                cursor = next_cursor(options, revision, [
                    last_row['sort_time'], last_row['history_id'], last_row['position'],
                ]) if more else None
                return {'items': items, 'next_cursor': cursor, 'total': total, 'page_size': options.size}
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            raise IndexUnavailable(503, '查询索引暂不可用；原历史接口保持可用。') from exc


class HistoryQueryCache:
    """One disposable projection, one background build, no queue or permissions.

    The caller supplies the already-read immutable JSON snapshot on fallback.
    This avoids another full parse and avoids retaining one snapshot per request.
    Reads always verify the source revision; no expired result is served.
    """
    def __init__(self, index, identify, *, min_source_bytes, retry_seconds=30, clock=time.monotonic):
        self.index = index
        self.identify = identify
        self.min_source_bytes = min_source_bytes
        self.retry_seconds = retry_seconds
        self._clock = clock
        self._lock = RLock()
        self._executor = None
        self._future = None
        self._retry_at = 0
        self._built_revision = None
        self._closed = False

    def page(self, params, **policy):
        with self._lock:
            if self._closed:
                return None
        try:
            revision = file_revision(self.index.source)
            if revision[1] <= self.min_source_bytes:
                return None
            result = self.index.page(params, **policy)
            with self._lock:
                self._built_revision = revision
            return result
        except (OSError, IndexUnavailable):
            with self._lock:
                self._built_revision = None
            return None

    def consider(self, document, revision):
        """Called only after a successful JSON page; never rebuild in the request."""
        if not revision or revision[1] <= self.min_source_bytes:
            return
        with self._lock:
            if (self._closed or self._clock() < self._retry_at
                    or self._built_revision == revision
                    or self._future is not None and not self._future.done()):
                return
            try:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='history-query')
                self._future = self._executor.submit(self._build, (document, revision))
            except (RuntimeError, OSError) as exc:
                self._defer(exc)

    def _defer(self, exc):
        self._retry_at = self._clock() + self.retry_seconds
        # No source paths, prompts, ownership or credentials in failure logs.
        level = logging.INFO if isinstance(exc, QueryError) and exc.status == 409 else logging.WARNING
        logger.log(level, 'History query index deferred (%s); JSON remains available.', type(exc).__name__)

    def _build(self, snapshot):
        try:
            self.index.rebuild(self.identify, snapshot=snapshot)
        except Exception as exc:
            # An optional background cache failure must not fail creative tasks.
            with self._lock:
                self._defer(exc)
        else:
            with self._lock:
                self._retry_at = 0
                self._built_revision = snapshot[1]

    def close(self):
        with self._lock:
            self._closed = True
            executor = self._executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
