"""Opt-in real fixed-EXE/update-worker drills on synthetic, verified packages.

Never customer assets or paid providers. Existing KnownFolder directories block
by default; temporarily preserving stopped historical directories requires an
explicit operator flag. Same-volume renames preserve their contents and ACLs.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from enterprise.path_safety import assert_no_reparse_ancestors
from enterprise.tests.update_mvp_1_windows_smoke import (
    _assert_unused_local_roots, _create_owned_local_roots, _free_port,
    _owned_identities_absent, _port_open, _read_status, _runtime_identities,
    _update_worker_pids, _wait,
)

NAMES = ("InfiniteCanvasEnterprise", "Infinite-Canvas-Enterprise")
USERNAME = "update-drill-super-admin"
PASSWORD = "Local-fixture-only-Strong-Password-2026!"
TERMINAL = {"SUCCEEDED", "ROLLED_BACK", "FAILED", "RECOVERY_REQUIRED"}


def _json_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _tree_snapshot(root):
    """Hash without exporting contents; reject links and bound enumeration."""
    assert_no_reparse_ancestors(root)
    # Historical extracted packages can exceed MAX_PATH. Keep lexical checks
    # and no-follow semantics, but use Windows' extended-length namespace for
    # enumeration/stat/open so present long files are not reported as absent.
    root = _snapshot_io_root(root)
    files = {}
    count = 0
    for folder, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            path = Path(folder) / name
            assert_no_reparse_ancestors(path)
            count += 1
            if count > 40000:
                raise RuntimeError("FIXED_EXE_SAVED_TREE_TOO_LARGE")
        for name in directories:
            files[(Path(folder) / name).relative_to(root).as_posix() + "/"] = ("directory",)
        for name in names:
            path = Path(folder) / name
            before = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise RuntimeError("FIXED_EXE_SAVED_TREE_CHANGED")
            files[path.relative_to(root).as_posix()] = (before.st_size, before.st_mtime_ns, digest.hexdigest())
    return files


def _snapshot_io_root(root):
    absolute = Path(os.path.abspath(os.fspath(root)))
    if os.name != "nt" or str(absolute).startswith("\\\\?\\"):
        return absolute
    value = str(absolute)
    return Path("\\\\?\\UNC\\" + value[2:]) if value.startswith("\\\\") else Path("\\\\?\\" + value)


def _require_quiescent(local_base):
    runtime = local_base / NAMES[0] / "runtime"
    assert_no_reparse_ancestors(runtime, allow_missing=True)
    if (runtime / "runtime-supervisor.lock").exists():
        raise RuntimeError("FIXED_EXE_EXISTING_RUNTIME_LOCKED")
    state_path = runtime / "runtime-state.json"
    if not state_path.exists():
        if runtime.exists() and any(runtime.iterdir()):
            raise RuntimeError("FIXED_EXE_EXISTING_RUNTIME_UNVERIFIED")
        return
    assert_no_reparse_ancestors(state_path)
    if state_path.stat().st_size > 1024 * 1024:
        raise RuntimeError("FIXED_EXE_EXISTING_RUNTIME_UNVERIFIED")
    state = json.loads(state_path.read_bytes())
    if state.get("schema_version") != "runtime-supervisor-state-v1" or state.get("state") != "stopped":
        raise RuntimeError("FIXED_EXE_EXISTING_RUNTIME_NOT_STOPPED")
    identities = _runtime_identities({"runtime_state": state})
    if not identities or not _owned_identities_absent(identities):
        raise RuntimeError("FIXED_EXE_EXISTING_RUNTIME_NOT_STOPPED")
    # Historical state does not necessarily retain ports. Do not invent them:
    # also exclude any live process using its fixed executable (any instance).
    if _saved_executable_in_use(state.get("supervisor_executable")):
        raise RuntimeError("FIXED_EXE_EXISTING_RUNTIME_NOT_STOPPED")
    for role in ("upstream", "gateway"):
        port = state.get(role, {}).get("port")
        if port is not None and (type(port) is not int or not 0 < port < 65536 or _port_open(port)):
            raise RuntimeError("FIXED_EXE_EXISTING_RUNTIME_PORT_UNVERIFIED")


def _saved_executable_in_use(executable):
    if not isinstance(executable, str) or not Path(executable).is_absolute():
        raise RuntimeError("FIXED_EXE_EXISTING_RUNTIME_UNVERIFIED")
    environment = dict(os.environ)
    environment["ICE_DRILL_SAVED_EXE"] = executable
    result = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-Command",
        "$ErrorActionPreference='Stop'; $n=@(Get-CimInstance Win32_Process | Where-Object { "
        "$_.ExecutablePath -and $_.ExecutablePath.Equals($env:ICE_DRILL_SAVED_EXE,"
        "[System.StringComparison]::OrdinalIgnoreCase)}).Count; ConvertTo-Json -Compress $n"],
        env=environment, capture_output=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError("FIXED_EXE_EXISTING_RUNTIME_UNVERIFIED")
    count = json.loads(result.stdout.decode("utf-8-sig"))
    if type(count) is not int or count < 0:
        raise RuntimeError("FIXED_EXE_EXISTING_RUNTIME_UNVERIFIED")
    return count != 0


@contextlib.contextmanager
def preserved_local_roots(local_base, nonce, *, explicitly_authorized=False):
    """Never move by default, replace a root, or erase an unowned directory."""
    if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", nonce):
        raise RuntimeError("FIXED_EXE_NONCE_INVALID")
    existing = [local_base / name for name in NAMES if (local_base / name).exists()]
    if not explicitly_authorized:
        _assert_unused_local_roots(local_base, NAMES)
        yield {"historical_roots_preserved": False}
        return
    assert_no_reparse_ancestors(local_base)
    _require_quiescent(local_base)
    saved = local_base / ("ICE-UpdateDrill-Saved-" + nonce)
    if saved.exists():
        raise RuntimeError("FIXED_EXE_SAVED_ROOT_EXISTS")
    snapshots = {path.name: _tree_snapshot(path) for path in existing}
    identities = {path.name: (path.stat().st_dev, path.stat().st_ino) for path in existing}
    _require_quiescent(local_base)
    saved.mkdir(exist_ok=False)
    _json_new(saved / "preservation.json", {"nonce": nonce, "roots": list(snapshots), "complete": False,
                                           "snapshots": snapshots, "directory_identities": identities})
    moved = []
    try:
        for source in existing:
            if (source.stat().st_dev, source.stat().st_ino) != identities[source.name] or _tree_snapshot(source) != snapshots[source.name]:
                raise RuntimeError("FIXED_EXE_SAVED_TREE_CHANGED")
            source.rename(saved / source.name)
            moved.append(source.name)
        _assert_unused_local_roots(local_base, NAMES)
        yield {"historical_roots_preserved": bool(moved)}
    finally:
        # A fixture cleanup error leaves both the original and the fixture in
        # place for recovery; never overwrite either to obtain a passing test.
        for name in moved:
            if (local_base / name).exists() or (local_base / name).is_symlink():
                raise RuntimeError("FIXED_EXE_RESTORE_DESTINATION_OCCUPIED")
            source = saved / name
            if (source.stat().st_dev, source.stat().st_ino) != identities[name] or _tree_snapshot(source) != snapshots[name]:
                raise RuntimeError("FIXED_EXE_SAVED_TREE_CHANGED")
        for name in moved:
            (saved / name).rename(local_base / name)
        for name in moved:
            if _tree_snapshot(local_base / name) != snapshots[name]:
                raise RuntimeError("FIXED_EXE_RESTORE_VERIFY_FAILED")
        _json_new(saved / "RESTORED.json", {"nonce": nonce, "all_bytes_and_mtimes_verified": True,
                                         "same_directory_identities": True, "roots": moved})


def _environment():
    result = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT", "JWT_SECRET", "DB_PATH",
                "ADMIN_USERNAME", "ADMIN_PASSWORD", "ENTERPRISE_ENV", "ENTERPRISE_STRICT_SECURITY",
                "GATEWAY_PORT", "UPSTREAM_PORT", "UPSTREAM_URL", "ENTERPRISE_UPDATE_ENABLED"):
        result.pop(key, None)
    return result


def _remove_owned_local_root(path, local_base, nonce):
    """Use the lexical KnownFolder identity, not a virtualized resolve alias."""
    if path.parent != local_base or path.name not in NAMES:
        raise RuntimeError("FIXED_EXE_LOCAL_ROOT_IDENTITY_INVALID")
    assert_no_reparse_ancestors(path, allow_missing=True)
    if not path.exists():
        return
    marker = path / ".ops3b-drill-owned"
    assert_no_reparse_ancestors(marker)
    if not marker.is_file() or marker.read_text(encoding="ascii") != nonce:
        raise RuntimeError("FIXED_EXE_LOCAL_ROOT_NOT_OWNED")
    if (path / "runtime/runtime-supervisor.lock").exists():
        raise RuntimeError("FIXED_EXE_LOCAL_RUNTIME_STILL_ACTIVE")
    # Exact named, no-reparse, nonce-owned directory only. Historical roots
    # remain in the preservation directory, never under this removal target.
    shutil.rmtree(_snapshot_io_root(path))


def _asset_view(build, destination):
    """Builder records stay intact; install consumes a closed three-asset view."""
    from enterprise import fresh_install as fresh
    from enterprise.release.release_manifest_v2 import read_release_manifest_v2

    manifest = read_release_manifest_v2(build / fresh.MANIFEST_NAME)
    names = (fresh.MANIFEST_NAME, fresh.INVENTORY_NAME, str(manifest.section("archive")["filename"]))
    destination.mkdir(parents=True, exist_ok=False)
    for name in names:
        source = build / name
        assert_no_reparse_ancestors(source)
        if not source.is_file():
            raise RuntimeError("FIXED_EXE_BUILD_ASSET_MISSING")
        shutil.copyfile(source, destination / name)
    return fresh.verify_release_assets(destination)


def _native(install, command, evidence):
    path = evidence / (command + "-" + uuid.uuid4().hex[:8] + ".json")
    result = subprocess.run([str(install / "InfiniteCanvas.exe"), "--" + command, "--result-file", str(path)],
                            cwd=evidence, env=_environment(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    payload = json.loads(path.read_bytes())
    return result.returncode, payload


def _configure(roots, upstream_port, gateway_port):
    config = roots.CONFIG_ROOT / "enterprise.env"
    # Fresh installation owns this file and its generated JWT secret. Preserve
    # it; add only fixture ports/update access, never inherited credentials.
    config.write_text(config.read_text(encoding="utf-8") +
                      f"UPSTREAM_PORT={upstream_port}\nGATEWAY_PORT={gateway_port}\nENTERPRISE_UPDATE_ENABLED=true\n",
                      encoding="utf-8", newline="\n")


def _seed_business(roots, user_id):
    canvas = roots.DATA_ROOT / "canvases" / "update-drill.json"
    canvas.parent.mkdir(exist_ok=True)
    canvas.write_bytes(b'{"id":"update-drill","nodes":[],"fixture":"retain"}\n')
    media = roots.INSTALL_ROOT / "assets" / "update-drill.bin"
    media.parent.mkdir(exist_ok=True)
    media.write_bytes(b"synthetic media, no customer content\n")
    with contextlib.closing(sqlite3.connect(roots.DATA_ROOT / "enterprise.db")) as conn:
        conn.execute("INSERT INTO user_canvas_map(user_id,canvas_id,created_at) VALUES(?,?,?)",
                     (user_id, "update-drill", 1))
        conn.execute("INSERT INTO enterprise_feature_flags(feature_key,enabled,description,updated_by,updated_at) "
                     "VALUES(?,?,?,?,?) ON CONFLICT(feature_key) DO UPDATE SET enabled=excluded.enabled, "
                     "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                     ("system_update", 1, "synthetic fixture update authorization", user_id, 1))
        conn.commit()
    return {str(p.relative_to(roots.INSTALL_ROOT)): p.read_bytes() for p in (
        canvas, media, roots.CONFIG_ROOT / "enterprise.env", roots.STATE_ROOT / "installation.json",
        roots.INSTALL_ROOT / "InfiniteCanvas.exe")}


def _database_snapshot(database):
    with contextlib.closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("FIXED_EXE_DATABASE_INVALID")
        users = conn.execute("SELECT id,username,password_hash,role,auth_version,is_active FROM users ORDER BY id").fetchall()
        canvases = conn.execute("SELECT * FROM user_canvas_map ORDER BY canvas_id").fetchall()
        flags = conn.execute("SELECT * FROM enterprise_feature_flags ORDER BY feature_key").fetchall()
        return users, canvases, flags


def _login_and_execute(gateway_port, job_id=None):
    import httpx
    base = f"http://127.0.0.1:{gateway_port}"
    with httpx.Client(base_url=base, trust_env=False, timeout=20) as client:
        result = client.post("/enterprise/login", json={"username": USERNAME, "password": PASSWORD},
                             headers={"Origin": base})
        if result.status_code != 200 or result.json().get("role") != "super_admin":
            raise RuntimeError("FIXED_EXE_REAL_LOGIN_FAILED")
        if client.get("/enterprise/admin").status_code != 200:
            raise RuntimeError("FIXED_EXE_ADMIN_READ_FAILED")
        if job_id:
            result = client.post(f"/enterprise/api/update-mvp/jobs/{job_id}/execute",
                                 json={"password": PASSWORD}, headers={"Origin": base})
            if result.status_code != 202 or result.json().get("state") != "UPDATING":
                raise RuntimeError("FIXED_EXE_REAL_EXECUTE_FAILED")


def _fault_listener(status_path, port, retain_until_terminal, evidence):
    deadline = time.monotonic() + 180
    while not ((s := _read_status(status_path)) and s.get("state") == "RESTARTING"):
        if time.monotonic() >= deadline:
            raise RuntimeError("FIXED_EXE_FAULT_RESTARTING_TIMED_OUT")
        if s and s.get("state") in TERMINAL:
            raise RuntimeError("FIXED_EXE_FAULT_RESTARTING_MISSED")
        time.sleep(0.02)
    with socket.socket() as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(2)
        _json_new(evidence / "fault-acquired.json", {"bound": True, "port": port})
        def done():
            s = _read_status(status_path) or {}
            phase = s.get("runtime_phases", {}).get("target_start", {})
            return s.get("state") in TERMINAL if retain_until_terminal else phase.get("launcher_exit_code", 0) != 0
        deadline = time.monotonic() + 180
        while not done():
            if time.monotonic() >= deadline:
                raise RuntimeError("FIXED_EXE_FAULT_OBSERVATION_TIMED_OUT")
            time.sleep(0.02)
    _json_new(evidence / "fault-released.json", {"released": True, "retained_until_terminal": retain_until_terminal})
    return 0


def _cleanup_install(install, evidence, ports):
    if not (install / "InfiniteCanvas.exe").is_file() or not (install / "state/current-release.json").is_file():
        return
    exit_code, status = _native(install, "status", evidence)
    if exit_code != 0:
        raise RuntimeError("FIXED_EXE_CLEANUP_IDENTITY_UNVERIFIED")
    identities = _runtime_identities(status)
    exit_code, result = _native(install, "stop", evidence)
    if exit_code != 0:
        raise RuntimeError("FIXED_EXE_CLEANUP_STOP_UNCONFIRMED")
    _wait(lambda: _owned_identities_absent(identities) and not any(_port_open(p) for p in ports),
          seconds=60, label="owned-cleanup")


def _scenario(args, scenario, local_base, nonce):
    from enterprise import fresh_install as fresh
    from enterprise.ops.update.mvp import UpdateMvpService, UpdateJobStore
    from enterprise.paths import PortableRootInputs, derive_portable_path_roots
    from enterprise.release.release_manifest_v2 import verify_materialized_release

    evidence = args.evidence_root / scenario
    evidence.mkdir(exist_ok=False)
    # Windows update preparation uses a nonce-bearing partial Release name;
    # keep the fixture install path short without overriding system policy.
    install = args.evidence_root / "f" / {"success": "s", "rollback": "r", "recovery-required": "g",
                                        "job-blocked": "b"}[scenario] / "i"
    ports = ()
    roots = None
    watcher = None
    prepared = None
    try:
        installed = fresh.install_greenfield(release_dir=args.source_build, install_root=install, username=USERNAME,
            password=PASSWORD, password_confirmation=PASSWORD, local_app_data_base=local_base,
            native_entry_dir=args.source_native_entry)
        roots = derive_portable_path_roots(PortableRootInputs(install, local_base), installed.release_id)
        ports = (_free_port(), _free_port())
        while ports[0] == ports[1]:
            ports = (_free_port(), _free_port())
        _configure(roots, *ports)
        business = _seed_business(roots, installed.first_user_id)
        database = _database_snapshot(roots.DATA_ROOT / "enterprise.db")
        start_exit, started = _native(install, "start", evidence)
        if start_exit != 0 or started.get("result") != "started":
            raise RuntimeError("FIXED_EXE_SOURCE_START_FAILED:" + str(started.get("code")))
        health_exit, health = _native(install, "health", evidence)
        status_exit, status = _native(install, "status", evidence)
        source_identities = _runtime_identities(status)
        if health_exit != 0 or status_exit != 0 or health.get("readiness", {}).get("ready") is not True or len(source_identities) != 3:
            raise RuntimeError("FIXED_EXE_SOURCE_HEALTH_INVALID")
        target = fresh.verify_release_assets(args.target_build)
        prepared = UpdateMvpService(roots).prepare_from_artifacts(actor_user_id=installed.first_user_id,
            manifest_path=target.manifest_path, archive_path=target.archive_path, inventory_path=target.inventory_path)
        store = UpdateJobStore(roots)
        status_path = store.job_root(prepared.job_id) / "status.json"
        if scenario not in {"success", "job-blocked"}:
            watcher = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--fault-listener",
                "--status-path", str(status_path), "--port", str(ports[1]), "--evidence-root", str(evidence),
                *( ["--retain-fault"] if scenario == "recovery-required" else [] )],
                env=_environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _login_and_execute(ports[1], prepared.job_id)
        terminal = _wait(lambda: (s if (s := _read_status(status_path)) and s.get("state") in TERMINAL else None),
                         seconds=300, label=scenario + "-terminal")
        # Retain observed failure evidence even when the expected scenario
        # fails. Fixture cleanup must not make a failed drill look unexecuted.
        _json_new(evidence / "observed-terminal.json", terminal)
        shutil.copyfile(store.job_root(prepared.job_id) / "events.jsonl", evidence / "events.jsonl")
        if watcher:
            watcher.wait(timeout=30)
            if watcher.returncode != 0 or not (evidence / "fault-acquired.json").exists():
                raise RuntimeError("FIXED_EXE_FAULT_NOT_EXECUTED")
        expected = {"success": "SUCCEEDED", "rollback": "ROLLED_BACK", "recovery-required": "RECOVERY_REQUIRED",
                    "job-blocked": "FAILED"}[scenario]
        if terminal["state"] != expected:
            raise RuntimeError("FIXED_EXE_UNEXPECTED_TERMINAL:" + terminal["state"])
        pointer = json.loads((roots.STATE_ROOT / "current-release.json").read_bytes())
        expected_id = prepared.source_release_id if scenario in {"rollback", "job-blocked"} else prepared.target_release_id
        if pointer["release_id"] != expected_id or (scenario != "job-blocked" and not _owned_identities_absent(source_identities)):
            raise RuntimeError("FIXED_EXE_POINTER_OR_SOURCE_EXIT_INVALID")
        _wait(lambda: not _update_worker_pids(roots.PYTHON_RUNTIME / "python.exe", prepared.job_id),
              seconds=60, label="detached-worker-exit")
        phases = terminal.get("runtime_phases", {})
        phase_set = {"target_start", "target_health"} if scenario == "success" else (
            {"target_start", "target_stop", "source_start", "source_health"} if scenario == "rollback" else (
                set() if scenario == "job-blocked" else {"target_start", "target_stop"}))
        if set(phases) != phase_set:
            raise RuntimeError("FIXED_EXE_PHASES_INVALID")
        if scenario == "recovery-required":
            if terminal.get("result_code") != "SYSTEM_UPDATE_TARGET_STOP_UNCONFIRMED" or store.pending_recovery_jobs() != [prepared.job_id]:
                raise RuntimeError("FIXED_EXE_RECOVERY_GATE_MISSING")
        else:
            exit_code, active_health = _native(install, "health", evidence)
            if exit_code != 0 or active_health.get("readiness", {}).get("ready") is not True:
                raise RuntimeError("FIXED_EXE_FINAL_HEALTH_INVALID")
            _login_and_execute(ports[1])
        if scenario == "job-blocked":
            if terminal.get("result_code") != "SYSTEM_UPDATE_HANDOFF_JOB_BLOCKED":
                raise RuntimeError("FIXED_EXE_JOB_GUARD_CODE_MISSING")
            exit_code, still_running = _native(install, "status", evidence)
            if exit_code != 0 or _runtime_identities(still_running) != source_identities:
                raise RuntimeError("FIXED_EXE_JOB_GUARD_STOPPED_SOURCE")
        if store.lock_path.exists() or _database_snapshot(roots.DATA_ROOT / "enterprise.db") != database:
            raise RuntimeError("FIXED_EXE_DATA_OR_LOCK_INVALID")
        if any((install / p).read_bytes() != value for p, value in business.items()):
            raise RuntimeError("FIXED_EXE_BUSINESS_NOT_RETAINED")
        for release_id in (prepared.source_release_id, prepared.target_release_id):
            app = roots.RELEASE_ROOT / release_id
            verify_materialized_release(app, inventory_path=app / "release-payload-inventory.json")
        _json_new(evidence / "terminal.json", terminal)
        return {"scenario": scenario, "state": expected, "source_release_id": prepared.source_release_id,
                "target_release_id": prepared.target_release_id, "fixed_exe": True, "real_http_execute": True,
                "detached_worker_exited": True, "source_processes_exited": scenario != "job-blocked",
                **({"source_stop_prevented": True, "source_healthy_after_guard": True} if scenario == "job-blocked" else {}),
                "business_identity_config_and_media_retained": True, "runtime_phases": phases,
                "automatic_source_recovery": scenario == "rollback", "production_touched": False}
    finally:
        if watcher and watcher.poll() is None:
            watcher.terminate()  # Only this script's exact owned fault listener.
            watcher.wait(timeout=10)
        _cleanup_install(install, evidence, ports)
        if prepared:
            _wait(lambda: not _update_worker_pids(roots.PYTHON_RUNTIME / "python.exe", prepared.job_id),
                  seconds=60, label="cleanup-worker-exit")
        for name in NAMES:
            _remove_owned_local_root(local_base / name, local_base, nonce)


def _validate_evidence_root(evidence_root, protected_roots):
    if not evidence_root.is_absolute() or evidence_root == Path(evidence_root.anchor):
        raise RuntimeError("FIXED_EXE_EVIDENCE_ROOT_INVALID")
    assert_no_reparse_ancestors(evidence_root, allow_missing=True)
    candidate = evidence_root.absolute()
    for root in protected_roots:
        root = root.absolute()
        if candidate == root or candidate in root.parents or root in candidate.parents:
            raise RuntimeError("FIXED_EXE_EVIDENCE_ROOT_OVERLAP")
    if evidence_root.exists():
        raise RuntimeError("FIXED_EXE_EVIDENCE_EXISTS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--run-all", action="store_true")
    modes.add_argument("--restricted-job-guard", action="store_true",
                       help="Negative real-EXE drill: unsafe Job handoff must fail before source shutdown")
    modes.add_argument("--fault-listener", action="store_true")
    parser.add_argument("--source-build", type=Path)
    parser.add_argument("--source-native-entry", type=Path)
    parser.add_argument("--target-build", type=Path)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--status-path", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--retain-fault", action="store_true")
    parser.add_argument("--preserve-existing-local-roots", action="store_true",
                        help="Explicit authorization to temporarily preserve verified-stopped history and restore it")
    args = parser.parse_args()
    if args.fault_listener:
        return _fault_listener(args.status_path, args.port, args.retain_fault, args.evidence_root)
    if os.name != "nt" or not all((args.source_build, args.source_native_entry, args.target_build)):
        raise RuntimeError("FIXED_EXE_DRILL_ARGUMENTS_INVALID")
    from enterprise.runtime.portable import windows_local_app_data_known_folder
    local_base = windows_local_app_data_known_folder()
    for path in (args.source_build, args.source_native_entry, args.target_build):
        assert_no_reparse_ancestors(path)
    _validate_evidence_root(args.evidence_root, (REPO, local_base, args.source_build,
                                               args.source_native_entry, args.target_build))
    args.evidence_root.mkdir(parents=True, exist_ok=False)
    # Reject unqualified inputs before temporarily moving any historical root.
    source_assets = _asset_view(args.source_build, args.evidence_root / "qualified-source")
    _asset_view(args.target_build, args.evidence_root / "qualified-target")
    from enterprise.install_entry import verify_entry_bundle
    source = source_assets.manifest.section("enterprise_source")
    verify_entry_bundle(args.source_native_entry, commit=str(source["commit"]), tree=str(source["tree"]))
    args.source_build = args.evidence_root / "qualified-source"
    args.target_build = args.evidence_root / "qualified-target"
    nonce = uuid.uuid4().hex
    results = []
    with preserved_local_roots(local_base, nonce, explicitly_authorized=args.preserve_existing_local_roots) as preservation:
        for scenario in (("job-blocked",) if args.restricted_job_guard else ("success", "rollback", "recovery-required")):
            _create_owned_local_roots(local_base, NAMES, nonce)
            results.append(_scenario(args, scenario, local_base, nonce))
    summary = {"schema_version": "fixed-exe-update-windows-drill-v1", "results": results,
               **preservation, "historical_roots_restored": True, "production_touched": False,
               "paid_provider_called": False, "gui_click_acceptance": False}
    _json_new(args.evidence_root / "SUMMARY.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "blocked", "code": str(exc).split(":", 1)[0]}))
        raise SystemExit(2)
