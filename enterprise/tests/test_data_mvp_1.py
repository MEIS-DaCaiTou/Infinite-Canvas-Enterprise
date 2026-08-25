from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from enterprise.migrations.versioned import (
    BASELINE_SCHEMA_VERSION,
    LEDGER_TABLE,
    STATE_PARTIAL,
    STATE_READY,
    STATE_TABLE,
    DataMigrationError,
    MigrationStep,
    apply_versioned_migrations,
    bootstrap_existing_schema_metadata,
    create_database_backup,
    finalize_release_database_validation,
    initialize_schema_metadata_in_transaction,
    inspect_schema_metadata,
    inspect_schema_metadata_connection,
    migration_registry_sha256,
    plan_migrations,
    restore_database_backup,
    schema_snapshot_sha256,
    verify_database_backup,
)
from enterprise.release.release_builder_v2 import _database_snapshot
from enterprise.release.release_manifest_v2 import canonical_json, sha256_bytes


MIGRATION_SQL = "ALTER TABLE records ADD COLUMN label TEXT NOT NULL DEFAULT ''; UPDATE records SET label='preserved'"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _create_v1_database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.executemany(
            "INSERT INTO records (id, value) VALUES (?, ?)",
            [(1, "existing-user"), (2, "existing-business-data")],
        )
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        initialize_schema_metadata_in_transaction(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _migration_1_to_2() -> MigrationStep:
    def apply(conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE records ADD COLUMN label TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE records SET label='preserved'")

    def validate(conn: sqlite3.Connection) -> bool:
        columns = [str(row[1]) for row in conn.execute("PRAGMA table_info(records)")]
        rows = conn.execute("SELECT id, value, label FROM records ORDER BY id").fetchall()
        return columns == ["id", "value", "label"] and rows == [
            (1, "existing-user", "preserved"),
            (2, "existing-business-data", "preserved"),
        ]

    return MigrationStep(
        migration_id="data_mvp_1_fixture_1_to_2",
        from_version=1,
        to_version=2,
        checksum_sha256=sha256_bytes(MIGRATION_SQL.encode("utf-8")),
        apply_in_transaction=apply,
        validate_in_transaction=validate,
    )


def _target_schema_sha256(database_path: Path, tmp_path: Path, step: MigrationStep) -> str:
    target = tmp_path / "target-schema.db"
    shutil.copyfile(database_path, target)
    conn = sqlite3.connect(target)
    try:
        conn.execute("BEGIN EXCLUSIVE")
        step.apply_in_transaction(conn)
        digest = schema_snapshot_sha256(conn)
        conn.rollback()
    finally:
        conn.close()
    return digest


def _migrate(tmp_path: Path):
    database = _create_v1_database(tmp_path / "data" / "enterprise.db")
    step = _migration_1_to_2()
    target_schema = _target_schema_sha256(database, tmp_path, step)
    result = apply_versioned_migrations(
        database,
        tmp_path / "backups",
        operation_id="update-job-001",
        target_version=2,
        expected_target_schema_sha256=target_schema,
        registry=(step,),
    )
    return database, step, target_schema, result


def test_schema_metadata_requires_transaction_and_fails_closed_on_partial_state(tmp_path: Path) -> None:
    database = tmp_path / "metadata.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY)")
        with pytest.raises(DataMigrationError) as outside_transaction:
            initialize_schema_metadata_in_transaction(conn)
        assert outside_transaction.value.code == "DATA_SCHEMA_TRANSACTION_REQUIRED"
        conn.execute(f"CREATE TABLE {STATE_TABLE} (unexpected INTEGER)")
        conn.commit()
        inspection = inspect_schema_metadata_connection(conn)
        assert inspection["current_state"] == STATE_PARTIAL
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(DataMigrationError) as partial:
            initialize_schema_metadata_in_transaction(conn)
        assert partial.value.code == "DATA_SCHEMA_METADATA_PARTIAL"
        conn.rollback()


def test_existing_schema_bootstrap_requires_exact_fingerprint_and_preserves_data(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO records VALUES (1, 'preserve-me')")
        conn.commit()
        expected_schema = schema_snapshot_sha256(conn)

    with pytest.raises(DataMigrationError) as mismatch:
        bootstrap_existing_schema_metadata(database, expected_schema_sha256="0" * 64)
    assert mismatch.value.code == "DATA_EXPECTED_SCHEMA_MISMATCH"
    assert inspect_schema_metadata(database)["current_state"] != STATE_READY

    result = bootstrap_existing_schema_metadata(database, expected_schema_sha256=expected_schema)
    assert result["current_state"] == STATE_READY
    assert result["schema_version"] == BASELINE_SCHEMA_VERSION
    assert result["migration_ids"] == []
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT id, value FROM records").fetchall() == [(1, "preserve-me")]


def test_registry_and_plan_are_deterministic_and_strict(tmp_path: Path) -> None:
    database = _create_v1_database(tmp_path / "enterprise.db")
    step = _migration_1_to_2()
    first = migration_registry_sha256((step,))
    second = migration_registry_sha256((step,))
    assert first == second
    plan = plan_migrations(database, target_version=2, registry=(step,))
    assert plan.current_version == 1
    assert plan.target_version == 2
    assert plan.registry_sha256 == first
    assert [item.migration_id for item in plan.steps] == [step.migration_id]

    gap = MigrationStep("gap", 2, 3, "a" * 64, lambda _conn: None, lambda _conn: True)
    with pytest.raises(DataMigrationError, match="DATA_MIGRATION_REGISTRY_INVALID"):
        plan_migrations(database, target_version=3, registry=(gap,))
    invalid_checksum = MigrationStep("bad", 1, 2, "not-a-hash", lambda _conn: None, lambda _conn: True)
    with pytest.raises(DataMigrationError, match="DATA_MIGRATION_REGISTRY_INVALID"):
        migration_registry_sha256((invalid_checksum,))


def test_migration_backup_and_validation_preserve_existing_data(tmp_path: Path) -> None:
    database, step, target_schema, result = _migrate(tmp_path)
    assert result.source_version == 1
    assert result.target_version == 2
    assert result.migration_ids == (step.migration_id,)
    assert result.target_schema_sha256 == target_schema
    assert verify_database_backup(result.backup.manifest_path) == result.backup

    manifest = json.loads(result.backup.manifest_path.read_text(encoding="utf-8"))
    assert set(manifest) == {
        "schema_version", "operation_id", "created_at", "database_filename", "backup_filename",
        "source_database_size_bytes", "source_database_sha256", "backup_size_bytes", "backup_sha256",
        "source_schema_version", "source_schema_sha256", "source_ledger_sha256", "integrity_check",
        "foreign_key_violation_count",
    }
    assert not any(":" in str(value) or "\\" in str(value) for value in manifest.values())
    inspection = inspect_schema_metadata(database)
    assert inspection["schema_version"] == 2
    assert inspection["migration_ids"] == [step.migration_id]
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT id, value, label FROM records ORDER BY id").fetchall() == [
            (1, "existing-user", "preserved"),
            (2, "existing-business-data", "preserved"),
        ]


def test_migration_interruption_rolls_back_schema_data_and_ledger(tmp_path: Path) -> None:
    database = _create_v1_database(tmp_path / "enterprise.db")
    source_sha = _file_sha256(database)
    first = _migration_1_to_2()

    def fail_after_write(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE must_rollback (id INTEGER PRIMARY KEY)")
        conn.execute("UPDATE records SET value='must-rollback'")
        raise sqlite3.OperationalError("fixture interruption")

    second = MigrationStep(
        "data_mvp_1_fixture_2_to_3",
        2,
        3,
        sha256_bytes(b"fixture interruption"),
        fail_after_write,
        lambda _conn: True,
    )
    with pytest.raises(DataMigrationError) as interrupted:
        apply_versioned_migrations(
            database,
            tmp_path / "backups",
            operation_id="interrupted-job",
            target_version=3,
            expected_target_schema_sha256="f" * 64,
            registry=(first, second),
        )
    assert interrupted.value.code == "DATA_MIGRATION_FAILED"
    assert _file_sha256(database) == source_sha
    inspection = inspect_schema_metadata(database)
    assert inspection["schema_version"] == 1
    assert inspection["migration_ids"] == []
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT value FROM records ORDER BY id").fetchall() == [
            ("existing-user",),
            ("existing-business-data",),
        ]
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='must_rollback'"
        ).fetchone()[0] == 0


