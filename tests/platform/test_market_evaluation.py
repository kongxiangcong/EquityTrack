from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from tests.platform.owning_adapter_fixture import (
    SQLiteOwningAdapterFixture,
)
from tests.platform.test_plan_confirmation import (
    _open_trade_plan_test_seams,
)
from tests.platform.test_trade_plan_model_b import (
    _authority_root,
    _confirm_graph,
)
from trading_platform.application import (
    open_market,

)
from trading_platform.application.market_contracts import (
    EvaluatePlanCommand,
)
from trading_platform.application.command_codecs import (
    CommandCodecError,
    decode_plan_evaluation_command_value,
)
from trading_platform.domain.conflicts import ResolutionOutcome
from trading_platform.domain.market import (
    ComponentStatus,
    MarketBar,
    SnapshotStatus,
    UniverseMember,
    compute_components,
)
from trading_platform.domain.plans import (
    CoreFloor,
    CoreSleeve,
    GridSleeve,
    TradePlanMasterId,
    TradePlanRule,
    build_trade_plan_draft_graph,
)
from trading_platform.domain.rules import (
    CandidateIntent,
    GridConstraint,
    OperandState,
    OperandValue,
    RuleAstV2,
    RuleClass,
    RulePriority,
    RuleScope,
)
from trading_platform.market import MarketError


def _value(operand_id: str, value: Decimal) -> OperandValue:
    return OperandValue(
        operand_id=operand_id,
        value_state=OperandState.KNOWN,
        value=value,
        unit=(
            "CNY"
            if operand_id == "candidate.notional"
            else "share"
        ),
        currency=(
            "CNY"
            if operand_id == "candidate.notional"
            else None
        ),
        as_of_identity="estimated_account_state_fixture",
        evidence_refs=("estimated_account_state_fixture",),
    )


def _active_grid_plan(data_root, snapshot_id: str) -> str:
    constraint = GridConstraint(
        grid_constraint_id="grid_constraint_market_evaluation",
        lower_price=Decimal("8"),
        upper_price=Decimal("12"),
        level_count=5,
        quantity_per_level=Decimal("100"),
        total_quantity_budget=Decimal("500"),
        price_basis="unadjusted",
        trigger_mode="crosses_level",
        cooldown_trading_sessions=1,
    )
    intent = CandidateIntent(
        intent_id="candidate_grid_increase",
        direction="increase",
        quantity=_value("candidate.quantity", Decimal("100")),
        remaining_quantity=_value(
            "candidate.remaining_quantity", Decimal("100")
        ),
        notional=_value(
            "candidate.notional", Decimal("950")
        ),
        grid_level_ids=("grid_level_1",),
    )
    rule = TradePlanRule.build(
        rule_id="rule_grid_cross",
        rule_class=RuleClass.HARD,
        rule_kind="grid_level_candidate",
        priority=RulePriority.ORDINARY,
        scope=RuleScope.GRID,
        sleeve_id="grid",
        effect="create_candidate_intent",
        applies_to="increase",
        candidate_intent=intent,
        input_applicability=(
            "security.close_unadjusted",
            "security.previous_close_unadjusted",
        ),
        condition=RuleAstV2(
            node="grid_constraint",
            grid_constraint=constraint,
        ),
    )
    content = {
        "schema_version": "TradePlanContent@1",
        "purpose": "market-evaluation-fixture",
    }
    plan_id = TradePlanMasterId.derive(
        "account_local", "security_600000", "market-evaluation"
    )
    with _open_trade_plan_test_seams(data_root) as (tasks, _):
        graph = build_trade_plan_draft_graph(
            plan_version_id="trade_plan_version_market_evaluation",
            plan_id=plan_id.value,
            version_no=1,
            supersedes_version_id=None,
            strategy_version_id="strategy_version_core_plus_grid_1",
            investment_thesis_version_id=None,
            account_snapshot_version_id=snapshot_id,
            data_snapshot_id="data_snapshot_plan_fixture",
            horizon_start="2026-07-27",
            horizon_end="2026-10-27",
            review_by="2026-08-27",
            risk_policy_version_id=None,
            metric_catalog_version="metric-catalog@2",
            evaluator_policy_version="plan-evaluator@2",
            content=content,
            sleeves=(
                CoreSleeve(
                    sleeve_id="core",
                    quantity_budget=Decimal("80"),
                    core_floor=CoreFloor(Decimal("80")),
                ),
                GridSleeve(
                    sleeve_id="grid",
                    quantity_budget=Decimal("500"),
                    core_floor=CoreFloor(Decimal("80")),
                    constraint=constraint,
                ),
            ),
            rules=(rule,),
            evidence_references=(),
            adjusted_price_evidence=(),
        )
        graph = _confirm_graph(
            tasks, graph, "market_evaluation"
        ).graph
    return graph.version.plan_version_id


