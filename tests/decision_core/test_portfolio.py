from __future__ import annotations

import pytest

from trading_platform.portfolio import AccountSnapshot, ExecutionRecord, RiskPolicy, build_portfolio, evaluate_risk


def snapshot(cash: object = None) -> dict[str, object]:
    return {
        "snapshot_id": "snapshot-orchid",
        "account_id": "account-orchid",
        "as_of": "2035-04-18T08:00:00+00:00",
        "confirmed_by": "synthetic-user",
        "cash": cash,
        "positions": [
            {
                "security_id": "security-aster-001",
                "quantity": "120",
                "available_quantity": None,
                "cost_basis": None,
            }
        ],
    }


def test_market_price_changes_only_the_derived_portfolio() -> None:
    account = snapshot({"amount": "800", "currency": "XCU"})
    first = build_portfolio(AccountSnapshot.from_dict(account), {"security-aster-001": {"amount": "10", "currency": "XCU", "source_id": "fixture-price-10"}})
    second = build_portfolio(AccountSnapshot.from_dict(account), {"security-aster-001": {"amount": "12", "currency": "XCU", "source_id": "fixture-price-12"}})

    assert first.total_value == "2000"
    assert second.total_value == "2240"
    assert account["positions"][0]["quantity"] == "120"
    assert account["cash"]["amount"] == "800"

    frozen = AccountSnapshot.from_dict(account)
    with pytest.raises(TypeError):
        frozen.positions[0]["quantity"] = "0"


def test_unknown_cash_degrades_only_cash_dependent_risk() -> None:
    state = build_portfolio(AccountSnapshot.from_dict(snapshot()), {"security-aster-001": {"amount": "10", "currency": "XCU", "source_id": "fixture-source-price"}})
    result = evaluate_risk(
        state,
        RiskPolicy.from_candidate({"policy_id": "risk-orchid", "max_concentration": "0.70", "max_position_value": "1500", "confirmed": True, "confirmed_by": "synthetic-user"}),
    )

    assert state.total_value is None
    assert result.status == "insufficient"
    assert result.limits["max_position_value"]["status"] == "within_limit"
    assert result.limits["max_concentration"]["status"] == "insufficient"
    assert result.limits["max_concentration"]["missing"] == ("cash",)
    assert result.portfolio_state.portfolio_state_ref == result.as_dict()["portfolio_state_ref"]
    assert result.input_refs["price_source_ids"] == ("fixture-source-price",)


def test_execution_projection_is_deterministic_and_does_not_upgrade_verification() -> None:
    state = build_portfolio(
        AccountSnapshot.from_dict(snapshot({"amount": "800", "currency": "XCU"})),
        {"security-aster-001": {"amount": "10", "currency": "XCU", "source_id": "fixture-source-price"}},
        executions=[
            ExecutionRecord.from_dict({
                "execution_id": "execution-lantern",
                "account_id": "account-orchid",
                "base_snapshot_id": "snapshot-orchid",
                "security_id": "security-aster-001",
                "quantity_delta": "5",
                "verification_status": "user_declared",
                "declared_by": "synthetic-user",
                "declared_at": "2035-04-18T09:00:00+00:00",
            })
        ],
    )

    assert state.positions[0]["quantity"] == "125"
    assert state.execution_refs == ("execution-lantern",)
