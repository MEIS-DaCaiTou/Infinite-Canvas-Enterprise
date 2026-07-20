"""Deterministic, fail-closed static tree staging for immutable releases."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import urllib.parse
from pathlib import Path
from typing import Callable, Iterable


SCHEMA_VERSION = "env-1b1a-static-build-report-v1"
BUILDER_VERSION = "env-1b1a-static-builder-v1"

_HASHABLE_SUFFIXES = frozenset(
    {
        ".css",
        ".eot",
        ".gif",
        ".html",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".mjs",
        ".otf",
        ".png",
        ".svg",
        ".ttf",
        ".webp",
        ".woff",
        ".woff2",
    }
)
_NON_LOCAL_SCHEMES = frozenset({"blob", "data", "http", "https", "javascript", "mailto"})
_ATTRIBUTE_URL = re.compile(
    r"(?P<prefix>\b(?:data-src|href|poster|src)\s*=\s*(?P<quote>['\"]))"
    r"(?P<url>.*?)"
    r"(?P=quote)",
    re.IGNORECASE,
)
_CSS_URL = re.compile(
    r"(?P<prefix>\burl\(\s*(?P<quote>['\"]?))"
    r"(?P<url>[^)'\"]+)"
    r"(?P=quote)(?P<suffix>\s*\))",
    re.IGNORECASE,
)


class StaticBuildError(RuntimeError):
    """A sanitized, stable build failure suitable for CLI output."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        message = code if not detail else f"{code}: {detail}"
        super().__init__(message)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _has_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _validate_paths(source: Path, output: Path, report: Path) -> tuple[Path, Path, Path]:
    source_input = source.absolute()
    if not source_input.is_dir():
        raise StaticBuildError("source-not-directory")
    if _has_reparse_point(source_input):
        raise StaticBuildError("source-root-reparse-point")

    source_root = source_input.resolve(strict=True)
    output_root = output.absolute().resolve(strict=False)
    report_path = report.absolute().resolve(strict=False)

    if output_root == source_root:
        raise StaticBuildError("output-equals-source")
    if _is_relative_to(output_root, source_root):
        raise StaticBuildError("output-inside-source")
    if output_root.exists():
        raise StaticBuildError("output-already-exists")
    if report_path.exists():
        raise StaticBuildError("report-already-exists")
    if _is_relative_to(report_path, source_root):
        raise StaticBuildError("report-inside-source")
    if _is_relative_to(report_path, output_root):
        raise StaticBuildError("report-inside-output")
    if not output_root.parent.is_dir():
        raise StaticBuildError("output-parent-missing")
    if not report_path.parent.is_dir():
        raise StaticBuildError("report-parent-missing")
    return source_root, output_root, report_path


