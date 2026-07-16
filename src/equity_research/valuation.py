from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any, Mapping

from .evidence import EvidenceBook, numeric_value, period_rank
from .financial import (
    EquityBridge,
    FinancialInvariantError,
    FinancialQuantity,
    exact_decimal_from_legacy,
    valuation_decimal_context,
)
from .models import CapabilityResult, EvidenceItem, MethodResult
from .research_inputs import ResearchInputs


FINANCIAL_TYPES = {"financial", "bank", "insurance", "broker"}
BIOPHARMA_TYPES = {"biopharma", "pre_revenue_biopharma", "innovative_drug"}
CYCLICAL_TYPES = {"cyclical", "cyclical_manufacturing", "resources", "commodity"}
METHOD_SOURCE_TIERS = {"official", "terminal", "secondary"}
WACC_EVIDENCE_FIELDS = {
    "risk_free_rate": ("risk_free_rate", "wacc:risk_free_rate", "decimal"),
    "equity_risk_premium": ("equity_risk_premium", "wacc:equity_risk_premium", "decimal"),
    "beta": ("beta", "wacc:beta", "x"),
    "pre_tax_cost_of_debt": ("pre_tax_cost_of_debt", "wacc:pre_tax_cost_of_debt", "decimal"),
    "tax_rate": ("wacc_tax_rate", "wacc:tax_rate", "decimal"),
    "equity_weight": ("equity_weight", "wacc:equity_weight", "decimal"),
    "debt_weight": ("debt_weight", "wacc:debt_weight", "decimal"),
}


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("Cannot calculate a percentile from an empty list.")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _percentile_decimal(values: list[Decimal], probability: Decimal) -> Decimal:
    if not values:
        raise ValueError("Cannot calculate a percentile from an empty list.")
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] * (Decimal("1") - fraction) + ordered[upper] * fraction


def _status_from_capability(capability: CapabilityResult) -> str:
    if capability.status == "ready_with_estimates":
        return "caution"
    return capability.status


def _observed_multiples(book: EvidenceBook) -> MethodResult:
    price_item = book.best("current_price")
    eps_item = book.best("eps", full_year=True, official_only=True)
    market_cap_item = book.best("market_cap")
    revenue_item = book.best("revenue", full_year=True, official_only=True)
    metrics: dict[str, Any] = {}
    evidence_ids: list[str] = []
    diagnostics: list[str] = []

    if price_item:
        evidence_ids.append(price_item.evidence_id)
    if eps_item:
        evidence_ids.append(eps_item.evidence_id)
    if market_cap_item:
        evidence_ids.append(market_cap_item.evidence_id)
    if revenue_item:
        evidence_ids.append(revenue_item.evidence_id)

    price = numeric_value(price_item.value) if price_item else None
    eps = numeric_value(eps_item.value) if eps_item else None
    market_cap = numeric_value(market_cap_item.value) if market_cap_item else None
    revenue = numeric_value(revenue_item.value) if revenue_item else None

    if price is not None and eps is not None and eps > 0:
        metrics["price_to_reported_fy_eps"] = price / eps
        metrics["eps_period"] = eps_item.period if eps_item else ""
    elif eps is not None and eps <= 0:
        diagnostics.append("Reported full-year EPS is non-positive; P/E context is not meaningful.")

    if market_cap is not None and revenue is not None and revenue > 0:
        metrics["market_cap_to_reported_fy_revenue"] = market_cap / revenue
        metrics["revenue_period"] = revenue_item.period if revenue_item else ""

    status = "ready" if metrics else "blocked"
    explanation = (
        "仅展示可复核的市场观察倍数，不把它解释为内在价值或价格结论。"
        if metrics
        else "缺少一致期间的价格、年度分母或市值数据。"
    )
    return MethodResult(
        method_id="observed_multiples",
        label="市场观察倍数",
        status=status,
        role="context",
        explanation=explanation,
        missing_fields=() if metrics else ("current_price", "eps_or_revenue"),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        assumptions={
            "denominator_basis": "reported_full_year",
            "interpretation": "market_context_only",
        },
        metrics=metrics,
        diagnostics=tuple(diagnostics),
    )


def _number_from_book(
    book: EvidenceBook,
    field_name: str,
    *,
    allow_estimate: bool = False,
    expected_currency: str = "",
) -> float:
    item = book.best(field_name, official_only=True)
    if item is None and allow_estimate:
        item = book.best_estimate(field_name)
    if not item:
        raise ValueError(f"A finite official value is required for {field_name}.")
    if expected_currency and item.currency != expected_currency:
        raise ValueError(
            f"Currency mismatch for {field_name}: {item.currency} != {expected_currency}."
        )
    value = item.value
    if isinstance(value, Mapping):
        preferred_keys = (
            f"total_{field_name}",
            "total_lease_liability",
            "total_depreciation_and_amortization",
            "total",
        )
        for key in preferred_keys:
            if key in value:
                number = numeric_value(value[key])
                if number is not None:
                    return number
        raise ValueError(f"A finite numeric value is required for {field_name}.")
    number = numeric_value(value)
    if number is None:
        raise ValueError(f"A finite numeric value is required for {field_name}.")
    return number


def _exact_decimal(value: Any, field_name: str) -> Decimal:
    return exact_decimal_from_legacy(value, field_name)


def _exact_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _legacy_item_value(item: EvidenceItem, field_name: str) -> Any:
    value = item.value
    if not isinstance(value, Mapping):
        return value
    for key in (
        f"total_{field_name}",
        "total_lease_liability",
        "total_depreciation_and_amortization",
        "total",
    ):
        if key in value:
            return value[key]
    raise FinancialInvariantError(
        "FINANCIAL_VALUE_INVALID",
        f"A decimal-compatible value is required for {field_name}.",
    )


