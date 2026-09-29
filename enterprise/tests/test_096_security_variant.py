"""The 09.6 greenfield/security-activated schema is not the 18-object baseline."""

from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from enterprise.db import ensure_db_schema_in_connection
from enterprise.migrations.sec_1b2_activation import ensure_bootstrap_lifecycle_schema_in_transaction
from enterprise.migrations.versioned import schema_objects
from enterprise.migrations.versioned import (
    DEFAULT_MIGRATIONS,
    apply_legacy_versioned_migrations,
    finalize_release_database_validation,
    inspect_schema_metadata,
    schema_snapshot_sha256,
)
from enterprise.ops.update.mvp import UpdateMvpError, _database_update_plan
from enterprise.release.release_builder_v2 import _versioned_database_snapshot
from enterprise.ops.update.legacy_security_variant import (
    SOURCE_MANIFEST_SHA256,
    SOURCE_RELEASE_ID,
    LegacySecurityVariantError,
    canonical_security_variant_objects,
    inspect_096_security_variant,
)
from enterprise.security_audit import ensure_security_audit_schema_in_transaction


def _source_database(path, *, marker=True, event=True):
    conn = sqlite3.connect(path)
    ensure_db_schema_in_connection(conn)
    baseline = schema_objects(conn)
    assert len(baseline) == 18
    conn.execute("BEGIN IMMEDIATE")
    ensure_security_audit_schema_in_transaction(conn)
    ensure_bootstrap_lifecycle_schema_in_transaction(conn)
    if marker:
        conn.execute(
            "INSERT INTO security_governance_bootstrap VALUES (1,1000,'u','u','op','local',1000)"
        )
    if event:
        conn.execute(
            """INSERT INTO security_audit_events
            (event_id,operation_id,action,risk_level,result,actor_type,context_json,created_at)
            VALUES ('event','op','security.super_admin.bootstrap','L3','success','local_operator','{}',1000)"""
        )
    conn.commit()
    return conn, baseline


def _inspect(conn, baseline):
    return inspect_096_security_variant(
        conn,
        baseline_objects=baseline,
        source_release_id=SOURCE_RELEASE_ID,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
    )


def test_recognizes_only_exact_28_object_security_schema(tmp_path):
    conn, baseline = _source_database(tmp_path / "enterprise.db")
    try:
        assert len(canonical_security_variant_objects(baseline)) == 28
        result = _inspect(conn, baseline)
        assert result["object_count"] == 28
        assert result["audit_event_count"] == 1
        assert result["bootstrap_marker_count"] == 1
        assert "marker" not in result
    finally:
        conn.close()


def test_refuses_extra_schema_or_changed_security_trigger(tmp_path):
    conn, baseline = _source_database(tmp_path / "enterprise.db")
    try:
        conn.execute("CREATE TABLE unexpected (id INTEGER)")
        with pytest.raises(LegacySecurityVariantError, match="SOURCE_SECURITY_SCHEMA_MISMATCH"):
            _inspect(conn, baseline)
        conn.execute("DROP TABLE unexpected")
        conn.execute("DROP TRIGGER trg_security_audit_no_delete")
        conn.execute(
            "CREATE TRIGGER trg_security_audit_no_delete BEFORE DELETE ON security_audit_events "
            "BEGIN SELECT RAISE(IGNORE); END"
        )
        with pytest.raises(LegacySecurityVariantError, match="SOURCE_SECURITY_SCHEMA_MISMATCH"):
            _inspect(conn, baseline)
    finally:
        conn.close()


def test_refuses_missing_marker_or_audit_event(tmp_path):
    conn, baseline = _source_database(tmp_path / "no-marker.db", marker=False)
    try:
        assert len(schema_objects(conn)) == 28
        with pytest.raises(LegacySecurityVariantError, match="SOURCE_SECURITY_BOOTSTRAP_INVALID"):
            _inspect(conn, baseline)
    finally:
        conn.close()
    conn, baseline = _source_database(tmp_path / "no-event.db", event=False)
    try:
        assert len(schema_objects(conn)) == 28
        with pytest.raises(LegacySecurityVariantError, match="SOURCE_SECURITY_AUDIT_INVALID"):
            _inspect(conn, baseline)
    finally:
        conn.close()


def test_refuses_other_source_identity(tmp_path):
    conn, baseline = _source_database(tmp_path / "enterprise.db")
    try:
        with pytest.raises(LegacySecurityVariantError, match="SOURCE_RELEASE_UNSUPPORTED"):
            inspect_096_security_variant(
                conn,
                baseline_objects=baseline,
                source_release_id=SOURCE_RELEASE_ID,
                source_manifest_sha256="0" * 64,
            )
    finally:
        conn.close()


@dataclass
class _Manifest:
    release_id: str
    raw_sha256: str
    target: bool = False

    def section(self, name):
        assert name == "database_contract"
        return {
            "schema_id": "enterprise-database-contract-v1",
            "schema_snapshot_path": "release-evidence/database-schema.json",
            "schema_snapshot_sha256": ("2" if self.target else "1") * 64,
            "migration_ids": ["sec_1b2_activation", "sec_1f0_audit"],
            "migration_compatibility": "versioned-forward-migration" if self.target else "same-schema-no-migration",
            "rollback_classification": "database-backup-restore" if self.target else "code-release-pointer",
            "ops3b_activation_eligible": self.target,
        }


