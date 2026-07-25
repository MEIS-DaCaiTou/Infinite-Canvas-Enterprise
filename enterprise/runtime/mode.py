"""Explicit runtime mode contract for ENV-1B1C-B1."""

from __future__ import annotations

from dataclasses import dataclass

from .error_contract import RuntimeContractError


MODE_SCHEMA_VERSION = "env-1b1c-runtime-mode-v1"
DEVELOPMENT = "development"
PORTABLE_RELEASE = "portable-release"
SERVER = "server"


@dataclass(frozen=True)
class RuntimeMode:
    mode: str
    allow_system_python: bool
    allows_path_fallback: bool
    release_validation_eligible: bool
    development_only: bool
    schema_version: str = MODE_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "allow_system_python": self.allow_system_python,
            "allows_path_fallback": self.allows_path_fallback,
            "development_only": self.development_only,
            "mode": self.mode,
            "release_validation_eligible": self.release_validation_eligible,
            "schema_version": self.schema_version,
        }


def parse_runtime_mode(value: object) -> RuntimeMode:
    if value is None or value == "":
        raise RuntimeContractError("RUNTIME_MODE_REQUIRED")
    if not isinstance(value, str):
        raise RuntimeContractError("RUNTIME_MODE_INVALID")
    normalized = value.strip().lower()
    if normalized != value:
        raise RuntimeContractError("RUNTIME_MODE_INVALID")
    if normalized == DEVELOPMENT:
        return RuntimeMode(
            mode=DEVELOPMENT,
            allow_system_python=True,
            allows_path_fallback=True,
            release_validation_eligible=False,
            development_only=True,
        )
    if normalized == PORTABLE_RELEASE:
        return RuntimeMode(
            mode=PORTABLE_RELEASE,
            allow_system_python=False,
            allows_path_fallback=False,
            release_validation_eligible=True,
            development_only=False,
        )
    if normalized == SERVER:
        raise RuntimeContractError("RUNTIME_MODE_NOT_IMPLEMENTED")
    raise RuntimeContractError("RUNTIME_MODE_INVALID")
