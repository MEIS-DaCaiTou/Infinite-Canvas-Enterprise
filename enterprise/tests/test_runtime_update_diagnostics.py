"""Targeted lifecycle evidence checks; no customer data or services."""
import json
import io
import os
import ctypes
from types import SimpleNamespace
from contextlib import redirect_stdout
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from enterprise.runtime.control import RuntimeControlError, RuntimeController, RuntimeServiceHostStartupError
from enterprise.runtime.error_contract import public_lifecycle_details
from enterprise.runtime.cli import _paths, main as runtime_cli_main
from enterprise.path_safety import PathSafetyError
from enterprise.runtime.portable import stable_error_document
from enterprise.ops.update.mvp import _run_launcher, execute_update_job
from enterprise.ops.update.diagnostics import diagnostics_zip, recent_diagnostics
from enterprise.tests.test_stab_1_supervisor_logging import build_supervisor
from enterprise.tests.test_update_mvp_1 import (
    _execution_fixture, _create_update_database, _update_migration_step, _migration_update_plan,
)
from enterprise.migrations.versioned import inspect_schema_metadata


def test_portable_paths_do_not_rebind_virtualized_known_folder(tmp_path):
    from argparse import Namespace
    app, runtime = tmp_path / "app", tmp_path / "runtime"
    app.mkdir()
    runtime.mkdir()
    args = Namespace(app_root=str(app), runtime_root=str(runtime), runtime_mode="portable-release")
    with patch.object(Path, "resolve", side_effect=AssertionError("must keep trusted lexical roots")):
        assert _paths(args) == (app.absolute(), runtime.absolute())
    with patch("enterprise.runtime.control.assert_no_reparse_ancestors", side_effect=PathSafetyError("reparse")):
        with pytest.raises(RuntimeControlError):
            _paths(args)
    args.runtime_root = str(app / "data")
    with pytest.raises(RuntimeControlError):
        _paths(args)


def test_portable_failure_retains_only_whitelisted_details():
    error = RuntimeControlError("private path and secret", public_details={
        "failure_stage": "service_host_create", "errno": 13, "winerror": 5,
        "path": "C:/private", "password": "private", "reason": "private",
    })
    assert stable_error_document(error) == {
        "code": "RUNTIME_CONTROL_ERROR", "status": "blocked",
        "failure_stage": "service_host_create", "errno": 13, "winerror": 5,
    }
    assert stable_error_document(RuntimeServiceHostStartupError(
        exit_code=2, failure_category="module_not_found"))["host_exit_code"] == 2
    error.public_details = {"failure_stage": {}, "bootstrap_failure_category": [],
                            "errno": True, "winerror": 2**99, "host_exit_code": "secret"}
    assert public_lifecycle_details(error.public_details) == {}
    error.code = "C:/private secret"
    assert stable_error_document(error)["code"] == "PORTABLE_BOOTSTRAP_INVALID"


def test_direct_cli_uses_the_same_detail_allowlist():
    error = RuntimeControlError("private-secret", public_details={
        "failure_stage": "service_host_create", "winerror": 5, "password": "private-secret",
    })
    output = io.StringIO()
    with patch("enterprise.runtime.cli.run", side_effect=error), redirect_stdout(output):
        assert runtime_cli_main(["start"]) == 2
    assert json.loads(output.getvalue()) == {"code": "RUNTIME_CONTROL_ERROR", "status": "blocked",
                                            "failure_stage": "service_host_create", "winerror": 5}


@pytest.mark.parametrize("stage", ["service_host_create", "bootstrap_marker_prepare"])
def test_controller_failure_is_durable_and_releases_reserved_lock(tmp_path, stage):
    supervisor = build_supervisor(tmp_path / "runtime")
    controller = RuntimeController(supervisor.config)
    error = OSError(13, "secret-private-path")
    error.winerror = 5
    real_unlink = Path.unlink
    def unlink(path, *args, **kwargs):
        if path.name == "service-host-bootstrap.failure":
            raise error
        return real_unlink(path, *args, **kwargs)
    failure_patch = (patch("enterprise.runtime.control.subprocess.Popen", side_effect=error)
                     if stage == "service_host_create" else patch.object(Path, "unlink", autospec=True, side_effect=unlink))
    with patch("enterprise.runtime.control.inspect_runtime", return_value={"start_disposition": "stopped"}), \
         patch("enterprise.runtime.control.current_job_diagnostics", return_value={}), \
         failure_patch:
        with pytest.raises(RuntimeControlError) as caught:
            controller.start(wait_seconds=1)
    assert caught.value.public_details == {"failure_stage": stage, "errno": 13, "winerror": 5,
                                          **({"creation_flags": (0x01000208 if os.name == "nt" else 0)}
                                             if stage == "service_host_create" else {})}
    assert not controller.store.lock_path.exists()
    raw = (tmp_path / "runtime" / "launcher.log").read_text(encoding="utf-8")
    assert "secret-private-path" not in raw
    result = [json.loads(line) for line in raw.splitlines() if '"service_host_start_failed"' in line][-1]
    assert result["failure_stage"] == stage and result["winerror"] == 5


