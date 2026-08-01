from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Protocol


_WINDOWS_CREDENTIAL_TARGET_PREFIX = "tradingSystem/"
_WINDOWS_ERROR_NOT_FOUND = 1168
_WINDOWS_GENERIC_CREDENTIAL = 1


class CredentialAdapter(Protocol):
    def get(self, scope: str) -> str | None: ...


class CredentialStoreReadError(RuntimeError):
    code = "CREDENTIAL_STORE_READ_FAILED"
    substep = "windows_credential_manager"
    cause_type = "OSError"

    def __init__(self, native_error_code: int) -> None:
        super().__init__(
            f"Windows Credential Manager read failed ({native_error_code})."
        )


class _EnvironmentCredentialSource:
    def get(self, scope: str) -> str | None:
        return os.environ.get(scope)


class _WindowsCredentialSource:
    """Read the namespaced Generic credential without logging its value."""

    class _Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    def get(self, scope: str) -> str | None:
        if os.name != "nt":
            return None
        pointer = ctypes.POINTER(self._Credential)()
        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(self._Credential)),
        ]
        api.CredReadW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        target = _WINDOWS_CREDENTIAL_TARGET_PREFIX + scope
        if not api.CredReadW(
            target,
            _WINDOWS_GENERIC_CREDENTIAL,
            0,
            ctypes.byref(pointer),
        ):
            error_code = ctypes.get_last_error()
            if error_code == _WINDOWS_ERROR_NOT_FOUND:
                return None
            raise CredentialStoreReadError(error_code)
        try:
            credential = pointer.contents
            payload = ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            return payload.decode("utf-16-le")
        finally:
            api.CredFree(ctypes.cast(pointer, ctypes.c_void_p))


class LocalCredentialAdapter:
    """Resolve one local credential behind a single production policy.

    A present process variable is authoritative, including an explicit blank
    value that disables secure-store fallback. When the variable is absent,
    the namespaced Windows Credential Manager entry is the persistent source.
    """

    def __init__(
        self,
        environment: CredentialAdapter | None = None,
        secure_store: CredentialAdapter | None = None,
    ) -> None:
        self._environment = (
            environment if environment is not None else _EnvironmentCredentialSource()
        )
        self._secure_store = (
            secure_store if secure_store is not None else _WindowsCredentialSource()
        )

    def get(self, scope: str) -> str | None:
        process_value = self._environment.get(scope)
        if process_value is not None:
            return process_value
        return self._secure_store.get(scope)
