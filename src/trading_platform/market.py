from __future__ import annotations

from typing import Protocol

from trading_platform.application.market_contracts import (
    BuildMarketSnapshotCommand,
    EvaluatePlanCommand,
)
from trading_platform.domain.market import (
    MarketError,
    MarketSnapshotView,
    PlanEvaluationView,
)
from trading_platform.domain.plans import (
    ActiveTradePlan,
    PlanValidationError,
    TradePlanVersion,
)


class MarketRepository(Protocol):
    def build_market_snapshot(
        self, command: BuildMarketSnapshotCommand
    ) -> MarketSnapshotView: ...
    def get_market_snapshot(self, market_snapshot_id: str) -> MarketSnapshotView: ...
    def save_plan_evaluation(
        self, evaluation: PlanEvaluationView
    ) -> PlanEvaluationView: ...
    def get_plan_evaluation(self, evaluation_id: str) -> PlanEvaluationView: ...


class PlanLookup(Protocol):
    def get_version(self, version_id: str) -> TradePlanVersion: ...

    def get_active_master_by_plan(self, plan_id: str) -> ActiveTradePlan: ...


class MarketEvaluationService:
    def __init__(self, repository: MarketRepository, plans: PlanLookup) -> None:
        self.repository = repository
        self.plans = plans

    def build_market_snapshot(
        self, command: BuildMarketSnapshotCommand
    ) -> MarketSnapshotView:
        return self.repository.build_market_snapshot(command)

    def evaluate_plan(self, command: EvaluatePlanCommand) -> PlanEvaluationView:
        try:
            version = self.plans.get_version(command.plan_version_id)
        except PlanValidationError as error:
            raise MarketError("PLAN_VERSION_NOT_ACTIVE") from error
        lifecycle = self.plans.get_active_master_by_plan(version.plan_id)
        if (
            lifecycle.version is None
            or lifecycle.version.plan_version_id != command.plan_version_id
        ):
            raise MarketError("PLAN_VERSION_NOT_ACTIVE")
        raise MarketError("PLAN_AST_V2_EVALUATOR_UNAVAILABLE")

    def get_market_snapshot(self, market_snapshot_id: str) -> MarketSnapshotView:
        return self.repository.get_market_snapshot(market_snapshot_id)

    def get_plan_evaluation(self, evaluation_id: str) -> PlanEvaluationView:
        return self.repository.get_plan_evaluation(evaluation_id)
