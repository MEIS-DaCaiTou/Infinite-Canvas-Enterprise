from __future__ import annotations

import json
import asyncio
import shutil
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from enterprise.ops.update.diagnostics import diagnostics_zip, recent_diagnostics
from enterprise.ops.update.handoff import _emit_terminal_audit, _finalize_terminal_failure
from enterprise.ops.update.mvp import (
    PreparedUpdate,
    UpdateJobStore,
    UpdateMvpError,
    _database_contract_compatible,
    _database_update_plan,
    execute_update_job,
)
from enterprise.migrations.versioned import (
    DataMigrationError,
    MigrationStep,
    initialize_schema_metadata_in_transaction,
    inspect_schema_metadata,
    migration_registry_sha256,
    preview_legacy_schema_enrollment,
    schema_objects,
    schema_snapshot_sha256,
)
from enterprise.release.release_builder_v2 import _database_snapshot
from enterprise.ops.update.providers import DEFAULT_GITHUB_REPOSITORY, GitHubReleasesProvider
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, prepare_install_state_directories
from enterprise.release.current_release import (
    CurrentRelease,
    CurrentReleaseError,
    atomic_write_current_release,
    canonical_json as pointer_json,
    read_current_release_result_from_state_root,
)
from enterprise.release.release_manifest_v2 import canonical_json, parse_release_manifest_v2_bytes
from enterprise.tests.release_manifest_v2_fixture import release_manifest


def _roots(tmp_path: Path):
    roots = derive_portable_path_roots(PortableRootInputs(tmp_path / "install", tmp_path / "local"), "release-A")
    prepare_install_state_directories(roots)
    for path in (roots.RELEASE_ROOT, roots.STAGING_ROOT, roots.LOG_ROOT, roots.RUNTIME_ROOT):
        path.mkdir(parents=True, exist_ok=True)
    return roots


def test_prepare_sync_workflow_does_not_block_gateway_event_loop(monkeypatch):
    from enterprise import update_api

    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    worker_thread_ids: list[int] = []

    def slow_prepare(actor_user_id: str, provider_release_id: str):
        worker_thread_ids.append(threading.get_ident())
        assert actor_user_id == "actor-1"
        assert provider_release_id == "release-2"
        started.set()
        assert release.wait(5), "slow prepare fixture was not released"
        completed.set()
        return {"state": "READY", "job_id": "a" * 32}

    current = {
        "id": "actor-1", "role": "super_admin", "is_admin": True,
        "is_active": True, "auth_version": 1,
    }
    monkeypatch.setattr(update_api, "ENTERPRISE_UPDATE_ENABLED", True)
    monkeypatch.setattr(update_api.edb, "get_user_by_id", lambda _uid: current)
    monkeypatch.setattr(update_api.edb, "can_use_feature", lambda *_args: True)
    monkeypatch.setattr(update_api, "_prepare_update_sync", slow_prepare)

    app = FastAPI()

    @app.middleware("http")
    async def fixture_identity(request: Request, call_next):
        request.state.user = {
            "user_id": "actor-1", "role": "super_admin", "is_admin": True,
            "auth_version": 1,
        }
        return await call_next(request)

    @app.get("/probe")
    async def probe():
        return {"responsive": True}

    app.include_router(update_api.router, prefix="/enterprise")

    async def exercise():
        event_loop_thread_id = threading.get_ident()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://fixture") as client:
            prepare = asyncio.create_task(client.post(
                "/enterprise/api/update-mvp/prepare",
                json={"provider_release_id": "release-2"},
            ))
            assert await asyncio.to_thread(started.wait, 2)
            concurrent = await asyncio.wait_for(client.get("/probe"), timeout=1)
            assert concurrent.status_code == 200
            assert concurrent.json() == {"responsive": True}
            assert prepare.done() is False
            release.set()
            prepared = await asyncio.wait_for(prepare, timeout=2)
        return event_loop_thread_id, prepared

    event_loop_thread_id, prepared = asyncio.run(exercise())
    assert completed.is_set()
    assert worker_thread_ids and worker_thread_ids[0] != event_loop_thread_id
    assert prepared.status_code == 200
    assert prepared.json() == {"state": "READY", "job_id": "a" * 32}


@pytest.mark.parametrize("mode", ["same-schema-no-migration", "versioned-forward-migration"])
def test_prepared_update_exposes_database_mode_without_plan_details(mode: str):
    prepared = PreparedUpdate(
        "a" * 32, "release-A", "release-B", "b" * 64, "c" * 64,
        mode,
    )
    public = prepared.public()
    assert public["database_update_mode"] == mode
    assert "migration_ids" not in public


def _eligible_manifest():
    payload = release_manifest(release_id="ice-2026.07.6-bbbbbbbbbbbb").data
    payload["database_contract"].update(
        {
            "migration_compatibility": "same-schema-no-migration",
            "rollback_classification": "code-release-pointer",
            "ops3b_activation_eligible": True,
        }
    )
    return parse_release_manifest_v2_bytes(canonical_json(payload))


def test_manifest_v2_accepts_only_the_narrow_online_update_database_classification():
    source = release_manifest(release_id="ice-2026.07.6-bbbbbbbbbbbb")
    target = _eligible_manifest()
    assert _database_contract_compatible(source, target) is True
    for key, value in (
        ("migration_compatibility", "forward"),
        ("rollback_classification", "restore-database"),
        ("ops3b_activation_eligible", False),
    ):
        payload = target.data
        payload["database_contract"][key] = value
        with pytest.raises(Exception):
            parse_release_manifest_v2_bytes(canonical_json(payload))


def test_github_v2_provider_requires_the_closed_three_asset_set():
    def asset(name: str, asset_id: int):
        return {
            "id": asset_id, "name": name, "state": "uploaded", "size": asset_id,
            "url": f"https://api.github.com/repos/{DEFAULT_GITHUB_REPOSITORY}/releases/assets/{asset_id}",
        }

    complete = {
        "id": 90, "tag_name": "v2026.08.1", "draft": False, "prerelease": False,
        "published_at": "2026-08-13T00:00:00Z", "body": "notes",
        "assets": [
            asset("ops-release-manifest-v2.json", 1),
            asset("release-payload-inventory.json", 2),
            asset("Infinite-Canvas-Enterprise-ice-2026.08.1-aabbccddeeff-win-x64.zip", 3),
        ],
    }
    incomplete = {**complete, "id": 89, "assets": [asset("ops-release-manifest-v2.json", 4)]}
    ambiguous_visibility = {**complete, "id": 88, "draft": None}

    class Client:
        def read_json(self, *_args, **_kwargs):
            return [incomplete, ambiguous_visibility, complete]

    provider = GitHubReleasesProvider(http_client=Client())
    candidates = provider.list_release_v2_candidates()
    assert len(candidates) == 1
    assert candidates[0].provider_release_id == "90"
    assert candidates[0].manifest_url.endswith("/1")
    assert candidates[0].inventory_url.endswith("/2")
    assert candidates[0].archive_url.endswith("/3")


def test_database_contract_allows_signed_evidence_change_but_not_legacy_migration_change():
    source = release_manifest(release_id="ice-2026.07.6-bbbbbbbbbbbb")
    payload = _eligible_manifest().data
    payload["database_contract"]["schema_snapshot_sha256"] = "f" * 64
    target = parse_release_manifest_v2_bytes(canonical_json(payload))
    assert _database_contract_compatible(source, target) is True

    payload["database_contract"]["migration_ids"] = ["new-migration"]
    target = parse_release_manifest_v2_bytes(canonical_json(payload))
    assert _database_contract_compatible(source, target) is False


