"""Opt-in full-payload installation-copy drills; never customer data or Setup UI.

Build clean, same-source Release assets and a native entry beforehand. The real
bundled Python/named pipe exercises the same v2 handler as Setup, without
changing global shortcuts, registry hints or authenticating a browser user.
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
from enterprise.install_setup_bridge import MAINTENANCE_REQUEST_SCHEMA
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.release_manifest_v2 import materialize_release_fixture
from enterprise.tests.test_install_ux_1 import _client_exchange

PASSWORD = "Fixture-only-Maintenance-Strong-Password-2026!"


def _snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


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


def _pipe(resources, root, operation):
    suffix = uuid.uuid4().hex
    app = resources["app"]
    request = {"schema_version": MAINTENANCE_REQUEST_SCHEMA, "operation": operation,
               "install_mode": "custom", "install_root": str(root),
               "username": "fixture-maintainer" if operation == "install" else "",
               "password": PASSWORD if operation == "install" else "",
               "password_confirmation": PASSWORD if operation == "install" else ""}
    observed = {}
    process = subprocess.Popen(
        [str(app / "python/python.exe"), "-I", "-B", str(app / "enterprise/install_setup_bridge.py"),
         "--pipe-name", suffix], cwd=resources["base"], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    def exchange():
        try:
            observed["result"] = _client_exchange(suffix, request)
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
    assert _snapshot(root) == before and _database(root) == database


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
    # No inherited deployment secrets/ports or customer runtime. Hold both test
    # ports until just before launch; Runtime rechecks ownership before starting.
    reservations = [socket.socket() for _ in range(2)]
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
        assert exit_code == 0, healthy
        exit_code, status = _native(root, "status", evidence / "status.json", environment)
        assert exit_code == 0, status
    finally:
        exit_code, stopped = _native(root, "stop", evidence / "stop.json", environment)
        assert exit_code == 0 and stopped.get("result") in {"stopped", "already_stopped"}, stopped
    for port in ports:
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0
    assert all((root / name).read_bytes() == data for name, data in business.items())
    assert _database(root)["integrity"] == "ok"
    print("actual bundled application lifecycle seconds", round(time.monotonic() - started, 3))
