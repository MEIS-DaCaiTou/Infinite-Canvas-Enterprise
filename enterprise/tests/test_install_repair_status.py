"""Repair display is not transaction authority; owned fixtures and real pipe."""
from __future__ import annotations

import json
import os
import threading
import uuid

import pytest

from enterprise import install_repair as repair
from enterprise.install_repair_status import inspect_program_repair
from enterprise.install_setup_bridge import GRAPHICAL_MAINTENANCE_REQUEST_SCHEMA, _decode_request, _serve_once, SetupBridgeError
from enterprise.release.release_manifest_v2 import canonical_json
from enterprise.tests.test_install_program_repair import installed, damaged, preserved, Interrupted
from enterprise.tests.test_install_ux_1 import _client_exchange


def query(arguments):
    return inspect_program_repair(**{k: v for k, v in arguments.items() if k != "confirm_no_active_tasks"})


def files(root):
    # A live Windows kernel lease intentionally denies reading its one byte.
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and p.name != "runner.lock"}


def test_idle_query_creates_no_state_or_business_files(installed):
    arguments, roots = installed
    before = files(roots.INSTALL_ROOT)
    assert query(arguments)["repair_state"] == "NONE"
    assert files(roots.INSTALL_ROOT) == before and not roots.STAGING_ROOT.exists()


def test_live_query_and_final_query_across_phases_are_read_only(installed):
    arguments, roots = installed
    damaged(roots)
    before = preserved(roots)
    phases = []
    def observe(phase, operation):
        state = files(roots.INSTALL_ROOT)
        result = query(arguments)
        assert result["repair_state"] == "RUNNING" and result["operation_id"] == operation
        assert result["phase"] == phase and files(roots.INSTALL_ROOT) == state
        phases.append(phase)
    assert repair.repair_program(**arguments, notify_progress=observe)["repair_state"] == "SUCCEEDED"
    assert phases == ["preparing", "locked", "publishing", "verifying", "committed"]
    state = files(roots.INSTALL_ROOT)
    assert query(arguments)["repair_state"] == "SUCCEEDED"
    assert files(roots.INSTALL_ROOT) == state and preserved(roots) == before


@pytest.mark.parametrize("checkpoint", ["locked", "original_moved", "candidate_published", "committed"])
def test_interrupted_state_is_not_claimed_success_until_recovery_finishes(installed, monkeypatch, checkpoint):
    arguments, roots = installed
    damaged(roots)
    before = preserved(roots)
    def interrupt(name):
        if name == checkpoint:
            raise Interrupted()
    monkeypatch.setattr(repair, "_checkpoint", interrupt)
    with pytest.raises(Interrupted): repair.repair_program(**arguments)
    state = files(roots.INSTALL_ROOT)
    assert query(arguments)["repair_state"] == "RECOVERY_REQUIRED"
    assert files(roots.INSTALL_ROOT) == state
    repair.recover_program(**arguments)
    expected = "SUCCEEDED" if checkpoint == "committed" else "ROLLED_BACK"
    assert query(arguments)["repair_state"] == expected and preserved(roots) == before


def test_preparation_exit_does_not_create_recovery_authority_or_switch_program(installed):
    arguments, roots = installed
    original = repair._tree_token(roots.APP_ROOT)
    def stop(phase, operation):
        if phase == "preparing": raise Interrupted()
    with pytest.raises(Interrupted): repair.repair_program(**arguments, notify_progress=stop)
    assert query(arguments)["repair_state"] == "STOPPED_BEFORE_SWITCH"
    assert repair._tree_token(roots.APP_ROOT) == original
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()


def test_old_v3_plan_without_display_records_can_be_inspected_and_recovered(installed, monkeypatch):
    arguments, roots = installed
    damaged(roots)
    before = preserved(roots)
    def stop(name):
        if name == "candidate_published": raise Interrupted()
    monkeypatch.setattr(repair, "_checkpoint", stop)
    with pytest.raises(Interrupted): repair.repair_program(**arguments)
    operation = json.loads((roots.STATE_ROOT / "system-update-active.lock").read_bytes())["operation_id"]
    # Model an interrupted #141 v3 transaction, before display files existed.
    (roots.STATE_ROOT / "program-repair-progress.json").unlink()
    (roots.STAGING_ROOT / "program-repairs" / operation[:12] / "progress.json").unlink()
    state = files(roots.INSTALL_ROOT)
    assert query(arguments)["repair_state"] == "RECOVERY_REQUIRED"
    assert files(roots.INSTALL_ROOT) == state
    assert repair.recover_program(**arguments)["repair_state"] == "ROLLED_BACK"
    assert query(arguments)["repair_state"] == "ROLLED_BACK" and preserved(roots) == before


def test_progress_write_failure_cannot_change_committed_program_result(installed, monkeypatch):
    from enterprise import install_repair_status as status
    arguments, roots = installed
    damaged(roots)
    before = preserved(roots)
    original = status._atomic_publish
    def fail_display(path, *args, **kwargs):
        if path.name == "progress.json": raise OSError("fixture display storage unavailable")
        return original(path, *args, **kwargs)
    def notify(phase, operation):
        if phase == "preparing": monkeypatch.setattr(status, "_atomic_publish", fail_display)
    assert repair.repair_program(**arguments, notify_progress=notify)["repair_state"] == "SUCCEEDED"
    result = query(arguments)
    assert result["repair_state"] == "SUCCEEDED" and result["phase"] == "preparing"
    assert preserved(roots) == before


