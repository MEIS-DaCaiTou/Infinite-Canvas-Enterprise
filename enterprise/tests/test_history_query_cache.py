"""Actual query entry plus bounded background maintenance, without provider calls."""
import json
import asyncio
import threading
from types import SimpleNamespace

import pytest

from enterprise import collection_query as query
from enterprise import history_query_index as projection
from enterprise.interceptors import history_id_for_record
from enterprise.local_json import atomic_write_json
from enterprise.tests.test_collection_query import env, payload


def make_cache(tmp_path, *, minimum=0, **options):
    source = tmp_path/'history.json'
    rows = [{'timestamp': i, 'images': [f'/output/cache-{i}.png'], 'type': 'online'} for i in range(8)]
    atomic_write_json(source, rows)
    index = projection.HistoryQueryIndex(source, tmp_path/'query.sqlite3')
    return projection.HistoryQueryCache(index, history_id_for_record, min_source_bytes=minimum, **options), rows


def policy():
    return {'user_id': 'a', 'owners': {}, 'admin': True, 'annotate': lambda row, _: row}


def test_small_histories_keep_original_memory_path(tmp_path):
    cache, rows = make_cache(tmp_path, minimum=8*1024*1024)
    try:
        assert cache.page({'page_size': 2}, **policy()) is None
        cache.consider(rows, query.file_revision(cache.index.source))
        assert cache._executor is None and not cache.index.target.exists()
    finally:
        cache.close()


def test_requests_coalesce_one_build_and_share_existing_parse(tmp_path, monkeypatch):
    cache, rows = make_cache(tmp_path)
    entered, release = threading.Event(), threading.Event()
    build = cache.index.rebuild
    calls = []
    def blocked(identify, *, snapshot):
        calls.append(1)
        assert snapshot[0] is rows
        entered.set()
        assert release.wait(5)
        return build(identify, snapshot=snapshot)
    monkeypatch.setattr(cache.index, 'rebuild', blocked)
    monkeypatch.setattr(projection, 'read_records', lambda _: pytest.fail('background reparsed whole JSON'))
    revision = query.file_revision(cache.index.source)
    try:
        assert cache.page({'page_size': 2}, **policy()) is None
        cache.consider(rows, revision)
        assert entered.wait(5)
        for _ in range(30):
            cache.consider(rows, revision)
        assert calls == [1] and not cache.index.target.exists()
        release.set(); cache._future.result(timeout=5)
        assert cache.page({'page_size': 2}, **policy())['total'] == 8
        cache.consider(rows, revision)
        assert calls == [1], 'already-completed revision must not rebuild for late fallback requests'
    finally:
        release.set(); cache.close()


def test_failed_build_backs_off_without_breaking_queries_or_erasing_foreign_file(tmp_path, monkeypatch, caplog):
    clock = [100.0]
    cache, rows = make_cache(tmp_path, clock=lambda:clock[0])
    cache.index.target.write_bytes(b'keep unknown file')
    calls = []
    build = cache.index.rebuild
    def counted(*args, **kwargs):
        calls.append(1)
        return build(*args, **kwargs)
    monkeypatch.setattr(cache.index, 'rebuild', counted)
    revision = query.file_revision(cache.index.source)
    try:
        assert cache.page({'page_size': 2}, **policy()) is None
        cache.consider(rows, revision); cache._future.result(timeout=5)
        for _ in range(20):
            cache.consider(rows, revision)
        assert calls == [1]
        clock[0] += 31
        cache.consider(rows, revision); cache._future.result(timeout=5)
        assert calls == [1,1]
        assert cache.index.target.read_bytes() == b'keep unknown file'
        assert json.loads(cache.index.source.read_text()) == rows
        assert 'JSON remains available' in caplog.text
        assert str(cache.index.source) not in caplog.text
    finally:
        cache.close()


