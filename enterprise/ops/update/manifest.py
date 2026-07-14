"""Strict validation for the non-secret ops-release-manifest-v1 format."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from enterprise.ops.update.errors import ReleaseManifestError
from enterprise.ops.update.models import (
    ReleaseArchive,
    ReleaseCompatibility,
    ReleaseManifest,
    ReleasePackage,
)
from enterprise.ops.update.versions import parse_version


MANIFEST_SCHEMA_VERSION = "ops-release-manifest-v1"
MANIFEST_TOP_LEVEL_KEYS = {
    "schema_version",
    "release_version",
    "source_commit",
    "source_tree",
    "generated_at",
    "archive",
    "package",
    "compatibility",
    "release_notes",
}
ARCHIVE_KEYS = {"filename", "size_bytes", "sha256"}
PACKAGE_KEYS = {"file_count", "root_prefix"}
COMPATIBILITY_KEYS = {
    "minimum_current_version",
    "maximum_current_version",
    "requires_database_migration",
    "migration_ids",
}
LOWER_SHA1 = re.compile(r"^[0-9a-f]{40}$")
LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MIGRATION_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
MAX_RELEASE_NOTES_CHARS = 16 * 1024


def _require_exact_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        raise ReleaseManifestError(f"{label} fields are invalid")
    return value


def _required_text(value: object, label: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise ReleaseManifestError(f"{label} is invalid")
    return value


def _required_nonnegative_int(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ReleaseManifestError(f"{label} is invalid")
    return value


def _validate_utc_timestamp(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=32)
    if not text.endswith("Z"):
        raise ReleaseManifestError(f"{label} is invalid")
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ReleaseManifestError(f"{label} is invalid") from exc
    return text


def _validate_archive_filename(value: object, source_commit: str) -> str:
    filename = _required_text(value, "archive filename", maximum=256)
    if filename != PurePosixPath(filename).name or "\\" in filename or "/" in filename or ".." in filename:
        raise ReleaseManifestError("archive filename is invalid")
    expected = f"Infinite-Canvas-Enterprise-release-{source_commit}.zip"
    if filename != expected:
        raise ReleaseManifestError("archive filename does not bind the source commit")
    return filename


def _validate_root_prefix(value: object, source_commit: str) -> str:
    prefix = _required_text(value, "package root prefix", maximum=256)
    if prefix != PurePosixPath(prefix).name or "\\" in prefix or "/" in prefix or ".." in prefix:
        raise ReleaseManifestError("package root prefix is invalid")
    if prefix != f"Infinite-Canvas-Enterprise-{source_commit}":
        raise ReleaseManifestError("package root prefix does not bind the source commit")
    return prefix


def _parse_optional_version(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ReleaseManifestError(f"{label} is invalid")
    if not value:
        return ""
    try:
        return str(parse_version(value))
    except ValueError as exc:
        raise ReleaseManifestError(f"{label} is invalid") from exc


def parse_release_manifest(payload: object) -> ReleaseManifest:
    """Parse exactly the v1 schema, rejecting unknown or type-coerced fields."""
    raw = _require_exact_keys(payload, MANIFEST_TOP_LEVEL_KEYS, "manifest")
    if raw["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ReleaseManifestError("manifest schema version is unsupported")
    try:
        release_version = str(parse_version(raw["release_version"]))
    except ValueError as exc:
        raise ReleaseManifestError("release version is invalid") from exc
    source_commit = raw["source_commit"]
    source_tree = raw["source_tree"]
    if not isinstance(source_commit, str) or not LOWER_SHA1.fullmatch(source_commit):
        raise ReleaseManifestError("source commit is invalid")
    if not isinstance(source_tree, str) or not LOWER_SHA1.fullmatch(source_tree):
        raise ReleaseManifestError("source tree is invalid")
    generated_at = _validate_utc_timestamp(raw["generated_at"], "generated time")

    archive_raw = _require_exact_keys(raw["archive"], ARCHIVE_KEYS, "archive")
    archive_hash = archive_raw["sha256"]
    if not isinstance(archive_hash, str) or not LOWER_SHA256.fullmatch(archive_hash):
        raise ReleaseManifestError("archive SHA256 is invalid")
    archive = ReleaseArchive(
        filename=_validate_archive_filename(archive_raw["filename"], source_commit),
        size_bytes=_required_nonnegative_int(archive_raw["size_bytes"], "archive size", minimum=1),
        sha256=archive_hash,
    )

    package_raw = _require_exact_keys(raw["package"], PACKAGE_KEYS, "package")
    package = ReleasePackage(
        file_count=_required_nonnegative_int(package_raw["file_count"], "package file count", minimum=1),
        root_prefix=_validate_root_prefix(package_raw["root_prefix"], source_commit),
    )

    compatibility_raw = _require_exact_keys(raw["compatibility"], COMPATIBILITY_KEYS, "compatibility")
    requires_migration = compatibility_raw["requires_database_migration"]
    migration_ids = compatibility_raw["migration_ids"]
    if type(requires_migration) is not bool or type(migration_ids) is not list:
        raise ReleaseManifestError("compatibility values are invalid")
    if len(migration_ids) > 128 or any(
        not isinstance(item, str) or not MIGRATION_ID.fullmatch(item) for item in migration_ids
    ):
        raise ReleaseManifestError("migration identifiers are invalid")
    if (not requires_migration and migration_ids) or len(set(migration_ids)) != len(migration_ids):
        raise ReleaseManifestError("migration requirements are invalid")
    minimum_version = _parse_optional_version(compatibility_raw["minimum_current_version"], "minimum version")
    maximum_version = _parse_optional_version(compatibility_raw["maximum_current_version"], "maximum version")
    if minimum_version and maximum_version and parse_version(minimum_version) > parse_version(maximum_version):
        raise ReleaseManifestError("compatibility version range is invalid")
    release_notes = raw["release_notes"]
    if not isinstance(release_notes, str) or len(release_notes) > MAX_RELEASE_NOTES_CHARS:
        raise ReleaseManifestError("release notes are invalid")
    return ReleaseManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        release_version=release_version,
        source_commit=source_commit,
        source_tree=source_tree,
        generated_at=generated_at,
        archive=archive,
        package=package,
        compatibility=ReleaseCompatibility(
            minimum_current_version=minimum_version,
            maximum_current_version=maximum_version,
            requires_database_migration=requires_migration,
            migration_ids=tuple(migration_ids),
        ),
        release_notes=release_notes,
    )


def parse_release_manifest_bytes(data: bytes) -> ReleaseManifest:
    """Parse UTF-8 manifest bytes without permitting duplicate JSON keys."""
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ReleaseManifestError("manifest is not valid UTF-8 JSON") from exc
    return parse_release_manifest(payload)
