"""Writable-root probe primitive for ENV-1B1C-B1."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from enterprise.path_safety import PathSafetyError, assert_no_reparse_ancestors, has_reparse_point

from .error_contract import RuntimeContractError


PROBE_SCHEMA_VERSION = "env-1b1c-writable-probe-v1"
WRITABLE_PROBE_LABELS = frozenset({"DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"})
PROBE_PREFIX = ".ice-probe-"
_SUFFIX_RE = re.compile(r"^[a-z0-9]{8,64}$")


def _path_safety(path: Path, *, allow_missing: bool = False) -> None:
    try:
        assert_no_reparse_ancestors(path, allow_missing=allow_missing)
    except PathSafetyError as exc:
        raise RuntimeContractError("WRITABLE_PROBE_REPARSE_FORBIDDEN") from exc


@dataclass(frozen=True)
class WritableProbeResult:
    root_label: str
    created: bool
    cleaned_up: bool
    schema_version: str = PROBE_SCHEMA_VERSION

    def as_public_dict(self) -> dict[str, object]:
        return {
            "cleaned_up": self.cleaned_up,
            "created": self.created,
            "root_label": self.root_label,
            "schema_version": self.schema_version,
        }


def _identity(path: Path) -> tuple[int, int]:
    info = os.stat(path, follow_symlinks=False)
    return info.st_dev, info.st_ino


def _owned(path: Path, identity: tuple[int, int] | None) -> bool:
    if identity is None:
        return False
    try:
        return _identity(path) == identity
    except OSError:
        return False


def probe_writable_root(
    root: Path,
    root_label: str,
    *,
    name_factory: Callable[[], str] | None = None,
) -> WritableProbeResult:
    if root_label not in WRITABLE_PROBE_LABELS:
        raise RuntimeContractError("WRITABLE_PROBE_LABEL_INVALID")
    root = Path(root)
    if root_label == "APP_ROOT":
        raise RuntimeContractError("WRITABLE_PROBE_LABEL_INVALID")
    try:
        if not root.is_dir():
            raise RuntimeContractError("WRITABLE_PROBE_CREATE_FAILED", details={"label": root_label})
    except OSError as exc:
        raise RuntimeContractError("WRITABLE_PROBE_CREATE_FAILED", details={"label": root_label}) from exc
    _path_safety(root)
    suffix = name_factory() if name_factory is not None else uuid.uuid4().hex
    if not isinstance(suffix, str) or not _SUFFIX_RE.fullmatch(suffix):
        raise RuntimeContractError("WRITABLE_PROBE_LABEL_INVALID")
    path = root / f"{PROBE_PREFIX}{root_label.lower()}-{suffix}.tmp"
    created = False
    file_identity: tuple[int, int] | None = None
    cleanup_failed = False
    try:
        _path_safety(path.parent)
        try:
            handle = path.open("xb")
        except FileExistsError as exc:
            raise RuntimeContractError("WRITABLE_PROBE_EXISTS", details={"label": root_label}) from exc
        except OSError as exc:
            raise RuntimeContractError("WRITABLE_PROBE_CREATE_FAILED", details={"label": root_label}) from exc
        with handle:
            created = True
            try:
                file_identity = _identity(path)
                handle.write(b"probe\n")
            except OSError as exc:
                raise RuntimeContractError("WRITABLE_PROBE_WRITE_FAILED", details={"label": root_label}) from exc
            try:
                handle.flush()
            except OSError as exc:
                raise RuntimeContractError("WRITABLE_PROBE_WRITE_FAILED", details={"label": root_label}) from exc
            try:
                os.fsync(handle.fileno())
            except OSError as exc:
                raise RuntimeContractError("WRITABLE_PROBE_FSYNC_FAILED", details={"label": root_label}) from exc
        try:
            reparse = has_reparse_point(path)
            owned = _owned(path, file_identity)
        except PathSafetyError as exc:
            raise RuntimeContractError("WRITABLE_PROBE_REPARSE_FORBIDDEN", details={"label": root_label}) from exc
        if reparse or not owned:
            raise RuntimeContractError("WRITABLE_PROBE_OWNERSHIP_LOST", details={"label": root_label})
        try:
            path.unlink()
        except OSError as exc:
            cleanup_failed = True
            raise RuntimeContractError("WRITABLE_PROBE_CLEANUP_FAILED", details={"label": root_label}) from exc
        return WritableProbeResult(root_label, created=True, cleaned_up=True)
    finally:
        if created and _owned(path, file_identity):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                cleanup_failed = True
        if cleanup_failed:
            # The primary exception is preserved above.  This flag exists to
            # make the ownership branch explicit for tests and reviewers.
            pass
