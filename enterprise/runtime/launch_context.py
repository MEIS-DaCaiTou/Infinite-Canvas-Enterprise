"""Launch context schema and atomic publish primitive for ENV-1B1C-B1."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .error_contract import RuntimeContractError, canonical_json
from .preflight import StartupPreflightResult
from .runtime_manifest import assert_no_reparse_ancestors


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
    if payload.get("schema_version") != LAUNCH_CONTEXT_SCHEMA_VERSION:
        raise RuntimeContractError("LAUNCH_CONTEXT_SCHEMA_INVALID")
    for key in (
        "path_roots_identity",
        "current_release_sha256",
        "runtime_manifest_sha256",
        "python_executable_sha256",
        "startup_preflight_sha256",
    ):
        if not isinstance(payload.get(key), str) or not _SHA_RE.fullmatch(payload[key]):
            raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    if not isinstance(payload.get("instance_id"), str) or not _INSTANCE_RE.fullmatch(payload["instance_id"]):
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    context = RuntimeLaunchContext(**payload)
    if context.canonical_json() != canonical_json(payload):
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    return context


def read_launch_context(path: Path) -> RuntimeLaunchContext:
    assert_no_reparse_ancestors(path, code="LAUNCH_CONTEXT_INVALID")
    try:
        raw = Path(path).read_bytes()
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
    return _validate_payload(payload)


def _file_identity(path: Path) -> tuple[int, int]:
    stat_result = os.stat(path, follow_symlinks=False)
    return stat_result.st_dev, stat_result.st_ino


def _owned_file(path: Path, identity: tuple[int, int] | None) -> bool:
    if identity is None:
        return False
    try:
        return _file_identity(path) == identity
    except OSError:
        return False


def _directory_sync_is_unsupported(exc: OSError, *, stage: str) -> bool:
    if exc.errno in {errno.EINVAL, getattr(errno, "ENOTSUP", 95), getattr(errno, "EOPNOTSUPP", 95)}:
        return True
    if os.name == "nt" and stage == "open" and exc.errno in {errno.EACCES, errno.EPERM}:
        return True
    return False


def sync_context_directory(root: Path) -> str:
    try:
        assert_no_reparse_ancestors(root, code="LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED")
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


def publish_launch_context(
    target: Path,
    context: RuntimeLaunchContext,
    *,
    expected_existing_identity: str | None,
) -> LaunchContextPublishResult:
    target = Path(target)
    if target.name != LAUNCH_CONTEXT_FILENAME:
        raise RuntimeContractError("LAUNCH_CONTEXT_INVALID")
    if target.exists():
        if expected_existing_identity is None:
            raise RuntimeContractError("LAUNCH_CONTEXT_EXISTING_REQUIRED")
        existing = read_launch_context(target)
        if existing.identity != expected_existing_identity:
            raise RuntimeContractError("LAUNCH_CONTEXT_EXISTING_MISMATCH")
    elif expected_existing_identity is not None:
        raise RuntimeContractError("LAUNCH_CONTEXT_EXISTING_FORBIDDEN")
    encoded = context.canonical_json()
    if len(encoded) > LAUNCH_CONTEXT_MAX_BYTES:
        raise RuntimeContractError("LAUNCH_CONTEXT_SIZE_INVALID")
    temporary = target.with_name(LAUNCH_CONTEXT_TEMP_FILENAME)
    created = False
    identity: tuple[int, int] | None = None
    try:
        assert_no_reparse_ancestors(target.parent, code="LAUNCH_CONTEXT_INVALID")
        if temporary.exists():
            raise RuntimeContractError("LAUNCH_CONTEXT_TEMP_EXISTS")
        with temporary.open("xb") as handle:
            created = True
            identity = _file_identity(temporary)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if not _owned_file(temporary, identity):
            raise RuntimeContractError("LAUNCH_CONTEXT_TEMP_OWNERSHIP_LOST")
        os.replace(temporary, target)
        sync_status = sync_context_directory(target.parent)
        return LaunchContextPublishResult(context.identity, True, sync_status)
    except RuntimeContractError:
        raise
    except FileExistsError as exc:
        raise RuntimeContractError("LAUNCH_CONTEXT_TEMP_EXISTS") from exc
    except OSError as exc:
        raise RuntimeContractError("LAUNCH_CONTEXT_WRITE_FAILED") from exc
    finally:
        try:
            if created and _owned_file(temporary, identity):
                temporary.unlink()
        except OSError:
            pass
