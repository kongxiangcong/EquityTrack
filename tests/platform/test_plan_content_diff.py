from __future__ import annotations

import json

import pytest

from trading_platform.domain.plan_content_diff import (
    PlanContentRevisionError,
    compare_plan_content,
    merge_plan_content,
)


def test_partial_revision_preserves_unmentioned_plan_authority() -> None:
    base = {
        "schema_version": "TradePlanContent@1",
        "strategy_key": "trend_hold_break_exit",
        "strategy_parameters": {
            "ast_version": "ConditionAST@1",
            "trend_metric_ref": "metric:close",
            "break_threshold": "28.12",
        },
        "risk_policy_limits": {"single_plan_loss": "0.02"},
        "purpose": "current",
    }

    merged = merge_plan_content(base, {"purpose": "revised"})

    assert merged["purpose"] == "revised"
    assert merged["strategy_parameters"] == base["strategy_parameters"]
    assert merged["risk_policy_limits"] == base["risk_policy_limits"]
    with pytest.raises(
        PlanContentRevisionError,
        match="PLAN_CONTENT_REVISION_CONTRACT_METADATA_DENIED",
    ):
        merge_plan_content(base, {"strategy_key": "other"})


def test_user_diff_has_four_categories_without_contract_metadata() -> None:
    before = {
        "schema_version": "TradePlanContent@1",
        "strategy_key": "trend_hold_break_exit",
        "strategy_parameters": {
            "ast_version": "ConditionAST@1",
            "trend_metric_ref": "metric:close",
            "break_threshold": "28.12",
            "stable_field": "same",
        },
        "removed_note": "old",
    }
    after = merge_plan_content(
        before,
        {
            "strategy_parameters": {"break_threshold": "27.50"},
            "added_note": "new",
        },
    )
    after = {key: value for key, value in after.items() if key != "removed_note"}

    rendered = compare_plan_content(before, after).as_dict()

    assert set(rendered) == {"added", "modified", "removed", "unchanged"}
    encoded = json.dumps(rendered, ensure_ascii=False)
    for internal in (
        "schema_version",
        "strategy_key",
        "ast_version",
        "trend_metric_ref",
        "metric:close",
    ):
        assert internal not in encoded
    assert rendered["added"]
    assert rendered["modified"]
    assert rendered["removed"]
    assert rendered["unchanged"]
