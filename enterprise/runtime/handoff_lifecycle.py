"""Bounded, application-free readiness handshake for a Windows handoff worker.

An inherited Job is diagnostic evidence, not a blanket refusal. Readiness instead
requires an original source-process lease and the same two creation contexts used
by launcher -> service host. This does not prove application/version compatibility.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from ctypes import wintypes

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from enterprise.runtime.ownership import ProcessIdentity, process_identity
from enterprise.runtime.windows import JobObjectError, ProcessJob, current_job_diagnostics

READY_SCHEMA = "runtime-handoff-ready-v1"
FAILURE_SCHEMA = "runtime-handoff-rejected-v1"
_FAILURE_STAGES = frozenset({
    "worker_job_query", "source_lease", "worker_identity", "probe_launcher_create",
    "probe_host_create", "probe_host_assign", "probe_host_identity", "probe_host_job",
    "probe_host_result", "probe_host_registration", "probe_host_lease", "probe_result",
    "probe_cleanup", "source_liveness", "readiness", "launcher_probe", "host_probe",
})
_MAX_LINE = 4096
_PROBE_SECONDS = 3.0
_CLEANUP_SECONDS = 0.5
_WAIT_TIMEOUT = 0x102


class HandoffLifecycleError(JobObjectError):
    """A failed or unconfirmed readiness/cleanup condition; never a fallback."""

    def __init__(self, message: str, *, stage: str = "readiness", cause=None):
        super().__init__(message)
        self.stage = stage if type(stage) is str and stage in _FAILURE_STAGES else "readiness"
        self.code = "HANDOFF_READINESS_UNCONFIRMED"
        for name in ("winerror", "errno"):
            value = getattr(cause, name, None)
            if type(value) is int and 0 <= value <= 65535:
                setattr(self, name, value)


def _failure(exc, stage: str) -> HandoffLifecycleError:
    if isinstance(exc, HandoffLifecycleError) and exc.stage != "readiness":
        return exc
    return HandoffLifecycleError("handoff readiness was not confirmed", stage=stage, cause=exc)


def _failure_record(exc, stage: str) -> dict[str, object]:
    failure = _failure(exc, stage)
    result = {"schema": FAILURE_SCHEMA, "event": "probe_failed",
              "stage": failure.stage, "code": failure.code}
    for name in ("winerror", "errno"):
        value = getattr(failure, name, None)
        if type(value) is int:
            result[name] = value
    if type(getattr(failure, "probe_cleanup_confirmed", None)) is bool:
        result["probe_cleanup_confirmed"] = failure.probe_cleanup_confirmed
    return result


def _received_failure(message: dict[str, object], fallback: str) -> HandoffLifecycleError:
    stage = message.get("stage")
    failure = HandoffLifecycleError("probe rejected readiness", stage=stage if type(stage) is str
                                    and stage in _FAILURE_STAGES else fallback)
    for name in ("winerror", "errno"):
        value = message.get(name)
        if type(value) is int and 0 <= value <= 65535:
            setattr(failure, name, value)
    return failure


def host_creation_flags() -> int:
    return 0x01000208 if os.name == "nt" else 0


def worker_creation_flags(context: dict[str, object]) -> int:
    if os.name != "nt":
        return 0
    flags = context.get("job_limit_flags")
    silent_only = (
        context.get("process_in_job") is True
        and type(flags) is int
        and bool(flags & 0x1000)
        and not bool(flags & 0x0800)
    )
    return 0x208 if silent_only else host_creation_flags()


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _open_source_handle(pid: int):
    api = _kernel32()
    api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    api.OpenProcess.restype = wintypes.HANDLE
    handle = api.OpenProcess(0x1000 | 0x00100000, False, pid)
    if not handle:
        raise HandoffLifecycleError("source process lease could not be opened")
    return handle


def _handle_identity(handle, pid: int) -> ProcessIdentity:
    api = _kernel32()
    api.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    api.GetProcessTimes.restype = wintypes.BOOL
    times = [wintypes.FILETIME() for _ in range(4)]
    if not api.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
        raise HandoffLifecycleError("source process creation identity could not be queried")
    api.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    api.QueryFullProcessImageNameW.restype = wintypes.BOOL
    size = wintypes.DWORD(32768)
    image = ctypes.create_unicode_buffer(size.value)
    if not api.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
        raise HandoffLifecycleError("source process image could not be queried")
    created = (int(times[0].dwHighDateTime) << 32) | int(times[0].dwLowDateTime)
    return ProcessIdentity(pid, created, str(Path(image.value).resolve()))


def _wait_handle(handle, milliseconds: int) -> int:
    api = _kernel32()
    api.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    api.WaitForSingleObject.restype = wintypes.DWORD
    return int(api.WaitForSingleObject(handle, milliseconds))


def _close_handle(handle) -> None:
    api = _kernel32()
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    if not api.CloseHandle(handle):
        raise HandoffLifecycleError("source process lease could not be closed")


def _duration(value: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("timeout must be finite and nonnegative")
    return float(value)


class SourceProcessLease:
    """Pin a live process by creation ticks/image, then wait on that same handle."""

    def __init__(self, pid: int, created_at: int, executable: str) -> None:
        self._handle = None
        if os.name != "nt":
            raise HandoffLifecycleError("source process leases require Windows")
        if (type(pid) is not int or pid < 1 or type(created_at) is not int or created_at < 1
                or type(executable) is not str or not executable or not Path(executable).is_absolute()):
            raise ValueError("source process identity is invalid")
        handle = _open_source_handle(pid)
        self._handle = handle
        try:
            actual = _handle_identity(handle, pid)
            if (actual.created_at != created_at
                    or actual.executable.casefold() != str(Path(executable).resolve()).casefold()
                    or _wait_handle(handle, 0) != _WAIT_TIMEOUT):
                raise HandoffLifecycleError("source process lease identity or liveness mismatch")
        except BaseException:
            self.close()
            raise

    def wait_for_exit(self, timeout_seconds: float) -> bool:
        if self._handle is None:
            raise HandoffLifecycleError("source process lease is closed")
        milliseconds = min(math.ceil(_duration(timeout_seconds) * 1000), 0xFFFFFFFE)
        status = _wait_handle(self._handle, milliseconds)
        if status == 0:
            return True
        if status == _WAIT_TIMEOUT:
            return False
        raise HandoffLifecycleError("source process lease wait could not be confirmed")

    def close(self) -> None:
        if self._handle is not None:
            _close_handle(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def _read_json_line(process: subprocess.Popen[bytes], deadline: float) -> dict[str, object] | None:
    """Read a bounded original pipe without a thread holding BufferedReader's lock."""
    stream = process.stdout
    if stream is None:
        return None
    data = bytearray()
    try:
        if os.name == "nt":
            import msvcrt
            handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
            api = _kernel32()
            api.PeekNamedPipe.argtypes = (
                wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
            api.PeekNamedPipe.restype = wintypes.BOOL
            api.ReadFile.argtypes = (
                wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
            api.ReadFile.restype = wintypes.BOOL
        while time.monotonic() < deadline and len(data) < _MAX_LINE:
            if os.name == "nt":
                available = wintypes.DWORD()
                if not api.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                    return None
                if not available.value:
                    if process.poll() is not None:
                        return None
                    time.sleep(0.01)
                    continue
                # One byte avoids consuming a following internal protocol line.
                byte = ctypes.create_string_buffer(1)
                received = wintypes.DWORD()
                if not api.ReadFile(handle, byte, 1, ctypes.byref(received), None) or received.value != 1:
                    return None
                chunk = byte.raw
            else:
                import select
                readable, _, _ = select.select([stream], [], [], min(0.01, max(0, deadline - time.monotonic())))
                if not readable:
                    continue
                chunk = os.read(stream.fileno(), 1)
                if not chunk:
                    return None
            data.extend(chunk)
            if chunk == b"\n":
                result = json.loads(bytes(data).decode("utf-8"))
                return result if type(result) is dict else None
    except (OSError, ValueError, UnicodeError):
        return None
    return None


def _identity_field(identity, name: str):
    return identity.get(name) if isinstance(identity, dict) else getattr(identity, name, None)


def read_worker_ready(process, job_id: str, source_identity, worker_identity,
                      timeout_seconds: float = 5) -> bool:
    """Accept only a live, identity-bound worker's strict readiness JSON."""
    timeout = min(_duration(timeout_seconds), 5.0)
    if process.poll() is not None:
        return False
    message = _read_json_line(process, time.monotonic() + timeout)
    if message is not None and message.get("schema") == FAILURE_SCHEMA:
        # Diagnostic only: this can never authorize source shutdown. No paths,
        # environment, commands or exception text are copied from the child.
        if (type(message.get("stage")) is str and message["stage"] in _FAILURE_STAGES
                and message.get("code") == "HANDOFF_READINESS_UNCONFIRMED"):
            process.handoff_ready_failure = {"stage": message["stage"], "code": message["code"]}
            for name in ("winerror", "errno"):
                value = message.get(name)
                if type(value) is int and 0 <= value <= 65535:
                    process.handoff_ready_failure[name] = value
            if type(message.get("probe_cleanup_confirmed")) is bool:
                process.handoff_ready_failure["probe_cleanup_confirmed"] = message["probe_cleanup_confirmed"]
        return False
    if message is None or process.poll() is not None:
        return False
    if message.get("schema") != READY_SCHEMA or message.get("job_id") != job_id:
        return False
    for prefix, identity in (("source", source_identity), ("worker", worker_identity)):
        for name in ("pid", "created_at"):
            expected = _identity_field(identity, name)
            actual = message.get(f"{prefix}_{name}")
            if type(expected) is not int or expected < 1 or type(actual) is not int or actual != expected:
                return False
    if type(process.pid) is not int or process.pid != _identity_field(worker_identity, "pid"):
        return False
    return all(message.get(field) is True for field in (
        "source_process_lease_opened", "host_creation_verified", "host_cleanup_confirmed"))


def _spawn_probe(mode: str, flags: int = 0):
    # Fixed same-runtime/module commands only; no application, database or env paths.
    return subprocess.Popen(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), mode],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        close_fds=True, shell=False, creationflags=flags, bufsize=0)


