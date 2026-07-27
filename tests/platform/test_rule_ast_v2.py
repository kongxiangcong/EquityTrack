from __future__ import annotations

from decimal import Decimal

import pytest

from trading_platform.domain.rules import (
    CandidateIntent,
    EventWindow,
    GridConstraint,
    OperandState,
    OperandValue,
    RuleAstV2,
    RuleClass,
    RuleContractError,
    RuleResult,
    evaluate_rule,
)


def _operand(
    operand_id: str,
    value,
    *,
    state: OperandState = OperandState.KNOWN,
    reason: str | None = None,
) -> OperandValue:
    return OperandValue(
        operand_id=operand_id,
        value_state=state,
        value=value,
        unit="CNY_per_share" if "close" in operand_id else "share",
        currency="CNY" if "close" in operand_id else None,
        as_of_identity="market_snapshot_fixture",
        evidence_refs=(f"evidence:{operand_id}",),
        reason_code=reason,
    )


def test_ast_v2_operands_sessions_events_and_grid_replay() -> None:
    constraint = GridConstraint(
        grid_constraint_id="grid_constraint_ast",
        lower_price=Decimal("8"),
        upper_price=Decimal("12"),
        level_count=5,
        quantity_per_level=Decimal("100"),
        total_quantity_budget=Decimal("500"),
        price_basis="unadjusted",
        trigger_mode="crosses_level",
        cooldown_trading_sessions=1,
    )
    condition = RuleAstV2(
        node="all",
        children=(
            RuleAstV2(
                node="comparison",
                operand_id="account.remaining_quantity",
                operator="gte",
                expected=Decimal("80"),
            ),
            RuleAstV2(
                node="elapsed_trading_sessions",
                operand_id="event.session",
                threshold_sessions=2,
            ),
            RuleAstV2(
                node="event_window",
                event_type="grid_level_observed",
            ),
            RuleAstV2(
                node="grid_constraint",
                grid_constraint=constraint,
            ),
        ),
    )
    operands = {
        item.operand_id: item
        for item in (
            _operand(
                "account.remaining_quantity", Decimal("100")
            ),
            _operand("event.session", "2026-07-23"),
            _operand(
                "security.previous_close_unadjusted",
                Decimal("8.5"),
            ),
            _operand(
                "security.close_unadjusted", Decimal("9.5")
            ),
        )
    }
    arguments = {
        "rule_id": "grid_rule",
        "rule_class": RuleClass.HARD,
        "condition": condition,
        "candidate_intent": CandidateIntent(
            intent_id="candidate_grid_1",
            direction="increase",
            quantity=_operand(
                "candidate.quantity", Decimal("100")
            ),
            remaining_quantity=_operand(
                "candidate.remaining_quantity", Decimal("100")
            ),
            notional=OperandValue(
                operand_id="candidate.notional",
                value_state=OperandState.KNOWN,
                value=Decimal("950"),
                unit="CNY",
                currency="CNY",
                as_of_identity="market_snapshot_fixture",
                evidence_refs=("evidence:notional",),
            ),
            grid_level_ids=("grid_level_1",),
        ),
        "operands": operands,
        "complete_sessions": (
            "2026-07-23",
            "2026-07-24",
            "2026-07-27",
        ),
        "event_windows": (
            EventWindow(
                "grid_level_observed",
                "2026-07-24",
                "2026-07-27",
                ("event_grid_1",),
            ),
        ),
        "observed_at": "2026-07-27",
    }
    first = evaluate_rule(**arguments)
    replay = evaluate_rule(**arguments)
    assert first.result is RuleResult.TRIGGERED
    assert first.matched_grid_levels == ("grid_level_1",)
    assert replay == first
    assert replay.replay_hash == first.replay_hash
    assert constraint.generated_levels_hash


@pytest.mark.parametrize(
    ("state", "value", "reason", "expected"),
    [
        (
            OperandState.KNOWN,
            Decimal("100"),
            None,
            RuleResult.TRIGGERED,
        ),
        (
            OperandState.UNKNOWN,
            None,
            "AVAILABLE_QUANTITY_UNKNOWN",
            RuleResult.UNABLE,
        ),
        (
            OperandState.NOT_APPLICABLE,
            None,
            "NO_POSITION_AT_SNAPSHOT",
            RuleResult.NOT_APPLICABLE,
        ),
    ],
)
def test_operand_three_state_never_coerces_unknown_to_zero(
    state: OperandState,
    value,
    reason: str | None,
    expected: RuleResult,
) -> None:
    result = evaluate_rule(
        rule_id="quantity_rule",
        rule_class=RuleClass.HARD,
        condition=RuleAstV2(
            node="comparison",
            operand_id="account.available_quantity",
            operator="gte",
            expected=Decimal("1"),
        ),
        candidate_intent=None,
        operands={
            "account.available_quantity": _operand(
                "account.available_quantity",
                value,
                state=state,
                reason=reason,
            )
        },
        complete_sessions=(),
        event_windows=(),
        observed_at="2026-07-27",
    )
    assert result.result is expected


def test_ast_v2_rejects_arbitrary_fields_functions_and_versions() -> None:
    for ast in (
        RuleAstV2(
            node="comparison",
            operand_id="portfolio.any.path",
            operator="eq",
            expected="x",
        ),
        RuleAstV2(node="python", expected="__import__('os')"),
        RuleAstV2(
            node="comparison",
            operand_id="account.cash",
            operator="eq",
            expected=Decimal("0"),
            ast_version="plan-rule-ast@1",
        ),
    ):
        with pytest.raises(RuleContractError):
            ast.validate()
