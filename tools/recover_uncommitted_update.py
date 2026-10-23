"""Explicit local recovery of an uncommitted first-hop update; never upgrade.

Run with the installed source Python. Imports reuse that installation's recovery,
audit, file ownership and sequence-stop implementation without changing payload.
Default invocation only checks; --recover additionally requires admin password.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys


def inspect_uncommitted(roots, job_id):
    from enterprise.ops.update import mvp, sequence
    from enterprise.ops.update.updater import select_verified_updater, plan_sha256
    from enterprise.release.current_release import read_current_release_result_from_state_root
    from enterprise.path_safety import lexical_path_state

    store = mvp.UpdateJobStore(roots)
    plan, status = store.read_plan(job_id), store.read_status(job_id)
    def reject():
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_RECOVERY_STATE_UNVERIFIED", status_code=409)
    if (status.get("state") not in {"RECOVERY_REQUIRED", "RECOVERY_CLEARED"}
            or status.get("handoff_committed") is not None
            or status.get("runtime_phases")
            or (status["state"] == "RECOVERY_REQUIRED"
                and status.get("actor_user_id") != plan.get("actor_user_id"))
            or status.get("plan_sha256") != plan_sha256(plan)
            or plan.get("database_update", {}).get("mode") != "same-schema-no-migration"
            or lexical_path_state(roots.STATE_ROOT / "install-upgrade-active.json") != "missing"
            or lexical_path_state(store.job_root(job_id) / "database-result.json") != "missing"):
        reject()
    if (status["state"] == "RECOVERY_REQUIRED"
            and status.get("result_code") != "SYSTEM_UPDATE_HANDOFF_CLEANUP_UNCONFIRMED"):
        reject()
    pointer = read_current_release_result_from_state_root(roots.STATE_ROOT)
    if (pointer.release.release_id != plan.get("source_release_id")
            or pointer.release.manifest_sha256 != plan.get("source_manifest_sha256")
            or pointer.raw_sha256 != plan.get("source_pointer_sha256")):
        reject()
    selected = select_verified_updater(roots, plan, status)
    if selected is None or selected.readiness_binding.get("updater_contract") != 4:
        reject()
    root_plan, path, directory, _ = sequence._root_plan(roots, job_id)
    if root_plan != plan or sequence._checkpoints(roots, job_id, plan, path, directory):
        reject()
    state, _ = sequence.files._read(directory / "state.json")
    if state.get("current_job_id") != job_id or state.get("completed_hops") != 0:
        reject()
    if lexical_path_state(roots.STATE_ROOT / sequence.ACTIVE_NAME) == "missing":
        if (status["state"] != "RECOVERY_CLEARED"
                or state.get("result_code") != "SYSTEM_UPDATE_SEQUENCE_STOPPED"):
            reject()
    else:
        sequence._assert_active(roots, job_id, plan, directory)
    if lexical_path_state(store.lock_path) != "missing":
        lock = mvp._bounded_json(store.lock_path, 16384,
            missing="SYSTEM_UPDATE_LOCK_MISSING", invalid="SYSTEM_UPDATE_LOCK_INVALID")
        if lock.get("schema_version") != mvp.LOCK_SCHEMA or lock.get("job_id") != job_id:
            reject()
    return store, plan, status


def check(roots, job_id, *, launcher=None):
    from enterprise.ops.update import recovery
    from enterprise.runtime.handoff_commit import HandoffCommitGate
    with HandoffCommitGate(job_id):
        store, plan, status = inspect_uncommitted(roots, job_id)
        if status["state"] == "RECOVERY_CLEARED":
            store.assert_no_unresolved_recovery()
            return {"current_release_id": plan["source_release_id"], "state": status["state"]}
        return recovery.assess_recovery(roots, job_id,
            database_path=roots.DATA_ROOT / "enterprise.db", lock_held=True,
            **({"launcher": launcher} if launcher else {}))


def recover(roots, job_id, actor_user_id, *, launcher=None):
    from enterprise.ops.update import recovery, sequence
    from enterprise.runtime.handoff_commit import HandoffCommitGate
    kwargs = {"launcher": launcher} if launcher else {}
    with HandoffCommitGate(job_id):
        store, plan, status = inspect_uncommitted(roots, job_id)
        if status["state"] == "RECOVERY_REQUIRED":
            handle = None
            try:
                # The verified worker cannot execute after RECOVERY_REQUIRED;
                # the same commit gate also excludes a late source acceptance.
                if store.lock_path.exists():
                    handle = store.acquire_execution_lock(job_id)
                report = recovery.assess_recovery(roots, job_id,
                    database_path=roots.DATA_ROOT / "enterprise.db", lock_held=True, **kwargs)
                if handle is not None:
                    store.append_event(job_id, "RECOVERY_REQUIRED", "SYSTEM_UPDATE_HANDOFF_RESERVATION_RELEASED",
                        actor_user_id=actor_user_id, assessment_sha256=report["assessment_sha256"])
                    store.release_execution_lock(handle, job_id)
                    handle = None
            finally:
                if handle is not None:
                    handle.close()  # Failed checks retain the reservation.
            recovery.clear_recovery(roots, job_id, database_path=roots.DATA_ROOT / "enterprise.db",
                actor_user_id=actor_user_id, expected_release_id=report["current_release_id"],
                expected_assessment_sha256=report["assessment_sha256"],
                manual_evidence_note="Explicit local recovery: verified uncommitted first hop, original source and database healthy.",
                **kwargs)
        else:
            store.assert_no_unresolved_recovery()
        # Reuse original ownership, current DB checks, native tool restore and
        # sequence-stop; never unlink the maintenance marker directly.
        if (roots.STATE_ROOT / sequence.ACTIVE_NAME).exists():
            sequence.stop_sequence(roots, job_id, **kwargs)
    return {"recovered": True, "release_id": plan["source_release_id"], "upgrade_executed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    root = args.install_root.absolute()
    pointer = json.loads((root / "state/current-release.json").read_bytes())
    release = pointer["release_id"]
    if not isinstance(release, str) or Path(release).name != release or release in {".", ".."}:
        raise ValueError("Invalid installed release")
    app = root / "releases" / release
    if os.path.normcase(sys.executable) != os.path.normcase(str(app / "python/python.exe")):
        raise ValueError("Run with this installation's source Python")
    sys.path.insert(0, str(app))
    from enterprise.paths import PortableRootInputs, derive_portable_path_roots, install_path_roots_for_process
    from enterprise.runtime.portable import windows_local_app_data_known_folder
    roots = derive_portable_path_roots(PortableRootInputs(root, windows_local_app_data_known_folder()), release)
    install_path_roots_for_process(roots)
    report = check(roots, args.job_id)
    print(json.dumps({"check": "passed", "current_release_id": report["current_release_id"]}))
    if not args.recover:
        return
    from enterprise import db, config
    store, plan, _ = inspect_uncommitted(roots, args.job_id)
    password = getpass.getpass("请输入原升级超级管理员的密码（输入不显示）: ")
    actor = db.get_user_by_id(plan["actor_user_id"])
    valid = (actor and actor.get("is_active") is True and actor.get("role") == "super_admin"
             and config.ENTERPRISE_UPDATE_ENABLED and db.can_use_feature(actor, "system_update")
             and db.verify_password(password, actor.get("password_hash", "")))
    del password
    if not valid:
        raise ValueError("Super administrator confirmation failed")
    result = recover(roots, args.job_id, actor["id"])
    print(json.dumps(result))
    print("已结束未完成的升级并保留原版本。请刷新画布页面；本工具没有执行升级。")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"recovered": False, "code": getattr(exc, "code", type(exc).__name__)}))
        sys.exit(1)
