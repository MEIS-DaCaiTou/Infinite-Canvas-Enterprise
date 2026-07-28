from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from enterprise.release.release_manifest_v2 import (
    ReleaseManifestV2Error,
    build_inventory,
    canonical_json,
    derive_release_id,
    materialize_release_fixture,
    parse_release_manifest_v2_bytes,
    parse_inventory_bytes,
    sha256_bytes,
    sha256_file,
    verify_materialized_release,
    verify_release_manifest_v2,
)


SHA1 = "a" * 40
TREE = "b" * 40
SHA = "c" * 64


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    payload = tmp_path / "payload"
    static_content = b"<html>fixture</html>\n"
    static_digest = hashlib.sha256()
    static_relative = b"index.html"
    static_digest.update(b"file\0"); static_digest.update(len(static_relative).to_bytes(8, "big")); static_digest.update(static_relative)
    static_digest.update(len(static_content).to_bytes(8, "big")); static_digest.update(static_content)
    static_tree = static_digest.hexdigest()
    runtime_manifest = canonical_json({
        "schema_version": "enterprise-windows-runtime-manifest-v1",
        "python_version": "3.14.6",
        "python_abi": "cp314",
        "architecture": "x64",
    })
    provenance_report = canonical_json({
        "schema_version": "env-1b2p-runtime-provenance-report-v2",
        "overall_classification": "verified",
        "core_runtime_provenance_verified": True,
        "dependency_layer_rebuilt_and_verified": True,
        "archive_provenance_verified": True,
        "production_approved": False,
    })
    installed_closure = "1" * 64
    dependency_graph = "2" * 64
    installed_distributions = canonical_json({
        "schema_version": "env-1b2b-installed-distributions-v1",
        "installed_closure_sha256": installed_closure,
        "dependency_graph_sha256": dependency_graph,
        "distributions": [],
    })
    sbom = canonical_json({
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"component": {"bom-ref": "runtime", "name": "fixture runtime", "type": "application"}, "properties": [{"name": "dependency_graph_sha256", "value": dependency_graph}]},
        "components": [{"bom-ref": "fixture", "type": "application", "name": "fixture", "version": "1"}],
        "dependencies": [{"ref": "fixture", "dependsOn": []}, {"ref": "runtime", "dependsOn": ["fixture"]}],
    })
    licenses = canonical_json({
        "schema_version": "ops-third-party-license-inventory-v1",
        "inventory_complete": True,
        "unresolved_count": 0,
        "legal_review_complete": False,
        "components": [{"component": "fixture", "version": "1", "source": "fixture", "license_expression": "LicenseRef-Fixture", "license_text_sha256": "4" * 64, "evidence_type": "fixture", "payload_paths": ["VERSION"]}],
    })
    static_report = canonical_json({
        "schema_version": "env-1b1a-static-build-report-v2",
        "result": "pass",
        "builder_version": "env-1b1a-static-builder-v2",
        "source_tree_digest": SHA,
        "output_tree_digest": static_tree,
        "html_build_id": SHA,
    })
    config_contract = canonical_json({
        "schema_id": "enterprise-config-contract-v1",
        "secret_values_embedded": False,
        "keys": [{"key": "GATEWAY_PORT", "type": "integer", "required": True, "default_classification": "non-secret-default", "secret": False, "scope": "runtime", "validation": "1..65535"}],
    })
    database_contract = canonical_json({
        "schema_id": "enterprise-database-contract-v1",
        "migration_ids": [],
        "objects": [],
    })
    runtime_source_policy = canonical_json({"schema_version": "env-1b2a-python-source-v1", "version": "3.14.6", "python_abi": "cp314", "architecture": "x64", "ordinary_gil_build": True, "free_threaded": False})
    requirements_lock = b"fixture==1 --hash=sha256:" + b"3" * 64 + b"\n"
    wheelhouse_tree = "5" * 64
    wheelhouse_inventory = canonical_json({"schema_version": "env-1b2a-wheelhouse-sha256-v1", "target_python_abi": "cp314", "target_platform": "win_amd64", "invalid_wheel_count": 0, "tree_sha256": wheelhouse_tree, "files": []})
    app_source_root = tmp_path / "app-source"
    _write(app_source_root / "VERSION", b"2026.07.6\n")
    app_source_inventory = build_inventory(app_source_root)
    hashes = {
        "runtime-manifest.json": _write(payload / "runtime-manifest.json", runtime_manifest),
        "release-evidence/runtime-provenance-report.json": _write(payload / "release-evidence/runtime-provenance-report.json", provenance_report),
        "release-evidence/installed-distributions.json": _write(payload / "release-evidence/installed-distributions.json", installed_distributions),
        "release-evidence/runtime-source-policy.json": _write(payload / "release-evidence/runtime-source-policy.json", runtime_source_policy),
        "release-evidence/requirements.lock": _write(payload / "release-evidence/requirements.lock", requirements_lock),
        "release-evidence/wheelhouse-inventory.json": _write(payload / "release-evidence/wheelhouse-inventory.json", wheelhouse_inventory),
        "release-evidence/app-source-inventory.json": _write(payload / "release-evidence/app-source-inventory.json", app_source_inventory.canonical_bytes),
        "release-evidence/release-sbom.cdx.json": _write(payload / "release-evidence/release-sbom.cdx.json", sbom),
        "release-evidence/third-party-licenses.json": _write(payload / "release-evidence/third-party-licenses.json", licenses),
        "THIRD-PARTY-LICENSES.txt": _write(payload / "THIRD-PARTY-LICENSES.txt", b"notice\n"),
        "release-evidence/static-build-report.json": _write(payload / "release-evidence/static-build-report.json", static_report),
        "release-evidence/config-contract.json": _write(payload / "release-evidence/config-contract.json", config_contract),
        "release-evidence/database-schema.json": _write(payload / "release-evidence/database-schema.json", database_contract),
        "python/python.exe": _write(payload / "python/python.exe", b"python\n"),
        "static/index.html": _write(payload / "static/index.html", static_content),
        "VERSION": _write(payload / "VERSION", b"2026.07.6\n"),
    }
    runtime_tree_digest = hashlib.sha256()
    for entry in build_inventory(payload / "python").entries:
        encoded = entry.path.encode("utf-8")
        runtime_tree_digest.update(len(encoded).to_bytes(8, "big"))
        runtime_tree_digest.update(encoded)
        runtime_tree_digest.update(entry.size_bytes.to_bytes(8, "big"))
        runtime_tree_digest.update(bytes.fromhex(entry.sha256))
    runtime_tree = runtime_tree_digest.hexdigest()
    attestation = canonical_json({
        "schema_version": "env-1b2p-dependency-rebuild-attestation-v1", "result": "pass", "exit_code": 0,
        "network_download_count": 0, "runtime_tree_sha256": runtime_tree,
        "requirements_lock_sha256": hashes["release-evidence/requirements.lock"],
        "wheelhouse_manifest_sha256": hashes["release-evidence/wheelhouse-inventory.json"],
        "wheelhouse_tree_sha256": wheelhouse_tree, "installed_closure_sha256": installed_closure,
        "python_version": "3.14.6", "python_abi": "cp314", "architecture": "x64",
        "upstream_commit": "f1dd6834a72f3e7ff8340be05a84347d931e9cb9",
    })
    archive_record = canonical_json({
        "schema_version": "env-1b2p-archive-build-record-v1", "build_result": "pass", "exit_code": 0,
        "post_build_changes_detected": False, "runtime_tree_sha256": runtime_tree,
        "output_archive_sha256": SHA, "wheelhouse_manifest_sha256": hashes["release-evidence/wheelhouse-inventory.json"],
        "python_version": "3.14.6", "python_abi": "cp314",
        "upstream_commit": "f1dd6834a72f3e7ff8340be05a84347d931e9cb9",
    })
    hashes["release-evidence/dependency-rebuild-attestation.json"] = _write(payload / "release-evidence/dependency-rebuild-attestation.json", attestation)
    hashes["release-evidence/runtime-archive-build-record.json"] = _write(payload / "release-evidence/runtime-archive-build-record.json", archive_record)
    inventory = build_inventory(payload)
    inventory_path = tmp_path / "release-payload-inventory.json"
    inventory_path.write_bytes(inventory.canonical_bytes)
    (payload / inventory_path.name).write_bytes(inventory.canonical_bytes)
    release_id = derive_release_id("2026.07.6", SHA1)
    root = f"Infinite-Canvas-Enterprise-{release_id}"
    archive = tmp_path / f"{root}-win-x64.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        for entry in inventory.entries:
            output.write(payload / Path(entry.path), f"{root}/{entry.path}")
        output.write(payload / inventory_path.name, f"{root}/{inventory_path.name}")
    archive_hash, archive_size = sha256_file(archive)
    manifest: dict[str, object] = {
        "schema_version": "ops-release-manifest-v2",
        "identity": {"manifest_builder_version": "ops-release-manifest-v2-builder-v1", "release_id": release_id, "release_version": "2026.07.6", "release_channel": "enterprise-portable", "source_date_epoch": 1},
        "enterprise_source": {"repository": "MEIS-DaCaiTou/Infinite-Canvas-Enterprise", "commit": SHA1, "tree": TREE, "version": "2026.07.6", "version_file_sha256": hashes["VERSION"]},
        "upstream_source": {"repository": "hero8152/Infinite-Canvas", "commit": "f1dd6834a72f3e7ff8340be05a84347d931e9cb9", "tree": "ebcc3b2df68aa6ee4f43ffd5f9fc392ac7d70dbc", "version": "2026.07.6", "version_file_sha256": hashes["VERSION"]},
        "archive": {"filename": archive.name, "root_prefix": root, "size_bytes": archive_size, "sha256": archive_hash, "file_count": len(inventory.entries) + 1, "total_uncompressed_bytes": inventory.total_size_bytes + len(inventory.canonical_bytes), "payload_tree_sha256": inventory.tree_sha256, "inventory_sha256": inventory.sha256, "payload_excludes": ["release-manifest.json"]},
        "release_payload": {"inventory_schema": "ops-release-payload-inventory-v1", "inventory_path": inventory_path.name, "inventory_sha256": inventory.sha256, "tree_sha256": inventory.tree_sha256, "file_count": len(inventory.entries), "total_size_bytes": inventory.total_size_bytes, "static_tree_sha256": static_tree, "app_source_tree_sha256": app_source_inventory.tree_sha256, "embedded_manifest_path": "release-manifest.json", "archive_payload_excludes": ["release-manifest.json"]},
        "runtime": {"runtime_manifest_path": "runtime-manifest.json", "runtime_manifest_sha256": hashes["runtime-manifest.json"], "runtime_manifest_schema": "enterprise-windows-runtime-manifest-v1", "python_version": "3.14.6", "python_abi": "cp314", "architecture": "x64", "runtime_tree_sha256": runtime_tree, "runtime_archive_sha256": SHA, "runtime_provenance_report_sha256": hashes["release-evidence/runtime-provenance-report.json"], "runtime_source_policy_sha256": hashes["release-evidence/runtime-source-policy.json"], "requirements_lock_sha256": hashes["release-evidence/requirements.lock"], "wheelhouse_manifest_sha256": hashes["release-evidence/wheelhouse-inventory.json"], "installed_closure_sha256": installed_closure, "dependency_graph_sha256": dependency_graph},
        "sbom": {"format": "CycloneDX", "spec_version": "1.6", "path": "release-evidence/release-sbom.cdx.json", "sha256": hashes["release-evidence/release-sbom.cdx.json"], "component_count": 1, "dependency_edge_count": 1},
        "licenses": {"machine_inventory_path": "release-evidence/third-party-licenses.json", "machine_inventory_sha256": hashes["release-evidence/third-party-licenses.json"], "human_notice_path": "THIRD-PARTY-LICENSES.txt", "human_notice_sha256": hashes["THIRD-PARTY-LICENSES.txt"], "component_count": 1, "unresolved_count": 0, "legal_review_complete": False, "inventory_complete": True},
        "static_build": {"builder_version": "env-1b1a-static-builder-v2", "build_record_path": "release-evidence/static-build-report.json", "build_record_sha256": hashes["release-evidence/static-build-report.json"], "source_tree_sha256": SHA, "output_tree_sha256": static_tree, "html_build_id": SHA},
        "config_contract": {"schema_id": "enterprise-config-contract-v1", "schema_path": "release-evidence/config-contract.json", "schema_sha256": hashes["release-evidence/config-contract.json"], "secret_values_embedded": False},
        "database_contract": {"schema_id": "enterprise-database-contract-v1", "schema_snapshot_path": "release-evidence/database-schema.json", "schema_snapshot_sha256": hashes["release-evidence/database-schema.json"], "migration_ids": [], "migration_compatibility": "unclassified", "rollback_classification": "unclassified", "ops3b_activation_eligible": False},
        "compatibility": {"minimum_launcher_contract": 2, "minimum_runtime_contract": 2, "supported_platform": "windows", "supported_architecture": "x64", "portable_release_only": True},
    }
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_bytes(canonical_json(manifest))
    return manifest_path, archive, inventory_path, manifest


