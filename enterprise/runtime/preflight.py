"""Pure startup preflight result and release-mismatch models for ENV-1B1C-B1."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .error_contract import PORTABLE_EXIT_BLOCKED, PORTABLE_EXIT_OK, RuntimeContractError, canonical_json
from .mode import PORTABLE_RELEASE, RuntimeMode
from .python_identity import PythonIdentity
from .runtime_manifest import RuntimeManifestStartupView, is_strict_cpython_310_version
from .writable_probe import WRITABLE_PROBE_LABELS, WritableProbeResult
from enterprise.paths import PathRootsError, validate_release_component


PREFLIGHT_SCHEMA_VERSION = "env-1b1c-startup-preflight-v1"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_WRITABLE_ROOT_ORDER = ("DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT")


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
        if self.schema_version != PREFLIGHT_SCHEMA_VERSION or self.result != "pass" or self.mode != PORTABLE_RELEASE:
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        try:
            validate_release_component(self.release_id)
        except PathRootsError as exc:
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
        if (
            self.python_implementation != "CPython"
            or not is_strict_cpython_310_version(self.python_version)
            or self.python_abi != "cp310"
            or self.architecture != "x64"
        ):
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        if self.bytecode_policy != "disabled-no-user-site":
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        if self.writable_roots_verified != _WRITABLE_ROOT_ORDER:
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        if not isinstance(self.warnings, tuple) or len(set(self.warnings)) != len(self.warnings):
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        if self.warnings:
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
    mode: RuntimeMode,
    release_id: str,
    path_roots_identity: str,
    current_release_sha256: str,
    runtime_manifest: RuntimeManifestStartupView,
    python_identity: PythonIdentity,
    writable_probe_results: tuple[WritableProbeResult, ...],
    warnings: tuple[str, ...] = (),
) -> StartupPreflightResult:
    """Build a preflight result only from independently validated inputs.

    This deliberately accepts no raw interpreter or manifest strings.  B2 may
    orchestrate the validators, but it must hand this pure builder their typed
    results so the canonical preflight identity binds the same artefacts.
    """

    if not isinstance(mode, RuntimeMode):
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    if not isinstance(runtime_manifest, RuntimeManifestStartupView) or not isinstance(python_identity, PythonIdentity):
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    try:
        mode.validated()
        runtime_manifest.validated()
        python_identity.validated()
    except RuntimeContractError as exc:
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID") from exc
    if mode.mode != PORTABLE_RELEASE:
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    if not isinstance(writable_probe_results, tuple) or len(writable_probe_results) != len(_WRITABLE_ROOT_ORDER):
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    if any(not isinstance(item, WritableProbeResult) for item in writable_probe_results):
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    if tuple(item.root_label for item in writable_probe_results) != _WRITABLE_ROOT_ORDER:
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    if set(item.root_label for item in writable_probe_results) != WRITABLE_PROBE_LABELS:
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    try:
        for item in writable_probe_results:
            item.validated()
    except RuntimeContractError as exc:
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID") from exc
    if (
        runtime_manifest.python_implementation != "CPython"
        or python_identity.implementation != "CPython"
        or runtime_manifest.python_version != python_identity.version
        or runtime_manifest.python_abi != python_identity.abi
        or runtime_manifest.architecture != python_identity.architecture
    ):
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    if not is_strict_cpython_310_version(runtime_manifest.python_version):
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    python_record = next((item for item in runtime_manifest.startup_core_files if item.relative_path == "python.exe"), None)
    if python_record is None or python_record.sha256 != python_identity.executable_sha256:
        raise RuntimeContractError("STARTUP_PREFLIGHT_PYTHON_MANIFEST_MISMATCH")
    if runtime_manifest.architecture != "x64" or not runtime_manifest.architecture_supported or not python_identity.architecture_supported:
        raise RuntimeContractError("PORTABLE_ARCHITECTURE_UNSUPPORTED")
    if python_identity.pointer_bits != 64 or not python_identity.dont_write_bytecode or not python_identity.no_user_site:
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    if warnings != ():
        raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
    return StartupPreflightResult(
        result="pass",
        mode=mode.mode,
        release_id=release_id,
        app_root_relative=f"releases/{release_id}",
        path_roots_identity=path_roots_identity,
        current_release_sha256=current_release_sha256,
        runtime_manifest_sha256=runtime_manifest.manifest_sha256,
        python_executable_sha256=python_identity.executable_sha256,
        python_implementation=python_identity.implementation,
        python_version=python_identity.version,
        python_abi=python_identity.abi,
        architecture=python_identity.architecture,
        bytecode_policy="disabled-no-user-site",
        writable_roots_verified=_WRITABLE_ROOT_ORDER,
        warnings=warnings,
    )


@dataclass(frozen=True)
class ReleaseMismatchDecision:
    allowed: bool
    exit_code: int
    launcher_release_mismatch: bool
    running_release_mismatch: bool
    running_instance_present: bool
    ownership_valid: bool
    ownership_untrusted: bool
    status_code: str
    decision_scope: str = "release_gate_only"

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "exit_code": self.exit_code,
            "launcher_release_mismatch": self.launcher_release_mismatch,
            "running_release_mismatch": self.running_release_mismatch,
            "running_instance_present": self.running_instance_present,
            "ownership_valid": self.ownership_valid,
            "ownership_untrusted": self.ownership_untrusted,
            "status_code": self.status_code,
            "decision_scope": self.decision_scope,
        }


def decide_release_mismatch(
    *,
    launcher_release_id: str,
    current_release_id: str,
    running_release_id: str | None,
    owned_instance_valid: bool,
    command: str,
) -> ReleaseMismatchDecision:
    """Apply only the release/ownership gate, never final process or HTTP health.

    ``allowed`` means this narrow release gate has not blocked the command. B2
    must still validate process ownership, launch context, and readiness.
    """
    if command not in {"start", "stop", "restart", "status", "health"}:
        raise RuntimeContractError("RELEASE_MISMATCH_COMMAND_INVALID")
    launcher_mismatch = launcher_release_id != current_release_id
    running_present = running_release_id is not None
    mismatch = running_present and running_release_id != current_release_id
    if launcher_mismatch:
        return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, True, mismatch, running_present, owned_instance_valid, running_present and not owned_instance_valid, "PORTABLE_RELEASE_NOT_CURRENT")
    if running_present and not owned_instance_valid:
        if command == "status":
            return ReleaseMismatchDecision(True, PORTABLE_EXIT_OK, False, mismatch, True, False, True, "RUNTIME_OWNERSHIP_UNTRUSTED")
        if command == "stop":
            return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, False, mismatch, True, False, True, "STOP_OWNERSHIP_UNAVAILABLE")
        return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, False, mismatch, True, False, True, "RUNTIME_OWNERSHIP_UNTRUSTED")
    if not mismatch:
        return ReleaseMismatchDecision(True, PORTABLE_EXIT_OK, False, False, running_present, owned_instance_valid, False, "RELEASE_MATCH")
    if command == "stop":
        if owned_instance_valid:
            return ReleaseMismatchDecision(True, PORTABLE_EXIT_OK, False, True, True, True, False, "STOP_OWNED_MISMATCH_ALLOWED")
        return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, False, True, True, False, True, "STOP_OWNERSHIP_UNAVAILABLE")
    if command == "status":
        return ReleaseMismatchDecision(True, PORTABLE_EXIT_OK, False, True, True, owned_instance_valid, False, "READINESS_RELEASE_MISMATCH")
    if command == "health":
        return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, False, True, True, owned_instance_valid, False, "READINESS_RELEASE_MISMATCH")
    if command == "restart":
        return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, False, True, True, owned_instance_valid, False, "RESTART_RELEASE_MISMATCH_BLOCKED")
    return ReleaseMismatchDecision(False, PORTABLE_EXIT_BLOCKED, False, True, True, owned_instance_valid, False, "RUNTIME_RELEASE_MISMATCH_RUNNING")