def test_log_constructor_failure_still_releases_reservation(tmp_path):
    supervisor = build_supervisor(tmp_path / "runtime")
    controller = RuntimeController(supervisor.config)
    with patch("enterprise.runtime.control.inspect_runtime", return_value={"start_disposition": "stopped"}), \
         patch("enterprise.runtime.control.RuntimeLogs", side_effect=OSError(13, "private-secret")):
        with pytest.raises(RuntimeControlError) as caught:
            controller.start(wait_seconds=1)
    assert caught.value.public_details == {"failure_stage": "service_host_log", "errno": 13}
    assert not controller.store.lock_path.exists()


def test_job_context_allowlist_rejects_unbounded_or_coerced_values():
    payload = {"creation_flags": 0x01000208, "process_in_job": True,
               "job_query_ok": True, "job_limit_flags": 0x2000,
               "worker_creation_flags": 0, "worker_process_in_job": True,
               "worker_job_query_ok": False, "worker_job_query_winerror": 5}
    assert public_lifecycle_details({**payload, "job_name": "secret", "ancestor_jobs": "secret"}) == payload
    for value in (True, -1, 2**32, "secret", None):
        assert public_lifecycle_details({"creation_flags": value, "worker_job_limit_flags": value}) == {}
    for value in (0, 1, "true", None):
        assert public_lifecycle_details({"process_in_job": value, "worker_job_query_ok": value}) == {}


@pytest.mark.skipif(os.name != "nt", reason="Windows structures")
@pytest.mark.parametrize("in_job,is_error,query_error", [(False, 0, 0), (True, 0, 0),
                                                       (True, 5, 0), (True, 0, 6)])
def test_job_observation_is_read_only_and_failure_is_explicit(in_job, is_error, query_error):
    from enterprise.runtime import windows
    from ctypes import wintypes
    calls = []
    class Api:
        def __init__(self, callback):
            self.callback = callback
        def __call__(self, *args):
            return self.callback(*args)
    def membership(process, job, result):
        calls.append("IsProcessInJob")
        assert job is None and process == 123
        ctypes.cast(result, ctypes.POINTER(wintypes.BOOL))[0] = in_job
        return not is_error
    def query(job, kind, result, size, returned):
        calls.append("QueryInformationJobObject")
        assert job is None and kind == 9 and returned is None
        info = ctypes.cast(result, ctypes.POINTER(windows._JOBOBJECT_EXTENDED_LIMIT_INFORMATION)).contents
        info.BasicLimitInformation.LimitFlags = 0x2000
        return not query_error
    class Kernel:
        GetCurrentProcess = Api(lambda: 123)
        IsProcessInJob = Api(membership)
        QueryInformationJobObject = Api(query)
    with patch.object(ctypes, "WinDLL", return_value=Kernel()), \
         patch.object(ctypes, "get_last_error", return_value=is_error or query_error):
        result = windows.current_job_diagnostics()
    if is_error:
        assert result == {"job_query_ok": False, "job_query_winerror": is_error}
    elif query_error:
        assert result == {"process_in_job": True, "job_query_ok": False, "job_query_winerror": query_error}
    else:
        assert result == {"process_in_job": in_job, "job_query_ok": True,
                          **({"job_limit_flags": 0x2000} if in_job else {})}
    assert calls == ["IsProcessInJob"] + (["QueryInformationJobObject"] if in_job and not is_error else [])