def test_manifest_accepts_only_explicit_versioned_forward_migration_pair():
    source = release_manifest(release_id="ice-2026.07.6-bbbbbbbbbbbb")
    payload = _eligible_manifest().data
    payload["database_contract"].update({
        "schema_snapshot_sha256": "f" * 64,
        "migration_compatibility": "versioned-forward-migration",
        "rollback_classification": "database-backup-restore",
    })
    target = parse_release_manifest_v2_bytes(canonical_json(payload))
    assert _database_contract_compatible(source, target) is True


def test_current_release_compare_before_switch_is_fail_closed(tmp_path: Path):
    roots = _roots(tmp_path)
    roots.APP_ROOT.mkdir(parents=True)
    source = CurrentRelease(
        "env-1b1b-current-release-v1", "release-A", "releases/release-A", "a" * 64,
        "2026-08-13T00:00:00Z", None,
    )
    atomic_write_current_release(roots, source)
    accepted = read_current_release_result_from_state_root(roots.STATE_ROOT)
    (roots.STATE_ROOT / "current-release.json").write_bytes(pointer_json(CurrentRelease(
        source.schema_version, source.release_id, source.app_root_relative, source.manifest_sha256,
        "2026-08-13T00:00:01Z", source.previous_release_id,
    )))
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_EXPECTED_IDENTITY_MISMATCH"):
        atomic_write_current_release(roots, source, expected_existing_raw_sha256=accepted.raw_sha256)


def test_job_store_is_durable_bounded_and_password_free(tmp_path: Path):
    store = UpdateJobStore(_roots(tmp_path))
    job_id, root = store.create("actor-1")
    plan_sha = store.write_plan(job_id, {
        "job_id": job_id, "actor_user_id": "actor-1", "source_release_id": "release-A",
        "source_pointer_sha256": "a" * 64, "source_manifest_sha256": "b" * 64,
        "target_release_id": "release-B", "target_manifest_sha256": "c" * 64,
        "target_inventory_sha256": "d" * 64, "target_payload_tree_sha256": "e" * 64,
    })
    status = store.write_status(job_id, "READY", actor_user_id="actor-1", result_code="SYSTEM_UPDATE_READY", plan_sha256=plan_sha)
    assert status["state"] == "READY"
    persisted = (root / "plan.json").read_text(encoding="utf-8") + (root / "status.json").read_text(encoding="utf-8")
    assert "password" not in persisted.casefold()
    assert store.read_plan(job_id)["target_release_id"] == "release-B"


def test_one_active_update_reservation_blocks_a_second_job(tmp_path: Path):
    store = UpdateJobStore(_roots(tmp_path))
    first, _ = store.create("actor-1")
    second, _ = store.create("actor-2")
    store.reserve_execution(first)
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_ALREADY_ACTIVE"):
        store.reserve_execution(second)
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_ALREADY_ACTIVE"):
        store.reserve_execution(first)
    handle = store.acquire_execution_lock(first)
    store.release_execution_lock(handle, first)


def test_recovery_required_blocks_prepare_and_new_execution(tmp_path: Path, monkeypatch):
    from enterprise import update_api

    roots = _roots(tmp_path)
    store = UpdateJobStore(roots)
    old_job, _ = store.create("actor-1")
    store.write_status(
        old_job, "RECOVERY_REQUIRED", actor_user_id="actor-1",
        result_code="SYSTEM_UPDATE_DATABASE_RESTORE_INCOMPLETE",
    )
    new_job, _ = store.create("actor-2")
    monkeypatch.setattr(update_api, "PATH_ROOTS", roots)
    monkeypatch.setattr(update_api, "_provider", lambda: pytest.fail("provider must not be called"))
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_RECOVERY_REQUIRED") as prepare_error:
        update_api._prepare_update_sync("actor-2", "fixture-release")
    assert prepare_error.value.status_code == 409
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_RECOVERY_REQUIRED") as execute_error:
        store.reserve_execution(new_job)
    assert execute_error.value.status_code == 409
    assert not store.lock_path.exists()


def test_unverifiable_prior_job_state_blocks_new_execution(tmp_path: Path):
    store = UpdateJobStore(_roots(tmp_path))
    old_job, old_root = store.create("actor-1")
    (old_root / "status.json").write_text("{broken", encoding="utf-8")
    new_job, _ = store.create("actor-2")
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED") as error:
        store.reserve_execution(new_job)
    assert error.value.status_code == 409
    assert not store.lock_path.exists()


def _reserved_worker_job(tmp_path: Path):
    roots = _roots(tmp_path)
    store = UpdateJobStore(roots)
    job_id, root = store.create("actor-1")
    store.write_plan(job_id, {
        "job_id": job_id, "actor_user_id": "actor-1",
        "source_release_id": "release-A", "target_release_id": "release-B",
    })
    store.write_status(
        job_id, "UPDATING", actor_user_id="actor-1",
        result_code="SYSTEM_UPDATE_STARTED",
    )
    store.reserve_execution(job_id)
    return roots, store, job_id, root


