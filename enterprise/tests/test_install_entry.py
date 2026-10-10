"""Entry publication/repair contracts; MZ unit bytes are not a compiled EXE."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from enterprise import install_entry as delivery
from enterprise.install_setup_bridge import MAINTENANCE_REQUEST_SCHEMA, SetupBridgeError, _decode_request
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.release_manifest_v2 import (
    build_inventory, canonical_json, git_blob_sha1, materialize_release_fixture,
)
from enterprise.tests.test_install_mvp_1 import _assets, _fake_materialize, FIXTURE_PASSWORD
from enterprise.tests.test_ops_release_manifest_v2 import _fixture, _rebind_fixture


def bundle(root: Path, label: bytes = b"fixture", commit: str = "b" * 40, tree: str = "c" * 40):
    root.mkdir(parents=True)
    data = b"MZ-unit-fixture-only-" + label
    (root / delivery.ENTRY_NAME).write_bytes(data)
    record = {
        "schema_version": "enterprise-native-entry-build-record-v1",
        "source_commit": commit, "source_tree": tree, "dirty_experimental_build": False,
        "policy_sha256": "a" * 64, "source_files_sha256": {name: "a" * 64 for name in
            ("NativeCore.cs", "LauncherProgram.cs", "app.manifest")},
        "compiler_package_sha256": delivery.COMPILER_PACKAGE_SHA, "compiler_sha256": "a" * 64,
        "deterministic_double_build": True, "signed": False,
        "executable": {"filename": delivery.ENTRY_NAME, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)},
    }
    (root / "native-entry-build-record.json").write_bytes(canonical_json(record))
    return delivery.verify_entry_bundle(root)


def install_roots(tmp_path):
    roots = derive_portable_path_roots(PortableRootInputs(tmp_path / "安装 空格", tmp_path / "local"), "source-release")
    for path in (roots.APP_ROOT, roots.DATA_ROOT, roots.CONFIG_ROOT, roots.STATE_ROOT):
        path.mkdir(parents=True)
    for path in (roots.DATA_ROOT / "enterprise.db", roots.DATA_ROOT / "canvas.json",
                 roots.DATA_ROOT / "image.bin", roots.CONFIG_ROOT / "enterprise.env",
                 roots.STATE_ROOT / "current-release.json"):
        path.write_bytes(b"untouched-business-fixture")
    return roots


def business(roots):
    return {str(path): path.read_bytes() for area in (roots.DATA_ROOT, roots.CONFIG_ROOT)
            for path in area.rglob('*') if path.is_file()} | {
                "pointer": (roots.STATE_ROOT / "current-release.json").read_bytes()}


@pytest.mark.parametrize("change", ["dirty", "signed", "double", "boolean_size", "wrong_hash", "wrong_source", "extra", "duplicate", "exe"])
def test_unverified_native_bundle_is_rejected_without_install_writes(tmp_path, change):
    path = tmp_path / "bundle"
    bundle(path)
    record_file = path / "native-entry-build-record.json"
    record = json.loads(record_file.read_bytes())
    if change in {"dirty", "signed"}: record[{"dirty": "dirty_experimental_build", "signed": "signed"}[change]] = True
    elif change == "double": record["deterministic_double_build"] = 1
    elif change == "boolean_size": record["executable"]["size_bytes"] = True
    elif change == "wrong_hash": record["executable"]["sha256"] = "d" * 64
    elif change == "wrong_source": record["source_commit"] = "d" * 40
    elif change == "extra": record["unreviewed"] = True
    elif change == "exe": (path / delivery.ENTRY_NAME).write_bytes(b"changed")
    record_file.write_bytes(canonical_json(record))
    if change == "duplicate": record_file.write_bytes(record_file.read_bytes().replace(b'"signed":false', b'"signed":false,"signed":false'))
    with pytest.raises(delivery.InstallEntryError):
        delivery.verify_entry_bundle(path, commit="b" * 40, tree="c" * 40)
    assert not (tmp_path / "install").exists()


def test_stable_instance_and_entry_only_repair_are_idempotent(tmp_path):
    roots = install_roots(tmp_path)
    first = bundle(tmp_path / "native-a")
    before = business(roots)
    publication = delivery.publish_fixed_entry(roots, first)
    publication.complete()
    identity = publication.installation_id
    after_first = {str(p): p.read_bytes() for p in roots.INSTALL_ROOT.rglob('*') if p.is_file()}
    second = delivery.publish_fixed_entry(roots, first)
    second.complete()
    assert second.installation_id == identity
    assert {str(p): p.read_bytes() for p in roots.INSTALL_ROOT.rglob('*') if p.is_file()} == after_first
    newer = bundle(tmp_path / "native-b", b"newer")
    third = delivery.publish_fixed_entry(roots, newer)
    third.complete()
    assert third.installation_id == identity
    assert (roots.INSTALL_ROOT / delivery.ENTRY_NAME).read_bytes() == newer.data
    assert business(roots) == before


@pytest.mark.parametrize("change", ["foreign_exe", "foreign_record", "moved_record", "busy_lock", "broken_link"])
def test_foreign_or_uncertain_install_entry_is_not_overwritten(tmp_path, change):
    roots = install_roots(tmp_path)
    entry = bundle(tmp_path / "native")
    if change == "foreign_exe": (roots.INSTALL_ROOT / delivery.ENTRY_NAME).write_bytes(b"other-project-exe")
    elif change == "foreign_record": (roots.STATE_ROOT / delivery.RECORD_NAME).write_bytes(b"other-project-record")
    elif change == "busy_lock": (roots.STATE_ROOT / "system-update-active.lock").write_bytes(b"unresolved-lock")
    elif change == "moved_record":
        publication = delivery.publish_fixed_entry(roots, entry); publication.complete()
        path = roots.STATE_ROOT / delivery.RECORD_NAME
        value = json.loads(path.read_bytes()); value["install_root"] = str(tmp_path / "another project")
        path.write_bytes(canonical_json(value))
    else:
        try: (roots.INSTALL_ROOT / delivery.ENTRY_NAME).symlink_to(tmp_path / "absent")
        except OSError: pytest.skip("Windows symlink permission is unavailable")
    before = {str(p): p.read_bytes() for p in roots.INSTALL_ROOT.rglob('*') if p.is_file() and not p.is_symlink()}
    with pytest.raises(delivery.InstallEntryError): delivery.publish_fixed_entry(roots, entry)
    assert {str(p): p.read_bytes() for p in roots.INSTALL_ROOT.rglob('*') if p.is_file() and not p.is_symlink()} == before


def test_metadata_failure_restores_owned_entry_without_touching_business(monkeypatch, tmp_path):
    roots = install_roots(tmp_path)
    first = bundle(tmp_path / "native-a")
    publication = delivery.publish_fixed_entry(roots, first); publication.complete()
    record_path = roots.STATE_ROOT / delivery.RECORD_NAME
    record_before = record_path.read_bytes()
    before = business(roots)
    original = delivery._atomic_publish
    def fail_record(path, data, expected):
        if path == record_path: raise OSError("injected metadata write failure")
        return original(path, data, expected)
    monkeypatch.setattr(delivery, "_atomic_publish", fail_record)
    with pytest.raises(delivery.InstallEntryError, match="INSTALL_ENTRY_PUBLISH_FAILED"):
        delivery.publish_fixed_entry(roots, bundle(tmp_path / "native-b", b"newer"))
    assert (roots.INSTALL_ROOT / delivery.ENTRY_NAME).read_bytes() == first.data
    assert record_path.read_bytes() == record_before
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()
    assert business(roots) == before


def test_failed_restore_keeps_blocking_evidence(monkeypatch, tmp_path):
    roots = install_roots(tmp_path)
    publication = delivery.publish_fixed_entry(roots, bundle(tmp_path / "native-a")); publication.complete()
    original = delivery._atomic_publish
    calls = 0
    def fail_restore(path, data, expected):
        nonlocal calls
        if path == roots.STATE_ROOT / delivery.RECORD_NAME: raise OSError("injected")
        calls += 1
        if calls > 1: raise OSError("injected restore failure")
        return original(path, data, expected)
    monkeypatch.setattr(delivery, "_atomic_publish", fail_restore)
    before = business(roots)
    entry = bundle(tmp_path / "native-b", b"newer")
    with pytest.raises(delivery.InstallEntryError, match="INSTALL_ENTRY_RECOVERY_REQUIRED"):
        delivery.publish_fixed_entry(roots, entry)
    lock = roots.STATE_ROOT / "system-update-active.lock"
    evidence = lock.read_bytes()
    with pytest.raises(delivery.InstallEntryError, match="INSTALL_ENTRY_MAINTENANCE_BUSY"):
        delivery.publish_fixed_entry(roots, entry)
    assert lock.read_bytes() == evidence and business(roots) == before


@pytest.mark.parametrize("fail_pointer", [False, True])
def test_fresh_install_publishes_entry_before_pointer_and_undoes_precommit_failure(monkeypatch, tmp_path, fail_pointer):
    from enterprise import fresh_install as fresh
    assets = _assets()
    original_section = assets.manifest.section
    assets.manifest.section = lambda name: {"commit": "b" * 40, "tree": "c" * 40} if name == "enterprise_source" else original_section(name)
    monkeypatch.setattr(fresh, "verify_release_assets", lambda path: assets)
    monkeypatch.setattr(fresh, "validate_entry_target_paths", lambda *args: None)
    monkeypatch.setattr(fresh, "materialize_release_fixture", _fake_materialize)
    bundle(tmp_path / "native")
    root = tmp_path / "new install"
    original_pointer = fresh.atomic_write_current_release
    def pointer_last(roots, pointer, **kwargs):
        assert (root / delivery.ENTRY_NAME).is_file()
        assert (root / "state" / delivery.RECORD_NAME).is_file()
        assert (root / "data/enterprise.db").is_file()
        if fail_pointer: raise OSError("injected pointer failure")
        return original_pointer(roots, pointer, **kwargs)
    monkeypatch.setattr(fresh, "atomic_write_current_release", pointer_last)
    arguments = dict(release_dir=tmp_path / "assets", install_root=root, username="fixture-admin",
                     password=FIXTURE_PASSWORD, password_confirmation=FIXTURE_PASSWORD,
                     local_app_data_base=tmp_path / "local", native_entry_dir=tmp_path / "native")
    if fail_pointer:
        with pytest.raises(fresh.FreshInstallError, match="INSTALL_FAILED"): fresh.install_greenfield(**arguments)
        assert not root.exists()
    else:
        result = fresh.install_greenfield(**arguments)
        assert result.launcher_installed and result.installation_id
        assert json.loads((root / "state/installation.json").read_bytes())["installation_id"] == result.installation_id
        assert not (root / "state/system-update-active.lock").exists()


def qualified_program_fixture(tmp_path):
    manifest, archive, inventory, document = _fixture(tmp_path / "assets")
    # The verifier fixture intentionally omits a runnable application. Add the
    # portable layout without bypassing any source/policy/inventory bindings.
    source = manifest.parent / "app-source"
    payload = manifest.parent / "payload"
    for path in (source / "main.py", payload / "main.py"):
        path.write_bytes(b"# non-running portable layout fixture\n")
    source_inventory = build_inventory(source)
    (payload / "release-evidence/app-source-inventory.json").write_bytes(source_inventory.canonical_bytes)
    document["release_payload"]["app_source_tree_sha256"] = source_inventory.tree_sha256
    policy_path = payload / "release-evidence/release-payload-policy.json"
    policy = json.loads(policy_path.read_bytes())
    policy["included_root_files"].append("main.py")
    policy_path.write_bytes(canonical_json(policy))
    document["payload_policy"]["git_blob_sha1"] = git_blob_sha1(policy_path.read_bytes())
    _rebind_fixture(manifest, archive, inventory, document)
    root = tmp_path / "installed"
    app = root / "releases" / str(document["identity"]["release_id"])
    materialize_release_fixture(manifest, archive, inventory, app)
    (root / "state").mkdir()
    (root / "data").mkdir()
    (root / "config").mkdir()
    (root / "data/enterprise.db").write_bytes(b"opaque-database-never-opened")
    (root / "config/enterprise.env").write_bytes(b"preserve-settings")
    pointer = canonical_json({"schema_version": "env-1b1b-current-release-v1",
        "release_id": app.name, "app_root_relative": "releases/" + app.name,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "activated_at": "2026-10-05T00:00:00Z", "previous_release_id": None})
    (root / "state/current-release.json").write_bytes(pointer)
    return root, manifest, archive, inventory, document


@pytest.mark.parametrize("recovery_race", [False, True])
def test_entry_repair_uses_real_release_verifier_and_leaves_database_and_pointer_untouched(tmp_path, monkeypatch, recovery_race):
    root, manifest, archive, inventory, document = qualified_program_fixture(tmp_path)
    app = root / "releases" / str(document["identity"]["release_id"])
    from enterprise import install_entry_repair as recovery
    monkeypatch.setattr(recovery, "_runtime_quiescent", lambda roots: None)
    source = document["enterprise_source"]
    entry = bundle(tmp_path / "native", commit=source["commit"], tree=source["tree"])
    roots = derive_portable_path_roots(PortableRootInputs(root, tmp_path / "local"), app.name)
    publication = delivery.publish_fixed_entry(roots, entry)
    publication.complete()
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    if recovery_race:
        from enterprise.ops.update.mvp import UpdateJobStore
        inspections = 0
        def pending(self, **kwargs):
            nonlocal inspections
            inspections += 1
            return [] if inspections == 1 else ["unresolved-update"]
        monkeypatch.setattr(UpdateJobStore, "pending_recovery_jobs", pending)
        with pytest.raises(delivery.InstallEntryError, match="RECOVERY_REQUIRED"):
            delivery.repair_fixed_entry(install_root=root, entry=entry, local_app_data_base=tmp_path / "local")
        assert all(Path(p).read_bytes() == data for p, data in before.items())
        assert (root / "state/system-update-active.lock").exists()
        return
    result = delivery.repair_fixed_entry(install_root=root, entry=entry, local_app_data_base=tmp_path / "local")
    assert result["database_changed"] is result["pointer_changed"] is False
    assert all(Path(p).read_bytes() == data for p, data in before.items())
    assert result["repair_state"] == "SUCCEEDED"
    assert not (root / "state/system-update-active.lock").exists()
    (app / "foreign.py").write_bytes(b"unowned import")
    snapshot = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with pytest.raises(delivery.InstallEntryError, match="INSTALL_ENTRY_SOURCE_INVALID"):
        delivery.repair_fixed_entry(install_root=root, entry=bundle(tmp_path / "native2", b"newer", source["commit"], source["tree"]), local_app_data_base=tmp_path / "local")
    assert {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()} == snapshot


@pytest.mark.parametrize("operation", ["repair-entry", "recover-entry"])
def test_maintenance_request_requires_explicit_operation_and_no_repair_password(operation):
    value = {"schema_version": MAINTENANCE_REQUEST_SCHEMA, "operation": operation,
             "install_mode": "custom", "install_root": "C:\\fixture install", "username": "",
             "password": "", "password_confirmation": ""}
    assert _decode_request(canonical_json(value)) == value
    for change in ({"operation": "arbitrary"}, {"password": "not-accepted"}, {"unknown": True}):
        with pytest.raises(SetupBridgeError): _decode_request(canonical_json(value | change))


def test_too_deep_setup_target_is_blocked_before_installation_writes(tmp_path):
    manifest, _archive, inventory, document = _fixture(tmp_path / "assets")
    root = tmp_path / ("x" * 150)
    with pytest.raises(delivery.InstallEntryError, match="INSTALL_ENTRY_TARGET_PATH_TOO_LONG"):
        delivery.validate_entry_target_paths(root, document["identity"]["release_id"], inventory)
    assert not root.exists()
