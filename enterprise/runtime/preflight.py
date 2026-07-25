"""Pure startup preflight result and release-mismatch models for ENV-1B1C-B1."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .error_contract import PORTABLE_EXIT_BLOCKED, PORTABLE_EXIT_OK, RuntimeContractError, canonical_json
from .mode import PORTABLE_RELEASE, parse_runtime_mode


PREFLIGHT_SCHEMA_VERSION = "env-1b1c-startup-preflight-v1"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _require_sha(value: str, code: str = "STARTUP_PREFLIGHT_INVALID") -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise RuntimeContractError(code)
    return value


@dataclass(frozen=True)
class StartupPreflightResult:
    result: str
    mode: str
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
    writable_roots_verified: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    schema_version: str = PREFLIGHT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.result != "pass" or self.mode != PORTABLE_RELEASE:
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        if not _RELEASE_RE.fullmatch(self.release_id):
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        if self.app_root_relative != f"releases/{self.release_id}":
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        for value in (
            self.path_roots_identity,
            self.current_release_sha256,
            self.runtime_manifest_sha256,
            self.python_executable_sha256,
        ):
            _require_sha(value)
        if self.python_implementation != "CPython" or self.python_abi != "cp310" or self.architecture != "x64":
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        if self.bytecode_policy != "disabled-no-user-site":
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        allowed = {"DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"}
        if set(self.writable_roots_verified) != allowed:
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")

    def as_dict(self) -> dict[str, object]:
        return {
            "app_root_relative": self.app_root_relative,
            "architecture": self.architecture,
            "bytecode_policy": self.bytecode_policy,
            "current_release_sha256": self.current_release_sha256,
            "mode": self.mode,
            "path_roots_identity": self.path_roots_identity,
            "python_abi": self.python_abi,
            "python_executable_sha256": self.python_executable_sha256,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "release_id": self.release_id,
            "result": self.result,
            "runtime_manifest_sha256": self.runtime_manifest_sha256,
            "schema_version": self.schema_version,
            "warnings": list(self.warnings),
            "writable_roots_verified": list(self.writable_roots_verified),
        }

    def canonical_json(self) -> bytes:
        return canonical_json(self.as_dict())

    @property
    def identity(self) -> str:
        return hashlib.sha256(self.canonical_json()).hexdigest()


def build_startup_preflight_result(
    *,
    mode_value: str,
    release_id: str,
    path_roots_identity: str,
    current_release_sha256: str,
    runtime_manifest_sha256: str,
    python_executable_sha256: str,
    python_version: str,
    warnings: tuple[str, ...] = (),
) -> StartupPreflightResult:
    mode = parse_runtime_mode(mode_value)
    if mode.mode != PORTABLE_RELEASE:
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    return StartupPreflightResult(
        result="pass",
        mode=mode.mode,
        release_id=release_id,
        app_root_relative=f"releases/{release_id}",
        path_roots_identity=path_roots_identity,
        current_release_sha256=current_release_sha256,
        runtime_manifest_sha256=runtime_manifest_sha256,
        python_executable_sha256=python_executable_sha256,
        python_implementation="CPython",
        python_version=python_version,
        python_abi="cp310",
        architecture="x64",
        bytecode_policy="disabled-no-user-site",
        writable_roots_verified=("CACHE_ROOT", "DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "TEMP_ROOT"),
        warnings=warnings,
    )


@dataclass(frozen=True)
class ReleaseMismatchDecision:
    allowed: bool
    exit_code: int
    running_release_mismatch: bool
    status_code: str

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "exit_code": self.exit_code,
            "running_release_mismatch": self.running_release_mismatch,
            "status_code": self.status_code,
        }


def decide_release_mismatch(
    *,
    launcher_release_id: str,
    current_release_id: str,
    running_release_id: str | None,
    owned_instance_valid: bool,
    command: str,
) -> ReleaseMismatchDecision:
    if command not in {"start", "stop", "restart", "status", "health"}:
        raise RuntimeContractError("RELEASE_MISMATCH_COMMAND_INVALID")
    if launcher_release_id != current_release_id:
        return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, True, "PORTABLE_RELEASE_NOT_CURRENT")
    mismatch = running_release_id is not None and running_release_id != current_release_id
    if not mismatch:
        return ReleaseMismatchDecision(True, PORTABLE_EXIT_OK, False, "RELEASE_MATCH")
    if command == "stop":
        if owned_instance_valid:
            return ReleaseMismatchDecision(True, PORTABLE_EXIT_OK, True, "STOP_OWNED_MISMATCH_ALLOWED")
        return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, True, "STOP_OWNERSHIP_UNAVAILABLE")
    if command == "status":
        return ReleaseMismatchDecision(True, PORTABLE_EXIT_OK, True, "READINESS_RELEASE_MISMATCH")
    if command == "health":
        return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, True, "READINESS_RELEASE_MISMATCH")
    if command == "restart":
        return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, True, "RESTART_RELEASE_MISMATCH_BLOCKED")
    return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, True, "RUNTIME_RELEASE_MISMATCH_RUNNING")
