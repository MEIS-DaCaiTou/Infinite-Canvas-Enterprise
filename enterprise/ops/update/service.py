"""Service-layer orchestration for non-executing OPS-3A update preparation."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from enterprise.ops.update.download import atomic_download
from enterprise.ops.update.errors import (
    OnlineUpdateError,
    OnlineUpdateValidationError,
    ReleaseDownloadError,
    ReleaseManifestError,
    UpdatePlanBlockedError,
)
from enterprise.ops.update.http_client import SafeHttpClient
from enterprise.ops.update.jobs import UpdateJob, ensure_workspace, workspace_child, workspace_relative
from enterprise.ops.update.manifest import parse_release_manifest_bytes
from enterprise.ops.update.models import ReleaseManifest, ReleaseMetadata
from enterprise.ops.update.providers import ReleaseProvider
from enterprise.ops.update.staging import stage_release_archive, verify_staged_release_directory
from enterprise.ops.update.versions import compare_versions, parse_version


MAX_MANIFEST_BYTES = 512 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_INPUT_REPORT_BYTES = 4 * 1024 * 1024
MAX_DATABASE_BYTES = 64 * 1024 * 1024 * 1024
MAX_BACKUP_AGE_SECONDS = 24 * 60 * 60
NOT_EXECUTED = (
    "No production files were replaced.",
    "No services were stopped or started.",
    "No database migration was applied.",
    "No version switch was performed.",
    "No rollback was performed.",
)
LOWER_SHA1 = re.compile(r"^[0-9a-f]{40}$")
LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _read_bounded_bytes(path: Path, *, maximum_bytes: int) -> bytes:
    if not path.is_file():
        raise OnlineUpdateValidationError("online update input file is unavailable")
    chunks: list[bytes] = []
    received = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(64 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > maximum_bytes:
                    raise OnlineUpdateValidationError("online update input file exceeds its size limit")
                chunks.append(chunk)
    except OSError as exc:
        raise OnlineUpdateValidationError("online update input file could not be read") from exc
    return b"".join(chunks)


def _sha256_file(path: Path, *, maximum_bytes: int) -> tuple[int, str]:
    """Hash a regular local file with a caller-supplied bounded size."""
    if not path.is_file():
        raise OnlineUpdateValidationError("online update input file is unavailable")
    digest = hashlib.sha256()
    received = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(64 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > maximum_bytes:
                    raise OnlineUpdateValidationError("online update input file exceeds its size limit")
                digest.update(chunk)
    except OSError as exc:
        raise OnlineUpdateValidationError("online update input file could not be read") from exc
    return received, digest.hexdigest()


def _read_json_file(path: Path, *, maximum_bytes: int = MAX_INPUT_REPORT_BYTES) -> dict[str, Any]:
    data = _read_bounded_bytes(path, maximum_bytes=maximum_bytes)
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OnlineUpdateValidationError("online update JSON input is invalid") from exc
    if len(data) < 2 or type(payload) is not dict:
        raise OnlineUpdateValidationError("online update JSON input is invalid")
    return payload


def _required_text(value: object, label: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise OnlineUpdateValidationError(f"{label} is invalid")
    return value


def _metadata_summary(metadata: ReleaseMetadata) -> dict[str, object]:
    """Keep external URLs and release body out of persistent job reports."""
    return {
        "provider": metadata.provider,
        "repository": metadata.repository,
        "release_id": metadata.release_id,
        "tag_name": metadata.tag_name,
        "version": metadata.version,
        "published_at": metadata.published_at,
    }


def _required_nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise OnlineUpdateValidationError(f"{label} is invalid")
    return value


def _required_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not LOWER_SHA256.fullmatch(value):
        raise OnlineUpdateValidationError(f"{label} is invalid")
    return value


def _required_workspace_relative(value: object, label: str, *, prefix: str | None = None) -> str:
    text = _required_text(value, label, maximum=512)
    if "\\" in text or text.startswith("/") or ".." in Path(text).parts:
        raise OnlineUpdateValidationError(f"{label} is invalid")
    if prefix is not None and not text.startswith(prefix):
        raise OnlineUpdateValidationError(f"{label} is invalid")
    return text


def _parse_utc_timestamp(value: object, label: str) -> datetime:
    text = _required_text(value, label, maximum=64)
    if not text.endswith("Z"):
        raise OnlineUpdateValidationError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise OnlineUpdateValidationError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise OnlineUpdateValidationError(f"{label} is invalid")
    return parsed.astimezone(timezone.utc)


def _stage_evidence(report: dict[str, Any]) -> dict[str, object]:
    """Allow only validated scalar evidence from a prior staging report into a plan."""
    if report.get("kind") != "online-update-job-report" or report.get("status") != "pass" or report.get("state") != "staged":
        raise OnlineUpdateValidationError("a successful staged release report is required")
    try:
        target_version = str(parse_version(report.get("target_version")))
    except ValueError as exc:
        raise OnlineUpdateValidationError("staged release target version is invalid") from exc
    source_commit = report.get("source_commit")
    if not isinstance(source_commit, str) or not LOWER_SHA1.fullmatch(source_commit):
        raise OnlineUpdateValidationError("staged release source commit is invalid")
    manifest_sha256 = _required_sha256(report.get("manifest_sha256"), "staged release manifest SHA256")
    archive_sha256 = _required_sha256(report.get("archive_sha256"), "staged release archive SHA256")
    staging_path = _required_workspace_relative(report.get("staging_path"), "staging path", prefix="staging/")
    manifest_path = _required_workspace_relative(report.get("manifest_path"), "staged manifest path", prefix="downloads/")
    archive_path = _required_workspace_relative(report.get("archive_path"), "staged archive path", prefix="downloads/")
    release_validation = report.get("release_validation")
    if type(release_validation) is not dict or release_validation.get("status") not in {"pass", "warn"}:
        raise OnlineUpdateValidationError("staged release validation evidence is invalid")
    validation_summary = {
        "status": release_validation["status"],
        "file_count": _required_nonnegative_int(release_validation.get("file_count"), "validation file count"),
        "forbidden_path_count": _required_nonnegative_int(release_validation.get("forbidden_path_count"), "validation forbidden path count"),
        "critical_count": _required_nonnegative_int(release_validation.get("critical_count"), "validation critical count"),
        "warning_count": _required_nonnegative_int(release_validation.get("warning_count"), "validation warning count"),
    }
    migration_required = report.get("migration_required")
    migration_ids = report.get("migration_ids")
    if type(migration_required) is not bool or type(migration_ids) is not list or len(migration_ids) > 128:
        raise OnlineUpdateValidationError("staged release migration evidence is invalid")
    if any(not isinstance(item, str) or not item or item != item.strip() or len(item) > 128 for item in migration_ids):
        raise OnlineUpdateValidationError("staged release migration evidence is invalid")
    return {
        "target_version": target_version,
        "source_commit": source_commit,
        "manifest_sha256": manifest_sha256,
        "archive_sha256": archive_sha256,
        "archive_size_bytes": _required_nonnegative_int(report.get("archive_size_bytes"), "archive size"),
        "manifest_path": manifest_path,
        "archive_path": archive_path,
        "staging_path": staging_path,
        "staging_file_count": _required_nonnegative_int(report.get("staging_file_count"), "staging file count"),
        "release_validation": validation_summary,
        "migration_required": migration_required,
        "migration_ids": list(migration_ids),
    }


class OnlineUpdateService:
    """Explicit-workspace OPS-3A service with no apply, rollback, or service control."""

    def __init__(
        self,
        *,
        app_root: str | Path,
        workspace: str | Path,
        provider: ReleaseProvider,
        http_client: SafeHttpClient | None = None,
    ) -> None:
        self.app_root = Path(app_root).resolve(strict=True)
        self.workspace = ensure_workspace(workspace, app_root=self.app_root)
        self.provider = provider
        self.http_client = http_client or SafeHttpClient(provider.url_policy)

    def _run_job(self, job_type: str, callback: Callable[[UpdateJob], str]) -> dict[str, Any]:
        job = UpdateJob(job_type=job_type, workspace=self.workspace)
        job.append_log("started")
        try:
            status = callback(job)
            if status not in {"pass", "blocked"}:
                raise OnlineUpdateValidationError("online update command returned an invalid status")
            job.complete()
            job.append_log("finished", status=status)
            report = job.write_report(status=status)
        except UpdatePlanBlockedError as exc:
            job.fail(exc)
            job.append_log("blocked", code=exc.code, message=exc.public_message)
            report = job.write_report(status="blocked")
        except OnlineUpdateError as exc:
            job.fail(exc)
            job.append_log("failed", code=exc.code, message=exc.public_message)
            report = job.write_report(status="fail")
        except Exception:
            error = OnlineUpdateError()
            job.fail(error)
            job.append_log("failed", code=error.code, message=error.public_message)
            report = job.write_report(status="fail")
        report["_report_path"] = str(self.workspace / job.report_paths[-1])
        return report

    def _current_version(self, supplied: str | None) -> str:
        if supplied is not None:
            try:
                return str(parse_version(supplied))
            except ValueError as exc:
                raise OnlineUpdateValidationError("current application version is invalid") from exc
        version_path = self.app_root / "VERSION"
        try:
            raw = version_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise OnlineUpdateValidationError("current application version is unavailable") from exc
        if raw.endswith("\n"):
            raw = raw[:-1]
        if raw.endswith("\r"):
            raw = raw[:-1]
        try:
            return str(parse_version(raw))
        except ValueError as exc:
            raise OnlineUpdateValidationError("current application version is invalid") from exc

    def _select_release(
        self,
        current_version: str,
        *,
        allow_prerelease: bool,
        release_id: str | None = None,
    ) -> ReleaseMetadata | None:
        releases = self.provider.list_releases()
        visible = [
            release
            for release in releases
            if not release.draft and (allow_prerelease or not release.prerelease)
        ]
        if release_id is not None:
            identifier = _required_text(release_id, "release identifier", maximum=256)
            matches = [release for release in visible if release.release_id == identifier]
            if len(matches) != 1:
                raise OnlineUpdateValidationError("requested release is unavailable")
            if compare_versions(current_version, matches[0].version) != "newer":
                raise UpdatePlanBlockedError("requested release is not newer than the current application version")
            return matches[0]
        candidates = [release for release in visible if compare_versions(current_version, release.version) == "newer"]
        if not candidates:
            return None
        return max(candidates, key=lambda release: parse_version(release.version))

    def _read_manifest(self, metadata: ReleaseMetadata) -> tuple[bytes, ReleaseManifest]:
        data = self.http_client.read_bytes(metadata.manifest_url, maximum_bytes=MAX_MANIFEST_BYTES)
        manifest = parse_release_manifest_bytes(data)
        self._bind_manifest(metadata, manifest)
        return data, manifest

    def _workspace_input_path(self, value: str | Path) -> Path:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        return workspace_child(self.workspace, candidate)

    @staticmethod
    def _input_path(value: str | Path) -> Path:
        if not isinstance(value, (str, Path)):
            raise OnlineUpdateValidationError("online update evidence file is unavailable")
        try:
            path = Path(value).resolve(strict=True)
        except OSError as exc:
            raise OnlineUpdateValidationError("online update evidence file is unavailable") from exc
        if not path.is_file():
            raise OnlineUpdateValidationError("online update evidence file is unavailable")
        return path

    def _stage_evidence_from_report(self, value: str | Path, *, current_version: str, job_id: str) -> dict[str, object]:
        """Rebuild staging evidence from current workspace artifacts, never report scalars."""
        report_path = self._workspace_input_path(value)
        report_size, report_sha256 = _sha256_file(report_path, maximum_bytes=MAX_INPUT_REPORT_BYTES)
        report = _read_json_file(report_path)
        evidence = _stage_evidence(report)
        if compare_versions(current_version, str(evidence["target_version"])) != "newer":
            raise UpdatePlanBlockedError("staged release is not newer than the current application version")

        manifest_path = self._workspace_input_path(str(evidence["manifest_path"]))
        archive_path = self._workspace_input_path(str(evidence["archive_path"]))
        staging_path = self._workspace_input_path(str(evidence["staging_path"]))
        manifest_data = _read_bounded_bytes(manifest_path, maximum_bytes=MAX_MANIFEST_BYTES)
        manifest_sha256 = hashlib.sha256(manifest_data).hexdigest()
        if manifest_sha256 != evidence["manifest_sha256"]:
            raise OnlineUpdateValidationError("staged release manifest evidence no longer matches")
        manifest = parse_release_manifest_bytes(manifest_data)
        if manifest.release_version != evidence["target_version"] or manifest.source_commit != evidence["source_commit"]:
            raise OnlineUpdateValidationError("staged release manifest evidence no longer matches")
        if (
            manifest.compatibility.requires_database_migration != evidence["migration_required"]
            or list(manifest.compatibility.migration_ids) != evidence["migration_ids"]
        ):
            raise OnlineUpdateValidationError("staged release migration evidence no longer matches")
        archive_size, archive_sha256 = _sha256_file(archive_path, maximum_bytes=MAX_ARCHIVE_BYTES)
        if (
            archive_path.name != manifest.archive.filename
            or archive_size != manifest.archive.size_bytes
            or archive_sha256 != manifest.archive.sha256
            or archive_size != evidence["archive_size_bytes"]
            or archive_sha256 != evidence["archive_sha256"]
        ):
            raise OnlineUpdateValidationError("staged release archive evidence no longer matches")
        staged = verify_staged_release_directory(
            archive_path,
            manifest,
            staging_path=staging_path,
            job_id=job_id,
        )
        validation = staged.validation_report
        fresh_summary = {
            "status": validation["status"],
            "file_count": validation["file_count"],
            "forbidden_path_count": validation["forbidden_path_count"],
            "critical_count": len(validation["findings"]["critical"]),
            "warning_count": len(validation["findings"]["warnings"]),
        }
        if (
            staged.file_count != evidence["staging_file_count"]
            or fresh_summary != evidence["release_validation"]
        ):
            raise OnlineUpdateValidationError("staged release directory evidence no longer matches")
        return {
            **evidence,
            "manifest": manifest,
            "stage_report_path": workspace_relative(self.workspace, report_path),
            "stage_report_size_bytes": report_size,
            "stage_report_sha256": report_sha256,
            "manifest_path": workspace_relative(self.workspace, manifest_path),
            "archive_path": workspace_relative(self.workspace, archive_path),
            "staging_path": workspace_relative(self.workspace, staging_path),
            "staging_file_count": staged.file_count,
            "staging_total_bytes": staged.total_bytes,
            "release_validation": fresh_summary,
        }

    def _validate_backup_manifest(self, value: str | Path) -> dict[str, object]:
        path = self._input_path(value)
        size, digest = _sha256_file(path, maximum_bytes=MAX_INPUT_REPORT_BYTES)
        manifest = _read_json_file(path)
        try:
            if manifest.get("kind") != "backup-manifest" or manifest.get("dry_run") is not False or manifest.get("status") != "pass":
                raise OnlineUpdateValidationError("backup manifest is not an executed successful backup")
            if manifest.get("sqlite_backup_status") != "success":
                raise OnlineUpdateValidationError("backup manifest does not prove SQLite backup success")
            if _required_text(manifest.get("app_root"), "backup app root", maximum=4096) != self.app_root.as_posix():
                raise OnlineUpdateValidationError("backup manifest app root does not match")
            if _required_text(manifest.get("source_database_relative_path"), "backup source database path") != "data/enterprise.db":
                raise OnlineUpdateValidationError("backup manifest source database path is invalid")
            source_path = self.app_root / "data" / "enterprise.db"
            source_size, source_sha256 = _sha256_file(source_path, maximum_bytes=MAX_DATABASE_BYTES)
            if source_size != _required_nonnegative_int(manifest.get("source_database_size_bytes"), "backup source database size"):
                raise OnlineUpdateValidationError("backup manifest source database fingerprint does not match")
            if source_sha256 != _required_sha256(manifest.get("source_database_sha256"), "backup source database SHA256"):
                raise OnlineUpdateValidationError("backup manifest source database fingerprint does not match")
            journal_mode = self._journal_mode(source_path)
            if _required_text(manifest.get("source_database_journal_mode"), "backup source database journal mode", maximum=32) != journal_mode:
                raise OnlineUpdateValidationError("backup manifest source database journal mode does not match")
            backup_dir = self._input_directory(_required_text(manifest.get("backup_dir"), "backup directory", maximum=4096), "backup directory")
            backup_path = self._input_path(_required_text(manifest.get("sqlite_backup_path"), "backup SQLite path", maximum=4096))
            expected_backup = (backup_dir / "app" / "data" / "enterprise.db").resolve(strict=True)
            if backup_path != expected_backup:
                raise OnlineUpdateValidationError("backup manifest SQLite backup path is invalid")
            backup_size, backup_sha256 = _sha256_file(backup_path, maximum_bytes=MAX_DATABASE_BYTES)
            if backup_size != _required_nonnegative_int(manifest.get("sqlite_backup_size_bytes"), "backup SQLite size"):
                raise OnlineUpdateValidationError("backup manifest SQLite backup fingerprint does not match")
            if backup_sha256 != _required_sha256(manifest.get("sqlite_backup_sha256"), "backup SQLite SHA256"):
                raise OnlineUpdateValidationError("backup manifest SQLite backup fingerprint does not match")
            copied_at = _parse_utc_timestamp(manifest.get("copied_at"), "backup copied time")
            age_seconds = (datetime.now(timezone.utc) - copied_at).total_seconds()
            if age_seconds < -300 or age_seconds > MAX_BACKUP_AGE_SECONDS:
                raise OnlineUpdateValidationError("backup manifest is outside the permitted freshness window")
        except OnlineUpdateValidationError:
            raise
        return {
            "path": path.as_posix(),
            "size_bytes": size,
            "sha256": digest,
            "backup_id": _required_text(manifest.get("backup_id"), "backup identifier"),
            "source_database_relative_path": "data/enterprise.db",
            "source_database_size_bytes": source_size,
            "source_database_sha256": source_sha256,
            "source_database_journal_mode": journal_mode,
            "sqlite_backup_path": backup_path.as_posix(),
            "sqlite_backup_size_bytes": backup_size,
            "sqlite_backup_sha256": backup_sha256,
            "copied_at": manifest["copied_at"],
        }

    def _validate_data_check_report(self, value: str | Path) -> dict[str, object]:
        path = self._input_path(value)
        size, digest = _sha256_file(path, maximum_bytes=MAX_INPUT_REPORT_BYTES)
        report = _read_json_file(path)
        if (
            report.get("kind") != "data-check-report"
            or report.get("status") not in {"pass", "warn"}
            or _required_text(report.get("app_root"), "data-check app root", maximum=4096) != self.app_root.as_posix()
        ):
            raise OnlineUpdateValidationError("data-check report is not usable")
        warnings = report.get("findings", {}).get("warnings", []) if type(report.get("findings")) is dict else []
        if type(warnings) is not list:
            raise OnlineUpdateValidationError("data-check report is not usable")
        return {
            "path": path.as_posix(),
            "size_bytes": size,
            "sha256": digest,
            "status": report["status"],
            "warning_count": len(warnings),
        }

    @staticmethod
    def _input_directory(value: object, label: str) -> Path:
        if not isinstance(value, str) or not value:
            raise OnlineUpdateValidationError(f"{label} is invalid")
        try:
            path = Path(value).resolve(strict=True)
        except OSError as exc:
            raise OnlineUpdateValidationError(f"{label} is invalid") from exc
        if not path.is_dir():
            raise OnlineUpdateValidationError(f"{label} is invalid")
        return path

    @staticmethod
    def _journal_mode(database_path: Path) -> str:
        try:
            with sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True) as connection:
                row = connection.execute("PRAGMA main.journal_mode").fetchone()
        except sqlite3.Error as exc:
            raise OnlineUpdateValidationError("source database journal mode is unavailable") from exc
        if not row or not isinstance(row[0], str) or not row[0]:
            raise OnlineUpdateValidationError("source database journal mode is unavailable")
        return row[0].casefold()

    @staticmethod
    def _bind_manifest(metadata: ReleaseMetadata, manifest: ReleaseManifest) -> None:
        if manifest.release_version != metadata.version:
            raise ReleaseManifestError("release manifest version does not bind provider metadata")
        archive_name = unquote(Path(urlparse(metadata.archive_url).path).name)
        if archive_name != manifest.archive.filename:
            raise ReleaseManifestError("release manifest archive does not bind provider metadata")

    @staticmethod
    def _compatible(current_version: str, manifest: ReleaseManifest) -> bool:
        minimum = manifest.compatibility.minimum_current_version
        maximum = manifest.compatibility.maximum_current_version
        current = parse_version(current_version)
        return (not minimum or current >= parse_version(minimum)) and (
            not maximum or current <= parse_version(maximum)
        )

    def check_update(
        self,
        *,
        current_version: str | None = None,
        allow_prerelease: bool = False,
    ) -> dict[str, Any]:
        """Find and validate the newest eligible release without writing downloads."""
        def action(job: UpdateJob) -> str:
            job.transition("checking")
            current = self._current_version(current_version)
            target = self._select_release(current, allow_prerelease=allow_prerelease)
            if target is None:
                job.transition(
                    "metadata_ready",
                    current_version=current,
                    target_version="",
                    relation="same_or_newer_not_available",
                    update_available=False,
                )
                return "pass"
            data, manifest = self._read_manifest(target)
            compatible = self._compatible(current, manifest)
            job.transition(
                "metadata_ready",
                current_version=current,
                target_version=target.version,
                relation="newer",
                update_available=compatible,
                compatibility_satisfied=compatible,
                release=_metadata_summary(target),
                source_commit=manifest.source_commit,
                manifest_sha256=hashlib.sha256(data).hexdigest(),
                archive_sha256=manifest.archive.sha256,
                archive_size_bytes=manifest.archive.size_bytes,
                migration_required=manifest.compatibility.requires_database_migration,
            )
            return "pass"

        return self._run_job("check-update", action)

    def fetch_release(
        self,
        *,
        current_version: str | None = None,
        allow_prerelease: bool = False,
        release_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a verified manifest and archive into a new job-owned workspace path."""
        def action(job: UpdateJob) -> str:
            job.transition("checking")
            current = self._current_version(current_version)
            target = self._select_release(
                current,
                allow_prerelease=allow_prerelease,
                release_id=release_id,
            )
            if target is None:
                raise OnlineUpdateValidationError("no newer eligible release is available")
            job.transition("metadata_ready", current_version=current, target_version=target.version, release=_metadata_summary(target))
            job.transition("downloading")
            download_dir = workspace_child(self.workspace, self.workspace / "downloads" / job.job_id)
            manifest_path = download_dir / "ops-release-manifest-v1.json"
            manifest_download = atomic_download(
                self.http_client,
                url=target.manifest_url,
                destination=manifest_path,
                maximum_bytes=MAX_MANIFEST_BYTES,
            )
            manifest = parse_release_manifest_bytes(manifest_path.read_bytes())
            self._bind_manifest(target, manifest)
            if compare_versions(current, manifest.release_version) != "newer":
                raise UpdatePlanBlockedError("release manifest is not newer than the current application version")
            if not self._compatible(current, manifest):
                raise UpdatePlanBlockedError("release compatibility does not include the current version")
            archive_path = download_dir / manifest.archive.filename
            archive_download = atomic_download(
                self.http_client,
                url=target.archive_url,
                destination=archive_path,
                maximum_bytes=MAX_ARCHIVE_BYTES,
                expected_size_bytes=manifest.archive.size_bytes,
                expected_sha256=manifest.archive.sha256,
            )
            job.transition(
                "verifying",
                current_version=current,
                target_version=target.version,
                source_commit=manifest.source_commit,
                manifest_sha256=manifest_download.sha256,
                archive_sha256=archive_download.sha256,
                archive_size_bytes=archive_download.size_bytes,
                manifest_path=workspace_relative(self.workspace, manifest_path),
                archive_path=workspace_relative(self.workspace, archive_path),
                release=_metadata_summary(target),
                migration_required=manifest.compatibility.requires_database_migration,
            )
            return "pass"

        return self._run_job("fetch-release", action)

    def stage_release(self, *, manifest_path: str | Path, archive_path: str | Path) -> dict[str, Any]:
        """Stage a fetched package only when its local manifest and archive still match."""
        def action(job: UpdateJob) -> str:
            job.transition("staging")
            manifest_file = self._workspace_input_path(manifest_path)
            archive_file = self._workspace_input_path(archive_path)
            manifest_data = _read_bounded_bytes(manifest_file, maximum_bytes=MAX_MANIFEST_BYTES)
            if len(manifest_data) < 2:
                raise ReleaseManifestError("staged release manifest is invalid")
            manifest = parse_release_manifest_bytes(manifest_data)
            current = self._current_version(None)
            if compare_versions(current, manifest.release_version) != "newer":
                raise UpdatePlanBlockedError("release manifest is not newer than the current application version")
            size, digest = _sha256_file(archive_file, maximum_bytes=MAX_ARCHIVE_BYTES)
            if archive_file.name != manifest.archive.filename or size != manifest.archive.size_bytes or digest != manifest.archive.sha256:
                raise ReleaseDownloadError("staged release archive no longer matches its manifest")
            staging_path = workspace_child(self.workspace, self.workspace / "staging" / job.job_id)
            staged = stage_release_archive(archive_file, manifest, staging_path=staging_path, job_id=job.job_id)
            validation = staged.validation_report
            job.transition(
                "staged",
                current_version=current,
                target_version=manifest.release_version,
                source_commit=manifest.source_commit,
                manifest_sha256=hashlib.sha256(manifest_data).hexdigest(),
                archive_sha256=digest,
                archive_size_bytes=size,
                manifest_path=workspace_relative(self.workspace, manifest_file),
                archive_path=workspace_relative(self.workspace, archive_file),
                staging_path=workspace_relative(self.workspace, staged.staging_path),
                staging_file_count=staged.file_count,
                staging_total_bytes=staged.total_bytes,
                release_validation={
                    "status": validation["status"],
                    "file_count": validation["file_count"],
                    "forbidden_path_count": validation["forbidden_path_count"],
                    "critical_count": len(validation["findings"]["critical"]),
                    "warning_count": len(validation["findings"]["warnings"]),
                },
                migration_required=manifest.compatibility.requires_database_migration,
                migration_ids=list(manifest.compatibility.migration_ids),
            )
            return "pass"

        return self._run_job("stage-release", action)

    def prepare_online_update(
        self,
        *,
        stage_report_path: str | Path,
        backup_manifest_path: str | Path | None,
        data_check_report_path: str | Path | None,
        maintenance_window: str = "",
    ) -> dict[str, Any]:
        """Compose a non-executing plan from validated local preparation evidence."""
        def action(job: UpdateJob) -> str:
            blockers: list[str] = []
            current = self._current_version(None)
            try:
                staged = self._stage_evidence_from_report(stage_report_path, current_version=current, job_id=job.job_id)
            except OnlineUpdateError:
                staged = None
                blockers.append("A successful staged release report is required")
            backup = None
            if backup_manifest_path is None:
                blockers.append("An executed backup manifest is required")
            else:
                try:
                    backup = self._validate_backup_manifest(backup_manifest_path)
                except OnlineUpdateError:
                    blockers.append("The backup manifest does not prove a successful executed SQLite backup")
            data_check = None
            if data_check_report_path is None:
                blockers.append("A data-check report is required")
            else:
                try:
                    data_check = self._validate_data_check_report(data_check_report_path)
                except OnlineUpdateError:
                    blockers.append("The data-check report is not usable")
            if maintenance_window and (maintenance_window != maintenance_window.strip() or len(maintenance_window) > 256):
                blockers.append("The maintenance window text is invalid")
            job.transition(
                "planned",
                current_version=current,
                target_version="" if staged is None else staged["target_version"],
                source_commit="" if staged is None else staged["source_commit"],
                manifest_sha256="" if staged is None else staged["manifest_sha256"],
                archive_sha256="" if staged is None else staged["archive_sha256"],
                archive_size_bytes=0 if staged is None else staged["archive_size_bytes"],
                staging_path="" if staged is None else staged["staging_path"],
                staging_file_count=0 if staged is None else staged["staging_file_count"],
                staging_total_bytes=0 if staged is None else staged["staging_total_bytes"],
                release_validation={} if staged is None else staged["release_validation"],
                migration_required=False if staged is None else staged["migration_required"],
                migration_ids=[] if staged is None else staged["migration_ids"],
                backup_verified=backup is not None,
                data_check_status="" if data_check is None else data_check["status"],
                maintenance_window=maintenance_window,
                blockers=blockers,
                warnings=[] if data_check is None or data_check["status"] != "warn" else ["Data-check warnings require operator review"],
                data_check_warning_count=0 if data_check is None else data_check["warning_count"],
                input_evidence={
                    "stage_report": {} if staged is None else {
                        "path": staged["stage_report_path"],
                        "size_bytes": staged["stage_report_size_bytes"],
                        "sha256": staged["stage_report_sha256"],
                    },
                    "release_manifest": {} if staged is None else {
                        "path": staged["manifest_path"],
                        "sha256": staged["manifest_sha256"],
                    },
                    "release_archive": {} if staged is None else {
                        "path": staged["archive_path"],
                        "size_bytes": staged["archive_size_bytes"],
                        "sha256": staged["archive_sha256"],
                    },
                    "staging_directory": {} if staged is None else {
                        "path": staged["staging_path"],
                        "file_count": staged["staging_file_count"],
                        "total_bytes": staged["staging_total_bytes"],
                    },
                    "backup_manifest": {} if backup is None else backup,
                    "data_check_report": {} if data_check is None else data_check,
                },
                app_root_fingerprint=self._app_root_fingerprint(),
                not_executed=list(NOT_EXECUTED),
            )
            return "blocked" if blockers else "pass"

        return self._run_job("prepare-online-update", action)

    def _app_root_fingerprint(self) -> dict[str, object]:
        version_path = self.app_root / "VERSION"
        size, digest = _sha256_file(version_path, maximum_bytes=64 * 1024)
        return {"version_file_sha256": digest, "version_file_size_bytes": size}
