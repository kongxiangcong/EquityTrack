from __future__ import annotations

import hashlib
from dataclasses import dataclass

from trading_platform.data.providers import TushareCompatibleProvider
from trading_platform.identity import canonical_hash
from trading_platform.provider_config import (
    DecodedProviderJob,
    ProviderRuntimeBinding,
    validate_preconfigured_source_policy,
)


@dataclass(frozen=True)
class LoopbackTushareRuntime:
    """Deterministic external-seam adapter for local HTTP contract tests."""

    endpoint: str
    credential: str = "secret-not-for-artifacts"

    def bind(self, decoded: DecodedProviderJob) -> ProviderRuntimeBinding:
        validate_preconfigured_source_policy(decoded)
        provider = TushareCompatibleProvider(
            decoded.provider_id,
            decoded.adapter_version,
            self.endpoint,
            self.credential,
            decoded.source_policy.source_identity,
            decoded.source_policy.terms_profile,
            source_authority=decoded.source_policy.source_authority,
        )
        return ProviderRuntimeBinding(
            provider,
            hashlib.sha256(decoded.credential_variable.encode()).hexdigest(),
            decoded.credential_variable,
            canonical_hash(
                {
                    "provider_id": decoded.provider_id,
                    "adapter_version": decoded.adapter_version,
                    "destination": self.endpoint,
                }
            ),
            "test_loopback",
        )