def test_source_stop_timeout_finalizes_evidence_and_releases_matching_reservation(tmp_path: Path, monkeypatch):
    roots, store, job_id, root = _reserved_worker_job(tmp_path)
    audits = []
    monkeypatch.setattr(
        "enterprise.ops.update.handoff._emit_terminal_audit",
        lambda plan, code: audits.append((dict(plan), code)),
    )
    assert _finalize_terminal_failure(
        roots, job_id, "SYSTEM_UPDATE_SOURCE_STOP_TIMEOUT"
    ) is True
    status = store.read_status(job_id)
    assert status["state"] == "FAILED"
    assert status["result_code"] == "SYSTEM_UPDATE_SOURCE_STOP_TIMEOUT"
    events = [json.loads(line) for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[-1]["state"] == "FAILED"
    assert events[-1]["code"] == "SYSTEM_UPDATE_SOURCE_STOP_TIMEOUT"
    assert audits == [(
        store.read_plan(job_id), "SYSTEM_UPDATE_SOURCE_STOP_TIMEOUT"
    )]
    assert not store.lock_path.exists()

    subsequent, _ = store.create("actor-2")
    store.reserve_execution(subsequent)
    handle = store.acquire_execution_lock(subsequent)
    store.release_execution_lock(handle, subsequent)


def test_terminal_failure_preserves_foreign_reservation(tmp_path: Path, monkeypatch):
    roots = _roots(tmp_path)
    store = UpdateJobStore(roots)
    current_job, _ = store.create("actor-1")
    foreign_job, _ = store.create("actor-2")
    store.write_plan(current_job, {
        "job_id": current_job, "actor_user_id": "actor-1",
        "source_release_id": "release-A", "target_release_id": "release-B",
    })
    store.write_status(
        current_job, "UPDATING", actor_user_id="actor-1",
        result_code="SYSTEM_UPDATE_STARTED",
    )
    store.reserve_execution(foreign_job)
    before = store.lock_path.read_bytes()
    monkeypatch.setattr("enterprise.ops.update.handoff._emit_terminal_audit", lambda *_args: None)
    assert _finalize_terminal_failure(
        roots, current_job, "SYSTEM_UPDATE_SOURCE_STOP_TIMEOUT"
    ) is False
    assert store.lock_path.read_bytes() == before
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_ALREADY_ACTIVE"):
        store.reserve_execution(current_job)
    handle = store.acquire_execution_lock(foreign_job)
    store.release_execution_lock(handle, foreign_job)


def test_terminal_failure_evidence_is_bounded_nonsecret_and_not_false_rollback(tmp_path: Path, monkeypatch):
    roots, store, job_id, root = _reserved_worker_job(tmp_path)
    audits = []
    monkeypatch.setattr(
        "enterprise.ops.update.handoff._emit_terminal_audit",
        lambda plan, code: audits.append({
            "job_id": plan["job_id"], "source_release_id": plan["source_release_id"],
            "target_release_id": plan["target_release_id"], "result_code": code,
        }),
    )
    assert _finalize_terminal_failure(roots, job_id, "SYSTEM_UPDATE_WORKER_FAILED") is True
    evidence = (
        (root / "status.json").read_text(encoding="utf-8")
        + (root / "events.jsonl").read_text(encoding="utf-8")
        + json.dumps(audits)
    )
    lowered = evidence.casefold()
    for forbidden in ("password", "authorization", "bearer", "token", "traceback", str(tmp_path).casefold()):
        assert forbidden not in lowered
    assert "rolled_back" not in lowered


@pytest.mark.parametrize("interrupted_state", ["MIGRATING", "RESTARTING", "VERIFYING"])
def test_worker_interruption_after_database_or_pointer_work_requires_recovery(
    tmp_path: Path, monkeypatch, interrupted_state: str
):
    roots, store, job_id, root = _reserved_worker_job(tmp_path)
    store.write_status(
        job_id,
        interrupted_state,
        actor_user_id="actor-1",
        result_code="SYSTEM_UPDATE_IN_PROGRESS",
    )
    monkeypatch.setattr("enterprise.ops.update.handoff._emit_terminal_audit", lambda *_args: None)
    assert _finalize_terminal_failure(roots, job_id, "SYSTEM_UPDATE_WORKER_FAILED") is True
    status = store.read_status(job_id)
    assert status["state"] == "RECOVERY_REQUIRED"
    assert status["recovery_required"] is True
    assert status["interrupted_state"] == interrupted_state
    events = [json.loads(line) for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[-1]["state"] == "RECOVERY_REQUIRED"


def test_terminal_failure_audit_is_fixed_bounded_and_nonsecret(monkeypatch):
    calls = []
    monkeypatch.setattr("enterprise.db.log_action", lambda *args: calls.append(args))
    _emit_terminal_audit(
        {
            "job_id": "a" * 32,
            "actor_user_id": "actor-1",
            "source_release_id": "release-A",
            "target_release_id": "release-B",
            "ignored": "password=not-exported Authorization: Bearer not-exported",
        },
        "SYSTEM_UPDATE_SOURCE_STOP_TIMEOUT",
    )
    assert calls[0][0:2] == ("actor-1", "system_update_failed")
    detail = json.loads(calls[0][2])
    assert set(detail) == {"job_id", "source_release_id", "target_release_id", "result_code"}
    assert detail["result_code"] == "SYSTEM_UPDATE_SOURCE_STOP_TIMEOUT"
    assert len(calls[0][2].encode("utf-8")) < 1024
    assert "password" not in calls[0][2].casefold() and "bearer" not in calls[0][2].casefold()


@dataclass
class _Manifest:
    release_id: str
    raw_sha256: str
    migration_target: bool = False
    registry_stage: bool = False
    migration_ids: tuple[str, ...] = ("base",)

    def section(self, name: str):
        if name == "release_payload":
            return {"inventory_path": "release-payload-inventory.json"}
        if name == "database_contract":
            target = self.release_id == "release-B"
            return {
                "schema_id": "enterprise-database-contract-v1",
                "schema_snapshot_path": "release-evidence/database-schema.json",
                "schema_snapshot_sha256": (
                    "8" if target and (self.migration_target or self.registry_stage) else "9"
                ) * 64,
                "migration_ids": list(self.migration_ids),
                "migration_compatibility": (
                    "versioned-forward-migration"
                    if target and self.migration_target
                    else "same-schema-no-migration" if target else "unclassified"
                ),
                "rollback_classification": (
                    "database-backup-restore"
                    if target and self.migration_target
                    else "code-release-pointer" if target else "unclassified"
                ),
                "ops3b_activation_eligible": target,
            }
        raise AssertionError(name)


def _execution_fixture(
    tmp_path: Path,
    monkeypatch,
    *,
    target_start_exit: int = 0,
    target_health_exit: int = 0,
    database_update: dict[str, object] | None = None,
    migration_target: bool = False,
):
    roots = _roots(tmp_path)
    source_root = roots.RELEASE_ROOT / "release-A"
    target_root = roots.RELEASE_ROOT / "release-B"
    source_root.mkdir(exist_ok=True); target_root.mkdir(exist_ok=True)
    for root in (source_root, target_root):
        (root / "release-manifest.json").write_text("fixture", encoding="utf-8")
        (root / "release-payload-inventory.json").write_text("fixture", encoding="utf-8")
    store = UpdateJobStore(roots)
    job_id, _ = store.create("actor-1")
    pointer = SimpleNamespace(
        release=SimpleNamespace(release_id="release-A"),
        raw_sha256="a" * 64,
    )
    plan = {
        "job_id": job_id, "actor_user_id": "actor-1", "source_release_id": "release-A",
        "source_pointer_sha256": "a" * 64, "source_manifest_sha256": "1" * 64,
        "target_release_id": "release-B", "target_manifest_sha256": "2" * 64,
        "target_inventory_sha256": "3" * 64, "target_payload_tree_sha256": "4" * 64,
    }
    if database_update is not None:
        plan["database_update"] = {**database_update, "operation_id": job_id}
    store.write_plan(job_id, plan)
    store.write_status(job_id, "UPDATING", actor_user_id="actor-1", result_code="SYSTEM_UPDATE_STARTED")

    def read_manifest(path: Path):
        return (
            _Manifest("release-A", "1" * 64, migration_target)
            if "release-A" in str(path)
            else _Manifest("release-B", "2" * 64, migration_target)
        )

    def read_pointer(_path: Path):
        return pointer

    def write_pointer(_roots, value, **_kwargs):
        pointer.release = SimpleNamespace(release_id=value.release_id)
        pointer.raw_sha256 = "b" * 64 if value.release_id == "release-B" else "c" * 64
        return SimpleNamespace(pointer_replaced=True)

    monkeypatch.setattr("enterprise.ops.update.mvp.read_release_manifest_v2", read_manifest)
    monkeypatch.setattr(
        "enterprise.ops.update.mvp.verify_materialized_release",
        lambda *a, **k: SimpleNamespace(payload_tree_sha256="4" * 64),
    )
    monkeypatch.setattr(
        "enterprise.ops.update.mvp._database_update_plan",
        lambda **_kwargs: plan.get("database_update") or {"mode": "same-schema-no-migration"},
    )
    monkeypatch.setattr("enterprise.ops.update.mvp.read_current_release_result_from_state_root", read_pointer)
    monkeypatch.setattr("enterprise.ops.update.mvp.atomic_write_current_release", write_pointer)
    calls = []

    def launcher(root: Path, command: str):
        calls.append((root.name, command))
        if root.name == "release-B" and command == "start" and target_start_exit:
            return target_start_exit, {"code": "TARGET_START_BLOCKED"}
        if root.name == "release-B" and command == "health" and target_health_exit:
            return target_health_exit, {"code": "TARGET_HEALTH_BLOCKED"}
        return 0, {"status": "ok"}

    return roots, store, job_id, pointer, calls, launcher


def test_execute_success_switches_once_and_verifies_health(tmp_path: Path, monkeypatch):
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(tmp_path, monkeypatch)
    assert execute_update_job(roots, job_id, launcher=launcher) == 0
    assert pointer.release.release_id == "release-B"
    assert calls == [("release-B", "start"), ("release-B", "health")]
    assert store.read_status(job_id)["state"] == "SUCCEEDED"
    assert not store.lock_path.exists()


def test_target_start_failure_rolls_pointer_back_and_restores_source(tmp_path: Path, monkeypatch):
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(tmp_path, monkeypatch, target_start_exit=2)
    assert execute_update_job(roots, job_id, launcher=launcher) == 2
    assert pointer.release.release_id == "release-A"
    assert calls == [
        ("release-B", "start"), ("release-B", "stop"),
        ("release-A", "start"), ("release-A", "health"),
    ]
    status = store.read_status(job_id)
    assert status["state"] == "ROLLED_BACK" and status["result_code"] == "TARGET_START_BLOCKED"


def _create_update_database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO records (id, value) VALUES (1, 'preserved')")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        initialize_schema_metadata_in_transaction(conn)
        conn.commit()
    return path


def _update_migration_step(*, validation_result: bool = True) -> MigrationStep:
    def apply(conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE records ADD COLUMN label TEXT NOT NULL DEFAULT 'migrated'")

    def validate(conn: sqlite3.Connection) -> bool:
        columns = [str(row[1]) for row in conn.execute("PRAGMA table_info(records)")]
        return validation_result and columns == ["id", "value", "label"]

    return MigrationStep("update-data-1", 1, 2, "7" * 64, apply, validate)


def _target_schema_sha256(database: Path, tmp_path: Path, step: MigrationStep) -> str:
    probe = tmp_path / "target-schema-probe.db"
    shutil.copyfile(database, probe)
    with closing(sqlite3.connect(probe)) as conn:
        step.apply_in_transaction(conn)
        result = schema_snapshot_sha256(conn)
        conn.rollback()
        return result


def _migration_update_plan(database: Path, tmp_path: Path, step: MigrationStep) -> dict[str, object]:
    source = inspect_schema_metadata(database)
    return {
        "mode": "versioned-forward-migration",
        "source_schema_version": 1,
        "target_schema_version": 2,
        "source_schema_sha256": source["schema_sha256"],
        "target_schema_sha256": _target_schema_sha256(database, tmp_path, step),
        "migration_registry_sha256": migration_registry_sha256((step,)),
        "migration_ids": [step.migration_id],
    }


def test_database_update_plan_binds_release_evidence_registry_and_current_database(tmp_path: Path):
    roots = _roots(tmp_path)
    database = _create_update_database(roots.DATA_ROOT / "enterprise.db")
    step = _update_migration_step()
    target_schema = _target_schema_sha256(database, tmp_path, step)
    registry_sha = migration_registry_sha256((step,))
    source_schema = inspect_schema_metadata(database)["schema_sha256"]
    for root, version, schema in (
        (roots.RELEASE_ROOT / "release-A", 1, source_schema),
        (roots.RELEASE_ROOT / "release-B", 2, target_schema),
    ):
        evidence = root / "release-evidence" / "database-schema.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text(json.dumps({
            "schema_version": version,
            "schema_objects_sha256": schema,
            "migration_registry_sha256": registry_sha,
            "versioned_migration_ids": [step.migration_id],
        }), encoding="utf-8")
    plan = _database_update_plan(
        source_root=roots.RELEASE_ROOT / "release-A",
        target_root=roots.RELEASE_ROOT / "release-B",
        source_manifest=_Manifest("release-A", "1" * 64, True),
        target_manifest=_Manifest("release-B", "2" * 64, True),
        database_path=database,
        registry=(step,),
        operation_id="a" * 32,
    )
    assert plan == {
        "mode": "versioned-forward-migration",
        "operation_id": "a" * 32,
        "source_schema_version": 1,
        "target_schema_version": 2,
        "source_schema_sha256": source_schema,
        "target_schema_sha256": target_schema,
        "migration_registry_sha256": registry_sha,
        "migration_ids": [step.migration_id],
    }


