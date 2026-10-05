"""Bounded, non-authoritative repair progress; query never performs recovery.

The kernel lease proves a runner is live. Plans/results, not display phases,
decide completion and recovery. No database, credentials or arbitrary paths.
"""
from __future__ import annotations

from pathlib import Path

from enterprise.install_entry import Snapshot, _atomic_publish, _document, _safe, _sha, _snapshot
from enterprise.release.release_manifest_v2 import canonical_json
from enterprise.release.current_release import sync_state_root_directory

SCHEMA = "enterprise-program-repair-progress-v1"
INDEX_SCHEMA = "enterprise-program-repair-progress-index-v1"
PHASES = {"preparing", "locked", "publishing", "verifying", "committed", "recovering", "rolled_back"}


def _index(roots):
    path = roots.STATE_ROOT / "program-repair-progress.json"
    before = _snapshot(path, maximum=16384)
    if before:
        from enterprise.install_repair import OPERATION, _fail
        value = _document(before.data)
        if (set(value) != {"schema_version", "operation_id", "root_identity", "installation_id"}
                or value["schema_version"] != INDEX_SCHEMA or value["root_identity"] != roots.root_identity
                or not isinstance(value["operation_id"], str) or not OPERATION.fullmatch(value["operation_id"])):
            _fail("INSTALL_PROGRAM_PROGRESS_INVALID")
        return path, before, value
    return path, None, None


class RepairProgress:
    def __init__(self, roots, binding, notify=None):
        self.roots, self.binding, self.notify = roots, binding, notify
        self.directory = _safe(roots.STAGING_ROOT / "program-repairs" / binding["operation_id"][:12])
        self.path = self.directory / "progress.json"
        self.previous = _snapshot(self.path, maximum=16384)
        if self.previous:
            old_progress = _document(self.previous.data)
            if (set(old_progress) != {"schema_version", *binding.keys(), "phase"}
                    or old_progress.get("schema_version") != SCHEMA or not isinstance(old_progress.get("phase"), str)
                    or old_progress["phase"] not in PHASES
                    or _binding(old_progress) != binding):
                from enterprise.install_repair import _fail
                _fail("INSTALL_PROGRAM_PROGRESS_INVALID")
        index, before, old = _index(roots)
        if old and old["installation_id"] != binding["installation_id"]:
            from enterprise.install_repair import _fail
            _fail("INSTALL_PROGRAM_PROGRESS_INVALID")
        value = {"schema_version": INDEX_SCHEMA, "operation_id": binding["operation_id"],
                 "root_identity": roots.root_identity, "installation_id": binding["installation_id"]}
        _atomic_publish(index, canonical_json(value), before)
        sync_state_root_directory(roots.STATE_ROOT)

    def emit(self, phase):
        if phase not in PHASES:
            raise ValueError("invalid repair progress phase")
        # Display persistence/transport cannot change a committed transaction.
        # If display fails, query still derives state from the owned plan/result.
        try:
            value = {"schema_version": SCHEMA, **self.binding, "phase": phase}
            self.previous = _atomic_publish(self.path, canonical_json(value), self.previous)
            sync_state_root_directory(self.directory)
        except (OSError, RuntimeError):
            pass
        if self.notify:
            try:
                self.notify(phase, self.binding["operation_id"])
            except Exception:
                pass  # Transport cannot decide the transaction outcome.


def _binding(plan):
    return {key: plan[key] for key in ("operation_id", "root_identity", "installation_id", "release_id",
                                      "manifest_sha256", "installation_record", "pointer", "original", "runner")}