def test_new_cache_reuses_persistent_index_and_shutdown_stops_new_work(tmp_path, monkeypatch):
    cache, rows = make_cache(tmp_path)
    cache.consider(rows, query.file_revision(cache.index.source)); cache._future.result(timeout=5)
    cache.close()
    assert cache.page({'page_size': 2}, **policy()) is None
    cache.consider(rows, query.file_revision(cache.index.source))
    next_cache = projection.HistoryQueryCache(cache.index, history_id_for_record, min_source_bytes=0)
    monkeypatch.setattr(cache.index, 'rebuild', lambda *_args, **_kw: pytest.fail('restart rebuilt valid index'))
    try:
        assert next_cache.page({'page_size': 2}, **policy())['total'] == 8
        assert next_cache._executor is None
        with pytest.raises(query.QueryError) as error:
            next_cache.page({'page_size': 2, 'cursor': 'bad'}, **policy())
        assert error.value.status == 400
    finally:
        next_cache.close()


def test_source_changed_while_building_defers_and_does_not_publish_stale(tmp_path, monkeypatch):
    cache, rows = make_cache(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = cache.index.rebuild
    def blocked(identify, *, snapshot):
        entered.set(); assert release.wait(5)
        return original(identify, snapshot=snapshot)
    monkeypatch.setattr(cache.index, 'rebuild', blocked)
    try:
        cache.consider(rows, query.file_revision(cache.index.source)); assert entered.wait(5)
        atomic_write_json(cache.index.source, rows[:2])
        release.set(); cache._future.result(timeout=5)
        assert not cache.index.target.exists() and cache._retry_at > 0
        assert cache.page({'page_size': 2}, **policy()) is None
    finally:
        release.set(); cache.close()


def test_shutdown_drains_one_running_build_and_accepts_no_more_snapshots(tmp_path, monkeypatch):
    cache, rows = make_cache(tmp_path)
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    build = cache.index.rebuild
    def blocked(*args, **kwargs):
        entered.set(); assert release.wait(5)
        return build(*args, **kwargs)
    monkeypatch.setattr(cache.index, 'rebuild', blocked)
    def stop():
        cache.close(); stopped.set()
    cache.consider(rows, query.file_revision(cache.index.source)); assert entered.wait(5)
    worker = threading.Thread(target=stop)
    worker.start()
    try:
        assert not stopped.wait(.05), 'shutdown returned while the build still held its snapshot'
        release.set(); worker.join(timeout=5)
        assert stopped.is_set() and cache.page({'page_size':2}, **policy()) is None
        future = cache._future
        cache.consider(rows, query.file_revision(cache.index.source))
        assert cache._future is future
    finally:
        release.set(); worker.join(timeout=5); cache.close()


@pytest.fixture
def integrated(env, monkeypatch):
    db, api, (a,b) = env
    rows = [{'timestamp': i, 'images': [f'/output/integrated-{i}.png'], 'type': 'online'} for i in range(8)]
    atomic_write_json(api._HISTORY_FILE, rows)
    for i,row in enumerate(rows):
        db.record_history_owner(a['user_id'] if i % 2 else b['user_id'], api.history_id_for_record(row), 'online')
    index = projection.HistoryQueryIndex(api._HISTORY_FILE, api._HISTORY_FILE.parent/'query.sqlite3')
    cache = projection.HistoryQueryCache(index, api.history_id_for_record, min_source_bytes=0)
    monkeypatch.setattr(api, '_HISTORY_QUERIES', cache)
    yield db, api, a, b, rows, cache
    cache.close()


def test_original_entry_falls_back_then_uses_index_with_current_permissions(integrated, monkeypatch):
    db, api, a, b, rows, cache = integrated
    args = {'page_size':2, 'type':'online'}
    first = payload(api.handle_collection_query(a, 'api/history', args))
    assert first['total'] == 4
    cache._future.result(timeout=5)
    monkeypatch.setattr(api._COLLECTION_QUERIES, 'read', lambda *_: pytest.fail('valid index fell back to JSON'))
    assert payload(api.handle_collection_query(a, 'api/history', args)) == first
    other = payload(api.handle_collection_query(b, 'api/history', args))
    assert other['total'] == 4 and not {x['enterprise_history_id'] for x in first['items']} & {x['enterprise_history_id'] for x in other['items']}
    db.remove_history_mapping(api.history_id_for_record(rows[7]))
    assert payload(api.handle_collection_query(a, 'api/history', args))['total'] == 3
    assert payload(api.handle_collection_query({'user_id':'admin','is_admin':True},'api/history',args))['total'] == 8
    assert api.handle_collection_query(b,'api/history',{**args,'cursor':first['next_cursor']}).status_code == 400


def test_active_index_still_sits_behind_existing_feature_guard(integrated, monkeypatch):
    from starlette.responses import JSONResponse
    _db, api, a, _b, _rows, cache = integrated
    payload(api.handle_collection_query(a,'api/history',{'page_size':2})); cache._future.result(timeout=5)
    monkeypatch.setattr(api,'_request_feature_key',lambda *_:'controlled-feature')
    monkeypatch.setattr(api,'_feature_denial',lambda *_:JSONResponse({'message':'not allowed'},status_code=403))
    monkeypatch.setattr(cache,'page',lambda *_args,**_kwargs:pytest.fail('feature guard bypassed'))
    response=asyncio.run(api.pre_process('api/history','GET',a,{'page_size':2}))
    assert response.status_code == 403


def test_append_delete_and_old_cursor_follow_source_revision(integrated, monkeypatch):
    from enterprise.history_records import append_record, delete_matching
    db, api, a, _b, rows, cache = integrated
    args = {'page_size':2}
    first = payload(api.handle_collection_query(a, 'api/history', args)); cache._future.result(timeout=5)
    added = {'timestamp': 20,'images':['/output/new-record.png'],'type':'online'}
    db.record_history_owner(a['user_id'], api.history_id_for_record(added), 'online')
    append_record(api._HISTORY_FILE, added)
    assert api.handle_collection_query(a,'api/history',{**args,'cursor':first['next_cursor']}).status_code == 409
    fresh = payload(api.handle_collection_query(a,'api/history',args))
    assert fresh['total'] == 5 and fresh['items'][0]['timestamp'] == 20
    cache._future.result(timeout=5)
    assert payload(api.handle_collection_query(a,'api/history',args)) == fresh
    delete_matching(api._HISTORY_FILE,20)
    deleted = payload(api.handle_collection_query(a,'api/history',args))
    assert deleted['total'] == 4 and all(x['timestamp'] != 20 for x in deleted['items'])
    cache._future.result(timeout=5)
    assert payload(api.handle_collection_query(a,'api/history',args)) == deleted


def test_corrupt_source_never_serves_cached_success_and_broken_index_keeps_json(integrated):
    _db, api, a, _b, rows, cache = integrated
    args = {'page_size':2}
    first = payload(api.handle_collection_query(a,'api/history',args)); cache._future.result(timeout=5)
    cache.index.target.write_bytes(b'bad cached file')
    assert payload(api.handle_collection_query(a,'api/history',args)) == first
    cache._future.result(timeout=5)
    assert cache.index.target.read_bytes() == b'bad cached file'
    api._HISTORY_FILE.write_text('{broken source', encoding='utf-8')
    assert api.handle_collection_query(a,'api/history',args).status_code == 503
    assert api._HISTORY_FILE.read_text() == '{broken source'


def test_gateway_factory_uses_cache_root_and_disable_switch(env, monkeypatch, tmp_path):
    _db, api, (a, _b) = env
    atomic_write_json(api._HISTORY_FILE, [])
    monkeypatch.setattr(api, 'PATH_ROOTS', SimpleNamespace(CACHE_ROOT=tmp_path/'cache'))
    monkeypatch.setattr(api, 'ENTERPRISE_HISTORY_QUERY_INDEX_ENABLED', True)
    api.start_collection_queries()
    cache = api._HISTORY_QUERIES
    assert cache.index.target == tmp_path/'cache/queries/history-v1.sqlite3'
    assert cache.min_source_bytes == api._COLLECTION_QUERIES.max_cached_bytes
    assert payload(api.handle_collection_query(a,'api/history',{'page_size':2}))['total'] == 0
    assert not (tmp_path/'cache').exists()
    api.stop_collection_queries()
    assert api._HISTORY_QUERIES is None and cache._closed
    monkeypatch.setattr(api, 'ENTERPRISE_HISTORY_QUERY_INDEX_ENABLED', False)
    api.start_collection_queries()
    assert api._HISTORY_QUERIES is None
    assert payload(api.handle_collection_query(a,'api/history',{'page_size':2}))['total'] == 0