def _rebind_fixture(manifest_path: Path, archive: Path, inventory_path: Path, manifest: dict[str, object]) -> None:
    payload = manifest_path.parent / "payload"
    embedded_inventory = payload / inventory_path.name
    embedded_inventory.unlink()
    direct_bindings = {
        ("runtime", "runtime_manifest_sha256"): "runtime-manifest.json",
        ("runtime", "runtime_provenance_report_sha256"): "release-evidence/runtime-provenance-report.json",
        ("runtime", "runtime_source_policy_sha256"): "release-evidence/runtime-source-policy.json",
        ("runtime", "requirements_lock_sha256"): "release-evidence/requirements.lock",
        ("runtime", "wheelhouse_manifest_sha256"): "release-evidence/wheelhouse-inventory.json",
        ("sbom", "sha256"): "release-evidence/release-sbom.cdx.json",
        ("licenses", "machine_inventory_sha256"): "release-evidence/third-party-licenses.json",
        ("licenses", "human_notice_sha256"): "THIRD-PARTY-LICENSES.txt",
        ("static_build", "build_record_sha256"): "release-evidence/static-build-report.json",
        ("config_contract", "schema_sha256"): "release-evidence/config-contract.json",
        ("database_contract", "schema_snapshot_sha256"): "release-evidence/database-schema.json",
    }
    for (section, field), relative in direct_bindings.items():
        manifest[section][field] = sha256_file(payload / Path(relative))[0]  # type: ignore[index]
    inventory = build_inventory(payload)
    inventory_path.write_bytes(inventory.canonical_bytes)
    embedded_inventory.write_bytes(inventory.canonical_bytes)
    release_payload = manifest["release_payload"]
    release_payload.update({  # type: ignore[union-attr]
        "file_count": len(inventory.entries), "inventory_sha256": inventory.sha256,
        "total_size_bytes": inventory.total_size_bytes, "tree_sha256": inventory.tree_sha256,
    })
    if archive.exists():
        archive.unlink()
    root = manifest["archive"]["root_prefix"]  # type: ignore[index]
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        for entry in inventory.entries:
            output.write(payload / Path(entry.path), f"{root}/{entry.path}")
        output.write(embedded_inventory, f"{root}/{inventory_path.name}")
    archive_hash, archive_size = sha256_file(archive)
    manifest["archive"].update({  # type: ignore[union-attr]
        "file_count": len(inventory.entries) + 1, "inventory_sha256": inventory.sha256,
        "payload_tree_sha256": inventory.tree_sha256, "sha256": archive_hash,
        "size_bytes": archive_size, "total_uncompressed_bytes": inventory.total_size_bytes + len(inventory.canonical_bytes),
    })
    manifest_path.write_bytes(canonical_json(manifest))


