"""Append-only supplier facts, permission-filtered summaries and advisory budgets.

No submission, balance inference, currency conversion or budget enforcement.
Supplier adapters call record_fact; there is no public endpoint to invent costs.
"""
from decimal import Decimal, InvalidOperation, localcontext
import json
import re
import sqlite3
import time
import uuid

from enterprise.department_governance import GovernanceError, _audit, _company, _manages, _member, _require, identifier, label


def money(value):
    if type(value) not in {str, int, Decimal} or len(str(value)) > 80:
        raise GovernanceError('INVALID_COST_AMOUNT')
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount.copy_abs() >= Decimal('1e18') or amount.as_tuple().exponent < -12:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise GovernanceError('INVALID_COST_AMOUNT') from None
    return format(amount, 'f')


def _add_money(left, right):
    # The input contract permits 18 integer and 12 fractional digits. Python's
    # default 28-digit context would silently round valid ledger facts.
    with localcontext() as context:
        context.prec = 64
        return left + right


def unit_code(value):
    if value != 'platform_units' and (not isinstance(value, str) or not re.fullmatch('[A-Z]{3}', value)):
        raise GovernanceError('INVALID_COST_UNIT')
    return value


class DepartmentCosts:
    def __init__(self, governance):
        self.governance = governance

    def record_fact(self, task_id, attempt_index, event_id, *, kind, amount=None, unit=None, receipt_ref=''):
        """Internal trusted adapter boundary. Replaying a receipt never adds cost.

        A changed fact under the same event ID is a conflict, not a silent
        overwrite. Refund/correction uses a new supplier event ID.
        """
        task_id, event_id = identifier(task_id), identifier(event_id)
        if type(attempt_index) is not int or attempt_index < 0 or attempt_index > 10000:
            raise GovernanceError('INVALID_ATTEMPT_INDEX')
        if kind not in {'estimate', 'charge', 'refund', 'adjustment', 'unknown'}:
            raise GovernanceError('INVALID_COST_KIND')
        if kind == 'unknown':
            if amount is not None or unit is not None:
                raise GovernanceError('UNKNOWN_COST_MUST_NOT_INFER_AMOUNT')
        else:
            amount, unit = money(amount), unit_code(unit)
            if kind != 'adjustment' and Decimal(amount) < 0:
                raise GovernanceError('INVALID_COST_AMOUNT')
        if receipt_ref:
            receipt_ref = identifier(receipt_ref)  # Receipt identity, never raw response/token/URL.
        conn = self.governance.connect()
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('BEGIN IMMEDIATE')
            _require(conn.execute('SELECT 1 FROM generation_billing_context WHERE task_id=?', (task_id,)).fetchone(),
                     'TASK_BILLING_CONTEXT_REQUIRED', 409)
            old = conn.execute('SELECT * FROM generation_cost_entries WHERE task_id=? AND attempt_index=? AND event_id=?',
                               (task_id, attempt_index, event_id)).fetchone()
            values = (kind, amount, unit, receipt_ref)
            if old:
                _require(tuple(old[k] for k in ('kind', 'amount', 'unit', 'receipt_ref')) == values,
                         'COST_RECEIPT_CONFLICT', 409)
                conn.commit()
                return old['id']
            entry_id = uuid.uuid4().hex
            conn.execute('INSERT INTO generation_cost_entries VALUES (?,?,?,?,?,?,?,?,?)',
                (entry_id, task_id, attempt_index, event_id, *values, int(time.time())))
            conn.commit()
            return entry_id
        except sqlite3.Error as exc:
            conn.rollback()
            raise GovernanceError('COST_STORAGE_UNAVAILABLE', 503) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _filter(self, conn, actor, scope, department_id):
        if scope == 'me':
            return 'c.user_id=?', [actor['id']]
        if scope == 'company':
            _require(_company(actor))
            return '1=1', []
        if scope == 'department':
            member = _member(conn, actor['id'])
            department_id = department_id or (member['department_id'] if member else None)
            _require(department_id and _manages(conn, actor, department_id))
            return 'c.department_id=?', [department_id]
        raise GovernanceError('INVALID_COST_VIEW')

    def entries(self, principal, *, scope='me', department_id=None, before=None, limit=50):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise GovernanceError('INVALID_PAGE_LIMIT')
        if before is not None:
            before = identifier(before)
        with self.governance.session(principal) as (conn, actor):
            where, params = self._filter(conn, actor, scope, department_id)
            rows = conn.execute('SELECT e.*,c.snapshot_json FROM generation_cost_entries e '
                'JOIN generation_billing_context c ON c.task_id=e.task_id WHERE ' + where +
                (' AND e.rowid<(SELECT rowid FROM generation_cost_entries WHERE id=?)' if before else '') +
                ' ORDER BY e.rowid DESC LIMIT ?',
                (*params, *([before] if before else []), limit + 1)).fetchall()
            result = [{**{k:r[k] for k in r.keys() if k != 'snapshot_json'}, 'context':json.loads(r['snapshot_json'])}
                      for r in rows[:limit]]
            return {'entries':result, 'next_cursor':rows[limit-1]['id'] if len(rows) > limit else None}

    def summary(self, principal, *, scope='me', department_id=None, starts_at=0, ends_at=None):
        ends_at = int(time.time()) + 1 if ends_at is None else ends_at
        if type(starts_at) is not int or type(ends_at) is not int or starts_at < 0 or ends_at <= starts_at:
            raise GovernanceError('INVALID_COST_PERIOD')
        with self.governance.session(principal) as (conn, actor):
            where, params = self._filter(conn, actor, scope, department_id)
            rows = conn.execute('SELECT e.*,c.snapshot_json FROM generation_cost_entries e '
                'JOIN generation_billing_context c ON c.task_id=e.task_id WHERE ' + where +
                ' AND e.created_at>=? AND e.created_at<?', (*params, starts_at, ends_at))
            groups = {}
            # A missing projection is unknown, not zero expenditure. Keep it
            # visible even if a process stopped after saving its task receipt.
            contexts = conn.execute('SELECT c.task_id,c.snapshot_json FROM generation_billing_context c WHERE ' + where +
                ' AND c.created_at>=? AND c.created_at<?', (*params, starts_at, ends_at))
            pending = {(row[0],index) for row in contexts
                       for index in range(json.loads(row[1]).get('expected_attempts',1))}
            resolved = set()
            for row in rows:
                context = json.loads(row['snapshot_json'])
                task_attempt = (row['task_id'], row['attempt_index'])
                if row['kind'] == 'unknown':
                    pending.add(task_attempt)
                    continue
                key = (context['department_id'], context['project_id'], context['user_id'], context['provider_id'],
                       context['model'], context['scope'], context['procurement'], context['account_ref'], row['unit'])
                if key not in groups:
                    groups[key] = {'department_id':key[0], 'project_id':key[1], 'user_id':key[2],
                        'provider_id':key[3], 'model':key[4], 'scope':key[5], 'procurement':key[6],
                        'account_ref':key[7], 'unit':key[8], 'estimated':Decimal(0), 'actual':Decimal(0)}
                amount = Decimal(row['amount'])
                if row['kind'] == 'estimate':
                    groups[key]['estimated'] = _add_money(groups[key]['estimated'], amount)
                else:
                    groups[key]['actual'] = _add_money(groups[key]['actual'],
                        amount.copy_negate() if row['kind'] == 'refund' else amount)
                    if row['kind'] == 'charge':
                        resolved.add(task_attempt)
            result = [{**group, 'actual':str(group['actual']), 'estimated':str(group['estimated'])}
                      for group in groups.values()]
            return {'groups':result, 'pending_reconciliation':len(pending-resolved), 'budget_enforced':False}

    def set_budget(self, principal, department_id, period, starts_at, ends_at, unit, amount):
        department_id, period, unit, amount = identifier(department_id), label(period), unit_code(unit), money(amount)
        if (type(starts_at) is not int or type(ends_at) is not int or starts_at < 0
                or ends_at <= starts_at or Decimal(amount) < 0):
            raise GovernanceError('INVALID_BUDGET')
        with self.governance.session(principal, write=True) as (conn, actor):
            _require(_manages(conn, actor, department_id))
            conn.execute('INSERT INTO department_budgets VALUES (?,?,?,?,?,?) '
                'ON CONFLICT(department_id,period,unit) DO UPDATE SET starts_at=excluded.starts_at,'
                'ends_at=excluded.ends_at,amount=excluded.amount', (department_id, period, starts_at, ends_at, unit, amount))
            _audit(conn, actor, 'department_budget_updated', department_id)

    def budgets(self, principal, department_id):
        with self.governance.session(principal) as (conn, actor):
            _require(_manages(conn, actor, department_id))
            budgets = [dict(r) for r in conn.execute('SELECT * FROM department_budgets WHERE department_id=?', (department_id,))]
        for budget in budgets:
            summary = self.summary(principal, scope='department', department_id=department_id,
                                   starts_at=budget['starts_at'], ends_at=budget['ends_at'])
            actual = Decimal(0)
            for group in summary['groups']:
                if group['unit'] == budget['unit']:
                    actual = _add_money(actual, Decimal(group['actual']))
            budget.update(actual=str(actual), exceeded=actual > Decimal(budget['amount']),
                          over_amount=str(max(Decimal(0), _add_money(actual, Decimal(budget['amount']).copy_negate()))),
                          pending_reconciliation=summary['pending_reconciliation'], blocking=False)
        return budgets

    def alerts(self, principal):
        """Current-period advisory notices for authorized department managers."""
        try:
            with self.governance.session(principal) as (conn, actor):
                departments = [dict(r) for r in conn.execute('SELECT id,name FROM departments WHERE active=1')
                               if _manages(conn, actor, r['id'])]
                user_id, company = actor['id'], _company(actor)
        except GovernanceError as exc:
            if exc.code == 'DEPARTMENT_SCHEMA_UPGRADE_REQUIRED':
                return {'enabled':False, 'alerts':[]}
            raise
        now, alerts = int(time.time()), []
        for department in departments:
            for budget in self.budgets(principal, department['id']):
                if budget['starts_at'] <= now < budget['ends_at'] and budget['exceeded']:
                    identity = [department['id'], budget['period'], budget['unit'], budget['starts_at'],
                                budget['ends_at'], budget['amount']]
                    alerts.append({**budget, 'department_id':department['id'], 'department_name':department['name'],
                                   'id':json.dumps(identity, ensure_ascii=False, separators=(',', ':'))})
        return {'enabled':True, 'user_id':user_id, 'company_admin':company, 'alerts':alerts}
