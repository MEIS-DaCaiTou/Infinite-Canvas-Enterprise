"""Shared fail-closed path inspection primitives for release contracts.

The helpers never resolve a path before inspecting its lexical components:
``Path.resolve`` can otherwise follow the very reparse point the caller is
trying to reject.  A missing component is only permitted when a caller
explicitly asks for a not-yet-created leaf; inspection errors always fail
closed.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


class PathSafetyError(RuntimeError):
    """A sanitized path-safety failure; callers map it to their own contract."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def has_reparse_point(path: Path) -> bool:
    """Return whether *path* is a symlink/reparse point, or fail closed."""

    try:
        metadata = os.lstat(path)
    except FileNotFoundError as exc:
        raise PathSafetyError("path-missing") from exc
    except OSError as exc:
        raise PathSafetyError("path-inspection-failed") from exc
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def assert_no_reparse_ancestors(path: Path, *, allow_missing: bool = False) -> None:
    """Reject a reparse point in any lexical component of an absolute path.

    ``allow_missing`` is for a new leaf only.  Once an absent component is
    encountered there cannot be an existing descendant to inspect, so the
    caller must still perform a post-create check before use.
    """

    absolute = Path(os.path.abspath(os.fspath(path)))
    parts = absolute.parts
    if not parts:
        raise PathSafetyError("path-inspection-failed")
    current = Path(parts[0])
    try:
        if has_reparse_point(current):
            raise PathSafetyError("path-reparse-forbidden")
    except PathSafetyError as exc:
        if allow_missing and exc.code == "path-missing":
            return
        raise
    for part in parts[1:]:
        current = current / part
        try:
            if has_reparse_point(current):
                raise PathSafetyError("path-reparse-forbidden")
        except PathSafetyError as exc:
            # A not-yet-created path is not an inspection error only when the
            # caller explicitly supports creation and the missing point is the
            # first absent lexical component.
            if allow_missing and exc.code == "path-missing":
                return
            raise


def assert_path_within_root(path: Path, root: Path) -> Path:
    """Return lexical absolute *path* after proving it stays beneath *root*."""

    absolute_root = Path(os.path.abspath(os.fspath(root)))
    absolute_path = Path(os.path.abspath(os.fspath(path)))
    try:
        common = os.path.commonpath((os.path.normcase(str(absolute_root)), os.path.normcase(str(absolute_path))))
    except ValueError as exc:  # different drives on Windows
        raise PathSafetyError("path-outside-root") from exc
    if common != os.path.normcase(str(absolute_root)):
        raise PathSafetyError("path-outside-root")
    return absolute_path
