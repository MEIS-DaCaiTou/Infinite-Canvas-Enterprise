"""Opt-in live continuation rechecks current grants and rebases its anchor."""
import pytest
from enterprise import collection_query as query
from enterprise.history_query_index import HistoryQueryIndex
from enterprise.interceptors import history_id_for_record
from enterprise.local_json import atomic_write_json


@pytest.mark.parametrize('indexed',[False,True])
def test_append_delete_and_revocation_between_live_pages(tmp_path,indexed):
    source=tmp_path/'history.json';index=HistoryQueryIndex(source,tmp_path/'index.sqlite3')
    rows=[{'timestamp':i,'images':[f'/output/{i}.png'],'type':'online'} for i in range(30,0,-1)]
    allowed={history_id_for_record(r) for r in rows}
    params={'page_size':4,'type':'online','continuation':'live'}
    def fetch(params):
        atomic_write_json(source,rows)
        if indexed:
            index.rebuild(history_id_for_record)
            return index.page(params,user_id='alice',owners={key:'alice' for key in allowed},admin=False,
                annotate=lambda r,key:{**r,'enterprise_history_id':key})
        visible=[dict(r,enterprise_history_id=history_id_for_record(r),_query_position=i)
                 for i,r in enumerate(rows) if history_id_for_record(r) in allowed]
        return query.page(visible,params,actor='alice',source='history',revision=query.file_revision(source))
    first=fetch(params);assert [r['timestamp'] for r in first['items']]==[30,29,28,27]
    rows.insert(0,{'timestamp':31,'images':['/output/new.png'],'type':'online'})
    allowed.add(history_id_for_record(rows[0]))
    second=fetch({**params,'cursor':first['next_cursor']})
    assert [r['timestamp'] for r in second['items']]==[26,25,24,23]
    # Delete the anchor and revoke an older row: neither is restored by cursor.
    rows[:]=[r for r in rows if r['timestamp']!=23]
    allowed.discard(history_id_for_record(next(r for r in rows if r['timestamp']==22)))
    third=fetch({**params,'cursor':second['next_cursor']})
    assert [r['timestamp'] for r in third['items']]==[21,20,19,18]
    with pytest.raises(query.QueryError) as exc:fetch({**params,'q':'changed','cursor':third['next_cursor']})
    assert exc.value.status==400
    with pytest.raises(query.QueryError):fetch({'page_size':4,'type':'online','cursor':third['next_cursor']})
