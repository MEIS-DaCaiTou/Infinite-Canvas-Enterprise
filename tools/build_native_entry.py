#!/usr/bin/env python3
"""Build the version-independent Windows entry; never install or update data.

The compiler is supplied externally and verified against a pinned official
package and its entire extracted net472 closure. Outputs belong to a new,
dedicated artifact directory outside this checkout and the toolchain. No
customer installation, historical catalogue or application target is needed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT))

from enterprise.path_safety import assert_no_reparse_ancestors
from enterprise.release.release_manifest_v2 import canonical_json

POLICY_PATH = Path('installer/windows/native-entry-build-policy.json')
NATIVE_PATH = Path('installer/windows/native')
SOURCES = ('NativeCore.cs', 'LauncherProgram.cs', 'app.manifest')
COMPILER_SHA256 = 'fe24ef31a6ffcb7c49383d2fd362763dee291ad9b9d98cc0c19ef80203b99ebc'
REFERENCES = ('mscorlib', 'System', 'System.Core', 'System.Drawing',
              'System.Windows.Forms', 'System.Web.Extensions', 'System.IO.Compression')


def absolute(path: Path, *, allow_missing: bool = False) -> Path:
    # Inspect lexical ancestors before any operation that could follow links.
    result = Path(os.path.abspath(path))
    assert_no_reparse_ancestors(result, allow_missing=allow_missing)
    return result


def digest(path: Path) -> str:
    path = absolute(path)
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def read_policy(repo: Path) -> dict:
    policy = json.loads(absolute(repo / POLICY_PATH).read_bytes())
    expected = {
        'schema_version': 'enterprise-native-entry-build-policy-v1',
        'compiler_package': 'microsoft.net.compilers.toolset.4.12.0.nupkg',
        'compiler_package_sha256': COMPILER_SHA256,
        'compiler_relative': 'tasks/net472/csc.exe',
        'language_version': '7.3', 'platform': 'x64',
        'launcher_filename': 'InfiniteCanvas.exe',
        'signed': False, 'requires_administrator': False,
    }
    if not isinstance(policy, dict) or any(type(policy.get(key)) is not type(value) or policy.get(key) != value
                                           for key, value in expected.items()):
        raise ValueError('NATIVE_ENTRY_BUILD_POLICY_INVALID')
    if set(policy) != set(expected) | {'compiler_package_url'} or policy['compiler_package_url'] != (
        'https://api.nuget.org/v3-flatcontainer/microsoft.net.compilers.toolset/'
        '4.12.0/microsoft.net.compilers.toolset.4.12.0.nupkg'
    ):
        raise ValueError('NATIVE_ENTRY_BUILD_POLICY_INVALID')
    return policy


def verify_compiler(package: Path, compiler_root: Path, policy: dict) -> Path:
    package, compiler_root = absolute(package), absolute(compiler_root)
    if digest(package) != policy['compiler_package_sha256']:
        raise ValueError('NATIVE_ENTRY_COMPILER_PACKAGE_MISMATCH')
    directory = absolute(compiler_root / 'tasks/net472')
    expected: set[str] = set()
    with zipfile.ZipFile(package) as archive:
        for item in archive.infolist():
            if item.is_dir() or not item.filename.startswith('tasks/net472/'):
                continue
            relative = item.filename[len('tasks/net472/'):]
            # The pinned package is trusted, but still do not extract or follow
            # a package pathname outside its declared compiler directory.
            if not relative or any(part in ('', '.', '..') for part in relative.split('/')) or '\\' in relative or ':' in relative:
                raise ValueError('NATIVE_ENTRY_COMPILER_CLOSURE_MISMATCH')
            if relative in expected:
                raise ValueError('NATIVE_ENTRY_COMPILER_CLOSURE_MISMATCH')
            expected.add(relative)
            if digest(directory / relative) != hashlib.sha256(archive.read(item)).hexdigest():
                raise ValueError('NATIVE_ENTRY_COMPILER_CLOSURE_MISMATCH')
    actual: set[str] = set()
    for folder, directories, files in os.walk(directory, followlinks=False):
        for name in directories + files:
            absolute(Path(folder) / name)
        actual.update((Path(folder) / name).relative_to(directory).as_posix() for name in files)
    if actual != expected or 'csc.exe' not in expected:
        raise ValueError('NATIVE_ENTRY_COMPILER_CLOSURE_MISMATCH')
    return absolute(compiler_root / policy['compiler_relative'])


def verify_output(output: Path, inputs: tuple[Path, ...]) -> Path:
    output = absolute(output, allow_missing=True)
    if output == Path(output.anchor):
        raise ValueError('NATIVE_ENTRY_OUTPUT_INVALID')
    for source in inputs:
        source = absolute(source)
        if output == source or output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError('NATIVE_ENTRY_OUTPUT_OVERLAPS_INPUT')
    if output.exists():
        raise ValueError('NATIVE_ENTRY_OUTPUT_EXISTS')
    return output


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(['git', *arguments], cwd=repo, check=True, capture_output=True,
                          text=True, encoding='utf-8', timeout=30).stdout.strip()


def compile_entry(compiler: Path, repo: Path, output: Path) -> None:
    framework = absolute(Path(os.environ.get('WINDIR', r'C:\Windows')) /
                         'Microsoft.NET/Framework64/v4.0.30319')
    output.parent.mkdir()
    absolute(output.parent)
    native = repo / NATIVE_PATH
    arguments = [str(compiler), '/nologo', '/noconfig', '/nostdlib+',
                 '/target:winexe', '/platform:x64', '/langversion:7.3',
                 '/codepage:65001', '/optimize+', '/deterministic+', '/debug-', '/warnaserror+',
                 '/out:' + str(output), '/win32manifest:' + str(absolute(native / 'app.manifest')),
                 '/pathmap:' + str(repo) + '=/_/source',
                 *('/reference:' + str(absolute(framework / (name + '.dll'))) for name in REFERENCES),
                 str(absolute(native / 'NativeCore.cs')), str(absolute(native / 'LauncherProgram.cs'))]
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('NATIVE_ENTRY_COMPILE_FAILED\n' + result.stdout[-4000:] + result.stderr[-4000:])


def build(args: argparse.Namespace) -> dict:
    if os.name != 'nt':
        raise ValueError('NATIVE_ENTRY_BUILD_REQUIRES_WINDOWS')
    repo = absolute(args.repo)
    package, compiler_root = absolute(args.compiler_package), absolute(args.compiler_root)
    output = verify_output(args.output_root, (repo, package, compiler_root))
    status = _git(repo, 'status', '--porcelain', '--untracked-files=all')
    if status and not args.allow_dirty:
        raise ValueError('NATIVE_ENTRY_BUILD_REQUIRES_CLEAN_COMMIT')
    commit, tree = _git(repo, 'rev-parse', 'HEAD'), _git(repo, 'rev-parse', 'HEAD^{tree}')
    policy = read_policy(repo)
    compiler = verify_compiler(package, compiler_root, policy)
    source_hashes = {name: digest(repo / NATIVE_PATH / name) for name in SOURCES}
    output.mkdir(parents=True)
    absolute(output)
    name = policy['launcher_filename']
    for attempt in ('pass1', 'pass2'):
        compile_entry(compiler, repo, output / attempt / name)
    first, second = output / 'pass1' / name, output / 'pass2' / name
    if first.read_bytes() != second.read_bytes():
        raise ValueError('NATIVE_ENTRY_NOT_REPRODUCIBLE')
    if source_hashes != {item: digest(repo / NATIVE_PATH / item) for item in SOURCES}:
        raise ValueError('NATIVE_ENTRY_SOURCE_CHANGED_DURING_BUILD')
    (output / name).write_bytes(first.read_bytes())
    record = {
        'schema_version': 'enterprise-native-entry-build-record-v1',
        'source_commit': commit, 'source_tree': tree,
        'dirty_experimental_build': bool(status),
        'policy_sha256': digest(repo / POLICY_PATH), 'source_files_sha256': source_hashes,
        'compiler_package_sha256': digest(package), 'compiler_sha256': digest(compiler),
        'deterministic_double_build': True, 'signed': False,
        'executable': {'filename': name, 'sha256': digest(output / name),
                       'size_bytes': (output / name).stat().st_size},
    }
    (output / 'native-entry-build-record.json').write_bytes(canonical_json(record))
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--compiler-package', type=Path, required=True)
    parser.add_argument('--compiler-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--allow-dirty', action='store_true', help='Experiments only; never publish this build')
    print(json.dumps(build(parser.parse_args()), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
