"""Explicit cleanup of closed, owned Setup preparation bundles, not business data.

No age, capacity or retention policy. Legacy/unregistered bundles are retained.
The ledger is outside the deletable tree. A terminal operation, exited authenticated
Setup/worker identities, an OS lease and a fresh byte/identity inventory authorize
one selected deletion. Interrupted deletion remains quarantined and needs another
explicit preview/confirmation; no automatic retry or recursive broad deletion.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from enterprise.release.release_manifest_v2 import canonical_json
from enterprise.runtime.ownership import ProcessIdentity, process_identity, same_process

RECEIPT_SCHEMA = "enterprise-setup-cache-receipt-v1"
STATE_SCHEMA = "enterprise-setup-cache-state-v1"
ID = re.compile(r"^[0-9a-f]{32}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_CONTAINERS = 64
MAX_ENTRIES = 24000  # Parser/work bounds, not a customer retention policy.
MAX_LEDGER_BYTES = 12 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_TREE_BYTES = 4 * 1024 * 1024 * 1024
RECEIPT_KEYS = {"schema_version", "cache_id", "container_identity", "lease_identity",
                "release_id", "manifest_sha256", "files", "directories"}
STATE_KEYS = {"schema_version", "cache_id", "status", "client", "worker", "install_root",
              "install_identity", "receipt_sha256"}

if os.name == "nt":
    from ctypes import wintypes

    class FileInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                    ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD), ("size_low", wintypes.DWORD),
                    ("links", wintypes.DWORD), ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]

    class FileIdInfo(ctypes.Structure):
        _fields_ = [("volume", ctypes.c_uint64), ("file_id", ctypes.c_ubyte * 16)]

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
    _kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    _kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _kernel.SetFileInformationByHandle.restype = wintypes.BOOL


class CacheError(RuntimeError):
    def __init__(self, code="INSTALL_CACHE_UNPROVEN"):
        self.code = code
        super().__init__(code)


def _fail(code="INSTALL_CACHE_UNPROVEN"):
    raise CacheError(code)


def _checkpoint(stage):
    """Literal fault checkpoints for owned-copy drills; no production env switch."""


def cache_root(local_app_data_base):
    return _logical(local_app_data_base) / "Infinite-Canvas-Enterprise" / "maintenance-payloads"


def _logical(path):
    from enterprise.release.release_manifest_v2 import _strip_windows_namespace
    return Path(os.path.abspath(_strip_windows_namespace(str(path))))


def _io(path):
    # Logical paths remain ordinary absolute paths for identity/comparison.
    # Only validated filesystem I/O uses the Windows extended-path spelling.
    value = str(_logical(path))
    return Path("\\\\?\\" + value) if os.name == "nt" and not value.startswith("\\\\?\\") else Path(value)


def _exists(path):
    try:
        _io(path).lstat()
        return True
    except FileNotFoundError:
        return False


def _safe(path, *, missing=False):
    path = _logical(path)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            info = _io(current).lstat()
        except FileNotFoundError:
            if missing:
                return path
            _fail()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            _fail("INSTALL_CACHE_PATH_UNSAFE")
    return path


def _handle_identity(handle):
    # Persist one OS identity, independent of Python's changing st_dev encoding.
    info = FileIdInfo()
    if not _kernel.GetFileInformationByHandleEx(handle, 18, ctypes.byref(info), ctypes.sizeof(info)):
        _fail("INSTALL_CACHE_IDENTITY_UNKNOWN")
    return [info.volume, int.from_bytes(info.file_id, "little")]


def _fd_identity(handle):
    if os.name == "nt":
        import msvcrt
        return _handle_identity(msvcrt.get_osfhandle(handle.fileno()))
    info = os.fstat(handle.fileno())
    return [info.st_dev, info.st_ino]


def _identity(path):
    _safe(path)
    if os.name != "nt":
        info = _io(path).stat()
        if not stat.S_ISDIR(info.st_mode):
            _fail()
        return [info.st_dev, info.st_ino]
    handle = _kernel.CreateFileW(str(_io(path)), 0x80, 7, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        _fail("INSTALL_CACHE_IDENTITY_UNKNOWN")
    try:
        info = FileInfo()
        if (not _kernel.GetFileInformationByHandle(handle, ctypes.byref(info))
                or info.attributes & 0x400 or not info.attributes & 0x10):
            _fail("INSTALL_CACHE_PATH_UNSAFE")
        return _handle_identity(handle)
    finally:
        _kernel.CloseHandle(handle)


def _relative(value):
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or value != PurePosixPath(value).as_posix()
            or PurePosixPath(value).is_absolute() or any(p in {".", ".."} for p in value.split("/"))):
        _fail()
    return value


def _file(path):
    _safe(path)
    before = _io(path).lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_FILE_BYTES:
        _fail("INSTALL_CACHE_PATH_UNSAFE")
    digest = hashlib.sha256()
    size = 0
    with _io(path).open("rb") as handle:
        opened = os.fstat(handle.fileno())
        identity = _fd_identity(handle)
        if ((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                or opened.st_nlink != 1 or not stat.S_ISREG(opened.st_mode)):
            _fail("INSTALL_CACHE_CHANGED")
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                _fail("INSTALL_CACHE_LIMIT")
        after = os.fstat(handle.fileno())
        if (_fd_identity(handle) != identity or after.st_nlink != 1
                or (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            _fail("INSTALL_CACHE_CHANGED")
    current = _io(path).lstat()
    # Compare path metadata with path metadata and fd metadata with fd metadata:
    # Windows Python 3.14 exposes different ctime semantics for lstat and fstat.
    if (size != before.st_size or current.st_nlink != 1
            or (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)):
        _fail("INSTALL_CACHE_CHANGED")
    return {"identity": identity, "size_bytes": size, "sha256": digest.hexdigest()}


def _tree(root):
    _identity(root)
    files, directories = {}, {"": _identity(root)}
    todo = [root]
    total = 0
    while todo:
        parent = todo.pop()
        _safe(parent)
        for entry in sorted(_io(parent).iterdir()):
            path = parent / entry.name
            relative = _relative(path.relative_to(root).as_posix())
            _safe(path)
            if _io(path).is_dir():
                directories[relative] = _identity(path)
                todo.append(path)
            else:
                files[relative] = _file(path)
                total += files[relative]["size_bytes"]
            if len(files) + len(directories) > MAX_ENTRIES or total > MAX_TREE_BYTES:
                _fail("INSTALL_CACHE_LIMIT")
    return {"files": files, "directories": directories}


def _read(path):
    _safe(path)
    info = _io(path).stat()
    if not _io(path).is_file() or info.st_nlink != 1 or info.st_size > MAX_LEDGER_BYTES:
        _fail()
    with _io(path).open("rb") as handle:
        raw = handle.read(MAX_LEDGER_BYTES + 1)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail()
    if not isinstance(value, dict) or canonical_json(value) != raw:
        _fail()
    return value, hashlib.sha256(raw).hexdigest()


def _new_json(path, value):
    _safe(path, missing=True)
    raw = canonical_json(value)
    if len(raw) > MAX_LEDGER_BYTES:
        _fail("INSTALL_CACHE_LIMIT")
    physical = _io(path)
    with physical.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _state(path, value):
    # An owned ledger + kernel lease serializes these fixed-name publications.
    _safe(path.parent)
    temporary = path.with_name("state-" + uuid.uuid4().hex + ".pending")
    _new_json(temporary, value)
    _safe(path, missing=True)
    os.replace(_io(temporary), _io(path))
    from enterprise.release.current_release import sync_state_root_directory
    sync_state_root_directory(path.parent)


@contextmanager
def _lease(path, identity):
    _safe(path)
    physical = _io(path)
    with physical.open("r+b") as handle:
        info = os.fstat(handle.fileno())
        if _fd_identity(handle) != identity or info.st_size != 1 or info.st_nlink != 1:
            _fail()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise CacheError("INSTALL_CACHE_BUSY") from exc
        try:
            if handle.read(1) != b"C":
                _fail()
            yield
        finally:
            # close() is authoritative even if an explicit unlock is unavailable.
            if os.name != "nt":
                fcntl.flock(handle, fcntl.LOCK_UN)


def _exited(value):
    if (not isinstance(value, dict) or set(value) != {"pid", "created_at", "executable"}
            or type(value["pid"]) is not int or value["pid"] < 1
            or type(value["created_at"]) is not int or value["created_at"] <= 0
            or not isinstance(value["executable"], str) or not value["executable"]):
        _fail()
    expected = ProcessIdentity(**value)
    observed = process_identity(expected.pid)
    if observed is not None:
        return not same_process(expected, observed)  # Reused PID is not its former owner.
    if os.name != "nt":
        _fail("INSTALL_CACHE_PROCESS_UNCONFIRMED")
    from enterprise.runtime.ownership import _kernel32
    handle = _kernel32.OpenProcess(0x00100000, False, expected.pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # INVALID_PARAMETER: PID does not exist.
            return True
        _fail("INSTALL_CACHE_PROCESS_UNCONFIRMED")
    try:
        result = _kernel32.WaitForSingleObject(handle, 0)
        if result == 0:
            return True
        _fail("INSTALL_CACHE_PROCESS_UNCONFIRMED")
    finally:
        _kernel32.CloseHandle(handle)


def _closed_payload(container, assets, raw_app_root, verified):
    from enterprise.install_entry import verify_entry_bundle
    from enterprise.release.release_manifest_v2 import parse_inventory_bytes, verify_materialized_release
    source = verified.manifest.section("enterprise_source")
    verify_entry_bundle(_io(assets / "native-entry"), commit=source["commit"], tree=source["tree"])
    verify_materialized_release(_io(raw_app_root), inventory_path=_io(raw_app_root / "release-payload-inventory.json"))
    inventory = parse_inventory_bytes(verified.inventory_path.read_bytes())
    expected = {_logical(path).relative_to(container).as_posix() for path in (
        verified.archive_path, verified.manifest_path, verified.inventory_path,
        assets / "native-entry/InfiniteCanvas.exe", assets / "native-entry/native-entry-build-record.json")}
    prefix = raw_app_root.relative_to(container).as_posix() + "/"
    expected.update(prefix + item.path for item in inventory.entries)
    expected.update(prefix + value for value in ("release-manifest.json", "release-payload-inventory.json"))
    tree = _tree(container)
    expected_dirs = {""}
    for name in expected:
        parent = PurePosixPath(name).parent
        while parent.as_posix() != ".":
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    if set(tree["files"]) != expected or set(tree["directories"]) != expected_dirs:
        _fail("INSTALL_CACHE_CONTENT_UNPROVEN")
    return tree


def _no_recovery_dependency(target, local_base):
    from enterprise.paths import PortableRootInputs, validate_path_roots_for_use
    from enterprise.release.current_release import resolve_portable_path_roots
    from enterprise.ops.update.mvp import UpdateJobStore
    roots = resolve_portable_path_roots(PortableRootInputs(target, local_base))
    validate_path_roots_for_use(roots)
    for path in (roots.STATE_ROOT / "system-update-active.lock", roots.RUNTIME_ROOT / "runtime-reconcile.lock"):
        _safe(path, missing=True)
        if _exists(path):
            _fail("INSTALL_CACHE_RECOVERY_DEPENDENCY")
    if UpdateJobStore(roots).pending_recovery_jobs(initialize=False):
        _fail("INSTALL_CACHE_RECOVERY_DEPENDENCY")


@contextmanager
def setup_cache_session(*, local_app_data_base, assets, raw_app_root, verified, target, client):
    """Track only the canonical persistent Setup layout; temporary fresh install is unchanged."""
    root = cache_root(local_app_data_base)
    assets, raw_app_root, target = map(_logical, (assets, raw_app_root, target))
    container = assets.parent
    if container.parent != root:
        yield None
        return
    if not ID.fullmatch(container.name) or assets.name != "install-ux-bundle":
        _fail("INSTALL_CACHE_PATH_UNSAFE")
    worker = process_identity(os.getpid())
    if client is None or worker is None:
        _fail("INSTALL_CACHE_PROCESS_UNCONFIRMED")
    ledger = root / ".ledger" / container.name
    _safe(ledger, missing=True)
    if not _exists(ledger):
        tree = _closed_payload(container, assets, raw_app_root, verified)
        _io(ledger).mkdir(parents=True, exist_ok=False)
        runner = ledger / "runner.lock"
        physical = _io(runner)
        with physical.open("xb") as handle:
            handle.write(b"C")
            handle.flush()
            os.fsync(handle.fileno())
        receipt = {"schema_version": RECEIPT_SCHEMA, "cache_id": container.name,
                   "container_identity": _identity(container), "lease_identity": _file(runner)["identity"],
                   "release_id": verified.manifest.release_id, "manifest_sha256": verified.manifest.raw_sha256, **tree}
        _new_json(ledger / "receipt.json", receipt)
    receipt, digest = _read(ledger / "receipt.json")
    _validate_receipt(receipt, container.name)
    with _lease(ledger / "runner.lock", receipt["lease_identity"]):
        if _tree(container) != {"files": receipt["files"], "directories": receipt["directories"]}:
            _fail("INSTALL_CACHE_CHANGED")
        value = {"schema_version": STATE_SCHEMA, "cache_id": container.name, "status": "RETAIN",
                 "client": client.snapshot(), "worker": worker.snapshot(), "install_root": str(target),
                 "install_identity": _identity(target), "receipt_sha256": digest}
        _state(ledger / "state.json", value)
        session = {"value": value, "ledger": ledger, "target": target, "local_base": local_app_data_base}
        yield session


def finish_setup_cache(session, response):
    if session is None:
        return
    if (response.get("status") != "succeeded" or response.get("cleanup_warning")
            or response.get("repair_state", "NONE") not in {"SUCCEEDED", "ROLLED_BACK", "NONE", "STOPPED_BEFORE_SWITCH"}):
        return
    try:
        _no_recovery_dependency(session["target"], session["local_base"])
        _state(session["ledger"] / "state.json", {**session["value"], "status": "COMPLETE"})
    except Exception:
        # Bookkeeping cannot turn an already committed repair into a failure.
        # Missing/RETAIN/uncertain state is never authorization to delete.
        response["cache_warning"] = "INSTALL_CACHE_RETAINED"


def _valid_identity(value):
    return isinstance(value, list) and len(value) == 2 and all(type(v) is int and v >= 0 for v in value)


def _validate_receipt(receipt, cache_id):
    if (set(receipt) != RECEIPT_KEYS or receipt["schema_version"] != RECEIPT_SCHEMA
            or receipt["cache_id"] != cache_id or not _valid_identity(receipt["container_identity"])
            or not _valid_identity(receipt["lease_identity"]) or not SHA.fullmatch(str(receipt["manifest_sha256"]))
            or not isinstance(receipt["release_id"], str) or not receipt["release_id"]
            or not isinstance(receipt["files"], dict) or not isinstance(receipt["directories"], dict)
            or len(receipt["files"]) + len(receipt["directories"]) > MAX_ENTRIES
            or receipt["directories"].get("") != receipt["container_identity"]):
        _fail()
    for name, token in receipt["files"].items():
        _relative(name)
        if (not name.startswith("install-ux-bundle/") or not isinstance(token, dict)
                or set(token) != {"identity", "size_bytes", "sha256"} or not _valid_identity(token["identity"])
                or type(token["size_bytes"]) is not int or not 0 <= token["size_bytes"] <= MAX_FILE_BYTES
                or not SHA.fullmatch(str(token["sha256"]))):
            _fail()
    for name, identity in receipt["directories"].items():
        if name:
            _relative(name)
        if not _valid_identity(identity):
            _fail()


def _inspect(root, cache_id, local_base):
    if not ID.fullmatch(cache_id):
        _fail("INSTALL_CACHE_SELECTION_INVALID")
    ledger = root / ".ledger" / cache_id
    receipt, digest = _read(ledger / "receipt.json")
    _validate_receipt(receipt, cache_id)
    state, state_digest = _read(ledger / "state.json")
    if (set(state) != STATE_KEYS or state["schema_version"] != STATE_SCHEMA or state["cache_id"] != cache_id
            or state["receipt_sha256"] != digest or state["status"] not in {"COMPLETE", "DELETING"}
            or not isinstance(state["install_root"], str) or not Path(state["install_root"]).is_absolute()
            or not _valid_identity(state["install_identity"])):
        _fail("INSTALL_CACHE_RETAIN")
    if not _exited(state["client"]) or not _exited(state["worker"]):
        _fail("INSTALL_CACHE_BUSY")
    target = Path(state["install_root"])
    if _identity(target) != state["install_identity"]:
        _fail("INSTALL_CACHE_CHANGED")
    _no_recovery_dependency(target, local_base)
    container = root / cache_id if state["status"] == "COMPLETE" else root / ".quarantine" / cache_id
    if _exists(root / cache_id) and _exists(root / ".quarantine" / cache_id):
        _fail("INSTALL_CACHE_CHANGED")
    if state["status"] == "DELETING" and not _exists(container):
        # Crash before rename, or after removing the final directory.
        if _exists(root / cache_id):
            container = root / cache_id
        else:
            tree = {"files": {}, "directories": {}}
            return receipt, state, container, tree, hashlib.sha256(canonical_json([digest, state_digest, tree])).hexdigest()
    if _identity(container) != receipt["container_identity"]:
        _fail("INSTALL_CACHE_CHANGED")
    tree = _tree(container)
    expected = {"files": receipt["files"], "directories": receipt["directories"]}
    if state["status"] == "COMPLETE":
        if tree != expected:
            _fail("INSTALL_CACHE_CHANGED")
    elif any(token != expected[key].get(name) for key in tree for name, token in tree[key].items()):
        _fail("INSTALL_CACHE_CHANGED")  # Interrupted cleanup permits missing, never changed/additional members.
    token = hashlib.sha256(canonical_json([digest, state_digest, tree])).hexdigest()
    return receipt, state, container, tree, token


def inspect_cache(*, local_app_data_base):
    root = cache_root(local_app_data_base)
    _safe(root, missing=True)
    if not _exists(root):
        return {"candidates": [], "retained_unknown": 0}
    names = set()
    unknown = 0
    for parent in (root, root / ".quarantine"):
        _safe(parent, missing=True)
        if not _exists(parent):
            continue
        for path in _io(parent).iterdir():
            if parent == root and path.name in {".ledger", ".quarantine"}:
                continue
            if ID.fullmatch(path.name):
                names.add(path.name)
            else:
                unknown += 1
            if len(names) + unknown > MAX_CONTAINERS:
                _fail("INSTALL_CACHE_LIMIT")
    # Include a cleanup whose last directory was removed just before a crash.
    ledger = root / ".ledger"
    _safe(ledger, missing=True)
    if _exists(ledger):
        for path in _io(ledger).iterdir():
            if ID.fullmatch(path.name):
                names.add(path.name)
            if len(names) > MAX_CONTAINERS:
                _fail("INSTALL_CACHE_LIMIT")
    candidates = []
    for cache_id in sorted(names):
        try:
            receipt, state = _read(ledger / cache_id / "receipt.json")[0], _read(ledger / cache_id / "state.json")[0]
            if state.get("status") == "REMOVED":
                continue
            _validate_receipt(receipt, cache_id)
            with _lease(ledger / cache_id / "runner.lock", receipt["lease_identity"]):
                _, _, _, tree, token = _inspect(root, cache_id, local_app_data_base)
            candidates.append({"cache_id": cache_id, "status": "CLEANABLE", "token": token,
                               "size_bytes": sum(f["size_bytes"] for f in tree["files"].values())})
        except (CacheError, OSError, ValueError) as exc:
            code = getattr(exc, "code", "INSTALL_CACHE_UNPROVEN")
            candidates.append({"cache_id": cache_id, "status": code, "token": "", "size_bytes": 0})
    return {"candidates": candidates, "retained_unknown": unknown}


def _remove_file(path, expected):
    """Pin the actual Windows file, deny new writers/renames, then delete by handle.

    This does not trust a path lstat followed by DeleteFile: a substituted parent
    or leaf can never authorize a different inode/byte payload for deletion.
    """
    if os.name != "nt":
        _fail("INSTALL_WINDOWS_REQUIRED")
    import msvcrt
    kernel = _kernel
    _safe(path)
    handle = kernel.CreateFileW(str(_io(path)), 0x80000000 | 0x00010000, 1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        _fail("INSTALL_CACHE_FILE_BUSY")
    try:
        fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
    except Exception:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(fd, "rb") as stream:  # Owns and closes the original handle.
        info = os.fstat(stream.fileno())
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                _fail("INSTALL_CACHE_LIMIT")
        actual = {"identity": _handle_identity(handle), "size_bytes": size, "sha256": digest.hexdigest()}
        if actual != expected or info.st_nlink != 1 or not stat.S_ISREG(info.st_mode):
            _fail("INSTALL_CACHE_CHANGED")
        delete = wintypes.BOOLEAN(1)
        if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)):
            _fail("INSTALL_CACHE_FILE_BUSY")


def _directory_action(path, identity, *, destination=None):
    """Rename/remove a pinned, non-reparse Windows directory; never copy or overwrite."""
    if os.name != "nt":
        _fail("INSTALL_WINDOWS_REQUIRED")
    kernel = _kernel
    _safe(path)
    handle = kernel.CreateFileW(str(_io(path)), 0x00010000 | 0x00000080, 3, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        _fail("INSTALL_CACHE_FILE_BUSY")
    try:
        info = FileInfo()
        if (not kernel.GetFileInformationByHandle(handle, ctypes.byref(info))
                or info.attributes & 0x400 or not info.attributes & 0x10
                or _handle_identity(handle) != identity):
            _fail("INSTALL_CACHE_CHANGED")
        if destination is None:
            delete = wintypes.BOOLEAN(1)
            ok = kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete))
        else:
            _safe(destination, missing=True)
            if _exists(destination) or _identity(destination.parent)[0] != identity[0]:
                _fail("INSTALL_CACHE_CHANGED")
            name = str(_io(destination))
            class RenameInfo(ctypes.Structure):
                _fields_ = [("replace", wintypes.BOOLEAN), ("root", wintypes.HANDLE),
                            ("length", wintypes.DWORD), ("name", wintypes.WCHAR * (len(name) + 1))]
            rename = RenameInfo(False, None, len(name.encode("utf-16-le")), name)
            ok = kernel.SetFileInformationByHandle(handle, 3, ctypes.byref(rename), ctypes.sizeof(rename))
        if not ok:
            _fail("INSTALL_CACHE_FILE_BUSY")
    finally:
        kernel.CloseHandle(handle)


def clean_cache(*, local_app_data_base, cache_id, token, confirmed):
    if confirmed is not True or not isinstance(cache_id, str) or not ID.fullmatch(cache_id) or not isinstance(token, str) or not SHA.fullmatch(token):
        _fail("INSTALL_CACHE_CONFIRMATION_REQUIRED")
    root = cache_root(local_app_data_base)
    ledger = root / ".ledger" / cache_id
    receipt, _ = _read(ledger / "receipt.json")
    _validate_receipt(receipt, cache_id)
    deleted_bytes = 0
    with _lease(ledger / "runner.lock", receipt["lease_identity"]):
        receipt, state, container, tree, current = _inspect(root, cache_id, local_app_data_base)
        if current != token:
            _fail("INSTALL_CACHE_PREVIEW_CHANGED")
        _state(ledger / "state.json", {**state, "status": "DELETING"})
        _checkpoint("deleting_recorded")
        quarantine = root / ".quarantine" / cache_id
        if _exists(container) and container != quarantine:
            _safe(quarantine, missing=True)
            _io(quarantine.parent).mkdir(exist_ok=True)
            if _exists(quarantine) or _identity(container) != receipt["container_identity"]:
                _fail("INSTALL_CACHE_CHANGED")
            _directory_action(container, receipt["container_identity"], destination=quarantine)
            container = quarantine
        _checkpoint("quarantined")
        if _exists(container):
            observed = _tree(container)
            if observed != tree:
                _fail("INSTALL_CACHE_CHANGED")
            for name, expected in tree["files"].items():
                path = container / name
                if _file(path) != expected or _identity(container) != receipt["container_identity"]:
                    _fail("INSTALL_CACHE_CHANGED")
                _remove_file(path, expected)  # Never rmtree; delete only the pinned owned file.
                deleted_bytes += expected["size_bytes"]
                _checkpoint("member_removed")
            for name, identity in sorted(tree["directories"].items(), key=lambda item: item[0].count("/") + bool(item[0]), reverse=True):
                path = container / name
                if _identity(path) != identity:
                    _fail("INSTALL_CACHE_CHANGED")
                _directory_action(path, identity)
        _checkpoint("tree_removed")
        _state(ledger / "state.json", {**state, "status": "REMOVED"})
    return {"cache_id": cache_id, "deleted_bytes": deleted_bytes, "status": "REMOVED"}
