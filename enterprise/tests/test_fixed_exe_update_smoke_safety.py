"""Small safety regressions; the full Windows/EXE drill remains opt-in."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from enterprise.tests import fixed_exe_update_windows_smoke as drill
from enterprise.tests import fixed_exe_handoff_qualification as qualification


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


@pytest.mark.skipif(drill.os.name != "nt", reason="Windows creation flags")
@pytest.mark.parametrize("limits,expected", [(0x2000, 0x01000208), (0x1000, 0x208),
                                            (0x1800, 0x01000208), (None, 0x01000208)])
def test_runner_qualification_uses_guarded_worker_flags(limits, expected):
    assert qualification.worker_flags({"process_in_job": True, "job_limit_flags": limits}) == expected


def _qualification_mocks(monkeypatch):
    source = qualification.ProcessIdentity(qualification.os.getpid(), 10, qualification.sys.executable)
    worker = qualification.ProcessIdentity(42, 20, qualification.sys.executable)
    process = Mock(pid=worker.pid)
    live = {"exited": False}
    process.poll.side_effect = lambda: 0 if live["exited"] else None
    process.wait.side_effect = lambda **kwargs: live.update(exited=True) or 0
    job = Mock()
    job.contains_process.return_value = False
    context = {"job_query_ok": True, "process_in_job": True, "job_limit_flags": 0x1800}
    monkeypatch.setattr(qualification, "current_job_diagnostics", lambda: context)
    monkeypatch.setattr(qualification, "ProcessJob", lambda: job)
    identities = {source.pid: source, worker.pid: worker}
    monkeypatch.setattr(qualification, "process_identity", lambda pid: identities.get(pid))
    monkeypatch.setattr(qualification, "worker_flags", lambda _: 0x01000208)
    spawn = Mock(return_value=process)
    monkeypatch.setattr(qualification.subprocess, "Popen", spawn)
    ready = Mock(return_value=True)
    monkeypatch.setattr(qualification, "_read_ready", ready)
    diagnostic = Mock(return_value=True)
    monkeypatch.setattr(qualification, "process_in_any_job", diagnostic)
    return process, job, context, identities, spawn, ready, diagnostic


@pytest.mark.parametrize("ambient_job", [False, True])
def test_qualification_uses_bound_source_job_and_ready_not_ambient_job(monkeypatch, ambient_job):
    process, job, _, identities, spawn, ready, diagnostic = _qualification_mocks(monkeypatch)
    diagnostic.return_value = ambient_job
    result = qualification.qualify_owned_child()
    assert qualification.qualified_owned_result(result)
    assert result["worker_not_in_source_job"] is True
    job.contains_process.assert_called_once_with(process)
    source = identities[qualification.os.getpid()]
    ready.assert_called_once_with(process, spawn.call_args.args[0][6], source, identities[42])
    assert spawn.call_args.kwargs["creationflags"] == 0x01000208
    assert spawn.call_args.kwargs["stdout"] == qualification.subprocess.PIPE
    process.terminate.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=5)
    process.stdout.close.assert_called_once_with()
    job.close.assert_called_once_with()


@pytest.mark.parametrize("failure", ["context", "context-shape", "source", "worker", "source-member",
                                    "membership-query", "membership-shape", "ready", "ready-error",
                                    "ambient-query", "ambient-shape", "cleanup-denied", "cleanup-timeout",
                                    "cleanup-unconfirmed", "job-close"])
def test_qualification_refuses_unknown_identity_membership_ready_or_cleanup(monkeypatch, failure):
    process, job, context, identities, spawn, ready, diagnostic = _qualification_mocks(monkeypatch)
    if failure == "context":
        context["job_query_ok"] = False
    elif failure == "context-shape":
        context.pop("job_limit_flags")
    elif failure == "source":
        identities.pop(qualification.os.getpid())
    elif failure == "worker":
        identities.pop(42)
    elif failure == "source-member":
        job.contains_process.return_value = True
    elif failure == "membership-query":
        job.contains_process.side_effect = qualification.JobObjectError("owned query unavailable")
    elif failure == "membership-shape":
        job.contains_process.return_value = None
    elif failure == "ready":
        ready.return_value = False
    elif failure == "ready-error":
        ready.side_effect = OSError("bounded handshake failed")
    elif failure == "ambient-query":
        diagnostic.side_effect = qualification.JobObjectError("ambient membership query unavailable")
    elif failure == "ambient-shape":
        diagnostic.return_value = None
    elif failure == "cleanup-denied":
        process.terminate.side_effect = OSError("owned terminate denied")
    elif failure == "cleanup-timeout":
        process.wait.side_effect = qualification.subprocess.TimeoutExpired("owned worker", 5)
    elif failure == "cleanup-unconfirmed":
        process.wait.side_effect = None
    else:
        job.close.side_effect = qualification.JobObjectError("owned close unavailable")
    result = qualification.qualify_owned_child()
    assert not qualification.qualified_owned_result(result)
    assert result["qualified"] is False
    if failure in {"ambient-query", "ambient-shape"}:
        ready.assert_not_called()
        assert result["worker_any_job_query_ok"] is False
    if failure in {"context", "context-shape", "source"}:
        spawn.assert_not_called()
    else:
        assert spawn.call_count == 1
        assert process.terminate.call_count == 1
        if failure != "cleanup-denied":
            process.wait.assert_called_once_with(timeout=5)
        job.close.assert_called_once_with()


def test_qualification_breakaway_denial_has_no_unisolated_fallback(monkeypatch):
    _, job, _, _, spawn, ready, _ = _qualification_mocks(monkeypatch)
    spawn.side_effect = OSError("guarded creation denied")
    result = qualification.qualify_owned_child()
    assert result["qualified"] is False
    assert spawn.call_count == 1
    ready.assert_not_called()
    job.close.assert_called_once_with()
