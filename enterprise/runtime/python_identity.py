"""Pure Python identity normalization for ENV-1B1C-B1."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .error_contract import RuntimeContractError
from .runtime_manifest import (
    APPROVED_PORTABLE_ARCHITECTURES,
    SINGLE_FILE_HASH_MAX_BYTES,
    abi_from_cache_tag,
    assert_no_reparse_ancestors,
    has_reparse_point,
    normalize_architecture,
)


PYTHON_IDENTITY_SCHEMA = "env-1b1c-python-identity-v1"


@dataclass(frozen=True)
class PythonIdentity:
    implementation: str
    version: str
    abi: str
    architecture: str
    architecture_supported: bool
    pointer_bits: int
    executable_basename: str
    executable_sha256: str
    prefix_identity: str
    base_prefix_identity: str
    dont_write_bytecode: bool
    no_user_site: bool
    schema_version: str = PYTHON_IDENTITY_SCHEMA

    def public_snapshot(self) -> dict[str, object]:
        return {
            "abi": self.abi,
            "architecture": self.architecture,
            "architecture_supported": self.architecture_supported,
            "base_prefix_identity": self.base_prefix_identity,
            "dont_write_bytecode": self.dont_write_bytecode,
            "executable_basename": self.executable_basename,
            "executable_sha256": self.executable_sha256,
            "implementation": self.implementation,
            "no_user_site": self.no_user_site,
            "pointer_bits": self.pointer_bits,
            "prefix_identity": self.prefix_identity,
            "schema_version": self.schema_version,
            "version": self.version,
        }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            if size > SINGLE_FILE_HASH_MAX_BYTES:
                raise RuntimeContractError("PYTHON_IDENTITY_HASH_LIMIT_EXCEEDED", details={"label": path.name})
            digest.update(chunk)
    return digest.hexdigest()


def _identity_for_basename(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return hashlib.sha256(Path(value).name.encode("utf-8")).hexdigest()


def build_python_identity(
    executable: Path,
    probe: dict[str, Any],
    *,
    expected_executable: Path | None = None,
) -> PythonIdentity:
    executable = Path(executable)
    assert_no_reparse_ancestors(executable, code="PYTHON_IDENTITY_REPARSE_FORBIDDEN")
    if not executable.is_file() or has_reparse_point(executable):
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISSING", details={"label": executable.name})
    if executable.name.lower() != "python.exe":
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_INVALID", details={"label": executable.name})
    if expected_executable is not None:
        try:
            if executable.resolve() != Path(expected_executable).resolve():
                raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH", details={"label": executable.name})
        except OSError as exc:
            raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH", details={"label": executable.name}) from exc
    implementation = str(probe.get("implementation", "")).lower()
    if implementation != "cpython":
        raise RuntimeContractError("PYTHON_IDENTITY_IMPLEMENTATION_INVALID")
    version = probe.get("version")
    if not isinstance(version, str) or not version.startswith("3.10."):
        raise RuntimeContractError("PYTHON_IDENTITY_VERSION_INVALID")
    abi = abi_from_cache_tag(probe.get("cache_tag"))
    architecture = normalize_architecture(probe.get("machine", probe.get("architecture")))
    pointer_bits = probe.get("pointer_bits")
    if pointer_bits != 64:
        raise RuntimeContractError("PYTHON_IDENTITY_ARCHITECTURE_INVALID")
    if abi != "cp310":
        raise RuntimeContractError("PYTHON_IDENTITY_ABI_INVALID")
    if architecture not in APPROVED_PORTABLE_ARCHITECTURES:
        # Parsed but not approved for current formal Windows portable target.
        architecture_supported = False
    else:
        architecture_supported = True
    if probe.get("dont_write_bytecode") is not True or probe.get("no_user_site") is not True:
        raise RuntimeContractError("PYTHON_IDENTITY_BYTECODE_POLICY_INVALID")
    return PythonIdentity(
        implementation="CPython",
        version=version,
        abi=abi,
        architecture=architecture,
        architecture_supported=architecture_supported,
        pointer_bits=64,
        executable_basename=executable.name,
        executable_sha256=_hash_file(executable),
        prefix_identity=_identity_for_basename(probe.get("prefix")),
        base_prefix_identity=_identity_for_basename(probe.get("base_prefix")),
        dont_write_bytecode=True,
        no_user_site=True,
    )