def test_worker_creation_context_survives_the_launcher_return(tmp_path):
    (tmp_path / "python").mkdir()
    (tmp_path / "python/python.exe").touch()
    (tmp_path / "enterprise/runtime").mkdir(parents=True)
    (tmp_path / "enterprise/runtime/launcher.py").touch()
    context = {"process_in_job": True, "job_limit_flags": 0x2000, "job_query_ok": True}
    completed = subprocess.CompletedProcess([], 2, stdout=b'{"code":"RUNTIME_CONTROL_ERROR","winerror":5}\n')
    with patch("enterprise.runtime.windows.current_job_diagnostics", return_value=context), \
         patch("enterprise.ops.update.mvp.subprocess.run", return_value=completed) as create:
        exit_code, payload = _run_launcher(tmp_path, "start")
    assert exit_code == 2 and payload == {"code": "RUNTIME_CONTROL_ERROR", "winerror": 5,
        "worker_creation_flags": 0, **{"worker_" + k: v for k, v in context.items()}}
    assert create.call_args.kwargs.get("creationflags", 0) == 0


@pytest.mark.parametrize("failure", ["foreign-job", "query-failed", "creation-denied", "other-denial"])
def test_handoff_job_failure_never_stops_source_or_retries_ordinary_creation(tmp_path, monkeypatch, failure):
    from enterprise.runtime import supervisor as module
    from enterprise.runtime.ownership import ProcessIdentity
    from enterprise.runtime.windows import JobObjectError
    from unittest.mock import Mock
    app = tmp_path / "source"
    python, worker = app / "python/python.exe", app / "enterprise/ops/update/handoff.py"
    python.parent.mkdir(parents=True)
    worker.parent.mkdir(parents=True)
    python.touch()
    worker.touch()
    supervisor = module.RuntimeSupervisor.__new__(module.RuntimeSupervisor)
    supervisor.config = SimpleNamespace(app_root=app, python_executable=str(python), runtime_mode="portable-release")
    supervisor._update_handoff_request = {"request_id": "request", "update_job_id": "a" * 32}
    supervisor._stopping = False
    supervisor._command_snapshot = lambda: {"state": "healthy"}
    supervisor._ack = Mock()
    supervisor._log = Mock()
    process = Mock(pid=123)
    process.poll.return_value = None
    popen = Mock(return_value=process)
    if failure in {"creation-denied", "other-denial"}:
        error = OSError(13, "private-secret")
        error.winerror = 5
        popen.side_effect = error
    monkeypatch.setattr(module, "current_job_diagnostics", lambda: {
        "process_in_job": failure != "other-denial", "job_query_ok": True, "job_limit_flags": 0x2000})
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(module, "process_identity", lambda pid: ProcessIdentity(pid, 1, str(python)))
    query = Mock(return_value=True)
    if failure == "query-failed":
        query.side_effect = JobObjectError("private-secret")
    monkeypatch.setattr(module, "process_in_any_job", query)
    supervisor._perform_update_handoff()
    expected = "update_handoff_failed" if failure == "other-denial" else "update_handoff_job_blocked"
    assert supervisor._ack.call_args.kwargs["result"] == expected
    assert supervisor._stopping is False and popen.call_count == 1
    if os.name == "nt":
        assert popen.call_args.kwargs["creationflags"] == 0x01000208
    if failure in {"foreign-job", "query-failed"}:
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)
    else:
        process.terminate.assert_not_called()


def test_blocked_handoff_has_durable_specific_code_and_releases_only_own_reservation(tmp_path, monkeypatch):
    from enterprise import update_api
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(update_api, "PATH_ROOTS", roots)
    monkeypatch.setattr(update_api, "request_portable_update_handoff", lambda **kw: {"result": "update_handoff_job_blocked"})
    monkeypatch.setattr(update_api.edb, "log_action", lambda *_args: None)
    actor = store.read_plan(job_id)["actor_user_id"]
    update_api._launch_handoff(job_id, actor)
    assert store.read_status(job_id)["state"] == "FAILED"
    assert store.read_status(job_id)["result_code"] == "SYSTEM_UPDATE_HANDOFF_JOB_BLOCKED"
    assert not store.lock_path.exists() and pointer.release.release_id == "release-A" and calls == []
    assert "SYSTEM_UPDATE_HANDOFF_JOB_BLOCKED" in (store.job_root(job_id) / "events.jsonl").read_text()


