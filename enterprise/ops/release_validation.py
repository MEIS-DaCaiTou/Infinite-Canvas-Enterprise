"""Shared, read-only release-package validation for OPS commands.

The validator deliberately reports policy findings without extracting archives
or modifying a release. OPS-3A staging performs its separate, stricter ZIP
structure checks before calling this shared policy layer.
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SAMPLE_LIMIT = 20

RELEASE_FORBIDDEN_PREFIXES = (
    "assets/",
    "output/",
    "data/",
    "python/",
    "logs/",
    "ops_artifacts/",
    "ops_backups/",
)

RELEASE_FORBIDDEN_EXACT = {
    ".env",
    "enterprise.env",
    "history.json",
    "API/.env",
    "data/enterprise.db",
}

RELEASE_FORBIDDEN_NAME_FRAGMENTS = (
    "auth.json",
    "cookie",
    "token",
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_sample(values: list[str] | set[str], limit: int = SAMPLE_LIMIT) -> list[str]:
    return sorted(values)[:limit]


def _iter_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    if path.is_file():
        return [path]
    return [child for child in path.rglob("*") if child.is_file()]


def _rel_posix(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def validate_release(release_path: Path, job_id: str) -> dict[str, Any]:
    """Read-only policy validation for an offline directory or ZIP package."""
    critical: list[str] = []
    warnings: list[str] = []
    entries: list[str] = []
    total_bytes = 0
    if not release_path.exists():
        critical.append("release path missing")
    elif release_path.is_dir():
        for file_path in _iter_files(release_path):
            rel = _rel_posix(release_path, file_path)
            entries.append(rel)
            try:
                total_bytes += file_path.stat().st_size
            except OSError:
                pass
    elif zipfile.is_zipfile(release_path):
        try:
            with zipfile.ZipFile(release_path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    entries.append(normalize_release_entry(info.filename))
                    total_bytes += int(info.file_size)
        except (OSError, zipfile.BadZipFile):
            critical.append("release archive could not be read")
    else:
        critical.append("release path is not a directory or zip file")

    forbidden = [entry for entry in entries if release_forbidden_reason(entry)]
    if forbidden:
        critical.append(f"{len(forbidden)} forbidden runtime or secret paths found in release")
    if entries and not has_release_app_signal(entries):
        warnings.append("release does not appear to include VERSION/main.py/enterprise app files")
    if entries and not has_manifest_signal(entries):
        warnings.append("release manifest/checksums not found")
    status = "fail" if critical else "warn" if warnings else "pass"
    return {
        "kind": "release-validation-report",
        "job_id": job_id,
        "status": status,
        "generated_at": _utc_now(),
        "release_path": release_path.as_posix(),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "forbidden_path_count": len(forbidden),
        "forbidden_path_samples": _safe_sample(forbidden),
        "findings": {"critical": critical, "warnings": warnings},
        "note": "Read-only release validation. No files were modified.",
    }


def release_forbidden_reason(entry: str) -> str:
    """Return a stable reason when a release entry is disallowed."""
    normalized = normalize_release_entry(entry)
    if is_unsafe_release_entry_path(normalized):
        return "unsafe-path"
    normalized = normalized.lstrip("/")
    lower = normalized.lower()
    parts = lower.split("/")
    basename = parts[-1] if parts else lower
    candidate_roots = path_suffix_candidates(lower)
    for candidate in candidate_roots:
        if candidate in {item.lower() for item in RELEASE_FORBIDDEN_EXACT}:
            return "exact"
        if any(candidate.startswith(prefix.lower()) for prefix in RELEASE_FORBIDDEN_PREFIXES):
            return "prefix"
    if basename == ".env" or (basename.endswith(".env") and not basename.endswith(".env.example")):
        return "env"
    if any(fragment in lower for fragment in RELEASE_FORBIDDEN_NAME_FRAGMENTS):
        return "credential-name"
    if any(fragment in lower for fragment in ("/output/", "\\output\\")) and Path(lower).suffix in IMAGE_SUFFIXES:
        return "runtime-output"
    return ""


def normalize_release_entry(entry: str) -> str:
    """Normalize path separators without making an unsafe path safe."""
    raw = entry.replace("\\", "/")
    return raw[2:] if raw.startswith("./") else raw


def is_unsafe_release_entry_path(entry: str) -> bool:
    """Detect paths that cannot safely represent a relative release file."""
    normalized = entry.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith("//"):
        return True
    if normalized.startswith("/"):
        return True
    if len(normalized) >= 3 and normalized[1] == ":" and normalized[0].isalpha() and normalized[2] == "/":
        return True
    return any(part == ".." for part in parts)


def path_suffix_candidates(path: str) -> list[str]:
    parts = [part for part in path.split("/") if part]
    candidates = ["/".join(parts[index:]) for index in range(len(parts))]
    return candidates or [path]


def has_release_app_signal(entries: list[str]) -> bool:
    normalized = [normalize_release_entry(entry).lstrip("/") for entry in entries]
    has_version = any(entry == "VERSION" or entry.endswith("/VERSION") for entry in normalized)
    has_main = any(entry == "main.py" or entry.endswith("/main.py") for entry in normalized)
    has_enterprise = any(entry.startswith("enterprise/") or "/enterprise/" in entry for entry in normalized)
    return has_version and has_main and has_enterprise


def has_manifest_signal(entries: list[str]) -> bool:
    lower = [normalize_release_entry(entry).lower().lstrip("/") for entry in entries]
    return any("manifest" in entry for entry in lower) or any(entry.endswith("checksums.txt") for entry in lower)
