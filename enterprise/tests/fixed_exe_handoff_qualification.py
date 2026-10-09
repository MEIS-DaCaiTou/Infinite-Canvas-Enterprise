"""Opt-in Runner qualification; no application, data, or external Job changes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from enterprise.runtime.windows import current_job_diagnostics, process_in_any_job


def worker_flags(context):
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    limits = context.get("job_limit_flags")
    silent_only = (context.get("process_in_job") is True and type(limits) is int
                   and limits & 0x1000 and not limits & 0x0800)
    return flags if silent_only else flags | subprocess.CREATE_BREAKAWAY_FROM_JOB


def qualify_owned_child():
    context = current_job_diagnostics()
    flags = worker_flags(context)
    result = {"creation_context": context, "popen_creation_flags": flags,
              "qualified": False, "worker_stop_confirmed": False}
    process = None
    try:
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, shell=False, creationflags=flags)
        result["worker_in_job"] = process_in_any_job(process)
        result["qualified"] = result["worker_in_job"] is False
    except Exception as exc:
        result.update(error_type=type(exc).__name__, winerror=getattr(exc, "winerror", None))
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
                result["worker_stop_confirmed"] = process.poll() is not None
            except (OSError, subprocess.TimeoutExpired):
                result["qualified"] = False
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
        return 0 if result["qualified"] and result["worker_stop_confirmed"] else 2
    if args.output is None or args.output.exists():
        raise RuntimeError("NEW_QUALIFICATION_OUTPUT_REQUIRED")
    # Match the ordinary detached host context before the guarded worker.
    child = subprocess.run([sys.executable, "-B", "-m", "enterprise.tests.fixed_exe_handoff_qualification", "--supervisor-context"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    result = {"runner_context": current_job_diagnostics(), "child_exit_code": child.returncode,
              "qualified": False, "production_touched": False}
    try:
        result["handoff_context"] = json.loads(child.stdout)
        result["qualified"] = (child.returncode == 0 and result["handoff_context"]["qualified"] is True
                               and result["handoff_context"]["worker_stop_confirmed"] is True)
    except (ValueError, KeyError, TypeError):
        result["error"] = "QUALIFICATION_RESULT_UNVERIFIED"
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
