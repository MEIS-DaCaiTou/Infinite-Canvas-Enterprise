"""Small complete path fixtures: real release/SQLite/pointer and checkpoint I/O.

Runtime launch is substituted here. Full native/runtime evidence is separate.
"""
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

import pytest

from enterprise import install_cache as files
from enterprise.ops.update import mvp, sequence, updater
from enterprise.ops.update.upgrade_routes import AllowedSource, ReleaseState, UpgradeRoutes
from enterprise.release.release_manifest_v2 import canonical_json, read_release_manifest_v2
from enterprise.tests.test_install_upgrade import installed
from enterprise.tests.test_install_entry import bundle
from enterprise.tests.test_ops_release_manifest_v2 import _rebind_fixture

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows installation/lease adapter")


@pytest.fixture
def prepared_path(installed, tmp_path, monkeypatch, request):
    f = installed
    roots = f["roots"]
    source = read_release_manifest_v2(roots.APP_ROOT / "release-manifest.json")
    source_schema = mvp._database_evidence(roots.APP_ROOT, source)["schema_objects_sha256"]
    current = ReleaseState(source.release_id, source.section("identity")["release_version"], source.raw_sha256,
                           source_schema, 4, "stable")
    sequence_id = uuid.uuid4().hex
    directory = sequence.input_root(roots, sequence_id)
    directory.mkdir(parents=True)
    (directory / "runner.lock").write_bytes(b"C")
    files._new_json(directory / "ownership.json", {"schema_version": sequence.SCHEMA, "sequence_id": sequence_id,
        "install_root_identity": files._identity(roots.INSTALL_ROOT), "local_app_data_base": str(f["local"]),
        "lease": files._file(directory / "runner.lock")["identity"]})
    original_manifest = next(f["target_assets"].glob("*manifest-v2.json"))
    base = json.loads(original_manifest.read_bytes())
    template = tmp_path / "target-area/payload"
    hops = []
    for index, (version, commit) in enumerate((("2026.07.7", "d" * 40), ("2026.07.8", "e" * 40))):
        release_id = "ice-" + version + "-" + commit[:12]
        hop_root = directory / release_id
        hop_root.mkdir()
        payload = hop_root / "payload"
        shutil.copytree(template, payload)
        descriptor_path = payload / updater.DESCRIPTOR_PATH
        descriptor_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor_path.write_bytes(canonical_json({"schema_version": updater.DESCRIPTOR_SCHEMA,
            "minimum_controller_contract": 1, "worker_protocol": 2, "updater_contract": 4,
            "worker_entry": updater.WORKER_PATH}))
        (payload / updater.WORKER_PATH).write_bytes(b"fixture-worker-not-executed")
        (payload / sequence.DESCRIPTOR).write_bytes(canonical_json({"schema_version": "enterprise-upgrade-sequence-controller-v1",
            "controller_contract": 1, "maximum_hops": 8, "maintenance_tools_contract": 1}))
        doc = json.loads(json.dumps(base))
        doc["identity"].update(release_id=release_id, release_version=version)
        doc["enterprise_source"].update(commit=commit, version=version)
        doc["archive"].update(filename=f"Infinite-Canvas-Enterprise-{release_id}-win-x64.zip", root_prefix="Infinite-Canvas-Enterprise-" + release_id)
        manifest, archive, inventory = (hop_root / name for name in ("ops-release-manifest-v2.json", "release.zip", "release-payload-inventory.json"))
        _rebind_fixture(manifest, archive, inventory, doc)
        materialized, verification = mvp.stage_verified_release(roots, manifest_path=manifest, archive_path=archive, inventory_path=inventory)
        sequence.require_sequence_controller(materialized)
        target = ReleaseState(release_id, version, verification.manifest_sha256, source_schema, 4, "stable")
        route = UpgradeRoutes(target, (AllowedSource(current.release_id, current.version, current.manifest_sha256,
            source_schema, 4, "same-schema-no-migration"),))
        hops.append({"release_id": release_id, "version": version, "manifest_sha256": verification.manifest_sha256,
                     "tools_sha256": None, "route": {"target": asdict(route.target),
                         "allowed_sources": [asdict(item) for item in route.allowed_sources]}})
        current = target
    context = {"upgrade_sequence": {"schema_version": sequence.SCHEMA, "sequence_id": sequence_id,
        "operator_revision": 1, "hops": hops}, "sequence_controller": {"release_id": current.release_id,
        "manifest_sha256": verification.manifest_sha256, "payload_tree_sha256": verification.payload_tree_sha256,
        "inventory_sha256": verification.inventory_sha256}}
    if getattr(request, "param", False):
        from enterprise.ops.update.maintenance_assets import ASSET_NAME, FILENAMES, SCHEMA, verify_tools
        from enterprise.runtime import windows_install_registration as registration
        support = roots.INSTALL_ROOT / sequence.SLOTS["support"]
        support.parent.mkdir(parents=True)
        old_setup = roots.INSTALL_ROOT / sequence.SLOTS["setup"]
        old_setup.write_bytes(b"MZ-old-unit-setup")
        installation_id = json.loads((roots.STATE_ROOT / "installation.json").read_bytes())["installation_id"]
        support.write_text('[Lifecycle]\nProduct=MEIS-DaCaiTou/Infinite-Canvas-Enterprise\nInstallationId=' + installation_id
            + '\nSetupSha256=' + hashlib.sha256(old_setup.read_bytes()).hexdigest() + '\nSetupSize=' + str(old_setup.stat().st_size)
            + '\nUninstaller=unins000.exe\nUninstallerSha256=' + 'f' * 64 + '\n', encoding='utf-8')
        monkeypatch.setattr(registration, "verify_registration", lambda *a, **kw: None)
        monkeypatch.setattr(registration, "update_registration_version", lambda *a, **kw: None)
        monkeypatch.setattr("enterprise.runtime.portable.windows_local_app_data_known_folder", lambda: f["local"])
        for hop in hops:
            tools = directory / hop["release_id"] / "tools"
            manifest = read_release_manifest_v2(directory / hop["release_id"] / "ops-release-manifest-v2.json")
            identity = manifest.section("enterprise_source")
            bundle(tools, hop["version"].encode(), identity["commit"], identity["tree"])
            setup = b"MZ-unit-setup-" + hop["version"].encode()
            (tools / FILENAMES[2]).write_bytes(setup)
            (tools / FILENAMES[3]).write_bytes(canonical_json({"schema_version": "install-ux-1-unsigned-build-record-v1",
                "enterprise_commit": identity["commit"], "enterprise_tree": identity["tree"], "release_id": hop["release_id"],
                "unsigned_setup_sha256": hashlib.sha256(setup).hexdigest(), "unsigned_setup_size_bytes": len(setup),
                "unsigned_builds_identical": True}))
            document = {"schema_version": SCHEMA, "release_id": hop["release_id"], "manifest_sha256": hop["manifest_sha256"],
                "source_commit": identity["commit"], "source_tree": identity["tree"], "uninstaller_contract": 1,
                "files": {name: {"sha256": hashlib.sha256((tools / name).read_bytes()).hexdigest(),
                    "size_bytes": (tools / name).stat().st_size} for name in FILENAMES}}
            raw = canonical_json(document)
            (tools / ASSET_NAME).write_bytes(raw)
            verify_tools(tools, manifest)
            hop["tools_sha256"] = hashlib.sha256(raw).hexdigest()
    first = directory / hops[0]["release_id"]
    prepared = mvp.UpdateMvpService(roots).prepare_from_artifacts(actor_user_id="admin-path-owner",
        manifest_path=first / "ops-release-manifest-v2.json", archive_path=first / "release.zip",
        inventory_path=first / "release-payload-inventory.json", execution_context=context)
    store = mvp.UpdateJobStore(roots)
    monkeypatch.setattr(sequence, "check_authorization", lambda *args: None)
    store.reserve_execution(prepared.job_id)
    store.write_status(prepared.job_id, "UPDATING", actor_user_id="admin-path-owner", result_code="SYSTEM_UPDATE_STARTED")
    sequence.activate_sequence(roots, prepared.job_id)
    calls = []
    def launcher(app_root, command):
        calls.append((app_root.name, command))
        return 0, {"result": "healthy" if command == "health" else command}
    return roots, prepared.job_id, directory, hops, launcher, calls


