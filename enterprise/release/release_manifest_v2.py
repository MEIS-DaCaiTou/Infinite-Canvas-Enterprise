"""Detached Release Manifest v2 parser, verifier, and materializer.

This module is intentionally separate from ``enterprise.ops.update.manifest``.
The latter is the frozen OPS-3A ``ops-release-manifest-v1`` protocol.  V2 is a
closed, detached Release payload contract used by the portable runtime trust
chain; it is not an activation protocol.
"""

from __future__ import annotations

import hashlib
import fnmatch
import json
import os
import re
import shutil
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Mapping

from enterprise.path_safety import (
    PathSafetyError,
    assert_no_reparse_ancestors,
    assert_path_within_root,
    lexical_path_state,
)


SCHEMA_VERSION = "ops-release-manifest-v2"
INVENTORY_SCHEMA_VERSION = "ops-release-payload-inventory-v1"
MANIFEST_MAX_BYTES = 2 * 1024 * 1024
INVENTORY_MAX_BYTES = 16 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024
MAX_FILES = 20_000
MAX_SINGLE_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
WINDOWS_REPARSE_POINT = 0x0400
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_ID = re.compile(r"^ice-[0-9]{4}\.[0-9]{2}\.[0-9]+-[0-9a-f]{12}$")
_DEVICE_NAMES = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))})
ENTERPRISE_REPOSITORY = "MEIS-DaCaiTou/Infinite-Canvas-Enterprise"
UPSTREAM_REPOSITORY = "hero8152/Infinite-Canvas"
UPSTREAM_COMMIT = "f1dd6834a72f3e7ff8340be05a84347d931e9cb9"
UPSTREAM_TREE = "ebcc3b2df68aa6ee4f43ffd5f9fc392ac7d70dbc"
UPSTREAM_VERSION = "2026.07.6"
UPSTREAM_VERSION_FILE_SHA256 = "db54399b7b6be245825b48942db881ce40a183bd489ccab3973543c3b0deb065"
_VALIDATED_MANIFEST_TOKEN = object()
PORTABLE_RELEASE_CONTRACT_VERSION = 2
PAYLOAD_POLICY_SCHEMA_VERSION = "ops-release-payload-policy-v1"
PAYLOAD_POLICY_PATH = "release-evidence/release-payload-policy.json"
CONFIG_OPERATOR_KEYS = frozenset({
    "GATEWAY_PORT", "UPSTREAM_PORT", "JWT_SECRET", "JWT_EXPIRE_HOURS",
    "ADMIN_USERNAME", "ADMIN_PASSWORD", "DB_PATH", "ENTERPRISE_REPO_URL",
    "ENTERPRISE_UPDATE_ENABLED", "ENTERPRISE_HIDE_UPSTREAM_AUTHOR",
    "ENTERPRISE_ENV", "ENTERPRISE_STRICT_SECURITY",
})

TOP_LEVEL_KEYS = frozenset({
    "schema_version", "identity", "enterprise_source", "upstream_source",
    "archive", "payload_policy", "release_payload", "runtime", "sbom", "licenses",
    "static_build", "config_contract", "database_contract", "compatibility",
})
SECTION_KEYS: dict[str, frozenset[str]] = {
    "identity": frozenset({"manifest_builder_version", "release_id", "release_version", "release_channel", "source_date_epoch"}),
    "enterprise_source": frozenset({"repository", "commit", "tree", "version", "version_file_sha256"}),
    "upstream_source": frozenset({"repository", "commit", "tree", "version", "version_file_sha256"}),
    "archive": frozenset({"filename", "root_prefix", "size_bytes", "sha256", "file_count", "total_uncompressed_bytes", "payload_tree_sha256", "inventory_sha256", "payload_excludes"}),
    "payload_policy": frozenset({"schema_version", "git_path", "git_blob_sha1", "payload_path", "sha256"}),
    "release_payload": frozenset({"inventory_schema", "inventory_path", "inventory_sha256", "tree_sha256", "file_count", "total_size_bytes", "static_tree_sha256", "app_source_tree_sha256", "embedded_manifest_path", "archive_payload_excludes"}),
    "runtime": frozenset({"runtime_manifest_path", "runtime_manifest_sha256", "runtime_manifest_schema", "python_version", "python_abi", "architecture", "runtime_tree_sha256", "runtime_archive_sha256", "runtime_provenance_report_sha256", "runtime_source_policy_sha256", "requirements_lock_sha256", "wheelhouse_manifest_sha256", "installed_closure_sha256", "dependency_graph_sha256"}),
    "sbom": frozenset({"format", "spec_version", "path", "sha256", "component_count", "dependency_edge_count"}),
    "licenses": frozenset({"machine_inventory_path", "machine_inventory_sha256", "component_policy_path", "component_policy_sha256", "human_notice_path", "human_notice_sha256", "component_count", "unresolved_count", "legal_review_complete", "inventory_complete"}),
    "static_build": frozenset({"builder_version", "build_record_path", "build_record_sha256", "source_tree_sha256", "output_tree_sha256", "html_build_id"}),
    "config_contract": frozenset({"schema_id", "schema_path", "schema_sha256", "secret_values_embedded"}),
    "database_contract": frozenset({"schema_id", "schema_snapshot_path", "schema_snapshot_sha256", "migration_ids", "migration_compatibility", "rollback_classification", "ops3b_activation_eligible"}),
    "compatibility": frozenset({"minimum_launcher_contract", "minimum_runtime_contract", "supported_platform", "supported_architecture", "portable_release_only"}),
}


