"""Opt-in full-payload installation-copy drills; never customer data or Setup UI.

Build clean, same-source Release assets and a native entry beforehand. The real
bundled Python/named pipe exercises Setup's v2/v3 and graphical v4 handlers,
without changing global shortcuts, registry hints or authenticating a browser user.
SQLite/config/media are fresh fixtures. Runtime listener checks are a separate
explicit opt-in and use only dynamically allocated ports and owned processes.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest

from enterprise import fresh_install as fresh
from enterprise import install_entry as entry_module
from enterprise.install_setup_bridge import (
    GRAPHICAL_MAINTENANCE_REQUEST_SCHEMA, MAINTENANCE_REQUEST_SCHEMA, PROGRAM_MAINTENANCE_REQUEST_SCHEMA,
)
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.release_manifest_v2 import materialize_release_fixture
from enterprise.tests.test_install_ux_1 import _client_exchange

PASSWORD = "Fixture-only-Maintenance-Strong-Password-2026!"


def _snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def _entry_preserved_snapshot(root):
    # Only new, owned entry journals may accumulate during entry maintenance.
    # Do not exempt unrelated staging files, program repairs or installation state.
    return {name: digest for name, digest in _snapshot(root).items()
            if not Path(name).parts[:2] == ("staging", "entry-repairs")}


def _database(root):
    # Read-only, explicitly close even under assertion failure (Windows locks).
    with contextlib.closing(sqlite3.connect((root / "data/enterprise.db").as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        result = {
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "users": conn.execute("SELECT count(*) FROM users").fetchone()[0],
            "super_admins": conn.execute("SELECT count(*) FROM users WHERE role='super_admin'").fetchone()[0],
            "audit": conn.execute("SELECT count(*) FROM security_audit_events").fetchone()[0],
        }
    return result


@pytest.fixture(scope="module")
def resources(tmp_path_factory):
    values = [os.environ.get(k) for k in ("ICE_MAINTENANCE_RELEASE_ASSETS", "ICE_NATIVE_ENTRY")]
    if os.name != "nt" or not all(values):
        pytest.skip("opt-in Windows drill requires clean same-source Release assets/native entry")
    assets, native = (Path(v).absolute() for v in values)
    verified = fresh.verify_release_assets(assets)
    source = verified.manifest.section("enterprise_source")
    entry = entry_module.verify_entry_bundle(native.parent, commit=source["commit"], tree=source["tree"])
    base = tmp_path_factory.getbasetemp()
    # Keep paths short, but never outside the caller's fresh pytest artifact root.
    # Match Setup's fixed extraction layout, not a permissive test-only path.
    bundle = base / "install-ux-bundle"
    bundle.mkdir()
    for path in (verified.manifest_path, verified.archive_path, verified.inventory_path):
        shutil.copyfile(path, bundle / path.name)
    shutil.copytree(native.parent, bundle / "native-entry")
    app = bundle / "raw" / verified.manifest.section("archive")["root_prefix"]
    materialize_release_fixture(verified.manifest_path, verified.archive_path, verified.inventory_path, app)
    return {"assets": bundle, "app": app, "entry": entry, "base": base,
            "release_id": verified.manifest.release_id}


def _root(resources):
    return resources["base"] / ("i-" + uuid.uuid4().hex[:6])


def _install(resources, root):
    return fresh.install_greenfield(
        release_dir=resources["assets"], install_root=root, username="fixture-maintainer",
        password=PASSWORD, password_confirmation=PASSWORD,
        local_app_data_base=resources["base"] / "local",
        native_entry_dir=resources["assets"] / "native-entry",
    )


def _pipe(resources, root, operation, *, graphical=False, on_progress=None):
    suffix = uuid.uuid4().hex
    app = resources["app"]
    request = {"schema_version": MAINTENANCE_REQUEST_SCHEMA, "operation": operation,
               "install_mode": "custom", "install_root": str(root),
               "username": "fixture-maintainer" if operation == "install" else "",
               "password": PASSWORD if operation == "install" else "",
               "password_confirmation": PASSWORD if operation == "install" else ""}
    if operation in {"repair-program", "recover-program"}:
        request.update(schema_version=PROGRAM_MAINTENANCE_REQUEST_SCHEMA, confirm_no_active_tasks=True)
    if graphical:
        request.update(schema_version=GRAPHICAL_MAINTENANCE_REQUEST_SCHEMA,
                       confirm_no_active_tasks=operation != "inspect-program")
    observed = {}
    process = subprocess.Popen(
        [str(app / "python/python.exe"), "-I", "-B", str(app / "enterprise/install_setup_bridge.py"),
         "--pipe-name", suffix], cwd=resources["base"], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    def exchange():
        try:
            observed["result"] = _client_exchange(suffix, request, on_progress=on_progress)
        except BaseException as exc:
            observed["error"] = type(exc).__name__
    worker = threading.Thread(target=exchange, daemon=True)
    worker.start()
    try:
        stdout, stderr = process.communicate(timeout=180)
    finally:
        if process.poll() is None:
            process.terminate()  # Only this exact, test-owned bridge process.
            process.wait(timeout=10)
        worker.join(timeout=5)
        request.clear()
    assert not worker.is_alive() and "error" not in observed, observed
    assert PASSWORD.encode() not in stdout + stderr
    return process.returncode, observed["result"]


def _fixture_business(root):
    (root / "data/canvases").mkdir(exist_ok=True)
    (root / "data/canvases/maintenance-fixture.json").write_bytes(b'{"fixture":"preserve"}\n')
    (root / "assets").mkdir(exist_ok=True)
    (root / "assets/maintenance-fixture.bin").write_bytes(b"test media; no customer material")


def _fixture_stale_entry_record(root):
    """Seed owned stale metadata, NOT a real historical native Release.

    The compiled EXE hash, installation identity, root and all Release assets
    remain valid and unchanged. Only this synthetic installation's build-record
    reference is intentionally stale, so real record publication/restoration is
    nonempty even when the deterministic same-source EXE bytes are identical.
    """
    from enterprise.release.release_manifest_v2 import canonical_json
    path = root / "state/installation.json"
    expected = path.read_bytes()
    value = json.loads(expected)
    value["native_entry"]["build_record_sha256"] = hashlib.sha256(b"fixture-only-stale-build-record").hexdigest()
    path.write_bytes(canonical_json(value))
    assert path.read_bytes() != expected
    return expected


def test_actual_bundled_python_new_install_duplicate_rejection_and_repair(resources):
    root = _root(resources)
    exit_code, result = _pipe(resources, root, "install")
    assert exit_code == 0 and result["status"] == "succeeded", result
    assert result["launcher_installed"] and result["pointer_published"]
    identity = json.loads((root / "state/installation.json").read_bytes())["installation_id"]
    assert result["installation_id"] == identity
    database = _database(root)
    assert database["integrity"] == "ok" and database["users"] == database["super_admins"] == 1
    assert database["audit"] >= 1
    _fixture_business(root)
    before = _snapshot(root)
    exit_code, duplicate = _pipe(resources, root, "install")
    assert exit_code == 2 and duplicate["code"] == "INSTALL_TARGET_NOT_GREENFIELD", duplicate
    assert _snapshot(root) == before
    for _ in range(2):
        exit_code, repaired = _pipe(resources, root, "repair-entry")
        assert exit_code == 0 and repaired["code"] == "INSTALL_ENTRY_REPAIRED", repaired
        assert repaired["installation_id"] == identity
        assert repaired["database_changed"] is repaired["pointer_changed"] is False
    assert _entry_preserved_snapshot(root) == before and _database(root) == database


def test_real_new_install_pointer_failure_rolls_back_then_retry_succeeds(resources, monkeypatch):
    root = _root(resources)
    original = fresh.atomic_write_current_release
    def fail_pointer(*args, **kwargs):
        assert (root / "InfiniteCanvas.exe").is_file()
        assert _database(root)["integrity"] == "ok"
        raise OSError("fixture-only pointer publication failure")
    with monkeypatch.context() as patch:
        patch.setattr(fresh, "atomic_write_current_release", fail_pointer)
        with pytest.raises(fresh.FreshInstallError, match="INSTALL_FAILED"):
            _install(resources, root)
    assert not root.exists()
    assert fresh.atomic_write_current_release is original
    result = _install(resources, root)
    assert result.pointer_published and result.launcher_installed
    assert _database(root)["integrity"] == "ok"


def test_entry_repair_postpublication_failure_restores_only_owned_files(resources, monkeypatch):
    root = _root(resources)
    installed = _install(resources, root)
    _fixture_business(root)
    (root / "InfiniteCanvas.exe").unlink()  # Simulate missing entry in this owned fixture only.
    before = _snapshot(root)
    from enterprise.ops.update.mvp import UpdateJobStore
    original = UpdateJobStore.pending_recovery_jobs
    calls = 0
    def pending(store, **kwargs):
        nonlocal calls
        calls += 1
        return [] if calls == 1 else ["fixture-only-unresolved-recovery"]
    with monkeypatch.context() as patch:
        patch.setattr(UpdateJobStore, "pending_recovery_jobs", pending)
        with pytest.raises(entry_module.InstallEntryError, match="INSTALL_ENTRY_RECOVERY_REQUIRED"):
            entry_module.repair_fixed_entry(install_root=root, entry=resources["entry"],
                                           local_app_data_base=resources["base"] / "local")
    # Backups are retained evidence, not business data or an incomplete active lock.
    after = _snapshot(root)
    assert all(after.get(name) == digest for name, digest in before.items())
    assert not (root / "InfiniteCanvas.exe").exists()
    assert not (root / "state/system-update-active.lock").exists()
    assert UpdateJobStore.pending_recovery_jobs is original
    repaired = entry_module.repair_fixed_entry(install_root=root, entry=resources["entry"],
                                               local_app_data_base=resources["base"] / "local")
    assert repaired["installation_id"] == installed.installation_id
    after = _snapshot(root)
    assert all(after[name] == digest for name, digest in before.items())
    assert _database(root)["integrity"] == "ok"


def test_existing_unknown_lock_is_not_removed_or_reinitialized(resources):
    root = _root(resources)
    _install(resources, root)
    lock = root / "state/system-update-active.lock"
    lock.write_bytes(b"fixture foreign or interrupted lock; do not guess ownership")
    before = _snapshot(root)
    with pytest.raises(entry_module.InstallEntryError, match="INSTALL_ENTRY_MAINTENANCE_BUSY"):
        entry_module.repair_fixed_entry(install_root=root, entry=resources["entry"],
                                       local_app_data_base=resources["base"] / "local")
    assert _snapshot(root) == before and _database(root)["integrity"] == "ok"


def _program(resources, root):
    return root / "releases" / resources["release_id"]


def _damage_program(resources, root):
    app = _program(resources, root)
    (app / "main.py").write_bytes(b"# damaged test fixture; never customer code\n")
    (app / "python/python.exe").unlink()  # Only this test-owned installed copy.


def _maintenance_snapshot(root):
    result = {name + "/" + path: digest for name in ("data", "config", "assets")
              for path, digest in _snapshot(root / name).items()}
    for name in ("state/installation.json", "state/current-release.json", "InfiniteCanvas.exe"):
        result[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    return result


def test_actual_bundled_python_program_and_environment_repair(resources):
    root = _root(resources)
    _install(resources, root)
    _fixture_business(root)
    before, database = _maintenance_snapshot(root), _database(root)
    _damage_program(resources, root)
    exit_code, repaired = _pipe(resources, root, "repair-program")
    assert exit_code == 0 and repaired["code"] == "INSTALL_PROGRAM_REPAIRED", repaired
    assert repaired["repair_state"] == "SUCCEEDED"
    assert repaired["entry_changed"] is repaired["pointer_changed"] is repaired["database_changed"] is False
    assert _maintenance_snapshot(root) == before and _database(root) == database
    from enterprise.release.release_manifest_v2 import verify_materialized_release
    app = _program(resources, root)
    verify_materialized_release(app, inventory_path=app / "release-payload-inventory.json")
    assert (app / "python/python.exe").is_file()


def _crash_program_runner(resources, root, checkpoint):
    app = resources["app"]
    # Kill this owned runner without finally blocks; the second process must
    # acquire the Windows-released lease, verify the saved plan and recover.
    code = """
