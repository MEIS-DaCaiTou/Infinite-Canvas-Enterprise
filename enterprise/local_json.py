"""Atomic replacement for local business JSON; callers own paths and locking."""
from __future__ import annotations

import json
import errno
import os
import time
from pathlib import Path
from threading import RLock
from uuid import uuid4
from contextlib import contextmanager
from threading import local
from enterprise.runtime import performance

_IO_LOCK = RLock()
_DOCUMENT_LOCKS = {}
_DOCUMENT_STATE = local()


@contextmanager
def document_lock(path, *, timeout=10):
    """Serialize a document's read/modify/write across Gateway and upstream.

    Keep the sidecar inode stable. Nested operations in the same thread reuse
    the lease; callers still use atomic_write_json to publish complete bytes.
    """
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _IO_LOCK:
        guard = _DOCUMENT_LOCKS.setdefault(key, RLock())
    waiting = time.perf_counter()
    with guard:
        held = getattr(_DOCUMENT_STATE, 'held', None)
        if held is None:
            held = _DOCUMENT_STATE.held = set()
        if key in held:
            yield
            return
        lock_path = Path(key + '.lock')
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open('a+b') as stream:
            if not stream.seek(0, os.SEEK_END):
                stream.write(b'\0')
                stream.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Document is busy; retry without discarding local changes') from exc
                    time.sleep(.02)
            performance.observe("json.lock_wait", (time.perf_counter()-waiting)*1000)
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


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


@performance.timed("json.read")
def read_json(path):
    """Read a complete document, including during another thread's replacement."""
    def read():
        with Path(path).open(encoding="utf-8") as stream:
            return json.load(stream)
    with _IO_LOCK:
        return _sharing_retry(read)


@performance.timed("json.write")
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
