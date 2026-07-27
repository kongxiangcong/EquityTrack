from __future__ import annotations

from decimal import Decimal

import pytest

from trading_platform.domain.conflicts import (
    ConflictInput,
    ResolutionOutcome,
    resolve_conflicts,
)
from trading_platform.domain.rules import (
    CandidateIntent,
    OperandState,
    OperandValue,
    RuleEvaluation,
    RulePriority,
    RuleResult,
)


def _value(
    operand_id: str,
    value,
    *,
    state: OperandState = OperandState.KNOWN,
) -> OperandValue:
    return OperandValue(
        operand_id=operand_id,
        value_state=state,
        value=value,
        unit="share",
        currency=None,
        as_of_identity="estimated_state_fixture",
        evidence_refs=("estimated_state_fixture",),
        reason_code=(
            None if state is OperandState.KNOWN else "VALUE_UNKNOWN"
        ),
    )


def _input(
    rule_id: str,
    direction: str,
    *,
    remaining: Decimal | None = Decimal("80"),
    priority: RulePriority = RulePriority.ORDINARY,
    levels: tuple[str, ...] = ("grid_level_1",),
    result: RuleResult = RuleResult.TRIGGERED,
) -> ConflictInput:
    state = (
        OperandState.KNOWN
        if remaining is not None
        else OperandState.UNKNOWN
    )
    intent = CandidateIntent(
        intent_id=f"intent_{rule_id}",
        direction=direction,
        quantity=_value("candidate.quantity", Decimal("100")),
        remaining_quantity=_value(
            "candidate.remaining_quantity",
            remaining,
            state=state,
        ),
        notional=_value(
            "candidate.notional", Decimal("1000")
        ),
        grid_level_ids=levels,
    )
    evaluation = RuleEvaluation(
        rule_id=rule_id,
        result=result,
        reason_code="CONDITION_TRUE",
        operands=(),
        candidate_intent=intent if result is RuleResult.TRIGGERED else None,
        matched_grid_levels=levels,
        observed_at="2026-07-27",
        evidence_refs=(),
        replay_hash=f"hash_{rule_id}",
    )
    return ConflictInput(evaluation, priority)


@pytest.mark.parametrize(
    ("inputs", "graph_valid", "resource_conflict", "outcome", "reason"),
    [
        (
            (_input("corrupt", "increase"),),
            False,
            False,
            ResolutionOutcome.BLOCKED,
            "INVARIANT_CORRUPTION",
        ),
        (
            (
                _input(
                    "risk",
                    "decrease",
                    priority=RulePriority.RISK,
                ),
            ),
            True,
            False,
            ResolutionOutcome.MANUAL_REVIEW_REQUIRED,
            "RISK_INVALIDATION_OR_CORE_FLOOR_PRECEDENCE",
        ),
        (
            (
                _input("increase", "increase"),
                _input("decrease", "decrease"),
            ),
            True,
            False,
            ResolutionOutcome.MANUAL_REVIEW_REQUIRED,
            "OPPOSING_CANDIDATE_INTENTS",
        ),
        (
            (_input("resource", "increase"),),
            True,
            True,
            ResolutionOutcome.MANUAL_REVIEW_REQUIRED,
            "RESOURCE_OPERAND_CONFLICT",
        ),
        (
            (_input("floor", "decrease", remaining=Decimal("79")),),
            True,
            False,
            ResolutionOutcome.MANUAL_REVIEW_REQUIRED,
            "GRID_DECREASE_CROSSES_CORE_FLOOR",
        ),
        (
            (_input("unique", "increase"),),
            True,
            False,
            ResolutionOutcome.DECISION_TASK,
            "UNIQUE_GRID_LEVEL_ACTIONABLE",
        ),
        (
            (),
            True,
            False,
            ResolutionOutcome.NO_ACTION,
            "NO_VALID_TRIGGER",
        ),
    ],
)
def test_conflict_precedence_table(
    inputs,
    graph_valid: bool,
    resource_conflict: bool,
    outcome: ResolutionOutcome,
    reason: str,
) -> None:
    resolution = resolve_conflicts(
        evaluations=inputs,
        graph_valid=graph_valid,
        core_floor=Decimal("80"),
        resource_conflict=resource_conflict,
    )
    assert resolution.outcome is outcome
    assert resolution.reason_code == reason
    assert resolution.policy_version == "trade-plan-conflict@1"
    assert resolution.content_hash
    assert not hasattr(resolution, "execution")
