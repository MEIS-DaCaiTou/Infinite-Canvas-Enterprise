"""Owned entry repair/recovery contracts; unit MZ bytes are not a native EXE.

Only OS quiescence is replaced in these tiny, non-runnable Release fixtures.
The separate full-payload Windows module exercises real process death, kernel
leases, Setup v2 and the compiled fixed entry. No customer database is opened.
"""
from __future__ import annotations

import json
import errno
import os
from pathlib import Path

import pytest

from enterprise import install_entry as entry
from enterprise import install_entry_repair as recovery
from enterprise.install_setup_bridge import (
    GRAPHICAL_MAINTENANCE_REQUEST_SCHEMA, MAINTENANCE_REQUEST_SCHEMA,
    SetupBridgeError, _decode_request,
)
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.release_manifest_v2 import canonical_json
from enterprise.tests.test_install_entry import bundle, qualified_program_fixture


class Interrupted(BaseException):
    """Simulate runner loss without exercising the ordinary exception rollback."""


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root, _manifest, _archive, _inventory, document = qualified_program_fixture(tmp_path)
    local = tmp_path / "local"
    roots = derive_portable_path_roots(PortableRootInputs(root, local), document["identity"]["release_id"])
    source = document["enterprise_source"]
    original = bundle(tmp_path / "native-original", b"original-owned-entry", source["commit"], source["tree"])
    publication = entry.publish_fixed_entry(roots, original)
    publication.complete()
    target = bundle(tmp_path / "native-target", b"replacement-owned-entry", source["commit"], source["tree"])
    monkeypatch.setattr(recovery, "_runtime_quiescent", lambda roots: None)
    return dict(install_root=root, entry=target, local_app_data_base=local), roots, original


def _files(root, *, exclude=()):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file() and path not in exclude}


def _business(roots):
    # The opaque database is never connected; preservation is byte-exact.
    result = {name + "/" + path: data for name in ("data", "config", "assets", "releases")
              for path, data in _files(roots.INSTALL_ROOT / name).items()}
    result["pointer"] = (roots.STATE_ROOT / "current-release.json").read_bytes()
    return result


def _published(roots):
    return {str(path): path.read_bytes() if path.exists() else None for path in (
        roots.INSTALL_ROOT / entry.ENTRY_NAME, roots.STATE_ROOT / entry.RECORD_NAME)}


def _journal(roots):
    marker = json.loads((roots.STATE_ROOT / "system-update-active.lock").read_bytes())
    return roots.STAGING_ROOT / "entry-repairs" / marker["operation_id"][:12]


def _interrupt(monkeypatch, arguments, checkpoint, *, recover=False):
    def interrupt(name):
        if name == checkpoint:
            raise Interrupted()
    monkeypatch.setattr(recovery, "_checkpoint", interrupt)
    operation = entry.recover_fixed_entry if recover else entry.repair_fixed_entry
    with pytest.raises(Interrupted):
        operation(**arguments)
    monkeypatch.setattr(recovery, "_checkpoint", lambda name: None)


def test_repair_changes_only_owned_entry_record_and_preserves_business_identity(installed):
    arguments, roots, original = installed
    before = _business(roots)
    identity = json.loads((roots.STATE_ROOT / entry.RECORD_NAME).read_bytes())["installation_id"]
    assert original.data != arguments["entry"].data
    result = entry.repair_fixed_entry(**arguments)
    assert result["repair_state"] == "SUCCEEDED"
    assert result["installation_id"] == identity
    assert result["database_changed"] is result["pointer_changed"] is False
    assert (roots.INSTALL_ROOT / entry.ENTRY_NAME).read_bytes() == arguments["entry"].data
    assert json.loads((roots.STATE_ROOT / entry.RECORD_NAME).read_bytes())["installation_id"] == identity
    assert _business(roots) == before
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()
    assert not (roots.RUNTIME_ROOT / "runtime-reconcile.lock").exists()
    # A fresh idempotent repair may retain a new owned journal, not business writes.
    published = _published(roots)
    assert entry.repair_fixed_entry(**arguments)["repair_state"] == "SUCCEEDED"
    assert _published(roots) == published and _business(roots) == before


