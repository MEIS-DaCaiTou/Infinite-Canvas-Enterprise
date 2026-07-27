"""Writable-root probe primitive for ENV-1B1C-B1."""

from __future__ import annotations

import os
import re
import secrets
import stat
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

    def validated(self) -> "WritableProbeResult":
        if self.schema_version != PROBE_SCHEMA_VERSION or self.root_label not in WRITABLE_PROBE_LABELS or self.created is not True or self.cleaned_up is not True:
            raise RuntimeContractError("STARTUP_PREFLIGHT_INVALID")
        return self

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


def _descriptor_identity(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _owned(path: Path, identity: tuple[int, int] | None, token: bytes) -> bool:
    if identity is None:
        return False
    try:
        if _identity(path) != identity or has_reparse_point(path):
            return False
        info = os.lstat(path)
        if not os.path.isfile(path) or not stat.S_ISREG(info.st_mode):
            return False
        return _read_exact_bounded(path, len(token)) == token
    except (OSError, PathSafetyError):
        return False


def _token_only_owned(path: Path, token: bytes) -> bool:
    """Conservative recovery after descriptor identity acquisition failed."""

    if not token:
        return False
    try:
        if has_reparse_point(path):
            return False
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            return False
        return _read_exact_bounded(path, len(token)) == token
    except (OSError, PathSafetyError):
        return False


def _read_exact_bounded(path: Path, expected_length: int) -> bytes | None:
    """Read no more than the token length plus a mismatch byte."""

    fd: int | None = None
    try:
        fd = os.open(path, os.O_RDONLY)
        data = os.read(fd, expected_length + 1)
        return None if len(data) > expected_length else data
    except OSError:
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                return None


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
    suffix = name_factory() if name_factory is not None else secrets.token_hex(16)
    if not isinstance(suffix, str) or not _SUFFIX_RE.fullmatch(suffix):
        raise RuntimeContractError("WRITABLE_PROBE_LABEL_INVALID")
    path = root / f"{PROBE_PREFIX}{root_label.lower()}-{suffix}.tmp"
    created = False
    file_identity: tuple[int, int] | None = None
    token = b"ice-probe-v1:" + secrets.token_hex(16).encode("ascii") + b"\n"
    expected_content = b""
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
                written = handle.write(token)
                if written != len(token):
                    expected_content = token[: max(0, int(written))]
                    raise OSError("short probe write")
                expected_content = token
            except OSError as exc:
                # A failed write can leave an empty or partial file.  Obtain
                # identity from the still-open exclusive-create descriptor so
                # final cleanup can remove only this invocation's pathname.
                try:
                    file_identity = _descriptor_identity(handle.fileno())
                except OSError as identity_exc:
                    raise RuntimeContractError("WRITABLE_PROBE_IDENTITY_FAILED", details={"label": root_label}) from identity_exc
                raise RuntimeContractError("WRITABLE_PROBE_WRITE_FAILED", details={"label": root_label}) from exc
            try:
                handle.flush()
            except OSError as exc:
                raise RuntimeContractError("WRITABLE_PROBE_WRITE_FAILED", details={"label": root_label}) from exc
            try:
                # The first identity comes from the exclusive-create handle,
                # not a later pathname stat that can race replacement.
                file_identity = _descriptor_identity(handle.fileno())
            except OSError as exc:
                raise RuntimeContractError("WRITABLE_PROBE_IDENTITY_FAILED", details={"label": root_label}) from exc
            try:
                os.fsync(handle.fileno())
            except OSError as exc:
                raise RuntimeContractError("WRITABLE_PROBE_FSYNC_FAILED", details={"label": root_label}) from exc
        try:
            reparse = has_reparse_point(path)
            owned = _owned(path, file_identity, expected_content)
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
    except RuntimeContractError:
        raise
    except OSError as exc:
        # All other write-stage operations are individually mapped above.  An
        # OSError escaping the context manager here is its close/__exit__
        # failure; preserve no host diagnostic in the public contract.
        raise RuntimeContractError("WRITABLE_PROBE_CLOSE_FAILED", details={"label": root_label}) from exc
    finally:
        owned_for_cleanup = _owned(path, file_identity, expected_content)
        if created and file_identity is None:
            # Descriptor identity was unavailable. The unique per-call token
            # still distinguishes our fully written file from a replacement;
            # if that proof fails, retain the pathname rather than deleting a
            # possible foreign file.
            owned_for_cleanup = _token_only_owned(path, expected_content)
        if created and owned_for_cleanup:
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
