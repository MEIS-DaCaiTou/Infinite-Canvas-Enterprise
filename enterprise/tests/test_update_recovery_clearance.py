from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request

from enterprise.ops.update.mvp import UpdateJobStore, UpdateMvpError
from enterprise.ops.update.recovery import _database_identity, assess_recovery, clear_recovery, write_recovery_security_audit
from enterprise.migrations.versioned import (
    initialize_schema_metadata_in_transaction,
    migration_registry_sha256,
    schema_objects,
    schema_snapshot_sha256,
)
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, prepare_install_state_directories
from enterprise.release.current_release import CurrentRelease, atomic_write_current_release
from enterprise.security_audit import ensure_security_audit_schema_in_transaction


def _roots(tmp_path: Path):
    roots = derive_portable_path_roots(PortableRootInputs(tmp_path / "install", tmp_path / "local"), "release-A")
    prepare_install_state_directories(roots)
    for path in (roots.RELEASE_ROOT, roots.STAGING_ROOT, roots.LOG_ROOT, roots.RUNTIME_ROOT):
        path.mkdir(parents=True, exist_ok=True)
    return roots


def _recovery_job(tmp_path: Path, monkeypatch):
    from enterprise.ops.update import recovery

    roots = _roots(tmp_path)
    source_root = roots.RELEASE_ROOT / "release-A"
    source_root.mkdir()
    store = UpdateJobStore(roots)
    job_id, job_root = store.create("original-actor")
    atomic_write_current_release(roots, CurrentRelease(
        "env-1b1b-current-release-v1", "release-A", "releases/release-A", "a" * 64,
        "2026-09-23T00:00:00Z", None,
    ))
    store.write_plan(job_id, {
        "job_id": job_id, "actor_user_id": "original-actor",
        "source_release_id": "release-A", "target_release_id": "release-B",
        "source_manifest_sha256": "a" * 64, "target_manifest_sha256": "b" * 64,
    })
    store.write_status(
        job_id, "RECOVERY_REQUIRED", actor_user_id="original-actor",
        result_code="SYSTEM_UPDATE_DATABASE_RESTORE_INCOMPLETE",
        source_release_id="release-A", target_release_id="release-B",
    )
    manifest = SimpleNamespace(release_id="release-A", raw_sha256="a" * 64, section=lambda _name: {"inventory_path": "release-payload-inventory.json"})
    monkeypatch.setattr(recovery, "read_release_manifest_v2", lambda _path: manifest)
    monkeypatch.setattr(recovery, "verify_materialized_release", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recovery, "_database_identity", lambda *_args: {"mode": "versioned", "schema_version": 1, "schema_sha256": "c" * 64})
    return roots, store, job_id, job_root


def test_recovery_clearance_requires_fresh_identity_and_writes_audit_last(tmp_path: Path, monkeypatch):
    roots, store, job_id, job_root = _recovery_job(tmp_path, monkeypatch)
    database = roots.DATA_ROOT / "enterprise.db"
    launcher = lambda _root, command: (0, {"result": "healthy"}) if command == "health" else (2, {})
    report = assess_recovery(roots, job_id, database_path=database, launcher=launcher)
    audits = []
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_RECOVERY_ASSESSMENT_CHANGED"):
        clear_recovery(
            roots, job_id, database_path=database, actor_user_id="new-actor",
            expected_release_id="release-A", expected_assessment_sha256="0" * 64,
            manual_evidence_note="checked data and backup ticket R-123",
            audit=lambda *args, **kwargs: audits.append((args, kwargs)), launcher=launcher,
        )
    assert store.read_status(job_id)["state"] == "RECOVERY_REQUIRED"
    assert not audits
    assert not store.lock_path.exists()

    result = clear_recovery(
        roots, job_id, database_path=database, actor_user_id="new-actor",
        expected_release_id="release-A", expected_assessment_sha256=report["assessment_sha256"],
        manual_evidence_note="checked data and backup ticket R-123",
        audit=lambda *args, **kwargs: audits.append((args, kwargs)), launcher=launcher,
    )
    assert result["state"] == "RECOVERY_CLEARED"
    assert result["current_release_id"] == "release-A"
    assert len(audits) == 1 and audits[0][1]["job_id"] == job_id
    assert store.pending_recovery_jobs() == []
    assert not store.lock_path.exists()
    clearance = json.loads((job_root / result["recovery_clearance_file"]).read_text(encoding="utf-8"))
    assert clearance["assessment"]["assessment_sha256"] == report["assessment_sha256"]
    assert clearance["actor_user_id"] == "new-actor"
    assert clearance["manual_evidence_note"] == "checked data and backup ticket R-123"
    events = (job_root / "events.jsonl").read_text(encoding="utf-8")
    assert "SYSTEM_UPDATE_RECOVERY_CLEARED" in events
    new_job, _ = store.create("another-actor")
    store.reserve_execution(new_job)
    handle = store.acquire_execution_lock(new_job)
    store.release_execution_lock(handle, new_job)