@pytest.mark.parametrize("checkpoint", ["locked", "prepared", "entry_published", "record_published", "committed"])
def test_entry_interruption_has_exact_rollback_and_commit_boundary(installed, monkeypatch, checkpoint):
    arguments, roots, _original = installed
    before, published = _business(roots), _published(roots)
    _interrupt(monkeypatch, arguments, checkpoint)
    assert (roots.STATE_ROOT / "system-update-active.lock").is_file()
    result = entry.recover_fixed_entry(**arguments)
    expected = "SUCCEEDED" if checkpoint == "committed" else "ROLLED_BACK"
    assert result["repair_state"] == expected
    assert result["database_changed"] is result["pointer_changed"] is False
    if checkpoint == "committed":
        assert (roots.INSTALL_ROOT / entry.ENTRY_NAME).read_bytes() == arguments["entry"].data
    else:
        assert _published(roots) == published
    assert _business(roots) == before
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()
    assert not (roots.RUNTIME_ROOT / "runtime-reconcile.lock").exists()


@pytest.mark.parametrize("checkpoint", ["record_restored", "entry_restored"])
def test_recovery_interruption_can_resume_exact_owned_restoration(installed, monkeypatch, checkpoint):
    arguments, roots, _original = installed
    before, published = _business(roots), _published(roots)
    _interrupt(monkeypatch, arguments, "record_published")
    _interrupt(monkeypatch, arguments, checkpoint, recover=True)
    assert (roots.STATE_ROOT / "system-update-active.lock").is_file()
    assert entry.recover_fixed_entry(**arguments)["repair_state"] == "ROLLED_BACK"
    assert _published(roots) == published and _business(roots) == before
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()


@pytest.mark.parametrize("checkpoint", ["entry_published", "record_published"])
def test_observed_publication_failure_restores_owned_entry_without_business_writes(installed, monkeypatch, checkpoint):
    arguments, roots, _original = installed
    before, published = _business(roots), _published(roots)
    def fail(name):
        if name == checkpoint:
            raise OSError("fixture-only observed entry publication failure")
    monkeypatch.setattr(recovery, "_checkpoint", fail)
    with pytest.raises(entry.InstallEntryError):
        entry.repair_fixed_entry(**arguments)
    assert _published(roots) == published and _business(roots) == before
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()


@pytest.mark.parametrize("value", [b"foreign lock", canonical_json({
    "schema_version": "enterprise-entry-maintenance-lock-v1", "operation_id": "a" * 32,
    "installation_id": "b" * 32, "target_entry_sha256": "c" * 64,
    "previous_entry_sha256": "d" * 64, "previous_record_sha256": "e" * 64})])
def test_unknown_or_legacy_lock_is_never_adopted_or_deleted(installed, value):
    arguments, roots, _original = installed
    (roots.STATE_ROOT / "system-update-active.lock").write_bytes(value)
    before = _files(roots.INSTALL_ROOT)
    for operation in (entry.repair_fixed_entry, entry.recover_fixed_entry):
        with pytest.raises(entry.InstallEntryError):
            operation(**arguments)
        assert _files(roots.INSTALL_ROOT) == before


@pytest.mark.parametrize("name", ["lock", "common_marker", "plan", "candidate_entry", "candidate_record", "restore_entry",
                                  "restore_record", "pointer", "record", "entry", "fence", "retained_fence", "runner"])
