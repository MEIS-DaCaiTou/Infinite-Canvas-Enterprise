"""Offline department activation: real SQLite, artifacts and native object moves.

Runtime commands and Windows registration are controlled here. Actual packaged
acceptance remains separate from these small isolated fixtures.
"""
from contextlib import closing
import hashlib
import json
import shutil
import sqlite3

import pytest

from enterprise import install_upgrade as upgrade
from enterprise.migrations.versioned import inspect_schema_metadata, DataMigrationError
from enterprise.release.release_manifest_v2 import canonical_json, materialize_release_fixture
from enterprise.tests.test_department_governance import baseline
from enterprise.tests.test_department_release import snapshots
from enterprise.tests.test_install_upgrade import installed, arguments, finish, interrupted_at, protected, Interrupted
from enterprise.tests.test_ops_release_manifest_v2 import _rebind_fixture


@pytest.fixture
def department_install(installed, tmp_path, snapshots):
    f = installed
    database = f['roots'].DATA_ROOT / 'enterprise.db'
    database.unlink()  # Newly owned fixture, before any upgrade transaction.
    baseline(database)
    for area, version, destination in ((tmp_path/'source/assets', 2, f['source_assets']),
                                       (tmp_path/'target-area', 4, f['target_assets'])):
        manifest = area/'ops-release-manifest-v2.json'
        if not manifest.exists():
            manifest = next(area.glob('*manifest*.json'))
        doc = json.loads(manifest.read_bytes())
        (area/'payload/release-evidence/database-schema.json').write_bytes(canonical_json(snapshots[version]))
        doc['database_contract'].update(migration_ids=snapshots[version]['migration_ids'],
            migration_compatibility='versioned-forward-migration' if version == 4 else 'same-schema-no-migration',
            rollback_classification='database-backup-restore' if version == 4 else 'code-release-pointer')
        archive = area/doc['archive']['filename']; inventory = area/'release-payload-inventory.json'
        _rebind_fixture(manifest, archive, inventory, doc)
        for source in (manifest, archive, inventory):
            shutil.copyfile(source, destination/('ops-release-manifest-v2.json' if source == manifest else source.name))
        if version == 2:
            app = f['roots'].APP_ROOT
            assert app.is_relative_to(tmp_path/'source/installed/releases')
            shutil.rmtree(app)
            materialize_release_fixture(manifest, archive, inventory, app)
            pointer_path = f['roots'].STATE_ROOT/'current-release.json'
            pointer = json.loads(pointer_path.read_bytes())
            pointer['manifest_sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
            pointer_path.write_bytes(canonical_json(pointer))
    return f


def accounts(f):
    with closing(sqlite3.connect(f['roots'].DATA_ROOT/'enterprise.db')) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        return conn.execute('SELECT * FROM users ORDER BY id').fetchall()


@pytest.mark.parametrize('target_failure', [False, True])
def test_offline_department_activation_and_target_failure(department_install, monkeypatch, target_failure):
    f = department_install; before = accounts(f)
    media = (f['roots'].DATA_ROOT/'media.bin').read_bytes()
    original_launch = upgrade.mvp._run_launcher
    if target_failure:
        monkeypatch.setattr(upgrade.mvp, '_run_launcher', lambda app, command:
            (2, {'code':'SYSTEM_UPDATE_TARGET_HEALTH_FAILED'})
            if command == 'health' and app.name.startswith('ice-2026.07.7-') else original_launch(app, command))
    assert upgrade.inspect_upgrade(install_root=f['roots'].INSTALL_ROOT, release_dir=f['target_assets'],
        local_app_data_base=f['local'])['database_update_mode'] == 'versioned-forward-migration'
    result = upgrade.upgrade_retained(**arguments(f))
    if target_failure:
        assert result['upgrade_state'] == 'ROLLED_BACK'
        assert inspect_schema_metadata(f['roots'].DATA_ROOT/'enterprise.db')['schema_version'] == 2
        assert (f['roots'].INSTALL_ROOT/'InfiniteCanvas.exe').read_bytes() == f['old_entry'].data
    else:
        assert result['upgrade_state'] == 'AWAITING_REGISTRATION'
        assert finish(f)['upgrade_state'] == 'COMPLETE'
        assert inspect_schema_metadata(f['roots'].DATA_ROOT/'enterprise.db')['schema_version'] == 4
    assert accounts(f) == before
    assert (f['roots'].DATA_ROOT/'media.bin').read_bytes() == media
    assert not (f['roots'].STATE_ROOT/'system-update-active.lock').exists()


@pytest.mark.parametrize('phase', ['upgrade_ready', 'entry_published', 'target_health', 'awaiting_registration'])
def test_offline_migration_interruption_recovers_database_and_tools(department_install, monkeypatch, phase):
    f = department_install; before = accounts(f)
    interrupted_at(f, monkeypatch, phase)
    result = upgrade.recover_upgrade(install_root=f['roots'].INSTALL_ROOT, release_dir=f['target_assets'],
        local_app_data_base=f['local'], confirm_no_active_tasks=True)
    if phase == 'awaiting_registration':
        assert result['upgrade_state'] == 'AWAITING_REGISTRATION'
        assert finish(f)['upgrade_state'] == 'COMPLETE'
        expected = 4
    else:
        assert result['upgrade_state'] == 'ROLLED_BACK'
        expected = 2
        assert (f['roots'].INSTALL_ROOT/'InfiniteCanvas.exe').read_bytes() == f['old_entry'].data
    assert inspect_schema_metadata(f['roots'].DATA_ROOT/'enterprise.db')['schema_version'] == expected
    assert accounts(f) == before


def test_interrupted_migration_does_not_overwrite_later_business_data(department_install, monkeypatch):
    f = department_install
    interrupted_at(f, monkeypatch, 'target_health')
    with closing(sqlite3.connect(f['roots'].DATA_ROOT/'enterprise.db')) as conn:
        conn.execute("UPDATE users SET display_name='later write' WHERE id='employee'"); conn.commit()
    before = protected(f)
    with pytest.raises(DataMigrationError, match='DATA_RESTORE_EXPECTED_CURRENT_MISMATCH'):
        upgrade.recover_upgrade(install_root=f['roots'].INSTALL_ROOT, release_dir=f['target_assets'],
            local_app_data_base=f['local'], confirm_no_active_tasks=True)
    assert protected(f) == before
    assert (f['roots'].STATE_ROOT/upgrade.ACTIVE_NAME).exists()


def test_recovery_resumes_after_database_replace_without_repeating_restore(department_install, monkeypatch):
    f = department_install; before = accounts(f)
    interrupted_at(f, monkeypatch, 'target_health')
    def interrupt(phase):
        if phase == 'database_restored':
            raise Interrupted()
    monkeypatch.setattr(upgrade, '_checkpoint', interrupt)
    args = dict(install_root=f['roots'].INSTALL_ROOT, release_dir=f['target_assets'],
                local_app_data_base=f['local'], confirm_no_active_tasks=True)
    with pytest.raises(Interrupted):
        upgrade.recover_upgrade(**args)
    monkeypatch.setattr(upgrade, '_checkpoint', lambda _: None)
    assert upgrade.recover_upgrade(**args)['upgrade_state'] == 'ROLLED_BACK'
    assert accounts(f) == before
    assert inspect_schema_metadata(f['roots'].DATA_ROOT/'enterprise.db')['schema_version'] == 2


def test_migrated_installation_waits_for_windows_registration(department_install):
    f = department_install
    assert upgrade.upgrade_retained(**arguments(f))['upgrade_state'] == 'AWAITING_REGISTRATION'
    def unregistered(*_):
        raise RuntimeError('controlled-registration-incomplete')
    with pytest.raises(RuntimeError, match='registration-incomplete'):
        upgrade.finish_upgrade(install_root=f['roots'].INSTALL_ROOT, release_dir=f['target_assets'],
            local_app_data_base=f['local'], verify_registration=unregistered)
    assert (f['roots'].STATE_ROOT/upgrade.ACTIVE_NAME).exists()
    assert inspect_schema_metadata(f['roots'].DATA_ROOT/'enterprise.db')['schema_version'] == 4
    assert finish(f)['upgrade_state'] == 'COMPLETE'
