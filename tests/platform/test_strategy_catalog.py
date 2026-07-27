from __future__ import annotations

import sqlite3

import pytest

from trading_platform.application import (
    GetStrategyCatalog,
    GetStrategyVersion,
    open_strategy_queries,
)
from trading_platform.domain.strategies import StrategyContractError
from tests.platform.test_account_snapshots import _ready_root


def test_only_two_builtin_strategy_versions_are_available(
    tmp_path,
) -> None:
    data_root = _ready_root(tmp_path)
    with open_strategy_queries(data_root) as queries:
        catalog = queries.get(GetStrategyCatalog())
        exact = queries.get(
            GetStrategyVersion(
                "strategy_version_trend_hold_break_exit_1"
            )
        )
    assert tuple(item.public_identity for item in catalog) == (
        "core_plus_grid@1",
        "trend_hold_break_exit@1",
    )
    assert exact == catalog[1]
    assert exact.content_hash
    assert exact.strategy_definition.market_scope == "CN_A_SHARE"
    assert exact.strategy_definition.authoring_mode == "built_in"
    assert tuple(
        item.parameter_key for item in exact.parameter_contracts
    ) == (
        "price_basis",
        "trend_metric_ref",
        "break_condition",
        "break_confirmation_sessions",
        "core_floor_quantity",
        "invalidation_review_rule_ids",
        "candidate_decrease_quantity",
        "review_by",
    )
    assert tuple(
        item.parameter_key for item in catalog[0].parameter_contracts
    ) == (
        "core_floor_quantity",
        "grid_lower_price",
        "grid_upper_price",
        "grid_level_count",
        "grid_quantity_per_level",
        "grid_total_quantity_budget",
        "grid_price_basis",
        "grid_trigger_mode",
        "cooldown_trading_sessions",
        "cash_operand_policy",
        "quantity_operand_policy",
    )

    connection = sqlite3.connect(data_root / "platform.sqlite3")
    with pytest.raises(sqlite3.IntegrityError, match="STRATEGY_REGISTRY_IMMUTABLE"):
        connection.execute(
            "UPDATE strategy_version SET status='retired' "
            "WHERE strategy_version_id=?",
            (exact.strategy_version_id,),
        )
    connection.close()


def test_parameter_contract_rejects_unknown_or_missing_fields(tmp_path) -> None:
    data_root = _ready_root(tmp_path)
    with open_strategy_queries(data_root) as queries:
        version = queries.get(
            GetStrategyVersion("strategy_version_core_plus_grid_1")
        )
    with pytest.raises(StrategyContractError) as unknown:
        version.validate_parameters({"free_form_expression": "anything"})
    assert unknown.value.code == (
        "STRATEGY_PARAMETER_UNKNOWN:free_form_expression"
    )
    with pytest.raises(StrategyContractError) as missing:
        version.validate_parameters({})
    assert missing.value.code == (
        "STRATEGY_PARAMETER_REQUIRED:cash_operand_policy"
    )


def test_catalog_versions_apply_cross_field_sleeve_parameter_contracts(
    tmp_path,
) -> None:
    data_root = _ready_root(tmp_path)
    with open_strategy_queries(data_root) as queries:
        trend = queries.get(
            GetStrategyVersion(
                "strategy_version_trend_hold_break_exit_1"
            )
        )
        grid = queries.get(
            GetStrategyVersion("strategy_version_core_plus_grid_1")
        )
    trend.validate_parameters(
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
    with pytest.raises(
        StrategyContractError, match="GRID_LOT_SIZE_INVALID"
    ):
        grid.validate_parameters(
            {
                "core_floor_quantity": "80",
                "grid_lower_price": "8",
                "grid_upper_price": "12",
                "grid_level_count": 5,
                "grid_quantity_per_level": "50",
                "grid_total_quantity_budget": "500",
                "grid_price_basis": "unadjusted",
                "grid_trigger_mode": "crosses_level",
                "cooldown_trading_sessions": 1,
                "cash_operand_policy": "known_required",
                "quantity_operand_policy": "known_required",
            }
        )


def test_application_exports_no_strategy_authoring_command() -> None:
    import trading_platform.application as application

    assert not any(
        name.startswith(("CreateStrategy", "EditStrategy", "UploadStrategy"))
        for name in application.__all__
    )
