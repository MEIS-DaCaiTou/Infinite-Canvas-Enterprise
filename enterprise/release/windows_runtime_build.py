"""Reproducible, offline Windows bundled Runtime build primitives for ENV-1B2A.

The module is intentionally release tooling.  It never discovers inputs from
the current working directory, never falls back to PATH Python, and never
grants production approval.  Network acquisition is outside the build/verify
commands; every build consumes explicit, hash-pinned local artifacts.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from enterprise.path_safety import PathSafetyError, assert_no_reparse_ancestors, has_reparse_point
from enterprise.release import runtime_provenance as provenance
from enterprise.release.current_release import (
    SCHEMA_VERSION as CURRENT_RELEASE_SCHEMA,
    CurrentRelease,
    canonical_json as canonical_current_release_json,
)


BUILD_TOOL_VERSION = "env-1b2a-windows-runtime-builder-v1"
PYTHON_SOURCE_SCHEMA = "env-1b2a-python-source-v1"
WHEELHOUSE_LOCK_SCHEMA = provenance.WHEELHOUSE_MANIFEST_SCHEMA
BUILD_POLICY_SCHEMA = "env-1b2a-runtime-build-policy-v1"
INSTALLED_DISTRIBUTIONS_SCHEMA = "env-1b2a-installed-distributions-v1"
SBOM_SCHEMA = "CycloneDX-1.6"
ARCHIVE_INVENTORY_SCHEMA = "env-1b2a-runtime-archive-inventory-v1"
BUILD_SUMMARY_SCHEMA = "env-1b2a-reproducible-build-summary-v1"
B2_FIXTURE_REPORT_SCHEMA = "env-1b2a-real-bundled-python-lifecycle-v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCK_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;]+)"
    r"\s+--hash=sha256:(?P<sha256>[0-9a-f]{64})$"
)
_WINDOWS_DEVICES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
_JSON_LIMIT = 16 * 1024 * 1024
_CHUNK = 1024 * 1024
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_PTH_BYTES = b"python310.zip\r\n.\r\n..\r\nimport site\r\n"


class WindowsRuntimeBuildError(RuntimeError):
    """Stable path-free build failure."""

    def __init__(self, code: str, label: str = "") -> None:
        self.code = code
        self.label = label
        super().__init__(code if not label else f"{code}:{label}")


@dataclass(frozen=True)
class LockedWheel:
    name: str
    version: str
    filename: str
    sha256: str
    size_bytes: int
    python_tags: tuple[str, ...]
    abi_tags: tuple[str, ...]
    platform_tags: tuple[str, ...]
    source_requirement_relation: str


@dataclass(frozen=True)
class BuildInputs:
    source_archive: Path
    source_policy: Path
    requirements_lock: Path
    wheelhouse_lock: Path
    build_policy: Path
    wheelhouse: Path
    bootstrap_wheelhouse: Path
    enterprise_commit: str


@dataclass(frozen=True)
class BuildOutput:
    root: Path
    runtime: Path
    evidence: Path
    archive: Path
    runtime_manifest: Path
    rebuild_attestation: Path
    pip_check_report: Path
    installed_distributions: Path
    wheelhouse_inventory: Path
    sbom: Path
    archive_inventory: Path
    archive_build_record: Path
    provenance_report: Path


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_CHUNK)
                if not chunk:
                    return digest.hexdigest()
                digest.update(chunk)
    except OSError as exc:
        raise WindowsRuntimeBuildError("ARTIFACT_READ_FAILED", path.name) from exc


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WindowsRuntimeBuildError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _load_json(path: Path, schema: str) -> dict[str, Any]:
    _input_file(path, "json")
    try:
        if path.stat().st_size < 1 or path.stat().st_size > _JSON_LIMIT:
            raise WindowsRuntimeBuildError("JSON_SIZE_INVALID", path.name)
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise WindowsRuntimeBuildError("JSON_BOM_FORBIDDEN", path.name)
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs_no_duplicates)
    except WindowsRuntimeBuildError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WindowsRuntimeBuildError("JSON_READ_FAILED", path.name) from exc
    if type(value) is not dict or value.get("schema_version") != schema:
        raise WindowsRuntimeBuildError("JSON_SCHEMA_INVALID", path.name)
    return value


def _assert_safe_path(path: Path, *, allow_missing: bool = False) -> None:
    raw = os.fspath(path)
    lowered = raw.casefold()
    if raw.startswith(("\\\\", "//")) or lowered.startswith(("\\\\?\\", "\\\\.\\")):
        raise WindowsRuntimeBuildError("PATH_SPECIAL_FORBIDDEN")
    try:
        assert_no_reparse_ancestors(path)
        if not allow_missing and has_reparse_point(path):
            raise PathSafetyError("path-reparse-forbidden")
    except (OSError, PathSafetyError) as exc:
        raise WindowsRuntimeBuildError("PATH_REPARSE_FORBIDDEN", path.name) from exc


def _input_file(path: Path | str, label: str) -> Path:
    candidate = Path(path).absolute()
    _assert_safe_path(candidate, allow_missing=True)
    if not candidate.is_file():
        raise WindowsRuntimeBuildError("INPUT_FILE_MISSING", label)
    _assert_safe_path(candidate)
    return candidate.resolve(strict=True)


def _input_directory(path: Path | str, label: str) -> Path:
    candidate = Path(path).absolute()
    _assert_safe_path(candidate, allow_missing=True)
    if not candidate.is_dir():
        raise WindowsRuntimeBuildError("INPUT_DIRECTORY_MISSING", label)
    _assert_safe_path(candidate)
    return candidate.resolve(strict=True)


def _safe_relative(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise WindowsRuntimeBuildError("RELATIVE_PATH_INVALID", label)
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise WindowsRuntimeBuildError("RELATIVE_PATH_INVALID", label)
    for part in pure.parts:
        if ":" in part or any(ord(character) < 32 for character in part):
            raise WindowsRuntimeBuildError("RELATIVE_PATH_INVALID", label)
        base = part.rstrip(" .").split(".", 1)[0].casefold()
        if not part.rstrip(" .") or base in _WINDOWS_DEVICES:
            raise WindowsRuntimeBuildError("RELATIVE_PATH_INVALID", label)
    return pure.as_posix()


def _new_output_root(path: Path | str) -> Path:
    root = Path(path).absolute()
    if not root.parent.is_dir():
        raise WindowsRuntimeBuildError("OUTPUT_PARENT_MISSING", root.name)
    _assert_safe_path(root.parent, allow_missing=False)
    if root.exists() or os.path.lexists(root):
        raise WindowsRuntimeBuildError("OUTPUT_ALREADY_EXISTS", root.name)
    try:
        root.mkdir()
    except OSError as exc:
        raise WindowsRuntimeBuildError("OUTPUT_CREATE_FAILED", root.name) from exc
    _assert_safe_path(root)
    return root


def _write_new(path: Path, content: bytes) -> None:
    _assert_safe_path(path.parent)
    try:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise WindowsRuntimeBuildError("OUTPUT_WRITE_FAILED", path.name) from exc


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    _write_new(path, _canonical_json(payload))


def _replace_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = _canonical_json(payload)
    temporary = path.with_name(path.name + ".new")
    if temporary.exists() or os.path.lexists(temporary):
        raise WindowsRuntimeBuildError("OUTPUT_TEMP_EXISTS", temporary.name)
    try:
        _write_new(temporary, encoded)
        os.replace(temporary, path)
    except OSError as exc:
        raise WindowsRuntimeBuildError("OUTPUT_REPLACE_FAILED", path.name) from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _copy_new(source: Path, target: Path) -> None:
    if target.exists() or os.path.lexists(target):
        raise WindowsRuntimeBuildError("OUTPUT_ALREADY_EXISTS", target.name)
    _assert_safe_path(source)
    try:
        with source.open("rb") as reader, target.open("xb") as writer:
            while True:
                chunk = reader.read(_CHUNK)
                if not chunk:
                    break
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
    except OSError as exc:
        raise WindowsRuntimeBuildError("ARTIFACT_COPY_FAILED", source.name) from exc


def load_source_policy(path: Path | str) -> dict[str, Any]:
    payload = _load_json(Path(path).absolute(), PYTHON_SOURCE_SCHEMA)
    if (
        payload.get("implementation") != "CPython"
        or payload.get("version") != "3.10.11"
        or payload.get("architecture") != "x64"
        or payload.get("python_abi") != "cp310"
        or payload.get("archive_filename") != "python-3.10.11-embed-amd64.zip"
        or not isinstance(payload.get("official_source_url"), str)
        or not str(payload["official_source_url"]).startswith("https://www.python.org/")
        or _SHA256_RE.fullmatch(str(payload.get("sha256", ""))) is None
    ):
        raise WindowsRuntimeBuildError("PYTHON_SOURCE_POLICY_INVALID")
    inventory = payload.get("expected_core_inventory")
    if type(inventory) is not list or len(inventory) != len(provenance.UPSTREAM_CORE_FILES):
        raise WindowsRuntimeBuildError("PYTHON_SOURCE_INVENTORY_INVALID")
    names: set[str] = set()
    for item in inventory:
        if (
            type(item) is not dict
            or _SHA256_RE.fullmatch(str(item.get("sha256", ""))) is None
            or type(item.get("size_bytes")) is not int
            or item["size_bytes"] < 0
        ):
            raise WindowsRuntimeBuildError("PYTHON_SOURCE_INVENTORY_INVALID")
        names.add(_safe_relative(item.get("path"), label="source_core"))
    if names != set(provenance.UPSTREAM_CORE_FILES):
        raise WindowsRuntimeBuildError("PYTHON_SOURCE_INVENTORY_INVALID")
    pth = payload.get("python310_pth_policy")
    if type(pth) is not dict or pth.get("candidate_sha256") != sha256_bytes(_PTH_BYTES):
        raise WindowsRuntimeBuildError("PYTHON_PTH_POLICY_INVALID")
    return payload


def parse_requirements_lock(path: Path | str) -> dict[str, tuple[str, str]]:
    lock = _input_file(path, "requirements_lock")
    try:
        text = lock.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise WindowsRuntimeBuildError("DEPENDENCY_LOCK_READ_FAILED") from exc
    result: dict[str, tuple[str, str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_RE.fullmatch(line)
        if match is None:
            raise WindowsRuntimeBuildError("DEPENDENCY_LOCK_LINE_INVALID")
        name = _normalized_name(match.group("name"))
        if name in result:
            raise WindowsRuntimeBuildError("DEPENDENCY_LOCK_DUPLICATE")
        result[name] = (match.group("version"), match.group("sha256"))
    if not result:
        raise WindowsRuntimeBuildError("DEPENDENCY_LOCK_EMPTY")
    return dict(sorted(result.items()))


def load_wheelhouse_lock(path: Path | str) -> tuple[dict[str, Any], dict[str, LockedWheel]]:
    payload = _load_json(Path(path).absolute(), WHEELHOUSE_LOCK_SCHEMA)
    if payload.get("target_python_abi") != "cp310" or payload.get("target_platform") != "win_amd64":
        raise WindowsRuntimeBuildError("WHEELHOUSE_TARGET_INVALID")
    values = payload.get("wheels")
    if type(values) is not list or payload.get("wheel_count") != len(values) or payload.get("invalid_wheel_count") != 0:
        raise WindowsRuntimeBuildError("WHEELHOUSE_LOCK_INVALID")
    result: dict[str, LockedWheel] = {}
    filenames: set[str] = set()
    for item in values:
        if type(item) is not dict:
            raise WindowsRuntimeBuildError("WHEELHOUSE_RECORD_INVALID")
        filename = _safe_relative(item.get("filename"), label="wheel")
        name = _normalized_name(str(item.get("package", "")))
        version = item.get("version")
        digest = item.get("sha256")
        size = item.get("size_bytes")
        relation = item.get("source_requirement_relation")
        python_tags = item.get("python_tags")
        abi_tags = item.get("abi_tags")
        platform_tags = item.get("platform_tags")
        if (
            "/" in filename
            or not filename.endswith(".whl")
            or not name
            or name in result
            or filename in filenames
            or not isinstance(version, str)
            or _SHA256_RE.fullmatch(str(digest or "")) is None
            or type(size) is not int
            or size < 1
            or not isinstance(relation, str)
            or not relation
            or not all(type(tags) is list and tags and all(isinstance(tag, str) and tag for tag in tags) for tags in (python_tags, abi_tags, platform_tags))
            or item.get("compatible_with_cpython_310_win_amd64") is not True
            or not provenance._wheel_is_cp310_win_amd64(filename)
        ):
            raise WindowsRuntimeBuildError("WHEELHOUSE_RECORD_INVALID")
        result[name] = LockedWheel(
            name=name,
            version=version,
            filename=filename,
            sha256=str(digest),
            size_bytes=size,
            python_tags=tuple(python_tags),
            abi_tags=tuple(abi_tags),
            platform_tags=tuple(platform_tags),
            source_requirement_relation=relation,
        )
        filenames.add(filename)
    return payload, dict(sorted(result.items()))


def load_build_policy(path: Path | str) -> dict[str, Any]:
    payload = _load_json(Path(path).absolute(), BUILD_POLICY_SCHEMA)
    if (
        payload.get("build_tool_version") != BUILD_TOOL_VERSION
        or payload.get("bootstrap_distribution_allowlist") != sorted(provenance.BOOTSTRAP_DISTRIBUTION_ALLOWLIST)
        or payload.get("archive_root_prefix") != "runtime"
        or payload.get("zip_timestamp") != list(_ZIP_TIMESTAMP)
        or payload.get("ignored_nondeterministic_fields") != []
        or payload.get("console_scripts_policy") != "omit-and-normalize-wheel-records"
    ):
        raise WindowsRuntimeBuildError("BUILD_POLICY_INVALID")
    bootstrap = payload.get("bootstrap_wheels")
    if type(bootstrap) is not list or {_normalized_name(str(item.get("package", ""))) for item in bootstrap if type(item) is dict} != provenance.BOOTSTRAP_DISTRIBUTION_ALLOWLIST:
        raise WindowsRuntimeBuildError("BOOTSTRAP_POLICY_INVALID")
    for item in bootstrap:
        if (
            type(item) is not dict
            or not isinstance(item.get("filename"), str)
            or _SHA256_RE.fullmatch(str(item.get("sha256", ""))) is None
            or type(item.get("size_bytes")) is not int
        ):
            raise WindowsRuntimeBuildError("BOOTSTRAP_POLICY_INVALID")
    return payload


def validate_inputs(inputs: BuildInputs) -> tuple[dict[str, Any], dict[str, Any], dict[str, LockedWheel], dict[str, Any]]:
    source = load_source_policy(inputs.source_policy)
    wheel_payload, wheels = load_wheelhouse_lock(inputs.wheelhouse_lock)
    lock = parse_requirements_lock(inputs.requirements_lock)
    policy = load_build_policy(inputs.build_policy)
    source_archive = _input_file(inputs.source_archive, "python_source")
    if source_archive.name != source["archive_filename"] or sha256_file(source_archive) != source["sha256"] or source_archive.stat().st_size != source["size_bytes"]:
        raise WindowsRuntimeBuildError("PYTHON_SOURCE_HASH_MISMATCH")
    _verify_source_inventory(source_archive, source)
    expected_lock = {name: (wheel.version, wheel.sha256) for name, wheel in wheels.items()}
    if lock != expected_lock:
        raise WindowsRuntimeBuildError("LOCK_WHEELHOUSE_CLOSURE_INVALID")
    if not re.fullmatch(r"[0-9a-f]{40}", inputs.enterprise_commit):
        raise WindowsRuntimeBuildError("ENTERPRISE_COMMIT_INVALID")
    _input_directory(inputs.wheelhouse, "wheelhouse")
    _input_directory(inputs.bootstrap_wheelhouse, "bootstrap_wheelhouse")
    _verify_wheel_files(inputs.wheelhouse, wheels)
    _verify_bootstrap_files(inputs.bootstrap_wheelhouse, policy)
    return source, wheel_payload, wheels, policy


def _verify_source_inventory(path: Path, policy: Mapping[str, Any]) -> None:
    records, _ = provenance._zip_inventory(path)
    expected = {
        str(item["path"]): provenance.FileRecord(str(item["path"]), str(item["sha256"]), int(item["size_bytes"]))
        for item in policy["expected_core_inventory"]
    }
    if records != expected:
        raise WindowsRuntimeBuildError("PYTHON_SOURCE_INVENTORY_MISMATCH")


def _verify_wheel_files(root: Path, wheels: Mapping[str, LockedWheel]) -> None:
    root = _input_directory(root, "wheelhouse")
    files = sorted(path for path in root.iterdir() if path.is_file())
    if {path.name for path in files} != {wheel.filename for wheel in wheels.values()} or any(path.is_symlink() for path in files):
        raise WindowsRuntimeBuildError("WHEELHOUSE_CLOSURE_INVALID")
    by_filename = {wheel.filename: wheel for wheel in wheels.values()}
    for path in files:
        wheel = by_filename[path.name]
        if path.stat().st_size != wheel.size_bytes or sha256_file(path) != wheel.sha256:
            raise WindowsRuntimeBuildError("WHEEL_HASH_MISMATCH", path.name)


def _verify_bootstrap_files(root: Path, policy: Mapping[str, Any]) -> None:
    root = _input_directory(root, "bootstrap_wheelhouse")
    expected = {str(item["filename"]): item for item in policy["bootstrap_wheels"]}
    files = sorted(path for path in root.iterdir() if path.is_file())
    if {path.name for path in files} != set(expected):
        raise WindowsRuntimeBuildError("BOOTSTRAP_WHEELHOUSE_CLOSURE_INVALID")
    for path in files:
        item = expected[path.name]
        if path.stat().st_size != item["size_bytes"] or sha256_file(path) != item["sha256"]:
            raise WindowsRuntimeBuildError("BOOTSTRAP_WHEEL_HASH_MISMATCH", path.name)


def prepare_sources(*, source_archive: Path, source_policy: Path, output: Path) -> Path:
    policy = load_source_policy(source_policy)
    source = _input_file(source_archive, "python_source")
    if source.name != policy["archive_filename"] or sha256_file(source) != policy["sha256"]:
        raise WindowsRuntimeBuildError("PYTHON_SOURCE_HASH_MISMATCH")
    _verify_source_inventory(source, policy)
    root = _new_output_root(output)
    target = root / source.name
    _copy_new(source, target)
    _write_json(root / "source-verification.json", {
        "archive_filename": source.name,
        "architecture": "x64",
        "implementation": "CPython",
        "schema_version": "env-1b2a-source-verification-v1",
        "sha256": sha256_file(target),
        "size_bytes": target.stat().st_size,
        "version": "3.10.11",
    })
    return target


def prepare_wheelhouse(
    *,
    seed_wheelhouse: Path,
    seed_bootstrap_wheelhouse: Path,
    wheelhouse_lock: Path,
    build_policy: Path,
    output: Path,
) -> tuple[Path, Path]:
    _payload, wheels = load_wheelhouse_lock(wheelhouse_lock)
    policy = load_build_policy(build_policy)
    _verify_wheel_files(seed_wheelhouse, wheels)
    _verify_bootstrap_files(seed_bootstrap_wheelhouse, policy)
    root = _new_output_root(output)
    application = root / "application"
    bootstrap = root / "bootstrap"
    application.mkdir()
    bootstrap.mkdir()
    for wheel in sorted(wheels.values(), key=lambda item: item.filename):
        _copy_new(Path(seed_wheelhouse) / wheel.filename, application / wheel.filename)
    for item in sorted(policy["bootstrap_wheels"], key=lambda value: value["filename"]):
        _copy_new(Path(seed_bootstrap_wheelhouse) / item["filename"], bootstrap / item["filename"])
    _verify_wheel_files(application, wheels)
    _verify_bootstrap_files(bootstrap, policy)
    return application, bootstrap


def _zip_safe_entries(path: Path) -> list[zipfile.ZipInfo]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            normalized: set[str] = set()
            for info in infos:
                name = info.filename.rstrip("/")
                if not name:
                    continue
                relative = _safe_relative(name, label="zip_entry")
                folded = relative.casefold()
                if folded in normalized:
                    raise WindowsRuntimeBuildError("ZIP_DUPLICATE_PATH")
                normalized.add(folded)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(mode) == stat.S_IFLNK or info.flag_bits & 0x1:
                    raise WindowsRuntimeBuildError("ZIP_ENTRY_UNSAFE")
            return infos
    except WindowsRuntimeBuildError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise WindowsRuntimeBuildError("ZIP_READ_FAILED", path.name) from exc


def _extract_zip(path: Path, target: Path, *, expected_names: set[str] | None = None) -> None:
    infos = _zip_safe_entries(path)
    names = {info.filename.rstrip("/") for info in infos if info.filename.rstrip("/")}
    if expected_names is not None and names != expected_names:
        raise WindowsRuntimeBuildError("PYTHON_SOURCE_INVENTORY_MISMATCH")
    with zipfile.ZipFile(path, "r") as archive:
        for info in sorted(infos, key=lambda item: item.filename):
            name = info.filename.rstrip("/")
            if not name or info.is_dir():
                continue
            relative = _safe_relative(name, label="zip_entry")
            destination = target.joinpath(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or os.path.lexists(destination):
                raise WindowsRuntimeBuildError("ZIP_TARGET_COLLISION", destination.name)
            try:
                with archive.open(info, "r") as reader, destination.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, length=_CHUNK)
            except OSError as exc:
                raise WindowsRuntimeBuildError("ZIP_EXTRACT_FAILED", path.name) from exc


def _install_bootstrap(runtime: Path, bootstrap_root: Path, policy: Mapping[str, Any]) -> None:
    site_packages = runtime / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    for item in sorted(policy["bootstrap_wheels"], key=lambda value: value["filename"]):
        wheel = bootstrap_root / item["filename"]
        _extract_zip(wheel, site_packages)


def _strip_console_scripts(site_packages: Path) -> None:
    """Remove path-bearing pip launchers and their RECORD rows deterministically.

    The application imports modules directly and the formal entrypoint is the
    repository launcher, so distribution console scripts are not part of the
    bundled Runtime contract.  Pip's Windows launchers embed the absolute
    build interpreter path; retaining them would make clean build roots differ.
    """

    scripts = site_packages / "bin"
    if scripts.exists():
        _assert_safe_path(scripts)
        for item in sorted(scripts.iterdir(), key=lambda value: value.name):
            if not item.is_file() or item.is_symlink():
                raise WindowsRuntimeBuildError("CONSOLE_SCRIPT_ENTRY_INVALID")
            item.unlink()
        scripts.rmdir()
    for record in sorted(site_packages.glob("*.dist-info/RECORD"), key=lambda value: value.as_posix()):
        try:
            rows = list(csv.reader(io.StringIO(record.read_text(encoding="utf-8", errors="strict"))))
        except (OSError, UnicodeError, csv.Error) as exc:
            raise WindowsRuntimeBuildError("WHEEL_RECORD_READ_FAILED") from exc
        filtered = [
            row for row in rows
            if row and not row[0].replace("\\", "/").startswith("../../bin/")
        ]
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerows(filtered)
        try:
            record.write_text(buffer.getvalue(), encoding="utf-8", newline="")
        except OSError as exc:
            raise WindowsRuntimeBuildError("WHEEL_RECORD_WRITE_FAILED") from exc


def _clean_environment(runtime: Path) -> dict[str, str]:
    result = {
        "PATH": str(runtime),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_CACHE_DIR": "1",
    }
    for name in (
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_ARCHITEW6432",
    ):
        value = os.environ.get(name)
        if value:
            result[name] = value
    return result


def _run_fixed_python(
    runtime: Path,
    arguments: Sequence[str],
    *,
    timeout: int = 180,
    cwd: Path | None = None,
    extra_environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    executable = runtime / "python.exe"
    environment = _clean_environment(runtime)
    if extra_environment:
        for name, value in extra_environment.items():
            if not isinstance(name, str) or not name.startswith("ICE_B2_FIXTURE_") or not isinstance(value, str):
                raise WindowsRuntimeBuildError("FIXTURE_ENVIRONMENT_INVALID")
            environment[name] = value
    try:
        return subprocess.run(
            [str(executable), *arguments],
            cwd=str(runtime if cwd is None else cwd),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise WindowsRuntimeBuildError("FIXED_PYTHON_EXECUTION_FAILED") from exc


def _copy_tree_exact(source: Path, target: Path) -> tuple[int, int, str]:
    source = _input_directory(source, "tree_source")
    if target.exists() or os.path.lexists(target):
        raise WindowsRuntimeBuildError("OUTPUT_ALREADY_EXISTS", target.name)
    target.mkdir()
    records, digest, size = provenance._tree_inventory(source)
    for relative in sorted(records):
        source_file = source.joinpath(*PurePosixPath(relative).parts)
        target_file = target.joinpath(*PurePosixPath(relative).parts)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        _copy_new(source_file, target_file)
    copied_records, copied_digest, copied_size = provenance._tree_inventory(target)
    if copied_records != records or copied_digest != digest or copied_size != size:
        raise WindowsRuntimeBuildError("TREE_COPY_MISMATCH", target.name)
    return len(records), size, digest


def _fixture_sitecustomize() -> bytes:
    return (
        "import json\n"
        "import os\n"
        "from pathlib import Path\n"
        "from enterprise.runtime import portable as _portable\n"
        "_original_validate = _portable.validate_portable_process_binding\n"
        "def _fixture_validate(**kwargs):\n"
        "    kwargs.pop('local_app_data_resolver', None)\n"
        "    base = Path(os.environ['ICE_B2_FIXTURE_LOCAL_BASE'])\n"
        "    return _original_validate(local_app_data_resolver=lambda: base, **kwargs)\n"
        "_portable.validate_portable_process_binding = _fixture_validate\n"
        "from enterprise.runtime import cli as _runtime_cli\n"
        "_original_cli_main = _runtime_cli.main\n"
        "def _fixture_cli_main(argv=None):\n"
        "    try:\n"
        "        return _original_cli_main(argv)\n"
        "    except BaseException as exc:\n"
        "        diagnostic = Path(os.environ['ICE_B2_FIXTURE_DIAGNOSTIC'])\n"
        "        diagnostic.write_text(json.dumps({'code':str(getattr(exc,'code',type(exc).__name__))[:64]},sort_keys=True),encoding='utf-8')\n"
        "        raise\n"
        "_runtime_cli.main = _fixture_cli_main\n"
    ).encode("utf-8")


def _run_wrapper_bootstrap_fixture(app_root: Path, different_cwd: Path) -> dict[str, object]:
    wrapper = app_root / "查看企业版状态.bat"
    if not wrapper.is_file():
        raise WindowsRuntimeBuildError("FIXTURE_WRAPPER_MISSING")
    comspec = os.environ.get("COMSPEC")
    if os.name != "nt" or not comspec:
        raise WindowsRuntimeBuildError("FIXTURE_WINDOWS_REQUIRED")
    environment = _clean_environment(app_root / "python")
    environment.update(
        {
            "PYTHONHOME": str(different_cwd / "polluted-home"),
            "PYTHONPATH": str(different_cwd / "polluted-path"),
        }
    )
    try:
        completed = subprocess.run(
            [comspec, "/d", "/s", "/c", str(wrapper)],
            cwd=str(different_cwd),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise WindowsRuntimeBuildError("FIXTURE_WRAPPER_EXECUTION_FAILED") from exc
    output_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 2 or output_lines != ['{"code":"CURRENT_RELEASE_MISSING","status":"blocked"}']:
        raise WindowsRuntimeBuildError("FIXTURE_WRAPPER_CONTRACT_FAILED")
    return {
        "different_cwd_verified": True,
        "environment_pollution_rejected": True,
        "exit_code": completed.returncode,
        "fixed_python_only": True,
        "stable_error_code": "CURRENT_RELEASE_MISSING",
        "unicode_and_space_path_verified": True,
    }


def verify_b2_fixture(
    *,
    runtime: Path,
    runtime_manifest: Path,
    app_source_archive: Path,
    output: Path,
) -> dict[str, object]:
    """Exercise the B2 lifecycle with the real built Runtime and fixture children.

    The fixture uses an external, test-only local-root injection so no real
    LocalAppData Runtime state is read or changed.  The production launcher,
    controller, host, supervisor, child process construction, lock, state, and
    launch-context implementations are reused unchanged.
    """

    runtime = _input_directory(runtime, "runtime")
    manifest = _input_file(runtime_manifest, "runtime_manifest")
    source_archive = _input_file(app_source_archive, "app_source_archive")
    root = _new_output_root(output)
    install_root = root / "fixture-install"
    app_root = install_root / "releases" / "env-1b2a-fixture"
    local_base = root / "fixture-local-app-data"
    different_cwd = root / "Unicode 路径 with spaces"
    app_root.mkdir(parents=True)
    local_base.mkdir()
    different_cwd.mkdir()
    _extract_zip(source_archive, app_root)
    runtime_count, runtime_size, runtime_digest = _copy_tree_exact(runtime, app_root / "python")
    _copy_new(manifest, app_root / "runtime-manifest.json")

    wrapper_result = _run_wrapper_bootstrap_fixture(app_root, different_cwd)

    for directory in (
        install_root / "config",
        install_root / "data" / "uploads",
        install_root / "logs",
        install_root / "backups",
        install_root / "state",
        install_root / "staging",
        local_base / "InfiniteCanvasEnterprise" / "runtime",
        local_base / "Infinite-Canvas-Enterprise" / "cache",
        local_base / "Infinite-Canvas-Enterprise" / "temp",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    current_release = CurrentRelease(
        schema_version=CURRENT_RELEASE_SCHEMA,
        release_id="env-1b2a-fixture",
        app_root_relative="releases/env-1b2a-fixture",
        manifest_sha256=sha256_file(manifest),
        activated_at="2026-07-28T00:00:00Z",
        previous_release_id=None,
    )
    _write_new(install_root / "state" / "current-release.json", canonical_current_release_json(current_release))
    sitecustomize = app_root / "sitecustomize.py"
    host_diagnostic = root / "host-diagnostic.json"
    _write_new(sitecustomize, _fixture_sitecustomize())
    completed: subprocess.CompletedProcess[str] | None = None
    try:
        completed = _run_fixed_python(
            app_root / "python",
            [
                "-I",
                "-B",
                str(app_root / "enterprise" / "tests" / "runtime_fixture_portable_harness.py"),
                "--app-root",
                str(app_root),
                "--local-base",
                str(local_base),
            ],
            timeout=150,
            cwd=different_cwd,
            extra_environment={
                "ICE_B2_FIXTURE_DIAGNOSTIC": str(host_diagnostic),
                "ICE_B2_FIXTURE_LOCAL_BASE": str(local_base),
            },
        )
    finally:
        try:
            sitecustomize.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise WindowsRuntimeBuildError("FIXTURE_HOOK_CLEANUP_FAILED") from exc
    if completed is None or len(completed.stdout.encode("utf-8")) > 64 * 1024:
        raise WindowsRuntimeBuildError("B2_FIXTURE_LIFECYCLE_FAILED")
    try:
        lifecycle = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WindowsRuntimeBuildError("B2_FIXTURE_REPORT_INVALID") from exc
    if (
        completed.returncode != 0
        or type(lifecycle) is not dict
        or lifecycle.get("result") != "pass"
        or lifecycle.get("schema_version") != B2_FIXTURE_REPORT_SCHEMA
    ):
        label = lifecycle.get("error_code", "fixture_failed") if type(lifecycle) is dict else "fixture_failed"
        if host_diagnostic.is_file() and host_diagnostic.stat().st_size <= 1024:
            try:
                diagnostic = json.loads(host_diagnostic.read_text(encoding="utf-8", errors="strict"))
                if type(diagnostic) is dict and isinstance(diagnostic.get("code"), str):
                    label = diagnostic["code"]
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
        raise WindowsRuntimeBuildError("B2_FIXTURE_LIFECYCLE_FAILED", str(label)[:64])
    after_records, after_digest, after_size = provenance._tree_inventory(app_root / "python")
    if len(after_records) != runtime_count or after_size != runtime_size or after_digest != runtime_digest:
        raise WindowsRuntimeBuildError("B2_FIXTURE_RUNTIME_CHANGED")
    report = {
        "app_source_archive_sha256": sha256_file(source_archive),
        "fixed_release_python_real_start_chain_verified": True,
        "fixture_child_wrapper": True,
        "fixture_only_local_root_injection": True,
        "lifecycle": lifecycle,
        "production_approved": False,
        "production_data_accessed": False,
        "provider_accessed": False,
        "real_bundled_python_fixture_tests": True,
        "result": "pass",
        "runtime_file_count": runtime_count,
        "runtime_size_bytes": runtime_size,
        "runtime_tree_sha256_after": after_digest,
        "runtime_tree_sha256_before": runtime_digest,
        "runtime_tree_unchanged": True,
        "schema_version": B2_FIXTURE_REPORT_SCHEMA,
        "temporary_business_test_environment_accessed": False,
        "wrapper_bootstrap": wrapper_result,
    }
    _write_json(root / "b2-real-bundled-python-fixture-report.json", report)
    return report


def _probe_installed(runtime: Path) -> tuple[dict[str, object], list[dict[str, str]]]:
    script = (
        "import importlib.metadata,json,platform,struct,sys,sysconfig;"
        "d=[];"
        "[(d.append({'name':x.metadata.get('Name') or '', 'version':x.version})) for x in importlib.metadata.distributions()];"
        "print(json.dumps({'implementation':platform.python_implementation(),'version':platform.python_version(),"
        "'cache_tag':sys.implementation.cache_tag,'architecture':platform.machine(),'pointer_bits':struct.calcsize('P')*8,"
        "'executable_basename':__import__('os').path.basename(sys.executable),'soabi':sysconfig.get_config_var('SOABI'),"
        "'distributions':sorted(d,key=lambda x:((x['name'] or '').lower(),x['version']))},sort_keys=True,separators=(',',':')))"
    )
    completed = _run_fixed_python(runtime, ["-I", "-B", "-c", script], timeout=30)
    if completed.returncode != 0 or len(completed.stdout.encode("utf-8")) > 256 * 1024:
        raise WindowsRuntimeBuildError("FIXED_PYTHON_PROBE_FAILED")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WindowsRuntimeBuildError("FIXED_PYTHON_PROBE_INVALID") from exc
    distributions = payload.get("distributions")
    if type(payload) is not dict or type(distributions) is not list:
        raise WindowsRuntimeBuildError("FIXED_PYTHON_PROBE_INVALID")
    return payload, distributions


def _wheel_metadata(path: Path) -> tuple[str | None, list[str]]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                return None, []
            message = BytesParser(policy=compat32).parsebytes(archive.read(names[0]))
            license_value = message.get("License")
            classifiers = [value for value in message.get_all("Classifier", []) if value.startswith("License ::")]
            return (str(license_value).strip() if license_value else None), sorted(classifiers)
    except (OSError, zipfile.BadZipFile):
        return None, []


def _build_sbom(
    *,
    wheels: Mapping[str, LockedWheel],
    wheelhouse: Path,
    installed: Mapping[str, str],
    runtime_digest: str,
    input_hashes: Mapping[str, str],
    bootstrap_policy: Mapping[str, Any],
) -> dict[str, object]:
    components: list[dict[str, object]] = [
        {
            "bom-ref": "pkg:generic/cpython@3.10.11?arch=x64",
            "name": "CPython",
            "properties": [{"name": "runtime_tree_sha256", "value": runtime_digest}],
            "type": "framework",
            "version": "3.10.11",
        }
    ]
    bootstrap = {
        _normalized_name(str(item["package"])): item
        for item in bootstrap_policy["bootstrap_wheels"]
    }
    for name in sorted(installed):
        wheel = wheels.get(name)
        component: dict[str, object] = {
            "bom-ref": f"pkg:pypi/{name}@{installed[name]}",
            "name": name,
            "type": "library",
            "version": installed[name],
        }
        if wheel is not None:
            license_value, classifiers = _wheel_metadata(wheelhouse / wheel.filename)
            component["hashes"] = [{"alg": "SHA-256", "content": wheel.sha256}]
            if license_value or classifiers:
                component["licenses"] = [
                    {"license": {"name": value}}
                    for value in ([license_value] if license_value else classifiers)
                ]
            component["properties"] = [
                {"name": "source_requirement_relation", "value": wheel.source_requirement_relation}
            ]
        elif name in bootstrap:
            component["hashes"] = [{"alg": "SHA-256", "content": bootstrap[name]["sha256"]}]
            component["properties"] = [
                {"name": "source_requirement_relation", "value": "bootstrap-fixed-allowlist"}
            ]
        components.append(component)
    dependencies = [{"ref": "runtime", "dependsOn": [component["bom-ref"] for component in components]}] + [
        {"ref": component["bom-ref"], "dependsOn": []}
        for component in components
    ]
    return {
        "bomFormat": "CycloneDX",
        "components": components,
        "dependencies": dependencies,
        "metadata": {
            "component": {"bom-ref": "runtime", "name": "Infinite Canvas Enterprise bundled Python", "type": "application"},
            "properties": [{"name": name, "value": value} for name, value in sorted(input_hashes.items())],
        },
        "serialNumber": "urn:uuid:00000000-0000-0000-0000-000000000000",
        "specVersion": "1.6",
        "version": 1,
    }


def _records_payload(records: Mapping[str, provenance.FileRecord]) -> list[dict[str, object]]:
    return [
        {"path": name, "sha256": records[name].sha256, "size_bytes": records[name].size_bytes}
        for name in sorted(records)
    ]


def _output_layout(root: Path) -> BuildOutput:
    evidence = root / "evidence"
    archive_root = root / "archive"
    runtime = root / "runtime"
    for directory in (evidence, archive_root, runtime):
        directory.mkdir()
    return BuildOutput(
        root=root,
        runtime=runtime,
        evidence=evidence,
        archive=archive_root / "python-runtime.zip",
        runtime_manifest=evidence / "runtime-manifest.json",
        rebuild_attestation=evidence / "dependency-rebuild-attestation.json",
        pip_check_report=evidence / "pip-check-report.json",
        installed_distributions=evidence / "installed-distributions.json",
        wheelhouse_inventory=evidence / "wheelhouse-inventory.json",
        sbom=evidence / "runtime-sbom.cdx.json",
        archive_inventory=evidence / "runtime-archive-inventory.json",
        archive_build_record=evidence / "runtime-archive-build-record.json",
        provenance_report=evidence / "runtime-archive-provenance-report.json",
    )


def build_runtime(inputs: BuildInputs, output_root: Path | str) -> BuildOutput:
    source, wheel_payload, wheels, policy = validate_inputs(inputs)
    root = _new_output_root(output_root)
    output = _output_layout(root)
    _extract_zip(inputs.source_archive, output.runtime, expected_names=set(provenance.UPSTREAM_CORE_FILES))
    original_pth = output.runtime / "python310._pth"
    if sha256_file(original_pth) != source["python310_pth_policy"]["original_sha256"]:
        raise WindowsRuntimeBuildError("PYTHON_PTH_SOURCE_MISMATCH")
    try:
        original_pth.write_bytes(_PTH_BYTES)
    except OSError as exc:
        raise WindowsRuntimeBuildError("PYTHON_PTH_WRITE_FAILED") from exc
    _install_bootstrap(output.runtime, inputs.bootstrap_wheelhouse, policy)
    install = _run_fixed_python(
        output.runtime,
        [
            "-I", "-B", "-m", "pip", "--isolated", "install",
            "--disable-pip-version-check", "--no-index", "--no-compile", "--only-binary=:all:",
            "--find-links", str(inputs.wheelhouse), "--require-hashes",
            "--target", str(output.runtime / "Lib" / "site-packages"),
            "-r", str(inputs.requirements_lock),
        ],
        timeout=600,
    )
    if install.returncode != 0:
        raise WindowsRuntimeBuildError("OFFLINE_INSTALL_FAILED")
    _strip_console_scripts(output.runtime / "Lib" / "site-packages")
    probe, distribution_items = _probe_installed(output.runtime)
    installed: dict[str, str] = {}
    for item in distribution_items:
        name = _normalized_name(str(item.get("name", "")))
        version = str(item.get("version", ""))
        if not name or not version or name in installed:
            raise WindowsRuntimeBuildError("INSTALLED_DISTRIBUTIONS_INVALID")
        installed[name] = version
    expected = {name: wheel.version for name, wheel in wheels.items()}
    extras = set(installed) - set(expected)
    if (
        any(installed.get(name) != version for name, version in expected.items())
        or set(expected) - set(installed)
        or extras != provenance.BOOTSTRAP_DISTRIBUTION_ALLOWLIST
    ):
        raise WindowsRuntimeBuildError("INSTALLED_CLOSURE_MISMATCH")
    pip_check = _run_fixed_python(output.runtime, ["-I", "-B", "-m", "pip", "check"], timeout=120)
    if pip_check.returncode != 0:
        raise WindowsRuntimeBuildError("PIP_CHECK_FAILED")
    runtime_records, runtime_digest, runtime_size = provenance._tree_inventory(output.runtime)
    wheel_records, wheel_digest, wheel_size = provenance._tree_inventory(inputs.wheelhouse)
    wheel_inventory = dict(wheel_payload)
    wheel_inventory["tree_sha256"] = wheel_digest
    wheel_inventory["tree_size_bytes"] = wheel_size
    _write_json(output.wheelhouse_inventory, wheel_inventory)
    lock_sha = sha256_file(inputs.requirements_lock)
    wheel_inventory_sha = sha256_file(output.wheelhouse_inventory)
    input_hashes = {
        "build_policy_sha256": sha256_file(inputs.build_policy),
        "python_source_sha256": sha256_file(inputs.source_archive),
        "requirements_lock_sha256": lock_sha,
        "wheelhouse_inventory_sha256": wheel_inventory_sha,
    }
    installed_digest = provenance._installed_closure_digest(installed)
    common = {
        "dependency_lock_sha256": lock_sha,
        "enterprise_commit": inputs.enterprise_commit,
        "installed_closure_sha256": installed_digest,
        "python_abi": "cp310",
        "python_version": "3.10.11",
        "runtime_tree_sha256": runtime_digest,
        "upstream_commit": provenance.FIXED_UPSTREAM_COMMIT,
        "wheelhouse_manifest_sha256": wheel_inventory_sha,
        "wheelhouse_tree_sha256": wheel_digest,
    }
    rebuild = {
        **common,
        **input_hashes,
        "architecture": "x64",
        "build_tool_version": BUILD_TOOL_VERSION,
        "exit_code": 0,
        "network_download_count": 0,
        "python_executable_sha256": sha256_file(output.runtime / "python.exe"),
        "python_implementation": "CPython",
        "rebuild_command_classification": "offline-locked-wheelhouse",
        "result": "pass",
        "schema_version": provenance.DEPENDENCY_REBUILD_ATTESTATION_SCHEMA,
    }
    pip_report = {
        **common,
        "broken_requirements": [],
        "command_identity": "python-minus-m-pip-check",
        "exit_code": pip_check.returncode,
        "result": "pass",
        "schema_version": provenance.PIP_CHECK_REPORT_SCHEMA,
        "stdout_classification": "no-broken-requirements",
    }
    _write_json(output.rebuild_attestation, rebuild)
    _write_json(output.pip_check_report, pip_report)
    _write_json(output.installed_distributions, {
        "distributions": [{"name": name, "version": installed[name]} for name in sorted(installed)],
        "installed_closure_sha256": installed_digest,
        "python_executable_sha256": sha256_file(output.runtime / "python.exe"),
        "runtime_tree_sha256": runtime_digest,
        "schema_version": INSTALLED_DISTRIBUTIONS_SCHEMA,
    })
    sbom = _build_sbom(
        wheels=wheels,
        wheelhouse=inputs.wheelhouse,
        installed=installed,
        runtime_digest=runtime_digest,
        input_hashes=input_hashes,
        bootstrap_policy=policy,
    )
    _write_json(output.sbom, sbom)
    core_files = [
        {
            "filename": name,
            "sha256": runtime_records[name].sha256,
            "size_bytes": runtime_records[name].size_bytes,
        }
        for name in ("python.exe", "pythonw.exe", "python310.dll", "python310.zip", "python310._pth")
    ]
    manifest = {
        "architecture": "x64",
        "core_files": core_files,
        "dependency_lock": {
            "filename": inputs.requirements_lock.name,
            "invalid_wheel_count": 0,
            "pip_check_report_filename": output.pip_check_report.name,
            "pip_check_report_sha256": sha256_file(output.pip_check_report),
            "rebuild_attestation_filename": output.rebuild_attestation.name,
            "rebuild_attestation_sha256": sha256_file(output.rebuild_attestation),
            "sha256": lock_sha,
            "wheel_count": len(wheels),
            "wheelhouse_manifest_filename": output.wheelhouse_inventory.name,
            "wheelhouse_manifest_sha256": wheel_inventory_sha,
        },
        "embedded_pth": {
            "candidate_sha256": sha256_bytes(_PTH_BYTES),
            "import_site_enabled": True,
            "original_sha256": source["python310_pth_policy"]["original_sha256"],
            "relative_app_root_entry": "..",
        },
        "files": _records_payload(runtime_records),
        "files_summary": {"runtime_file_count": len(runtime_records), "runtime_size_bytes": runtime_size},
        "python_abi": "cp310",
        "python_implementation": "CPython",
        "python_version": "3.10.11",
        "schema_version": provenance.RUNTIME_MANIFEST_SCHEMA,
        "source": {
            "enterprise_commit": inputs.enterprise_commit,
            "upstream_commit": provenance.FIXED_UPSTREAM_COMMIT,
            "upstream_repository": provenance.FIXED_UPSTREAM_REPOSITORY,
            "upstream_version": provenance.FIXED_UPSTREAM_VERSION,
        },
        "source_python_zip": {
            "official_source_url": source["official_source_url"],
            "provenance_verified": True,
            "sha256": source["sha256"],
            "size_bytes": source["size_bytes"],
        },
    }
    _write_json(output.runtime_manifest, manifest)
    return output


def _deterministic_archive(runtime: Path, target: Path) -> tuple[dict[str, provenance.FileRecord], str]:
    records, _digest, _size = provenance._tree_inventory(runtime)
    try:
        with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as archive:
            for relative in sorted(records):
                info = zipfile.ZipInfo(f"runtime/{relative}", date_time=_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (0o100644 & 0xFFFF) << 16
                with (runtime / Path(relative)).open("rb") as reader, archive.open(info, "w", force_zip64=True) as writer:
                    shutil.copyfileobj(reader, writer, length=_CHUNK)
    except (OSError, zipfile.BadZipFile) as exc:
        raise WindowsRuntimeBuildError("ARCHIVE_BUILD_FAILED") from exc
    archive_records, _ = provenance._zip_inventory(target)
    expected = {f"runtime/{name}" for name in records}
    if set(archive_records) != expected:
        raise WindowsRuntimeBuildError("ARCHIVE_GLOBAL_INVENTORY_INVALID")
    return archive_records, sha256_file(target)


def build_archive(inputs: BuildInputs, output: BuildOutput) -> None:
    validate_inputs(inputs)
    if output.archive.exists() or output.archive_build_record.exists() or output.archive_inventory.exists():
        raise WindowsRuntimeBuildError("ARCHIVE_OUTPUT_ALREADY_EXISTS")
    runtime_records, runtime_digest, _runtime_size = provenance._tree_inventory(output.runtime)
    archive_records, archive_sha = _deterministic_archive(output.runtime, output.archive)
    archive_inventory = {
        "archive_entry_count": len(archive_records),
        "archive_sha256": archive_sha,
        "entries": _records_payload(archive_records),
        "inventory_sha256": provenance._records_digest(archive_records),
        "root_prefix": "runtime",
        "schema_version": ARCHIVE_INVENTORY_SCHEMA,
    }
    _write_json(output.archive_inventory, archive_inventory)
    manifest = _load_json(output.runtime_manifest, provenance.RUNTIME_MANIFEST_SCHEMA)
    dependency = manifest["dependency_lock"]
    wheel_inventory = _load_json(output.wheelhouse_inventory, WHEELHOUSE_LOCK_SCHEMA)
    build_record = {
        "archive_inventory_sha256": sha256_file(output.archive_inventory),
        "build_policy_sha256": sha256_file(inputs.build_policy),
        "build_result": "pass",
        "builder_identifier": "infinite-canvas-enterprise-windows-runtime-builder",
        "builder_version": BUILD_TOOL_VERSION,
        "dependency_lock_sha256": dependency["sha256"],
        "enterprise_commit": inputs.enterprise_commit,
        "exit_code": 0,
        "full_file_inventory_sha256": provenance._records_digest(runtime_records),
        "output_archive_entry_count": len(archive_records),
        "output_archive_sha256": archive_sha,
        "post_build_changes_detected": False,
        "python_abi": "cp310",
        "python_source_sha256": sha256_file(inputs.source_archive),
        "python_version": "3.10.11",
        "runtime_tree_sha256": runtime_digest,
        "schema_version": provenance.ARCHIVE_BUILD_RECORD_SCHEMA,
        "upstream_commit": provenance.FIXED_UPSTREAM_COMMIT,
        "wheelhouse_manifest_sha256": sha256_file(output.wheelhouse_inventory),
        "wheelhouse_tree_sha256": wheel_inventory["tree_sha256"],
    }
    _write_json(output.archive_build_record, build_record)
    manifest["archive_provenance"] = {
        "archive_build_record_filename": output.archive_build_record.name,
        "archive_build_record_sha256": sha256_file(output.archive_build_record),
        "archive_sha256": archive_sha,
        "artifact_role": "assembled_candidate_runtime",
        "dependency_lock_sha256": dependency["sha256"],
        "enterprise_commit": inputs.enterprise_commit,
        "post_build_changes_detected": False,
        "python_abi": "cp310",
        "python_version": "3.10.11",
        "root_prefix": "runtime",
        "upstream_commit": provenance.FIXED_UPSTREAM_COMMIT,
        "wheelhouse_manifest_sha256": sha256_file(output.wheelhouse_inventory),
    }
    _replace_json(output.runtime_manifest, manifest)


def verify_output(inputs: BuildInputs, output: BuildOutput, *, include_archive: bool) -> dict[str, object]:
    report = provenance.verify_runtime_provenance(
        core_runtime_root=output.runtime,
        runtime_manifest=output.runtime_manifest,
        dependency_lock=inputs.requirements_lock,
        wheelhouse_manifest=output.wheelhouse_inventory,
        wheelhouse=inputs.wheelhouse,
        dependency_rebuild_attestation=output.rebuild_attestation,
        pip_check_report=output.pip_check_report,
        archive=output.archive if include_archive else None,
        archive_build_record=output.archive_build_record if include_archive else None,
        source_runtime_archive=inputs.source_archive,
        upstream_core_archive=inputs.source_archive,
        enterprise_commit=inputs.enterprise_commit,
        upstream_commit=provenance.FIXED_UPSTREAM_COMMIT,
    )
    report_path = output.provenance_report if include_archive else output.evidence / "runtime-provenance-report.json"
    if report_path.exists():
        raise WindowsRuntimeBuildError("PROVENANCE_REPORT_ALREADY_EXISTS")
    provenance.write_report(report_path, report)
    expected_archive = include_archive
    if (
        report.get("core_runtime_provenance_verified") is not True
        or report.get("dependency_layer_rebuilt_and_verified") is not True
        or report.get("archive_provenance_verified") is not expected_archive
        or report.get("production_approved") is not False
    ):
        raise WindowsRuntimeBuildError("PROVENANCE_VERIFICATION_FAILED")
    return report


def existing_output(root: Path | str) -> BuildOutput:
    root = _input_directory(root, "build_output")
    evidence = root / "evidence"
    archive_root = root / "archive"
    runtime = root / "runtime"
    return BuildOutput(
        root, runtime, evidence, archive_root / "python-runtime.zip",
        evidence / "runtime-manifest.json", evidence / "dependency-rebuild-attestation.json",
        evidence / "pip-check-report.json", evidence / "installed-distributions.json",
        evidence / "wheelhouse-inventory.json", evidence / "runtime-sbom.cdx.json",
        evidence / "runtime-archive-inventory.json", evidence / "runtime-archive-build-record.json",
        evidence / "runtime-archive-provenance-report.json",
    )


def compare_builds(first: BuildOutput, second: BuildOutput) -> dict[str, object]:
    first_records, first_digest, _ = provenance._tree_inventory(first.runtime)
    second_records, second_digest, _ = provenance._tree_inventory(second.runtime)
    comparisons = {
        "archive_sha256_equal": sha256_file(first.archive) == sha256_file(second.archive),
        "archive_inventory_equal": sha256_file(first.archive_inventory) == sha256_file(second.archive_inventory),
        "installed_distributions_equal": sha256_file(first.installed_distributions) == sha256_file(second.installed_distributions),
        "runtime_file_inventory_equal": first_records == second_records,
        "runtime_tree_sha256_equal": first_digest == second_digest,
        "sbom_sha256_equal": sha256_file(first.sbom) == sha256_file(second.sbom),
    }
    return {
        "build_a_archive_sha256": sha256_file(first.archive),
        "build_a_runtime_tree_sha256": first_digest,
        "build_b_archive_sha256": sha256_file(second.archive),
        "build_b_runtime_tree_sha256": second_digest,
        "comparisons": comparisons,
        "result": "pass" if all(comparisons.values()) else "fail",
        "schema_version": BUILD_SUMMARY_SCHEMA,
    }