def test_same_schema_update_can_only_stage_an_append_only_future_registry(tmp_path: Path):
    roots = _roots(tmp_path)
    database = _create_update_database(roots.DATA_ROOT / "enterprise.db")
    source_schema = inspect_schema_metadata(database)["schema_sha256"]
    step = _update_migration_step()
    source_registry_sha = migration_registry_sha256(())
    target_registry_sha = migration_registry_sha256((step,))
    for root, registry_sha, ids in (
        (roots.RELEASE_ROOT / "release-A", source_registry_sha, []),
        (roots.RELEASE_ROOT / "release-B", target_registry_sha, [step.migration_id]),
    ):
        evidence = root / "release-evidence" / "database-schema.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text(json.dumps({
            "schema_version": 1,
            "schema_objects_sha256": source_schema,
            "migration_registry_sha256": registry_sha,
            "versioned_migration_ids": ids,
        }), encoding="utf-8")
    plan = _database_update_plan(
        source_root=roots.RELEASE_ROOT / "release-A",
        target_root=roots.RELEASE_ROOT / "release-B",
        source_manifest=_Manifest("release-A", "1" * 64, registry_stage=True),
        target_manifest=_Manifest("release-B", "2" * 64, registry_stage=True),
        database_path=database,
        registry=(),
        operation_id="a" * 32,
    )
    assert plan == {
        "mode": "same-schema-no-migration",
        "registry_staged": True,
        "target_migration_registry_sha256": target_registry_sha,
        "target_versioned_migration_ids": [step.migration_id],
    }


def _legacy_migration_case(tmp_path: Path) -> tuple[Path, MigrationStep, dict[str, object], list[dict[str, str]]]:
    roots = _roots(tmp_path)
    database = roots.DATA_ROOT / "enterprise.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO records (id, value) VALUES (1, 'preserved')")
        conn.commit()
        source_objects = schema_objects(conn)
        source_sha = schema_snapshot_sha256(conn)
    step = _update_migration_step()
    enrolled_sha = preview_legacy_schema_enrollment(database, expected_legacy_schema_sha256=source_sha)
    probe = tmp_path / "target-legacy-probe.db"
    shutil.copyfile(database, probe)
    with closing(sqlite3.connect(probe)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        initialize_schema_metadata_in_transaction(conn)
        step.apply_in_transaction(conn)
        target_objects = schema_objects(conn)
        target_sha = schema_snapshot_sha256(conn)
        conn.rollback()
    source_evidence = {
        "schema_id": "enterprise-database-contract-v1", "migration_ids": ["base"],
        "objects": source_objects,
    }
    target_evidence = {
        "schema_id": "enterprise-database-contract-v1", "migration_ids": ["base"],
        "objects": target_objects,
        "schema_version": 2,
        "schema_objects_sha256": target_sha,
        "migration_registry_sha256": migration_registry_sha256((step,)),
        "versioned_migration_ids": [step.migration_id],
        "legacy_source_schema_sha256": source_sha,
        "legacy_enrolled_schema_sha256": enrolled_sha,
    }
    for release_id, evidence in (("release-A", source_evidence), ("release-B", target_evidence)):
        path = roots.RELEASE_ROOT / release_id / "release-evidence" / "database-schema.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence), encoding="utf-8")
    plan = _database_update_plan(
        source_root=roots.RELEASE_ROOT / "release-A",
        target_root=roots.RELEASE_ROOT / "release-B",
        source_manifest=_Manifest("release-A", "1" * 64, migration_target=True),
        target_manifest=_Manifest("release-B", "2" * 64, migration_target=True),
        database_path=database, registry=(step,), operation_id="a" * 32,
    )
    return database, step, plan, source_objects


def test_legacy_migration_plan_requires_exact_source_and_enrolled_schema(tmp_path: Path):
    database, step, plan, source_objects = _legacy_migration_case(tmp_path)
    assert plan["source_schema_format"] == "legacy-exact"
    assert plan["source_schema_version"] == 0
    assert plan["migration_ids"] == [step.migration_id]
    assert inspect_schema_metadata(database)["current_state"] == "DATA_SCHEMA_METADATA_MISSING"
    target = tmp_path / "install" / "releases" / "release-B" / "release-evidence" / "database-schema.json"
    evidence = json.loads(target.read_text(encoding="utf-8"))
    evidence["legacy_enrolled_schema_sha256"] = "f" * 64
    target.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_DATABASE_SOURCE_IDENTITY_MISMATCH"):
        _database_update_plan(
            source_root=target.parents[2] / "release-A", target_root=target.parents[1],
            source_manifest=_Manifest("release-A", "1" * 64, migration_target=True),
            target_manifest=_Manifest("release-B", "2" * 64, migration_target=True),
            database_path=database, registry=(step,), operation_id="a" * 32,
        )
    with closing(sqlite3.connect(database)) as conn:
        assert schema_objects(conn) == source_objects


def test_legacy_update_backs_up_before_migration_and_keeps_rows(tmp_path: Path, monkeypatch):
    database, step, plan, _ = _legacy_migration_case(tmp_path)
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path, monkeypatch, database_update=plan, migration_target=True,
    )
    assert execute_update_job(roots, job_id, launcher=launcher, database_path=database, migration_registry=(step,)) == 0
    assert pointer.release.release_id == "release-B"
    assert inspect_schema_metadata(database)["schema_version"] == 2
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT id, value, label FROM records").fetchall() == [(1, "preserved", "migrated")]
    result = store.read_database_result(job_id)
    assert result["source_schema_version"] == 0
    from enterprise.migrations.versioned import verify_database_backup
    backup = verify_database_backup(roots.BACKUP_ROOT / result["backup_manifest_relative_path"])
    assert backup.source_schema_version == 0
    assert store.read_status(job_id)["state"] == "SUCCEEDED"
    assert calls == [("release-B", "start"), ("release-B", "health")]


