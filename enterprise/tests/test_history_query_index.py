"""Shadow projection parity, fresh ownership and failed-publication boundaries."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from enterprise import collection_query as query
from enterprise import history_query_index as projection
from enterprise.interceptors import (
    _annotate_history_record, filter_history_list, history_id_for_record,
)
from enterprise.local_json import atomic_write_json


@pytest.fixture
def sample(tmp_path):
    rows = []
    for i in range(19):
        row = {'timestamp': i//3, 'images': [f'/output/{i}.png'],
               'type': 'online' if i % 2 else 'zimage', 'kind': 'image',
               'name': f'款式 {i}', 'prompt': 'Straße 春夏', 'tags': ['服装'],
               'library_id': 'wardrobe', 'category_id': 'spring'}
        rows.append(row)
    rows[0]['_query_position'] = 999  # Internal navigation fields never escape either implementation.
    rows += [deepcopy(rows[0]), {'images': ['/output/no-time.png']},
             {'timestamp': 'invalid', 'images': ['/output/invalid-time.png']},
             {'timestamp': '2026-10-20T08:00:00Z', 'images': ['/output/iso.png']},
             {'timestamp': 1790000000000, 'images': ['/output/ms.png']},
             {'timestamp': 80, 'images': []}, {'timestamp': 90},
             {'timestamp': 92, 'type': None, 'images': ['/output/none.png']}]
    source = tmp_path/'history.json'
    atomic_write_json(source, rows)
    index = projection.HistoryQueryIndex(source, tmp_path/'query.sqlite3')
    index.rebuild(history_id_for_record)
    owners = {history_id_for_record(row): ('a' if i % 2 else 'b') for i, row in enumerate(rows[:-1])}
    users = {'a': {'username': 'A', 'display_name': '同事 A'}, 'b': {'username': 'B'}}
    return rows, index, owners, users


def compare_pages(sample, params, actor='a', admin=False):
    rows, index, owners, users = sample
    eligible = [dict(row, _query_position=i) for i, row in enumerate(rows) if row.get('images')]
    filter_history_list({'user_id': actor, 'is_admin': admin}, eligible,
                        [history_id_for_record(row) for row in eligible], owners=owners, users=users)
    annotate = lambda row, identifier: _annotate_history_record(row, owners, users, identifier)
    cursor = None
    pages = []
    while True:
        args = {**params, **({'cursor': cursor} if cursor else {})}
        expected = query.page(eligible, args, actor=actor, source='history', revision=query.file_revision(index.source))
        actual = index.page(args, user_id=actor, owners=owners, admin=admin, annotate=annotate)
        assert actual == expected
        pages.append(actual)
        cursor = expected['next_cursor']
        if cursor is None:
            return pages


@pytest.mark.parametrize('params', [
    {'page_size': 1}, {'page_size': 3, 'sort': 'oldest'}, {'page_size': 4, 'type': 'online'},
    {'page_size': 2, 'q': 'STRASSE'}, {'page_size': 3, 'q': '服装'},
    {'page_size': 2, 'kind': 'image', 'library_id': 'wardrobe', 'category_id': 'spring'},
    {'page_size': 2, 'q': 'absent'}, {'page_size': 2, 'type': 'zimage'},
])
@pytest.mark.parametrize('actor,admin', [('a', False), ('b', False), ('admin', True)])
def test_all_pages_match_original_policy_and_query(sample, params, actor, admin):
    compare_pages(sample, params, actor, admin)


def test_owner_changes_and_cursor_cannot_retain_access(sample):
    rows, index, owners, users = sample
    first = compare_pages(sample, {'page_size': 2})[0]
    for identifier in list(owners):
        if owners[identifier] == 'a':
            owners[identifier] = 'b'
    assert compare_pages(sample, {'page_size': 2})[0]['total'] == 0
    args = {'page_size': 2, 'cursor': first['next_cursor']}
    annotate = lambda row, identifier: _annotate_history_record(row, owners, users, identifier)
    assert index.page(args, user_id='a', owners=owners, admin=False, annotate=annotate)['items'] == []
    with pytest.raises(query.QueryError) as error:
        index.page(args, user_id='b', owners=owners, admin=False, annotate=annotate)
    assert error.value.status == 400
    with pytest.raises(query.QueryError) as error:
        index.page({**args, 'q': 'changed'}, user_id='a', owners=owners, admin=False, annotate=annotate)
    assert error.value.status == 400


def test_reopen_queries_do_not_parse_source_or_write_projection(sample, monkeypatch):
    _, index, _, _ = sample
    before = index.source.read_bytes(), index.target.read_bytes()
    monkeypatch.setattr(projection, 'read_records', lambda _: pytest.fail('warm query read whole JSON'))
    reopened = projection.HistoryQueryIndex(index.source, index.target)
    compare_pages((sample[0], reopened, sample[2], sample[3]), {'page_size': 3})
    assert before == (index.source.read_bytes(), index.target.read_bytes())


def test_replacement_invalidates_old_cursor_and_requires_rebuild(sample):
    rows, index, _, _ = sample
    old = compare_pages(sample, {'page_size': 2})[0]['next_cursor']
    atomic_write_json(index.source, rows[:5])
    with pytest.raises(query.QueryError) as error:
        index.page({'page_size': 2}, user_id='a', owners={}, admin=True, annotate=lambda row, _: row)
    assert error.value.status == 409
    index.rebuild(history_id_for_record)
    with pytest.raises(query.QueryError) as error:
        index.page({'page_size': 2, 'cursor': old}, user_id='a', owners={}, admin=True, annotate=lambda row, _: row)
    assert error.value.status == 409
    compare_pages((rows[:5], index, sample[2], sample[3]), {'page_size': 2})


def test_prepend_updates_only_new_projection_rows_and_keeps_cursor_parity(sample, monkeypatch):
    rows, index, owners, users = sample
    added = [deepcopy(rows[0]), {'timestamp': 20, 'images': ['/output/new.png']}]
    records = added + rows
    owners[history_id_for_record(added[1])] = 'a'
    atomic_write_json(index.source, records)
    monkeypatch.setattr(index, 'rebuild', lambda *a, **kw: pytest.fail('pure prepend rebuilt projection'))
    projected = []
    def identify(row):
        projected.append(row)
        return history_id_for_record(row)
    index.refresh(identify, snapshot=(records, query.file_revision(index.source)))
    assert projected == added
    for sort in ('newest', 'oldest'):
        compare_pages((records, index, owners, users), {'page_size': 1, 'sort': sort}, admin=True)
        compare_pages((records, index, owners, users), {'page_size': 2, 'sort': sort})


def test_prepend_with_edit_of_same_history_id_rebuilds_projection(sample):
    rows, index, owners, users = sample
    records = [{'timestamp': 20, 'images': ['/output/new.png']}, *deepcopy(rows)]
    records[1]['name'] = 'edited without changing identity'
    assert history_id_for_record(records[1]) == history_id_for_record(rows[0])
    atomic_write_json(index.source, records)
    index.refresh(history_id_for_record, snapshot=(records, query.file_revision(index.source)))
    compare_pages((records, index, owners, users), {'page_size': 2}, admin=True)


def test_concurrent_source_change_rolls_back_projection_rows_and_revision(sample):
    rows, index, owners, users = sample
    added = {'timestamp': 20, 'images': ['/output/new.png']}
    records = [added, *rows]
    atomic_write_json(index.source, records)
    def identify(row):
        atomic_write_json(index.source, rows[:1])
        return history_id_for_record(row)
    with pytest.raises(query.QueryError) as error:
        index.refresh(identify, snapshot=(records, query.file_revision(index.source)))
    assert error.value.status == 409
    with closing(sqlite3.connect(index.target)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM history_rows').fetchone()[0] == len(rows)
    index.refresh(history_id_for_record, snapshot=(rows[:1], query.file_revision(index.source)))
    compare_pages((rows[:1], index, owners, users), {'page_size': 2}, admin=True)


def test_restart_recovers_projection_interrupted_before_commit(sample):
    rows, index, owners, users = sample
    added = [{'timestamp': 100 + i, 'images': [f'/output/new-{i}.png'], 'prompt': 'x'*10000}
             for i in range(10)]
    records = added + rows
    atomic_write_json(index.source, records)
    revision = query.file_revision(index.source)
    command = """
