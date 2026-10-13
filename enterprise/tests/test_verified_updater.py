"""Target engine custody, compatibility and pre-stop refusal contracts."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from enterprise.ops.update import handoff, updater
from enterprise.ops.update.mvp import UpdateJobStore
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, prepare_install_state_directories
from enterprise.runtime import handoff_lifecycle as lifecycle
from enterprise.runtime.ownership import ProcessIdentity

JOB_ID = "a" * 32


def descriptor():
    return {"schema_version": updater.DESCRIPTOR_SCHEMA, "minimum_controller_contract": 1,
            "worker_protocol": 2, "updater_contract": 4, "worker_entry": updater.WORKER_PATH}


def write_descriptor(root, payload):
    path = root / updater.DESCRIPTOR_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def prepared(tmp_path):
    roots = derive_portable_path_roots(PortableRootInputs(tmp_path / "install", tmp_path / "local"), "source-A")
    prepare_install_state_directories(roots)
    target = roots.RELEASE_ROOT / "target-B"
    write_descriptor(target, descriptor())
    worker, python = target / updater.WORKER_PATH, target / "python/python.exe"
    python.parent.mkdir()
    worker.write_bytes(b"verified-worker")
    python.write_bytes(b"verified-python")
    binding = updater.prepared_updater_binding(target, "b" * 64, "c" * 64)
    plan = {"schema_version": "enterprise-update-mvp-plan-v1", "job_id": JOB_ID,
            "actor_user_id": "admin-1", "source_release_id": "source-A",
            "target_release_id": "target-B", "target_manifest_sha256": "b" * 64,
            "target_payload_tree_sha256": "c" * 64, "target_inventory_sha256": "d" * 64,
            "updater_execution": binding}
    status = {"updater_execution": binding, "plan_sha256": updater.plan_sha256(plan)}
    return roots, target, plan, status


def verify_fixture(monkeypatch):
    monkeypatch.setattr(updater, "read_release_manifest_v2", lambda path: SimpleNamespace(
        release_id=path.parent.name, section=lambda _: {"inventory_path": "inventory.json"}))
    monkeypatch.setattr(updater, "verify_materialized_release", lambda *args, **kwargs: SimpleNamespace(
        manifest_sha256="b" * 64, payload_tree_sha256="c" * 64, inventory_sha256="d" * 64))


def test_legacy_missing_descriptor_keeps_source_contract_without_target_reads(tmp_path, monkeypatch):
    assert updater.read_updater_descriptor(tmp_path) is None
    monkeypatch.setattr(updater, "verify_materialized_release", lambda *_a, **_kw: pytest.fail("legacy must not select target"))
    assert updater.select_verified_updater(None, {}, {}) is None


@pytest.mark.parametrize("key,value", [
    ("worker_protocol", True), ("updater_contract", "4"), ("minimum_controller_contract", 0),
    ("worker_entry", "../../run.py"), ("schema_version", "unknown"), ("extra", "ignored"),
])
def test_untrusted_descriptor_never_downgrades_to_legacy(tmp_path, key, value):
    payload = descriptor()
    payload[key] = value
    write_descriptor(tmp_path, payload)
    with pytest.raises(updater.UpdaterExecutionError, match="UPDATER_UNVERIFIED"):
        updater.read_updater_descriptor(tmp_path)


@pytest.mark.parametrize("key,value", [("worker_protocol", 3), ("minimum_controller_contract", 2), ("updater_contract", 3)])
def test_incompatible_engine_is_refused_before_execution(tmp_path, key, value):
    payload = descriptor()
    payload[key] = value
    write_descriptor(tmp_path, payload)
    with pytest.raises(updater.UpdaterExecutionError, match="UPDATER_INCOMPATIBLE"):
        updater.read_updater_descriptor(tmp_path)


def test_newer_engine_can_use_stable_controller_protocol(tmp_path):
    payload = descriptor()
    payload["updater_contract"] = 5
    write_descriptor(tmp_path, payload)
    assert updater.read_updater_descriptor(tmp_path)[0]["updater_contract"] == 5


@pytest.mark.parametrize("raw", [b"{}", b"null", b"[1]", b"{", b" " * 4097])
def test_malformed_or_oversized_contract_is_not_a_legacy_release(tmp_path, raw):
    path = write_descriptor(tmp_path, descriptor())
    path.write_bytes(raw)
    with pytest.raises(updater.UpdaterExecutionError):
        updater.read_updater_descriptor(tmp_path)


def test_reparse_descriptor_is_refused(tmp_path, monkeypatch):
    path = write_descriptor(tmp_path, descriptor())
    monkeypatch.setattr(updater, "has_reparse_point", lambda candidate: candidate == path)
    with pytest.raises(updater.UpdaterExecutionError):
        updater.read_updater_descriptor(tmp_path)


@pytest.mark.parametrize("change", ["actor", "hash", "release", "bool", "drop-plan", "drop-status", "status-hash"])
def test_prepared_authorization_cannot_be_rebound_or_downgraded(tmp_path, change):
    _, _, plan, status = prepared(tmp_path)
    plan, status = copy.deepcopy(plan), copy.deepcopy(status)
    if change == "actor":
        plan["actor_user_id"] = "another-admin"
    elif change == "hash":
        plan["updater_execution"]["contract_sha256"] = "e" * 64
    elif change == "release":
        plan["target_release_id"] = "another-target"
    elif change == "bool":
        status["updater_execution"]["controller_contract"] = True
    elif change == "drop-plan":
        plan.pop("updater_execution")
    elif change == "drop-status":
        status.pop("updater_execution")
    else:
        status["plan_sha256"] = "f" * 64
    with pytest.raises(updater.UpdaterExecutionError):
        updater.sealed_updater_binding(plan, status)


def test_target_selection_uses_verified_fixed_runtime_and_contract(tmp_path, monkeypatch):
    roots, target, plan, status = prepared(tmp_path)
    verify_fixture(monkeypatch)
    selected = updater.select_verified_updater(roots, plan, status)
    assert selected.app_root == target
    assert selected.python == target / "python/python.exe"
    assert selected.worker == target / updater.WORKER_PATH
    assert selected.readiness_binding["plan_sha256"] == status["plan_sha256"]
    # Changing a contract after READY cannot start a target worker.
    payload = descriptor()
    payload["updater_contract"] = 5
    write_descriptor(target, payload)
    with pytest.raises(updater.UpdaterExecutionError):
        updater.select_verified_updater(roots, plan, status)


def test_payload_verification_failure_prevents_loading_target_code(tmp_path, monkeypatch):
    roots, _, plan, status = prepared(tmp_path)
    verify_fixture(monkeypatch)
    def tampered(*_args, **_kwargs):
        raise ValueError("payload changed")
    monkeypatch.setattr(updater, "verify_materialized_release", tampered)
    with pytest.raises(updater.UpdaterExecutionError):
        updater.select_verified_updater(roots, plan, status)


def test_plan_seal_and_executor_survive_terminal_transitions(tmp_path):
    roots, _, plan, _ = prepared(tmp_path)
    store = UpdateJobStore(roots)
    job_id, _ = store.create("admin-1")
    plan["job_id"] = job_id
    digest = store.write_plan(job_id, plan)
    store.write_status(job_id, "READY", actor_user_id="admin-1", result_code="SYSTEM_UPDATE_READY",
                       plan_sha256=digest, updater_execution=plan["updater_execution"])
    for state in ("UPDATING", "VERIFYING", "ROLLED_BACK"):
        status = store.write_status(job_id, state, actor_user_id="admin-1", result_code="fixture")
        assert updater.sealed_updater_binding(store.read_plan(job_id), status)["plan_sha256"] == digest


@pytest.mark.parametrize("alter", [None, "legacy", "plan", "type", "job"])
def test_readiness_is_bound_to_engine_and_exact_prepared_job(tmp_path, monkeypatch, alter):
    _, _, plan, status = prepared(tmp_path)
    expected = updater.sealed_updater_binding(plan, status)
    actual = copy.deepcopy(expected)
    message = {"schema": lifecycle.BOUND_READY_SCHEMA, "job_id": JOB_ID,
               "source_pid": 11, "source_created_at": 111, "worker_pid": 22, "worker_created_at": 222,
               "source_process_lease_opened": True, "host_creation_verified": True,
               "host_cleanup_confirmed": True, "updater_execution": actual}
    if alter == "legacy":
        message["schema"] = lifecycle.READY_SCHEMA
    elif alter == "plan":
        actual["plan_sha256"] = "f" * 64
    elif alter == "type":
        actual["controller_contract"] = True
    elif alter == "job":
        message["job_id"] = "b" * 32
    monkeypatch.setattr(lifecycle, "_read_json_line", lambda *_: message)
    assert lifecycle.read_worker_ready(SimpleNamespace(pid=22, poll=lambda: None), JOB_ID,
        ProcessIdentity(11, 111, "source.exe"), ProcessIdentity(22, 222, "target.exe"),
        updater_binding=expected) is (alter is None)
    assert not lifecycle.read_worker_ready(SimpleNamespace(pid=22, poll=lambda: None), JOB_ID,
        ProcessIdentity(11, 111, "source.exe"), ProcessIdentity(22, 222, "target.exe"))


def test_source_root_is_a_validated_sibling_and_code_root_stays_target(tmp_path, monkeypatch):
    target = tmp_path / "releases/target-B"
    source = tmp_path / "releases/source-A"
    source.mkdir(parents=True)
    target.mkdir()
    monkeypatch.setattr(handoff, "CODE_ROOT", target)
    assert handoff._source_app_root("source-A") == source
    assert handoff._source_app_root(None) == target
    for value in ("../outside", "C:/outside", "target-B"):
        with pytest.raises(Exception):
            handoff._source_app_root(value)


def test_target_worker_cannot_use_source_runtime_or_legacy_invocation(tmp_path, monkeypatch):
    roots, target, plan, status = prepared(tmp_path)
    verify_fixture(monkeypatch)
    monkeypatch.setattr(handoff, "CODE_ROOT", target)
    monkeypatch.setattr(UpdateJobStore, "read_plan", lambda *_: plan)
    monkeypatch.setattr(UpdateJobStore, "read_status", lambda *_: status)
    monkeypatch.setattr(UpdateJobStore, "active_handoff_reservation", lambda *_: (1, 2))
    monkeypatch.setattr(handoff.sys, "executable", str(target / "python/python.exe"))
    assert handoff._worker_binding(roots, JOB_ID, "source-A")["updater_contract"] == 4
    with pytest.raises(updater.UpdaterExecutionError):
        handoff._worker_binding(roots, JOB_ID, None)
    monkeypatch.setattr(handoff.sys, "executable", str(roots.APP_ROOT / "python/python.exe"))
    with pytest.raises(updater.UpdaterExecutionError):
        handoff._worker_binding(roots, JOB_ID, "source-A")


def test_supervisor_refuses_unverified_target_before_spawning_or_stopping(tmp_path, monkeypatch):
    from enterprise.runtime.supervisor import RuntimeSupervisor
    root = tmp_path / "source-A"
    python, worker = root / "python/python.exe", root / updater.WORKER_PATH
    python.parent.mkdir(parents=True)
    worker.parent.mkdir(parents=True)
    python.touch()
    worker.touch()
    supervisor = RuntimeSupervisor.__new__(RuntimeSupervisor)
    supervisor.config = SimpleNamespace(app_root=root, python_executable=python, runtime_mode="portable-release")
    supervisor._update_handoff_request = {"update_job_id": JOB_ID}
    supervisor._stopping = False
    supervisor._command_snapshot = lambda: {"state": "healthy"}
    supervisor._handoff_reservation = lambda *_: (1, 2)
    def refuse(_):
        raise updater.UpdaterExecutionError()
    supervisor._select_handoff_updater = refuse
    acknowledgements = []
    supervisor._safe_handoff_ack = lambda _, **fields: acknowledgements.append(fields)
    monkeypatch.setattr("enterprise.runtime.supervisor.subprocess.Popen", lambda *_a, **_k: pytest.fail("must not spawn"))
    supervisor._perform_update_handoff()
    assert supervisor._stopping is False
    assert acknowledgements[0]["result"] == "update_handoff_updater_rejected"
