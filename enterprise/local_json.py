"""Atomic replacement for local business JSON; callers own paths and locking."""
from __future__ import annotations

import json
import errno
import os
import time
from pathlib import Path
from threading import RLock
from uuid import uuid4

_IO_LOCK = RLock()


def _sharing_retry(operation):
    # Replacement and opening a replaced file can both encounter a transient
    # Windows sharing violation. Do not retry malformed JSON or other I/O errors.
    for delay in (0.005, 0.01, 0.02, None):
        try:
            return operation()
        except PermissionError as exc:
            sharing = getattr(exc, "winerror", None) in {5, 32, 33}
            # CRT fopen reports EACCES without winerror while MoveFileEx has the
            # destination delete-pending. A lasting ACL failure still surfaces.
            sharing = sharing or (os.name == "nt" and exc.errno == errno.EACCES)
            if not sharing or delay is None:
                raise
            time.sleep(delay)


def read_json(path):
    """Read a complete document, including during another thread's replacement."""
    def read():
        with Path(path).open(encoding="utf-8") as stream:
            return json.load(stream)
    with _IO_LOCK:
        return _sharing_retry(read)


def atomic_write_json(path, payload, *, indent=2, create_parent=False):
    """Leave the previous file intact if serialization or replacement fails.

    A sibling temporary file keeps replacement on the same volume. This is a
    single-file commit, not a multi-file transaction or a backup mechanism.
    """
    target = Path(path)
    if create_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False, indent=indent)
            stream.flush()
            os.fsync(stream.fileno())
        # Readers in this process must release their CRT handles before replace.
        # Serialization/fsync stay outside this short publication lock.
        with _IO_LOCK:
            _sharing_retry(lambda: os.replace(temporary, target))
    finally:
        temporary.unlink(missing_ok=True)
