"""Readiness protocol and original-handle safety; no application/DB is launched."""

from types import SimpleNamespace
import select
import subprocess
import sys

import pytest

from enterprise.runtime import handoff_lifecycle as lifecycle
from enterprise.runtime.ownership import ProcessIdentity

JOB_ID = "a" * 32
SOURCE = ProcessIdentity(11, 111, sys.executable)
WORKER = ProcessIdentity(22, 222, sys.executable)


def ready():
    return {"schema": lifecycle.READY_SCHEMA, "job_id": JOB_ID,
            "source_pid": 11, "source_created_at": 111,
            "worker_pid": 22, "worker_created_at": 222,
            "source_process_lease_opened": True,
            "host_creation_verified": True, "host_cleanup_confirmed": True}


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(lifecycle, "os", SimpleNamespace(name="nt", getpid=lambda: 22))


def test_creation_flags_preserve_silent_only_rule(windows):
    assert lifecycle.host_creation_flags() == 0x01000208
    assert lifecycle.worker_creation_flags({"process_in_job": True, "job_limit_flags": 0x1000}) == 0x208
    for context in ({}, {"process_in_job": True, "job_limit_flags": 0x2000},
                    {"process_in_job": True, "job_limit_flags": 0x1800},
                    {"process_in_job": True, "job_limit_flags": True}):
        assert lifecycle.worker_creation_flags(context) == 0x01000208


def test_source_lease_queries_and_waits_same_original_handle(windows, monkeypatch):
    calls = []
    handle = object()
    monkeypatch.setattr(lifecycle, "_open_source_handle", lambda pid: handle)
    monkeypatch.setattr(lifecycle, "_handle_identity", lambda owned, pid:
                        calls.append(("identity", owned, pid)) or SOURCE)
    waits = iter((0x102, 0x102, 0))
    monkeypatch.setattr(lifecycle, "_wait_handle", lambda owned, ms:
                        calls.append(("wait", owned, ms)) or next(waits))
    monkeypatch.setattr(lifecycle, "_close_handle", lambda owned: calls.append(("close", owned)))
    with lifecycle.SourceProcessLease(SOURCE.pid, SOURCE.created_at, SOURCE.executable) as lease:
        assert lease.wait_for_exit(0.1) is False
        assert lease.wait_for_exit(1) is True
    assert all(call[1] is handle for call in calls)
    assert calls[-1] == ("close", handle)
    with pytest.raises(lifecycle.HandoffLifecycleError):
        lease.wait_for_exit(0)


@pytest.mark.parametrize("actual,wait", [(ProcessIdentity(11, 999, sys.executable), 0x102),
                                        (ProcessIdentity(11, 111, sys.executable + ".other"), 0x102),
                                        (SOURCE, 0), (SOURCE, 0xFFFFFFFF)])
def test_source_lease_rejects_reused_pid_or_dead_unknown_handle(windows, monkeypatch, actual, wait):
    closed = []
    handle = object()
    monkeypatch.setattr(lifecycle, "_open_source_handle", lambda pid: handle)
    monkeypatch.setattr(lifecycle, "_handle_identity", lambda *_args: actual)
    monkeypatch.setattr(lifecycle, "_wait_handle", lambda *_args: wait)
    monkeypatch.setattr(lifecycle, "_close_handle", closed.append)
    with pytest.raises(lifecycle.HandoffLifecycleError):
        lifecycle.SourceProcessLease(SOURCE.pid, SOURCE.created_at, SOURCE.executable)
    assert closed == [handle]


@pytest.mark.parametrize("pid,ticks,image", [(True, 111, sys.executable), (11, True, sys.executable),
                                          (0, 111, sys.executable), (11, 0, sys.executable),
                                          (11, 111, "relative.exe")])
def test_source_lease_rejects_malformed_identity_without_open(windows, monkeypatch, pid, ticks, image):
    monkeypatch.setattr(lifecycle, "_open_source_handle", lambda *_: pytest.fail("must not open"))
    with pytest.raises(ValueError):
        lifecycle.SourceProcessLease(pid, ticks, image)