def _mutate_json(path: Path, mutation) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload)
    path.write_bytes(canonical_json(payload))


def test_detached_manifest_v2_verifies_closed_archive(tmp_path: Path) -> None:
    manifest, archive, inventory, payload = _fixture(tmp_path)
    result = verify_release_manifest_v2(manifest, archive, inventory, expected_enterprise_commit=SHA1, expected_enterprise_tree=TREE)
    assert result.result == "pass"
    assert "release-manifest.json" not in zipfile.ZipFile(archive).namelist()
    assert parse_release_manifest_v2_bytes(manifest.read_bytes()).release_id == payload["identity"]["release_id"]


@pytest.mark.parametrize("mutation,code", [
    (lambda p: p.update(extra=True), "RELEASE_MANIFEST_FIELDS_INVALID"),
    (lambda p: p.__setitem__("schema_version", "ops-release-manifest-v1"), "RELEASE_MANIFEST_SCHEMA_INVALID"),
    (lambda p: p["identity"].__setitem__("release_id", "NUL"), "RELEASE_MANIFEST_RELEASE_ID_INVALID"),
    (lambda p: p["database_contract"].__setitem__("ops3b_activation_eligible", True), "RELEASE_DATABASE_CONTRACT_INVALID"),
    (lambda p: p["licenses"].__setitem__("unresolved_count", 1), "RELEASE_LICENSE_INVENTORY_INVALID"),
    (lambda p: p["config_contract"].__setitem__("secret_values_embedded", True), "RELEASE_CONFIG_CONTRACT_INVALID"),
])
def test_schema_tamper_fails_closed(tmp_path: Path, mutation, code: str) -> None:
    _, _, _, payload = _fixture(tmp_path)
    mutation(payload)
    with pytest.raises(ReleaseManifestV2Error, match=code):
        parse_release_manifest_v2_bytes(canonical_json(payload))


