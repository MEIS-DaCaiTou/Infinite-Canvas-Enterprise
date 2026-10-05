"""Same-Release program repair; no database, entry, config or pointer writes.

Run from a verified external maintenance payload, never from damaged installed
Python. A prepared complete directory replaces the stopped program by rename.
Immutable plans, kernel leases and retained directories support process-death
recovery. Unknown locks, files or identities are never adopted or deleted.
"""
from __future__ import annotations

import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

from enterprise.fresh_install import verify_release_assets
from enterprise.install_entry import (
    Snapshot, _document, _safe, _sha, _snapshot, _write_new,
    validate_entry_target_paths, validate_installation_record,
)
from enterprise.ops.update.mvp import UpdateJobStore
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, validate_path_roots_for_use
from enterprise.release.current_release import read_current_release_result_from_state_root, sync_state_root_directory
from enterprise.release.release_manifest_v2 import build_inventory, canonical_json, materialize_release_fixture, verify_materialized_release
from enterprise.runtime.control import inspect_runtime
from enterprise.runtime.state import RuntimeStateStore
from enterprise.runtime.supervisor import SupervisorConfig

LOCK_SCHEMA = "enterprise-program-repair-lock-v1"
PLAN_SCHEMA = "enterprise-program-repair-plan-v1"
RESULT_SCHEMA = "enterprise-program-repair-result-v1"
OPERATION = re.compile(r"[0-9a-f]{32}\Z")


class ProgramRepairError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code="INSTALL_PROGRAM_RECOVERY_REQUIRED"):
    raise ProgramRepairError(code)


def _checkpoint(name: str):
    """No production injection switches; tests can terminate their own runner."""


def _file_token(value: Snapshot) -> dict:
    return {"sha256": _sha(value.data), "identity": list(value.identity)}


def _tree_token(path: Path) -> dict | None:
    _safe(path, missing=True)
    if not path.exists():
        return None
    info = path.stat()
    if not path.is_dir():
        _fail("INSTALL_PROGRAM_PATH_UNSAFE")
    inventory = build_inventory(path)
    # Include directories, too: recovery must not move newly added empty ones.
    directories = sorted(str(p.relative_to(path)).replace("\\", "/") for p in path.rglob("*") if p.is_dir())
    return {"identity": [info.st_dev, info.st_ino], "tree_sha256": inventory.tree_sha256,
            "directories_sha256": _sha(canonical_json(directories))}


def _identity_gate(root: Path, assets, local: Path):
    _safe(root)
    pointer = read_current_release_result_from_state_root(root / "state")
    if (pointer.release.release_id != assets.manifest.release_id
            or pointer.release.manifest_sha256 != assets.manifest.raw_sha256):
        _fail("INSTALL_PROGRAM_SAME_RELEASE_REQUIRED")
    roots = derive_portable_path_roots(PortableRootInputs(root, local), pointer.release.release_id)
    validate_path_roots_for_use(roots)
    record = _snapshot(roots.STATE_ROOT / "installation.json", maximum=16384)
    if record is None:
        _fail("INSTALL_PROGRAM_IDENTITY_REQUIRED")
    identity = validate_installation_record(root, record)
    source_pointer = _snapshot(roots.STATE_ROOT / "current-release.json", maximum=16384)
    if source_pointer is None or _sha(source_pointer.data) != pointer.raw_sha256:
        _fail()
    if UpdateJobStore(roots).pending_recovery_jobs(initialize=False):
        _fail("INSTALL_PROGRAM_UPDATE_RECOVERY_REQUIRED")
    return roots, identity["installation_id"], _file_token(record), _file_token(source_pointer)


def _assert_plan_source(plan, roots, installation_id, record, pointer):
    if (plan["root_identity"] != roots.root_identity or plan["installation_id"] != installation_id
            or plan["release_id"] != roots.APP_ROOT.name
            or plan["installation_record"] != record or plan["pointer"] != pointer):
        _fail()


