"""Shadow projection parity, fresh ownership and failed-publication boundaries."""
from copy import deepcopy
import json
import sqlite3

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
