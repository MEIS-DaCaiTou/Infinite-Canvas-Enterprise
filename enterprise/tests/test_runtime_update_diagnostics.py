"""Targeted lifecycle evidence checks; no customer data or services."""
import json
import io
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from enterprise.runtime.control import RuntimeControlError, RuntimeController, RuntimeServiceHostStartupError
from enterprise.runtime.error_contract import public_lifecycle_details
from enterprise.runtime.cli import _paths
from enterprise.path_safety import PathSafetyError
from enterprise.runtime.portable import stable_error_document
from enterprise.ops.update.mvp import _run_launcher, execute_update_job
from enterprise.ops.update.diagnostics import diagnostics_zip, recent_diagnostics
from enterprise.tests.test_stab_1_supervisor_logging import build_supervisor
from enterprise.tests.test_update_mvp_1 import _execution_fixture


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
         failure_patch:
        with pytest.raises(RuntimeControlError) as caught:
            controller.start(wait_seconds=1)
    assert caught.value.public_details == {"failure_stage": stage, "errno": 13, "winerror": 5}
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
    assert set(status["runtime_phases"]) == {"target_start", "target_stop", "source_start", "source_health"}
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
