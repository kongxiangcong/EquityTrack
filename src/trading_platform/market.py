from __future__ import annotations

from typing import Protocol

from trading_platform.application.market_contracts import BuildMarketSnapshotCommand, EvaluatePlanCommand
from trading_platform.domain.market import MarketError, MarketSnapshotView, PlanEvaluationView, evaluate_rules
from trading_platform.domain.plans import ActivePlanView, PlanValidationError, TradePlanVersionView
from trading_platform.identity import canonical_hash


class MarketRepository(Protocol):
    def build_market_snapshot(self, command: BuildMarketSnapshotCommand) -> MarketSnapshotView: ...
    def get_market_snapshot(self, market_snapshot_id: str) -> MarketSnapshotView: ...
    def save_plan_evaluation(self, evaluation: PlanEvaluationView) -> PlanEvaluationView: ...
    def get_plan_evaluation(self, evaluation_id: str) -> PlanEvaluationView: ...


class PlanLookup(Protocol):
    def get_version(self, version_id: str) -> TradePlanVersionView: ...
    def get_lifecycle(self, plan_id: str) -> ActivePlanView: ...


class MarketEvaluationService:
    def __init__(self, repository: MarketRepository, plans: PlanLookup) -> None:
        self.repository = repository
        self.plans = plans

    def build_market_snapshot(self, command: BuildMarketSnapshotCommand) -> MarketSnapshotView:
        return self.repository.build_market_snapshot(command)

    def evaluate_plan(self, command: EvaluatePlanCommand) -> PlanEvaluationView:
        try:
            version = self.plans.get_version(command.plan_version_id)
        except PlanValidationError as error:
            raise MarketError("PLAN_VERSION_NOT_ACTIVE") from error
        lifecycle = self.plans.get_lifecycle(version.plan_id)
        if lifecycle.active_version is None or lifecycle.active_version.plan_version_id != command.plan_version_id:
            raise MarketError("PLAN_VERSION_NOT_ACTIVE")
        if command.evaluator_version != version.content.evaluator_policy_version or command.evaluation_policy_version not in {"evaluation-policy@1", "evaluation-policy@2"}:
            raise MarketError("EVALUATOR_OR_POLICY_UNAVAILABLE")
        market = self.repository.get_market_snapshot(command.market_snapshot_id)
        if market.security_id != version.content.security_id:
            raise MarketError("SNAPSHOT_SCOPE_MISMATCH")
        status, outcome, completeness, results = evaluate_rules(version.content, market)
        identity = canonical_hash({"plan_version_id": command.plan_version_id, "market_snapshot_id": command.market_snapshot_id, "evaluator_version": command.evaluator_version, "evaluation_policy_version": command.evaluation_policy_version})
        evaluation = PlanEvaluationView(f"plan_evaluation_{identity[:24]}", command.plan_version_id, command.market_snapshot_id, command.evaluator_version, command.evaluation_policy_version, status, outcome, completeness, results)
        return self.repository.save_plan_evaluation(evaluation)

    def get_market_snapshot(self, market_snapshot_id: str) -> MarketSnapshotView:
        return self.repository.get_market_snapshot(market_snapshot_id)

    def get_plan_evaluation(self, evaluation_id: str) -> PlanEvaluationView:
        return self.repository.get_plan_evaluation(evaluation_id)
