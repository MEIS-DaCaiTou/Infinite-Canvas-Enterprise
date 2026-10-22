"""Windows current-user DPAPI adapter, without an extra runtime dependency.

Ciphertext is bound to source and revision. No plaintext fallback. A different
Windows service identity/machine needs an explicitly designed credential
re-provisioning step; copying the database alone does not transfer secrets.
"""
import ctypes
from ctypes import wintypes
import os


class VaultUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('CREDENTIAL_VAULT_UNAVAILABLE')


class WindowsCredentialVault:
    def _transform(self, value: bytes, binding: str, *, decrypt: bool) -> bytes:
        if os.name != 'nt' or not isinstance(value, bytes) or not value or len(value) > 32768:
            raise VaultUnavailable()

        class Blob(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]

        buffers = []
        def blob(raw):
            buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
            buffers.append(buffer)  # Keep input memory alive through the native call.
            return Blob(len(raw), buffer)

        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        incoming, entropy, outgoing = blob(value), blob(binding.encode('utf8')), Blob()
        description = ctypes.c_void_p()
        operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                              ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        operation.restype = wintypes.BOOL
        try:
            ok = operation(ctypes.byref(incoming), ctypes.byref(description) if decrypt else None,
                           ctypes.byref(entropy), None, None, 1, ctypes.byref(outgoing))
            if not ok:
                raise VaultUnavailable()
            return ctypes.string_at(outgoing.pbData, outgoing.cbData)
        finally:
            if outgoing.pbData:
                kernel.LocalFree(outgoing.pbData)
            if description.value:
                kernel.LocalFree(description)
            for buffer in buffers:
                ctypes.memset(buffer, 0, len(buffer))

    def seal(self, secret: str, binding: str) -> bytes:
        if not isinstance(secret, str) or not secret.strip() or len(secret) > 8192 or any(c in secret for c in '\r\n\x00'):
            raise ValueError('INVALID_CREDENTIAL_SECRET')
        return self._transform(secret.encode('utf8'), binding, decrypt=False)

    def open(self, ciphertext: bytes, binding: str) -> str:
        return self._transform(ciphertext, binding, decrypt=True).decode('utf8')