@pytest.mark.parametrize("failure_kind", ["start", "health"])
def test_legacy_target_failure_restores_database_and_pointer(tmp_path: Path, monkeypatch, failure_kind: str):
    database, step, plan, _ = _legacy_migration_case(tmp_path)
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path, monkeypatch,
        target_start_exit=2 if failure_kind == "start" else 0,
        target_health_exit=2 if failure_kind == "health" else 0,
        database_update=plan, migration_target=True,
    )
    assert execute_update_job(roots, job_id, launcher=launcher, database_path=database, migration_registry=(step,)) == 2
    assert pointer.release.release_id == "release-A"
    assert inspect_schema_metadata(database)["current_state"] == "DATA_SCHEMA_METADATA_MISSING"
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT id, value FROM records").fetchall() == [(1, "preserved")]
        assert [row[1] for row in conn.execute("PRAGMA table_info(records)")] == ["id", "value"]
    assert store.read_status(job_id)["state"] == "ROLLED_BACK"
    assert calls[-2:] == [("release-A", "start"), ("release-A", "health")]


def test_legacy_migration_validation_failure_keeps_old_database(tmp_path: Path, monkeypatch):
    database, step, plan, _ = _legacy_migration_case(tmp_path)
    rejecting_step = _update_migration_step(validation_result=False)
    assert rejecting_step.checksum_sha256 == step.checksum_sha256
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path, monkeypatch, database_update=plan, migration_target=True,
    )
    assert execute_update_job(
        roots, job_id, launcher=launcher, database_path=database,
        migration_registry=(rejecting_step,),
    ) == 2
    assert pointer.release.release_id == "release-A"
    assert inspect_schema_metadata(database)["current_state"] == "DATA_SCHEMA_METADATA_MISSING"
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT value FROM records WHERE id=1").fetchone() == ("preserved",)
    assert calls == [("release-A", "start"), ("release-A", "health")]
    assert store.read_status(job_id)["result_code"] == "DATA_MIGRATION_VALIDATION_FAILED"


def test_legacy_backup_failure_never_switches_pointer(tmp_path: Path, monkeypatch):
    database, step, plan, _ = _legacy_migration_case(tmp_path)
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path, monkeypatch, database_update=plan, migration_target=True,
    )

    def fail_backup(*_args, **_kwargs):
        raise DataMigrationError("DATA_BACKUP_FAILED")

    monkeypatch.setattr("enterprise.migrations.versioned.create_database_backup", fail_backup)
    assert execute_update_job(roots, job_id, launcher=launcher, database_path=database, migration_registry=(step,)) == 2
    assert pointer.release.release_id == "release-A"
    assert inspect_schema_metadata(database)["current_state"] == "DATA_SCHEMA_METADATA_MISSING"
    assert calls == [("release-A", "start"), ("release-A", "health")]
    assert store.read_status(job_id)["result_code"] == "DATA_BACKUP_FAILED"


def test_legacy_restore_failure_requires_manual_recovery(tmp_path: Path, monkeypatch):
    database, step, plan, _ = _legacy_migration_case(tmp_path)
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path, monkeypatch, target_start_exit=2, database_update=plan, migration_target=True,
    )

    def fail_restore(_database, _result, *, validation_result):
        raise DataMigrationError("DATA_RESTORE_FAILED", database_may_have_changed=True)

    monkeypatch.setattr("enterprise.ops.update.mvp.finalize_release_database_validation", fail_restore)
    assert execute_update_job(roots, job_id, launcher=launcher, database_path=database, migration_registry=(step,)) == 2
    assert inspect_schema_metadata(database)["schema_version"] == 2
    assert pointer.release.release_id == "release-B"
    assert not any(item[0] == "release-A" for item in calls)
    assert store.read_status(job_id)["state"] == "RECOVERY_REQUIRED"


def test_legacy_post_commit_uncertainty_never_starts_old_release(tmp_path: Path, monkeypatch):
    from enterprise.migrations.versioned import apply_legacy_versioned_migrations

    database, step, plan, _ = _legacy_migration_case(tmp_path)
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path, monkeypatch, database_update=plan, migration_target=True,
    )

    def fail_after_commit(*args, **kwargs):
        apply_legacy_versioned_migrations(*args, **kwargs)
        raise DataMigrationError("DATA_MIGRATION_POST_COMMIT_VALIDATION_FAILED", database_may_have_changed=True)

    monkeypatch.setattr("enterprise.ops.update.mvp.apply_legacy_versioned_migrations", fail_after_commit)
    assert execute_update_job(roots, job_id, launcher=launcher, database_path=database, migration_registry=(step,)) == 2
    assert inspect_schema_metadata(database)["schema_version"] == 2
    assert pointer.release.release_id == "release-A"
    assert calls == []
    assert store.read_status(job_id)["state"] == "RECOVERY_REQUIRED"


def test_customer_095_legacy_bridge_keeps_database_unchanged(tmp_path: Path):
    roots = _roots(tmp_path)
    database = roots.DATA_ROOT / "enterprise.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO records (value) VALUES ('customer-data')")
        conn.commit()
        objects = schema_objects(conn)
    before = database.read_bytes()
    evidence = {
        "schema_id": "enterprise-database-contract-v1",
        "migration_ids": ["base"],
        "objects": objects,
    }
    for release_id in ("release-A", "release-B"):
        path = roots.RELEASE_ROOT / release_id / "release-evidence" / "database-schema.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(evidence), encoding="utf-8")
    plan = _database_update_plan(
        source_root=roots.RELEASE_ROOT / "release-A",
        target_root=roots.RELEASE_ROOT / "release-B",
        source_manifest=_Manifest("release-A", "1" * 64, migration_ids=tuple(evidence["migration_ids"])),
        target_manifest=_Manifest("release-B", "2" * 64, migration_ids=tuple(evidence["migration_ids"])),
        database_path=database,
        registry=(),
        operation_id="a" * 32,
    )
    assert plan == {"mode": "same-schema-no-migration", "source_schema_format": "legacy-exact"}
    assert database.read_bytes() == before
    assert inspect_schema_metadata(database)["current_state"] == "DATA_SCHEMA_METADATA_MISSING"

    # The bridge must not pretend that a legacy database is already eligible
    # for a schema-changing release.
    target_path = roots.RELEASE_ROOT / "release-B" / "release-evidence" / "database-schema.json"
    target_path.write_text(json.dumps({
        "schema_version": 2,
        "schema_objects_sha256": "8" * 64,
        "migration_registry_sha256": "7" * 64,
        "versioned_migration_ids": [],
    }), encoding="utf-8")
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_DATABASE_CONTRACT_UNSUPPORTED"):
        _database_update_plan(
            source_root=roots.RELEASE_ROOT / "release-A",
            target_root=roots.RELEASE_ROOT / "release-B",
            source_manifest=_Manifest("release-A", "1" * 64, migration_target=True),
            target_manifest=_Manifest("release-B", "2" * 64, migration_target=True),
            database_path=database,
            registry=(),
            operation_id="a" * 32,
        )
    assert database.read_bytes() == before

    # A target that quietly adds a table is not a compatible bridge.
    target_path.write_text(json.dumps({**evidence, "objects": []}), encoding="utf-8")
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_DATABASE_CONTRACT_UNSUPPORTED"):
        _database_update_plan(
            source_root=roots.RELEASE_ROOT / "release-A",
            target_root=roots.RELEASE_ROOT / "release-B",
            source_manifest=_Manifest("release-A", "1" * 64),
            target_manifest=_Manifest("release-B", "2" * 64),
            database_path=database,
            registry=(),
            operation_id="a" * 32,
        )

    target_path.write_text(json.dumps(evidence), encoding="utf-8")
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE unexpected_customer_table (id INTEGER PRIMARY KEY)")
        conn.commit()
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_DATABASE_SOURCE_IDENTITY_MISMATCH"):
        _database_update_plan(
            source_root=roots.RELEASE_ROOT / "release-A",
            target_root=roots.RELEASE_ROOT / "release-B",
            source_manifest=_Manifest("release-A", "1" * 64),
            target_manifest=_Manifest("release-B", "2" * 64),
            database_path=database,
            registry=(),
            operation_id="a" * 32,
        )