class ReleaseManifestV2Error(RuntimeError):
    """Stable fail-closed error with no host path in its public code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _strip_windows_namespace(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\") and len(value) >= 7 and value[5] == ":" and value[6] in "\\/":
        return value[4:]
    return value


def _filesystem_path(path: Path) -> Path:
    """Use an extended Windows path for trusted, already-validated file I/O."""
    absolute = str(Path(path).absolute())
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def sha256_file(path: Path, *, maximum: int = MAX_SINGLE_FILE_BYTES) -> tuple[str, int]:
    digest = hashlib.sha256()
    received = 0
    try:
        with _filesystem_path(Path(path)).open("rb") as handle:
            while True:
                chunk = handle.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                received += len(chunk)
                if received > maximum:
                    raise ReleaseManifestV2Error("RELEASE_ARTIFACT_SIZE_INVALID")
                digest.update(chunk)
    except ReleaseManifestV2Error:
        raise
    except OSError as exc:
        raise ReleaseManifestV2Error("RELEASE_ARTIFACT_READ_FAILED") from exc
    return digest.hexdigest(), received


def _read_bounded(path: Path, maximum: int, *, missing: str, failed: str, oversized: str) -> bytes:
    try:
        handle: BinaryIO = _filesystem_path(Path(path)).open("rb")
    except FileNotFoundError as exc:
        raise ReleaseManifestV2Error(missing) from exc
    except OSError as exc:
        raise ReleaseManifestV2Error(failed) from exc
    data = bytearray()
    failure: OSError | None = None
    try:
        while len(data) <= maximum:
            chunk = handle.read(min(64 * 1024, maximum + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
    except OSError as exc:
        failure = exc
    try:
        handle.close()
    except OSError as exc:
        failure = failure or exc
    if failure is not None:
        raise ReleaseManifestV2Error(failed) from failure
    if not data or len(data) > maximum:
        raise ReleaseManifestV2Error(oversized)
    return bytes(data)


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseManifestV2Error("RELEASE_MANIFEST_DUPLICATE_KEY")
        result[key] = value
    return result


def _exact_dict(value: object, keys: frozenset[str], code: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ReleaseManifestV2Error(code)
    return value


def _sha(value: object, code: str = "RELEASE_MANIFEST_FIELD_INVALID") -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ReleaseManifestV2Error(code)
    return value


def _positive_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_FIELD_INVALID")
    return value


def _strict_positive_int(value: object, code: str) -> int:
    if type(value) is not int or value <= 0:
        raise ReleaseManifestV2Error(code)
    return value


def _assert_regular_file(path: Path, code: str) -> Path:
    candidate = Path(path)
    try:
        assert_no_reparse_ancestors(candidate)
        if lexical_path_state(candidate) != "regular" or not candidate.is_file():
            raise PathSafetyError("path-invalid")
    except (OSError, PathSafetyError) as exc:
        raise ReleaseManifestV2Error(code) from exc
    return candidate


def _assert_directory(path: Path, code: str, *, allow_missing: bool = False) -> Path:
    candidate = Path(path)
    try:
        assert_no_reparse_ancestors(candidate, allow_missing=allow_missing)
        state = lexical_path_state(candidate)
        if state == "missing" and allow_missing:
            return candidate
        if state != "regular" or not candidate.is_dir():
            raise PathSafetyError("path-invalid")
    except (OSError, PathSafetyError) as exc:
        raise ReleaseManifestV2Error(code) from exc
    return candidate


def assert_non_overlapping_roots(*roots: Path) -> None:
    normalized = [Path(os.path.abspath(os.fspath(item))) for item in roots]
    for index, left in enumerate(normalized):
        for right in normalized[index + 1:]:
            try:
                left_in_right = assert_path_within_root(left, right) == left
            except PathSafetyError:
                left_in_right = False
            try:
                right_in_left = assert_path_within_root(right, left) == right
            except PathSafetyError:
                right_in_left = False
            if left_in_right or right_in_left:
                raise ReleaseManifestV2Error("RELEASE_ROOT_OVERLAP_FORBIDDEN")


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 240 or "\\" in value or value.startswith(("/", "//")):
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_PATH_INVALID")
    if len(value) > 1 and value[1] == ":":
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_PATH_INVALID")
    parts = value.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_PATH_INVALID")
    for part in parts:
        if ":" in part or part.endswith((" ", ".")) or any(ord(c) < 32 or ord(c) == 127 for c in part):
            raise ReleaseManifestV2Error("RELEASE_MANIFEST_PATH_INVALID")
        if unicodedata.normalize("NFC", part).casefold().split(".", 1)[0] in _DEVICE_NAMES:
            raise ReleaseManifestV2Error("RELEASE_MANIFEST_PATH_INVALID")
    return "/".join(parts)


def _windows_key(value: str) -> str:
    return "/".join(unicodedata.normalize("NFC", part).casefold() for part in value.split("/"))


def _validate_payload_policy(value: object) -> dict[str, object]:
    keys = frozenset({
        "schema_version", "included_roots", "included_root_files",
        "excluded_globs", "runtime_destination", "static_destination",
        "source_static_root",
    })
    policy = _exact_dict(value, keys, "RELEASE_PAYLOAD_POLICY_INVALID")
    if (
        policy["schema_version"] != PAYLOAD_POLICY_SCHEMA_VERSION
        or policy["runtime_destination"] != "python"
        or policy["static_destination"] != "static"
    ):
        raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
    for field in ("included_roots", "included_root_files", "excluded_globs"):
        if type(policy[field]) is not list or not all(isinstance(item, str) and item for item in policy[field]):
            raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
    roots = [_safe_relative(item) for item in policy["included_roots"]]
    root_files = [_safe_relative(item) for item in policy["included_root_files"]]
    if any("/" in item for item in roots) or len({_windows_key(item) for item in roots}) != len(roots):
        raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
    if len({_windows_key(item) for item in root_files}) != len(root_files):
        raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
    if any(file == root or file.startswith(root + "/") for file in root_files for root in roots):
        raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
    source_static = _safe_relative(policy["source_static_root"])
    if source_static not in roots:
        raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
    if any(
        not isinstance(pattern, str)
        or not pattern
        or "\\" in pattern
        or pattern.startswith(("/", "//"))
        or ".." in pattern.split("/")
        for pattern in policy["excluded_globs"]
    ):
        raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
    return policy


def _policy_excluded(relative: str, globs: list[str]) -> bool:
    return any(
        fnmatch.fnmatchcase(relative, pattern)
        or fnmatch.fnmatchcase(relative + "/", pattern)
        for pattern in globs
    )


def _expected_app_source_paths(
    policy: dict[str, object], by_path: Mapping[str, InventoryEntry]
) -> set[str]:
    roots = list(policy["included_roots"])
    root_files = list(policy["included_root_files"])
    globs = list(policy["excluded_globs"])
    source_static = str(policy["source_static_root"])
    expected: set[str] = set()
    for relative in root_files:
        if _policy_excluded(relative, globs) or relative not in by_path:
            raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_CONTENT_INVALID")
        expected.add(relative)
    for root in roots:
        matching = {path for path in by_path if path.startswith(root + "/")}
        if not matching:
            raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_CONTENT_INVALID")
        if root == source_static:
            continue
        expected.update(path for path in matching if not _policy_excluded(path, globs))
    return expected


def _validate_third_party_component_policy(
    value: object, by_path: Mapping[str, InventoryEntry]
) -> dict[str, dict[str, object]]:
    policy = _exact_dict(
        value,
        frozenset({"schema_version", "components", "project_owned_payload_files"}),
        "RELEASE_LICENSE_POLICY_INVALID",
    )
    if policy["schema_version"] != "ops-third-party-component-policy-v1" or type(policy["components"]) is not list or type(policy["project_owned_payload_files"]) is not dict:
        raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
    result: dict[str, dict[str, object]] = {}
    covered: set[str] = set()
    keys = frozenset({"bom_ref", "name", "version", "source", "license_expression", "license_source_path", "payload_files"})
    for raw in policy["components"]:
        item = _exact_dict(raw, keys, "RELEASE_LICENSE_POLICY_INVALID")
        if not all(isinstance(item[key], str) and item[key] for key in keys - {"payload_files"}) or type(item["payload_files"]) is not dict or not item["payload_files"]:
            raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
        bom_ref = str(item["bom_ref"])
        if bom_ref in result:
            raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
        license_source = _safe_relative(item["license_source_path"])
        license_evidence_path = "release-evidence/licenses/" + Path(license_source).name
        if license_evidence_path not in by_path:
            raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
        files: dict[str, str] = {}
        for raw_path, raw_sha in item["payload_files"].items():
            path = _safe_relative(raw_path)
            digest = _sha(raw_sha, "RELEASE_LICENSE_POLICY_INVALID")
            if path in covered or path not in by_path or by_path[path].sha256 != digest:
                raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
            covered.add(path); files[path] = digest
        result[bom_ref] = {
            **item,
            "payload_files": files,
            "license_evidence_path": license_evidence_path,
        }
    project_owned: set[str] = set()
    for raw_path, raw_sha in policy["project_owned_payload_files"].items():
        path = _safe_relative(raw_path)
        digest = _sha(raw_sha, "RELEASE_LICENSE_POLICY_INVALID")
        if path in covered or path in project_owned or path not in by_path or by_path[path].sha256 != digest:
            raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
        project_owned.add(path)
    actual_vendor = {
        path for path in by_path
        if path.startswith("static/vendor/")
    }
    if covered | project_owned != actual_vendor:
        raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
    return result


def derive_release_id(version: str, enterprise_commit: str) -> str:
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]+", version):
        raise ReleaseManifestV2Error("RELEASE_VERSION_INVALID")
    if not isinstance(enterprise_commit, str) or not _SHA1.fullmatch(enterprise_commit):
        raise ReleaseManifestV2Error("RELEASE_ENTERPRISE_COMMIT_INVALID")
    return f"ice-{version}-{enterprise_commit[:12]}"


@dataclass(frozen=True)
class ReleaseManifestV2:
    _canonical: bytes
    raw_sha256: str
    _validation_token: object | None = None

    def __post_init__(self) -> None:
        if self._validation_token is not _VALIDATED_MANIFEST_TOKEN:
            raise ReleaseManifestV2Error("RELEASE_MANIFEST_UNVALIDATED_OBJECT")

    @property
    def data(self) -> dict[str, object]:
        return json.loads(self._canonical)

    def section(self, name: str) -> dict[str, object]:
        value = self.data[name]
        assert isinstance(value, dict)
        return value

    @property
    def release_id(self) -> str:
        return str(self.section("identity")["release_id"])

    @property
    def canonical_bytes(self) -> bytes:
        return self._canonical


def _validate_manifest(payload: object, raw: bytes) -> ReleaseManifestV2:
    top = _exact_dict(payload, TOP_LEVEL_KEYS, "RELEASE_MANIFEST_FIELDS_INVALID")
    if top["schema_version"] != SCHEMA_VERSION:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_SCHEMA_INVALID")
    sections = {name: _exact_dict(top[name], keys, "RELEASE_MANIFEST_FIELDS_INVALID") for name, keys in SECTION_KEYS.items()}
    identity = sections["identity"]
    enterprise = sections["enterprise_source"]
    upstream = sections["upstream_source"]
    if identity["manifest_builder_version"] != "ops-release-manifest-v2-builder-v1" or identity["release_channel"] != "enterprise-portable":
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_IDENTITY_INVALID")
    if type(identity["source_date_epoch"]) is not int or identity["source_date_epoch"] < 0:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_IDENTITY_INVALID")
    if identity["release_id"] != derive_release_id(str(identity["release_version"]), str(enterprise["commit"])):
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_RELEASE_ID_INVALID")
    if not _RELEASE_ID.fullmatch(str(identity["release_id"])):
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_RELEASE_ID_INVALID")
    for source in (enterprise, upstream):
        if not isinstance(source["repository"], str) or not source["repository"] or not _SHA1.fullmatch(str(source["commit"])) or not _SHA1.fullmatch(str(source["tree"])):
            raise ReleaseManifestV2Error("RELEASE_MANIFEST_SOURCE_INVALID")
        _sha(source["version_file_sha256"])
    if enterprise["repository"] != ENTERPRISE_REPOSITORY or enterprise["version"] != identity["release_version"]:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_SOURCE_INVALID")
    if upstream != {"repository": UPSTREAM_REPOSITORY, "commit": UPSTREAM_COMMIT, "tree": UPSTREAM_TREE, "version": UPSTREAM_VERSION, "version_file_sha256": UPSTREAM_VERSION_FILE_SHA256}:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_SOURCE_INVALID")
    archive = sections["archive"]
    policy = sections["payload_policy"]
    payload_section = sections["release_payload"]
    root = str(archive["root_prefix"])
    expected_root = f"Infinite-Canvas-Enterprise-{identity['release_id']}"
    if root != expected_root or archive["filename"] != f"{expected_root}-win-x64.zip":
        raise ReleaseManifestV2Error("RELEASE_ARCHIVE_IDENTITY_INVALID")
    for key in ("sha256", "payload_tree_sha256", "inventory_sha256"):
        _sha(archive[key])
    for key in ("size_bytes", "file_count", "total_uncompressed_bytes"):
        _positive_int(archive[key])
    if archive["payload_excludes"] != ["release-manifest.json"]:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_FIELD_INVALID")
    if (
        policy["schema_version"] != PAYLOAD_POLICY_SCHEMA_VERSION
        or policy["git_path"] != "release/windows/release-payload-policy.json"
        or policy["payload_path"] != PAYLOAD_POLICY_PATH
    ):
        raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
    if not _SHA1.fullmatch(str(policy["git_blob_sha1"])):
        raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
    _sha(policy["sha256"], "RELEASE_PAYLOAD_POLICY_INVALID")
    for key in ("inventory_sha256", "tree_sha256", "static_tree_sha256", "app_source_tree_sha256"):
        _sha(payload_section[key])
    for key in ("file_count", "total_size_bytes"):
        _positive_int(payload_section[key])
    if payload_section["inventory_schema"] != INVENTORY_SCHEMA_VERSION:
        raise ReleaseManifestV2Error("RELEASE_INVENTORY_SCHEMA_INVALID")
    _safe_relative(payload_section["inventory_path"])
    if payload_section["embedded_manifest_path"] != "release-manifest.json" or payload_section["archive_payload_excludes"] != ["release-manifest.json"]:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_FIELD_INVALID")
    if archive["inventory_sha256"] != payload_section["inventory_sha256"] or archive["payload_tree_sha256"] != payload_section["tree_sha256"] or archive["file_count"] != payload_section["file_count"] + 1 or archive["total_uncompressed_bytes"] <= payload_section["total_size_bytes"]:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_BINDING_INVALID")
    runtime = sections["runtime"]
    for key in ("runtime_manifest_path",):
        _safe_relative(runtime[key])
    for key in ("runtime_manifest_sha256", "runtime_tree_sha256", "runtime_archive_sha256", "runtime_provenance_report_sha256", "runtime_source_policy_sha256", "requirements_lock_sha256", "wheelhouse_manifest_sha256", "installed_closure_sha256", "dependency_graph_sha256"):
        _sha(runtime[key])
    if runtime["runtime_manifest_schema"] != "enterprise-windows-runtime-manifest-v1" or runtime["python_abi"] != "cp314" or runtime["architecture"] != "x64" or not str(runtime["python_version"]).startswith("3.14."):
        raise ReleaseManifestV2Error("RELEASE_RUNTIME_IDENTITY_INVALID")
    sbom = sections["sbom"]
    if sbom["format"] != "CycloneDX" or sbom["spec_version"] != "1.6":
        raise ReleaseManifestV2Error("RELEASE_SBOM_INVALID")
    _safe_relative(sbom["path"]); _sha(sbom["sha256"]); _positive_int(sbom["component_count"]); _positive_int(sbom["dependency_edge_count"])
    licenses = sections["licenses"]
    _safe_relative(licenses["machine_inventory_path"]); _safe_relative(licenses["component_policy_path"]); _safe_relative(licenses["human_notice_path"])
    _sha(licenses["machine_inventory_sha256"]); _sha(licenses["component_policy_sha256"]); _sha(licenses["human_notice_sha256"])
    if type(licenses["component_count"]) is not int or licenses["component_count"] < 1 or licenses["unresolved_count"] != 0 or licenses["legal_review_complete"] is not False or licenses["inventory_complete"] is not True:
        raise ReleaseManifestV2Error("RELEASE_LICENSE_INVENTORY_INVALID")
    static = sections["static_build"]
    _safe_relative(static["build_record_path"])
    for key in ("build_record_sha256", "source_tree_sha256", "output_tree_sha256", "html_build_id"):
        _sha(static[key])
    if payload_section["static_tree_sha256"] != static["output_tree_sha256"]:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_BINDING_INVALID")
    config = sections["config_contract"]
    _safe_relative(config["schema_path"]); _sha(config["schema_sha256"])
    if config["schema_id"] != "enterprise-config-contract-v1" or config["secret_values_embedded"] is not False:
        raise ReleaseManifestV2Error("RELEASE_CONFIG_CONTRACT_INVALID")
    database = sections["database_contract"]
    _safe_relative(database["schema_snapshot_path"]); _sha(database["schema_snapshot_sha256"])
    inactive_database_contract = (
        database["migration_compatibility"] == "unclassified"
        and database["rollback_classification"] == "unclassified"
        and database["ops3b_activation_eligible"] is False
    )
    online_update_database_contract = (
        database["migration_compatibility"] == "same-schema-no-migration"
        and database["rollback_classification"] == "code-release-pointer"
        and database["ops3b_activation_eligible"] is True
    )
    if (
        database["schema_id"] != "enterprise-database-contract-v1"
        or type(database["migration_ids"]) is not list
        or any(not isinstance(item, str) or not item for item in database["migration_ids"])
        or not (inactive_database_contract or online_update_database_contract)
    ):
        raise ReleaseManifestV2Error("RELEASE_DATABASE_CONTRACT_INVALID")
    compatibility = sections["compatibility"]
    _strict_positive_int(compatibility["minimum_launcher_contract"], "RELEASE_COMPATIBILITY_INVALID")
    _strict_positive_int(compatibility["minimum_runtime_contract"], "RELEASE_COMPATIBILITY_INVALID")
    if compatibility["supported_platform"] != "windows" or compatibility["supported_architecture"] != "x64" or compatibility["portable_release_only"] is not True:
        raise ReleaseManifestV2Error("RELEASE_COMPATIBILITY_INVALID")
    canonical = canonical_json(top)
    if raw != canonical:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_NONCANONICAL")
    return ReleaseManifestV2(canonical, sha256_bytes(raw), _VALIDATED_MANIFEST_TOKEN)


def parse_release_manifest_v2_bytes(data: bytes) -> ReleaseManifestV2:
    if not isinstance(data, bytes) or not data or len(data) > MANIFEST_MAX_BYTES:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_SIZE_INVALID")
    if data.startswith(b"\xef\xbb\xbf"):
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_BOM_FORBIDDEN")
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except ReleaseManifestV2Error:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_JSON_INVALID") from exc
    return _validate_manifest(payload, data)


def read_release_manifest_v2(path: Path) -> ReleaseManifestV2:
    candidate = Path(path)
    state = lexical_path_state(candidate)
    if state == "missing":
        raise ReleaseManifestV2Error("RELEASE_MANIFEST_MISSING")
    _assert_regular_file(candidate, "RELEASE_MANIFEST_REPARSE_FORBIDDEN")
    return parse_release_manifest_v2_bytes(_read_bounded(candidate, MANIFEST_MAX_BYTES, missing="RELEASE_MANIFEST_MISSING", failed="RELEASE_MANIFEST_READ_FAILED", oversized="RELEASE_MANIFEST_SIZE_INVALID"))


def enforce_portable_contract_compatibility(manifest: ReleaseManifestV2) -> None:
    compatibility = manifest.section("compatibility")
    if (
        compatibility["minimum_launcher_contract"] > PORTABLE_RELEASE_CONTRACT_VERSION
        or compatibility["minimum_runtime_contract"] > PORTABLE_RELEASE_CONTRACT_VERSION
    ):
        raise ReleaseManifestV2Error("RELEASE_COMPATIBILITY_UNSUPPORTED")


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    size_bytes: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "size_bytes": self.size_bytes}


@dataclass(frozen=True)
class ReleasePayloadInventory:
    entries: tuple[InventoryEntry, ...]
    tree_sha256: str
    total_size_bytes: int
    canonical_bytes: bytes

    @property
    def sha256(self) -> str:
        return sha256_bytes(self.canonical_bytes)


def payload_tree_sha256(entries: tuple[InventoryEntry, ...]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item.path):
        digest.update(entry.path.encode("utf-8") + b"\0" + str(entry.size_bytes).encode("ascii") + b"\0" + entry.sha256.encode("ascii") + b"\n")
    return digest.hexdigest()


def build_inventory(root: Path) -> ReleasePayloadInventory:
    logical_root = Path(root)
    _assert_directory(logical_root, "RELEASE_PAYLOAD_ROOT_INVALID")
    root = _filesystem_path(logical_root)
    entries: list[InventoryEntry] = []
    seen: set[str] = set()
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        relative = _safe_relative(path.relative_to(root).as_posix())
        key = _windows_key(relative)
        if key in seen:
            raise ReleaseManifestV2Error("RELEASE_PAYLOAD_PATH_COLLISION")
        seen.add(key)
        try:
            mode = path.lstat().st_mode
            attrs = getattr(path.lstat(), "st_file_attributes", 0)
        except OSError as exc:
            raise ReleaseManifestV2Error("RELEASE_PAYLOAD_READ_FAILED") from exc
        if stat.S_ISLNK(mode) or attrs & WINDOWS_REPARSE_POINT:
            raise ReleaseManifestV2Error("RELEASE_PAYLOAD_REPARSE_FORBIDDEN")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ReleaseManifestV2Error("RELEASE_PAYLOAD_FILE_TYPE_INVALID")
        digest, size = sha256_file(path)
        entries.append(InventoryEntry(relative, size, digest))
        if len(entries) > MAX_FILES or sum(item.size_bytes for item in entries) > MAX_TOTAL_BYTES:
            raise ReleaseManifestV2Error("RELEASE_PAYLOAD_LIMIT_EXCEEDED")
    ordered = tuple(entries)
    tree = payload_tree_sha256(ordered)
    total = sum(item.size_bytes for item in ordered)
    document = {"entries": [item.as_dict() for item in ordered], "file_count": len(ordered), "schema_version": INVENTORY_SCHEMA_VERSION, "total_size_bytes": total, "tree_sha256": tree}
    return ReleasePayloadInventory(ordered, tree, total, canonical_json(document))


def parse_inventory_bytes(data: bytes) -> ReleasePayloadInventory:
    if not data or len(data) > INVENTORY_MAX_BYTES or data.startswith(b"\xef\xbb\xbf"):
        raise ReleaseManifestV2Error("RELEASE_INVENTORY_INVALID")
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except Exception as exc:
        if isinstance(exc, ReleaseManifestV2Error):
            raise
        raise ReleaseManifestV2Error("RELEASE_INVENTORY_INVALID") from exc
    top = _exact_dict(payload, frozenset({"schema_version", "entries", "file_count", "total_size_bytes", "tree_sha256"}), "RELEASE_INVENTORY_INVALID")
    if top["schema_version"] != INVENTORY_SCHEMA_VERSION or type(top["entries"]) is not list or type(top["file_count"]) is not int or type(top["total_size_bytes"]) is not int:
        raise ReleaseManifestV2Error("RELEASE_INVENTORY_INVALID")
    entries: list[InventoryEntry] = []
    keys: set[str] = set()
    for raw in top["entries"]:
        record = _exact_dict(raw, frozenset({"path", "size_bytes", "sha256"}), "RELEASE_INVENTORY_INVALID")
        path = _safe_relative(record["path"]); key = _windows_key(path)
        if key in keys:
            raise ReleaseManifestV2Error("RELEASE_INVENTORY_PATH_DUPLICATE")
        keys.add(key)
        entries.append(InventoryEntry(path, _positive_int(record["size_bytes"]), _sha(record["sha256"])))
        if record["size_bytes"] > MAX_SINGLE_FILE_BYTES or len(entries) > MAX_FILES:
            raise ReleaseManifestV2Error("RELEASE_PAYLOAD_LIMIT_EXCEEDED")
    if tuple(item.path for item in entries) != tuple(sorted(item.path for item in entries)):
        raise ReleaseManifestV2Error("RELEASE_INVENTORY_NONCANONICAL")
    ordered = tuple(entries)
    tree = payload_tree_sha256(ordered); total = sum(item.size_bytes for item in ordered)
    if total > MAX_TOTAL_BYTES:
        raise ReleaseManifestV2Error("RELEASE_PAYLOAD_LIMIT_EXCEEDED")
    if top["file_count"] != len(ordered) or top["total_size_bytes"] != total or top["tree_sha256"] != tree or data != canonical_json(top):
        raise ReleaseManifestV2Error("RELEASE_INVENTORY_BINDING_INVALID")
    return ReleasePayloadInventory(ordered, tree, total, data)


@dataclass(frozen=True)
class ReleaseVerificationResult:
    result: str
    manifest_sha256: str
    archive_sha256: str
    inventory_sha256: str
    payload_tree_sha256: str
    file_count: int
    total_size_bytes: int

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def _zip_entry_unsafe(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)
    return kind not in {0, stat.S_IFREG, stat.S_IFDIR} or stat.S_ISLNK(mode) or bool(info.external_attr & WINDOWS_REPARSE_POINT)


def _static_tree_digest_from_archive(archive_path: Path, root_prefix: str, inventory: ReleasePayloadInventory) -> str:
    static_entries = [item for item in inventory.entries if item.path.startswith("static/")]
    if not static_entries:
        raise ReleaseManifestV2Error("RELEASE_STATIC_CONTENT_INVALID")
    directories: set[str] = set()
    for item in static_entries:
        relative = item.path[len("static/"):]
        parts = relative.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            directories.add("/".join(parts[:index]))
    digest = hashlib.sha256()
    for relative in sorted(directories):
        encoded = relative.encode("utf-8")
        digest.update(b"directory\0"); digest.update(len(encoded).to_bytes(8, "big")); digest.update(encoded)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for item in sorted(static_entries, key=lambda value: value.path):
                relative = item.path[len("static/"):]
                with archive.open(f"{root_prefix}/{item.path}") as handle:
                    content = handle.read(item.size_bytes + 1)
                if len(content) != item.size_bytes:
                    raise ReleaseManifestV2Error("RELEASE_STATIC_CONTENT_INVALID")
                encoded = relative.encode("utf-8")
                digest.update(b"file\0"); digest.update(len(encoded).to_bytes(8, "big")); digest.update(encoded)
                digest.update(len(content).to_bytes(8, "big")); digest.update(content)
    except ReleaseManifestV2Error:
        raise
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise ReleaseManifestV2Error("RELEASE_STATIC_CONTENT_INVALID") from exc
    return digest.hexdigest()


def verify_release_manifest_v2(manifest_path: Path, archive_path: Path, inventory_path: Path, *, expected_enterprise_commit: str | None = None, expected_enterprise_tree: str | None = None) -> ReleaseVerificationResult:
    _assert_regular_file(Path(manifest_path), "RELEASE_MANIFEST_REPARSE_FORBIDDEN")
    _assert_regular_file(Path(archive_path), "RELEASE_ARCHIVE_PATH_INVALID")
    _assert_regular_file(Path(inventory_path), "RELEASE_INVENTORY_PATH_INVALID")
    manifest = read_release_manifest_v2(manifest_path)
    data = manifest.data; archive_section = manifest.section("archive"); payload_section = manifest.section("release_payload")
    enterprise = manifest.section("enterprise_source")
    if expected_enterprise_commit is not None and enterprise["commit"] != expected_enterprise_commit:
        raise ReleaseManifestV2Error("RELEASE_ENTERPRISE_COMMIT_MISMATCH")
    if expected_enterprise_tree is not None and enterprise["tree"] != expected_enterprise_tree:
        raise ReleaseManifestV2Error("RELEASE_ENTERPRISE_TREE_MISMATCH")
    inventory_raw = _read_bounded(inventory_path, INVENTORY_MAX_BYTES, missing="RELEASE_INVENTORY_MISSING", failed="RELEASE_INVENTORY_READ_FAILED", oversized="RELEASE_INVENTORY_INVALID")
    inventory = parse_inventory_bytes(inventory_raw)
    if inventory.sha256 != payload_section["inventory_sha256"] or inventory.tree_sha256 != payload_section["tree_sha256"] or len(inventory.entries) != payload_section["file_count"] or inventory.total_size_bytes != payload_section["total_size_bytes"]:
        raise ReleaseManifestV2Error("RELEASE_INVENTORY_BINDING_INVALID")
    archive_hash, archive_size = sha256_file(archive_path, maximum=MAX_TOTAL_BYTES)
    if archive_hash != archive_section["sha256"] or archive_size != archive_section["size_bytes"]:
        raise ReleaseManifestV2Error("RELEASE_ARCHIVE_HASH_MISMATCH")
    expected = {f"{archive_section['root_prefix']}/{item.path}": item for item in inventory.entries}
    embedded_inventory = InventoryEntry(str(payload_section["inventory_path"]), len(inventory_raw), inventory.sha256)
    expected[f"{archive_section['root_prefix']}/{embedded_inventory.path}"] = embedded_inventory
    seen: dict[str, str] = {}
    total = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            files = []
            for info in archive.infolist():
                name = info.filename.rstrip("/")
                if info.is_dir():
                    continue
                canonical = _safe_relative(name)
                key = _windows_key(canonical)
                if key in seen:
                    raise ReleaseManifestV2Error("RELEASE_ARCHIVE_PATH_DUPLICATE")
                seen[key] = canonical
                if _zip_entry_unsafe(info):
                    raise ReleaseManifestV2Error("RELEASE_ARCHIVE_ENTRY_INVALID")
                files.append((info, canonical))
            if set(name for _, name in files) != set(expected):
                raise ReleaseManifestV2Error("RELEASE_ARCHIVE_GLOBAL_INVENTORY_MISMATCH")
            for info, name in files:
                record = expected[name]
                if info.file_size != record.size_bytes:
                    raise ReleaseManifestV2Error("RELEASE_ARCHIVE_FILE_MISMATCH")
                digest = hashlib.sha256(); received = 0
                with archive.open(info) as handle:
                    while True:
                        chunk = handle.read(COPY_CHUNK_BYTES)
                        if not chunk: break
                        received += len(chunk); digest.update(chunk)
                if received != record.size_bytes or digest.hexdigest() != record.sha256:
                    raise ReleaseManifestV2Error("RELEASE_ARCHIVE_FILE_MISMATCH")
                total += received
    except ReleaseManifestV2Error:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReleaseManifestV2Error("RELEASE_ARCHIVE_READ_FAILED") from exc
    if len(expected) != archive_section["file_count"] or total != archive_section["total_uncompressed_bytes"] or total != inventory.total_size_bytes + len(inventory_raw):
        raise ReleaseManifestV2Error("RELEASE_ARCHIVE_BINDING_INVALID")
    # Every critical payload artifact is independently SHA-bound.
    by_path = {entry.path: entry for entry in inventory.entries}
    if "VERSION" not in by_path or by_path["VERSION"].sha256 != enterprise["version_file_sha256"]:
        raise ReleaseManifestV2Error("RELEASE_ENTERPRISE_VERSION_MISMATCH")
    bindings = {
        str(manifest.section("payload_policy")["payload_path"]): str(manifest.section("payload_policy")["sha256"]),
        str(manifest.section("runtime")["runtime_manifest_path"]): str(manifest.section("runtime")["runtime_manifest_sha256"]),
        str(manifest.section("sbom")["path"]): str(manifest.section("sbom")["sha256"]),
        str(manifest.section("licenses")["machine_inventory_path"]): str(manifest.section("licenses")["machine_inventory_sha256"]),
        str(manifest.section("licenses")["component_policy_path"]): str(manifest.section("licenses")["component_policy_sha256"]),
        str(manifest.section("licenses")["human_notice_path"]): str(manifest.section("licenses")["human_notice_sha256"]),
        str(manifest.section("static_build")["build_record_path"]): str(manifest.section("static_build")["build_record_sha256"]),
        str(manifest.section("config_contract")["schema_path"]): str(manifest.section("config_contract")["schema_sha256"]),
        str(manifest.section("database_contract")["schema_snapshot_path"]): str(manifest.section("database_contract")["schema_snapshot_sha256"]),
        "release-evidence/runtime-provenance-report.json": str(manifest.section("runtime")["runtime_provenance_report_sha256"]),
        "release-evidence/runtime-source-policy.json": str(manifest.section("runtime")["runtime_source_policy_sha256"]),
        "release-evidence/requirements.lock": str(manifest.section("runtime")["requirements_lock_sha256"]),
        "release-evidence/wheelhouse-inventory.json": str(manifest.section("runtime")["wheelhouse_manifest_sha256"]),
    }
    if any(path not in by_path or by_path[path].sha256 != digest for path, digest in bindings.items()):
        raise ReleaseManifestV2Error("RELEASE_CRITICAL_ARTIFACT_BINDING_INVALID")
    prefix = str(archive_section["root_prefix"]) + "/"
    def artifact_bytes(relative: str, maximum: int = 16 * 1024 * 1024) -> bytes:
        try:
            with zipfile.ZipFile(archive_path) as source, source.open(prefix + relative) as handle:
                data = handle.read(maximum + 1)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise ReleaseManifestV2Error("RELEASE_CRITICAL_ARTIFACT_READ_FAILED") from exc
        if len(data) > maximum:
            raise ReleaseManifestV2Error("RELEASE_CRITICAL_ARTIFACT_SIZE_INVALID")
        return data
    try:
        runtime_manifest_payload = json.loads(artifact_bytes(str(manifest.section("runtime")["runtime_manifest_path"])).decode("utf-8"))
        provenance_payload = json.loads(artifact_bytes("release-evidence/runtime-provenance-report.json").decode("utf-8"))
        attestation_payload = json.loads(artifact_bytes("release-evidence/dependency-rebuild-attestation.json").decode("utf-8"))
        archive_record_payload = json.loads(artifact_bytes("release-evidence/runtime-archive-build-record.json").decode("utf-8"))
        installed_payload = json.loads(artifact_bytes("release-evidence/installed-distributions.json").decode("utf-8"))
        source_policy_payload = json.loads(artifact_bytes("release-evidence/runtime-source-policy.json").decode("utf-8"))
        wheelhouse_payload = json.loads(artifact_bytes("release-evidence/wheelhouse-inventory.json").decode("utf-8"))
        requirements_lock_bytes = artifact_bytes("release-evidence/requirements.lock")
        sbom_payload = json.loads(artifact_bytes(str(manifest.section("sbom")["path"])).decode("utf-8"))
        license_payload = json.loads(artifact_bytes(str(manifest.section("licenses")["machine_inventory_path"])).decode("utf-8"))
        component_policy_payload = json.loads(artifact_bytes(str(manifest.section("licenses")["component_policy_path"])).decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
        config_payload = json.loads(artifact_bytes(str(manifest.section("config_contract")["schema_path"])).decode("utf-8"))
        database_payload = json.loads(artifact_bytes(str(manifest.section("database_contract")["schema_snapshot_path"])).decode("utf-8"))
        static_payload = json.loads(artifact_bytes(str(manifest.section("static_build")["build_record_path"])).decode("utf-8"))
        app_source_inventory = parse_inventory_bytes(artifact_bytes("release-evidence/app-source-inventory.json"))
        payload_policy_bytes = artifact_bytes(str(manifest.section("payload_policy")["payload_path"]))
        payload_policy = json.loads(payload_policy_bytes.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseManifestV2Error("RELEASE_CRITICAL_ARTIFACT_CONTENT_INVALID") from exc
    runtime_section = manifest.section("runtime")
    if (
        sha256_bytes(payload_policy_bytes) != manifest.section("payload_policy")["sha256"]
        or git_blob_sha1(payload_policy_bytes) != manifest.section("payload_policy")["git_blob_sha1"]
    ):
        raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
    policy = _validate_payload_policy(payload_policy)
    if not (
        runtime_manifest_payload.get("schema_version") == runtime_section["runtime_manifest_schema"]
        and runtime_manifest_payload.get("python_version") == runtime_section["python_version"]
        and runtime_manifest_payload.get("python_abi") == runtime_section["python_abi"]
        and runtime_manifest_payload.get("architecture") == runtime_section["architecture"]
        and provenance_payload.get("overall_classification") == "verified"
        and provenance_payload.get("core_runtime_provenance_verified") is True
        and provenance_payload.get("dependency_layer_rebuilt_and_verified") is True
        and provenance_payload.get("archive_provenance_verified") is True
            and provenance_payload.get("production_approved") is False
            and installed_payload.get("installed_closure_sha256") == runtime_section["installed_closure_sha256"]
            and installed_payload.get("dependency_graph_sha256") == runtime_section["dependency_graph_sha256"]
            and attestation_payload.get("schema_version") == "env-1b2p-dependency-rebuild-attestation-v1"
            and attestation_payload.get("result") == "pass"
            and attestation_payload.get("exit_code") == 0
            and attestation_payload.get("network_download_count") == 0
            and attestation_payload.get("runtime_tree_sha256") == runtime_section["runtime_tree_sha256"]
            and attestation_payload.get("requirements_lock_sha256") == runtime_section["requirements_lock_sha256"]
            and attestation_payload.get("wheelhouse_manifest_sha256") == runtime_section["wheelhouse_manifest_sha256"]
            and attestation_payload.get("installed_closure_sha256") == runtime_section["installed_closure_sha256"]
            and attestation_payload.get("python_version") == runtime_section["python_version"]
            and attestation_payload.get("python_abi") == runtime_section["python_abi"]
            and attestation_payload.get("architecture") == runtime_section["architecture"]
            and attestation_payload.get("upstream_commit") == UPSTREAM_COMMIT
            and archive_record_payload.get("schema_version") == "env-1b2p-archive-build-record-v1"
            and archive_record_payload.get("build_result") == "pass"
            and archive_record_payload.get("exit_code") == 0
            and archive_record_payload.get("post_build_changes_detected") is False
            and archive_record_payload.get("runtime_tree_sha256") == runtime_section["runtime_tree_sha256"]
            and archive_record_payload.get("output_archive_sha256") == runtime_section["runtime_archive_sha256"]
            and archive_record_payload.get("wheelhouse_manifest_sha256") == runtime_section["wheelhouse_manifest_sha256"]
            and archive_record_payload.get("python_version") == runtime_section["python_version"]
            and archive_record_payload.get("python_abi") == runtime_section["python_abi"]
            and archive_record_payload.get("upstream_commit") == UPSTREAM_COMMIT
            and source_policy_payload.get("schema_version") == "env-1b2a-python-source-v1"
            and source_policy_payload.get("version") == runtime_section["python_version"]
            and source_policy_payload.get("python_abi") == runtime_section["python_abi"]
            and source_policy_payload.get("architecture") == runtime_section["architecture"]
            and source_policy_payload.get("ordinary_gil_build") is True
            and source_policy_payload.get("free_threaded") is False
            and wheelhouse_payload.get("schema_version") == "env-1b2a-wheelhouse-sha256-v1"
            and wheelhouse_payload.get("target_python_abi") == runtime_section["python_abi"]
            and wheelhouse_payload.get("target_platform") == "win_amd64"
            and wheelhouse_payload.get("invalid_wheel_count") == 0
            and wheelhouse_payload.get("tree_sha256") == attestation_payload.get("wheelhouse_tree_sha256")
        ):
            raise ReleaseManifestV2Error("RELEASE_RUNTIME_EVIDENCE_CONTENT_INVALID")
    try:
        requirements_text = requirements_lock_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise ReleaseManifestV2Error("RELEASE_RUNTIME_EVIDENCE_CONTENT_INVALID") from exc
    requirement_lines = [line.strip() for line in requirements_text.splitlines() if line.strip() and not line.lstrip().startswith("#") and not line.startswith((" ", "\t"))]
    if not requirement_lines or any("--hash=sha256:" not in line for line in requirement_lines):
        raise ReleaseManifestV2Error("RELEASE_RUNTIME_EVIDENCE_CONTENT_INVALID")
    runtime_entries = tuple(InventoryEntry(item.path[len("python/"):], item.size_bytes, item.sha256) for item in inventory.entries if item.path.startswith("python/"))
    runtime_digest = hashlib.sha256()
    for item in runtime_entries:
        encoded = item.path.encode("utf-8"); runtime_digest.update(len(encoded).to_bytes(8, "big")); runtime_digest.update(encoded); runtime_digest.update(item.size_bytes.to_bytes(8, "big")); runtime_digest.update(bytes.fromhex(item.sha256))
    if runtime_digest.hexdigest() != runtime_section["runtime_tree_sha256"]:
        raise ReleaseManifestV2Error("RELEASE_RUNTIME_TREE_MISMATCH")
    sbom_section = manifest.section("sbom")
    components = sbom_payload.get("components"); dependencies = sbom_payload.get("dependencies")
    component_refs = [item.get("bom-ref") for item in components] if type(components) is list else []
    component_by_ref = {item.get("bom-ref"): item for item in components if type(item) is dict} if type(components) is list else {}
    metadata = sbom_payload.get("metadata")
    metadata_component = metadata.get("component") if type(metadata) is dict else None
    metadata_ref = metadata_component.get("bom-ref") if type(metadata_component) is dict else None
    valid_refs = {item for item in component_refs if isinstance(item, str)} | ({metadata_ref} if isinstance(metadata_ref, str) else set())
    dependency_refs = [item.get("ref") for item in dependencies] if type(dependencies) is list and all(type(item) is dict for item in dependencies) else []
    edge_count = sum(len(item.get("dependsOn", [])) for item in dependencies if type(item) is dict and type(item.get("dependsOn")) is list) if type(dependencies) is list else -1
    metadata_properties = metadata.get("properties") if type(metadata) is dict else None
    graph_properties = {item.get("name"): item.get("value") for item in metadata_properties if type(item) is dict} if type(metadata_properties) is list else {}
    if sbom_payload.get("bomFormat") != "CycloneDX" or sbom_payload.get("specVersion") != "1.6" or type(components) is not list or type(dependencies) is not list or len(components) != sbom_section["component_count"] or len(component_refs) != len(set(component_refs)) or not all(isinstance(item, str) and item for item in component_refs) or any(type(item) is not dict or not isinstance(item.get("name"), str) or not item["name"] or not isinstance(item.get("version"), str) or not item["version"] for item in components) or len(dependency_refs) != len(set(dependency_refs)) or set(dependency_refs) != valid_refs or any(type(item.get("dependsOn")) is not list or any(ref not in valid_refs for ref in item["dependsOn"]) for item in dependencies) or edge_count != sbom_section["dependency_edge_count"] or graph_properties.get("dependency_graph_sha256") != runtime_section["dependency_graph_sha256"]:
        raise ReleaseManifestV2Error("RELEASE_SBOM_CONTENT_INVALID")
    license_section = manifest.section("licenses")
    license_components = license_payload.get("components")
    vendor_policy = _validate_third_party_component_policy(component_policy_payload, by_path)
    license_keys = {"bom_ref", "component", "version", "source", "license_expression", "license_text_sha256", "license_evidence_path", "evidence_type", "payload_paths"}
    if license_payload.get("schema_version") != "ops-third-party-license-inventory-v1" or license_payload.get("inventory_complete") is not True or license_payload.get("unresolved_count") != 0 or license_payload.get("legal_review_complete") is not False or type(license_components) is not list or len(license_components) != license_section["component_count"] or any(type(item) is not dict or set(item) != license_keys or not isinstance(item["bom_ref"], str) or item["bom_ref"] not in valid_refs or not isinstance(item["component"], str) or not item["component"] or not isinstance(item["version"], str) or not item["version"] or not isinstance(item["source"], str) or not item["source"] or not isinstance(item["license_expression"], str) or not item["license_expression"] or not _SHA256.fullmatch(str(item["license_text_sha256"])) or not isinstance(item["license_evidence_path"], str) or item["license_evidence_path"] not in by_path or by_path[item["license_evidence_path"]].sha256 != item["license_text_sha256"] or not isinstance(item["evidence_type"], str) or not item["evidence_type"] or type(item["payload_paths"]) is not list or not item["payload_paths"] or any(not isinstance(path, str) or path not in by_path for path in item["payload_paths"]) for item in license_components):
        raise ReleaseManifestV2Error("RELEASE_LICENSE_CONTENT_INVALID")
    if {item["bom_ref"] for item in license_components} != set(component_refs):
        raise ReleaseManifestV2Error("RELEASE_LICENSE_CONTENT_INVALID")
    if any(
        item["component"] != component_by_ref[item["bom_ref"]].get("name")
        or item["version"] != component_by_ref[item["bom_ref"]].get("version")
        or (item["bom_ref"] not in vendor_policy and item["source"] != item["bom_ref"])
        for item in license_components
    ):
        raise ReleaseManifestV2Error("RELEASE_LICENSE_CONTENT_INVALID")
    vendor_license_by_ref = {item["bom_ref"]: item for item in license_components if item["bom_ref"] in vendor_policy}
    if set(vendor_license_by_ref) != set(vendor_policy):
        raise ReleaseManifestV2Error("RELEASE_LICENSE_CONTENT_INVALID")
    for bom_ref, expected in vendor_policy.items():
        actual = vendor_license_by_ref[bom_ref]
        if (
            actual["component"] != expected["name"]
            or actual["version"] != expected["version"]
            or actual["source"] != expected["source"]
            or actual["license_expression"] != expected["license_expression"]
            or actual["license_evidence_path"] != expected["license_evidence_path"]
            or actual["payload_paths"] != sorted(expected["payload_files"])
            or component_by_ref[bom_ref].get("licenses") != [{"expression": expected["license_expression"]}]
        ):
            raise ReleaseManifestV2Error("RELEASE_LICENSE_CONTENT_INVALID")
    config_keys = config_payload.get("keys")
    config_record_keys = {"key", "type", "required", "default_classification", "secret", "scope", "validation"}
    if config_payload.get("schema_id") != "enterprise-config-contract-v1" or config_payload.get("secret_values_embedded") is not False or type(config_keys) is not list or not config_keys or any(type(item) is not dict or set(item) != config_record_keys or not isinstance(item["key"], str) or not item["key"] or not isinstance(item["type"], str) or type(item["required"]) is not bool or not isinstance(item["default_classification"], str) or type(item["secret"]) is not bool or not isinstance(item["scope"], str) or not isinstance(item["validation"], str) for item in config_keys) or {item["key"] for item in config_keys} != CONFIG_OPERATOR_KEYS:
        raise ReleaseManifestV2Error("RELEASE_CONFIG_CONTENT_INVALID")
    database_section = manifest.section("database_contract")
    database_objects = database_payload.get("objects")
    if database_payload.get("schema_id") != "enterprise-database-contract-v1" or database_payload.get("migration_ids") != database_section["migration_ids"] or type(database_objects) is not list or any(type(item) is not dict or set(item) != {"name", "sql", "table", "type"} or any(not isinstance(item[key], str) for key in item) for item in database_objects):
        raise ReleaseManifestV2Error("RELEASE_DATABASE_CONTENT_INVALID")
    static_section = manifest.section("static_build")
    actual_static_digest = _static_tree_digest_from_archive(archive_path, str(archive_section["root_prefix"]), inventory)
    if static_payload.get("result") != "pass" or static_payload.get("builder_version") != static_section["builder_version"] or static_payload.get("source_tree_digest") != static_section["source_tree_sha256"] or static_payload.get("output_tree_digest") != static_section["output_tree_sha256"] or static_payload.get("html_build_id") != static_section["html_build_id"] or actual_static_digest != static_section["output_tree_sha256"]:
        raise ReleaseManifestV2Error("RELEASE_STATIC_CONTENT_INVALID")
    expected_app_paths = _expected_app_source_paths(policy, by_path)
    app_by_path = {item.path: item for item in app_source_inventory.entries}
    if app_source_inventory.tree_sha256 != payload_section["app_source_tree_sha256"] or set(app_by_path) != expected_app_paths or any(app_by_path[path] != by_path[path] for path in expected_app_paths):
        raise ReleaseManifestV2Error("RELEASE_APP_SOURCE_CONTENT_INVALID")
    return ReleaseVerificationResult("pass", manifest.raw_sha256, archive_hash, inventory.sha256, inventory.tree_sha256, len(inventory.entries), inventory.total_size_bytes)


def verify_materialized_release(app_root: Path, manifest_path: Path | None = None, inventory_path: Path | None = None) -> ReleaseVerificationResult:
    app_root = Path(app_root)
    _assert_directory(app_root, "RELEASE_APP_ROOT_INVALID")
    manifest_path = app_root / "release-manifest.json" if manifest_path is None else Path(manifest_path)
    manifest = read_release_manifest_v2(manifest_path)
    if inventory_path is None:
        raise ReleaseManifestV2Error("RELEASE_INVENTORY_MISSING")
    try:
        assert_path_within_root(manifest_path, app_root)
        assert_path_within_root(inventory_path, app_root)
    except PathSafetyError as exc:
        raise ReleaseManifestV2Error("RELEASE_APP_ROOT_INVALID") from exc
    _assert_regular_file(Path(inventory_path), "RELEASE_INVENTORY_PATH_INVALID")
    inventory = parse_inventory_bytes(_read_bounded(inventory_path, INVENTORY_MAX_BYTES, missing="RELEASE_INVENTORY_MISSING", failed="RELEASE_INVENTORY_READ_FAILED", oversized="RELEASE_INVENTORY_INVALID"))
    payload_section = manifest.section("release_payload")
    if (
        inventory.sha256 != payload_section["inventory_sha256"]
        or inventory.tree_sha256 != payload_section["tree_sha256"]
        or len(inventory.entries) != payload_section["file_count"]
        or inventory.total_size_bytes != payload_section["total_size_bytes"]
    ):
        raise ReleaseManifestV2Error("RELEASE_INVENTORY_BINDING_INVALID")
    actual = build_inventory(app_root)
    # release-manifest.json is materialization metadata and is deliberately
    # detached from the closed archive payload inventory.
    materialized_entries = tuple(
        item for item in actual.entries
        if item.path not in {str(payload_section["embedded_manifest_path"]), str(payload_section["inventory_path"])}
    )
    if materialized_entries != inventory.entries or payload_tree_sha256(materialized_entries) != inventory.tree_sha256:
        raise ReleaseManifestV2Error("RELEASE_MATERIALIZED_INVENTORY_MISMATCH")
    if sha256_file(manifest_path, maximum=MANIFEST_MAX_BYTES)[0] != manifest.raw_sha256:
        raise ReleaseManifestV2Error("RELEASE_MATERIALIZED_MANIFEST_MISMATCH")
    return ReleaseVerificationResult("pass", manifest.raw_sha256, "", inventory.sha256, inventory.tree_sha256, len(inventory.entries), inventory.total_size_bytes)


def materialize_release_fixture(manifest_path: Path, archive_path: Path, inventory_path: Path, destination: Path) -> ReleaseVerificationResult:
    _assert_regular_file(Path(manifest_path), "RELEASE_MANIFEST_REPARSE_FORBIDDEN")
    _assert_regular_file(Path(archive_path), "RELEASE_ARCHIVE_PATH_INVALID")
    _assert_regular_file(Path(inventory_path), "RELEASE_INVENTORY_PATH_INVALID")
    result = verify_release_manifest_v2(manifest_path, archive_path, inventory_path)
    manifest = read_release_manifest_v2(manifest_path); root_prefix = str(manifest.section("archive")["root_prefix"])
    destination = Path(destination)
    _assert_directory(destination.parent, "RELEASE_MATERIALIZE_ROOT_INVALID", allow_missing=True)
    for source in (Path(manifest_path), Path(archive_path), Path(inventory_path)):
        try:
            assert_path_within_root(source, destination)
        except PathSafetyError:
            continue
        raise ReleaseManifestV2Error("RELEASE_ROOT_OVERLAP_FORBIDDEN")
    if destination.exists():
        raise ReleaseManifestV2Error("RELEASE_MATERIALIZE_DESTINATION_EXISTS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _assert_directory(destination.parent, "RELEASE_MATERIALIZE_ROOT_INVALID")
    created = False
    try:
        destination.mkdir(exist_ok=False); created = True
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir(): continue
                canonical = _safe_relative(info.filename)
                prefix = root_prefix + "/"
                if not canonical.startswith(prefix):
                    raise ReleaseManifestV2Error("RELEASE_ARCHIVE_GLOBAL_INVENTORY_MISMATCH")
                relative = canonical[len(prefix):]
                target = destination.joinpath(*relative.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                _assert_directory(target.parent, "RELEASE_MATERIALIZE_ROOT_INVALID")
                if target.exists() or target.is_symlink():
                    raise ReleaseManifestV2Error("RELEASE_MATERIALIZE_DESTINATION_COLLISION")
                with archive.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, COPY_CHUNK_BYTES)
                _assert_regular_file(target, "RELEASE_MATERIALIZE_FILE_INVALID")
        embedded_manifest = destination / str(manifest.section("release_payload")["embedded_manifest_path"])
        embedded_inventory = destination / str(manifest.section("release_payload")["inventory_path"])
        if _read_bounded(embedded_inventory, INVENTORY_MAX_BYTES, missing="RELEASE_INVENTORY_MISSING", failed="RELEASE_INVENTORY_READ_FAILED", oversized="RELEASE_INVENTORY_INVALID") != _read_bounded(Path(inventory_path), INVENTORY_MAX_BYTES, missing="RELEASE_INVENTORY_MISSING", failed="RELEASE_INVENTORY_READ_FAILED", oversized="RELEASE_INVENTORY_INVALID"):
            raise ReleaseManifestV2Error("RELEASE_MATERIALIZED_INVENTORY_MISMATCH")
        shutil.copyfile(manifest_path, embedded_manifest)
        _assert_regular_file(embedded_manifest, "RELEASE_MATERIALIZE_FILE_INVALID")
        verify_materialized_release(destination, manifest_path=embedded_manifest, inventory_path=embedded_inventory)
        return result
    except Exception:
        if created:
            shutil.rmtree(destination, ignore_errors=True)
        raise
