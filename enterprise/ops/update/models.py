"""Typed, non-secret data models for OPS-3A release preparation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseMetadata:
    """Normalized trusted-provider metadata; it does not contain credentials."""

    provider: str
    repository: str
    release_id: str
    tag_name: str
    version: str
    prerelease: bool
    draft: bool
    published_at: str
    manifest_url: str
    archive_url: str
    release_notes: str


@dataclass(frozen=True)
class ReleaseArchive:
    filename: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ReleasePackage:
    file_count: int
    root_prefix: str


@dataclass(frozen=True)
class ReleaseCompatibility:
    minimum_current_version: str
    maximum_current_version: str
    requires_database_migration: bool
    migration_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: str
    release_version: str
    source_commit: str
    source_tree: str
    generated_at: str
    archive: ReleaseArchive
    package: ReleasePackage
    compatibility: ReleaseCompatibility
    release_notes: str
