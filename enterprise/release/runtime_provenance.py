"""Offline, layered provenance verification for a Windows Python candidate.

The verifier is release tooling only.  It never imports application modules,
uses the network, installs dependencies, or mutates supplied evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "env-1b2p-runtime-provenance-report-v2"
VERIFIER_VERSION = "env-1b2p-runtime-provenance-verifier-v2"
RUNTIME_MANIFEST_SCHEMA = "enterprise-windows-runtime-manifest-v1"
WHEELHOUSE_MANIFEST_SCHEMA = "env-1b2a-wheelhouse-sha256-v1"
DEPENDENCY_REBUILD_ATTESTATION_SCHEMA = "env-1b2p-dependency-rebuild-attestation-v1"
PIP_CHECK_REPORT_SCHEMA = "env-1b2p-pip-check-report-v1"
ARCHIVE_BUILD_RECORD_SCHEMA = "env-1b2p-archive-build-record-v1"
BOOTSTRAP_DISTRIBUTION_ALLOWLIST = frozenset({"pip", "setuptools", "wheel"})
FIXED_UPSTREAM_REPOSITORY = "hero8152/Infinite-Canvas"
FIXED_UPSTREAM_COMMIT = "f1dd6834a72f3e7ff8340be05a84347d931e9cb9"
FIXED_UPSTREAM_VERSION = "2026.07.6"

UPSTREAM_CORE_FILES = (
    "LICENSE.txt",
    "_asyncio.pyd",
    "_bz2.pyd",
    "_ctypes.pyd",
    "_decimal.pyd",
    "_elementtree.pyd",
    "_hashlib.pyd",
    "_lzma.pyd",
    "_msi.pyd",
    "_multiprocessing.pyd",
    "_overlapped.pyd",
    "_queue.pyd",
    "_socket.pyd",
    "_sqlite3.pyd",
    "_ssl.pyd",
    "_uuid.pyd",
    "_zoneinfo.pyd",
    "libcrypto-1_1.dll",
    "libffi-7.dll",
    "libssl-1_1.dll",
    "pyexpat.pyd",
    "python.cat",
    "python.exe",
    "python3.dll",
    "python310._pth",
    "python310.dll",
    "python310.zip",
    "pythonw.exe",
    "select.pyd",
    "sqlite3.dll",
    "unicodedata.pyd",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "winsound.pyd",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_LOCK_LINE_RE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;]+)$")
_WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_ZIP_ENTRIES = 100_000
_MAX_ZIP_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024


class ProvenanceVerificationError(RuntimeError):
    """Stable, sanitized verification error intended for CLI output."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


@dataclass(frozen=True)
class FileRecord:
    path: str
    sha256: str
    size_bytes: int


@dataclass
class _EvidenceState:
    checks: list[dict[str, object]] = field(default_factory=list)
    warnings: set[str] = field(default_factory=set)
    gaps: set[str] = field(default_factory=set)
    integrity_failed: bool = False

    def check(self, identifier: str, status: str, *, count: int | None = None) -> None:
        if status not in {"pass", "fail", "insufficient"}:
            raise ValueError("invalid check status")
        item: dict[str, object] = {"id": identifier, "status": status}
        if count is not None:
            item["count"] = count
        self.checks.append(item)
        if status == "fail":
            self.integrity_failed = True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise ProvenanceVerificationError("artifact-read-failed", path.name) from exc
    return digest.hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _has_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProvenanceVerificationError("path-inspection-failed", path.name) from exc
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _reject_reparse_ancestors(path: Path) -> None:
    current = path.absolute()
    for candidate in (current, *current.parents):
        if candidate.exists() and _has_reparse_point(candidate):
            raise ProvenanceVerificationError("input-reparse-point", path.name)


def _input_file(path: Path | str, artifact_type: str) -> Path:
    candidate = Path(path).absolute()
    if not candidate.is_file():
        raise ProvenanceVerificationError("input-file-missing", artifact_type)
    _reject_reparse_ancestors(candidate)
    return candidate.resolve(strict=True)


def _input_directory(path: Path | str, artifact_type: str) -> Path:
    candidate = Path(path).absolute()
    if not candidate.is_dir():
        raise ProvenanceVerificationError("input-directory-missing", artifact_type)
    _reject_reparse_ancestors(candidate)
    return candidate.resolve(strict=True)


def _safe_relative_path(value: object, *, code: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ProvenanceVerificationError(code)
    pure = PurePosixPath(value)
    if pure.is_absolute() or value.startswith("/") or any(part in {"", ".", ".."} for part in pure.parts):
        raise ProvenanceVerificationError(code)
    normalized_parts: list[str] = []
    for part in pure.parts:
        if any(ord(character) < 32 for character in part) or ":" in part:
            raise ProvenanceVerificationError(code)
        windows_name = part.rstrip(" .").split(".", 1)[0].casefold()
        if not part.rstrip(" .") or windows_name in _WINDOWS_DEVICE_NAMES:
            raise ProvenanceVerificationError(code)
        normalized_parts.append(part)
    return PurePosixPath(*normalized_parts).as_posix()


def _iter_tree(root: Path) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    try:
        for current_root, directory_names, file_names in os.walk(root, followlinks=False):
            current = Path(current_root)
            directory_names.sort()
            file_names.sort()
            for name in list(directory_names):
                directory = current / name
                relative = directory.relative_to(root).as_posix()
                if _has_reparse_point(directory):
                    raise ProvenanceVerificationError("tree-reparse-point", relative)
            for name in file_names:
                file_path = current / name
                relative = _safe_relative_path(file_path.relative_to(root).as_posix(), code="unsafe-tree-path")
                if _has_reparse_point(file_path):
                    raise ProvenanceVerificationError("tree-reparse-point", relative)
                if not file_path.is_file():
                    raise ProvenanceVerificationError("tree-non-regular-entry", relative)
                entries.append((relative, file_path))
    except ProvenanceVerificationError:
        raise
    except OSError as exc:
        raise ProvenanceVerificationError("tree-read-failed", root.name) from exc
    return sorted(entries, key=lambda item: item[0])


def _tree_inventory(root: Path) -> tuple[dict[str, FileRecord], str, int]:
    records: dict[str, FileRecord] = {}
    digest = hashlib.sha256()
    total_size = 0
    for relative, path in _iter_tree(root):
        file_digest = _sha256_file(path)
        size = path.stat().st_size
        record = FileRecord(relative, file_digest, size)
        records[relative] = record
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(file_digest))
        total_size += size
    return records, digest.hexdigest(), total_size


