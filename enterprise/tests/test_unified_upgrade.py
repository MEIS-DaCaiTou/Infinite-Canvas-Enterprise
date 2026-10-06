"""Catalog/approval/orchestration contracts; no customer install or shared Runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from enterprise.ops.update.historical_install import read_catalog
from enterprise.ops.update.legacy_security_variant import LegacySecurityVariantError, inspect_approved_security_variant
from enterprise.ops.update.mvp import PreparedUpdate, UpdateJobStore, _database_update_plan
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, prepare_install_state_directories
from enterprise.release.current_release import CurrentRelease, SCHEMA_VERSION, atomic_write_current_release
from enterprise.tests.test_096_security_variant import _source_database, _variant_plan, _Manifest
from tools import unified_upgrade as worker
from tools.build_unified_upgrader import longest_target_suffix

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'installer/windows/historical-install-catalog.json'


def test_catalog_contains_pinned_public_sources_and_no_invented_085():
    sources = read_catalog(CATALOG)
    assert len(sources) == 10
    assert {row['version'] for row in sources.values()} == {
        '2026.08.1', '2026.08.2', '2026.08.3', '2026.08.4',
        '2026.09.4', '2026.09.5', '2026.09.6', '2026.09.7', '2026.09.8', '2026.09.9'}
    assert sources['ice-2026.09.7-9b6c09f76efa']['channel'] == 'development'
    assert len({row['database_objects_sha256'] for row in sources.values() if row['schema_version'] is None}) == 1


@pytest.mark.parametrize('change', ['duplicate', 'bad-hash', 'bad-version', 'bad-count', 'extra-top-key'])
def test_catalog_fails_closed(tmp_path, change):
    value = json.loads(CATALOG.read_bytes())
    if change == 'duplicate': value['sources'].append(value['sources'][0])
    elif change == 'bad-hash': value['sources'][0]['python_sha256'] = 'untrusted'
    elif change == 'bad-version': value['sources'][0]['version'] = 'latest'
    elif change == 'bad-count': value['sources'][0]['object_count'] = True
    else: value['allow_any_source'] = True
    path = tmp_path / 'catalog.json'; path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError, match='NATIVE_UPGRADE_CATALOG_INVALID'): read_catalog(path)


def test_approved_shape_does_not_relax_online_default_or_source_hash(tmp_path):
    kwargs, _ = _variant_plan(tmp_path)
    source_id = 'ice-2026.09.5-7609bb1b7cfa'; sha = '5' * 64
    kwargs['source_manifest'] = _Manifest(source_id, sha)
    with pytest.raises(Exception, match='SYSTEM_UPDATE_DATABASE_SOURCE_IDENTITY_MISMATCH'):
        _database_update_plan(**kwargs)
    result = _database_update_plan(**kwargs, approved_legacy_security_source=(source_id, sha))
    assert result['source_variant'] == 'legacy-security-activated-v1'
    with pytest.raises(Exception, match='SYSTEM_UPDATE_DATABASE_SOURCE_IDENTITY_MISMATCH'):
        _database_update_plan(**kwargs, approved_legacy_security_source=(source_id, '0' * 64))


def test_approved_variant_checks_definitions_not_object_count(tmp_path):
    conn, baseline = _source_database(tmp_path / 'db')
    try:
        conn.execute('DROP TRIGGER trg_security_audit_no_delete')
        conn.execute('CREATE TRIGGER trg_security_audit_no_delete BEFORE DELETE ON security_audit_events BEGIN SELECT RAISE(IGNORE); END')
        with pytest.raises(LegacySecurityVariantError, match='SOURCE_SECURITY_SCHEMA_MISMATCH'):
            inspect_approved_security_variant(conn, baseline_objects=baseline,
                source_release_id='source', source_manifest_sha256='5' * 64,
                approved_source=('source', '5' * 64))
    finally: conn.close()


def _worker_fixture(tmp_path, monkeypatch, *, already_current=False):
    catalog = read_catalog(CATALOG)
    source_id = 'ice-2026.09.9-54f9e67d1643' if already_current else 'ice-2026.09.5-7609bb1b7cfa'
    target_id = 'ice-2026.09.9-54f9e67d1643'
    roots = derive_portable_path_roots(PortableRootInputs(tmp_path / 'install', tmp_path / 'local'), source_id)
    prepare_install_state_directories(roots)
    manifest = SimpleNamespace(raw_sha256=catalog[source_id]['manifest_sha256'], release_id=source_id)
    target = SimpleNamespace(raw_sha256=catalog[target_id]['manifest_sha256'], release_id=target_id)
    atomic_write_current_release(roots, CurrentRelease(SCHEMA_VERSION, source_id, 'releases/' + source_id,
        manifest.raw_sha256, '2026-10-01T00:00:00Z', None), expected_manifest_sha256=manifest.raw_sha256)
    monkeypatch.setattr(worker, 'inspect_historical_install', lambda *a, **kw: (
        {'source_release_id': source_id, 'database_variant': 'release-exact'}, roots, manifest))
    monkeypatch.setattr(worker, 'read_release_manifest_v2', lambda _: target)
    monkeypatch.setattr(worker.sys, 'executable', str(roots.PYTHON_RUNTIME / 'python.exe'))
    monkeypatch.setattr(worker, 'install_path_roots_for_process', lambda _: None)
    store = UpdateJobStore(roots)
    class Service:
        def __init__(self, *a, **kw): pass
        def prepare_from_artifacts(self, **kw):
            job_id, _ = store.create('local-native-upgrader')
            store.write_status(job_id, 'READY', actor_user_id='local-native-upgrader', result_code='SYSTEM_UPDATE_READY')
            return PreparedUpdate(job_id, source_id, target_id, target.raw_sha256, '1' * 64, 'versioned-forward-migration')
    monkeypatch.setattr(worker, 'UpdateMvpService', Service)
    def execute(roots, job_id, **kw):
        assert store.lock_path.exists()
        lock = store.acquire_execution_lock(job_id)
        store.write_status(job_id, 'SUCCEEDED', actor_user_id='local-native-upgrader', result_code='SYSTEM_UPDATE_SUCCEEDED')
        store.release_execution_lock(lock, job_id)
        return 0
    monkeypatch.setattr(worker, 'execute_update_job', execute)
    return roots, store, dict(install_root=roots.INSTALL_ROOT, catalog_path=CATALOG,
        manifest_path=tmp_path / 'manifest', archive_path=tmp_path / 'archive', inventory_path=tmp_path / 'inventory')


def test_reservation_precedes_stop_and_is_released_by_worker(tmp_path, monkeypatch):
    _, store, args = _worker_fixture(tmp_path, monkeypatch)
    def launcher(root, command):
        assert command == 'stop' and store.lock_path.exists()
        return 0, {'result': 'stopped'}
    result = worker.run(**args, launcher=launcher, confirm_no_active_tasks=True)
    assert result['result'] == 'succeeded'
    assert not store.lock_path.exists()


def test_existing_other_reservation_never_stops_runtime(tmp_path, monkeypatch):
    _, store, args = _worker_fixture(tmp_path, monkeypatch)
    store.reserve_execution('a' * 32)
    result = worker.run(**args, confirm_no_active_tasks=True,
        launcher=lambda *a: pytest.fail('must not stop another updater'))
    assert result['code'] == 'SYSTEM_UPDATE_ALREADY_ACTIVE'
    assert json.loads(store.lock_path.read_bytes())['job_id'] == 'a' * 32
    assert store.read_status(result['job_id'])['state'] == 'FAILED'


def test_read_only_recovery_check_does_not_create_staging(tmp_path):
    roots = derive_portable_path_roots(PortableRootInputs(tmp_path / 'install', tmp_path / 'local'), 'source')
    store = UpdateJobStore(roots)
    store.assert_no_unresolved_recovery(read_only=True)
    assert not roots.INSTALL_ROOT.exists()


def test_uncertain_recovery_is_not_reported_as_safe_failure(tmp_path, monkeypatch):
    _, store, args = _worker_fixture(tmp_path, monkeypatch)
    def execute(roots, job_id, **kw):
        lock = store.acquire_execution_lock(job_id)
        store.write_status(job_id, 'RECOVERY_REQUIRED', actor_user_id='local-native-upgrader', result_code='SYSTEM_UPDATE_RECOVERY_REQUIRED')
        store.release_execution_lock(lock, job_id)
        return 2
    monkeypatch.setattr(worker, 'execute_update_job', execute)
    result = worker.run(**args, confirm_no_active_tasks=True, launcher=lambda *a: (0, {'result': 'stopped'}))
    assert result['result'] == 'recovery_required'
    assert result['terminal_state'] == 'RECOVERY_REQUIRED'


def test_failed_stop_leaves_no_owned_lock_and_checks_safe_restart(tmp_path, monkeypatch):
    _, store, args = _worker_fixture(tmp_path, monkeypatch)
    calls = []
    def launcher(root, command):
        calls.append(command)
        return (2, {}) if len(calls) == 1 else (0, {'result': 'stopped'} if command == 'stop' else {})
    result = worker.run(**args, launcher=launcher, confirm_no_active_tasks=True)
    assert result['code'] == 'NATIVE_UPGRADE_CONTROLLED_STOP_FAILED'
    assert result['source_recovery'] == 'healthy'
    assert calls == ['stop', 'stop', 'start', 'health']
    assert not store.lock_path.exists()
    assert store.read_status(result['job_id'])['state'] == 'FAILED'


def test_service_recovery_never_prepares_migrates_or_changes_pointer(tmp_path, monkeypatch):
    roots, store, args = _worker_fixture(tmp_path, monkeypatch)
    before = (roots.STATE_ROOT / 'current-release.json').read_bytes()
    monkeypatch.setattr(worker, 'UpdateMvpService', lambda *a, **k: pytest.fail('no upgrade preparation'))
    monkeypatch.setattr(worker, 'execute_update_job', lambda *a, **k: pytest.fail('no migration'))
    calls = []
    def launcher(root, command):
        assert store.lock_path.exists()
        calls.append(command)
        return 0, {'result': 'stopped' if command == 'stop' else 'started'}
    result = worker.run(**args, recover_service_only=True, confirm_no_active_tasks=True, launcher=launcher)
    assert result['result'] == 'service_recovered'
    assert calls == ['stop', 'start', 'health']
    assert (roots.STATE_ROOT / 'current-release.json').read_bytes() == before
    assert not store.lock_path.exists()


def test_unconfirmed_stop_never_blindly_restarts_source(tmp_path, monkeypatch):
    _, store, args = _worker_fixture(tmp_path, monkeypatch)
    def launcher(root, command):
        assert command == 'stop', 'must not start into unknown/foreign occupancy'
        return 2, {'result': 'foreign_port_occupant'}
    result = worker.run(**args, confirm_no_active_tasks=True, launcher=launcher)
    assert result['source_recovery'] == 'stop_unconfirmed'
    assert not store.lock_path.exists()


def test_inspect_and_noop_do_not_prepare_stop_or_mutate_pointer(tmp_path, monkeypatch):
    roots, _, args = _worker_fixture(tmp_path, monkeypatch, already_current=True)
    before = (roots.STATE_ROOT / 'current-release.json').read_bytes()
    launcher = lambda *a: pytest.fail('read-only/noop must not control Runtime')
    assert worker.run(**args, inspect_only=True, launcher=launcher)['result'] == 'inspected'
    assert worker.run(**args, launcher=launcher)['code'] == 'ACTIVE_TASK_DRAIN_CONFIRMATION_REQUIRED'
    assert worker.run(**args, confirm_no_active_tasks=True, launcher=launcher)['result'] == 'already_current'
    assert (roots.STATE_ROOT / 'current-release.json').read_bytes() == before


def test_target_path_budget_accounts_for_atomic_partial(tmp_path):
    import zipfile
    archive = tmp_path / 'release.zip'
    with zipfile.ZipFile(archive, 'w') as value: value.writestr('payload/python/Lib/known.py', b'x')
    assert longest_target_suffix(archive, 'payload', 'release-B') == len('releases\\.release-B.' + '0' * 32 + '.partial\\python\\Lib\\known.py')
