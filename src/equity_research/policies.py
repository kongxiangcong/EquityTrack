from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .evidence import EvidenceBook
from .models import CapabilityResult
from trading_platform.domain.research_inputs import ResearchInputs


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    label: str
    required_official: tuple[str, ...] = ()
    required_sourced: tuple[str, ...] = ()
    estimate_allowed: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    context_checks: tuple[str, ...] = ()


CAPABILITY_SPECS = (
    CapabilitySpec(
        "research_core",
        "基础研究",
        required_official=("revenue", "net_income", "cash", "debt"),
        optional_fields=("cfo", "eps", "current_price", "market_cap", "working_capital"),
    ),
    CapabilitySpec(
        "earnings_quality",
        "盈利质量",
        required_official=("net_income", "cfo"),
        optional_fields=("fcf", "capex", "working_capital", "cash"),
    ),
    CapabilitySpec(
        "per_share_context",
        "每股与市场口径",
        required_official=("eps", "diluted_shares"),
        required_sourced=("current_price",),
        optional_fields=("market_cap", "sbc_options_dilution"),
    ),
    CapabilitySpec(
        "financial_model",
        "财务模型与情景",
        required_official=(
            "revenue",
            "ebit",
            "net_income",
            "tax",
            "capex",
            "cfo",
            "working_capital",
            "cash",
            "debt",
            "diluted_shares",
        ),
        estimate_allowed=("d_and_a", "lease_debt"),
        optional_fields=("fcf", "minority_interest", "preferred_stock"),
    ),
    CapabilitySpec(
        "dcf",
        "DCF",
        required_official=(
            "ebit",
            "tax",
            "capex",
            "working_capital",
            "cash",
            "debt",
            "minority_interest",
            "preferred_stock",
            "pension_deficit",
            "non_operating_assets",
            "associates_jv_value",
            "diluted_shares",
        ),
        estimate_allowed=("d_and_a", "lease_debt"),
        context_checks=("dcf_case",),
    ),
    CapabilitySpec(
        "peer_comps",
        "可比公司估值",
        required_official=("eps", "diluted_shares"),
        required_sourced=("current_price",),
        optional_fields=("market_cap", "ebit", "d_and_a"),
        context_checks=("peer_count_at_least_3",),
    ),
    CapabilitySpec(
        "historical_band",
        "历史估值带",
        required_sourced=("current_price",),
        context_checks=("historical_multiples",),
    ),
    CapabilitySpec(
        "conditional_research_plan",
        "条件研究计划",
        required_official=("revenue", "net_income"),
        optional_fields=("cfo", "current_price", "working_capital", "cash", "debt"),
    ),
    CapabilitySpec(
        "research_report",
        "完整研究报告",
        required_official=("revenue", "net_income"),
        optional_fields=("cfo", "cash", "debt", "current_price", "market_cap"),
    ),
)


METHOD_SOURCE_TIERS = {"official", "terminal", "secondary"}
WACC_EVIDENCE_FIELDS = {
    "risk_free_rate": ("risk_free_rate", "wacc:risk_free_rate"),
    "equity_risk_premium": ("equity_risk_premium", "wacc:equity_risk_premium"),
    "beta": ("beta", "wacc:beta"),
    "pre_tax_cost_of_debt": ("pre_tax_cost_of_debt", "wacc:pre_tax_cost_of_debt"),
    "tax_rate": ("wacc_tax_rate", "wacc:tax_rate"),
    "equity_weight": ("equity_weight", "wacc:equity_weight"),
    "debt_weight": ("debt_weight", "wacc:debt_weight"),
}


def _peer_metric_key(metric: Any) -> str:
    value = str(metric or "pe").strip().lower()
    return {
        "price_to_sales": "ps",
        "ev_to_ebitda": "ev_ebitda",
    }.get(value, value)


def _peer_evidence(peer: Mapping[str, Any], metric: str, book: EvidenceBook) -> Any:
    ticker = str(peer.get("ticker", "")).strip()
    if not ticker:
        return None
    return book.resolve_reference(
        peer.get("evidence_ref"),
        allowed_tiers=METHOD_SOURCE_TIERS,
        expected_subject_id=ticker,
        expected_semantic_role=f"peer_multiple:{metric}",
    )