def _iter_tree(root: Path) -> Iterable[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    for current_root, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(current_root)
        directory_names.sort()
        file_names.sort()
        for name in list(directory_names):
            directory = current / name
            relative = directory.relative_to(root).as_posix()
            if _has_reparse_point(directory):
                raise StaticBuildError("source-reparse-point", relative)
        for name in file_names:
            file_path = current / name
            relative = file_path.relative_to(root).as_posix()
            if _has_reparse_point(file_path):
                raise StaticBuildError("source-reparse-point", relative)
            if not file_path.is_file():
                raise StaticBuildError("source-entry-not-regular-file", relative)
            entries.append((relative, file_path))
    return sorted(entries, key=lambda item: item[0])


def _iter_directories(root: Path) -> Iterable[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    for current_root, directory_names, _ in os.walk(root, followlinks=False):
        current = Path(current_root)
        directory_names.sort()
        for name in directory_names:
            directory = current / name
            relative = directory.relative_to(root).as_posix()
            if _has_reparse_point(directory):
                raise StaticBuildError("source-reparse-point", relative)
            entries.append((relative, directory))
    return sorted(entries, key=lambda item: item[0])


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for relative, _ in _iter_directories(root):
        relative_bytes = relative.encode("utf-8")
        digest.update(b"directory\0")
        digest.update(len(relative_bytes).to_bytes(8, "big"))
        digest.update(relative_bytes)
    for relative, file_path in _iter_tree(root):
        content = file_path.read_bytes()
        relative_bytes = relative.encode("utf-8")
        digest.update(b"file\0")
        digest.update(len(relative_bytes).to_bytes(8, "big"))
        digest.update(relative_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _copy_tree(source_root: Path, output_root: Path) -> None:
    output_root.mkdir()
    for relative, _ in _iter_directories(source_root):
        (output_root / Path(relative)).mkdir()
    for relative, source_path in _iter_tree(source_root):
        destination = output_root / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("rb") as source_handle, destination.open("xb") as output_handle:
            shutil.copyfileobj(source_handle, output_handle)


def _with_hash_query(url: str, digest: str) -> str:
    before_fragment, separator, fragment = url.partition("#")
    path, query_separator, query = before_fragment.partition("?")
    parts = []
    if query_separator:
        for part in query.split("&"):
            key = part.split("=", 1)[0]
            if urllib.parse.unquote_plus(key).lower() != "v":
                parts.append(part)
    parts.append(f"v={digest}")
    rewritten = f"{path}?{'&'.join(parts)}"
    return rewritten if not separator else f"{rewritten}#{fragment}"


def _reference_path(html_relative: str, url: str, source_root: Path) -> tuple[str, Path] | None:
    clean = url.strip()
    if not clean or clean.startswith("#") or clean.startswith("?"):
        return None
    if "${" in clean or "{{" in clean or "<%" in clean:
        return None
    if clean.startswith("//"):
        return None

    split = urllib.parse.urlsplit(clean)
    if split.scheme.lower() in _NON_LOCAL_SCHEMES or split.netloc:
        return None
    decoded_path = urllib.parse.unquote(split.path)
    if not decoded_path or "\\" in decoded_path or "\x00" in decoded_path:
        return None

    if decoded_path.startswith("/static/"):
        relative_candidate = decoded_path[len("/static/") :]
    elif decoded_path.startswith("/"):
        return None
    else:
        relative_candidate = (Path(html_relative).parent / decoded_path).as_posix()

    candidate = (source_root / Path(relative_candidate)).resolve(strict=False)
    if not _is_relative_to(candidate, source_root):
        raise StaticBuildError("reference-escapes-source", html_relative)
    relative = candidate.relative_to(source_root).as_posix()
    if Path(relative).suffix.lower() not in _HASHABLE_SUFFIXES:
        return None
    if not candidate.is_file() or _has_reparse_point(candidate):
        raise StaticBuildError("local-resource-unresolved", f"{html_relative} -> {relative}")
    return relative, candidate


def _rewrite_html(
    content: str,
    html_relative: str,
    source_root: Path,
    resources: dict[str, str],
) -> tuple[str, int]:
    skipped_non_local = 0

    def rewrite_url(url: str) -> str:
        nonlocal skipped_non_local
        stripped = url.strip()
        split = urllib.parse.urlsplit(stripped)
        if (
            split.scheme.lower() in _NON_LOCAL_SCHEMES
            or split.netloc
            or stripped.startswith("//")
            or stripped.startswith("data:")
            or stripped.startswith("blob:")
        ):
            skipped_non_local += 1
            return url
        resolved = _reference_path(html_relative, url, source_root)
        if resolved is None:
            return url
        relative, resource_path = resolved
        resource_digest = hashlib.sha256(resource_path.read_bytes()).hexdigest()
        resources[relative] = resource_digest
        leading = url[: len(url) - len(url.lstrip())]
        trailing = url[len(url.rstrip()) :]
        return f"{leading}{_with_hash_query(stripped, resource_digest)}{trailing}"

    def replace_attribute(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{rewrite_url(match.group('url'))}{match.group('quote')}"

    def replace_css(match: re.Match[str]) -> str:
        return (
            f"{match.group('prefix')}"
            f"{rewrite_url(match.group('url'))}"
            f"{match.group('quote')}"
            f"{match.group('suffix')}"
        )

    rewritten = _ATTRIBUTE_URL.sub(replace_attribute, content)
    rewritten = _CSS_URL.sub(replace_css, rewritten)
    return rewritten, skipped_non_local


def _atomic_write_report(report_path: Path, payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="xb",
            dir=report_path.parent,
            prefix=f".{report_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, report_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def build_static_tree(source: Path | str, output: Path | str, report: Path | str) -> dict[str, object]:
    """Build a deterministic static tree and atomically publish its report.

    The source is never written.  Output and report must not already exist.
    Absolute host paths are deliberately excluded from both successful reports
    and sanitized exceptions.
    """

    source_root, output_root, report_path = _validate_paths(Path(source), Path(output), Path(report))
    source_digest = _tree_digest(source_root)
    resources: dict[str, str] = {}
    changed_html: list[str] = []
    html_count = 0
    skipped_external_count = 0

    try:
        _copy_tree(source_root, output_root)
        html_files = [
            (relative, path)
            for relative, path in _iter_tree(source_root)
            if path.suffix.lower() == ".html"
        ]
        for relative, source_html in html_files:
            html_count += 1
            try:
                original_bytes = source_html.read_bytes()
                original = original_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise StaticBuildError("html-not-utf8", relative) from exc
            rewritten, skipped = _rewrite_html(original, relative, source_root, resources)
            skipped_external_count += skipped
            rewritten_bytes = rewritten.encode("utf-8")
            if rewritten_bytes != original_bytes:
                (output_root / Path(relative)).write_bytes(rewritten_bytes)
                changed_html.append(relative)

        payload: dict[str, object] = {
            "builder_version": BUILDER_VERSION,
            "html_file_count": html_count,
            "modified_html": sorted(changed_html),
            "output_tree_digest": _tree_digest(output_root),
            "resources": [
                {"path": relative, "sha256": resources[relative]}
                for relative in sorted(resources)
            ],
            "result": "pass",
            "schema_version": SCHEMA_VERSION,
            "skipped_external_url_count": skipped_external_count,
            "source_tree_digest": source_digest,
            "static_resource_count": len(resources),
            "unresolved_references": [],
            "warnings": [],
        }
        _atomic_write_report(report_path, payload)
        return payload
    except Exception:
        if output_root.exists():
            shutil.rmtree(output_root)
        raise
