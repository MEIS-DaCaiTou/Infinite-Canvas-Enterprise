"""Opt-in handoff qualification; no application, data, or external Job changes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from enterprise.runtime.ownership import ProcessIdentity, process_identity
from enterprise.runtime.windows import JobObjectError, ProcessJob, current_job_diagnostics, process_in_any_job

SCHEMA = "fixed-exe-handoff-qualification-v2"
CHILD_SCHEMA = "fixed-exe-handoff-child-qualification-v2"
REQUIRED_EVIDENCE = (
    "source_identity_verified", "worker_identity_verified", "source_job_query_ok", "worker_any_job_query_ok",
    "worker_not_in_source_job", "source_process_lease_opened", "host_creation_verified",
    "host_cleanup_confirmed", "worker_stop_confirmed", "source_job_closed",
)


def worker_flags(context):
    from enterprise.runtime.handoff_lifecycle import worker_creation_flags
    return worker_creation_flags(context)


def _read_ready(process, job_id, source, worker):
    from enterprise.runtime.handoff_lifecycle import read_worker_ready
    return read_worker_ready(process, job_id, source, worker, timeout_seconds=5)


def _context_verified(context):
    return (type(context) is dict and context.get("job_query_ok") is True
            and type(context.get("process_in_job")) is bool
            and (context["process_in_job"] is False
                 or type(context.get("job_limit_flags")) is int and context["job_limit_flags"] >= 0))


def _identity_verified(identity, pid):
    return (isinstance(identity, ProcessIdentity) and identity.pid == pid
            and type(identity.pid) is int and identity.pid > 0
            and type(identity.created_at) is int and identity.created_at > 0
            and isinstance(identity.executable, str)
            and os.path.normcase(identity.executable) == os.path.normcase(sys.executable))


def qualified_owned_result(result):
    if (type(result) is not dict or result.get("schema_version") != CHILD_SCHEMA
            or result.get("qualified") is not True or result.get("production_touched") is not False
            or not all(result.get(field) is True for field in REQUIRED_EVIDENCE)
            or not _context_verified(result.get("creation_context"))):
        return False
    return all(type(result.get(field)) is int and result[field] > 0
               for field in ("source_pid", "source_created_at", "worker_pid", "worker_created_at"))


def qualified_result(result):
    """The driver requires bound evidence, never an unversioned true label."""
    return (type(result) is dict and result.get("schema_version") == SCHEMA
            and result.get("qualified") is True and result.get("production_touched") is False
            and type(result.get("child_exit_code")) is int and result["child_exit_code"] == 0
            and qualified_owned_result(result.get("handoff_context")))


def qualify_owned_child():
    context = current_job_diagnostics()
    result = {"schema_version": CHILD_SCHEMA, "creation_context": context,
              "qualified": False, "production_touched": False,
              **{field: False for field in REQUIRED_EVIDENCE}}
    process = None
    owned_job = None
    try:
        if not _context_verified(context):
            raise RuntimeError("SOURCE_JOB_CONTEXT_UNVERIFIED")
        source = process_identity(os.getpid())
        if not _identity_verified(source, os.getpid()):
            raise RuntimeError("SOURCE_IDENTITY_UNVERIFIED")
        result.update(source_identity_verified=True, source_pid=source.pid, source_created_at=source.created_at)
        flags = worker_flags(context)
        result["popen_creation_flags"] = flags
        owned_job = ProcessJob()
        job_id = uuid.uuid4().hex
        helper = Path(__file__).resolve().parents[1] / "runtime" / "handoff_lifecycle.py"
        process = subprocess.Popen([sys.executable, "-I", "-B", str(helper), "--worker-ready",
            "--job-id", job_id, "--source-pid", str(source.pid),
            "--source-created-at", str(source.created_at), "--source-executable", source.executable],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            close_fds=True, shell=False, creationflags=flags)
        worker = process_identity(process.pid)
        if not _identity_verified(worker, process.pid) or process.poll() is not None:
            raise RuntimeError("WORKER_IDENTITY_UNVERIFIED")
        result.update(worker_identity_verified=True, worker_pid=worker.pid, worker_created_at=worker.created_at)
        in_source_job = owned_job.contains_process(process)
        if type(in_source_job) is not bool:
            raise RuntimeError("SOURCE_JOB_MEMBERSHIP_UNVERIFIED")
        result["source_job_query_ok"] = True
        result["worker_not_in_source_job"] = in_source_job is False
        if in_source_job:
            raise RuntimeError("WORKER_IN_SOURCE_JOB")
        # Ambient membership true is not a blanket refusal, but its original-
        # handle query must succeed, consistently with the product guard.
        ambient_member = process_in_any_job(process)
        if type(ambient_member) is not bool:
            raise JobObjectError("owned ambient membership is unknown")
        result["worker_any_job_query_ok"] = True
        result["worker_in_job"] = ambient_member
        ready = _read_ready(process, job_id, source, worker)
        failure = getattr(process, "handoff_ready_failure", None)
        if type(failure) is dict:
            result["worker_ready_failure"] = failure
        if ready is not True or process.poll() is not None:
            raise RuntimeError("WORKER_READY_UNVERIFIED")
        result.update(source_process_lease_opened=True, host_creation_verified=True,
                      host_cleanup_confirmed=True, qualified=True)
    except Exception as exc:
        result.update(qualified=False, error_type=type(exc).__name__, winerror=getattr(exc, "winerror", None))
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
                result["worker_stop_confirmed"] = process.poll() is not None
                if not result["worker_stop_confirmed"]:
                    result["qualified"] = False
            except (OSError, subprocess.TimeoutExpired):
                result["qualified"] = False
            finally:
                if process.stdout is not None:
                    try:
                        process.stdout.close()
                    except OSError:
                        result["qualified"] = False
        if owned_job is not None:
            try:
                owned_job.close()
                result["source_job_closed"] = True
            except (OSError, JobObjectError):
                result["qualified"] = False
    result["qualified"] = qualified_owned_result(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supervisor-context", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("WINDOWS_REQUIRED")
    if args.supervisor_context:
        result = qualify_owned_child()
        print(json.dumps(result, sort_keys=True))
        return 0 if qualified_owned_result(result) else 2
    if args.output is None or args.output.exists():
        raise RuntimeError("NEW_QUALIFICATION_OUTPUT_REQUIRED")
    child = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--supervisor-context"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    result = {"schema_version": SCHEMA, "runner_context": current_job_diagnostics(),
              "child_exit_code": child.returncode, "qualified": False, "production_touched": False}
    try:
        if len(child.stdout.encode("utf-8")) > 16384:
            raise ValueError("QUALIFICATION_RESULT_TOO_LARGE")
        result["handoff_context"] = json.loads(child.stdout)
        result["qualified"] = child.returncode == 0 and qualified_owned_result(result["handoff_context"])
    except (ValueError, KeyError, TypeError):
        result["error"] = "QUALIFICATION_RESULT_UNVERIFIED"
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True)
    print(json.dumps(result, sort_keys=True))
    return 0 if qualified_result(result) else 2


if __name__ == "__main__":
    raise SystemExit(main())