def test_noncanonical_duplicate_bom_and_oversize_rejected(tmp_path: Path) -> None:
    manifest, _, _, _ = _fixture(tmp_path)
    raw = manifest.read_bytes()
    with pytest.raises(ReleaseManifestV2Error, match="NONCANONICAL"):
        parse_release_manifest_v2_bytes(raw.replace(b'"archive":', b'"archive" :', 1))
    with pytest.raises(ReleaseManifestV2Error, match="BOM"):
        parse_release_manifest_v2_bytes(b"\xef\xbb\xbf" + raw)
    with pytest.raises(ReleaseManifestV2Error, match="SIZE"):
        parse_release_manifest_v2_bytes(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ReleaseManifestV2Error, match="DUPLICATE"):
        parse_release_manifest_v2_bytes(b'{"schema_version":"ops-release-manifest-v2","schema_version":"x"}\n')


def test_archive_extra_root_prefix_outsider_rejected_even_when_rehashed(tmp_path: Path) -> None:
    manifest, archive, inventory, payload = _fixture(tmp_path)
    with zipfile.ZipFile(archive, "a") as output:
        output.writestr("unexpected.exe", b"foreign")
    digest, size = sha256_file(archive)
    payload["archive"]["sha256"] = digest; payload["archive"]["size_bytes"] = size
    manifest.write_bytes(canonical_json(payload))
    with pytest.raises(ReleaseManifestV2Error, match="GLOBAL_INVENTORY"):
        verify_release_manifest_v2(manifest, archive, inventory)