@pytest.mark.parametrize("target", ["index", "progress", "runner", "pointer"])
def test_tampered_display_or_identity_blocks_without_modification(installed, monkeypatch, target):
    arguments, roots = installed
    def stop(name):
        if name == "locked": raise Interrupted()
    monkeypatch.setattr(repair, "_checkpoint", stop)
    with pytest.raises(Interrupted): repair.repair_program(**arguments)
    lock = roots.STATE_ROOT / "system-update-active.lock"
    operation = json.loads(lock.read_bytes())["operation_id"]
    area = roots.STAGING_ROOT / "program-repairs" / operation[:12]
    path = {"index": roots.STATE_ROOT / "program-repair-progress.json", "progress": area / "progress.json",
            "runner": area / "runner.lock", "pointer": roots.STATE_ROOT / "current-release.json"}[target]
    path.write_bytes(b"unknown")
    before = files(roots.INSTALL_ROOT)
    with pytest.raises(RuntimeError): query(arguments)
    assert files(roots.INSTALL_ROOT) == before and lock.exists()


def test_forged_success_phase_cannot_override_transaction_result(installed, monkeypatch):
    arguments, roots = installed
    def stop(name):
        if name == "locked": raise Interrupted()
    monkeypatch.setattr(repair, "_checkpoint", stop)
    with pytest.raises(Interrupted): repair.repair_program(**arguments)
    operation = json.loads((roots.STATE_ROOT / "system-update-active.lock").read_bytes())["operation_id"]
    progress = roots.STAGING_ROOT / "program-repairs" / operation[:12] / "progress.json"
    value = json.loads(progress.read_bytes()); value["phase"] = "committed"
    progress.write_bytes(canonical_json(value))
    assert query(arguments)["repair_state"] == "RECOVERY_REQUIRED"


def test_unrecognized_lock_never_becomes_a_repair_recovery(installed):
    arguments, roots = installed
    (roots.STATE_ROOT / "system-update-active.lock").write_bytes(b'{"schema_version":"other-job"}')
    before = files(roots.INSTALL_ROOT)
    with pytest.raises(repair.ProgramRepairError, match="INSTALL_PROGRAM_FOREIGN_LOCK"): query(arguments)
    assert files(roots.INSTALL_ROOT) == before


def request(operation="repair-program"):
    return {"schema_version": GRAPHICAL_MAINTENANCE_REQUEST_SCHEMA, "operation": operation,
            "install_mode": "custom", "install_root": "C:\\owned-fixture", "username": "",
            "password": "", "password_confirmation": "", "confirm_no_active_tasks": operation != "inspect-program"}


@pytest.mark.parametrize("operation", ["repair-program", "recover-program", "inspect-program"])
def test_v4_contract_has_closed_operations_and_no_credentials(operation):
    value = request(operation)
    assert _decode_request(canonical_json(value)) == value
    for changed in ({"confirm_no_active_tasks": 1}, {"confirm_no_active_tasks": not value["confirm_no_active_tasks"]},
                    {"password": "not-accepted"}, {"operation": "install"}, {"extra": True}):
        with pytest.raises(SetupBridgeError): _decode_request(canonical_json(value | changed))


@pytest.mark.skipif(os.name != "nt", reason="actual Windows current-user pipe")
def test_closing_view_does_not_cancel_runner_and_new_window_can_query(installed):
    arguments, roots = installed
    damaged(roots)
    before = preserved(roots)
    suffix, resumed = uuid.uuid4().hex, threading.Event()
    result = {}
    def handler(value, notify_progress):
        def progress(phase, operation):
            notify_progress(phase, operation)
            if phase == "preparing":
                assert resumed.wait(10)
        payload = repair.repair_program(**arguments, notify_progress=progress)
        return {"schema_version": "install-ux-1-result-v1", "status": "succeeded", "code": "INSTALL_PROGRAM_REPAIRED", **payload}
    def serve():
        try: result["exit"] = _serve_once(suffix, handler)
        except BaseException as exc: result["error"] = repr(exc)
    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        frame = _client_exchange(suffix, request(), on_progress=lambda response: False)
        assert frame["event"] == "progress"
        assert query(arguments)["repair_state"] == "RUNNING"
    finally:
        resumed.set()
        worker.join(15)
    assert not worker.is_alive() and result == {"exit": 0}
    assert query(arguments)["repair_state"] == "SUCCEEDED" and preserved(roots) == before


def test_gui_scopes_and_payload_lifetime_remain_explicit():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[2] / "installer/windows/InfiniteCanvasEnterprise.iss").read_text(encoding="utf-8")
    for operation in ("repair-program", "recover-program", "inspect-program"):
        assert operation in source
    assert "enterprise-install-maintenance-request-v4" in source
    assert "TaskConfirmationPage.Values[0] := False" in source
    assert "关闭查看（后台继续）" in source and "PeekNamedPipe(Stream.Handle" in source
    assert "InstallProgress.SetProgress(0, 0)" in source
    assert "if (BundleRoot <> '') and not PersistentBundle then" in source
    assert "maintenance-payloads" in source and "HasReparseAncestors(CacheRoot)" in source
    assert "(CurStep = ssPostInstall) and ShouldMaintainEntry" in source
    assert "Check: ShouldMaintainEntry" in source
    assert "if RepairState <> 'SUCCEEDED' then" in source