def _records_digest(records: Mapping[str, FileRecord]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(records):
        record = records[relative]
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(record.size_bytes.to_bytes(8, "big"))
        digest.update(bytes.fromhex(record.sha256))
    return digest.hexdigest()


def _load_json(path: Path, expected_schema: str) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise ProvenanceVerificationError("json-too-large", path.name)
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except ProvenanceVerificationError:
        raise
    except UnicodeError as exc:
        raise ProvenanceVerificationError("json-not-utf8", path.name) from exc
    except json.JSONDecodeError as exc:
        raise ProvenanceVerificationError("json-invalid", path.name) from exc
    except OSError as exc:
        raise ProvenanceVerificationError("artifact-read-failed", path.name) from exc
    if type(value) is not dict:
        raise ProvenanceVerificationError("json-root-invalid", path.name)
    if value.get("schema_version") != expected_schema:
        raise ProvenanceVerificationError("unsupported-schema", path.name)
    return value


def _artifact(path: Path, artifact_type: str, *, schema_version: str | None = None) -> dict[str, object]:
    item: dict[str, object] = {
        "artifact_type": artifact_type,
        "basename": path.name,
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }
    if schema_version:
        item["schema_version"] = schema_version
    return item


def _load_bound_json_artifact(
    *,
    path: Path | None,
    expected_schema: str,
    binding: Mapping[str, object] | None,
    filename_field: str,
    sha256_field: str,
    artifact_type: str,
    binding_check: str,
    content_check: str,
    missing_gap: str,
    state: _EvidenceState,
    artifacts: list[dict[str, object]],
) -> dict[str, Any] | None:
    if path is None:
        state.check(binding_check, "insufficient")
        state.check(content_check, "insufficient")
        state.gaps.add(missing_gap)
        return None

    artifact = _artifact(path, artifact_type)
    artifacts.append(artifact)
    binding_ok = (
        binding is not None
        and binding.get(filename_field) == path.name
        and binding.get(sha256_field) == artifact["sha256"]
    )
    state.check(binding_check, "pass" if binding_ok else "fail")
    if not binding_ok:
        state.check(content_check, "insufficient")
        return None
    try:
        value = _load_json(path, expected_schema)
    except ProvenanceVerificationError:
        state.check(content_check, "fail")
        return None
    artifact["schema_version"] = expected_schema
    return value


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _parse_lock(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeError as exc:
        raise ProvenanceVerificationError("dependency-lock-not-utf8", path.name) from exc
    except OSError as exc:
        raise ProvenanceVerificationError("artifact-read-failed", path.name) from exc
    packages: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE_RE.fullmatch(line)
        if match is None:
            raise ProvenanceVerificationError("dependency-lock-line-invalid")
        name = _normalized_name(match.group("name"))
        if name in packages:
            raise ProvenanceVerificationError("dependency-lock-duplicate", name)
        packages[name] = match.group("version")
    if not packages:
        raise ProvenanceVerificationError("dependency-lock-empty")
    return dict(sorted(packages.items()))


def _wheel_filename_tags(filename: str) -> tuple[set[str], set[str], set[str]]:
    if not filename.endswith(".whl"):
        raise ProvenanceVerificationError("wheel-extension-invalid", filename)
    components = filename[:-4].rsplit("-", 3)
    if len(components) != 4 or not components[0]:
        raise ProvenanceVerificationError("wheel-filename-invalid", filename)
    return set(components[1].split(".")), set(components[2].split(".")), set(components[3].split("."))


def _wheel_is_cp310_win_amd64(filename: str) -> bool:
    python_tags, abi_tags, platform_tags = _wheel_filename_tags(filename)
    python_ok = bool(python_tags & {"cp310", "py3"})
    abi_ok = bool(abi_tags & {"cp310", "abi3", "none"})
    platform_ok = bool(platform_tags & {"win_amd64", "any"})
    return python_ok and abi_ok and platform_ok


def _zip_inventory(path: Path) -> tuple[dict[str, FileRecord], int]:
    records: dict[str, FileRecord] = {}
    normalized_names: set[str] = set()
    total_size = 0
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ZIP_ENTRIES:
                raise ProvenanceVerificationError("archive-entry-limit-exceeded")
            for info in infos:
                raw_name = info.filename
                directory_entry = raw_name.endswith("/")
                name = raw_name[:-1] if directory_entry else raw_name
                if not name:
                    continue
                relative = _safe_relative_path(name, code="archive-unsafe-path")
                normalized = relative.casefold()
                if normalized in normalized_names:
                    raise ProvenanceVerificationError("archive-duplicate-path", relative)
                normalized_names.add(normalized)
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(unix_mode) == stat.S_IFLNK:
                    raise ProvenanceVerificationError("archive-symlink-entry", relative)
                if info.flag_bits & 0x1:
                    raise ProvenanceVerificationError("archive-encrypted-entry", relative)
                if directory_entry:
                    continue
                total_size += info.file_size
                if total_size > _MAX_ZIP_UNCOMPRESSED_BYTES:
                    raise ProvenanceVerificationError("archive-size-limit-exceeded")
                digest = hashlib.sha256()
                with archive.open(info, "r") as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                records[relative] = FileRecord(relative, digest.hexdigest(), info.file_size)
    except ProvenanceVerificationError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ProvenanceVerificationError("archive-read-failed", path.name) from exc
    return dict(sorted(records.items())), total_size


def _zip_subtree(records: Mapping[str, FileRecord], prefix: str) -> dict[str, FileRecord]:
    marker = prefix.rstrip("/") + "/"
    return {
        relative[len(marker) :]: FileRecord(relative[len(marker) :], record.sha256, record.size_bytes)
        for relative, record in records.items()
        if relative.startswith(marker)
    }


def _atomic_write_report(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists():
        raise ProvenanceVerificationError("output-report-already-exists", path.name)
    if not path.parent.is_dir():
        raise ProvenanceVerificationError("output-report-parent-missing", path.name)
    _reject_reparse_ancestors(path.parent)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="xb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_report(path: Path | str, payload: Mapping[str, object]) -> None:
    _atomic_write_report(Path(path).absolute(), payload)


def failure_report(code: str) -> dict[str, object]:
    return {
        "archive_provenance_verified": False,
        "checks": [{"id": code, "status": "fail"}],
        "core_runtime_provenance_verified": False,
        "dependency_layer_rebuilt_and_verified": False,
        "evidence_gaps": [],
        "overall_classification": "failed_integrity",
        "production_approved": False,
        "result": "fail",
        "schema_version": SCHEMA_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "warnings": [],
    }


def _candidate_interpreter_probe(runtime_root: Path, *, timeout_seconds: int = 15) -> dict[str, object]:
    executable = runtime_root / "python.exe"
    if not executable.is_file() or _has_reparse_point(executable):
        raise ProvenanceVerificationError("candidate-python-missing")
    probe = (
        "import importlib.metadata,json,platform,struct,sys,sysconfig;"
        "d=[];"
        "[(d.append({'name':x.metadata.get('Name') or '', 'version':x.version})) "
        "for x in importlib.metadata.distributions()];"
        "print(json.dumps({"
        "'version':sys.version,'version_info':list(sys.version_info[:3]),"
        "'implementation':platform.python_implementation(),"
        "'implementation_name':sys.implementation.name,"
        "'architecture':list(platform.architecture()),'machine':platform.machine(),"
        "'pointer_bits':struct.calcsize('P')*8,'abiflags':getattr(sys,'abiflags',''),"
        "'soabi':sysconfig.get_config_var('SOABI'),"
        "'prefix_basename':__import__('os').path.basename(sys.prefix),"
        "'base_prefix_basename':__import__('os').path.basename(sys.base_prefix),"
        "'executable_basename':__import__('os').path.basename(sys.executable),"
        "'distributions':sorted(d,key=lambda x:((x['name'] or '').lower(),x['version']))"
        "},sort_keys=True,separators=(',',':')))"
    )
    environment: dict[str, str] = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "PATH": str(runtime_root),
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
            environment[name] = value
    try:
        completed = subprocess.run(
            [str(executable), "-B", "-c", probe],
            cwd=str(runtime_root),
            env=environment,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProvenanceVerificationError("candidate-python-timeout") from exc
    except (OSError, UnicodeError) as exc:
        raise ProvenanceVerificationError("candidate-python-execution-failed") from exc
    if completed.returncode != 0 or len(completed.stdout.encode("utf-8")) > 256 * 1024:
        raise ProvenanceVerificationError("candidate-python-probe-failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProvenanceVerificationError("candidate-python-output-invalid") from exc
    if type(value) is not dict:
        raise ProvenanceVerificationError("candidate-python-output-invalid")
    return value


def _manifest_core_records(manifest: Mapping[str, object]) -> dict[str, FileRecord]:
    value = manifest.get("core_files")
    if type(value) is not list or not value:
        raise ProvenanceVerificationError("manifest-core-files-invalid")
    records: dict[str, FileRecord] = {}
    for item in value:
        if type(item) is not dict:
            raise ProvenanceVerificationError("manifest-core-file-invalid")
        relative = _safe_relative_path(item.get("filename"), code="manifest-core-path-invalid")
        digest = item.get("sha256")
        size = item.get("size_bytes")
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None or type(size) is not int or size < 0:
            raise ProvenanceVerificationError("manifest-core-file-invalid", relative)
        if relative in records:
            raise ProvenanceVerificationError("manifest-core-file-duplicate", relative)
        records[relative] = FileRecord(relative, digest, size)
    return records


def _records_equal(left: FileRecord | None, right: FileRecord | None) -> bool:
    return left is not None and right is not None and left.sha256 == right.sha256 and left.size_bytes == right.size_bytes


def _verify_core_layer(
    *,
    manifest: Mapping[str, object],
    runtime_records_before: Mapping[str, FileRecord],
    runtime_digest_before: str,
    runtime_size_before: int,
    runtime_records_after: Mapping[str, FileRecord],
    runtime_digest_after: str,
    probe: Mapping[str, object],
    upstream_records: Mapping[str, FileRecord] | None,
    source_archive_records: Mapping[str, FileRecord] | None,
    state: _EvidenceState,
) -> bool:
    valid = True
    source = manifest.get("source")
    source_ok = (
        type(source) is dict
        and source.get("upstream_repository") == FIXED_UPSTREAM_REPOSITORY
        and source.get("upstream_commit") == FIXED_UPSTREAM_COMMIT
        and source.get("upstream_version") == FIXED_UPSTREAM_VERSION
    )
    state.check("core-upstream-identity", "pass" if source_ok else "fail")
    valid &= source_ok

    manifest_records = _manifest_core_records(manifest)
    manifest_ok = all(_records_equal(record, runtime_records_before.get(relative)) for relative, record in manifest_records.items())
    state.check("core-manifest-files-match-runtime", "pass" if manifest_ok else "fail", count=len(manifest_records))
    valid &= manifest_ok

    required_manifest_names = {"python.exe", "pythonw.exe", "python310.dll", "python310.zip", "python310._pth"}
    required_manifest_ok = required_manifest_names.issubset(manifest_records)
    state.check("core-manifest-required-files", "pass" if required_manifest_ok else "fail", count=len(required_manifest_names))
    valid &= required_manifest_ok

    summary = manifest.get("files_summary")
    summary_ok = (
        type(summary) is dict
        and summary.get("runtime_file_count") == len(runtime_records_before)
        and summary.get("runtime_size_bytes") == runtime_size_before
    )
    state.check("runtime-manifest-tree-summary", "pass" if summary_ok else "fail", count=len(runtime_records_before))
    valid &= summary_ok

    if upstream_records is None:
        state.check("fixed-upstream-core-inventory", "insufficient")
        state.gaps.add("fixed-upstream-core-archive-missing")
        valid = False
    else:
        upstream_core = _zip_subtree(upstream_records, "python")
        inventory_ok = set(upstream_core) == set(UPSTREAM_CORE_FILES)
        state.check("fixed-upstream-core-inventory", "pass" if inventory_ok else "fail", count=len(upstream_core))
        valid &= inventory_ok

        if source_archive_records is None:
            state.check("source-archive-core-matches-upstream", "insufficient")
            state.gaps.add("source-runtime-archive-missing")
            valid = False
        else:
            source_core = _zip_subtree(source_archive_records, "python")
            source_match = set(source_core) >= set(UPSTREAM_CORE_FILES) and all(
                _records_equal(source_core.get(relative), upstream_core.get(relative)) for relative in UPSTREAM_CORE_FILES
            )
            state.check("source-archive-core-matches-upstream", "pass" if source_match else "fail", count=len(UPSTREAM_CORE_FILES))
            valid &= source_match

        candidate_matches = True
        transformed_pth = False
        for relative in UPSTREAM_CORE_FILES:
            upstream_record = upstream_core.get(relative)
            candidate_record = runtime_records_before.get(relative)
            if relative != "python310._pth":
                candidate_matches &= _records_equal(upstream_record, candidate_record)
                continue
            if _records_equal(upstream_record, candidate_record):
                continue
            embedded = manifest.get("embedded_pth")
            declared = (
                type(embedded) is dict
                and upstream_record is not None
                and candidate_record is not None
                and embedded.get("original_sha256") == upstream_record.sha256
                and embedded.get("candidate_sha256") == candidate_record.sha256
                and embedded.get("relative_app_root_entry") == ".."
                and embedded.get("import_site_enabled") is True
            )
            expected_pth = b"python310.zip\r\n.\r\n..\r\nimport site\r\n"
            declared = declared and candidate_record.sha256 == _sha256_bytes(expected_pth)
            transformed_pth = bool(declared)
            candidate_matches &= declared
        state.check(
            "candidate-core-matches-upstream-with-declared-pth-transform",
            "pass" if candidate_matches else "fail",
            count=len(UPSTREAM_CORE_FILES),
        )
        if transformed_pth:
            state.warnings.add("python310-pth-is-declared-relative-app-root-transform")
        valid &= candidate_matches

    identity_ok = (
        probe.get("version_info") == [3, 10, 11]
        and probe.get("implementation") == "CPython"
        and probe.get("implementation_name") == "cpython"
        and probe.get("pointer_bits") == 64
        and str(probe.get("machine", "")).casefold() in {"amd64", "x86_64"}
        and str(probe.get("executable_basename", "")).casefold() == "python.exe"
        and manifest.get("python_version") == "3.10.11"
        and str(manifest.get("python_implementation", "")).casefold() == "cpython"
        and manifest.get("architecture") == "x64"
        and manifest.get("python_abi") == "cp310"
    )
    state.check("candidate-interpreter-identity", "pass" if identity_ok else "fail")
    valid &= identity_ok

    unchanged = runtime_digest_before == runtime_digest_after and runtime_records_before == runtime_records_after
    state.check("candidate-runtime-unchanged-after-probe", "pass" if unchanged else "fail", count=len(runtime_records_after))
    valid &= unchanged
    return bool(valid)


def _installed_distributions(probe: Mapping[str, object]) -> dict[str, str]:
    value = probe.get("distributions")
    if type(value) is not list:
        raise ProvenanceVerificationError("candidate-distributions-invalid")
    result: dict[str, str] = {}
    for item in value:
        if type(item) is not dict or not isinstance(item.get("name"), str) or not isinstance(item.get("version"), str):
            raise ProvenanceVerificationError("candidate-distributions-invalid")
        normalized = _normalized_name(item["name"])
        if not normalized or normalized in result:
            raise ProvenanceVerificationError("candidate-distributions-invalid")
        result[normalized] = item["version"]
    return dict(sorted(result.items()))


def _installed_closure_digest(installed: Mapping[str, str]) -> str:
    payload = [{"name": name, "version": installed[name]} for name in sorted(installed)]
    return _sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _verify_dependency_layer(
    *,
    manifest: Mapping[str, object],
    dependency_lock: Path | None,
    wheelhouse_manifest_path: Path | None,
    wheelhouse_root: Path | None,
    rebuild_attestation_path: Path | None,
    pip_check_report_path: Path | None,
    runtime_tree_digest: str,
    enterprise_commit: str,
    upstream_commit: str,
    probe: Mapping[str, object],
    state: _EvidenceState,
    artifacts: list[dict[str, object]],
) -> tuple[bool, dict[str, int], dict[str, object]]:
    counts = {"locked_dependencies": 0, "wheelhouse_files": 0}
    context: dict[str, object] = {}
    manifest_dependency_value = manifest.get("dependency_lock")
    manifest_dependency = manifest_dependency_value if type(manifest_dependency_value) is dict else None
    rebuild_attestation = _load_bound_json_artifact(
        path=rebuild_attestation_path,
        expected_schema=DEPENDENCY_REBUILD_ATTESTATION_SCHEMA,
        binding=manifest_dependency,
        filename_field="rebuild_attestation_filename",
        sha256_field="rebuild_attestation_sha256",
        artifact_type="dependency_rebuild_attestation",
        binding_check="dependency-rebuild-attestation-binding",
        content_check="dependency-rebuild-attestation-content",
        missing_gap="dependency-rebuild-attestation-missing",
        state=state,
        artifacts=artifacts,
    )
    pip_check_report = _load_bound_json_artifact(
        path=pip_check_report_path,
        expected_schema=PIP_CHECK_REPORT_SCHEMA,
        binding=manifest_dependency,
        filename_field="pip_check_report_filename",
        sha256_field="pip_check_report_sha256",
        artifact_type="pip_check_report",
        binding_check="pip-check-report-binding",
        content_check="pip-check-report-content",
        missing_gap="pip-check-report-missing",
        state=state,
        artifacts=artifacts,
    )
    state.check("manifest-self-declared-dependency-evidence-non-authoritative", "pass")

    supplied = (dependency_lock is not None, wheelhouse_manifest_path is not None, wheelhouse_root is not None)
    if not all(supplied):
        state.check("dependency-evidence-complete", "insufficient")
        state.gaps.add("dependency-lock-wheelhouse-evidence-incomplete")
        if rebuild_attestation is not None:
            state.check("dependency-rebuild-attestation-content", "insufficient")
        if pip_check_report is not None:
            state.check("pip-check-report-content", "insufficient")
        return False, counts, context

    assert dependency_lock is not None and wheelhouse_manifest_path is not None and wheelhouse_root is not None
    lock_packages = _parse_lock(dependency_lock)
    wheel_manifest = _load_json(wheelhouse_manifest_path, WHEELHOUSE_MANIFEST_SCHEMA)
    artifacts.append(_artifact(dependency_lock, "dependency_lock"))
    artifacts.append(_artifact(wheelhouse_manifest_path, "wheelhouse_manifest", schema_version=WHEELHOUSE_MANIFEST_SCHEMA))

    wheel_items = wheel_manifest.get("wheels")
    if type(wheel_items) is not list:
        raise ProvenanceVerificationError("wheelhouse-manifest-wheels-invalid")
    declared: dict[str, dict[str, object]] = {}
    declared_packages: dict[str, str] = {}
    for item in wheel_items:
        if type(item) is not dict:
            raise ProvenanceVerificationError("wheelhouse-record-invalid")
        filename = _safe_relative_path(item.get("filename"), code="wheelhouse-filename-invalid")
        if "/" in filename or not filename.endswith(".whl"):
            raise ProvenanceVerificationError("wheelhouse-filename-invalid", filename)
        digest = item.get("sha256")
        size = item.get("size_bytes")
        package = item.get("package")
        version = item.get("version")
        if (
            filename in declared
            or not isinstance(digest, str)
            or _SHA256_RE.fullmatch(digest) is None
            or type(size) is not int
            or size < 0
            or not isinstance(package, str)
            or not isinstance(version, str)
        ):
            raise ProvenanceVerificationError("wheelhouse-record-invalid", filename)
        normalized = _normalized_name(package)
        if normalized in declared_packages:
            raise ProvenanceVerificationError("wheelhouse-package-duplicate", normalized)
        declared[filename] = item
        declared_packages[normalized] = version

    actual_files = _iter_tree(wheelhouse_root)
    actual_by_basename: dict[str, tuple[str, Path]] = {}
    duplicate_basename = False
    for relative, path in actual_files:
        basename = PurePosixPath(relative).name
        if basename in actual_by_basename:
            duplicate_basename = True
        actual_by_basename[basename] = (relative, path)
    actual_names = set(actual_by_basename)
    closure_ok = not duplicate_basename and actual_names == set(declared)
    hash_ok = closure_ok
    tags_ok = True
    wheelhouse_size = 0
    wheel_digest = hashlib.sha256()
    for relative, path in actual_files:
        basename = PurePosixPath(relative).name
        actual_hash = _sha256_file(path)
        actual_size = path.stat().st_size
        wheelhouse_size += actual_size
        encoded = relative.encode("utf-8")
        wheel_digest.update(len(encoded).to_bytes(8, "big"))
        wheel_digest.update(encoded)
        wheel_digest.update(actual_size.to_bytes(8, "big"))
        wheel_digest.update(bytes.fromhex(actual_hash))
        record = declared.get(basename)
        if record is None:
            hash_ok = False
            continue
        hash_ok &= actual_hash == record.get("sha256") and actual_size == record.get("size_bytes")
        tags_ok &= _wheel_is_cp310_win_amd64(basename)
    lock_closure_ok = lock_packages == dict(sorted(declared_packages.items()))
    declared_summary_ok = (
        wheel_manifest.get("target_python_abi") == "cp310"
        and wheel_manifest.get("target_platform") == "win_amd64"
        and wheel_manifest.get("wheel_count") == len(declared)
        and wheel_manifest.get("invalid_wheel_count") == 0
        and all(item.get("compatible_with_cpython_310_win_amd64") is True for item in declared.values())
    )
    binding_ok = (
        manifest_dependency is not None
        and manifest_dependency.get("filename") == dependency_lock.name
        and manifest_dependency.get("sha256") == _sha256_file(dependency_lock)
        and manifest_dependency.get("wheelhouse_manifest_filename") == wheelhouse_manifest_path.name
        and manifest_dependency.get("wheelhouse_manifest_sha256") == _sha256_file(wheelhouse_manifest_path)
        and manifest_dependency.get("wheel_count") == len(declared)
        and manifest_dependency.get("invalid_wheel_count") == 0
    )
    installed = _installed_distributions(probe)
    missing_installed = set(lock_packages) - set(installed)
    version_mismatches = {
        name for name in set(installed) & set(lock_packages) if installed[name] != lock_packages[name]
    }
    installed_extras = set(installed) - set(lock_packages)
    installed_ok = (
        not missing_installed
        and not version_mismatches
        and installed_extras <= BOOTSTRAP_DISTRIBUTION_ALLOWLIST
    )
    bootstrap_distributions = [
        {"name": name, "version": installed[name]} for name in sorted(installed_extras)
    ]
    installed_closure_digest = _installed_closure_digest(installed)
    wheelhouse_tree_digest = wheel_digest.hexdigest()

    state.check("dependency-lock-wheel-manifest-closure", "pass" if lock_closure_ok else "fail", count=len(lock_packages))
    state.check("wheelhouse-bidirectional-closure", "pass" if closure_ok else "fail", count=len(actual_files))
    state.check("wheelhouse-sha256", "pass" if hash_ok else "fail", count=len(actual_files))
    state.check("wheel-tags-cp310-win-amd64", "pass" if tags_ok and declared_summary_ok else "fail", count=len(actual_files))
    state.check("runtime-manifest-dependency-binding", "pass" if binding_ok else "fail")
    state.check("candidate-installed-exact-closure", "pass" if installed_ok else "fail", count=len(installed))

    artifacts.append(
        {
            "artifact_type": "wheelhouse",
            "basename": wheelhouse_root.name,
            "sha256": wheelhouse_tree_digest,
            "size_bytes": wheelhouse_size,
            "declared_identifier": f"{len(actual_files)}-file-tree",
        }
    )
    counts.update(
        {
            "bootstrap_distributions": len(bootstrap_distributions),
            "locked_dependencies": len(lock_packages),
            "wheelhouse_files": len(actual_files),
        }
    )

    lock_sha256 = _sha256_file(dependency_lock)
    wheel_manifest_sha256 = _sha256_file(wheelhouse_manifest_path)
    expected_independent_binding: dict[str, object] = {
        "runtime_tree_sha256": runtime_tree_digest,
        "dependency_lock_sha256": lock_sha256,
        "wheelhouse_manifest_sha256": wheel_manifest_sha256,
        "wheelhouse_tree_sha256": wheelhouse_tree_digest,
        "python_version": manifest.get("python_version"),
        "python_abi": manifest.get("python_abi"),
        "enterprise_commit": enterprise_commit,
        "upstream_commit": upstream_commit,
        "installed_closure_sha256": installed_closure_digest,
    }
    rebuild_ok = False
    if rebuild_attestation is not None:
        rebuild_ok = all(rebuild_attestation.get(key) == value for key, value in expected_independent_binding.items())
        rebuild_ok = bool(
            rebuild_ok
            and rebuild_attestation.get("rebuild_command_classification") == "offline-locked-wheelhouse"
            and rebuild_attestation.get("network_download_count") == 0
            and rebuild_attestation.get("exit_code") == 0
            and rebuild_attestation.get("result") == "pass"
        )
        state.check("dependency-rebuild-attestation-content", "pass" if rebuild_ok else "fail")

    pip_check_ok = False
    if pip_check_report is not None:
        pip_check_ok = all(pip_check_report.get(key) == value for key, value in expected_independent_binding.items())
        pip_check_ok = bool(
            pip_check_ok
            and pip_check_report.get("command_identity") == "python-minus-m-pip-check"
            and pip_check_report.get("exit_code") == 0
            and pip_check_report.get("broken_requirements") == []
            and pip_check_report.get("result") == "pass"
        )
        state.check("pip-check-report-content", "pass" if pip_check_ok else "fail")

    context.update(
        {
            "dependency_lock_sha256": lock_sha256,
            "bootstrap_distributions": bootstrap_distributions,
            "installed_closure_sha256": installed_closure_digest,
            "runtime_tree_sha256": runtime_tree_digest,
            "wheelhouse_manifest_sha256": wheel_manifest_sha256,
            "wheelhouse_tree_sha256": wheelhouse_tree_digest,
        }
    )
    return bool(
        lock_closure_ok
        and closure_ok
        and hash_ok
        and tags_ok
        and declared_summary_ok
        and binding_ok
        and installed_ok
        and rebuild_ok
        and pip_check_ok
    ), counts, context


def _manifest_full_inventory(manifest: Mapping[str, object]) -> dict[str, FileRecord] | None:
    value = manifest.get("files")
    if value is None:
        return None
    if type(value) is not list:
        raise ProvenanceVerificationError("manifest-file-inventory-invalid")
    records: dict[str, FileRecord] = {}
    for item in value:
        if type(item) is not dict:
            raise ProvenanceVerificationError("manifest-file-record-invalid")
        relative = _safe_relative_path(item.get("path"), code="manifest-file-path-invalid")
        digest = item.get("sha256")
        size = item.get("size_bytes")
        if (
            relative in records
            or not isinstance(digest, str)
            or _SHA256_RE.fullmatch(digest) is None
            or type(size) is not int
            or size < 0
        ):
            raise ProvenanceVerificationError("manifest-file-record-invalid", relative)
        records[relative] = FileRecord(relative, digest, size)
    return dict(sorted(records.items()))


def _verify_archive_layer(
    *,
    manifest: Mapping[str, object],
    archive_path: Path | None,
    archive_records: Mapping[str, FileRecord] | None,
    archive_build_record_path: Path | None,
    runtime_records: Mapping[str, FileRecord],
    core_verified: bool,
    dependency_verified: bool,
    dependency_context: Mapping[str, object],
    enterprise_commit: str,
    upstream_commit: str,
    state: _EvidenceState,
    artifacts: list[dict[str, object]],
) -> bool:
    formal_value = manifest.get("archive_provenance")
    formal = formal_value if type(formal_value) is dict else None
    build_record = _load_bound_json_artifact(
        path=archive_build_record_path,
        expected_schema=ARCHIVE_BUILD_RECORD_SCHEMA,
        binding=formal,
        filename_field="archive_build_record_filename",
        sha256_field="archive_build_record_sha256",
        artifact_type="archive_build_record",
        binding_check="archive-build-record-binding",
        content_check="archive-build-record-content",
        missing_gap="archive-build-record-missing",
        state=state,
        artifacts=artifacts,
    )
    if archive_path is None or archive_records is None:
        state.check("archive-evidence-present", "insufficient")
        state.gaps.add("candidate-runtime-archive-missing")
        if build_record is not None:
            state.check("archive-build-record-content", "insufficient")
        return False

    state.check("archive-safe-entry-structure", "pass", count=len(archive_records))

    full_inventory = _manifest_full_inventory(manifest)
    if formal is None or full_inventory is None:
        state.check("assembled-archive-manifest-binding", "insufficient")
        state.gaps.update(
            {
                "assembled-candidate-archive-not-generated",
                "archive-full-file-manifest-missing",
                "archive-build-process-provenance-missing",
            }
        )
        if build_record is not None:
            state.check("archive-build-record-content", "insufficient")
        return False

    root_prefix_value = formal.get("root_prefix")
    root_prefix = _safe_relative_path(root_prefix_value, code="archive-root-prefix-invalid")
    archive_runtime = _zip_subtree(archive_records, root_prefix)
    inventory_match = set(archive_runtime) == set(full_inventory) and all(
        _records_equal(archive_runtime.get(relative), record) for relative, record in full_inventory.items()
    )
    runtime_match = set(runtime_records) == set(full_inventory) and all(
        _records_equal(runtime_records.get(relative), record) for relative, record in full_inventory.items()
    )
    archive_sha256 = _sha256_file(archive_path)
    identity_ok = (
        formal.get("artifact_role") == "assembled_candidate_runtime"
        and formal.get("archive_sha256") == archive_sha256
        and formal.get("upstream_commit") == FIXED_UPSTREAM_COMMIT
        and formal.get("enterprise_commit") == enterprise_commit
        and formal.get("python_version") == manifest.get("python_version")
        and formal.get("python_abi") == manifest.get("python_abi")
        and formal.get("post_build_changes_detected") is False
    )
    dependency = manifest.get("dependency_lock")
    dependency_binding_ok = (
        type(dependency) is dict
        and formal.get("dependency_lock_sha256") == dependency.get("sha256")
        and formal.get("wheelhouse_manifest_sha256") == dependency.get("wheelhouse_manifest_sha256")
    )
    full_inventory_digest = _records_digest(full_inventory)
    runtime_tree_digest = _records_digest(runtime_records)
    build_record_ok = False
    if build_record is not None:
        expected_build_binding: dict[str, object] = {
            "enterprise_commit": enterprise_commit,
            "upstream_commit": upstream_commit,
            "python_version": manifest.get("python_version"),
            "python_abi": manifest.get("python_abi"),
            "runtime_tree_sha256": runtime_tree_digest,
            "dependency_lock_sha256": dependency_context.get("dependency_lock_sha256"),
            "wheelhouse_manifest_sha256": dependency_context.get("wheelhouse_manifest_sha256"),
            "wheelhouse_tree_sha256": dependency_context.get("wheelhouse_tree_sha256"),
            "full_file_inventory_sha256": full_inventory_digest,
            "output_archive_sha256": archive_sha256,
            "output_archive_entry_count": len(archive_records),
        }
        build_record_ok = all(build_record.get(key) == value for key, value in expected_build_binding.items())
        build_record_ok = bool(
            build_record_ok
            and isinstance(build_record.get("builder_identifier"), str)
            and bool(build_record.get("builder_identifier"))
            and isinstance(build_record.get("builder_version"), str)
            and bool(build_record.get("builder_version"))
            and build_record.get("build_result") == "pass"
            and build_record.get("post_build_changes_detected") is False
        )
        state.check("archive-build-record-content", "pass" if build_record_ok else "fail")
    state.check("assembled-archive-file-inventory", "pass" if inventory_match else "fail", count=len(archive_runtime))
    state.check("assembled-archive-runtime-match", "pass" if runtime_match else "fail", count=len(runtime_records))
    state.check("assembled-archive-build-provenance", "pass" if identity_ok and dependency_binding_ok else "fail")
    if not dependency_verified:
        state.check("assembled-archive-dependency-layer", "insufficient")
        state.gaps.add("archive-dependency-layer-not-verified")
    else:
        state.check("assembled-archive-dependency-layer", "pass")
    return bool(
        inventory_match
        and runtime_match
        and identity_ok
        and dependency_binding_ok
        and build_record_ok
        and core_verified
        and dependency_verified
    )


def _resolve_optional_file(path: Path | str | None, artifact_type: str) -> Path | None:
    return None if path is None else _input_file(path, artifact_type)


def _resolve_optional_directory(path: Path | str | None, artifact_type: str) -> Path | None:
    return None if path is None else _input_directory(path, artifact_type)


def validate_output_report_path(
    output_report: Path | str,
    *,
    input_files: Sequence[Path | str | None],
    input_directories: Sequence[Path | str | None],
) -> Path:
    output = Path(output_report).absolute()
    if output.exists():
        raise ProvenanceVerificationError("output-report-already-exists", output.name)
    if not output.parent.is_dir():
        raise ProvenanceVerificationError("output-report-parent-missing", output.name)
    _reject_reparse_ancestors(output.parent)
    resolved_output = output.resolve(strict=False)
    for value in input_files:
        if value is not None and resolved_output == Path(value).absolute().resolve(strict=False):
            raise ProvenanceVerificationError("output-report-overlaps-input", output.name)
    for value in input_directories:
        if value is None:
            continue
        root = Path(value).absolute().resolve(strict=False)
        try:
            resolved_output.relative_to(root)
        except ValueError:
            continue
        raise ProvenanceVerificationError("output-report-inside-input", output.name)
    return output


def verify_runtime_provenance(
    *,
    core_runtime_root: Path | str,
    runtime_manifest: Path | str,
    enterprise_commit: str,
    upstream_commit: str,
    dependency_lock: Path | str | None = None,
    wheelhouse_manifest: Path | str | None = None,
    wheelhouse: Path | str | None = None,
    dependency_rebuild_attestation: Path | str | None = None,
    pip_check_report: Path | str | None = None,
    archive: Path | str | None = None,
    archive_build_record: Path | str | None = None,
    source_runtime_archive: Path | str | None = None,
    external_validation_report: Path | str | None = None,
    upstream_core_archive: Path | str | None = None,
) -> dict[str, object]:
    """Verify supplied evidence without modifying it or granting production approval."""

    if _COMMIT_RE.fullmatch(enterprise_commit) is None:
        raise ProvenanceVerificationError("enterprise-commit-invalid")
    if upstream_commit != FIXED_UPSTREAM_COMMIT:
        raise ProvenanceVerificationError("upstream-commit-not-fixed")

    runtime_root = _input_directory(core_runtime_root, "core_runtime_root")
    manifest_path = _input_file(runtime_manifest, "runtime_manifest")
    dependency_lock_path = _resolve_optional_file(dependency_lock, "dependency_lock")
    wheel_manifest_path = _resolve_optional_file(wheelhouse_manifest, "wheelhouse_manifest")
    wheelhouse_root = _resolve_optional_directory(wheelhouse, "wheelhouse")
    rebuild_attestation_path = _resolve_optional_file(
        dependency_rebuild_attestation, "dependency_rebuild_attestation"
    )
    pip_check_report_path = _resolve_optional_file(pip_check_report, "pip_check_report")
    archive_path = _resolve_optional_file(archive, "archive")
    archive_build_record_path = _resolve_optional_file(archive_build_record, "archive_build_record")
    source_archive_path = _resolve_optional_file(source_runtime_archive, "source_runtime_archive")
    external_report_path = _resolve_optional_file(external_validation_report, "external_validation_report")
    upstream_archive_path = _resolve_optional_file(upstream_core_archive, "upstream_core_archive")

    manifest = _load_json(manifest_path, RUNTIME_MANIFEST_SCHEMA)
    state = _EvidenceState()
    artifacts: list[dict[str, object]] = [
        _artifact(manifest_path, "runtime_manifest", schema_version=RUNTIME_MANIFEST_SCHEMA)
    ]
    input_files = [
        path
        for path in (
            manifest_path,
            dependency_lock_path,
            wheel_manifest_path,
            rebuild_attestation_path,
            pip_check_report_path,
            archive_path,
            archive_build_record_path,
            source_archive_path,
            external_report_path,
            upstream_archive_path,
        )
        if path is not None
    ]
    input_snapshots = {path: (path.stat().st_size, _sha256_file(path)) for path in input_files}

    source = manifest.get("source")
    evidence_enterprise_commit = source.get("enterprise_commit") if type(source) is dict else None
    if evidence_enterprise_commit == enterprise_commit:
        state.check("enterprise-baseline-binding", "pass")
    else:
        state.check("enterprise-baseline-binding", "insufficient")
        state.gaps.add("evidence-built-against-earlier-enterprise-commit")
        state.warnings.add("historical-evidence-enterprise-commit-differs-from-current-base")

    runtime_records_before, runtime_digest_before, runtime_size_before = _tree_inventory(runtime_root)
    artifacts.append(
        {
            "artifact_type": "core_runtime_root",
            "basename": runtime_root.name,
            "sha256": runtime_digest_before,
            "size_bytes": runtime_size_before,
            "declared_identifier": f"{len(runtime_records_before)}-file-tree",
        }
    )
    probe = _candidate_interpreter_probe(runtime_root)
    runtime_records_after, runtime_digest_after, _runtime_size_after = _tree_inventory(runtime_root)

    upstream_records: dict[str, FileRecord] | None = None
    if upstream_archive_path is not None:
        upstream_records, _ = _zip_inventory(upstream_archive_path)
        artifacts.append(_artifact(upstream_archive_path, "fixed_upstream_core_archive"))

    source_archive_records: dict[str, FileRecord] | None = None
    source_archive_uncompressed_bytes = 0
    if source_archive_path is not None:
        source_archive_records, source_archive_uncompressed_bytes = _zip_inventory(source_archive_path)
        artifacts.append(_artifact(source_archive_path, "source_runtime_archive"))
        source_archive = manifest.get("source_python_zip")
        source_identity_ok = (
            type(source_archive) is dict
            and source_archive.get("sha256") == _sha256_file(source_archive_path)
            and source_archive.get("size_bytes") == source_archive_path.stat().st_size
        )
        state.check("source-archive-declared-hash", "pass" if source_identity_ok else "fail")
    else:
        source_identity_ok = False
        state.check("source-archive-declared-hash", "insufficient")
        state.gaps.add("source-runtime-archive-missing")

    archive_records: dict[str, FileRecord] | None = None
    archive_uncompressed_bytes = 0
    if archive_path is not None:
        archive_records, archive_uncompressed_bytes = _zip_inventory(archive_path)
        artifacts.append(_artifact(archive_path, "runtime_archive"))

    if external_report_path is not None:
        artifacts.append(_artifact(external_report_path, "external_validation_report"))
        state.check("external-report-is-non-authoritative-attachment", "pass")
    else:
        state.check("external-report-is-non-authoritative-attachment", "insufficient")
        state.gaps.add("external-validation-report-missing")

    core_verified = _verify_core_layer(
        manifest=manifest,
        runtime_records_before=runtime_records_before,
        runtime_digest_before=runtime_digest_before,
        runtime_size_before=runtime_size_before,
        runtime_records_after=runtime_records_after,
        runtime_digest_after=runtime_digest_after,
        probe=probe,
        upstream_records=upstream_records,
        source_archive_records=source_archive_records,
        state=state,
    )
    core_verified = bool(core_verified and source_identity_ok)
    dependency_verified, dependency_counts, dependency_context = _verify_dependency_layer(
        manifest=manifest,
        dependency_lock=dependency_lock_path,
        wheelhouse_manifest_path=wheel_manifest_path,
        wheelhouse_root=wheelhouse_root,
        rebuild_attestation_path=rebuild_attestation_path,
        pip_check_report_path=pip_check_report_path,
        runtime_tree_digest=runtime_digest_before,
        enterprise_commit=enterprise_commit,
        upstream_commit=upstream_commit,
        probe=probe,
        state=state,
        artifacts=artifacts,
    )
    archive_verified = _verify_archive_layer(
        manifest=manifest,
        archive_path=archive_path,
        archive_records=archive_records,
        archive_build_record_path=archive_build_record_path,
        runtime_records=runtime_records_before,
        core_verified=core_verified,
        dependency_verified=dependency_verified,
        dependency_context=dependency_context,
        enterprise_commit=enterprise_commit,
        upstream_commit=upstream_commit,
        state=state,
        artifacts=artifacts,
    )

    unchanged_files = all((path.stat().st_size, _sha256_file(path)) == snapshot for path, snapshot in input_snapshots.items())
    state.check("input-file-artifacts-unchanged", "pass" if unchanged_files else "fail", count=len(input_snapshots))
    if wheelhouse_root is not None:
        wheel_after, wheel_digest_after, wheel_size_after = _tree_inventory(wheelhouse_root)
        wheel_artifact = next(item for item in artifacts if item.get("artifact_type") == "wheelhouse")
        wheel_unchanged = (
            wheel_artifact.get("sha256") == wheel_digest_after
            and wheel_artifact.get("size_bytes") == wheel_size_after
            and wheel_artifact.get("declared_identifier") == f"{len(wheel_after)}-file-tree"
        )
        state.check("wheelhouse-unchanged", "pass" if wheel_unchanged else "fail", count=len(wheel_after))

    integrity_failed = state.integrity_failed
    if integrity_failed:
        core_verified = dependency_verified = archive_verified = False
        classification = "failed_integrity"
        result = "fail"
    elif core_verified and dependency_verified and archive_verified:
        classification = "verified"
        result = "pass"
    elif core_verified or dependency_verified or archive_verified:
        classification = "partially_verified"
        result = "pass"
    else:
        classification = "insufficient_evidence"
        result = "pass"

    python_version_info = probe.get("version_info")
    python_version = ".".join(str(item) for item in python_version_info) if type(python_version_info) is list else "unknown"
    candidate_material = "\0".join(
        (
            artifacts[0]["sha256"],
            runtime_digest_before,
            str((runtime_records_before.get("python.exe") or FileRecord("", "", 0)).sha256),
        )
    ).encode("utf-8")
    counts: dict[str, int] = {
        "archive_entries": len(archive_records or {}),
        "archive_uncompressed_bytes": archive_uncompressed_bytes,
        "core_runtime_files": len(runtime_records_before),
        "fixed_upstream_core_files": len(UPSTREAM_CORE_FILES),
        "source_archive_entries": len(source_archive_records or {}),
        "source_archive_uncompressed_bytes": source_archive_uncompressed_bytes,
        **dependency_counts,
    }
    return {
        "abi": manifest.get("python_abi"),
        "architecture": manifest.get("architecture"),
        "archive_provenance_verified": archive_verified,
        "artifacts": sorted(artifacts, key=lambda item: (str(item["artifact_type"]), str(item["basename"]))),
        "bootstrap_distribution_allowlist": sorted(BOOTSTRAP_DISTRIBUTION_ALLOWLIST),
        "bootstrap_distributions": dependency_context.get("bootstrap_distributions", []),
        "candidate_id": _sha256_bytes(candidate_material),
        "checks": sorted(state.checks, key=lambda item: str(item["id"])),
        "core_runtime_provenance_verified": core_verified,
        "counts": counts,
        "dependency_layer_rebuilt_and_verified": dependency_verified,
        "enterprise_commit": enterprise_commit,
        "evidence_enterprise_commit": evidence_enterprise_commit,
        "evidence_gaps": sorted(state.gaps),
        "installed_closure_sha256": dependency_context.get("installed_closure_sha256"),
        "overall_classification": classification,
        "production_approved": False,
        "python_implementation": probe.get("implementation"),
        "python_version": python_version,
        "result": result,
        "schema_version": SCHEMA_VERSION,
        "upstream_commit": upstream_commit,
        "verifier_version": VERIFIER_VERSION,
        "warnings": sorted(state.warnings),
    }