def test_failed_recovery_verification_or_audit_keeps_update_blocked(tmp_path: Path, monkeypatch):
    roots, store, job_id, _ = _recovery_job(tmp_path, monkeypatch)
    database = roots.DATA_ROOT / "enterprise.db"
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_RECOVERY_HEALTH_UNVERIFIED"):
        assess_recovery(roots, job_id, database_path=database, launcher=lambda *_: (2, {}))
    assert store.pending_recovery_jobs() == [job_id]
    report = assess_recovery(roots, job_id, database_path=database, launcher=lambda *_: (0, {}))
    with pytest.raises(RuntimeError, match="audit unavailable"):
        clear_recovery(
            roots, job_id, database_path=database, actor_user_id="new-actor",
            expected_release_id="release-A", expected_assessment_sha256=report["assessment_sha256"],
            manual_evidence_note="checked data and backup ticket R-123",
            audit=lambda *_, **__: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
            launcher=lambda *_: (0, {}),
        )
    assert store.read_status(job_id)["state"] == "RECOVERY_REQUIRED"
    assert store.pending_recovery_jobs() == [job_id]
    assert not store.lock_path.exists()


def test_corrupt_clearance_record_fails_closed(tmp_path: Path, monkeypatch):
    roots, store, job_id, job_root = _recovery_job(tmp_path, monkeypatch)
    database = roots.DATA_ROOT / "enterprise.db"
    report = assess_recovery(roots, job_id, database_path=database, launcher=lambda *_: (0, {}))
    result = clear_recovery(
        roots, job_id, database_path=database, actor_user_id="new-actor",
        expected_release_id="release-A", expected_assessment_sha256=report["assessment_sha256"],
        manual_evidence_note="checked data and backup ticket R-123",
        audit=lambda *_, **__: None, launcher=lambda *_: (0, {}),
    )
    (job_root / result["recovery_clearance_file"]).write_text("{}", encoding="utf-8")
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED"):
        store.pending_recovery_jobs()


def test_legacy_database_identity_requires_exact_schema_and_integrity(tmp_path: Path):
    app_root = tmp_path / "app"
    evidence_path = app_root / "release-evidence" / "database-schema.json"
    evidence_path.parent.mkdir(parents=True)
    database = tmp_path / "enterprise.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        objects = schema_objects(conn)
    evidence_path.write_text(json.dumps({"schema_id": "enterprise-database-contract-v1", "migration_ids": ["sqlite_existing"], "objects": objects}), encoding="utf-8")
    manifest = SimpleNamespace(section=lambda name: {
        "database_contract": {"schema_id": "enterprise-database-contract-v1", "migration_ids": ["sqlite_existing"], "schema_snapshot_path": "release-evidence/database-schema.json"},
    }[name])
    result = _database_identity(database, app_root, manifest)
    assert result["mode"] == "legacy-exact-schema"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE unexpected (id INTEGER)")
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED"):
        _database_identity(database, app_root, manifest)


