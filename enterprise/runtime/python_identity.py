"""Pure Python identity normalization for ENV-1B1C-B1."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .error_contract import RuntimeContractError
from .runtime_manifest import (
    APPROVED_PORTABLE_ARCHITECTURES,
    SINGLE_FILE_HASH_MAX_BYTES,
    abi_from_cache_tag,
    normalize_architecture,
)
from enterprise.path_safety import (
    PathSafetyError,
    assert_no_reparse_ancestors,
    assert_path_within_root,
    has_reparse_point,
)


PYTHON_IDENTITY_SCHEMA = "env-1b1c-python-identity-v1"
_PYTHON_310_VERSION_RE = re.compile(r"^3\.10\.(?:0|[1-9][0-9]{0,2})$")


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


def _private_path_identity(path: Path, *, domain: str) -> str:
    """Hash a normalized full path without publishing its plaintext value."""

    material = os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path)))).encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\0" + material).hexdigest()


def _probe_path(probe: dict[str, Any], field: str) -> Path:
    value = probe.get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeContractError("PYTHON_IDENTITY_PREFIX_MISMATCH")
    return Path(value)


def _assert_identity_path_safe(path: Path, *, runtime_root: Path) -> Path:
    try:
        assert_no_reparse_ancestors(path)
        return assert_path_within_root(path, runtime_root)
    except PathSafetyError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_PREFIX_MISMATCH", details={"label": path.name}) from exc


def build_python_identity(
    executable: Path,
    probe: dict[str, Any],
    *,
    expected_executable: Path | None = None,
    expected_runtime_root: Path | None = None,
) -> PythonIdentity:
    executable = Path(executable)
    try:
        assert_no_reparse_ancestors(executable)
    except PathSafetyError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_REPARSE_FORBIDDEN", details={"label": executable.name}) from exc
    try:
        is_reparse = has_reparse_point(executable)
    except PathSafetyError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_REPARSE_FORBIDDEN", details={"label": executable.name}) from exc
    if not executable.is_file() or is_reparse:
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISSING", details={"label": executable.name})
    if executable.name.lower() != "python.exe":
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_INVALID", details={"label": executable.name})
    if expected_executable is not None:
        try:
            if os.path.normcase(os.path.abspath(os.fspath(executable))) != os.path.normcase(os.path.abspath(os.fspath(expected_executable))):
                raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH", details={"label": executable.name})
        except OSError as exc:
            raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH", details={"label": executable.name}) from exc
    runtime_root = Path(expected_runtime_root) if expected_runtime_root is not None else (Path(expected_executable).parent if expected_executable is not None else executable.parent)
    try:
        assert_no_reparse_ancestors(runtime_root)
        executable = assert_path_within_root(executable, runtime_root)
    except PathSafetyError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH", details={"label": executable.name}) from exc
    probed_executable = _probe_path(probe, "executable")
    if os.path.normcase(os.path.abspath(os.fspath(probed_executable))) != os.path.normcase(os.path.abspath(os.fspath(executable))):
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH", details={"label": executable.name})
    prefix = _assert_identity_path_safe(_probe_path(probe, "prefix"), runtime_root=runtime_root)
    base_prefix = _assert_identity_path_safe(_probe_path(probe, "base_prefix"), runtime_root=runtime_root)
    implementation = str(probe.get("implementation", "")).lower()
    if implementation != "cpython":
        raise RuntimeContractError("PYTHON_IDENTITY_IMPLEMENTATION_INVALID")
    version = probe.get("version")
    if not isinstance(version, str) or _PYTHON_310_VERSION_RE.fullmatch(version) is None:
        raise RuntimeContractError("PYTHON_IDENTITY_VERSION_INVALID")
    try:
        abi = abi_from_cache_tag(probe.get("cache_tag"))
    except RuntimeContractError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_ABI_INVALID") from exc
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
        prefix_identity=_private_path_identity(prefix, domain="prefix"),
        base_prefix_identity=_private_path_identity(base_prefix, domain="base-prefix"),
        dont_write_bytecode=True,
        no_user_site=True,
    )
