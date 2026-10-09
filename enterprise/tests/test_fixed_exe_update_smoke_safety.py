"""Small safety regressions; the full Windows/EXE drill remains opt-in."""
import json
from pathlib import Path

import pytest

from enterprise.tests import fixed_exe_update_windows_smoke as drill


def _history(tmp_path):
    for name in drill.NAMES:
        root = tmp_path / name
        root.mkdir()
        (root / "retain.bin").write_bytes(b"original history")


def test_history_is_never_moved_without_explicit_authorization(tmp_path):
    _history(tmp_path)
    with pytest.raises(RuntimeError, match="LOCAL_ROOTS_IN_USE"):
        with drill.preserved_local_roots(tmp_path, "test"):
            pytest.fail("must block before yielding")
    assert not (tmp_path / "ICE-UpdateDrill-Saved-test").exists()
    assert all((tmp_path / name / "retain.bin").read_bytes() == b"original history" for name in drill.NAMES)


@pytest.mark.parametrize("fail_during_drill", [False, True])
def test_authorized_history_is_restored_on_success_and_exception(tmp_path, monkeypatch, fail_during_drill):
    _history(tmp_path)
    monkeypatch.setattr(drill, "_require_quiescent", lambda _: None)
    snapshots = {name: drill._tree_snapshot(tmp_path / name) for name in drill.NAMES}
    identities = {name: (tmp_path / name).stat().st_ino for name in drill.NAMES}
    try:
        with drill.preserved_local_roots(tmp_path, "test", explicitly_authorized=True):
            assert all(not (tmp_path / name).exists() for name in drill.NAMES)
            if fail_during_drill:
                raise ValueError("synthetic failure")
    except ValueError:
        assert fail_during_drill
    assert all(drill._tree_snapshot(tmp_path / name) == snapshots[name] for name in drill.NAMES)
    assert all((tmp_path / name).stat().st_ino == identities[name] for name in drill.NAMES)
    assert (tmp_path / "ICE-UpdateDrill-Saved-test/RESTORED.json").is_file()


def test_restore_never_overwrites_new_or_unowned_root(tmp_path, monkeypatch):
    _history(tmp_path)
    monkeypatch.setattr(drill, "_require_quiescent", lambda _: None)
    with pytest.raises(RuntimeError, match="RESTORE_DESTINATION_OCCUPIED"):
        with drill.preserved_local_roots(tmp_path, "test", explicitly_authorized=True):
            root = tmp_path / drill.NAMES[0]
            root.mkdir()
            (root / "retain.bin").write_bytes(b"unowned replacement")
    assert (tmp_path / drill.NAMES[0] / "retain.bin").read_bytes() == b"unowned replacement"
    assert all((tmp_path / "ICE-UpdateDrill-Saved-test" / name / "retain.bin").read_bytes() == b"original history" for name in drill.NAMES)


def test_running_or_unverifiable_state_blocks_before_moving(tmp_path):
    _history(tmp_path)
    runtime = tmp_path / drill.NAMES[0] / "runtime"
    runtime.mkdir()
    (runtime / "runtime-state.json").write_text(json.dumps({"schema_version": "runtime-supervisor-state-v1", "state": "healthy"}))
    with pytest.raises(RuntimeError, match="RUNTIME_NOT_STOPPED"):
        with drill.preserved_local_roots(tmp_path, "test", explicitly_authorized=True):
            pytest.fail("must block")
    assert all((tmp_path / name / "retain.bin").is_file() for name in drill.NAMES)


def test_locked_state_is_never_reconciled_or_stopped(tmp_path):
    _history(tmp_path)
    runtime = tmp_path / drill.NAMES[0] / "runtime"
    runtime.mkdir()
    (runtime / "runtime-supervisor.lock").write_bytes(b"keep original lock")
    with pytest.raises(RuntimeError, match="RUNTIME_LOCKED"):
        drill._require_quiescent(tmp_path)
    assert (runtime / "runtime-supervisor.lock").read_bytes() == b"keep original lock"


def test_saved_tree_change_blocks_restoration_without_discarding_either_copy(tmp_path, monkeypatch):
    _history(tmp_path)
    monkeypatch.setattr(drill, "_require_quiescent", lambda _: None)
    with pytest.raises(RuntimeError, match="SAVED_TREE_CHANGED"):
        with drill.preserved_local_roots(tmp_path, "test", explicitly_authorized=True):
            (tmp_path / "ICE-UpdateDrill-Saved-test" / drill.NAMES[0] / "retain.bin").write_bytes(b"changed")
    assert (tmp_path / "ICE-UpdateDrill-Saved-test" / drill.NAMES[0] / "retain.bin").read_bytes() == b"changed"
    assert (tmp_path / "ICE-UpdateDrill-Saved-test" / drill.NAMES[1] / "retain.bin").read_bytes() == b"original history"


