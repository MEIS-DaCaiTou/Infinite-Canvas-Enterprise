"""Strict, non-activating current-release state primitive for ENV-1B1B."""
from __future__ import annotations

import json
import os
import re
import threading
import errno
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from enterprise.paths import (
    PathRoots,
    PathRootsError,
    PortableRootInputs,
    _assert_no_reparse,
    _normalise,
    derive_portable_path_roots,
    derive_portable_root_layout,
    validate_path_roots_for_use,
    validate_portable_release_layout,
    validate_release_component,
)


SCHEMA_VERSION = "env-1b1b-current-release-v1"
MAX_BYTES = 16 * 1024
FILENAME = "current-release.json"
TEMP_FILENAME = "current-release.json.new"
DIRECTORY_SYNC_VERIFIED = "synced"
DIRECTORY_SYNC_UNSUPPORTED = "unsupported"
_FIELDS = frozenset({"schema_version", "release_id", "app_root_relative", "manifest_sha256", "activated_at", "previous_release_id"})
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_writer_lock = threading.Lock()
# ENV-1B1B deliberately supplies only an in-process writer serialization.
# Cross-process activation locking belongs to a later activation protocol.
CROSS_PROCESS_LOCK = False


class CurrentReleaseError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CurrentRelease:
    schema_version: str
    release_id: str
    app_root_relative: str
    manifest_sha256: str
    activated_at: str
    previous_release_id: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "release_id": self.release_id,
            "app_root_relative": self.app_root_relative, "manifest_sha256": self.manifest_sha256,
            "activated_at": self.activated_at, "previous_release_id": self.previous_release_id,
        }


@dataclass(frozen=True)
class CurrentReleaseWriteResult:
    pointer_replaced: bool
    directory_sync_status: Literal["synced", "unsupported"]


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CurrentReleaseError("CURRENT_RELEASE_DUPLICATE_KEY")
        result[key] = value
    return result


def _validate_release_id(value: object) -> str:
    try:
        return validate_release_component(value)
    except PathRootsError as exc:
        code = "CURRENT_RELEASE_ID_DEVICE" if exc.code == "RELEASE_COMPONENT_DEVICE" else "CURRENT_RELEASE_ID_INVALID"
        raise CurrentReleaseError(code) from exc


