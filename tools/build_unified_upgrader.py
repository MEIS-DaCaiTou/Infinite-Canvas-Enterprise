#!/usr/bin/env python3
"""Build a pinned offline updater and version-independent Windows launcher.

The thin C# layer handles Windows UI, discovery and CreateProcess only. The
existing Python DATA engine remains the sole migration/recovery implementation.
No compiler, customer data or credentials are installed on a customer's PC.
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

from enterprise.ops.update.historical_install import read_catalog
from enterprise.path_safety import assert_no_reparse_ancestors
from enterprise.release.release_manifest_v2 import canonical_json, read_release_manifest_v2, verify_release_manifest_v2


def digest(path: Path) -> str:
    assert_no_reparse_ancestors(path)
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def verify_compiler(package: Path, compiler_root: Path, policy: dict) -> Path:
    if digest(package) != policy['compiler_package_sha256']:
        raise ValueError('NATIVE_COMPILER_PACKAGE_MISMATCH')
    # Package hash alone does not establish that extracted DLLs are unchanged.
    directory = compiler_root / 'tasks' / 'net472'
    expected = set()
    with zipfile.ZipFile(package) as archive:
        for item in archive.infolist():
            if item.is_dir() or not item.filename.startswith('tasks/net472/'):
                continue
            path = compiler_root / item.filename
            expected.add(path.relative_to(directory).as_posix())
            if digest(path) != hashlib.sha256(archive.read(item)).hexdigest():
                raise ValueError('NATIVE_COMPILER_CLOSURE_MISMATCH')
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob('*') if path.is_file()}
    if actual != expected:
        raise ValueError('NATIVE_COMPILER_CLOSURE_MISMATCH')
    return compiler_root / policy['compiler_relative']


def longest_target_suffix(archive: Path, prefix: str, release_id: str) -> int:
    with zipfile.ZipFile(archive) as handle:
        lengths = [len(item.filename[len(prefix.rstrip('/') + '/'):].replace('/', '\\'))
                   for item in handle.infolist() if not item.is_dir()]
    if not lengths:
        raise ValueError('NATIVE_TARGET_ARCHIVE_EMPTY')
    return len(f"releases\\.{release_id}.{'0' * 32}.partial\\") + max(lengths)


def compile_program(compiler: Path, repo: Path, output: Path, program: str, *, extra: list[str] = ()) -> None:
    framework = Path(os.environ.get('WINDIR', 'C:\\Windows')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319'
    references = ['mscorlib', 'System', 'System.Core', 'System.Drawing', 'System.Windows.Forms',
                  'System.Web.Extensions', 'System.IO.Compression', 'System.Management', 'System.Xml']
    output.parent.mkdir(parents=True, exist_ok=True)
    native = repo / 'installer' / 'windows' / 'native'
    arguments = [str(compiler), '/nologo', '/noconfig', '/nostdlib+', '/target:winexe', '/platform:x64',
                 '/langversion:7.3', '/optimize+', '/deterministic+', '/debug-', '/warnaserror+',
                 '/out:' + str(output), '/win32manifest:' + str(native / 'app.manifest'),
                 '/pathmap:' + str(repo) + '=/_/source',
                 *('/reference:' + str(framework / (name + '.dll')) for name in references),
                 str(native / 'NativeCore.cs'), str(native / program), *extra]
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('NATIVE_COMPILE_FAILED\n' + result.stdout[-6000:] + result.stderr[-6000:])


def _zip_bytes(path: Path, files: dict[str, bytes]) -> bytes:
    with zipfile.ZipFile(path, 'x') as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if name.endswith('.zip') else zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)
    return canonical_json({'files': [{'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)}
                                     for name, data in sorted(files.items())]})


def build(args: argparse.Namespace) -> dict:
    if os.name != 'nt':
        raise ValueError('NATIVE_BUILD_REQUIRES_WINDOWS')
    repo, assets, output = (value.resolve() for value in (args.repo, args.target_assets, args.output_root))
    for path in (repo, assets, output, args.compiler_root, args.compiler_package):
        assert_no_reparse_ancestors(path, allow_missing=True)
    for source in (repo, assets, args.compiler_root.resolve(), args.compiler_package.resolve()):
        if output == source or output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError('NATIVE_BUILD_OUTPUT_OVERLAPS_INPUT')
    if output.exists():
        raise ValueError('NATIVE_BUILD_OUTPUT_EXISTS')
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=repo, check=True, capture_output=True, text=True).stdout
    if status and not args.allow_dirty:
        raise ValueError('NATIVE_BUILD_REQUIRES_CLEAN_COMMIT')
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    tree = subprocess.run(['git', 'rev-parse', 'HEAD^{tree}'], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    policy_path = repo / 'installer' / 'windows' / 'native-build-policy.json'
    policy = json.loads(policy_path.read_bytes())
    if policy.get('schema_version') != 'enterprise-native-build-policy-v1':
        raise ValueError('NATIVE_BUILD_POLICY_INVALID')
    compiler = verify_compiler(args.compiler_package.resolve(), args.compiler_root.resolve(), policy)
    catalog_path = repo / 'installer' / 'windows' / 'historical-install-catalog.json'
    catalog = read_catalog(catalog_path)
    manifest_path = assets / 'ops-release-manifest-v2.json'
    inventory_path = assets / 'release-payload-inventory.json'
    target = read_release_manifest_v2(manifest_path)
    record = catalog.get(target.release_id)
    if (target.release_id != policy['target_release_id'] or record is None
        or record['channel'] != 'stable' or record['manifest_sha256'] != target.raw_sha256):
        raise ValueError('NATIVE_BUILD_TARGET_INVALID')
    archive_path = assets / target.section('archive')['filename']
    verify_release_manifest_v2(manifest_path, archive_path, inventory_path)
    output.mkdir(parents=True)
    catalog_bytes = canonical_json(json.loads(catalog_path.read_bytes()))
    catalog_resource = output / 'catalog.json'; catalog_resource.write_bytes(catalog_bytes)
    launcher_name = policy['launcher_filename']
    for name in ('pass1', 'pass2'):
        compile_program(compiler, repo, output / name / launcher_name, 'LauncherProgram.cs')
    first = output / 'pass1' / launcher_name
    if first.read_bytes() != (output / 'pass2' / launcher_name).read_bytes():
        raise ValueError('NATIVE_LAUNCHER_NOT_REPRODUCIBLE')
    (output / launcher_name).write_bytes(first.read_bytes())
    files = {'catalog.json': catalog_bytes, launcher_name: first.read_bytes(),
             'core/ops-release-manifest-v2.json': manifest_path.read_bytes(),
             'core/release.zip': archive_path.read_bytes(),
             'core/release-payload-inventory.json': inventory_path.read_bytes()}
    paths = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', 'enterprise'],
        cwd=repo, check=True, capture_output=True).stdout.decode('utf-8').split('\0')
    for relative in sorted(set(paths) - {''}):
        path = repo / relative
        if '/tests/' in relative or '__pycache__' in path.parts or path.suffix not in {'.py', '.json', '.sql'}:
            continue
        if path.is_file():
            assert_no_reparse_ancestors(path)
            files['engine/' + relative] = path.read_bytes()
    files['engine/tools/unified_upgrade.py'] = (repo / 'tools' / 'unified_upgrade.py').read_bytes()
    files['engine/LICENSE'] = (repo / 'LICENSE').read_bytes()
    index_bytes = _zip_bytes(output / 'bundle.zip', files)
    index_path = output / 'bundle-index.json'; index_path.write_bytes(index_bytes)
    suffix = longest_target_suffix(archive_path, target.section('archive')['root_prefix'], target.release_id)
    build_info = output / 'BuildInfo.cs'
    build_info.write_text('namespace InfiniteCanvas.Native { internal static class BuildInfo {\n'
        + 'internal const string CatalogSha = "' + hashlib.sha256(catalog_bytes).hexdigest() + '";\n'
        + 'internal const string BundleSha = "' + digest(output / 'bundle.zip') + '";\n'
        + 'internal const string TargetVersion = "' + policy['target_version'] + '";\n'
        + 'internal const int TargetSuffixLength = ' + str(suffix) + ';\n} }\n', encoding='utf-8')
    upgrade_name = policy['upgrader_filename']
    extra = [str(build_info), '/resource:' + str(catalog_resource) + ',Catalog',
             '/resource:' + str(output / 'bundle.zip') + ',Bundle', '/resource:' + str(index_path) + ',BundleIndex']
    for name in ('pass1', 'pass2'):
        compile_program(compiler, repo, output / name / upgrade_name, 'UpgradeProgram.cs', extra=extra)
    first_upgrade = output / 'pass1' / upgrade_name
    if first_upgrade.read_bytes() != (output / 'pass2' / upgrade_name).read_bytes():
        raise ValueError('NATIVE_UPGRADER_NOT_REPRODUCIBLE')
    (output / upgrade_name).write_bytes(first_upgrade.read_bytes())
    build_record = {'schema_version': 'enterprise-native-build-record-v1', 'source_commit': commit, 'source_tree': tree,
        'dirty_experimental_build': bool(status), 'policy_sha256': digest(policy_path),
        'catalog_sha256': digest(catalog_resource), 'bundle_sha256': digest(output / 'bundle.zip'),
        'compiler_package_sha256': digest(args.compiler_package), 'compiler_sha256': digest(compiler),
        'target_release_id': target.release_id, 'maximum_target_suffix_length': suffix,
        'deterministic_double_build': True, 'signed': False,
        'executables': [{'filename': name, 'sha256': digest(output / name), 'size_bytes': (output / name).stat().st_size}
                        for name in (launcher_name, upgrade_name)]}
    (output / 'unsigned-native-build-record.json').write_bytes(canonical_json(build_record))
    return build_record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--target-assets', type=Path, required=True)
    parser.add_argument('--compiler-package', type=Path, required=True)
    parser.add_argument('--compiler-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--allow-dirty', action='store_true', help='Local experiments only; never publish this build')
    print(json.dumps(build(parser.parse_args()), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
