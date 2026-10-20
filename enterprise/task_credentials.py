"""Bind existing durable tasks to one call source; never select a fallback key.

Only metadata goes in the existing receipt. DPAPI plaintext is scoped to one
async execution/query context and is not saved in payloads, logs or histories.
"""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import logging
import sqlite3

from fastapi import HTTPException
from pydantic import BaseModel, Field

from enterprise import db
from enterprise.department_governance import DepartmentGovernance, GovernanceError
from enterprise.department_costs import DepartmentCosts
from enterprise.canvas_image_recovery import provider_scope
from enterprise.providers.zhenzhen import is_zhenzhen
from enterprise.runtime.logging import redact_text

_binding = ContextVar('task_credential_binding', default=None)


class CallSourceSelection(BaseModel):
    call_source_id: str | None = Field(default=None, max_length=200)
    business_project_id: str | None = Field(default=None, max_length=200)


def prepare_task_binding(service, record, selection, user_id, provider):
    explicit = bool(selection.get('call_source_id') or selection.get('business_project_id'))
    if not user_id:
        if explicit:
            raise HTTPException(401, '调用来源需要登录')
        return None
    conn = service.connect()
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='credential_sources'").fetchone():
            if explicit:
                raise HTTPException(503, '调用来源尚未启用，请先完成受控版本升级')
            return None  # Old-schema generation keeps its existing behavior.
        configured = conn.execute('SELECT 1 FROM credential_sources WHERE provider_id=?', (provider['id'],)).fetchone()
    finally:
        conn.close()
    if not configured and not explicit:
        return None  # Existing global settings are adopted only by an administrator.
    if not is_zhenzhen(provider):
        raise HTTPException(400, '当前来源接线仅支持已验证的贞贞HTTP协议')
    safe_provider = provider_scope(provider)
    actor = db.get_user_by_id(user_id)
    if not actor:
        raise HTTPException(403, '任务身份不可用')
    try:
        snapshot = service.accept_context({'user_id':user_id,'auth_version':actor['auth_version']},
            task_id=record['id'], provider_id=provider['id'], model=record['model'],
            source_id=selection.get('call_source_id'), project_id=selection.get('business_project_id'))
        return {'snapshot':snapshot, 'provider':safe_provider}
    except GovernanceError as exc:
        raise HTTPException(exc.status_code, {'code':exc.code}) from None


@contextmanager
def credential_scope(record, *, service=None):
    binding = record.get('billing_context')
    if not binding:
        yield
        return
    service = service or DepartmentGovernance()
    conn = service.connect()
    try:
        row = conn.execute('SELECT snapshot_json FROM generation_billing_context WHERE task_id=?', (record['id'],)).fetchone()
        import json
        if not row or json.loads(row[0]) != binding['snapshot']:
            raise HTTPException(409, '原任务调用身份不可确认；未改用其他来源')
    finally:
        conn.close()
    try:
        secret = service.bound_secret(record['id'])
    except GovernanceError as exc:
        raise HTTPException(exc.status_code, {'code':exc.code}) from None
    token = _binding.set({'provider':binding['provider'], 'secret':secret})
    try:
        yield
    finally:
        _binding.reset(token)


def scoped_api_key(provider):
    binding = _binding.get()
    if binding is None:
        return None
    if provider_scope(provider) != binding['provider']:
        raise HTTPException(409, '供应商地址或协议已改变；未向新地址发送原凭据')
    return binding['secret']


def credential_bound():
    return _binding.get() is not None


def task_error(value):
    text = str(value)
    current = _binding.get()
    if current:
        text = text.replace(current['secret'], '[REDACTED]')
    return redact_text(text)


def require_bound_generation(provider):
    if credential_bound() or not is_zhenzhen(provider):
        return
    conn = db.get_db()
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='credential_sources'").fetchone():
            if conn.execute('SELECT 1 FROM credential_sources WHERE provider_id=?', (provider['id'],)).fetchone():
                raise HTTPException(409, '此供应商已启用调用来源，请从持久任务入口发起；未改用全局密钥')
    finally:
        conn.close()


