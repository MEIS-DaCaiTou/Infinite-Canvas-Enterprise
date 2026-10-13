"""Closed-program repair fixtures; no customer data, services or GUI actions."""
from __future__ import annotations

import json
import shutil

import pytest

from enterprise import install_repair as repair
from enterprise import install_entry as entry
from enterprise.install_setup_bridge import PROGRAM_MAINTENANCE_REQUEST_SCHEMA, _decode_request, SetupBridgeError
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.release_manifest_v2 import canonical_json, verify_materialized_release
from enterprise.runtime.ownership import ProcessIdentity
from enterprise.runtime.state import RuntimeStateStore
from enterprise.tests.test_install_entry import bundle, qualified_program_fixture


class Interrupted(BaseException):
    pass


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root, manifest, archive, inventory, document = qualified_program_fixture(tmp_path)
    local = tmp_path / "local"
    roots = derive_portable_path_roots(PortableRootInputs(root, local), document["identity"]["release_id"])
    published = entry.publish_fixed_entry(roots, bundle(tmp_path / "native"))
    published.complete()
    assets = tmp_path / "closed-assets"
    assets.mkdir()
    shutil.copyfile(manifest, assets / "ops-release-manifest-v2.json")
    shutil.copyfile(inventory, assets / "release-payload-inventory.json")
    shutil.copyfile(archive, assets / document["archive"]["filename"])
    # Only replace OS observations for these tiny non-runnable fixtures. Real
    # complete-payload tests exercise the actual inspector and kernel leases.
    monkeypatch.setattr(repair, "inspect_runtime", lambda config: {"start_disposition": "stopped"})
    return dict(install_root=root, release_dir=assets, local_app_data_base=local,
                confirm_no_active_tasks=True), roots


def preserved(roots):
    paths = [roots.DATA_ROOT / "enterprise.db", roots.CONFIG_ROOT / "enterprise.env",
             roots.STATE_ROOT / "installation.json", roots.STATE_ROOT / "current-release.json",
             roots.INSTALL_ROOT / "InfiniteCanvas.exe"]
    return {str(path): path.read_bytes() for path in paths}


def damaged(roots):
    (roots.APP_ROOT / "main.py").write_bytes(b"fixture broken program")
    (roots.APP_ROOT / "python/python.exe").unlink()


def test_same_release_repair_restores_program_and_python_without_business_writes(installed):
    arguments, roots = installed
    before = preserved(roots)
    damaged(roots)
    original = repair._tree_token(roots.APP_ROOT)
    result = repair.repair_program(**arguments)
    assert result["repair_state"] == "SUCCEEDED"
    assert result["database_changed"] is result["pointer_changed"] is result["entry_changed"] is False
    assert preserved(roots) == before
    assert (roots.APP_ROOT / "python/python.exe").is_file()
    verify_materialized_release(roots.APP_ROOT, inventory_path=roots.APP_ROOT / "release-payload-inventory.json")
    directory = roots.STAGING_ROOT / "program-repairs" / result["operation_id"][:12]
    assert repair._tree_token(directory / "original") == original
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()
    assert not (roots.RUNTIME_ROOT / "runtime-reconcile.lock").exists()


def test_observed_publication_failure_rolls_back_without_waiting_for_recovery(installed, monkeypatch):
    arguments, roots = installed
    damaged(roots)
    before, original = preserved(roots), repair._tree_token(roots.APP_ROOT)
    def fail(name):
        if name == "candidate_published":
            raise OSError("fixture-only postpublication failure")
    monkeypatch.setattr(repair, "_checkpoint", fail)
    with pytest.raises(repair.ProgramRepairError, match="INSTALL_PROGRAM_REPAIR_FAILED"):
        repair.repair_program(**arguments)
    assert preserved(roots) == before and repair._tree_token(roots.APP_ROOT) == original
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()
    assert not (roots.RUNTIME_ROOT / "runtime-reconcile.lock").exists()


