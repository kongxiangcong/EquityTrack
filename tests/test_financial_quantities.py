from decimal import Decimal, localcontext
from dataclasses import replace

import pytest

from equity_research import EquityBridge, FinancialInvariantError, FinancialQuantity


def money(value: str, ref: str) -> FinancialQuantity:
    return FinancialQuantity(
        value=Decimal(value),
        unit="USD million",
        scale=Decimal("1000000"),
        currency="USD",
        period="2025FY",
        as_of="2026-01-01",
        provenance_refs=(f"Fact:{ref}",),
        kind="money",
    )


def shares(value: str, ref: str) -> FinancialQuantity:
    return FinancialQuantity(
        value=Decimal(value),
        unit="million shares",
        scale=Decimal("1000000"),
        currency="N/A",
        period="2025FY",
        as_of="2026-01-01",
        provenance_refs=(f"Fact:{ref}",),
        kind="shares",
    )


def bridge() -> EquityBridge:
    return EquityBridge(
        basis_value=money("1000", "enterprise_value"),
        value_basis="enterprise_value",
        balance_sheet_period="2025FY",
        valuation_as_of="2026-01-01",
        output_currency="USD",
        cash=money("100", "cash"),
        debt=money("200", "debt"),
        lease_debt=money("30", "lease_debt"),
        preferred_stock=money("5", "preferred_stock"),
        minority_interest=money("15", "minority_interest"),
        pension_deficit=money("10", "pension_deficit"),
        associates_jv_value=money("10", "associates_jv_value"),
        non_operating_assets=money("20", "non_operating_assets"),
        diluted_shares=shares("100", "diluted_shares"),
    )


def test_enterprise_value_bridge_is_exact_and_recomputable() -> None:
    result = bridge().evaluate()

    assert result.equity_value == Decimal("870000000")
    assert result.per_share_value == Decimal("8.7")
    assert result.to_dict() == {
        "value_basis": "enterprise_value",
        "input_currency": "USD",
        "output_currency": "USD",
        "balance_sheet_period": "2025FY",
        "valuation_as_of": "2026-01-01",
        "equity_value": "870000000",
        "diluted_shares": "100000000",
        "per_share_value": "8.7",
        "trace": [
            {"operation": "basis_value", "amount": "1000000000", "ref_ids": ["Fact:enterprise_value"]},
            {"operation": "add_cash", "amount": "100000000", "ref_ids": ["Fact:cash"]},
            {"operation": "add_non_operating_assets", "amount": "20000000", "ref_ids": ["Fact:non_operating_assets"]},
            {"operation": "add_associates_jv_value", "amount": "10000000", "ref_ids": ["Fact:associates_jv_value"]},
            {"operation": "subtract_debt", "amount": "200000000", "ref_ids": ["Fact:debt"]},
            {"operation": "subtract_lease_debt", "amount": "30000000", "ref_ids": ["Fact:lease_debt"]},
            {"operation": "subtract_preferred_stock", "amount": "5000000", "ref_ids": ["Fact:preferred_stock"]},
            {"operation": "subtract_minority_interest", "amount": "15000000", "ref_ids": ["Fact:minority_interest"]},
            {"operation": "subtract_pension_deficit", "amount": "10000000", "ref_ids": ["Fact:pension_deficit"]},
            {"operation": "divide_diluted_shares", "amount": "100000000", "ref_ids": ["Fact:diluted_shares"]},
        ],
    }


def test_enterprise_value_bridge_preserves_equity_value_when_share_basis_is_missing() -> None:
    result = replace(bridge(), diluted_shares=None).evaluate()

    assert result.equity_value == Decimal("870000000")
    assert result.diluted_shares is None
    assert result.per_share_value is None
    assert result.to_dict()["diluted_shares"] is None
    assert result.to_dict()["per_share_value"] is None
    assert result.trace[-1] == {
        "operation": "subtract_pension_deficit",
        "amount": "10000000",
        "ref_ids": ["Fact:pension_deficit"],
    }


def test_bridge_blocks_period_mismatch_with_stable_code() -> None:
    subject = bridge()
    subject = replace(
        subject,
        debt=replace(subject.debt, period="2024FY"),
    )

    with pytest.raises(FinancialInvariantError) as error:
        subject.evaluate()

    assert error.value.code == "FINANCIAL_PERIOD_MISMATCH"


def test_equity_value_basis_cannot_apply_enterprise_value_adjustments() -> None:
    subject = replace(bridge(), value_basis="equity_value")

    with pytest.raises(FinancialInvariantError) as error:
        subject.evaluate()

    assert error.value.code == "FINANCIAL_VALUE_BASIS_DOUBLE_BRIDGE"


def test_bridge_applies_an_explicit_dimensioned_fx_rate() -> None:
    subject = replace(
        bridge(),
        output_currency="CNY",
        fx_rate=FinancialQuantity(
            value=Decimal("7.2"),
            unit="CNY/USD",
            scale=Decimal("1"),
            currency="CNY",
            period="2026-01-01",
            as_of="2026-01-01",
            provenance_refs=("Fact:fx_rate",),
            kind="fx",
        ),
    )

    result = subject.evaluate()

    assert result.equity_value == Decimal("6264000000.0")
    assert result.per_share_value == Decimal("62.64")
    assert result.trace[-2] == {
        "operation": "convert_fx",
        "amount": "7.2",
        "ref_ids": ["Fact:fx_rate"],
    }


def test_legacy_adapter_rejects_malformed_thousands_grouping() -> None:
    with pytest.raises(FinancialInvariantError) as error:
        FinancialQuantity.from_legacy(
            value="1,2",
            unit="USD",
            currency="USD",
            period="2025FY",
            as_of="2026-01-01",
            provenance_refs=("Fact:malformed",),
            kind="money",
        )

    assert error.value.code == "FINANCIAL_VALUE_INVALID"


def test_bridge_blocks_mixed_money_units_even_when_normalized_values_match() -> None:
    subject = bridge()
    subject = replace(
        subject,
        cash=FinancialQuantity(
            value=Decimal("100000000"),
            unit="USD",
            scale=Decimal("1"),
            currency="USD",
            period="2025FY",
            as_of="2026-01-01",
            provenance_refs=("Fact:cash",),
            kind="money",
        ),
    )

    with pytest.raises(FinancialInvariantError) as error:
        subject.evaluate()

    assert error.value.code == "FINANCIAL_SCALE_MISMATCH"

    unit_mismatch = replace(
        bridge(),
        cash=replace(bridge().cash, unit="million USD"),
    )
    with pytest.raises(FinancialInvariantError) as unit_error:
        unit_mismatch.evaluate()
    assert unit_error.value.code == "FINANCIAL_UNIT_MISMATCH"


def test_bridge_result_does_not_depend_on_process_decimal_precision() -> None:
    subject = replace(
        bridge(),
        diluted_shares=shares("7", "diluted_shares"),
    )
    expected = subject.evaluate().to_dict()

    with localcontext() as context:
        context.prec = 6
        actual = subject.evaluate().to_dict()

    assert actual == expected


def test_quantity_normalization_does_not_depend_on_process_decimal_precision() -> None:
    quantity = FinancialQuantity(
        value=Decimal("1.23456789"),
        unit="USD billion",
        scale=Decimal("1000000000"),
        currency="USD",
        period="2025FY",
        as_of="2026-01-01",
        provenance_refs=("Fact:precise_quantity",),
        kind="money",
    )
    expected = quantity.to_dict()

    with localcontext() as context:
        context.prec = 6
        actual = quantity.to_dict()

    assert actual == expected