def test_inherited_deployment_credentials_and_ports_do_not_enter_fixture(monkeypatch):
    for key in ("JWT_SECRET", "DB_PATH", "ADMIN_PASSWORD", "GATEWAY_PORT", "UPSTREAM_PORT"):
        monkeypatch.setenv(key, "fixture-should-remove")
    assert not any(key in drill._environment() for key in ("JWT_SECRET", "DB_PATH", "ADMIN_PASSWORD", "GATEWAY_PORT", "UPSTREAM_PORT"))


@pytest.mark.parametrize("nonce", ["../elsewhere", "a/b", "a\\b", "", "a" * 65])
def test_preservation_nonce_cannot_escape_exact_backup_parent(tmp_path, nonce):
    _history(tmp_path)
    with pytest.raises(RuntimeError, match="NONCE_INVALID"):
        with drill.preserved_local_roots(tmp_path, nonce, explicitly_authorized=True):
            pytest.fail("must reject before moving")
    assert all((tmp_path / name / "retain.bin").is_file() for name in drill.NAMES)


@pytest.mark.parametrize("kind", ["inside", "parent", "equal", "existing", "relative", "volume-root"])
def test_evidence_directory_cannot_overlap_or_overwrite(tmp_path, kind):
    protected = tmp_path / "protected"
    protected.mkdir()
    candidates = {"inside": protected / "evidence", "parent": tmp_path, "equal": protected,
                  "existing": tmp_path / "existing", "relative": Path("relative-evidence"),
                  "volume-root": Path(tmp_path.anchor)}
    (tmp_path / "existing").mkdir()
    with pytest.raises(RuntimeError, match="EVIDENCE"):
        drill._validate_evidence_root(candidates[kind], (protected,))


def test_saved_snapshot_includes_empty_directories(tmp_path):
    root = tmp_path / "history"
    root.mkdir()
    (root / "empty").mkdir()
    assert drill._tree_snapshot(root) == {"empty/": ("directory",)}


@pytest.mark.skipif(drill.os.name != "nt", reason="Windows extended-length path behavior")
def test_snapshot_hashes_existing_long_files_without_weakening_path_gates(tmp_path):
    root = tmp_path / "long-history"
    extended = drill._snapshot_io_root(root)
    leaf = extended
    for index in range(5):
        leaf /= str(index) + "x" * 48
    leaf.mkdir(parents=True)
    (leaf / "retain.bin").write_bytes(b"long retained file")
    snapshot = drill._tree_snapshot(root)
    relative = (leaf / "retain.bin").relative_to(extended).as_posix()
    assert len(str(leaf / "retain.bin")) > 260
    assert snapshot[relative][0] == len(b"long retained file")
    assert snapshot[relative][2] == drill.hashlib.sha256(b"long retained file").hexdigest()


def test_owned_cleanup_does_not_replace_lexical_identity_with_resolve(tmp_path, monkeypatch):
    root = tmp_path / drill.NAMES[0]
    root.mkdir()
    (root / ".ops3b-drill-owned").write_text("test", encoding="ascii")
    monkeypatch.setattr(Path, "resolve", lambda *a, **k: pytest.fail("must keep lexical KnownFolder identity"))
    drill._remove_owned_local_root(root, tmp_path, "test")
    assert not root.exists()


@pytest.mark.parametrize("reason", ["foreign-marker", "active-lock", "wrong-name"])
def test_owned_cleanup_retains_unverified_or_active_roots(tmp_path, reason):
    root = tmp_path / ("other" if reason == "wrong-name" else drill.NAMES[0])
    root.mkdir()
    (root / ".ops3b-drill-owned").write_text("other" if reason == "foreign-marker" else "test", encoding="ascii")
    if reason == "active-lock":
        (root / "runtime").mkdir()
        (root / "runtime/runtime-supervisor.lock").write_bytes(b"retain")
    with pytest.raises(RuntimeError, match="FIXED_EXE_LOCAL"):
        drill._remove_owned_local_root(root, tmp_path, "test")
    assert root.is_dir()