def test_migration_callback_cannot_commit_caller_transaction(tmp_path: Path) -> None:
    database = _create_v1_database(tmp_path / "enterprise.db")

    def forbidden_commit(conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE records ADD COLUMN must_rollback TEXT")
        conn.commit()

    step = MigrationStep(
        "data_mvp_1_forbidden_commit",
        1,
        2,
        sha256_bytes(b"forbidden commit"),
        forbidden_commit,
        lambda _conn: True,
    )
    with pytest.raises(DataMigrationError) as rejected:
        apply_versioned_migrations(
            database,
            tmp_path / "backups",
            operation_id="forbidden-commit",
            target_version=2,
            expected_target_schema_sha256="f" * 64,
            registry=(step,),
        )
    assert rejected.value.code == "DATA_MIGRATION_FAILED"
    assert inspect_schema_metadata(database)["schema_version"] == 1
    with sqlite3.connect(database) as conn:
        assert "must_rollback" not in [str(row[1]) for row in conn.execute("PRAGMA table_info(records)")]


@pytest.mark.parametrize("validation_result", ["start_failed", "health_failed"])
def test_failed_new_release_validation_restores_source_database(tmp_path: Path, validation_result: str) -> None:
    database, _step, _target_schema, migration = _migrate(tmp_path)
    finalization = finalize_release_database_validation(
        database,
        migration,
        validation_result=validation_result,
    )
    assert finalization.validation_result == validation_result
    assert finalization.database_restored is True
    assert finalization.restore is not None
    assert finalization.restore.restored_database_sha256 == migration.backup.backup_sha256
    inspection = inspect_schema_metadata(database)
    assert inspection["schema_version"] == 1
    assert inspection["migration_ids"] == []
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT id, value FROM records ORDER BY id").fetchall() == [
            (1, "existing-user"),
            (2, "existing-business-data"),
        ]


