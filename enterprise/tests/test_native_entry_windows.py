"""Actual compiled EXE contract checks with an explicit fixture-only worker.

No real Supervisor, application, database migration, listener or customer PC is
invoked here. The executable, pointer resolution and pre-execution guard are
real; lifecycle command responses come from ContractWorker, not Python.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import build_native_entry as builder

ROOT = Path(__file__).resolve().parents[2]


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope='module')
def native():
    value = os.environ.get('ICE_NATIVE_ENTRY')
    if os.name != 'nt' or not value:
        pytest.skip('Set ICE_NATIVE_ENTRY to the actual compiled InfiniteCanvas.exe on Windows')
    exe = Path(value).resolve()
    assert exe.is_file()
    return exe


@pytest.fixture(scope='module')
def contract_worker(native, tmp_path_factory):
    compiler_root, package = os.environ.get('ICE_NATIVE_COMPILER_ROOT'), os.environ.get('ICE_NATIVE_COMPILER_PACKAGE')
    assert compiler_root and package, 'Compiled tests require the pinned compiler package and extracted closure'
    compiler = builder.verify_compiler(Path(package), Path(compiler_root), builder.read_policy(ROOT))
    output = tmp_path_factory.mktemp('native-worker') / 'ContractWorker.exe'
    framework = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319'
    completed = subprocess.run([
        str(compiler), '/nologo', '/noconfig', '/nostdlib+', '/target:exe', '/platform:x64',
        '/langversion:7.3', '/codepage:65001', '/out:' + str(output),
        *('/reference:' + str(framework / (name + '.dll')) for name in ('mscorlib', 'System', 'System.Web.Extensions')),
        str(ROOT / 'enterprise/tests/fixtures/native/ContractWorker.cs'),
    ], capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return output


def release(root, release_id, worker):
    app = root / 'releases' / release_id
    files = {'python/python.exe': worker.read_bytes(),
             'enterprise/runtime/launcher.py': b'# fixture-only; ContractWorker never runs Python\n'}
    for relative, data in files.items():
        path = app / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    inventory = encode({'schema_version': 'ops-release-payload-inventory-v1', 'entries': [
        {'path': name, 'size_bytes': len(data), 'sha256': sha(data)} for name, data in files.items()
    ]})
    (app / 'release-payload-inventory.json').write_bytes(inventory)
    manifest = encode({
        'schema_version': 'ops-release-manifest-v2', 'identity': {'release_id': release_id},
        'enterprise_source': {'repository': 'MEIS-DaCaiTou/Infinite-Canvas-Enterprise'},
        'release_payload': {'inventory_path': 'release-payload-inventory.json',
                            'inventory_sha256': sha(inventory), 'embedded_manifest_path': 'release-manifest.json'},
    })
    (app / 'release-manifest.json').write_bytes(manifest)
    return manifest


def activate(root, release_id, manifest):
    state = root / 'state'
    state.mkdir(exist_ok=True)
    (state / 'current-release.json').write_bytes(encode({
        'schema_version': 'env-1b1b-current-release-v1', 'release_id': release_id,
        'app_root_relative': 'releases/' + release_id, 'manifest_sha256': sha(manifest),
        'activated_at': '2026-10-05T00:00:00Z', 'previous_release_id': None,
    }))


def invoke(exe, root, args, result, *, explicit_root=True, env=None):
    command = [str(exe), *args, '--result-file', str(result)]
    if explicit_root:
        command += ['--install-root', str(root)]
    completed = subprocess.run(command, cwd=root.parent, env=env, capture_output=True, timeout=60)
    assert result.is_file(), 'Native CLI must return a non-blocking result without a dialog'
    return completed.returncode, json.loads(result.read_bytes())


def snapshot(root):
    return {str(path.relative_to(root)): sha(path.read_bytes()) for path in root.rglob('*') if path.is_file()}


def test_fixed_entry_follows_switch_and_rollback_without_touching_data(native, contract_worker, tmp_path):
    root = tmp_path / '中文 安装'
    root.mkdir()
    entry = root / 'InfiniteCanvas.exe'
    shutil.copyfile(native, entry)
    for area in ('data', 'config', '素材'):
        (root / area).mkdir()
        (root / area / 'preserve.bin').write_bytes(b'fixture-preserved')
    releases = {name: release(root, name, contract_worker) for name in ('source-release', 'target-release')}
    for number, name in enumerate(('source-release', 'target-release', 'source-release')):
        activate(root, name, releases[name])
        before = snapshot(root)
        code, result = invoke(entry, root, ['--identity'], tmp_path / f'identity-{number}.json', explicit_root=False)
        assert code == 0 and result['release_id'] == name
        assert snapshot(root) == before
    assert sha(entry.read_bytes()) == sha(native.read_bytes())


@pytest.mark.parametrize('command', ['start', 'stop', 'restart', 'status', 'health'])
def test_handoff_uses_isolated_direct_script_not_bat(native, contract_worker, tmp_path, command):
    root = tmp_path / '中文 带空格'
    root.mkdir()
    manifest = release(root, 'current-source', contract_worker)
    activate(root, 'current-source', manifest)
    before = snapshot(root)
    environment = dict(os.environ, PYTHONPATH='fixture-hostile', PYTHONHOME='fixture-hostile')
    code, result = invoke(native, root, ['--' + command], tmp_path / 'result.json', env=environment)
    assert code == 0 and result['worker_exit_code'] == 0
    assert result['result'] == 'fixture-only-no-service'
    assert result['argv'] == ['-I', '-B', str(root / 'releases/current-source/enterprise/runtime/launcher.py'), 'portable', command]
    assert result['cwd'] == str(root / 'releases/current-source')
    assert result['pythonpath_removed'] and result['pythonhome_removed']
    assert result['no_user_site'] == result['no_bytecode'] == '1'
    assert snapshot(root) == before


@pytest.mark.parametrize('change,expected', [
    ('manifest', 'NATIVE_FILE_IDENTITY_MISMATCH'),
    ('python', 'NATIVE_FILE_IDENTITY_MISMATCH'),
    ('extra', 'NATIVE_INVENTORY_UNEXPECTED_FILE'),
    ('missing', 'NATIVE_PATH_MISSING'),
    ('escape', 'NATIVE_CURRENT_RELEASE_INVALID'),
    ('duplicate', 'NATIVE_CURRENT_RELEASE_INVALID'),
])
def test_changed_or_unknown_payload_is_blocked_before_handoff(native, contract_worker, tmp_path, change, expected):
    root = tmp_path / 'install'
    root.mkdir()
    manifest = release(root, 'source', contract_worker)
    activate(root, 'source', manifest)
    app = root / 'releases/source'
    if change == 'manifest':
        (app / 'release-manifest.json').write_bytes(manifest + b' ')
    elif change == 'python':
        path = app / 'python/python.exe'
        path.write_bytes(b'x' * path.stat().st_size)
    elif change == 'extra':
        (app / 'foreign.py').write_bytes(b'not-owned')
    elif change == 'missing':
        (app / 'enterprise/runtime/launcher.py').unlink()
    elif change == 'escape':
        pointer = json.loads((root / 'state/current-release.json').read_bytes())
        pointer['app_root_relative'] = '../other-project'
        (root / 'state/current-release.json').write_bytes(encode(pointer))
    else:
        path = root / 'state/current-release.json'
        path.write_bytes(path.read_bytes().replace(b'"release_id": "source"', b'"release_id": "source", "release_id": "source"'))
    before = snapshot(root)
    code, result = invoke(native, root, ['--status'], tmp_path / 'result.json')
    assert code == 2 and result == {'result': 'blocked', 'code': expected}
    assert snapshot(root) == before


@pytest.mark.parametrize('arguments', [['--start', '--stop'], ['--status', '--status'], ['--arbitrary-command'], ['--install-root']])
def test_invalid_cli_does_not_pop_up_or_mutate_install(native, tmp_path, arguments):
    root = tmp_path / 'install'
    root.mkdir()
    before = snapshot(root)
    code, result = invoke(native, root, arguments, tmp_path / 'result.json')
    assert code == 2 and result['code'] == 'NATIVE_ARGUMENT_INVALID'
    assert snapshot(root) == before


def test_result_file_never_overwrites_user_file(native, contract_worker, tmp_path):
    root = tmp_path / 'install'
    root.mkdir()
    activate(root, 'source', release(root, 'source', contract_worker))
    result_path = tmp_path / 'user-file.json'
    result_path.write_bytes(b'not-owned')
    completed = subprocess.run([str(native), '--identity', '--install-root', str(root),
                                '--result-file', str(result_path)], capture_output=True, timeout=60)
    assert completed.returncode == 2
    assert result_path.read_bytes() == b'not-owned'