def inspect_program_repair(*, install_root: Path, release_dir: Path, local_app_data_base: Path) -> dict:
    from enterprise.fresh_install import verify_release_assets
    from enterprise.install_repair import (
        LOCK_SCHEMA, PLAN_SCHEMA, RESULT_SCHEMA, OPERATION, _assert_plan_source, _fail,
        _identity_gate, _runner_lease, _tree_token, ProgramRepairError,
    )
    import os
    assets = verify_release_assets(release_dir)
    roots, installation_id, record, pointer = _identity_gate(Path(os.path.abspath(install_root)), assets, local_app_data_base)
    lock = _snapshot(roots.STATE_ROOT / "system-update-active.lock", maximum=16384)
    _, _, index = _index(roots)
    marker = _document(lock.data) if lock else None
    if marker and (set(marker) != {"schema_version", "operation_id", "plan_sha256", "root_identity"}
                   or marker["schema_version"] != LOCK_SCHEMA or marker["root_identity"] != roots.root_identity
                   or not isinstance(marker["operation_id"], str) or not OPERATION.fullmatch(marker["operation_id"])):
        _fail("INSTALL_PROGRAM_FOREIGN_LOCK")
    operation = marker["operation_id"] if marker else (index["operation_id"] if index else None)
    public = {"installation_id": installation_id, "release_id": roots.APP_ROOT.name,
              "database_changed": False, "pointer_changed": False, "entry_changed": False}
    if operation is None:
        return {**public, "operation_id": None, "repair_state": "NONE", "phase": "none"}
    directory = _safe(roots.STAGING_ROOT / "program-repairs" / operation[:12])
    progress = _snapshot(directory / "progress.json", maximum=16384)
    saved = _snapshot(directory / "plan.json", maximum=16384)
    plan = _document(saved.data) if saved else None
    if plan:
        if (set(plan) != {"schema_version", "operation_id", "root_identity", "installation_id", "release_id",
                         "manifest_sha256", "installation_record", "pointer", "original", "candidate", "runner"}
                or plan["schema_version"] != PLAN_SCHEMA):
            _fail("INSTALL_PROGRAM_PROGRESS_INVALID")
        _assert_plan_source(plan, roots, installation_id, record, pointer)
    if marker and (saved is None or _sha(saved.data) != marker["plan_sha256"]):
        _fail("INSTALL_PROGRAM_PROGRESS_INVALID")
    if progress:
        value = _document(progress.data)
        if (set(value) != {"schema_version", "operation_id", "root_identity", "installation_id", "release_id",
                          "manifest_sha256", "installation_record", "pointer", "original", "runner", "phase"}
                or value["schema_version"] != SCHEMA or not isinstance(value["phase"], str) or value["phase"] not in PHASES):
            _fail("INSTALL_PROGRAM_PROGRESS_INVALID")
        _assert_plan_source(value, roots, installation_id, record, pointer)
        if plan and _binding(plan) != _binding(value):
            _fail("INSTALL_PROGRAM_PROGRESS_INVALID")
    elif plan:
        value = {**_binding(plan), "phase": "locked"}  # Older v3 repair, no display record.
    else:
        _fail("INSTALL_PROGRAM_PROGRESS_INVALID")
    if (value["operation_id"] != operation or value["manifest_sha256"] != assets.manifest.raw_sha256
            or (index and index["installation_id"] != installation_id)):
        _fail("INSTALL_PROGRAM_PROGRESS_INVALID")
    token = value["runner"]
    if (not isinstance(token, dict) or set(token) != {"sha256", "identity"} or token["sha256"] != _sha(b"R")
            or not isinstance(token["identity"], list) or len(token["identity"]) != 2
            or any(type(item) is not int for item in token["identity"])):
        _fail("INSTALL_PROGRAM_PROGRESS_INVALID")
    busy = False
    try:
        with _runner_lease(directory / "runner.lock", Snapshot(b"R", tuple(token["identity"]))):
            pass
    except ProgramRepairError as exc:
        if exc.code != "INSTALL_PROGRAM_RUNNER_BUSY":
            raise
        busy = True
    # Queries are observations, never authorization. Re-read concurrent authority
    # after lease probing; an observed change asks the caller to refresh.
    if (_snapshot(roots.STATE_ROOT / "system-update-active.lock", maximum=16384) != lock
            or _snapshot(directory / "plan.json", maximum=16384) != saved
            or _snapshot(directory / "progress.json", maximum=16384) != progress):
        _fail("INSTALL_PROGRAM_PROGRESS_CHANGED")
    if busy:
        state = "RUNNING"
    elif lock:
        state = "RECOVERY_REQUIRED"
    else:
        result = _snapshot(directory / "result.json", maximum=16384)
        if result and plan:
            outcome = _document(result.data).get("status")
            if (outcome not in {"SUCCEEDED", "ROLLED_BACK"} or result.data != canonical_json({
                    "schema_version": RESULT_SCHEMA, "operation_id": operation,
                    "plan_sha256": _sha(saved.data), "status": outcome})):
                _fail("INSTALL_PROGRAM_PROGRESS_INVALID")
            expected = plan["candidate"] if outcome == "SUCCEEDED" else plan["original"]
            if _tree_token(roots.APP_ROOT) != expected:
                _fail("INSTALL_PROGRAM_RECOVERY_REQUIRED")
            state = outcome
        elif _tree_token(roots.APP_ROOT) == value["original"]:
            state = "STOPPED_BEFORE_SWITCH"
        else:
            _fail("INSTALL_PROGRAM_RECOVERY_REQUIRED")
    return {**public, "operation_id": operation, "repair_state": state, "phase": value["phase"]}