def _market_snapshot(data_root) -> str:
    fixture = SQLiteOwningAdapterFixture(data_root)
    with fixture.transaction():
        fixture.execute(
            "INSERT INTO market_universe_version VALUES(?,?,?,?,?)",
            (
                "market_universe_evaluation",
                "CN_A_SHARE",
                "2026-07-27T00:00:00+08:00",
                "fixture",
                "fixture-membership",
            ),
        )
        fixture.execute(
            "INSERT INTO market_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "market_snapshot_evaluation",
                "security_600000",
                "CN_A_SHARE",
                "2026-07-27",
                "2026-07-24",
                "data_snapshot_plan_fixture",
                "market_universe_evaluation",
                "cn-a-share-market@1",
                "freshness_fixture@1",
                "code-identity-fixture",
                "input-fingerprint-fixture",
                "limited",
                1,
                "2026-07-27T00:00:00+08:00",
            ),
        )
        fixture.execute(
            "INSERT INTO market_snapshot_component "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "market_snapshot_evaluation",
                0,
                "security.price_context",
                "complete",
                "available",
                '[["close","9.5"],["previous_close","8.5"]]',
                "COMPONENT_COMPUTED",
                1,
                1,
                0,
                0,
                '["market-evidence-fixture"]',
            ),
        )
    fixture.close()
    return "market_snapshot_evaluation"


def test_ast_v2_market_evaluation_persists_one_locked_resolution(
    tmp_path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    plan_version_id = _active_grid_plan(data_root, snapshot_id)
    market_snapshot_id = _market_snapshot(data_root)
    command = EvaluatePlanCommand(
        invocation_id="evaluate:grid",
        plan_version_id=plan_version_id,
        market_snapshot_id=market_snapshot_id,
    )
    with open_market(data_root) as market:
        first = market.evaluate_plan(command)
        replay = market.evaluate_plan(command)
        assert replay == first
        assert (
            first.resolution.outcome
            is ResolutionOutcome.DECISION_TASK
        )
        assert first.rule_results[0].matched_grid_levels == (
            "grid_level_1",
        )
        assert market.get_plan_evaluation(
            first.plan_evaluation_id
        ) == first

    fixture = SQLiteOwningAdapterFixture(data_root)
    with pytest.raises(Exception, match="PLAN_EVALUATION_IMMUTABLE"):
        fixture.execute(
            "DELETE FROM plan_evaluation WHERE plan_evaluation_id=?",
            (first.plan_evaluation_id,),
        )
    fixture.close()


def test_evaluation_requires_the_exact_active_plan_version(
    tmp_path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    market_snapshot_id = _market_snapshot(data_root)
    with open_market(data_root) as market:
        with pytest.raises(MarketError, match="PLAN_VERSION_NOT_ACTIVE"):
            market.evaluate_plan(
                EvaluatePlanCommand(
                    invocation_id="evaluate:missing",
                    plan_version_id="missing",
                    market_snapshot_id=market_snapshot_id,
                )
            )


def test_same_snapshot_with_distinct_inputs_has_distinct_resolution(
    tmp_path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    plan_version_id = _active_grid_plan(data_root, snapshot_id)
    market_snapshot_id = _market_snapshot(data_root)
    with open_market(data_root) as market:
        actionable = market.evaluate_plan(
            EvaluatePlanCommand(
                invocation_id="evaluate:actionable",
                plan_version_id=plan_version_id,
                market_snapshot_id=market_snapshot_id,
            )
        )
        conflicted = market.evaluate_plan(
            EvaluatePlanCommand(
                invocation_id="evaluate:resource-conflict",
                plan_version_id=plan_version_id,
                market_snapshot_id=market_snapshot_id,
                resource_conflict=True,
            )
        )
    assert actionable.plan_evaluation_id != conflicted.plan_evaluation_id
    assert conflicted.resolution.outcome is (
        ResolutionOutcome.MANUAL_REVIEW_REQUIRED
    )


def test_evaluation_command_codec_rejects_retired_policy_selection() -> None:
    with pytest.raises(CommandCodecError) as failure:
        decode_plan_evaluation_command_value(
            {
                "invocation_id": "evaluate:retired",
                "plan_version_id": "plan_version",
                "market_snapshot_id": "market_snapshot",
                "evaluator_version": "plan-evaluator@1",
            }
        )
    assert failure.value.code == "PLAN_EVALUATION_COMMAND_INVALID"

def test_price_context_degrades_locally_when_constraint_evidence_is_absent() -> None:
    sessions = tuple(
        (date(2025, 11, 1) + timedelta(days=index)).isoformat()
        for index in range(60)
    )
    bars = tuple(
        MarketBar(
            "security_600000",
            session,
            Decimal(index + 1),
            Decimal("1000"),
            f"daily:{index}",
        )
        for index, session in enumerate(sessions)
    )
    status, components = compute_components(
        security_id="security_600000",
        benchmark_id="benchmark_unavailable",
        universe_members=(
            UniverseMember(
                "security_600000",
                "2020-01-01",
                None,
                "universe:evidence",
            ),
        ),
        bars=bars,
        effective_session=sessions[-1],
        freshness="valid",
        quality="pass",
        constraints={},
    )
    price = next(
        item
        for item in components
        if item.component_id == "security.price_context"
    )

    assert status is SnapshotStatus.LIMITED
    assert price.status is ComponentStatus.LIMITED
    assert dict(price.values)["close"] == "60"
    assert "suspended" not in dict(price.values)
    assert len(price.evidence_refs) == 60
