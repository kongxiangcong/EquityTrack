from __future__ import annotations

from dataclasses import dataclass

from trading_platform.application.contracts import SecurityIdentity
from trading_platform.application.market_contracts import BuildMarketSnapshotCommand
from trading_platform.domain.research_evaluation import ResearchWorkflowRequest


@dataclass(frozen=True)
class PlanEvaluationTemplate:
    invocation_id: str
    plan_version_id: str
    evaluator_version: str
    evaluation_policy_version: str

@dataclass(frozen=True)
class ProviderJob:
    schema_version: str
    security_identity: SecurityIdentity | None
    security_invocation_id: str | None
    research_request: ResearchWorkflowRequest | None
    market_command: BuildMarketSnapshotCommand | None
    evaluation_template: PlanEvaluationTemplate | None

    def __post_init__(self) -> None:
        if self.schema_version != "ProviderJob@2":
            raise ValueError("PROVIDER_JOB_SCHEMA_INVALID")
        if self.evaluation_template is not None and self.market_command is None:
            raise ValueError("PROVIDER_JOB_EVALUATION_WITHOUT_MARKET")
