"""Opt-in accurate public-archive matrix; shared Supervisor is NOT invoked.

Each case runs the new worker with that source's bundled Python. Lifecycle
callbacks are fixtures, not claims of an independent Windows-device reboot.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import uuid
from contextlib import closing
from pathlib import Path

import pytest

from enterprise.migrations.sec_1b2_activation import ensure_bootstrap_lifecycle_schema_in_transaction
from enterprise.migrations.versioned import inspect_schema_metadata, schema_objects
from enterprise.ops.update.historical_install import read_catalog
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, prepare_install_state_directories
from enterprise.release.current_release import CurrentRelease, SCHEMA_VERSION, atomic_write_current_release
from enterprise.release.release_manifest_v2 import materialize_release_fixture, read_release_manifest_v2
from enterprise.security_audit import ensure_security_audit_schema_in_transaction
from enterprise.tests.test_customer_095_bridge_candidate import _assert_target_serves_http

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / 'installer/windows/historical-install-catalog.json'
CATALOG = read_catalog(CATALOG_PATH)
LEGACY = [row for row in CATALOG.values() if row['schema_version'] is None]
TARGET_ID = 'ice-2026.09.9-54f9e67d1643'


@pytest.fixture(scope='module')
def assets():
    value = os.environ.get('ICE_HISTORICAL_ASSETS')
    if not value: pytest.skip('Set ICE_HISTORICAL_ASSETS to verified public assets for installed-copy matrix')
    return Path(value).resolve()


@pytest.fixture(scope='module')
def materialized_sources(assets, tmp_path_factory):
    # Accurate source copies are shared read-only; each drill gets its own data.
    folder = tmp_path_factory.getbasetemp() / 'sources'; folder.mkdir()
    result = {}
    for record in LEGACY:
        source_assets = assets / record['version']; target = folder / record['version']
        materialize_release_fixture(source_assets / 'ops-release-manifest-v2.json',
            source_assets / record['archive_filename'], source_assets / 'release-payload-inventory.json', target)
        result[record['release_id']] = target
    return result


def installation(base: Path, source: Path, *, security: bool):
    source_manifest = read_release_manifest_v2(source / 'release-manifest.json')
    install = base / ('i-' + uuid.uuid4().hex[:6])
    local = base / ('l-' + uuid.uuid4().hex[:6])
    roots = derive_portable_path_roots(PortableRootInputs(install, local), source_manifest.release_id)
    prepare_install_state_directories(roots)
    shutil.copytree(source, roots.APP_ROOT)
    atomic_write_current_release(roots, CurrentRelease(SCHEMA_VERSION, source_manifest.release_id,
        'releases/' + source_manifest.release_id, source_manifest.raw_sha256, '2026-10-01T00:00:00Z', None),
        expected_manifest_sha256=source_manifest.raw_sha256)
    evidence = json.loads((source / source_manifest.section('database_contract')['schema_snapshot_path']).read_bytes())
    database = roots.DATA_ROOT / 'enterprise.db'
    roots.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as conn:
        for kind in ('table', 'index', 'trigger', 'view'):
            for item in evidence['objects']:
                if item['type'] == kind: conn.execute(item['sql'])
        conn.execute("INSERT INTO users (id,username,password_hash,display_name,is_admin,role,created_at) VALUES ('u','fixture','hash','Fixture',1,'admin',1)")
        conn.execute("INSERT INTO user_canvas_map (user_id,canvas_id,created_at) VALUES ('u','canvas-1',1)")
        if security:
            ensure_security_audit_schema_in_transaction(conn)
            ensure_bootstrap_lifecycle_schema_in_transaction(conn)
            conn.execute("INSERT INTO security_governance_bootstrap VALUES (1,1000,'u','u','op','local',1000)")
            conn.execute("INSERT INTO security_audit_events (event_id,operation_id,action,risk_level,result,actor_type,context_json,created_at) VALUES ('event','op','security.super_admin.bootstrap','L3','success','local_operator','{}',1000)")
        conn.commit()
        assert len(schema_objects(conn)) == (28 if security else 18)
    roots.CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    roots.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    (roots.CONFIG_ROOT / 'enterprise.env').write_text('ENTERPRISE_ENV=development\nJWT_SECRET=' + 'a' * 64 + '\n', encoding='utf-8')
    (roots.DATA_ROOT / 'canvas.json').write_bytes(b'{"canvas-1":{"nodes":["preserved"]}}\n')
    (roots.UPLOAD_ROOT / 'asset.bin').write_bytes(b'preserved-media-fixture')
    return roots


SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tools import unified_upgrade as worker
from enterprise.ops.update import mvp
from enterprise.migrations import versioned
from enterprise.ops.update.mvp import UpdateJobStore
from enterprise.release.current_release import read_current_release_result_from_state_root
repo, install, local, catalog, target_assets = map(Path, sys.argv[1:6])
source_id, failure = sys.argv[6:8]
calls = []
def launcher(root, command):
    calls.append([root.name, command])
    if failure == 'target_start' and root.name != source_id and command == 'start': return 2, {'code':'DRILL_TARGET_START_FAILED'}
    return 0, {'result':'stopped' if command == 'stop' else 'fixture-only-no-process'}
if failure == 'migration':
    original = versioned._apply_steps_in_transaction
    def fail(conn, steps):
        original(conn, steps)
        raise RuntimeError('DRILL_MIGRATION_FAILURE_BEFORE_COMMIT')
    versioned._apply_steps_in_transaction = fail
manifest = target_assets / 'ops-release-manifest-v2.json'
target = worker.read_release_manifest_v2(manifest)
result = worker.run(install_root=install, local_app_data_base=local, catalog_path=catalog,
    manifest_path=manifest, inventory_path=target_assets / 'release-payload-inventory.json',
    archive_path=target_assets / target.section('archive')['filename'], confirm_no_active_tasks=True, launcher=launcher)
current = read_current_release_result_from_state_root(install / 'state')
result['current'] = current.release.release_id
result['calls'] = calls
print(json.dumps(result, ensure_ascii=False))
'''


@pytest.mark.parametrize('record', LEGACY, ids=lambda row: row['version'])
@pytest.mark.parametrize('security', [False, True], ids=['18-objects', '28-objects'])
@pytest.mark.parametrize('failure', ['none', 'target_start'])
def test_exact_source_upgrade_and_start_failure_rollback(record, security, failure, assets, materialized_sources, tmp_path_factory):
    _drill(record, security, failure, assets, materialized_sources, tmp_path_factory)


@pytest.mark.parametrize('security', [False, True], ids=['18-objects', '28-objects'])
def test_095_migration_failure_restores_old_identity(security, assets, materialized_sources, tmp_path_factory):
    _drill(CATALOG['ice-2026.09.5-7609bb1b7cfa'], security, 'migration', assets, materialized_sources, tmp_path_factory)


def _drill(record, security, failure, assets, materialized_sources, tmp_path_factory):
    roots = installation(tmp_path_factory.getbasetemp(), materialized_sources[record['release_id']], security=security)
    database = roots.DATA_ROOT / 'enterprise.db'
    db_before = hashlib.sha256(database.read_bytes()).hexdigest()
    pointer_before = (roots.STATE_ROOT / 'current-release.json').read_bytes()
    completed = subprocess.run([str(roots.PYTHON_RUNTIME / 'python.exe'), '-I', '-B', '-c', SCRIPT,
        str(ROOT), str(roots.INSTALL_ROOT), str(roots.CACHE_ROOT.parents[1]), str(CATALOG_PATH),
        str(assets / '2026.09.9'), record['release_id'], failure], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
    assert completed.returncode == 0, completed.stderr[-2500:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    success = failure == 'none'
    assert result['result'] == ('succeeded' if success else 'failed_safe'), result
    assert result['terminal_state'] == ('SUCCEEDED' if success else 'ROLLED_BACK' if failure == 'target_start' else 'FAILED'), result
    assert result['current'] == (TARGET_ID if success else record['release_id'])
    assert result['calls'][0] == [record['release_id'], 'stop']
    assert (roots.DATA_ROOT / 'canvas.json').read_bytes() == b'{"canvas-1":{"nodes":["preserved"]}}\n'
    assert (roots.UPLOAD_ROOT / 'asset.bin').read_bytes() == b'preserved-media-fixture'
    assert (roots.CONFIG_ROOT / 'enterprise.env').read_text(encoding='utf-8').startswith('ENTERPRISE_ENV=development')
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert conn.execute('SELECT canvas_id FROM user_canvas_map WHERE user_id="u"').fetchone() == ('canvas-1',)
        assert len(schema_objects(conn)) == (30 if success else 28 if security else 18)
        if security:
            assert conn.execute('SELECT count(*) FROM security_audit_events').fetchone() == (1,)
            assert conn.execute('SELECT count(*) FROM security_governance_bootstrap').fetchone() == (1,)
    store = __import__('enterprise.ops.update.mvp', fromlist=['UpdateJobStore']).UpdateJobStore(roots)
    assert not store.lock_path.exists()
    assert (roots.BACKUP_ROOT / 'system-update').is_dir()
    if not success:
        after = json.loads((roots.STATE_ROOT / 'current-release.json').read_bytes())
        before = json.loads(pointer_before)
        # A code rollback intentionally records a new activation timestamp and
        # previous Release. The active source identity, not that history, must
        # be identical; pre-switch migration failure keeps the original bytes.
        for field in ('schema_version', 'release_id', 'app_root_relative', 'manifest_sha256'):
            assert after[field] == before[field]
        if failure == 'migration':
            assert (roots.STATE_ROOT / 'current-release.json').read_bytes() == pointer_before
        assert hashlib.sha256(database.read_bytes()).hexdigest() == db_before
    elif record['version'] == '2026.09.5':
        assert inspect_schema_metadata(database)['schema_version'] == 2
        _assert_target_serves_http(roots.RELEASE_ROOT / TARGET_ID, roots.INSTALL_ROOT, roots.CACHE_ROOT.parents[1])


@pytest.fixture(scope='module')
def native_build():
    value = os.environ.get('ICE_NATIVE_BUILD_ROOT')
    if os.name != 'nt' or not value: pytest.skip('Set ICE_NATIVE_BUILD_ROOT to compiled native binaries')
    return Path(value).resolve()


def _native(exe, roots, arguments, output):
    completed = subprocess.run([str(exe), *arguments, '--install-root', str(roots.INSTALL_ROOT),
        '--result-file', str(output)], capture_output=True, timeout=120)
    assert output.is_file(), 'native result file missing'
    return completed.returncode, json.loads(output.read_bytes())


@pytest.mark.parametrize('security', [False, True], ids=['18-objects', '28-objects'])
def test_native_inspector_is_read_only_and_cleans_its_bundle(security, assets, materialized_sources, tmp_path_factory, native_build):
    roots = installation(tmp_path_factory.getbasetemp(), materialized_sources['ice-2026.09.5-7609bb1b7cfa'], security=security)
    database = roots.DATA_ROOT / 'enterprise.db'
    before_db = hashlib.sha256(database.read_bytes()).hexdigest()
    before_pointer = (roots.STATE_ROOT / 'current-release.json').read_bytes()
    assert not roots.STAGING_ROOT.exists()
    product_temp = Path(os.environ['TEMP']) / 'ICE/U'
    temp_before = set(product_temp.iterdir()) if product_temp.exists() else set()
    code, result = _native(native_build / 'Infinite-Canvas-Enterprise-Unified-Upgrader-x64.exe', roots,
        ['--inspect'], roots.INSTALL_ROOT / 'inspect-result.json')
    assert code == 0 and result['result'] == 'inspected', result
    assert result['database_variant'] == ('legacy-security-activated' if security else 'release-exact')
    assert result['source_version'] == '2026.09.5'
    assert (roots.STATE_ROOT / 'current-release.json').read_bytes() == before_pointer
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before_db
    assert not (roots.STAGING_ROOT / 'system-update').exists()
    assert not (roots.INSTALL_ROOT / 'InfiniteCanvas.exe').exists()
    assert not roots.STAGING_ROOT.exists()
    assert set(product_temp.iterdir()) == temp_before


@pytest.mark.parametrize('change', ['confirmation', 'python', 'extra-module', 'schema', 'pointer'])
def test_native_blocks_unsupported_state_before_runtime_or_data_change(change, assets, materialized_sources, tmp_path_factory, native_build):
    roots = installation(tmp_path_factory.getbasetemp(), materialized_sources['ice-2026.09.5-7609bb1b7cfa'], security=False)
    if change == 'python': (roots.PYTHON_RUNTIME / 'python.exe').write_bytes(b'must-never-execute')
    elif change == 'extra-module': (roots.APP_ROOT / 'enterprise/unapproved.py').write_bytes(b'raise RuntimeError("must-never-import")\n')
    elif change == 'schema':
        with closing(sqlite3.connect(roots.DATA_ROOT / 'enterprise.db')) as conn:
            conn.execute('CREATE TABLE unknown (value TEXT)'); conn.commit()
    elif change == 'pointer':
        pointer = roots.STATE_ROOT / 'current-release.json'
        doc = json.loads(pointer.read_bytes()); doc['manifest_sha256'] = '0' * 64
        pointer.write_text(json.dumps(doc), encoding='utf-8')
    before = (roots.DATA_ROOT / 'enterprise.db').read_bytes()
    command = ['--upgrade'] if change == 'confirmation' else ['--inspect']
    code, result = _native(native_build / 'Infinite-Canvas-Enterprise-Unified-Upgrader-x64.exe', roots,
        command, roots.INSTALL_ROOT / 'blocked-result.json')
    assert code == 2 and result['result'] == 'blocked', result
    assert result['code'] == {
        'confirmation': 'ACTIVE_TASK_DRAIN_CONFIRMATION_REQUIRED', 'python': 'NATIVE_FILE_IDENTITY_MISMATCH',
        'extra-module': 'NATIVE_INVENTORY_UNEXPECTED_FILE', 'schema': 'NATIVE_UPGRADE_DATABASE_IDENTITY_MISMATCH',
        'pointer': 'NATIVE_FILE_IDENTITY_MISMATCH'}[change]
    assert (roots.DATA_ROOT / 'enterprise.db').read_bytes() == before
    assert not (roots.STAGING_ROOT / 'system-update').exists()


def test_fixed_native_entry_follows_current_pointer_after_upgrade_and_rollback(assets, materialized_sources, tmp_path_factory, native_build):
    roots = installation(tmp_path_factory.getbasetemp(), materialized_sources['ice-2026.09.5-7609bb1b7cfa'], security=False)
    entry = roots.INSTALL_ROOT / 'InfiniteCanvas.exe'
    shutil.copy2(native_build / 'InfiniteCanvas.exe', entry)
    before_hash = hashlib.sha256(entry.read_bytes()).hexdigest()
    source_id = roots.APP_ROOT.name
    original_pointer = (roots.STATE_ROOT / 'current-release.json').read_bytes()
    code, result = _native(entry, roots, ['--identity'], roots.INSTALL_ROOT / 'identity-source.json')
    assert code == 0 and result['release_id'] == source_id, result
    target_assets = assets / '2026.09.9'; target = roots.RELEASE_ROOT / TARGET_ID
    target_manifest = read_release_manifest_v2(target_assets / 'ops-release-manifest-v2.json')
    materialize_release_fixture(target_assets / 'ops-release-manifest-v2.json',
        target_assets / CATALOG[TARGET_ID]['archive_filename'], target_assets / 'release-payload-inventory.json', target)
    atomic_write_current_release(roots, CurrentRelease(SCHEMA_VERSION, TARGET_ID, 'releases/' + TARGET_ID,
        target_manifest.raw_sha256, '2026-10-01T00:00:00Z', source_id), expected_manifest_sha256=target_manifest.raw_sha256)
    code, result = _native(entry, roots, ['--identity'], roots.INSTALL_ROOT / 'identity-target.json')
    assert code == 0 and result['release_id'] == TARGET_ID, result
    (roots.STATE_ROOT / 'current-release.json').write_bytes(original_pointer)
    code, result = _native(entry, roots, ['--identity'], roots.INSTALL_ROOT / 'identity-rollback.json')
    assert code == 0 and result['release_id'] == source_id, result
    assert hashlib.sha256(entry.read_bytes()).hexdigest() == before_hash


@pytest.mark.parametrize('foreign_entry', [False, True], ids=['publish-and-repeat', 'preserve-unowned-file'])
def test_native_publishes_entry_only_in_selected_install_without_registry_or_shortcuts(foreign_entry, assets, materialized_sources, tmp_path_factory, native_build):
    source_id = 'ice-2026.09.5-7609bb1b7cfa'
    roots = installation(tmp_path_factory.getbasetemp(), materialized_sources[source_id], security=True)
    prepared = subprocess.run([str(roots.PYTHON_RUNTIME / 'python.exe'), '-I', '-B', '-c', SCRIPT,
        str(ROOT), str(roots.INSTALL_ROOT), str(roots.CACHE_ROOT.parents[1]), str(CATALOG_PATH),
        str(assets / '2026.09.9'), source_id, 'none'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
    assert prepared.returncode == 0, prepared.stderr[-2500:]
    assert json.loads(prepared.stdout.strip().splitlines()[-1])['result'] == 'succeeded'
    database = roots.DATA_ROOT / 'enterprise.db'
    before = database.read_bytes()
    entry = roots.INSTALL_ROOT / 'InfiniteCanvas.exe'
    if foreign_entry: entry.write_bytes(b'not-a-project-owned-executable')
    upgrade = native_build / 'Infinite-Canvas-Enterprise-Unified-Upgrader-x64.exe'
    code, result = _native(upgrade, roots, ['--upgrade', '--confirm-no-active-tasks', '--portable-entry'],
        roots.INSTALL_ROOT / 'publish-result.json')
    assert code == 0 and result['result'] == 'already_current', result
    assert result['launcher_installed'] is not foreign_entry
    assert database.read_bytes() == before
    if foreign_entry:
        assert result['launcher_code'] == 'NATIVE_ENTRY_UNOWNED_FILE'
        assert entry.read_bytes() == b'not-a-project-owned-executable'
    else:
        assert entry.read_bytes() == (native_build / 'InfiniteCanvas.exe').read_bytes()
        record = json.loads((roots.STATE_ROOT / 'native-entry.json').read_bytes())
        assert record['launcher_sha256'] == hashlib.sha256(entry.read_bytes()).hexdigest()
        code, second = _native(upgrade, roots, ['--upgrade', '--confirm-no-active-tasks', '--portable-entry'],
            roots.INSTALL_ROOT / 'repeat-result.json')
        assert code == 0 and second['launcher_installed'] is True, second