def test_payload_tamper_inventory_omission_and_binding_fail(tmp_path: Path) -> None:
    manifest, archive, inventory, payload = _fixture(tmp_path)
    raw = json.loads(inventory.read_text(encoding="utf-8"))
    raw["entries"] = raw["entries"][:-1]
    inventory.write_bytes(canonical_json(raw))
    with pytest.raises(ReleaseManifestV2Error):
        verify_release_manifest_v2(manifest, archive, inventory)
    manifest, archive, inventory, payload = _fixture(tmp_path / "second")
    payload["runtime"]["runtime_manifest_sha256"] = "e" * 64
    manifest.write_bytes(canonical_json(payload))
    with pytest.raises(ReleaseManifestV2Error, match="CRITICAL_ARTIFACT"):
        verify_release_manifest_v2(manifest, archive, inventory)


@pytest.mark.parametrize("paths,code", [
    (["A.txt", "a.TXT"], "RELEASE_INVENTORY_PATH_DUPLICATE"),
    (["same.txt", "same.txt"], "RELEASE_INVENTORY_PATH_DUPLICATE"),
    (["../escape.txt"], "RELEASE_MANIFEST_PATH_INVALID"),
    (["asset.txt:stream"], "RELEASE_MANIFEST_PATH_INVALID"),
])
def test_inventory_windows_collision_traversal_and_ads_fail_closed(paths: list[str], code: str) -> None:
    entries = [{"path": path, "sha256": SHA, "size_bytes": 1} for path in paths]
    document = {"entries": entries, "file_count": len(entries), "schema_version": "ops-release-payload-inventory-v1", "total_size_bytes": len(entries), "tree_sha256": SHA}
    with pytest.raises(ReleaseManifestV2Error, match=code):
        parse_inventory_bytes(canonical_json(document))


