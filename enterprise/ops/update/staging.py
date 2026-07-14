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
    if not value or "\x00" in value:
        raise ReleaseStagingError("release archive contains an invalid path")
    raw = value.replace("\\", "/")
    if raw.startswith(("/", "//")) or (len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha()):
        raise ReleaseStagingError("release archive contains an unsafe path")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ReleaseStagingError("release archive contains an unsafe path")
    return "/".join(parts)


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
                normalized_key = unicodedata.normalize("NFC", canonical).casefold()
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
        extracted_files = [path for path in staging_path.rglob("*") if path.is_file()]
        if len(extracted_files) != manifest.package.file_count:
            raise ReleaseStagingError("release staging file count does not match its manifest")
        validation = validate_release(staging_path, job_id)
        if validation["status"] == "fail":
            raise ReleaseStagingError("release staging violates shared release validation")
        total_bytes = sum(path.stat().st_size for path in extracted_files)
        result = StagingResult(
            staging_path=staging_path,
            file_count=len(extracted_files),
            total_bytes=total_bytes,
            validation_report=validation,
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
