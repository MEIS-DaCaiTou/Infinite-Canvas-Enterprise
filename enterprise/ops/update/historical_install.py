"""Pinned historical installation recognition for the offline native updater.

Public update endpoints never accept a caller-supplied source approval.  The
native tool ships a reviewed catalog and verified engine, instead of editing
an immutable old release or inventing one migration implementation per tag.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from enterprise.migrations.sqlite_existing import open_existing_sqlite
from enterprise.migrations.versioned import STATE_MISSING, STATE_READY, inspect_schema_metadata_connection, schema_objects, schema_snapshot_sha256
from enterprise.ops.update.legacy_security_variant import LegacySecurityVariantError, inspect_approved_security_variant
from enterprise.ops.update.mvp import UpdateJobStore, _database_evidence
from enterprise.path_safety import assert_no_reparse_ancestors
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.current_release import read_current_release_result_from_state_root
from enterprise.release.release_manifest_v2 import read_release_manifest_v2, sha256_file, verify_materialized_release
from enterprise.runtime.portable import windows_local_app_data_known_folder

CATALOG_SCHEMA = "enterprise-native-upgrade-catalog-v1"
MAX_CATALOG_BYTES = 128 * 1024


def read_catalog(path: Path) -> dict[str, dict[str, object]]:
    assert_no_reparse_ancestors(path)
    with path.open('rb') as handle:
        raw = handle.read(MAX_CATALOG_BYTES + 1)
    if not 0 < len(raw) <= MAX_CATALOG_BYTES:
        raise ValueError("NATIVE_UPGRADE_CATALOG_INVALID")
    document = json.loads(raw)
    if set(document) != {"schema_version", "sources"} or document["schema_version"] != CATALOG_SCHEMA:
        raise ValueError("NATIVE_UPGRADE_CATALOG_INVALID")
    sources = document["sources"]
    if type(sources) is not list or not 1 <= len(sources) <= 100:
        raise ValueError("NATIVE_UPGRADE_CATALOG_INVALID")
    result = {}
    for item in sources:
        if type(item) is not dict or item.get("channel") not in {"stable", "development"}:
            raise ValueError("NATIVE_UPGRADE_CATALOG_INVALID")
        release_id = item.get("release_id")
        if type(release_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", release_id):
            raise ValueError("NATIVE_UPGRADE_CATALOG_INVALID")
        for key in ("manifest_sha256", "python_sha256", "archive_sha256", "payload_tree_sha256", "database_evidence_sha256", "database_objects_sha256"):
            if type(item.get(key)) is not str or not re.fullmatch(r"[0-9a-f]{64}", item[key]):
                raise ValueError("NATIVE_UPGRADE_CATALOG_INVALID")
        if release_id in result:
            raise ValueError("NATIVE_UPGRADE_CATALOG_INVALID")
        if (type(item.get('version')) is not str
            or not re.fullmatch(r'\d{4}\.\d{2}\.\d+', item['version'])
            or type(item.get('object_count')) is not int
            or not 1 <= item['object_count'] <= 10000
            or (item.get('schema_version') is not None and
                (type(item['schema_version']) is not int or item['schema_version'] < 1))):
            raise ValueError("NATIVE_UPGRADE_CATALOG_INVALID")
        result[release_id] = item
    return result


def inspect_historical_install(
    install_root: Path, catalog: dict[str, dict[str, object]], *,
    local_app_data_base: Path | None = None,
) -> tuple[dict[str, object], object, object]:
    """Read-only full source/schema recognition; never expose customer rows."""
    install_root = Path(os.path.abspath(install_root))
    assert_no_reparse_ancestors(install_root)
    pointer = read_current_release_result_from_state_root(install_root / "state")
    source_id = pointer.release.release_id
    approval = catalog.get(source_id)
    if approval is None or pointer.release.manifest_sha256 != approval["manifest_sha256"]:
        raise ValueError("NATIVE_UPGRADE_SOURCE_UNSUPPORTED")
    local = local_app_data_base if local_app_data_base is not None else windows_local_app_data_known_folder()
    roots = derive_portable_path_roots(PortableRootInputs(install_root, local), source_id)
    source_manifest = read_release_manifest_v2(roots.APP_ROOT / "release-manifest.json")
    if (
        source_manifest.raw_sha256 != approval["manifest_sha256"]
        or source_manifest.release_id != source_id
        or source_manifest.section("identity")["release_version"] != approval["version"]
        or source_manifest.section("release_payload")["tree_sha256"] != approval["payload_tree_sha256"]
        or source_manifest.section("database_contract")["schema_snapshot_sha256"] != approval["database_evidence_sha256"]
    ):
        raise ValueError("NATIVE_UPGRADE_SOURCE_IDENTITY_MISMATCH")
    python = roots.PYTHON_RUNTIME / "python.exe"
    assert_no_reparse_ancestors(python)
    if sha256_file(python)[0] != approval["python_sha256"]:
        raise ValueError("NATIVE_UPGRADE_SOURCE_PYTHON_MISMATCH")
    verify_materialized_release(roots.APP_ROOT, inventory_path=roots.APP_ROOT / "release-payload-inventory.json")
    UpdateJobStore(roots).assert_no_unresolved_recovery(read_only=True)
    evidence = _database_evidence(roots.APP_ROOT, source_manifest)
    database_path = roots.DATA_ROOT / "enterprise.db"
    with open_existing_sqlite(database_path, mode="ro", error_type=sqlite3.OperationalError) as conn:
        conn.execute("PRAGMA query_only=ON")
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("NATIVE_UPGRADE_DATABASE_INVALID")
        metadata = inspect_schema_metadata_connection(conn)
        objects = schema_objects(conn)
        variant = "release-exact"
        if objects == evidence["objects"]:
            if "schema_version" in evidence:
                if metadata.get("current_state") != STATE_READY or metadata.get("schema_version") != evidence["schema_version"]:
                    raise ValueError("NATIVE_UPGRADE_DATABASE_IDENTITY_MISMATCH")
            elif metadata.get("current_state") != STATE_MISSING:
                raise ValueError("NATIVE_UPGRADE_DATABASE_IDENTITY_MISMATCH")
        elif "schema_version" not in evidence and approval["object_count"] == 18:
            try:
                inspect_approved_security_variant(conn, baseline_objects=evidence["objects"],
                    source_release_id=source_id, source_manifest_sha256=source_manifest.raw_sha256,
                    approved_source=(source_id, str(approval["manifest_sha256"])))
            except LegacySecurityVariantError as exc:
                raise ValueError("NATIVE_UPGRADE_DATABASE_IDENTITY_MISMATCH") from exc
            variant = "legacy-security-activated"
        else:
            raise ValueError("NATIVE_UPGRADE_DATABASE_IDENTITY_MISMATCH")
        summary = {
            "source_release_id": source_id, "source_version": approval["version"],
            "source_channel": approval["channel"], "source_manifest_sha256": source_manifest.raw_sha256,
            "database_variant": variant, "database_objects_sha256": schema_snapshot_sha256(conn),
            "object_count": len(objects), "integrity_check": "ok",
        }
    return summary, roots, source_manifest
