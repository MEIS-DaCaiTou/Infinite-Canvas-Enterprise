"""Opt-in exact 09.5 process/HTTP drill, NOT a customer-device acceptance.

KnownFolder/Popen wrappers isolate roots. Original old Supervisor, Job, host,
child, application and gateway run as real processes with bundled Python.
The stop controller is the production repaired engine, not a lifecycle mock.
"""
import hashlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from contextlib import closing

import pytest

from enterprise.release.release_manifest_v2 import materialize_release_fixture
from enterprise.tests.test_unified_upgrade_installed import installation, CATALOG, ROOT

SOURCE = 'ice-2026.09.5-7609bb1b7cfa'
HOST = ROOT / 'enterprise/tests/runtime_fixture_historical_host.py'


SCRIPT = r'''
import json, subprocess, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.runtime.recovery_control import stop_portable_service, portable_controller
from enterprise.runtime.control import inspect_runtime
from tools import unified_upgrade as worker
repo, install, local, assets, host = map(Path, sys.argv[1:6])
app = install / 'releases' / 'ice-2026.09.5-7609bb1b7cfa'
failure = sys.argv[6]
target_started = False
def legacy(command, root=app):
    done = subprocess.run([str(root/'python/python.exe'), '-I', '-B', str(host), '--fixture-app-root', str(root),
        '--fixture-local-base', str(local), '--fixture-entry', command], capture_output=True,
        text=True, encoding='utf-8', errors='replace', timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
    payload = json.loads(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else {'result':'no_output'}
    return done.returncode, payload
runtime = local / 'InfiniteCanvasEnterprise/runtime'
try:
    code, start = legacy('start')
    assert code == 0, start
    (runtime / 'fixture-incident-armed').write_text('fixture\n', encoding='ascii')
    deadline = time.monotonic() + 60
    while not (runtime / 'fixture-incident-observed').exists() and time.monotonic() < deadline:
        time.sleep(.2)
    assert (runtime / 'fixture-incident-observed').exists(), 'incident not reached'
    old_code, old_stop = legacy('stop')
    assert old_code != 0 and old_stop.get('code') == 'PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED', old_stop
    before = inspect_runtime(portable_controller(app, local_app_data_base=local).config)
    assert before['start_disposition'] == 'upstream_only' and before['portable_control_valid'] is True, before
    assert before['portable_ownership_valid'] is False
    original_launcher = worker._run_launcher
    # The old OS wrappers isolate start/health only. STOP is the actual new
    # production control, so the broken historical guard is NOT mocked away.
    def isolated_launcher(root, command):
        global target_started
        if command == 'stop': return stop_portable_service(root, local_app_data_base=local)
        code, payload = legacy(command, root)
        if failure == 'target_start' and root != app and command == 'start' and code == 0:
            target_started = True
            # Target's original Supervisor/Job/HTTP really started. Inject the
            # updater's post-start validation refusal, then stop that live
            # TARGET via its verified Python while this worker uses SOURCE.
            return 2, {'code':'DRILL_TARGET_POST_START_REFUSAL'}
        return code, payload
    result = worker.run(install_root=install, local_app_data_base=local,
        catalog_path=repo/'installer/windows/historical-install-catalog.json',
        manifest_path=assets/'2026.09.9/ops-release-manifest-v2.json',
        archive_path=assets/'2026.09.9/Infinite-Canvas-Enterprise-ice-2026.09.9-54f9e67d1643-win-x64.zip',
        inventory_path=assets/'2026.09.9/release-payload-inventory.json',
        recover_service_only=(failure == 'none'), confirm_no_active_tasks=True, launcher=isolated_launcher)
    assert result['result'] == ('service_recovered' if failure == 'none' else 'failed_safe'), result
    if failure != 'none':
        assert result['terminal_state'] == 'ROLLED_BACK' and target_started, result
        assert any(row['phase']=='stop' and row.get('quiescence_confirmed') is True
            for row in result['lifecycle'][1:]), result
    status = inspect_runtime(portable_controller(app, local_app_data_base=local).config)
    assert status['readiness']['ready'] is True, status
    assert result['lifecycle'][0]['quiescence_confirmed'] is True
    port = status['gateway_listener']['port']
    with urllib.request.urlopen('http://127.0.0.1:%s/enterprise/login'%port, timeout=10) as response:
        assert response.status == 200
    print(json.dumps({'result':'pass','old_stop_rejected':True,'new_stop_quiescent':True,
        'source_http_ready':True,'target_started':target_started,'scenario':failure,
        'terminal_state':result.get('terminal_state'),'lifecycle':result['lifecycle']}, ensure_ascii=False))
finally:
    try:
        from enterprise.release.current_release import read_current_release_result_from_state_root
        active = read_current_release_result_from_state_root(install/'state').release.release_id
        code, stopped = stop_portable_service(install/'releases'/active, local_app_data_base=local)
        assert code == 0, stopped
    except Exception:
        raise  # Never hide a leaked/unknown fixture process.
'''


