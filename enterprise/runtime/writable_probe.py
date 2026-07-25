"""Writable-root probe primitive for ENV-1B1C-B1."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .error_contract import RuntimeContractError
from .runtime_manifest import assert_no_reparse_ancestors, has_reparse_point


PROBE_SCHEMA_VERSION = "env-1b1c-writable-probe-v1"
WRITABLE_PROBE_LABELS = frozenset({"DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"})
PROBE_PREFIX = ".ice-probe-"


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
    assert_no_reparse_ancestors(root, code="WRITABLE_PROBE_REPARSE_FORBIDDEN")
    if root_label == "APP_ROOT":
        raise RuntimeContractError("WRITABLE_PROBE_LABEL_INVALID")
    suffix = name_factory() if name_factory is not None else uuid.uuid4().hex
    if not isinstance(suffix, str) or not suffix or any(ch in suffix for ch in "\\/:"):
        raise RuntimeContractError("WRITABLE_PROBE_LABEL_INVALID")
    path = root / f"{PROBE_PREFIX}{root_label.lower()}-{suffix}.tmp"
    created = False
    file_identity: tuple[int, int] | None = None
    cleanup_failed = False
    try:
        assert_no_reparse_ancestors(path.parent, code="WRITABLE_PROBE_REPARSE_FORBIDDEN")
        with path.open("xb") as handle:
            created = True
            file_identity = _identity(path)
            handle.write(b"probe\n")
            try:
                handle.flush()
            except OSError as exc:
                raise RuntimeContractError("WRITABLE_PROBE_WRITE_FAILED", details={"label": root_label}) from exc
            try:
                os.fsync(handle.fileno())
            except OSError as exc:
                raise RuntimeContractError("WRITABLE_PROBE_FSYNC_FAILED", details={"label": root_label}) from exc
        if has_reparse_point(path) or not _owned(path, file_identity):
            raise RuntimeContractError("WRITABLE_PROBE_OWNERSHIP_LOST", details={"label": root_label})
        try:
            path.unlink()
        except OSError as exc:
            cleanup_failed = True
            raise RuntimeContractError("WRITABLE_PROBE_CLEANUP_FAILED", details={"label": root_label}) from exc
        return WritableProbeResult(root_label, created=True, cleaned_up=True)
    except FileExistsError as exc:
        raise RuntimeContractError("WRITABLE_PROBE_EXISTS", details={"label": root_label}) from exc
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
