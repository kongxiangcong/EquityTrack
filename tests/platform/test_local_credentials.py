from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Callable

import pytest

import trading_platform.credentials as credential_module
from trading_platform.data.kimi_agentgw import (
    KimiAgentGatewayProvider,
    KimiAgentGwDetection,
)
from trading_platform.operations import PlatformOperations
from trading_platform.provider_config import (
    PreconfiguredKimiAgentGwRuntime,
    load_sync_job,
)


_KIMI_JOB = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "platform"
    / "kimi-agentgw-yihua-job.json"
)


class _AvailableAgentGwEnvironment:
    def detect(self) -> KimiAgentGwDetection:
        return KimiAgentGwDetection(True, "AGENTGW_AVAILABLE", "test-double")

    def build_client(self):  # pragma: no cover - bind never calls the network
        raise AssertionError("build_client must not run during bind")


def _kimi_runtime() -> PreconfiguredKimiAgentGwRuntime:
    return PreconfiguredKimiAgentGwRuntime(_AvailableAgentGwEnvironment())


def test_nonempty_environment_override_does_not_read_secure_store(
    monkeypatch,
) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "process-override")

    def unexpected_secure_store_read(_source: object, _scope: str) -> str | None:
        raise AssertionError("secure store must not be read")

    monkeypatch.setattr(
        credential_module._WindowsCredentialSource,
        "get",
        unexpected_secure_store_read,
    )

    assert (
        credential_module.LocalCredentialAdapter().get("KIMI_API_KEY")
        == "process-override"
    )


def test_default_local_credential_path_uses_windows_secure_store_when_environment_is_absent(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    secure_value = "secure-store-value-never-rendered"
    secure_reads: list[str] = []

    def read_secure_store(_source: object, scope: str) -> str | None:
        secure_reads.append(scope)
        return secure_value if scope == "KIMI_API_KEY" else None

    monkeypatch.setattr(
        credential_module._WindowsCredentialSource,
        "get",
        read_secure_store,
    )

    loaded = load_sync_job(_KIMI_JOB, provider_runtime=_kimi_runtime())
    assert isinstance(loaded.provider, KimiAgentGatewayProvider)

    operations = PlatformOperations(tmp_path / "data")
    operations.bootstrap()
    readiness = operations.doctor(_KIMI_JOB)["provider_readiness"]
    assert readiness["status"] == "configured"
    # doctor reads the scope twice: credential scopes plus provider readiness;
    # the agent-gw bind itself never touches the local credential adapter.
    assert secure_reads.count("KIMI_API_KEY") == 2


def test_explicit_blank_environment_scope_disables_secure_store_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "")
    secure_reads: list[str] = []

    def read_secure_store(_source: object, scope: str) -> str | None:
        secure_reads.append(scope)
        return "must-not-be-used"

    monkeypatch.setattr(
        credential_module._WindowsCredentialSource,
        "get",
        read_secure_store,
    )

    operations = PlatformOperations(tmp_path / "data")
    operations.bootstrap()
    readiness = operations.doctor(_KIMI_JOB)["provider_readiness"]
    assert readiness["status"] == "missing_credential"
    assert secure_reads == []


class _FakeFunction:
    def __init__(self, implementation: Callable[..., object]) -> None:
        self._implementation = implementation
        self.argtypes: list[object] = []
        self.restype: object | None = None

    def __call__(self, *args: object) -> object:
        return self._implementation(*args)


class _FakeCredentialApi:
    def __init__(
        self,
        read: Callable[..., object],
        free: Callable[..., object],
    ) -> None:
        self.CredReadW = _FakeFunction(read)
        self.CredFree = _FakeFunction(free)


class _MissingEnvironment:
    def get(self, _scope: str) -> str | None:
        return None


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager contract")
def test_windows_secure_store_uses_namespaced_target_and_frees_success(
    monkeypatch,
) -> None:
    source = credential_module._WindowsCredentialSource()
    payload = "secure-store-value-never-rendered".encode("utf-16-le")
    blob = ctypes.create_string_buffer(payload)
    credential = source._Credential()
    credential.CredentialBlobSize = len(payload)
    credential.CredentialBlob = ctypes.cast(
        blob,
        ctypes.POINTER(ctypes.c_ubyte),
    )
    credential_pointer = ctypes.pointer(credential)
    targets: list[str] = []
    freed: list[object] = []

    def read(
        target: str,
        credential_type: int,
        flags: int,
        output_pointer: object,
    ) -> bool:
        targets.append(target)
        assert credential_type == 1
        assert flags == 0
        ctypes.cast(
            output_pointer,
            ctypes.POINTER(ctypes.POINTER(source._Credential)),
        )[0] = credential_pointer
        return True

    monkeypatch.setattr(
        credential_module.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: _FakeCredentialApi(read, freed.append),
    )
    adapter = credential_module.LocalCredentialAdapter(
        environment=_MissingEnvironment(),
        secure_store=source,
    )

    assert adapter.get("KIMI_API_KEY") == payload.decode("utf-16-le")
    assert targets == ["tradingSystem/KIMI_API_KEY"]
    assert len(freed) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager contract")
@pytest.mark.parametrize(
    ("native_error", "expected"),
    (
        (1168, None),
        (5, "CREDENTIAL_STORE_READ_FAILED"),
    ),
)
def test_windows_secure_store_maps_native_failures(
    monkeypatch,
    native_error: int,
    expected: str | None,
) -> None:
    source = credential_module._WindowsCredentialSource()
    targets: list[str] = []
    freed: list[object] = []

    def read(
        target: str,
        _credential_type: int,
        _flags: int,
        _output_pointer: object,
    ) -> bool:
        targets.append(target)
        return False

    monkeypatch.setattr(
        credential_module.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: _FakeCredentialApi(read, freed.append),
    )
    monkeypatch.setattr(
        credential_module.ctypes,
        "get_last_error",
        lambda: native_error,
    )
    adapter = credential_module.LocalCredentialAdapter(
        environment=_MissingEnvironment(),
        secure_store=source,
    )

    if expected is None:
        assert adapter.get("KIMI_API_KEY") is None
    else:
        with pytest.raises(credential_module.CredentialStoreReadError) as captured:
            adapter.get("KIMI_API_KEY")
        assert captured.value.code == expected
        assert captured.value.substep == "windows_credential_manager"
    assert targets == ["tradingSystem/KIMI_API_KEY"]
    assert freed == []