def test_missing_whole_program_directory_can_be_repaired_without_reinitializing(installed):
    arguments, roots = installed
    before = preserved(roots)
    original = roots.INSTALL_ROOT.parent / "owned-missing-program-fixture"
    roots.APP_ROOT.rename(original)
    original_token = repair._tree_token(original)
    assert repair.repair_program(**arguments)["repair_state"] == "SUCCEEDED"
    assert preserved(roots) == before and repair._tree_token(original) == original_token


@pytest.mark.parametrize("checkpoint", ["locked", "prepared", "original_moved", "candidate_published", "committed"])
def test_interruption_recovery_has_exact_owned_rollback_or_commit_boundary(installed, monkeypatch, checkpoint):
    arguments, roots = installed
    damaged(roots)
    before, original = preserved(roots), repair._tree_token(roots.APP_ROOT)
    def interrupt(name):
        if name == checkpoint:
            raise Interrupted()
    monkeypatch.setattr(repair, "_checkpoint", interrupt)
    with pytest.raises(Interrupted):
        repair.repair_program(**arguments)
    assert (roots.STATE_ROOT / "system-update-active.lock").exists()
    monkeypatch.setattr(repair, "_checkpoint", lambda name: None)
    recovered = repair.recover_program(**arguments)
    assert recovered["repair_state"] == ("SUCCEEDED" if checkpoint == "committed" else "ROLLED_BACK")
    assert preserved(roots) == before
    if checkpoint != "committed":
        assert repair._tree_token(roots.APP_ROOT) == original
        assert repair.repair_program(**arguments)["repair_state"] == "SUCCEEDED"
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()
    assert not (roots.RUNTIME_ROOT / "runtime-reconcile.lock").exists()


@pytest.mark.parametrize("change", ["unowned_file", "unowned_empty_directory", "foreign_lock", "pointer", "identity", "tasks", "runtime", "pending_update"])
def test_unsafe_sources_block_before_any_program_or_business_mutation(installed, monkeypatch, change):
    arguments, roots = installed
    if change == "unowned_file": (roots.APP_ROOT / "other-project.txt").write_bytes(b"do not move")
    if change == "unowned_empty_directory": (roots.APP_ROOT / "other-project").mkdir()
    if change == "foreign_lock": (roots.STATE_ROOT / "system-update-active.lock").write_bytes(b"foreign")
    if change == "pointer":
        path = roots.STATE_ROOT / "current-release.json"
        value = json.loads(path.read_bytes()); value["manifest_sha256"] = "a" * 64
        path.write_bytes(canonical_json(value))
    if change == "identity": (roots.STATE_ROOT / "installation.json").unlink()
    if change == "tasks": arguments["confirm_no_active_tasks"] = False
    if change == "runtime": monkeypatch.setattr(repair, "inspect_runtime", lambda config: {"start_disposition": "startup_in_progress"})
    if change == "pending_update": monkeypatch.setattr(repair.UpdateJobStore, "pending_recovery_jobs", lambda *a, **k: ["unresolved"])
    before, program = preserved(roots) if change != "identity" else {}, repair._tree_token(roots.APP_ROOT)
    with pytest.raises(repair.ProgramRepairError): repair.repair_program(**arguments)
    assert repair._tree_token(roots.APP_ROOT) == program
    if before: assert preserved(roots) == before
    assert not roots.STAGING_ROOT.exists()


@pytest.mark.parametrize("change", ["pointer", "identity", "plan", "backup", "foreign_fence", "runner"])
def test_uncertain_interruption_preserves_lock_and_evidence(installed, monkeypatch, change):
    arguments, roots = installed
    damaged(roots)
    def interrupt(name):
        if name == "candidate_published": raise Interrupted()
    monkeypatch.setattr(repair, "_checkpoint", interrupt)
    with pytest.raises(Interrupted): repair.repair_program(**arguments)
    lock = roots.STATE_ROOT / "system-update-active.lock"
    marker = json.loads(lock.read_bytes())
    directory = roots.STAGING_ROOT / "program-repairs" / marker["operation_id"][:12]
    if change in {"pointer", "identity"}:
        path = roots.STATE_ROOT / ("current-release.json" if change == "pointer" else "installation.json")
        path.write_bytes(path.read_bytes() + b" ")
    if change == "plan": (directory / "plan.json").write_bytes(b"changed")
    if change == "backup": (directory / "original/main.py").write_bytes(b"foreign mutation")
    if change == "foreign_fence": (roots.RUNTIME_ROOT / "runtime-reconcile.lock").write_bytes(b"other repair")
    if change == "runner": (directory / "runner.lock").write_bytes(b"tamper")
    before, program, lock_before = preserved(roots), repair._tree_token(roots.APP_ROOT), lock.read_bytes()
    with pytest.raises(repair.ProgramRepairError): repair.recover_program(**arguments)
    assert preserved(roots) == before and repair._tree_token(roots.APP_ROOT) == program
    assert lock.read_bytes() == lock_before


