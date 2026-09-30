"""The formal schema-changing Release and greenfield install share one shape."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from enterprise.db import ensure_db_schema_in_connection
from enterprise.migrations.sec_1b2_activation import ensure_bootstrap_lifecycle_schema_in_transaction
from enterprise.migrations.versioned import (
    initialize_current_schema_in_transaction,
    schema_objects,
    schema_snapshot_sha256,
)
from enterprise.release.release_builder_v2 import _versioned_database_snapshot
from enterprise.security_audit import ensure_security_audit_schema_in_transaction


def test_builder_versioned_evidence_matches_greenfield_schema(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    evidence = json.loads(_versioned_database_snapshot(repository, tmp_path / "schema.json"))
    assert evidence["schema_version"] == 2
    assert evidence["legacy_source_schema_sha256"] == "28b7a7d5994303fdfc7a1186cde19aa1d09312c2985b13427317b04af7a97691"
    assert evidence["versioned_migration_ids"] == ["ice_096_security_schema_v2"]
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