def test_customer_095_bridge_matches_real_initialized_schema(tmp_path: Path, monkeypatch):
    from enterprise import db
    from enterprise.paths import derive_development_path_roots

    repository = Path(__file__).resolve().parents[2]
    evidence = json.loads(_database_snapshot(repository, tmp_path / "snapshot.tmp"))
    roots = derive_development_path_roots(tmp_path / "customer-install")
    monkeypatch.setattr(db, "PATH_ROOTS", roots)
    monkeypatch.setattr(db, "DB_PATH", "enterprise.db")
    monkeypatch.setattr(db, "ADMIN_USERNAME", "fixture-admin")
    monkeypatch.setattr(db, "ADMIN_PASSWORD", "fixture-only-password")
    db.init_db()
    database = roots.DATA_ROOT / "enterprise.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("INSERT INTO users (id, username, password_hash, display_name, is_admin, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     ("customer-1", "customer", "fixture-hash", "Customer", 1, 1))
        conn.commit()
        assert schema_objects(conn) == evidence["objects"]
    before = database.read_bytes()
    source = roots.RELEASE_ROOT / "release-A" / "release-evidence" / "database-schema.json"
    target = roots.RELEASE_ROOT / "release-B" / "release-evidence" / "database-schema.json"
    for path in (source, target):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence), encoding="utf-8")
    result = _database_update_plan(
        source_root=source.parents[1], target_root=target.parents[1],
        source_manifest=_Manifest("release-A", "1" * 64, migration_ids=tuple(evidence["migration_ids"])),
        target_manifest=_Manifest("release-B", "2" * 64, migration_ids=tuple(evidence["migration_ids"])),
        database_path=database, registry=(), operation_id="a" * 32,
    )
    assert result == {"mode": "same-schema-no-migration", "source_schema_format": "legacy-exact"}
    assert database.read_bytes() == before


def test_versioned_update_migrates_before_switch_and_persists_bounded_result(tmp_path: Path, monkeypatch):
    roots = _roots(tmp_path)
    database = _create_update_database(roots.DATA_ROOT / "enterprise.db")
    step = _update_migration_step()
    database_update = _migration_update_plan(database, tmp_path, step)
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path,
        monkeypatch,
        database_update=database_update,
        migration_target=True,
    )
    assert execute_update_job(
        roots,
        job_id,
        launcher=launcher,
        database_path=database,
        migration_registry=(step,),
    ) == 0
    assert pointer.release.release_id == "release-B"
    assert calls == [("release-B", "start"), ("release-B", "health")]
    assert inspect_schema_metadata(database)["schema_version"] == 2
    result = store.read_database_result(job_id)
    assert result["migration_ids"] == [step.migration_id]
    assert result["backup_manifest_relative_path"].startswith("system-update/")
    assert str(tmp_path) not in json.dumps(result)
    assert store.read_status(job_id)["state"] == "SUCCEEDED"


def test_execution_rereads_database_evidence_and_rejects_plan_drift(tmp_path: Path, monkeypatch):
    roots = _roots(tmp_path)
    database = _create_update_database(roots.DATA_ROOT / "enterprise.db")
    step = _update_migration_step()
    database_update = _migration_update_plan(database, tmp_path, step)
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path,
        monkeypatch,
        database_update=database_update,
        migration_target=True,
    )
    monkeypatch.setattr(
        "enterprise.ops.update.mvp._database_update_plan",
        lambda **_kwargs: {**store.read_plan(job_id)["database_update"], "target_schema_sha256": "f" * 64},
    )
    assert execute_update_job(
        roots,
        job_id,
        launcher=launcher,
        database_path=database,
        migration_registry=(step,),
    ) == 2
    assert pointer.release.release_id == "release-A"
    assert inspect_schema_metadata(database)["schema_version"] == 1
    assert calls == [("release-A", "start"), ("release-A", "health")]
    assert store.read_status(job_id)["result_code"] == "SYSTEM_UPDATE_DATABASE_MIGRATION_PLAN_INVALID"


def test_migration_validation_failure_keeps_source_database_and_restarts_source(tmp_path: Path, monkeypatch):
    roots = _roots(tmp_path)
    database = _create_update_database(roots.DATA_ROOT / "enterprise.db")
    step = _update_migration_step(validation_result=False)
    database_update = _migration_update_plan(database, tmp_path, step)
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path,
        monkeypatch,
        database_update=database_update,
        migration_target=True,
    )
    assert execute_update_job(
        roots,
        job_id,
        launcher=launcher,
        database_path=database,
        migration_registry=(step,),
    ) == 2
    assert pointer.release.release_id == "release-A"
    assert inspect_schema_metadata(database)["schema_version"] == 1
    assert calls == [("release-A", "start"), ("release-A", "health")]
    assert store.read_status(job_id)["result_code"] == "DATA_MIGRATION_VALIDATION_FAILED"


def test_post_commit_migration_error_never_restarts_source_on_target_schema(tmp_path: Path, monkeypatch):
    from enterprise.migrations.versioned import apply_versioned_migrations

    roots = _roots(tmp_path)
    database = _create_update_database(roots.DATA_ROOT / "enterprise.db")
    step = _update_migration_step()
    database_update = _migration_update_plan(database, tmp_path, step)
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path,
        monkeypatch,
        database_update=database_update,
        migration_target=True,
    )

    def fail_after_commit(*args, **kwargs):
        apply_versioned_migrations(*args, **kwargs)
        raise DataMigrationError("DATA_MIGRATION_POST_COMMIT_VALIDATION_FAILED")

    monkeypatch.setattr("enterprise.ops.update.mvp.apply_versioned_migrations", fail_after_commit)
    assert execute_update_job(
        roots,
        job_id,
        launcher=launcher,
        database_path=database,
        migration_registry=(step,),
    ) == 2
    assert inspect_schema_metadata(database)["schema_version"] == 2
    assert pointer.release.release_id == "release-A"
    assert calls == []
    assert store.read_status(job_id)["state"] == "RECOVERY_REQUIRED"


