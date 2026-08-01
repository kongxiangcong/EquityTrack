from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from trading_platform.domain.rules import (
    OperandState,
    RuleEvaluation,
    RulePriority,
    RuleResult,
)
from trading_platform.identity import canonical_hash


class ConflictPolicyV1(str, Enum):
    IDENTITY = "trade-plan-conflict@1"


class ResolutionOutcome(str, Enum):
    BLOCKED = "blocked"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    DECISION_TASK = "decision_task"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class ConflictInput:
    evaluation: RuleEvaluation
    priority: RulePriority


@dataclass(frozen=True)
class ConflictResolution:
    outcome: ResolutionOutcome
    reason_code: str
    selected_intent_id: str | None
    contributing_rule_ids: tuple[str, ...]
    policy_version: str
    content_hash: str


def resolve_conflicts(
    *,
    evaluations: tuple[ConflictInput, ...],
    graph_valid: bool,
    core_floor: Decimal,
    resource_conflict: bool = False,
) -> ConflictResolution:
    if not graph_valid or any(
        item.evaluation.result is RuleResult.BLOCKED
        for item in evaluations
    ):
        return _resolution(
            ResolutionOutcome.BLOCKED,
            "INVARIANT_CORRUPTION",
            None,
            evaluations,
        )
    triggered = tuple(
        item
        for item in evaluations
        if item.evaluation.result is RuleResult.TRIGGERED
        and item.evaluation.candidate_intent is not None
    )
    overriding = tuple(
        item
        for item in triggered
        if item.priority
        in {
            RulePriority.INVALIDATION,
            RulePriority.RISK,
            RulePriority.CORE_FLOOR,
        }
    )
    if overriding:
        return _resolution(
            ResolutionOutcome.MANUAL_REVIEW_REQUIRED,
            "RISK_INVALIDATION_OR_CORE_FLOOR_PRECEDENCE",
            None,
            overriding,
        )
    directions = {
        item.evaluation.candidate_intent.direction
        for item in triggered
        if item.evaluation.candidate_intent is not None
    }
    if {"increase", "decrease"} <= directions:
        return _resolution(
            ResolutionOutcome.MANUAL_REVIEW_REQUIRED,
            "OPPOSING_CANDIDATE_INTENTS",
            None,
            triggered,
        )
    if resource_conflict or any(
        _intent_has_unknown_resource(item.evaluation)
        for item in triggered
    ):
        return _resolution(
            ResolutionOutcome.MANUAL_REVIEW_REQUIRED,
            "RESOURCE_OPERAND_CONFLICT",
            None,
            triggered,
        )
    decreases = tuple(
        item
        for item in triggered
        if item.evaluation.candidate_intent is not None
        and item.evaluation.candidate_intent.direction == "decrease"
    )
    for item in decreases:
        remaining = item.evaluation.candidate_intent.remaining_quantity
        if (
            remaining.value_state is OperandState.KNOWN
            and isinstance(remaining.value, Decimal)
            and remaining.value < core_floor
        ):
            return _resolution(
                ResolutionOutcome.MANUAL_REVIEW_REQUIRED,
                "GRID_DECREASE_CROSSES_CORE_FLOOR",
                None,
                (item,),
            )
    if len(triggered) == 1:
        candidate = triggered[0]
        intent = candidate.evaluation.candidate_intent
        assert intent is not None
        if not intent.grid_level_ids:
            return _resolution(
                ResolutionOutcome.DECISION_TASK,
                "UNIQUE_CANDIDATE_ACTIONABLE",
                intent.intent_id,
                (candidate,),
            )
        if len(candidate.evaluation.matched_grid_levels) == 1:
            return _resolution(
                ResolutionOutcome.DECISION_TASK,
                "UNIQUE_GRID_LEVEL_ACTIONABLE",
                intent.intent_id,
                (candidate,),
            )
    if triggered:
        return _resolution(
            ResolutionOutcome.MANUAL_REVIEW_REQUIRED,
            "GRID_CANDIDATE_CARDINALITY_CONFLICT",
            None,
            triggered,
        )
    return _resolution(
        ResolutionOutcome.NO_ACTION,
        "NO_VALID_TRIGGER",
        None,
        evaluations,
    )


def _intent_has_unknown_resource(evaluation: RuleEvaluation) -> bool:
    intent = evaluation.candidate_intent
    return bool(
        intent
        and any(
            operand.value_state is not OperandState.KNOWN
            for operand in (
                intent.quantity,
                intent.remaining_quantity,
                intent.notional,
            )
        )
    )


def _resolution(
    outcome: ResolutionOutcome,
    reason_code: str,
    selected_intent_id: str | None,
    inputs: tuple[ConflictInput, ...],
) -> ConflictResolution:
    rule_ids = tuple(
        sorted(item.evaluation.rule_id for item in inputs)
    )
    payload = {
        "outcome": outcome.value,
        "reason_code": reason_code,
        "selected_intent_id": selected_intent_id,
        "contributing_rule_ids": rule_ids,
        "policy_version": ConflictPolicyV1.IDENTITY.value,
    }
    return ConflictResolution(
        outcome=outcome,
        reason_code=reason_code,
        selected_intent_id=selected_intent_id,
        contributing_rule_ids=rule_ids,
        policy_version=ConflictPolicyV1.IDENTITY.value,
        content_hash=canonical_hash(payload),
    )


__all__ = [
    "ConflictInput",
    "ConflictPolicyV1",
    "ConflictResolution",
    "ResolutionOutcome",
    "resolve_conflicts",
]