def _validate_payload(payload: object, *, expected_manifest_sha256: str | None = None) -> CurrentRelease:
    if type(payload) is not dict:
        raise CurrentReleaseError("CURRENT_RELEASE_NOT_OBJECT")
    if set(payload) != _FIELDS:
        raise CurrentReleaseError("CURRENT_RELEASE_FIELDS_INVALID")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise CurrentReleaseError("CURRENT_RELEASE_SCHEMA_INVALID")
    release_id = _validate_release_id(payload["release_id"])
    app_relative = payload["app_root_relative"]
    if not isinstance(app_relative, str) or "\\" in app_relative or app_relative != f"releases/{release_id}" or app_relative.startswith("/") or ".." in app_relative.split("/") or ":" in app_relative:
        raise CurrentReleaseError("CURRENT_RELEASE_APP_PATH_INVALID")
    manifest = payload["manifest_sha256"]
    if not isinstance(manifest, str) or not _SHA_RE.fullmatch(manifest):
        raise CurrentReleaseError("CURRENT_RELEASE_MANIFEST_SHA_INVALID")
    if expected_manifest_sha256 is not None and manifest != expected_manifest_sha256:
        raise CurrentReleaseError("CURRENT_RELEASE_MANIFEST_SHA_MISMATCH")
    activated = payload["activated_at"]
    if not isinstance(activated, str):
        raise CurrentReleaseError("CURRENT_RELEASE_TIMESTAMP_INVALID")
    try:
        parsed = datetime.strptime(activated, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise CurrentReleaseError("CURRENT_RELEASE_TIMESTAMP_INVALID") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != activated:
        raise CurrentReleaseError("CURRENT_RELEASE_TIMESTAMP_INVALID")
    previous = payload["previous_release_id"]
    if previous is not None:
        previous = _validate_release_id(previous)
        if previous == release_id:
            raise CurrentReleaseError("CURRENT_RELEASE_PREVIOUS_INVALID")
    return CurrentRelease(SCHEMA_VERSION, release_id, app_relative, manifest, activated, previous)


def validate_current_release(
    release: CurrentRelease | dict[str, object], *, expected_manifest_sha256: str | None = None
) -> CurrentRelease:
    """Validate an in-memory pointer with the same strict contract as disk I/O."""
    payload: object = release.as_dict() if isinstance(release, CurrentRelease) else release
    return _validate_payload(payload, expected_manifest_sha256=expected_manifest_sha256)


def canonical_json(release: CurrentRelease) -> bytes:
    return (json.dumps(release.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _file_identity(stat_result: os.stat_result) -> tuple[int, int]:
    """Return stable file identity fields, never content/time-derived ownership."""
    return stat_result.st_dev, stat_result.st_ino


def _owned_temp_still_present(path: Path, identity: tuple[int, int] | None) -> bool:
    if identity is None:
        return False
    try:
        return _file_identity(os.stat(path, follow_symlinks=False)) == identity
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _directory_sync_is_unsupported(exc: OSError, *, stage: str, platform_name: str | None = None) -> bool:
    platform_name = os.name if platform_name is None else platform_name
    errno_value = exc.errno
    unsupported_errnos = {
        errno.EINVAL,
        getattr(errno, "ENOTSUP", 95),
        getattr(errno, "EOPNOTSUPP", getattr(errno, "ENOTSUP", 95)),
    }
    if errno_value in unsupported_errnos:
        return True
    if platform_name == "nt" and stage == "open" and errno_value in {errno.EACCES, errno.EPERM}:
        return True
    return False


def sync_state_root_directory(state_root: Path) -> str:
    """Best-effort directory durability after pointer replacement.

    ``unsupported`` is an explicit platform classification, not a verified
    durable directory sync. Unexpected failures happen after ``os.replace`` may
    already have made the new pointer authoritative; callers must re-read state
    and must not attempt an automatic rollback here.
    """
    try:
        try:
            _assert_no_reparse(state_root, "STATE_ROOT")
        except PathRootsError as exc:
            raise CurrentReleaseError("CURRENT_RELEASE_DIRECTORY_SYNC_FAILED") from exc
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(state_root, flags)
    except OSError as exc:
        if _directory_sync_is_unsupported(exc, stage="open"):
            return DIRECTORY_SYNC_UNSUPPORTED
        raise CurrentReleaseError("CURRENT_RELEASE_DIRECTORY_SYNC_FAILED") from exc
    try:
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            if _directory_sync_is_unsupported(exc, stage="fsync"):
                return DIRECTORY_SYNC_UNSUPPORTED
            raise CurrentReleaseError("CURRENT_RELEASE_DIRECTORY_SYNC_FAILED") from exc
    finally:
        try:
            os.close(directory_fd)
        except OSError:
            pass
    return DIRECTORY_SYNC_VERIFIED


def read_current_release_from_state_root(state_root: Path, *, expected_manifest_sha256: str | None = None) -> CurrentRelease:
    """Read the v1 pointer from a pre-release-owned state root."""
    try:
        state_root = _normalise(state_root, "STATE_ROOT")
    except PathRootsError as exc:
        raise CurrentReleaseError(exc.code) from exc
    path = state_root / FILENAME
    try:
        _assert_no_reparse(state_root, "STATE_ROOT")
        _assert_no_reparse(path, "STATE_ROOT")
    except PathRootsError as exc:
        raise CurrentReleaseError(exc.code) from exc
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise CurrentReleaseError("CURRENT_RELEASE_MISSING") from exc
    except OSError as exc:
        raise CurrentReleaseError("CURRENT_RELEASE_READ_FAILED") from exc
    if not raw or len(raw) > MAX_BYTES:
        raise CurrentReleaseError("CURRENT_RELEASE_SIZE_INVALID")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise CurrentReleaseError("CURRENT_RELEASE_BOM_FORBIDDEN")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except UnicodeDecodeError as exc:
        raise CurrentReleaseError("CURRENT_RELEASE_UTF8_INVALID") from exc
    except CurrentReleaseError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise CurrentReleaseError("CURRENT_RELEASE_JSON_INVALID") from exc
    return _validate_payload(payload, expected_manifest_sha256=expected_manifest_sha256)


def read_current_release(roots: PathRoots, *, expected_manifest_sha256: str | None = None) -> CurrentRelease:
    try:
        validate_path_roots_for_use(roots)
    except PathRootsError as exc:
        raise CurrentReleaseError(exc.code) from exc
    return read_current_release_from_state_root(roots.STATE_ROOT, expected_manifest_sha256=expected_manifest_sha256)


def resolve_portable_path_roots(inputs: PortableRootInputs) -> PathRoots:
    """Complete portable startup's two-stage root derivation without activation.

    Stage one derives only install-owned roots.  Stage two validates the
    current-release pointer stored in ``STATE_ROOT`` and derives the final
    release-owned APP_ROOT/PYTHON_RUNTIME pair.  Callers still own runtime
    entrypoint and interpreter selection (ENV-1B1C).
    """
    layout = derive_portable_root_layout(inputs)
    release = read_current_release_from_state_root(
        layout.STATE_ROOT,
        expected_manifest_sha256=layout.expected_manifest_sha256,
    )
    roots = derive_portable_path_roots(inputs, release.release_id)
    candidate = roots.INSTALL_ROOT.joinpath(*release.app_root_relative.split("/"))
    if os.path.normcase(os.path.normpath(str(candidate))) != os.path.normcase(os.path.normpath(str(roots.APP_ROOT))):
        raise CurrentReleaseError("CURRENT_RELEASE_APP_PATH_MISMATCH")
    try:
        validate_portable_release_layout(roots)
    except PathRootsError as exc:
        raise CurrentReleaseError(exc.code) from exc
    return roots


def resolve_current_app_root(roots: PathRoots, *, expected_manifest_sha256: str | None = None) -> Path:
    release = read_current_release(roots, expected_manifest_sha256=expected_manifest_sha256)
    candidate = roots.INSTALL_ROOT.joinpath(*release.app_root_relative.split("/"))
    expected = roots.RELEASE_ROOT / release.release_id
    if os.path.normcase(os.path.normpath(str(candidate))) != os.path.normcase(os.path.normpath(str(expected))):
        raise CurrentReleaseError("CURRENT_RELEASE_APP_PATH_MISMATCH")
    if not candidate.is_dir():
        raise CurrentReleaseError("CURRENT_RELEASE_APP_ROOT_MISSING")
    try:
        _assert_no_reparse(candidate, "APP_ROOT")
    except PathRootsError as exc:
        raise CurrentReleaseError(exc.code) from exc
    return candidate


def atomic_write_current_release(
    roots: PathRoots,
    release: CurrentRelease,
    *,
    expected_manifest_sha256: str | None = None,
) -> CurrentReleaseWriteResult:
    try:
        validate_path_roots_for_use(roots)
    except PathRootsError as exc:
        raise CurrentReleaseError(exc.code) from exc
    checked = validate_current_release(release, expected_manifest_sha256=expected_manifest_sha256)
    target, temporary = roots.STATE_ROOT / FILENAME, roots.STATE_ROOT / TEMP_FILENAME
    encoded = canonical_json(checked)
    if len(encoded) > MAX_BYTES:
        raise CurrentReleaseError("CURRENT_RELEASE_SIZE_INVALID")
    with _writer_lock:
        created_by_this_invocation = False
        created_temp_identity: tuple[int, int] | None = None
        try:
            _assert_no_reparse(roots.STATE_ROOT, "STATE_ROOT")
            if not roots.STATE_ROOT.is_dir():
                raise CurrentReleaseError("CURRENT_RELEASE_STATE_ROOT_MISSING")
            if temporary.exists():
                raise CurrentReleaseError("CURRENT_RELEASE_TEMP_EXISTS")
            with temporary.open("xb") as handle:
                created_by_this_invocation = True
                created_temp_identity = _file_identity(os.fstat(handle.fileno()))
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            _assert_no_reparse(temporary, "STATE_ROOT")
            if not _owned_temp_still_present(temporary, created_temp_identity):
                raise CurrentReleaseError("CURRENT_RELEASE_TEMP_OWNERSHIP_LOST")
            os.replace(temporary, target)
            sync_status = sync_state_root_directory(roots.STATE_ROOT)
            return CurrentReleaseWriteResult(True, sync_status)
        except CurrentReleaseError:
            raise
        except PathRootsError as exc:
            raise CurrentReleaseError(exc.code) from exc
        except FileExistsError as exc:
            raise CurrentReleaseError("CURRENT_RELEASE_TEMP_EXISTS") from exc
        except OSError as exc:
            raise CurrentReleaseError("CURRENT_RELEASE_WRITE_FAILED") from exc
        finally:
            # Cleanup needs both this invocation's exclusive-create record and
            # the original file identity.  Never infer ownership from bytes,
            # size, mtime, or merely a pathname that another process may have
            # replaced after our create.
            try:
                if created_by_this_invocation and _owned_temp_still_present(temporary, created_temp_identity):
                    temporary.unlink()
            except OSError:
                pass
