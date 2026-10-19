"""Small owned fixtures: real verifiers, SQLite and Windows object moves.

Only Runtime process launch is substituted. MZ unit entries/Setups do not prove
native compilation, full installed-copy execution, or GUI acceptance.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from enterprise import install_upgrade as upgrade, install_lifecycle as lifecycle, install_cache as files
from enterprise.install_entry import publish_fixed_entry
from enterprise.migrations.versioned import DEFAULT_MIGRATIONS, initialize_schema_metadata_in_transaction, migration_registry_sha256, schema_snapshot_sha256, schema_objects
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.release_manifest_v2 import canonical_json, materialize_release_fixture
from enterprise.tests.test_install_entry import bundle, qualified_program_fixture
from enterprise.tests.test_ops_release_manifest_v2 import _rebind_fixture

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native-object adapter")


class Interrupted(BaseException):
    pass


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root, manifest, archive, inventory, doc = qualified_program_fixture(tmp_path / "source")
    db = root / "data/enterprise.db"
    db.unlink()
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE business(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO business VALUES(1,'retained-business')")
        initialize_schema_metadata_in_transaction(conn)
        conn.commit()
        schema_sha = schema_snapshot_sha256(conn)
        objects = schema_objects(conn)
    evidence = {"schema_id": "enterprise-database-contract-v1", "migration_ids": doc["database_contract"]["migration_ids"],
        "objects": objects, "schema_version": 1, "schema_objects_sha256": schema_sha,
        "migration_registry_sha256": migration_registry_sha256(DEFAULT_MIGRATIONS),
        "versioned_migration_ids": [step.migration_id for step in DEFAULT_MIGRATIONS]}
    payload = manifest.parent / "payload"
    (payload / "release-evidence/database-schema.json").write_bytes(canonical_json(evidence))
    doc["database_contract"].update(migration_compatibility="same-schema-no-migration",
        rollback_classification="code-release-pointer", ops3b_activation_eligible=True)
    _rebind_fixture(manifest, archive, inventory, doc)
    # Replace only this newly owned fixture's pre-seeded program, before any
    # installation identity or maintenance transaction has been published.
    app = root / "releases" / doc["identity"]["release_id"]
    shutil.rmtree(app)
    materialize_release_fixture(manifest, archive, inventory, app)
    pointer = json.loads((root / "state/current-release.json").read_bytes())
    pointer["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    (root / "state/current-release.json").write_bytes(canonical_json(pointer))
    local = tmp_path / "local"
    roots = derive_portable_path_roots(PortableRootInputs(root, local), app.name)
    entry = bundle(tmp_path / "old-entry", b"old", doc["enterprise_source"]["commit"], doc["enterprise_source"]["tree"])
    publication = publish_fixed_entry(roots, entry); publication.complete()
    (root / "data/canvas.json").write_bytes(b'{"customer":"retained"}')
    (root / "data/media.bin").write_bytes(b"retained-media")
    assets = tmp_path / "source-assets"; assets.mkdir()
    for source in (manifest, archive, inventory):
        shutil.copyfile(source, assets / ("ops-release-manifest-v2.json" if source == manifest else source.name))
    target_area = tmp_path / "target-area"; target_area.mkdir()
    target_payload = target_area / "payload"; shutil.copytree(payload, target_payload)
    target_doc = json.loads(json.dumps(doc))
    target_id = "ice-2026.07.7-" + "d" * 12
    target_doc["identity"].update(release_id=target_id, release_version="2026.07.7")
    target_doc["enterprise_source"].update(commit="d" * 40, version="2026.07.7")
    target_doc["archive"].update(filename=f"Infinite-Canvas-Enterprise-{target_id}-win-x64.zip", root_prefix="Infinite-Canvas-Enterprise-" + target_id)
    target_manifest = target_area / "ops-release-manifest-v2.json"
    target_inventory = target_area / "release-payload-inventory.json"
    target_archive = target_area / target_doc["archive"]["filename"]
    _rebind_fixture(target_manifest, target_archive, target_inventory, target_doc)
    target_assets = tmp_path / "target-assets"; target_assets.mkdir()
    for path in (target_manifest, target_archive, target_inventory):
        shutil.copyfile(path, target_assets / path.name)
    new_entry = bundle(tmp_path / "new-entry", b"new", "d" * 40, target_doc["enterprise_source"]["tree"])
    setup = tmp_path / "synthetic-setup.exe"; setup.write_bytes(b"MZ-unit-setup-not-executable")
    monkeypatch.setattr(lifecycle, "_runtime_quiescent", lambda _roots: None)
    calls = []
    def launch(app_root, command):
        calls.append((app_root.name, command))
        return 0, {"result": "healthy" if command == "health" else "stopped" if command == "stop" else "started"}
    monkeypatch.setattr(upgrade.mvp, "_run_launcher", launch)
    return dict(roots=roots, source_assets=assets, target_assets=target_assets, local=local,
        old_entry=entry, new_entry=new_entry, setup=setup, calls=calls)


def arguments(fixture):
    return dict(install_root=fixture["roots"].INSTALL_ROOT, release_dir=fixture["target_assets"],
        native_entry_dir=fixture["new_entry_dir"] if "new_entry_dir" in fixture else fixture["setup"].parent / "new-entry",
        setup_executable=fixture["setup"], local_app_data_base=fixture["local"], confirm_no_active_tasks=True)


def protected(fixture):
    root = fixture["roots"].INSTALL_ROOT
    return {p.relative_to(root).as_posix(): p.read_bytes() for area in (root / "data", root / "config")
            for p in area.rglob("*") if p.is_file()}


def finish(fixture):
    return upgrade.finish_upgrade(install_root=fixture["roots"].INSTALL_ROOT, release_dir=fixture["target_assets"],
        local_app_data_base=fixture["local"], verify_registration=lambda *_: None)


@pytest.mark.parametrize("target_failure", [False, True])
def test_page_upgraded_source_without_registration_uses_existing_entry_repair(installed, monkeypatch, target_failure):
    from enterprise import install_entry_repair
    from enterprise.install_entry import repair_fixed_entry
    f = installed; roots = f["roots"]
    (roots.STATE_ROOT / "installation.json").unlink()
    (roots.STATE_ROOT / "native-entry.json").write_bytes(canonical_json({
        "schema_version": "enterprise-native-entry-v1", "launcher_sha256": f["old_entry"].sha256}))
    before = protected(f)
    pointer_before = (roots.STATE_ROOT / "current-release.json").read_bytes()
    args = dict(install_root=roots.INSTALL_ROOT, release_dir=f["target_assets"], local_app_data_base=f["local"])
    with pytest.raises(lifecycle.LifecycleError, match="INSTALL_LIFECYCLE_IDENTITY_REQUIRED"):
        upgrade.inspect_upgrade(**args)
    entry_args = dict(install_root=roots.INSTALL_ROOT, entry=f["new_entry"], local_app_data_base=f["local"])
    assert install_entry_repair.inspect_fixed_entry(**entry_args)["entry_state"] == "REGISTRATION_REQUIRED"
    assert not (roots.STATE_ROOT / "installation.json").exists()
    monkeypatch.setattr(install_entry_repair, "_runtime_quiescent", lambda _: None)
    assert repair_fixed_entry(**entry_args)["repair_state"] == "SUCCEEDED"
    assert (roots.STATE_ROOT / "current-release.json").read_bytes() == pointer_before
    assert protected(f) == before
    assert upgrade.inspect_upgrade(**args)["upgrade_state"] == "ELIGIBLE"
    installation = (roots.STATE_ROOT / "installation.json").read_bytes()
    if target_failure:
        monkeypatch.setattr(upgrade.mvp, "_run_launcher", lambda app, command:
            (2, {"code": "SYSTEM_UPDATE_TARGET_HEALTH_FAILED"})
            if command == "health" and app.name.startswith("ice-2026.07.7-")
            else (0, {"result": "stopped"}))
    result = upgrade.upgrade_retained(**arguments(f))
    if target_failure:
        assert result["upgrade_state"] == "ROLLED_BACK"
        # Rollback reactivates the original source with a new activation time.
        current = json.loads((roots.STATE_ROOT / "current-release.json").read_bytes())
        source = json.loads(pointer_before)
        assert {key: current[key] for key in ("release_id", "manifest_sha256", "app_root_relative", "schema_version")} == {
            key: source[key] for key in ("release_id", "manifest_sha256", "app_root_relative", "schema_version")}
        assert current["previous_release_id"] == result["target_release_id"]
        assert (roots.STATE_ROOT / "installation.json").read_bytes() == installation
    else:
        assert result["upgrade_state"] == "AWAITING_REGISTRATION"
        assert finish(f)["upgrade_state"] == "COMPLETE"
    assert protected(f) == before


@pytest.mark.parametrize("retained", [False, True])
def test_shared_upgrade_changes_program_and_native_tools_preserves_business_and_identity(installed, retained):
    f = installed; root = f["roots"].INSTALL_ROOT
    before = protected(f)
    identity = json.loads((root / "state/installation.json").read_bytes())["installation_id"]
    if retained:
        lifecycle.uninstall_retaining_data(install_root=root, release_dir=f["source_assets"], local_app_data_base=f["local"], confirm_no_active_tasks=True)
    result = upgrade.upgrade_retained(**arguments(f))
    assert result["upgrade_state"] == "AWAITING_REGISTRATION"
    assert result["installation_id"] == identity and (root / upgrade.ACTIVE_NAME).exists() is False
    assert (root / "state" / upgrade.ACTIVE_NAME).exists()
    assert protected(f) == before
    assert (root / "InfiniteCanvas.exe").read_bytes() == f["new_entry"].data
    assert (root / "state/windows-maintenance/maintenance-setup.exe").read_bytes() == f["setup"].read_bytes()
    assert f["calls"] == [(result["target_release_id"], "start"), (result["target_release_id"], "health")]
    assert finish(f)["upgrade_state"] == "COMPLETE"
    assert not (root / "state" / upgrade.ACTIVE_NAME).exists()
    assert lifecycle.inspect_lifecycle(install_root=root, release_dir=f["target_assets"], local_app_data_base=f["local"])["lifecycle_state"] == "INSTALLED"
    assert protected(f) == before


@pytest.mark.parametrize("retained", [False, True])
@pytest.mark.parametrize("target_failure", [False, True])
def test_stopped_wal_mode_source_does_not_gain_sidecars_from_shared_reads(installed, monkeypatch, retained, target_failure):
    f = installed; root = f["roots"].INSTALL_ROOT
    database = root / "data/enterprise.db"
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    before = protected(f)
    if target_failure:
        def launch(app_root, command):
            return (2, {"code": "SYSTEM_UPDATE_TARGET_HEALTH_FAILED"}) if command == "health" and app_root.name.startswith("ice-2026.07.7-") else (0, {"result": "stopped"})
        monkeypatch.setattr(upgrade.mvp, "_run_launcher", launch)
    if retained:
        lifecycle.uninstall_retaining_data(install_root=root, release_dir=f["source_assets"], local_app_data_base=f["local"], confirm_no_active_tasks=True)
    result = upgrade.upgrade_retained(**arguments(f))
    assert result["upgrade_state"] == ("ROLLED_BACK" if target_failure else "AWAITING_REGISTRATION")
    assert protected(f) == before
    assert all(not database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))


@pytest.mark.parametrize("field", list(upgrade.SLOTS))
def test_interrupted_native_field_publication_recovers_original_objects_without_db_restore(installed, monkeypatch, field):
    f = installed; root = f["roots"].INSTALL_ROOT
    before = protected(f)
    original = files._file(root / "InfiniteCanvas.exe")
    def die(stage):
        if stage == field + "_published":
            raise Interrupted()
    monkeypatch.setattr(upgrade, "_checkpoint", die)
    with pytest.raises(Interrupted):
        upgrade.upgrade_retained(**arguments(f))
    monkeypatch.setattr(upgrade, "_checkpoint", lambda _stage: None)
    result = upgrade.recover_upgrade(install_root=root, release_dir=f["target_assets"], local_app_data_base=f["local"], confirm_no_active_tasks=True)
    assert result["upgrade_state"] == "ROLLED_BACK"
    assert files._file(root / "InfiniteCanvas.exe") == original
    assert protected(f) == before
    assert not (root / "state/system-update-active.lock").exists()
    assert not (root / "state" / upgrade.ACTIVE_NAME).exists()


def test_target_health_failure_restores_native_objects_before_source_start(installed, monkeypatch):
    f = installed; root = f["roots"].INSTALL_ROOT
    before = files._file(root / "InfiniteCanvas.exe")
    def launch(app_root, command):
        if app_root.name != f["roots"].APP_ROOT.name and command == "health":
            return 2, {"code": "RUNTIME_HEALTH_FAILED"}
        if app_root.name == f["roots"].APP_ROOT.name and command == "start":
            assert files._file(root / "InfiniteCanvas.exe") == before
        return 0, {"result": "ok"}
    monkeypatch.setattr(upgrade.mvp, "_run_launcher", launch)
    result = upgrade.upgrade_retained(**arguments(f))
    assert result["upgrade_state"] == "ROLLED_BACK" and files._file(root / "InfiniteCanvas.exe") == before


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_task_confirmation_is_typed_and_required_before_any_upgrade_writes(installed, value):
    f = installed
    with pytest.raises(upgrade.InstallUpgradeError, match="TASK_CONFIRMATION_REQUIRED"):
        upgrade.upgrade_retained(**(arguments(f) | {"confirm_no_active_tasks": value}))
    assert not (f["roots"].STATE_ROOT / "install-upgrades").exists()


def test_untrusted_setup_and_native_bundle_refuse_before_source_restoration(installed):
    f = installed; root = f["roots"].INSTALL_ROOT
    f["setup"].write_bytes(b"not-an-executable")
    with pytest.raises(upgrade.InstallUpgradeError, match="SETUP_UNPROVEN"):
        upgrade.upgrade_retained(**arguments(f))
    assert not (root / "state/install-upgrades").exists()


@pytest.mark.parametrize("stage", ["active_published", "fence_published", "source_fenced", "job_bound", "upgrade_ready"])
@pytest.mark.parametrize("retained", [False, True])
def test_pre_execution_interruption_never_loses_startup_fence_or_original_data(installed, monkeypatch, stage, retained):
    f = installed; root = f["roots"].INSTALL_ROOT
    before = protected(f)
    if retained:
        lifecycle.uninstall_retaining_data(install_root=root, release_dir=f["source_assets"], local_app_data_base=f["local"], confirm_no_active_tasks=True)
    def die(value):
        if value == stage:
            raise Interrupted()
    monkeypatch.setattr(upgrade, "_checkpoint", die)
    with pytest.raises(Interrupted):
        upgrade.upgrade_retained(**arguments(f))
    monkeypatch.setattr(upgrade, "_checkpoint", lambda _stage: None)
    result = upgrade.recover_upgrade(install_root=root, release_dir=f["target_assets"], local_app_data_base=f["local"], confirm_no_active_tasks=True)
    assert result["upgrade_state"] == "ROLLED_BACK"
    assert protected(f) == before and (root / "InfiniteCanvas.exe").read_bytes() == f["old_entry"].data
    assert not (root / "state/system-update-active.lock").exists()


def interrupted_at(fixture, monkeypatch, phase):
    def die(value):
        if value == phase:
            raise Interrupted()
    monkeypatch.setattr(upgrade, "_checkpoint", die)
    with pytest.raises(Interrupted):
        upgrade.upgrade_retained(**arguments(fixture))
    monkeypatch.setattr(upgrade, "_checkpoint", lambda _stage: None)


def test_successful_upgrade_cannot_be_rolled_back_when_registration_is_interrupted(installed, monkeypatch):
    f = installed; root = f["roots"].INSTALL_ROOT
    interrupted_at(f, monkeypatch, "awaiting_registration")
    calls = list(f["calls"])
    # Inno appends the proven uninstaller receipt to the same support object.
    with (root / "state/windows-maintenance/support.ini").open("ab") as stream:
        stream.write(b"Uninstaller=unins000.exe\nUninstallerSha256=" + b"a" * 64 + b"\n")
    recovered = upgrade.recover_upgrade(install_root=root, release_dir=f["target_assets"], local_app_data_base=f["local"], confirm_no_active_tasks=True)
    assert recovered["upgrade_state"] == "AWAITING_REGISTRATION" and f["calls"] == calls
    assert (root / "InfiniteCanvas.exe").read_bytes() == f["new_entry"].data
    assert finish(f)["upgrade_state"] == "COMPLETE"


def test_copied_candidate_same_bytes_has_no_original_object_authority(installed, monkeypatch):
    f = installed; root = f["roots"].INSTALL_ROOT
    interrupted_at(f, monkeypatch, "entry_published")
    entry = root / "InfiniteCanvas.exe"
    # Keep the original object at an unexpected location, replace only this
    # owned test candidate with a distinct file holding identical bytes.
    displaced = root / "displaced-entry"; entry.rename(displaced); shutil.copyfile(displaced, entry)
    copied = files._file(entry)
    with pytest.raises(upgrade.InstallUpgradeError, match="TOOL_CHANGED"):
        upgrade.recover_upgrade(install_root=root, release_dir=f["target_assets"], local_app_data_base=f["local"], confirm_no_active_tasks=True)
    assert files._file(entry) == copied and displaced.exists()
    assert (root / "state" / upgrade.ACTIVE_NAME).exists()


def test_identical_foreign_fence_is_not_adopted_or_deleted(installed, monkeypatch):
    f = installed; root = f["roots"].INSTALL_ROOT
    interrupted_at(f, monkeypatch, "fence_published")
    lock = root / "state/system-update-active.lock"
    owned = root / "state/displaced-fence"; lock.rename(owned); shutil.copyfile(owned, lock)
    foreign = files._file(lock)
    with pytest.raises(upgrade.InstallUpgradeError, match="FENCE_CHANGED"):
        upgrade.recover_upgrade(install_root=root, release_dir=f["target_assets"], local_app_data_base=f["local"], confirm_no_active_tasks=True)
    assert files._file(lock) == foreign and owned.exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_sqlite_sidecar_refuses_before_any_upgrade_publication(installed, suffix):
    f = installed; root = f["roots"].INSTALL_ROOT
    (root / ("data/enterprise.db" + suffix)).write_bytes(b"do-not-recover-implicitly")
    with pytest.raises(lifecycle.LifecycleError):
        upgrade.upgrade_retained(**arguments(f))
    assert not (root / "state/install-upgrades").exists()


def test_unowned_source_entry_refuses_before_any_upgrade_publication(installed):
    f = installed; root = f["roots"].INSTALL_ROOT
    (root / "InfiniteCanvas.exe").write_bytes(b"MZ-unowned")
    with pytest.raises(upgrade.InstallUpgradeError, match="SOURCE_ENTRY_UNPROVEN"):
        upgrade.upgrade_retained(**arguments(f))
    assert not (root / "state/install-upgrades").exists()