@contextmanager
def _runner_lease(path: Path, expected: Snapshot):
    """OS-released on process death; a live runner cannot be guessed stale."""
    _safe(path)
    handle = path.open("r+b")
    locked = False
    try:
        if (os.fstat(handle.fileno()).st_dev, os.fstat(handle.fileno()).st_ino) != expected.identity:
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
            raise ProgramRepairError("INSTALL_PROGRAM_RUNNER_BUSY") from exc
        if os.fstat(handle.fileno()).st_size != 1 or handle.read(1) != b"R":
            _fail()
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def _ports(roots) -> dict:
    # Read only the two port settings; never import deployment configuration or
    # load credentials into environment/logs. Ambiguous syntax fails closed.
    config = _snapshot(roots.CONFIG_ROOT / "enterprise.env", maximum=65536)
    ports = {"GATEWAY_PORT": 8000, "UPSTREAM_PORT": 3001}
    seen = set()
    if config:
        for line in config.data.decode("utf-8-sig").splitlines():
            name = line.split("=", 1)[0].strip().removeprefix("export ")
            if name not in ports:
                continue
            match = re.fullmatch(r"\s*(?:export\s+)?(?:GATEWAY_PORT|UPSTREAM_PORT)\s*=\s*"
                                 r"(?:([0-9]+)|\"([0-9]+)\"|'([0-9]+)')\s*(?:#.*)?", line)
            if match is None or name in seen:
                _fail("INSTALL_PROGRAM_RUNTIME_UNCERTAIN")
            value = next(item for item in match.groups() if item is not None)
            if not 1 <= int(value) <= 65535:
                _fail("INSTALL_PROGRAM_RUNTIME_UNCERTAIN")
            seen.add(name)
            ports[name] = int(value)
    if ports["GATEWAY_PORT"] == ports["UPSTREAM_PORT"]:
        _fail("INSTALL_PROGRAM_RUNTIME_UNCERTAIN")
    return ports


def _runtime_quiescent(roots):
    store = RuntimeStateStore(roots.RUNTIME_ROOT)
    for name in (store.state_path, store.lock_path):
        _safe(name, missing=True)
    if store.lock_path.exists() or (store.state_path.exists() and store.read_state() is None):
        _fail("INSTALL_PROGRAM_RUNTIME_BUSY")
    ports = _ports(roots)
    config = SupervisorConfig(app_root=roots.APP_ROOT, runtime_root=roots.RUNTIME_ROOT,
                              mode="service-host",
                              upstream_port=ports["UPSTREAM_PORT"], gateway_port=ports["GATEWAY_PORT"])
    status = inspect_runtime(config)
    if (status.get("supervisor_identity_current") or status.get("owned_child_current")
            or status.get("start_disposition") not in {"stopped", "stale_runtime_state"}):
        _fail("INSTALL_PROGRAM_RUNTIME_BUSY")


def _release_marker(path: Path, expected: Snapshot):
    if _snapshot(path, maximum=16384) != expected:
        _fail()
    path.unlink()


def _unchanged_source(plan, roots):
    for name, expected in (("installation.json", plan["installation_record"]),
                           ("current-release.json", plan["pointer"])):
        observed = _snapshot(roots.STATE_ROOT / name, maximum=16384)
        if observed is None or _file_token(observed) != expected:
            _fail()


def _result(directory: Path, plan: dict, status: str):
    value = {"schema_version": RESULT_SCHEMA, "operation_id": plan["operation_id"],
             "plan_sha256": _sha(canonical_json(plan)), "status": status}
    path = directory / "result.json"
    existing = _snapshot(path, maximum=16384)
    if existing is not None and existing.data != canonical_json(value):
        _fail()
    if existing is None:
        _write_new(path, canonical_json(value))
    sync_state_root_directory(directory)


def _rollback(directory, plan, roots):
    _unchanged_source(plan, roots)
    source = roots.APP_ROOT
    candidate, backup, rejected = (directory / name for name in ("candidate", "original", "rejected"))
    source_token, backup_token = _tree_token(source), _tree_token(backup)
    if source_token == plan["candidate"]:
        if (backup_token != plan["original"] or _tree_token(rejected) is not None
                or _tree_token(candidate) is not None):
            _fail()
        source.rename(rejected)
        source_token = None
    if plan["original"] is None:
        if source_token is not None or backup_token is not None:
            _fail()
    elif source_token is None and backup_token == plan["original"]:
        backup.rename(source)
    elif source_token != plan["original"] or backup_token is not None:
        _fail()
    if _tree_token(source) != plan["original"]:
        _fail()
    sync_state_root_directory(roots.RELEASE_ROOT)
    _result(directory, plan, "ROLLED_BACK")


def _public(plan, status):
    return {"operation_id": plan["operation_id"], "installation_id": plan["installation_id"],
            "release_id": plan["release_id"], "repair_state": status,
            "database_changed": False, "pointer_changed": False, "entry_changed": False}