def validate_pending_binding(service, record):
    binding = record.get('billing_context')
    if not binding:
        return True
    snapshot = binding['snapshot']
    actor = db.get_user_by_id(record['enterprise_user_id'])
    if not actor:
        return False
    principal = {'user_id':actor['id'],'auth_version':actor['auth_version']}
    sources = service.sources(principal)
    source = next((s for s in sources if s['id'] == snapshot['source_id']), None)
    with service.session(principal) as (conn, current):
        from enterprise.department_governance import _member
        member = _member(conn, current['id'])
        department = member['department_id'] if member else None
        if snapshot['project_id']:
            project = conn.execute('SELECT * FROM business_projects WHERE id=?', (snapshot['project_id'],)).fetchone()
            if not service._project_access(conn, current, project, write=True):
                return False
    return bool(source and source['current_revision'] == snapshot['revision_id'] and department == snapshot['department_id'])


def project_task_costs(service, record):
    if not record.get('billing_context'):
        return
    costs = DepartmentCosts(service)
    for receipt in record.get('provider_receipts') or []:
        # A journal receipt, not local success/failure, supplies the actual fact.
        usage = receipt.get('reported_usage') or {}
        amount, currency = usage.get('reported_cost'), usage.get('currency')
        if amount is not None and currency:
            costs.record_fact(record['id'], receipt['index'], 'supplier-charge', kind='charge',
                              amount=str(amount), unit=currency, receipt_ref=receipt.get('upstream_task_id',''))
        elif receipt.get('state') not in {'started', 'submitting'}:
            costs.record_fact(record['id'], receipt['index'], 'supplier-cost-unknown', kind='unknown')


def project_record_costs(record):
    if not record.get('billing_context'):
        return
    try:
        project_task_costs(DepartmentGovernance(), record)
    except (GovernanceError, sqlite3.Error, OSError, ValueError):
        logging.getLogger(__name__).warning('Task cost projection pending reconciliation')


def refresh_cost_projection(service, principal, scope, department_id, journal):
    """Replay existing receipts on report reads; no new queue or paid request.

    The same permission predicate as the report bounds the source records. An
    unavailable receipt is left unknown by the ledger summary.
    """
    costs = DepartmentCosts(service)
    with service.session(principal) as (conn, actor):
        where, params = costs._filter(conn, actor, scope, department_id)
        task_ids = [row[0] for row in conn.execute('SELECT c.task_id FROM generation_billing_context c WHERE '+where+
            " AND (NOT EXISTS (SELECT 1 FROM generation_cost_entries e WHERE e.task_id=c.task_id AND e.kind='charge')"
            " OR EXISTS (SELECT 1 FROM generation_cost_entries u WHERE u.task_id=c.task_id AND u.kind='unknown'"
            " AND NOT EXISTS (SELECT 1 FROM generation_cost_entries p WHERE p.task_id=u.task_id"
            " AND p.attempt_index=u.attempt_index AND p.kind='charge')))", params)]
    for task_id in task_ids:
        try:
            record = journal.get(task_id)
            if record and record.get('billing_context'):
                project_task_costs(service, record)
        except (GovernanceError, sqlite3.Error, OSError, ValueError):
            logging.getLogger(__name__).warning('Task cost projection pending reconciliation')


def bound_runner(journal, runner, *, service=None):
    service = service or DepartmentGovernance()
    async def run(task_id, payload):
        record = await asyncio.to_thread(journal.get, task_id)
        try:
            if not await asyncio.to_thread(validate_pending_binding, service, record):
                raise HTTPException(403, '原调用来源权限已改变，未提交生成')
            with credential_scope(record, service=service):
                return await runner(task_id, payload)
        except (HTTPException, GovernanceError, sqlite3.Error, OSError, ValueError, KeyError):
            if await asyncio.to_thread(journal.mark_running, task_id):
                await asyncio.to_thread(journal.finish, task_id, {'status':'failed',
                    'error':'原调用身份不可用；没有生成或切换来源', 'recovery_required':False})
        finally:
            try:
                await asyncio.to_thread(project_task_costs, service, await asyncio.to_thread(journal.get, task_id))
            except (GovernanceError, sqlite3.Error, OSError, ValueError):
                # Receipt remains durable for reconciliation; never replay a paid request.
                logging.getLogger(__name__).warning('Task cost projection pending reconciliation')
    return run
