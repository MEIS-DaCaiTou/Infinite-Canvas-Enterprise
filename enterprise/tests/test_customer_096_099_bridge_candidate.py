"""Opt-in exact installed-copy drills for both supported 09.9 source shapes.

This uses the official source Release's bundled Python and the candidate's
materialized code, but stubs the shared Supervisor switch.  It does not touch
the customer's install or claim independent-device validation.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from enterprise.migrations.versioned import inspect_schema_metadata, schema_objects
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, prepare_install_state_directories
from enterprise.release.current_release import CurrentRelease, SCHEMA_VERSION, atomic_write_current_release
from enterprise.release.release_manifest_v2 import (
    materialize_release_fixture,
    read_release_manifest_v2,
    verify_materialized_release,
)
from enterprise.tests.test_customer_095_bridge_candidate import _assert_target_serves_http


CASES = (
    ("ice-2026.09.8-87277c0e7f68", "ICE_098_RELEASE_ROOT", False),
    ("ice-2026.09.6-8f65c5cd328f", "ICE_096_RELEASE_ROOT", True),
)


@pytest.mark.parametrize("fail_target_start", [False, True])
@pytest.mark.parametrize("source_id,source_env,security_variant", CASES, ids=["098-18-objects", "096-28-objects"])
def test_installed_copy_migration_preservation_and_rollback(
    tmp_path: Path, source_id: str, source_env: str, security_variant: bool, fail_target_start: bool,
):
    source_text = os.environ.get(source_env)
    candidate_text = os.environ.get("ICE_099_CANDIDATE_ROOT")
    if not source_text or not candidate_text:
        pytest.skip("Set exact source Release and 09.9 candidate roots for this opt-in drill")
    source = Path(source_text).resolve()
    candidate = Path(candidate_text).resolve()
    source_manifest = read_release_manifest_v2(source / "release-manifest.json")
    assert source_manifest.release_id == source_id
    verify_materialized_release(source, inventory_path=source / "release-payload-inventory.json")
    target_manifest_path = candidate / "ops-release-manifest-v2.json"
    target_inventory_path = candidate / "release-payload-inventory.json"
    target_manifest = read_release_manifest_v2(target_manifest_path)
    assert target_manifest.section("identity")["release_version"] == "2026.09.9"
    assert target_manifest.section("database_contract")["migration_compatibility"] == "versioned-forward-migration"
    archives = list(candidate.glob("Infinite-Canvas-Enterprise-*-win-x64.zip"))
    assert len(archives) == 1

    install = tmp_path / "install"
    local = tmp_path / "local"
    roots = derive_portable_path_roots(PortableRootInputs(install, local), source_id)
    prepare_install_state_directories(roots)
    source_install = roots.RELEASE_ROOT / source_id
    shutil.copytree(source, source_install)
    atomic_write_current_release(
        roots,
        CurrentRelease(SCHEMA_VERSION, source_id, f"releases/{source_id}", source_manifest.raw_sha256,
                       "2026-09-29T00:00:00Z", None),
        expected_manifest_sha256=source_manifest.raw_sha256,
    )
    roots.CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    roots.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    (roots.CONFIG_ROOT / "enterprise.env").write_text(
        "ENTERPRISE_ENV=development\nJWT_SECRET=" + "a" * 64 + "\n", encoding="utf-8",
    )
    asset = roots.UPLOAD_ROOT / "customer-asset.bin"
    asset.write_bytes(b"preserved-media-fixture")
    bootstrap = r'''
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.migrations.sec_1b2_activation import ensure_bootstrap_lifecycle_schema_in_transaction
from enterprise.security_audit import ensure_security_audit_schema_in_transaction
import enterprise.db as db
source, install, local = map(Path, sys.argv[1:4])
db.PATH_ROOTS = derive_portable_path_roots(PortableRootInputs(install, local), source.name)
db.DB_PATH = 'enterprise.db'; db.ADMIN_USERNAME = 'fixture-admin'; db.ADMIN_PASSWORD = 'fixture-only-not-a-secret'
db.init_db()
with sqlite3.connect(db.PATH_ROOTS.DATA_ROOT / 'enterprise.db') as conn:
    conn.execute("INSERT INTO users (id,username,password_hash,display_name,is_admin,role,created_at) VALUES ('u','fixture','hash','Fixture',1,'admin',1)")
    conn.execute("INSERT INTO user_canvas_map (user_id,canvas_id,created_at) VALUES ('u','canvas-1',1)")
    if sys.argv[4] == '1':
        ensure_security_audit_schema_in_transaction(conn)
        ensure_bootstrap_lifecycle_schema_in_transaction(conn)
        conn.execute("INSERT INTO security_governance_bootstrap VALUES (1,1000,'u','u','op','local',1000)")
        conn.execute("INSERT INTO security_audit_events (event_id,operation_id,action,risk_level,result,actor_type,context_json,created_at) VALUES ('event','op','security.super_admin.bootstrap','L3','success','local_operator','{}',1000)")
    conn.commit()
'''
    subprocess.run(
        [str(source_install / "python" / "python.exe"), "-I", "-B", "-c", bootstrap,
         str(source_install), str(install), str(local), "1" if security_variant else "0"],
        check=True, capture_output=True, text=True, timeout=120,
    )
    database = roots.DATA_ROOT / "enterprise.db"
    with closing(sqlite3.connect(database)) as conn:
        assert len(schema_objects(conn)) == (28 if security_variant else 18)

    stage = tmp_path / "verified-target"
    materialize_release_fixture(target_manifest_path, archives[0], target_inventory_path, stage)
    verify_materialized_release(stage, inventory_path=stage / "release-payload-inventory.json")
    # Normal 09.8 uses its installed updater; the exceptional 09.6 variant
    # uses the verified 09.9 code, never the immutable 09.6 updater.
    updater_code_root = stage if security_variant else source_install
    update_script = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.ops.update.mvp import UpdateJobStore, UpdateMvpService, execute_update_job
from enterprise.release.current_release import read_current_release_result_from_state_root
code_root, install, local, manifest, archive, inventory = map(Path, sys.argv[1:7])
variant = sys.argv[7] == '1'; fail = sys.argv[8] == '1'
source_id = sys.argv[9]
roots = derive_portable_path_roots(PortableRootInputs(install, local), source_id)
options = {'allow_096_security_variant': True} if variant else {}
prepared = UpdateMvpService(roots, **options).prepare_from_artifacts(
    actor_user_id='fixture-admin', manifest_path=manifest, archive_path=archive, inventory_path=inventory)
store = UpdateJobStore(roots)
store.reserve_execution(prepared.job_id)
store.write_status(prepared.job_id, 'UPDATING', actor_user_id='fixture-admin',
    result_code='SYSTEM_UPDATE_STARTED', source_release_id=prepared.source_release_id,
    target_release_id=prepared.target_release_id)
def launcher(root, command):
    if fail and root.name == prepared.target_release_id and command == 'start':
        return 2, {'code': 'DRILL_TARGET_START_FAILED'}
    return 0, {'status': 'fixture-only-no-process'}
code = execute_update_job(roots, prepared.job_id, launcher=launcher, **options)
pointer = read_current_release_result_from_state_root(roots.STATE_ROOT)
print(json.dumps({'exit_code': code, 'job_id': prepared.job_id,
    'state': store.read_status(prepared.job_id)['state'], 'current': pointer.release.release_id}))
'''
    completed = subprocess.run(
        [str(source_install / "python" / "python.exe"), "-I", "-B", "-c", update_script,
         str(updater_code_root), str(install), str(local), str(target_manifest_path), str(archives[0]),
         str(target_inventory_path), "1" if security_variant else "0", "1" if fail_target_start else "0", source_id],
        capture_output=True, text=True, timeout=300,
    )
    assert completed.returncode == 0, completed.stderr[-2500:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["state"] == ("ROLLED_BACK" if fail_target_start else "SUCCEEDED")
    assert result["current"] == (source_id if fail_target_start else target_manifest.release_id)
    assert asset.read_bytes() == b"preserved-media-fixture"
    assert (roots.CONFIG_ROOT / "enterprise.env").read_text(encoding="utf-8").startswith("ENTERPRISE_ENV=development")
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert conn.execute("SELECT canvas_id FROM user_canvas_map WHERE user_id='u'").fetchone() == ("canvas-1",)
        if security_variant:
            assert conn.execute("SELECT count(*) FROM security_audit_events").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM security_governance_bootstrap").fetchone()[0] == 1
        assert len(schema_objects(conn)) == ((28 if security_variant else 18) if fail_target_start else 30)
    if fail_target_start:
        assert inspect_schema_metadata(database)["current_state"] == "DATA_SCHEMA_METADATA_MISSING"
        return
    assert inspect_schema_metadata(database)["schema_version"] == 2
    target = roots.RELEASE_ROOT / target_manifest.release_id
    verify_materialized_release(target, inventory_path=target / "release-payload-inventory.json")
    preflight_script = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.runtime.portable import build_portable_preflight
result = build_portable_preflight(Path(sys.argv[1]), local_app_data_resolver=lambda: Path(sys.argv[2]))
print(json.dumps({'release_id': result.release_manifest.release_id, 'result': result.result.result}))
'''
    started = subprocess.run(
        [str(target / "python" / "python.exe"), "-I", "-B", "-c", preflight_script, str(target), str(local)],
        capture_output=True, text=True, timeout=180,
    )
    assert started.returncode == 0, started.stderr[-2500:]
    assert json.loads(started.stdout.strip().splitlines()[-1])["result"] == "pass"
    _assert_target_serves_http(target, install, local)