@pytest.mark.parametrize("relative,mutation,code", [
    ("runtime-manifest.json", lambda value: value.__setitem__("python_version", "3.13.9"), "RELEASE_RUNTIME_EVIDENCE_CONTENT_INVALID"),
    ("release-evidence/runtime-provenance-report.json", lambda value: value.__setitem__("dependency_layer_rebuilt_and_verified", False), "RELEASE_RUNTIME_EVIDENCE_CONTENT_INVALID"),
    ("release-evidence/dependency-rebuild-attestation.json", lambda value: value.__setitem__("runtime_tree_sha256", "9" * 64), "RELEASE_RUNTIME_EVIDENCE_CONTENT_INVALID"),
    ("release-evidence/runtime-archive-build-record.json", lambda value: value.__setitem__("output_archive_sha256", "9" * 64), "RELEASE_RUNTIME_EVIDENCE_CONTENT_INVALID"),
    ("release-evidence/installed-distributions.json", lambda value: value.__setitem__("installed_closure_sha256", "9" * 64), "RELEASE_RUNTIME_EVIDENCE_CONTENT_INVALID"),
    ("release-evidence/wheelhouse-inventory.json", lambda value: value.__setitem__("invalid_wheel_count", 1), "RELEASE_RUNTIME_EVIDENCE_CONTENT_INVALID"),
    ("release-evidence/release-sbom.cdx.json", lambda value: value["metadata"]["properties"][0].__setitem__("value", "9" * 64), "RELEASE_SBOM_CONTENT_INVALID"),
    ("release-evidence/third-party-licenses.json", lambda value: value.__setitem__("unresolved_count", 1), "RELEASE_LICENSE_CONTENT_INVALID"),
    ("release-evidence/config-contract.json", lambda value: value.__setitem__("secret_values_embedded", True), "RELEASE_CONFIG_CONTENT_INVALID"),
    ("release-evidence/database-schema.json", lambda value: value["migration_ids"].append("foreign"), "RELEASE_DATABASE_CONTENT_INVALID"),
    ("release-evidence/static-build-report.json", lambda value: value.__setitem__("result", "fail"), "RELEASE_STATIC_CONTENT_INVALID"),
])
def test_semantic_artifact_tamper_fails_even_when_archive_inventory_and_hashes_are_rebound(tmp_path: Path, relative: str, mutation, code: str) -> None:
    manifest_path, archive, inventory_path, manifest = _fixture(tmp_path)
    _mutate_json(tmp_path / "payload" / Path(relative), mutation)
    _rebind_fixture(manifest_path, archive, inventory_path, manifest)
    with pytest.raises(ReleaseManifestV2Error, match=code):
        verify_release_manifest_v2(manifest_path, archive, inventory_path)


def test_version_and_expected_git_identity_mismatch_fail_closed(tmp_path: Path) -> None:
    manifest_path, archive, inventory_path, manifest = _fixture(tmp_path)
    (tmp_path / "payload" / "VERSION").write_text("2099.01.1\n", encoding="utf-8")
    _rebind_fixture(manifest_path, archive, inventory_path, manifest)
    with pytest.raises(ReleaseManifestV2Error, match="RELEASE_ENTERPRISE_VERSION_MISMATCH"):
        verify_release_manifest_v2(manifest_path, archive, inventory_path)
    manifest_path, archive, inventory_path, _ = _fixture(tmp_path / "identity")
    with pytest.raises(ReleaseManifestV2Error, match="RELEASE_ENTERPRISE_COMMIT_MISMATCH"):
        verify_release_manifest_v2(manifest_path, archive, inventory_path, expected_enterprise_commit="f" * 40)
    with pytest.raises(ReleaseManifestV2Error, match="RELEASE_ENTERPRISE_TREE_MISMATCH"):
        verify_release_manifest_v2(manifest_path, archive, inventory_path, expected_enterprise_tree="f" * 40)