def _variant_plan(tmp_path):
    conn, baseline = _source_database(tmp_path / "enterprise.db")
    conn.close()
    source = tmp_path / "source"
    target = tmp_path / "target"
    for root in (source, target):
        (root / "release-evidence").mkdir(parents=True)
    (source / "release-evidence" / "database-schema.json").write_text(
        json.dumps({"schema_id": "enterprise-database-contract-v1", "migration_ids": ["sec_1b2_activation", "sec_1f0_audit"], "objects": baseline}),
        encoding="utf-8",
    )
    evidence = _versioned_database_snapshot(Path(__file__).parents[2], tmp_path / "snapshot.json")
    (target / "release-evidence" / "database-schema.json").write_bytes(evidence)
    plan_kwargs = {
        "source_root": source,
        "target_root": target,
        "source_manifest": _Manifest(SOURCE_RELEASE_ID, SOURCE_MANIFEST_SHA256),
        "target_manifest": _Manifest("ice-2026.09.9-123456789abc", "3" * 64, target=True),
        "database_path": tmp_path / "enterprise.db",
        "registry": DEFAULT_MIGRATIONS,
        "operation_id": "a" * 32,
    }
    return plan_kwargs, json.loads(evidence)


def test_28_object_bridge_requires_explicit_opt_in_and_exact_target_evidence(tmp_path):
    kwargs, evidence = _variant_plan(tmp_path)
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_DATABASE_SOURCE_IDENTITY_MISMATCH"):
        _database_update_plan(**kwargs)
    plan = _database_update_plan(**kwargs, allow_096_security_variant=True)
    assert plan["source_variant"] == "ice-2026.09.6-security-activated-v1"
    assert plan["source_schema_sha256"] == evidence["legacy_security_variant_schema_sha256"]
    assert plan["target_schema_sha256"] == evidence["schema_objects_sha256"]
    target = kwargs["target_root"] / "release-evidence" / "database-schema.json"
    evidence["legacy_security_variant_schema_sha256"] = "0" * 64
    target.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_DATABASE_CONTRACT_UNSUPPORTED"):
        _database_update_plan(**kwargs, allow_096_security_variant=True)


def test_18_object_098_source_uses_normal_versioned_path(tmp_path):
    kwargs, evidence = _variant_plan(tmp_path)
    database = tmp_path / "enterprise-18.db"
    kwargs["database_path"] = database
    with sqlite3.connect(database) as conn:
        ensure_db_schema_in_connection(conn)
        conn.execute("INSERT INTO users (id,username,password_hash,is_admin,role,created_at) VALUES ('u','user','hash',1,'admin',1)")
        conn.commit()
    kwargs["source_manifest"] = _Manifest("ice-2026.09.8-87277c0e7f68", "4" * 64)
    plan = _database_update_plan(**kwargs)
    assert "source_variant" not in plan
    assert plan["source_schema_sha256"] == evidence["legacy_source_schema_sha256"]
    migration = apply_legacy_versioned_migrations(
        database, tmp_path / "backups", operation_id=kwargs["operation_id"],
        expected_legacy_schema_sha256=plan["source_schema_sha256"],
        expected_enrolled_schema_sha256=plan["enrolled_schema_sha256"],
        target_version=2, expected_target_schema_sha256=plan["target_schema_sha256"],
        registry=DEFAULT_MIGRATIONS,
    )
    finalize_release_database_validation(database, migration, validation_result="healthy")
    assert inspect_schema_metadata(database)["schema_version"] == 2
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT username FROM users WHERE id='u'").fetchone() == ("user",)


@pytest.mark.parametrize("validation_result", ["healthy", "start_failed"])
def test_28_object_bridge_preserves_or_restores_security_data(tmp_path, validation_result):
    kwargs, _ = _variant_plan(tmp_path)
    database = kwargs["database_path"]
    plan = _database_update_plan(**kwargs, allow_096_security_variant=True)
    migration = apply_legacy_versioned_migrations(
        database,
        tmp_path / "backups",
        operation_id=kwargs["operation_id"],
        expected_legacy_schema_sha256=plan["source_schema_sha256"],
        expected_enrolled_schema_sha256=plan["enrolled_schema_sha256"],
        target_version=plan["target_schema_version"],
        expected_target_schema_sha256=plan["target_schema_sha256"],
        registry=DEFAULT_MIGRATIONS,
    )
    result = finalize_release_database_validation(database, migration, validation_result=validation_result)
    if validation_result == "healthy":
        assert inspect_schema_metadata(database)["schema_version"] == 2
        with sqlite3.connect(database) as conn:
            assert schema_snapshot_sha256(conn) == plan["target_schema_sha256"]
            assert conn.execute("SELECT count(*) FROM security_audit_events").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM security_governance_bootstrap").fetchone()[0] == 1
    else:
        assert result.database_restored is True
        assert inspect_schema_metadata(database)["current_state"] == "DATA_SCHEMA_METADATA_MISSING"
        with sqlite3.connect(database) as conn:
            assert schema_snapshot_sha256(conn) == plan["source_schema_sha256"]
            assert conn.execute("SELECT count(*) FROM security_audit_events").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM security_governance_bootstrap").fetchone()[0] == 1
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
