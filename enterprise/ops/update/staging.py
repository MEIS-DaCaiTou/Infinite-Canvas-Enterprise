"""Fail-closed ZIP inspection and extraction into a brand-new staging directory."""

from __future__ import annotations

import shutil
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

from enterprise.ops.release_validation import validate_release
from enterprise.ops.update.errors import ReleaseStagingError
from enterprise.ops.update.models import ReleaseManifest


MAX_ARCHIVE_FILES = 10_000
MAX_SINGLE_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
COPY_CHUNK_BYTES = 64 * 1024
WINDOWS_REPARSE_POINT = 0x0400
WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)


@dataclass(frozen=True)
class ZipEntry:
    info: zipfile.ZipInfo
    relative_path: str


@dataclass(frozen=True)
class StagingResult:
    staging_path: Path
    file_count: int
    total_bytes: int
    validation_report: dict


def _canonical_zip_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseStagingError("release archive contains an invalid path")
    raw = value.replace("\\", "/")
    if raw.startswith(("/", "//")) or (len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha()):
        raise ReleaseStagingError("release archive contains an unsafe path")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ReleaseStagingError("release archive contains an unsafe path")
    for part in parts:
        # Windows treats a colon as an alternate data stream separator, strips
        # trailing spaces/dots, and reserves device names even with extensions.
        # Reject rather than trying to repair names so the central directory and
        # the extracted filesystem cannot disagree about their final identity.
        if (
            ":" in part
            or part.endswith((" ", "."))
            or any(ord(character) < 32 or ord(character) == 127 for character in part)
        ):
            raise ReleaseStagingError("release archive contains an unsafe Windows path")
        normalized_part = unicodedata.normalize("NFC", part).casefold()
        if normalized_part.split(".", 1)[0] in WINDOWS_RESERVED_DEVICE_NAMES:
            raise ReleaseStagingError("release archive contains a reserved Windows device name")
    return "/".join(parts)


def _windows_path_key(value: str) -> str:
    """Return the case-insensitive NFC key Windows would use for collisions."""
    return "/".join(
        unicodedata.normalize("NFC", part).casefold() for part in value.split("/")
    )


