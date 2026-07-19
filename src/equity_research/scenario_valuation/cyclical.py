from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import cast

from ..financial import (
    FinancialQuantity,
)
from ..forecast import (
    ForecastGraph,
    ForecastQuantity,
    ForecastRequest,
)
from .contracts import (
    CyclicalResourceValuationSpec,
    MethodBlocked,
    MethodCalculationResult,
    ScenarioInvariantError,
    ScenarioMethodResult,
    ValuationAssumption,
    ValuationPlan,
    ValuationSensitivity,
    isolate_method,
    merge_refs,
    percentile,
)
from .basis import ValuationBasis, ValuationContext


class CyclicalValuation:
    """Own the complete CyclicalValuation method-family economics."""

    MID_CYCLE_FORMULA_VERSION = "cycle_normalized_ev_ebitda@1"
    RESOURCE_NAV_FORMULA_VERSION = "finite_resource_nav_after_tax@1"
    CYCLICAL_HISTORY_FORMULA_VERSION = "pit_cycle_band_derived_peak@2"

    def __init__(self, basis: ValuationBasis) -> None:
        self._basis = basis

    def evaluate(
        self, context: ValuationContext, plan: ValuationPlan
    ) -> tuple[ScenarioMethodResult, ...]:
        graph = context.graph
        base_request = context.request
        horizon = f"terminal_period={context.periods[-1]}"
        if context.reference_graph is None:
            raise ScenarioInvariantError(
                "CYCLICAL_REFERENCE_FORECAST_MISSING",
                "Cyclical valuation requires one engine-bound reference Forecast.",
            )
        reference_graph = context.reference_graph
        spec = plan.cyclical_resource
        missing_refs = ("Assumption:cyclical_resource_spec_missing",)
        if spec is None:
            return tuple(
                ScenarioMethodResult(
                    method_id=method_id,
                    status="blocked",
                    applicability=(
                        "Cyclical/resource route requires a versioned commodity curve, "
                        "asset reserves, cost, tax, life, and maintenance-capex inputs."
                    ),
                    value_basis=value_basis,
                    horizon=horizon,
                    assumptions=(),
                    formula_version=formula_version,
                    conditional_value_range=None,
                    sensitivity=(),
                    diagnostics=(
                        "CYCLICAL_RESOURCE_SPEC_MISSING: specialized cyclical valuation inputs are required.",
                    ),
                    lineage_refs=missing_refs,
                )
                for method_id, value_basis, formula_version in (
                    (
                        "mid_cycle_ev_ebitda",
                        "enterprise_value",
                        self.MID_CYCLE_FORMULA_VERSION,
                    ),
                    (
                        "resource_nav",
                        "enterprise_value",
                        self.RESOURCE_NAV_FORMULA_VERSION,
                    ),
                    (
                        "cyclical_historical_band",
                        "equity_value",
                        self.CYCLICAL_HISTORY_FORMULA_VERSION,
                    ),
                )
            )
        common_refs = merge_refs(
            spec.lineage_refs,
            plan.present_value_bridge.provenance_refs,
            plan.terminal_value_bridge.provenance_refs,
        )
        curve_label = (
            f"Applicable to {base_request.security.archetype.value}; "
            f"uses finite, versioned commodity curve {spec.curve_version} "
            f"as of {spec.curve_as_of}."
        )
        return (
            isolate_method(
                "mid_cycle_ev_ebitda",
                curve_label
                + " Normalizes price, volume, yield, and cost instead of extrapolating peak earnings.",
                "enterprise_value",
                horizon,
                graph,
                self.MID_CYCLE_FORMULA_VERSION,
                lambda: self._mid_cycle(
                    graph, reference_graph, plan, base_request, spec
                ),
                common_refs,
            ),
            isolate_method(
                "resource_nav",
                curve_label
                + " Discounts only finite reserve-backed after-tax cash flows.",
                "enterprise_value",
                f"valuation_as_of={self._basis.as_of(graph)};finite_resource_life",
                graph,
                self.RESOURCE_NAV_FORMULA_VERSION,
                lambda: self._resource_nav(
                    graph, reference_graph, plan, base_request, spec
                ),
                common_refs,
            ),
            isolate_method(
                "cyclical_historical_band",
                "PIT historical cross-check derives and excludes peak-earnings observations from the reusable range under a versioned threshold rule.",
                "equity_value",
                horizon,
                graph,
                self.CYCLICAL_HISTORY_FORMULA_VERSION,
                lambda: self._cyclical_historical_band(graph, plan, base_request, spec),
                common_refs,
            ),
        )

    def _validate_cyclical_runtime(
        self,
        graph: ForecastGraph,
        base_request: ForecastRequest,
        spec: CyclicalResourceValuationSpec,
        *,
        require_resources: bool = False,
    ) -> None:
        periods = self._basis.periods(graph)
        forecast_curve_keys = {
            (segment_id, period)
            for segment_id in base_request.security.segment_ids
            for period in periods
        }
        schedule_curve_keys = {
            (asset.segment_id, item.period)
            for asset in spec.assets
            for item in asset.schedule
        }
        curve_keys = {(item.segment_id, item.period) for item in spec.commodity_curve}
        asset_ids = {item.segment_id for item in spec.assets}
        if not forecast_curve_keys.issubset(curve_keys):
            raise MethodBlocked(
                "COMMODITY_CURVE_COVERAGE_INVALID: curve must cover every forecast segment-period."
            )
        if require_resources and curve_keys != schedule_curve_keys:
            raise MethodBlocked(
                "COMMODITY_CURVE_COVERAGE_INVALID: resource NAV curve must cover every finite resource-schedule segment-period exactly once."
            )
        if require_resources and asset_ids != set(base_request.security.segment_ids):
            raise MethodBlocked(
                "RESOURCE_ASSET_COVERAGE_INVALID: resource assets must cover every modeled segment exactly once."
            )
        if require_resources and any(
            asset.schedule[0].period != periods[0] for asset in spec.assets
        ):
            raise MethodBlocked(
                "RESOURCE_SCHEDULE_ANCHOR_INVALID: every finite-life resource schedule must begin at the first forward forecast period."
            )
        if date.fromisoformat(spec.curve_as_of) > date.fromisoformat(
            self._basis.as_of(graph)
        ) or any(
            item.price_base.as_of != self._basis.as_of(graph)
            for item in spec.commodity_curve
        ):
            raise MethodBlocked(
                "COMMODITY_CURVE_AS_OF_INVALID: curve version and points must bind the frozen valuation as-of."
            )
        reporting_currency = base_request.security.reporting_currency
        if any(
            point.price_base.currency != reporting_currency
            for point in spec.commodity_curve
        ) or (
            require_resources
            and any(
                quantity.currency != reporting_currency
                for asset in spec.assets
                for item in asset.schedule
                for quantity in (
                    item.unit_cost_low,
                    item.unit_cost_base,
                    item.unit_cost_high,
                    item.operating_expense_low,
                    item.operating_expense_base,
                    item.operating_expense_high,
                    item.maintenance_capex_low,
                    item.maintenance_capex_base,
                    item.maintenance_capex_high,
                )
            )
        ):
            raise MethodBlocked(
                "RESOURCE_REPORTING_CURRENCY_MISMATCH: every asset curve, cost, opex, and capex input must use the reporting currency unless an explicit FX conversion model is present."
            )
        if spec.historical_observations and (
            spec.peak_earnings_threshold.as_of != self._basis.as_of(graph)
            or spec.peak_earnings_threshold.period != self._basis.as_of(graph)
        ):
            raise MethodBlocked(
                "CYCLICAL_PEAK_THRESHOLD_BINDING_INVALID: peak-earnings rule must bind the valuation as-of."
            )
        self._validate_cyclical_evidence(base_request, spec)

    def _validate_cyclical_evidence(
        self,
        base_request: ForecastRequest,
        spec: CyclicalResourceValuationSpec,
    ) -> None:
        facts = {fact.fact_id: fact for fact in base_request.data_snapshot.facts}
        assumptions = {item.assumption_id: item for item in base_request.assumptions}

        def exact_fact(
            quantity: ForecastQuantity | FinancialQuantity,
            *,
            scope: str,
            segment_id: str,
            available_by: str,
            official_required: bool,
            metric_id: str,
            assumption_allowed: bool = False,
        ) -> None:
            refs = (
                quantity.lineage_refs
                if isinstance(quantity, ForecastQuantity)
                else quantity.provenance_refs
            )
            resolved = tuple(
                facts.get(ref.removeprefix("Fact:"))
                for ref in refs
                if ref.startswith("Fact:")
            )
            resolved_assumptions = tuple(
                assumptions.get(ref.removeprefix("Assumption:"))
                for ref in refs
                if ref.startswith("Assumption:")
            )
            assumption_match = (
                assumption_allowed
                and bool(resolved_assumptions)
                and len(resolved_assumptions) == len(refs)
                and any(
                    item is not None
                    and item.value == quantity.normalized_value
                    and item.scope == scope
                    and item.segment_id == segment_id
                    and item.metric_id == metric_id
                    and item.period == quantity.period
                    and item.unit == quantity.unit
                    and item.currency == quantity.currency
                    and date.fromisoformat(item.available_at)
                    <= date.fromisoformat(available_by)
                    for item in resolved_assumptions
                )
            )
            if (
                not refs
                or not assumption_match
                and (
                    len(resolved) != len(refs)
                    or any(fact is None for fact in resolved)
                    or not any(
                        fact.subject_id == base_request.security.security_id
                        and fact.scope == scope
                        and fact.segment_id == segment_id
                        and fact.metric_id == metric_id
                        and fact.period == quantity.period
                        and fact.value == quantity.normalized_value
                        and fact.unit == quantity.unit
                        and fact.currency == quantity.currency
                        and date.fromisoformat(fact.available_at)
                        <= date.fromisoformat(available_by)
                        and (not official_required or fact.official)
                        for fact in resolved
                        if fact is not None
                    )
                )
            ):
                raise MethodBlocked(
                    "CYCLICAL_EVIDENCE_INVALID: critical curve, reserve, or PIT denominator quantities must resolve exactly through the frozen DataSnapshot."
                )

        for point in spec.commodity_curve:
            for quantity in (
                point.price_low,
                point.price_base,
                point.price_high,
            ):
                exact_fact(
                    quantity,
                    scope="segment",
                    segment_id=point.segment_id,
                    available_by=spec.curve_as_of,
                    official_required=False,
                    metric_id="commodity_curve_price",
                    assumption_allowed=True,
                )
        for asset in spec.assets:
            exact_fact(
                asset.reserve_quantity,
                scope="segment",
                segment_id=asset.segment_id,
                available_by=base_request.as_of,
                official_required=True,
                metric_id="proved_probable_reserves",
            )
        for observation in spec.historical_observations:
            exact_fact(
                observation.market_value,
                scope="company",
                segment_id="",
                available_by=observation.observation_date,
                official_required=False,
                metric_id="historical_market_value",
            )
            exact_fact(
                observation.pit_earnings_denominator,
                scope="company",
                segment_id="",
                available_by=observation.denominator_available_at,
                official_required=True,
                metric_id=f"historical_{observation.denominator_metric}_denominator",
            )

    def _mid_cycle(
        self,
        graph: ForecastGraph,
        reference_graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: CyclicalResourceValuationSpec,
    ) -> MethodCalculationResult:
        self._validate_cyclical_runtime(
            graph,
            base_request,
            spec,
        )
        self._basis.validate_method_bridge(
            graph,
            plan.terminal_value_bridge,
            base_request,
        )
        periods = self._basis.periods(graph)
        curve = {(item.segment_id, item.period): item for item in spec.commodity_curve}
        assets = {item.segment_id: item for item in spec.assets}
        case_ebitda = [Decimal("0"), Decimal("0"), Decimal("0")]
        lineage: tuple[str, ...] = ()
        for segment_id in base_request.security.segment_ids:
            asset = assets.get(segment_id)
            if asset is None:
                yields = (Decimal("1"),) * 3
                production_factors = (Decimal("1"),) * 3
                cost_factors = (Decimal("1"),) * 3
                asset_lineage: tuple[str, ...] = ()
            else:
                yields = (
                    asset.grade_yield_low.normalized_value,
                    asset.grade_yield_base.normalized_value,
                    asset.grade_yield_high.normalized_value,
                )
                production_totals = tuple(
                    sum(
                        (
                            getattr(item, field_name).normalized_value
                            for item in asset.schedule
                        ),
                        Decimal("0"),
                    )
                    for field_name in (
                        "production_low",
                        "production_base",
                        "production_high",
                    )
                )
                if production_totals[1] <= 0:
                    raise MethodBlocked(
                        "RESOURCE_PRODUCTION_RANGE_INVALID: base finite-life production must be positive."
                    )
                production_factors = tuple(
                    value / production_totals[1] for value in production_totals
                )
                weighted_costs = tuple(
                    sum(
                        (
                            getattr(item, production_name).normalized_value
                            * getattr(item, cost_name).normalized_value
                            for item in asset.schedule
                        ),
                        Decimal("0"),
                    )
                    / production_total
                    for production_name, cost_name, production_total in (
                        ("production_low", "unit_cost_low", production_totals[0]),
                        ("production_base", "unit_cost_base", production_totals[1]),
                        ("production_high", "unit_cost_high", production_totals[2]),
                    )
                )
                cost_factors = (
                    weighted_costs[2] / weighted_costs[1],
                    Decimal("1"),
                    weighted_costs[0] / weighted_costs[1],
                )
                asset_lineage = asset.lineage_refs
            for period in periods:
                point = curve[(segment_id, period)]
                prices = (
                    point.price_low.normalized_value,
                    point.price_base.normalized_value,
                    point.price_high.normalized_value,
                )
                volume = graph.quantity(f"{segment_id}.volume.{period}")
                scenario_asp = graph.quantity(f"{segment_id}.asp.{period}")
                reference_asp = reference_graph.quantity(f"{segment_id}.asp.{period}")
                unit_cost = graph.quantity(f"{segment_id}.unit_cost.{period}")
                operating_expense = graph.quantity(
                    f"{segment_id}.operating_expense.{period}"
                )
                if (
                    (asset is not None and volume.unit != asset.reserve_quantity.unit)
                    or unit_cost.unit != point.price_base.unit
                    or unit_cost.currency != point.price_base.currency
                    or operating_expense.currency != point.price_base.currency
                    or reference_asp.normalized_value <= 0
                ):
                    raise MethodBlocked(
                        "RESOURCE_UNIT_MISMATCH: curve price, production, reserve, cost, and operating expense dimensions must reconcile."
                    )
                for index in range(3):
                    modeled_volume = volume.normalized_value * production_factors[index]
                    saleable = modeled_volume * yields[index]
                    case_ebitda[index] += (
                        saleable
                        * prices[index]
                        * (
                            scenario_asp.normalized_value
                            / reference_asp.normalized_value
                        )
                        - modeled_volume
                        * unit_cost.normalized_value
                        * cost_factors[index]
                        - operating_expense.normalized_value
                    )
                lineage = merge_refs(
                    lineage,
                    point.lineage_refs,
                    asset_lineage,
                    volume.lineage_refs,
                    scenario_asp.lineage_refs,
                    reference_asp.lineage_refs,
                    unit_cost.lineage_refs,
                    operating_expense.lineage_refs,
                )
        normalized = tuple(value / Decimal(len(periods)) for value in case_ebitda)
        multiples = (
            spec.mid_cycle_multiple_low.normalized_value,
            spec.mid_cycle_multiple_base.normalized_value,
            spec.mid_cycle_multiple_high.normalized_value,
        )
        values = tuple(
            ebitda * multiple
            for ebitda, multiple in zip(normalized, multiples, strict=True)
        )
        lineage = merge_refs(
            lineage,
            spec.mid_cycle_multiple_low.lineage_refs,
            spec.mid_cycle_multiple_base.lineage_refs,
            spec.mid_cycle_multiple_high.lineage_refs,
            (f"Assumption:formula:{self.MID_CYCLE_FORMULA_VERSION}",),
        )
        value_range = self._basis.bridge_range(
            graph,
            plan.terminal_value_bridge,
            "enterprise_value",
            values,
            self.MID_CYCLE_FORMULA_VERSION,
            basis_period=periods[-1],
            basis_refs=lineage,
        )
        assumptions = (
            ValuationAssumption(
                "mid_cycle_ebitda",
                self._basis.model_quantity(
                    normalized[1],
                    unit=base_request.security.reporting_currency,
                    period=periods[-1],
                    as_of=self._basis.as_of(graph),
                    refs=lineage,
                ),
            ),
            ValuationAssumption(
                "mid_cycle_multiple",
                spec.mid_cycle_multiple_base,
            ),
        )
        return (
            value_range,
            assumptions,
            self._cyclical_sensitivities(graph, reference_graph, base_request, spec),
            lineage,
            (
                "No terminal commodity-price perpetuity is used; the result is conditional on a finite explicit cycle window.",
            ),
        )

    def _resource_nav(
        self,
        graph: ForecastGraph,
        reference_graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: CyclicalResourceValuationSpec,
    ) -> MethodCalculationResult:
        if not spec.assets:
            raise MethodBlocked(
                "RESOURCE_NAV_NOT_APPLICABLE: no reserve-backed resource asset was supplied for this cyclical manufacturer."
            )
        self._validate_cyclical_runtime(
            graph,
            base_request,
            spec,
            require_resources=True,
        )
        self._basis.validate_method_bridge(
            graph,
            plan.present_value_bridge,
            base_request,
        )
        forecast_periods = self._basis.periods(graph)
        curve = {(item.segment_id, item.period): item for item in spec.commodity_curve}
        assets = {item.segment_id: item for item in spec.assets}
        values = [Decimal("0"), Decimal("0"), Decimal("0")]
        rates = (
            spec.nav_discount_rate_high.normalized_value,
            spec.nav_discount_rate_base.normalized_value,
            spec.nav_discount_rate_low.normalized_value,
        )
        lineage: tuple[str, ...] = ()
        for segment_id in base_request.security.segment_ids:
            asset = assets[segment_id]
            yields = (
                asset.grade_yield_low.normalized_value,
                asset.grade_yield_base.normalized_value,
                asset.grade_yield_high.normalized_value,
            )
            scenario_volume = sum(
                (
                    graph.quantity(f"{segment_id}.volume.{period}").normalized_value
                    for period in forecast_periods
                ),
                Decimal("0"),
            )
            reference_volume = sum(
                (
                    reference_graph.quantity(
                        f"{segment_id}.volume.{period}"
                    ).normalized_value
                    for period in forecast_periods
                ),
                Decimal("0"),
            )
            scenario_cost = sum(
                (
                    graph.quantity(f"{segment_id}.unit_cost.{period}").normalized_value
                    for period in forecast_periods
                ),
                Decimal("0"),
            )
            reference_cost = sum(
                (
                    reference_graph.quantity(
                        f"{segment_id}.unit_cost.{period}"
                    ).normalized_value
                    for period in forecast_periods
                ),
                Decimal("0"),
            )
            scenario_price = sum(
                (
                    graph.quantity(f"{segment_id}.asp.{period}").normalized_value
                    for period in forecast_periods
                ),
                Decimal("0"),
            )
            reference_price = sum(
                (
                    reference_graph.quantity(
                        f"{segment_id}.asp.{period}"
                    ).normalized_value
                    for period in forecast_periods
                ),
                Decimal("0"),
            )
            scenario_opex = sum(
                (
                    graph.quantity(
                        f"{segment_id}.operating_expense.{period}"
                    ).normalized_value
                    for period in forecast_periods
                ),
                Decimal("0"),
            )
            reference_opex = sum(
                (
                    reference_graph.quantity(
                        f"{segment_id}.operating_expense.{period}"
                    ).normalized_value
                    for period in forecast_periods
                ),
                Decimal("0"),
            )
            scenario_capex = sum(
                (
                    graph.quantity(f"{segment_id}.capex.{period}").normalized_value
                    for period in forecast_periods
                ),
                Decimal("0"),
            )
            reference_capex = sum(
                (
                    reference_graph.quantity(
                        f"{segment_id}.capex.{period}"
                    ).normalized_value
                    for period in forecast_periods
                ),
                Decimal("0"),
            )
            if any(
                value <= 0
                for value in (
                    reference_volume,
                    reference_price,
                    reference_cost,
                    reference_opex,
                    reference_capex,
                )
            ):
                raise MethodBlocked(
                    "RESOURCE_SCENARIO_LINK_INVALID: reference forecast volume, cost, opex, and capex must be positive."
                )
            volume_factor = scenario_volume / reference_volume
            price_factor = scenario_price / reference_price
            cost_factor = scenario_cost / reference_cost
            opex_factor = scenario_opex / reference_opex
            capex_factor = scenario_capex / reference_capex
            extracted = [Decimal("0"), Decimal("0"), Decimal("0")]
            for year_index, schedule in enumerate(asset.schedule, start=1):
                point = curve[(segment_id, schedule.period)]
                prices = (
                    point.price_low.normalized_value,
                    point.price_base.normalized_value,
                    point.price_high.normalized_value,
                )
                production = (
                    schedule.production_low.normalized_value,
                    schedule.production_base.normalized_value,
                    schedule.production_high.normalized_value,
                )
                unit_costs = (
                    schedule.unit_cost_high.normalized_value,
                    schedule.unit_cost_base.normalized_value,
                    schedule.unit_cost_low.normalized_value,
                )
                operating_expenses = (
                    schedule.operating_expense_high.normalized_value,
                    schedule.operating_expense_base.normalized_value,
                    schedule.operating_expense_low.normalized_value,
                )
                maintenance_capex = (
                    schedule.maintenance_capex_high.normalized_value,
                    schedule.maintenance_capex_base.normalized_value,
                    schedule.maintenance_capex_low.normalized_value,
                )
                if (
                    schedule.production_base.unit != asset.reserve_quantity.unit
                    or point.price_base.unit != schedule.unit_cost_base.unit
                    or point.price_base.currency != schedule.unit_cost_base.currency
                    or schedule.operating_expense_base.currency
                    != schedule.unit_cost_base.currency
                    or schedule.maintenance_capex_base.currency
                    != schedule.unit_cost_base.currency
                ):
                    raise MethodBlocked(
                        "RESOURCE_UNIT_MISMATCH: NAV curve, schedule production, reserve, cost, opex, tax, and capex dimensions must reconcile."
                    )
                for index in range(3):
                    modeled_production = production[index] * volume_factor
                    saleable = modeled_production * yields[index]
                    extracted[index] += modeled_production
                    pre_tax = (
                        saleable * prices[index] * price_factor
                        - modeled_production * unit_costs[index] * cost_factor
                        - operating_expenses[index] * opex_factor
                    )
                    after_tax = max(pre_tax, Decimal("0")) * (
                        Decimal("1") - schedule.tax_rate.normalized_value
                    ) + min(pre_tax, Decimal("0"))
                    cash_flow = after_tax - maintenance_capex[index] * capex_factor
                    values[index] += cash_flow / (
                        (Decimal("1") + rates[index]) ** year_index
                    )
                lineage = merge_refs(
                    lineage,
                    point.lineage_refs,
                    asset.lineage_refs,
                    *(
                        graph.quantity(f"{segment_id}.{metric}.{period}").lineage_refs
                        for metric in (
                            "volume",
                            "asp",
                            "unit_cost",
                            "operating_expense",
                            "capex",
                        )
                        for period in forecast_periods
                    ),
                )
            if any(
                amount > asset.reserve_quantity.normalized_value for amount in extracted
            ):
                raise MethodBlocked(
                    "RESOURCE_RESERVE_OVER_EXTRACTION: modeled saleable production exceeds documented reserves."
                )
        lineage = merge_refs(
            lineage,
            spec.nav_discount_rate_low.lineage_refs,
            spec.nav_discount_rate_base.lineage_refs,
            spec.nav_discount_rate_high.lineage_refs,
            (f"Assumption:formula:{self.RESOURCE_NAV_FORMULA_VERSION}",),
        )
        value_range = self._basis.bridge_range(
            graph,
            plan.present_value_bridge,
            "enterprise_value",
            tuple(values),
            self.RESOURCE_NAV_FORMULA_VERSION,
            basis_period=self._basis.as_of(graph),
            basis_refs=lineage,
        )
        assumptions = (
            ValuationAssumption(
                "resource_nav_discount_rate",
                spec.nav_discount_rate_base,
            ),
        )
        return (
            value_range,
            assumptions,
            self._cyclical_sensitivities(graph, reference_graph, base_request, spec),
            lineage,
            (
                "NAV stops at documented resource life and reserves; no residual extraction or commodity-price perpetuity is added.",
            ),
        )

    def _cyclical_historical_band(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: CyclicalResourceValuationSpec,
    ) -> MethodCalculationResult:
        if len(spec.historical_observations) < 3:
            raise MethodBlocked(
                "CYCLICAL_HISTORY_INSUFFICIENT: at least three replayable PIT observations are required."
            )
        self._validate_cyclical_runtime(graph, base_request, spec)
        self._basis.validate_method_bridge(
            graph,
            plan.terminal_value_bridge,
            base_request,
        )
        denominator_values = tuple(
            item.pit_earnings_denominator.normalized_value
            for item in spec.historical_observations
        )
        median_denominator = percentile(
            denominator_values,
            Decimal("0.50"),
        )
        peak_cutoff = median_denominator * spec.peak_earnings_threshold.normalized_value
        peak_observation_ids = {
            item.observation_id
            for item in spec.historical_observations
            if item.pit_earnings_denominator.normalized_value >= peak_cutoff
        }
        observations = tuple(
            item
            for item in spec.historical_observations
            if item.observation_id not in peak_observation_ids
        )
        if len(observations) < 3:
            raise MethodBlocked(
                "CYCLICAL_HISTORY_INSUFFICIENT: fewer than three non-peak PIT observations remain."
            )
        if any(
            date.fromisoformat(item.market_value.as_of)
            > date.fromisoformat(self._basis.as_of(graph))
            for item in observations
        ):
            raise MethodBlocked(
                "CYCLICAL_HISTORY_LOOKAHEAD: historical observations must be available by the valuation as-of."
            )
        multiples = tuple(
            item.reported_multiple.normalized_value for item in observations
        )
        ranges = (
            percentile(multiples, Decimal("0.25")),
            percentile(multiples, Decimal("0.50")),
            percentile(multiples, Decimal("0.75")),
        )
        periods = self._basis.periods(graph)
        denominator_values = tuple(
            graph.quantity(f"company.ebit.{period}").normalized_value
            for period in periods
        )
        denominator = sum(denominator_values, Decimal("0")) / Decimal(
            len(denominator_values)
        )
        if denominator <= 0:
            raise MethodBlocked(
                "CYCLICAL_HISTORY_DENOMINATOR_NON_POSITIVE: normalized forecast EBIT must be positive."
            )
        values = tuple(denominator * multiple for multiple in ranges)
        lineage = merge_refs(
            *(item.lineage_refs for item in spec.historical_observations),
            spec.peak_earnings_threshold.lineage_refs,
            *(
                graph.quantity(f"company.ebit.{period}").lineage_refs
                for period in periods
            ),
            (f"Assumption:formula:{self.CYCLICAL_HISTORY_FORMULA_VERSION}",),
        )
        value_range = self._basis.bridge_range(
            graph,
            plan.terminal_value_bridge,
            "equity_value",
            values,
            self.CYCLICAL_HISTORY_FORMULA_VERSION,
            basis_period=periods[-1],
            basis_refs=lineage,
        )
        multiple_quantities = tuple(
            self._basis.model_quantity(
                value,
                unit="x",
                period=self._basis.as_of(graph),
                as_of=self._basis.as_of(graph),
                refs=lineage,
            )
            for value in ranges
        )
        peak_count = len(peak_observation_ids)
        return (
            value_range,
            (
                ValuationAssumption(
                    "normalized_cycle_ebit",
                    self._basis.model_quantity(
                        denominator,
                        unit=base_request.security.reporting_currency,
                        period=periods[-1],
                        as_of=self._basis.as_of(graph),
                        refs=lineage,
                    ),
                ),
            ),
            (
                ValuationSensitivity(
                    "pit_historical_multiple",
                    multiple_quantities[0],
                    multiple_quantities[1],
                    multiple_quantities[2],
                ),
            ),
            lineage,
            (
                f"{peak_count} peak-earnings observation(s) were derived by {self.CYCLICAL_HISTORY_FORMULA_VERSION} at or above {spec.peak_earnings_threshold.normalized_value}x the PIT median denominator because high earnings can create a mechanically low multiple.",
                "This historical range is a conditional cross-check and does not assume mean reversion.",
            ),
        )

    def _cyclical_sensitivities(
        self,
        graph: ForecastGraph,
        reference_graph: ForecastGraph,
        base_request: ForecastRequest,
        spec: CyclicalResourceValuationSpec,
    ) -> tuple[ValuationSensitivity, ...]:
        periods = self._basis.periods(graph)
        assets = spec.assets
        scenario_factors: dict[str, dict[str, Decimal]] = {}
        for segment_id in base_request.security.segment_ids:
            factors: dict[str, Decimal] = {}
            for metric in (
                "asp",
                "volume",
                "unit_cost",
                "operating_expense",
                "capex",
            ):
                scenario_total = sum(
                    (
                        graph.quantity(
                            f"{segment_id}.{metric}.{period}"
                        ).normalized_value
                        for period in periods
                    ),
                    Decimal("0"),
                )
                reference_total = sum(
                    (
                        reference_graph.quantity(
                            f"{segment_id}.{metric}.{period}"
                        ).normalized_value
                        for period in periods
                    ),
                    Decimal("0"),
                )
                if reference_total <= 0:
                    raise MethodBlocked(
                        "RESOURCE_SCENARIO_LINK_INVALID: sensitivity reference inputs must be positive."
                    )
                factors[metric] = scenario_total / reference_total
            scenario_factors[segment_id] = factors
        curve_count = Decimal(len(spec.commodity_curve))
        price_values = tuple(
            sum(
                (
                    getattr(item, field_name).normalized_value
                    * scenario_factors[item.segment_id]["asp"]
                    for item in spec.commodity_curve
                ),
                Decimal("0"),
            )
            / curve_count
            for field_name in ("price_low", "price_base", "price_high")
        )
        refs = merge_refs(
            spec.lineage_refs,
            *(
                graph.quantity(f"{segment_id}.{metric}.{period}").lineage_refs
                for segment_id in base_request.security.segment_ids
                for metric in (
                    "volume",
                    "unit_cost",
                    "operating_expense",
                    "capex",
                )
                for period in periods
            ),
        )

        def quantities(
            values: tuple[Decimal, Decimal, Decimal],
            unit: str,
        ) -> tuple[ForecastQuantity, ForecastQuantity, ForecastQuantity]:
            return cast(
                tuple[
                    ForecastQuantity,
                    ForecastQuantity,
                    ForecastQuantity,
                ],
                tuple(
                    self._basis.model_quantity(
                        value,
                        unit=unit,
                        period=self._basis.as_of(graph),
                        as_of=self._basis.as_of(graph),
                        refs=refs,
                    )
                    for value in values
                ),
            )

        if not assets:
            volume_total = sum(
                (
                    graph.quantity(f"{segment_id}.volume.{period}").normalized_value
                    for segment_id in base_request.security.segment_ids
                    for period in periods
                ),
                Decimal("0"),
            )
            unit_cost_average = sum(
                (
                    graph.quantity(f"{segment_id}.unit_cost.{period}").normalized_value
                    for segment_id in base_request.security.segment_ids
                    for period in periods
                ),
                Decimal("0"),
            ) / Decimal(len(base_request.security.segment_ids) * len(periods))
            opex_total = sum(
                (
                    graph.quantity(
                        f"{segment_id}.operating_expense.{period}"
                    ).normalized_value
                    for segment_id in base_request.security.segment_ids
                    for period in periods
                ),
                Decimal("0"),
            )
            capex_total = sum(
                (
                    graph.quantity(f"{segment_id}.capex.{period}").normalized_value
                    for segment_id in base_request.security.segment_ids
                    for period in periods
                ),
                Decimal("0"),
            )
            grade_values = (Decimal("1"),) * 3
            production_values = (volume_total,) * 3
            cost_values = (unit_cost_average,) * 3
            opex_values = (opex_total,) * 3
            capex_values = (capex_total,) * 3
        else:
            grade_values = tuple(
                sum(
                    (getattr(asset, field_name).normalized_value for asset in assets),
                    Decimal("0"),
                )
                / Decimal(len(assets))
                for field_name in (
                    "grade_yield_low",
                    "grade_yield_base",
                    "grade_yield_high",
                )
            )
            production_values = tuple(
                sum(
                    (
                        getattr(item, field_name).normalized_value
                        * scenario_factors[asset.segment_id]["volume"]
                        for asset in assets
                        for item in asset.schedule
                    ),
                    Decimal("0"),
                )
                for field_name in (
                    "production_low",
                    "production_base",
                    "production_high",
                )
            )
            cost_values = tuple(
                sum(
                    (
                        getattr(item, production_name).normalized_value
                        * scenario_factors[asset.segment_id]["volume"]
                        * getattr(item, cost_name).normalized_value
                        * scenario_factors[asset.segment_id]["unit_cost"]
                        for asset in assets
                        for item in asset.schedule
                    ),
                    Decimal("0"),
                )
                / production
                for production_name, cost_name, production in (
                    ("production_low", "unit_cost_low", production_values[0]),
                    ("production_base", "unit_cost_base", production_values[1]),
                    ("production_high", "unit_cost_high", production_values[2]),
                )
            )
            opex_values = tuple(
                sum(
                    (
                        getattr(item, field_name).normalized_value
                        * scenario_factors[asset.segment_id]["operating_expense"]
                        for asset in assets
                        for item in asset.schedule
                    ),
                    Decimal("0"),
                )
                for field_name in (
                    "operating_expense_low",
                    "operating_expense_base",
                    "operating_expense_high",
                )
            )
            capex_values = tuple(
                sum(
                    (
                        getattr(item, field_name).normalized_value
                        * scenario_factors[asset.segment_id]["capex"]
                        for asset in assets
                        for item in asset.schedule
                    ),
                    Decimal("0"),
                )
                for field_name in (
                    "maintenance_capex_low",
                    "maintenance_capex_base",
                    "maintenance_capex_high",
                )
            )
        price = quantities(price_values, "currency/unit")
        volume = quantities(production_values, "units")
        grade = quantities(grade_values, "decimal")
        cost = quantities(cost_values, "currency/unit")
        opex = quantities(opex_values, "currency")
        capex = quantities(capex_values, "currency")
        return (
            ValuationSensitivity("commodity_price", *price),
            ValuationSensitivity("production_volume", *volume),
            ValuationSensitivity("grade_yield", *grade),
            ValuationSensitivity("unit_cost", *cost),
            ValuationSensitivity("operating_expense", *opex),
            ValuationSensitivity("maintenance_capex", *capex),
        )
