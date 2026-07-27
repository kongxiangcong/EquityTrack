from __future__ import annotations

from decimal import Decimal
import sqlite3

import pytest

from trading_platform.domain.plans import (
    CoreFloor,
    CoreSleeve,
    GridConstraint,
    GridSleeve,
    PlanValidationError,
    PositionSleeveKind,
    TradePlanMaster,
    TradePlanMasterId,
    build_plan_version,
    validate_sleeve_contract,
    validate_sleeve_quantities,
)
from trading_platform.application import (
    CreateTradePlanMaster,
    GetTradePlanGraph,
    SealTradePlanGraph,
    open_trade_plan,
)
from trading_platform.identity import canonical_hash
from trading_platform.domain.strategies import (
    CorePlusGridParameters,
    StrategyContractError,
    TrendHoldBreakExitParameters,
)
from tests.platform.test_trade_plan_model_b import (
    _authority_root,
    _seed_approval,
    _with_hash,
)


def _core(
    *,
    budget: str | None = "80",
    floor: str = "80",
) -> CoreSleeve:
    return CoreSleeve(
        sleeve_id="core",
        quantity_budget=(
            None if budget is None else Decimal(budget)
        ),
        core_floor=CoreFloor(Decimal(floor)),
    )


def _grid(
    *,
    budget: str = "20",
    lower: str = "8",
    upper: str = "12",
    quantity_per_level: str = "100",
) -> GridSleeve:
    return GridSleeve(
        sleeve_id="grid",
        quantity_budget=Decimal(budget),
        core_floor=CoreFloor(Decimal("80")),
        constraint=GridConstraint(
            grid_constraint_id="grid_constraint_fixture",
            lower_price=Decimal(lower),
            upper_price=Decimal(upper),
            level_count=5,
            quantity_per_level=Decimal(quantity_per_level),
            total_quantity_budget=Decimal(budget),
            price_basis="unadjusted",
            trigger_mode="crosses_level",
            cooldown_trading_sessions=1,
        ),
    )


def test_only_strategy_compatible_core_and_grid_sleeves_are_accepted() -> None:
    core = _core()
    grid = _grid()
    validate_sleeve_contract(
        "strategy_version_trend_hold_break_exit_1",
        (core,),
    )
    validate_sleeve_contract(
        "strategy_version_core_plus_grid_1",
        (core, grid),
    )
    validate_sleeve_contract(
        "strategy_version_core_plus_grid_1",
        (core,),
    )

    cases = (
        (
            "strategy_version_trend_hold_break_exit_1",
            (),
            "SLEEVE_CORE_REQUIRED",
        ),
        (
            "strategy_version_core_plus_grid_1",
            (core, _core()),
            "SLEEVE_CORE_DUPLICATE",
        ),
        (
            "strategy_version_core_plus_grid_1",
            (core, grid, _grid()),
            "SLEEVE_GRID_DUPLICATE",
        ),
        (
            "strategy_version_trend_hold_break_exit_1",
            (core, grid),
            "SLEEVE_STRATEGY_MISMATCH",
        ),
    )
    for strategy_version_id, sleeves, code in cases:
        with pytest.raises(PlanValidationError) as rejected:
            validate_sleeve_contract(strategy_version_id, sleeves)
        assert rejected.value.code == code

    with pytest.raises(PlanValidationError) as tactical:
        PositionSleeveKind.parse("tactical")
    assert tactical.value.code == "SLEEVE_KIND_INVALID"


def test_grid_sell_cannot_cross_core_floor() -> None:
    sleeves = (_core(), _grid())
    validate_sleeve_quantities(
        sleeves,
        total_quantity=Decimal("100"),
        remaining_quantity=Decimal("100"),
        candidate_grid_decrease=Decimal("20"),
    )
    with pytest.raises(PlanValidationError) as crossed:
        validate_sleeve_quantities(
            sleeves,
            total_quantity=Decimal("100"),
            remaining_quantity=Decimal("100"),
            candidate_grid_decrease=Decimal("21"),
        )
    assert crossed.value.code == "GRID_DECREASE_CROSSES_CORE_FLOOR"

    validate_sleeve_quantities(sleeves, total_quantity=None)