def test_update_records_target_and_automatic_recovery_separately(tmp_path, monkeypatch):
    roots, store, job_id, pointer, calls, original = _execution_fixture(tmp_path, monkeypatch)
    def launcher(root, command):
        if command == "start":
            return 2, {"code": "RUNTIME_CONTROL_ERROR", "failure_stage": "service_host_create",
                       "winerror": 5, "errno": 13, "path": "private", "message": "private"}
        return original(root, command)
    assert execute_update_job(roots, job_id, launcher=launcher) == 2
    status = store.read_status(job_id)
    assert status["result_code"] == "SYSTEM_UPDATE_ROLLBACK_HEALTH_FAILED"
    assert status["failure_code"] == "RUNTIME_CONTROL_ERROR"
    assert pointer.release.release_id == "release-A"
    assert status["state"] == "RECOVERY_REQUIRED"
    assert set(status["runtime_phases"]) == {"target_start", "target_stop", "source_start"}
    assert status["runtime_phases"]["target_start"]["winerror"] == 5
    assert status["runtime_phases"]["source_start"]["launcher_exit_code"] == 2
    evidence = (store.job_root(job_id) / "events.jsonl").read_text(encoding="utf-8")
    assert "private" not in json.dumps(status) + evidence
    assert "SYSTEM_UPDATE_RUNTIME_PHASE_STARTED" in evidence


def test_update_success_and_rollback_keep_phase_results(tmp_path, monkeypatch):
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path, monkeypatch, target_start_exit=2)
    assert execute_update_job(roots, job_id, launcher=launcher) == 2
    result = store.read_status(job_id)
    assert result["state"] == "ROLLED_BACK"
    assert result["runtime_phases"]["source_health"]["launcher_exit_code"] == 0
    for phase, release, command in (
        ("target_start", "release-B", "start"), ("target_stop", "release-B", "stop"),
        ("source_start", "release-A", "start"), ("source_health", "release-A", "health"),
    ):
        assert result["runtime_phases"][phase]["release_id"] == release
        assert result["runtime_phases"][phase]["command"] == command
        assert result["runtime_phases"][phase]["recorded_at"]


def test_update_launcher_exception_has_phase_without_exception_text(tmp_path, monkeypatch):
    roots, store, job_id, pointer, calls, original = _execution_fixture(tmp_path, monkeypatch)
    def launcher(root, command):
        if root.name == "release-B" and command == "start":
            raise OSError(13, "private-path-secret")
        return original(root, command)
    assert execute_update_job(roots, job_id, launcher=launcher) == 2
    status = store.read_status(job_id)
    assert status["runtime_phases"]["target_start"]["errno"] == 13
    assert "private-path-secret" not in json.dumps(status)


@pytest.mark.parametrize("failure,stage", [(OSError(13, "private-secret"), "launcher_create"),
                                        (subprocess.TimeoutExpired("private-secret", 1), "launcher_wait")])
def test_launcher_failure_is_path_free(tmp_path, failure, stage):
    (tmp_path / "python").mkdir()
    (tmp_path / "python/python.exe").touch()
    (tmp_path / "enterprise/runtime").mkdir(parents=True)
    (tmp_path / "enterprise/runtime/launcher.py").touch()
    with patch("enterprise.ops.update.mvp.subprocess.run", side_effect=failure):
        result, payload = _run_launcher(tmp_path, "start")
    assert result == 2 and payload["failure_stage"] == stage
    assert "private-secret" not in json.dumps(payload)


def test_export_keeps_phase_evidence_without_raw_error(tmp_path, monkeypatch):
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(
        tmp_path, monkeypatch, target_start_exit=2)
    assert execute_update_job(roots, job_id, launcher=launcher) == 2
    payload = recent_diagnostics(roots, job_id=job_id, limit=500)
    with zipfile.ZipFile(io.BytesIO(diagnostics_zip(payload))) as archive:
        report = json.loads(archive.read("update-diagnostics.json"))
    assert report["summary"]["update_job"]["runtime_phases"]["source_health"]["launcher_exit_code"] == 0
    assert any("SYSTEM_UPDATE_RUNTIME_PHASE_RESULT" in record["line"] for record in report["records"])