def business(roots):
    with closing(sqlite3.connect(roots.DATA_ROOT / "enterprise.db")) as conn:
        return conn.execute("SELECT * FROM business").fetchall()


def test_complete_two_hops_use_final_engine_and_preserve_business(prepared_path):
    roots, job_id, directory, hops, launch, calls = prepared_path
    before = business(roots)
    store = mvp.UpdateJobStore(roots)
    selected = updater.select_verified_updater(roots, store.read_plan(job_id), store.read_status(job_id))
    assert selected.app_root.name == hops[-1]["release_id"]
    assert sequence.execute_sequence(roots, job_id, launcher=launch) == 0
    public = sequence.public_sequence(roots, job_id)
    assert public["state"] == "SUCCEEDED" and public["completed_hops"] == 2
    assert business(roots) == before
    assert not (roots.STATE_ROOT / sequence.ACTIVE_NAME).exists()
    assert (hops[0]["release_id"], "stop") in calls
    assert (hops[1]["release_id"], "start") in calls


class ProcessInterrupted(BaseException):
    pass


@pytest.mark.parametrize("state", ["FAILED", "ROLLED_BACK", "RECOVERY_REQUIRED"])
def test_terminal_hop_reports_its_failure_instead_of_stale_sequence_start(prepared_path, state):
    roots, job_id, directory, hops, launch, calls = prepared_path
    store = mvp.UpdateJobStore(roots)
    store.write_status(job_id, state, actor_user_id="admin-path-owner", result_code="SYSTEM_UPDATE_HANDOFF_JOB_BLOCKED")
    status = store.read_status(job_id)
    public = sequence.public_sequence(roots, job_id)
    assert public["state"] == state
    assert public["result_code"] == status["result_code"]
    assert public["updated_at"] == status["updated_at"]
    assert not calls