def repair_program(*, install_root: Path, release_dir: Path, local_app_data_base: Path,
                   confirm_no_active_tasks: bool = False) -> dict:
    if confirm_no_active_tasks is not True:
        _fail("INSTALL_PROGRAM_TASK_CONFIRMATION_REQUIRED")
    assets = verify_release_assets(release_dir)
    root = Path(os.path.abspath(install_root))
    roots, installation_id, record, pointer = _identity_gate(root, assets, local_app_data_base)
    lock_path = roots.STATE_ROOT / "system-update-active.lock"
    if _snapshot(lock_path, maximum=16384) is not None:
        _fail("INSTALL_PROGRAM_MAINTENANCE_BUSY")
    validate_entry_target_paths(root, assets.manifest.release_id, assets.inventory_path)
    original = _tree_token(roots.APP_ROOT)
    # An unrelated file in the program directory is not silently quarantined.
    if original is not None:
        from enterprise.release.release_manifest_v2 import parse_inventory_bytes
        allowed = {item.path for item in parse_inventory_bytes(assets.inventory_path.read_bytes()).entries}
        allowed.update(str(assets.manifest.section("release_payload")[name])
                       for name in ("embedded_manifest_path", "inventory_path"))
        if not {item.path for item in build_inventory(roots.APP_ROOT).entries} <= allowed:
            _fail("INSTALL_PROGRAM_UNOWNED_FILE")
        allowed_dirs = {str(Path(name).parent).replace("\\", "/") for name in allowed}
        allowed_dirs |= {str(p).replace("\\", "/") for name in allowed for p in Path(name).parents if str(p) != "."}
        if any(str(p.relative_to(roots.APP_ROOT)).replace("\\", "/") not in allowed_dirs
               for p in roots.APP_ROOT.rglob("*") if p.is_dir()):
            _fail("INSTALL_PROGRAM_UNOWNED_FILE")
    _runtime_quiescent(roots)
    operation = uuid.uuid4().hex
    area = _safe(roots.STAGING_ROOT / "program-repairs", missing=True)
    directory = area / operation[:12]
    from enterprise.release.release_manifest_v2 import parse_inventory_bytes
    if any(len(str(directory / "candidate" / item.path).encode("utf-16-le")) // 2 >= 260
           for item in parse_inventory_bytes(assets.inventory_path.read_bytes()).entries):
        _fail("INSTALL_PROGRAM_TARGET_PATH_TOO_LONG")
    area.mkdir(parents=True, exist_ok=True)
    directory.mkdir()
    candidate = directory / "candidate"
    materialize_release_fixture(assets.manifest_path, assets.archive_path, assets.inventory_path, candidate)
    runner = _write_new(directory / "runner.lock", b"R")
    plan = {"schema_version": PLAN_SCHEMA, "operation_id": operation,
            "root_identity": roots.root_identity, "installation_id": installation_id,
            "release_id": roots.APP_ROOT.name, "manifest_sha256": assets.manifest.raw_sha256,
            "installation_record": record, "pointer": pointer, "original": original,
            "candidate": _tree_token(candidate), "runner": _file_token(runner)}
    _write_new(directory / "plan.json", canonical_json(plan))
    sync_state_root_directory(directory)
    marker = canonical_json({"schema_version": LOCK_SCHEMA, "operation_id": operation,
                             "plan_sha256": _sha(canonical_json(plan)), "root_identity": roots.root_identity})
    with _runner_lease(directory / "runner.lock", runner):
        try:
            lock = _write_new(lock_path, marker)
        except FileExistsError as exc:
            raise ProgramRepairError("INSTALL_PROGRAM_MAINTENANCE_BUSY") from exc
        fence_path = roots.RUNTIME_ROOT / "runtime-reconcile.lock"
        fence = None
        terminal = False
        committed = False
        try:
            _checkpoint("locked")
            _safe(roots.RUNTIME_ROOT, missing=True).mkdir(parents=True, exist_ok=True)
            fence = _write_new(fence_path, marker)
            _runtime_quiescent(roots)
            now = _identity_gate(root, assets, local_app_data_base)
            _assert_plan_source(plan, now[0], *now[1:])
            if _tree_token(roots.APP_ROOT) != original or _tree_token(candidate) != plan["candidate"]:
                _fail()
            _checkpoint("prepared")
            if original is not None:
                roots.APP_ROOT.rename(directory / "original")
            _checkpoint("original_moved")
            candidate.rename(roots.APP_ROOT)
            _checkpoint("candidate_published")
            verify_materialized_release(roots.APP_ROOT, inventory_path=roots.APP_ROOT / "release-payload-inventory.json")
            _assert_plan_source(plan, *_identity_gate(root, assets, local_app_data_base))
            sync_state_root_directory(roots.RELEASE_ROOT)
            _result(directory, plan, "SUCCEEDED")
            committed = True
            _checkpoint("committed")
            terminal = True
        except Exception as exc:
            try:
                # A committed outcome must never be converted to a rollback.
                if not committed:
                    _rollback(directory, plan, roots)
                terminal = True
            except Exception as recovery_error:
                raise ProgramRepairError("INSTALL_PROGRAM_RECOVERY_REQUIRED") from recovery_error
            if isinstance(exc, ProgramRepairError):
                raise
            raise ProgramRepairError("INSTALL_PROGRAM_REPAIR_FAILED") from exc
        finally:
            if terminal:
                if fence is not None:
                    _release_marker(fence_path, fence)
                _release_marker(lock_path, lock)
    return _public(plan, "SUCCEEDED")


