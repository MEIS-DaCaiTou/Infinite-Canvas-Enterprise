"""The formal schema-changing Release and greenfield install share one shape."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from enterprise.db import ensure_db_schema_in_connection
from enterprise.migrations.sec_1b2_activation import ensure_bootstrap_lifecycle_schema_in_transaction
from enterprise.migrations.versioned import (
    DEFAULT_MIGRATIONS,
    initialize_current_schema_in_transaction,
    schema_objects,
    schema_snapshot_sha256,
)
from enterprise.release.release_builder_v2 import _database_snapshot, _versioned_database_snapshot
from enterprise.security_audit import ensure_security_audit_schema_in_transaction


def test_builder_versioned_evidence_matches_greenfield_schema(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    evidence = json.loads(_versioned_database_snapshot(repository, tmp_path / "schema.json"))
    assert evidence["schema_version"] == 2
    assert evidence["legacy_source_schema_sha256"] == "28b7a7d5994303fdfc7a1186cde19aa1d09312c2985b13427317b04af7a97691"
    assert evidence["versioned_migration_ids"] == ["ice_096_security_schema_v2"]
    assert evidence["schema_objects_sha256"] == "cd8790a1ef22a97b96c76105b26f14c309ed02396249ab97d36034bb88d25284"
    assert evidence["migration_registry_sha256"] == "34dedc0c49d4cb4b9f69231bdcbe24a3ebb49fb04199544aab531d7602fc7774"
    assert json.loads(_database_snapshot(repository, tmp_path / "default-schema.json")) == evidence
    conn = sqlite3.connect(":memory:")
    try:
        ensure_db_schema_in_connection(conn)
        conn.execute("BEGIN IMMEDIATE")
        ensure_security_audit_schema_in_transaction(conn)
        ensure_bootstrap_lifecycle_schema_in_transaction(conn)
        inspection = initialize_current_schema_in_transaction(conn)
        assert inspection["schema_version"] == 2
        assert schema_objects(conn) == evidence["objects"]
        assert schema_snapshot_sha256(conn) == evidence["schema_objects_sha256"]
        conn.rollback()
    finally:
        conn.close()


def test_official_v2_contract_can_prepare_same_schema_update_without_database_writes(tmp_path):
    from enterprise.ops.update.mvp import _database_update_plan
    import hashlib

    repo = Path(__file__).resolve().parents[2]
    data = _database_snapshot(repo, tmp_path / "schema.json")
    evidence = json.loads(data)

    class Manifest:
        def section(self, name):
            assert name == "database_contract"
            return {
                "schema_id": evidence["schema_id"], "migration_ids": evidence["migration_ids"],
                "schema_snapshot_path": "release-evidence/database-schema.json",
                "schema_snapshot_sha256": hashlib.sha256(data).hexdigest(),
                "migration_compatibility": "same-schema-no-migration",
                "rollback_classification": "code-release-pointer", "ops3b_activation_eligible": True,
            }

    source, target = tmp_path / "source", tmp_path / "target"
    for root in (source, target):
        (root / "release-evidence").mkdir(parents=True)
        (root / "release-evidence" / "database-schema.json").write_bytes(data)
    database = tmp_path / "enterprise.db"
    conn = sqlite3.connect(database)
    try:
        ensure_db_schema_in_connection(conn)
        conn.execute("BEGIN IMMEDIATE")
        initialize_current_schema_in_transaction(conn)
        conn.commit()
    finally:
        conn.close()
    original = database.read_bytes()
    plan = _database_update_plan(
        source_root=source, target_root=target, source_manifest=Manifest(), target_manifest=Manifest(),
        database_path=database, registry=DEFAULT_MIGRATIONS, operation_id="mainline-contract-check",
    )
    assert plan["mode"] == "same-schema-no-migration"
    assert plan["registry_staged"] is False
    assert database.read_bytes() == original
