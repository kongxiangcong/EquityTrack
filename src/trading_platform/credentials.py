from __future__ import annotations

import hashlib
import os
import ctypes
from ctypes import wintypes
from typing import Protocol


class CredentialAdapter(Protocol):
    def get(self, scope: str) -> str | None: ...


class EnvironmentCredentialAdapter:
    """Default replaceable adapter; values are never persisted or rendered."""

    def get(self, scope: str) -> str | None:
        return os.environ.get(scope)

    @staticmethod
    def status(scope: str) -> dict[str, str]:
        return {"credential_scope": hashlib.sha256(scope.encode()).hexdigest(), "status": "configured" if os.environ.get(scope) else "missing"}


class WindowsCredentialAdapter:
    """Reads a Generic credential from Windows Credential Manager without logging it."""

    class _Credential(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    def get(self, scope: str) -> str | None:
        if os.name != "nt": return None
        pointer = ctypes.POINTER(self._Credential)()
        advapi = ctypes.WinDLL("Advapi32.dll")
        if not advapi.CredReadW(scope, 1, 0, ctypes.byref(pointer)): return None
        try:
            credential = pointer.contents
            payload = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return payload.decode("utf-16-le")
        finally: advapi.CredFree(pointer)
