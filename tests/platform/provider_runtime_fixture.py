from __future__ import annotations

import hashlib
from typing import Any, Callable, Mapping

from trading_platform.data.kimi_agentgw import KimiAgentGatewayProvider
from trading_platform.provider_config import (
    DecodedProviderJob,
    ProviderRuntimeBinding,
    validate_kimi_agentgw_source_policy,
)


class _FakeTools:
    def __init__(self, handler: Callable[[dict], Any]) -> None:
        self._handler = handler

    def call_data_source_tool(self, payload):
        return self._handler(payload)


class _FakeClient:
    def __init__(self, handler: Callable[[dict], Any]) -> None:
        self.tools = _FakeTools(handler)


class FakeAgentGwRuntime:
    """Deterministic external-seam adapter for agent-gw contract tests.

    ``handler`` receives the ``call_data_source_tool`` payload and returns an
    object with a ``raw`` mapping, mirroring the ``agent_gw`` SDK response.
    """

    def __init__(self, handler: Callable[[dict], Any]) -> None:
        self._handler = handler

    def bind(self, decoded: DecodedProviderJob) -> ProviderRuntimeBinding:
        validate_kimi_agentgw_source_policy(decoded)
        security_identity = decoded.job.security_identity
        resolver = (
            (lambda security_id: (security_identity.code, security_identity.market))
            if security_identity is not None
            else None
        )
        provider = KimiAgentGatewayProvider(
            decoded.provider_id,
            decoded.adapter_version,
            decoded.source_policy.source_identity,
            decoded.source_policy.terms_profile,
            client_factory=lambda: _FakeClient(self._handler),
            source_authority=decoded.source_policy.source_authority,
            forecast_security_resolver=resolver,
        )
        return ProviderRuntimeBinding(
            provider,
            hashlib.sha256(decoded.credential_variable.encode()).hexdigest(),
            decoded.credential_variable,
            provider.transport_identity,
            "test_loopback",
            decoded.source_policy,
        )


def csv_response(headers: list[str], rows: list[list[object]]) -> Mapping[str, Any]:
    lines = [",".join(headers)]
    lines.extend(",".join(str(value) for value in row) for row in rows)
    content = "\n".join(lines) + "\n"
    return {
        "is_success": True,
        "files": [{"name": "virtual.csv", "content": content}],
        "result": {"assistant": []},
    }


class RawResponse:
    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.raw = raw
