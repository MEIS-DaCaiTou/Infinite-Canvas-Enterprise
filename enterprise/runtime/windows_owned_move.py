"""Windows object-bound moves for installation lifecycle adapters.

Never copy across volumes, overwrite a destination, traverse a reparse point,
or delete a program tree. Business decisions belong to the Python caller.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import stat

from enterprise import install_cache as files


def _opened(path, expected, *, directory=False, marker=False):
    if os.name != "nt":
        raise files.CacheError("INSTALL_WINDOWS_REQUIRED")
    files._safe(path)
    kernel = files._kernel
    access = 0x00010000 | 0x00000080 | (0 if directory else 0x80000000)
    flags = 0x00200000 | (0x02000000 if directory else 0)
    handle = kernel.CreateFileW(str(files._io(path)), access, 3 if directory else 1,
                               None, 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise files.CacheError("INSTALL_LIFECYCLE_FILE_BUSY")
    try:
        info = files.FileInfo()
        if (not kernel.GetFileInformationByHandle(handle, ctypes.byref(info))
                or info.attributes & 0x400 or bool(info.attributes & 0x10) != directory):
            raise files.CacheError("INSTALL_LIFECYCLE_CHANGED")
        identity = files._handle_identity(handle)
        if directory:
            if identity != expected:
                raise files.CacheError("INSTALL_LIFECYCLE_CHANGED")
            return handle
        if info.links != (2 if marker else 1) or identity != expected["identity"]:
            raise files.CacheError("INSTALL_LIFECYCLE_CHANGED")
        import msvcrt
        # Read through this exact handle. Duplicate only for CRT ownership;
        # the original remains pinned until the rename/delete is committed.
        duplicate = files.wintypes.HANDLE()
        kernel.DuplicateHandle.argtypes = [files.wintypes.HANDLE, files.wintypes.HANDLE,
            files.wintypes.HANDLE, ctypes.POINTER(files.wintypes.HANDLE),
            files.wintypes.DWORD, files.wintypes.BOOL, files.wintypes.DWORD]
        kernel.DuplicateHandle.restype = files.wintypes.BOOL
        kernel.GetCurrentProcess.restype = files.wintypes.HANDLE
        process = kernel.GetCurrentProcess()
        if not kernel.DuplicateHandle(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
            raise files.CacheError("INSTALL_LIFECYCLE_CHANGED")
        try:
            fd = msvcrt.open_osfhandle(int(duplicate.value), os.O_RDONLY | os.O_BINARY)
        except Exception:
            kernel.CloseHandle(duplicate)
            raise
        digest, size = hashlib.sha256(), 0
        with os.fdopen(fd, "rb") as stream:
            observed = os.fstat(stream.fileno())
            if not stat.S_ISREG(observed.st_mode):
                raise files.CacheError("INSTALL_LIFECYCLE_CHANGED")
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                if size > files.MAX_FILE_BYTES:
                    raise files.CacheError("INSTALL_LIFECYCLE_LIMIT")
        if {"identity": identity, "size_bytes": size, "sha256": digest.hexdigest()} != expected:
            raise files.CacheError("INSTALL_LIFECYCLE_CHANGED")
        return handle
    except BaseException:
        kernel.CloseHandle(handle)
        raise


def rename_owned(path, destination, expected, *, directory=False):
    """Move one proven object on its current volume; no replacement or recursion."""
    handle = _opened(path, expected, directory=directory)
    try:
        files._safe(destination, missing=True)
        if (files._exists(destination)
                or files._identity(destination.parent)[0] != files._handle_identity(handle)[0]):
            raise files.CacheError("INSTALL_LIFECYCLE_CHANGED")
        name = str(files._io(destination))
        class RenameInfo(ctypes.Structure):
            _fields_ = [("replace", files.wintypes.BOOLEAN), ("root", files.wintypes.HANDLE),
                        ("length", files.wintypes.DWORD),
                        ("name", files.wintypes.WCHAR * (len(name) + 1))]
        value = RenameInfo(False, None, len(name.encode("utf-16-le")), name)
        if not files._kernel.SetFileInformationByHandle(handle, 3, ctypes.byref(value), ctypes.sizeof(value)):
            raise files.CacheError("INSTALL_LIFECYCLE_FILE_BUSY")
    finally:
        files._kernel.CloseHandle(handle)


def release_fence(path, expected):
    """Unlink only the active side of a proven two-link lifecycle fence."""
    handle = _opened(path, expected, marker=True)
    try:
        value = files.wintypes.BOOLEAN(1)
        if not files._kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(value), ctypes.sizeof(value)):
            raise files.CacheError("INSTALL_LIFECYCLE_FILE_BUSY")
    finally:
        files._kernel.CloseHandle(handle)
