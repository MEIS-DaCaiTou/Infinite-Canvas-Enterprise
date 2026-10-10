"""Bounded mutual exclusion for one update handoff's commit/status decision.

Windows uses a session-local, non-inheritable named mutex. The non-Windows
fallback synchronizes threads in this process only; it proves no Windows or
cross-process capability. This module does not read or write persistent state.
"""

from __future__ import annotations

import ctypes
import math
import os
import re
import threading
from ctypes import wintypes

_WAIT_OBJECT_0 = 0
_WAIT_ABANDONED = 0x80
_MAX_TIMEOUT_SECONDS = 2.0
_LOCAL_LOCKS = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


class HandoffCommitUnavailable(RuntimeError):
    """The commit gate's ownership or cleanup could not be confirmed."""


def _kernel32():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    api.CreateMutexW.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    api.ReleaseMutex.restype = wintypes.BOOL
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    return api


class HandoffCommitGate:
    """Serialize the decision for a validated job, on the acquiring thread.

    Only an ordinary successful wait permits the body to execute. An abandoned
    mutex grants ownership but does not prove protected state consistency, so
    it is released and rejected. Acquiring the gate never authorizes an update;
    callers must validate and persist their decision while they hold it.
    """

    def __init__(self, job_id: str, timeout_seconds: float = 2) -> None:
        if type(job_id) is not str or re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
            raise ValueError("job identity is invalid")
        if (type(timeout_seconds) not in (int, float)
                or (type(timeout_seconds) is float and not math.isfinite(timeout_seconds))
                or timeout_seconds < 0):
            raise ValueError("timeout must be finite and nonnegative")
        self._job_id = job_id
        self._timeout = float(min(timeout_seconds, _MAX_TIMEOUT_SECONDS))
        self._name = "Local\\InfiniteCanvas.UpdateHandoffCommit." + job_id
        self._api = None
        self._handle = None
        self._owned = False
        self._local_lock = None

    def __enter__(self):
        if self._handle is not None or self._local_lock is not None:
            raise HandoffCommitUnavailable("commit gate is already active")
        if os.name != "nt":
            with _LOCAL_LOCKS_GUARD:
                lock = _LOCAL_LOCKS.setdefault(self._job_id, threading.RLock())
            if not lock.acquire(timeout=self._timeout):
                raise HandoffCommitUnavailable("commit gate acquisition was not confirmed")
            self._local_lock = lock
            return self
        try:
            self._api = _kernel32()
            self._handle = self._api.CreateMutexW(None, False, self._name)
            if not self._handle:
                raise HandoffCommitUnavailable("commit mutex could not be created or opened")
            status = self._api.WaitForSingleObject(
                self._handle, math.ceil(self._timeout * 1000))
            if type(status) is not int:
                raise HandoffCommitUnavailable("commit mutex wait result is unknown")
            self._owned = status in (_WAIT_OBJECT_0, _WAIT_ABANDONED)
            if status != _WAIT_OBJECT_0:
                raise HandoffCommitUnavailable("commit mutex acquisition was not confirmed")
            return self
        except OSError as exc:
            try:
                self._close_windows()
            finally:
                raise HandoffCommitUnavailable("commit mutex operation could not be confirmed") from exc
        except BaseException:
            self._close_windows()
            raise

    def _close_windows(self) -> None:
        api, handle, owned = self._api, self._handle, self._owned
        self._api = None
        self._handle = None
        self._owned = False
        if not handle:
            return
        try:
            try:
                if owned and not api.ReleaseMutex(handle):
                    raise HandoffCommitUnavailable("commit mutex ownership could not be released")
            finally:
                if not api.CloseHandle(handle):
                    raise HandoffCommitUnavailable("commit mutex handle could not be closed")
        except OSError as exc:
            raise HandoffCommitUnavailable("commit mutex cleanup could not be confirmed") from exc

    def __exit__(self, *_exc) -> bool:
        if self._local_lock is not None:
            lock = self._local_lock
            self._local_lock = None
            try:
                lock.release()
            except RuntimeError as exc:
                raise HandoffCommitUnavailable("commit gate ownership could not be released") from exc
        else:
            self._close_windows()
        return False
