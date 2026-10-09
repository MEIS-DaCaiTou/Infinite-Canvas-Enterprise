"""One-shot portable update worker launched only by the owned supervisor."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source-pid", required=True, type=int)
    parser.add_argument("--source-created-at", required=True, type=int)
    parser.add_argument("--source-executable", required=True)
    return parser.parse_args()


def _emit_terminal_audit(plan: dict[str, object], result_code: str) -> None:
    """Emit only the bounded, non-secret terminal audit payload."""
    from enterprise import db as edb

    detail = {
        "job_id": plan.get("job_id"),
        "source_release_id": plan.get("source_release_id"),
        "target_release_id": plan.get("target_release_id"),
        "result_code": result_code,
    }
    edb.log_action(
        str(plan.get("actor_user_id") or ""),
        "system_update_failed",
        json.dumps(detail, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


def _finalize_terminal_failure(roots: object, job_id: str, result_code: str,
                               *, handoff_cleanup_unconfirmed: bool = False) -> bool:
    """Persist terminal evidence and release only this job's reservation.

    The existing lock adoption path verifies both the canonical lock payload
    and the open-file identity.  A foreign, replaced, malformed, or missing
    lock is therefore never removed here.
    """
    from enterprise.ops.update.mvp import TERMINAL_STATES, UpdateJobStore
    from enterprise.runtime.handoff_commit import HandoffCommitGate

    store = UpdateJobStore(roots)
    released = False
    try:
        # The worker is also a cancellation writer. Serialize its fresh read,
        # terminal publication and any unlock with source acceptance/API timeout.
        with HandoffCommitGate(job_id):
            plan = store.read_plan(job_id)
            actor = str(plan.get("actor_user_id") or "")
            current_state = str(store.read_status(job_id).get("state") or "")
            if current_state in TERMINAL_STATES:
                # A late worker cannot clear an already persisted safety block.
                return False
            uncertain_database_or_pointer = current_state in {"MIGRATING", "RESTARTING", "VERIFYING"}
            uncertain = uncertain_database_or_pointer or handoff_cleanup_unconfirmed
            terminal_state = "RECOVERY_REQUIRED" if uncertain else "FAILED"
            store.write_status(
                job_id,
                terminal_state,
                actor_user_id=actor,
                result_code=result_code,
                source_release_id=plan.get("source_release_id"),
                target_release_id=plan.get("target_release_id"),
                **({"recovery_required": True, "interrupted_state": current_state} if uncertain else {}),
            )
            store.append_event(job_id, terminal_state, result_code)
            if not uncertain:
                try:
                    handle = store.acquire_execution_lock(job_id)
                    store.release_execution_lock(handle, job_id)
                    released = not store.lock_path.exists()
                except Exception:
                    released = False  # A foreign/unconfirmed reservation stays intact.
    except Exception:
        return False  # Unconfirmed gate/state I/O may never authorize an unlock.
    audit_written = True
    try:
        _emit_terminal_audit(plan, result_code)
    except Exception:  # audit failure must not strand the reservation
        audit_written = False
    return released and audit_written


def _wait_source_stopped(source_lease, supervisor_lock: Path, timeout_seconds: float = 90) -> bool:
    """Require original process exit AND lock absence before touching data."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        exited = source_lease.wait_for_exit(0.1)
        if exited and not supervisor_lock.exists():
            return True
        if exited:
            time.sleep(0.05)  # A signalled handle otherwise makes this a busy loop.
    return False


class _SilentStdout:
    """Discard later import prints without retaining a parent-owned IPC pipe."""
    encoding = "utf-8"

    def write(self, value):
        return len(value)

    def flush(self):
        pass

    def isatty(self):
        return False


def main() -> int:
    arguments = _arguments()
    roots = None
    job_id = ""
    source_lease = None
    readiness_sent = False
    try:
        from enterprise.paths import PortableRootInputs, derive_portable_path_roots, install_path_roots_for_process
        from enterprise.runtime.portable import windows_local_app_data_known_folder

        install_root = APP_ROOT.parent.parent
        roots = derive_portable_path_roots(
            PortableRootInputs(install_root, windows_local_app_data_known_folder()),
            APP_ROOT.name,
        )
        install_path_roots_for_process(roots)
        from enterprise.config import DB_PATH
        from enterprise.ops.update.mvp import UpdateJobStore, execute_update_job
        from enterprise.runtime.handoff_lifecycle import prepare_worker_ready

        job_id = UpdateJobStore.validate_job_id(arguments.job_id)
        # Hold the verified original source process handle before announcing
        # readiness. A disappearing/replaced lock alone never proves exit.
        source_lease, readiness = prepare_worker_ready(
            job_id, arguments.source_pid, arguments.source_created_at, arguments.source_executable)
        print(json.dumps(readiness, sort_keys=True), flush=True)
        readiness_sent = True
        # The source owns the read end and will exit. Do not retain that pipe
        # as a later application logging sink or depend on its continued life.
        sys.stdout = _SilentStdout()
        supervisor_lock = roots.RUNTIME_ROOT / "runtime-supervisor.lock"
        if not _wait_source_stopped(source_lease, supervisor_lock):
            _finalize_terminal_failure(roots, job_id, "SYSTEM_UPDATE_SOURCE_STOP_TIMEOUT")
            return 2
        status = UpdateJobStore(roots).read_status(job_id)
        if status.get("state") != "UPDATING" or status.get("handoff_committed") is not True:
            return 2  # Rejected/late worker cannot overwrite a recovery block.
        result = execute_update_job(roots, job_id, database_path=Path(DB_PATH))
        try:
            from enterprise import db as edb

            plan = UpdateJobStore(roots).read_plan(job_id)
            status = UpdateJobStore(roots).read_status(job_id)
            action = {
                "SUCCEEDED": "system_update_succeeded",
                "ROLLED_BACK": "system_update_rolled_back",
                "FAILED": "system_update_failed",
                "RECOVERY_REQUIRED": "system_update_recovery_required",
            }.get(str(status.get("state")), "system_update_failed")
            detail = {
                "job_id": job_id,
                "source_release_id": plan.get("source_release_id"),
                "target_release_id": plan.get("target_release_id"),
                "result_code": status.get("result_code"),
            }
            edb.log_action(str(plan.get("actor_user_id") or ""), action, json.dumps(detail, ensure_ascii=False))
        except Exception:
            pass
        return result
    except Exception:
        if roots is not None and job_id:
            try:
                _finalize_terminal_failure(roots, job_id, "SYSTEM_UPDATE_WORKER_FAILED",
                                           handoff_cleanup_unconfirmed=not readiness_sent)
            except Exception:
                pass
        return 2
    finally:
        if source_lease is not None:
            source_lease.close()


if __name__ == "__main__":
    raise SystemExit(main())