def test_healthy_release_keeps_migrated_database(tmp_path: Path) -> None:
    database, _step, _target_schema, migration = _migrate(tmp_path)
    finalization = finalize_release_database_validation(database, migration, validation_result="healthy")
    assert finalization.database_restored is False
    assert finalization.restore is None
    assert inspect_schema_metadata(database)["schema_version"] == 2


def test_restore_rejects_tampered_backup_and_changed_current_database(tmp_path: Path) -> None:
    database, _step, _target_schema, migration = _migrate(tmp_path)
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE records SET value='concurrent-change' WHERE id=1")
        conn.commit()
    changed_sha = _file_sha256(database)
    with pytest.raises(DataMigrationError) as current_mismatch:
        restore_database_backup(
            database,
            migration.backup.manifest_path,
            expected_current_database_sha256=migration.post_migration_database_sha256,
        )
    assert current_mismatch.value.code == "DATA_RESTORE_EXPECTED_CURRENT_MISMATCH"
    assert _file_sha256(database) == changed_sha

    database_two, _step, _target_schema, migration_two = _migrate(tmp_path / "second")
    with migration_two.backup.backup_path.open("r+b") as handle:
        handle.seek(128)
        original = handle.read(1)
        handle.seek(128)
        handle.write(bytes([original[0] ^ 0x01]))
    with pytest.raises(DataMigrationError) as tampered:
        finalize_release_database_validation(database_two, migration_two, validation_result="start_failed")
    assert tampered.value.code == "DATA_BACKUP_IDENTITY_MISMATCH"
    assert inspect_schema_metadata(database_two)["schema_version"] == 2


def test_restore_replace_failure_preserves_migrated_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import enterprise.migrations.versioned as versioned

    database, _step, _target_schema, migration = _migrate(tmp_path)
    migrated_sha = _file_sha256(database)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("fixture replace failure")

    monkeypatch.setattr(versioned.os, "replace", fail_replace)
    with pytest.raises(DataMigrationError) as failed:
        finalize_release_database_validation(database, migration, validation_result="health_failed")
    assert failed.value.code == "DATA_RESTORE_FAILED"
    assert failed.value.database_may_have_changed is False
    assert failed.value.reread_required is False
    assert _file_sha256(database) == migrated_sha
    assert inspect_schema_metadata(database)["schema_version"] == 2
    assert list(database.parent.glob(f".{database.name}.restore-*.new")) == []


def test_restore_post_replace_sync_failure_reports_uncertain_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import enterprise.migrations.versioned as versioned

    database, _step, _target_schema, migration = _migrate(tmp_path)

    def fail_sync(_path: Path) -> str:
        raise DataMigrationError("DATA_DIRECTORY_SYNC_FAILED")

    monkeypatch.setattr(versioned, "_sync_directory", fail_sync)
    with pytest.raises(DataMigrationError) as failed:
        finalize_release_database_validation(database, migration, validation_result="start_failed")
    assert failed.value.code == "DATA_RESTORE_DIRECTORY_SYNC_FAILED"
    assert failed.value.database_may_have_changed is True
    assert failed.value.reread_required is True
    assert _file_sha256(database) == migration.backup.backup_sha256
    assert inspect_schema_metadata(database)["schema_version"] == 1


def test_release_database_snapshot_binds_versioned_schema_contract(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    payload = json.loads(_database_snapshot(repository, tmp_path / "snapshot.tmp"))
    assert payload["schema_id"] == "enterprise-database-contract-v1"
    assert payload["schema_version"] == 1
    assert payload["versioned_migration_ids"] == []
    assert payload["schema_objects_sha256"] == sha256_bytes(canonical_json(payload["objects"]))
    assert payload["migration_registry_sha256"] == migration_registry_sha256()
    assert payload["migration_ids"] == [
        "sec_1b1_role_auth",
        "sec_1b2_activation",
        "sec_1f0_security_audit",
    ]
    object_names = {item["name"] for item in payload["objects"]}
    assert {STATE_TABLE, LEDGER_TABLE, "security_audit_events", "security_governance_bootstrap"} <= object_names