def test_versioned_database_recovery_identity_uses_schema_fingerprint(tmp_path: Path):
    app_root = tmp_path / "app"
    evidence_path = app_root / "release-evidence" / "database-schema.json"
    evidence_path.parent.mkdir(parents=True)
    database = tmp_path / "enterprise.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sample (value) VALUES ('customer-data')")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        initialize_schema_metadata_in_transaction(conn)
        conn.commit()
        schema_hash = schema_snapshot_sha256(conn)
    evidence_path.write_text(json.dumps({
        "schema_version": 1,
        "schema_objects_sha256": schema_hash,
        "migration_registry_sha256": migration_registry_sha256(()),
        "versioned_migration_ids": [],
    }), encoding="utf-8")
    manifest = SimpleNamespace(section=lambda name: {
        "database_contract": {
            "schema_id": "enterprise-database-contract-v1",
            "schema_snapshot_path": "release-evidence/database-schema.json",
        },
    }[name])
    result = _database_identity(database, app_root, manifest)
    assert result["mode"] == "versioned"
    assert result["schema_version"] == 1
    assert result["schema_sha256"] == schema_hash
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE unexpected (id INTEGER)")
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED"):
        _database_identity(database, app_root, manifest)


def test_clearance_api_rejects_bad_password_without_touching_state(tmp_path: Path, monkeypatch):
    from enterprise import update_api

    roots, store, job_id, _ = _recovery_job(tmp_path, monkeypatch)
    actor = {"id": "admin", "role": "super_admin", "is_active": True, "auth_version": 1, "password_hash": "fixture"}
    monkeypatch.setattr(update_api, "PATH_ROOTS", roots)
    monkeypatch.setattr(update_api, "ENTERPRISE_UPDATE_ENABLED", True)
    monkeypatch.setattr(update_api.edb, "get_user_by_id", lambda _id: actor)
    monkeypatch.setattr(update_api.edb, "can_use_feature", lambda *_: True)
    monkeypatch.setattr(update_api.edb, "verify_password", lambda *_: False)
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user = {"user_id": "admin", "auth_version": 1}
        return await call_next(request)

    app.include_router(update_api.router, prefix="/enterprise")

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            pending = await client.get("/enterprise/api/update-mvp/recovery/pending")
            rejected = await client.post(
                f"/enterprise/api/update-mvp/jobs/{job_id}/recovery-clearance",
                json={"password": "bad", "expected_release_id": "release-A", "expected_assessment_sha256": "f" * 64,
                      "manual_evidence_note": "checked data and backup ticket R-123"},
            )
        return pending, rejected

    pending, rejected = asyncio.run(exercise())
    assert pending.status_code == 200 and pending.json() == {"job_ids": [job_id]}
    assert rejected.status_code == 403
    assert store.read_status(job_id)["state"] == "RECOVERY_REQUIRED"


def test_clearance_security_audit_is_persisted_or_raises(tmp_path: Path):
    database = tmp_path / "audit.db"
    with sqlite3.connect(database) as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_security_audit_schema_in_transaction(conn)
        conn.commit()
    write_recovery_security_audit(
        database, actor_user_id="admin", job_id="a" * 32,
        current_release_id="release-A", assessment_sha256="b" * 64,
        clearance_sha256="c" * 64,
        manual_evidence_note="checked data and backup ticket R-123",
    )
    with sqlite3.connect(database) as conn:
        rows = conn.execute(
            "SELECT action, risk_level, actor_user_id, target_id, reason FROM security_audit_events"
        ).fetchall()
    assert rows == [(
        "security.system_update.recovery_clearance", "L3", "admin", "a" * 32,
        "checked data and backup ticket R-123",
    )]
    with pytest.raises(Exception):
        write_recovery_security_audit(
            tmp_path / "absent.db", actor_user_id="admin", job_id="a" * 32,
            current_release_id="release-A", assessment_sha256="b" * 64,
            clearance_sha256="c" * 64,
            manual_evidence_note="checked data and backup ticket R-123",
        )
    assert not (tmp_path / "absent.db").exists()
