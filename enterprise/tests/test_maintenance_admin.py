"""Narrow maintenance regression: no production DB/network/service operations."""
import asyncio
import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_shipped_admin_role_rows_and_gate_controls():
    root = Path(__file__).resolve().parents[2]
    subprocess.run(["node", str(root / "enterprise/tests/test_maintenance_admin.js")], cwd=root, check=True)


@pytest.mark.parametrize("role,deployment,feature,code", [
    ("super_admin", True, True, None),
    ("super_admin", False, True, "SYSTEM_UPDATE_EMERGENCY_SWITCH_DISABLED"),
    ("super_admin", True, False, "SYSTEM_UPDATE_PERMISSION_DENIED"),
    ("super_admin", False, False, "SYSTEM_UPDATE_EMERGENCY_SWITCH_DISABLED"),
    ("admin", True, True, "SYSTEM_UPDATE_SUPER_ADMIN_REQUIRED"),
    ("admin", False, False, "SYSTEM_UPDATE_SUPER_ADMIN_REQUIRED"),
])
def test_access_explanations_preserve_backend_authorization(monkeypatch, role, deployment, feature, code):
    from enterprise import update_api
    current = {"id":"actor", "role":role, "is_active":True, "auth_version":4}
    allowed = feature and role == "super_admin"
    effective = {"allowed":allowed, "global_enabled":feature, "source":"super_admin" if feature else "global_disabled"}
    monkeypatch.setattr(update_api, "ENTERPRISE_UPDATE_ENABLED", deployment)
    monkeypatch.setattr(update_api.edb, "get_user_by_id", lambda _: current)
    monkeypatch.setattr(update_api.edb, "get_effective_feature_value", lambda *_: effective)
    monkeypatch.setattr(update_api.edb, "can_use_feature", lambda *_: allowed)
    request = SimpleNamespace(state=SimpleNamespace(user={"user_id":"actor", "role":"super_admin", "auth_version":4}))
    result = asyncio.run(update_api.update_access(request))
    assert result == {"role":role, "can_operate":code is None,
        "global_update_enabled":deployment and feature, "deployment_update_enabled":deployment,
        "feature_update_enabled":feature, "denial_code":code, "permission_source":effective["source"]}
    if code is None:
        assert update_api._require_update_operator(request) == current
    else:
        with pytest.raises(HTTPException) as denied:
            update_api._require_update_operator(request)
        assert denied.value.status_code == 403
        assert denied.value.detail["code"] == code


def test_access_does_not_accept_stale_sessions(monkeypatch):
    from enterprise import update_api
    monkeypatch.setattr(update_api.edb, "get_effective_feature_value", lambda *_: pytest.fail("stale identity"))
    request = SimpleNamespace(state=SimpleNamespace(user={"user_id":"actor", "auth_version":1}))
    monkeypatch.setattr(update_api.edb, "get_user_by_id", lambda _: {"id":"actor", "role":"super_admin", "is_active":True,"auth_version":2})
    with pytest.raises(HTTPException) as denied:
        asyncio.run(update_api.update_access(request))
    assert denied.value.status_code == 401


def test_versioned_maintenance_build_choice():
    from tools.build_release_manifest_v2 import _parser
    args = _parser().parse_args(["build", "--repo", "X", "--output-root", "Y", "--runtime-root", "Z",
        "--runtime-evidence-root", "E", "--database-contract-mode", "same-versioned-schema-no-migration"])
    assert args.database_contract_mode == "same-versioned-schema-no-migration"


def test_maintenance_preserves_real_099_versioned_schema_and_user_rows(tmp_path, monkeypatch):
    from enterprise import db
    from enterprise.migrations.versioned import DEFAULT_MIGRATIONS, _apply_steps_in_transaction, initialize_schema_metadata_in_transaction
    from enterprise.ops.update.mvp import _database_update_plan
    from enterprise.paths import derive_development_path_roots
    from enterprise.release.release_builder_v2 import _versioned_database_snapshot
    from enterprise.tests.test_update_mvp_1 import _Manifest

    repository = Path(__file__).resolve().parents[2]
    evidence = json.loads(_versioned_database_snapshot(repository, tmp_path / "snapshot.tmp"))
    assert evidence["schema_version"] == 2
    assert len(evidence["objects"]) == 30
    assert evidence["schema_objects_sha256"] == "cd8790a1ef22a97b96c76105b26f14c309ed02396249ab97d36034bb88d25284"
    roots = derive_development_path_roots(tmp_path / "fixture-install")
    monkeypatch.setattr(db, "PATH_ROOTS", roots)
    monkeypatch.setattr(db, "DB_PATH", "enterprise.db")
    monkeypatch.setattr(db, "ADMIN_USERNAME", "fixture-admin")
    monkeypatch.setattr(db, "ADMIN_PASSWORD", "fixture-only-password")
    db.init_db()
    database = roots.DATA_ROOT / "enterprise.db"
    with sqlite3.connect(database) as conn:
        conn.execute("BEGIN IMMEDIATE")
        initialize_schema_metadata_in_transaction(conn)
        _apply_steps_in_transaction(conn, DEFAULT_MIGRATIONS)
        conn.execute("UPDATE users SET role='super_admin', is_admin=1 WHERE username='fixture-admin'")
        conn.commit()
        before = list(conn.iterdump())
    source = roots.RELEASE_ROOT / "release-A" / "release-evidence" / "database-schema.json"
    target = roots.RELEASE_ROOT / "release-B" / "release-evidence" / "database-schema.json"
    for path in (source, target):
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(evidence), encoding="utf-8")
    result = _database_update_plan(source_root=source.parents[1], target_root=target.parents[1],
        source_manifest=_Manifest("release-A", "1"*64, migration_ids=tuple(evidence["migration_ids"])),
        target_manifest=_Manifest("release-B", "2"*64, migration_ids=tuple(evidence["migration_ids"])),
        database_path=database, registry=DEFAULT_MIGRATIONS, operation_id="a"*32)
    assert result["mode"] == "same-schema-no-migration"
    with sqlite3.connect(database) as conn:
        assert list(conn.iterdump()) == before
