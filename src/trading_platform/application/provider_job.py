from __future__ import annotations

from dataclasses import dataclass

from trading_platform.application.contracts import SecurityIdentity
from trading_platform.application.market_contracts import BuildMarketSnapshotCommand
from trading_platform.domain.research_evaluation import ResearchWorkflowRequest


@dataclass(frozen=True)
class ProviderJob:
    schema_version: str
    security_identity: SecurityIdentity | None
    security_invocation_id: str | None
    research_request: ResearchWorkflowRequest | None
    market_command: BuildMarketSnapshotCommand | None

    def __post_init__(self) -> None:
        if self.schema_version != "ProviderJob@2":
            raise ValueError("PROVIDER_JOB_SCHEMA_INVALID")
