"""Owned Windows copies for empty-log preparation; no customer fixtures."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from enterprise import install_upgrade as upgrade, install_lifecycle as lifecycle
from enterprise.tests.test_install_upgrade import installed, arguments, protected, finish, interrupted_at

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native-object adapter")
needs_sqlite_control = pytest.mark.skipif(
    not hasattr(sqlite3.Connection, "setconfig"), reason="fixed CP314 SQLite close-checkpoint control required")


def empty_wal_residue(fixture):
    database = fixture["roots"].DATA_ROOT / "enterprise.db"
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    # A real readonly connection can leave these files after the final writer
    # has closed. Do not manufacture an SHM format in this acceptance fixture.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        assert conn.execute("SELECT value FROM business").fetchone() == ("retained-business",)
    assert database.with_name(database.name + "-wal").stat().st_size == 0
    assert database.with_name(database.name + "-shm").stat().st_size == 32768
    return database


@pytest.mark.parametrize("target_failure", [False, True])
@needs_sqlite_control
def test_empty_wal_preflight_is_readonly_and_fenced_preparation_preserves_main_bytes(installed, monkeypatch, target_failure):
    f = installed; db = empty_wal_residue(f)
    before = protected(f)
    args = dict(install_root=f["roots"].INSTALL_ROOT, release_dir=f["target_assets"], local_app_data_base=f["local"])
    assert upgrade.inspect_upgrade(**args)["database_preparation_required"] is True
    assert protected(f) == before and not (f["roots"].STATE_ROOT / "install-upgrades").exists()
    original = upgrade.database_preparation._checkpoint_quiescent_database
    calls = []
    def checkpoint(database, **kwargs):
        assert (f["roots"].STATE_ROOT / "system-update-active.lock").exists()
        assert (f["roots"].STATE_ROOT / upgrade.ACTIVE_NAME).exists()
        calls.append(database)
        return original(database, **kwargs)
    monkeypatch.setattr(upgrade.database_preparation, "_checkpoint_quiescent_database", checkpoint)
    if target_failure:
        monkeypatch.setattr(upgrade.mvp, "_run_launcher", lambda app, command:
            (2, {"code": "SYSTEM_UPDATE_TARGET_HEALTH_FAILED"})
            if command == "health" and app.name.startswith("ice-2026.07.7-") else (0, {"result": "stopped"}))
    result = upgrade.upgrade_retained(**arguments(f))
    assert result["upgrade_state"] == ("ROLLED_BACK" if target_failure else "AWAITING_REGISTRATION")
    assert calls == [db]
    assert protected(f) == {key: value for key, value in before.items() if not key.endswith(("-wal", "-shm"))}
    if not target_failure:
        assert finish(f)["upgrade_state"] == "COMPLETE"


@pytest.mark.parametrize("stage", ["active_published", "fence_published", "database_preparing", "database_prepared"])
@needs_sqlite_control
def test_empty_wal_preparation_interruption_requires_explicit_leased_recovery(installed, monkeypatch, stage):
    f = installed; db = empty_wal_residue(f)
    original = db.read_bytes()
    interrupted_at(f, monkeypatch, stage)
    args = dict(install_root=f["roots"].INSTALL_ROOT, release_dir=f["target_assets"], local_app_data_base=f["local"])
    before = protected(f)
    assert upgrade.inspect_upgrade(**args)["upgrade_state"] == "RECOVERY_REQUIRED"
    assert protected(f) == before  # Inspect never performs checkpoint/recovery.
    result = upgrade.recover_upgrade(**args, confirm_no_active_tasks=True)
    assert result["upgrade_state"] == "ROLLED_BACK"
    assert db.read_bytes() == original and lifecycle._database_inspection(f["roots"])["is_ready"]
    assert not (f["roots"].STATE_ROOT / "system-update-active.lock").exists()
    assert not f["calls"]


@needs_sqlite_control
def test_database_writer_blocks_preparation_and_keeps_recovery_fence(installed, monkeypatch):
    f = installed; db = empty_wal_residue(f)
    original = db.read_bytes()
    with closing(sqlite3.connect(db)) as writer:
        def occupy(stage):
            if stage == "database_preparing":
                writer.execute("BEGIN IMMEDIATE")
                writer.execute("INSERT INTO business VALUES(2, 'not-committed')")
        monkeypatch.setattr(upgrade, "_checkpoint", occupy)
        with pytest.raises(lifecycle.LifecycleError, match="INSTALL_UPGRADE_DATABASE_PREPARATION_REQUIRED"):
            upgrade.upgrade_retained(**arguments(f))
        assert (f["roots"].STATE_ROOT / "system-update-active.lock").exists()
        assert (f["roots"].STATE_ROOT / upgrade.ACTIVE_NAME).exists()
        assert db.read_bytes() == original and not f["calls"]
        writer.rollback()
    monkeypatch.setattr(upgrade, "_checkpoint", lambda _: None)
    assert upgrade.recover_upgrade(install_root=f["roots"].INSTALL_ROOT, release_dir=f["target_assets"],
        local_app_data_base=f["local"], confirm_no_active_tasks=True)["upgrade_state"] == "ROLLED_BACK"


@needs_sqlite_control
def test_changed_wal_before_checkpoint_is_not_recovered_or_ignored(installed, monkeypatch):
    f = installed; db = empty_wal_residue(f)
    original = db.read_bytes()
    def alter(stage):
        if stage == "database_preparing":
            db.with_name(db.name + "-wal").write_bytes(b"unknown-log-must-be-retained")
    monkeypatch.setattr(upgrade, "_checkpoint", alter)
    monkeypatch.setattr(upgrade.database_preparation, "_checkpoint_quiescent_database",
        lambda *a, **k: pytest.fail("unknown WAL must never reach SQLite checkpoint"))
    with pytest.raises(lifecycle.LifecycleError, match="DATABASE_RECOVERY_REQUIRED"):
        upgrade.upgrade_retained(**arguments(f))
    assert db.read_bytes() == original and not f["calls"]
    assert (f["roots"].STATE_ROOT / "system-update-active.lock").exists()
    assert (f["roots"].STATE_ROOT / upgrade.ACTIVE_NAME).exists()


def test_real_committed_wal_is_not_an_empty_log_candidate(installed):
    f = installed; db = f["roots"].DATA_ROOT / "enterprise.db"
    with closing(sqlite3.connect(db)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("INSERT INTO business VALUES(2, 'committed-in-wal')")
        writer.commit()
        assert db.with_name(db.name + "-wal").stat().st_size > 0
        before = db.read_bytes()
        with pytest.raises(lifecycle.LifecycleError, match="DATABASE_RECOVERY_REQUIRED"):
            upgrade.upgrade_retained(**arguments(f))
        assert db.read_bytes() == before and not f["calls"]
        assert not (f["roots"].STATE_ROOT / "install-upgrades").exists()


@pytest.mark.parametrize("guard", ["runtime", "foreign-fence", "identity"])
@needs_sqlite_control
def test_empty_log_preparation_cannot_bypass_source_or_maintenance_guards(installed, monkeypatch, guard):
    f = installed; db = empty_wal_residue(f)
    before = protected(f)
    monkeypatch.setattr(upgrade.database_preparation, "_checkpoint_quiescent_database",
        lambda *a, **k: pytest.fail("guard refusal must precede SQLite writes"))
    def change(stage):
        if stage != "fence_published":
            return
        if guard == "runtime":
            def busy(_):
                raise lifecycle.LifecycleError("INSTALL_LIFECYCLE_RUNTIME_BUSY")
            monkeypatch.setattr(lifecycle, "_runtime_quiescent", busy)
        elif guard == "identity":
            (f["roots"].STATE_ROOT / "installation.json").write_bytes(b"changed identity")
        else:
            lock = f["roots"].STATE_ROOT / "system-update-active.lock"
            displaced = lock.with_name("displaced-fence")
            lock.rename(displaced)
            shutil.copyfile(displaced, lock)
    monkeypatch.setattr(upgrade, "_checkpoint", change)
    with pytest.raises((lifecycle.LifecycleError, upgrade.InstallUpgradeError)):
        upgrade.upgrade_retained(**arguments(f))
    assert protected(f) == before and not f["calls"]
    assert (f["roots"].STATE_ROOT / upgrade.ACTIVE_NAME).exists()


@needs_sqlite_control
def test_wal_committed_after_qualification_is_not_checkpointed_even_on_close(installed, monkeypatch):
    f = installed; db = empty_wal_residue(f)
    before = db.read_bytes()
    original = upgrade.database_preparation._checkpoint_quiescent_database
    def race(database, **kwargs):
        with closing(sqlite3.connect(database)) as writer:
            writer.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
            writer.execute("INSERT INTO business VALUES(2, 'late-commit')")
            writer.commit()
        wal = db.with_name(db.name + "-wal")
        committed_log = wal.read_bytes()
        assert len(committed_log) > 0
        try:
            return original(database, **kwargs)
        finally:
            assert db.read_bytes() == before
            assert wal.read_bytes() == committed_log
    monkeypatch.setattr(upgrade.database_preparation, "_checkpoint_quiescent_database", race)
    with pytest.raises((lifecycle.LifecycleError, upgrade.database_preparation.DataMigrationError)):
        upgrade.upgrade_retained(**arguments(f))
    assert not f["calls"] and (f["roots"].STATE_ROOT / "system-update-active.lock").exists()


@needs_sqlite_control
def test_sqlite_mutex_blocks_new_writer_through_empty_checkpoint(installed, monkeypatch):
    f = installed; db = empty_wal_residue(f)
    before = db.read_bytes(); blocked = []
    def competing_writer(stage):
        if stage == "database_locked":
            with closing(sqlite3.connect(db, timeout=0)) as writer:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    writer.execute("BEGIN IMMEDIATE")
                blocked.append(True)
    monkeypatch.setattr(upgrade.database_preparation, "_checkpoint", competing_writer)
    assert upgrade.upgrade_retained(**arguments(f))["upgrade_state"] == "AWAITING_REGISTRATION"
    assert blocked == [True] and db.read_bytes() == before
    assert finish(f)["upgrade_state"] == "COMPLETE"


@needs_sqlite_control
def test_hard_exit_while_sqlite_mutex_is_held_preserves_explicit_recovery(installed, tmp_path):
    f = installed; db = empty_wal_residue(f)
    before = db.read_bytes()
    request = tmp_path / "owned-request.json"
    request.write_text(json.dumps({key: str(value) if isinstance(value, Path) else value
                                  for key, value in arguments(f).items()}), encoding="utf-8")
    code = """