def test_read_worker_ready_accepts_only_bound_strict_success(monkeypatch):
    process = SimpleNamespace(pid=22, poll=lambda: None)
    monkeypatch.setattr(lifecycle, "_read_json_line", lambda *_args: ready())
    assert lifecycle.read_worker_ready(process, JOB_ID, SOURCE, WORKER) is True


@pytest.mark.parametrize("field,value", [("schema", "wrong"), ("job_id", "b" * 32),
    ("source_pid", 12), ("source_created_at", 112), ("worker_pid", 23),
    ("worker_created_at", 223), ("source_pid", True), ("worker_created_at", "222"),
    ("source_process_lease_opened", 1), ("host_creation_verified", "true"),
    ("host_cleanup_confirmed", False)])
def test_read_worker_ready_rejects_unbound_or_forged_message(monkeypatch, field, value):
    message = ready()
    message[field] = value
    monkeypatch.setattr(lifecycle, "_read_json_line", lambda *_args: message)
    assert lifecycle.read_worker_ready(SimpleNamespace(pid=22, poll=lambda: None),
                                        JOB_ID, SOURCE, WORKER) is False


def test_read_worker_ready_deadline_is_bounded_and_exit_rejected(monkeypatch):
    deadlines = []
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: 100)
    monkeypatch.setattr(lifecycle, "_read_json_line", lambda _process, deadline:
                        deadlines.append(deadline) or None)
    assert not lifecycle.read_worker_ready(SimpleNamespace(pid=22, poll=lambda: None),
                                            JOB_ID, SOURCE, WORKER, 100)
    assert deadlines == [105]
    assert not lifecycle.read_worker_ready(SimpleNamespace(pid=22, poll=lambda: 0),
                                            JOB_ID, SOURCE, WORKER)
    assert deadlines == [105]


def test_prepare_rejects_unknown_job_before_lease_or_spawn(monkeypatch):
    monkeypatch.setattr(lifecycle, "current_job_diagnostics", lambda: {"job_query_ok": False})
    monkeypatch.setattr(lifecycle, "SourceProcessLease", lambda *_args: pytest.fail("must not open"))
    monkeypatch.setattr(lifecycle, "_verify_host_creation", lambda: pytest.fail("must not spawn"))
    with pytest.raises(lifecycle.HandoffLifecycleError):
        lifecycle.prepare_worker_ready(JOB_ID, 11, 111, sys.executable)


def test_prepare_closes_lease_when_host_probe_fails_without_retry(monkeypatch):
    closed = []
    monkeypatch.setattr(lifecycle, "current_job_diagnostics", lambda: {"job_query_ok": True, "process_in_job": False})
    monkeypatch.setattr(lifecycle, "SourceProcessLease", lambda *_args: SimpleNamespace(close=lambda: closed.append(True)))
    monkeypatch.setattr(lifecycle, "process_identity", lambda _pid: WORKER)
    def denied():
        error = OSError("denied")
        error.winerror = 5
        raise error
    monkeypatch.setattr(lifecycle, "_verify_host_creation", denied)
    with pytest.raises(lifecycle.HandoffLifecycleError) as error:
        lifecycle.prepare_worker_ready(JOB_ID, 11, 111, sys.executable)
    assert error.value.winerror == 5
    assert error.value.stage == "readiness"
    assert closed == [True]


def test_spawn_probe_is_fixed_same_module_and_flags(monkeypatch):
    calls = []
    monkeypatch.setattr(lifecycle.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    lifecycle._spawn_probe("--probe-host", 0x01000208)
    command = calls[0][0][0]
    assert command[0:3] == [sys.executable, "-I", "-B"]
    assert command[-2:] == [str(lifecycle.Path(lifecycle.__file__).resolve()), "--probe-host"]
    assert calls[0][1]["creationflags"] == 0x01000208
    assert calls[0][1]["shell"] is False
    assert "env" not in calls[0][1]


def test_reap_cleanup_timeout_remains_unconfirmed():
    process = SimpleNamespace(poll=lambda: None, terminate=lambda: None,
                              wait=lambda **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("probe", 0.5)))
    assert lifecycle._reap(process) is False


@pytest.mark.parametrize("payload,valid", [(b'{"ok":true}\n', True), (b'[]\n', False),
    (b'{broken}\n', False), (b'\xff\n', False), (b'{"x":"' + b'x' * 4096 + b'"}\n', False)])
