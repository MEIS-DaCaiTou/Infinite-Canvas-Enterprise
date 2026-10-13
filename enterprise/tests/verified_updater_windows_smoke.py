"""Opt-in target-engine handoff drills using owned synthetic Windows installs.

Reuse the qualified fixed-entry/data-preservation harness. No public Release,
customer device, paid provider or installer GUI acceptance is involved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from enterprise.tests import fixed_exe_update_windows_smoke as fixed
from enterprise.runtime.ownership import process_identity


def scenario(args, name, local_base, nonce):
    from enterprise import fresh_install as fresh
    from enterprise.ops.update.mvp import UpdateMvpService, UpdateJobStore
    from enterprise.ops.update.updater import WORKER_PATH, UpdaterExecutionError
    from enterprise.paths import PortableRootInputs, derive_portable_path_roots
    from enterprise.release.release_manifest_v2 import verify_materialized_release

    evidence = args.evidence_root / name
    evidence.mkdir(exist_ok=False)
    install = args.evidence_root / "f" / {"success": "s", "rollback": "r", "tampered": "t", "incompatible": "p"}[name] / "i"
    ports, roots, prepared, watcher = (), None, None, None
    observations = []
    done = threading.Event()
    observer = None
    original_worker = None
    target_python = None
    try:
        installed = fresh.install_greenfield(release_dir=args.source_build, install_root=install,
            username=fixed.USERNAME, password=fixed.PASSWORD, password_confirmation=fixed.PASSWORD,
            local_app_data_base=local_base, native_entry_dir=args.source_native_entry)
        roots = derive_portable_path_roots(PortableRootInputs(install, local_base), installed.release_id)
        ports = (fixed._free_port(), fixed._free_port())
        while ports[0] == ports[1]:
            ports = (fixed._free_port(), fixed._free_port())
        fixed._configure(roots, *ports)
        business = fixed._seed_business(roots, installed.first_user_id)
        database = fixed._database_snapshot(roots.DATA_ROOT / "enterprise.db")
        fixed._json_new(evidence / "data-preservation-baseline.json", {
            "protected_files_sha256": {path: hashlib.sha256(value).hexdigest() for path, value in business.items()},
            "database_snapshot_sha256": hashlib.sha256(json.dumps(database, sort_keys=True).encode()).hexdigest(),
        })
        exit_code, started = fixed._native(install, "start", evidence)
        if exit_code != 0 or started.get("result") != "started":
            raise RuntimeError("C5_SOURCE_START_FAILED")
        exit_code, status = fixed._native(install, "status", evidence)
        source_processes = fixed._runtime_identities(status)
        if exit_code != 0 or len(source_processes) != 3:
            raise RuntimeError("C5_SOURCE_IDENTITY_INVALID")
        source_pointer = (roots.STATE_ROOT / "current-release.json").read_bytes()
        target = fresh.verify_release_assets(args.incompatible_build if name == "incompatible" else args.target_build)
        service = UpdateMvpService(roots)
        if name == "incompatible":
            try:
                service.prepare_from_artifacts(actor_user_id=installed.first_user_id,
                    manifest_path=target.manifest_path, archive_path=target.archive_path, inventory_path=target.inventory_path)
            except UpdaterExecutionError as exc:
                if exc.code != "SYSTEM_UPDATE_UPDATER_INCOMPATIBLE":
                    raise
            else:
                raise RuntimeError("C5_INCOMPATIBLE_NOT_REFUSED")
            terminal = {"state": "FAILED", "result_code": "SYSTEM_UPDATE_UPDATER_INCOMPATIBLE"}
        else:
            prepared = service.prepare_from_artifacts(actor_user_id=installed.first_user_id,
                manifest_path=target.manifest_path, archive_path=target.archive_path, inventory_path=target.inventory_path)
            store = UpdateJobStore(roots)
            status_path = store.job_root(prepared.job_id) / "status.json"
            target_root = roots.RELEASE_ROOT / prepared.target_release_id
            target_python = target_root / "python/python.exe"
            if prepared.updater_execution["updater_contract"] != args.expected_target_contract:
                raise RuntimeError("C5_EXPECTED_ENGINE_MISMATCH")
            if name == "tampered":
                worker = target_root / WORKER_PATH
                original_worker = (worker, worker.read_bytes())
                worker.write_bytes(original_worker[1] + b"\n# C5 owned post-READY tamper\n")
            def observe():
                while not done.is_set():
                    for pid in fixed._update_worker_pids(target_python, prepared.job_id):
                        identity = process_identity(pid)
                        if identity is not None and identity.executable.casefold() == str(target_python).casefold():
                            observations.append({"pid": pid, "created_at": identity.created_at,
                                                 "executable": identity.executable})
                    done.wait(0.2)
            observer = threading.Thread(target=observe, daemon=True)
            observer.start()
            if name == "rollback":
                watcher = subprocess.Popen([sys.executable, str(Path(fixed.__file__)), "--fault-listener",
                    "--status-path", str(status_path), "--port", str(ports[1]), "--evidence-root", str(evidence)],
                    env=fixed._environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            started_at = time.monotonic()
            fixed._login_and_execute(ports[1], prepared.job_id)
            terminal = fixed._wait(lambda: (s if (s := fixed._read_status(status_path)) and s.get("state") in fixed.TERMINAL else None),
                                   seconds=300, label="C5-" + name)
            elapsed = time.monotonic() - started_at
            done.set()
            observer.join(timeout=20)
            if observer.is_alive():
                raise RuntimeError("C5_OBSERVER_NOT_REAPED")
            fixed._json_new(evidence / "terminal.json", terminal)
            fixed._json_new(evidence / "worker-observations.json", observations)
            expected = {"success": "SUCCEEDED", "rollback": "ROLLED_BACK", "tampered": "FAILED"}[name]
            if terminal["state"] != expected:
                raise RuntimeError("C5_UNEXPECTED_TERMINAL:" + terminal["state"])
            if name == "tampered":
                if observations or terminal["result_code"] != "SYSTEM_UPDATE_UPDATER_UNVERIFIED":
                    raise RuntimeError("C5_TAMPER_NOT_PRESTOP_REFUSED")
            elif not observations or terminal["updater_execution"] != prepared.updater_execution:
                raise RuntimeError("C5_TARGET_ENGINE_NOT_OBSERVED")
            fixed._wait(lambda: not fixed._update_worker_pids(target_python, prepared.job_id), seconds=60, label="C5-worker-exit")
            if store.lock_path.exists():
                raise RuntimeError("C5_RESERVATION_NOT_RELEASED")
            if name == "rollback":
                fault = json.loads((evidence / "fault-acquired.json").read_bytes())
                if fault.get("bound") is not True or fault.get("port") != ports[1]:
                    raise RuntimeError("C5_ROLLBACK_FAULT_NOT_OBSERVED")
        pointer = json.loads((roots.STATE_ROOT / "current-release.json").read_bytes())
        if name in {"tampered", "incompatible"}:
            exit_code, active = fixed._native(install, "status", evidence)
            if (exit_code != 0 or fixed._runtime_identities(active) != source_processes
                    or (roots.STATE_ROOT / "current-release.json").read_bytes() != source_pointer):
                raise RuntimeError("C5_REFUSAL_STOPPED_SOURCE")
        else:
            expected_id = prepared.target_release_id if name == "success" else prepared.source_release_id
            if pointer["release_id"] != expected_id or not fixed._owned_identities_absent(source_processes):
                raise RuntimeError("C5_POINTER_OR_SOURCE_EXIT_INVALID")
        exit_code, health = fixed._native(install, "health", evidence)
        if exit_code != 0 or health.get("readiness", {}).get("ready") is not True:
            raise RuntimeError("C5_FINAL_HEALTH_INVALID")
        if (fixed._database_snapshot(roots.DATA_ROOT / "enterprise.db") != database
                or any((install / path).read_bytes() != value for path, value in business.items())):
            raise RuntimeError("C5_CUSTOMER_DATA_CHANGED")
        if original_worker is not None:
            original_worker[0].write_bytes(original_worker[1])
            original_worker = None
        for release_id in ({prepared.source_release_id, prepared.target_release_id} if prepared else {installed.release_id}):
            app_root = roots.RELEASE_ROOT / release_id
            verify_materialized_release(app_root, inventory_path=app_root / "release-payload-inventory.json")
        result = {"scenario": name, "state": terminal["state"], "result_code": terminal["result_code"],
                  "target_worker_observed": bool(observations), "source_stop_prevented": name in {"tampered", "incompatible"},
                  "source_recovered": name == "rollback", "business_data_retained": True,
                  "final_health_passed": True, "fixed_entry": True, "gui_acceptance": False,
                  **({"elapsed_seconds": round(elapsed, 3), "job_id": prepared.job_id,
                      "updater_execution": prepared.updater_execution} if prepared else {})}
        fixed._json_new(evidence / "result.json", result)
        return result
    finally:
        done.set()
        if observer is not None:
            observer.join(timeout=20)
        if watcher and watcher.poll() is None:
            watcher.terminate()
            watcher.wait(timeout=10)
        if original_worker is not None:
            original_worker[0].write_bytes(original_worker[1])  # Only the exact owned tamper fixture.
        fixed._cleanup_install(install, evidence, ports)
        if prepared and target_python is not None:
            fixed._wait(lambda: not fixed._update_worker_pids(target_python, prepared.job_id), seconds=60, label="C5-cleanup-worker")
        for local_name in fixed.NAMES:
            fixed._remove_owned_local_root(local_base / local_name, local_base, nonce)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-build", "source-native-entry", "target-build", "incompatible-build", "evidence-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-target-contract", type=int, default=5)
    parser.add_argument("--scenarios", nargs="+", choices=("success", "rollback", "tampered", "incompatible"),
                        default=("success", "rollback", "tampered", "incompatible"))
    parser.add_argument("--preserve-existing-local-roots", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("C5_WINDOWS_REQUIRED")
    from enterprise.runtime.portable import windows_local_app_data_known_folder
    from enterprise.install_entry import verify_entry_bundle
    local_base = windows_local_app_data_known_folder()
    fixed._validate_evidence_root(args.evidence_root, (REPO, local_base, args.source_build,
        args.source_native_entry, args.target_build, args.incompatible_build))
    args.evidence_root.mkdir(parents=True, exist_ok=False)
    from enterprise.tests.fixed_exe_handoff_qualification import qualified_result
    # Qualify the driver context before any historical roots are moved or a
    # synthetic service is installed. A restrictive Job is a safety refusal,
    # never a reason to weaken application handoff or repeat a whole drill.
    qualification_path = args.evidence_root / "driver-qualification.json"
    result = subprocess.run([sys.executable, "-I", "-B",
        str(REPO / "enterprise/tests/fixed_exe_handoff_qualification.py"), "--output", str(qualification_path)],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    if result.returncode != 0 or not qualified_result(json.loads(qualification_path.read_bytes())):
        raise RuntimeError("C5_DRIVER_HANDOFF_CONTEXT_UNQUALIFIED")
    for key in ("source_build", "target_build", "incompatible_build"):
        destination = args.evidence_root / key.replace("_", "-")
        assets = fixed._asset_view(getattr(args, key), destination)
        if key == "source_build":
            identity = assets.manifest.section("enterprise_source")
            verify_entry_bundle(args.source_native_entry, commit=identity["commit"], tree=identity["tree"])
        setattr(args, key, destination)
    nonce = uuid.uuid4().hex
    results = []
    with fixed.preserved_local_roots(local_base, nonce, explicitly_authorized=args.preserve_existing_local_roots) as preservation:
        for name in args.scenarios:
            fixed._create_owned_local_roots(local_base, fixed.NAMES, nonce)
            results.append(scenario(args, name, local_base, nonce))
    summary = {"schema_version": "verified-updater-windows-drill-v1", "results": results, **preservation,
               "driver_context_qualified": True,
               "historical_roots_restored": True, "production_touched": False, "release_published": False,
               "paid_provider_called": False, "gui_acceptance": False}
    fixed._json_new(args.evidence_root / "SUMMARY.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