@pytest.mark.parametrize("failure_kind", ["start", "health"])
def test_target_failure_restores_database_before_restarting_source(tmp_path: Path, monkeypatch, failure_kind: str):
    roots = _roots(tmp_path)
    database = _create_update_database(roots.DATA_ROOT / "enterprise.db")
    step = _update_migration_step()
    database_update = _migration_update_plan(database, tmp_path, step)
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path,
        monkeypatch,
        target_start_exit=2 if failure_kind == "start" else 0,
        target_health_exit=2 if failure_kind == "health" else 0,
        database_update=database_update,
        migration_target=True,
    )
    assert execute_update_job(
        roots,
        job_id,
        launcher=launcher,
        database_path=database,
        migration_registry=(step,),
    ) == 2
    observed_status = store.read_status(job_id)
    assert pointer.release.release_id == "release-A", (observed_status, calls)
    assert inspect_schema_metadata(database)["schema_version"] == 1
    status = observed_status
    assert status["state"] == "ROLLED_BACK"
    assert status["database_restored"] is True
    assert calls[-2:] == [("release-A", "start"), ("release-A", "health")]


def test_restore_failure_is_durable_recovery_required_and_not_retried(tmp_path: Path, monkeypatch):
    roots = _roots(tmp_path)
    database = _create_update_database(roots.DATA_ROOT / "enterprise.db")
    step = _update_migration_step()
    database_update = _migration_update_plan(database, tmp_path, step)
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path,
        monkeypatch,
        target_start_exit=2,
        database_update=database_update,
        migration_target=True,
    )
    original = __import__(
        "enterprise.migrations.versioned",
        fromlist=["finalize_release_database_validation"],
    ).finalize_release_database_validation

    def fail_restore(path, result, *, validation_result):
        if validation_result != "healthy":
            raise DataMigrationError("DATA_RESTORE_FAILED", database_may_have_changed=True, reread_required=True)
        return original(path, result, validation_result=validation_result)

    monkeypatch.setattr("enterprise.ops.update.mvp.finalize_release_database_validation", fail_restore)
    assert execute_update_job(
        roots,
        job_id,
        launcher=launcher,
        database_path=database,
        migration_registry=(step,),
    ) == 2
    status = store.read_status(job_id)
    assert status["state"] == "RECOVERY_REQUIRED"
    assert status["recovery_required"] is True
    assert status["result_code"] == "DATA_RESTORE_FAILED"
    assert pointer.release.release_id == "release-B"
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_JOB_NOT_EXECUTABLE"):
        execute_update_job(
            roots,
            job_id,
            launcher=launcher,
            database_path=database,
            migration_registry=(step,),
        )


def test_pre_switch_verification_failure_is_failed_without_false_rollback(tmp_path: Path, monkeypatch):
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "enterprise.ops.update.mvp.verify_materialized_release",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            UpdateMvpError("SYSTEM_UPDATE_TARGET_VERIFY_FAILED")
        ),
    )
    assert execute_update_job(roots, job_id, launcher=launcher) == 2
    assert pointer.release.release_id == "release-A"
    assert calls == []
    status = store.read_status(job_id)
    assert status["state"] == "FAILED"
    assert status["result_code"] == "SYSTEM_UPDATE_TARGET_VERIFY_FAILED"


def test_diagnostics_are_bounded_redacted_and_zip_safe(tmp_path: Path):
    roots = _roots(tmp_path)
    runtime = roots.LOG_ROOT / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "gateway.stderr.log").write_text(
        "Authorization: Bearer secret-token\npassword=hunter2\nnormal line\n",
        encoding="utf-8",
    )
    payload = recent_diagnostics(roots, limit=10, secret_values=("secret-token", "hunter2"))
    rendered = json.dumps(payload)
    assert "secret-token" not in rendered and "hunter2" not in rendered
    assert "[REDACTED]" in rendered
    archive = diagnostics_zip(payload)
    assert archive.startswith(b"PK") and len(archive) < 128 * 1024


def test_update_center_ui_never_persists_password_and_hides_dangerous_actions():
    html = (Path(__file__).resolve().parents[2] / "enterprise-static" / "admin.html").read_text(encoding="utf-8")
    assert 'type="password" id="updateConfirmPassword"' in html
    assert "update-dangerous" in html and "SYSTEM_UPDATE" not in html
    assert "document.getElementById('updateConfirmPassword').value = ''" in html
    assert "localStorage" not in html[html.index("async function executeSystemUpdate"):html.index("async function refreshUpdateJob")]


def test_legacy_in_place_update_endpoint_is_unconditionally_blocked():
    source = (Path(__file__).resolve().parents[1] / "interceptors.py").read_text(encoding="utf-8")
    block = source[source.index("update_paths = {"):source.index('if path == "api/config/token"')]
    assert "return _deny_forbidden" in block
    assert "can_use_feature" not in block


class _Request:
    def __init__(self, user: dict, body: dict | None = None):
        self.state = SimpleNamespace(user=user)
        self._body = body or {}
        self.query_params = {}

    async def json(self):
        return self._body


def test_update_api_denies_unprivileged_roles_before_provider_or_filesystem(monkeypatch):
    from enterprise import update_api

    users = {
        "admin": {
            "id": "admin", "role": "admin", "is_admin": True,
            "is_active": True, "auth_version": 1,
        },
        "user": {
            "id": "user", "role": "user", "is_admin": False,
            "is_active": True, "auth_version": 1,
        },
    }
    monkeypatch.setattr(update_api, "ENTERPRISE_UPDATE_ENABLED", True)
    monkeypatch.setattr(update_api.edb, "get_user_by_id", lambda uid: users[uid])
    monkeypatch.setattr(update_api.edb, "can_use_feature", lambda *_args: True)
    monkeypatch.setattr(
        update_api,
        "_provider",
        lambda: (_ for _ in ()).throw(AssertionError("provider must not be reached")),
    )
    with pytest.raises(HTTPException) as admin_denial:
        asyncio.run(
            update_api.check_update(
                _Request({"user_id": "admin", "role": "admin", "is_admin": True, "auth_version": 1})
            )
        )
    assert admin_denial.value.status_code == 403
    with pytest.raises(HTTPException) as user_denial:
        asyncio.run(
            update_api.update_access(
                _Request({"user_id": "user", "role": "user", "is_admin": False, "auth_version": 1})
            )
        )
    assert user_denial.value.status_code == 403


@pytest.mark.parametrize("candidate_version,available", [
    ("2026.09.4", False),
    ("2026.09.5", True),
])
def test_update_check_only_offers_a_newer_version(monkeypatch, candidate_version, available):
    from enterprise import update_api

    current = {
        "id": "actor-1", "role": "super_admin", "is_active": True,
        "auth_version": 1,
    }
    release = SimpleNamespace(
        provider_release_id="candidate-1", tag_name=candidate_version,
        version=candidate_version, published_at="2026-09-24T00:00:00Z",
        release_notes="test",
    )
    monkeypatch.setattr(update_api, "ENTERPRISE_UPDATE_ENABLED", True)
    monkeypatch.setattr(update_api.edb, "get_user_by_id", lambda _uid: current)
    monkeypatch.setattr(update_api.edb, "can_use_feature", lambda *_args: True)
    monkeypatch.setattr(update_api, "_provider", lambda: SimpleNamespace(list_release_v2_candidates=lambda: [release]))
    monkeypatch.setattr(update_api, "read_current_release_result_from_state_root", lambda _root: SimpleNamespace(release=SimpleNamespace(release_id="ice-2026.09.4")))
    monkeypatch.setattr(update_api, "read_release_manifest_v2", lambda _path: SimpleNamespace(section=lambda _key: {"release_version": "2026.09.4"}))

    result = asyncio.run(update_api.check_update(_Request({"user_id": "actor-1", "auth_version": 1})))
    assert result["update_available"] is available
    assert result["latest"]["version"] == candidate_version


