"""Real Windows object moves and offline SQLite, using small owned fixtures.

Runtime observation is substituted in unit cases; these are not Setup GUI or
compiled-entry acceptance. No file, database or program verifier is replaced.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pytest

from enterprise import install_cache as files, install_lifecycle as lifecycle
from enterprise.install_entry import publish_fixed_entry
from enterprise.migrations.versioned import initialize_schema_metadata_in_transaction
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.tests.test_install_entry import bundle, qualified_program_fixture
from enterprise.install_setup_bridge import LIFECYCLE_REQUEST_SCHEMA, SetupBridgeError, _decode_request
from enterprise.release.release_manifest_v2 import canonical_json

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows lifecycle adapter")


class Interrupted(BaseException):
    pass


@pytest.fixture
def installed(tmp_path, monkeypatch):
    base = tmp_path.parent / ("l-" + uuid.uuid4().hex[:8]); base.mkdir()
    root, manifest, archive, inventory, document = qualified_program_fixture(base)
    roots = derive_portable_path_roots(PortableRootInputs(root, base / "local"), document["identity"]["release_id"])
    source = document["enterprise_source"]
    entry = bundle(base / "native", commit=source["commit"], tree=source["tree"])
    publication = publish_fixed_entry(roots, entry); publication.complete()
    database = root / "data/enterprise.db"
    database.unlink()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE retained_business (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO retained_business VALUES (1, 'retain exactly')")
        initialize_schema_metadata_in_transaction(connection)
        connection.commit()
    (root / "data/canvas.json").write_bytes(b'{"owned":"retained"}')
    (root / "data/media.bin").write_bytes(b"original-asset")
    (root / "backups").mkdir(); (root / "backups/do-not-touch.db").write_bytes(b"valid-backup-fixture")
    monkeypatch.setattr(lifecycle, "_runtime_quiescent", lambda _roots: None)
    assets = base / "core"; assets.mkdir()
    for original in (manifest, archive, inventory):
        shutil.copyfile(original, assets / ("ops-release-manifest-v2.json" if original == manifest else original.name))
    arguments = dict(install_root=root, release_dir=assets, local_app_data_base=base / "local",
                     confirm_no_active_tasks=True)
    return roots, arguments


def preserved(roots):
    return {str(path.relative_to(roots.INSTALL_ROOT)): path.read_bytes()
            for path in roots.INSTALL_ROOT.rglob("*") if path.is_file() and
            (path.is_relative_to(roots.DATA_ROOT) or path.is_relative_to(roots.CONFIG_ROOT)
             or path.is_relative_to(roots.BACKUP_ROOT)
             or path.name in {"installation.json", "current-release.json"})}


def all_files(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def uninstall(installed, **changes):
    return lifecycle.uninstall_retaining_data(**(installed[1] | changes))


def reinstall(installed):
    return lifecycle.reinstall_retained(**installed[1])


def test_uninstall_reinstall_preserves_business_and_original_program_object_identities(installed):
    roots, arguments = installed
    before, program, entry = preserved(roots), files._tree(roots.APP_ROOT), files._file(roots.INSTALL_ROOT / "InfiniteCanvas.exe")
    result = uninstall(installed)
    assert result["lifecycle_state"] == "UNINSTALLED" and result["program_recovery_copy_retained"]
    assert not roots.APP_ROOT.exists() and not (roots.INSTALL_ROOT / "InfiniteCanvas.exe").exists()
    assert (roots.STATE_ROOT / "system-update-active.lock").exists()
    assert preserved(roots) == before
    result = reinstall(installed)
    assert result["lifecycle_state"] == "INSTALLED" and not result["program_recovery_copy_retained"]
    assert files._tree(roots.APP_ROOT) == program
    assert files._file(roots.INSTALL_ROOT / "InfiniteCanvas.exe") == entry
    assert not (roots.STATE_ROOT / "system-update-active.lock").exists()
    assert preserved(roots) == before
    assert reinstall(installed)["installation_id"] == result["installation_id"]
    assert uninstall(installed)["installation_id"] == result["installation_id"]


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_explicit_task_confirmation_is_required_before_any_writes(installed, value):
    roots, _ = installed
    before = all_files(roots.INSTALL_ROOT)
    with pytest.raises(lifecycle.LifecycleError, match="TASK_CONFIRMATION_REQUIRED"):
        uninstall(installed, confirm_no_active_tasks=value)
    assert all_files(roots.INSTALL_ROOT) == before


@pytest.mark.parametrize("stage", ["fence_published", "state_uninstalling", "program_retained", "entry_retained", "state_uninstalled"])
@pytest.mark.parametrize("finish", ["recover-uninstall", "reinstall"])
def test_interruption_requires_explicit_proven_recovery_and_never_initializes_database(installed, monkeypatch, stage, finish):
    roots, _ = installed
    before = preserved(roots)
    def stop(point):
        if point == stage:
            raise Interrupted()
    monkeypatch.setattr(lifecycle, "_checkpoint", stop)
    with pytest.raises(Interrupted):
        uninstall(installed)
    monkeypatch.setattr(lifecycle, "_checkpoint", lambda _stage: None)
    with pytest.raises(lifecycle.LifecycleError, match="BUSY"):
        uninstall(installed)
    assert preserved(roots) == before
    if finish == "recover-uninstall":
        assert uninstall(installed, recover=True)["lifecycle_state"] == "UNINSTALLED"
    assert reinstall(installed)["lifecycle_state"] == "INSTALLED"
    assert preserved(roots) == before


@pytest.mark.parametrize("stage", ["state_reinstalling", "program_reinstated", "entry_reinstated", "state_installed", "fence_released"])
def test_reinstall_interruption_is_repeatable_without_replacing_business(installed, monkeypatch, stage):
    roots, _ = installed
    before = preserved(roots); uninstall(installed)
    def stop(point):
        if point == stage:
            raise Interrupted()
    monkeypatch.setattr(lifecycle, "_checkpoint", stop)
    with pytest.raises(Interrupted):
        reinstall(installed)
    monkeypatch.setattr(lifecycle, "_checkpoint", lambda _stage: None)
    assert reinstall(installed)["lifecycle_state"] == "INSTALLED"
    assert preserved(roots) == before


@pytest.mark.parametrize("change", ["bytes", "same-byte-object", "extra-file", "extra-dir", "hardlink", "record", "pointer", "database-object", "config", "schema", "wal", "lock"])
def test_changed_retained_material_is_not_adopted_or_overwritten(installed, change):
    roots, _ = installed
    uninstall(installed)
    state = json.loads((roots.STATE_ROOT / lifecycle.STATE_NAME).read_bytes())
    directory = roots.STATE_ROOT / "install-lifecycle" / state["operation_id"]
    path = directory / "entry.exe"
    if change == "bytes": path.write_bytes(b"changed")
    elif change == "same-byte-object":
        replacement = path.with_suffix(".new"); replacement.write_bytes(path.read_bytes()); path.unlink(); replacement.rename(path)
    elif change == "extra-file": (directory / "program/business.db").write_bytes(b"unknown")
    elif change == "extra-dir": (directory / "program/extra").mkdir()
    elif change == "hardlink": os.link(path, directory / "second-entry.exe")
    elif change in {"record", "pointer"}:
        selected = roots.STATE_ROOT / ("installation.json" if change == "record" else "current-release.json")
        raw = selected.read_bytes(); selected.unlink(); selected.write_bytes(raw)
    elif change == "schema":
        with closing(sqlite3.connect(roots.DATA_ROOT / "enterprise.db")) as connection:
            connection.execute("CREATE TABLE unknown_schema (value TEXT)")
            connection.commit()
    elif change == "database-object":
        database = roots.DATA_ROOT / "enterprise.db"
        raw = database.read_bytes(); database.unlink(); database.write_bytes(raw)
    elif change == "config": (roots.CONFIG_ROOT / "enterprise.env").write_bytes(b"changed settings")
    elif change == "wal": (roots.DATA_ROOT / "enterprise.db-wal").write_bytes(b"unresolved")
    else:
        lock = roots.STATE_ROOT / "system-update-active.lock"
        raw = lock.read_bytes(); lock.unlink(); lock.write_bytes(raw)
    before = all_files(roots.INSTALL_ROOT)
    with pytest.raises((lifecycle.LifecycleError, files.CacheError)):
        reinstall(installed)
    assert all_files(roots.INSTALL_ROOT) == before


def test_live_runner_lease_rejects_parallel_recovery(installed):
    roots, _ = installed
    uninstall(installed)
    directory, plan, _ = lifecycle._active(roots)
    with files._lease(directory / "runner.lock", plan["lease"]):
        with pytest.raises(files.CacheError, match="BUSY"):
            reinstall(installed)
    assert reinstall(installed)["lifecycle_state"] == "INSTALLED"


def test_running_runtime_blocks_before_any_installation_writes(installed, monkeypatch):
    roots, _ = installed
    def busy(_roots): raise lifecycle.LifecycleError("INSTALL_LIFECYCLE_RUNTIME_BUSY")
    monkeypatch.setattr(lifecycle, "_runtime_quiescent", busy)
    before = all_files(roots.INSTALL_ROOT)
    with pytest.raises(lifecycle.LifecycleError, match="RUNTIME_BUSY"):
        uninstall(installed)
    assert all_files(roots.INSTALL_ROOT) == before


def test_runtime_started_during_preparation_is_blocked_under_the_fence(installed, monkeypatch):
    roots, _ = installed
    before = preserved(roots); observations = 0
    def raced(_roots):
        nonlocal observations
        observations += 1
        if observations > 1:
            raise lifecycle.LifecycleError("INSTALL_LIFECYCLE_RUNTIME_BUSY")
    monkeypatch.setattr(lifecycle, "_runtime_quiescent", raced)
    with pytest.raises(lifecycle.LifecycleError, match="RUNTIME_BUSY"):
        uninstall(installed)
    assert roots.APP_ROOT.exists() and preserved(roots) == before
    assert (roots.STATE_ROOT / "system-update-active.lock").exists()


def test_inspection_has_no_recovery_side_effect(installed):
    roots, arguments = installed
    arguments = {k: v for k, v in arguments.items() if k != "confirm_no_active_tasks"}
    assert lifecycle.inspect_lifecycle(**arguments)["lifecycle_state"] == "NONE"
    uninstall(installed); before = all_files(roots.INSTALL_ROOT)
    assert lifecycle.inspect_lifecycle(**arguments)["lifecycle_state"] == "UNINSTALLED"
    assert all_files(roots.INSTALL_ROOT) == before


@pytest.mark.parametrize("operation", ["inspect-lifecycle", "uninstall-retain", "recover-uninstall", "reinstall-retained"])
def test_lifecycle_protocol_requires_explicit_operation_and_never_accepts_credentials(operation):
    request = {"schema_version": LIFECYCLE_REQUEST_SCHEMA, "operation": operation,
        "install_mode": "custom", "install_root": "D:\\owned-copy", "username": "", "password": "",
        "password_confirmation": "", "confirm_no_active_tasks": operation != "inspect-lifecycle"}
    assert _decode_request(canonical_json(request)) == request
    for change in ({"password": "fixture-only"}, {"confirm_no_active_tasks": 1}, {"operation": "delete-data"}, {"extra": True}):
        with pytest.raises(SetupBridgeError):
            _decode_request(canonical_json(request | change))
