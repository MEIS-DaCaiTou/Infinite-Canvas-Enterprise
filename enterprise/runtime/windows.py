"""Windows Job Object support with a harmless non-Windows fallback."""

from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes


class JobObjectError(RuntimeError):
    pass


if os.name == "nt":
    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


def current_job_diagnostics() -> dict[str, object]:
    """Read only the calling process's immediate Job; never query ancestors.

    Missing/failed observations must not change process creation behaviour.
    No handles, names, paths, environment, or exception text are exported.
    """
    if os.name != "nt":
        return {}
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = ()
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
        kernel32.IsProcessInJob.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID)
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        in_job = wintypes.BOOL()
        if not kernel32.IsProcessInJob(kernel32.GetCurrentProcess(), None, ctypes.byref(in_job)):
            return {"job_query_ok": False, "job_query_winerror": ctypes.get_last_error()}
        result: dict[str, object] = {"process_in_job": bool(in_job.value), "job_query_ok": True}
        if in_job.value:
            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            if not kernel32.QueryInformationJobObject(None, 9, ctypes.byref(info), ctypes.sizeof(info), None):
                return {"process_in_job": True, "job_query_ok": False,
                        "job_query_winerror": ctypes.get_last_error()}
            result["job_limit_flags"] = int(info.BasicLimitInformation.LimitFlags)
        return result
    except OSError as exc:
        result = {"job_query_ok": False}
        if type(getattr(exc, "winerror", None)) is int:
            result["job_query_winerror"] = exc.winerror
        return result


class ProcessJob:
    """A service-host-owned kill-on-close Job Object.

    The short-lived `start` CLI never creates this object, so closing its
    console cannot terminate the independently hosted supervisor or children.
    """

    _KILL_ON_CLOSE = 0x00002000
    _EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self) -> None:
        self._handle: object | None = None
        if os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise JobObjectError("Windows Job Object could not be created")
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = self._KILL_ON_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            self._EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            kernel32.CloseHandle(handle)
            raise JobObjectError("Windows Job Object limits could not be configured")
        self._kernel32 = kernel32
        self._handle = handle

    def add(self, process: subprocess.Popen[bytes]) -> None:
        if self._handle is None:
            return
        if not self._kernel32.AssignProcessToJobObject(self._handle, wintypes.HANDLE(int(process._handle))):
            raise JobObjectError("child process could not be assigned to the service Job Object")

    def terminate(self, exit_code: int = 1) -> None:
        if self._handle is not None and not self._kernel32.TerminateJobObject(self._handle, int(exit_code)):
            raise JobObjectError("owned Job Object could not be terminated")

    def close(self) -> None:
        if self._handle is not None:
            if not self._kernel32.CloseHandle(self._handle):
                raise JobObjectError("owned Job Object could not be closed")
            self._handle = None
