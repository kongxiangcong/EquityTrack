from __future__ import annotations

from datetime import date
from math import isclose, isfinite
from typing import Any, Mapping

from .evidence import EvidenceBook, numeric_value, period_rank
from .models import CapabilityResult, MethodResult


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
    raw_forecast = [
        float(numeric_value(item.value))
        for item in forecast_items
        if item is not None and numeric_value(item.value) is not None
    ]
    if len(raw_forecast) != len(forecast_items):
        raise ValueError("Every FCFF forecast evidence item must be finite and numeric.")
    unit_scale = float(case["forecast_unit_scale"])
    currency = str(case["currency"]).strip()
    if not isfinite(unit_scale) or unit_scale <= 0:
        raise ValueError("forecast_unit_scale must be a finite positive number.")
    expected_units = {
        1.0: {currency, f"{currency} units"},
        1_000.0: {f"{currency} thousand", f"thousand {currency}"},
        1_000_000.0: {f"{currency} million", f"million {currency}"},
    }.get(unit_scale, set())
    if not expected_units or any(
        item is None
        or item.currency != currency
        or item.unit not in expected_units
        for item in forecast_items
    ):
        raise ValueError("FCFF evidence currency/unit does not reconcile to forecast_unit_scale.")
    forecast_ranks = [period_rank(item.period) for item in forecast_items if item is not None]
    if (
        any(rank < 0 for rank in forecast_ranks)
        or forecast_ranks != sorted(forecast_ranks)
        or len(set(forecast_ranks)) != len(forecast_ranks)
        or len({item.evidence_id for item in forecast_items if item is not None})
        != len(forecast_items)
    ):
        raise ValueError("FCFF evidence periods must be unique and strictly increasing.")
    forecast = [value * unit_scale for value in raw_forecast]
    wacc = float(case["wacc"])
    terminal_item = book.resolve_reference(
        case["terminal_growth_evidence_ref"],
        allowed_tiers=METHOD_SOURCE_TIERS,
        expected_subject_id=book.subject_id,
        expected_semantic_role="dcf_terminal_growth",
        expected_field_names={"terminal_growth"},
    )
    terminal_growth_value = numeric_value(terminal_item.value) if terminal_item else None
    if terminal_growth_value is None:
        raise ValueError("Terminal growth must resolve to finite canonical evidence.")
    if terminal_item is None or terminal_item.unit != "decimal" or terminal_item.currency not in {"", "N/A"}:
        raise ValueError("Terminal growth evidence must use decimal units and no currency.")
    terminal_growth = float(terminal_growth_value)
    if not isfinite(wacc) or not 0 < wacc < 1:
        raise ValueError("WACC must be a finite decimal between zero and one.")
    if not isfinite(terminal_growth) or not -1 < terminal_growth < 1:
        raise ValueError("Terminal growth must be a finite decimal between -1 and 1.")
    if wacc <= terminal_growth:
        raise ValueError("WACC must be greater than terminal growth.")
    if not forecast or any(not isfinite(value) for value in forecast):
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
    component_values = {
        name: float(numeric_value(item.value))
        for name, item in component_items.items()
        if item is not None and numeric_value(item.value) is not None
    }
    if len(component_values) != len(component_items):
        raise ValueError("Every WACC component must resolve to finite canonical evidence.")
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
    if any(not isfinite(value) for value in component_values.values()):
        raise ValueError("WACC components must be finite numbers.")
    equity_weight = component_values["equity_weight"]
    debt_weight = component_values["debt_weight"]
    tax_rate = component_values["tax_rate"]
    if equity_weight < 0 or debt_weight < 0 or not isclose(
        equity_weight + debt_weight, 1.0, abs_tol=1e-6
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
        * (1 - tax_rate)
    )
    if not isclose(wacc, calculated_wacc, abs_tol=1e-6):
        raise ValueError(
            f"Declared WACC {wacc:.6f} does not reconcile to components {calculated_wacc:.6f}."
        )

    present_value_forecast = sum(
        cash_flow / ((1 + wacc) ** year)
        for year, cash_flow in enumerate(forecast, start=1)
    )
    terminal_value = forecast[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    present_value_terminal = terminal_value / ((1 + wacc) ** len(forecast))
    enterprise_value = present_value_forecast + present_value_terminal

    cash = _number_from_book(book, "cash", expected_currency=currency)
    debt = _number_from_book(book, "debt", expected_currency=currency)
    minority = _number_from_book(book, "minority_interest", expected_currency=currency)
    preferred = _number_from_book(book, "preferred_stock", expected_currency=currency)
    pension = _number_from_book(book, "pension_deficit", expected_currency=currency)
    non_operating = _number_from_book(book, "non_operating_assets", expected_currency=currency)
    associates = _number_from_book(book, "associates_jv_value", expected_currency=currency)
    lease_debt = _number_from_book(
        book,
        "lease_debt",
        allow_estimate=True,
        expected_currency=currency,
    )
    shares = _number_from_book(book, "diluted_shares", expected_currency=currency)
    if shares <= 0:
        raise ValueError("Diluted shares must be positive.")

    equity_value = (
        enterprise_value
        + cash
        + non_operating
        + associates
        - debt
        - lease_debt
        - minority
        - preferred
        - pension
    )

    sensitivity: list[dict[str, float | None]] = []
    for wacc_delta in (-0.02, -0.01, 0.0, 0.01, 0.02):
        row_wacc = wacc + wacc_delta
        for growth_delta in (-0.01, -0.005, 0.0, 0.005, 0.01):
            row_growth = terminal_growth + growth_delta
            if row_wacc <= row_growth or row_wacc <= 0:
                per_share = None
            else:
                pv_forecast = sum(
                    cash_flow / ((1 + row_wacc) ** year)
                    for year, cash_flow in enumerate(forecast, start=1)
                )
                tv = forecast[-1] * (1 + row_growth) / (row_wacc - row_growth)
                pv_tv = tv / ((1 + row_wacc) ** len(forecast))
                row_equity = (
                    pv_forecast
                    + pv_tv
                    + cash
                    + non_operating
                    + associates
                    - debt
                    - lease_debt
                    - minority
                    - preferred
                    - pension
                )
                per_share = row_equity / shares
            sensitivity.append(
                {
                    "wacc": row_wacc,
                    "terminal_growth": row_growth,
                    "equity_value_per_share": per_share,
                }
            )

    terminal_share = present_value_terminal / enterprise_value if enterprise_value else 0.0
    diagnostics: list[str] = []
    if terminal_share > 0.80:
        diagnostics.append("Present value of terminal value exceeds 80% of enterprise value; interpret the range cautiously.")
    if any(value < 0 for value in forecast):
        diagnostics.append("The explicit FCFF forecast contains negative periods.")

    metrics: dict[str, Any] = {
        "forecast_fcff": forecast,
        "forecast_fcff_unscaled": raw_forecast,
        "forecast_unit_scale": unit_scale,
        "currency": currency,
        "input_source_ids": list(
            dict.fromkeys(
                [item.source_id for item in forecast_items if item is not None]
                + ([terminal_item.source_id] if terminal_item else [])
                + [item.source_id for item in component_items.values() if item is not None]
            )
        ),
        "wacc": wacc,
        "calculated_wacc": calculated_wacc,
        "wacc_components": component_values,
        "terminal_growth": terminal_growth,
        "present_value_forecast": present_value_forecast,
        "terminal_value": terminal_value,
        "present_value_terminal": present_value_terminal,
        "terminal_value_share_of_enterprise_value": terminal_share,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "equity_value_per_share": equity_value / shares,
        "equity_bridge": {
            "cash": cash,
            "debt": debt,
            "lease_debt": lease_debt,
            "minority_interest": minority,
            "preferred_stock": preferred,
            "pension_deficit": pension,
            "non_operating_assets": non_operating,
            "associates_jv_value": associates,
            "diluted_shares": shares,
        },
        "sensitivity": sensitivity,
    }
    input_evidence_ids = tuple(
        dict.fromkeys(
            [item.evidence_id for item in forecast_items if item is not None]
            + ([terminal_item.evidence_id] if terminal_item else [])
            + [item.evidence_id for item in component_items.values() if item is not None]
        )
    )
    return metrics, tuple(diagnostics), input_evidence_ids


def _peer_metrics(book: EvidenceBook, case: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    raw_peers = case.get("peers")
    if not isinstance(raw_peers, list):
        raise ValueError("peer_case.peers must be a list.")
    metric = str(case.get("metric", "pe")).strip().lower()
    metric = {"price_to_sales": "ps", "ev_to_ebitda": "ev_ebitda"}.get(
        metric,
        metric,
    )
    peers: list[tuple[Mapping[str, Any], Any, float]] = []
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
        multiple = numeric_value(evidence_item.value) if evidence_item else None
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
    q25 = _percentile(multiples, 0.25)
    median = _percentile(multiples, 0.50)
    q75 = _percentile(multiples, 0.75)
    default_company_fields = {
        "pe": "eps",
        "ps": "revenue",
        "ev_ebitda": "ebitda",
    }
    company_field = str(
        case.get("company_metric_field", default_company_fields.get(metric, ""))
    ).strip()
    company_item = book.best(company_field, full_year=True, official_only=True)
    company_value = numeric_value(company_item.value) if company_item else None
    if company_value is None or company_value <= 0:
        raise ValueError("A positive company metric is required for peer valuation.")

    metrics: dict[str, Any] = {
        "metric": metric,
        "peer_count": len(peers),
        "peer_multiples": [
            {
                "ticker": str(peer.get("ticker", "")),
                "multiple": multiple,
                "source_id": evidence_item.source_id,
                "evidence_id": evidence_item.evidence_id,
                "period": evidence_item.period,
            }
            for peer, evidence_item, multiple in peers
        ],
        "peer_q25_multiple": q25,
        "peer_median_multiple": median,
        "peer_q75_multiple": q75,
        "company_metric_field": company_field,
        "company_metric_value": company_value,
    }
    evidence_ids: list[str] = [company_item.evidence_id] if company_item else []
    evidence_ids.extend(evidence_item.evidence_id for _, evidence_item, _ in peers)

    if metric == "pe":
        metrics.update(
            {
                "implied_per_share_q25": company_value * q25,
                "implied_per_share_median": company_value * median,
                "implied_per_share_q75": company_value * q75,
            }
        )
    else:
        expected_currency = company_item.currency if company_item else ""
        shares = _number_from_book(
            book,
            "diluted_shares",
            expected_currency=expected_currency,
        )
        if shares <= 0:
            raise ValueError("Diluted shares are required for non-P/E peer valuation.")
        if metric in {"ps", "price_to_sales"}:
            metrics.update(
                {
                    "implied_per_share_q25": company_value * q25 / shares,
                    "implied_per_share_median": company_value * median / shares,
                    "implied_per_share_q75": company_value * q75 / shares,
                }
            )
        elif metric in {"ev_ebitda", "ev_to_ebitda"}:
            cash = _number_from_book(book, "cash", expected_currency=expected_currency)
            debt = _number_from_book(book, "debt", expected_currency=expected_currency)
            minority = _number_from_book(
                book,
                "minority_interest",
                expected_currency=expected_currency,
            )
            def per_share(multiple: float) -> float:
                return (company_value * multiple + cash - debt - minority) / shares
            metrics.update(
                {
                    "implied_per_share_q25": per_share(q25),
                    "implied_per_share_median": per_share(median),
                    "implied_per_share_q75": per_share(q75),
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
        value = numeric_value(evidence_item.value) if evidence_item else None
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
    values = [float(item["multiple"]) for item in observations]
    current = values[-1]
    percentile_position = sum(1 for value in values if value <= current) / len(values)
    metrics = {
        "observations": len(values),
        "series": observations,
        "minimum": min(values),
        "q25": _percentile(values, 0.25),
        "median": _percentile(values, 0.50),
        "q75": _percentile(values, 0.75),
        "maximum": max(values),
        "current": current,
        "current_percentile": percentile_position,
    }
    return metrics, tuple(item["evidence_id"] for item in observations)


def route_methods(
    book: EvidenceBook,
    capabilities: Mapping[str, CapabilityResult],
    company: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    *,
    as_of_date: str,
) -> dict[str, MethodResult]:
    context = context or {}
    company_type = str(context.get("company_type", "general")).strip().lower()
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
            metrics={"peer_count": int(context.get("peer_count", 0) or 0)},
        )
    elif isinstance(context.get("peer_case"), Mapping):
        try:
            peer_metrics, peer_evidence_ids = _peer_metrics(book, context["peer_case"])
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
            metrics={"peer_count": int(context.get("peer_count", 0) or 0)},
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
            metrics, historical_evidence_ids = _historical_metrics(
                context.get("historical_multiples"),
                book,
                as_of_date,
                {"price_to_sales": "ps", "ev_to_ebitda": "ev_ebitda"}.get(
                    str(context.get("historical_metric", "pe")).strip().lower(),
                    str(context.get("historical_metric", "pe")).strip().lower(),
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
        case = context.get("dcf_case")
        assert isinstance(case, Mapping)
        try:
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
                if context.get("mid_cycle_case") is None
                else "已收到中周期输入，但完整 builder、证据校验和计算尚未实现，不能标记为已完成方法。"
            ),
            missing_fields=("mid_cycle_builder",),
            assumptions={"input_received": context.get("mid_cycle_case") is not None},
        )

    return methods