def _financial_quantity_from_item(
    item: EvidenceItem,
    *,
    field_name: str,
    as_of_date: str,
    kind: str,
    expected_currency: str = "",
    expected_scale: Any | None = None,
    provenance_kind: str = "",
) -> FinancialQuantity:
    if kind == "money" and expected_currency and item.currency != expected_currency:
        raise FinancialInvariantError(
            "FINANCIAL_CURRENCY_MISMATCH",
            f"{field_name} currency {item.currency} does not match {expected_currency}.",
        )
    resolved_provenance_kind = (
        provenance_kind
        or ("Assumption" if item.estimated else "Fact")
    )
    if resolved_provenance_kind not in {"Fact", "Assumption"}:
        raise FinancialInvariantError(
            "FINANCIAL_PROVENANCE_INVALID",
            f"Unsupported provenance kind for {field_name}.",
        )
    return FinancialQuantity.from_legacy(
        value=_legacy_item_value(item, field_name),
        unit=item.unit,
        currency=item.currency,
        period=item.period,
        as_of=as_of_date,
        provenance_refs=(f"{resolved_provenance_kind}:{item.evidence_id}",),
        kind=kind,  # type: ignore[arg-type]
        expected_scale=expected_scale,
    )


def _financial_quantity_from_book(
    book: EvidenceBook,
    field_name: str,
    *,
    as_of_date: str,
    kind: str = "money",
    allow_estimate: bool = False,
    expected_currency: str = "",
) -> tuple[FinancialQuantity, EvidenceItem]:
    item = book.best(field_name, official_only=True)
    if item is None and allow_estimate:
        item = book.best_estimate(field_name)
    if item is None:
        raise FinancialInvariantError(
            "FINANCIAL_VALUE_MISSING",
            f"A sourced value is required for {field_name}.",
        )
    return (
        _financial_quantity_from_item(
            item,
            field_name=field_name,
            as_of_date=as_of_date,
            kind=kind,
            expected_currency=expected_currency,
        ),
        item,
    )


