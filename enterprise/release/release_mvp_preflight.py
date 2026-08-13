"""Fail-closed readiness checks for the first upgradeable Release assets."""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Iterable

from enterprise.ops.update.mvp import _database_contract_compatible
from enterprise.ops.update.versions import compare_versions, parse_version
from enterprise.release.release_manifest_v2 import (
    INVENTORY_MAX_BYTES,
    MANIFEST_MAX_BYTES,
    ReleaseManifestV2,
    read_release_manifest_v2,
    verify_release_manifest_v2,
)


EXPECTED_MANIFEST_NAME = "ops-release-manifest-v2.json"
EXPECTED_INVENTORY_NAME = "release-payload-inventory.json"
METADATA_NAME_BUDGET = 4 * 1024 * 1024
METADATA_ENTRY_LIMIT = 200_000


class ReleaseMvpPreflightError(RuntimeError):
    """Stable, public Gate A preflight failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise ReleaseMvpPreflightError(code)


def _require_absolute_file(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_file() or candidate.is_symlink():
        _fail("RELEASE_MVP_INPUT_INVALID")
    return candidate


def _read_bounded(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        raise ReleaseMvpPreflightError("RELEASE_MVP_INPUT_READ_FAILED") from exc
    if not data or len(data) > limit:
        _fail("RELEASE_MVP_INPUT_SIZE_INVALID")
    return data


def validate_versions(
    source_manifest: ReleaseManifestV2,
    target_manifest: ReleaseManifestV2,
    *,
    source_version: str,
    target_version: str,
    target_tag: str,
) -> None:
    try:
        parsed_source = parse_version(source_version)
        parsed_target = parse_version(target_version)
        parsed_tag = parse_version(target_tag)
    except ValueError as exc:
        raise ReleaseMvpPreflightError("RELEASE_MVP_VERSION_INVALID") from exc
    if compare_versions(str(parsed_source), str(parsed_target)) != "newer":
        _fail("RELEASE_MVP_VERSION_NOT_NEWER")
    if parsed_tag != parsed_target:
        _fail("RELEASE_MVP_TAG_VERSION_MISMATCH")
    if source_manifest.section("identity")["release_version"] != str(parsed_source):
        _fail("RELEASE_MVP_MANIFEST_VERSION_MISMATCH")
    if target_manifest.section("identity")["release_version"] != str(parsed_target):
        _fail("RELEASE_MVP_MANIFEST_VERSION_MISMATCH")


def validate_asset_set(manifest_path: Path, inventory_path: Path, archive_path: Path, manifest: ReleaseManifestV2) -> None:
    paths = tuple(_require_absolute_file(item) for item in (manifest_path, inventory_path, archive_path))
    parents = {item.parent.resolve() for item in paths}
    if len(parents) != 1:
        _fail("RELEASE_MVP_ASSET_SET_INVALID")
    expected_archive = str(manifest.section("archive")["filename"])
    expected_names = {EXPECTED_MANIFEST_NAME, EXPECTED_INVENTORY_NAME, expected_archive}
    if {item.name for item in paths} != expected_names:
        _fail("RELEASE_MVP_ASSET_SET_INVALID")
    try:
        actual_names = {item.name for item in paths[0].parent.iterdir() if item.is_file()}
        unexpected_directories = any(item.is_dir() for item in paths[0].parent.iterdir())
    except OSError as exc:
        raise ReleaseMvpPreflightError("RELEASE_MVP_ASSET_SET_INVALID") from exc
    if actual_names != expected_names or unexpected_directories:
        _fail("RELEASE_MVP_ASSET_SET_INVALID")


def validate_database_contract(source_manifest: ReleaseManifestV2, target_manifest: ReleaseManifestV2) -> None:
    if not _database_contract_compatible(source_manifest, target_manifest):
        _fail("RELEASE_MVP_DATABASE_CONTRACT_UNSUPPORTED")


_LEAK_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        rb"authorization\s*[:=]\s*(?:bearer|basic)\s+[^\s\"']+",
        rb"bearer\s+[a-z0-9._~+/=-]{16,}",
        rb"gh[pousr]_[a-z0-9]{20,}",
        rb"github_token",
        rb"eyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}",
        rb"(?:api[ _-]?key|provider[ _-]?(?:key|secret)|password|cookie|token)\s*[:=]\s*[^\s,;]{6,}",
        rb"[a-z]:\\(?:users|codeproject)\\",
        rb"review-artifacts",
    )
)


def _assert_no_leak(chunks: Iterable[bytes]) -> None:
    if any(pattern.search(chunk) for chunk in chunks for pattern in _LEAK_PATTERNS):
        _fail("RELEASE_MVP_SECRET_OR_LOCAL_PATH_LEAKAGE")


def scan_outer_asset_metadata(manifest_path: Path, inventory_path: Path, archive_path: Path) -> None:
    chunks = [
        manifest_path.name.encode("utf-8"),
        inventory_path.name.encode("utf-8"),
        archive_path.name.encode("utf-8"),
        _read_bounded(manifest_path, MANIFEST_MAX_BYTES),
        _read_bounded(inventory_path, INVENTORY_MAX_BYTES),
    ]
    name_bytes = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > METADATA_ENTRY_LIMIT:
                _fail("RELEASE_MVP_ARCHIVE_METADATA_INVALID")
            for info in infos:
                encoded = info.filename.encode("utf-8", errors="strict")
                name_bytes += len(encoded)
                if name_bytes > METADATA_NAME_BUDGET:
                    _fail("RELEASE_MVP_ARCHIVE_METADATA_INVALID")
                chunks.append(encoded)
    except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
        raise ReleaseMvpPreflightError("RELEASE_MVP_ARCHIVE_METADATA_INVALID") from exc
    _assert_no_leak(chunks)


def run_release_mvp_preflight(
    *,
    source_manifest_path: Path,
    manifest_path: Path,
    inventory_path: Path,
    archive_path: Path,
    source_version: str,
    target_version: str,
    target_tag: str,
) -> dict[str, object]:
    source_path = _require_absolute_file(source_manifest_path)
    target_manifest_path = _require_absolute_file(manifest_path)
    target_inventory_path = _require_absolute_file(inventory_path)
    target_archive_path = _require_absolute_file(archive_path)
    source_manifest = read_release_manifest_v2(source_path)
    target_manifest = read_release_manifest_v2(target_manifest_path)
    validate_asset_set(target_manifest_path, target_inventory_path, target_archive_path, target_manifest)
    scan_outer_asset_metadata(target_manifest_path, target_inventory_path, target_archive_path)
    validate_versions(
        source_manifest,
        target_manifest,
        source_version=source_version,
        target_version=target_version,
        target_tag=target_tag,
    )
    validate_database_contract(source_manifest, target_manifest)
    verification = verify_release_manifest_v2(target_manifest_path, target_archive_path, target_inventory_path)
    database = target_manifest.section("database_contract")
    return {
        "schema_version": "release-mvp-1-gate-a-preflight-v1",
        "status": "pass",
        "ready": True,
        "ready_for_github_release": True,
        "release_id": target_manifest.release_id,
        "source_version": source_version,
        "target_version": target_version,
        "target_tag": target_tag,
        "asset_count": 3,
        "expected_asset_count": 3,
        "missing_asset_count": 0,
        "unexpected_asset_count": 0,
        "archive_filename": target_archive_path.name,
        "archive_sha256": verification.archive_sha256,
        "manifest_sha256": verification.manifest_sha256,
        "inventory_sha256": verification.inventory_sha256,
        "payload_tree_sha256": verification.payload_tree_sha256,
        "database_schema_id": database["schema_id"],
        "database_schema_snapshot_sha256": database["schema_snapshot_sha256"],
        "migration_ids": list(database["migration_ids"]),
        "migration_compatibility": database["migration_compatibility"],
        "rollback_classification": database["rollback_classification"],
        "ops3b_activation_eligible": database["ops3b_activation_eligible"],
        "outer_metadata_leak_scan": "pass",
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