@pytest.mark.parametrize("same_bytes_replacement", [False, True])
def test_uncertain_interruption_never_mutates_replaced_evidence_or_business(installed, monkeypatch, name, same_bytes_replacement):
    arguments, roots, _original = installed
    _interrupt(monkeypatch, arguments, "prepared")
    directory = _journal(roots)
    paths = {
        "lock": roots.STATE_ROOT / "system-update-active.lock", "common_marker": directory / "common.marker",
        "plan": directory / "plan.json",
        "candidate_entry": directory / "candidate-entry.exe", "candidate_record": directory / "candidate-record.json",
        "restore_entry": directory / "restore-entry.exe", "restore_record": directory / "restore-record.json",
        "pointer": roots.STATE_ROOT / "current-release.json", "record": roots.STATE_ROOT / entry.RECORD_NAME,
        "entry": roots.INSTALL_ROOT / entry.ENTRY_NAME, "fence": roots.RUNTIME_ROOT / "runtime-reconcile.lock",
        "retained_fence": recovery._fence_retained(roots, json.loads((directory / "plan.json").read_bytes())["operation_id"]),
        "runner": directory / "runner.lock",
    }
    path = paths[name]
    if same_bytes_replacement:
        # Equal content is not proof of ownership; an attacker/race can replace
        # an object between interruption and recovery without changing its hash.
        identity = (path.stat().st_dev, path.stat().st_ino)
        replacement = path.with_name(path.name + ".foreign-replacement")
        replacement.write_bytes(path.read_bytes())
        os.replace(replacement, path)
        assert (path.stat().st_dev, path.stat().st_ino) != identity
    else:
        path.write_bytes(path.read_bytes() + b" foreign mutation")
    before, runtime = _files(roots.INSTALL_ROOT), _files(roots.RUNTIME_ROOT)
    with pytest.raises(entry.InstallEntryError):
        entry.recover_fixed_entry(**arguments)
    assert _files(roots.INSTALL_ROOT) == before
    assert _files(roots.RUNTIME_ROOT) == runtime


def test_live_runner_lease_cannot_be_stolen_by_recovery(installed, monkeypatch):
    arguments, roots, _original = installed
    observed = []
    def recover_while_running(name):
        if name == "prepared":
            runner = _journal(roots) / "runner.lock"
            stat = runner.stat()
            identity = (stat.st_dev, stat.st_ino, stat.st_size)
            # Windows byte-range lease intentionally denies reading this byte
            # from a second handle; compare its path identity/size and every
            # other file instead of disabling the actual OS lease for tests.
            before = _files(roots.INSTALL_ROOT, exclude=(runner,))
            with pytest.raises(entry.InstallEntryError, match="RUNNER_BUSY"):
                entry.recover_fixed_entry(**arguments)
            assert _files(roots.INSTALL_ROOT, exclude=(runner,)) == before
            stat = runner.stat()
            assert (stat.st_dev, stat.st_ino, stat.st_size) == identity
            observed.append(name)
    monkeypatch.setattr(recovery, "_checkpoint", recover_while_running)
    assert entry.repair_fixed_entry(**arguments)["repair_state"] == "SUCCEEDED"
    assert observed == ["prepared"]


@pytest.mark.parametrize("checkpoint", [None, "entry_published", "record_published"])
def test_owned_release_without_entry_record_does_not_reinitialize_business(installed, monkeypatch, checkpoint):
    arguments, roots, _original = installed
    # Already qualified payload/pointer but no installation ownership record or
    # root entry; this is NOT authority to replace an unknown existing EXE.
    (roots.STATE_ROOT / entry.RECORD_NAME).unlink()
    (roots.INSTALL_ROOT / entry.ENTRY_NAME).unlink()
    before = _business(roots)
    if checkpoint is not None:
        _interrupt(monkeypatch, arguments, checkpoint)
        assert entry.recover_fixed_entry(**arguments)["repair_state"] == "ROLLED_BACK"
        assert not (roots.STATE_ROOT / entry.RECORD_NAME).exists()
        assert not (roots.INSTALL_ROOT / entry.ENTRY_NAME).exists()
    assert entry.repair_fixed_entry(**arguments)["repair_state"] == "SUCCEEDED"
    assert (roots.INSTALL_ROOT / entry.ENTRY_NAME).read_bytes() == arguments["entry"].data
    assert _business(roots) == before