def test_explicit_stop_retains_its_result_after_failed_handoff(prepared_path):
    roots, job_id, directory, hops, launch, calls = prepared_path
    store = mvp.UpdateJobStore(roots)
    store.write_status(job_id, "FAILED", actor_user_id="admin-path-owner", result_code="SYSTEM_UPDATE_HANDOFF_JOB_BLOCKED")
    lock = store.acquire_execution_lock(job_id)
    store.release_execution_lock(lock, job_id)
    result = sequence.stop_sequence(roots, job_id, launcher=launch)
    assert result["state"] == "FAILED"
    assert result["result_code"] == "SYSTEM_UPDATE_SEQUENCE_STOPPED"
    assert result["completed_hops"] == 0
    assert not result["can_stop"]


def test_checkpoint_process_interruption_resumes_suffix_without_repeating_success(prepared_path, monkeypatch):
    roots, job_id, directory, hops, launch, calls = prepared_path
    before = business(roots)
    monkeypatch.setattr(sequence, "_checkpoint", lambda *_: (_ for _ in ()).throw(ProcessInterrupted()))
    with pytest.raises(ProcessInterrupted):
        sequence.execute_sequence(roots, job_id, launcher=launch)
    public = sequence.public_sequence(roots, job_id)
    assert public["completed_hops"] == 1 and public["can_resume"] is True
    child = sequence.resume_sequence(roots, job_id, launcher=launch)
    monkeypatch.setattr(sequence, "_checkpoint", lambda *_: None)
    assert sequence.execute_sequence(roots, job_id, launcher=launch) == 0
    assert calls.count((hops[0]["release_id"], "start")) == 1
    assert business(roots) == before
    assert mvp.UpdateJobStore(roots).read_status(child)["state"] == "SUCCEEDED"


def test_second_hop_failure_restores_first_hop_only(prepared_path):
    roots, job_id, directory, hops, launch, calls = prepared_path
    before = business(roots)
    def fail_target(app_root, command):
        if app_root.name == hops[1]["release_id"] and command == "health":
            return 2, {"code": "SYSTEM_UPDATE_TARGET_HEALTH_FAILED"}
        return launch(app_root, command)
    assert sequence.execute_sequence(roots, job_id, launcher=fail_target) == 2
    pointer = sequence.read_current_release_result_from_state_root(roots.STATE_ROOT)
    assert pointer.release.release_id == hops[0]["release_id"]
    assert sequence.public_sequence(roots, job_id)["state"] == "ROLLED_BACK"
    assert business(roots) == before
    assert not (roots.STATE_ROOT / sequence.ACTIVE_NAME).exists()