def _context_check(
    check: str,
    inputs: ResearchInputs,
    book: EvidenceBook,
) -> bool:
    if check == "dcf_case":
        case = inputs.dcf_case
        if not isinstance(case, Mapping):
            return False
        forecast_refs = case.get("forecast_evidence_refs")
        component_refs = case.get("wacc_component_evidence_refs")
        terminal_ref = case.get("terminal_growth_evidence_ref")
        forecast_items = (
            [
                book.resolve_reference(
                    value,
                    allowed_tiers=METHOD_SOURCE_TIERS,
                    expected_subject_id=book.subject_id,
                    expected_semantic_role="dcf_forecast_fcff",
                    expected_field_names={"dcf_fcff"},
                )
                for value in forecast_refs
            ]
            if isinstance(forecast_refs, list)
            else []
        )
        terminal_item = book.resolve_reference(
            terminal_ref,
            allowed_tiers=METHOD_SOURCE_TIERS,
            expected_subject_id=book.subject_id,
            expected_semantic_role="dcf_terminal_growth",
            expected_field_names={"terminal_growth"},
        )
        component_items = (
            {
                name: book.resolve_reference(
                    component_refs.get(name),
                    allowed_tiers=METHOD_SOURCE_TIERS,
                    expected_subject_id=book.subject_id,
                    expected_semantic_role=role,
                    expected_field_names={field_name},
                )
                for name, (field_name, role) in WACC_EVIDENCE_FIELDS.items()
            }
            if isinstance(component_refs, Mapping)
            else {}
        )
        input_ids = [
            item.evidence_id
            for item in forecast_items + [terminal_item] + list(component_items.values())
            if item is not None
        ]
        return (
            isinstance(forecast_refs, list)
            and len(forecast_refs) >= 2
            and len(forecast_items) == len(forecast_refs)
            and all(item is not None for item in forecast_items)
            and isinstance(case.get("wacc"), (int, float))
            and terminal_item is not None
            and isinstance(component_refs, Mapping)
            and len(component_items) == len(WACC_EVIDENCE_FIELDS)
            and all(item is not None for item in component_items.values())
            and len(input_ids) == len(set(input_ids))
            and isinstance(case.get("currency"), str)
            and bool(str(case.get("currency", "")).strip())
            and isinstance(case.get("forecast_unit_scale"), (int, float))
        )
    if check == "peer_count_at_least_3":
        peer_case = inputs.peer_case
        if isinstance(peer_case, Mapping):
            peers = peer_case.get("peers")
            if isinstance(peers, list):
                metric = _peer_metric_key(peer_case.get("metric", "pe"))
                usable: list[tuple[str, str]] = []
                for peer in peers:
                    if not isinstance(peer, Mapping):
                        continue
                    evidence_item = _peer_evidence(peer, metric, book)
                    if (
                        peer.get("usable", True) is not False
                        and bool(str(peer.get("period", "")).strip())
                        and peer.get("currency_checked") is True
                        and peer.get("accounting_checked") is True
                        and evidence_item is not None
                        and evidence_item.period == str(peer.get("period", "")).strip()
                    ):
                        usable.append((str(peer.get("ticker", "")).strip(), evidence_item.evidence_id))
                return (
                    len(usable) >= 3
                    and len({ticker for ticker, _ in usable}) == len(usable)
                    and len({evidence_id for _, evidence_id in usable}) == len(usable)
                )
        value = inputs.peer_count
        return isinstance(value, int) and value >= 3
    if check == "historical_multiples":
        values = inputs.historical_multiples
        if len(values) < 12:
            return False
        role = (
            "historical_multiple:"
            f"{_peer_metric_key(inputs.historical_metric)}"
        )
        resolved: list[tuple[str, str]] = []
        for item in values:
            if not isinstance(item, Mapping):
                return False
            date_text = str(item.get("date", "")).strip()
            evidence_item = book.resolve_reference(
                item.get("evidence_ref"),
                allowed_tiers=METHOD_SOURCE_TIERS,
                expected_subject_id=book.subject_id,
                expected_semantic_role=role,
            )
            if not date_text or evidence_item is None or evidence_item.period != date_text:
                return False
            resolved.append((date_text, evidence_item.evidence_id))
        return (
            len({date_text for date_text, _ in resolved}) == len(resolved)
            and len({evidence_id for _, evidence_id in resolved}) == len(resolved)
        )
    if check == "conditional_plan":
        return bool(inputs.conditional_plan)
    return False


def evaluate_capabilities(
    book: EvidenceBook,
    inputs: ResearchInputs,
) -> dict[str, CapabilityResult]:
    results: dict[str, CapabilityResult] = {}

    for spec in CAPABILITY_SPECS:
        sourced: list[str] = []
        estimated: list[str] = []
        missing: list[str] = []
        evidence_ids: list[str] = []

        for field_name in spec.required_official:
            item = book.best(field_name, official_only=True)
            if field_name in book.official_fields and item is not None:
                sourced.append(field_name)
                evidence_ids.append(item.evidence_id)
            else:
                missing.append(field_name)

        for field_name in spec.required_sourced:
            item = book.best(field_name)
            if field_name in book.sourced_fields and item is not None:
                sourced.append(field_name)
                evidence_ids.append(item.evidence_id)
            else:
                missing.append(field_name)

        for field_name in spec.estimate_allowed:
            official_item = book.best(field_name, official_only=True)
            estimate_item = book.best_estimate(field_name)
            if field_name in book.official_fields and official_item is not None:
                sourced.append(field_name)
                evidence_ids.append(official_item.evidence_id)
            elif field_name in book.estimated_fields and estimate_item is not None:
                estimated.append(field_name)
                evidence_ids.append(estimate_item.evidence_id)
            else:
                missing.append(field_name)

        optional_gaps = tuple(
            field_name for field_name in spec.optional_fields if field_name not in book.fields
        )
        context_gaps = tuple(
            check
            for check in spec.context_checks
            if not _context_check(check, inputs, book)
        )

        if missing or context_gaps:
            status = "blocked"
            explanation = "缺少该能力直接依赖的证据或结构化输入；其他能力不受影响。"
        elif estimated:
            status = "ready_with_estimates"
            explanation = "能力可用于探索情景；估算保持独立标签，不升级正式来源覆盖。"
        elif optional_gaps:
            status = "limited"
            explanation = "核心输入已满足，部分增强字段缺失，输出会显示限制。"
        else:
            status = "ready"
            explanation = "该能力的必要输入已满足。"

        required_fields = tuple(
            dict.fromkeys(spec.required_official + spec.required_sourced + spec.estimate_allowed)
        )
        results[spec.capability_id] = CapabilityResult(
            capability_id=spec.capability_id,
            label=spec.label,
            status=status,
            required_fields=required_fields,
            sourced_fields=tuple(dict.fromkeys(sourced)),
            estimated_fields=tuple(dict.fromkeys(estimated)),
            missing_fields=tuple(dict.fromkeys(missing)),
            optional_gaps=optional_gaps,
            context_gaps=context_gaps,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            explanation=explanation,
        )

    return results
