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
    is_strict_cpython_314_version,
    normalize_architecture,
)
from enterprise.path_safety import (
    PathSafetyError,
    assert_no_reparse_ancestors,
    assert_path_within_root,
    has_reparse_point,
    lexical_path_state,
)


PYTHON_IDENTITY_SCHEMA = "env-1b1c-python-identity-v1"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


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

    def validated(self) -> "PythonIdentity":
        if (
            self.schema_version != PYTHON_IDENTITY_SCHEMA
            or self.implementation != "CPython"
            or not is_strict_cpython_314_version(self.version)
            or self.abi != "cp314"
            or self.architecture not in {"x64", "arm64"}
            or self.architecture_supported != (self.architecture in APPROVED_PORTABLE_ARCHITECTURES)
            or self.pointer_bits != 64
            or self.executable_basename.lower() != "python.exe"
            or any(not isinstance(value, str) or _SHA_RE.fullmatch(value) is None for value in (self.executable_sha256, self.prefix_identity, self.base_prefix_identity))
            or self.dont_write_bytecode is not True
            or self.no_user_site is not True
        ):
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        return self

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
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                if size > SINGLE_FILE_HASH_MAX_BYTES:
                    raise RuntimeContractError("PYTHON_IDENTITY_HASH_LIMIT_EXCEEDED", details={"label": "executable"})
                digest.update(chunk)
    except RuntimeContractError:
        raise
    except OSError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_READ_FAILED", details={"label": "executable"}) from exc
    return digest.hexdigest()


def _private_path_identity(path: Path, *, domain: str) -> str:
    """Hash a normalized full path without publishing its plaintext value."""

    material = os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path)))).encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\0" + material).hexdigest()


def _probe_path(probe: dict[str, Any], field: str) -> Path:
    value = probe.get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeContractError("PYTHON_IDENTITY_PREFIX_MISMATCH")
    if os.name == "nt":
        # CPython can preserve the Win32 extended-length namespace in
        # sys.prefix/base_prefix when it starts with an extended cwd, while
        # sys.executable and the trusted Runtime root remain ordinary absolute
        # paths.  Normalize only these two well-formed namespace spellings
        # before the existing reparse/root/equality gates; do not relax them.
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif re.match(r"^\\\\\?\\[A-Za-z]:\\", value):
            value = value[4:]
    return Path(value)


def _assert_identity_path_safe(path: Path, *, runtime_root: Path) -> Path:
    try:
        assert_no_reparse_ancestors(path)
        return assert_path_within_root(path, runtime_root)
    except PathSafetyError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_PREFIX_MISMATCH", details={"label": "runtime_root"}) from exc


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(first)))) == os.path.normcase(
        os.path.normpath(os.path.abspath(os.fspath(second)))
    )


def _validate_soabi(value: object, *, abi: str, architecture: str) -> None:
    """Validate an optional SOABI against the active Windows CPython 3.14 ABI."""

    if value is None:
        return
    if not isinstance(value, str):
        raise RuntimeContractError("PYTHON_IDENTITY_ABI_INVALID")
    normalized = value.strip().lower().replace("_", "-")
    if abi != "cp314" or architecture != "x64" or normalized not in {
        "cp314-win-amd64", "cpython-314-win-amd64",
    }:
        raise RuntimeContractError("PYTHON_IDENTITY_ABI_INVALID")


def build_python_identity(
    executable: Path,
    probe: dict[str, Any],
    *,
    expected_executable: Path | None = None,
    expected_runtime_root: Path | None = None,
) -> PythonIdentity:
    if expected_executable is None or expected_runtime_root is None:
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH")
    executable = Path(executable)
    leaf_state = lexical_path_state(executable)
    if leaf_state == "missing":
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISSING", details={"label": "executable"})
    if leaf_state != "regular":
        raise RuntimeContractError("PYTHON_IDENTITY_REPARSE_FORBIDDEN", details={"label": "executable"})
    try:
        assert_no_reparse_ancestors(executable)
    except PathSafetyError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_REPARSE_FORBIDDEN", details={"label": "executable"}) from exc
    try:
        is_reparse = has_reparse_point(executable)
    except PathSafetyError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_REPARSE_FORBIDDEN", details={"label": "executable"}) from exc
    if not executable.is_file() or is_reparse:
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISSING", details={"label": "executable"})
    if executable.name.lower() != "python.exe":
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_INVALID", details={"label": "executable"})
    try:
        if not _same_path(executable, Path(expected_executable)):
            raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH", details={"label": "executable"})
    except OSError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH", details={"label": "executable"}) from exc
    runtime_root = Path(expected_runtime_root)
    try:
        assert_no_reparse_ancestors(runtime_root)
        if not runtime_root.is_dir() or has_reparse_point(runtime_root):
            raise PathSafetyError("path-reparse-forbidden")
        executable = assert_path_within_root(executable, runtime_root)
        expected_fixed_executable = runtime_root / "python.exe"
        if not _same_path(executable, expected_fixed_executable):
            raise PathSafetyError("path-outside-root")
    except PathSafetyError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH", details={"label": "executable"}) from exc
    probed_executable = _probe_path(probe, "executable")
    if not _same_path(probed_executable, executable):
        raise RuntimeContractError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH", details={"label": "executable"})
    prefix = _assert_identity_path_safe(_probe_path(probe, "prefix"), runtime_root=runtime_root)
    base_prefix = _assert_identity_path_safe(_probe_path(probe, "base_prefix"), runtime_root=runtime_root)
    try:
        if not _same_path(prefix, runtime_root) or not _same_path(base_prefix, runtime_root) or not prefix.is_dir() or not base_prefix.is_dir():
            raise RuntimeContractError("PYTHON_IDENTITY_PREFIX_MISMATCH", details={"label": "runtime_root"})
    except OSError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_PREFIX_MISMATCH", details={"label": "runtime_root"}) from exc
    implementation = str(probe.get("implementation", "")).lower()
    if implementation != "cpython":
        raise RuntimeContractError("PYTHON_IDENTITY_IMPLEMENTATION_INVALID")
    version = probe.get("version")
    if not is_strict_cpython_314_version(version):
        raise RuntimeContractError("PYTHON_IDENTITY_VERSION_INVALID")
    try:
        abi = abi_from_cache_tag(probe.get("cache_tag"))
    except RuntimeContractError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_ABI_INVALID") from exc
    try:
        architecture = normalize_architecture(probe.get("machine", probe.get("architecture")))
    except RuntimeContractError as exc:
        raise RuntimeContractError("PYTHON_IDENTITY_ARCHITECTURE_INVALID") from exc
    pointer_bits = probe.get("pointer_bits")
    if pointer_bits != 64:
        raise RuntimeContractError("PYTHON_IDENTITY_ARCHITECTURE_INVALID")
    if abi != "cp314":
        raise RuntimeContractError("PYTHON_IDENTITY_ABI_INVALID")
    _validate_soabi(probe.get("soabi"), abi=abi, architecture=architecture)
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