@pytest.mark.parametrize(
    ("factory", "code"),
    [
        (lambda: CoreFloor(Decimal("-1")), "CORE_FLOOR_INVALID"),
        (lambda: CoreFloor(None), "CORE_FLOOR_REQUIRED"),
        (
            lambda: _grid(lower="12", upper="8"),
            "GRID_PRICE_BOUNDS_INVALID",
        ),
        (
            lambda: _grid(quantity_per_level="50"),
            "GRID_LOT_SIZE_INVALID",
        ),
    ],
)
def test_sleeve_quantity_contract_rejects_invalid_exact_values(
    factory,
    code: str,
) -> None:
    with pytest.raises(PlanValidationError) as rejected:
        factory()
    assert rejected.value.code == code


def test_strategy_parameter_objects_bind_cross_field_sleeve_contracts() -> None:
    trend = TrendHoldBreakExitParameters.from_mapping(
        {
            "price_basis": "unadjusted",
            "trend_metric_ref": "security.close_unadjusted",
            "break_condition": {
                "ast_version": "plan-rule-ast@2",
                "session_scope": "complete_session",
            },
            "break_confirmation_sessions": 2,
            "core_floor_quantity": "80",
            "invalidation_review_rule_ids": ["review_invalidation"],
            "candidate_decrease_quantity": {
                "state": "unknown",
                "value": None,
            },
            "review_by": "2026-08-27",
        }
    )
    assert trend.core_floor_quantity == Decimal("80")

    with pytest.raises(StrategyContractError) as invalid_grid:
        CorePlusGridParameters.from_mapping(
            {
                "core_floor_quantity": "80",
                "grid_lower_price": "12",
                "grid_upper_price": "8",
                "grid_level_count": 5,
                "grid_quantity_per_level": "100",
                "grid_total_quantity_budget": "500",
                "grid_price_basis": "unadjusted",
                "grid_trigger_mode": "crosses_level",
                "cooldown_trading_sessions": 1,
                "cash_operand_policy": "known_required",
                "quantity_operand_policy": "known_required",
            }
        )
    assert invalid_grid.value.code == "GRID_PRICE_BOUNDS_INVALID"


def test_sealed_core_grid_graph_round_trips_exact_rows_and_rejects_mutation(
    tmp_path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    plan_id = TradePlanMasterId.derive(
        "account_local", "security_600000", "core-grid-round-trip"
    )
    content = {
        "schema_version": "TradePlanContent@1",
        "purpose": "core-grid-round-trip",
    }
    with open_trade_plan(data_root) as tasks:
        tasks.execute(
            CreateTradePlanMaster(
                TradePlanMaster(
                    plan_id=plan_id,
                    strategy_version_id=(
                        "strategy_version_core_plus_grid_1"
                    ),
                    lifecycle_status="inactive",
                    transition_seq=0,
                    created_at="2026-07-27T00:00:00+08:00",
                )
            )
        )
        connection = sqlite3.connect(data_root / "platform.sqlite3")
        receipt = _seed_approval(
            connection,
            plan_id=plan_id.value,
            suffix="core_grid_round_trip",
            content_hash=canonical_hash(content),
        )
        connection.close()
        rule = _with_hash(
            {
                "rule_id": "rule_core_grid_round_trip",
                "rule_class": "hard",
                "priority": "ordinary",
                "scope": "grid",
                "ast_version": "plan-rule-ast@2",
                "condition": {
                    "ast_version": "plan-rule-ast@2",
                    "node": "always_false_fixture",
                },
                "candidate_intent": None,
            }
        )
        graph = build_plan_version(
            plan_version_id="trade_plan_version_core_grid_round_trip",
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
            sleeves=(_core(), _grid()),
            rules=(rule,),
            evidence_references=(),
            adjusted_price_evidence=(),
            confirmed_at="2026-07-27T00:00:00+08:00",
            user_approval_receipt_id=receipt,
        )
        sealed = tasks.execute(SealTradePlanGraph(graph))
        assert tasks.get(
            GetTradePlanGraph(graph.version.plan_version_id)
        ) == sealed

    connection = sqlite3.connect(data_root / "platform.sqlite3")
    with pytest.raises(
        sqlite3.IntegrityError, match="TRADE_PLAN_GRAPH_IMMUTABLE"
    ):
        connection.execute(
            "UPDATE grid_constraint SET quantity_per_level='200'"
        )
    connection.close()