import os, sys
sys.path.insert(0, sys.argv[1])
from enterprise import history_query_index as projection
from enterprise.interceptors import history_id_for_record
index = projection.HistoryQueryIndex(sys.argv[2], sys.argv[3])
records = projection.read_records(index.source)
file_revision = projection.file_revision
revision = file_revision(index.source)
open_existing = projection._open_existing
def small_cache(path):
    conn = open_existing(path)
    conn.execute('PRAGMA cache_size=1')
    return conn
projection._open_existing = small_cache
calls = iter([revision, revision])
def interrupt(path):
    try:
        return next(calls)
    except StopIteration:
        os._exit(42)
projection.file_revision = interrupt
index.refresh(history_id_for_record, snapshot=(records, revision))
"""
    result = subprocess.run([sys.executable, '-B', '-c', command, str(Path(__file__).parents[2]),
                             str(index.source), str(index.target)], capture_output=True, timeout=15)
    assert result.returncode == 42, result.stderr
    assert index.target.with_suffix('.sqlite3-journal').is_file()
    with pytest.raises(projection.IndexUnavailable):
        index.page({'page_size': 2}, user_id='a', owners=owners, admin=False, annotate=lambda row, _: row)
    index.refresh(history_id_for_record, snapshot=(records, revision))
    compare_pages((records, index, owners, users), {'page_size': 2}, admin=True)
    assert projection.read_records(index.source) == records


def test_source_update_during_page_cancels_the_result(sample):
    rows, index, owners, users = sample
    def annotate(row, identifier):
        atomic_write_json(index.source, rows[:1])
        return _annotate_history_record(row, owners, users, identifier)
    with pytest.raises(query.QueryError) as error:
        index.page({'page_size': 2}, user_id='a', owners=owners, admin=False, annotate=annotate)
    assert error.value.status == 409


@pytest.mark.parametrize('failure', ['publish', 'identity', 'source_changed'])
def test_failed_build_preserves_previous_index_and_cleans_own_temporary(sample, monkeypatch, failure):
    rows, index, _, _ = sample
    old_index, old_source = index.target.read_bytes(), index.source.read_bytes()
    identify = history_id_for_record
    if failure == 'publish':
        def denied(*_): raise PermissionError('fixture locked target')
        monkeypatch.setattr(projection.os, 'replace', denied)
    elif failure == 'identity':
        def identify(_): raise ValueError('fixture unsupported record')
    else:
        changed = False
        def identify(row):
            nonlocal changed
            if not changed:
                atomic_write_json(index.source, rows[:3]); changed = True
            return history_id_for_record(row)
    with pytest.raises(query.QueryError) as error:
        index.rebuild(identify)
    assert error.value.status == (409 if failure == 'source_changed' else 503)
    assert index.target.read_bytes() == old_index
    if failure != 'source_changed':
        assert index.source.read_bytes() == old_source
    assert not list(index.target.parent.glob('.query.sqlite3.*.tmp'))


def test_foreign_database_is_never_replaced(tmp_path):
    source, target = tmp_path/'history.json', tmp_path/'business.sqlite3'
    atomic_write_json(source, [])
    with sqlite3.connect(target) as conn:
        conn.execute('CREATE TABLE business (value TEXT)')
        conn.execute('INSERT INTO business VALUES (?)', ('keep',)); conn.commit()
    before = target.read_bytes()
    with pytest.raises(query.QueryError) as error:
        projection.HistoryQueryIndex(source, target).rebuild(history_id_for_record)
    assert error.value.status == 409 and target.read_bytes() == before
    assert not list(tmp_path.glob('.*.tmp'))


def test_bad_json_and_projection_fail_explicitly_without_erasing_source(sample):
    _, index, _, _ = sample
    old_index = index.target.read_bytes()
    index.source.write_text('{broken', encoding='utf-8')
    with pytest.raises(query.QueryError) as error:
        index.rebuild(history_id_for_record)
    assert error.value.status == 503 and index.source.read_text() == '{broken'
    assert index.target.read_bytes() == old_index
    index.target.write_bytes(b'broken sqlite')
    with pytest.raises(query.QueryError) as error:
        index.page({'page_size': 2}, user_id='a', owners={}, admin=True, annotate=lambda row, _: row)
    assert error.value.status == 503


def test_shadow_tool_uses_readonly_current_owner_database(tmp_path):
    from tools.check_history_query_index import check, ownership_snapshot
    source, database = tmp_path/'history.json', tmp_path/'enterprise.db'
    rows = [{'timestamp': i, 'images': [f'/output/{i}.png']} for i in range(5)]
    atomic_write_json(source, rows)
    with sqlite3.connect(database) as conn:
        conn.executescript('CREATE TABLE users(id TEXT,username TEXT,display_name TEXT,is_admin INTEGER,is_active INTEGER);'
                           'CREATE TABLE user_history_map(history_id TEXT,user_id TEXT);')
        conn.executemany('INSERT INTO users VALUES (?,?,?,?,?)', [('a','qa-a','A',0,1),('b','qa-b','B',0,1),('admin','qa-admin','Admin',1,1)])
        conn.executemany('INSERT INTO user_history_map VALUES (?,?)', [(history_id_for_record(row), 'a' if i%2 else 'b') for i,row in enumerate(rows)])
        conn.commit()
    index = projection.HistoryQueryIndex(source, tmp_path/'query.sqlite3')
    index.rebuild(history_id_for_record)
    before = database.read_bytes(), source.read_bytes()
    result = check(index, database, ['qa-a','qa-b','qa-admin'], [{'page_size': 1}, {'page_size': 2, 'sort': 'oldest'}])
    assert result['ok'] and result['page_comparisons'] == 16
    assert before == (database.read_bytes(), source.read_bytes())
    with sqlite3.connect(database) as conn:
        conn.execute('UPDATE user_history_map SET user_id=?', ('b',)); conn.commit()
    assert set(ownership_snapshot(database)[0].values()) == {'b'}
    assert check(index, database, ['qa-a','qa-b'], [{'page_size': 2}])['ok']
