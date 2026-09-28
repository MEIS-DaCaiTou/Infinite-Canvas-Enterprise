"""Opt-in exact-source updater drills against built same-schema candidates.

The formal portable Supervisor uses the Windows known-folder API, so this test
does not run that shared control plane or touch the user's existing runtime.
It exercises the actual installed updater, the target's full portable preflight,
and a separate target-Python HTTP process bound only to a random loopback port.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from enterprise.paths import PortableRootInputs, derive_portable_path_roots, prepare_install_state_directories
from enterprise.release.current_release import CurrentRelease, SCHEMA_VERSION, atomic_write_current_release
from enterprise.release.release_manifest_v2 import read_release_manifest_v2, verify_materialized_release


BRIDGE_CASES = (
    ("ice-2026.09.5-7609bb1b7cfa", "2026.09.6", "ICE_095_RELEASE_ROOT", "ICE_096_CANDIDATE_ROOT"),
    ("ice-2026.09.6-8f65c5cd328f", "2026.09.7", "ICE_096_RELEASE_ROOT", "ICE_097_CANDIDATE_ROOT"),
)


def _assert_target_serves_http(target: Path, install: Path, local: Path) -> None:
    """Start the installed target app in its own process, without shared runtime state."""

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, install_path_roots_for_process
target, install, local = map(Path, sys.argv[1:4])
roots = derive_portable_path_roots(PortableRootInputs(install, local), target.name)
install_path_roots_for_process(roots)
import main
import uvicorn
uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[4]), lifespan="on", log_level="error")
'''
    command = [str(target / "python" / "python.exe"), "-I", "-B", "-c", script,
               str(target), str(install), str(local), str(port)]
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as output:
        process = subprocess.Popen(command, cwd=target, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                        assert response.status == 200
                        assert response.read(64)
                        return
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.25)
            output.seek(0)
            pytest.fail(f"installed target did not serve HTTP: {output.read()[-3000:]}")
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


@pytest.mark.parametrize("fail_target_start", [False, True])
@pytest.mark.parametrize(
    "source_id,target_version,source_env,candidate_env", BRIDGE_CASES,
    ids=["095-to-096", "096-to-097"],
)
def test_exact_source_updater_accepts_candidate_and_preserves_install(
    tmp_path: Path, fail_target_start: bool, source_id: str, target_version: str,
    source_env: str, candidate_env: str,
):
    source_text = os.environ.get(source_env)
    candidate_text = os.environ.get(candidate_env)
    if not source_text or not candidate_text:
        pytest.skip(f"Set {source_env} and {candidate_env} to exact source/candidate roots")
    source = Path(source_text).resolve()
    candidate = Path(candidate_text).resolve()
    source_manifest = read_release_manifest_v2(source / "release-manifest.json")
    assert source_manifest.release_id == source_id
    verify_materialized_release(source, inventory_path=source / "release-payload-inventory.json")
    target_manifest = read_release_manifest_v2(candidate / "ops-release-manifest-v2.json")
    assert target_manifest.section("identity")["release_version"] == target_version
    assert target_manifest.section("database_contract") == source_manifest.section("database_contract")
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
        CurrentRelease(
            SCHEMA_VERSION, source_id, f"releases/{source_id}", source_manifest.raw_sha256,
            "2026-09-24T00:00:00Z", None,
        ),
        expected_manifest_sha256=source_manifest.raw_sha256,
    )
    config = roots.CONFIG_ROOT / "enterprise.env"
    database = roots.DATA_ROOT / "enterprise.db"
    asset = roots.UPLOAD_ROOT / "customer-asset.bin"
    database.parent.mkdir(parents=True, exist_ok=True)
    asset.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("ENTERPRISE_ENV=development\nJWT_SECRET=" + "a" * 64 + "\n", encoding="utf-8")
    bootstrap = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
import enterprise.db as db
db.PATH_ROOTS = derive_portable_path_roots(PortableRootInputs(Path(sys.argv[2]), Path(sys.argv[3])), sys.argv[4])
db.DB_PATH = "enterprise.db"
db.ADMIN_USERNAME = "fixture-admin"
db.ADMIN_PASSWORD = "fixture-only-not-a-secret"
db.init_db()
'''
    subprocess.run(
        [str(source_install / "python" / "python.exe"), "-I", "-B", "-c", bootstrap,
         str(source_install), str(install), str(local), source_id],
        check=True, capture_output=True, text=True, timeout=120,
    )
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, display_name, is_admin, role, created_at) "
            "VALUES (?, ?, ?, ?, 1, 'admin', ?)",
            ("bridge-user", "bridge-fixture", "fixture-hash", "Bridge Fixture", 1),
        )
        conn.execute(
            "INSERT INTO user_canvas_map (user_id, canvas_id, created_at) VALUES (?, ?, ?)",
            ("bridge-user", "bridge-canvas", 1),
        )
    original_database = database.read_bytes()
    asset.write_bytes(b"unchanged-customer-asset-fixture")

    # Run from the copied official source with its bundled Python.  No code
    # from the current checkout is imported by this updater subprocess.
    source_worker = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.ops.update.mvp import UpdateJobStore, UpdateMvpService, execute_update_job
from enterprise.release.current_release import read_current_release_result_from_state_root
source, install, local, manifest, archive, inventory = map(Path, sys.argv[1:7])
fail = sys.argv[7] == "1"
roots = derive_portable_path_roots(PortableRootInputs(install, local), source.name)
prepared = UpdateMvpService(roots).prepare_from_artifacts(
    actor_user_id="fixture-admin", manifest_path=manifest, archive_path=archive, inventory_path=inventory)
store = UpdateJobStore(roots)
store.reserve_execution(prepared.job_id)
store.write_status(prepared.job_id, "UPDATING", actor_user_id="fixture-admin",
    result_code="SYSTEM_UPDATE_STARTED", source_release_id=prepared.source_release_id,
    target_release_id=prepared.target_release_id)
def launcher(root, command):
    if fail and root.name == prepared.target_release_id and command == "start":
        return 2, {"code": "DRILL_TARGET_START_FAILED"}
    return 0, {"status": "fixture-only-no-process"}
code = execute_update_job(roots, prepared.job_id, launcher=launcher)
pointer = read_current_release_result_from_state_root(roots.STATE_ROOT)
print(json.dumps({"exit_code": code, "job_id": prepared.job_id, "prepared_target": prepared.target_release_id,
    "state": store.read_status(prepared.job_id)["state"], "current": pointer.release.release_id}))
'''
    command = [
        str(source_install / "python" / "python.exe"), "-I", "-B", "-c", source_worker,
        str(source_install), str(install), str(local), str(candidate / "ops-release-manifest-v2.json"),
        str(archives[0]), str(candidate / "release-payload-inventory.json"),
        "1" if fail_target_start else "0",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stderr[-2000:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["prepared_target"] == target_manifest.release_id
    assert result["state"] == ("ROLLED_BACK" if fail_target_start else "SUCCEEDED")
    assert result["current"] == (source_id if fail_target_start else target_manifest.release_id)
    assert config.read_text(encoding="utf-8").startswith("ENTERPRISE_ENV=development")
    assert database.read_bytes() == original_database
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT canvas_id FROM user_canvas_map WHERE user_id = 'bridge-user'").fetchone() == ("bridge-canvas",)
    assert asset.read_bytes() == b"unchanged-customer-asset-fixture"

    target = roots.RELEASE_ROOT / target_manifest.release_id
    verify_materialized_release(target, inventory_path=target / "release-payload-inventory.json")
    if fail_target_start:
        return
    target_preflight = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.runtime.portable import build_portable_preflight
result = build_portable_preflight(Path(sys.argv[1]), local_app_data_resolver=lambda: Path(sys.argv[2]))
print(json.dumps({"release_id": result.release_manifest.release_id, "result": result.result.result}))
'''
    startup = subprocess.run(
        [str(target / "python" / "python.exe"), "-I", "-B", "-c", target_preflight, str(target), str(local)],
        check=False, capture_output=True, text=True, timeout=180,
    )
    assert startup.returncode == 0, startup.stderr[-2000:]
    preflight = json.loads(startup.stdout.strip().splitlines()[-1])
    assert preflight["release_id"] == target_manifest.release_id
    assert preflight["result"] == "pass"
    _assert_target_serves_http(target, install, local)
    with sqlite3.connect(database) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert conn.execute("SELECT canvas_id FROM user_canvas_map WHERE user_id = 'bridge-user'").fetchone() == ("bridge-canvas",)
    assert asset.read_bytes() == b"unchanged-customer-asset-fixture"
