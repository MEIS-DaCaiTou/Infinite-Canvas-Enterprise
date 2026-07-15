"""Windows-safe assertions for temporary test resources.

SQLite keeps database handles open on Windows until the owning connection is
explicitly closed. These assertions make that requirement observable without
using deletion retries or cleanup-error suppression.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path


SQLITE_FILE_SUFFIXES = (".db", ".db-wal", ".db-shm")


def assert_file_releasable(path: Path, *, unlink: bool = False) -> None:
    """Require a fixture file to support an immediate same-directory rename."""
    if not path.exists():
        return
    probe = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.release-probe")
    moved = False
    try:
        os.replace(path, probe)
        moved = True
        os.replace(probe, path)
        moved = False
        if unlink:
            path.unlink()
    except OSError as exc:
        raise AssertionError(f"temporary fixture file remains locked: {path}") from exc
    finally:
        if moved and probe.exists() and not path.exists():
            os.replace(probe, path)


def assert_sqlite_files_releasable(root: Path, *, unlink: bool = False) -> list[Path]:
    """Assert that every SQLite database and sidecar below ``root`` is released."""
    files = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.name.casefold().endswith(SQLITE_FILE_SUFFIXES)
        ),
        key=lambda path: path.as_posix(),
    )
    for path in files:
        assert_file_releasable(path, unlink=unlink)
    return files
