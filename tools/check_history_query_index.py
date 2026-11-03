"""Local shadow check; never changes business JSON, owner DB, or API routing."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enterprise import collection_query as query
from enterprise.history_query_index import HistoryQueryIndex
from enterprise.history_records import HistoryUnavailable, read_records


def ownership_snapshot(database):
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        owners = {row['history_id']: row['user_id'] for row in conn.execute('SELECT history_id,user_id FROM user_history_map')}
        users = {row['id']: dict(row) for row in conn.execute('SELECT id,username,display_name,is_admin,is_active FROM users')}
    return owners, users


def check(index, database, usernames, queries):
    # These are the same existing identity, policy and annotations used by Gateway.
    from enterprise.interceptors import history_id_for_record, filter_history_list, _annotate_history_record
    revision = query.file_revision(index.source)
    records = read_records(index.source)
    identities = [history_id_for_record(record) for record in records]
    if query.file_revision(index.source) != revision:
        raise query.QueryError(409, '历史在读取时更新，本次校对取消。')
    comparisons = 0
    for username in usernames:
        for params in queries:
            owners, users = ownership_snapshot(database)
            user = next((row for row in users.values() if row['username'] == username), None)
            if not user or not user['is_active']:
                raise query.QueryError(403, '校对账号不存在或未启用。')
            actor = {'user_id': user['id'], 'is_admin': bool(user['is_admin'])}
            rows = [dict(row, _query_position=i) for i, row in enumerate(records) if row.get('images')]
            filter_history_list(actor, rows, [identities[row['_query_position']] for row in rows], owners=owners, users=users)
            annotate = lambda row, identifier: _annotate_history_record(row, owners, users, identifier)
            cursor = None
            while True:
                current = {**params, **({'cursor': cursor} if cursor else {})}
                expected = query.page(rows, current, actor=user['id'], source='history', revision=revision)
                actual = index.page(current, user_id=user['id'], owners=owners, admin=actor['is_admin'], annotate=annotate)
                if expected != actual:
                    return {'ok': False, 'comparisons': comparisons, 'different_fields': [key for key in expected if expected[key] != actual.get(key)]}
                comparisons += 1
                cursor = expected['next_cursor']
                if cursor is None:
                    break
    if query.file_revision(index.source) != revision:
        raise query.QueryError(409, '历史在校对时更新，本次结果不作为一致性证据。')
    return {'ok': True, 'source_rows': len(records), 'users_checked': len(usernames), 'queries_per_user': len(queries),
            'page_comparisons': comparisons, 'authority_modified': False, 'api_switched': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--index', required=True)
    parser.add_argument('--database', required=True, help='Existing ownership DB, opened mode=ro.')
    parser.add_argument('--username', action='append', required=True)
    parser.add_argument('--queries-file', type=Path)
    parser.add_argument('--build', action='store_true', help='Explicitly rebuild only the disposable projection.')
    args = parser.parse_args()
    try:
        queries = json.loads(args.queries_file.read_text(encoding='utf-8')) if args.queries_file else [
            {'page_size': 24}, {'page_size': 24, 'type': 'online'}, {'page_size': 7, 'sort': 'oldest'}]
        index = HistoryQueryIndex(args.source, args.index)
        if args.build:
            from enterprise.interceptors import history_id_for_record
            index.rebuild(history_id_for_record)
        result = check(index, args.database, args.username, queries)
    except query.QueryError as exc:
        result = {'ok': False, 'status': exc.status, 'message': str(exc), 'authority_modified': False, 'api_switched': False}
    except (OSError, sqlite3.Error, HistoryUnavailable, ValueError) as exc:
        result = {'ok': False, 'status': 503, 'message': '校对未完成；检查输入文件和只读权限。',
                  'error_type': type(exc).__name__, 'authority_modified': False, 'api_switched': False}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