import json, os, sys
sys.path.insert(0, REPOSITORY)
from enterprise import install_upgrade as upgrade, install_lifecycle as lifecycle
lifecycle._runtime_quiescent = lambda _: None
upgrade.database_preparation._checkpoint = lambda stage: os._exit(93) if stage == 'database_locked' else None
upgrade.upgrade_retained(**json.load(open(sys.argv[1], encoding='utf-8')))
raise AssertionError('owned hard-exit checkpoint not reached')
""".replace("REPOSITORY", repr(str(Path(__file__).resolve().parents[2])))
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(request)], capture_output=True, timeout=45)
    assert result.returncode == 93, (result.returncode, result.stdout, result.stderr)
    assert db.read_bytes() == before and (f["roots"].STATE_ROOT / "system-update-active.lock").exists()
    assert upgrade.recover_upgrade(install_root=f["roots"].INSTALL_ROOT, release_dir=f["target_assets"],
        local_app_data_base=f["local"], confirm_no_active_tasks=True)["upgrade_state"] == "ROLLED_BACK"
    assert db.read_bytes() == before and lifecycle._database_inspection(f["roots"])["is_ready"]


def test_older_python_without_close_checkpoint_control_refuses_before_publication(installed):
    if hasattr(sqlite3.Connection, "setconfig"):
        pytest.skip("older-tooling fail-closed path")
    f = installed; empty_wal_residue(f); before = protected(f)
    with pytest.raises(lifecycle.LifecycleError, match="DATABASE_PREPARATION_UNSUPPORTED"):
        upgrade.upgrade_retained(**arguments(f))
    assert protected(f) == before and not (f["roots"].STATE_ROOT / "install-upgrades").exists()