def test_revoked_authorization_at_checkpoint_does_not_execute_another_hop(prepared_path, monkeypatch):
    roots, job_id, directory, hops, launch, calls = prepared_path
    checks = []
    def authorize(*_):
        checks.append(True)
        if len(checks) == 2:
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_AUTHORIZATION_REVOKED")
    monkeypatch.setattr(sequence, "check_authorization", authorize)
    assert sequence.execute_sequence(roots, job_id, launcher=launch) == 2
    assert sequence.public_sequence(roots, job_id)["completed_hops"] == 1
    assert (hops[1]["release_id"], "start") not in calls
    assert (roots.STATE_ROOT / sequence.ACTIVE_NAME).exists()


@pytest.mark.parametrize("prepared_path", [True], indirect=True)
def test_native_entry_setup_and_exact_original_objects_follow_each_hop(prepared_path):
    roots, job_id, directory, hops, launch, calls = prepared_path
    before = business(roots)
    assert sequence.execute_sequence(roots, job_id, launcher=launch) == 0
    final_tools = directory / hops[-1]["release_id"] / "tools"
    assert (roots.INSTALL_ROOT / "InfiniteCanvas.exe").read_bytes() == (final_tools / "InfiniteCanvas.exe").read_bytes()
    assert (roots.INSTALL_ROOT / sequence.SLOTS["setup"]).read_bytes() == (final_tools / "InfiniteCanvasSetup.exe").read_bytes()
    child = files._read(directory / "hop-1.json")[0]["job_id"]
    originals = mvp.UpdateJobStore(roots).job_root(child) / "native-tools"
    assert (originals / "original-entry").read_bytes() == (directory / hops[0]["release_id"] / "tools/InfiniteCanvas.exe").read_bytes()
    assert business(roots) == before


@pytest.mark.parametrize("prepared_path", [True], indirect=True)
def test_native_second_hop_failure_restores_previous_tools(prepared_path):
    roots, job_id, directory, hops, launch, calls = prepared_path
    def fail(app_root, command):
        if app_root.name == hops[-1]["release_id"] and command == "health":
            return 2, {"code": "SYSTEM_UPDATE_TARGET_HEALTH_FAILED"}
        return launch(app_root, command)
    assert sequence.execute_sequence(roots, job_id, launcher=fail) == 2
    assert (roots.INSTALL_ROOT / "InfiniteCanvas.exe").read_bytes() == (directory / hops[0]["release_id"] / "tools/InfiniteCanvas.exe").read_bytes()
    assert sequence.public_sequence(roots, job_id)["state"] == "ROLLED_BACK"


def test_progress_json_cannot_skip_unexecuted_hops(prepared_path):
    roots, job_id, directory, hops, launch, calls = prepared_path
    state = files._read(directory / "state.json")[0]
    files._state(directory / "state.json", {**state, "completed_hops": len(hops)})
    assert sequence.public_sequence(roots, job_id)["completed_hops"] == 0
    assert sequence.execute_sequence(roots, job_id, launcher=launch) == 0
    assert (hops[0]["release_id"], "start") in calls and (hops[1]["release_id"], "start") in calls


def test_tampered_intermediate_is_refused_before_source_shutdown(prepared_path):
    roots, job_id, directory, hops, launch, calls = prepared_path
    (roots.RELEASE_ROOT / hops[0]["release_id"] / updater.WORKER_PATH).write_bytes(b'changed-intermediate')
    store = mvp.UpdateJobStore(roots)
    with pytest.raises(updater.UpdaterExecutionError):
        updater.select_verified_updater(roots, store.read_plan(job_id), store.read_status(job_id))
    assert not calls
    assert sequence.read_current_release_result_from_state_root(roots.STATE_ROOT).release.release_id == roots.APP_ROOT.name


