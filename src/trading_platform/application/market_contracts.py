from __future__ import annotations

from dataclasses import dataclass

from trading_platform.identity.code import CodeIdentity


@dataclass(frozen=True)
class BuildMarketSnapshotCommand:
    invocation_id: str
    security_id: str
    market_scope_id: str
    data_snapshot_id: str
    market_model_version: str
    freshness_policy_version: str
    code_identity: CodeIdentity


@dataclass(frozen=True)
class EvaluatePlanCommand:
    invocation_id: str
    plan_version_id: str
    market_snapshot_id: str
    evaluator_version: str
    evaluation_policy_version: str