def test_pipe_read_is_bounded_single_line_without_reader_thread(monkeypatch, payload, valid):
    chunks = iter(bytes((byte,)) for byte in payload)
    stream = SimpleNamespace(fileno=lambda: 77)
    monkeypatch.setattr(lifecycle, "os", SimpleNamespace(name="posix", read=lambda *_: next(chunks, b"")))
    monkeypatch.setattr(select, "select", lambda *_: ([stream], [], []))
    result = lifecycle._read_json_line(SimpleNamespace(stdout=stream, poll=lambda: None),
                                       lifecycle.time.monotonic() + 1)
    assert (result == {"ok": True}) if valid else result is None


@pytest.mark.parametrize("context", [{"job_query_ok": True},
    {"job_query_ok": True, "process_in_job": True},
    {"job_query_ok": True, "process_in_job": "false"}])
def test_prepare_rejects_incomplete_job_evidence(monkeypatch, context):
    monkeypatch.setattr(lifecycle, "current_job_diagnostics", lambda: context)
    monkeypatch.setattr(lifecycle, "SourceProcessLease", lambda *_: pytest.fail("must not open"))
    with pytest.raises(lifecycle.HandoffLifecycleError):
        lifecycle.prepare_worker_ready(JOB_ID, 11, 111, sys.executable)


def test_fixed_failure_record_excludes_exception_text_paths_and_environment():
    original = OSError("C:/secret/project API_KEY=not-for-output")
    original.winerror = 5
    record = lifecycle._failure_record(original, "probe_host_create")
    assert record == {"schema": lifecycle.FAILURE_SCHEMA, "event": "probe_failed",
                      "stage": "probe_host_create", "code": "HANDOFF_READINESS_UNCONFIRMED", "winerror": 5}
    assert "secret" not in str(record)


def test_failure_diagnostic_is_never_readiness_and_has_strict_fields(monkeypatch):
    process = SimpleNamespace(pid=22, poll=lambda: None)
    message = {"schema": lifecycle.FAILURE_SCHEMA, "stage": "probe_host_create",
               "code": "HANDOFF_READINESS_UNCONFIRMED", "winerror": 5,
               "probe_cleanup_confirmed": False, "environment": "must not copy"}
    monkeypatch.setattr(lifecycle, "_read_json_line", lambda *_: message)
    assert lifecycle.read_worker_ready(process, JOB_ID, SOURCE, WORKER) is False
    assert process.handoff_ready_failure == {"stage": "probe_host_create",
        "code": "HANDOFF_READINESS_UNCONFIRMED", "winerror": 5, "probe_cleanup_confirmed": False}


def test_invalid_failure_stage_and_numeric_bool_are_not_exported(monkeypatch):
    process = SimpleNamespace(pid=22, poll=lambda: None)
    monkeypatch.setattr(lifecycle, "_read_json_line", lambda *_: {
        "schema": lifecycle.FAILURE_SCHEMA, "stage": "C:/secret", "code": "HANDOFF_READINESS_UNCONFIRMED"})
    assert lifecycle.read_worker_ready(process, JOB_ID, SOURCE, WORKER) is False
    assert not hasattr(process, "handoff_ready_failure")
    assert lifecycle._received_failure({"stage": "C:/secret", "winerror": True}, "probe_result").stage == "probe_result"


def test_probe_failure_keeps_first_fixed_stage_and_unknown_cleanup(monkeypatch):
    process = SimpleNamespace(stdin=None, stdout=None)
    monkeypatch.setattr(lifecycle, "_spawn_probe", lambda *_: process)
    monkeypatch.setattr(lifecycle, "_read_json_line", lambda *_: {
        "schema": lifecycle.FAILURE_SCHEMA, "stage": "probe_host_create",
        "code": "HANDOFF_READINESS_UNCONFIRMED", "winerror": 5})
    reaped = []
    monkeypatch.setattr(lifecycle, "_reap", lambda owned: reaped.append(owned) or True)
    with pytest.raises(lifecycle.HandoffLifecycleError) as failure:
        lifecycle._verify_host_creation()
    assert failure.value.stage == "probe_host_create"
    assert failure.value.winerror == 5
    assert failure.value.probe_cleanup_confirmed is False
    assert reaped == [process]
