"""Bounded Runtime Manifest v1 startup parser for ENV-1B1C-B1.

This is a startup-view parser only.  It does not verify a complete Runtime
tree, wheelhouse, lock, SBOM, dependency closure, or production approval.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .error_contract import RuntimeContractError
from enterprise.path_safety import (
    PathSafetyError,
    assert_no_reparse_ancestors as _assert_no_reparse_ancestors,
    assert_path_within_root,
    has_reparse_point as _has_reparse_point,
)


RUNTIME_MANIFEST_SCHEMA = "enterprise-windows-runtime-manifest-v1"
STARTUP_VIEW_SCHEMA = "env-1b1c-runtime-manifest-startup-view-v1"
MANIFEST_MAX_BYTES = 1024 * 1024
STARTUP_CORE_FILE_COUNT = 5
STARTUP_CORE_FILE_COUNT_HARD_MAX = 8
RELATIVE_PATH_MAX_CHARS = 160
SINGLE_FILE_HASH_MAX_BYTES = 64 * 1024 * 1024
TOTAL_STARTUP_HASH_MAX_BYTES = 128 * 1024 * 1024
STARTUP_CORE_FILES = ("python.exe", "pythonw.exe", "python310.dll", "python310.zip", "python310._pth")
APPROVED_PORTABLE_ARCHITECTURES = frozenset({"x64"})
KNOWN_ARCHITECTURES = frozenset({"x64", "arm64"})
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_PYTHON_310_VERSION_RE = re.compile(r"^3\.10\.(?:0|[1-9][0-9]{0,2})$")
_CANDIDATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_DEVICE_RE = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.I)


@dataclass(frozen=True)
class StartupCoreFile:
    relative_path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class RuntimeManifestStartupView:
    schema_version: str
    manifest_sha256: str
    python_version: str
    python_implementation: str
    python_abi: str
    architecture: str
    architecture_supported: bool
    startup_core_files: tuple[StartupCoreFile, ...]
    startup_core_digest: str
    candidate_id: str | None
    manifest_self_declared_enterprise_commit: str | None
    runtime_manifest_v1_self_consistency_checked: bool = True
    runtime_provenance_promoted: bool = False
    Manifest_v2_implemented: bool = False

    def validated(self) -> "RuntimeManifestStartupView":
        if (
            self.schema_version != STARTUP_VIEW_SCHEMA
            or not isinstance(self.manifest_sha256, str)
            or _SHA_RE.fullmatch(self.manifest_sha256) is None
            or self.python_implementation != "CPython"
            or _PYTHON_310_VERSION_RE.fullmatch(self.python_version) is None
            or self.python_abi != "cp310"
            or self.architecture not in KNOWN_ARCHITECTURES
            or self.architecture_supported != (self.architecture in APPROVED_PORTABLE_ARCHITECTURES)
            or self.runtime_manifest_v1_self_consistency_checked is not True
            or self.runtime_provenance_promoted is not False
            or self.Manifest_v2_implemented is not False
            or not isinstance(self.startup_core_files, tuple)
            or len(self.startup_core_files) != STARTUP_CORE_FILE_COUNT
        ):
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        names: list[str] = []
        digest = hashlib.sha256()
        for record in self.startup_core_files:
            if not isinstance(record, StartupCoreFile):
                raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
            if (
                record.relative_path not in STARTUP_CORE_FILES
                or not isinstance(record.sha256, str)
                or _SHA_RE.fullmatch(record.sha256) is None
                or type(record.size_bytes) is not int
                or record.size_bytes < 0
            ):
                raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
            names.append(record.relative_path)
            encoded = record.relative_path.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            digest.update(record.size_bytes.to_bytes(8, "big"))
            digest.update(bytes.fromhex(record.sha256))
        if tuple(names) != STARTUP_CORE_FILES or self.startup_core_digest != digest.hexdigest():
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        if self.candidate_id is not None and (not isinstance(self.candidate_id, str) or _CANDIDATE_ID_RE.fullmatch(self.candidate_id) is None):
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        if self.manifest_self_declared_enterprise_commit is not None and (
            not isinstance(self.manifest_self_declared_enterprise_commit, str)
            or re.fullmatch(r"[0-9a-f]{40}", self.manifest_self_declared_enterprise_commit) is None
        ):
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        return self

    def as_dict(self) -> dict[str, object]:
        return {
            "Manifest_v2_implemented": self.Manifest_v2_implemented,
            "architecture": self.architecture,
            "architecture_supported": self.architecture_supported,
            "candidate_id": self.candidate_id,
            "manifest_self_declared_enterprise_commit": self.manifest_self_declared_enterprise_commit,
            "manifest_sha256": self.manifest_sha256,
            "python_abi": self.python_abi,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "runtime_manifest_v1_self_consistency_checked": self.runtime_manifest_v1_self_consistency_checked,
            "runtime_provenance_promoted": self.runtime_provenance_promoted,
            "schema_version": self.schema_version,
            "startup_core_digest": self.startup_core_digest,
            "startup_core_files": [item.__dict__ for item in self.startup_core_files],
        }


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeContractError("RUNTIME_MANIFEST_DUPLICATE_KEY")
        result[key] = value
    return result


def has_reparse_point(path: Path) -> bool:
    try:
        return _has_reparse_point(Path(path))
    except PathSafetyError as exc:
        raise RuntimeContractError("RUNTIME_MANIFEST_REPARSE_FORBIDDEN", details={"label": Path(path).name}) from exc


def assert_no_reparse_ancestors(path: Path, *, code: str = "RUNTIME_MANIFEST_REPARSE_FORBIDDEN") -> None:
    try:
        _assert_no_reparse_ancestors(Path(path))
    except PathSafetyError as exc:
        raise RuntimeContractError(code, details={"label": Path(path).name}) from exc


def sha256_file(path: Path, *, max_bytes: int = SINGLE_FILE_HASH_MAX_BYTES) -> tuple[str, int]:
    assert_no_reparse_ancestors(path)
    if not path.is_file() or has_reparse_point(path):
        raise RuntimeContractError("RUNTIME_MANIFEST_REPARSE_FORBIDDEN", details={"label": path.name})
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            if size > max_bytes:
                raise RuntimeContractError("RUNTIME_MANIFEST_HASH_LIMIT_EXCEEDED", details={"label": path.name})
            digest.update(chunk)
    return digest.hexdigest(), size


def normalize_abi(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeContractError("RUNTIME_MANIFEST_ABI_INVALID")
    normalized = value.strip().lower().replace("_", "-")
    if normalized == "cp310":
        return "cp310"
    if normalized == "cpython-310":
        return "cp310"
    raise RuntimeContractError("RUNTIME_MANIFEST_ABI_INVALID", details={"label": value[:32]})


def abi_from_cache_tag(cache_tag: object) -> str:
    return normalize_abi(cache_tag)


def normalize_architecture(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeContractError("RUNTIME_MANIFEST_ARCHITECTURE_INVALID")
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"amd64", "x86_64", "x64"}:
        return "x64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    raise RuntimeContractError("RUNTIME_MANIFEST_ARCHITECTURE_INVALID", details={"label": value[:32]})


def validate_manifest_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > RELATIVE_PATH_MAX_CHARS:
        raise RuntimeContractError("RUNTIME_MANIFEST_PATH_INVALID")
    if "\\" in value or "*" in value or "?" in value or value.startswith(("/", "//", "\\\\")):
        raise RuntimeContractError("RUNTIME_MANIFEST_PATH_INVALID", details={"label": PurePosixPath(value).name[:80]})
    if value.startswith("\\\\?\\") or value.startswith("\\\\.\\"):
        raise RuntimeContractError("RUNTIME_MANIFEST_PATH_INVALID")
    if len(value) >= 2 and value[1] == ":":
        raise RuntimeContractError("RUNTIME_MANIFEST_PATH_INVALID")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeContractError("RUNTIME_MANIFEST_PATH_INVALID")
    for part in path.parts:
        if ":" in part or _WINDOWS_DEVICE_RE.fullmatch(part):
            raise RuntimeContractError("RUNTIME_MANIFEST_PATH_INVALID", details={"label": part[:80]})
    return path.as_posix()


def _load_manifest(path: Path) -> tuple[dict[str, Any], str]:
    assert_no_reparse_ancestors(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise RuntimeContractError("RUNTIME_MANIFEST_MISSING") from exc
    except OSError as exc:
        raise RuntimeContractError("RUNTIME_MANIFEST_READ_FAILED") from exc
    if not raw or len(raw) > MANIFEST_MAX_BYTES:
        raise RuntimeContractError("RUNTIME_MANIFEST_SIZE_INVALID")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise RuntimeContractError("RUNTIME_MANIFEST_BOM_FORBIDDEN")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except UnicodeDecodeError as exc:
        raise RuntimeContractError("RUNTIME_MANIFEST_UTF8_INVALID") from exc
    except RuntimeContractError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeContractError("RUNTIME_MANIFEST_JSON_INVALID") from exc
    if type(payload) is not dict:
        raise RuntimeContractError("RUNTIME_MANIFEST_JSON_INVALID")
    return payload, hashlib.sha256(raw).hexdigest()


def parse_runtime_manifest_startup_view(manifest_path: Path, python_runtime_root: Path) -> RuntimeManifestStartupView:
    manifest_path = Path(manifest_path)
    runtime_root = Path(python_runtime_root)
    assert_no_reparse_ancestors(runtime_root)
    payload, manifest_sha256 = _load_manifest(manifest_path)
    if payload.get("schema_version") != RUNTIME_MANIFEST_SCHEMA:
        raise RuntimeContractError("RUNTIME_MANIFEST_SCHEMA_INVALID")
    architecture = normalize_architecture(payload.get("architecture"))
    architecture_supported = architecture in APPROVED_PORTABLE_ARCHITECTURES
    abi = normalize_abi(payload.get("python_abi"))
    implementation = payload.get("python_implementation")
    version = payload.get("python_version")
    if not isinstance(implementation, str) or implementation.lower() != "cpython":
        raise RuntimeContractError("PYTHON_IDENTITY_IMPLEMENTATION_INVALID")
    if not isinstance(version, str) or _PYTHON_310_VERSION_RE.fullmatch(version) is None:
        raise RuntimeContractError("PYTHON_IDENTITY_VERSION_INVALID")
    records: dict[str, dict[str, Any]] = {}
    core_items = payload.get("core_files")
    if type(core_items) is not list:
        raise RuntimeContractError("RUNTIME_MANIFEST_CORE_MISSING")
    if len(core_items) > STARTUP_CORE_FILE_COUNT_HARD_MAX:
        raise RuntimeContractError("RUNTIME_MANIFEST_CORE_LIMIT_EXCEEDED")
    for item in core_items:
        if type(item) is not dict:
            raise RuntimeContractError("RUNTIME_MANIFEST_CORE_MISSING")
        relative = validate_manifest_relative_path(item.get("filename", item.get("path")))
        normalized = relative.casefold()
        if normalized in records:
            raise RuntimeContractError("RUNTIME_MANIFEST_PATH_DUPLICATE", details={"label": relative})
        records[normalized] = item
    startup_records: list[StartupCoreFile] = []
    total_size = 0
    digest = hashlib.sha256()
    for relative in STARTUP_CORE_FILES:
        item = records.get(relative.casefold())
        if item is None:
            raise RuntimeContractError("RUNTIME_MANIFEST_CORE_MISSING", details={"label": relative})
        declared_sha = item.get("sha256")
        declared_size = item.get("size_bytes")
        if not isinstance(declared_sha, str) or not _SHA_RE.fullmatch(declared_sha):
            raise RuntimeContractError("RUNTIME_MANIFEST_CORE_HASH_MISMATCH", details={"label": relative})
        if type(declared_size) is not int or declared_size < 0:
            raise RuntimeContractError("RUNTIME_MANIFEST_CORE_SIZE_MISMATCH", details={"label": relative})
        actual_path = runtime_root / Path(relative)
        try:
            actual_path = assert_path_within_root(actual_path, runtime_root)
        except PathSafetyError as exc:
            raise RuntimeContractError("RUNTIME_MANIFEST_PATH_INVALID", details={"label": relative}) from exc
        if not actual_path.is_file():
            raise RuntimeContractError("RUNTIME_MANIFEST_CORE_MISSING", details={"label": relative})
        actual_sha, actual_size = sha256_file(actual_path)
        if actual_sha != declared_sha:
            raise RuntimeContractError("RUNTIME_MANIFEST_CORE_HASH_MISMATCH", details={"label": relative})
        if actual_size != declared_size:
            raise RuntimeContractError("RUNTIME_MANIFEST_CORE_SIZE_MISMATCH", details={"label": relative})
        total_size += actual_size
        if total_size > TOTAL_STARTUP_HASH_MAX_BYTES:
            raise RuntimeContractError("RUNTIME_MANIFEST_HASH_LIMIT_EXCEEDED", details={"label": relative})
        record = StartupCoreFile(relative, actual_sha, actual_size)
        startup_records.append(record)
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(actual_size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(actual_sha))
    if "source" not in payload:
        source: dict[str, Any] = {}
    elif type(payload["source"]) is dict:
        source_value = payload["source"]
        source = source_value
    else:
        raise RuntimeContractError("RUNTIME_MANIFEST_METADATA_INVALID")
    enterprise_commit = source.get("enterprise_commit")
    if enterprise_commit is not None and (
        not isinstance(enterprise_commit, str) or re.fullmatch(r"[0-9a-f]{40}", enterprise_commit) is None
    ):
        raise RuntimeContractError("RUNTIME_MANIFEST_METADATA_INVALID")
    candidate_id = payload.get("candidate_id")
    if candidate_id is not None and (not isinstance(candidate_id, str) or _CANDIDATE_ID_RE.fullmatch(candidate_id) is None):
        raise RuntimeContractError("RUNTIME_MANIFEST_METADATA_INVALID")
    view = RuntimeManifestStartupView(
        schema_version=STARTUP_VIEW_SCHEMA,
        manifest_sha256=manifest_sha256,
        python_version=version,
        python_implementation="CPython",
        python_abi=abi,
        architecture=architecture,
        architecture_supported=architecture_supported,
        startup_core_files=tuple(startup_records),
        startup_core_digest=digest.hexdigest(),
        candidate_id=candidate_id,
        manifest_self_declared_enterprise_commit=enterprise_commit,
    )
    if not architecture_supported:
        # The parsed model is valid, but the current formal Windows portable
        # target is x64-only.  Callers must fail preflight with this code.
        return view
    return view