import os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from enterprise import install_repair as repair
from enterprise.runtime.portable import windows_local_app_data_known_folder
def crash(name):
    if name == sys.argv[4]: os._exit(86)
repair._checkpoint = crash
repair.repair_program(install_root=pathlib.Path(sys.argv[2]), release_dir=pathlib.Path(sys.argv[3]),
    local_app_data_base=windows_local_app_data_known_folder(), confirm_no_active_tasks=True)
"""
    process = subprocess.run([str(app / "python/python.exe"), "-I", "-B", "-c", code,
                              str(app), str(root), str(resources["assets"]), checkpoint],
                             cwd=resources["base"], capture_output=True, timeout=180,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode == 86, (process.returncode, process.stdout, process.stderr)


def _crash_entry_runner(resources, root, checkpoint, *, recovering=False):
    app = resources["app"]
    # The runner really exits: no monkeypatched OS inspector, no finally-based
    # lease release and no in-process recovery. A distinct Setup bridge acquires
    # the Windows-released lease and rechecks the retained immutable identities.
    code = """
import os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from enterprise import install_entry, install_entry_repair
from enterprise.runtime.portable import windows_local_app_data_known_folder
def crash(name):
    if name == sys.argv[4]: os._exit(86)
install_entry_repair._checkpoint = crash
entry = install_entry.verify_entry_bundle(pathlib.Path(sys.argv[3]) / 'native-entry')
operation = install_entry.recover_fixed_entry if sys.argv[5] == 'recover' else install_entry.repair_fixed_entry
operation(install_root=pathlib.Path(sys.argv[2]), entry=entry,
    local_app_data_base=windows_local_app_data_known_folder())
