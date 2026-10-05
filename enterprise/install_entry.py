"""Shared fixed-entry publication, not a second update or database engine.

The Setup supplies an independently verified native build. First install uses
this before its final pointer publication; entry-only repair verifies the whole
current Release but never opens a database or changes the Release pointer.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from enterprise.path_safety import assert_no_reparse_ancestors
from enterprise.paths import PathRoots, PortableRootInputs, validate_path_roots_for_use
from enterprise.release.current_release import (
    read_current_release_result_from_state_root, resolve_portable_path_roots,
)
from enterprise.release.release_manifest_v2 import (
    INVENTORY_MAX_BYTES, canonical_json, enforce_portable_contract_compatibility,
    parse_inventory_bytes, read_release_manifest_v2, verify_materialized_release,
)

PRODUCT = "MEIS-DaCaiTou/Infinite-Canvas-Enterprise"
RECORD_SCHEMA = "enterprise-installation-v1"
RECORD_NAME = "installation.json"
ENTRY_NAME = "InfiniteCanvas.exe"
COMPILER_PACKAGE_SHA = "fe24ef31a6ffcb7c49383d2fd362763dee291ad9b9d98cc0c19ef80203b99ebc"
SHA = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
INSTANCE = re.compile(r"[0-9a-f]{32}\Z")


class InstallEntryError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe(path: Path, *, missing: bool = False) -> Path:
    path = Path(os.path.abspath(path))
    try:
        assert_no_reparse_ancestors(path, allow_missing=missing)
    except Exception as exc:
        raise InstallEntryError("INSTALL_ENTRY_PATH_UNSAFE") from exc
    return path


@dataclass(frozen=True)
class Snapshot:
    data: bytes
    identity: tuple[int, int]


def _snapshot(path: Path, *, maximum: int = 4 * 1024 * 1024) -> Snapshot | None:
    _safe(path, missing=True)
    try:
        with path.open("rb") as handle:
            info = os.fstat(handle.fileno())
            if not 0 < info.st_size <= maximum:
                raise InstallEntryError("INSTALL_ENTRY_FILE_INVALID")
            data = handle.read(maximum + 1)
            if len(data) != info.st_size:
                raise InstallEntryError("INSTALL_ENTRY_FILE_CHANGED")
            return Snapshot(data, (info.st_dev, info.st_ino))
    except FileNotFoundError:
        return None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InstallEntryError("INSTALL_ENTRY_RECORD_INVALID")
        result[key] = value
    return result


def _document(data: bytes) -> dict:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError) as exc:
        raise InstallEntryError("INSTALL_ENTRY_RECORD_INVALID") from exc


@dataclass(frozen=True)
class NativeEntry:
    data: bytes
    sha256: str
    source_commit: str
    source_tree: str
    record_sha256: str


def verify_entry_bundle(directory: Path, *, commit: str | None = None, tree: str | None = None) -> NativeEntry:
    executable = _snapshot(directory / ENTRY_NAME)
    record_file = _snapshot(directory / "native-entry-build-record.json", maximum=16384)
    if executable is None or record_file is None:
        raise InstallEntryError("INSTALL_ENTRY_BUNDLE_MISSING")
    record = _document(record_file.data)
    expected_fields = {
        "schema_version", "source_commit", "source_tree", "dirty_experimental_build",
        "policy_sha256", "source_files_sha256", "compiler_package_sha256",
        "compiler_sha256", "deterministic_double_build", "signed", "executable",
    }
    exe = record.get("executable")
    sources = record.get("source_files_sha256")
    if (set(record) != expected_fields or record.get("schema_version") != "enterprise-native-entry-build-record-v1"
            or record.get("dirty_experimental_build") is not False
            or record.get("deterministic_double_build") is not True or record.get("signed") is not False
            or record.get("compiler_package_sha256") != COMPILER_PACKAGE_SHA
            or not isinstance(sources, dict) or set(sources) != {"NativeCore.cs", "LauncherProgram.cs", "app.manifest"}
            or not all(isinstance(value, str) and SHA.fullmatch(value) for value in sources.values())
            or not all(isinstance(record.get(key), str) and SHA.fullmatch(record[key])
                       for key in ("policy_sha256", "compiler_sha256"))
            or not all(isinstance(record.get(key), str) and COMMIT.fullmatch(record[key])
                       for key in ("source_commit", "source_tree"))
            or not isinstance(exe, dict) or set(exe) != {"filename", "sha256", "size_bytes"}
            or exe.get("filename") != ENTRY_NAME or type(exe.get("size_bytes")) is not int
            or exe.get("size_bytes") != len(executable.data) or exe.get("sha256") != _sha(executable.data)
            or not executable.data.startswith(b"MZ")):
        raise InstallEntryError("INSTALL_ENTRY_BUNDLE_INVALID")
    if ((commit is not None and record["source_commit"] != commit)
            or (tree is not None and record["source_tree"] != tree)):
        raise InstallEntryError("INSTALL_ENTRY_SOURCE_MISMATCH")
    return NativeEntry(executable.data, exe["sha256"], record["source_commit"],
                       record["source_tree"], _sha(record_file.data))


def validate_entry_target_paths(root: Path, release_id: str, inventory_path: Path) -> None:
    """Reject unsupported deep destinations before any installation writes.

    The fixed .NET entry/current bundled materializer do not yet promise long
    paths on machines without the Windows long-path policy. Do not change that
    system policy or discover this limit halfway through a new installation.
    """
    snapshot = _snapshot(inventory_path, maximum=INVENTORY_MAX_BYTES)
    if snapshot is None:
        raise InstallEntryError("INSTALL_ENTRY_SOURCE_INVALID")
    inventory = parse_inventory_bytes(snapshot.data)
    root = Path(os.path.abspath(root))
    paths = [root / "releases" / release_id / item.path for item in inventory.entries]
    paths += [root / (ENTRY_NAME + "." + "a" * 32 + ".new"),
              root / "state" / (RECORD_NAME + "." + "a" * 32 + ".new"),
              root / "state/native-entry-backups" / ("a" * 32 + ".json")]
    if any(len(str(path).encode("utf-16-le")) // 2 >= 260 for path in paths):
        raise InstallEntryError("INSTALL_ENTRY_TARGET_PATH_TOO_LONG")


def _record(root: Path, entry: NativeEntry, before: Snapshot | None) -> dict:
    identity = uuid.uuid4().hex
    if before is not None:
        old = _document(before.data)
        if (set(old) != {"schema_version", "product", "installation_id", "install_root",
                         "deployment_role", "scope", "data_relative", "config_relative",
                         "release_pointer_relative", "update_protocol", "channel", "native_entry"}
                or old.get("schema_version") != RECORD_SCHEMA or old.get("product") != PRODUCT
                or not isinstance(old.get("installation_id"), str) or not INSTANCE.fullmatch(old["installation_id"])
                or os.path.normcase(str(old.get("install_root"))) != os.path.normcase(str(root))
                or old.get("deployment_role") != "single-host" or old.get("scope") != "current-user"
                or old.get("data_relative") != "data" or old.get("config_relative") != "config"
                or old.get("release_pointer_relative") != "state/current-release.json"
                or type(old.get("update_protocol")) is not int or old["update_protocol"] != 1
                or old.get("channel") not in {"stable", "development"}
                or not isinstance(old.get("native_entry"), dict)
                or set(old["native_entry"]) != {"filename", "sha256", "source_commit", "source_tree", "build_record_sha256"}
                or old["native_entry"].get("filename") != ENTRY_NAME
                or not all(isinstance(old["native_entry"].get(key), str) and SHA.fullmatch(old["native_entry"][key])
                           for key in ("sha256", "build_record_sha256"))
                or not all(isinstance(old["native_entry"].get(key), str) and COMMIT.fullmatch(old["native_entry"][key])
                           for key in ("source_commit", "source_tree"))):
            raise InstallEntryError("INSTALL_IDENTITY_INVALID")
        identity = old["installation_id"]
    return {
        "schema_version": RECORD_SCHEMA, "product": PRODUCT, "installation_id": identity,
        "install_root": str(root), "deployment_role": "single-host", "scope": "current-user",
        "data_relative": "data", "config_relative": "config",
        "release_pointer_relative": "state/current-release.json", "update_protocol": 1,
        "channel": _document(before.data)["channel"] if before else "stable",
        "native_entry": {"filename": ENTRY_NAME, "sha256": entry.sha256,
                         "source_commit": entry.source_commit, "source_tree": entry.source_tree,
                         "build_record_sha256": entry.record_sha256},
    }


def _write_new(path: Path, data: bytes) -> Snapshot:
    _safe(path, missing=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    result = _snapshot(path)
    assert result is not None
    return result


def _atomic_publish(path: Path, data: bytes, expected: Snapshot | None) -> Snapshot:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".new")
    owned = _write_new(temporary, data)
    try:
        if _snapshot(path) != expected:
            raise InstallEntryError("INSTALL_ENTRY_FILE_CHANGED")
        if expected is None:
            # A new destination is create-only, never a replace of a raced file.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        # link/replace retains the fsynced temporary's identity. Do not perform
        # fallible post-commit I/O before the caller receives its rollback token.
        return Snapshot(data, owned.identity)
    finally:
        try:
            if _snapshot(temporary) == owned:
                temporary.unlink()
        except (OSError, InstallEntryError):
            pass  # Preserve unverifiable residue; never guess cleanup ownership.


def _restore(path: Path, previous: Snapshot | None, published: Snapshot | None):
    if published is None:
        return
    if _snapshot(path) != published:
        raise InstallEntryError("INSTALL_ENTRY_RECOVERY_REQUIRED")
    if previous is None:
        path.unlink()
    else:
        _atomic_publish(path, previous.data, published)


@dataclass
class EntryPublication:
    entry_path: Path
    record_path: Path
    lock_path: Path
    previous_entry: Snapshot | None
    previous_record: Snapshot | None
    published_entry: Snapshot | None
    published_record: Snapshot | None
    lock: Snapshot
    installation_id: str

    def complete(self):
        if _snapshot(self.lock_path, maximum=16384) != self.lock:
            raise InstallEntryError("INSTALL_ENTRY_RECOVERY_REQUIRED")
        self.lock_path.unlink()

    def rollback(self):
        # Only the two entry files written by this exact operation are restored.
        _restore(self.record_path, self.previous_record, self.published_record)
        _restore(self.entry_path, self.previous_entry, self.published_entry)
        self.complete()


def publish_fixed_entry(roots: PathRoots, entry: NativeEntry) -> EntryPublication:
    if (not isinstance(entry, NativeEntry) or not isinstance(entry.data, bytes)
            or not entry.data.startswith(b"MZ") or _sha(entry.data) != entry.sha256):
        raise InstallEntryError("INSTALL_ENTRY_BUNDLE_INVALID")
    validate_path_roots_for_use(roots)
    root = _safe(roots.INSTALL_ROOT)
    _safe(roots.STATE_ROOT)
    target, record_path = root / ENTRY_NAME, roots.STATE_ROOT / RECORD_NAME
    previous_entry = _snapshot(target)
    previous_record = _snapshot(record_path, maximum=16384)
    record = _record(root, entry, previous_record)
    if previous_entry is not None and _sha(previous_entry.data) != entry.sha256:
        owner = _document(previous_record.data)["native_entry"]["sha256"] if previous_record else None
        legacy = _snapshot(roots.STATE_ROOT / "native-entry.json", maximum=16384)
        if owner is None and legacy is not None:
            old = _document(legacy.data)
            if set(old) == {"schema_version", "launcher_sha256"} and old.get("schema_version") == "enterprise-native-entry-v1":
                owner = old.get("launcher_sha256")
        if owner != _sha(previous_entry.data):
            raise InstallEntryError("INSTALL_ENTRY_UNOWNED_FILE")
    lock_path = roots.STATE_ROOT / "system-update-active.lock"
    operation = uuid.uuid4().hex
    # The common update lock also prevents an online update from racing Setup.
    # Existing/abandoned locks are never deleted or adopted by entry repair.
    try:
        lock = _write_new(lock_path, canonical_json({
            "schema_version": "enterprise-entry-maintenance-lock-v1", "operation_id": operation,
            "installation_id": record["installation_id"], "target_entry_sha256": entry.sha256,
            "previous_entry_sha256": _sha(previous_entry.data) if previous_entry else None,
            "previous_record_sha256": _sha(previous_record.data) if previous_record else None,
        }))
    except FileExistsError as exc:
        raise InstallEntryError("INSTALL_ENTRY_MAINTENANCE_BUSY") from exc
    publication = EntryPublication(target, record_path, lock_path, previous_entry,
                                   previous_record, None, None, lock, record["installation_id"])
    try:
        # Preserve owned prior bytes as recovery evidence before replacing them.
        changed = (previous_entry is None or previous_entry.data != entry.data
                   or previous_record is None or previous_record.data != canonical_json(record))
        if changed and (previous_entry is not None or previous_record is not None):
            backup = _safe(roots.STATE_ROOT / "native-entry-backups", missing=True)
            backup.mkdir(exist_ok=True)
            _safe(backup)
            if previous_entry:
                _write_new(backup / (operation + ".exe"), previous_entry.data)
            if previous_record:
                _write_new(backup / (operation + ".json"), previous_record.data)
        if previous_entry is None or previous_entry.data != entry.data:
            publication.published_entry = _atomic_publish(target, entry.data, previous_entry)
        if previous_record is None or previous_record.data != canonical_json(record):
            publication.published_record = _atomic_publish(record_path, canonical_json(record), previous_record)
        return publication
    except Exception as exc:
        try:
            publication.rollback()
        except Exception as rollback_error:
            raise InstallEntryError("INSTALL_ENTRY_RECOVERY_REQUIRED") from rollback_error
        if isinstance(exc, InstallEntryError):
            raise
        raise InstallEntryError("INSTALL_ENTRY_PUBLISH_FAILED") from exc


def repair_fixed_entry(*, install_root: Path, entry: NativeEntry, local_app_data_base: Path) -> dict:
    try:
        inputs = PortableRootInputs(install_root, local_app_data_base)
        roots = resolve_portable_path_roots(inputs)
        pointer = read_current_release_result_from_state_root(roots.STATE_ROOT)
        manifest = read_release_manifest_v2(roots.APP_ROOT / "release-manifest.json")
        if manifest.raw_sha256 != pointer.release.manifest_sha256 or manifest.release_id != pointer.release.release_id:
            raise InstallEntryError("INSTALL_ENTRY_SOURCE_INVALID")
        enforce_portable_contract_compatibility(manifest)
        validate_entry_target_paths(roots.INSTALL_ROOT, manifest.release_id, roots.APP_ROOT / "release-payload-inventory.json")
        verify_materialized_release(roots.APP_ROOT, inventory_path=roots.APP_ROOT / "release-payload-inventory.json")
        from enterprise.ops.update.mvp import UpdateJobStore
        store = UpdateJobStore(roots)
        if store.pending_recovery_jobs(initialize=False):
            raise InstallEntryError("INSTALL_ENTRY_RECOVERY_REQUIRED")
        publication = publish_fixed_entry(roots, entry)
        try:
            # An update may have completed with unresolved recovery between
            # the initial inspection and our lock acquisition. Recheck while
            # holding that same lock before accepting the entry publication.
            if store.pending_recovery_jobs(initialize=False):
                raise InstallEntryError("INSTALL_ENTRY_RECOVERY_REQUIRED")
            if read_current_release_result_from_state_root(roots.STATE_ROOT) != pointer:
                raise InstallEntryError("INSTALL_ENTRY_SOURCE_CHANGED")
            publication.complete()
        except Exception:
            publication.rollback()
            raise
        return {"installation_id": publication.installation_id, "release_id": pointer.release.release_id,
                "launcher_installed": True, "database_changed": False, "pointer_changed": False}
    except InstallEntryError:
        raise
    except Exception as exc:
        raise InstallEntryError("INSTALL_ENTRY_SOURCE_INVALID") from exc