def _dcf_metrics(
    book: EvidenceBook,
    case: Mapping[str, Any],
    as_of_date: str,
) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
    forecast_items = [
        book.resolve_reference(
            reference,
            allowed_tiers=METHOD_SOURCE_TIERS,
            expected_subject_id=book.subject_id,
            expected_semantic_role="dcf_forecast_fcff",
            expected_field_names={"dcf_fcff"},
        )
        for reference in case["forecast_evidence_refs"]
    ]
    if any(item is None for item in forecast_items):
        raise ValueError("Every FCFF forecast must resolve to canonical evidence.")
    currency = str(case["currency"]).strip()
    unit_scale = _exact_decimal(case["forecast_unit_scale"], "forecast_unit_scale")
    forecast_quantities = [
        _financial_quantity_from_item(
            item,
            field_name="dcf_fcff",
            as_of_date=as_of_date,
            kind="money",
            expected_currency=currency,
            expected_scale=unit_scale,
            provenance_kind="Assumption",
        )
        for item in forecast_items
        if item is not None
    ]
    forecast_ranks = [period_rank(item.period) for item in forecast_items if item is not None]
    if (
        any(rank < 0 for rank in forecast_ranks)
        or forecast_ranks != sorted(forecast_ranks)
        or len(set(forecast_ranks)) != len(forecast_ranks)
        or len({item.evidence_id for item in forecast_items if item is not None})
        != len(forecast_items)
    ):
        raise ValueError("FCFF evidence periods must be unique and strictly increasing.")
    raw_forecast = [quantity.value for quantity in forecast_quantities]
    forecast = [quantity.normalized_value for quantity in forecast_quantities]
    wacc = _exact_decimal(case["wacc"], "wacc")
    terminal_item = book.resolve_reference(
        case["terminal_growth_evidence_ref"],
        allowed_tiers=METHOD_SOURCE_TIERS,
        expected_subject_id=book.subject_id,
        expected_semantic_role="dcf_terminal_growth",
        expected_field_names={"terminal_growth"},
    )
    if terminal_item is None:
        raise ValueError("Terminal growth must resolve to finite canonical evidence.")
    if terminal_item.unit != "decimal" or terminal_item.currency not in {"", "N/A"}:
        raise ValueError("Terminal growth evidence must use decimal units and no currency.")
    terminal_growth = _exact_decimal(terminal_item.value, "terminal_growth")
    if not Decimal("0") < wacc < Decimal("1"):
        raise ValueError("WACC must be a finite decimal between zero and one.")
    if not Decimal("-1") < terminal_growth < Decimal("1"):
        raise ValueError("Terminal growth must be a finite decimal between -1 and 1.")
    if wacc <= terminal_growth:
        raise ValueError("WACC must be greater than terminal growth.")
    if not forecast or any(not value.is_finite() for value in forecast):
        raise ValueError("FCFF forecast must contain finite values.")
    if forecast[-1] <= 0:
        raise ValueError("The final explicit FCFF must be positive for a Gordon-growth terminal value.")

    component_refs = case["wacc_component_evidence_refs"]
    component_items = {
        name: book.resolve_reference(
            component_refs[name],
            allowed_tiers=METHOD_SOURCE_TIERS,
            expected_subject_id=book.subject_id,
            expected_semantic_role=role,
            expected_field_names={field_name},
        )
        for name, (field_name, role, _) in WACC_EVIDENCE_FIELDS.items()
    }
    if any(item is None for item in component_items.values()):
        raise ValueError("Every WACC component must resolve to finite canonical evidence.")
    component_values = {
        name: _exact_decimal(item.value, name)
        for name, item in component_items.items()
        if item is not None
    }
    if len({item.evidence_id for item in component_items.values() if item is not None}) != len(component_items):
        raise ValueError("WACC components must reference unique evidence items.")
    for name, item in component_items.items():
        expected_unit = WACC_EVIDENCE_FIELDS[name][2]
        if item is None or item.unit != expected_unit or item.currency not in {"", "N/A"}:
            raise ValueError(f"WACC component {name} has an invalid semantic unit or currency.")
    component_periods = {item.period for item in component_items.values() if item is not None}
    if len(component_periods) != 1:
        raise ValueError("WACC component evidence must share one valuation date.")
    try:
        component_date = date.fromisoformat(next(iter(component_periods)))
    except ValueError as exc:
        raise ValueError("WACC component period must be an ISO valuation date.") from exc
    if component_date > date.fromisoformat(as_of_date):
        raise ValueError("WACC component evidence cannot be dated after the as-of date.")
    if any(not value.is_finite() for value in component_values.values()):
        raise ValueError("WACC components must be finite numbers.")
    equity_weight = component_values["equity_weight"]
    debt_weight = component_values["debt_weight"]
    tax_rate = component_values["tax_rate"]
    if (
        equity_weight < 0
        or debt_weight < 0
        or abs(equity_weight + debt_weight - Decimal("1")) > Decimal("0.000001")
    ):
        raise ValueError("Equity and debt weights must be non-negative and sum to one.")
    if not 0 <= tax_rate < 1:
        raise ValueError("The WACC tax rate must be a decimal in [0, 1).")
    cost_of_equity = (
        component_values["risk_free_rate"]
        + component_values["beta"] * component_values["equity_risk_premium"]
    )
    calculated_wacc = (
        equity_weight * cost_of_equity
        + debt_weight
        * component_values["pre_tax_cost_of_debt"]
        * (Decimal("1") - tax_rate)
    )
    if abs(wacc - calculated_wacc) > Decimal("0.000001"):
        raise ValueError(
            f"Declared WACC {wacc} does not reconcile to components {calculated_wacc}."
        )

    present_value_forecast = sum(
        (cash_flow / ((Decimal("1") + wacc) ** year) for year, cash_flow in enumerate(forecast, start=1)),
        Decimal("0"),
    )
    terminal_value = (
        forecast[-1]
        * (Decimal("1") + terminal_growth)
        / (wacc - terminal_growth)
    )
    present_value_terminal = terminal_value / (
        (Decimal("1") + wacc) ** len(forecast)
    )
    enterprise_value = present_value_forecast + present_value_terminal

    bridge_fields = {
        "cash": ("money", False),
        "debt": ("money", False),
        "lease_debt": ("money", True),
        "minority_interest": ("money", False),
        "preferred_stock": ("money", False),
        "pension_deficit": ("money", False),
        "non_operating_assets": ("money", False),
        "associates_jv_value": ("money", False),
        "diluted_shares": ("shares", False),
    }
    quantity_items = {
        field_name: _financial_quantity_from_book(
            book,
            field_name,
            as_of_date=as_of_date,
            kind=kind,
            allow_estimate=allow_estimate,
            expected_currency=currency if kind == "money" else "",
        )
        for field_name, (kind, allow_estimate) in bridge_fields.items()
    }
    quantities = {
        field_name: quantity
        for field_name, (quantity, _) in quantity_items.items()
    }
    bridge_evidence_items = [item for _, item in quantity_items.values()]
    balance_sheet_period = quantities["cash"].period

    output_currency = str(case.get("output_currency", currency)).strip() or currency
    fx_quantity: FinancialQuantity | None = None
    fx_item: EvidenceItem | None = None
    if output_currency != currency:
        fx_item = book.resolve_reference(
            case.get("fx_rate_evidence_ref"),
            allowed_tiers=METHOD_SOURCE_TIERS,
            expected_subject_id=book.subject_id,
            expected_semantic_role="valuation_fx_rate",
            expected_field_names={"fx_rate"},
        )
        if fx_item is None:
            raise FinancialInvariantError(
                "FINANCIAL_FX_REQUIRED",
                "A canonical valuation FX rate is required for cross-currency per-share value.",
            )
        fx_quantity = _financial_quantity_from_item(
            fx_item,
            field_name="fx_rate",
            as_of_date=as_of_date,
            kind="fx",
            expected_scale=Decimal("1"),
        )

    valuation_refs = tuple(
        f"Assumption:{item.evidence_id}"
        for item in (
            [item for item in forecast_items if item is not None]
            + [terminal_item]
            + [item for item in component_items.values() if item is not None]
        )
    )
    basis_quantity = FinancialQuantity(
        value=enterprise_value / unit_scale,
        unit=forecast_quantities[0].unit,
        scale=unit_scale,
        currency=currency,
        period=as_of_date,
        as_of=as_of_date,
        provenance_refs=valuation_refs,
        kind="money",
    )
    bridge = EquityBridge(
        basis_value=basis_quantity,
        value_basis="enterprise_value",
        balance_sheet_period=balance_sheet_period,
        valuation_as_of=as_of_date,
        output_currency=output_currency,
        cash=quantities["cash"],
        debt=quantities["debt"],
        lease_debt=quantities["lease_debt"],
        preferred_stock=quantities["preferred_stock"],
        minority_interest=quantities["minority_interest"],
        pension_deficit=quantities["pension_deficit"],
        associates_jv_value=quantities["associates_jv_value"],
        non_operating_assets=quantities["non_operating_assets"],
        diluted_shares=quantities["diluted_shares"],
        fx_rate=fx_quantity,
    )
    bridge_result = bridge.evaluate()

    sensitivity: list[dict[str, float | None]] = []
    for wacc_delta in (
        Decimal("-0.02"),
        Decimal("-0.01"),
        Decimal("0"),
        Decimal("0.01"),
        Decimal("0.02"),
    ):
        row_wacc = wacc + wacc_delta
        for growth_delta in (
            Decimal("-0.01"),
            Decimal("-0.005"),
            Decimal("0"),
            Decimal("0.005"),
            Decimal("0.01"),
        ):
            row_growth = terminal_growth + growth_delta
            if row_wacc <= row_growth or row_wacc <= 0:
                per_share = None
            else:
                pv_forecast = sum(
                    (
                        cash_flow / ((Decimal("1") + row_wacc) ** year)
                        for year, cash_flow in enumerate(forecast, start=1)
                    ),
                    Decimal("0"),
                )
                tv = (
                    forecast[-1]
                    * (Decimal("1") + row_growth)
                    / (row_wacc - row_growth)
                )
                pv_tv = tv / ((Decimal("1") + row_wacc) ** len(forecast))
                row_result = replace(
                    bridge,
                    basis_value=replace(
                        basis_quantity,
                        value=(pv_forecast + pv_tv) / unit_scale,
                    ),
                ).evaluate()
                per_share = float(row_result.per_share_value)
            sensitivity.append(
                {
                    "wacc": float(row_wacc),
                    "terminal_growth": float(row_growth),
                    "equity_value_per_share": per_share,
                }
            )

    terminal_share = (
        present_value_terminal / enterprise_value
        if enterprise_value
        else Decimal("0")
    )
    diagnostics: list[str] = []
    if terminal_share > Decimal("0.80"):
        diagnostics.append("Present value of terminal value exceeds 80% of enterprise value; interpret the range cautiously.")
    if any(value < 0 for value in forecast):
        diagnostics.append("The explicit FCFF forecast contains negative periods.")

    all_input_items = (
        [item for item in forecast_items if item is not None]
        + [terminal_item]
        + [item for item in component_items.values() if item is not None]
        + bridge_evidence_items
        + ([fx_item] if fx_item is not None else [])
    )
    exact_calculation = bridge_result.to_dict()
    exact_calculation.update(
        {
            "forecast_fcff": [_exact_text(value) for value in forecast],
            "wacc": _exact_text(wacc),
            "calculated_wacc": _exact_text(calculated_wacc),
            "terminal_growth": _exact_text(terminal_growth),
            "present_value_forecast": _exact_text(present_value_forecast),
            "terminal_value": _exact_text(terminal_value),
            "present_value_terminal": _exact_text(present_value_terminal),
            "enterprise_value": _exact_text(enterprise_value),
            "dimensioned_inputs": {
                "forecast_fcff": [
                    quantity.to_dict() for quantity in forecast_quantities
                ],
                "terminal_growth": {
                    "value": _exact_text(terminal_growth),
                    "unit": terminal_item.unit,
                    "scale": "1",
                    "currency": terminal_item.currency,
                    "period": terminal_item.period,
                    "as_of": as_of_date,
                    "provenance_refs": [
                        f"Assumption:{terminal_item.evidence_id}"
                    ],
                },
                "wacc_components": {
                    name: {
                        "value": _exact_text(component_values[name]),
                        "unit": item.unit,
                        "scale": "1",
                        "currency": item.currency,
                        "period": item.period,
                        "as_of": as_of_date,
                        "provenance_refs": [
                            f"Assumption:{item.evidence_id}"
                        ],
                    }
                    for name, item in component_items.items()
                    if item is not None
                },
                "basis_value": basis_quantity.to_dict(),
                "equity_bridge": {
                    field_name: quantity.to_dict()
                    for field_name, quantity in quantities.items()
                },
                "fx_rate": fx_quantity.to_dict() if fx_quantity else None,
            },
        }
    )
    metrics: dict[str, Any] = {
        "forecast_fcff": [float(value) for value in forecast],
        "forecast_fcff_unscaled": [float(value) for value in raw_forecast],
        "forecast_unit_scale": float(unit_scale),
        "currency": currency,
        "output_currency": output_currency,
        "input_source_ids": list(dict.fromkeys(item.source_id for item in all_input_items)),
        "wacc": float(wacc),
        "calculated_wacc": float(calculated_wacc),
        "wacc_components": {name: float(value) for name, value in component_values.items()},
        "terminal_growth": float(terminal_growth),
        "present_value_forecast": float(present_value_forecast),
        "terminal_value": float(terminal_value),
        "present_value_terminal": float(present_value_terminal),
        "terminal_value_share_of_enterprise_value": float(terminal_share),
        "enterprise_value": float(enterprise_value),
        "equity_value": float(bridge_result.equity_value),
        "equity_value_per_share": float(bridge_result.per_share_value),
        "equity_bridge": {
            field_name: float(quantity.normalized_value)
            for field_name, quantity in quantities.items()
        },
        "exact_calculation": exact_calculation,
        "sensitivity": sensitivity,
    }
    input_evidence_ids = tuple(dict.fromkeys(item.evidence_id for item in all_input_items))
    return metrics, tuple(diagnostics), input_evidence_ids


