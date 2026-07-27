"""Stable public error payloads for ENV-1B1C runtime contracts.

This module is deliberately pure and standard-library only.  It must remain
safe to import before application configuration, gateway, upstream, or runtime
controller wiring is available.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


ERROR_SCHEMA_VERSION = "env-1b1c-runtime-error-v1"
PORTABLE_EXIT_OK = 0
PORTABLE_EXIT_BLOCKED = 2
_CODE_RE = re.compile(r"^[A-Z0-9_]{3,64}$")
_SAFE_DETAIL_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class ErrorDefinition:
    code: str
    layer: str
    message: str
    retryable: bool = False
    pointer_or_context_may_have_changed: bool = False
    reread_state_required: bool = False
    exit_code: int = PORTABLE_EXIT_BLOCKED


_DEFINITIONS: tuple[ErrorDefinition, ...] = (
    ErrorDefinition("ERROR_CONTRACT_INVALID", "error_contract", "runtime error payload is invalid"),
    ErrorDefinition("RUNTIME_MODE_REQUIRED", "mode", "runtime mode is required"),
    ErrorDefinition("RUNTIME_MODE_INVALID", "mode", "runtime mode is invalid"),
    ErrorDefinition("RUNTIME_MODE_NOT_IMPLEMENTED", "mode", "runtime mode is not implemented"),
    ErrorDefinition("RUNTIME_MANIFEST_MISSING", "runtime_manifest", "runtime manifest is missing"),
    ErrorDefinition("RUNTIME_MANIFEST_READ_FAILED", "runtime_manifest", "runtime manifest could not be read"),
    ErrorDefinition("RUNTIME_MANIFEST_SIZE_INVALID", "runtime_manifest", "runtime manifest size is invalid"),
    ErrorDefinition("RUNTIME_MANIFEST_UTF8_INVALID", "runtime_manifest", "runtime manifest is not valid UTF-8"),
    ErrorDefinition("RUNTIME_MANIFEST_BOM_FORBIDDEN", "runtime_manifest", "runtime manifest BOM is forbidden"),
    ErrorDefinition("RUNTIME_MANIFEST_JSON_INVALID", "runtime_manifest", "runtime manifest JSON is invalid"),
    ErrorDefinition("RUNTIME_MANIFEST_DUPLICATE_KEY", "runtime_manifest", "runtime manifest contains a duplicate key"),
    ErrorDefinition("RUNTIME_MANIFEST_SCHEMA_INVALID", "runtime_manifest", "runtime manifest schema is invalid"),
    ErrorDefinition("RUNTIME_MANIFEST_CORE_MISSING", "runtime_manifest", "runtime manifest is missing a startup core file"),
    ErrorDefinition("RUNTIME_MANIFEST_CORE_LIMIT_EXCEEDED", "runtime_manifest", "runtime manifest startup core file limit exceeded"),
    ErrorDefinition("RUNTIME_MANIFEST_METADATA_INVALID", "runtime_manifest", "runtime manifest optional metadata is invalid"),
    ErrorDefinition("RUNTIME_MANIFEST_CORE_HASH_MISMATCH", "runtime_manifest", "startup core file hash does not match"),
    ErrorDefinition("RUNTIME_MANIFEST_CORE_SIZE_MISMATCH", "runtime_manifest", "startup core file size does not match"),
    ErrorDefinition("RUNTIME_MANIFEST_PATH_INVALID", "runtime_manifest", "runtime manifest path is invalid"),
    ErrorDefinition("RUNTIME_MANIFEST_PATH_DUPLICATE", "runtime_manifest", "runtime manifest path is duplicated"),
    ErrorDefinition("RUNTIME_MANIFEST_REPARSE_FORBIDDEN", "runtime_manifest", "runtime manifest input uses a reparse point"),
    ErrorDefinition("RUNTIME_MANIFEST_HASH_LIMIT_EXCEEDED", "runtime_manifest", "runtime manifest hash limit exceeded"),
    ErrorDefinition("RUNTIME_MANIFEST_CORE_READ_FAILED", "runtime_manifest", "runtime manifest core file could not be read"),
    ErrorDefinition("RUNTIME_MANIFEST_ABI_INVALID", "runtime_manifest", "runtime manifest ABI is invalid"),
    ErrorDefinition("RUNTIME_MANIFEST_ARCHITECTURE_INVALID", "runtime_manifest", "runtime manifest architecture is invalid"),
    ErrorDefinition("PORTABLE_ARCHITECTURE_UNSUPPORTED", "runtime_manifest", "portable architecture is not supported"),
    ErrorDefinition("PYTHON_IDENTITY_EXECUTABLE_MISSING", "python_identity", "Python executable is missing"),
    ErrorDefinition("PYTHON_IDENTITY_EXECUTABLE_INVALID", "python_identity", "Python executable is invalid"),
    ErrorDefinition("PYTHON_IDENTITY_EXECUTABLE_MISMATCH", "python_identity", "Python executable identity mismatch"),
    ErrorDefinition("PYTHON_IDENTITY_PREFIX_MISMATCH", "python_identity", "Python runtime prefix identity mismatch"),
    ErrorDefinition("PYTHON_IDENTITY_CACHE_TAG_INVALID", "python_identity", "Python cache tag is invalid"),
    ErrorDefinition("PYTHON_IDENTITY_REPARSE_FORBIDDEN", "python_identity", "Python executable uses a reparse point"),
    ErrorDefinition("PYTHON_IDENTITY_HASH_LIMIT_EXCEEDED", "python_identity", "Python executable hash limit exceeded"),
    ErrorDefinition("PYTHON_IDENTITY_EXECUTABLE_READ_FAILED", "python_identity", "Python executable could not be read"),
    ErrorDefinition("PYTHON_IDENTITY_IMPLEMENTATION_INVALID", "python_identity", "Python implementation is invalid"),
    ErrorDefinition("PYTHON_IDENTITY_VERSION_INVALID", "python_identity", "Python version is invalid"),
    ErrorDefinition("PYTHON_IDENTITY_ABI_INVALID", "python_identity", "Python ABI is invalid"),
    ErrorDefinition("PYTHON_IDENTITY_ARCHITECTURE_INVALID", "python_identity", "Python architecture is invalid"),
    ErrorDefinition("PYTHON_IDENTITY_BYTECODE_POLICY_INVALID", "python_identity", "Python bytecode policy is invalid"),
    ErrorDefinition("STARTUP_PREFLIGHT_INVALID", "preflight", "startup preflight result is invalid"),
    ErrorDefinition("STARTUP_PREFLIGHT_PYTHON_MANIFEST_MISMATCH", "preflight", "Python executable does not match runtime manifest"),
    ErrorDefinition("LAUNCH_CONTEXT_INVALID", "launch_context", "launch context is invalid"),
    ErrorDefinition("LAUNCH_CONTEXT_SIZE_INVALID", "launch_context", "launch context size is invalid"),
    ErrorDefinition("LAUNCH_CONTEXT_UTF8_INVALID", "launch_context", "launch context is not valid UTF-8"),
    ErrorDefinition("LAUNCH_CONTEXT_BOM_FORBIDDEN", "launch_context", "launch context BOM is forbidden"),
    ErrorDefinition("LAUNCH_CONTEXT_JSON_INVALID", "launch_context", "launch context JSON is invalid"),
    ErrorDefinition("LAUNCH_CONTEXT_DUPLICATE_KEY", "launch_context", "launch context contains a duplicate key"),
    ErrorDefinition("LAUNCH_CONTEXT_SCHEMA_INVALID", "launch_context", "launch context schema is invalid"),
    ErrorDefinition("LAUNCH_CONTEXT_TEMP_EXISTS", "launch_context", "launch context temporary file already exists"),
    ErrorDefinition("LAUNCH_CONTEXT_EXISTING_REQUIRED", "launch_context", "launch context expected identity is required"),
    ErrorDefinition("LAUNCH_CONTEXT_EXISTING_FORBIDDEN", "launch_context", "launch context expected identity is forbidden"),
    ErrorDefinition("LAUNCH_CONTEXT_EXISTING_MISMATCH", "launch_context", "launch context existing identity mismatch"),
    ErrorDefinition("LAUNCH_CONTEXT_TEMP_OWNERSHIP_LOST", "launch_context", "launch context temp ownership was lost"),
    ErrorDefinition("LAUNCH_CONTEXT_WRITE_FAILED", "launch_context", "launch context write failed"),
    ErrorDefinition("LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED", "launch_context", "launch context directory sync failed", pointer_or_context_may_have_changed=True, reread_state_required=True),
    ErrorDefinition("WRITABLE_PROBE_LABEL_INVALID", "writable_probe", "writable probe label is invalid"),
    ErrorDefinition("WRITABLE_PROBE_CREATE_FAILED", "writable_probe", "writable probe could not be created"),
    ErrorDefinition("WRITABLE_PROBE_EXISTS", "writable_probe", "writable probe file already exists"),
    ErrorDefinition("WRITABLE_PROBE_WRITE_FAILED", "writable_probe", "writable probe write failed"),
    ErrorDefinition("WRITABLE_PROBE_IDENTITY_FAILED", "writable_probe", "writable probe identity could not be verified"),
    ErrorDefinition("WRITABLE_PROBE_FSYNC_FAILED", "writable_probe", "writable probe fsync failed"),
    ErrorDefinition("WRITABLE_PROBE_CLOSE_FAILED", "writable_probe", "writable probe close failed"),
    ErrorDefinition("WRITABLE_PROBE_REPARSE_FORBIDDEN", "writable_probe", "writable probe path uses a reparse point"),
    ErrorDefinition("WRITABLE_PROBE_OWNERSHIP_LOST", "writable_probe", "writable probe ownership was lost"),
    ErrorDefinition("WRITABLE_PROBE_CLEANUP_FAILED", "writable_probe", "writable probe cleanup failed"),
    ErrorDefinition("RELEASE_MISMATCH_COMMAND_INVALID", "release_mismatch", "release mismatch command is invalid"),
    ErrorDefinition("PORTABLE_RELEASE_NOT_CURRENT", "release_mismatch", "launcher release is not current"),
    ErrorDefinition("RUNTIME_RELEASE_MISMATCH_RUNNING", "release_mismatch", "another owned release is running"),
    ErrorDefinition("RESTART_RELEASE_MISMATCH_BLOCKED", "release_mismatch", "restart is blocked by release mismatch"),
    ErrorDefinition("STOP_OWNERSHIP_UNAVAILABLE", "release_mismatch", "stop ownership is unavailable"),
    ErrorDefinition("RUNTIME_OWNERSHIP_UNTRUSTED", "release_mismatch", "running instance ownership is untrusted"),
    ErrorDefinition("READINESS_RELEASE_MISMATCH", "readiness", "running release does not match current release"),
    ErrorDefinition("PORTABLE_BOOTSTRAP_INVALID", "portable", "portable bootstrap identity is invalid"),
    ErrorDefinition("PORTABLE_PLATFORM_UNSUPPORTED", "portable", "portable platform is not supported"),
    ErrorDefinition("PORTABLE_PYTHON_MISSING", "portable", "portable Release Python is missing"),
    ErrorDefinition("PORTABLE_LOCALAPPDATA_UNAVAILABLE", "portable", "portable local application data root is unavailable"),
    ErrorDefinition("PORTABLE_RELEASE_LAYOUT_INVALID", "portable", "portable Release layout is invalid"),
    ErrorDefinition("PORTABLE_RELEASE_POINTER_MISMATCH", "portable", "portable Release pointer does not identify this Release"),
    ErrorDefinition("PORTABLE_CONTEXT_UNTRUSTED", "portable", "portable launch context identity is untrusted"),
    ErrorDefinition("PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED", "portable", "portable runtime ownership identity is untrusted"),
    ErrorDefinition("PORTABLE_STARTUP_NOT_READY", "readiness", "portable runtime startup is not ready"),
)

ERROR_REGISTRY: dict[str, ErrorDefinition] = {definition.code: definition for definition in _DEFINITIONS}
if len(ERROR_REGISTRY) != len(_DEFINITIONS):
    raise RuntimeError("duplicate ENV-1B1C error code")


class RuntimeContractError(RuntimeError):
    """Raised by pure ENV-1B1C contract modules with a stable public payload."""

    def __init__(self, code: str, *, details: Mapping[str, Any] | None = None) -> None:
        self.payload = error_payload(code, details=details)
        super().__init__(code)

    @property
    def code(self) -> str:
        return self.payload.code


def _validate_detail_value(value: Any) -> Any:
    if value is None or type(value) in {bool, int}:
        return value
    if isinstance(value, str):
        # Details are public labels/basenames, not free-form diagnostic text.
        # A single bounded symbolic grammar prevents POSIX, Windows, relative,
        # UNC, device, and control-character path disclosure.
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", value) or value in {".", ".."} or ".." in value.split("."):
            raise RuntimeContractError("ERROR_CONTRACT_INVALID")
        return value
    if isinstance(value, (tuple, list)):
        if len(value) > 16:
            raise RuntimeContractError("ERROR_CONTRACT_INVALID")
        return tuple(_validate_detail_value(item) for item in value)
    raise RuntimeContractError("ERROR_CONTRACT_INVALID")


def _sanitize_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in details.items():
        if not isinstance(key, str) or not _SAFE_DETAIL_KEY_RE.fullmatch(key):
            raise RuntimeContractError("ERROR_CONTRACT_INVALID")
        sanitized[key] = _validate_detail_value(value)
    encoded = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 2048:
        raise RuntimeContractError("ERROR_CONTRACT_INVALID")
    return MappingProxyType(sanitized)


def _public_detail_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_public_detail_value(item) for item in value]
    return value


def _public_details(details: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _public_detail_value(value) for key, value in details.items()}


@dataclass(frozen=True)
class ErrorPayload:
    code: str
    layer: str
    message: str
    retryable: bool
    exit_code: int
    pointer_or_context_may_have_changed: bool
    reread_state_required: bool
    details: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    correlation_id: str | None = None
    schema_version: str = ERROR_SCHEMA_VERSION
    status: str = "blocked"

    def __post_init__(self) -> None:
        """Make direct construction as strict as the public factory.

        Do not raise ``RuntimeContractError`` here: constructing that error
        itself constructs an ``ErrorPayload`` and would recurse on malformed
        direct input.
        """

        definition = ERROR_REGISTRY.get(self.code) if isinstance(self.code, str) else None
        if definition is None:
            raise ValueError("error code is invalid")
        if self.schema_version != ERROR_SCHEMA_VERSION or self.status != "blocked":
            raise ValueError("error payload schema or status is invalid")
        if (
            self.layer != definition.layer
            or self.message != definition.message
            or self.retryable is not definition.retryable
            or self.exit_code != definition.exit_code
            or self.pointer_or_context_may_have_changed is not definition.pointer_or_context_may_have_changed
            or self.reread_state_required is not definition.reread_state_required
        ):
            raise ValueError("error payload definition does not match registry")
        if self.correlation_id is not None and (
            not isinstance(self.correlation_id, str) or _CORRELATION_ID_RE.fullmatch(self.correlation_id) is None
        ):
            raise ValueError("correlation_id is invalid")
        if not isinstance(self.details, Mapping):
            raise ValueError("error payload details are invalid")
        try:
            sanitized = _sanitize_details(dict(self.details))
        except RuntimeContractError as exc:
            raise ValueError("error payload details are invalid") from exc
        object.__setattr__(self, "details", sanitized)

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "correlation_id": self.correlation_id,
            "details": _public_details(self.details),
            "exit_code": self.exit_code,
            "layer": self.layer,
            "message": self.message,
            "pointer_or_context_may_have_changed": self.pointer_or_context_may_have_changed,
            "reread_state_required": self.reread_state_required,
            "retryable": self.retryable,
            "schema_version": self.schema_version,
            "status": self.status,
        }

    def canonical_json(self) -> bytes:
        return canonical_json(self.as_public_dict())


def error_payload(
    code: str,
    *,
    details: Mapping[str, Any] | None = None,
    correlation_id: str | None = None,
) -> ErrorPayload:
    if not isinstance(code, str) or not _CODE_RE.fullmatch(code) or code not in ERROR_REGISTRY:
        raise ValueError(f"unknown ENV-1B1C error code: {code!r}")
    if correlation_id is not None and (not isinstance(correlation_id, str) or not _CORRELATION_ID_RE.fullmatch(correlation_id)):
        raise ValueError("correlation_id is invalid")
    definition = ERROR_REGISTRY[code]
    if definition.exit_code not in {PORTABLE_EXIT_OK, PORTABLE_EXIT_BLOCKED}:
        raise ValueError("portable exit code is invalid")
    return ErrorPayload(
        code=definition.code,
        layer=definition.layer,
        message=definition.message,
        retryable=definition.retryable,
        exit_code=definition.exit_code,
        pointer_or_context_may_have_changed=definition.pointer_or_context_may_have_changed,
        reread_state_required=definition.reread_state_required,
        details=_sanitize_details(details),
        correlation_id=correlation_id,
    )


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