"""
    process = subprocess.run([str(app / "python/python.exe"), "-I", "-B", "-c", code,
                              str(app), str(root), str(resources["assets"]), checkpoint,
                              "recover" if recovering else "repair"],
                             cwd=resources["base"], capture_output=True, timeout=180,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode == 86, (process.returncode, process.stdout, process.stderr)


@pytest.mark.parametrize("checkpoint", ["locked", "prepared", "entry_published", "record_published", "committed"])
def test_actual_process_death_recovers_only_its_fixed_entry_transaction(resources, checkpoint):
    root = _root(resources)
    _install(resources, root)
    _fixture_business(root)
    expected_record = _fixture_stale_entry_record(root)
    # A same-source native build has equal bytes before and after maintenance.
    # Removing ONLY this fixture's owned entry proves real nonempty publication
    # and absent-entry rollback. Different nonempty old bytes are a unit contract,
    # not a claimed real historical native build validated by this drill.
    (root / "InfiniteCanvas.exe").unlink()
    before, database = _entry_preserved_snapshot(root), _database(root)
    _crash_entry_runner(resources, root, checkpoint)
    lock = root / "state/system-update-active.lock"
    assert lock.is_file()
    exit_code, recovered = _pipe(resources, root, "recover-entry")
    expected = "SUCCEEDED" if checkpoint == "committed" else "ROLLED_BACK"
    assert exit_code == 0 and recovered["code"] == "INSTALL_ENTRY_RECOVERED", recovered
    assert recovered["repair_state"] == expected
    assert recovered["database_changed"] is recovered["pointer_changed"] is False
    assert not lock.exists()
    if expected == "ROLLED_BACK":
        assert not (root / "InfiniteCanvas.exe").exists()
        assert _entry_preserved_snapshot(root) == before
        exit_code, repaired = _pipe(resources, root, "repair-entry")
        assert exit_code == 0 and repaired["repair_state"] == "SUCCEEDED", repaired
    assert (root / "InfiniteCanvas.exe").read_bytes() == resources["entry"].data
    assert (root / "state/installation.json").read_bytes() == expected_record
    after = _entry_preserved_snapshot(root)
    assert all(after[name] == digest for name, digest in before.items() if name != str(Path("state/installation.json")))
    assert _database(root) == database


@pytest.mark.parametrize("checkpoint", ["record_restored", "entry_restored"])
def test_actual_second_process_death_resumes_fixed_entry_restoration(resources, checkpoint):
    root = _root(resources)
    _install(resources, root)
    _fixture_business(root)
    expected_record = _fixture_stale_entry_record(root)
    (root / "InfiniteCanvas.exe").unlink()
    before, database = _entry_preserved_snapshot(root), _database(root)
    _crash_entry_runner(resources, root, "record_published")
    _crash_entry_runner(resources, root, checkpoint, recovering=True)
    exit_code, recovered = _pipe(resources, root, "recover-entry")
    assert exit_code == 0 and recovered["repair_state"] == "ROLLED_BACK", recovered
    assert _entry_preserved_snapshot(root) == before and _database(root) == database
    assert not (root / "state/system-update-active.lock").exists()
    exit_code, repaired = _pipe(resources, root, "repair-entry")
    assert exit_code == 0 and repaired["repair_state"] == "SUCCEEDED", repaired
    assert (root / "InfiniteCanvas.exe").read_bytes() == resources["entry"].data
    assert (root / "state/installation.json").read_bytes() == expected_record


def test_actual_d_install_c_knownfolder_fence_recovers_with_same_volume_markers(resources):
    from enterprise.runtime.portable import windows_local_app_data_known_folder
    from enterprise import install_entry_repair
    local_base = windows_local_app_data_known_folder()
    root = _root(resources)
    roots = derive_portable_path_roots(PortableRootInputs(root, local_base), resources["release_id"])
    if root.drive.upper() != "D:" or roots.RUNTIME_ROOT.drive.upper() != "C:":
        pytest.skip("actual D installation / C KnownFolder cross-volume gate requires those real host drives")
    _install(resources, root)
    _fixture_business(root)
    (root / "InfiniteCanvas.exe").unlink()
    before, database = _entry_preserved_snapshot(root), _database(root)
    _crash_entry_runner(resources, root, "prepared")
    common = root / "state/system-update-active.lock"
    marker = json.loads(common.read_bytes())
    directory = root / "staging/entry-repairs" / marker["operation_id"][:12]
    retained = install_entry_repair._fence_retained(roots, marker["operation_id"])
    fence = roots.RUNTIME_ROOT / "runtime-reconcile.lock"
    assert directory.drive.upper() == "D:" and retained.drive.upper() == fence.drive.upper() == "C:"
    assert retained.read_bytes() == fence.read_bytes()
    assert (retained.stat().st_dev, retained.stat().st_ino) == (fence.stat().st_dev, fence.stat().st_ino)
    assert list((retained.stat().st_dev, retained.stat().st_ino)) == marker["fence"]["identity"]
    assert (directory / "common.marker").read_bytes() == common.read_bytes()
    assert (directory / "common.marker").stat().st_ino == common.stat().st_ino
    exit_code, recovered = _pipe(resources, root, "recover-entry")
    assert exit_code == 0 and recovered["repair_state"] == "ROLLED_BACK", recovered
    assert _entry_preserved_snapshot(root) == before and _database(root) == database
    assert not common.exists() and not fence.exists()
    assert retained.exists()  # Retained evidence, never a guessed cleanup target.


@pytest.mark.parametrize("checkpoint", ["original_moved", "candidate_published", "committed"])
def test_actual_process_death_recovers_only_its_program_transaction(resources, checkpoint):
    root = _root(resources)
    _install(resources, root)
    _fixture_business(root)
    before, database = _maintenance_snapshot(root), _database(root)
    _damage_program(resources, root)
    damaged = _snapshot(_program(resources, root))
    _crash_program_runner(resources, root, checkpoint)
    lock = root / "state/system-update-active.lock"
    assert lock.is_file()
    exit_code, recovered = _pipe(resources, root, "recover-program")
    assert exit_code == 0 and recovered["code"] == "INSTALL_PROGRAM_RECOVERED", recovered
    expected = "SUCCEEDED" if checkpoint == "committed" else "ROLLED_BACK"
    assert recovered["repair_state"] == expected and not lock.exists()
    assert _maintenance_snapshot(root) == before and _database(root) == database
    if checkpoint != "committed":
        assert _snapshot(_program(resources, root)) == damaged
        exit_code, retried = _pipe(resources, root, "repair-program")
        assert exit_code == 0 and retried["repair_state"] == "SUCCEEDED", retried
    assert _maintenance_snapshot(root) == before and _database(root) == database


def test_actual_graphical_repair_survives_detach_and_later_query(resources):
    root = _root(resources)
    _install(resources, root)
    _fixture_business(root)
    before, database = _maintenance_snapshot(root), _database(root)
    _damage_program(resources, root)
    started = time.monotonic()
    # Only the client view disconnects; the unmodified external worker exits
    # after committing the actual full program/interpreter repair.
    exit_code, frame = _pipe(resources, root, "repair-program", graphical=True,
                             on_progress=lambda progress: False)
    assert exit_code == 0 and frame["event"] == "progress" and frame["phase"] == "preparing", frame
    complete = _snapshot(root)
    exit_code, status = _pipe(resources, root, "inspect-program", graphical=True)
    assert exit_code == 0 and status["code"] == "INSTALL_PROGRAM_STATUS", status
    assert status["repair_state"] == "SUCCEEDED" and status["operation_id"] == frame["operation_id"]
    assert status["database_changed"] is status["pointer_changed"] is status["entry_changed"] is False
    assert _snapshot(root) == complete
    assert _maintenance_snapshot(root) == before and _database(root) == database
    from enterprise.release.release_manifest_v2 import verify_materialized_release
    app = _program(resources, root)
    verify_materialized_release(app, inventory_path=app / "release-payload-inventory.json")
    print("full-payload detached graphical repair and query seconds", round(time.monotonic() - started, 3))


def test_actual_graphical_interruption_query_recovery_and_retry(resources):
    root = _root(resources)
    _install(resources, root)
    _fixture_business(root)
    before, database = _maintenance_snapshot(root), _database(root)
    _damage_program(resources, root)
    damaged = _snapshot(_program(resources, root))
    _crash_program_runner(resources, root, "candidate_published")
    complete = _snapshot(root)
    exit_code, status = _pipe(resources, root, "inspect-program", graphical=True)
    assert exit_code == 0 and status["repair_state"] == "RECOVERY_REQUIRED", status
    assert _snapshot(root) == complete  # Inspection is not recovery.
    phases = []
    def observe(frame):
        phases.append(frame["phase"])
    exit_code, recovered = _pipe(resources, root, "recover-program", graphical=True, on_progress=observe)
    assert exit_code == 0 and recovered["repair_state"] == "ROLLED_BACK", recovered
    assert phases == ["recovering", "rolled_back"]
    assert _snapshot(_program(resources, root)) == damaged
    assert not (root / "state/system-update-active.lock").exists()
    complete = _snapshot(root)
    exit_code, status = _pipe(resources, root, "inspect-program", graphical=True)
    assert exit_code == 0 and status["repair_state"] == "ROLLED_BACK", status
    assert _snapshot(root) == complete
    phases.clear()
    exit_code, repaired = _pipe(resources, root, "repair-program", graphical=True, on_progress=observe)
    assert exit_code == 0 and repaired["repair_state"] == "SUCCEEDED", repaired
    assert phases == ["preparing", "locked", "publishing", "verifying", "committed"]
    assert _maintenance_snapshot(root) == before and _database(root) == database


def _native(root, command, output, environment):
    completed = subprocess.run([str(root / "InfiniteCanvas.exe"), "--" + command,
                                "--result-file", str(output)], cwd=output.parent, env=environment,
                               capture_output=True, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    payload = json.loads(output.read_bytes())
    return completed.returncode, payload


def test_actual_native_entry_and_supervisor_start_health_stop(resources):
    if os.environ.get("ICE_MAINTENANCE_RUNTIME_DRILL") != "1":
        pytest.skip("real application listener drill requires explicit opt-in")
    root = _root(resources)
    _install(resources, root)
    _fixture_business(root)
    # Exercise a fixed entry recreated after real interrupted publication and
    # second-process rollback, not the already-validated program-repair path.
    (root / "InfiniteCanvas.exe").unlink()
    _crash_entry_runner(resources, root, "entry_published")
    exit_code, recovered = _pipe(resources, root, "recover-entry")
    assert exit_code == 0 and recovered["repair_state"] == "ROLLED_BACK", recovered
    assert not (root / "InfiniteCanvas.exe").exists()
    exit_code, repaired = _pipe(resources, root, "repair-entry")
    assert exit_code == 0 and repaired["repair_state"] == "SUCCEEDED", repaired
    # No inherited deployment secrets/ports or customer runtime. Hold both test
    # ports until just before launch; Runtime rechecks ownership before starting.
    reservations = [socket.socket() for _ in range(2)]
    from enterprise.tests.update_mvp_1_windows_smoke import _owned_identities_absent, _runtime_identities, _wait
    identities = ()
    try:
        for reservation in reservations:
            reservation.bind(("127.0.0.1", 0))
        ports = [s.getsockname()[1] for s in reservations]
    finally:
        for reservation in reservations:
            reservation.close()
    environment = os.environ.copy()
    for key in ("JWT_SECRET", "DB_PATH", "ADMIN_USERNAME", "ADMIN_PASSWORD", "ENTERPRISE_ENV",
                "ENTERPRISE_STRICT_SECURITY", "PYTHONHOME", "PYTHONPATH", "GATEWAY_PORT", "UPSTREAM_PORT"):
        environment.pop(key, None)
    environment.update({"GATEWAY_PORT": str(ports[0]), "UPSTREAM_PORT": str(ports[1])})
    evidence = resources["base"] / ("r-" + uuid.uuid4().hex[:6])
    evidence.mkdir()
    business = {p: (root / p).read_bytes() for p in ("state/current-release.json", "state/installation.json",
                "config/enterprise.env", "data/canvases/maintenance-fixture.json", "assets/maintenance-fixture.bin")}
    started = time.monotonic()
    # KnownFolder Runtime state is currently shared per Windows user. Never
    # stop/reconcile an active installation just to make this drill pass.
    exit_code, baseline = _native(root, "status", evidence / "before.json", environment)
    assert exit_code == 0, baseline
    if (baseline.get("supervisor_identity_current") or baseline.get("owned_child_current")
            or baseline.get("start_disposition") not in {"stopped", "stale_runtime_state"}):
        pytest.skip("current-user Runtime is not quiescent; do not interfere with another installation")
    try:
        exit_code, result = _native(root, "start", evidence / "start.json", environment)
        assert exit_code == 0 and result.get("result") == "started", result
        exit_code, healthy = _native(root, "health", evidence / "health.json", environment)
        assert exit_code == 0 and healthy.get("readiness", {}).get("ready") is True, healthy
        exit_code, status = _native(root, "status", evidence / "status.json", environment)
        identities = _runtime_identities(status)
        assert exit_code == 0 and len(identities) == 3, status
        assert status.get("portable_ownership_valid") is True and status.get("running_release_id") == resources["release_id"], status
        assert status.get("running_release_mismatch") is False and status.get("readiness", {}).get("ready") is True, status
        pointer = json.loads((root / "state/current-release.json").read_bytes())
        assert status["runtime_state"]["release_manifest_sha256"] == pointer["manifest_sha256"]
    finally:
        if not identities:
            _exit_code, observed = _native(root, "status", evidence / "cleanup-status.json", environment)
            identities = _runtime_identities(observed)
        exit_code, stopped = _native(root, "stop", evidence / "stop.json", environment)
        assert exit_code == 0 and stopped.get("result") in {"stopped", "already_stopped"}, stopped
        if identities:
            _wait(lambda: _owned_identities_absent(identities), seconds=60, label="entry-repair-owned-process-exit")
    for port in ports:
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0
    assert all((root / name).read_bytes() == data for name, data in business.items())
    assert _database(root)["integrity"] == "ok"
    print("actual bundled application lifecycle seconds", round(time.monotonic() - started, 3))
