"""Targeted build policy checks; no customer installation or service writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from enterprise.path_safety import PathSafetyError
from tools import build_native_entry as builder

ROOT = Path(__file__).resolve().parents[2]


def test_policy_is_version_independent_and_pins_unsigned_toolchain():
    policy = builder.read_policy(ROOT)
    assert not any('target' in key or 'catalog' in key for key in policy)
    assert policy['signed'] is False
    assert policy['requires_administrator'] is False
    assert policy['launcher_filename'] == 'InfiniteCanvas.exe'
    assert policy['compiler_package_sha256'] == builder.COMPILER_SHA256


@pytest.mark.parametrize('field,value', [
    ('compiler_package_sha256', '0' * 64), ('compiler_relative', '../csc.exe'),
    ('language_version', 'latest'), ('signed', True),
    ('launcher_filename', '09.9.exe'), ('target_version', '09.9'),
])
def test_policy_drift_is_rejected(tmp_path, field, value):
    policy = builder.read_policy(ROOT)
    policy[field] = value
    target = tmp_path / builder.POLICY_PATH
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(policy), encoding='utf-8')
    with pytest.raises(ValueError, match='NATIVE_ENTRY_BUILD_POLICY_INVALID'):
        builder.read_policy(tmp_path)


@pytest.mark.parametrize('relationship', ['same', 'child', 'parent', 'exists', 'drive-root'])
def test_output_never_overwrites_or_overlaps_inputs(tmp_path, relationship):
    source = tmp_path / 'source'
    source.mkdir()
    output = {'same': source, 'child': source / 'build', 'parent': tmp_path,
              'exists': tmp_path / 'existing', 'drive-root': Path(tmp_path.anchor)}[relationship]
    if relationship == 'exists':
        output.mkdir()
        (output / 'do-not-touch.txt').write_bytes(b'other-project')
    with pytest.raises(ValueError, match='NATIVE_ENTRY_OUTPUT_'):
        builder.verify_output(output, (source,))
    if relationship == 'exists':
        assert (output / 'do-not-touch.txt').read_bytes() == b'other-project'


def test_output_accepts_only_new_sibling_and_does_not_create_it(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    output = tmp_path / 'artifacts' / 'entry-1'
    assert builder.verify_output(output, (source,)) == output
    assert not output.exists()


def compiler_fixture(base):
    package = base / 'compiler.nupkg'
    folder = base / 'compiler' / 'tasks' / 'net472'
    folder.mkdir(parents=True)
    with zipfile.ZipFile(package, 'x') as archive:
        for name in ('csc.exe', 'csc.exe.config', 'compiler.dll'):
            data = ('fixture-' + name).encode()
            archive.writestr('tasks/net472/' + name, data)
            (folder / name).write_bytes(data)
    policy = {'compiler_package_sha256': builder.digest(package),
              'compiler_relative': 'tasks/net472/csc.exe'}
    return package, folder.parent.parent, policy


def test_compiler_fixture_closure_is_checked(tmp_path):
    package, folder, policy = compiler_fixture(tmp_path)
    assert builder.verify_compiler(package, folder, policy) == folder / 'tasks/net472/csc.exe'


@pytest.mark.parametrize('change', ['package', 'dll', 'extra', 'missing'])
def test_compiler_tampering_is_rejected(tmp_path, change):
    package, folder, policy = compiler_fixture(tmp_path)
    if change == 'package':
        package.write_bytes(package.read_bytes() + b'changed')
    elif change == 'dll':
        (folder / 'tasks/net472/compiler.dll').write_bytes(b'changed')
    elif change == 'extra':
        (folder / 'tasks/net472/unexpected.dll').write_bytes(b'injected')
    else:
        (folder / 'tasks/net472/compiler.dll').unlink()
    with pytest.raises((ValueError, PathSafetyError)):
        builder.verify_compiler(package, folder, policy)


def test_output_reparse_ancestor_is_rejected(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    link = tmp_path / 'linked'
    try:
        link.symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip('Creating symlinks is not allowed on this host')
    with pytest.raises(PathSafetyError):
        builder.verify_output(link / 'new-build', (tmp_path / 'other-input',))


@pytest.mark.skipif(os.name != 'nt', reason='Windows build integration')
def test_build_fails_on_dirty_source_before_writing_artifacts(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'untracked.txt').write_bytes(b'fixture')
    package = tmp_path / 'package'
    package.write_bytes(b'fixture')
    compiler = tmp_path / 'compiler'
    compiler.mkdir()
    output = tmp_path / 'build'
    args = argparse.Namespace(repo=repo, compiler_package=package, compiler_root=compiler,
                              output_root=output, allow_dirty=False)
    with pytest.raises(ValueError, match='NATIVE_ENTRY_BUILD_REQUIRES_CLEAN_COMMIT'):
        builder.build(args)
    assert not output.exists()
