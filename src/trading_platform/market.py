from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from trading_platform.application.market_contracts import (
    BuildMarketSnapshotCommand,
    EvaluatePlanCommand,
)
from trading_platform.domain.market import (
    Completeness,
    EvaluationStatus,
    MarketError,
    MarketSnapshotView,
    PlanEvaluationView,
)
from trading_platform.domain.conflicts import (
    ConflictInput,
    resolve_conflicts,
)
from trading_platform.domain.plans import (
    ActiveTradePlan,
    CoreSleeve,
    PlanValidationError,
    TradePlanGraph,
)
from trading_platform.domain.rules import (
    OperandState,
    OperandValue,
    RuleEvaluation,
    RuleResult,
    evaluate_rule,
)
from trading_platform.identity import canonical_hash


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
    def get_graph(self, version_id: str) -> TradePlanGraph: ...

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
        if (
            not command.invocation_id
            or len(
                {
                    operand.operand_id
                    for operand in command.operands
                }
            )
            != len(command.operands)
            or len(set(command.complete_sessions))
            != len(command.complete_sessions)
            or tuple(sorted(command.complete_sessions))
            != command.complete_sessions
            or any(
                operand.operand_id
                in {
                    "security.close_unadjusted",
                    "security.previous_close_unadjusted",
                }
                for operand in command.operands
            )
        ):
            raise MarketError("PLAN_EVALUATION_INPUT_INVALID")
        try:
            graph = self.plans.get_graph(command.plan_version_id)
        except PlanValidationError as error:
            raise MarketError("PLAN_VERSION_NOT_ACTIVE") from error
        version = graph.version
        lifecycle = self.plans.get_active_master_by_plan(version.plan_id)
        if (
            lifecycle.version is None
            or lifecycle.version.plan_version_id != command.plan_version_id
        ):
            raise MarketError("PLAN_VERSION_NOT_ACTIVE")
        market = self.repository.get_market_snapshot(
            command.market_snapshot_id
        )
        if (
            market.security_id
            != lifecycle.master.plan_id.security_id
        ):
            raise MarketError("PLAN_MARKET_SCOPE_MISMATCH")
        operands = {
            operand.operand_id: operand
            for operand in command.operands
        }
        operands.update(_market_operands(market))
        evaluations = tuple(
            _blocked_evaluation(rule, market)
            if market.status.value == "blocked"
            else evaluate_rule(
                rule_id=rule.rule_id,
                rule_class=rule.rule_class,
                condition=rule.condition,
                candidate_intent=rule.candidate_intent,
                operands=operands,
                complete_sessions=command.complete_sessions,
                event_windows=command.event_windows,
                observed_at=market.effective_session_date,
            )
            for rule in graph.rules
        )
        core = next(
            sleeve
            for sleeve in graph.sleeves
            if isinstance(sleeve, CoreSleeve)
        )
        resolution = resolve_conflicts(
            evaluations=tuple(
                ConflictInput(evaluation, rule.priority)
                for rule, evaluation in zip(
                    graph.rules, evaluations, strict=True
                )
            ),
            graph_valid=True,
            core_floor=core.core_floor.quantity,
            resource_conflict=command.resource_conflict,
        )
        completeness = (
            Completeness.PARTIAL
            if any(
                evaluation.result
                in {
                    RuleResult.UNABLE,
                    RuleResult.NOT_APPLICABLE,
                    RuleResult.BLOCKED,
                }
                for evaluation in evaluations
            )
            else Completeness.COMPLETE
        )
        identity = {
            "plan_version_id": version.plan_version_id,
            "market_snapshot_id": market.market_snapshot_id,
            "evaluator_version": "plan-evaluator@2",
            "evaluation_policy_version": "trade-plan-conflict@1",
            "rule_replay_hashes": tuple(
                item.replay_hash for item in evaluations
            ),
            "resolution_hash": resolution.content_hash,
        }
        evaluation_hash = canonical_hash(identity)
        view = PlanEvaluationView(
            plan_evaluation_id=(
                f"plan_evaluation_{evaluation_hash[:24]}"
            ),
            plan_version_id=version.plan_version_id,
            market_snapshot_id=market.market_snapshot_id,
            evaluator_version="plan-evaluator@2",
            evaluation_policy_version="trade-plan-conflict@1",
            status=(
                EvaluationStatus.BLOCKED
                if resolution.outcome.value == "blocked"
                else EvaluationStatus.COMPLETED
            ),
            completeness=completeness,
            rule_results=evaluations,
            resolution=resolution,
            evaluation_hash=evaluation_hash,
        )
        return self.repository.save_plan_evaluation(view)

    def get_market_snapshot(self, market_snapshot_id: str) -> MarketSnapshotView:
        return self.repository.get_market_snapshot(market_snapshot_id)

    def get_plan_evaluation(self, evaluation_id: str) -> PlanEvaluationView:
        return self.repository.get_plan_evaluation(evaluation_id)


def _market_operands(
    market: MarketSnapshotView,
) -> dict[str, OperandValue]:
    component = next(
        (
            item
            for item in market.components
            if item.component_id == "security.price_context"
        ),
        None,
    )
    if component is None or component.status.value == "blocked":
        return {}
    values = dict(component.values)
    result: dict[str, OperandValue] = {}
    for operand_id, key in (
        ("security.close_unadjusted", "close"),
        ("security.previous_close_unadjusted", "previous_close"),
    ):
        value = values.get(key)
        if value is not None:
            result[operand_id] = OperandValue(
                operand_id=operand_id,
                value_state=OperandState.KNOWN,
                value=Decimal(value),
                unit="CNY_per_share",
                currency="CNY",
                as_of_identity=market.market_snapshot_id,
                evidence_refs=component.evidence_refs,
            )
    return result


def _blocked_evaluation(rule, market) -> RuleEvaluation:
    blocker = next(
        (
            item
            for item in market.components
            if item.status.value == "blocked"
        ),
        None,
    )
    reason = (
        blocker.reason_code.value
        if blocker is not None
        else "MARKET_SNAPSHOT_BLOCKED"
    )
    payload = {
        "rule_id": rule.rule_id,
        "result": RuleResult.BLOCKED.value,
        "reason_code": reason,
        "observed_at": market.effective_session_date,
    }
    return RuleEvaluation(
        rule_id=rule.rule_id,
        result=RuleResult.BLOCKED,
        reason_code=reason,
        operands=(),
        candidate_intent=None,
        matched_grid_levels=(),
        observed_at=market.effective_session_date,
        evidence_refs=(
            blocker.evidence_refs if blocker is not None else ()
        ),
        replay_hash=canonical_hash(payload),
    )