def test_independently_verified_newer_entry_does_not_change_current_release_source(installed, tmp_path):
    arguments, roots, _original = installed
    before = _business(roots)
    arguments["entry"] = bundle(tmp_path / "native-independent", b"independently-built-entry", "d" * 40, "e" * 40)
    result = entry.repair_fixed_entry(**arguments)
    assert result["repair_state"] == "SUCCEEDED"
    record = json.loads((roots.STATE_ROOT / entry.RECORD_NAME).read_bytes())
    assert record["native_entry"]["source_commit"] == "d" * 40
    assert record["native_entry"]["source_tree"] == "e" * 40
    assert _business(roots) == before


def test_fsync_commit_result_prevents_rollback_when_directory_sync_fails(installed, monkeypatch):
    arguments, roots, _original = installed
    before = _business(roots)
    original_sync = recovery.sync_state_root_directory
    failures = []
    def fail_after_committed_result(path):
        results = list((roots.STAGING_ROOT / "entry-repairs").glob("*/result.json"))
        committed = any(json.loads(result.read_bytes()).get("status") == "SUCCEEDED" for result in results)
        if committed and not failures:
            failures.append(path)
            raise OSError("fixture-only directory sync failure after fsynced commit result")
        return original_sync(path)
    with monkeypatch.context() as patch:
        patch.setattr(recovery, "sync_state_root_directory", fail_after_committed_result)
        with pytest.raises(entry.InstallEntryError):
            entry.repair_fixed_entry(**arguments)
    assert failures
    assert (roots.INSTALL_ROOT / entry.ENTRY_NAME).read_bytes() == arguments["entry"].data
    published = _published(roots)
    assert (roots.STATE_ROOT / "system-update-active.lock").is_file()
    assert entry.recover_fixed_entry(**arguments)["repair_state"] == "SUCCEEDED"
    assert _published(roots) == published and _business(roots) == before
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()


@pytest.mark.parametrize("recovering", [False, True])
def test_final_unlink_sync_warning_preserves_truthful_terminal_not_false_recovery(installed, monkeypatch, recovering):
    arguments, roots, _original = installed
    before, published = _business(roots), _published(roots)
    if recovering:
        _interrupt(monkeypatch, arguments, "record_published")
    original_sync = recovery.sync_state_root_directory
    failures = []
    def fail_after_releasing_common(path):
        if path == roots.STATE_ROOT and not (roots.STATE_ROOT / "system-update-active.lock").exists() and not failures:
            failures.append(path)
            raise OSError("fixture-only final state-directory sync failure")
        return original_sync(path)
    monkeypatch.setattr(recovery, "sync_state_root_directory", fail_after_releasing_common)
    operation = entry.recover_fixed_entry if recovering else entry.repair_fixed_entry
    result = operation(**arguments)
    assert failures
    assert result["repair_state"] == ("ROLLED_BACK" if recovering else "SUCCEEDED")
    assert result["cleanup_warning"] == "INSTALL_ENTRY_DIRECTORY_SYNC_UNCONFIRMED"
    assert result["database_changed"] is result["pointer_changed"] is False
    if recovering:
        assert _published(roots) == published
    else:
        assert (roots.INSTALL_ROOT / entry.ENTRY_NAME).read_bytes() == arguments["entry"].data
    assert _business(roots) == before
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()
    assert not (roots.RUNTIME_ROOT / "runtime-reconcile.lock").exists()


def test_runtime_fence_cleanup_sync_failure_keeps_common_recovery_authority(installed, monkeypatch):
    arguments, roots, _original = installed
    before = _business(roots)
    original_sync = recovery.sync_state_root_directory
    failures = []
    def fail_after_releasing_fence(path):
        if (path == roots.RUNTIME_ROOT and (roots.STATE_ROOT / "system-update-active.lock").exists()
                and not (roots.RUNTIME_ROOT / "runtime-reconcile.lock").exists() and not failures):
            failures.append(path)
            raise OSError("fixture-only fence cleanup sync failure")
        return original_sync(path)
    with monkeypatch.context() as patch:
        patch.setattr(recovery, "sync_state_root_directory", fail_after_releasing_fence)
        with pytest.raises(entry.InstallEntryError, match="RECOVERY_REQUIRED"):
            entry.repair_fixed_entry(**arguments)
    assert failures
    published = _published(roots)
    assert (roots.STATE_ROOT / "system-update-active.lock").exists()
    assert entry.recover_fixed_entry(**arguments)["repair_state"] == "SUCCEEDED"
    assert _published(roots) == published and _business(roots) == before
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()