def test_live_kernel_lease_cannot_be_stolen_by_recovery(installed, monkeypatch):
    arguments, roots = installed
    def recover_while_running(name):
        if name == "prepared":
            with pytest.raises(repair.ProgramRepairError, match="INSTALL_PROGRAM_RUNNER_BUSY"):
                repair.recover_program(**arguments)
    monkeypatch.setattr(repair, "_checkpoint", recover_while_running)
    assert repair.repair_program(**arguments)["repair_state"] == "SUCCEEDED"


def test_port_probe_reads_only_explicit_valid_decimal_config(installed):
    _, roots = installed
    (roots.CONFIG_ROOT / "enterprise.env").write_bytes(
        b'GATEWAY_PORT="41234" # fixture\nexport UPSTREAM_PORT=\'41235\'\nSECRET=never-returned\n')
    assert repair._ports(roots) == {"GATEWAY_PORT": 41234, "UPSTREAM_PORT": 41235}


@pytest.mark.parametrize("config", [b'GATEWAY_PORT="8000', b'GATEWAY_PORT', b'GATEWAY_PORT=0',
                                  b'GATEWAY_PORT=8000\nGATEWAY_PORT=8001', b'UPSTREAM_PORT=8000'])
def test_ambiguous_ports_block_before_staging(installed, config):
    arguments, roots = installed
    (roots.CONFIG_ROOT / "enterprise.env").write_bytes(config)
    before = preserved(roots)
    with pytest.raises(repair.ProgramRepairError, match="INSTALL_PROGRAM_RUNTIME_UNCERTAIN"):
        repair.repair_program(**arguments)
    assert preserved(roots) == before and not roots.STAGING_ROOT.exists()


@pytest.mark.parametrize("foreground", [False, True])
@pytest.mark.parametrize("raced", [False, True])
def test_runtime_launch_reservation_respects_maintenance_fence(tmp_path, monkeypatch, foreground, raced):
    store = RuntimeStateStore(tmp_path / "runtime")
    store.initialize()
    if not raced: store.reconcile_path.write_bytes(b"fixture maintenance fence")
    else:
        original = store._reservation_survives_reconcile
        def create_fence(instance, identity):
            store.reconcile_path.write_bytes(b"raced maintenance fence")
            return original(instance, identity)
        monkeypatch.setattr(store, "_reservation_survives_reconcile", create_fence)
    identity = ProcessIdentity(123, 123, "fixture-only")
    outcome = (store.acquire_foreground_lock(instance_id="fixture", supervisor=identity) if foreground
               else store.reserve_lock(instance_id="fixture", owner=identity))
    assert outcome is False and not store.lock_path.exists()
    assert store.reconcile_path.exists()


def test_v3_repair_request_keeps_v1_v2_closed_and_requires_explicit_task_confirmation():
    value = {"schema_version": PROGRAM_MAINTENANCE_REQUEST_SCHEMA, "operation": "repair-program",
             "confirm_no_active_tasks": True, "install_mode": "custom", "install_root": "C:\\fixture",
             "username": "", "password": "", "password_confirmation": ""}
    assert _decode_request(canonical_json(value)) == value
    for changes in ({"confirm_no_active_tasks": 1}, {"confirm_no_active_tasks": False},
                    {"password": "not accepted"}, {"operation": "install"}, {"extra": True}):
        with pytest.raises(SetupBridgeError): _decode_request(canonical_json(value | changes))
