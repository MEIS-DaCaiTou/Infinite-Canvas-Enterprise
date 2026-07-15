"""Process and port ownership checks used before lifecycle actions."""

from __future__ import annotations

import ctypes
import os
import subprocess
from dataclasses import asdict, dataclass
from ctypes import wintypes
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created_at: int
    executable: str

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortListenerSnapshot:
    """Raw listener evidence without treating an unqueryable PID as absent."""

    port: int
    listener_pids: tuple[int, ...]
    resolved_identities: tuple[ProcessIdentity, ...]
    unresolved_listener_pids: tuple[int, ...]
    inspection_failed: bool = False

    @property
    def has_listeners(self) -> bool:
        return bool(self.listener_pids)

    @property
    def is_empty(self) -> bool:
        return not self.inspection_failed and not self.listener_pids

    def snapshot(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "listener_pids": list(self.listener_pids),
            "resolved_identities": [identity.snapshot() for identity in self.resolved_identities],
            "unresolved_listener_pids": list(self.unresolved_listener_pids),
            "inspection_failed": self.inspection_failed,
        }


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _SYNCHRONIZE = 0x00100000

    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    )
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


def _filetime_to_ticks(value: Any) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def pid_exists(pid: object) -> bool:
    if type(pid) is not int or pid < 1:
        return False
    if os.name == "nt":
        handle = _kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            return _kernel32.WaitForSingleObject(handle, 0) == 0x00000102
        finally:
            _kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def process_identity(pid: object) -> ProcessIdentity | None:
    """Return PID, creation tick and executable path without command-line capture."""
    if type(pid) is not int or pid < 1:
        return None
    if os.name != "nt":
        if not pid_exists(pid):
            return None
        executable = ""
        proc_exe = Path("/proc") / str(pid) / "exe"
        try:
            executable = str(proc_exe.resolve())
        except OSError:
            executable = ""
        try:
            created_at = int((Path("/proc") / str(pid)).stat().st_ctime_ns)
        except OSError:
            created_at = 0
        return ProcessIdentity(pid=pid, created_at=created_at, executable=executable)

    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid)
    if not handle:
        return None
    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not _kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        size = ctypes.c_uint32(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return ProcessIdentity(pid=pid, created_at=_filetime_to_ticks(created), executable=str(Path(buffer.value).resolve()))
    finally:
        _kernel32.CloseHandle(handle)


def same_process(expected: ProcessIdentity | None, actual: ProcessIdentity | None) -> bool:
    if expected is None or actual is None:
        return False
    return (
        expected.pid == actual.pid
        and expected.created_at == actual.created_at
        and expected.executable.casefold() == actual.executable.casefold()
    )


def inspect_port_listeners(port: int) -> PortListenerSnapshot:
    """Inspect TCP listeners through one fixed OS command, never a shell string."""
    if type(port) is not int or port < 1 or port > 65535:
        raise ValueError("port is invalid")
    if os.name != "nt":
        return PortListenerSnapshot(port, (), (), (), False)
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return PortListenerSnapshot(port, (), (), (), True)
    if getattr(result, "returncode", 0) != 0:
        return PortListenerSnapshot(port, (), (), (), True)
    found: set[int] = set()
    marker = f":{port}"
    for raw_line in result.stdout.splitlines():
        fields = raw_line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP" or fields[-2].upper() != "LISTENING":
            continue
        local_address = fields[1]
        if not local_address.endswith(marker):
            continue
        try:
            found.add(int(fields[-1]))
        except ValueError:
            continue
    pids = tuple(sorted(found))
    resolved: list[ProcessIdentity] = []
    unresolved: list[int] = []
    for pid in pids:
        identity = process_identity(pid)
        if identity is None:
            unresolved.append(pid)
        else:
            resolved.append(identity)
    return PortListenerSnapshot(port, pids, tuple(resolved), tuple(unresolved), False)


def listening_port_pids(port: int) -> set[int]:
    """Compatibility view of listener PIDs; callers needing safety use snapshots."""
    return set(inspect_port_listeners(port).listener_pids)


def port_identities(port: int) -> list[ProcessIdentity]:
    return list(inspect_port_listeners(port).resolved_identities)
