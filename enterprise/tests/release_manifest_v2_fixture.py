"""Small in-memory Release Manifest v2 fixtures for contract tests."""

from __future__ import annotations

from enterprise.release.release_manifest_v2 import canonical_json, parse_release_manifest_v2_bytes


SHA = "a" * 64
COMMIT = "b" * 40
TREE = "c" * 40


def release_manifest(*, release_id: str = "release-A", runtime_manifest_sha256: str = "c" * 64, python_version: str = "3.14.6", python_abi: str = "cp314", architecture: str = "x64"):
    # The parser requires the algorithm-derived release ID. Contract tests that
    # historically used release-A use an internal parsed object whose canonical
    # identity is then copied with that test-only release component.
    derived = "ice-2026.07.6-bbbbbbbbbbbb"
    payload = {
        "schema_version": "ops-release-manifest-v2",
        "identity": {"manifest_builder_version": "ops-release-manifest-v2-builder-v1", "release_id": derived, "release_version": "2026.07.6", "release_channel": "enterprise-portable", "source_date_epoch": 1},
        "enterprise_source": {"repository": "MEIS-DaCaiTou/Infinite-Canvas-Enterprise", "commit": COMMIT, "tree": TREE, "version": "2026.07.6", "version_file_sha256": SHA},
        "upstream_source": {"repository": "hero8152/Infinite-Canvas", "commit": "f1dd6834a72f3e7ff8340be05a84347d931e9cb9", "tree": "ebcc3b2df68aa6ee4f43ffd5f9fc392ac7d70dbc", "version": "2026.07.6", "version_file_sha256": "db54399b7b6be245825b48942db881ce40a183bd489ccab3973543c3b0deb065"},
        "archive": {"filename": f"Infinite-Canvas-Enterprise-{derived}-win-x64.zip", "root_prefix": f"Infinite-Canvas-Enterprise-{derived}", "size_bytes": 1, "sha256": SHA, "file_count": 2, "total_uncompressed_bytes": 2, "payload_tree_sha256": SHA, "inventory_sha256": SHA, "payload_excludes": ["release-manifest.json"]},
        "release_payload": {"inventory_schema": "ops-release-payload-inventory-v1", "inventory_path": "release-payload-inventory.json", "inventory_sha256": SHA, "tree_sha256": SHA, "file_count": 1, "total_size_bytes": 1, "static_tree_sha256": SHA, "app_source_tree_sha256": SHA, "embedded_manifest_path": "release-manifest.json", "archive_payload_excludes": ["release-manifest.json"]},
        "runtime": {"runtime_manifest_path": "runtime-manifest.json", "runtime_manifest_sha256": runtime_manifest_sha256, "runtime_manifest_schema": "enterprise-windows-runtime-manifest-v1", "python_version": python_version, "python_abi": python_abi, "architecture": architecture, "runtime_tree_sha256": SHA, "runtime_archive_sha256": SHA, "runtime_provenance_report_sha256": SHA, "runtime_source_policy_sha256": SHA, "requirements_lock_sha256": SHA, "wheelhouse_manifest_sha256": SHA, "installed_closure_sha256": SHA, "dependency_graph_sha256": SHA},
        "sbom": {"format": "CycloneDX", "spec_version": "1.6", "path": "evidence/sbom.json", "sha256": SHA, "component_count": 1, "dependency_edge_count": 0},
        "licenses": {"machine_inventory_path": "evidence/licenses.json", "machine_inventory_sha256": SHA, "human_notice_path": "THIRD-PARTY-LICENSES.txt", "human_notice_sha256": SHA, "component_count": 1, "unresolved_count": 0, "legal_review_complete": False, "inventory_complete": True},
        "static_build": {"builder_version": "fixture", "build_record_path": "evidence/static.json", "build_record_sha256": SHA, "source_tree_sha256": SHA, "output_tree_sha256": SHA, "html_build_id": SHA},
        "config_contract": {"schema_id": "enterprise-config-contract-v1", "schema_path": "evidence/config.json", "schema_sha256": SHA, "secret_values_embedded": False},
        "database_contract": {"schema_id": "enterprise-database-contract-v1", "schema_snapshot_path": "evidence/database.json", "schema_snapshot_sha256": SHA, "migration_ids": [], "migration_compatibility": "unclassified", "rollback_classification": "unclassified", "ops3b_activation_eligible": False},
        "compatibility": {"minimum_launcher_contract": 2, "minimum_runtime_contract": 2, "supported_platform": "windows", "supported_architecture": "x64", "portable_release_only": True},
    }
    parsed = parse_release_manifest_v2_bytes(canonical_json(payload))
    if release_id == derived:
        return parsed
    # Existing B1 tests exercise Windows-safe generic release components. The
    # trusted builder never takes this path; it is limited to unit fixtures.
    object.__setattr__(parsed, "_canonical", canonical_json({**parsed.data, "identity": {**parsed.section("identity"), "release_id": release_id}, "archive": {**parsed.section("archive"), "filename": f"Infinite-Canvas-Enterprise-{release_id}-win-x64.zip", "root_prefix": f"Infinite-Canvas-Enterprise-{release_id}"}}))
    return parsed


def preflight_v2_fields() -> dict[str, str]:
    return {"release_manifest_sha256": SHA, "release_payload_tree_sha256": SHA, "enterprise_commit": COMMIT, "enterprise_tree": TREE}


def portable_config_v2_fields() -> dict[str, str]:
    return preflight_v2_fields()


def runtime_identity_v2_fields() -> dict[str, str]:
    return {"portable_identity_schema": "env-1b1c-portable-runtime-identity-v2", **preflight_v2_fields()}
