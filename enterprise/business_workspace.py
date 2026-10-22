"""Department task metadata; public project sharing never grants this access."""
import json

from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.config import PATH_ROOTS
from enterprise.department_costs import DepartmentCosts
from enterprise.department_governance import identifier
from enterprise.generation_tasks import describe_task


def task_summaries(service, principal, *, scope='me', department_id=None, before=None, journal=None):
    journal = journal or CanvasTaskJournal(PATH_ROOTS.DATA_ROOT / 'canvas-tasks')
    if before is not None:
        before = identifier(before)
    with service.session(principal) as (conn, actor):
        where, params = DepartmentCosts(service)._filter(conn, actor, scope, department_id)
        rows = conn.execute('SELECT c.task_id,c.snapshot_json FROM generation_billing_context c WHERE '+where+
            (' AND c.rowid<(SELECT rowid FROM generation_billing_context WHERE task_id=?)' if before else '')+
            ' ORDER BY c.rowid DESC LIMIT 51', (*params,*([before] if before else []))).fetchall()
    result=[]
    for row in rows[:50]:
        try:
            record=journal.get(row[0])
        except (OSError, ValueError):
            # One broken private receipt must not hide all other department
            # tasks. Its authorized billing snapshot remains the only metadata.
            result.append({'id':row[0], 'status':'unavailable',
                'model':json.loads(row[1])['model'], 'context':json.loads(row[1]),
                'error':'任务回执暂不可读，请保留原记录；没有重新生成'})
            continue
        # Context rows committed before journal acceptance are not executable tasks.
        if record and record.get('enterprise_user_id') == json.loads(row[1])['user_id']:
            result.append({**describe_task(record), 'context':json.loads(row[1])})
    return {'tasks':result,'next_cursor':rows[49][0] if len(rows)>50 else None}