def test_stop_after_committed_hop_keeps_current_data_without_replaying_suffix(prepared_path, monkeypatch):
    roots, job_id, directory, hops, launch, calls = prepared_path
    monkeypatch.setattr(sequence, '_checkpoint', lambda *_: (_ for _ in ()).throw(ProcessInterrupted()))
    with pytest.raises(ProcessInterrupted):
        sequence.execute_sequence(roots, job_id, launcher=launch)
    before = business(roots)
    result = sequence.stop_sequence(roots, job_id, launcher=launch)
    assert result['result_code'] == 'SYSTEM_UPDATE_SEQUENCE_STOPPED'
    assert business(roots) == before
    assert sequence.read_current_release_result_from_state_root(roots.STATE_ROOT).release.release_id == hops[0]['release_id']
    assert (hops[1]['release_id'], 'start') not in calls
    assert not (roots.STATE_ROOT / sequence.ACTIVE_NAME).exists()


def test_final_checkpoint_can_finish_after_coordinator_exits(prepared_path, monkeypatch):
    roots, job_id, directory, hops, launch, calls = prepared_path
    def interrupt(stage, completed):
        if completed == len(hops):
            raise ProcessInterrupted()
    monkeypatch.setattr(sequence, "_checkpoint", interrupt)
    with pytest.raises(ProcessInterrupted):
        sequence.execute_sequence(roots, job_id, launcher=launch)
    assert sequence.resume_sequence(roots, job_id, launcher=launch) is None
    assert sequence.public_sequence(roots, job_id)["state"] == "SUCCEEDED"
    assert not (roots.STATE_ROOT / sequence.ACTIVE_NAME).exists()


def test_registration_changes_only_owned_version_and_preserves_existing_uninstaller(installed):
    import winreg
    from enterprise.runtime.windows_install_registration import verify_registration, update_registration_version
    roots = installed["roots"]
    installation_id = json.loads((roots.STATE_ROOT / "installation.json").read_bytes())["installation_id"]
    uninstall_key = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\InfiniteCanvasEnterprise-' + installation_id + '_is1'
    locator_key = 'Software\\Infinite-Canvas-Enterprise\\Installations\\' + installation_id
    for key in (uninstall_key, locator_key):
        with pytest.raises(FileNotFoundError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, key)
    uninstaller = roots.STATE_ROOT / 'windows-uninstaller/unins000.exe'
    uninstaller.parent.mkdir()
    uninstaller.write_bytes(b'MZ-C7-unit-uninstaller-not-GUI-evidence')
    support = roots.INSTALL_ROOT / sequence.SLOTS['support']
    support.parent.mkdir()
    support.write_text('[Lifecycle]\nUninstaller=unins000.exe\nUninstallerSha256=' +
                       hashlib.sha256(uninstaller.read_bytes()).hexdigest() + '\n', encoding='utf-8')
    values = {'DisplayVersion': '2026.07.6', 'Publisher': 'MEIS-DaCaiTou', 'InstallLocation': str(roots.INSTALL_ROOT),
              'UninstallString': '"' + str(uninstaller) + '"', 'DisplayName': 'ICE C7 synthetic registry fixture'}
    locator = {'InstallLocation': str(roots.INSTALL_ROOT), 'Launcher': str(roots.INSTALL_ROOT / 'InfiniteCanvas.exe'),
               'C7TestOwner': installation_id}
    created = []
    try:
        for key, data in ((uninstall_key, values), (locator_key, locator)):
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_WRITE) as handle:
                created.append((key, data))
                for name, value in data.items():
                    winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)
        verify_registration(roots.INSTALL_ROOT, installation_id, expected_version='2026.07.6')
        update_registration_version(roots.INSTALL_ROOT, installation_id, source_version='2026.07.6', target_version='2026.07.7')
        update_registration_version(roots.INSTALL_ROOT, installation_id, source_version='2026.07.6', target_version='2026.07.7')
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key) as handle:
            assert winreg.QueryValueEx(handle, 'DisplayVersion')[0] == '2026.07.7'
            for name in ('Publisher', 'InstallLocation', 'UninstallString'):
                assert winreg.QueryValueEx(handle, name)[0] == values[name]
        with pytest.raises(files.CacheError):
            update_registration_version(roots.INSTALL_ROOT, installation_id, source_version='2026.07.5', target_version='2026.07.8')
        verify_registration(roots.INSTALL_ROOT, installation_id, expected_version='2026.07.7')
    finally:
        for key, data in reversed(created):
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                # Only this randomly identified, newly created test registration.
                for name in data:
                    if name != 'DisplayVersion':
                        assert winreg.QueryValueEx(handle, name)[0] == data[name]
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
