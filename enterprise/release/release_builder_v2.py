"""Deterministic detached Release v2 payload builder.

The builder exports one exact Git tree, reuses the accepted deterministic
static builder and an already-verified CP314 Runtime, and writes only to a new
caller-supplied output directory.  It never activates a Release.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from enterprise.path_safety import PathSafetyError, assert_no_reparse_ancestors, lexical_path_state

from . import runtime_provenance
from .release_manifest_v2 import (
    CONFIG_OPERATOR_KEYS,
    INVENTORY_SCHEMA_VERSION,
    PAYLOAD_POLICY_PATH,
    PAYLOAD_POLICY_SCHEMA_VERSION,
    PORTABLE_RELEASE_CONTRACT_VERSION,
    ReleaseManifestV2Error,
    _safe_relative,
    _validate_payload_policy,
    _windows_key,
    assert_non_overlapping_roots,
    build_inventory,
    canonical_json,
    derive_release_id,
    git_blob_sha1,
    sha256_bytes,
    sha256_file,
    verify_release_manifest_v2,
)
from .static_build import BUILDER_VERSION as STATIC_BUILDER_VERSION, build_static_tree


BUILDER_VERSION = "ops-release-manifest-v2-builder-v1"
POLICY_SCHEMA = PAYLOAD_POLICY_SCHEMA_VERSION
THIRD_PARTY_POLICY_PATH = "release/windows/third-party-component-policy.json"
THIRD_PARTY_POLICY_SCHEMA = "ops-third-party-component-policy-v1"
CONFIG_SCHEMA = "enterprise-config-contract-v1"
DATABASE_SCHEMA = "enterprise-database-contract-v1"
ENTERPRISE_REPOSITORY = "MEIS-DaCaiTou/Infinite-Canvas-Enterprise"
UPSTREAM_REPOSITORY = "hero8152/Infinite-Canvas"
RUNTIME_MANIFEST_SCHEMA = "enterprise-windows-runtime-manifest-v1"
RUNTIME_PROVENANCE_SCHEMA = "env-1b2p-runtime-provenance-report-v2"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", os.fspath(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise ReleaseManifestV2Error("RELEASE_GIT_IDENTITY_INVALID")
    return result.stdout.strip()


def _git_bytes(repo: Path, revision_path: str) -> bytes:
    result = subprocess.run(["git", "-C", os.fspath(repo), "show", revision_path], capture_output=True)
    if result.returncode:
        raise ReleaseManifestV2Error("RELEASE_GIT_IDENTITY_INVALID")
    return result.stdout


def clean_git_identity(repo: Path, commit: str | None = None) -> dict[str, object]:
    repo = Path(repo).resolve()
    head = _git(repo, "rev-parse", "HEAD")
    if commit is not None and head != commit:
        raise ReleaseManifestV2Error("RELEASE_GIT_HEAD_MISMATCH")
    if _git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ReleaseManifestV2Error("RELEASE_GIT_WORKTREE_DIRTY")
    return {
        "commit": head,
        "tree": _git(repo, "rev-parse", f"{head}^{{tree}}"),
        "source_date_epoch": int(_git(repo, "show", "-s", "--format=%ct", head)),
    }


def _load_json(path: Path) -> dict[str, object]:
    _assert_build_file(path)
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseManifestV2Error("RELEASE_BUILD_INPUT_INVALID") from exc
    if type(value) is not dict:
        raise ReleaseManifestV2Error("RELEASE_BUILD_INPUT_INVALID")
    return value


def _assert_build_file(path: Path) -> None:
    try:
        assert_no_reparse_ancestors(path)
        if lexical_path_state(path) != "regular" or not Path(path).is_file():
            raise PathSafetyError("path-invalid")
    except (OSError, PathSafetyError) as exc:
        raise ReleaseManifestV2Error("RELEASE_BUILD_INPUT_INVALID") from exc


def _assert_build_directory(path: Path) -> None:
    try:
        assert_no_reparse_ancestors(path)
        if lexical_path_state(path) != "regular" or not Path(path).is_dir():
            raise PathSafetyError("path-invalid")
    except (OSError, PathSafetyError) as exc:
        raise ReleaseManifestV2Error("RELEASE_BUILD_INPUT_INVALID") from exc


def _git_tree_modes(repo: Path, commit: str) -> dict[str, str]:
    result = subprocess.run(
        ["git", "-C", os.fspath(repo), "ls-tree", "-r", "-z", "--full-tree", commit],
        capture_output=True,
    )
    if result.returncode:
        raise ReleaseManifestV2Error("RELEASE_GIT_IDENTITY_INVALID")
    records: dict[str, str] = {}
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            metadata, name = raw.split(b"\t", 1)
            mode = metadata.split(b" ", 1)[0].decode("ascii")
            relative = _safe_relative(name.decode("utf-8"))
        except (ValueError, UnicodeError, ReleaseManifestV2Error) as exc:
            raise ReleaseManifestV2Error("RELEASE_GIT_TREE_INVALID") from exc
        key = _windows_key(relative)
        if key in records:
            raise ReleaseManifestV2Error("RELEASE_GIT_TREE_INVALID")
        records[key] = mode
    return records


def _extract_git_tree(repo: Path, commit: str, destination: Path) -> None:
    archive = destination.parent / "source-export.zip"
    result = subprocess.run(["git", "-C", os.fspath(repo), "archive", "--format=zip", f"--output={archive}", commit], capture_output=True)
    if result.returncode:
        raise ReleaseManifestV2Error("RELEASE_GIT_EXPORT_FAILED")
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            relative = Path(info.filename)
            if info.is_dir():
                continue
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ReleaseManifestV2Error("RELEASE_GIT_SYMLINK_FORBIDDEN")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as input_handle, target.open("xb") as output:
                shutil.copyfileobj(input_handle, output, 1024 * 1024)
    archive.unlink()


def _excluded(relative: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(relative, pattern) or fnmatch.fnmatchcase(relative + "/", pattern) for pattern in globs)


def _copy_git_payload(source: Path, payload: Path, policy: dict[str, object], git_modes: dict[str, str] | None = None):
    policy = _validate_payload_policy(policy)
    roots = policy["included_roots"]; root_files = policy["included_root_files"]; globs = policy["excluded_globs"]
    if git_modes is not None:
        selected_root_files = {_windows_key(item) for item in root_files}
        selected_roots = tuple(_windows_key(item) + "/" for item in roots)
        for relative_key, mode in git_modes.items():
            selected = relative_key in selected_root_files or relative_key.startswith(selected_roots)
            if selected and not _excluded(relative_key, globs) and mode not in {"100644", "100755"}:
                raise ReleaseManifestV2Error("RELEASE_GIT_SYMLINK_FORBIDDEN")
    selected = payload.parent / "application-source"
    selected.mkdir(exist_ok=False)
    for filename in root_files:
        origin = source / filename
        if lexical_path_state(origin) != "regular" or not origin.is_file() or _excluded(filename, globs):
            raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
        if git_modes is not None and git_modes.get(_windows_key(filename)) not in {"100644", "100755"}:
            raise ReleaseManifestV2Error("RELEASE_GIT_SYMLINK_FORBIDDEN")
        target = selected / filename; target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists(): raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_COLLISION")
        shutil.copyfile(origin, target)
    for root_name in roots:
        origin_root = source / root_name
        if lexical_path_state(origin_root) != "regular" or not origin_root.is_dir():
            raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID")
        if root_name == policy.get("source_static_root"):
            continue
        for origin in sorted(origin_root.rglob("*")):
            if not origin.is_file(): continue
            relative = origin.relative_to(source).as_posix()
            if _excluded(relative, globs): continue
            if lexical_path_state(origin) != "regular" or (git_modes is not None and git_modes.get(_windows_key(relative)) not in {"100644", "100755"}):
                raise ReleaseManifestV2Error("RELEASE_GIT_SYMLINK_FORBIDDEN")
            target = selected / Path(relative); target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists(): raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_COLLISION")
            shutil.copyfile(origin, target)
    source_inventory = build_inventory(selected)
    for origin in sorted(selected.rglob("*")):
        if origin.is_file():
            target = payload / origin.relative_to(selected); target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(origin, target)
    shutil.rmtree(selected)
    return source_inventory


def _runtime_values(repo: Path, runtime_root: Path, evidence_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    required = {
        "runtime-manifest.json", "runtime-archive-provenance-report.json", "runtime-sbom.cdx.json",
        "runtime-archive-build-record.json", "dependency-rebuild-attestation.json",
        "installed-distributions.json", "wheelhouse-inventory.json",
    }
    if not all((evidence_root / name).is_file() for name in required):
        raise ReleaseManifestV2Error("RELEASE_RUNTIME_EVIDENCE_MISSING")
    report = _load_json(evidence_root / "runtime-archive-provenance-report.json")
    if not (
        report.get("schema_version") == RUNTIME_PROVENANCE_SCHEMA
        and report.get("overall_classification") == "verified"
        and report.get("core_runtime_provenance_verified") is True
        and report.get("dependency_layer_rebuilt_and_verified") is True
        and report.get("archive_provenance_verified") is True
        and report.get("production_approved") is False
    ):
        raise ReleaseManifestV2Error("RELEASE_RUNTIME_PROVENANCE_INVALID")
    records, runtime_tree, runtime_size = runtime_provenance._tree_inventory(runtime_root)
    attestation = _load_json(evidence_root / "dependency-rebuild-attestation.json")
    archive_record = _load_json(evidence_root / "runtime-archive-build-record.json")
    installed = _load_json(evidence_root / "installed-distributions.json")
    runtime_manifest = _load_json(evidence_root / "runtime-manifest.json")
    if runtime_tree != attestation.get("runtime_tree_sha256") or runtime_tree != archive_record.get("runtime_tree_sha256"):
        raise ReleaseManifestV2Error("RELEASE_RUNTIME_TREE_MISMATCH")
    if runtime_manifest.get("schema_version") != RUNTIME_MANIFEST_SCHEMA or runtime_manifest.get("python_version") != "3.14.6" or runtime_manifest.get("python_abi") != "cp314" or runtime_manifest.get("architecture") != "x64":
        raise ReleaseManifestV2Error("RELEASE_RUNTIME_IDENTITY_INVALID")
    values = {
        "architecture": "x64",
        "dependency_graph_sha256": installed["dependency_graph_sha256"],
        "installed_closure_sha256": installed["installed_closure_sha256"],
        "python_abi": "cp314",
        "python_version": "3.14.6",
        "requirements_lock_sha256": attestation["requirements_lock_sha256"],
        "runtime_archive_sha256": archive_record["output_archive_sha256"],
        "runtime_manifest_schema": RUNTIME_MANIFEST_SCHEMA,
        "runtime_manifest_sha256": sha256_file(evidence_root / "runtime-manifest.json", maximum=2 * 1024 * 1024)[0],
        "runtime_provenance_report_sha256": sha256_file(evidence_root / "runtime-archive-provenance-report.json", maximum=2 * 1024 * 1024)[0],
        "runtime_source_policy_sha256": sha256_bytes(_git_bytes(repo, "HEAD:runtime/windows/python-source.json")),
        "runtime_tree_sha256": runtime_tree,
        "wheelhouse_manifest_sha256": attestation["wheelhouse_manifest_sha256"],
    }
    return values, {"file_count": len(records), "size_bytes": runtime_size}


def _third_party_policy(raw: bytes) -> dict[str, object]:
    try:
        policy = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID") from exc
    if type(policy) is not dict or set(policy) != {"schema_version", "components", "project_owned_payload_files"} or policy["schema_version"] != THIRD_PARTY_POLICY_SCHEMA or type(policy["components"]) is not list or type(policy["project_owned_payload_files"]) is not dict:
        raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
    refs: set[str] = set(); covered: set[str] = set()
    required = {"bom_ref", "name", "version", "source", "license_expression", "license_source_path", "payload_files"}
    for item in policy["components"]:
        if type(item) is not dict or set(item) != required or not all(isinstance(item[key], str) and item[key] for key in required - {"payload_files"}) or type(item["payload_files"]) is not dict or not item["payload_files"]:
            raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
        if item["bom_ref"] in refs:
            raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
        refs.add(item["bom_ref"])
        _safe_relative(item["license_source_path"])
        for path, digest in item["payload_files"].items():
            relative = _safe_relative(path)
            if relative in covered or not isinstance(digest, str) or len(digest) != 64:
                raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
            try:
                int(digest, 16)
            except ValueError as exc:
                raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID") from exc
            covered.add(relative)
    for path, digest in policy["project_owned_payload_files"].items():
        relative = _safe_relative(path)
        if relative in covered or not isinstance(digest, str) or len(digest) != 64:
            raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ReleaseManifestV2Error("RELEASE_LICENSE_POLICY_INVALID") from exc
        covered.add(relative)
    return policy


def _release_sbom(runtime_sbom: Path, version: str, commit: str, vendor_policy: dict[str, object]) -> tuple[bytes, int, int]:
    payload = _load_json(runtime_sbom)
    components = payload.get("components"); dependencies = payload.get("dependencies")
    if type(components) is not list or type(dependencies) is not list:
        raise ReleaseManifestV2Error("RELEASE_SBOM_INVALID")
    app_ref = f"pkg:github/MEIS-DaCaiTou/Infinite-Canvas-Enterprise@{commit}"
    upstream_ref = f"pkg:github/hero8152/Infinite-Canvas@{runtime_provenance.FIXED_UPSTREAM_COMMIT}"
    workflow_ref = f"pkg:generic/infinite-canvas-shipped-workflows@{commit}"
    vendor_components = [
        {
            "bom-ref": item["bom_ref"], "name": item["name"], "type": "library",
            "version": item["version"],
            "licenses": [{"expression": item["license_expression"]}],
            "properties": [
                {"name": "payload_revision", "value": sha256_bytes(canonical_json(item["payload_files"]))},
                {"name": "source", "value": item["source"]},
            ],
        }
        for item in vendor_policy["components"]
    ]
    vendor_refs = [item["bom-ref"] for item in vendor_components]
    components = list(components) + [
        {"bom-ref": app_ref, "name": "Infinite-Canvas-Enterprise", "type": "application", "version": version},
        {"bom-ref": upstream_ref, "name": "Infinite-Canvas", "type": "application", "version": runtime_provenance.FIXED_UPSTREAM_VERSION},
        {"bom-ref": workflow_ref, "name": "shipped-workflows", "type": "data", "version": commit},
    ] + vendor_components
    dependencies = list(dependencies) + [
        {"ref": app_ref, "dependsOn": [upstream_ref, workflow_ref, "runtime", *vendor_refs]},
        {"ref": upstream_ref, "dependsOn": vendor_refs},
        {"ref": workflow_ref, "dependsOn": []},
        *({"ref": ref, "dependsOn": []} for ref in vendor_refs),
    ]
    result = {**payload, "components": sorted(components, key=lambda item: str(item.get("bom-ref"))), "dependencies": sorted(dependencies, key=lambda item: str(item.get("ref")))}
    data = canonical_json(result)
    edge_count = sum(len(item.get("dependsOn", [])) for item in result["dependencies"] if type(item) is dict and type(item.get("dependsOn")) is list)
    return data, len(result["components"]), edge_count


def _license_documents(sbom_bytes: bytes, payload: Path, runtime_root: Path, version: str, commit: str, vendor_policy: dict[str, object]) -> tuple[bytes, bytes, int]:
    sbom = json.loads(sbom_bytes)
    vendor_by_ref = {item["bom_ref"]: item for item in vendor_policy["components"]}
    records = []
    for component in sbom["components"]:
        bom_ref = str(component.get("bom-ref")); name = str(component.get("name")); component_version = str(component.get("version", ""))
        licenses = component.get("licenses", [])
        expression = "LicenseRef-Metadata-Declared"
        if isinstance(licenses, list) and licenses:
            first = licenses[0]
            if type(first) is dict:
                if isinstance(first.get("expression"), str) and first["expression"]:
                    expression = str(first["expression"])
                else:
                    license_data = first.get("license", first)
                    if type(license_data) is dict:
                        expression = str(license_data.get("id") or license_data.get("name") or expression)
        evidence_path = payload / "LICENSE"
        payload_path = "LICENSE"
        evidence_type = "project-license"
        payload_paths = [payload_path]
        source = bom_ref
        if name == "CPython":
            expression = "Python-2.0"; evidence_path = runtime_root / "LICENSE.txt"; payload_path = "python/LICENSE.txt"; evidence_type = "upstream-license-file"
            payload_paths = [payload_path]
        elif bom_ref in vendor_by_ref:
            vendor = vendor_by_ref[bom_ref]
            expression = str(vendor["license_expression"])
            source = str(vendor["source"])
            payload_path = "release-evidence/licenses/" + Path(str(vendor["license_source_path"])).name
            evidence_path = payload / payload_path
            evidence_type = "git-tracked-vendor-license"
            payload_paths = sorted(vendor["payload_files"])
        elif name not in {"Infinite-Canvas-Enterprise", "Infinite-Canvas", "shipped-workflows"}:
            normalized = name.replace("-", "_").casefold()
            evidence_path = Path()
            for dist_info in (runtime_root / "Lib/site-packages").glob("*.dist-info"):
                if not dist_info.name.casefold().startswith(normalized + "-"):
                    continue
                license_files = sorted(
                    path for path in dist_info.rglob("*")
                    if path.is_file() and "license" in path.name.casefold()
                )
                if license_files:
                    evidence_path = license_files[0]
                    payload_path = "python/" + evidence_path.relative_to(runtime_root).as_posix()
                    evidence_type = "distribution-license-file"
                    break
                metadata = dist_info / "METADATA"
                if metadata.is_file():
                    try:
                        declared = [
                            line.split(":", 1)[1].strip()
                            for line in metadata.read_text(encoding="utf-8").splitlines()
                            if line.startswith(("License-Expression:", "License:"))
                            and line.split(":", 1)[1].strip().casefold() not in {"", "unknown"}
                        ]
                    except (OSError, UnicodeError) as exc:
                        raise ReleaseManifestV2Error("RELEASE_LICENSE_EVIDENCE_INVALID") from exc
                    if declared:
                        evidence_path = metadata
                        payload_path = "python/" + metadata.relative_to(runtime_root).as_posix()
                        evidence_type = "distribution-license-metadata"
                        if expression == "LicenseRef-Metadata-Declared":
                            expression = declared[0]
                        break
            if not evidence_path or not evidence_path.is_file():
                raise ReleaseManifestV2Error("RELEASE_LICENSE_EVIDENCE_MISSING")
            payload_paths = [payload_path]
        if name in {"Infinite-Canvas-Enterprise", "Infinite-Canvas", "shipped-workflows"}: expression = "LicenseRef-Infinite-Canvas-Project-License"
        if expression == "LicenseRef-Metadata-Declared":
            evidence_digest = sha256_file(evidence_path, maximum=4 * 1024 * 1024)[0]
            expression = f"LicenseRef-Distribution-{re.sub(r'[^A-Za-z0-9.-]+', '-', name).strip('-')}-{evidence_digest[:12]}"
        records.append({
            "bom_ref": bom_ref, "component": name, "evidence_type": evidence_type,
            "license_expression": expression, "license_text_sha256": sha256_file(evidence_path, maximum=4 * 1024 * 1024)[0],
            "license_evidence_path": payload_path,
            "payload_paths": payload_paths,
            "source": source, "version": component_version,
        })
    document = {"components": sorted(records, key=lambda item: (item["component"].casefold(), item["version"])), "inventory_complete": True, "legal_review_complete": False, "schema_version": "ops-third-party-license-inventory-v1", "unresolved_count": 0}
    machine = canonical_json(document)
    lines = ["Infinite Canvas Enterprise - Third-Party License Notice", "", "Legal review complete: false", "Inventory unresolved count: 0", ""]
    lines.extend(f"- {item['component']} {item['version']}: {item['license_expression']}" for item in document["components"])
    return machine, ("\n".join(lines) + "\n").encode("utf-8"), len(records)


def _config_contract() -> bytes:
    records = [
        ("GATEWAY_PORT", "integer", True, "non-secret-default", False, "runtime", "1..65535"),
        ("UPSTREAM_PORT", "integer", True, "non-secret-default", False, "runtime", "1..65535"),
        ("JWT_SECRET", "string", True, "operator-generated", True, "security", "non-placeholder"),
        ("JWT_EXPIRE_HOURS", "integer", True, "non-secret-default", False, "security", "positive"),
        ("ADMIN_USERNAME", "string", False, "legacy-explicit-bootstrap-only", False, "security", "non-empty"),
        ("ADMIN_PASSWORD", "string", False, "legacy-explicit-bootstrap-only", True, "security", "minimum-length"),
        ("DB_PATH", "path", True, "root-derived", False, "data", "DATA_ROOT-contained"),
        ("ENTERPRISE_REPO_URL", "url", True, "non-secret-default", False, "updates", "https-url"),
        ("ENTERPRISE_UPDATE_ENABLED", "boolean", True, "non-secret-default", False, "updates", "strict-boolean"),
        ("ENTERPRISE_HIDE_UPSTREAM_AUTHOR", "boolean", True, "non-secret-default", False, "presentation", "strict-boolean"),
        ("ENTERPRISE_ENV", "enum", True, "non-secret-default", False, "runtime", "development-or-production"),
        ("ENTERPRISE_STRICT_SECURITY", "boolean", True, "non-secret-default", False, "security", "strict-boolean"),
    ]
    result = {"keys": [{"default_classification": d, "key": k, "required": r, "scope": s, "secret": secret, "type": t, "validation": v} for k, t, r, d, secret, s, v in records], "schema_id": CONFIG_SCHEMA, "secret_values_embedded": False}
    if {item["key"] for item in result["keys"]} != CONFIG_OPERATOR_KEYS:
        raise ReleaseManifestV2Error("RELEASE_CONFIG_CONTENT_INVALID")
    return canonical_json(result)


def _database_snapshot(repo: Path, destination: Path) -> bytes:
    script = r'''import json, os, sqlite3, sys
from pathlib import Path
sys.path.insert(0, os.environ["ICE_REPO_ROOT"])
from enterprise.paths import derive_development_path_roots, resolve_database_path
import enterprise.config as config
import enterprise.db as db
from enterprise.migrations.sec_1b1_role_auth import MIGRATION_ID as ROLE_AUTH_MIGRATION_ID
from enterprise.migrations.sec_1b2_activation import BOOTSTRAP_MIGRATION_ID, ensure_bootstrap_lifecycle_schema_in_transaction
from enterprise.migrations.versioned import BASELINE_SCHEMA_VERSION, DEFAULT_MIGRATIONS, initialize_schema_metadata_in_transaction, migration_registry_sha256, schema_objects, schema_snapshot_sha256
from enterprise.security_audit import SECURITY_AUDIT_MIGRATION_ID, ensure_security_audit_schema_in_transaction
root=Path(os.environ["ICE_DB_SNAPSHOT_ROOT"])
roots=derive_development_path_roots(root)
db.PATH_ROOTS=roots; db.DB_PATH=Path("enterprise.db"); db.ADMIN_USERNAME="manifest_fixture_admin"; db.ADMIN_PASSWORD="fixture-only-not-a-secret"
db.init_db()
target=resolve_database_path(roots, db.DB_PATH)
con=sqlite3.connect(target)
con.execute("BEGIN IMMEDIATE")
ensure_security_audit_schema_in_transaction(con)
ensure_bootstrap_lifecycle_schema_in_transaction(con)
initialize_schema_metadata_in_transaction(con, schema_version=BASELINE_SCHEMA_VERSION)
con.commit()
objects=schema_objects(con)
payload={"migration_ids":sorted([ROLE_AUTH_MIGRATION_ID,BOOTSTRAP_MIGRATION_ID,SECURITY_AUDIT_MIGRATION_ID]),"migration_registry_sha256":migration_registry_sha256(DEFAULT_MIGRATIONS),"objects":objects,"schema_id":"enterprise-database-contract-v1","schema_objects_sha256":schema_snapshot_sha256(con),"schema_version":BASELINE_SCHEMA_VERSION,"versioned_migration_ids":[step.migration_id for step in DEFAULT_MIGRATIONS]}
con.close()
Path(os.environ["ICE_DB_SNAPSHOT_OUTPUT"]).write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")
'''
    temp_root = destination.parent / "database-fixture"
    env = os.environ.copy(); env.update({"ICE_DB_SNAPSHOT_ROOT": os.fspath(temp_root), "ICE_REPO_ROOT": os.fspath(repo), "ICE_DB_SNAPSHOT_OUTPUT": os.fspath(destination), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "ENTERPRISE_ENV": "development", "JWT_SECRET": "fixture-jwt-secret-not-production", "ADMIN_PASSWORD": "fixture-only-not-a-secret"})
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=repo, env=env, capture_output=True, text=True)
    if result.returncode or not destination.is_file():
        raise ReleaseManifestV2Error("RELEASE_DATABASE_SNAPSHOT_FAILED")
    data = destination.read_bytes(); shutil.rmtree(temp_root, ignore_errors=True); destination.unlink()
    return data


def _deterministic_zip(payload: Path, archive: Path, root_prefix: str, epoch: int) -> None:
    import datetime
    timestamp = datetime.datetime.fromtimestamp(max(epoch, 315532800), datetime.timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=False) as output:
        for path in sorted(payload.rglob("*"), key=lambda item: item.relative_to(payload).as_posix()):
            if not path.is_file(): continue
            relative = path.relative_to(payload).as_posix()
            info = zipfile.ZipInfo(f"{root_prefix}/{relative}", timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED; info.create_system = 0; info.external_attr = 0o100644 << 16
            with path.open("rb") as source, output.open(info, "w", force_zip64=True) as target:
                shutil.copyfileobj(source, target, 1024 * 1024)


def build_release_v2(*, repo: Path, output_root: Path, runtime_root: Path, runtime_evidence_root: Path, commit: str | None = None) -> dict[str, object]:
    repo = Path(repo).resolve(); output_root = Path(output_root).resolve(); runtime_root = Path(runtime_root).resolve(); runtime_evidence_root = Path(runtime_evidence_root).resolve()
    _assert_build_directory(repo); _assert_build_directory(runtime_root); _assert_build_directory(runtime_evidence_root)
    try:
        assert_no_reparse_ancestors(output_root, allow_missing=True)
    except PathSafetyError as exc:
        raise ReleaseManifestV2Error("RELEASE_BUILD_OUTPUT_INVALID") from exc
    assert_non_overlapping_roots(repo, output_root, runtime_root, runtime_evidence_root)
    if output_root.exists(): raise ReleaseManifestV2Error("RELEASE_BUILD_OUTPUT_EXISTS")
    identity = clean_git_identity(repo, commit); commit = str(identity["commit"]); tree = str(identity["tree"]); epoch = int(identity["source_date_epoch"])
    version_bytes = subprocess.check_output(["git", "-C", os.fspath(repo), "show", f"{commit}:VERSION"])
    version = version_bytes.decode("utf-8").strip(); release_id = derive_release_id(version, commit)
    policy_bytes = _git_bytes(repo, f"{commit}:release/windows/release-payload-policy.json")
    try:
        policy = json.loads(policy_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseManifestV2Error("RELEASE_PAYLOAD_POLICY_INVALID") from exc
    policy = _validate_payload_policy(policy)
    vendor_policy_bytes = _git_bytes(repo, f"{commit}:{THIRD_PARTY_POLICY_PATH}")
    vendor_policy = _third_party_policy(vendor_policy_bytes)
    git_modes = _git_tree_modes(repo, commit)
    runtime_values, runtime_summary = _runtime_values(repo, runtime_root, runtime_evidence_root)
    output_root.mkdir(parents=True, exist_ok=False)
    _assert_build_directory(output_root)
    completed = False
    source_export = output_root / ".source-export"; payload = output_root / ".payload"; source_export.mkdir(); payload.mkdir()
    try:
        _extract_git_tree(repo, commit, source_export)
        app_source_inventory = _copy_git_payload(source_export, payload, policy, git_modes)
        # ``git archive`` may apply the host's checkout line-ending policy on
        # Windows.  VERSION is a manifest authority, so publish its exact Git
        # blob bytes rather than environment-dependent checkout bytes.
        (payload / "VERSION").write_bytes(version_bytes)
        app_source_inventory = build_inventory(payload)
        static_report_path = payload / "release-evidence/static-build-report.json"
        static_report_path.parent.mkdir(parents=True, exist_ok=True)
        static_report = build_static_tree(source_export / "static", payload / "static", static_report_path)
        shutil.copytree(runtime_root, payload / "python")
        shutil.copyfile(runtime_evidence_root / "runtime-manifest.json", payload / "runtime-manifest.json")
        evidence = payload / "release-evidence"; evidence.mkdir(exist_ok=True)
        (evidence / "release-payload-policy.json").write_bytes(policy_bytes)
        (evidence / "third-party-component-policy.json").write_bytes(vendor_policy_bytes)
        license_evidence = evidence / "licenses"; license_evidence.mkdir()
        for component in vendor_policy["components"]:
            source_path = str(component["license_source_path"])
            (license_evidence / Path(source_path).name).write_bytes(_git_bytes(repo, f"{commit}:{source_path}"))
        (evidence / "app-source-inventory.json").write_bytes(app_source_inventory.canonical_bytes)
        for source_name, target_name in (
            ("runtime-archive-provenance-report.json", "runtime-provenance-report.json"),
            ("runtime-archive-build-record.json", "runtime-archive-build-record.json"),
            ("dependency-rebuild-attestation.json", "dependency-rebuild-attestation.json"),
            ("installed-distributions.json", "installed-distributions.json"),
            ("wheelhouse-inventory.json", "wheelhouse-inventory.json"),
        ):
            shutil.copyfile(runtime_evidence_root / source_name, evidence / target_name)
        # Evidence hashes are defined over exact Git blob bytes.  Do not use
        # git-archive checkout bytes here because path attributes may perform
        # line-ending conversion (notably for requirements.lock on Windows).
        (evidence / "runtime-source-policy.json").write_bytes(
            _git_bytes(repo, f"{commit}:runtime/windows/python-source.json")
        )
        (evidence / "requirements.lock").write_bytes(
            _git_bytes(repo, f"{commit}:runtime/windows/requirements.lock")
        )
        sbom_bytes, component_count, edge_count = _release_sbom(runtime_evidence_root / "runtime-sbom.cdx.json", version, commit, vendor_policy)
        (evidence / "release-sbom.cdx.json").write_bytes(sbom_bytes)
        machine, notice, license_count = _license_documents(sbom_bytes, payload, runtime_root, version, commit, vendor_policy)
        (evidence / "third-party-licenses.json").write_bytes(machine); (payload / "THIRD-PARTY-LICENSES.txt").write_bytes(notice)
        config_bytes = _config_contract(); (evidence / "config-contract.json").write_bytes(config_bytes)
        db_bytes = _database_snapshot(repo, output_root / ".database-snapshot.tmp"); (evidence / "database-schema.json").write_bytes(db_bytes)
        inventory = build_inventory(payload)
        inventory_path = output_root / "release-payload-inventory.json"; inventory_path.write_bytes(inventory.canonical_bytes)
        (payload / inventory_path.name).write_bytes(inventory.canonical_bytes)
        root_prefix = f"Infinite-Canvas-Enterprise-{release_id}"; archive_path = output_root / f"{root_prefix}-win-x64.zip"
        _deterministic_zip(payload, archive_path, root_prefix, epoch)
        archive_hash, archive_size = sha256_file(archive_path, maximum=2 * 1024 * 1024 * 1024)
        source_policy = _load_json(repo / "runtime/windows/python-source.json")
        database_payload = json.loads(db_bytes)
        manifest_data = {
            "archive": {"file_count": len(inventory.entries) + 1, "filename": archive_path.name, "inventory_sha256": inventory.sha256, "payload_excludes": ["release-manifest.json"], "payload_tree_sha256": inventory.tree_sha256, "root_prefix": root_prefix, "sha256": archive_hash, "size_bytes": archive_size, "total_uncompressed_bytes": inventory.total_size_bytes + len(inventory.canonical_bytes)},
            "compatibility": {"minimum_launcher_contract": PORTABLE_RELEASE_CONTRACT_VERSION, "minimum_runtime_contract": PORTABLE_RELEASE_CONTRACT_VERSION, "portable_release_only": True, "supported_architecture": "x64", "supported_platform": "windows"},
            "config_contract": {"schema_id": CONFIG_SCHEMA, "schema_path": "release-evidence/config-contract.json", "schema_sha256": sha256_bytes(config_bytes), "secret_values_embedded": False},
            "database_contract": {"migration_compatibility": "same-schema-no-migration", "migration_ids": database_payload["migration_ids"], "ops3b_activation_eligible": True, "rollback_classification": "code-release-pointer", "schema_id": DATABASE_SCHEMA, "schema_snapshot_path": "release-evidence/database-schema.json", "schema_snapshot_sha256": sha256_bytes(db_bytes)},
            "enterprise_source": {"commit": commit, "repository": ENTERPRISE_REPOSITORY, "tree": tree, "version": version, "version_file_sha256": sha256_bytes(version_bytes)},
            "identity": {"manifest_builder_version": BUILDER_VERSION, "release_channel": "enterprise-portable", "release_id": release_id, "release_version": version, "source_date_epoch": epoch},
            "licenses": {"component_count": license_count, "component_policy_path": "release-evidence/third-party-component-policy.json", "component_policy_sha256": sha256_bytes(vendor_policy_bytes), "human_notice_path": "THIRD-PARTY-LICENSES.txt", "human_notice_sha256": sha256_bytes(notice), "inventory_complete": True, "legal_review_complete": False, "machine_inventory_path": "release-evidence/third-party-licenses.json", "machine_inventory_sha256": sha256_bytes(machine), "unresolved_count": 0},
            "payload_policy": {"git_blob_sha1": git_blob_sha1(policy_bytes), "git_path": "release/windows/release-payload-policy.json", "payload_path": PAYLOAD_POLICY_PATH, "schema_version": POLICY_SCHEMA, "sha256": sha256_bytes(policy_bytes)},
            "release_payload": {"app_source_tree_sha256": app_source_inventory.tree_sha256, "archive_payload_excludes": ["release-manifest.json"], "embedded_manifest_path": "release-manifest.json", "file_count": len(inventory.entries), "inventory_path": inventory_path.name, "inventory_schema": INVENTORY_SCHEMA_VERSION, "inventory_sha256": inventory.sha256, "static_tree_sha256": static_report["output_tree_digest"], "total_size_bytes": inventory.total_size_bytes, "tree_sha256": inventory.tree_sha256},
            "runtime": {**runtime_values, "runtime_manifest_path": "runtime-manifest.json"},
            "sbom": {"component_count": component_count, "dependency_edge_count": edge_count, "format": "CycloneDX", "path": "release-evidence/release-sbom.cdx.json", "sha256": sha256_bytes(sbom_bytes), "spec_version": "1.6"},
            "schema_version": "ops-release-manifest-v2",
            "static_build": {"build_record_path": "release-evidence/static-build-report.json", "build_record_sha256": sha256_file(static_report_path, maximum=2 * 1024 * 1024)[0], "builder_version": STATIC_BUILDER_VERSION, "html_build_id": static_report["html_build_id"], "output_tree_sha256": static_report["output_tree_digest"], "source_tree_sha256": static_report["source_tree_digest"]},
            "upstream_source": {"commit": runtime_provenance.FIXED_UPSTREAM_COMMIT, "repository": UPSTREAM_REPOSITORY, "tree": _git(repo, "rev-parse", f"{runtime_provenance.FIXED_UPSTREAM_COMMIT}^{{tree}}"), "version": runtime_provenance.FIXED_UPSTREAM_VERSION, "version_file_sha256": sha256_bytes(subprocess.check_output(["git", "-C", os.fspath(repo), "show", f"{runtime_provenance.FIXED_UPSTREAM_COMMIT}:VERSION"]))},
        }
        manifest_path = output_root / "ops-release-manifest-v2.json"; manifest_path.write_bytes(canonical_json(manifest_data))
        verification = verify_release_manifest_v2(manifest_path, archive_path, inventory_path, expected_enterprise_commit=commit, expected_enterprise_tree=tree)
        report = {"archive": archive_path.name, "builder_version": BUILDER_VERSION, "enterprise_commit": commit, "enterprise_tree": tree, "manifest": manifest_path.name, "payload_policy_sha256": sha256_bytes(policy_bytes), "release_id": release_id, "result": "pass", "runtime_rebuilt": False, "runtime_summary": runtime_summary, "verification": verification.as_dict()}
        (output_root / "build-report.json").write_bytes(canonical_json(report))
        completed = True
        return report
    finally:
        shutil.rmtree(source_export, ignore_errors=True); shutil.rmtree(payload, ignore_errors=True)
        if not completed:
            shutil.rmtree(output_root, ignore_errors=True)
