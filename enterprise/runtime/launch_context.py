"""Launch context schema and atomic publish primitive for ENV-1B1C-B1."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from enterprise.path_safety import PathSafetyError, assert_no_reparse_ancestors, has_reparse_point
from enterprise.paths import PathRootsError, validate_release_component

from .error_contract import RuntimeContractError, canonical_json
from .preflight import StartupPreflightResult
from .runtime_manifest import is_strict_cpython_314_version


LAUNCH_CONTEXT_SCHEMA_VERSION = "env-1b1c-runtime-launch-context-v1"
LAUNCH_CONTEXT_FILENAME = "launch-context.json"
LAUNCH_CONTEXT_TEMP_FILENAME = "launch-context.json.new"
LAUNCH_CONTEXT_MAX_BYTES = 16 * 1024
DIRECTORY_SYNC_VERIFIED = "synced"
DIRECTORY_SYNC_UNSUPPORTED = "unsupported"
_FIELDS = frozenset({
    "schema_version",
    "mode",
    "instance_id",
    "release_id",
    "app_root_relative",
    "path_roots_identity",
    "current_release_sha256",
    "runtime_manifest_sha256",
    "python_executable_sha256",
    "python_implementation",
    "python_version",
    "python_abi",
    "architecture",
    "bytecode_policy",
    "startup_preflight_sha256",
})
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_INSTANCE_RE = re.compile(r"^[0-9a-f]{16,64}$")


def _path_safety(path: Path, *, allow_missing: bool = False) -> None:
    try:
        assert_no_reparse_ancestors(path, allow_missing=allow_missing)
    except PathSafetyError as exc:
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID") from exc


def _validate_context_values(context: "RuntimeLaunchContext") -> None:
    if context.schema_version != LAUNCH_CONTEXT_SCHEMA_VERSION:
        raise RuntimeContractError("LAUNCH_CONTEXT_SCHEMA_INVALID")
    if context.mode != "portable-release":
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    if not _INSTANCE_RE.fullmatch(context.instance_id):
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    try:
        validate_release_component(context.release_id)
    except PathRootsError as exc:
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    if context.app_root_relative != f"releases/{context.release_id}":
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    if context.python_implementation != "CPython" or not is_strict_cpython_314_version(context.python_version):
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    if context.python_abi != "cp314" or context.architecture != "x64":
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    if context.bytecode_policy != "disabled-no-user-site":
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    for value in (
        context.path_roots_identity,
        context.current_release_sha256,
        context.runtime_manifest_sha256,
        context.python_executable_sha256,
        context.startup_preflight_sha256,
    ):
        if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
            raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")


@dataclass(frozen=True)
class RuntimeLaunchContext:
    mode: str
    instance_id: str
    release_id: str
    app_root_relative: str
    path_roots_identity: str
    current_release_sha256: str
    runtime_manifest_sha256: str
    python_executable_sha256: str
    python_implementation: str
    python_version: str
    python_abi: str
    architecture: str
    bytecode_policy: str
    startup_preflight_sha256: str
    schema_version: str = LAUNCH_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_context_values(self)

    def as_dict(self) -> dict[str, object]:
        return {
            "app_root_relative": self.app_root_relative,
            "architecture": self.architecture,
            "bytecode_policy": self.bytecode_policy,
            "current_release_sha256": self.current_release_sha256,
            "instance_id": self.instance_id,
            "mode": self.mode,
            "path_roots_identity": self.path_roots_identity,
            "python_abi": self.python_abi,
            "python_executable_sha256": self.python_executable_sha256,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "release_id": self.release_id,
            "runtime_manifest_sha256": self.runtime_manifest_sha256,
            "schema_version": self.schema_version,
            "startup_preflight_sha256": self.startup_preflight_sha256,
        }

    def canonical_json(self) -> bytes:
        return canonical_json(self.as_dict())

    @property
    def identity(self) -> str:
        return hashlib.sha256(self.canonical_json()).hexdigest()


@dataclass(frozen=True)
class LaunchContextPublishResult:
    context_identity: str
    pointer_replaced: bool
    directory_sync_status: Literal["synced", "unsupported"]


def build_launch_context(preflight: StartupPreflightResult, *, instance_id: str) -> RuntimeLaunchContext:
    if not isinstance(preflight, StartupPreflightResult) or preflight.result != "pass":
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    if not isinstance(instance_id, str) or not _INSTANCE_RE.fullmatch(instance_id):
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    return RuntimeLaunchContext(
        mode=preflight.mode,
        instance_id=instance_id,
        release_id=preflight.release_id,
        app_root_relative=preflight.app_root_relative,
        path_roots_identity=preflight.path_roots_identity,
        current_release_sha256=preflight.current_release_sha256,
        runtime_manifest_sha256=preflight.runtime_manifest_sha256,
        python_executable_sha256=preflight.python_executable_sha256,
        python_implementation=preflight.python_implementation,
        python_version=preflight.python_version,
        python_abi=preflight.python_abi,
        architecture=preflight.architecture,
        bytecode_policy=preflight.bytecode_policy,
        startup_preflight_sha256=preflight.identity,
    )


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeContractError("LAUNCH_CONTEXT_DUPLICATE_KEY")
        result[key] = value
    return result


def _validate_payload(payload: object) -> RuntimeLaunchContext:
    if type(payload) is not dict or set(payload) != _FIELDS:
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    context = RuntimeLaunchContext(**payload)
    if context.canonical_json() != canonical_json(payload):
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    return context


def read_launch_context(path: Path) -> RuntimeLaunchContext:
    _path_safety(Path(path))
    try:
        raw = _read_context_bounded(Path(path))
    except OSError as exc:
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID") from exc
    if not raw or len(raw) > LAUNCH_CONTEXT_MAX_BYTES:
        raise RuntimeContractError("LAUNCH_CONTEXT_SIZE_INVALID")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise RuntimeContractError("LAUNCH_CONTEXT_BOM_FORBIDDEN")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except UnicodeDecodeError as exc:
        raise RuntimeContractError("LAUNCH_CONTEXT_UTF8_INVALID") from exc
    except RuntimeContractError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeContractError("LAUNCH_CONTEXT_JSON_INVALID") from exc
    context = _validate_payload(payload)
    if raw != context.canonical_json():
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    return context


def _read_context_bounded(path: Path) -> bytes:
    """Read at most the context limit plus a single overflow byte."""

    content = bytearray()
    try:
        with Path(path).open("rb") as handle:
            while len(content) < LAUNCH_CONTEXT_MAX_BYTES + 1:
                remaining = LAUNCH_CONTEXT_MAX_BYTES + 1 - len(content)
                # Do not issue an unbounded read or request beyond the single
                # overflow byte used to distinguish exact-limit input.
                chunk = handle.read(min(4 * 1024, remaining))
                if not chunk:
                    break
                content.extend(chunk)
    except OSError as exc:
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID") from exc
    if not content or len(content) > LAUNCH_CONTEXT_MAX_BYTES:
        raise RuntimeContractError("LAUNCH_CONTEXT_SIZE_INVALID")
    return bytes(content)


def _file_identity(path: Path) -> tuple[int, int]:
    stat_result = os.lstat(path)
    return stat_result.st_dev, stat_result.st_ino


def _lexical_exists(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID") from exc


def _owned_file(path: Path, identity: tuple[int, int] | None, expected: bytes) -> bool:
    if identity is None:
        return False
    try:
        metadata = os.lstat(path)
        if not stat.S_ISREG(metadata.st_mode) or _file_identity(path) != identity:
            return False
        if has_reparse_point(path):
            return False
        actual = _read_exact_bounded(path, len(expected))
        return actual == expected
    except (OSError, PathSafetyError):
        return False


def _read_exact_bounded(path: Path, expected_length: int) -> bytes | None:
    """Read at most one byte beyond the expected ownership payload.

    Ownership checks are deliberately not general file readers: a foreign
    replacement larger than the expected payload is immediately unowned.
    """

    if expected_length < 0:
        return None
    fd: int | None = None
    try:
        fd = os.open(path, os.O_RDONLY)
        data = os.read(fd, expected_length + 1)
        return None if len(data) > expected_length else data
    except OSError:
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                return None


def _directory_sync_is_unsupported(exc: OSError, *, stage: str) -> bool:
    if exc.errno in {errno.EINVAL, getattr(errno, "ENOTSUP", 95), getattr(errno, "EOPNOTSUPP", 95)}:
        return True
    if os.name == "nt" and stage == "open" and exc.errno in {errno.EACCES, errno.EPERM}:
        return True
    return False


def sync_context_directory(root: Path) -> str:
    try:
        _path_safety(root)
        fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError as exc:
        if _directory_sync_is_unsupported(exc, stage="open"):
            return DIRECTORY_SYNC_UNSUPPORTED
        raise RuntimeContractError("LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED") from exc
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if _directory_sync_is_unsupported(exc, stage="fsync"):
                return DIRECTORY_SYNC_UNSUPPORTED
            raise RuntimeContractError("LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED") from exc
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    return DIRECTORY_SYNC_VERIFIED


def _verify_target_state(target: Path, expected_existing_identity: str | None) -> None:
    """Check target immediately before publication.

    This is deliberately a second verification, not an atomic CAS claim.  An
    external exclusive runtime lock remains mandatory for lifecycle wiring in
    B2; an outside actor can still race the operating-system replacement.
    """
    if _lexical_exists(target):
        if expected_existing_identity is None:
            raise RuntimeContractError("LAUNCH_CONTEXT_EXISTING_FORBIDDEN")
        if read_launch_context(target).identity != expected_existing_identity:
            raise RuntimeContractError("LAUNCH_CONTEXT_EXISTING_MISMATCH")
    elif expected_existing_identity is not None:
        raise RuntimeContractError("LAUNCH_CONTEXT_EXISTING_FORBIDDEN")


def publish_launch_context(
    target: Path,
    context: RuntimeLaunchContext,
    *,
    expected_existing_identity: str | None,
) -> LaunchContextPublishResult:
    target = Path(target)
    if target.name != LAUNCH_CONTEXT_FILENAME:
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    if _lexical_exists(target) and expected_existing_identity is None:
        raise RuntimeContractError("LAUNCH_CONTEXT_EXISTING_REQUIRED")
    _verify_target_state(target, expected_existing_identity)
    _validate_context_values(context)
    encoded = context.canonical_json()
    if len(encoded) > LAUNCH_CONTEXT_MAX_BYTES:
        raise RuntimeContractError("LAUNCH_CONTEXT_SIZE_INVALID")
    temporary = target.with_name(LAUNCH_CONTEXT_TEMP_FILENAME)
    created = False
    target_replaced = False
    identity: tuple[int, int] | None = None
    try:
        _path_safety(target.parent)
        if _lexical_exists(temporary):
            raise RuntimeContractError("LAUNCH_CONTEXT_TEMP_EXISTS")
        with temporary.open("xb") as handle:
            created = True
            identity = _file_identity(temporary)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if not _owned_file(temporary, identity, encoded):
            raise RuntimeContractError("LAUNCH_CONTEXT_TEMP_OWNERSHIP_LOST")
        _verify_target_state(target, expected_existing_identity)
        if not _owned_file(temporary, identity, encoded):
            raise RuntimeContractError("LAUNCH_CONTEXT_TEMP_OWNERSHIP_LOST")
        os.replace(temporary, target)
        target_replaced = True
        try:
            sync_status = sync_context_directory(target.parent)
        except RuntimeContractError as exc:
            if exc.code == "LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED":
                raise
            raise RuntimeContractError("LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED") from exc
        except OSError as exc:
            raise RuntimeContractError("LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED") from exc
        return LaunchContextPublishResult(context.identity, True, sync_status)
    except RuntimeContractError as exc:
        # Once replacement succeeded the target already represents the new
        # authoritative context.  Any later unexpected failure is an
        # uncertain durability outcome and callers must reread it.
        if target_replaced and exc.code != "LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED":
            raise RuntimeContractError("LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED") from exc
        raise
    except FileExistsError as exc:
        raise RuntimeContractError("LAUNCH_CONTEXT_TEMP_EXISTS") from exc
    except OSError as exc:
        raise RuntimeContractError("LAUNCH_CONTEXT_WRITE_FAILED") from exc
    finally:
        try:
            if created and _owned_file(temporary, identity, encoded):
                temporary.unlink()
        except OSError:
            pass
