"""Real compiler/full public-payload checks, never a customer installation.

The Setup compilation sample is deliberately not executable installation
evidence. Published payload checks only run the native identity operation;
they do not execute Python, bind ports or call a provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from enterprise.install_entry import repair_fixed_entry, verify_entry_bundle
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.release_manifest_v2 import canonical_json, materialize_release_fixture
from enterprise.tests.test_ops_release_manifest_v2 import _fixture
from tools.build_install_ux_1 import _compile, _verify_toolchain

ROOT = Path(__file__).resolve().parents[2]


def required_path(name):
    value = os.environ.get(name)
    if os.name != "nt" or not value:
        pytest.skip("Windows verification requires " + name)
    path = Path(value)
    assert path.exists()
    return path


def test_pinned_inno_compiles_changed_pascal_and_shortcuts_twice(tmp_path):
    compiler = required_path("ICE_INNO_COMPILER")
    package = required_path("ICE_INNO_OFFICIAL_INSTALLER")
    policy = json.loads((ROOT / "installer/windows/inno-setup-toolchain-policy.json").read_bytes())
    _verify_toolchain(policy, compiler, package)
    native = required_path("ICE_NATIVE_ENTRY").parent
    entry = verify_entry_bundle(native)
    manifest, archive, inventory, document = _fixture(tmp_path / "compile-input")
    with zipfile.ZipFile(archive) as payload:
        archive_uncompressed = sum(info.file_size for info in payload.infolist())
    definitions = {
        "AppVersion": "2026.08.5", "ReleaseId": document["identity"]["release_id"],
        "ArchiveRootPrefix": document["archive"]["root_prefix"], "AssetDir": str(manifest.parent),
        "ArchiveUncompressedSize": str(archive_uncompressed),
        "MetadataPath": str(manifest), "NativeEntryDir": str(native),
        "OutputBaseFilename": "compile-contract-not-customer-setup",
        "NativeEntrySha256": entry.sha256, "NativeEntrySize": str(len(entry.data)),
        "NativeRecordSha256": entry.record_sha256,
        "NativeRecordSize": str((native / "native-entry-build-record.json").stat().st_size),
        "MetadataSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(), "MetadataSize": str(manifest.stat().st_size),
    }
    for name, path in (("Archive", archive), ("Manifest", manifest), ("Inventory", inventory)):
        definitions[name + "Filename"] = path.name
        definitions[name + "Sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        definitions[name + "Size"] = str(path.stat().st_size)
    outputs = []
    for label in ("compile-a", "compile-b"):
        output = tmp_path / label
        output.mkdir()
        _compile(iscc=compiler, script=ROOT / "installer/windows/InfiniteCanvasEnterprise.iss",
                 definitions=definitions | {"OutputDir": str(output)})
        outputs.append((output / (definitions["OutputBaseFilename"] + ".exe")).read_bytes())
    assert outputs[0] == outputs[1] and outputs[0].startswith(b"MZ")


@pytest.mark.parametrize("version", ["2026.09.5", "2026.09.9"])
def test_fixed_entry_repair_and_real_full_payload_identity_preserve_install(version, tmp_path):
    native = required_path("ICE_NATIVE_ENTRY")
    assets = required_path("ICE_ENTRY_RELEASE_ASSETS") / version
    manifest = assets / "ops-release-manifest-v2.json"
    document = json.loads(manifest.read_bytes())
    # Real full payload with Unicode/space paths, not the tiny worker fixture.
    # Unsupported deep paths have a separate pre-write rejection contract.
    root = tmp_path / "中文 安装"
    app = root / "releases" / document["identity"]["release_id"]
    materialize_release_fixture(manifest, assets / document["archive"]["filename"],
                                assets / "release-payload-inventory.json", app)
    for area in ("state", "data", "config", "素材"):
        (root / area).mkdir()
    (root / "data/enterprise.db").write_bytes(b"opaque never opened database fixture")
    (root / "data/canvas.json").write_bytes(b'{"fixture":"preserve"}\n')
    (root / "素材/image.bin").write_bytes(b"preserved media")
    (root / "config/enterprise.env").write_bytes(b"opaque preserve-only config")
    (root / "state/current-release.json").write_bytes(canonical_json({
        "schema_version": "env-1b1b-current-release-v1", "release_id": app.name,
        "app_root_relative": "releases/" + app.name,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "activated_at": "2026-10-05T00:00:00Z", "previous_release_id": None,
    }))
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in root.rglob("*") if path.is_file()}
    entry = verify_entry_bundle(native.parent)
    for _ in range(2):
        result = repair_fixed_entry(install_root=root, entry=entry, local_app_data_base=tmp_path / "local")
        assert result["database_changed"] is result["pointer_changed"] is False
        assert result["repair_state"] == "SUCCEEDED"
    started = time.monotonic()
    response_path = tmp_path / "identity.json"
    completed = subprocess.run([str(root / "InfiniteCanvas.exe"), "--identity", "--result-file", str(response_path)],
                               cwd=tmp_path, capture_output=True, timeout=120)
    identity_seconds = time.monotonic() - started
    result = json.loads(response_path.read_bytes())
    assert completed.returncode == 0 and result["result"] == "verified", result
    assert result["release_id"] == app.name
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in before.items())
    print("full-payload identity seconds", version, round(identity_seconds, 3))
    assert not (root / "state/system-update-active.lock").exists()
    roots = derive_portable_path_roots(PortableRootInputs(root, tmp_path / "local"), app.name)
    assert not (roots.RUNTIME_ROOT / "runtime-reconcile.lock").exists()
