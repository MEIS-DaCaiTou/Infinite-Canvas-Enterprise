"""Retain-data uninstall and same-Release reinstall, not a migration engine.

Program and entry objects move to a verified recovery set on the same volume.
No business/database/config/backup bytes are written, removed or initialized.
Windows registration/shortcuts belong to Setup. Retention/GC is not invented.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from enterprise import install_cache as files
from enterprise.fresh_install import verify_release_assets
from enterprise.install_entry import ENTRY_NAME, _snapshot, validate_installation_record
from enterprise.install_repair import _runtime_quiescent
from enterprise.migrations.versioned import inspect_schema_metadata_connection
from enterprise.ops.update.mvp import UpdateJobStore
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, validate_path_roots_for_use
from enterprise.release.current_release import read_current_release_result_from_state_root, sync_state_root_directory
from enterprise.release.release_manifest_v2 import canonical_json, read_release_manifest_v2, verify_materialized_release
from enterprise.runtime.windows_owned_move import rename_owned, release_fence

PLAN_SCHEMA = "enterprise-retained-lifecycle-plan-v1"
STATE_SCHEMA = "enterprise-retained-lifecycle-state-v1"
FENCE_SCHEMA = "enterprise-retained-lifecycle-fence-v1"
STATE_NAME = "retained-installation.json"
STATES = {"UNINSTALLING", "UNINSTALLED", "REINSTALLING", "INSTALLED"}
PLAN_KEYS = {"schema_version", "operation_id", "installation_id", "release_id", "manifest_sha256",
             "install_root", "root_identity", "record", "pointer", "data_identity", "config_identity",
             "database_identity", "config", "database_contract", "program", "entry", "fence", "lease"}
STATE_KEYS = {"schema_version", "operation_id", "installation_id", "plan_sha256", "status"}


class LifecycleError(RuntimeError):
    def __init__(self, code="INSTALL_LIFECYCLE_RECOVERY_REQUIRED"):
        self.code = code
        super().__init__(code)


def _fail(code="INSTALL_LIFECYCLE_RECOVERY_REQUIRED"):
    raise LifecycleError(code)


def _checkpoint(stage):
    """Owned-copy tests can kill their runner; no production injection switch."""


def _plain_file_identity(path):
    files._safe(path)
    with files._io(path).open("rb") as stream:
        info = os.fstat(stream.fileno())
        if not files.stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _fail("INSTALL_LIFECYCLE_CHANGED")
        return files._fd_identity(stream)


def _database_inspection(roots):
    """Read offline SQLite metadata; never recover or ignore a WAL/journal."""
    database = roots.DATA_ROOT / "enterprise.db"
    files._safe(database)
    info = files._io(database).lstat()
    if not files.stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail("INSTALL_LIFECYCLE_DATABASE_UNPROVEN")
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = database.with_name(database.name + suffix)
        files._safe(sidecar, missing=True)
        if files._exists(sidecar):
            _fail("INSTALL_LIFECYCLE_DATABASE_RECOVERY_REQUIRED")
    # immutable is permitted only after explicitly rejecting all sidecars and
    # proving Runtime quiescence. It prevents readonly inspection creating SHM.
    uri = database.as_uri() + "?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            metadata = inspect_schema_metadata_connection(connection)
            if not metadata.get("is_ready") or connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                _fail("INSTALL_LIFECYCLE_DATABASE_UNPROVEN")
    except sqlite3.Error as exc:
        raise LifecycleError("INSTALL_LIFECYCLE_DATABASE_UNPROVEN") from exc
    after = files._io(database).lstat()
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        _fail("INSTALL_LIFECYCLE_CHANGED")
    return metadata


def _database_contract(roots):
    metadata = _database_inspection(roots)
    return {name: metadata[name] for name in ("schema_version", "schema_sha256", "ledger_sha256")}


def _marker(path):
    """Fence is a deliberately retained two-link object, unlike payload files."""
    files._safe(path)
    with files._io(path).open("rb") as stream:
        info = os.fstat(stream.fileno())
        if info.st_nlink not in {1, 2} or not 0 < info.st_size < 16384:
            _fail()
        raw = stream.read(16384)
        if len(raw) != info.st_size:
            _fail()
        return {"identity": files._fd_identity(stream), "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest()}


def _read_fence(path):
    snapshot = _snapshot(path, maximum=16384)
    if snapshot is None:
        _fail()
    try:
        value = json.loads(snapshot.data)
    except (ValueError, UnicodeError):
        _fail()
    if not isinstance(value, dict) or canonical_json(value) != snapshot.data:
        _fail()
    return value


def _source(root, assets, local):
    return _source_manifest(root, assets.manifest, local)


def _source_manifest(root, manifest, local):
    root = files._safe(root)
    pointer = read_current_release_result_from_state_root(root / "state")
    if (pointer.release.release_id != manifest.release_id
            or pointer.release.manifest_sha256 != manifest.raw_sha256):
        _fail("INSTALL_LIFECYCLE_SAME_RELEASE_REQUIRED")
    roots = derive_portable_path_roots(PortableRootInputs(root, local), pointer.release.release_id)
    validate_path_roots_for_use(roots)
    before = _snapshot(roots.STATE_ROOT / "installation.json", maximum=16384)
    if before is None:
        _fail("INSTALL_LIFECYCLE_IDENTITY_REQUIRED")
    record = validate_installation_record(root, before)
    if files._exists(roots.STATE_ROOT / "install-upgrade-active.json"):
        _fail("INSTALL_LIFECYCLE_UPGRADE_RECOVERY_REQUIRED")
    if UpdateJobStore(roots).pending_recovery_jobs(initialize=False):
        _fail("INSTALL_LIFECYCLE_UPDATE_RECOVERY_REQUIRED")
    if files._exists(roots.RUNTIME_ROOT / "runtime-reconcile.lock"):
        _fail("INSTALL_LIFECYCLE_RUNTIME_BUSY")
    _runtime_quiescent(roots)
    return roots, record


def current_source(*, install_root, local_app_data_base):
    """Verify the installed/retained source, independently of the tool's version.

    An absent program is accepted only through the existing immutable lifecycle
    plan and its exact object placement. This never adopts an unknown layout.
    """
    root = files._safe(Path(install_root))
    pointer = read_current_release_result_from_state_root(root / "state")
    roots = derive_portable_path_roots(PortableRootInputs(root, Path(local_app_data_base)), pointer.release.release_id)
    program = roots.APP_ROOT
    if not files._exists(program):
        directory, plan, state = _active(roots)
        if state is None or state["status"] not in {"UNINSTALLED", "REINSTALLING", "UNINSTALLING"}:
            _fail()
        program, _entry = _placements(roots, directory, plan)
    manifest = read_release_manifest_v2(program / "release-manifest.json")
    roots, record = _source_manifest(root, manifest, Path(local_app_data_base))
    verify_materialized_release(program, inventory_path=program / "release-payload-inventory.json")
    if files._exists(roots.STATE_ROOT / STATE_NAME):
        directory, plan, state = _active(roots)
        if state is not None and state["status"] != "INSTALLED":
            with files._lease(directory / "runner.lock", plan["lease"]):
                _unchanged(roots, record, plan)
                _placements(roots, directory, plan)
    return roots, record, manifest


def _state(directory, plan, status):
    if status not in STATES:
        _fail()
    path = directory.parent.parent / STATE_NAME
    files._state(path, {"schema_version": STATE_SCHEMA, "operation_id": plan["operation_id"],
        "installation_id": plan["installation_id"],
        "plan_sha256": hashlib.sha256(canonical_json(plan)).hexdigest(), "status": status})
    _checkpoint("state_" + status.lower())


def _active(roots):
    descriptor = roots.STATE_ROOT / STATE_NAME
    lock = roots.STATE_ROOT / "system-update-active.lock"
    state = files._read(descriptor)[0] if files._exists(descriptor) else None
    if state is not None and (set(state) != STATE_KEYS or state["schema_version"] != STATE_SCHEMA
            or not files.ID.fullmatch(str(state["operation_id"]))
            or not files.ID.fullmatch(str(state["installation_id"]))
            or not files.SHA.fullmatch(str(state["plan_sha256"])) or state["status"] not in STATES):
        _fail()
    # A fully prepared fence precedes descriptor publication. Recovering a
    # death here reads its immutable plan; unknown lock formats stay blocked.
    if files._exists(lock):
        marker = _read_fence(lock)
        if (set(marker) != {"schema_version", "operation_id", "installation_id"}
                or marker["schema_version"] != FENCE_SCHEMA
                or not files.ID.fullmatch(str(marker["operation_id"]))):
            _fail()
        operation = marker["operation_id"]
        if state is not None and state["operation_id"] != operation:
            # A new fully prepared operation may follow a completed reinstall.
            if state["status"] != "INSTALLED":
                _fail()
            state = None
    elif state is not None and state["status"] == "INSTALLED":
        operation = state["operation_id"]
    else:
        _fail()
    directory = roots.STATE_ROOT / "install-lifecycle" / operation
    plan, digest = files._read(directory / "plan.json")
    if (set(plan) != PLAN_KEYS or plan["schema_version"] != PLAN_SCHEMA
            or plan["operation_id"] != operation or plan["install_root"] != str(roots.INSTALL_ROOT)
            or not files.ID.fullmatch(str(plan["installation_id"]))
            or not files.SHA.fullmatch(str(plan["manifest_sha256"]))
            or (state is not None and (state["plan_sha256"] != digest
                or state["installation_id"] != plan["installation_id"]))):
        _fail()
    if files._exists(lock):
        if marker["installation_id"] != plan["installation_id"] or (
                _marker(lock) != plan["fence"] or _marker(directory / "fence.json") != plan["fence"]):
            _fail()
    return directory, plan, state


def _unchanged(roots, record, plan):
    if (record["installation_id"] != plan["installation_id"]
            or roots.APP_ROOT.name != plan["release_id"]
            or files._identity(roots.INSTALL_ROOT) != plan["root_identity"]
            or files._file(roots.STATE_ROOT / "installation.json") != plan["record"]
            or files._file(roots.STATE_ROOT / "current-release.json") != plan["pointer"]
            or files._identity(roots.DATA_ROOT) != plan["data_identity"]
            or files._identity(roots.CONFIG_ROOT) != plan["config_identity"]
            or _plain_file_identity(roots.DATA_ROOT / "enterprise.db") != plan["database_identity"]
            or files._file(roots.CONFIG_ROOT / "enterprise.env") != plan["config"]
            or _database_contract(roots) != plan["database_contract"]
            or _plain_file_identity(roots.DATA_ROOT / "enterprise.db") != plan["database_identity"]):
        _fail("INSTALL_LIFECYCLE_CHANGED")


def _placement(source, retained, expected, *, directory=False):
    present = [path for path in (source, retained) if files._exists(path)]
    if len(present) != 1:
        _fail("INSTALL_LIFECYCLE_CHANGED")
    path = present[0]
    token = files._tree(path) if directory else files._file(path)
    if token != expected:
        _fail("INSTALL_LIFECYCLE_CHANGED")
    return path


def _placements(roots, directory, plan):
    program = _placement(roots.APP_ROOT, directory / "program", plan["program"], directory=True)
    entry = _placement(roots.INSTALL_ROOT / ENTRY_NAME, directory / "entry.exe", plan["entry"])
    return program, entry


@contextmanager
def _execution(roots, directory, plan):
    lock = roots.STATE_ROOT / "system-update-active.lock"
    with files._lease(directory / "runner.lock", plan["lease"]):
        if not files._exists(lock) or _marker(lock) != plan["fence"]:
            _fail()
        yield


def _public(plan, status):
    return {"installation_id": plan["installation_id"], "release_id": plan["release_id"],
            "operation_id": plan["operation_id"], "lifecycle_state": status,
            "database_changed": False, "pointer_changed": False,
            "program_recovery_copy_retained": status == "UNINSTALLED"}


def _uninstall(roots, record, directory, plan):
    _runtime_quiescent(roots)  # Recheck after publishing the common startup fence.
    _unchanged(roots, record, plan)
    program, entry = _placements(roots, directory, plan)
    _state(directory, plan, "UNINSTALLING")
    if program == roots.APP_ROOT:
        rename_owned(program, directory / "program", plan["program"]["directories"][""], directory=True)
        sync_state_root_directory(roots.RELEASE_ROOT)
        sync_state_root_directory(directory)
    _checkpoint("program_retained")
    if entry == roots.INSTALL_ROOT / ENTRY_NAME:
        rename_owned(entry, directory / "entry.exe", plan["entry"])
        sync_state_root_directory(roots.INSTALL_ROOT)
        sync_state_root_directory(directory)
    _checkpoint("entry_retained")
    _unchanged(roots, record, plan)
    program, entry = _placements(roots, directory, plan)
    if program == roots.APP_ROOT or entry == roots.INSTALL_ROOT / ENTRY_NAME:
        _fail()
    _state(directory, plan, "UNINSTALLED")
    # Keep the proven fence while uninstalled: startup/update must not assume
    # an ordinary installed state merely because the pointer remains intact.
    return _public(plan, "UNINSTALLED")


def uninstall_retaining_data(*, install_root, release_dir, local_app_data_base,
                             confirm_no_active_tasks=False, recover=False):
    if confirm_no_active_tasks is not True:
        _fail("INSTALL_LIFECYCLE_TASK_CONFIRMATION_REQUIRED")
    assets = verify_release_assets(Path(release_dir))
    roots, record = _source(Path(install_root), assets, Path(local_app_data_base))
    lock = roots.STATE_ROOT / "system-update-active.lock"
    if recover:
        directory, plan, state = _active(roots)
        if state is not None and state["status"] in {"REINSTALLING", "INSTALLED"}:
            _fail("INSTALL_LIFECYCLE_REINSTALL_RECOVERY_REQUIRED")
    else:
        if files._exists(lock):
            _fail("INSTALL_LIFECYCLE_BUSY")
        descriptor = roots.STATE_ROOT / STATE_NAME
        if files._exists(descriptor):
            _old_directory, _old_plan, state = _active(roots)
            if state["status"] != "INSTALLED":
                _fail()
        verify_materialized_release(roots.APP_ROOT, inventory_path=roots.APP_ROOT / "release-payload-inventory.json")
        entry = files._file(roots.INSTALL_ROOT / ENTRY_NAME)
        if entry["sha256"] != record["native_entry"]["sha256"]:
            _fail("INSTALL_LIFECYCLE_ENTRY_UNPROVEN")
        operation = uuid.uuid4().hex
        directory = roots.STATE_ROOT / "install-lifecycle" / operation
        files._safe(directory, missing=True)
        files._io(directory).mkdir(parents=True, exist_ok=False)
        files._new_json(directory / "fence.json", {"schema_version": FENCE_SCHEMA,
            "operation_id": operation, "installation_id": record["installation_id"]})
        with files._io(directory / "runner.lock").open("xb") as stream:
            stream.write(b"C"); stream.flush(); os.fsync(stream.fileno())
        plan = {"schema_version": PLAN_SCHEMA, "operation_id": operation,
            "installation_id": record["installation_id"], "release_id": roots.APP_ROOT.name,
            "manifest_sha256": assets.manifest.raw_sha256, "install_root": str(roots.INSTALL_ROOT),
            "root_identity": files._identity(roots.INSTALL_ROOT),
            "record": files._file(roots.STATE_ROOT / "installation.json"),
            "pointer": files._file(roots.STATE_ROOT / "current-release.json"),
            "data_identity": files._identity(roots.DATA_ROOT), "config_identity": files._identity(roots.CONFIG_ROOT),
            "database_identity": _plain_file_identity(roots.DATA_ROOT / "enterprise.db"),
            "config": files._file(roots.CONFIG_ROOT / "enterprise.env"),
            "database_contract": _database_contract(roots), "program": files._tree(roots.APP_ROOT),
            "entry": entry, "fence": _marker(directory / "fence.json"),
            "lease": files._file(directory / "runner.lock")["identity"]}
        files._new_json(directory / "plan.json", plan)
        sync_state_root_directory(directory)
        with files._lease(directory / "runner.lock", plan["lease"]):
            _unchanged(roots, record, plan)
            files._safe(lock, missing=True)
            try:
                os.link(files._io(directory / "fence.json"), files._io(lock))
            except FileExistsError as exc:
                raise LifecycleError("INSTALL_LIFECYCLE_BUSY") from exc
            sync_state_root_directory(roots.STATE_ROOT)
            _checkpoint("fence_published")
            return _uninstall(roots, record, directory, plan)
    with _execution(roots, directory, plan):
        return _uninstall(roots, record, directory, plan)


def reinstall_retained(*, install_root, release_dir, local_app_data_base, confirm_no_active_tasks=False):
    if confirm_no_active_tasks is not True:
        _fail("INSTALL_LIFECYCLE_TASK_CONFIRMATION_REQUIRED")
    assets = verify_release_assets(Path(release_dir))
    roots, record = _source(Path(install_root), assets, Path(local_app_data_base))
    return _reinstall(roots, record)


def _reinstall(roots, record, *, keep_fence=False):
    directory, plan, state = _active(roots)
    lock = roots.STATE_ROOT / "system-update-active.lock"
    if state is not None and state["status"] == "INSTALLED" and not files._exists(lock):
        _unchanged(roots, record, plan)
        _placements(roots, directory, plan)
        return _public(plan, "INSTALLED")
    with _execution(roots, directory, plan):
        _runtime_quiescent(roots)
        _unchanged(roots, record, plan)
        program, entry = _placements(roots, directory, plan)
        _state(directory, plan, "REINSTALLING")
        if program != roots.APP_ROOT:
            rename_owned(program, roots.APP_ROOT, plan["program"]["directories"][""], directory=True)
            sync_state_root_directory(roots.RELEASE_ROOT)
            sync_state_root_directory(directory)
        _checkpoint("program_reinstated")
        if entry != roots.INSTALL_ROOT / ENTRY_NAME:
            rename_owned(entry, roots.INSTALL_ROOT / ENTRY_NAME, plan["entry"])
            sync_state_root_directory(roots.INSTALL_ROOT)
            sync_state_root_directory(directory)
        _checkpoint("entry_reinstated")
        _unchanged(roots, record, plan)
        _placements(roots, directory, plan)
        verify_materialized_release(roots.APP_ROOT, inventory_path=roots.APP_ROOT / "release-payload-inventory.json")
        _state(directory, plan, "INSTALLED")
        if _marker(lock) != plan["fence"]:
            _fail()
        if not keep_fence:
            release_fence(lock, plan["fence"])
            sync_state_root_directory(roots.STATE_ROOT)
            _checkpoint("fence_released")
        return _public(plan, "INSTALLED")


def refresh_installed_proof(roots, manifest):
    """Record a new installed baseline under the offline updater's own lease.

    Called before any Runtime start. Old immutable lifecycle histories remain
    intact; the new pointer/native objects cannot reuse their old fingerprints.
    """
    _runtime_quiescent(roots)
    record = validate_installation_record(roots.INSTALL_ROOT, _snapshot(roots.STATE_ROOT / "installation.json"))
    verify_materialized_release(roots.APP_ROOT, inventory_path=roots.APP_ROOT / "release-payload-inventory.json")
    operation = uuid.uuid4().hex
    directory = roots.STATE_ROOT / "install-lifecycle" / operation
    files._safe(directory, missing=True)
    files._io(directory).mkdir(parents=True, exist_ok=False)
    files._new_json(directory / "fence.json", {"schema_version": FENCE_SCHEMA,
        "operation_id": operation, "installation_id": record["installation_id"]})
    with files._io(directory / "runner.lock").open("xb") as stream:
        stream.write(b"C"); stream.flush(); os.fsync(stream.fileno())
    plan = {"schema_version": PLAN_SCHEMA, "operation_id": operation,
        "installation_id": record["installation_id"], "release_id": roots.APP_ROOT.name,
        "manifest_sha256": manifest.raw_sha256, "install_root": str(roots.INSTALL_ROOT),
        "root_identity": files._identity(roots.INSTALL_ROOT),
        "record": files._file(roots.STATE_ROOT / "installation.json"),
        "pointer": files._file(roots.STATE_ROOT / "current-release.json"),
        "data_identity": files._identity(roots.DATA_ROOT), "config_identity": files._identity(roots.CONFIG_ROOT),
        "database_identity": _plain_file_identity(roots.DATA_ROOT / "enterprise.db"),
        "config": files._file(roots.CONFIG_ROOT / "enterprise.env"),
        "database_contract": _database_contract(roots), "program": files._tree(roots.APP_ROOT),
        "entry": files._file(roots.INSTALL_ROOT / ENTRY_NAME), "fence": _marker(directory / "fence.json"),
        "lease": files._file(directory / "runner.lock")["identity"]}
    if plan["entry"]["sha256"] != record["native_entry"]["sha256"]:
        _fail("INSTALL_LIFECYCLE_ENTRY_UNPROVEN")
    files._new_json(directory / "plan.json", plan)
    sync_state_root_directory(directory)
    _state(directory, plan, "INSTALLED")


def inspect_lifecycle(*, install_root, release_dir, local_app_data_base):
    assets = verify_release_assets(Path(release_dir))
    roots, record = _source(Path(install_root), assets, Path(local_app_data_base))
    if not files._exists(roots.STATE_ROOT / STATE_NAME) and not files._exists(roots.STATE_ROOT / "system-update-active.lock"):
        return {"installation_id": record["installation_id"], "lifecycle_state": "NONE"}
    directory, plan, state = _active(roots)
    with files._lease(directory / "runner.lock", plan["lease"]):
        _unchanged(roots, record, plan)
        _placements(roots, directory, plan)
    return _public(plan, state["status"] if state is not None else "UNINSTALLING")