@pytest.mark.skipif(os.name != 'nt', reason='Windows native lifecycle')
@pytest.mark.parametrize('failure', ['none', 'target_start'])
def test_exact_095_partial_instance_recovers_and_live_target_failure_rolls_back(tmp_path_factory, failure):
    raw_assets = os.environ.get('ICE_HISTORICAL_ASSETS')
    if not raw_assets: pytest.skip('Set ICE_HISTORICAL_ASSETS to verified historical assets')
    assets = Path(raw_assets)
    base = tmp_path_factory.getbasetemp()
    scenario = base / failure
    scenario.mkdir()
    source = scenario / 's'
    record = CATALOG[SOURCE]
    materialize_release_fixture(assets/'2026.09.5/ops-release-manifest-v2.json',
        assets/'2026.09.5'/record['archive_filename'], assets/'2026.09.5/release-payload-inventory.json', source)
    roots = installation(scenario, source, security=True)
    ports = []
    for _ in range(2):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); ports.append(sock.getsockname()[1])
    assert ports[0] != ports[1]
    env_file = roots.CONFIG_ROOT / 'enterprise.env'
    with env_file.open('a', encoding='utf-8') as output:
        output.write('UPSTREAM_PORT=%s\nGATEWAY_PORT=%s\n' % tuple(ports))
    preserve = [roots.STATE_ROOT/'current-release.json', roots.DATA_ROOT/'canvas.json', roots.UPLOAD_ROOT/'asset.bin', env_file]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in preserve}
    import sqlite3
    database = roots.DATA_ROOT/'enterprise.db'
    # On Windows even an idle open sqlite handle prevents atomic file
    # restore. Parent-side evidence inspection must release its own handles
    # BEFORE any real update/recovery child starts.
    with closing(sqlite3.connect(database)) as conn:
        schema = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    done = subprocess.run([str(roots.PYTHON_RUNTIME/'python.exe'), '-I', '-B', '-c', SCRIPT,
        str(ROOT), str(roots.INSTALL_ROOT), str(roots.CACHE_ROOT.parents[1]), str(assets), str(HOST), failure],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=480,
        creationflags=subprocess.CREATE_NO_WINDOW)
    assert done.returncode == 0, done.stdout[-5000:] + done.stderr[-5000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result['result'] == 'pass'
    if failure == 'none':
        assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in preserve} == before
    else:
        assert all(hashlib.sha256(path.read_bytes()).hexdigest() == before[path] for path in preserve[1:])
        pointer = json.loads(preserve[0].read_bytes())
        assert pointer['release_id'] == SOURCE and pointer['manifest_sha256'] == record['manifest_sha256']
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall() == schema
        assert conn.execute('SELECT count(*) FROM security_audit_events').fetchone() == (1,)
        assert conn.execute('SELECT count(*) FROM security_governance_bootstrap').fetchone() == (1,)
        assert conn.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    (base/('real-095-'+failure+'-evidence.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
