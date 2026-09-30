#!/usr/bin/env python3
"""Build the deterministic one-click updater for the exact 09.6 security variant."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if os.fspath(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, os.fspath(REPOSITORY_ROOT))

from tools.build_install_ux_1 import (
    InstallerBuildError,
    _compile,
    _inspect_archive,
    _load_json,
    _require_clean_repo,
    _sha256,
    _verify_toolchain,
    _write_new_json,
)


POLICY_SCHEMA = "security-bridge-updater-build-policy-v1"
METADATA_SCHEMA = "security-bridge-updater-metadata-v1"
BUILD_RECORD_SCHEMA = "security-bridge-updater-build-record-v1"


def _asset_record(path: Path) -> dict[str, object]:
    digest, size = _sha256(path)
    return {"filename": path.name, "sha256": digest, "size_bytes": size}


def _maximum_materialized_suffix_length(archive: Path, root_prefix: str, release_id: str) -> int:
    """Return the longest target path suffix created before atomic publication.

    The 09.6 bundled Python is not long-path-aware.  Rejecting an unsafe install
    root in the GUI is preferable to failing part-way through archive expansion.
    """

    prefix = root_prefix.rstrip("/") + "/"
    longest = 0
    with zipfile.ZipFile(archive) as handle:
        for info in handle.infolist():
            if info.is_dir():
                continue
            name = info.filename
            relative = name[len(prefix) :] if name.startswith(prefix) else name
            longest = max(longest, len(relative.replace("/", "\\")))
    if longest <= 0:
        raise InstallerBuildError("SECURITY_BRIDGE_BUILD_RELEASE_ASSETS_INVALID")
    partial = f"releases\\.{release_id}.{'0' * 32}.partial\\"
    bootstrap_stage = f"staging\\workspace\\security-bridge-{release_id}-{'0' * 32}\\"
    return max(len(partial), len(bootstrap_stage)) + longest


def build(args: argparse.Namespace) -> dict[str, object]:
    repo = args.repo.resolve()
    release_dir = args.release_dir.resolve()
    output_root = args.output_root.resolve()
    iscc = args.iscc.resolve()
    official_installer = args.official_installer.resolve()
    if output_root.exists():
        raise InstallerBuildError("SECURITY_BRIDGE_BUILD_OUTPUT_EXISTS")
    output_root.mkdir(parents=True)
    commit, tree = _require_clean_repo(repo)

    sys.path.insert(0, os.fspath(repo))
    from enterprise.fresh_install import verify_release_assets
    from enterprise.release.release_manifest_v2 import verify_release_manifest_v2

    policy_path = repo / "installer" / "windows" / "096-bridge-updater-build-policy.json"
    tool_policy_path = repo / "installer" / "windows" / "inno-setup-toolchain-policy.json"
    script = repo / "installer" / "windows" / "InfiniteCanvasEnterprise096Bridge.iss"
    policy = _load_json(policy_path)
    tool_policy = _load_json(tool_policy_path)
    policy_hash = str(policy.pop("_source_sha256"))
    tool_policy.pop("_source_sha256")
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise InstallerBuildError("SECURITY_BRIDGE_BUILD_POLICY_INVALID")
    if tool_policy.get("schema_version") != "install-ux-1-inno-toolchain-policy-v1":
        raise InstallerBuildError("SECURITY_BRIDGE_BUILD_TOOLCHAIN_POLICY_INVALID")
    toolchain = _verify_toolchain(tool_policy, iscc, official_installer)

    archives = sorted(release_dir.glob("Infinite-Canvas-Enterprise-*-win-x64.zip"))
    manifest_source = release_dir / "ops-release-manifest-v2.json"
    inventory_source = release_dir / "release-payload-inventory.json"
    if (
        len(archives) != 1
        or not manifest_source.is_file()
        or not inventory_source.is_file()
    ):
        raise InstallerBuildError("SECURITY_BRIDGE_BUILD_RELEASE_ASSETS_INVALID")
    core_asset_root = output_root / "verified-core-assets"
    core_asset_root.mkdir()
    for source in (archives[0], manifest_source, inventory_source):
        shutil.copy2(source, core_asset_root / source.name)
    try:
        assets = verify_release_assets(core_asset_root)
    except Exception as exc:
        raise InstallerBuildError("SECURITY_BRIDGE_BUILD_RELEASE_ASSETS_INVALID") from exc
    verification = verify_release_manifest_v2(
        assets.manifest_path, assets.archive_path, assets.inventory_path
    )
    target_version = str(assets.manifest.section("identity")["release_version"])
    if target_version != policy["target_version"]:
        raise InstallerBuildError("SECURITY_BRIDGE_BUILD_TARGET_VERSION_MISMATCH")
    database_contract = assets.manifest.section("database_contract")
    if (
        database_contract.get("migration_compatibility") != "versioned-forward-migration"
        or database_contract.get("rollback_classification") != "database-backup-restore"
    ):
        raise InstallerBuildError("SECURITY_BRIDGE_BUILD_DATABASE_CONTRACT_INVALID")
    root_prefix, archive_files, archive_uncompressed = _inspect_archive(
        assets.archive_path,
        {
            "archive_safety": {
                "maximum_entries": 20000,
                "maximum_uncompressed_bytes": 4294967296,
            }
        },
    )
    maximum_materialized_suffix_length = _maximum_materialized_suffix_length(
        assets.archive_path, root_prefix, assets.manifest.release_id
    )
    bridge_path = repo / str(policy["bootstrap_asset"])
    if not bridge_path.is_file() or bridge_path.name != "apply_096_security_bridge.py":
        raise InstallerBuildError("SECURITY_BRIDGE_BUILD_BOOTSTRAP_MISSING")
    bridge_text = bridge_path.read_text(encoding="utf-8")
    if (
        str(policy["source_release_id"]) not in bridge_text
        or str(policy["source_manifest_sha256"]) not in bridge_text
        or 'TARGET_VERSION = "2026.09.9"' not in bridge_text
    ):
        raise InstallerBuildError("SECURITY_BRIDGE_BUILD_BOOTSTRAP_IDENTITY_MISMATCH")

    core_assets = [
        _asset_record(assets.archive_path),
        _asset_record(assets.manifest_path),
        _asset_record(assets.inventory_path),
        _asset_record(bridge_path),
    ]
    metadata: dict[str, object] = {
        "schema_version": METADATA_SCHEMA,
        "updater_commit": commit,
        "updater_tree": tree,
        "source_release_id": policy["source_release_id"],
        "source_manifest_sha256": policy["source_manifest_sha256"],
        "target_release_id": assets.manifest.release_id,
        "target_version": target_version,
        "target_enterprise_commit": assets.manifest.section("enterprise_source")["commit"],
        "target_payload_tree_sha256": verification.payload_tree_sha256,
        "archive_root_prefix": root_prefix,
        "archive_file_count": archive_files,
        "archive_uncompressed_bytes": archive_uncompressed,
        "maximum_materialized_suffix_length": maximum_materialized_suffix_length,
        "core_assets": core_assets,
        "build_policy_sha256": policy_hash,
        "production_approved": False,
    }
    metadata_path = output_root / "bridge-updater-metadata.json"
    _write_new_json(metadata_path, metadata)
    metadata_hash, metadata_size = _sha256(metadata_path)

    by_name = {str(item["filename"]): item for item in core_assets}
    archive_record = by_name[assets.archive_path.name]
    manifest_record = by_name[assets.manifest_path.name]
    inventory_record = by_name[assets.inventory_path.name]
    bridge_record = by_name[bridge_path.name]
    output_name = Path(str(policy["installer_filename"])).stem
    common = {
        "TargetVersion": target_version,
        "SourceReleaseId": str(policy["source_release_id"]),
        "SourceManifestSha256": str(policy["source_manifest_sha256"]),
        "SourcePythonSha256": str(policy["source_python_sha256"]),
        "TargetReleaseId": assets.manifest.release_id,
        "ArchiveFilename": assets.archive_path.name,
        "ArchiveSha256": str(archive_record["sha256"]),
        "ArchiveSize": str(archive_record["size_bytes"]),
        "ManifestFilename": assets.manifest_path.name,
        "ManifestSha256": str(manifest_record["sha256"]),
        "ManifestSize": str(manifest_record["size_bytes"]),
        "InventoryFilename": assets.inventory_path.name,
        "InventorySha256": str(inventory_record["sha256"]),
        "InventorySize": str(inventory_record["size_bytes"]),
        "BridgeBootstrapPath": os.fspath(bridge_path),
        "BridgeBootstrapFilename": bridge_path.name,
        "BridgeBootstrapSha256": str(bridge_record["sha256"]),
        "BridgeBootstrapSize": str(bridge_record["size_bytes"]),
        "MetadataPath": os.fspath(metadata_path),
        "MetadataSha256": metadata_hash,
        "MetadataSize": str(metadata_size),
        "DiagnosticsRelative": str(policy["diagnostics_relative"]).replace("/", "\\"),
        "MaximumMaterializedSuffixLength": str(maximum_materialized_suffix_length),
        "AssetDir": os.fspath(core_asset_root),
        "OutputBaseFilename": output_name,
    }
    built: list[Path] = []
    for label in ("compile-a", "compile-b"):
        output = output_root / label
        output.mkdir()
        _compile(iscc=iscc, script=script, definitions={**common, "OutputDir": os.fspath(output)})
        candidate = output / f"{output_name}.exe"
        if not candidate.is_file():
            raise InstallerBuildError("SECURITY_BRIDGE_BUILD_OUTPUT_MISSING")
        built.append(candidate)
    first_hash, first_size = _sha256(built[0])
    second_hash, second_size = _sha256(built[1])
    if (first_hash, first_size) != (second_hash, second_size):
        raise InstallerBuildError("SECURITY_BRIDGE_BUILD_NOT_REPRODUCIBLE")
    updater_path = output_root / str(policy["installer_filename"])
    shutil.copy2(built[0], updater_path)
    record = {
        "schema_version": BUILD_RECORD_SCHEMA,
        "updater_commit": commit,
        "updater_tree": tree,
        "source_release_id": policy["source_release_id"],
        "target_release_id": assets.manifest.release_id,
        "target_version": target_version,
        "unsigned_updater_filename": updater_path.name,
        "unsigned_updater_sha256": first_hash,
        "unsigned_updater_size_bytes": first_size,
        "unsigned_builds_identical": True,
        "authenticode_signed": False,
        "rfc3161_timestamped": False,
        "toolchain": toolchain,
        "production_approved": False,
    }
    _write_new_json(output_root / "unsigned-bridge-updater-build-record.json", record)
    return record


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo", type=Path, required=True)
    result.add_argument("--release-dir", type=Path, required=True)
    result.add_argument("--output-root", type=Path, required=True)
    result.add_argument("--iscc", type=Path, required=True)
    result.add_argument("--official-installer", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        payload = build(parser().parse_args(argv))
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except InstallerBuildError as exc:
        code = exc.code.split(":", 1)[0]
        print(json.dumps({"status": "blocked", "code": code}, sort_keys=True, separators=(",", ":")))
        return 2
    except Exception:
        print(json.dumps({"status": "blocked", "code": "SECURITY_BRIDGE_BUILD_INTERNAL_ERROR"}, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
