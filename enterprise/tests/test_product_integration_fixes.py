"""Focused admin integration and actual plugin/form scripts; disposable SQLite only."""
import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from enterprise import admin_api, db as edb
from enterprise.tests.test_sec_1c0_super_admin_protection import (
    FakeRequest, _add_ready_user, _apply_audit, _principal,
)


@pytest.fixture
def users(tmp_path, monkeypatch):
    database = tmp_path / 'enterprise.db'
    monkeypatch.setattr(edb, 'DB_PATH', str(database))
    edb.init_db()
    super_user = _add_ready_user(database, username='fixture-super', role='super_admin')
    admin = _add_ready_user(database, username='fixture-admin', role='admin')
    member = _add_ready_user(database, username='fixture-member', role='user')
    _apply_audit(database, super_user['id'])
    return super_user, admin, member


def principal(user):
    return _principal(edb.get_user_by_id_any_status(user['id']))


def test_admin_creation_old_form_fails_and_current_confirmation_succeeds(users):
    super_user, admin, _ = users
    old_body = {'username':'new-admin', 'password':'fixture-password', 'is_admin':True}
    with pytest.raises(HTTPException) as old:
        asyncio.run(admin_api.create_user(FakeRequest(principal(super_user), old_body)))
    assert old.value.status_code == 403  # 10.1 form omitted super-admin password confirmation.
    body = {**old_body, 'role':'admin', 'current_password':super_user['password'], 'reason':'delegate operations'}
    response = asyncio.run(admin_api.create_user(FakeRequest(principal(super_user), body)))
    assert response.status_code == 201
    assert json.loads(response.body)['user']['role'] == 'admin'
    with pytest.raises(HTTPException) as ordinary_admin:
        asyncio.run(admin_api.create_user(FakeRequest(principal(admin), {**body,'username':'denied-admin'})))
    assert ordinary_admin.value.status_code == 403


def test_member_operations_require_reason_and_preserve_owned_data(users):
    _, admin, member = users
    with pytest.raises(HTTPException) as old:
        asyncio.run(admin_api.delete_user(member['id'], FakeRequest(principal(admin), {'confirm_username':member['username'], 'reason':''})))
    assert old.value.status_code == 400
    edb.set_canvas_owner('retained-fixture-canvas', member['id'])
    asyncio.run(admin_api.reset_password(member['id'], FakeRequest(principal(admin), {'password':'replacement-fixture-password','reason':'reset fixture'})))
    disabled = asyncio.run(admin_api.update_user_active(member['id'], FakeRequest(principal(admin), {'is_active':False,'reason':'disable fixture'})))
    assert disabled['is_active'] is False
    enabled = asyncio.run(admin_api.update_user_active(member['id'], FakeRequest(principal(admin), {'is_active':True,'reason':'enable fixture'})))
    assert enabled['is_active'] is True
    deleted = asyncio.run(admin_api.delete_user(member['id'], FakeRequest(principal(admin), {'confirm_username':member['username'],'reason':'offboard fixture'})))
    assert deleted['soft_deleted'] is True
    assert edb.get_user_by_id_any_status(member['id'])['is_active'] is False
    assert edb.get_canvas_owner('retained-fixture-canvas') == member['id']


@pytest.mark.parametrize('name', ['test_admin_operation_forms.js', 'test_chrome_platform_client.js'])
def test_actual_frontend_scripts(name):
    subprocess.run(['node', str(Path(__file__).with_name(name))], check=True)
