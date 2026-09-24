"""Optional drill against the exact, separately verified 2026.09.5 Release.

Set ICE_095_RELEASE_ROOT to the materialized official Release directory.  No
customer data or running service is used.  The target and launcher are test
fixtures, so this is a migration/rollback drill, not a formal Release test.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from enterprise.migrations.versioned import (
    MigrationStep,
    initialize_schema_metadata_in_transaction,
    inspect_schema_metadata,
    migration_registry_sha256,
    preview_legacy_schema_enrollment,
    schema_objects,
    schema_snapshot_sha256,
)
from enterprise.ops.update.mvp import UpdateJobStore, _database_update_plan, execute_update_job
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, prepare_install_state_directories
from enterprise.release.current_release import (
    CurrentRelease,
    SCHEMA_VERSION,
    atomic_write_current_release,
    read_current_release_result_from_state_root,
)
from enterprise.release.release_manifest_v2 import read_release_manifest_v2, verify_materialized_release


SOURCE_ID = "ice-2026.09.5-7609bb1b7cfa"
TARGET_ID = "ice-2026.09.6-migration-drill"


class _DrillTargetManifest:
    release_id = TARGET_ID
    raw_sha256 = "b" * 64

    def __init__(self, source_manifest):
        self.source_manifest = source_manifest

    def section(self, name: str):
        if name == "release_payload":
            return {"inventory_path": "release-payload-inventory.json"}
        if name == "database_contract":
            source = self.source_manifest.section("database_contract")
            return {
                "schema_id": source["schema_id"],
                "schema_snapshot_path": "release-evidence/database-schema.json",
                "schema_snapshot_sha256": "c" * 64,
                "migration_ids": source["migration_ids"],
                "migration_compatibility": "versioned-forward-migration",
                "rollback_classification": "database-backup-restore",
                "ops3b_activation_eligible": True,
            }
        raise AssertionError(name)


@pytest.mark.parametrize("target_health_ok", [True, False])
def test_official_095_install_copy_migrates_or_recovers(tmp_path: Path, monkeypatch, target_health_ok: bool):
    official = os.environ.get("ICE_095_RELEASE_ROOT")
    if not official:
        pytest.skip("Set ICE_095_RELEASE_ROOT to verified official 09.5 materialization")
    official_root = Path(official).resolve()
    official_manifest = read_release_manifest_v2(official_root / "release-manifest.json")
    assert official_manifest.release_id == SOURCE_ID
    verify_materialized_release(
        official_root, inventory_path=official_root / "release-payload-inventory.json",
    )

    roots = derive_portable_path_roots(
        PortableRootInputs(tmp_path / "install", tmp_path / "local"), SOURCE_ID,
    )
    prepare_install_state_directories(roots)
    source_root = roots.RELEASE_ROOT / SOURCE_ID
    shutil.copytree(official_root, source_root)
    source_manifest = read_release_manifest_v2(source_root / "release-manifest.json")
    verify_materialized_release(
        source_root, inventory_path=source_root / "release-payload-inventory.json",
    )

    environment = os.environ.copy()
    environment.update({
        "ENTERPRISE_ENV": "development",
        "JWT_SECRET": "fixture-jwt-secret-not-production",
        "ADMIN_PASSWORD": "fixture-only-not-a-secret",
    })
    bootstrap = '''import sqlite3, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
import enterprise.db as db
roots = derive_portable_path_roots(PortableRootInputs(Path(sys.argv[2]), Path(sys.argv[3])), sys.argv[4])
db.PATH_ROOTS = roots
db.DB_PATH = "enterprise.db"
db.ADMIN_USERNAME = "fixture-admin"
db.ADMIN_PASSWORD = "fixture-only-not-a-secret"
db.init_db()
'''
    subprocess.run(
        [str(source_root / "python" / "python.exe"), "-I", "-B", "-c", bootstrap,
         str(source_root), str(roots.INSTALL_ROOT), str(tmp_path / "local"), SOURCE_ID],
        env=environment, check=True, capture_output=True, text=True,
    )
    database = roots.DATA_ROOT / "enterprise.db"
    assert not [suffix for suffix in ("-wal", "-shm") if Path(str(database) + suffix).exists()], "after official bootstrap"
    with closing(sqlite3.connect(database)) as conn:
        admin_id = "customer-drill-user"
        conn.execute(
            "INSERT INTO users (id, username, password_hash, display_name, is_admin, role, created_at) "
            "VALUES (?, ?, ?, ?, 1, 'admin', ?)",
            (admin_id, "fixture-admin", "fixture-hash", "Fixture", 1),
        )
        conn.execute(
            "INSERT INTO user_canvas_map (user_id, canvas_id, created_at) VALUES (?, ?, ?)",
            (admin_id, "customer-canvas-fixture", 1),
        )
        conn.commit()
        source_schema_sha = schema_snapshot_sha256(conn)
    assert not [suffix for suffix in ("-wal", "-shm") if Path(str(database) + suffix).exists()], "after fixture rows"
    source_evidence = json.loads((source_root / "release-evidence" / "database-schema.json").read_text(encoding="utf-8"))
    with closing(sqlite3.connect(database)) as conn:
        assert schema_objects(conn) == source_evidence["objects"]
    assert inspect_schema_metadata(database)["current_state"] == "DATA_SCHEMA_METADATA_MISSING"

    config = roots.CONFIG_ROOT / "fixture.conf"
    asset = roots.UPLOAD_ROOT / "fixture-asset.bin"
    config.parent.mkdir(parents=True, exist_ok=True)
    asset.parent.mkdir(parents=True, exist_ok=True)
    config.write_bytes(b"customer-config-fixture")
    asset.write_bytes(b"customer-asset-fixture")

    def apply(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE migration_drill_marker (id INTEGER PRIMARY KEY)")

    def validate(conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='migration_drill_marker'"
        ).fetchone()[0] == 1

    step = MigrationStep("customer-095-drill-1", 1, 2, "d" * 64, apply, validate)
    probe = tmp_path / "target-schema-probe.db"
    shutil.copyfile(database, probe)
    with closing(sqlite3.connect(probe)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        initialize_schema_metadata_in_transaction(conn)
        step.apply_in_transaction(conn)
        target_objects = schema_objects(conn)
        target_schema_sha = schema_snapshot_sha256(conn)
        conn.rollback()
    enrolled_sha = preview_legacy_schema_enrollment(
        database, expected_legacy_schema_sha256=source_schema_sha,
    )
    target_root = roots.RELEASE_ROOT / TARGET_ID
    (target_root / "release-evidence").mkdir(parents=True)
    (target_root / "release-manifest.json").write_text("test-only-target", encoding="utf-8")
    (target_root / "release-payload-inventory.json").write_text("test-only-inventory", encoding="utf-8")
    target_evidence = {
        "schema_id": source_evidence["schema_id"],
        "migration_ids": source_evidence["migration_ids"],
        "objects": target_objects,
        "schema_version": 2,
        "schema_objects_sha256": target_schema_sha,
        "migration_registry_sha256": migration_registry_sha256((step,)),
        "versioned_migration_ids": [step.migration_id],
        "legacy_source_schema_sha256": source_schema_sha,
        "legacy_enrolled_schema_sha256": enrolled_sha,
    }
    (target_root / "release-evidence" / "database-schema.json").write_text(
        json.dumps(target_evidence), encoding="utf-8",
    )
    target_manifest = _DrillTargetManifest(source_manifest)
    pointer = CurrentRelease(
        SCHEMA_VERSION, SOURCE_ID, f"releases/{SOURCE_ID}", source_manifest.raw_sha256,
        "2026-09-24T00:00:00Z", None,
    )
    atomic_write_current_release(
        roots, pointer, expected_manifest_sha256=source_manifest.raw_sha256,
    )
    pointer_sha = read_current_release_result_from_state_root(roots.STATE_ROOT).raw_sha256
    store = UpdateJobStore(roots)
    job_id, _ = store.create("fixture-admin")
    database_plan = _database_update_plan(
        source_root=source_root, target_root=target_root,
        source_manifest=source_manifest, target_manifest=target_manifest,
        database_path=database, registry=(step,), operation_id=job_id,
    )
    assert database_plan["source_schema_format"] == "legacy-exact"
    store.write_plan(job_id, {
        "job_id": job_id, "actor_user_id": "fixture-admin", "source_release_id": SOURCE_ID,
        "source_pointer_sha256": pointer_sha, "source_manifest_sha256": source_manifest.raw_sha256,
        "target_release_id": TARGET_ID, "target_manifest_sha256": target_manifest.raw_sha256,
        "target_inventory_sha256": "e" * 64, "target_payload_tree_sha256": "f" * 64,
        "database_update": database_plan,
    })
    store.write_status(job_id, "UPDATING", actor_user_id="fixture-admin", result_code="SYSTEM_UPDATE_STARTED")
    real_read = read_release_manifest_v2
    real_verify = verify_materialized_release
    monkeypatch.setattr(
        "enterprise.ops.update.mvp.read_release_manifest_v2",
        lambda path: real_read(path) if SOURCE_ID in str(path) else target_manifest,
    )
    monkeypatch.setattr(
        "enterprise.ops.update.mvp.verify_materialized_release",
        lambda root, **kwargs: real_verify(root, **kwargs) if Path(root) == source_root
        else SimpleNamespace(payload_tree_sha256="f" * 64),
    )

    def launcher(root: Path, command: str):
        if root == target_root and command == "health" and not target_health_ok:
            return 2, {"code": "DRILL_TARGET_HEALTH_FAILED"}
        return 0, {"status": "ok"}

    exit_code = execute_update_job(
        roots, job_id, launcher=launcher, database_path=database, migration_registry=(step,),
    )
    current = read_current_release_result_from_state_root(roots.STATE_ROOT).release
    assert config.read_bytes() == b"customer-config-fixture"
    assert asset.read_bytes() == b"customer-asset-fixture"
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT canvas_id FROM user_canvas_map").fetchall() == [("customer-canvas-fixture",)]
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    if target_health_ok:
        assert exit_code == 0
        assert current.release_id == TARGET_ID
        assert inspect_schema_metadata(database)["schema_version"] == 2
        assert store.read_status(job_id)["state"] == "SUCCEEDED"
    else:
        assert exit_code == 2
        assert current.release_id == SOURCE_ID
        assert inspect_schema_metadata(database)["current_state"] == "DATA_SCHEMA_METADATA_MISSING"
        assert store.read_status(job_id)["state"] == "ROLLED_BACK"