def test_cross_volume_layout_does_not_link_staging_fence_into_runtime(installed, monkeypatch):
    arguments, roots, _original = installed
    original_link = recovery.os.link
    runtime_links = []
    def cross_volume_link(source, destination, *args, **kwargs):
        source, destination = Path(source), Path(destination)
        if destination.is_relative_to(roots.RUNTIME_ROOT):
            runtime_links.append((source, destination))
            if source.is_relative_to(roots.STAGING_ROOT):
                raise OSError(errno.EXDEV, "fixture cross-device fence link denied")
        return original_link(source, destination, *args, **kwargs)
    monkeypatch.setattr(recovery.os, "link", cross_volume_link)
    before = _business(roots)
    assert entry.repair_fixed_entry(**arguments)["repair_state"] == "SUCCEEDED"
    assert len(runtime_links) == 1
    assert runtime_links[0][0].is_relative_to(roots.RUNTIME_ROOT / "entry-repair-fences")
    assert _business(roots) == before


def test_v2_recover_entry_is_explicit_and_does_not_expand_graphical_v4():
    request = {"schema_version": MAINTENANCE_REQUEST_SCHEMA, "operation": "recover-entry",
               "install_mode": "custom", "install_root": "C:\\fixture install", "username": "",
               "password": "", "password_confirmation": ""}
    assert _decode_request(canonical_json(request)) == request
    for change in ({"password": "not accepted"}, {"operation": "recover-arbitrary"}, {"extra": True},
                   {"schema_version": GRAPHICAL_MAINTENANCE_REQUEST_SCHEMA, "confirm_no_active_tasks": True}):
        with pytest.raises(SetupBridgeError):
            _decode_request(canonical_json(request | change))


def test_replacing_both_common_names_cannot_reuse_the_old_fence_authority(installed, monkeypatch):
    arguments, roots, _original = installed
    _interrupt(monkeypatch, arguments, "prepared")
    directory = _journal(roots)
    retained = directory / "common.marker"
    active = roots.STATE_ROOT / "system-update-active.lock"
    original_identity = retained.stat().st_ino
    content = retained.read_bytes()
    retained.unlink()
    active.unlink()
    retained.write_bytes(content)
    os.link(retained, active)
    assert retained.stat().st_ino != original_identity
    before, runtime = _files(roots.INSTALL_ROOT), _files(roots.RUNTIME_ROOT)
    with pytest.raises(entry.InstallEntryError, match="RECOVERY_REQUIRED"):
        entry.recover_fixed_entry(**arguments)
    assert _files(roots.INSTALL_ROOT) == before and _files(roots.RUNTIME_ROOT) == runtime


@pytest.mark.skipif(os.name != "nt", reason="actual Windows byte-range lease cleanup")
def test_explicit_unlock_failure_still_closes_the_kernel_runner_lease(installed, monkeypatch):
    import msvcrt
    arguments, roots, _original = installed
    original_locking = msvcrt.locking
    failures = []
    def fail_unlock(handle, mode, length):
        if mode == msvcrt.LK_UNLCK:
            failures.append(handle)
            raise OSError("fixture-only explicit unlock failure")
        return original_locking(handle, mode, length)
    monkeypatch.setattr(msvcrt, "locking", fail_unlock)
    before = _business(roots)
    result = entry.repair_fixed_entry(**arguments)
    assert result["repair_state"] == "SUCCEEDED" and failures
    directory = roots.STAGING_ROOT / "entry-repairs" / result["operation_id"][:12]
    runner = directory / "runner.lock"
    # Closing the first handle released the OS lock despite injected UNLCK.
    with recovery._runner_lease(runner, entry._snapshot(runner)):
        pass
    assert len(failures) == 2
    assert _business(roots) == before
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()
    assert not (roots.RUNTIME_ROOT / "runtime-reconcile.lock").exists()
