from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from datetime import date
from decimal import Decimal
from typing import Any, Mapping

from ..financial import FinancialQuantity
from ..forecast import (
    ForecastGraph,
    ForecastQuantity,
    ForecastRequest,
)
from .contracts import (
    BiopharmaEventSpec,
    BiopharmaValuationSpec,
    MethodBlocked,
    MethodCalculationResult,
    ScenarioMethodResult,
    ScenarioRole,
    ValuationAssumption,
    ValuationPlan,
    ValuationSensitivity,
    decimal_text,
    isolate_method,
    merge_refs,
)
from .basis import ValuationBasis, ValuationContext


@dataclass(frozen=True)
class AssetCashFlowEntry:
    asset_key: str
    cash_flow_type: str
    source_period: str
    shifted_period: str
    timing_act365: str
    amount: str

    def to_dict(self) -> dict[str, str]:
        return {
            "asset_key": self.asset_key,
            "cash_flow_type": self.cash_flow_type,
            "source_period": self.source_period,
            "shifted_period": self.shifted_period,
            "timing_act365": self.timing_act365,
            "amount": self.amount,
        }


@dataclass(frozen=True)
class CorporateCashFlowEntry:
    cash_flow_type: str
    period: str
    timing_act365: str
    amount: str
    record_id: str | None = None
    issue_price: str | None = None
    new_shares: str | None = None

    def to_dict(self) -> dict[str, str]:
        result = {
            "cash_flow_type": self.cash_flow_type,
            "period": self.period,
            "timing_act365": self.timing_act365,
            "amount": self.amount,
        }
        if self.record_id is not None:
            result.update(
                record_id=self.record_id,
                issue_price=self.issue_price or "0",
                new_shares=self.new_shares or "0",
            )
        return result


@dataclass(frozen=True)
class RunwayPeriodEntry:
    period: str
    opening_cash: Decimal
    asset_cash_flow: Decimal
    corporate_cash_burn: Decimal
    committed_financing: Decimal
    ending_cash: Decimal
    minimum_buffer: Decimal
    above_buffer: bool

    def to_trace_dict(self) -> BiopharmaProjection:
        return {
            "period": self.period,
            "opening_cash": decimal_text(self.opening_cash),
            "asset_cash_flow": decimal_text(self.asset_cash_flow),
            "corporate_cash_burn": decimal_text(self.corporate_cash_burn),
            "committed_financing": decimal_text(self.committed_financing),
            "ending_cash": decimal_text(self.ending_cash),
            "minimum_buffer": decimal_text(self.minimum_buffer),
            "above_buffer": self.above_buffer,
        }


@dataclass(frozen=True)
class RunwayPath:
    path_id: int
    events: Mapping[str, bool]
    ending_cash: Decimal
    minimum_cash: Decimal
    breach_period: str
    period_ledger: tuple[RunwayPeriodEntry, ...]

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "path_id": self.path_id,
            "events": dict(self.events),
            "ending_cash": decimal_text(self.ending_cash),
            "minimum_cash": decimal_text(self.minimum_cash),
            "breach_period": self.breach_period,
            "period_ledger": [item.to_trace_dict() for item in self.period_ledger],
        }


@dataclass(frozen=True)
class BiopharmaProjection:
    scenario_case: str
    values: tuple[Decimal, Decimal, Decimal]
    asset_values_by_rate: tuple[dict[str, Decimal], ...]
    event_probabilities: Mapping[str, Decimal]
    full_probabilities: Mapping[str, Decimal]
    ending_cash: Decimal
    minimum_cash: Decimal
    dilution: Decimal
    runway_paths: tuple[RunwayPath, ...]
    asset_cash_flow_trace: tuple[AssetCashFlowEntry, ...]
    corporate_cash_flow_trace: tuple[CorporateCashFlowEntry, ...]
    discount_rate_cases: tuple[Decimal, Decimal, Decimal]