@pytest.mark.parametrize("migrating", [False, True])
def test_unconfirmed_target_stop_never_restores_pointer_or_database(tmp_path, monkeypatch, migrating):
    database = _create_update_database(tmp_path / "install/data/enterprise.db")
    step = _update_migration_step()
    plan = _migration_update_plan(database, tmp_path, step) if migrating else None
    roots, store, job_id, pointer, calls, original = _execution_fixture(
        tmp_path, monkeypatch, target_health_exit=2,
        database_update=plan, migration_target=migrating)
    def launcher(root, command):
        if root.name == "release-B" and command == "stop":
            calls.append((root.name, command))
            return 2, {"code": "RUNTIME_STOP_UNCONFIRMED"}
        return original(root, command)
    assert execute_update_job(roots, job_id, launcher=launcher, migration_registry=(step,)) == 2
    result = store.read_status(job_id)
    assert result["state"] == "RECOVERY_REQUIRED" and result["recovery_required"] is True
    assert result["result_code"] == "SYSTEM_UPDATE_TARGET_STOP_UNCONFIRMED"
    assert result["failure_code"] == "TARGET_HEALTH_BLOCKED"
    assert pointer.release.release_id == "release-B"
    assert not any(name == "release-A" for name, _ in calls)
    assert result["runtime_phases"]["target_stop"]["launcher_exit_code"] == 2
    assert "source_start" not in result["runtime_phases"]
    assert inspect_schema_metadata(database)["schema_version"] == (2 if migrating else 1)
    assert store.pending_recovery_jobs() == [job_id]


@pytest.mark.parametrize("before_switch", [False, True])
def test_source_recovery_exception_is_durable_and_skips_health(tmp_path, monkeypatch, before_switch):
    database = _create_update_database(tmp_path / "install/data/enterprise.db")
    step = _update_migration_step(validation_result=False)
    plan = _migration_update_plan(database, tmp_path, step) if before_switch else None
    roots, store, job_id, pointer, calls, original = _execution_fixture(
        tmp_path, monkeypatch, target_start_exit=2,
        database_update=plan, migration_target=before_switch)
    def launcher(root, command):
        if root.name == "release-A" and command == "start":
            raise OSError(13, "private-secret-source")
        return original(root, command)
    assert execute_update_job(roots, job_id, launcher=launcher, migration_registry=(step,)) == 2
    result = store.read_status(job_id)
    assert result["state"] == "RECOVERY_REQUIRED" and result["recovery_required"] is True
    assert pointer.release.release_id == "release-A"
    assert result["runtime_phases"]["source_start"]["errno"] == 13
    assert "source_health" not in result["runtime_phases"]
    assert not any(name == "release-A" and command == "health" for name, command in calls)
    assert "private-secret-source" not in json.dumps(result)
    assert store.pending_recovery_jobs() == [job_id]


def test_success_records_only_actual_phases_without_inventing_failure(tmp_path, monkeypatch):
    roots, store, job_id, pointer, calls, launcher = _execution_fixture(tmp_path, monkeypatch)
    assert execute_update_job(roots, job_id, launcher=launcher) == 0
    result = store.read_status(job_id)
    assert result["state"] == "SUCCEEDED"
    assert set(result["runtime_phases"]) == {"target_start", "target_health"}
    assert "failure_code" not in result


@pytest.mark.parametrize("output", [b"", b"private-secret", b"{}\n", b"[]\n"])
def test_launcher_zero_exit_without_valid_document_is_not_success(tmp_path, output):
    (tmp_path / "python").mkdir()
    (tmp_path / "python/python.exe").touch()
    (tmp_path / "enterprise/runtime").mkdir(parents=True)
    (tmp_path / "enterprise/runtime/launcher.py").touch()
    completed = subprocess.CompletedProcess([], 0, stdout=output)
    with patch("enterprise.ops.update.mvp.subprocess.run", return_value=completed):
        result, payload = _run_launcher(tmp_path, "start")
    assert result == 2 and payload["failure_stage"] == "launcher_output"
    assert "private-secret" not in json.dumps(payload)


@pytest.mark.parametrize("exit_code,payload", [(False, {"status": "ok"}), (0, {}), (0, [])])
def test_invalid_phase_document_cannot_publish_success(tmp_path, monkeypatch, exit_code, payload):
    roots, store, job_id, pointer, calls, original = _execution_fixture(tmp_path, monkeypatch)
    def launcher(root, command):
        if root.name == "release-B" and command == "start":
            return exit_code, payload
        return original(root, command)
    assert execute_update_job(roots, job_id, launcher=launcher) == 2
    result = store.read_status(job_id)
    assert result["state"] == "ROLLED_BACK"
    assert result["failure_code"] == "SYSTEM_UPDATE_FORMAL_ENTRY_OUTPUT_INVALID"
    assert result["runtime_phases"]["target_start"]["failure_stage"] == "launcher_output"