def test_requirement_without_hash_cannot_be_promoted_by_rebinding(tmp_path: Path) -> None:
    manifest_path, archive, inventory_path, manifest = _fixture(tmp_path)
    lock_path = tmp_path / "payload/release-evidence/requirements.lock"
    lock_path.write_text("fixture==1\n", encoding="utf-8")
    lock_sha = sha256_file(lock_path)[0]
    _mutate_json(tmp_path / "payload/release-evidence/dependency-rebuild-attestation.json", lambda value: value.__setitem__("requirements_lock_sha256", lock_sha))
    _rebind_fixture(manifest_path, archive, inventory_path, manifest)
    with pytest.raises(ReleaseManifestV2Error, match="RELEASE_RUNTIME_EVIDENCE_CONTENT_INVALID"):
        verify_release_manifest_v2(manifest_path, archive, inventory_path)


def test_materialize_copies_exact_detached_manifest_and_verifies(tmp_path: Path) -> None:
    manifest, archive, inventory, _ = _fixture(tmp_path)
    app_root = tmp_path / "materialized" / "app"
    materialize_release_fixture(manifest, archive, inventory, app_root)
    assert (app_root / "release-manifest.json").read_bytes() == manifest.read_bytes()
    assert (app_root / inventory.name).read_bytes() == inventory.read_bytes()
    assert verify_materialized_release(app_root, inventory_path=app_root / inventory.name).result == "pass"
    (app_root / "unexpected.txt").write_text("tamper", encoding="utf-8")
    with pytest.raises(ReleaseManifestV2Error, match="MATERIALIZED_INVENTORY"):
        verify_materialized_release(app_root, inventory_path=app_root / inventory.name)


def test_materialized_inventory_must_remain_bound_to_detached_manifest(tmp_path: Path) -> None:
    manifest, archive, inventory, _ = _fixture(tmp_path)
    app_root = tmp_path / "materialized" / "app"
    materialize_release_fixture(manifest, archive, inventory, app_root)
    materialized_manifest = app_root / "release-manifest.json"
    manifest_bytes = materialized_manifest.read_bytes()
    materialized_manifest.unlink()
    (app_root / inventory.name).unlink()
    version_bytes = (app_root / "VERSION").read_bytes()
    (app_root / "VERSION").write_bytes(b"X" + version_bytes[1:])
    rebound_inventory = build_inventory(app_root)
    (app_root / inventory.name).write_bytes(rebound_inventory.canonical_bytes)
    materialized_manifest.write_bytes(manifest_bytes)
    with pytest.raises(ReleaseManifestV2Error) as exc:
        verify_materialized_release(app_root, inventory_path=app_root / inventory.name)
    assert exc.value.code == "RELEASE_INVENTORY_BINDING_INVALID"


def test_materialize_refuses_existing_destination(tmp_path: Path) -> None:
    manifest, archive, inventory, _ = _fixture(tmp_path)
    destination = tmp_path / "existing"; destination.mkdir()
    with pytest.raises(ReleaseManifestV2Error, match="DESTINATION_EXISTS"):
        materialize_release_fixture(manifest, archive, inventory, destination)


def test_release_id_is_fixed_by_version_and_commit() -> None:
    assert derive_release_id("2026.07.6", SHA1) == "ice-2026.07.6-aaaaaaaaaaaa"
    with pytest.raises(ReleaseManifestV2Error):
        derive_release_id("../release", SHA1)


def test_cli_rejects_relative_paths_with_one_sanitized_json_line() -> None:
    tool = Path(__file__).parents[2] / "tools/build_release_manifest_v2.py"
    result = subprocess.run([sys.executable, "-B", str(tool), "inspect", "--manifest", "relative.json"], capture_output=True, text=True)
    assert result.returncode == 2
    assert result.stderr == ""
    assert result.stdout.strip() == '{"code":"RELEASE_CLI_PATH_NOT_ABSOLUTE","status":"blocked"}'
    assert "Traceback" not in result.stdout