def _peer_metrics(
    book: EvidenceBook,
    case: Mapping[str, Any],
    as_of_date: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    raw_peers = case.get("peers")
    if not isinstance(raw_peers, list):
        raise ValueError("peer_case.peers must be a list.")
    metric = str(case.get("metric", "pe")).strip().lower()
    metric = {"price_to_sales": "ps", "ev_to_ebitda": "ev_ebitda"}.get(
        metric,
        metric,
    )
    peers: list[tuple[Mapping[str, Any], EvidenceItem, Decimal]] = []
    used_tickers: set[str] = set()
    used_evidence_ids: set[str] = set()
    for peer in raw_peers:
        if not isinstance(peer, Mapping) or peer.get("usable", True) is False:
            continue
        ticker = str(peer.get("ticker", "")).strip()
        evidence_item = book.resolve_reference(
            peer.get("evidence_ref"),
            allowed_tiers=METHOD_SOURCE_TIERS,
            expected_subject_id=ticker,
            expected_semantic_role=f"peer_multiple:{metric}",
        )
        if evidence_item is not None and (
            evidence_item.unit != "x"
            or evidence_item.currency not in {"", "N/A"}
            or evidence_item.period != str(peer.get("period", "")).strip()
        ):
            raise FinancialInvariantError(
                "FINANCIAL_MULTIPLE_DIMENSION_MISMATCH",
                "Peer multiples must be dimensionless, non-currency values for the declared period.",
            )
        multiple = (
            _exact_decimal(evidence_item.value, "peer_multiple")
            if evidence_item is not None
            else None
        )
        if (
            multiple is None
            or multiple <= 0
            or not str(peer.get("period", "")).strip()
            or peer.get("currency_checked") is not True
            or peer.get("accounting_checked") is not True
            or not ticker
            or evidence_item.period != str(peer.get("period", "")).strip()
            or ticker in used_tickers
            or evidence_item.evidence_id in used_evidence_ids
        ):
            continue
        used_tickers.add(ticker)
        used_evidence_ids.add(evidence_item.evidence_id)
        peers.append((peer, evidence_item, multiple))
    if len(peers) < 3:
        raise ValueError("At least three usable peers with source IDs are required.")

    multiples = [multiple for _, _, multiple in peers]
    q25 = _percentile_decimal(multiples, Decimal("0.25"))
    median = _percentile_decimal(multiples, Decimal("0.50"))
    q75 = _percentile_decimal(multiples, Decimal("0.75"))
    default_company_fields = {
        "pe": "eps",
        "ps": "revenue",
        "ev_ebitda": "ebitda",
    }
    company_field = str(
        case.get("company_metric_field", default_company_fields.get(metric, ""))
    ).strip()
    company_item = book.best(company_field, full_year=True, official_only=True)
    if company_item is None:
        raise ValueError("A positive company metric is required for peer valuation.")
    company_quantity = _financial_quantity_from_item(
        company_item,
        field_name=company_field,
        as_of_date=as_of_date,
        kind="per_share" if metric == "pe" else "money",
        expected_currency=company_item.currency,
    )
    company_value = company_quantity.normalized_value
    if company_value <= 0:
        raise ValueError("A positive company metric is required for peer valuation.")
    if any(evidence_item.period != company_item.period for _, evidence_item, _ in peers):
        raise FinancialInvariantError(
            "FINANCIAL_PERIOD_MISMATCH",
            "Peer multiples and the company metric must share one fiscal period.",
        )

    peer_provenance_refs = tuple(
        f"Fact:{evidence_item.evidence_id}"
        for _, evidence_item, _ in peers
    )
    calculation_provenance_refs = (
        company_quantity.provenance_refs + peer_provenance_refs
    )
    peer_inputs = [
        {
            "value": _exact_text(multiple),
            "unit": evidence_item.unit,
            "scale": "1",
            "currency": evidence_item.currency,
            "period": evidence_item.period,
            "as_of": as_of_date,
            "provenance_refs": [f"Fact:{evidence_item.evidence_id}"],
        }
        for _, evidence_item, multiple in peers
    ]

    metrics: dict[str, Any] = {
        "metric": metric,
        "peer_count": len(peers),
        "peer_multiples": [
            {
                "ticker": str(peer.get("ticker", "")),
                "multiple": float(multiple),
                "source_id": evidence_item.source_id,
                "evidence_id": evidence_item.evidence_id,
                "period": evidence_item.period,
            }
            for peer, evidence_item, multiple in peers
        ],
        "peer_q25_multiple": float(q25),
        "peer_median_multiple": float(median),
        "peer_q75_multiple": float(q75),
        "company_metric_field": company_field,
        "company_metric_value": float(company_value),
    }
    evidence_ids: list[str] = [company_item.evidence_id] if company_item else []
    evidence_ids.extend(evidence_item.evidence_id for _, evidence_item, _ in peers)

    if metric == "pe":
        implied_q25 = company_value * q25
        implied_median = company_value * median
        implied_q75 = company_value * q75
        metrics.update(
            {
                "implied_per_share_q25": float(implied_q25),
                "implied_per_share_median": float(implied_median),
                "implied_per_share_q75": float(implied_q75),
                "exact_calculation": {
                    "value_basis": "equity_value_per_share",
                    "currency": company_quantity.currency,
                    "company_metric_value": _exact_text(company_value),
                    "peer_q25_multiple": _exact_text(q25),
                    "peer_median_multiple": _exact_text(median),
                    "peer_q75_multiple": _exact_text(q75),
                    "implied_per_share_q25": _exact_text(implied_q25),
                    "implied_per_share_median": _exact_text(implied_median),
                    "implied_per_share_q75": _exact_text(implied_q75),
                    "dimensioned_inputs": {
                        "company_metric": company_quantity.to_dict(),
                        "peer_multiples": peer_inputs,
                    },
                    "provenance_refs": list(calculation_provenance_refs),
                },
            }
        )
    else:
        expected_currency = company_item.currency if company_item else ""
        shares_quantity, shares_item = _financial_quantity_from_book(
            book,
            "diluted_shares",
            as_of_date=as_of_date,
            kind="shares",
            expected_currency=expected_currency,
        )
        shares = shares_quantity.normalized_value
        evidence_ids.append(shares_item.evidence_id)
        if shares <= 0:
            raise ValueError("Diluted shares are required for non-P/E peer valuation.")
        if metric in {"ps", "price_to_sales"}:
            def equity_result(multiple: Decimal):
                basis = FinancialQuantity(
                    value=company_value * multiple / company_quantity.scale,
                    unit=company_quantity.unit,
                    scale=company_quantity.scale,
                    currency=expected_currency,
                    period=company_quantity.period,
                    as_of=as_of_date,
                    provenance_refs=calculation_provenance_refs,
                    kind="money",
                )
                return EquityBridge(
                    basis_value=basis,
                    value_basis="equity_value",
                    balance_sheet_period=company_quantity.period,
                    valuation_as_of=as_of_date,
                    output_currency=expected_currency,
                    cash=None,
                    debt=None,
                    lease_debt=None,
                    preferred_stock=None,
                    minority_interest=None,
                    pension_deficit=None,
                    associates_jv_value=None,
                    non_operating_assets=None,
                    diluted_shares=shares_quantity,
                ).evaluate()

            q25_result = equity_result(q25)
            median_result = equity_result(median)
            q75_result = equity_result(q75)
            implied_q25 = q25_result.per_share_value
            implied_median = median_result.per_share_value
            implied_q75 = q75_result.per_share_value
            metrics.update(
                {
                    "implied_per_share_q25": float(implied_q25),
                    "implied_per_share_median": float(implied_median),
                    "implied_per_share_q75": float(implied_q75),
                    "exact_calculation": {
                        "value_basis": "equity_value",
                        "currency": expected_currency,
                        "company_metric_value": _exact_text(company_value),
                        "diluted_shares": _exact_text(shares),
                        "peer_q25_multiple": _exact_text(q25),
                        "peer_median_multiple": _exact_text(median),
                        "peer_q75_multiple": _exact_text(q75),
                        "implied_per_share_q25": _exact_text(implied_q25),
                        "implied_per_share_median": _exact_text(implied_median),
                        "implied_per_share_q75": _exact_text(implied_q75),
                        "q25_trace": q25_result.to_dict()["trace"],
                        "median_trace": median_result.to_dict()["trace"],
                        "q75_trace": q75_result.to_dict()["trace"],
                        "dimensioned_inputs": {
                            "company_metric": company_quantity.to_dict(),
                            "diluted_shares": shares_quantity.to_dict(),
                            "peer_multiples": peer_inputs,
                        },
                        "provenance_refs": list(
                            calculation_provenance_refs
                            + shares_quantity.provenance_refs
                        ),
                    },
                }
            )
        elif metric in {"ev_ebitda", "ev_to_ebitda"}:
            bridge_fields = {
                "cash": False,
                "debt": False,
                "lease_debt": True,
                "minority_interest": False,
                "preferred_stock": False,
                "pension_deficit": False,
                "non_operating_assets": False,
                "associates_jv_value": False,
            }
            bridge_quantity_items = {
                field_name: _financial_quantity_from_book(
                    book,
                    field_name,
                    as_of_date=as_of_date,
                    allow_estimate=allow_estimate,
                    expected_currency=expected_currency,
                )
                for field_name, allow_estimate in bridge_fields.items()
            }
            bridge_quantities = {
                field_name: quantity
                for field_name, (quantity, _) in bridge_quantity_items.items()
            }
            bridge_items = [item for _, item in bridge_quantity_items.values()]
            evidence_ids.extend(item.evidence_id for item in bridge_items)
            basis_refs = tuple(
                [f"Fact:{company_item.evidence_id}"]
                + [f"Fact:{item.evidence_id}" for _, item, _ in peers]
            )

            def bridge_result(multiple: Decimal):
                basis = FinancialQuantity(
                    value=company_value * multiple / company_quantity.scale,
                    unit=company_quantity.unit,
                    scale=company_quantity.scale,
                    currency=expected_currency,
                    period=as_of_date,
                    as_of=as_of_date,
                    provenance_refs=basis_refs,
                    kind="money",
                )
                return EquityBridge(
                    basis_value=basis,
                    value_basis="enterprise_value",
                    balance_sheet_period=bridge_quantities["cash"].period,
                    valuation_as_of=as_of_date,
                    output_currency=expected_currency,
                    cash=bridge_quantities["cash"],
                    debt=bridge_quantities["debt"],
                    lease_debt=bridge_quantities["lease_debt"],
                    preferred_stock=bridge_quantities["preferred_stock"],
                    minority_interest=bridge_quantities["minority_interest"],
                    pension_deficit=bridge_quantities["pension_deficit"],
                    associates_jv_value=bridge_quantities["associates_jv_value"],
                    non_operating_assets=bridge_quantities["non_operating_assets"],
                    diluted_shares=shares_quantity,
                ).evaluate()

            q25_result = bridge_result(q25)
            median_result = bridge_result(median)
            q75_result = bridge_result(q75)
            implied_q25 = q25_result.per_share_value
            implied_median = median_result.per_share_value
            implied_q75 = q75_result.per_share_value
            metrics.update(
                {
                    "implied_per_share_q25": float(implied_q25),
                    "implied_per_share_median": float(implied_median),
                    "implied_per_share_q75": float(implied_q75),
                    "exact_calculation": {
                        "value_basis": "enterprise_value",
                        "currency": expected_currency,
                        "company_metric_value": _exact_text(company_value),
                        "peer_q25_multiple": _exact_text(q25),
                        "peer_median_multiple": _exact_text(median),
                        "peer_q75_multiple": _exact_text(q75),
                        "implied_per_share_q25": _exact_text(implied_q25),
                        "implied_per_share_median": _exact_text(implied_median),
                        "implied_per_share_q75": _exact_text(implied_q75),
                        "q25_trace": q25_result.to_dict()["trace"],
                        "median_trace": median_result.to_dict()["trace"],
                        "q75_trace": q75_result.to_dict()["trace"],
                        "dimensioned_inputs": {
                            "company_metric": company_quantity.to_dict(),
                            "diluted_shares": shares_quantity.to_dict(),
                            "peer_multiples": peer_inputs,
                            "equity_bridge": {
                                field_name: quantity.to_dict()
                                for field_name, quantity in bridge_quantities.items()
                            },
                        },
                        "provenance_refs": list(
                            calculation_provenance_refs
                            + shares_quantity.provenance_refs
                            + tuple(
                                reference
                                for quantity in bridge_quantities.values()
                                for reference in quantity.provenance_refs
                            )
                        ),
                    },
                }
            )
        else:
            raise ValueError(f"Unsupported peer metric: {metric}.")
    return metrics, tuple(evidence_ids)


def _historical_metrics(
    raw_values: Any,
    book: EvidenceBook,
    as_of_date: str,
    metric: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if not isinstance(raw_values, list):
        raise ValueError("historical_multiples must be a list.")
    locked_date = date.fromisoformat(as_of_date)
    observations: list[dict[str, Any]] = []
    used_evidence_ids: set[str] = set()
    for item in raw_values:
        if not isinstance(item, Mapping):
            continue
        date_text = str(item.get("date", "")).strip()
        evidence_item = book.resolve_reference(
            item.get("evidence_ref"),
            allowed_tiers=METHOD_SOURCE_TIERS,
            expected_subject_id=book.subject_id,
            expected_semantic_role=f"historical_multiple:{metric}",
        )
        value = (
            _exact_decimal(evidence_item.value, "historical_multiple")
            if evidence_item is not None
            else None
        )
        if evidence_item is not None and (
            evidence_item.unit != "x"
            or evidence_item.currency not in {"", "N/A"}
        ):
            raise FinancialInvariantError(
                "FINANCIAL_MULTIPLE_DIMENSION_MISMATCH",
                "Historical multiples must be dimensionless and non-currency values.",
            )
        try:
            observation_date = date.fromisoformat(date_text)
        except ValueError:
            continue
        if (
            value is None
            or value <= 0
            or observation_date > locked_date
            or evidence_item is None
            or evidence_item.period != date_text
            or evidence_item.evidence_id in used_evidence_ids
        ):
            continue
        used_evidence_ids.add(evidence_item.evidence_id)
        observations.append(
            {
                "date": date_text,
                "multiple": value,
                "source_id": evidence_item.source_id,
                "evidence_id": evidence_item.evidence_id,
            }
        )
    if len(observations) < 12:
        raise ValueError("At least twelve usable historical multiple observations are required.")
    observations.sort(key=lambda item: item["date"])
    values = [item["multiple"] for item in observations]
    current = values[-1]
    percentile_position = Decimal(sum(1 for value in values if value <= current)) / Decimal(len(values))
    q25 = _percentile_decimal(values, Decimal("0.25"))
    median = _percentile_decimal(values, Decimal("0.50"))
    q75 = _percentile_decimal(values, Decimal("0.75"))
    legacy_series = [
        {
            **item,
            "multiple": float(item["multiple"]),
        }
        for item in observations
    ]
    metrics = {
        "metric": metric,
        "observations": len(values),
        "series": legacy_series,
        "minimum": float(min(values)),
        "q25": float(q25),
        "median": float(median),
        "q75": float(q75),
        "maximum": float(max(values)),
        "current": float(current),
        "current_percentile": float(percentile_position),
        "exact_calculation": {
            "value_basis": "market_multiple_distribution",
            "metric": metric,
            "observations": str(len(values)),
            "minimum": _exact_text(min(values)),
            "q25": _exact_text(q25),
            "median": _exact_text(median),
            "q75": _exact_text(q75),
            "maximum": _exact_text(max(values)),
            "current": _exact_text(current),
            "current_percentile": _exact_text(percentile_position),
            "dimensioned_inputs": [
                {
                    "value": _exact_text(item["multiple"]),
                    "unit": "x",
                    "scale": "1",
                    "currency": "N/A",
                    "period": item["date"],
                    "as_of": as_of_date,
                    "provenance_refs": [f"Fact:{item['evidence_id']}"],
                }
                for item in observations
            ],
            "provenance_refs": [
                f"Fact:{item['evidence_id']}" for item in observations
            ],
        },
    }
    return metrics, tuple(item["evidence_id"] for item in observations)


def route_methods(
    book: EvidenceBook,
    capabilities: Mapping[str, CapabilityResult],
    company: Mapping[str, Any],
    inputs: ResearchInputs,
    *,
    as_of_date: str,
) -> dict[str, MethodResult]:
    company_type = inputs.company_type.strip().lower()
    methods: dict[str, MethodResult] = {
        "observed_multiples": _observed_multiples(book),
    }

    peer_capability = capabilities["peer_comps"]
    if peer_capability.status == "blocked":
        methods["peer_comps"] = MethodResult(
            method_id="peer_comps",
            label="可比公司法",
            status="blocked",
            role="relative_valuation",
            explanation="同业样本或公司侧输入不足；该方法单独禁用，不影响基础研究。",
            missing_fields=peer_capability.missing_fields + peer_capability.context_gaps,
            evidence_ids=peer_capability.evidence_ids,
            metrics={"peer_count": inputs.peer_count},
        )
    elif inputs.peer_case is not None:
        try:
            with valuation_decimal_context():
                peer_metrics, peer_evidence_ids = _peer_metrics(
                    book,
                    inputs.peer_case,
                    as_of_date,
                )
            methods["peer_comps"] = MethodResult(
                method_id="peer_comps",
                label="可比公司法",
                status="ready",
                role="relative_valuation",
                explanation="同业样本、倍数和公司分母通过结构化最低检查；结果仍需结合增长、利润率和生命周期差异解释。",
                evidence_ids=tuple(dict.fromkeys(peer_capability.evidence_ids + peer_evidence_ids)),
                assumptions={
                    "minimum_peer_count": 3,
                    "currency_checked": True,
                    "accounting_checked": True,
                    "metric": peer_metrics.get("metric", ""),
                },
                metrics=peer_metrics,
            )
        except (TypeError, ValueError) as exc:
            methods["peer_comps"] = MethodResult(
                method_id="peer_comps",
                label="可比公司法",
                status="blocked",
                role="relative_valuation",
                explanation="可比公司 case 未通过计算 invariant。",
                evidence_ids=peer_capability.evidence_ids,
                diagnostics=(str(exc),),
            )
    else:
        methods["peer_comps"] = MethodResult(
            method_id="peer_comps",
            label="可比公司法",
            status="limited",
            role="relative_valuation",
            explanation="同业数量声明满足最低要求，但没有结构化 peer_case，暂不计算区间。",
            evidence_ids=peer_capability.evidence_ids,
            metrics={"peer_count": inputs.peer_count},
        )

    historical_capability = capabilities["historical_band"]
    if historical_capability.status == "blocked":
        methods["historical_band"] = MethodResult(
            method_id="historical_band",
            label="历史估值带",
            status="blocked",
            role="relative_to_self",
            explanation="缺少可审计的历史倍数序列；该方法独立禁用。",
            missing_fields=historical_capability.missing_fields + historical_capability.context_gaps,
            evidence_ids=historical_capability.evidence_ids,
        )
    else:
        try:
            with valuation_decimal_context():
                metrics, historical_evidence_ids = _historical_metrics(
                    list(inputs.historical_multiples),
                    book,
                    as_of_date,
                    {"price_to_sales": "ps", "ev_to_ebitda": "ev_ebitda"}.get(
                        inputs.historical_metric.strip().lower(),
                        inputs.historical_metric.strip().lower(),
                    ),
                )
            methods["historical_band"] = MethodResult(
                method_id="historical_band",
                label="历史估值带",
                status="ready",
                role="relative_to_self",
                explanation="历史序列满足最低长度；结果展示分布位置，不自动解释为均值回归。",
                evidence_ids=tuple(
                    dict.fromkeys(
                        historical_capability.evidence_ids + historical_evidence_ids
                    )
                ),
                assumptions={
                    "as_of_date": as_of_date,
                    "minimum_observations": 12,
                    "source_tiers": sorted(METHOD_SOURCE_TIERS),
                },
                metrics=metrics,
            )
        except (TypeError, ValueError) as exc:
            methods["historical_band"] = MethodResult(
                method_id="historical_band",
                label="历史估值带",
                status="blocked",
                role="relative_to_self",
                explanation="历史倍数序列未通过计算 invariant。",
                evidence_ids=historical_capability.evidence_ids,
                diagnostics=(str(exc),),
            )

    dcf_capability = capabilities["dcf"]
    if company_type in FINANCIAL_TYPES:
        methods["dcf"] = MethodResult(
            method_id="dcf",
            label="普通 FCFF/WACC DCF",
            status="disabled",
            role="intrinsic_valuation",
            explanation="金融企业的债务和再投资定义不适用于普通 FCFF/WACC DCF；应路由到 residual income、DDM 或 excess return。",
        )
    elif company_type in BIOPHARMA_TYPES:
        methods["dcf"] = MethodResult(
            method_id="dcf",
            label="普通 FCFF/WACC DCF",
            status="disabled",
            role="intrinsic_valuation",
            explanation="管线驱动或 pre-revenue 生物医药应优先使用 rNPV/SOTP 与现金 runway。",
        )
    elif dcf_capability.status == "blocked":
        methods["dcf"] = MethodResult(
            method_id="dcf",
            label="DCF",
            status="blocked",
            role="intrinsic_valuation",
            explanation="DCF 专属输入不完整；只禁用 DCF，不阻断其他研究和报告。",
            missing_fields=dcf_capability.missing_fields + dcf_capability.context_gaps,
            evidence_ids=dcf_capability.evidence_ids,
        )
    elif company_type in CYCLICAL_TYPES:
        methods["dcf"] = MethodResult(
            method_id="dcf",
            label="普通 FCFF/WACC DCF",
            status="disabled",
            role="intrinsic_valuation",
            explanation="周期企业必须先完成可审计的中周期正常化；当前 builder 尚未实现，因此不执行普通 DCF。",
            evidence_ids=dcf_capability.evidence_ids,
        )
    else:
        case = inputs.dcf_case
        assert isinstance(case, Mapping)
        try:
            with valuation_decimal_context():
                metrics, diagnostics, dcf_input_evidence_ids = _dcf_metrics(
                    book,
                    case,
                    as_of_date,
                )
            status = "caution" if dcf_capability.status == "ready_with_estimates" else "ready"
            explanation = (
                "DCF 已按显式 FCFF、WACC、终值和股权桥计算；估算输入使其仅作为探索性交叉检查。"
                if status == "caution"
                else "DCF 已按显式、可追溯的 FCFF、WACC、终值和股权桥计算。"
            )
            methods["dcf"] = MethodResult(
                method_id="dcf",
                label="DCF",
                status=status,
                role="intrinsic_valuation",
                explanation=explanation,
                evidence_ids=tuple(
                    dict.fromkeys(
                        dcf_capability.evidence_ids + dcf_input_evidence_ids
                    )
                ),
                assumptions={
                    "currency": metrics["currency"],
                    "forecast_unit_scale": metrics["forecast_unit_scale"],
                    "wacc": metrics["wacc"],
                    "terminal_growth": metrics["terminal_growth"],
                    "input_source_ids": metrics["input_source_ids"],
                },
                metrics=metrics,
                diagnostics=diagnostics,
            )
        except (KeyError, TypeError, ValueError) as exc:
            methods["dcf"] = MethodResult(
                method_id="dcf",
                label="DCF",
                status="blocked",
                role="intrinsic_valuation",
                explanation="DCF 输入或金融 invariant 未通过。",
                evidence_ids=dcf_capability.evidence_ids,
                diagnostics=(str(exc),),
            )

    if company_type in CYCLICAL_TYPES:
        methods["mid_cycle"] = MethodResult(
            method_id="mid_cycle",
            label="中周期框架",
            status="limited",
            role="industry_specific",
            explanation=(
                "公司类型要求用中周期收入、利润率和资本开支校准；当前结构化中周期 case 尚未提供。"
                if inputs.mid_cycle_case is None
                else "已收到中周期输入，但完整 builder、证据校验和计算尚未实现，不能标记为已完成方法。"
            ),
            missing_fields=("mid_cycle_builder",),
            assumptions={"input_received": inputs.mid_cycle_case is not None},
        )

    return methods
