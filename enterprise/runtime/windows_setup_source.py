"""Resolve the running Inno wrapper from its authenticated pipe client.

Inno's UI runs in an extracted .tmp executable; retaining that executable would
lose the embedded payload. Only the live, immediate wrapper parent is accepted.
No arbitrary file path is supplied by a maintenance request.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path

from enterprise.runtime.ownership import process_identity, same_process


def authenticated_setup_executable(client):
    from enterprise.install_setup_bridge import SetupBridgeError
    def fail():
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_FAILED")
    if os.name != "nt" or client is None or not same_process(client, process_identity(client.pid)):
        fail()
    image = Path(client.executable)
    if image.suffix.casefold() == ".exe":
        return image
    if image.suffix.casefold() != ".tmp":
        fail()
    class Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("image", wintypes.WCHAR * 260)]
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        fn = getattr(api, name)
        fn.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry)); fn.restype = wintypes.BOOL
    api.CloseHandle.argtypes = (wintypes.HANDLE,); api.CloseHandle.restype = wintypes.BOOL
    snapshot = api.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        fail()
    try:
        entry = Entry(); entry.size = ctypes.sizeof(entry)
        found = api.Process32FirstW(snapshot, ctypes.byref(entry))
        parent_id = None
        while found:
            if entry.pid == client.pid:
                parent_id = int(entry.parent); break
            found = api.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        api.CloseHandle(snapshot)
    parent = process_identity(parent_id)
    if (parent is None or parent.created_at > client.created_at
            or Path(parent.executable).suffix.casefold() != ".exe"
            or not same_process(client, process_identity(client.pid))
            or not same_process(parent, process_identity(parent.pid))):
        fail()
    return Path(parent.executable)
