"""One-shot portable update worker launched only by the owned supervisor."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--job-id", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    roots = None
    job_id = ""
    try:
        from enterprise.paths import PortableRootInputs, derive_portable_path_roots, install_path_roots_for_process
        from enterprise.runtime.portable import windows_local_app_data_known_folder

        install_root = APP_ROOT.parent.parent
        roots = derive_portable_path_roots(
            PortableRootInputs(install_root, windows_local_app_data_known_folder()),
            APP_ROOT.name,
        )
        install_path_roots_for_process(roots)
        from enterprise.ops.update.mvp import UpdateJobStore, execute_update_job

        job_id = UpdateJobStore.validate_job_id(arguments.job_id)
        deadline = time.monotonic() + 90
        supervisor_lock = roots.RUNTIME_ROOT / "runtime-supervisor.lock"
        while supervisor_lock.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if supervisor_lock.exists():
            store = UpdateJobStore(roots)
            plan = store.read_plan(job_id)
            store.write_status(
                job_id,
                "FAILED",
                actor_user_id=str(plan.get("actor_user_id") or ""),
                result_code="SYSTEM_UPDATE_SOURCE_STOP_TIMEOUT",
                source_release_id=plan.get("source_release_id"),
                target_release_id=plan.get("target_release_id"),
            )
            return 2
        result = execute_update_job(roots, job_id)
        try:
            from enterprise import db as edb

            plan = UpdateJobStore(roots).read_plan(job_id)
            status = UpdateJobStore(roots).read_status(job_id)
            action = {
                "SUCCEEDED": "system_update_succeeded",
                "ROLLED_BACK": "system_update_rolled_back",
                "FAILED": "system_update_failed",
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
                from enterprise.ops.update.mvp import UpdateJobStore

                store = UpdateJobStore(roots)
                plan = store.read_plan(job_id)
                store.write_status(
                    job_id,
                    "FAILED",
                    actor_user_id=str(plan.get("actor_user_id") or ""),
                    result_code="SYSTEM_UPDATE_WORKER_FAILED",
                    source_release_id=plan.get("source_release_id"),
                    target_release_id=plan.get("target_release_id"),
                )
                store.append_event(job_id, "FAILED", "SYSTEM_UPDATE_WORKER_FAILED")
                lock = store.acquire_execution_lock(job_id)
                store.release_execution_lock(lock, job_id)
            except Exception:
                pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
