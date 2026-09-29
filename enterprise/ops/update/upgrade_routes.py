"""Fail-closed, release-identity-bound upgrade path declarations.

This module only plans a path. Every hop must still pass the normal Manifest v2,
database, backup, and restart checks immediately before execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import asdict, dataclass
from typing import Iterable

from enterprise.ops.update.versions import parse_version


ROUTE_SCHEMA = "enterprise-upgrade-routes-v1"
ROUTE_ASSET_NAME = "upgrade-routes-v1.json"
MAX_ROUTE_BYTES = 64 * 1024
MAX_SOURCES = 32
MAX_HOPS = 8
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class UpgradeRouteError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ReleaseState:
    release_id: str
    version: str
    manifest_sha256: str
    database_schema_sha256: str
    updater_contract: int
    channel: str


@dataclass(frozen=True)
class AllowedSource:
    release_id: str
    version: str
    manifest_sha256: str
    database_schema_sha256: str
    minimum_updater_contract: int
    migration_mode: str


@dataclass(frozen=True)
class UpgradeRoutes:
    target: ReleaseState
    allowed_sources: tuple[AllowedSource, ...]


def _exact(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise UpgradeRouteError("UPGRADE_ROUTE_INVALID")
    return value


def _sha(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise UpgradeRouteError("UPGRADE_ROUTE_INVALID")
    return value


def _release(value: object) -> str:
    if type(value) is not str or _RELEASE_ID.fullmatch(value) is None:
        raise UpgradeRouteError("UPGRADE_ROUTE_INVALID")
    return value


def _version(value: object) -> str:
    try:
        parsed = parse_version(value)
    except ValueError as exc:
        raise UpgradeRouteError("UPGRADE_ROUTE_INVALID") from exc
    return str(parsed)


def _contract(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 100:
        raise UpgradeRouteError("UPGRADE_ROUTE_INVALID")
    return value


def parse_upgrade_routes(
    raw: bytes,
    *,
    expected_manifest_sha256: str,
    expected_release_id: str,
    expected_version: str,
    expected_channel: str,
) -> UpgradeRoutes:
    """Parse a canonical sidecar bound to one immutable Manifest v2 release."""
    if not raw or len(raw) > MAX_ROUTE_BYTES:
        raise UpgradeRouteError("UPGRADE_ROUTE_INVALID")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeRouteError("UPGRADE_ROUTE_INVALID") from exc
    document = _exact(payload, {"schema_version", "target", "allowed_sources"})
    if document["schema_version"] != ROUTE_SCHEMA:
        raise UpgradeRouteError("UPGRADE_ROUTE_INVALID")
    target = _exact(document["target"], {
        "release_id", "version", "manifest_sha256", "database_schema_sha256",
        "updater_contract", "channel",
    })
    state = ReleaseState(
        _release(target["release_id"]), _version(target["version"]),
        _sha(target["manifest_sha256"]), _sha(target["database_schema_sha256"]),
        _contract(target["updater_contract"]), target["channel"],
    )
    if type(state.channel) is not str or state.channel not in {"stable", "development"}:
        raise UpgradeRouteError("UPGRADE_ROUTE_INVALID")
    if (
        state.release_id != expected_release_id
        or state.version != expected_version
        or state.manifest_sha256 != _sha(expected_manifest_sha256)
        or state.channel != expected_channel
    ):
        raise UpgradeRouteError("UPGRADE_ROUTE_TARGET_MISMATCH")
    sources = document["allowed_sources"]
    if type(sources) is not list or not 1 <= len(sources) <= MAX_SOURCES:
        raise UpgradeRouteError("UPGRADE_ROUTE_INVALID")
    parsed_sources: list[AllowedSource] = []
    identities: set[tuple[str, str, str]] = set()
    for item in sources:
        source = _exact(item, {
            "release_id", "version", "manifest_sha256", "database_schema_sha256",
            "minimum_updater_contract", "migration_mode",
        })
        record = AllowedSource(
            _release(source["release_id"]), _version(source["version"]),
            _sha(source["manifest_sha256"]), _sha(source["database_schema_sha256"]),
            _contract(source["minimum_updater_contract"]), source["migration_mode"],
        )
        if (
            type(record.migration_mode) is not str
            or record.migration_mode not in {"same-schema-no-migration", "versioned-forward-migration"}
            or parse_version(record.version) >= parse_version(state.version)
            or (record.migration_mode == "same-schema-no-migration"
                and record.database_schema_sha256 != state.database_schema_sha256)
            or record.release_id == state.release_id
        ):
            raise UpgradeRouteError("UPGRADE_ROUTE_INVALID")
        identity = (record.release_id, record.manifest_sha256, record.database_schema_sha256)
        if identity in identities:
            raise UpgradeRouteError("UPGRADE_ROUTE_INVALID")
        identities.add(identity)
        parsed_sources.append(record)
    canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if raw != canonical:
        raise UpgradeRouteError("UPGRADE_ROUTE_NONCANONICAL")
    return UpgradeRoutes(state, tuple(parsed_sources))


def sidecar_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build_upgrade_routes(target: ReleaseState, allowed_sources: Iterable[AllowedSource]) -> bytes:
    """Render the exact public sidecar only after validating all declared edges."""
    document = {
        "schema_version": ROUTE_SCHEMA,
        "target": asdict(target),
        "allowed_sources": [asdict(item) for item in allowed_sources],
    }
    raw = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    parse_upgrade_routes(
        raw, expected_manifest_sha256=target.manifest_sha256,
        expected_release_id=target.release_id,
        expected_version=target.version, expected_channel=target.channel,
    )
    return raw


def plan_upgrade_path(
    installed: ReleaseState,
    target_release_id: str,
    releases: Iterable[UpgradeRoutes],
    *,
    allow_development: bool = False,
) -> tuple[ReleaseState, ...] | None:
    """Return shortest declared path, or None. Never infer edges by version alone."""
    if installed.release_id == target_release_id:
        return ()
    documents = tuple(releases)
    if len(documents) > 50 or len({doc.target.release_id for doc in documents}) != len(documents):
        raise UpgradeRouteError("UPGRADE_ROUTE_CATALOG_INVALID")
    queue: deque[tuple[ReleaseState, tuple[ReleaseState, ...]]] = deque([(installed, ())])
    seen = {(installed.release_id, installed.manifest_sha256, installed.database_schema_sha256)}
    while queue:
        current, path = queue.popleft()
        if len(path) >= MAX_HOPS:
            continue
        for document in documents:
            destination = document.target
            if destination.channel == "development" and not allow_development:
                continue
            if parse_version(destination.version) <= parse_version(current.version):
                continue
            if not any(
                source.release_id == current.release_id
                and source.version == current.version
                and source.manifest_sha256 == current.manifest_sha256
                and source.database_schema_sha256 == current.database_schema_sha256
                and current.updater_contract >= source.minimum_updater_contract
                for source in document.allowed_sources
            ):
                continue
            next_path = (*path, destination)
            if destination.release_id == target_release_id:
                return next_path
            key = (destination.release_id, destination.manifest_sha256, destination.database_schema_sha256)
            if key not in seen:
                seen.add(key)
                queue.append((destination, next_path))
    return None
