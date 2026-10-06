"""Small offline-export safety checks, no service start or installation drill."""
import base64
import hashlib
import io
import json
from types import SimpleNamespace
import zipfile

import pytest

from enterprise.paths import PortableRootInputs, derive_portable_path_roots, prepare_install_state_directories
from enterprise.ops.update import native_diagnostics as subject


def fixture(tmp_path, monkeypatch):
    roots = derive_portable_path_roots(PortableRootInputs(tmp_path/'install', tmp_path/'local'), 'source')
    prepare_install_state_directories(roots)
    roots.CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    roots.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    roots.RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    (roots.RUNTIME_ROOT/'launch-context.json').write_text(json.dumps({'path_roots_identity':roots.root_identity}))
    pointer = SimpleNamespace(release=SimpleNamespace(release_id='source', manifest_sha256='5'*64))
    monkeypatch.setattr(subject, 'read_current_release_result_from_state_root', lambda _:pointer)
    monkeypatch.setattr(subject, 'read_catalog', lambda _:{'source':{'manifest_sha256':'5'*64}})
    return roots


def unpack(result):
    data = base64.b64decode(result['project_logs_zip_base64'])
    assert hashlib.sha256(data).hexdigest() == result['project_logs_sha256']
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return json.loads(archive.read('project-diagnostics.json'))


def test_export_redacts_and_preserves_business_files(tmp_path, monkeypatch):
    roots = fixture(tmp_path, monkeypatch)
    env = roots.CONFIG_ROOT/'enterprise.env'
    env.write_text('API_KEY=private-secret-value-123456\n')
    folder = roots.LOG_ROOT/'runtime'; folder.mkdir(parents=True)
    log = folder/'supervisor.log'
    log.write_text(json.dumps({'event':'failed', 'token':'private-secret-value-123456',
        'args':['sensitive-command'], 'prompt':'customer-prompt'})+'\npassword=private-secret-value-123456\n')
    (folder/'supervisor.log.1').write_text('event=earlier\n')
    database = roots.DATA_ROOT/'enterprise.db'; database.write_bytes(b'do-not-open-database')
    canvas = roots.DATA_ROOT/'canvas.json'; canvas.write_bytes(b'private-canvas')
    protected = [env,log,database,canvas]
    before = [path.read_bytes() for path in protected]
    payload = unpack(subject.collect_project_logs(roots.INSTALL_ROOT, tmp_path/'catalog', local_app_data_base=tmp_path/'local'))
    text = json.dumps(payload)
    for value in ('private-secret-value-123456','sensitive-command','customer-prompt','private-canvas','do-not-open-database'):
        assert value not in text
    assert 'runtime/supervisor.log.1' in payload['sources']
    assert payload['business_database_included'] is False
    assert [path.read_bytes() for path in protected] == before


def test_export_limits_recent_jobs_and_records(tmp_path, monkeypatch):
    roots = fixture(tmp_path, monkeypatch)
    folder = roots.LOG_ROOT/'runtime'; folder.mkdir(parents=True)
    (folder/'upstream.stdout.log').write_text(('x'*4000+'\n')*300)
    jobs = roots.STAGING_ROOT/'update-mvp/jobs'; jobs.mkdir(parents=True)
    for index in range(5):
        path = jobs/(f'{index:032x}'); path.mkdir()
        (path/'events.jsonl').write_text('{"event":"sample"}\n')
        (path/'status.json').write_text('{"state":"FAILED","password":"hidden"}')
    result = subject.collect_project_logs(roots.INSTALL_ROOT, tmp_path/'catalog', local_app_data_base=tmp_path/'local')
    payload = unpack(result)
    assert len(payload['update_jobs']) == 3 and result['truncated'] is True
    assert len(json.dumps(payload).encode('utf-8')) <= subject.TOTAL_BUDGET
    assert all(len('\n'.join(row.get('lines',[])).encode()) < subject.FILE_BUDGET + 200 for row in payload['sources'].values())


def test_other_installation_runtime_state_is_not_collected(tmp_path, monkeypatch):
    roots = fixture(tmp_path, monkeypatch)
    (roots.RUNTIME_ROOT/'launch-context.json').write_text('{"path_roots_identity":"other-install"}')
    (roots.RUNTIME_ROOT/'runtime-state.json').write_text('{"marker":"other-project-data"}')
    payload = unpack(subject.collect_project_logs(roots.INSTALL_ROOT, tmp_path/'catalog', local_app_data_base=tmp_path/'local'))
    assert payload['runtime'] == {'status':'unavailable'}
    assert 'other-project-data' not in json.dumps(payload)


def test_reparse_log_is_never_read(tmp_path, monkeypatch):
    roots = fixture(tmp_path, monkeypatch)
    folder = roots.LOG_ROOT/'runtime'; folder.mkdir(parents=True)
    outside = tmp_path/'outside.log'; outside.write_text('other-project-data')
    path = folder/'supervisor.log'
    try: path.symlink_to(outside)
    except OSError: pytest.skip('Symlink creation is not allowed for this caller')
    payload = unpack(subject.collect_project_logs(roots.INSTALL_ROOT, tmp_path/'catalog', local_app_data_base=tmp_path/'local'))
    assert payload['sources']['runtime/supervisor.log'] == {'status':'unavailable'}
    assert 'other-project-data' not in json.dumps(payload)