def test_execute_reconfirms_current_password_without_persisting_it(tmp_path: Path, monkeypatch):
    from enterprise import update_api

    roots = _roots(tmp_path)
    store = UpdateJobStore(roots)
    job_id, root = store.create("actor-1")
    store.write_plan(job_id, {
        "job_id": job_id, "actor_user_id": "actor-1", "source_release_id": "release-A",
        "source_pointer_sha256": "a" * 64, "source_manifest_sha256": "b" * 64,
        "target_release_id": "release-B", "target_manifest_sha256": "c" * 64,
        "target_inventory_sha256": "d" * 64, "target_payload_tree_sha256": "e" * 64,
    })
    store.write_status(job_id, "READY", actor_user_id="actor-1", result_code="SYSTEM_UPDATE_READY")
    current_user = {
        "id": "actor-1", "user_id": "actor-1", "username": "admin-a", "role": "super_admin",
        "is_admin": True, "is_active": True, "auth_version": 7, "password_hash": "stored-hash",
    }
    monkeypatch.setattr(update_api, "PATH_ROOTS", roots)
    monkeypatch.setattr(update_api, "ENTERPRISE_UPDATE_ENABLED", True)
    monkeypatch.setattr(update_api.edb, "get_user_by_id", lambda _uid: current_user)
    monkeypatch.setattr(update_api.edb, "can_use_feature", lambda _user, _key: True)
    monkeypatch.setattr(update_api.edb, "verify_password", lambda password, digest: password == "correct-password" and digest == "stored-hash")
    audits = []
    monkeypatch.setattr(update_api.edb, "log_action", lambda *args: audits.append(args))
    monkeypatch.setattr(
        update_api,
        "read_current_release_result_from_state_root",
        lambda _root: SimpleNamespace(raw_sha256="a" * 64, release=SimpleNamespace(release_id="release-A")),
    )
    principal = {"user_id": "actor-1", "role": "super_admin", "is_admin": True, "auth_version": 7}
    tasks = BackgroundTasks()
    result = asyncio.run(update_api.execute_update(job_id, _Request(principal, {"password": "correct-password"}), tasks))
    assert result["state"] == "UPDATING" and len(tasks.tasks) == 1
    persisted = "".join(path.read_text(encoding="utf-8") for path in root.glob("*.json*"))
    assert "correct-password" not in persisted and "stored-hash" not in persisted
    assert all("correct-password" not in repr(item) for item in audits)
    lock = store.acquire_execution_lock(job_id); store.release_execution_lock(lock, job_id)


def test_execute_wrong_password_fails_without_reservation_or_background_task(tmp_path: Path, monkeypatch):
    from enterprise import update_api

    roots = _roots(tmp_path)
    store = UpdateJobStore(roots)
    job_id, _ = store.create("actor-1")
    store.write_plan(job_id, {"job_id": job_id, "actor_user_id": "actor-1"})
    store.write_status(job_id, "READY", actor_user_id="actor-1", result_code="SYSTEM_UPDATE_READY")
    current = {"id": "actor-1", "role": "super_admin", "is_admin": True, "is_active": True, "auth_version": 1, "password_hash": "hash"}
    monkeypatch.setattr(update_api, "PATH_ROOTS", roots)
    monkeypatch.setattr(update_api, "ENTERPRISE_UPDATE_ENABLED", True)
    monkeypatch.setattr(update_api.edb, "get_user_by_id", lambda _uid: current)
    monkeypatch.setattr(update_api.edb, "can_use_feature", lambda _user, _key: True)
    monkeypatch.setattr(update_api.edb, "verify_password", lambda *_args: False)
    tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as failure:
        asyncio.run(update_api.execute_update(
            job_id,
            _Request({"user_id": "actor-1", "role": "super_admin", "is_admin": True, "auth_version": 1}, {"password": "wrong"}),
            tasks,
        ))
    assert failure.value.status_code == 403
    assert not store.lock_path.exists() and not tasks.tasks


def test_runtime_handoff_command_carries_only_a_fixed_job_id(tmp_path: Path):
    from enterprise.runtime.state import RuntimeStateError, RuntimeStateStore

    store = RuntimeStateStore(tmp_path / "runtime")
    request_id = store.submit_command(
        command="update-handoff", supervisor_instance_id="instance", expected_state_generation=1,
        update_job_id="a" * 32,
    )
    commands = store.consume_commands("instance")
    assert len(commands) == 1 and commands[0]["update_job_id"] == "a" * 32
    assert set(commands[0]) == {
        "schema_version", "request_id", "command", "supervisor_instance_id", "issued_at",
        "expected_state_generation", "update_job_id",
    }
    with pytest.raises(RuntimeStateError):
        store.submit_command(
            command="update-handoff", supervisor_instance_id="instance", expected_state_generation=1,
            update_job_id="../worker.exe",
        )


def test_controller_rechecks_ownership_before_writing_update_handoff(monkeypatch):
    from enterprise.runtime.control import RuntimeController

    controller = RuntimeController.__new__(RuntimeController)
    controller.config = SimpleNamespace()
    submitted = []
    controller.store = SimpleNamespace(
        submit_command=lambda **kwargs: submitted.append(kwargs) or "request-id",
        read_ack=lambda *_args, **_kwargs: None,
    )
    healthy = {
        "portable_ownership_valid": True,
        "running_release_mismatch": False,
        "readiness": {"ready": True},
        "runtime_state": {"supervisor_instance_id": "instance", "state_generation": 7},
        "launch_context_identity": "context-a",
    }
    tampered = {
        **healthy,
        "runtime_state": {"supervisor_instance_id": "foreign", "state_generation": 7},
    }
    snapshots = iter((healthy, tampered))
    monkeypatch.setattr("enterprise.runtime.control.inspect_runtime", lambda _config: next(snapshots))
    result = controller.send_update_handoff("a" * 32, wait_seconds=0)
    assert result["result"] == "ownership_unavailable"
    assert submitted == []


def test_supervisor_handoff_uses_only_fixed_source_python_and_worker(tmp_path: Path, monkeypatch):
    from enterprise.runtime.ownership import ProcessIdentity
    from enterprise.runtime.supervisor import RuntimeSupervisor

    app_root = tmp_path / "release-A"
    python = app_root / "python" / "python.exe"
    worker = app_root / "enterprise" / "ops" / "update" / "handoff.py"
    python.parent.mkdir(parents=True)
    worker.parent.mkdir(parents=True)
    python.write_bytes(b"fixture")
    worker.write_text("# fixture\n", encoding="utf-8")
    launched = []

    class Process:
        pid = 4242

        @staticmethod
        def poll():
            return None

    def popen(arguments, **kwargs):
        launched.append((arguments, kwargs))
        return Process()

    supervisor = RuntimeSupervisor.__new__(RuntimeSupervisor)
    supervisor.config = SimpleNamespace(
        app_root=app_root,
        python_executable=str(python),
        runtime_mode="portable-release",
    )
    supervisor._update_handoff_request = {"request_id": "request", "update_job_id": "b" * 32}
    supervisor._stopping = False
    acknowledgements = []
    supervisor._command_snapshot = lambda: {"state": "healthy"}
    supervisor._ack = lambda request, **fields: acknowledgements.append((request, fields))
    supervisor._log = lambda *_args, **_kwargs: None
    monkeypatch.setattr("enterprise.runtime.supervisor.subprocess.Popen", popen)
    monkeypatch.setattr(
        "enterprise.runtime.supervisor.process_identity",
        lambda pid: ProcessIdentity(pid, 1, str(python)),
    )
    RuntimeSupervisor._perform_update_handoff(supervisor)
    assert launched[0][0] == [str(python), "-I", "-B", str(worker), "--job-id", "b" * 32]
    assert launched[0][1]["stdin"] is not None
    assert launched[0][1]["stdout"] is not None
    assert launched[0][1]["stderr"] is not None
    assert launched[0][1]["shell"] is False
    assert launched[0][1]["cwd"] == str(app_root)
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT"):
        assert name not in launched[0][1]["env"]
    assert acknowledgements[0][1]["result"] == "update_handoff_started"
    assert supervisor._stopping is True
