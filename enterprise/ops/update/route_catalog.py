"""Read route declarations from fixed GitHub assets without trusting release notes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

from enterprise.migrations.sqlite_existing import open_existing_sqlite
from enterprise.migrations.versioned import STATE_MISSING, STATE_READY, inspect_schema_metadata_connection, schema_objects, schema_snapshot_sha256
from enterprise.ops.update.models import ReleaseMetadataV2
from enterprise.ops.update.mvp import _database_evidence
from enterprise.ops.update.providers import GitHubReleasesProvider
from enterprise.ops.update.upgrade_routes import MAX_ROUTE_BYTES, ReleaseState, UpgradeRouteError, UpgradeRoutes, parse_upgrade_routes
from enterprise.release.release_manifest_v2 import MANIFEST_MAX_BYTES, ReleaseManifestV2, canonical_json, parse_release_manifest_v2_bytes


# This code can plan and verify route declarations. An installed release may
# advertise a lower contract in its own route asset; never infer that every
# historical release provides the current updater's capabilities.
UPDATER_ROUTE_CONTRACT = 3


def inspect_installed_route_state(
    *, app_root: Path, database_path: Path, manifest: ReleaseManifestV2,
) -> ReleaseState:
    """Refuse a path if the real database differs from this release's evidence."""
    evidence = _database_evidence(app_root, manifest)
    contract = manifest.section("database_contract")
    evidence_path = app_root / Path(*str(contract["schema_snapshot_path"]).split("/"))
    try:
        with evidence_path.open("rb") as source:
            evidence_raw = source.read(1024 * 1024 + 1)
    except OSError as exc:
        raise UpgradeRouteError("UPGRADE_ROUTE_SOURCE_DATABASE_UNVERIFIED") from exc
    if (
        len(evidence_raw) > 1024 * 1024
        or hashlib.sha256(evidence_raw).hexdigest() != contract["schema_snapshot_sha256"]
    ):
        raise UpgradeRouteError("UPGRADE_ROUTE_SOURCE_DATABASE_UNVERIFIED")
    try:
        with open_existing_sqlite(database_path, mode="ro", error_type=sqlite3.OperationalError) as conn:
            objects = schema_objects(conn)
            schema_sha = schema_snapshot_sha256(conn)
            inspection = inspect_schema_metadata_connection(conn)
    except sqlite3.Error as exc:
        raise UpgradeRouteError("UPGRADE_ROUTE_SOURCE_DATABASE_UNVERIFIED") from exc
    if "schema_version" in evidence:
        matched = (
            objects == evidence.get("objects")
            and schema_sha == evidence.get("schema_objects_sha256")
            and inspection.get("current_state") == STATE_READY
            and inspection.get("schema_version") == evidence.get("schema_version")
        )
    else:
        matched = objects == evidence.get("objects") and inspection.get("current_state") == STATE_MISSING
    if not matched:
        raise UpgradeRouteError("UPGRADE_ROUTE_SOURCE_DATABASE_UNVERIFIED")
    identity = manifest.section("identity")
    return ReleaseState(
        manifest.release_id, str(identity["release_version"]), manifest.raw_sha256,
        schema_sha, UPDATER_ROUTE_CONTRACT, "stable",
    )


def read_release_routes(provider: GitHubReleasesProvider, metadata: ReleaseMetadataV2) -> UpgradeRoutes | None:
    """Return a bound declaration, or None for older releases without a route asset."""
    route_url = metadata.upgrade_routes_url
    if route_url is None:
        return None
    if (
        metadata.upgrade_routes_size_bytes is None
        or metadata.upgrade_routes_sha256 is None
        or not 1 <= metadata.upgrade_routes_size_bytes <= MAX_ROUTE_BYTES
    ):
        raise UpgradeRouteError("UPGRADE_ROUTE_METADATA_INVALID")
    manifest_raw = provider.http_client.read_bytes(
        metadata.manifest_url,
        maximum_bytes=MANIFEST_MAX_BYTES,
        headers=provider.release_v2_asset_request_headers(metadata.manifest_url),
    )
    if len(manifest_raw) != metadata.manifest_size_bytes:
        raise UpgradeRouteError("UPGRADE_ROUTE_MANIFEST_MISMATCH")
    manifest = parse_release_manifest_v2_bytes(manifest_raw)
    if manifest.section("identity")["release_version"] != metadata.version:
        raise UpgradeRouteError("UPGRADE_ROUTE_MANIFEST_MISMATCH")
    route_raw = provider.http_client.read_bytes(
        route_url,
        maximum_bytes=MAX_ROUTE_BYTES,
        headers=provider.release_v2_asset_request_headers(route_url),
    )
    if (
        len(route_raw) != metadata.upgrade_routes_size_bytes
        or hashlib.sha256(route_raw).hexdigest() != metadata.upgrade_routes_sha256
    ):
        raise UpgradeRouteError("UPGRADE_ROUTE_DIGEST_MISMATCH")
    return parse_upgrade_routes(
        route_raw,
        expected_manifest_sha256=manifest.raw_sha256,
        expected_release_id=manifest.release_id,
        expected_version=metadata.version,
        expected_channel="development" if metadata.prerelease else "stable",
    )


def verify_target_route_schema(
    *, archive_path: Path, manifest: ReleaseManifestV2, routes: UpgradeRoutes,
) -> None:
    """Bind a declared target schema to the downloaded Release payload."""
    contract = manifest.section("database_contract")
    name = manifest.section("archive")["root_prefix"] + "/" + contract["schema_snapshot_path"]
    try:
        with zipfile.ZipFile(archive_path) as archive:
            info = archive.getinfo(name)
            if info.file_size > 1024 * 1024:
                raise UpgradeRouteError("UPGRADE_ROUTE_TARGET_SCHEMA_MISMATCH")
            with archive.open(info) as source:
                raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != contract["schema_snapshot_sha256"]:
            raise UpgradeRouteError("UPGRADE_ROUTE_TARGET_SCHEMA_MISMATCH")
        evidence = json.loads(raw)
        if type(evidence) is not dict or type(evidence.get("objects")) is not list:
            raise UpgradeRouteError("UPGRADE_ROUTE_TARGET_SCHEMA_MISMATCH")
        actual = hashlib.sha256(canonical_json(evidence["objects"])).hexdigest()
        if evidence.get("schema_objects_sha256", actual) != actual or actual != routes.target.database_schema_sha256:
            raise UpgradeRouteError("UPGRADE_ROUTE_TARGET_SCHEMA_MISMATCH")
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, UpgradeRouteError):
            raise
        raise UpgradeRouteError("UPGRADE_ROUTE_TARGET_SCHEMA_MISMATCH") from exc