def _zip_entry_is_unsafe(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        return True
    if stat.S_ISLNK(mode):
        return True
    return bool(info.external_attr & WINDOWS_REPARSE_POINT)


def inspect_zip_archive(
    archive_path: Path,
    manifest: ReleaseManifest,
    *,
    max_files: int = MAX_ARCHIVE_FILES,
    max_total_bytes: int = MAX_TOTAL_UNCOMPRESSED_BYTES,
    max_single_file_bytes: int = MAX_SINGLE_FILE_BYTES,
    max_compression_ratio: int = MAX_COMPRESSION_RATIO,
) -> list[ZipEntry]:
    """Inspect the ZIP central directory before creating any staging path."""
    if not archive_path.is_file() or not zipfile.is_zipfile(archive_path):
        raise ReleaseStagingError("release archive is not a readable ZIP file")
    entries: list[ZipEntry] = []
    seen: set[str] = set()
    total_bytes = 0
    prefix = manifest.package.root_prefix + "/"
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                canonical = _canonical_zip_path(info.filename.rstrip("/"))
                if _zip_entry_is_unsafe(info):
                    raise ReleaseStagingError("release archive contains a non-regular file entry")
                if canonical == manifest.package.root_prefix:
                    if not info.is_dir():
                        raise ReleaseStagingError("release archive root prefix is not a directory")
                    continue
                if not canonical.startswith(prefix):
                    raise ReleaseStagingError("release archive root prefix does not match its manifest")
                normalized_key = _windows_path_key(canonical)
                if normalized_key in seen:
                    raise ReleaseStagingError("release archive contains duplicate normalized paths")
                seen.add(normalized_key)
                if info.is_dir():
                    continue
                if info.file_size < 0 or info.file_size > max_single_file_bytes:
                    raise ReleaseStagingError("release archive contains an oversized file")
                total_bytes += info.file_size
                if total_bytes > max_total_bytes or len(entries) + 1 > max_files:
                    raise ReleaseStagingError("release archive exceeds its extraction limits")
                if info.file_size and (
                    not info.compress_size
                    or info.file_size / info.compress_size > max_compression_ratio
                ):
                    raise ReleaseStagingError("release archive exceeds its compression ratio limit")
                entries.append(ZipEntry(info=info, relative_path=canonical))
    except ReleaseStagingError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReleaseStagingError("release archive could not be inspected") from exc
    if len(entries) != manifest.package.file_count:
        raise ReleaseStagingError("release archive file count does not match its manifest")
    return entries


def _ensure_inside(root: Path, candidate: Path) -> None:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ReleaseStagingError("release extraction path escaped staging") from exc


def _filesystem_entry_is_unsafe(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & WINDOWS_REPARSE_POINT)


def verify_staged_release_directory(
    archive_path: Path,
    manifest: ReleaseManifest,
    *,
    staging_path: Path,
    job_id: str,
) -> StagingResult:
    """Reinspect archive and staging before a later plan can trust it.

    The report written by ``stage-release`` is evidence only. This function
    deliberately rebuilds the expected file set from the immutable archive and
    manifest, then compares it to the staged filesystem without following links.
    """
    entries = inspect_zip_archive(archive_path, manifest)
    if not staging_path.is_dir() or _filesystem_entry_is_unsafe(staging_path):
        raise ReleaseStagingError("release staging directory is not a safe directory")
    try:
        root = staging_path.resolve(strict=True)
        expected_by_key = {_windows_path_key(entry.relative_path): entry.relative_path for entry in entries}
        actual_by_key: dict[str, str] = {}
        expected_directories = {""}
        for relative_path in expected_by_key.values():
            parts = relative_path.split("/")
            expected_directories.update("/".join(parts[:index]) for index in range(1, len(parts)))

        for entry_path in staging_path.rglob("*"):
            if _filesystem_entry_is_unsafe(entry_path):
                raise ReleaseStagingError("release staging contains a link or reparse point")
            _ensure_inside(root, entry_path)
            try:
                raw_relative = entry_path.relative_to(staging_path).as_posix()
            except ValueError as exc:
                raise ReleaseStagingError("release staging path escaped its root") from exc
            canonical = _canonical_zip_path(raw_relative)
            key = _windows_path_key(canonical)
            if entry_path.is_dir():
                if canonical not in expected_directories:
                    raise ReleaseStagingError("release staging contains an unexpected directory")
                continue
            if not entry_path.is_file():
                raise ReleaseStagingError("release staging contains a non-regular filesystem entry")
            if key in actual_by_key:
                raise ReleaseStagingError("release staging contains duplicate normalized paths")
            actual_by_key[key] = canonical

        if set(actual_by_key) != set(expected_by_key):
            raise ReleaseStagingError("release staging files do not match the inspected archive")
        if any(actual_by_key[key] != expected_by_key[key] for key in expected_by_key):
            raise ReleaseStagingError("release staging file names do not match the inspected archive")
        if len(actual_by_key) != manifest.package.file_count:
            raise ReleaseStagingError("release staging file count does not match its manifest")
        # The archive itself is SHA-256 bound to the manifest. Compare each
        # staged byte stream to that archive so a same-name/same-count staging
        # modification cannot turn a report into forged preparation evidence.
        with zipfile.ZipFile(archive_path) as archive:
            for entry in entries:
                staged_path = staging_path.joinpath(*entry.relative_path.split("/"))
                received = 0
                with archive.open(entry.info, "r") as expected, staged_path.open("rb") as actual:
                    while True:
                        expected_chunk = expected.read(COPY_CHUNK_BYTES)
                        actual_chunk = actual.read(COPY_CHUNK_BYTES)
                        if expected_chunk != actual_chunk:
                            raise ReleaseStagingError("release staging file contents do not match the archive")
                        if not expected_chunk:
                            break
                        received += len(expected_chunk)
                if received != entry.info.file_size:
                    raise ReleaseStagingError("release staging file size does not match the archive")
        validation = validate_release(staging_path, job_id)
        if validation["status"] == "fail":
            raise ReleaseStagingError("release staging violates shared release validation")
        total_bytes = sum((staging_path / relative_path).stat().st_size for relative_path in actual_by_key.values())
        return StagingResult(
            staging_path=staging_path,
            file_count=len(actual_by_key),
            total_bytes=total_bytes,
            validation_report=validation,
        )
    except ReleaseStagingError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReleaseStagingError("release staging could not be revalidated") from exc


def stage_release_archive(
    archive_path: Path,
    manifest: ReleaseManifest,
    *,
    staging_path: Path,
    job_id: str,
) -> StagingResult:
    """Extract only preflighted regular files into a brand-new staging path."""
    entries = inspect_zip_archive(archive_path, manifest)
    if staging_path.exists():
        raise ReleaseStagingError("release staging destination already exists")
    created = False
    succeeded = False
    try:
        staging_path.mkdir(parents=True, exist_ok=False)
        created = True
        root = staging_path.resolve(strict=True)
        with zipfile.ZipFile(archive_path) as archive:
            for entry in entries:
                destination = staging_path.joinpath(*entry.relative_path.split("/"))
                _ensure_inside(root, destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                _ensure_inside(root, destination.parent)
                if destination.exists() or destination.is_symlink():
                    raise ReleaseStagingError("release staging encountered a duplicate destination")
                received = 0
                with archive.open(entry.info, "r") as source, destination.open("xb") as target:
                    while True:
                        chunk = source.read(COPY_CHUNK_BYTES)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > entry.info.file_size:
                            raise ReleaseStagingError("release archive entry size changed during extraction")
                        target.write(chunk)
                if received != entry.info.file_size:
                    raise ReleaseStagingError("release archive entry size changed during extraction")
        result = verify_staged_release_directory(
            archive_path,
            manifest,
            staging_path=staging_path,
            job_id=job_id,
        )
        succeeded = True
        return result
    except ReleaseStagingError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReleaseStagingError("release staging could not be completed") from exc
    finally:
        if created and staging_path.exists():
            # Successful callers retain staging. Failures remove only this job's
            # newly created path, never an existing path supplied by an operator.
            try:
                if not succeeded:
                    shutil.rmtree(staging_path)
            except OSError:
                pass
