"""Recoverable same-Release fixed-entry repair, never a second installer.

The immutable plan names every file identity before publication. Retained
hard-linked markers and an OS runner lease authorize recovery, not a phase,
timestamp, PID, or a same-byte replacement of a lock. Only the fixed EXE and
installation record can be restored; business data and pointers are read-only.
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

from enterprise.install_entry import (
    COMMIT, ENTRY_NAME, INSTANCE, RECORD_NAME, SHA, InstallEntryError,
    NativeEntry, Snapshot, _document, _record, _safe, _sha, _snapshot, _write_new,
    validate_entry_target_paths, validate_installation_record,
)
from enterprise.paths import PortableRootInputs, validate_path_roots_for_use
from enterprise.release.current_release import (
    read_current_release_result_from_state_root, resolve_portable_path_roots,
    sync_state_root_directory,
)
from enterprise.release.release_manifest_v2 import (
    canonical_json, enforce_portable_contract_compatibility,
    read_release_manifest_v2, verify_materialized_release,
)

LOCK_SCHEMA = "enterprise-entry-maintenance-lock-v2"
PLAN_SCHEMA = "enterprise-entry-maintenance-plan-v2"
RESULT_SCHEMA = "enterprise-entry-maintenance-result-v2"
FENCE_SCHEMA = "enterprise-entry-maintenance-fence-v2"
STAGES = {"entry": ("candidate-entry.exe", "restore-entry.exe"),
          "record": ("candidate-record.json", "restore-record.json")}


def _fail(code="INSTALL_ENTRY_RECOVERY_REQUIRED"):
    raise InstallEntryError(code)


def _checkpoint(name: str):
    """Tests may terminate their own runner; no production injection switch."""


def _token(value: Snapshot | None):
    return None if value is None else {"sha256": _sha(value.data),
        "identity": list(value.identity), "size_bytes": len(value.data)}


def _valid_identity(value):
    return (isinstance(value, list) and len(value) == 2
            and all(type(item) is int and item >= 0 for item in value))


def _valid_token(value, *, optional=False):
    if value is None:
        return optional
    return (isinstance(value, dict) and set(value) == {"sha256", "identity", "size_bytes"}
            and isinstance(value["sha256"], str) and SHA.fullmatch(value["sha256"])
            and _valid_identity(value["identity"])
            and type(value["size_bytes"]) is int and 0 < value["size_bytes"] <= 4 * 1024 * 1024)


def _directory_identity(path):
    path = _safe(path)
    info = path.stat()
    if not path.is_dir():
        _fail("INSTALL_ENTRY_PATH_UNSAFE")
    return [info.st_dev, info.st_ino]


def _bundle(entry):
    if (not isinstance(entry, NativeEntry) or not isinstance(entry.data, bytes)
            or not entry.data.startswith(b"MZ") or len(entry.data) > 4 * 1024 * 1024
            or _sha(entry.data) != entry.sha256
            or not all(isinstance(value, str) and COMMIT.fullmatch(value)
                       for value in (entry.source_commit, entry.source_tree))
            or not isinstance(entry.record_sha256, str) or not SHA.fullmatch(entry.record_sha256)):
        _fail("INSTALL_ENTRY_BUNDLE_INVALID")
    return {"sha256": entry.sha256, "source_commit": entry.source_commit,
            "source_tree": entry.source_tree, "build_record_sha256": entry.record_sha256}


def _source_unchecked(install_root, entry, local_app_data_base):
    """Real pointer, full current payload and independently verified EXE binding."""
    root = _safe(Path(os.path.abspath(install_root)))
    roots = resolve_portable_path_roots(PortableRootInputs(root, local_app_data_base))
    validate_path_roots_for_use(roots)
    pointer = read_current_release_result_from_state_root(roots.STATE_ROOT)
    observed = _snapshot(roots.STATE_ROOT / "current-release.json", maximum=16384)
    manifest = read_release_manifest_v2(roots.APP_ROOT / "release-manifest.json")
    native = _bundle(entry)
    if (observed is None or _sha(observed.data) != pointer.raw_sha256
            or manifest.raw_sha256 != pointer.release.manifest_sha256
            or manifest.release_id != pointer.release.release_id):
        _fail("INSTALL_ENTRY_SOURCE_INVALID")
    enforce_portable_contract_compatibility(manifest)
    validate_entry_target_paths(root, manifest.release_id, roots.APP_ROOT / "release-payload-inventory.json")
    verify_materialized_release(roots.APP_ROOT, inventory_path=roots.APP_ROOT / "release-payload-inventory.json")
    from enterprise.ops.update.mvp import UpdateJobStore
    if UpdateJobStore(roots).pending_recovery_jobs(initialize=False):
        _fail("INSTALL_ENTRY_UPDATE_RECOVERY_REQUIRED")
    return roots, manifest.raw_sha256, _token(observed), native


def _source(install_root, entry, local_app_data_base):
    try:
        return _source_unchecked(install_root, entry, local_app_data_base)
    except InstallEntryError:
        raise
    except Exception as exc:
        raise InstallEntryError("INSTALL_ENTRY_SOURCE_INVALID") from exc


def _runtime_quiescent(roots):
    from enterprise.install_repair import ProgramRepairError, _runtime_quiescent as check
    try:
        check(roots)
    except ProgramRepairError as exc:
        _fail(exc.code.replace("INSTALL_PROGRAM_", "INSTALL_ENTRY_"))


@contextmanager
def _runner_lease(path, expected):
    """Kernel ownership is released by close even if explicit unlock fails."""
    _safe(path)
    handle = path.open("r+b")
    locked = False
    cleanup_warnings = []
    try:
        info = os.fstat(handle.fileno())
        if (info.st_dev, info.st_ino) != expected.identity:
            _fail()
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise InstallEntryError("INSTALL_ENTRY_RUNNER_BUSY") from exc
        if os.fstat(handle.fileno()).st_size != 1 or handle.read(1) != b"R":
            _fail()
        yield cleanup_warnings
    finally:
        try:
            if locked:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle, fcntl.LOCK_UN)
                except OSError:
                    cleanup_warnings.append("INSTALL_ENTRY_LEASE_RELEASE_UNCONFIRMED")
        finally:
            try:
                handle.close()  # Closing is the final kernel lease release.
            except OSError:
                if not cleanup_warnings:
                    cleanup_warnings.append("INSTALL_ENTRY_LEASE_RELEASE_UNCONFIRMED")
                # Never mask an exception already escaping the transaction.


def _paths(roots):
    return {"entry": roots.INSTALL_ROOT / ENTRY_NAME,
            "record": roots.STATE_ROOT / RECORD_NAME}


def _fence_retained(roots, operation):
    # INSTALL_ROOT may be on D: while KnownFolder Runtime is on C:. Both
    # names of a hard link must live on the same volume; never copy a marker
    # as a fallback because that would destroy its identity proof.
    return roots.RUNTIME_ROOT / "entry-repair-fences" / operation[:12] / "fence.marker"


def _fill_prepared_marker(path, placeholder, data):
    """Finish an unpublished marker without changing its registered inode."""
    if _snapshot(path, maximum=16384) != placeholder:
        _fail()
    _safe(path)
    with path.open("r+b") as handle:
        info = os.fstat(handle.fileno())
        if (info.st_dev, info.st_ino) != placeholder.identity:
            _fail()
        handle.write(data)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
    expected = Snapshot(data, placeholder.identity)
    if _snapshot(path, maximum=16384) != expected:
        _fail()
    return expected


def _same_source(plan, roots, manifest, pointer, native):
    if (plan["root_identity"] != roots.root_identity
            or plan["install_root_identity"] != _directory_identity(roots.INSTALL_ROOT)
            or plan["runtime_root_identity"] != _directory_identity(roots.RUNTIME_ROOT)
            or plan["release_id"] != roots.APP_ROOT.name
            or plan["manifest_sha256"] != manifest or plan["pointer"] != pointer
            or plan["native_entry"] != native):
        _fail("INSTALL_ENTRY_SOURCE_CHANGED")


def _validate_plan(plan, marker):
    if (set(plan) != {"schema_version", "operation_id", "root_identity", "install_root_identity",
            "runtime_root_identity", "installation_id", "release_id", "manifest_sha256",
            "pointer", "native_entry", "files", "runner"}
            or plan["schema_version"] != PLAN_SCHEMA
            or plan["operation_id"] != marker["operation_id"]
            or plan["root_identity"] != marker["root_identity"]
            or not isinstance(plan["installation_id"], str) or not INSTANCE.fullmatch(plan["installation_id"])
            or not isinstance(plan["release_id"], str)
            or not isinstance(plan["manifest_sha256"], str) or not SHA.fullmatch(plan["manifest_sha256"])
            or not _valid_identity(plan["install_root_identity"])
            or not _valid_identity(plan["runtime_root_identity"])
            or not _valid_token(plan["pointer"]) or not _valid_token(plan["runner"])
            or plan["runner"]["sha256"] != _sha(b"R") or plan["runner"]["size_bytes"] != 1
            or not isinstance(plan["files"], dict) or set(plan["files"]) != set(STAGES)
            or not isinstance(plan["native_entry"], dict)
            or set(plan["native_entry"]) != {"sha256", "source_commit", "source_tree", "build_record_sha256"}):
        _fail()
    for name, value in plan["files"].items():
        if (not isinstance(value, dict) or set(value) != {"original", "candidate", "restore", "publish"}
                or not _valid_token(value["original"], optional=True)
                or not _valid_token(value["candidate"])
                or not _valid_token(value["restore"], optional=True)
                or type(value["publish"]) is not bool
                or (value["original"] is None) != (value["restore"] is None)):
            _fail()
        if value["original"] is not None:
            if (value["restore"]["sha256"] != value["original"]["sha256"]
                    or value["restore"]["size_bytes"] != value["original"]["size_bytes"]
                    or value["restore"]["identity"] == value["original"]["identity"]):
                _fail()
        different = value["original"] is None or any(value["original"][key] != value["candidate"][key]
                                                     for key in ("sha256", "size_bytes"))
        if value["publish"] != different:
            _fail()


def _inspect_files(directory, plan, roots, entry):
    """Validate BOTH targets and ALL staged identities before changing either."""
    states, observed = {}, {}
    for name, target in _paths(roots).items():
        spec = plan["files"][name]
        current = _snapshot(target)
        token = _token(current)
        if token == spec["original"]:
            state = "original"
        elif spec["publish"] and token == spec["candidate"]:
            state = "candidate"
        elif spec["publish"] and spec["restore"] is not None and token == spec["restore"]:
            state = "restored"
        else:
            _fail()
        candidate = _snapshot(directory / STAGES[name][0])
        restore = _snapshot(directory / STAGES[name][1])
        if candidate is not None and _token(candidate) != spec["candidate"]:
            _fail()
        if restore is not None and _token(restore) != spec["restore"]:
            _fail()
        if state == "original" and spec["original"] is not None and candidate is None:
            _fail()
        if not spec["publish"] and candidate is None:
            _fail()
        if spec["restore"] is not None and ((state == "restored") == (restore is not None)):
            _fail()
        if spec["restore"] is None and restore is not None:
            _fail()
        states[name] = state
        observed[name] = (current, candidate, restore)
    record, candidate, restore = observed["record"]
    if record is not None:
        identity = validate_installation_record(roots.INSTALL_ROOT, record)
        if identity["installation_id"] != plan["installation_id"]:
            _fail()
    old = (restore if restore is not None else record) if plan["files"]["record"]["original"] is not None else None
    if plan["files"]["record"]["original"] is not None and states["record"] == "candidate" and restore is None:
        _fail()
    if old is not None and validate_installation_record(roots.INSTALL_ROOT, old)["installation_id"] != plan["installation_id"]:
        _fail()
    candidate_record = _record(roots.INSTALL_ROOT, entry, old)
    # A pointer-owning historical installation may not yet have a record. Its
    # new identity is chosen once during preparation, never again on recovery.
    candidate_record["installation_id"] = plan["installation_id"]
    expected = canonical_json(candidate_record)
    validate_installation_record(roots.INSTALL_ROOT, Snapshot(expected, (0, 0)))
    candidate_token = plan["files"]["record"]["candidate"]
    if _sha(expected) != candidate_token["sha256"] or len(expected) != candidate_token["size_bytes"]:
        _fail()
    # After rollback the candidate was consumed and the target contains the
    # old bytes. Reconstructing the candidate from those independently bound
    # old bytes is valid; it must not require the rejected candidate to exist.
    if candidate is not None and candidate.data != expected:
        _fail()
    if states["record"] == "candidate" and record.data != expected:
        _fail()
    candidate_token = plan["files"]["entry"]["candidate"]
    if candidate_token["sha256"] != entry.sha256 or candidate_token["size_bytes"] != len(entry.data):
        _fail()
    candidate_entry = observed["entry"][1]
    if candidate_entry is not None and candidate_entry.data != entry.data:
        _fail()
    return states


def _link_marker(retained, path, expected, *, busy):
    if _snapshot(retained, maximum=16384) != expected:
        _fail()
    _safe(path, missing=True)
    try:
        os.link(retained, path)
    except FileExistsError as exc:
        raise InstallEntryError(busy) from exc
    if _snapshot(path, maximum=16384) != expected:
        _fail()
    sync_state_root_directory(path.parent)


def _marker_pair(directory, roots, lock):
    if (_snapshot(directory / "common.marker", maximum=16384) != lock
            or _snapshot(roots.STATE_ROOT / "system-update-active.lock", maximum=16384) != lock):
        _fail()
    common_value = _document(lock.data)
    saved = _snapshot(directory / "plan.json", maximum=16384)
    if saved is None or _token(saved) != common_value["plan"]:
        _fail()
    plan = _document(saved.data)
    runner_path = _safe(directory / "runner.lock")
    runner_info = runner_path.stat()
    if ([runner_info.st_dev, runner_info.st_ino] != plan["runner"]["identity"]
            or runner_info.st_size != 1):
        _fail()
    fence = _snapshot(_fence_retained(roots, common_value["operation_id"]), maximum=16384)
    expected = {key: value for key, value in common_value.items() if key != "fence"}
    expected["schema_version"] = FENCE_SCHEMA
    expected["common_identity"] = list(lock.identity)
    if (fence is None or _token(fence) != common_value["fence"]
            or fence.data != canonical_json(expected)):
        _fail()
    return fence


def _acquire_fence(directory, roots, lock):
    fence = _marker_pair(directory, roots, lock)
    path = roots.RUNTIME_ROOT / "runtime-reconcile.lock"
    current = _snapshot(path, maximum=16384)
    if current is not None and current != fence:
        _fail("INSTALL_ENTRY_FOREIGN_FENCE")
    if current is None:
        operation = _document(lock.data)["operation_id"]
        _link_marker(_fence_retained(roots, operation), path, fence, busy="INSTALL_ENTRY_RUNTIME_BUSY")
    return fence


def _owned_locks(directory, roots, lock, fence):
    if (_marker_pair(directory, roots, lock) != fence
            or _snapshot(roots.RUNTIME_ROOT / "runtime-reconcile.lock", maximum=16384) != fence):
        _fail()


def _result_value(plan, saved, status):
    return {"schema_version": RESULT_SCHEMA, "operation_id": plan["operation_id"],
            "plan": _token(saved), "status": status}


def _read_result(directory, plan, saved):
    existing = _snapshot(directory / "result.json", maximum=16384)
    if existing is None:
        return None
    value = _document(existing.data)
    status = value.get("status")
    if status not in {"SUCCEEDED", "ROLLED_BACK"} or existing.data != canonical_json(_result_value(plan, saved, status)):
        _fail()
    return status


def _persist_result(directory, plan, saved, status):
    existing = _read_result(directory, plan, saved)
    if existing is not None and existing != status:
        _fail()
    if existing is None:
        _write_new(directory / "result.json", canonical_json(_result_value(plan, saved, status)))
    # A failure AFTER the SUCCEEDED bytes are fsynced is not rollback authority.
    sync_state_root_directory(directory)


def _publish(directory, plan, roots, name):
    spec = plan["files"][name]
    if not spec["publish"]:
        return
    target = _paths(roots)[name]
    stage = directory / STAGES[name][0]
    if _token(_snapshot(target)) != spec["original"] or _token(_snapshot(stage)) != spec["candidate"]:
        _fail()
    if spec["original"] is None:
        os.link(stage, target)  # Create-only, never overwrite a raced destination.
        stage.unlink()
    else:
        os.replace(stage, target)
    sync_state_root_directory(target.parent)


def _rollback(directory, plan, roots, entry):
    states = _inspect_files(directory, plan, roots, entry)
    for name in ("record", "entry"):
        if states[name] != "candidate":
            continue
        _checkpoint("restoring_" + name)
        target = _paths(roots)[name]
        spec = plan["files"][name]
        if _token(_snapshot(target)) != spec["candidate"]:
            _fail()
        if spec["original"] is None:
            target.unlink()
        else:
            stage = directory / STAGES[name][1]
            if _token(_snapshot(stage)) != spec["restore"]:
                _fail()
            os.replace(stage, target)
        sync_state_root_directory(target.parent)
        _checkpoint(name + "_restored")
    states = _inspect_files(directory, plan, roots, entry)
    if any(state == "candidate" for state in states.values()):
        _fail()


def _cleanup(directory, roots, lock, fence):
    _owned_locks(directory, roots, lock, fence)
    (roots.RUNTIME_ROOT / "runtime-reconcile.lock").unlink()
    sync_state_root_directory(roots.RUNTIME_ROOT)
    _checkpoint("fence_released")
    # Retained markers must still match before removing the common lock.
    if _marker_pair(directory, roots, lock) != fence:
        _fail()
    (roots.STATE_ROOT / "system-update-active.lock").unlink()
    try:
        sync_state_root_directory(roots.STATE_ROOT)
    except Exception:
        # The common lock is already absent and the durable terminal result
        # was written earlier. There is no active transaction to recover; a
        # failed final directory flush cannot truthfully demand one.
        return "INSTALL_ENTRY_DIRECTORY_SYNC_UNCONFIRMED"
    return None


def _public(plan, status, warning=None):
    value = {"operation_id": plan["operation_id"], "installation_id": plan["installation_id"],
            "release_id": plan["release_id"], "repair_state": status,
            "launcher_installed": status == "SUCCEEDED" or plan["files"]["entry"]["original"] is not None,
            "database_changed": False, "pointer_changed": False}
    if warning is not None:
        value["cleanup_warning"] = warning
    return value


def _lease_warning(roots, lock, cleanup_warnings, warning):
    if cleanup_warnings:
        if _snapshot(roots.STATE_ROOT / "system-update-active.lock", maximum=16384) == lock:
            _fail()
        return warning or cleanup_warnings[0]
    return warning


def repair_entry_transaction(*, install_root: Path, entry: NativeEntry, local_app_data_base: Path) -> dict:
    try:
        roots, manifest, pointer, native = _source(install_root, entry, local_app_data_base)
        if _snapshot(roots.STATE_ROOT / "system-update-active.lock", maximum=16384) is not None:
            _fail("INSTALL_ENTRY_MAINTENANCE_BUSY")
        if _snapshot(roots.RUNTIME_ROOT / "runtime-reconcile.lock", maximum=16384) is not None:
            _fail("INSTALL_ENTRY_RUNTIME_BUSY")
        _runtime_quiescent(roots)
        originals = {name: _snapshot(path) for name, path in _paths(roots).items()}
        candidate_record = _record(roots.INSTALL_ROOT, entry, originals["record"])
        identity = validate_installation_record(roots.INSTALL_ROOT, originals["record"]) if originals["record"] else None
        if originals["entry"] is not None and _sha(originals["entry"].data) != entry.sha256:
            owner = identity["native_entry"]["sha256"] if identity else None
            legacy = _snapshot(roots.STATE_ROOT / "native-entry.json", maximum=16384)
            if owner is None and legacy is not None:
                old = _document(legacy.data)
                if set(old) == {"schema_version", "launcher_sha256"} and old.get("schema_version") == "enterprise-native-entry-v1":
                    owner = old.get("launcher_sha256")
            if owner != _sha(originals["entry"].data):
                _fail("INSTALL_ENTRY_UNOWNED_FILE")
        operation = uuid.uuid4().hex
        area = _safe(roots.STAGING_ROOT / "entry-repairs", missing=True)
        directory = area / operation[:12]
        names = ["plan.json", "runner.lock", "common.marker", "result.json",
                 *(name for pair in STAGES.values() for name in pair)]
        if (any(len(str(directory / name).encode("utf-16-le")) // 2 >= 260 for name in names)
                or len(str(_fence_retained(roots, operation)).encode("utf-16-le")) // 2 >= 260):
            _fail("INSTALL_ENTRY_TARGET_PATH_TOO_LONG")
        area.mkdir(parents=True, exist_ok=True)
        _safe(area)
        directory.mkdir()
        _safe(roots.RUNTIME_ROOT, missing=True).mkdir(parents=True, exist_ok=True)
        runner = _write_new(directory / "runner.lock", b"R")
        with _runner_lease(directory / "runner.lock", runner) as lease_warnings:
            candidates = {"entry": entry.data, "record": canonical_json(candidate_record)}
            files = {}
            for name, (candidate_name, restore_name) in STAGES.items():
                original = originals[name]
                candidate = _write_new(directory / candidate_name, candidates[name])
                restore = _write_new(directory / restore_name, original.data) if original is not None else None
                files[name] = {"original": _token(original), "candidate": _token(candidate),
                    "restore": _token(restore), "publish": original is None or original.data != candidate.data}
            plan = {"schema_version": PLAN_SCHEMA, "operation_id": operation,
                "root_identity": roots.root_identity, "install_root_identity": _directory_identity(roots.INSTALL_ROOT),
                "runtime_root_identity": _directory_identity(roots.RUNTIME_ROOT),
                "installation_id": candidate_record["installation_id"], "release_id": roots.APP_ROOT.name,
                "manifest_sha256": manifest, "pointer": pointer, "native_entry": native,
                "files": files, "runner": _token(runner)}
            saved = _write_new(directory / "plan.json", canonical_json(plan))
            marker = {"schema_version": LOCK_SCHEMA, "operation_id": operation,
                      "root_identity": roots.root_identity, "plan": _token(saved)}
            placeholder = _write_new(directory / "common.marker", b"P")
            retained_fence = _safe(_fence_retained(roots, operation), missing=True)
            fence_area = _safe(retained_fence.parent.parent, missing=True)
            fence_area.mkdir(exist_ok=True)
            _safe(fence_area)
            retained_fence.parent.mkdir()
            fence = _write_new(retained_fence, canonical_json({**marker, "schema_version": FENCE_SCHEMA,
                                                            "common_identity": list(placeholder.identity)}))
            sync_state_root_directory(retained_fence.parent)
            marker["fence"] = _token(fence)
            lock = _fill_prepared_marker(directory / "common.marker", placeholder, canonical_json(marker))
            sync_state_root_directory(directory)
            _link_marker(directory / "common.marker", roots.STATE_ROOT / "system-update-active.lock",
                         lock, busy="INSTALL_ENTRY_MAINTENANCE_BUSY")
            # An interruption from here retains a fully prepared recovery plan.
            try:
                _checkpoint("locked")
                _acquire_fence(directory, roots, lock)
                _checkpoint("fenced")
                _runtime_quiescent(roots)
                _same_source(plan, *_source(install_root, entry, local_app_data_base))
                states = _inspect_files(directory, plan, roots, entry)
                if any(state != "original" for state in states.values()):
                    _fail()
                _owned_locks(directory, roots, lock, fence)
                _checkpoint("prepared")
                _publish(directory, plan, roots, "entry")
                _checkpoint("entry_published")
                _publish(directory, plan, roots, "record")
                _checkpoint("record_published")
                _same_source(plan, *_source(install_root, entry, local_app_data_base))
                states = _inspect_files(directory, plan, roots, entry)
                if any(states[name] != ("candidate" if spec["publish"] else "original")
                       for name, spec in plan["files"].items()):
                    _fail()
                _owned_locks(directory, roots, lock, fence)
                _persist_result(directory, plan, saved, "SUCCEEDED")
            except Exception as exc:
                # A written success is authoritative even if a subsequent sync
                # failed. Unknown result state also blocks rather than guesses.
                try:
                    status = _read_result(directory, plan, saved)
                except Exception as result_error:
                    raise InstallEntryError("INSTALL_ENTRY_RECOVERY_REQUIRED") from result_error
                if status is not None:
                    raise InstallEntryError("INSTALL_ENTRY_RECOVERY_REQUIRED") from exc
                try:
                    # If no fence was obtained, no target was touched; leave a
                    # foreign shared-runtime fence untouched and the common
                    # marker for explicit recovery instead of deleting it.
                    _owned_locks(directory, roots, lock, fence)
                    _runtime_quiescent(roots)
                    _same_source(plan, *_source(install_root, entry, local_app_data_base))
                    _rollback(directory, plan, roots, entry)
                    _persist_result(directory, plan, saved, "ROLLED_BACK")
                    _checkpoint("rolled_back")
                    _cleanup(directory, roots, lock, fence)
                except Exception as rollback_error:
                    raise InstallEntryError("INSTALL_ENTRY_RECOVERY_REQUIRED") from rollback_error
                if isinstance(exc, InstallEntryError):
                    raise
                raise InstallEntryError("INSTALL_ENTRY_REPAIR_FAILED") from exc
            # Commit is outside the rollback handler. Cleanup failure cannot
            # revert an already successful publication.
            _checkpoint("committed")
            warning = _cleanup(directory, roots, lock, fence)
        warning = _lease_warning(roots, lock, lease_warnings, warning)
        return _public(plan, "SUCCEEDED", warning)
    except InstallEntryError:
        raise
    except Exception as exc:
        raise InstallEntryError("INSTALL_ENTRY_RECOVERY_REQUIRED") from exc


def recover_entry_transaction(*, install_root: Path, entry: NativeEntry, local_app_data_base: Path) -> dict:
    try:
        roots, manifest, pointer, native = _source(install_root, entry, local_app_data_base)
        path = roots.STATE_ROOT / "system-update-active.lock"
        lock = _snapshot(path, maximum=16384)
        if lock is None:
            _fail("INSTALL_ENTRY_NO_RECOVERY")
        marker = _document(lock.data)
        if (set(marker) != {"schema_version", "operation_id", "root_identity", "plan", "fence"}
                or marker["schema_version"] != LOCK_SCHEMA
                or not isinstance(marker["operation_id"], str) or not INSTANCE.fullmatch(marker["operation_id"])
                or marker["root_identity"] != roots.root_identity or not _valid_token(marker["plan"])
                or not _valid_token(marker["fence"])):
            _fail("INSTALL_ENTRY_FOREIGN_LOCK")
        directory = _safe(roots.STAGING_ROOT / "entry-repairs" / marker["operation_id"][:12])
        saved = _snapshot(directory / "plan.json", maximum=16384)
        if saved is None or _token(saved) != marker["plan"]:
            _fail()
        plan = _document(saved.data)
        _validate_plan(plan, marker)
        _same_source(plan, roots, manifest, pointer, native)
        runner = Snapshot(b"R", tuple(plan["runner"]["identity"]))
        with _runner_lease(directory / "runner.lock", runner) as lease_warnings:
            fence = _marker_pair(directory, roots, lock)
            states = _inspect_files(directory, plan, roots, entry)
            status = _read_result(directory, plan, saved)
            if status == "SUCCEEDED":
                if any(states[name] != ("candidate" if spec["publish"] else "original")
                       for name, spec in plan["files"].items()):
                    _fail()
            elif status == "ROLLED_BACK" and any(state == "candidate" for state in states.values()):
                _fail()
            _runtime_quiescent(roots)
            _acquire_fence(directory, roots, lock)
            _owned_locks(directory, roots, lock, fence)
            _runtime_quiescent(roots)
            _same_source(plan, *_source(install_root, entry, local_app_data_base))
            _inspect_files(directory, plan, roots, entry)
            if status is None:
                _rollback(directory, plan, roots, entry)
                _persist_result(directory, plan, saved, "ROLLED_BACK")
                status = "ROLLED_BACK"
                _checkpoint("rolled_back")
            warning = _cleanup(directory, roots, lock, fence)
        warning = _lease_warning(roots, lock, lease_warnings, warning)
        return _public(plan, status, warning)
    except InstallEntryError:
        raise
    except Exception as exc:
        raise InstallEntryError("INSTALL_ENTRY_RECOVERY_REQUIRED") from exc