class BiopharmaValuation:
    """Own the complete BiopharmaValuation method-family economics."""

    BIOPHARMA_RNPV_FORMULA_VERSION = "pipeline_rnpv_event_tree_act365@1"
    BIOPHARMA_SOTP_FORMULA_VERSION = "pipeline_sotp_unique_rights_act365@1"

    def __init__(self, basis: ValuationBasis) -> None:
        self._basis = basis

    def evaluate(
        self,
        context: ValuationContext,
        plan: ValuationPlan,
        scenario_role: ScenarioRole,
    ) -> tuple[ScenarioMethodResult, ...]:
        graph = context.graph
        base_request = context.request
        horizon = f"terminal_period={context.periods[-1]}"
        spec = plan.biopharma
        method_definitions = (
            (
                "pipeline_rnpv",
                self.BIOPHARMA_RNPV_FORMULA_VERSION,
                "Finite asset/indication rNPV discounts probability-gated development, milestone, licensing, and commercial cash flows.",
            ),
            (
                "pipeline_sotp",
                self.BIOPHARMA_SOTP_FORMULA_VERSION,
                "Pipeline SOTP aggregates each unique economic right exactly once using the same audited event-tree cash flows.",
            ),
        )
        horizon = (
            f"valuation_as_of={self._basis.as_of(graph)};"
            f"pipeline_periods={self._basis.periods(graph)[0]}..{self._basis.periods(graph)[-1]}"
        )
        if spec is None:
            return tuple(
                ScenarioMethodResult(
                    method_id=method_id,
                    status="blocked",
                    applicability=(
                        "Pre-revenue biopharma requires typed asset/indication "
                        "cash flows, calibrated event probabilities, licensing "
                        "terms, and a financing-aware cash-runway schedule."
                    ),
                    value_basis="enterprise_value",
                    horizon=horizon,
                    assumptions=(),
                    formula_version=formula_version,
                    conditional_value_range=None,
                    sensitivity=(),
                    diagnostics=(
                        "BIOPHARMA_SPECIALIZED_INPUT_MISSING: no biopharma valuation specification was supplied.",
                    ),
                    lineage_refs=("Assumption:biopharma_spec_missing",),
                )
                for method_id, formula_version, _ in method_definitions
            )
        common_refs = merge_refs(
            spec.lineage_refs,
            plan.present_value_bridge.provenance_refs,
        )
        results: list[ScenarioMethodResult] = []
        scenario_case = {
            ScenarioRole.STRESS: "low",
            ScenarioRole.BASE: "base",
            ScenarioRole.IMPROVEMENT: "high",
        }[scenario_role]
        for method_id, formula_version, diagnostic in method_definitions:
            result = isolate_method(
                method_id,
                (
                    "Applicable to a pre-revenue or pipeline-driven biopharma "
                    "company; ordinary FCFF and mature-company multiples are disabled."
                ),
                "enterprise_value",
                horizon,
                graph,
                formula_version,
                lambda formula_version=formula_version, diagnostic=diagnostic: (
                    self._biopharma_value(
                        graph,
                        plan,
                        base_request,
                        spec,
                        scenario_role,
                        formula_version=formula_version,
                        method_diagnostic=diagnostic,
                    )
                ),
                common_refs,
            )
            trace: list[dict[str, Any]] = [
                {
                    "kind": "biopharma_model_spec",
                    "scenario_case": scenario_case,
                    "model_spec": spec.to_dict(),
                }
            ]
            if result.status == "ready":
                projection = self._project(
                    graph,
                    plan,
                    base_request,
                    spec,
                    scenario_role,
                )
                trace.append(
                    {
                        "kind": "biopharma_selected_projection",
                        "scenario_case": scenario_case,
                        "event_probabilities": {
                            key: decimal_text(value)
                            for key, value in projection.event_probabilities.items()
                        },
                        "asset_cash_flows": [
                            item.to_dict() for item in projection.asset_cash_flow_trace
                        ],
                        "corporate_cash_flows": [
                            item.to_dict()
                            for item in projection.corporate_cash_flow_trace
                        ],
                        "discount_rate_cases": [
                            decimal_text(value)
                            for value in projection.discount_rate_cases
                        ],
                        "enterprise_value_range": [
                            decimal_text(value) for value in projection.values
                        ],
                        "runway_paths": [
                            path.to_trace_dict() for path in projection.runway_paths
                        ],
                    }
                )
            results.append(
                replace(
                    result,
                    component_trace=tuple(
                        json.dumps(
                            item,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        for item in trace
                    ),
                )
            )
        return tuple(results)

    def _validate_biopharma_runtime(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: BiopharmaValuationSpec,
    ) -> None:
        self._basis.validate_method_bridge(
            graph,
            plan.present_value_bridge,
            base_request,
        )
        periods = self._basis.periods(graph)
        if (
            tuple(item.period for item in spec.runway_periods) != periods
            or any(
                tuple(item.period for item in asset.periods) != periods
                for asset in spec.assets
            )
            or any(event.period not in periods for event in spec.events)
        ):
            raise MethodBlocked(
                "BIOPHARMA_PERIOD_COVERAGE_INVALID: events, assets, and runway must bind the routed finite forecast periods."
            )
        as_of = self._basis.as_of(graph)
        top_quantities = (
            spec.opening_cash,
            spec.minimum_cash_buffer,
            spec.discount_rate_low,
            spec.discount_rate_base,
            spec.discount_rate_high,
        )
        nested_quantities = tuple(
            quantity
            for owner in (
                *spec.events,
                *spec.assets,
                *(period for asset in spec.assets for period in asset.periods),
                *spec.runway_periods,
            )
            for field in fields(owner)
            for quantity in (getattr(owner, field.name),)
            if isinstance(
                quantity,
                (ForecastQuantity, FinancialQuantity),
            )
        )
        financing_quantities = tuple(
            quantity
            for runway in spec.runway_periods
            if runway.financing is not None
            for quantity in (
                runway.financing.proceeds,
                runway.financing.issue_price,
                runway.financing.new_shares,
            )
        )
        if any(
            quantity.as_of != as_of
            for quantity in (
                *top_quantities,
                *nested_quantities,
                *financing_quantities,
            )
        ):
            raise MethodBlocked(
                "BIOPHARMA_AS_OF_INVALID: every pipeline, probability, licensing, runway, and financing input must bind the frozen valuation as-of."
            )
        if (
            spec.opening_cash.period != plan.present_value_bridge.balance_sheet_period
            or spec.minimum_cash_buffer.period
            != plan.present_value_bridge.balance_sheet_period
        ):
            raise MethodBlocked(
                "BIOPHARMA_OPENING_PERIOD_INVALID: opening cash and minimum buffer must bind the present-value bridge balance-sheet period."
            )
        reporting_currency = base_request.security.reporting_currency
        money_quantities = tuple(
            quantity
            for quantity in (
                *top_quantities,
                *nested_quantities,
                *financing_quantities,
            )
            if isinstance(quantity, FinancialQuantity) and quantity.kind == "money"
        )
        if any(
            quantity.currency != reporting_currency
            or quantity.unit != reporting_currency
            for quantity in money_quantities
        ):
            raise MethodBlocked(
                "BIOPHARMA_CURRENCY_MISMATCH: every pipeline and runway money quantity must use the reporting currency."
            )
        if (
            spec.opening_cash.normalized_value
            != base_request.data_snapshot.company_opening_balance_sheet.cash.normalized_value
            or spec.opening_cash.period
            != base_request.data_snapshot.company_opening_balance_sheet.cash.period
            or spec.opening_cash.currency
            != base_request.data_snapshot.company_opening_balance_sheet.cash.currency
        ):
            raise MethodBlocked(
                "BIOPHARMA_OPENING_CASH_RECONCILIATION_INVALID: runway opening cash must equal the frozen opening balance-sheet cash used by the equity bridge."
            )
        for asset in spec.assets:
            valuation_date_quantities = (
                asset.ownership_low,
                asset.ownership_base,
                asset.ownership_high,
                asset.royalty_burden_low,
                asset.royalty_burden_base,
                asset.royalty_burden_high,
                asset.launch_delay_years_low,
                asset.launch_delay_years_base,
                asset.launch_delay_years_high,
                asset.delay_carry_cost_low,
                asset.delay_carry_cost_base,
                asset.delay_carry_cost_high,
            )
            if any(quantity.period != as_of for quantity in valuation_date_quantities):
                raise MethodBlocked(
                    "BIOPHARMA_ASSUMPTION_PERIOD_INVALID: ownership, royalties, delay, and delay carry cost must bind the valuation as-of."
                )
        if any(
            quantity.period != as_of
            for quantity in (
                spec.discount_rate_low,
                spec.discount_rate_base,
                spec.discount_rate_high,
            )
        ):
            raise MethodBlocked(
                "BIOPHARMA_DISCOUNT_RATE_PERIOD_INVALID: discount rates must bind the valuation as-of."
            )
        facts = {fact.fact_id: fact for fact in base_request.data_snapshot.facts}
        opening_facts = tuple(
            facts.get(ref.removeprefix("Fact:"))
            for ref in spec.opening_cash.provenance_refs
        )
        if any(fact is None for fact in opening_facts) or not any(
            fact.subject_id == graph.security_id
            and fact.scope == "company"
            and fact.metric_id == "cash"
            and fact.value == spec.opening_cash.normalized_value
            and fact.unit == spec.opening_cash.unit
            and fact.currency == spec.opening_cash.currency
            and fact.period == spec.opening_cash.period
            and fact.official
            and date.fromisoformat(fact.available_at) <= date.fromisoformat(as_of)
            for fact in opening_facts
            if fact is not None
        ):
            raise MethodBlocked(
                "BIOPHARMA_OPENING_CASH_EVIDENCE_INVALID: opening cash must resolve exactly through an official frozen fact."
            )
        for event in spec.events:
            resolved = tuple(
                facts.get(ref.removeprefix("Fact:")) for ref in event.base_fact_refs
            )
            if any(fact is None for fact in resolved) or not any(
                fact.subject_id == graph.security_id
                and fact.scope == "company"
                and fact.metric_id == "biopharma_event_probability"
                and fact.field_name == event.event_id
                and fact.value == event.probability_base.normalized_value
                and fact.unit == "decimal"
                and fact.currency == "N/A"
                and fact.period == event.period
                and fact.source_id == event.calibration_record_id
                and date.fromisoformat(event.calibration_window_end)
                <= date.fromisoformat(as_of)
                and date.fromisoformat(fact.available_at)
                >= date.fromisoformat(event.calibration_window_end)
                and date.fromisoformat(fact.available_at) <= date.fromisoformat(as_of)
                for fact in resolved
                if fact is not None
            ):
                raise MethodBlocked(
                    "BIOPHARMA_PROBABILITY_EVIDENCE_INVALID: every event probability must resolve through its exact registered calibration record, method, conditional basis, window, and sample."
                )
        for runway in spec.runway_periods:
            financing = runway.financing
            if financing is None:
                continue
            source_id = f"COMMITTED_FINANCING:{financing.record_id}"
            expected = (
                (
                    "biopharma_financing_proceeds",
                    financing.proceeds,
                ),
                (
                    "biopharma_financing_issue_price",
                    financing.issue_price,
                ),
                (
                    "biopharma_financing_new_shares",
                    financing.new_shares,
                ),
            )
            for metric_id, quantity in expected:
                resolved = tuple(
                    facts.get(ref.removeprefix("Fact:"))
                    for ref in quantity.provenance_refs
                )
                if any(fact is None for fact in resolved) or not any(
                    fact.subject_id == graph.security_id
                    and fact.scope == "company"
                    and fact.metric_id == metric_id
                    and fact.field_name == financing.record_id
                    and fact.value == quantity.normalized_value
                    and fact.unit == quantity.unit
                    and fact.currency == quantity.currency
                    and fact.period == financing.period
                    and fact.source_id == source_id
                    and fact.official
                    and date.fromisoformat(fact.available_at)
                    <= date.fromisoformat(as_of)
                    for fact in resolved
                    if fact is not None
                ):
                    raise MethodBlocked(
                        "BIOPHARMA_FINANCING_EVIDENCE_INVALID: financing proceeds, issue price, and new shares must resolve exactly to frozen committed terms."
                    )
        events = {item.event_id: item for item in spec.events}
        for asset in spec.assets:
            closure = self._biopharma_event_closure(
                events,
                asset.required_event_ids,
            )
            if any(
                period.milestone_event_id and period.milestone_event_id not in closure
                for period in asset.periods
            ):
                raise MethodBlocked(
                    "BIOPHARMA_MILESTONE_EVENT_INVALID: milestone cash must bind an event in the asset's dependency path."
                )

    def _biopharma_event_closure(
        self,
        events: Mapping[str, BiopharmaEventSpec],
        event_ids: tuple[str, ...],
    ) -> set[str]:
        closure: set[str] = set()
        stack = list(event_ids)
        while stack:
            event_id = stack.pop()
            if event_id in closure:
                continue
            closure.add(event_id)
            stack.extend(events[event_id].parent_event_ids)
        return closure

    def _project(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: BiopharmaValuationSpec,
        scenario_role: ScenarioRole,
    ) -> dict[str, Any]:
        self._validate_biopharma_runtime(
            graph,
            plan,
            base_request,
            spec,
        )
        if plan.present_value_bridge.diluted_shares is None:
            raise MethodBlocked(
                "BIOPHARMA_DILUTION_BASIS_MISSING: pipeline valuation requires an opening diluted-share basis because committed financing can change the share count."
            )
        scenario_case = {
            ScenarioRole.STRESS: "low",
            ScenarioRole.BASE: "base",
            ScenarioRole.IMPROVEMENT: "high",
        }[scenario_role]
        adverse_case = {
            "low": "high",
            "base": "base",
            "high": "low",
        }[scenario_case]
        periods = self._basis.periods(graph)
        valuation_date = date.fromisoformat(self._basis.as_of(graph))

        def period_date(period: str, delay: int = 0) -> date:
            return date(int(period[:4]) + delay, 12, 31)

        def discount_time(period: str, delay: int = 0) -> Decimal:
            return Decimal(
                (period_date(period, delay) - valuation_date).days
            ) / Decimal("365")

        events = {item.event_id: item for item in spec.events}
        event_probabilities = {
            event.event_id: getattr(
                event,
                f"probability_{scenario_case}",
            ).normalized_value
            for event in spec.events
        }

        def probability(event_ids: set[str]) -> Decimal:
            result = Decimal("1")
            for event_id in sorted(event_ids):
                result *= event_probabilities[event_id]
            return result

        asset_components: dict[
            str,
            tuple[tuple[Decimal, Decimal], ...],
        ] = {}
        asset_cash_flow_trace: list[AssetCashFlowEntry] = []
        full_probabilities: dict[str, Decimal] = {}
        for asset in spec.assets:
            closure = self._biopharma_event_closure(
                events,
                asset.required_event_ids,
            )
            full_probability = probability(closure)
            full_probabilities[f"{asset.asset_id}:{asset.indication_id}"] = (
                full_probability
            )
            ownership = getattr(
                asset,
                f"ownership_{scenario_case}",
            ).normalized_value
            royalty = getattr(
                asset,
                f"royalty_burden_{adverse_case}",
            ).normalized_value
            delay = getattr(
                asset,
                f"launch_delay_years_{adverse_case}",
            ).normalized_value
            delay_years = int(delay)
            carry_cost = getattr(
                asset,
                f"delay_carry_cost_{adverse_case}",
            ).normalized_value
            components: list[tuple[Decimal, Decimal]] = []
            for period_spec in asset.periods:
                period = period_spec.period
                period_year = int(period[:4])
                timing = discount_time(period, delay_years)
                prior_events = {
                    event_id
                    for event_id in closure
                    if int(events[event_id].period[:4]) < period_year
                }
                survival_probability = probability(prior_events)
                gross_sales = getattr(
                    period_spec,
                    f"gross_sales_{scenario_case}",
                ).normalized_value
                commercial_cost_rate = getattr(
                    period_spec,
                    f"commercial_cost_rate_{adverse_case}",
                ).normalized_value
                expected_sales = (
                    gross_sales
                    * ownership
                    * (Decimal("1") - royalty)
                    * (Decimal("1") - commercial_cost_rate)
                    * full_probability
                )
                development_cost = getattr(
                    period_spec,
                    f"development_cost_{adverse_case}",
                ).normalized_value
                expected_development_cost = development_cost * survival_probability
                milestone_cash = getattr(
                    period_spec,
                    f"milestone_cash_{scenario_case}",
                ).normalized_value
                milestone_probability = (
                    probability(
                        self._biopharma_event_closure(
                            events,
                            (period_spec.milestone_event_id,),
                        )
                    )
                    if period_spec.milestone_event_id
                    else Decimal("1")
                )
                expected_milestone = milestone_cash * milestone_probability
                components.extend(
                    (
                        (expected_sales, timing),
                        (-expected_development_cost, timing),
                        (expected_milestone, timing),
                    )
                )
                shifted_period = f"{int(period[:4]) + delay_years}E"
                asset_cash_flow_trace.extend(
                    (
                        AssetCashFlowEntry(
                            asset_key=f"{asset.asset_id}:{asset.indication_id}",
                            cash_flow_type="commercial_cash",
                            source_period=period,
                            shifted_period=shifted_period,
                            timing_act365=decimal_text(timing),
                            amount=decimal_text(expected_sales),
                        ),
                        AssetCashFlowEntry(
                            asset_key=f"{asset.asset_id}:{asset.indication_id}",
                            cash_flow_type="development_cost",
                            source_period=period,
                            shifted_period=shifted_period,
                            timing_act365=decimal_text(timing),
                            amount=decimal_text(-expected_development_cost),
                        ),
                        AssetCashFlowEntry(
                            asset_key=f"{asset.asset_id}:{asset.indication_id}",
                            cash_flow_type="milestone_cash",
                            source_period=period,
                            shifted_period=shifted_period,
                            timing_act365=decimal_text(timing),
                            amount=decimal_text(expected_milestone),
                        ),
                    )
                )
            for carry_year in range(1, delay_years + 1):
                carry_anchor = max(
                    (events[event_id].period for event_id in closure),
                    key=lambda item: int(item[:4]),
                )
                carry_timing = discount_time(
                    carry_anchor,
                    carry_year,
                )
                components.append(
                    (
                        -(carry_cost * full_probability),
                        carry_timing,
                    )
                )
                asset_cash_flow_trace.append(
                    AssetCashFlowEntry(
                        asset_key=f"{asset.asset_id}:{asset.indication_id}",
                        cash_flow_type="delay_carry_cost",
                        source_period=carry_anchor,
                        shifted_period=f"{int(carry_anchor[:4]) + carry_year}E",
                        timing_act365=decimal_text(carry_timing),
                        amount=decimal_text(-(carry_cost * full_probability)),
                    )
                )
            asset_components[f"{asset.asset_id}:{asset.indication_id}"] = tuple(
                components
            )

        rate_cases = (
            spec.discount_rate_high.normalized_value,
            spec.discount_rate_base.normalized_value,
            spec.discount_rate_low.normalized_value,
        )
        corporate_components: list[tuple[Decimal, Decimal]] = []
        corporate_cash_flow_trace: list[CorporateCashFlowEntry] = []
        current_shares = plan.present_value_bridge.diluted_shares.normalized_value
        final_shares = current_shares
        for runway in spec.runway_periods:
            burn = getattr(
                runway,
                f"corporate_cash_burn_{adverse_case}",
            ).normalized_value
            financing = (
                runway.financing.proceeds.normalized_value
                if runway.financing is not None
                else Decimal("0")
            )
            if runway.financing is not None:
                final_shares += runway.financing.new_shares.normalized_value
            timing = discount_time(runway.period)
            corporate_components.extend(((-burn, timing), (financing, timing)))
            corporate_cash_flow_trace.extend(
                (
                    CorporateCashFlowEntry(
                        cash_flow_type="corporate_cash_burn",
                        period=runway.period,
                        timing_act365=decimal_text(timing),
                        amount=decimal_text(-burn),
                    ),
                    CorporateCashFlowEntry(
                        cash_flow_type="committed_financing",
                        period=runway.period,
                        timing_act365=decimal_text(timing),
                        amount=decimal_text(financing),
                        record_id=(
                            runway.financing.record_id if runway.financing else ""
                        ),
                        issue_price=(
                            decimal_text(runway.financing.issue_price.normalized_value)
                            if runway.financing
                            else "0"
                        ),
                        new_shares=(
                            decimal_text(runway.financing.new_shares.normalized_value)
                            if runway.financing
                            else "0"
                        ),
                    ),
                )
            )

        if len(spec.events) > 12:
            raise MethodBlocked(
                "BIOPHARMA_RUNWAY_PATH_LIMIT: more than 12 dependent events requires an explicit path-aggregation model."
            )
        ordered_events: list[BiopharmaEventSpec] = []
        remaining = list(spec.events)
        while remaining:
            ready = [
                event
                for event in remaining
                if all(
                    parent_id in {item.event_id for item in ordered_events}
                    for parent_id in event.parent_event_ids
                )
            ]
            if not ready:
                raise MethodBlocked(
                    "BIOPHARMA_EVENT_DEPENDENCY_INVALID: event paths could not be ordered."
                )
            ready.sort(key=lambda item: (item.period, item.event_id))
            ordered_events.extend(ready)
            remaining = [item for item in remaining if item not in ready]

        path_states: list[dict[str, bool]] = [dict()]
        for event in ordered_events:
            next_states: list[dict[str, bool]] = []
            conditional_probability = event_probabilities[event.event_id]
            for state in path_states:
                if any(not state[parent_id] for parent_id in event.parent_event_ids):
                    next_states.append({**state, event.event_id: False})
                    continue
                if conditional_probability < 1:
                    next_states.append({**state, event.event_id: False})
                if conditional_probability > 0:
                    next_states.append({**state, event.event_id: True})
            path_states = next_states

        path_results: list[RunwayPath] = []
        for path_index, state in enumerate(path_states):
            path_cash_flows = {period: Decimal("0") for period in periods}
            for asset in spec.assets:
                closure = self._biopharma_event_closure(
                    events,
                    asset.required_event_ids,
                )
                ownership = getattr(
                    asset, f"ownership_{scenario_case}"
                ).normalized_value
                royalty = getattr(
                    asset, f"royalty_burden_{adverse_case}"
                ).normalized_value
                delay_years = int(
                    getattr(
                        asset,
                        f"launch_delay_years_{adverse_case}",
                    ).normalized_value
                )
                for period_spec in asset.periods:
                    shifted_year = int(period_spec.period[:4]) + delay_years
                    development_cost = getattr(
                        period_spec,
                        f"development_cost_{adverse_case}",
                    ).normalized_value
                    milestone_cash = getattr(
                        period_spec,
                        f"milestone_cash_{scenario_case}",
                    ).normalized_value
                    shifted_period = next(
                        (item for item in periods if int(item[:4]) == shifted_year),
                        "",
                    )
                    if not shifted_period:
                        if development_cost > 0 or milestone_cash < 0:
                            raise MethodBlocked(
                                "BIOPHARMA_RUNWAY_COVERAGE_INSUFFICIENT: "
                                f"{asset.asset_id}:{asset.indication_id} has a delayed cash obligation in {shifted_year}E beyond the declared runway."
                            )
                        continue
                    prior_events = {
                        event_id
                        for event_id in closure
                        if int(events[event_id].period[:4])
                        < int(period_spec.period[:4])
                    }
                    if all(state[event_id] for event_id in prior_events):
                        path_cash_flows[shifted_period] -= development_cost
                    if (
                        not period_spec.milestone_event_id
                        or state[period_spec.milestone_event_id]
                    ):
                        path_cash_flows[shifted_period] += milestone_cash
                    if all(state[event_id] for event_id in closure):
                        gross_sales = getattr(
                            period_spec,
                            f"gross_sales_{scenario_case}",
                        ).normalized_value
                        cost_rate = getattr(
                            period_spec,
                            f"commercial_cost_rate_{adverse_case}",
                        ).normalized_value
                        path_cash_flows[shifted_period] += (
                            gross_sales
                            * ownership
                            * (Decimal("1") - royalty)
                            * (Decimal("1") - cost_rate)
                        )
                carry_cost = getattr(
                    asset,
                    f"delay_carry_cost_{adverse_case}",
                ).normalized_value
                if delay_years and all(state[event_id] for event_id in closure):
                    carry_anchor_year = max(
                        int(events[event_id].period[:4]) for event_id in closure
                    )
                    for carry_year in range(1, delay_years + 1):
                        shifted_year = carry_anchor_year + carry_year
                        shifted_period = next(
                            (item for item in periods if int(item[:4]) == shifted_year),
                            "",
                        )
                        if not shifted_period and carry_cost > 0:
                            raise MethodBlocked(
                                "BIOPHARMA_RUNWAY_COVERAGE_INSUFFICIENT: "
                                f"{asset.asset_id}:{asset.indication_id} has delay carry cost in {shifted_year}E beyond the declared runway."
                            )
                        if shifted_period:
                            path_cash_flows[shifted_period] -= carry_cost
            cash = spec.opening_cash.normalized_value
            minimum_cash = cash
            breach_period = ""
            period_ledger: list[RunwayPeriodEntry] = []
            for runway in spec.runway_periods:
                financing = (
                    runway.financing.proceeds.normalized_value
                    if runway.financing is not None
                    else Decimal("0")
                )
                burn = getattr(
                    runway,
                    f"corporate_cash_burn_{adverse_case}",
                ).normalized_value
                opening_cash = cash
                cash += path_cash_flows[runway.period] - burn + financing
                minimum_cash = min(minimum_cash, cash)
                period_ledger.append(
                    RunwayPeriodEntry(
                        period=runway.period,
                        opening_cash=opening_cash,
                        asset_cash_flow=path_cash_flows[runway.period],
                        corporate_cash_burn=burn,
                        committed_financing=financing,
                        ending_cash=cash,
                        minimum_buffer=spec.minimum_cash_buffer.normalized_value,
                        above_buffer=(
                            cash >= spec.minimum_cash_buffer.normalized_value
                        ),
                    )
                )
                if (
                    not breach_period
                    and cash < spec.minimum_cash_buffer.normalized_value
                ):
                    breach_period = runway.period
            path_results.append(
                RunwayPath(
                    path_id=path_index,
                    events=dict(sorted(state.items())),
                    ending_cash=cash,
                    minimum_cash=minimum_cash,
                    breach_period=breach_period,
                    period_ledger=tuple(period_ledger),
                )
            )
        breached = next(
            (item for item in path_results if item.breach_period),
            None,
        )
        if breached is not None:
            raise MethodBlocked(
                "BIOPHARMA_RUNWAY_PATH_BREACH: "
                f"path={breached.path_id} falls below the minimum buffer in {breached.breach_period}."
            )
        minimum_path = min(
            path_results,
            key=lambda item: item.minimum_cash,
        )
        ending_path = min(
            path_results,
            key=lambda item: item.ending_cash,
        )
        cumulative_dilution = final_shares / current_shares
        asset_values_by_rate: list[dict[str, Decimal]] = []
        total_values: list[Decimal] = []
        for rate in rate_cases:
            by_asset = {
                asset_key: sum(
                    (
                        cash_flow / ((Decimal("1") + rate) ** timing)
                        for cash_flow, timing in components
                    ),
                    Decimal("0"),
                )
                for asset_key, components in asset_components.items()
            }
            corporate_value = sum(
                (
                    cash_flow / ((Decimal("1") + rate) ** timing)
                    for cash_flow, timing in corporate_components
                ),
                Decimal("0"),
            )
            asset_values_by_rate.append(by_asset)
            total_values.append(sum(by_asset.values(), Decimal("0")) + corporate_value)
        values = (
            min(total_values),
            total_values[1],
            max(total_values),
        )
        return BiopharmaProjection(
            scenario_case=scenario_case,
            values=values,
            asset_values_by_rate=tuple(asset_values_by_rate),
            event_probabilities=event_probabilities,
            full_probabilities=full_probabilities,
            ending_cash=ending_path.ending_cash,
            minimum_cash=minimum_path.minimum_cash,
            dilution=cumulative_dilution,
            runway_paths=tuple(path_results),
            asset_cash_flow_trace=tuple(asset_cash_flow_trace),
            corporate_cash_flow_trace=tuple(corporate_cash_flow_trace),
            discount_rate_cases=rate_cases,
        )

    def _biopharma_value(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: BiopharmaValuationSpec,
        scenario_role: ScenarioRole,
        *,
        formula_version: str,
        method_diagnostic: str,
    ) -> MethodCalculationResult:
        projection = self._project(
            graph,
            plan,
            base_request,
            spec,
            scenario_role,
        )
        lineage = merge_refs(
            spec.lineage_refs,
            graph.quantity(
                f"biopharma.horizon.{self._basis.periods(graph)[0]}"
            ).lineage_refs,
            (
                "Assumption:biopharma_scenario_case:" f"{projection.scenario_case}",
                f"Assumption:formula:{formula_version}",
            ),
        )
        dilution = projection.dilution
        value_range = self._basis.bridge_range(
            graph,
            plan.present_value_bridge,
            "enterprise_value",
            projection.values,
            formula_version,
            basis_period=plan.present_value_bridge.balance_sheet_period,
            basis_refs=lineage,
            share_multipliers=(dilution, dilution, dilution),
            share_multiplier_ref_prefix="biopharma_cumulative_dilution",
        )
        if any(
            point.equity_value.normalized_value <= 0
            for point in (
                value_range.low,
                value_range.base,
                value_range.high,
            )
        ):
            raise MethodBlocked(
                "BIOPHARMA_COMMON_EQUITY_INVALID: enterprise pipeline value less debt, preferred claims, and other bridge adjustments does not support positive common equity."
            )
        reporting_currency = base_request.security.reporting_currency
        ending_cash = ForecastQuantity(
            value=projection.ending_cash,
            unit=reporting_currency,
            scale=Decimal("1"),
            currency=reporting_currency,
            period=self._basis.periods(graph)[-1],
            as_of=self._basis.as_of(graph),
            lineage_refs=lineage,
        )
        minimum_cash = ForecastQuantity(
            value=projection.minimum_cash,
            unit=reporting_currency,
            scale=Decimal("1"),
            currency=reporting_currency,
            period=self._basis.periods(graph)[-1],
            as_of=self._basis.as_of(graph),
            lineage_refs=lineage,
        )
        dilution_quantity = self._basis.model_quantity(
            dilution,
            unit="x",
            period=self._basis.periods(graph)[-1],
            as_of=self._basis.as_of(graph),
            refs=lineage,
        )
        assumptions = (
            ValuationAssumption(
                "discount_rate",
                spec.discount_rate_base,
            ),
            ValuationAssumption(
                "ending_cash_after_committed_financing",
                ending_cash,
            ),
            ValuationAssumption(
                "minimum_cash_during_runway",
                minimum_cash,
            ),
            ValuationAssumption(
                "cumulative_dilution_factor",
                dilution_quantity,
            ),
        )
        sensitivity = (
            ValuationSensitivity(
                "discount_rate",
                spec.discount_rate_low,
                spec.discount_rate_base,
                spec.discount_rate_high,
            ),
            *(
                ValuationSensitivity(
                    f"event_probability:{event.event_id}",
                    event.probability_low,
                    event.probability_base,
                    event.probability_high,
                )
                for event in spec.events
            ),
            *(
                ValuationSensitivity(
                    f"ownership:{asset.asset_id}:{asset.indication_id}",
                    asset.ownership_low,
                    asset.ownership_base,
                    asset.ownership_high,
                )
                for asset in spec.assets
            ),
            *(
                ValuationSensitivity(
                    f"royalty_burden:{asset.asset_id}:{asset.indication_id}",
                    asset.royalty_burden_low,
                    asset.royalty_burden_base,
                    asset.royalty_burden_high,
                )
                for asset in spec.assets
            ),
            *(
                ValuationSensitivity(
                    f"launch_delay:{asset.asset_id}:{asset.indication_id}",
                    asset.launch_delay_years_low,
                    asset.launch_delay_years_base,
                    asset.launch_delay_years_high,
                )
                for asset in spec.assets
            ),
        )
        base_asset_values = projection.asset_values_by_rate[1]
        diagnostics = (
            method_diagnostic,
            (
                "Scenario event probabilities: "
                + ", ".join(
                    f"{event_id}={decimal_text(value)}"
                    for event_id, value in sorted(
                        projection.event_probabilities.items()
                    )
                )
            ),
            (
                "Base-rate unique-right SOTP contributions: "
                + ", ".join(
                    f"{asset_key}={decimal_text(value)}"
                    for asset_key, value in sorted(base_asset_values.items())
                )
            ),
            (
                "Asset cumulative success probabilities: "
                + ", ".join(
                    f"{asset_key}={decimal_text(value)}"
                    for asset_key, value in sorted(
                        projection.full_probabilities.items()
                    )
                )
            ),
            (
                "Cash runway remains above the declared buffer after committed "
                f"financing; minimum={decimal_text(projection.minimum_cash)}, "
                f"ending={decimal_text(projection.ending_cash)}, cumulative "
                f"dilution={decimal_text(dilution)}."
            ),
            "Financing proceeds enter post-financing equity value and cash runway together with their declared share dilution; no issuance economics are invented.",
            "Low/high conditional bounds are the minimum and maximum audited discount-rate cases around the declared base case because early development outflows can make rNPV non-monotonic in the discount rate.",
            "Only declared asset/indication economic rights are valued; platform know-how or technical reserves receive no automatic mature-revenue or full-probability value.",
            "Shared parent events are evaluated once per asset dependency closure, preserving correlated failure exposure without duplicate probability multiplication.",
        )
        return value_range, assumptions, sensitivity, lineage, diagnostics