def recover_program(*, install_root: Path, release_dir: Path, local_app_data_base: Path,
                    confirm_no_active_tasks: bool = False) -> dict:
    if confirm_no_active_tasks is not True:
        _fail("INSTALL_PROGRAM_TASK_CONFIRMATION_REQUIRED")
    assets = verify_release_assets(release_dir)
    root = Path(os.path.abspath(install_root))
    roots, installation_id, record, pointer = _identity_gate(root, assets, local_app_data_base)
    lock_path = roots.STATE_ROOT / "system-update-active.lock"
    lock = _snapshot(lock_path, maximum=16384)
    if lock is None:
        _fail("INSTALL_PROGRAM_NO_RECOVERY")
    marker = _document(lock.data)
    if (set(marker) != {"schema_version", "operation_id", "plan_sha256", "root_identity"}
            or marker["schema_version"] != LOCK_SCHEMA or not isinstance(marker["operation_id"], str)
            or not OPERATION.fullmatch(marker["operation_id"]) or marker["root_identity"] != roots.root_identity):
        _fail("INSTALL_PROGRAM_FOREIGN_LOCK")
    directory = _safe(roots.STAGING_ROOT / "program-repairs" / marker["operation_id"][:12])
    saved = _snapshot(directory / "plan.json", maximum=16384)
    if saved is None or _sha(saved.data) != marker["plan_sha256"]:
        _fail()
    plan = _document(saved.data)
    if (set(plan) != {"schema_version", "operation_id", "root_identity", "installation_id", "release_id",
                     "manifest_sha256", "installation_record", "pointer", "original", "candidate", "runner"}
            or plan["schema_version"] != PLAN_SCHEMA or plan["operation_id"] != marker["operation_id"]
            or plan["manifest_sha256"] != assets.manifest.raw_sha256):
        _fail()
    _assert_plan_source(plan, roots, installation_id, record, pointer)
    token = plan["runner"]
    if (not isinstance(token, dict) or set(token) != {"sha256", "identity"}
            or token["sha256"] != _sha(b"R") or not isinstance(token["identity"], list)
            or len(token["identity"]) != 2 or any(type(value) is not int for value in token["identity"])):
        _fail()
    runner = Snapshot(b"R", tuple(token["identity"]))
    with _runner_lease(directory / "runner.lock", runner):
        if _snapshot(lock_path, maximum=16384) != lock:
            _fail()
        fence_path = roots.RUNTIME_ROOT / "runtime-reconcile.lock"
        fence = _snapshot(fence_path, maximum=16384)
        if fence is not None and fence.data != lock.data:
            _fail("INSTALL_PROGRAM_FOREIGN_FENCE")
        if fence is None:
            _safe(roots.RUNTIME_ROOT, missing=True).mkdir(parents=True, exist_ok=True)
            fence = _write_new(fence_path, lock.data)
        _runtime_quiescent(roots)
        _assert_plan_source(plan, *_identity_gate(root, assets, local_app_data_base))
        result = _snapshot(directory / "result.json", maximum=16384)
        status = _document(result.data).get("status") if result else None
        if result and result.data != canonical_json({"schema_version": RESULT_SCHEMA,
                "operation_id": plan["operation_id"], "plan_sha256": _sha(saved.data), "status": status}):
            _fail()
        if status == "SUCCEEDED":
            if _tree_token(roots.APP_ROOT) != plan["candidate"]:
                _fail()
            verify_materialized_release(roots.APP_ROOT, inventory_path=roots.APP_ROOT / "release-payload-inventory.json")
        elif status in {None, "ROLLED_BACK"}:
            _rollback(directory, plan, roots)
            status = "ROLLED_BACK"
        else:
            _fail()
        _release_marker(fence_path, fence)
        _release_marker(lock_path, lock)
    return _public(plan, status)