def _reap(process, timeout: float = _CLEANUP_SECONDS) -> bool:
    if process is None:
        return True
    try:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=timeout)
        return process.poll() is not None
    except (OSError, subprocess.TimeoutExpired):
        return False


def _close_pipes(process) -> None:
    if process is not None:
        for name in ("stdin", "stdout"):
            stream = getattr(process, name, None)
            if stream is not None:
                stream.close()


def _emit(message: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _probe_host() -> int:
    if sys.stdin.buffer.readline(8) != b"go\n":
        return 2
    try:
        job = ProcessJob()
        job.close()
    except (JobObjectError, OSError) as exc:
        raise _failure(exc, "probe_host_job") from exc
    _emit({"host_job_created": True, "host_job_closed": True})
    return 0


def _probe_launcher() -> int:
    """Ordinary launcher, detached/breakaway host, and post-creation cleanup Job."""
    host = None
    cleanup_job = None
    stage = "probe_host_job"
    try:
        cleanup_job = ProcessJob()
        # Never retry WinError 5 with ordinary flags.
        stage = "probe_host_create"
        host = _spawn_probe("--probe-host", host_creation_flags())
        # Enclose it immediately. Only this newly owned host is assigned; the
        # source, worker and ordinary launcher remain untouched.
        stage = "probe_host_assign"
        cleanup_job.add(host)
        stage = "probe_host_identity"
        identity = process_identity(host.pid)
        if identity is None or host.poll() is not None:
            raise HandoffLifecycleError("probe host identity was not confirmed")
        # Does not alter the launcher context used for the host's CreateProcess.
        # Host waits for go before its own Job creation; kill-on-close covers faults.
        _emit({"event": "host_created", "pid": identity.pid, "created_at": identity.created_at})
        if sys.stdin.buffer.readline(8) != b"go\n":
            return 2
        host.stdin.write(b"go\n")
        host.stdin.close()
        deadline = time.monotonic() + _PROBE_SECONDS
        result = _read_json_line(host, deadline)
        stage = "probe_host_result"
        host.wait(timeout=max(0.01, deadline - time.monotonic()))
        if result is not None and result.get("schema") == FAILURE_SCHEMA:
            raise _received_failure(result, "probe_host_job")
        if (host.returncode != 0 or result is None or result.get("host_job_created") is not True
                or result.get("host_job_closed") is not True):
            return 2
        cleanup_job.close()
        _emit({"host_creation_verified": True, "host_cleanup_confirmed": True})
        return 0
    except (JobObjectError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise _failure(exc, stage) from exc
    finally:
        cleanup_confirmed = _reap(host)
        try:
            if cleanup_job is not None:
                cleanup_job.close()
        finally:
            _close_pipes(host)
        if not cleanup_confirmed:
            raise HandoffLifecycleError("probe host cleanup was not confirmed", stage="probe_cleanup")


def _verify_host_creation() -> None:
    launcher = None
    host_lease = None
    failure_stage = "probe_launcher_create"
    error = None
    deadline = time.monotonic() + _PROBE_SECONDS
    try:
        launcher = _spawn_probe("--probe-launcher")
        failure_stage = "probe_host_registration"
        identity = _read_json_line(launcher, deadline)
        if identity is not None and identity.get("schema") == FAILURE_SCHEMA:
            raise _received_failure(identity, "launcher_probe")
        if (identity is None or identity.get("event") != "host_created"
                or type(identity.get("pid")) is not int or identity["pid"] < 1
                or type(identity.get("created_at")) is not int or identity["created_at"] < 1):
            raise HandoffLifecycleError("probe host creation was not confirmed")
        failure_stage = "probe_host_lease"
        host_lease = SourceProcessLease(identity.get("pid"), identity.get("created_at"), sys.executable)
        launcher.stdin.write(b"go\n")
        launcher.stdin.close()
        result = _read_json_line(launcher, deadline)
        failure_stage = "probe_result"
        launcher.wait(timeout=max(0.01, deadline - time.monotonic()))
        if (launcher.returncode != 0 or result is None
                or result.get("host_creation_verified") is not True
                or result.get("host_cleanup_confirmed") is not True
                or not host_lease.wait_for_exit(0)):
            raise HandoffLifecycleError("probe lifecycle was not confirmed")
    except (JobObjectError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        error = _failure(exc, failure_stage)
        raise error from exc
    finally:
        launcher_stopped = _reap(launcher)
        try:
            # No host registration is not proof that no host was created. A
            # launcher interrupted before registration must remain unconfirmed.
            host_stopped = host_lease is not None and host_lease.wait_for_exit(_CLEANUP_SECONDS)
        finally:
            try:
                if host_lease is not None:
                    host_lease.close()
            finally:
                _close_pipes(launcher)
        if not launcher_stopped or not host_stopped:
            # Retain a bounded first-failure stage without claiming cleanup.
            if error is not None:
                error.probe_cleanup_confirmed = False
                raise error
            raise HandoffLifecycleError("probe cleanup was not confirmed", stage="probe_cleanup")


def prepare_worker_ready(job_id: str, source_pid: int, source_created_at: int,
                         source_executable: str):
    if type(job_id) is not str or re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
        raise ValueError("job identity is invalid")
    context = current_job_diagnostics()
    if (context.get("job_query_ok") is not True or type(context.get("process_in_job")) is not bool
            or (context["process_in_job"] and type(context.get("job_limit_flags")) is not int)):
        raise HandoffLifecycleError("worker Job context is unknown", stage="worker_job_query")
    try:
        lease = SourceProcessLease(source_pid, source_created_at, source_executable)
    except (JobObjectError, OSError, ValueError) as exc:
        raise _failure(exc, "source_lease") from exc
    stage = "worker_identity"
    try:
        worker = process_identity(os.getpid())
        if worker is None or type(worker.created_at) is not int or worker.created_at < 1:
            raise HandoffLifecycleError("worker identity is unknown")
        stage = "readiness"
        _verify_host_creation()
        stage = "source_liveness"
        if lease.wait_for_exit(0):
            raise HandoffLifecycleError("source exited before readiness")
        return lease, {
            "schema": READY_SCHEMA, "job_id": job_id,
            "source_pid": source_pid, "source_created_at": source_created_at,
            "worker_pid": worker.pid, "worker_created_at": worker.created_at,
            "source_process_lease_opened": True,
            "host_creation_verified": True, "host_cleanup_confirmed": True,
        }
    except (JobObjectError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        lease.close()
        raise _failure(exc, stage) from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--worker-ready", action="store_true")
    modes.add_argument("--probe-launcher", action="store_true")
    modes.add_argument("--probe-host", action="store_true")
    parser.add_argument("--job-id")
    parser.add_argument("--source-pid", type=int)
    parser.add_argument("--source-created-at", type=int)
    parser.add_argument("--source-executable")
    args = parser.parse_args(argv)
    try:
        if args.probe_launcher:
            return _probe_launcher()
        if args.probe_host:
            return _probe_host()
        lease, ready = prepare_worker_ready(args.job_id, args.source_pid, args.source_created_at,
                                            args.source_executable)
        with lease:
            _emit(ready)
            return 0 if lease.wait_for_exit(90) else 2
    except (JobObjectError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        record = _failure_record(exc, "launcher_probe" if args.probe_launcher else
                                  "host_probe" if args.probe_host else "readiness")
        if args.worker_ready:
            record["job_id"] = args.job_id
        _emit(record)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
