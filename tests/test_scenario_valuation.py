from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Context, Decimal, localcontext
import json

import pytest

from equity_research.scenario_valuation import (
    BiopharmaAssetSpec,
    BiopharmaCashFlowPeriodSpec,
    BiopharmaEventSpec,
    BiopharmaFinancingSpec,
    BiopharmaRunwayPeriodSpec,
    BiopharmaValuationSpec,
    CommodityCurvePoint,
    DcfApplicability,
    DcfValuationSpec,
    DeterministicScenarioRequest,
    EquityBridgeSpec,
    EquityBridgeTiming,
    FinancialInstitutionPeriodSpec,
    FinancialInstitutionValuationSpec,
    FinancialMetricRange,
    HistoricalCycleObservation,
    RelativeMultipleSpec,
    ResourceAssetSpec,
    ResourcePeriodSpec,
    CyclicalResourceValuationSpec,
    ReverseDcfSpec,
    ScenarioDefinition,
    ScenarioInvariantError,
    ScenarioProbabilityEvidence,
    ScenarioRole,
    ScenarioValuationEngine,
    SotpComponentSpec,
    SotpValuationSpec,
    ValuationPlan,
)
from equity_research import FinancialQuantity, MethodResult
from equity_research.scenario_valuation.basis import ValuationBasis
from equity_research.scenario_valuation.industrial import IndustrialValuation
from equity_research.forecast import (
    CompanyArchetype,
    ForecastQuantity,
    SegmentForecastOverride,
    SnapshotFact,
)
from test_forecast_graph import AS_OF, request as forecast_request_fixture


FORECAST_PERIODS = ("2026E", "2027E", "2028E", "2029E", "2030E")
OPENING_PERIOD = "2025FY"
TERMINAL_PERIOD = FORECAST_PERIODS[-1]
WACC_COMPONENT_VALUES = {
    "risk_free_rate": ("0.04", "decimal"),
    "equity_risk_premium": ("0.07", "decimal"),
    "beta": ("1", "x"),
    "pre_tax_cost_of_debt": ("0.08", "decimal"),
    "tax_rate": ("0.25", "decimal"),
    "equity_weight": ("0.8", "decimal"),
    "debt_weight": ("0.2", "decimal"),
}
WACC_REFS = tuple(
    f"Assumption:dcf_{name}" for name in WACC_COMPONENT_VALUES
)


def industrial_family() -> IndustrialValuation:
    return IndustrialValuation(ValuationBasis())


def model_quantity(
    value: str,
    unit: str,
    ref: str | tuple[str, ...],
    *,
    period: str,
) -> ForecastQuantity:
    return ForecastQuantity(
        value=Decimal(value),
        unit=unit,
        scale=Decimal("1"),
        currency="N/A",
        period=period,
        as_of=AS_OF,
        lineage_refs=(ref,) if isinstance(ref, str) else ref,
    )


def money(
    value: str,
    ref: str,
    *,
    period: str,
    provenance_refs: tuple[str, ...] | None = None,
) -> FinancialQuantity:
    return FinancialQuantity(
        value=Decimal(value),
        unit="CNY",
        scale=Decimal("1"),
        currency="CNY",
        period=period,
        as_of=AS_OF,
        provenance_refs=provenance_refs or (f"Assumption:{ref}",),
        kind="money",
    )


def curve_price(value: str, ref: str, *, period: str) -> ForecastQuantity:
    return ForecastQuantity(
        value=Decimal(value),
        unit="CNY/unit",
        scale=Decimal("1"),
        currency="CNY",
        period=period,
        as_of=AS_OF,
        lineage_refs=(ref,),
    )


def shares(
    period: str,
    value: str = "100",
    *,
    provenance_refs: tuple[str, ...] = ("Fact:diluted_shares",),
) -> FinancialQuantity:
    return FinancialQuantity(
        value=Decimal(value),
        unit="shares",
        scale=Decimal("1"),
        currency="N/A",
        period=period,
        as_of=AS_OF,
        provenance_refs=provenance_refs,
        kind="shares",
    )


def per_share(
    value: str,
    ref: str,
    *,
    period: str,
) -> FinancialQuantity:
    return FinancialQuantity(
        value=Decimal(value),
        unit="CNY/share",
        scale=Decimal("1"),
        currency="CNY",
        period=period,
        as_of=AS_OF,
        provenance_refs=(f"Fact:{ref}",),
        kind="per_share",
    )


def bridge_spec(timing: EquityBridgeTiming) -> EquityBridgeSpec:
    period = OPENING_PERIOD if timing == EquityBridgeTiming.OPENING else TERMINAL_PERIOD
    def refs(field_name: str) -> tuple[str, ...]:
        result = (f"Fact:{field_name}",)
        if timing == EquityBridgeTiming.TERMINAL:
            result += (
                f"Assumption:bridge_roll_forward:no_change:{field_name}",
            )
        return result

    return EquityBridgeSpec(
        timing=timing,
        diluted_shares=shares(period, provenance_refs=refs("diluted_shares")),
        lease_debt=money("0", "lease_debt", period=period, provenance_refs=refs("lease_debt")),
        preferred_stock=money("0", "preferred_stock", period=period, provenance_refs=refs("preferred_stock")),
        minority_interest=money("0", "minority_interest", period=period, provenance_refs=refs("minority_interest")),
        pension_deficit=money("0", "pension_deficit", period=period, provenance_refs=refs("pension_deficit")),
        associates_jv_value=money("0", "associates_jv_value", period=period, provenance_refs=refs("associates_jv_value")),
        non_operating_assets=money("0", "non_operating_assets", period=period, provenance_refs=refs("non_operating_assets")),
    )


def method_result(
    method_id: str,
    *,
    status: str = "ready",
    metric: str = "ps",
    multiples: tuple[str, ...] = ("8", "9", "10"),
) -> MethodResult:
    if status != "ready":
        return MethodResult(
            method_id=method_id,
            label=method_id,
            status=status,
            role="relative_valuation",
            explanation=f"{method_id} gate is {status}.",
            missing_fields=("gated_input",),
            evidence_ids=(f"{method_id}_gap",),
            diagnostics=("The existing evidence gate did not pass.",),
        )
    count = 3 if method_id == "peer_comps" else 12
    values = tuple(
        Decimal(multiples[index % len(multiples)]) for index in range(count)
    )
    ordered = sorted(values)

    def percentile(probability: Decimal) -> Decimal:
        position = Decimal(len(ordered) - 1) * probability
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - Decimal(lower)
        return ordered[lower] * (Decimal("1") - fraction) + ordered[upper] * fraction

    q25 = percentile(Decimal("0.25"))
    median = percentile(Decimal("0.50"))
    q75 = percentile(Decimal("0.75"))
    inputs = [
        {
            "value": format(value, "f"),
            "unit": "x",
            "scale": "1",
            "currency": "N/A",
            "period": AS_OF,
            "as_of": AS_OF,
            "provenance_refs": [f"Fact:{method_id}:{index}"],
        }
        for index, value in enumerate(values)
    ]
    exact = {
        "metric": metric,
        "q25": format(q25, "f"),
        "median": format(median, "f"),
        "q75": format(q75, "f"),
        "dimensioned_inputs": (
            {"peer_multiples": inputs} if method_id == "peer_comps" else inputs
        ),
        "provenance_refs": [ref for item in inputs for ref in item["provenance_refs"]],
    }
    if method_id == "peer_comps":
        exact.update(
            {
                "peer_q25_multiple": exact.pop("q25"),
                "peer_median_multiple": exact.pop("median"),
                "peer_q75_multiple": exact.pop("q75"),
            }
        )
    return MethodResult(
        method_id=method_id,
        label=method_id,
        status="ready",
        role="relative_valuation" if method_id == "peer_comps" else "relative_to_self",
        explanation="Existing evidence gate passed.",
        evidence_ids=tuple(ref.removeprefix("Fact:") for ref in exact["provenance_refs"]),
        assumptions={
            "minimum_peer_count": 3,
            "currency_checked": True,
            "accounting_checked": True,
            "minimum_observations": 12,
        },
        metrics={"metric": metric, "exact_calculation": exact},
    )


def dcf_gate_result(status: str = "ready") -> MethodResult:
    evidence_ids = (
        *(ref.removeprefix("Assumption:") for ref in WACC_REFS),
        "dcf_terminal_growth",
        "diluted_shares",
        "lease_debt",
        "preferred_stock",
        "minority_interest",
        "pension_deficit",
        "associates_jv_value",
        "non_operating_assets",
        "observed_enterprise_value",
    )
    metrics = {}
    if status in {"ready", "caution"}:
        metrics = {
            "exact_calculation": {
                "wacc": "0.10",
                "calculated_wacc": "0.10",
                "terminal_growth": "0.025",
                "dimensioned_inputs": {
                    "wacc_components": {
                        name: {
                            "value": value,
                            "unit": unit,
                            "scale": "1",
                            "currency": "N/A",
                            "period": AS_OF,
                            "as_of": AS_OF,
                            "provenance_refs": [f"Assumption:dcf_{name}"],
                        }
                        for name, (value, unit) in WACC_COMPONENT_VALUES.items()
                    },
                    "terminal_growth": {
                        "value": "0.025",
                        "unit": "decimal",
                        "scale": "1",
                        "currency": "N/A",
                        "period": TERMINAL_PERIOD,
                        "as_of": AS_OF,
                        "provenance_refs": ["Assumption:dcf_terminal_growth"],
                    },
                },
            }
        }
    return MethodResult(
        method_id="dcf",
        label="DCF",
        status=status,
        role="intrinsic_valuation",
        explanation=f"Existing router and DCF applicability gate returned {status}.",
        evidence_ids=evidence_ids,
        metrics=metrics,
        diagnostics=("DCF gate did not pass.",) if status not in {"ready", "caution"} else (),
    )


def dcf_applicability(status: str = "ready") -> DcfApplicability:
    return industrial_family().bind_dcf_applicability(
        dcf_gate_result(status),
        subject_id="002897.SZ",
        as_of=AS_OF,
    )


def relative_spec(method_id: str, *, status: str = "ready") -> RelativeMultipleSpec:
    return industrial_family().bind_relative_multiple(
        method_result(method_id, status=status),
        subject_id="002897.SZ",
        as_of=AS_OF,
    )


def valuation_plan(*, dcf_status: str = "ready") -> ValuationPlan:
    return ValuationPlan(
        present_value_bridge=bridge_spec(EquityBridgeTiming.OPENING),
        terminal_value_bridge=bridge_spec(EquityBridgeTiming.TERMINAL),
        dcf=DcfValuationSpec(
            applicability=dcf_applicability(dcf_status),
            discount_rate_low=model_quantity(
                "0.09", "decimal", WACC_REFS, period=AS_OF
            ),
            discount_rate_base=model_quantity(
                "0.10", "decimal", WACC_REFS, period=AS_OF
            ),
            discount_rate_high=model_quantity(
                "0.11", "decimal", WACC_REFS, period=AS_OF
            ),
            terminal_growth_low=model_quantity(
                "0.02", "decimal", "Assumption:dcf_terminal_growth", period=TERMINAL_PERIOD
            ),
            terminal_growth_base=model_quantity(
                "0.025", "decimal", "Assumption:dcf_terminal_growth", period=TERMINAL_PERIOD
            ),
            terminal_growth_high=model_quantity(
                "0.03", "decimal", "Assumption:dcf_terminal_growth", period=TERMINAL_PERIOD
            ),
        ),
        sotp=SotpValuationSpec(
            components=(
                SotpComponentSpec(
                    segment_id="components",
                    metric="ebit",
                    multiple_low=model_quantity(
                        "8", "x", "Assumption:components_multiple", period=TERMINAL_PERIOD
                    ),
                    multiple_base=model_quantity(
                        "10", "x", "Assumption:components_multiple", period=TERMINAL_PERIOD
                    ),
                    multiple_high=model_quantity(
                        "12", "x", "Assumption:components_multiple", period=TERMINAL_PERIOD
                    ),
                ),
                SotpComponentSpec(
                    segment_id="connectors",
                    metric="ebit",
                    multiple_low=model_quantity(
                        "7", "x", "Assumption:connectors_multiple", period=TERMINAL_PERIOD
                    ),
                    multiple_base=model_quantity(
                        "9", "x", "Assumption:connectors_multiple", period=TERMINAL_PERIOD
                    ),
                    multiple_high=model_quantity(
                        "11", "x", "Assumption:connectors_multiple", period=TERMINAL_PERIOD
                    ),
                ),
            )
        ),
        reverse_dcf=ReverseDcfSpec(
            current_enterprise_value=money(
                "5000",
                "observed_enterprise_value",
                period=AS_OF,
                provenance_refs=("Fact:observed_enterprise_value",),
            ),
            discount_rate=model_quantity(
                "0.10", "decimal", WACC_REFS, period=AS_OF
            ),
        ),
        relative_methods=(
            relative_spec("peer_comps"),
            relative_spec("historical_band", status="blocked"),
        ),
    )


def scenario_overrides(role: ScenarioRole) -> tuple[SegmentForecastOverride, ...]:
    settings = {
        ScenarioRole.STRESS: (Decimal("0"), Decimal("0"), Decimal("0.02")),
        ScenarioRole.BASE: (Decimal("0.05"), Decimal("0.02"), Decimal("0.01")),
        ScenarioRole.IMPROVEMENT: (
            Decimal("0.15"),
            Decimal("0.05"),
            Decimal("-0.02"),
        ),
    }
    demand_growth, asp_growth, unit_cost_growth = settings[role]
    return tuple(
        SegmentForecastOverride(
            segment_id=segment_id,
            period=period,
            demand_growth=demand_growth,
            asp_growth=asp_growth,
            capacity_growth=Decimal("0.10"),
            target_utilization=Decimal("0.95"),
            unit_cost_growth=unit_cost_growth,
            operating_expense_growth=Decimal("0.02"),
            capex_growth=Decimal("0.03"),
            depreciation_growth=Decimal("0.02"),
            working_capital_to_revenue=Decimal("0.15"),
            tax_rate=Decimal("0.25"),
            debt_change=Decimal("0"),
            event_probability=Decimal("1"),
        )
        for period in FORECAST_PERIODS
        for segment_id in ("components", "connectors")
    )


def probability_evidence(
    role: ScenarioRole, probability: Decimal
) -> ScenarioProbabilityEvidence:
    observed_count_fact_ref = f"Fact:scenario_calibration:{role.value}:observed_count"
    sample_size_fact_ref = "Fact:scenario_calibration:sample_size"
    fact_refs = (observed_count_fact_ref, sample_size_fact_ref)
    evidence_id = f"scenario_probability:{role.value}"
    probability_quantity = ForecastQuantity(
        value=probability,
        unit="decimal",
        scale=Decimal("1"),
        currency="N/A",
        period=TERMINAL_PERIOD,
        as_of=AS_OF,
        lineage_refs=(
            f"Assumption:calibration:{evidence_id}",
            *fact_refs,
        ),
    )
    return ScenarioProbabilityEvidence(
        evidence_id=evidence_id,
        schema_version="ScenarioProbabilityCalibration@1",
        formula_version="observed-frequency@1",
        calibration_window_start="2021-01-01",
        calibration_window_end="2026-06-30",
        calibration_sample_size=1000,
        observed_count=int(probability * Decimal("1000")),
        prior_count=Decimal("0"),
        prior_total_count=Decimal("0"),
        observed_count_fact_ref=observed_count_fact_ref,
        sample_size_fact_ref=sample_size_fact_ref,
        subject_id="002897.SZ",
        scenario_id=role.value,
        mutually_exclusive_group="operating_outlook_2030",
        probability=probability_quantity,
        basis_fact_refs=fact_refs,
    )


def scenario(
    role: ScenarioRole,
    probability: Decimal | None = None,
) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_id=role.value,
        role=role,
        label=role.value.title(),
        mutually_exclusive_group="operating_outlook_2030",
        partition_basis="Demand, price, utilization, and cost outcomes cover stress/base/improvement.",
        driver_overrides=scenario_overrides(role),
        probability_evidence=(
            probability_evidence(role, probability) if probability is not None else None
        ),
        rationale_refs=(f"Assumption:scenario:{role.value}",),
    )


def scenario_request(*, probabilities: bool = False) -> DeterministicScenarioRequest:
    plan = valuation_plan()
    base = replace(
        forecast_request_fixture(),
        forecast_periods=FORECAST_PERIODS,
        assumption_overrides=(),
    )
    opening_bridge = plan.present_value_bridge
    bridge_quantities = {
        "diluted_shares": opening_bridge.diluted_shares,
        "lease_debt": opening_bridge.lease_debt,
        "preferred_stock": opening_bridge.preferred_stock,
        "minority_interest": opening_bridge.minority_interest,
        "pension_deficit": opening_bridge.pension_deficit,
        "associates_jv_value": opening_bridge.associates_jv_value,
        "non_operating_assets": opening_bridge.non_operating_assets,
        "observed_enterprise_value": plan.reverse_dcf.current_enterprise_value,
    }
    valuation_facts = tuple(
        SnapshotFact(
            fact_id=field_name,
            subject_id=base.security.security_id,
            scope="company",
            segment_id="",
            metric_id=field_name,
            field_name=field_name,
            period=quantity.period,
            value=quantity.normalized_value,
            unit=quantity.unit,
            currency=quantity.currency,
            source_id="SCENARIO_VALUATION_GATE",
            available_at=AS_OF,
            official=field_name != "observed_enterprise_value",
        )
        for field_name, quantity in bridge_quantities.items()
    )
    calibration_period = "2021-01-01/2026-06-30"
    calibration_weights = {
        ScenarioRole.STRESS: Decimal("0.2"),
        ScenarioRole.BASE: Decimal("0.5"),
        ScenarioRole.IMPROVEMENT: Decimal("0.3"),
    }
    calibration_facts = (
        SnapshotFact(
            fact_id="scenario_calibration:sample_size",
            subject_id=base.security.security_id,
            scope="company",
            segment_id="",
            metric_id="scenario_calibration_sample_size",
            field_name="scenario_calibration_sample_size",
            period=calibration_period,
            value=Decimal("1000"),
            unit="count",
            currency="N/A",
            source_id="SCENARIO_CALIBRATION_GATE",
            available_at=AS_OF,
            official=False,
        ),
        *(
            SnapshotFact(
                fact_id=f"scenario_calibration:{role.value}:observed_count",
                subject_id=base.security.security_id,
                scope="company",
                segment_id="",
                metric_id="scenario_observed_count",
                field_name=role.value,
                period=calibration_period,
                value=calibration_weights[role] * Decimal("1000"),
                unit="count",
                currency="N/A",
                source_id="SCENARIO_CALIBRATION_GATE",
                available_at=AS_OF,
                official=False,
            )
            for role in ScenarioRole
        ),
    )
    base = replace(
        base,
        data_snapshot=replace(
            base.data_snapshot,
            facts=base.data_snapshot.facts + valuation_facts + calibration_facts,
            content_hash="",
        ),
    )
    weights = {
        ScenarioRole.STRESS: Decimal("0.2"),
        ScenarioRole.BASE: Decimal("0.5"),
        ScenarioRole.IMPROVEMENT: Decimal("0.3"),
    }
    return DeterministicScenarioRequest(
        base_forecast_request=base,
        scenarios=tuple(
            scenario(role, weights[role] if probabilities else None)
            for role in (
                ScenarioRole.STRESS,
                ScenarioRole.BASE,
                ScenarioRole.IMPROVEMENT,
            )
        ),
        valuation_plan=plan,
    )


def cyclical_resource_spec(
    *,
    reserve_value: str = "100000",
    reserve_unit: str = "units",
    life_years: int = 5,
) -> CyclicalResourceValuationSpec:
    resource_periods = tuple(
        f"{2026 + index}E" for index in range(life_years)
    )
    curve = tuple(
        CommodityCurvePoint(
            segment_id=segment_id,
            period=period,
            price_low=curve_price(
                "8" if segment_id == "components" else "16",
                f"Fact:curve:{segment_id}:{period}:low",
                period=period,
            ),
            price_base=curve_price(
                "10" if segment_id == "components" else "20",
                f"Fact:curve:{segment_id}:{period}:base",
                period=period,
            ),
            price_high=curve_price(
                "12" if segment_id == "components" else "24",
                f"Fact:curve:{segment_id}:{period}:high",
                period=period,
            ),
        )
        for period in resource_periods
        for segment_id in ("components", "connectors")
    )
    assets = tuple(
        ResourceAssetSpec(
            segment_id=segment_id,
            reserve_quantity=model_quantity(
                reserve_value,
                reserve_unit,
                f"Fact:reserve:{segment_id}",
                period=OPENING_PERIOD,
            ),
            schedule=tuple(
                ResourcePeriodSpec(
                    period=period,
                    production_low=model_quantity(
                        "90" if segment_id == "components" else "45",
                        "units",
                        f"Assumption:production:{segment_id}:low",
                        period=period,
                    ),
                    production_base=model_quantity(
                        "100" if segment_id == "components" else "50",
                        "units",
                        f"Assumption:production:{segment_id}:base",
                        period=period,
                    ),
                    production_high=model_quantity(
                        "110" if segment_id == "components" else "55",
                        "units",
                        f"Assumption:production:{segment_id}:high",
                        period=period,
                    ),
                    unit_cost_low=curve_price(
                        "5.4" if segment_id == "components" else "10.8",
                        f"Assumption:cost_curve:{segment_id}:low",
                        period=period,
                    ),
                    unit_cost_base=curve_price(
                        "6" if segment_id == "components" else "12",
                        f"Assumption:cost_curve:{segment_id}:base",
                        period=period,
                    ),
                    unit_cost_high=curve_price(
                        "6.6" if segment_id == "components" else "13.2",
                        f"Assumption:cost_curve:{segment_id}:high",
                        period=period,
                    ),
                    operating_expense_low=money(
                        "45" if segment_id == "components" else "22.5",
                        f"resource_opex:{segment_id}:low",
                        period=period,
                    ),
                    operating_expense_base=money(
                        "50" if segment_id == "components" else "25",
                        f"resource_opex:{segment_id}:base",
                        period=period,
                    ),
                    operating_expense_high=money(
                        "55" if segment_id == "components" else "27.5",
                        f"resource_opex:{segment_id}:high",
                        period=period,
                    ),
                    maintenance_capex_low=money(
                        "18" if segment_id == "components" else "9",
                        f"maintenance_capex:{segment_id}:low",
                        period=period,
                    ),
                    maintenance_capex_base=money(
                        "20" if segment_id == "components" else "10",
                        f"maintenance_capex:{segment_id}:base",
                        period=period,
                    ),
                    maintenance_capex_high=money(
                        "23" if segment_id == "components" else "11.5",
                        f"maintenance_capex:{segment_id}:high",
                        period=period,
                    ),
                    tax_rate=model_quantity(
                        "0.25",
                        "decimal",
                        f"Assumption:resource_tax:{segment_id}",
                        period=period,
                    ),
                )
                for period in resource_periods
            ),
            grade_yield_low=model_quantity(
                "0.85", "decimal", f"Assumption:yield:{segment_id}", period=AS_OF
            ),
            grade_yield_base=model_quantity(
                "0.90", "decimal", f"Assumption:yield:{segment_id}", period=AS_OF
            ),
            grade_yield_high=model_quantity(
                "0.95", "decimal", f"Assumption:yield:{segment_id}", period=AS_OF
            ),
            resource_life_years=life_years,
        )
        for segment_id in ("components", "connectors")
    )
    observations = tuple(
        HistoricalCycleObservation(
            observation_id=f"cycle:{index}",
            period=f"{2020 + index}FY",
            denominator_metric="ebit",
            observation_date=f"{2021 + index}-05-31",
            denominator_available_at=f"{2021 + index}-04-30",
            market_value=money(
                str(market_value),
                f"cycle_market_value:{index}",
                period=f"{2020 + index}FY",
                provenance_refs=(f"Fact:cycle_market_value:{index}",),
            ),
            pit_earnings_denominator=money(
                str(earnings),
                f"cycle_earnings:{index}",
                period=f"{2020 + index}FY",
                provenance_refs=(f"Fact:cycle_earnings:{index}",),
            ),
            reported_multiple=model_quantity(
                str(Decimal(market_value) / Decimal(earnings)),
                "x",
                (
                    f"Fact:cycle_market_value:{index}",
                    f"Fact:cycle_earnings:{index}",
                ),
                period=f"{2020 + index}FY",
            ),
        )
        for index, (market_value, earnings) in enumerate(
            (
                ("1200", "100"),
                ("1300", "100"),
                ("1400", "200"),
                ("1500", "100"),
            )
        )
    )
    return CyclicalResourceValuationSpec(
        curve_version="commodity-curve@2026-07-07",
        curve_as_of=AS_OF,
        commodity_curve=curve,
        assets=assets,
        mid_cycle_multiple_low=model_quantity(
            "5", "x", "Assumption:mid_cycle_multiple", period=AS_OF
        ),
        mid_cycle_multiple_base=model_quantity(
            "6", "x", "Assumption:mid_cycle_multiple", period=AS_OF
        ),
        mid_cycle_multiple_high=model_quantity(
            "7", "x", "Assumption:mid_cycle_multiple", period=AS_OF
        ),
        nav_discount_rate_low=model_quantity(
            "0.08", "decimal", "Assumption:resource_nav_discount", period=AS_OF
        ),
        nav_discount_rate_base=model_quantity(
            "0.10", "decimal", "Assumption:resource_nav_discount", period=AS_OF
        ),
        nav_discount_rate_high=model_quantity(
            "0.12", "decimal", "Assumption:resource_nav_discount", period=AS_OF
        ),
        peak_earnings_threshold=model_quantity(
            "1.5",
            "x",
            "Assumption:peak_earnings_threshold",
            period=AS_OF,
        ),
        historical_observations=observations,
    )


def cyclical_request(
    *,
    spec: CyclicalResourceValuationSpec | None = None,
    probabilities: bool = False,
) -> DeterministicScenarioRequest:
    subject = scenario_request(probabilities=probabilities)
    cyclical_spec = spec or cyclical_resource_spec()
    base = replace(
        subject.base_forecast_request,
        security=replace(
            subject.base_forecast_request.security,
            archetype=CompanyArchetype.CYCLICAL_RESOURCE,
        ),
    )
    cyclical_facts = tuple(
        SnapshotFact(
            fact_id=quantity.lineage_refs[0].removeprefix("Fact:"),
            subject_id=base.security.security_id,
            scope="segment",
            segment_id=point.segment_id,
            metric_id="commodity_curve_price",
            field_name=field_name,
            period=point.period,
            value=quantity.normalized_value,
            unit=quantity.unit,
            currency=quantity.currency,
            source_id="VERSIONED_COMMODITY_CURVE",
            available_at=cyclical_spec.curve_as_of,
            official=False,
        )
        for point in cyclical_spec.commodity_curve
        for field_name, quantity in (
            ("low", point.price_low),
            ("base", point.price_base),
            ("high", point.price_high),
        )
    ) + tuple(
        SnapshotFact(
            fact_id=asset.reserve_quantity.lineage_refs[0].removeprefix("Fact:"),
            subject_id=base.security.security_id,
            scope="segment",
            segment_id=asset.segment_id,
            metric_id="proved_probable_reserves",
            field_name="reserve_quantity",
            period=asset.reserve_quantity.period,
            value=asset.reserve_quantity.normalized_value,
            unit=asset.reserve_quantity.unit,
            currency=asset.reserve_quantity.currency,
            source_id="OFFICIAL_RESOURCE_DISCLOSURE",
            available_at=AS_OF,
            official=True,
        )
        for asset in cyclical_spec.assets
    ) + tuple(
        fact
        for observation in cyclical_spec.historical_observations
        for fact in (
            SnapshotFact(
                fact_id=observation.market_value.provenance_refs[0].removeprefix(
                    "Fact:"
                ),
                subject_id=base.security.security_id,
                scope="company",
                segment_id="",
                metric_id="historical_market_value",
                field_name="market_value",
                period=observation.period,
                value=observation.market_value.normalized_value,
                unit=observation.market_value.unit,
                currency=observation.market_value.currency,
                source_id="PIT_MARKET_DATA",
                available_at=observation.observation_date,
                official=False,
            ),
            SnapshotFact(
                fact_id=observation.pit_earnings_denominator.provenance_refs[
                    0
                ].removeprefix("Fact:"),
                subject_id=base.security.security_id,
                scope="company",
                segment_id="",
                metric_id=(
                    f"historical_{observation.denominator_metric}_denominator"
                ),
                field_name="earnings_denominator",
                period=observation.period,
                value=observation.pit_earnings_denominator.normalized_value,
                unit=observation.pit_earnings_denominator.unit,
                currency=observation.pit_earnings_denominator.currency,
                source_id="OFFICIAL_HISTORICAL_FINANCIALS",
                available_at=observation.denominator_available_at,
                official=True,
            ),
        )
    )
    base = replace(
        base,
        data_snapshot=replace(
            base.data_snapshot,
            facts=base.data_snapshot.facts + cyclical_facts,
            content_hash="",
        ),
    )
    return replace(
        subject,
        base_forecast_request=base,
        valuation_plan=replace(
            subject.valuation_plan,
            cyclical_resource=cyclical_spec,
        ),
    )


def financial_metric(
    metric_id: str,
    period: str,
    values: tuple[str, str, str],
) -> FinancialMetricRange:
    return FinancialMetricRange(
        metric_id=metric_id,
        low=model_quantity(
            values[0],
            "decimal",
            f"Assumption:{metric_id}:low",
            period=period,
        ),
        base=model_quantity(
            values[1],
            "decimal",
            f"Assumption:{metric_id}:base",
            period=period,
        ),
        high=model_quantity(
            values[2],
            "decimal",
            f"Assumption:{metric_id}:high",
            period=period,
        ),
    )


def financial_institution_spec(
    *,
    minimum_capital_ratio: str = "0.10",
) -> FinancialInstitutionValuationSpec:
    periods = tuple(
        FinancialInstitutionPeriodSpec(
            period=period,
            operating_metrics=(
                nim := financial_metric(
                    "nim", period, ("0.025", "0.030", "0.035")
                ),
                credit_cost := financial_metric(
                    "credit_cost", period, ("0.007", "0.010", "0.015")
                ),
                npl := financial_metric(
                    "npl_ratio", period, ("0.010", "0.015", "0.020")
                ),
            ),
            roe_low=model_quantity(
                "0.08",
                "decimal",
                (
                    *nim.low.lineage_refs,
                    *credit_cost.low.lineage_refs,
                    *npl.low.lineage_refs,
                    f"Assumption:roe:{period}:low",
                ),
                period=period,
            ),
            roe_base=model_quantity(
                "0.11",
                "decimal",
                (
                    *nim.base.lineage_refs,
                    *credit_cost.base.lineage_refs,
                    *npl.base.lineage_refs,
                    f"Assumption:roe:{period}:base",
                ),
                period=period,
            ),
            roe_high=model_quantity(
                "0.14",
                "decimal",
                (
                    *nim.high.lineage_refs,
                    *credit_cost.high.lineage_refs,
                    *npl.high.lineage_refs,
                    f"Assumption:roe:{period}:high",
                ),
                period=period,
            ),
            payout_low=model_quantity(
                "0.65",
                "decimal",
                f"Assumption:payout:{period}:low",
                period=period,
            ),
            payout_base=model_quantity(
                "0.75",
                "decimal",
                f"Assumption:payout:{period}:base",
                period=period,
            ),
            payout_high=model_quantity(
                "0.80",
                "decimal",
                f"Assumption:payout:{period}:high",
                period=period,
            ),
            rwa_growth_low=model_quantity(
                "0.02",
                "decimal",
                f"Assumption:rwa_growth:{period}:low",
                period=period,
            ),
            rwa_growth_base=model_quantity(
                "0.04",
                "decimal",
                f"Assumption:rwa_growth:{period}:base",
                period=period,
            ),
            rwa_growth_high=model_quantity(
                "0.06",
                "decimal",
                f"Assumption:rwa_growth:{period}:high",
                period=period,
            ),
            clean_surplus_adjustment_low=money(
                "0", f"clean_surplus:{period}:low", period=period
            ),
            clean_surplus_adjustment_base=money(
                "0", f"clean_surplus:{period}:base", period=period
            ),
            clean_surplus_adjustment_high=money(
                "0", f"clean_surplus:{period}:high", period=period
            ),
            regulatory_capital_adjustment_low=money(
                "0", f"regulatory_capital:{period}:low", period=period
            ),
            regulatory_capital_adjustment_base=money(
                "0", f"regulatory_capital:{period}:base", period=period
            ),
            regulatory_capital_adjustment_high=money(
                "0", f"regulatory_capital:{period}:high", period=period
            ),
            dilution_factor_low=model_quantity(
                "1",
                "x",
                f"Assumption:dilution:{period}:low",
                period=period,
            ),
            dilution_factor_base=model_quantity(
                "1.02",
                "x",
                f"Assumption:dilution:{period}:base",
                period=period,
            ),
            dilution_factor_high=model_quantity(
                "1.04",
                "x",
                f"Assumption:dilution:{period}:high",
                period=period,
            ),
            operating_exposure_to_equity_low=model_quantity(
                "3",
                "x",
                f"Assumption:operating_exposure_to_equity:{period}:low",
                period=period,
            ),
            operating_exposure_to_equity_base=model_quantity(
                "4",
                "x",
                f"Assumption:operating_exposure_to_equity:{period}:base",
                period=period,
            ),
            operating_exposure_to_equity_high=model_quantity(
                "5",
                "x",
                f"Assumption:operating_exposure_to_equity:{period}:high",
                period=period,
            ),
        )
        for period in FORECAST_PERIODS
    )
    return FinancialInstitutionValuationSpec(
        institution_type="bank",
        opening_book_value=money(
            "1000",
            "opening_book_value",
            period=OPENING_PERIOD,
            provenance_refs=("Fact:opening_book_value",),
        ),
        opening_regulatory_capital=money(
            "150",
            "opening_regulatory_capital",
            period=OPENING_PERIOD,
            provenance_refs=("Fact:opening_regulatory_capital",),
        ),
        opening_risk_weighted_assets=money(
            "1000",
            "opening_risk_weighted_assets",
            period=OPENING_PERIOD,
            provenance_refs=("Fact:opening_risk_weighted_assets",),
        ),
        minimum_regulatory_capital_ratio=model_quantity(
            minimum_capital_ratio,
            "decimal",
            "Assumption:minimum_regulatory_capital_ratio",
            period=AS_OF,
        ),
        specialized_risk_limit=model_quantity(
            "0.025",
            "decimal",
            "Assumption:specialized_risk_limit",
            period=AS_OF,
        ),
        cost_of_equity_low=model_quantity(
            "0.09", "decimal", "Assumption:financial_coe", period=AS_OF
        ),
        cost_of_equity_base=model_quantity(
            "0.10", "decimal", "Assumption:financial_coe", period=AS_OF
        ),
        cost_of_equity_high=model_quantity(
            "0.11", "decimal", "Assumption:financial_coe", period=AS_OF
        ),
        terminal_growth_low=model_quantity(
            "0.0385",
            "decimal",
            "Assumption:financial_terminal_growth",
            period=AS_OF,
        ),
        terminal_growth_base=model_quantity(
            "0.0475",
            "decimal",
            "Assumption:financial_terminal_growth",
            period=AS_OF,
        ),
        terminal_growth_high=model_quantity(
            "0.056",
            "decimal",
            "Assumption:financial_terminal_growth",
            period=AS_OF,
        ),
        periods=periods,
    )


def financial_request(
    *,
    spec: FinancialInstitutionValuationSpec | None = None,
) -> DeterministicScenarioRequest:
    subject = scenario_request()
    financial_spec = spec or financial_institution_spec()
    base = replace(
        subject.base_forecast_request,
        security=replace(
            subject.base_forecast_request.security,
            archetype=CompanyArchetype.FINANCIAL_INSTITUTION,
        ),
    )
    facts = tuple(
        SnapshotFact(
            fact_id=quantity.provenance_refs[0].removeprefix("Fact:"),
            subject_id=base.security.security_id,
            scope="company",
            segment_id="",
            metric_id=metric_id,
            field_name=metric_id,
            period=quantity.period,
            value=quantity.normalized_value,
            unit=quantity.unit,
            currency=quantity.currency,
            source_id="OFFICIAL_FINANCIAL_INSTITUTION_DISCLOSURE",
            available_at=AS_OF,
            official=True,
        )
        for metric_id, quantity in (
            ("opening_book_value", financial_spec.opening_book_value),
            (
                "opening_regulatory_capital",
                financial_spec.opening_regulatory_capital,
            ),
            (
                "opening_risk_weighted_assets",
                financial_spec.opening_risk_weighted_assets,
            ),
        )
    )
    base = replace(
        base,
        data_snapshot=replace(
            base.data_snapshot,
            facts=base.data_snapshot.facts + facts,
            content_hash="",
        ),
    )
    return replace(
        subject,
        base_forecast_request=base,
        valuation_plan=replace(
            subject.valuation_plan,
            financial_institution=financial_spec,
        ),
    )


def biopharma_event(
    event_id: str,
    event_type: str,
    period: str,
    probabilities: tuple[str, str, str],
    *,
    parents: tuple[str, ...] = (),
) -> BiopharmaEventSpec:
    probability_basis = (
        "conditional_on_parents" if parents else "standalone"
    )
    calibration_version = "biopharma-pos-calibration@2026-07"
    calibration_method_version = "beta-binomial-stage-benchmark@1"
    calibration_window_start = "2016-01-01"
    calibration_window_end = "2025-12-31"
    calibration_sample_size = 1200
    calibration_record_id = (
        "BIOPHARMA_POS_CALIBRATION:"
        f"{event_id}:"
        f"{calibration_version}:"
        f"{calibration_method_version}:"
        f"{probability_basis}:"
        f"{calibration_window_start}:"
        f"{calibration_window_end}:"
        f"n={calibration_sample_size}"
    )
    fact_ref = f"Fact:{calibration_record_id}"
    return BiopharmaEventSpec(
        event_id=event_id,
        event_type=event_type,
        probability_basis=probability_basis,
        period=period,
        parent_event_ids=parents,
        probability_low=model_quantity(
            probabilities[0],
            "decimal",
            (
                fact_ref,
                f"Assumption:biopharma_probability:{event_id}:low",
            ),
            period=period,
        ),
        probability_base=model_quantity(
            probabilities[1],
            "decimal",
            fact_ref,
            period=period,
        ),
        probability_high=model_quantity(
            probabilities[2],
            "decimal",
            (
                fact_ref,
                f"Assumption:biopharma_probability:{event_id}:high",
            ),
            period=period,
        ),
        calibration_version=calibration_version,
        calibration_method_version=calibration_method_version,
        calibration_window_start=calibration_window_start,
        calibration_window_end=calibration_window_end,
        calibration_sample_size=calibration_sample_size,
        calibration_record_id=calibration_record_id,
    )


def biopharma_asset(
    asset_id: str,
    indication_id: str,
    economic_right_id: str,
    required_event_id: str,
    sales: tuple[str, ...],
    development_costs: tuple[str, ...],
    *,
    launch_event_period: str,
    ownership: tuple[str, str, str],
) -> BiopharmaAssetSpec:
    periods = []
    for index, period in enumerate(FORECAST_PERIODS):
        sales_base = Decimal(sales[index])
        development_base = Decimal(development_costs[index])
        if period == "2026E":
            milestone_values = ("-25", "-20", "-15")
            milestone_event_id = "shared_phase2"
        elif period == launch_event_period:
            milestone_values = ("20", "30", "40")
            milestone_event_id = required_event_id
        else:
            milestone_values = ("0", "0", "0")
            milestone_event_id = ""
        periods.append(
            BiopharmaCashFlowPeriodSpec(
                period=period,
                gross_sales_low=money(
                    str(sales_base * Decimal("0.70")),
                    f"{asset_id}:gross_sales:low",
                    period=period,
                ),
                gross_sales_base=money(
                    str(sales_base),
                    f"{asset_id}:gross_sales:base",
                    period=period,
                ),
                gross_sales_high=money(
                    str(sales_base * Decimal("1.30")),
                    f"{asset_id}:gross_sales:high",
                    period=period,
                ),
                development_cost_low=money(
                    str(development_base * Decimal("0.80")),
                    f"{asset_id}:development_cost:low",
                    period=period,
                ),
                development_cost_base=money(
                    str(development_base),
                    f"{asset_id}:development_cost:base",
                    period=period,
                ),
                development_cost_high=money(
                    str(development_base * Decimal("1.25")),
                    f"{asset_id}:development_cost:high",
                    period=period,
                ),
                milestone_cash_low=money(
                    milestone_values[0],
                    f"{asset_id}:milestone_cash:low",
                    period=period,
                ),
                milestone_cash_base=money(
                    milestone_values[1],
                    f"{asset_id}:milestone_cash:base",
                    period=period,
                ),
                milestone_cash_high=money(
                    milestone_values[2],
                    f"{asset_id}:milestone_cash:high",
                    period=period,
                ),
                milestone_event_id=milestone_event_id,
                commercial_cost_rate_low=model_quantity(
                    "0.20",
                    "decimal",
                    f"Assumption:{asset_id}:commercial_cost_rate:low",
                    period=period,
                ),
                commercial_cost_rate_base=model_quantity(
                    "0.25",
                    "decimal",
                    f"Assumption:{asset_id}:commercial_cost_rate:base",
                    period=period,
                ),
                commercial_cost_rate_high=model_quantity(
                    "0.30",
                    "decimal",
                    f"Assumption:{asset_id}:commercial_cost_rate:high",
                    period=period,
                ),
            )
        )
    return BiopharmaAssetSpec(
        asset_id=asset_id,
        indication_id=indication_id,
        economic_right_id=economic_right_id,
        development_stage="phase2",
        required_event_ids=(required_event_id,),
        ownership_low=model_quantity(
            ownership[0],
            "decimal",
            f"Assumption:{asset_id}:ownership:low",
            period=AS_OF,
        ),
        ownership_base=model_quantity(
            ownership[1],
            "decimal",
            f"Assumption:{asset_id}:ownership:base",
            period=AS_OF,
        ),
        ownership_high=model_quantity(
            ownership[2],
            "decimal",
            f"Assumption:{asset_id}:ownership:high",
            period=AS_OF,
        ),
        royalty_burden_low=model_quantity(
            "0.10",
            "decimal",
            f"Assumption:{asset_id}:royalty_burden:low",
            period=AS_OF,
        ),
        royalty_burden_base=model_quantity(
            "0.15",
            "decimal",
            f"Assumption:{asset_id}:royalty_burden:base",
            period=AS_OF,
        ),
        royalty_burden_high=model_quantity(
            "0.20",
            "decimal",
            f"Assumption:{asset_id}:royalty_burden:high",
            period=AS_OF,
        ),
        launch_delay_years_low=model_quantity(
            "0",
            "years",
            f"Assumption:{asset_id}:launch_delay:low",
            period=AS_OF,
        ),
        launch_delay_years_base=model_quantity(
            "0",
            "years",
            f"Assumption:{asset_id}:launch_delay:base",
            period=AS_OF,
        ),
        launch_delay_years_high=model_quantity(
            "1",
            "years",
            f"Assumption:{asset_id}:launch_delay:high",
            period=AS_OF,
        ),
        delay_carry_cost_low=money(
            "25",
            f"{asset_id}:delay_carry_cost:low",
            period=AS_OF,
        ),
        delay_carry_cost_base=money(
            "50",
            f"{asset_id}:delay_carry_cost:base",
            period=AS_OF,
        ),
        delay_carry_cost_high=money(
            "75",
            f"{asset_id}:delay_carry_cost:high",
            period=AS_OF,
        ),
        periods=tuple(periods),
    )


def biopharma_spec(
    *,
    opening_cash: str = "1000",
) -> BiopharmaValuationSpec:
    events = (
        biopharma_event(
            "shared_phase2",
            "clinical",
            "2026E",
            ("0.40", "0.60", "0.80"),
        ),
        biopharma_event(
            "asset_a_regulatory",
            "regulatory",
            "2027E",
            ("0.50", "0.70", "0.85"),
            parents=("shared_phase2",),
        ),
        biopharma_event(
            "asset_a_launch",
            "commercial",
            "2028E",
            ("0.60", "0.80", "0.90"),
            parents=("asset_a_regulatory",),
        ),
        biopharma_event(
            "asset_b_regulatory",
            "regulatory",
            "2027E",
            ("0.45", "0.65", "0.80"),
            parents=("shared_phase2",),
        ),
        biopharma_event(
            "asset_b_launch",
            "commercial",
            "2029E",
            ("0.55", "0.75", "0.90"),
            parents=("asset_b_regulatory",),
        ),
    )
    assets = (
        biopharma_asset(
            "asset_a",
            "indication_alpha",
            "right_asset_a_alpha",
            "asset_a_launch",
            ("0", "0", "100", "300", "500"),
            ("60", "45", "25", "10", "0"),
            launch_event_period="2028E",
            ownership=("0.50", "0.60", "0.70"),
        ),
        biopharma_asset(
            "asset_b",
            "indication_beta",
            "right_asset_b_beta",
            "asset_b_launch",
            ("0", "0", "0", "150", "350"),
            ("50", "40", "30", "15", "0"),
            launch_event_period="2029E",
            ownership=("0.40", "0.50", "0.60"),
        ),
    )
    runway_periods = tuple(
        BiopharmaRunwayPeriodSpec(
            period=period,
            corporate_cash_burn_low=money(
                "20",
                f"corporate_cash_burn:{period}:low",
                period=period,
            ),
            corporate_cash_burn_base=money(
                "30",
                f"corporate_cash_burn:{period}:base",
                period=period,
            ),
            corporate_cash_burn_high=money(
                "45",
                f"corporate_cash_burn:{period}:high",
                period=period,
            ),
            financing=(
                BiopharmaFinancingSpec(
                    record_id="financing_2028",
                    period=period,
                    proceeds=money(
                        "80",
                        "financing_2028:proceeds",
                        period=period,
                        provenance_refs=(
                            "Fact:financing_2028:proceeds",
                        ),
                    ),
                    issue_price=per_share(
                        "8",
                        "financing_2028:issue_price",
                        period=period,
                    ),
                    new_shares=shares(
                        period,
                        "10",
                        provenance_refs=(
                            "Fact:financing_2028:new_shares",
                        ),
                    ),
                )
                if period == "2028E"
                else None
            ),
        )
        for period in FORECAST_PERIODS
    )
    return BiopharmaValuationSpec(
        events=events,
        assets=assets,
        opening_cash=money(
            opening_cash,
            "biopharma_opening_cash",
            period=OPENING_PERIOD,
            provenance_refs=("Fact:biopharma_opening_cash",),
        ),
        minimum_cash_buffer=money(
            "25",
            "biopharma_minimum_cash_buffer",
            period=OPENING_PERIOD,
        ),
        discount_rate_low=model_quantity(
            "0.12",
            "decimal",
            "Assumption:biopharma_discount_rate:low",
            period=AS_OF,
        ),
        discount_rate_base=model_quantity(
            "0.15",
            "decimal",
            "Assumption:biopharma_discount_rate:base",
            period=AS_OF,
        ),
        discount_rate_high=model_quantity(
            "0.18",
            "decimal",
            "Assumption:biopharma_discount_rate:high",
            period=AS_OF,
        ),
        runway_periods=runway_periods,
    )


def biopharma_request(
    *,
    spec: BiopharmaValuationSpec | None = None,
) -> DeterministicScenarioRequest:
    subject = scenario_request()
    pipeline_spec = spec or biopharma_spec()
    base = replace(
        subject.base_forecast_request,
        security=replace(
            subject.base_forecast_request.security,
            archetype=CompanyArchetype.BIOPHARMA,
        ),
    )
    opening = base.data_snapshot.company_opening_balance_sheet
    cash_delta = (
        pipeline_spec.opening_cash.normalized_value
        - opening.cash.normalized_value
    )
    opening_cash = replace(
        opening.cash,
        value=pipeline_spec.opening_cash.normalized_value,
        lineage_refs=pipeline_spec.opening_cash.provenance_refs,
    )
    opening_equity = replace(
        opening.equity,
        value=opening.equity.normalized_value + cash_delta,
        lineage_refs=("Fact:biopharma_opening_equity",),
    )
    opening = replace(
        opening,
        cash=opening_cash,
        equity=opening_equity,
    )
    facts = (
        SnapshotFact(
            fact_id="biopharma_opening_cash",
            subject_id=base.security.security_id,
            scope="company",
            segment_id="",
            metric_id="cash",
            field_name="cash",
            period=pipeline_spec.opening_cash.period,
            value=pipeline_spec.opening_cash.normalized_value,
            unit=pipeline_spec.opening_cash.unit,
            currency=pipeline_spec.opening_cash.currency,
            source_id="OFFICIAL_BIOPHARMA_DISCLOSURE",
            available_at=AS_OF,
            official=True,
        ),
        SnapshotFact(
            fact_id="biopharma_opening_equity",
            subject_id=base.security.security_id,
            scope="company",
            segment_id="",
            metric_id="equity",
            field_name="equity",
            period=opening_equity.period,
            value=opening_equity.normalized_value,
            unit=opening_equity.unit,
            currency=opening_equity.currency,
            source_id="OFFICIAL_BIOPHARMA_DISCLOSURE",
            available_at=AS_OF,
            official=True,
        ),
        *(
            SnapshotFact(
                fact_id=event.base_fact_refs[0].removeprefix("Fact:"),
                subject_id=base.security.security_id,
                scope="company",
                segment_id="",
                metric_id="biopharma_event_probability",
                field_name=event.event_id,
                period=event.period,
                value=event.probability_base.normalized_value,
                unit="decimal",
                currency="N/A",
                source_id=event.calibration_record_id,
                available_at=AS_OF,
                official=False,
            )
            for event in pipeline_spec.events
        ),
        *(
            SnapshotFact(
                fact_id=quantity.provenance_refs[0].removeprefix(
                    "Fact:"
                ),
                subject_id=base.security.security_id,
                scope="company",
                segment_id="",
                metric_id=metric_id,
                field_name=financing.record_id,
                period=financing.period,
                value=quantity.normalized_value,
                unit=quantity.unit,
                currency=quantity.currency,
                source_id=(
                    f"COMMITTED_FINANCING:{financing.record_id}"
                ),
                available_at=AS_OF,
                official=True,
            )
            for runway in pipeline_spec.runway_periods
            if runway.financing is not None
            for financing in (runway.financing,)
            for metric_id, quantity in (
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
        ),
    )
    base = replace(
        base,
        data_snapshot=replace(
            base.data_snapshot,
            company_opening_balance_sheet=opening,
            facts=base.data_snapshot.facts + facts,
            content_hash="",
        ),
    )
    return replace(
        subject,
        base_forecast_request=base,
        valuation_plan=replace(
            subject.valuation_plan,
            biopharma=pipeline_spec,
        ),
    )


def contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(contains_float(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_float(item) for item in value)
    return False


def test_deterministic_scenarios_recalculate_forecast_bridge_and_methods() -> None:
    result = ScenarioValuationEngine().run(scenario_request())

    assert result.probability_mode == "conditional_only"
    assert result.weighted_method_ranges == ()
    by_role = {item.role: item for item in result.scenarios}
    for item in result.scenarios:
        methods = {method.method_id: method for method in item.methods}
        assert methods["fcff_dcf"].status == "ready"
        assert methods["sotp"].status == "ready"
        assert methods["reverse_dcf"].status == "ready"
        assert methods["peer_comps"].status == "ready"
        assert methods["historical_band"].status == "blocked"
        assert methods["historical_band"].conditional_value_range is None
        assert all(method.formula_version for method in methods.values())
        assert all(method.lineage_refs for method in methods.values())
    stress = by_role[ScenarioRole.STRESS].method("fcff_dcf")
    base = by_role[ScenarioRole.BASE].method("fcff_dcf")
    improvement = by_role[ScenarioRole.IMPROVEMENT].method("fcff_dcf")
    assert (
        stress.conditional_value_range.per_share_base
        < base.conditional_value_range.per_share_base
        < improvement.conditional_value_range.per_share_base
    )
    assert not contains_float(result.to_dict())


def test_result_contract_rejects_duplicate_method_ids() -> None:
    result = ScenarioValuationEngine().run(scenario_request())
    scenario = result.scenarios[0]
    with pytest.raises(ScenarioInvariantError) as exc_info:
        replace(scenario, methods=scenario.methods + (scenario.methods[0],))

    assert exc_info.value.code == "SCENARIO_METHOD_ID_DUPLICATE"


def test_public_run_rejects_cross_scenario_method_order_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = IndustrialValuation.evaluate
    call_count = 0

    def reorder_second_scenario(self, context, plan):
        nonlocal call_count
        methods = original(self, context, plan)
        call_count += 1
        return tuple(reversed(methods)) if call_count == 2 else methods

    monkeypatch.setattr(IndustrialValuation, "evaluate", reorder_second_scenario)

    with pytest.raises(ScenarioInvariantError) as exc_info:
        ScenarioValuationEngine().run(scenario_request())

    assert exc_info.value.code == "SCENARIO_METHOD_PARTITION_INVALID"


def test_cyclical_resource_route_executes_mid_cycle_nav_and_pit_historical_band() -> None:
    result = ScenarioValuationEngine().run(cyclical_request())

    for scenario_result in result.scenarios:
        assert scenario_result.forecast_graph.template_id == (
            "cyclical_resource_driver_graph@1"
        )
        assert "stable-growth valuation is disabled" in (
            scenario_result.forecast_graph.routing_explanation
        )
        assert scenario_result.method("fcff_dcf").status == "blocked"
        assert "CYCLICAL_STABLE_GROWTH_DISABLED" in scenario_result.method(
            "fcff_dcf"
        ).diagnostics[0]
        mid_cycle = scenario_result.method("mid_cycle_ev_ebitda")
        nav = scenario_result.method("resource_nav")
        historical = scenario_result.method("cyclical_historical_band")
        assert mid_cycle.status == nav.status == historical.status == "ready"
        assert mid_cycle.conditional_value_range is not None
        assert nav.conditional_value_range is not None
        assert historical.conditional_value_range is not None
        assert "commodity-curve@2026-07-07" in mid_cycle.applicability
        assert any(
            "mechanically low multiple" in diagnostic
            for diagnostic in historical.diagnostics
        )
        assert any(
            "does not assume mean reversion" in diagnostic
            for diagnostic in historical.diagnostics
        )


def test_cyclical_enterprise_value_survives_when_per_share_basis_is_unavailable() -> None:
    subject = cyclical_request(probabilities=True)
    plan = replace(
        subject.valuation_plan,
        present_value_bridge=replace(
            subject.valuation_plan.present_value_bridge,
            diluted_shares=None,
        ),
        terminal_value_bridge=replace(
            subject.valuation_plan.terminal_value_bridge,
            diluted_shares=None,
        ),
    )

    result = ScenarioValuationEngine().run(
        replace(subject, valuation_plan=plan)
    )

    for scenario in result.scenarios:
        mid_cycle = scenario.method("mid_cycle_ev_ebitda")
        assert mid_cycle.status == "ready"
        assert mid_cycle.conditional_value_range is not None
        assert mid_cycle.conditional_value_range.base.equity_value.normalized_value
        assert mid_cycle.conditional_value_range.base.per_share_value is None
        assert not any(
            step["operation"] == "divide_diluted_shares"
            for step in mid_cycle.conditional_value_range.base.bridge_trace
        )
    assert result.weighted_method_ranges == ()
    assert any(
        "mid_cycle_ev_ebitda: not weighted because the per-share basis is unavailable."
        == item
        for item in result.weighting_diagnostics
    )


def test_cyclical_manufacturer_runs_mid_cycle_without_resource_or_history_inputs() -> None:
    subject = cyclical_request(
        spec=replace(
            cyclical_resource_spec(),
            assets=(),
            historical_observations=(),
        )
    )

    result = ScenarioValuationEngine().run(subject)

    for scenario in result.scenarios:
        assert scenario.method("mid_cycle_ev_ebitda").status == "ready"
        assert scenario.method("resource_nav").status == "blocked"
        assert "RESOURCE_NAV_NOT_APPLICABLE" in scenario.method(
            "resource_nav"
        ).diagnostics[0]
        assert scenario.method("cyclical_historical_band").status == "blocked"
        assert "CYCLICAL_HISTORY_INSUFFICIENT" in scenario.method(
            "cyclical_historical_band"
        ).diagnostics[0]


def test_cyclical_manufacturing_has_an_explicit_non_resource_route() -> None:
    subject = cyclical_request(
        spec=replace(
            cyclical_resource_spec(),
            assets=(),
            historical_observations=(),
        )
    )
    request = replace(
        subject.base_forecast_request,
        security=replace(
            subject.base_forecast_request.security,
            archetype=CompanyArchetype.CYCLICAL_MANUFACTURING,
        ),
    )

    result = ScenarioValuationEngine().run(
        replace(subject, base_forecast_request=request)
    )

    assert all(
        scenario.forecast_graph.template_id
        == "cyclical_manufacturing_driver_graph@1"
        for scenario in result.scenarios
    )
    assert all(
        scenario.method("mid_cycle_ev_ebitda").status == "ready"
        for scenario in result.scenarios
    )


def test_cyclical_stress_links_price_volume_yield_cost_and_maintenance_capex() -> None:
    result = ScenarioValuationEngine().run(cyclical_request())
    by_role = {item.role: item for item in result.scenarios}

    for method_id in ("mid_cycle_ev_ebitda", "resource_nav"):
        stress = by_role[ScenarioRole.STRESS].method(method_id)
        base = by_role[ScenarioRole.BASE].method(method_id)
        improvement = by_role[ScenarioRole.IMPROVEMENT].method(method_id)
        assert (
            stress.conditional_value_range.per_share_base
            < base.conditional_value_range.per_share_base
            < improvement.conditional_value_range.per_share_base
        )
        sensitivity_names = {item.name for item in base.sensitivity}
        assert {
            "commodity_price",
            "production_volume",
            "grade_yield",
            "unit_cost",
            "maintenance_capex",
        } <= sensitivity_names
        sensitivities = {item.name: item for item in base.sensitivity}
        for name in (
            "production_volume",
            "unit_cost",
            "operating_expense",
            "maintenance_capex",
        ):
            sensitivity = sensitivities[name]
            assert (
                sensitivity.low.normalized_value
                < sensitivity.base.normalized_value
                < sensitivity.high.normalized_value
            )
    stress_sensitivity = {
        item.name: item
        for item in by_role[ScenarioRole.STRESS]
        .method("resource_nav")
        .sensitivity
    }
    base_sensitivity = {
        item.name: item
        for item in by_role[ScenarioRole.BASE]
        .method("resource_nav")
        .sensitivity
    }
    improvement_sensitivity = {
        item.name: item
        for item in by_role[ScenarioRole.IMPROVEMENT]
        .method("resource_nav")
        .sensitivity
    }
    assert (
        stress_sensitivity["commodity_price"].base.normalized_value
        < base_sensitivity["commodity_price"].base.normalized_value
        < improvement_sensitivity["commodity_price"].base.normalized_value
    )
    assert (
        stress_sensitivity["production_volume"].base.normalized_value
        < base_sensitivity["production_volume"].base.normalized_value
        < improvement_sensitivity["production_volume"].base.normalized_value
    )
    assert (
        stress_sensitivity["unit_cost"].base.normalized_value
        > base_sensitivity["unit_cost"].base.normalized_value
        > improvement_sensitivity["unit_cost"].base.normalized_value
    )


def test_cyclical_resource_over_extraction_fails_closed_without_affecting_mid_cycle() -> None:
    result = ScenarioValuationEngine().run(
        cyclical_request(spec=cyclical_resource_spec(reserve_value="1"))
    )

    for scenario_result in result.scenarios:
        assert scenario_result.method("resource_nav").status == "blocked"
        assert "RESOURCE_RESERVE_OVER_EXTRACTION" in scenario_result.method(
            "resource_nav"
        ).diagnostics[0]
        assert scenario_result.method("mid_cycle_ev_ebitda").status == "ready"


def test_cyclical_resource_rejects_negative_life_and_unit_mismatch() -> None:
    with pytest.raises(ScenarioInvariantError) as negative_life:
        cyclical_resource_spec(life_years=-1)
    assert negative_life.value.code == "RESOURCE_LIFE_INVALID"

    result = ScenarioValuationEngine().run(
        cyclical_request(
            spec=cyclical_resource_spec(reserve_unit="tonnes")
        )
    )
    for scenario_result in result.scenarios:
        assert scenario_result.method("resource_nav").status == "blocked"
        assert "RESOURCE_UNIT_MISMATCH" in scenario_result.method(
            "resource_nav"
        ).diagnostics[0]


def test_cyclical_critical_inputs_must_resolve_through_frozen_snapshot() -> None:
    subject = cyclical_request()
    reserve_fact_ids = {
        asset.reserve_quantity.lineage_refs[0].removeprefix("Fact:")
        for asset in subject.valuation_plan.cyclical_resource.assets
    }
    snapshot = subject.base_forecast_request.data_snapshot
    broken_snapshot = replace(
        snapshot,
        facts=tuple(
            fact
            for fact in snapshot.facts
            if fact.fact_id not in reserve_fact_ids
        ),
        content_hash="",
    )
    result = ScenarioValuationEngine().run(
        replace(
            subject,
            base_forecast_request=replace(
                subject.base_forecast_request,
                data_snapshot=broken_snapshot,
            ),
        )
    )

    for scenario_result in result.scenarios:
        for method_id in (
            "mid_cycle_ev_ebitda",
            "resource_nav",
            "cyclical_historical_band",
        ):
            method = scenario_result.method(method_id)
            assert method.status == "blocked"
            assert "CYCLICAL_EVIDENCE_INVALID" in method.diagnostics[0]


def test_resource_nav_supports_life_beyond_forecast_and_responds_to_opex() -> None:
    long_life = cyclical_resource_spec(life_years=8)
    result = ScenarioValuationEngine().run(cyclical_request(spec=long_life))
    assert all(
        item.method("resource_nav").status == "ready"
        for item in result.scenarios
    )

    higher_opex = replace(
        long_life,
        assets=tuple(
            replace(
                asset,
                schedule=tuple(
                    replace(
                        item,
                        operating_expense_low=replace(
                            item.operating_expense_low,
                            value=item.operating_expense_low.value
                            * Decimal("1.5"),
                        ),
                        operating_expense_base=replace(
                            item.operating_expense_base,
                            value=item.operating_expense_base.value
                            * Decimal("1.5"),
                        ),
                        operating_expense_high=replace(
                            item.operating_expense_high,
                            value=item.operating_expense_high.value
                            * Decimal("1.5"),
                        ),
                    )
                    for item in asset.schedule
                ),
            )
            for asset in long_life.assets
        ),
    )
    base_nav = {
        item.role: item.method("resource_nav").conditional_value_range.per_share_base
        for item in result.scenarios
    }
    higher_opex_result = ScenarioValuationEngine().run(
        cyclical_request(spec=higher_opex)
    )
    assert all(
        item.method("resource_nav").conditional_value_range.per_share_base
        < base_nav[item.role]
        for item in higher_opex_result.scenarios
    )


def test_resource_schedule_chronology_and_cross_asset_currency_fail_closed() -> None:
    spec = cyclical_resource_spec()
    with pytest.raises(ScenarioInvariantError) as chronology:
        replace(
            spec.assets[0],
            schedule=tuple(reversed(spec.assets[0].schedule)),
        )
    assert chronology.value.code == "RESOURCE_SCHEDULE_CHRONOLOGY_INVALID"

    target_segment = spec.assets[0].segment_id

    def usd_money_quantity(quantity: FinancialQuantity) -> FinancialQuantity:
        return replace(quantity, unit="USD", currency="USD")

    def usd_unit_cost(quantity: ForecastQuantity) -> ForecastQuantity:
        return replace(quantity, unit="USD/unit", currency="USD")

    usd_schedule = tuple(
        replace(
            item,
            unit_cost_low=usd_unit_cost(item.unit_cost_low),
            unit_cost_base=usd_unit_cost(item.unit_cost_base),
            unit_cost_high=usd_unit_cost(item.unit_cost_high),
            operating_expense_low=usd_money_quantity(
                item.operating_expense_low
            ),
            operating_expense_base=usd_money_quantity(
                item.operating_expense_base
            ),
            operating_expense_high=usd_money_quantity(
                item.operating_expense_high
            ),
            maintenance_capex_low=usd_money_quantity(
                item.maintenance_capex_low
            ),
            maintenance_capex_base=usd_money_quantity(
                item.maintenance_capex_base
            ),
            maintenance_capex_high=usd_money_quantity(
                item.maintenance_capex_high
            ),
        )
        for item in spec.assets[0].schedule
    )
    usd_asset = replace(spec.assets[0], schedule=usd_schedule)
    usd_curve = tuple(
        replace(
            point,
            price_low=usd_unit_cost(point.price_low),
            price_base=usd_unit_cost(point.price_base),
            price_high=usd_unit_cost(point.price_high),
        )
        if point.segment_id == target_segment
        else point
        for point in spec.commodity_curve
    )
    mixed_currency_spec = replace(
        spec,
        assets=(usd_asset, *spec.assets[1:]),
        commodity_curve=usd_curve,
    )
    result = ScenarioValuationEngine().run(
        cyclical_request(spec=mixed_currency_spec)
    )
    for scenario_result in result.scenarios:
        for method_id in (
            "mid_cycle_ev_ebitda",
            "resource_nav",
            "cyclical_historical_band",
        ):
            method = scenario_result.method(method_id)
            assert method.status == "blocked"
            assert "RESOURCE_REPORTING_CURRENCY_MISMATCH" in method.diagnostics[0]


def test_financial_institution_route_disables_fcff_and_executes_specialized_methods() -> None:
    result = ScenarioValuationEngine().run(financial_request())

    for scenario_result in result.scenarios:
        assert scenario_result.forecast_graph.template_id == (
            "financial_institution_valuation_shell@1"
        )
        assert "Industrial FCFF/WACC" in (
            scenario_result.forecast_graph.routing_explanation
        )
        assert scenario_result.method("fcff_dcf").status == "blocked"
        assert "FINANCIAL_FCFF_DISABLED" in scenario_result.method(
            "fcff_dcf"
        ).diagnostics[0]
        assert scenario_result.method("sotp").status == "blocked"
        assert scenario_result.method("reverse_dcf").status == "blocked"
        for method_id in (
            "justified_pb",
            "dividend_discount_model",
            "residual_income",
        ):
            method = scenario_result.method(method_id)
            assert method.status == "ready"
            assert method.value_basis == "equity_value"
            assert method.conditional_value_range is not None
            assert any(
                "no cross-method averaging" in diagnostic
                for diagnostic in method.diagnostics
            )


def test_financial_ddm_and_residual_income_cross_explain_without_composite() -> None:
    result = ScenarioValuationEngine().run(financial_request())
    base_scenario = next(
        item for item in result.scenarios if item.role == ScenarioRole.BASE
    )
    ddm = base_scenario.method(
        "dividend_discount_model"
    ).conditional_value_range.per_share_base
    residual_income = base_scenario.method(
        "residual_income"
    ).conditional_value_range.per_share_base
    justified_pb = base_scenario.method(
        "justified_pb"
    ).conditional_value_range.per_share_base

    assert ddm > 0
    assert residual_income > 0
    assert abs(ddm - residual_income) < Decimal("1E-40")
    assert abs(ddm - justified_pb) < Decimal("1E-40")
    assert result.cross_method_composite is None


def test_financial_scenarios_and_specialized_metrics_change_values() -> None:
    baseline = ScenarioValuationEngine().run(financial_request())
    pb_by_role = {
        item.role: item.method(
            "justified_pb"
        ).conditional_value_range.per_share_base
        for item in baseline.scenarios
    }
    assert (
        pb_by_role[ScenarioRole.STRESS]
        < pb_by_role[ScenarioRole.BASE]
        < pb_by_role[ScenarioRole.IMPROVEMENT]
    )
    assert len(
        {item.forecast_graph.graph_id for item in baseline.scenarios}
    ) == 3

    base_spec = financial_institution_spec()
    weaker_periods = tuple(
        replace(
            period,
            operating_metrics=tuple(
                financial_metric(
                    metric.metric_id,
                    period.period,
                    (
                        ("0.010", "0.015", "0.020")
                        if metric.metric_id == "nim"
                        else (
                            "0.015",
                            "0.020",
                            "0.030",
                        )
                    ),
                )
                for metric in period.operating_metrics
            ),
        )
        for period in base_spec.periods
    )
    weaker = ScenarioValuationEngine().run(
        financial_request(
            spec=replace(
                base_spec,
                periods=weaker_periods,
                terminal_growth_low=replace(
                    base_spec.terminal_growth_low,
                    value=Decimal("0.007"),
                ),
                terminal_growth_base=replace(
                    base_spec.terminal_growth_base,
                    value=Decimal("0.0225"),
                ),
                terminal_growth_high=replace(
                    base_spec.terminal_growth_high,
                    value=Decimal("0.033"),
                ),
            )
        )
    )
    weaker_base = next(
        item for item in weaker.scenarios if item.role == ScenarioRole.BASE
    )
    assert (
        weaker_base.method(
            "justified_pb"
        ).conditional_value_range.per_share_base
        < pb_by_role[ScenarioRole.BASE]
    )


def test_financial_dilution_changes_per_share_not_total_equity_value() -> None:
    diluted_spec = financial_institution_spec()
    undiluted_periods = tuple(
        replace(
            period,
            dilution_factor_low=replace(
                period.dilution_factor_low,
                value=Decimal("1"),
            ),
            dilution_factor_base=replace(
                period.dilution_factor_base,
                value=Decimal("1"),
            ),
            dilution_factor_high=replace(
                period.dilution_factor_high,
                value=Decimal("1"),
            ),
        )
        for period in diluted_spec.periods
    )
    diluted = ScenarioValuationEngine().run(
        financial_request(spec=diluted_spec)
    )
    undiluted = ScenarioValuationEngine().run(
        financial_request(
            spec=replace(
                diluted_spec,
                periods=undiluted_periods,
            )
        )
    )
    diluted_method = next(
        item for item in diluted.scenarios if item.role == ScenarioRole.BASE
    ).method("dividend_discount_model")
    undiluted_method = next(
        item for item in undiluted.scenarios if item.role == ScenarioRole.BASE
    ).method("dividend_discount_model")

    assert (
        diluted_method.conditional_value_range.equity_value_base
        == undiluted_method.conditional_value_range.equity_value_base
    )
    assert (
        diluted_method.conditional_value_range.per_share_base
        < undiluted_method.conditional_value_range.per_share_base
    )


def test_financial_terminal_clean_surplus_requires_explicit_terminal_model() -> None:
    base_spec = financial_institution_spec()
    terminal = base_spec.periods[-1]
    unsupported_terminal = replace(
        terminal,
        clean_surplus_adjustment_low=replace(
            terminal.clean_surplus_adjustment_low,
            value=Decimal("5"),
        ),
        clean_surplus_adjustment_base=replace(
            terminal.clean_surplus_adjustment_base,
            value=Decimal("10"),
        ),
        clean_surplus_adjustment_high=replace(
            terminal.clean_surplus_adjustment_high,
            value=Decimal("15"),
        ),
    )
    result = ScenarioValuationEngine().run(
        financial_request(
            spec=replace(
                base_spec,
                periods=(
                    *base_spec.periods[:-1],
                    unsupported_terminal,
                ),
            )
        )
    )

    for scenario_result in result.scenarios:
        for method_id in (
            "justified_pb",
            "dividend_discount_model",
            "residual_income",
        ):
            method = scenario_result.method(method_id)
            assert method.status == "blocked"
            assert (
                "FINANCIAL_TERMINAL_CLEAN_SURPLUS_UNSUPPORTED"
                in method.diagnostics[0]
            )


def test_financial_finite_clean_surplus_adjustments_reconcile_methods() -> None:
    base_spec = financial_institution_spec()
    adjusted_periods = tuple(
        period
        if index == len(base_spec.periods) - 1
        else replace(
            period,
            clean_surplus_adjustment_low=replace(
                period.clean_surplus_adjustment_low,
                value=Decimal("5"),
            ),
            clean_surplus_adjustment_base=replace(
                period.clean_surplus_adjustment_base,
                value=Decimal("10"),
            ),
            clean_surplus_adjustment_high=replace(
                period.clean_surplus_adjustment_high,
                value=Decimal("15"),
            ),
        )
        for index, period in enumerate(base_spec.periods)
    )
    result = ScenarioValuationEngine().run(
        financial_request(
            spec=replace(base_spec, periods=adjusted_periods)
        )
    )

    for scenario_result in result.scenarios:
        values = tuple(
            scenario_result.method(
                method_id
            ).conditional_value_range.equity_value_base
            for method_id in (
                "justified_pb",
                "dividend_discount_model",
                "residual_income",
            )
        )
        assert max(values) - min(values) < Decimal("1E-40")


def test_financial_missing_inputs_and_regulatory_breach_fail_locally() -> None:
    subject = financial_request()
    missing = ScenarioValuationEngine().run(
        replace(
            subject,
            valuation_plan=replace(
                subject.valuation_plan,
                financial_institution=None,
            ),
        )
    )
    for scenario_result in missing.scenarios:
        for method_id in (
            "justified_pb",
            "dividend_discount_model",
            "residual_income",
        ):
            assert scenario_result.method(method_id).status == "blocked"
        assert scenario_result.method("fcff_dcf").status == "blocked"

    base_spec = financial_institution_spec()
    capital_stressed_periods = tuple(
        replace(
            period,
            regulatory_capital_adjustment_low=replace(
                period.regulatory_capital_adjustment_low,
                value=Decimal("-100"),
            ),
            regulatory_capital_adjustment_base=replace(
                period.regulatory_capital_adjustment_base,
                value=Decimal("-100"),
            ),
            regulatory_capital_adjustment_high=replace(
                period.regulatory_capital_adjustment_high,
                value=Decimal("-100"),
            ),
        )
        for period in base_spec.periods
    )
    breached = ScenarioValuationEngine().run(
        financial_request(
            spec=replace(
                base_spec,
                periods=capital_stressed_periods,
            )
        )
    )
    for scenario_result in breached.scenarios:
        for method_id in (
            "justified_pb",
            "dividend_discount_model",
            "residual_income",
        ):
            method = scenario_result.method(method_id)
            assert method.status == "blocked"
            assert "FINANCIAL_REGULATORY_CAPITAL_BREACH" in method.diagnostics[0]


def test_financial_opening_capital_period_and_as_of_fail_closed() -> None:
    base_spec = financial_institution_spec()
    opening_breach = replace(
        base_spec,
        opening_regulatory_capital=replace(
            base_spec.opening_regulatory_capital,
            value=Decimal("99"),
        ),
    )
    breached = ScenarioValuationEngine().run(
        financial_request(spec=opening_breach)
    )
    for scenario_result in breached.scenarios:
        assert (
            "FINANCIAL_OPENING_CAPITAL_BREACH"
            in scenario_result.method("justified_pb").diagnostics[0]
        )

    wrong_period = replace(
        base_spec,
        opening_book_value=replace(
            base_spec.opening_book_value,
            period="2020FY",
        ),
        opening_regulatory_capital=replace(
            base_spec.opening_regulatory_capital,
            period="2020FY",
        ),
        opening_risk_weighted_assets=replace(
            base_spec.opening_risk_weighted_assets,
            period="2020FY",
        ),
    )
    period_result = ScenarioValuationEngine().run(
        financial_request(spec=wrong_period)
    )
    for scenario_result in period_result.scenarios:
        assert (
            "FINANCIAL_OPENING_PERIOD_INVALID"
            in scenario_result.method("justified_pb").diagnostics[0]
        )

    first = base_spec.periods[0]
    wrong_as_of = replace(
        first,
        payout_low=replace(first.payout_low, as_of="2030-01-01"),
        payout_base=replace(first.payout_base, as_of="2030-01-01"),
        payout_high=replace(first.payout_high, as_of="2030-01-01"),
    )
    as_of_result = ScenarioValuationEngine().run(
        financial_request(
            spec=replace(
                base_spec,
                periods=(wrong_as_of, *base_spec.periods[1:]),
            )
        )
    )
    for scenario_result in as_of_result.scenarios:
        assert (
            "FINANCIAL_AS_OF_INVALID"
            in scenario_result.method("justified_pb").diagnostics[0]
        )


def test_financial_specialized_metric_domains_are_validated() -> None:
    base_spec = financial_institution_spec()
    first = base_spec.periods[0]
    npl = next(
        metric
        for metric in first.operating_metrics
        if metric.metric_id == "npl_ratio"
    )
    invalid_npl = replace(
        npl,
        low=replace(npl.low, value=Decimal("-0.01")),
    )
    invalid_period = replace(
        first,
        operating_metrics=tuple(
            invalid_npl if metric.metric_id == "npl_ratio" else metric
            for metric in first.operating_metrics
        ),
    )
    with pytest.raises(ScenarioInvariantError) as metric_error:
        replace(
            base_spec,
            periods=(invalid_period, *base_spec.periods[1:]),
        )
    assert (
        metric_error.value.code
        == "FINANCIAL_SPECIALIZED_METRIC_DOMAIN_INVALID"
    )

    with pytest.raises(ScenarioInvariantError) as limit_error:
        replace(
            base_spec,
            specialized_risk_limit=replace(
                base_spec.specialized_risk_limit,
                value=Decimal("2"),
            ),
        )
    assert (
        limit_error.value.code
        == "FINANCIAL_SPECIALIZED_METRIC_DOMAIN_INVALID"
    )


def test_financial_lineage_distinguishes_each_scenario_case() -> None:
    result = ScenarioValuationEngine().run(financial_request())
    lineages = {
        item.role: item.method("dividend_discount_model").lineage_refs
        for item in result.scenarios
    }

    assert len(set(lineages.values())) == 3
    for role, refs in lineages.items():
        expected_case = {
            ScenarioRole.STRESS: "low",
            ScenarioRole.BASE: "base",
            ScenarioRole.IMPROVEMENT: "high",
        }[role]
        assert (
            f"Assumption:financial_scenario_case:{expected_case}"
            in refs
        )
        assert any(
            ref.startswith("Assumption:financial_scenario_overrides:")
            for ref in refs
        )


def test_financial_methods_discount_with_actual_act365_dates() -> None:
    result = ScenarioValuationEngine().run(financial_request())
    base_result = next(
        item for item in result.scenarios if item.role == ScenarioRole.BASE
    )
    method = base_result.method("dividend_discount_model")

    assert method.conditional_value_range.equity_value_base == Decimal(
        "2850.1833072492151089437006595555892050569422243726"
    )
    assert method.horizon == (
        f"valuation_as_of={AS_OF};"
        f"financial_periods={FORECAST_PERIODS[0]}..{FORECAST_PERIODS[-1]}"
    )


@pytest.mark.parametrize(
    (
        "institution_type",
        "metric_values",
        "exposure_values",
        "risk_limit",
    ),
    (
        (
            "insurance",
            {
                "combined_ratio": ("0.92", "0.96", "1.02"),
                "solvency_ratio": ("0.12", "0.15", "0.18"),
            },
            ("0.50", "0.75", "1.00"),
            "0.11",
        ),
        (
            "broker",
            {
                "net_capital_ratio": ("0.12", "0.15", "0.18"),
                "fee_income_yield": ("0.03", "0.05", "0.07"),
            },
            ("0.50", "0.75", "1.00"),
            "0.11",
        ),
    ),
)
def test_insurance_and_broker_require_and_preserve_specialized_drivers(
    institution_type: str,
    metric_values: dict[str, tuple[str, str, str]],
    exposure_values: tuple[str, str, str],
    risk_limit: str,
) -> None:
    base_spec = financial_institution_spec()
    periods = []
    for period in base_spec.periods:
        metrics = tuple(
            financial_metric(
                metric_id,
                period.period,
                values,
            )
            for metric_id, values in metric_values.items()
        )
        periods.append(
            replace(
                period,
                operating_metrics=metrics,
                roe_low=replace(
                    period.roe_low,
                    lineage_refs=(
                        *(ref for metric in metrics for ref in metric.low.lineage_refs),
                        f"Assumption:roe:{period.period}:low",
                    ),
                ),
                roe_base=replace(
                    period.roe_base,
                    lineage_refs=(
                        *(ref for metric in metrics for ref in metric.base.lineage_refs),
                        f"Assumption:roe:{period.period}:base",
                    ),
                ),
                roe_high=replace(
                    period.roe_high,
                    lineage_refs=(
                        *(ref for metric in metrics for ref in metric.high.lineage_refs),
                        f"Assumption:roe:{period.period}:high",
                    ),
                ),
                operating_exposure_to_equity_low=model_quantity(
                    exposure_values[0],
                    "x",
                    (
                        "Assumption:operating_exposure_to_equity:"
                        f"{period.period}:low"
                    ),
                    period=period.period,
                ),
                operating_exposure_to_equity_base=model_quantity(
                    exposure_values[1],
                    "x",
                    (
                        "Assumption:operating_exposure_to_equity:"
                        f"{period.period}:base"
                    ),
                    period=period.period,
                ),
                operating_exposure_to_equity_high=model_quantity(
                    exposure_values[2],
                    "x",
                    (
                        "Assumption:operating_exposure_to_equity:"
                        f"{period.period}:high"
                    ),
                    period=period.period,
                ),
            )
        )
    spec = replace(
        base_spec,
        institution_type=institution_type,
        periods=tuple(periods),
        specialized_risk_limit=model_quantity(
            risk_limit,
            "decimal",
            "Assumption:specialized_risk_limit",
            period=AS_OF,
        ),
    )

    result = ScenarioValuationEngine().run(financial_request(spec=spec))

    for scenario_result in result.scenarios:
        assert scenario_result.method("justified_pb").status == "ready"
        assert scenario_result.method("dividend_discount_model").status == "ready"
        assert scenario_result.method("residual_income").status == "ready"


def test_biopharma_route_executes_rnpv_sotp_and_runway_gate() -> None:
    result = ScenarioValuationEngine().run(biopharma_request())
    per_share = {}

    for scenario_result in result.scenarios:
        assert scenario_result.forecast_graph.template_id == (
            "biopharma_pipeline_valuation_shell@1"
        )
        assert "asset/indication" in (
            scenario_result.forecast_graph.routing_explanation
        )
        for method_id in (
            "fcff_dcf",
            "sotp",
            "reverse_dcf",
            "peer_comps",
            "historical_band",
        ):
            assert scenario_result.method(method_id).status == "blocked"
        rnpv = scenario_result.method("pipeline_rnpv")
        pipeline_sotp = scenario_result.method("pipeline_sotp")
        assert rnpv.status == "ready"
        assert pipeline_sotp.status == "ready"
        assert (
            rnpv.conditional_value_range.equity_value_low,
            rnpv.conditional_value_range.equity_value_base,
            rnpv.conditional_value_range.equity_value_high,
        ) == (
            pipeline_sotp.conditional_value_range.equity_value_low,
            pipeline_sotp.conditional_value_range.equity_value_base,
            pipeline_sotp.conditional_value_range.equity_value_high,
        )
        assert any(
            "Cash runway remains above" in diagnostic
            for diagnostic in rnpv.diagnostics
        )
        assert any(
            "no automatic mature-revenue" in diagnostic
            for diagnostic in rnpv.diagnostics
        )
        per_share[scenario_result.role] = (
            rnpv.conditional_value_range.per_share_base
        )

    assert (
        per_share[ScenarioRole.STRESS]
        < per_share[ScenarioRole.BASE]
        < per_share[ScenarioRole.IMPROVEMENT]
    )
    assert result.cross_method_composite is None


def test_biopharma_missing_share_basis_blocks_methods_without_crashing() -> None:
    subject = biopharma_request()
    plan = replace(
        subject.valuation_plan,
        present_value_bridge=replace(
            subject.valuation_plan.present_value_bridge,
            diluted_shares=None,
        ),
        terminal_value_bridge=replace(
            subject.valuation_plan.terminal_value_bridge,
            diluted_shares=None,
        ),
    )

    result = ScenarioValuationEngine().run(
        replace(subject, valuation_plan=plan)
    )

    for scenario_result in result.scenarios:
        for method_id in ("pipeline_rnpv", "pipeline_sotp"):
            method = scenario_result.method(method_id)
            assert method.status == "blocked"
            assert "BIOPHARMA_DILUTION_BASIS_MISSING" in method.diagnostics[0]


def test_biopharma_shared_event_failure_hits_dependent_assets() -> None:
    baseline = ScenarioValuationEngine().run(biopharma_request())
    baseline_base = next(
        item for item in baseline.scenarios if item.role == ScenarioRole.BASE
    ).method("pipeline_rnpv")
    spec = biopharma_spec()
    shared = spec.events[0]
    failed_shared = replace(
        shared,
        probability_low=replace(
            shared.probability_low,
            value=Decimal("0"),
        ),
        probability_base=replace(
            shared.probability_base,
            value=Decimal("0"),
        ),
        probability_high=replace(
            shared.probability_high,
            value=Decimal("0"),
        ),
    )
    failed = ScenarioValuationEngine().run(
        biopharma_request(
            spec=replace(
                spec,
                events=(failed_shared, *spec.events[1:]),
            )
        )
    )
    failed_base = next(
        item for item in failed.scenarios if item.role == ScenarioRole.BASE
    ).method("pipeline_rnpv")

    assert failed_base.status == "ready"
    assert (
        failed_base.conditional_value_range.per_share_base
        < baseline_base.conditional_value_range.per_share_base
    )
    probability_diagnostic = next(
        diagnostic
        for diagnostic in failed_base.diagnostics
        if diagnostic.startswith("Asset cumulative success probabilities:")
    )
    assert "asset_a:indication_alpha=0" in probability_diagnostic
    assert "asset_b:indication_beta=0" in probability_diagnostic

    redundant_path_asset = replace(
        spec.assets[0],
        required_event_ids=("shared_phase2", "asset_a_launch"),
    )
    redundant = ScenarioValuationEngine().run(
        biopharma_request(
            spec=replace(
                spec,
                assets=(redundant_path_asset, *spec.assets[1:]),
            )
        )
    )
    redundant_base = next(
        item for item in redundant.scenarios if item.role == ScenarioRole.BASE
    ).method("pipeline_rnpv")
    assert (
        redundant_base.conditional_value_range.equity_value_base
        == baseline_base.conditional_value_range.equity_value_base
    )


def test_biopharma_delay_license_and_dilution_change_supported_terms() -> None:
    base_spec = biopharma_spec()
    baseline = ScenarioValuationEngine().run(
        biopharma_request(spec=base_spec)
    )
    baseline_base = next(
        item for item in baseline.scenarios if item.role == ScenarioRole.BASE
    ).method("pipeline_rnpv")

    first_asset = base_spec.assets[0]
    delayed_asset = replace(
        first_asset,
        launch_delay_years_low=replace(
            first_asset.launch_delay_years_low,
            value=Decimal("1"),
        ),
        launch_delay_years_base=replace(
            first_asset.launch_delay_years_base,
            value=Decimal("1"),
        ),
        launch_delay_years_high=replace(
            first_asset.launch_delay_years_high,
            value=Decimal("2"),
        ),
    )
    delayed = ScenarioValuationEngine().run(
        biopharma_request(
            spec=replace(
                base_spec,
                assets=(delayed_asset, *base_spec.assets[1:]),
            )
        )
    )
    delayed_base = next(
        item for item in delayed.scenarios if item.role == ScenarioRole.BASE
    ).method("pipeline_rnpv")
    assert (
        delayed_base.conditional_value_range.equity_value_base
        < baseline_base.conditional_value_range.equity_value_base
    )

    lower_rights_asset = replace(
        first_asset,
        ownership_low=replace(
            first_asset.ownership_low,
            value=Decimal("0.30"),
        ),
        ownership_base=replace(
            first_asset.ownership_base,
            value=Decimal("0.40"),
        ),
        ownership_high=replace(
            first_asset.ownership_high,
            value=Decimal("0.50"),
        ),
    )
    lower_rights = ScenarioValuationEngine().run(
        biopharma_request(
            spec=replace(
                base_spec,
                assets=(lower_rights_asset, *base_spec.assets[1:]),
            )
        )
    )
    lower_rights_base = next(
        item
        for item in lower_rights.scenarios
        if item.role == ScenarioRole.BASE
    ).method("pipeline_rnpv")
    assert (
        lower_rights_base.conditional_value_range.equity_value_base
        < baseline_base.conditional_value_range.equity_value_base
    )

    financing = base_spec.runway_periods[2]
    assert financing.financing is not None
    more_dilutive = replace(
        financing,
        financing=replace(
            financing.financing,
            issue_price=per_share(
                "4",
                "financing_2028:issue_price",
                period=financing.period,
            ),
            new_shares=shares(
                financing.period,
                "20",
                provenance_refs=(
                    "Fact:financing_2028:new_shares",
                ),
            ),
        ),
    )
    diluted = ScenarioValuationEngine().run(
        biopharma_request(
            spec=replace(
                base_spec,
                runway_periods=(
                    *base_spec.runway_periods[:2],
                    more_dilutive,
                    *base_spec.runway_periods[3:],
                ),
            )
        )
    )
    diluted_base = next(
        item for item in diluted.scenarios if item.role == ScenarioRole.BASE
    ).method("pipeline_rnpv")
    assert (
        diluted_base.conditional_value_range.equity_value_base
        == baseline_base.conditional_value_range.equity_value_base
    )
    assert (
        diluted_base.conditional_value_range.per_share_base
        < baseline_base.conditional_value_range.per_share_base
    )


def test_biopharma_probability_evidence_and_runway_fail_locally() -> None:
    subject = biopharma_request()
    missing = ScenarioValuationEngine().run(
        replace(
            subject,
            valuation_plan=replace(
                subject.valuation_plan,
                biopharma=None,
            ),
        )
    )
    for scenario_result in missing.scenarios:
        for method_id in ("pipeline_rnpv", "pipeline_sotp"):
            assert scenario_result.method(method_id).status == "blocked"
        assert scenario_result.method("fcff_dcf").status == "blocked"

    target_fact_id = (
        subject.valuation_plan.biopharma.events[0]
        .base_fact_refs[0]
        .removeprefix("Fact:")
    )
    unsupported_facts = tuple(
        replace(fact, source_id="UNVERIFIED_WEB_ESTIMATE")
        if fact.fact_id == target_fact_id
        else fact
        for fact in subject.base_forecast_request.data_snapshot.facts
    )
    unsupported = ScenarioValuationEngine().run(
        replace(
            subject,
            base_forecast_request=replace(
                subject.base_forecast_request,
                data_snapshot=replace(
                    subject.base_forecast_request.data_snapshot,
                    facts=unsupported_facts,
                    content_hash="",
                ),
            ),
        )
    )
    for scenario_result in unsupported.scenarios:
        for method_id in ("pipeline_rnpv", "pipeline_sotp"):
            method = scenario_result.method(method_id)
            assert method.status == "blocked"
            assert (
                "BIOPHARMA_PROBABILITY_EVIDENCE_INVALID"
                in method.diagnostics[0]
            )

    runway_breach = ScenarioValuationEngine().run(
        biopharma_request(spec=biopharma_spec(opening_cash="50"))
    )
    for scenario_result in runway_breach.scenarios:
        for method_id in ("pipeline_rnpv", "pipeline_sotp"):
            method = scenario_result.method(method_id)
            assert method.status == "blocked"
            assert "BIOPHARMA_RUNWAY_PATH_BREACH" in method.diagnostics[0]


def test_biopharma_runway_checks_success_failure_paths_not_expected_cash() -> None:
    spec = biopharma_spec()
    asset = spec.assets[0]
    period = asset.periods[1]
    conditional_spend = replace(
        period,
        development_cost_low=replace(
            period.development_cost_low,
            value=Decimal("800"),
        ),
        development_cost_base=replace(
            period.development_cost_base,
            value=Decimal("900"),
        ),
        development_cost_high=replace(
            period.development_cost_high,
            value=Decimal("1000"),
        ),
    )
    stressed_asset = replace(
        asset,
        periods=(
            asset.periods[0],
            conditional_spend,
            *asset.periods[2:],
        ),
    )
    result = ScenarioValuationEngine().run(
        biopharma_request(
            spec=replace(
                spec,
                assets=(stressed_asset, *spec.assets[1:]),
            )
        )
    )
    base = next(
        item for item in result.scenarios if item.role == ScenarioRole.BASE
    ).method("pipeline_rnpv")

    assert base.status == "blocked"
    assert "BIOPHARMA_RUNWAY_PATH_BREACH" in base.diagnostics[0]
    assert "2027E" in base.diagnostics[0]


def test_biopharma_financing_requires_exact_committed_terms() -> None:
    subject = biopharma_request()
    facts = tuple(
        replace(fact, source_id="MANAGEMENT_SCENARIO")
        if fact.metric_id == "biopharma_financing_issue_price"
        else fact
        for fact in subject.base_forecast_request.data_snapshot.facts
    )
    result = ScenarioValuationEngine().run(
        replace(
            subject,
            base_forecast_request=replace(
                subject.base_forecast_request,
                data_snapshot=replace(
                    subject.base_forecast_request.data_snapshot,
                    facts=facts,
                    content_hash="",
                ),
            ),
        )
    )

    for scenario_result in result.scenarios:
        method = scenario_result.method("pipeline_rnpv")
        assert method.status == "blocked"
        assert (
            "BIOPHARMA_FINANCING_EVIDENCE_INVALID"
            in method.diagnostics[0]
        )


def test_biopharma_probability_fact_cannot_predate_calibration_window() -> None:
    subject = biopharma_request()
    calibration_id = (
        subject.valuation_plan.biopharma.events[0]
        .calibration_record_id
    )
    facts = tuple(
        replace(fact, available_at="2010-01-01")
        if fact.source_id == calibration_id
        else fact
        for fact in subject.base_forecast_request.data_snapshot.facts
    )
    result = ScenarioValuationEngine().run(
        replace(
            subject,
            base_forecast_request=replace(
                subject.base_forecast_request,
                data_snapshot=replace(
                    subject.base_forecast_request.data_snapshot,
                    facts=facts,
                    content_hash="",
                ),
            ),
        )
    )

    for scenario_result in result.scenarios:
        method = scenario_result.method("pipeline_rnpv")
        assert method.status == "blocked"
        assert (
            "BIOPHARMA_PROBABILITY_EVIDENCE_INVALID"
            in method.diagnostics[0]
        )


def test_biopharma_common_equity_bridge_subtracts_preferred_claims() -> None:
    subject = biopharma_request()
    baseline = ScenarioValuationEngine().run(subject)
    baseline_base = next(
        item
        for item in baseline.scenarios
        if item.role == ScenarioRole.BASE
    ).method("pipeline_rnpv")
    bridge = subject.valuation_plan.present_value_bridge
    preferred = replace(
        bridge.preferred_stock,
        value=Decimal("100"),
    )
    facts = tuple(
        replace(fact, value=Decimal("100"))
        if fact.fact_id
        == preferred.provenance_refs[0].removeprefix("Fact:")
        else fact
        for fact in subject.base_forecast_request.data_snapshot.facts
    )
    result = ScenarioValuationEngine().run(
        replace(
            subject,
            base_forecast_request=replace(
                subject.base_forecast_request,
                data_snapshot=replace(
                    subject.base_forecast_request.data_snapshot,
                    facts=facts,
                    content_hash="",
                ),
            ),
            valuation_plan=replace(
                subject.valuation_plan,
                present_value_bridge=replace(
                    bridge,
                    preferred_stock=preferred,
                ),
            ),
        )
    )
    result_base = next(
        item
        for item in result.scenarios
        if item.role == ScenarioRole.BASE
    ).method("pipeline_rnpv")

    assert result_base.status == "ready"
    assert (
        baseline_base.conditional_value_range.equity_value_base
        - result_base.conditional_value_range.equity_value_base
        == Decimal("100")
    )


def test_biopharma_delay_trace_retimes_all_cash_flows_with_act365() -> None:
    spec = biopharma_spec()
    asset = spec.assets[0]
    delayed_asset = replace(
        asset,
        launch_delay_years_low=replace(
            asset.launch_delay_years_low,
            value=Decimal("1"),
        ),
        launch_delay_years_base=replace(
            asset.launch_delay_years_base,
            value=Decimal("1"),
        ),
        launch_delay_years_high=replace(
            asset.launch_delay_years_high,
            value=Decimal("1"),
        ),
    )
    result = ScenarioValuationEngine().run(
        biopharma_request(
            spec=replace(
                spec,
                assets=(delayed_asset, *spec.assets[1:]),
            )
        )
    )
    method = next(
        item
        for item in result.scenarios
        if item.role == ScenarioRole.BASE
    ).method("pipeline_rnpv")
    selected = next(
        json.loads(item)
        for item in method.component_trace
        if json.loads(item)["kind"]
        == "biopharma_selected_projection"
    )
    shifted = [
        item
        for item in selected["asset_cash_flows"]
        if item["asset_key"] == "asset_a:indication_alpha"
        and item["source_period"] == "2027E"
    ]
    expected_timing = Decimal(
        (
            date(2028, 12, 31) - date.fromisoformat(AS_OF)
        ).days
    ) / Decimal("365")

    assert {
        item["cash_flow_type"] for item in shifted
    } == {
        "commercial_cash",
        "development_cost",
        "milestone_cash",
    }
    assert all(item["shifted_period"] == "2028E" for item in shifted)
    assert all(
        abs(
            Decimal(item["timing_act365"]) - expected_timing
        )
        < Decimal("1e-25")
        for item in shifted
    )


def test_biopharma_delay_obligation_beyond_runway_fails_closed() -> None:
    spec = biopharma_spec()
    asset = spec.assets[0]
    final_period = replace(
        asset.periods[-1],
        gross_sales_low=replace(
            asset.periods[-1].gross_sales_low,
            value=Decimal("0"),
        ),
        gross_sales_base=replace(
            asset.periods[-1].gross_sales_base,
            value=Decimal("0"),
        ),
        gross_sales_high=replace(
            asset.periods[-1].gross_sales_high,
            value=Decimal("0"),
        ),
        development_cost_low=replace(
            asset.periods[-1].development_cost_low,
            value=Decimal("800"),
        ),
        development_cost_base=replace(
            asset.periods[-1].development_cost_base,
            value=Decimal("900"),
        ),
        development_cost_high=replace(
            asset.periods[-1].development_cost_high,
            value=Decimal("1000"),
        ),
    )
    delayed = replace(
        asset,
        launch_delay_years_low=replace(
            asset.launch_delay_years_low,
            value=Decimal("1"),
        ),
        launch_delay_years_base=replace(
            asset.launch_delay_years_base,
            value=Decimal("1"),
        ),
        launch_delay_years_high=replace(
            asset.launch_delay_years_high,
            value=Decimal("1"),
        ),
        periods=(*asset.periods[:-1], final_period),
    )
    result = ScenarioValuationEngine().run(
        biopharma_request(
            spec=replace(
                spec,
                assets=(delayed, *spec.assets[1:]),
            )
        )
    )

    for scenario_result in result.scenarios:
        method = scenario_result.method("pipeline_rnpv")
        assert method.status == "blocked"
        assert (
            "BIOPHARMA_RUNWAY_COVERAGE_INSUFFICIENT"
            in method.diagnostics[0]
        )
        assert "2031E" in method.diagnostics[0]


def test_biopharma_financing_tranche_identity_is_unique() -> None:
    spec = biopharma_spec()
    original = spec.runway_periods[2].financing
    assert original is not None
    duplicate = replace(
        original,
        period="2029E",
        proceeds=replace(original.proceeds, period="2029E"),
        issue_price=replace(original.issue_price, period="2029E"),
        new_shares=replace(original.new_shares, period="2029E"),
    )
    runway = replace(
        spec.runway_periods[3],
        financing=duplicate,
    )

    with pytest.raises(ScenarioInvariantError) as error:
        replace(
            spec,
            runway_periods=(
                *spec.runway_periods[:3],
                runway,
                *spec.runway_periods[4:],
            ),
        )
    assert error.value.code == "BIOPHARMA_FINANCING_RECORD_DUPLICATE"


def test_biopharma_duplicate_economic_right_fails_closed() -> None:
    spec = biopharma_spec()
    duplicate = replace(
        spec.assets[1],
        economic_right_id=spec.assets[0].economic_right_id,
    )
    with pytest.raises(ScenarioInvariantError) as error:
        replace(spec, assets=(spec.assets[0], duplicate))
    assert error.value.code == "BIOPHARMA_ECONOMIC_RIGHT_DUPLICATE"


def test_formal_ranges_preserve_dimensions_period_as_of_and_method_lineage() -> None:
    result = ScenarioValuationEngine().run(scenario_request())
    methods = {item.method_id: item for item in result.scenarios[1].methods}

    dcf = methods["fcff_dcf"].conditional_value_range.base
    assert dcf.basis_value.currency == "CNY"
    assert dcf.basis_value.period == AS_OF
    assert dcf.per_share_value.unit == "CNY/share"
    assert dcf.per_share_value.as_of == AS_OF
    assert "Assumption:dcf_risk_free_rate" in dcf.basis_value.provenance_refs
    assert "Assumption:dcf_terminal_growth" in dcf.basis_value.provenance_refs

    sotp = methods["sotp"].conditional_value_range.base
    assert sotp.basis_value.period == TERMINAL_PERIOD
    assert "Assumption:components_multiple" in sotp.basis_value.provenance_refs

    peer = methods["peer_comps"].conditional_value_range.base
    assert peer.basis_value.period == TERMINAL_PERIOD
    assert any(ref.startswith("Fact:peer_comps:") for ref in peer.basis_value.provenance_refs)
    assert "Fact:components:volume" in peer.basis_value.provenance_refs


def test_probability_weighting_is_method_specific_exact_and_dimensioned() -> None:
    result = ScenarioValuationEngine().run(scenario_request(probabilities=True))

    assert result.probability_mode == "evidence_weighted"
    weighted = {item.method_id: item for item in result.weighted_method_ranges}
    assert {"fcff_dcf", "sotp", "reverse_dcf", "peer_comps"} <= set(weighted)
    assert "historical_band" not in weighted
    assert all(item.probability_sum == Decimal("1") for item in weighted.values())
    assert all(item.per_share_base_quantity.unit == "CNY/share" for item in weighted.values())
    assert result.cross_method_composite is None


def test_scenario_probabilities_require_resolved_evidence_and_exact_sum() -> None:
    subject = scenario_request(probabilities=True)
    mixed = replace(
        subject,
        scenarios=(
            subject.scenarios[0],
            replace(subject.scenarios[1], probability_evidence=None),
            subject.scenarios[2],
        ),
    )
    with pytest.raises(ScenarioInvariantError) as mixed_error:
        ScenarioValuationEngine().run(mixed)
    assert mixed_error.value.code == "SCENARIO_PROBABILITY_INCOMPLETE"

    bad_total = replace(
        subject,
        scenarios=(
            subject.scenarios[0],
            subject.scenarios[1],
            replace(
                subject.scenarios[2],
                probability_evidence=probability_evidence(
                    ScenarioRole.IMPROVEMENT, Decimal("0.31")
                ),
            ),
        ),
    )
    with pytest.raises(ScenarioInvariantError) as total_error:
        ScenarioValuationEngine().run(bad_total)
    assert total_error.value.code == "SCENARIO_PROBABILITY_EVIDENCE_INVALID"

    unresolved = replace(
        subject.scenarios[0].probability_evidence,
        probability=replace(
            subject.scenarios[0].probability_evidence.probability,
            lineage_refs=(
                "Assumption:calibration:scenario_probability:stress",
                "Fact:not_in_snapshot",
                "Fact:scenario_calibration:sample_size",
            ),
        ),
        observed_count_fact_ref="Fact:not_in_snapshot",
        basis_fact_refs=(
            "Fact:not_in_snapshot",
            "Fact:scenario_calibration:sample_size",
        ),
    )
    with pytest.raises(ScenarioInvariantError) as evidence_error:
        ScenarioValuationEngine().run(
            replace(
                subject,
                scenarios=(
                    replace(subject.scenarios[0], probability_evidence=unresolved),
                    subject.scenarios[1],
                    subject.scenarios[2],
                ),
            )
        )
    assert evidence_error.value.code == "SCENARIO_PROBABILITY_EVIDENCE_INVALID"


def test_probability_sum_is_independent_of_ambient_decimal_precision() -> None:
    subject = scenario_request(probabilities=True)
    probabilities = (Decimal("0.333"), Decimal("0.333"), Decimal("0.335"))
    scenarios = tuple(
        replace(
            item,
            probability_evidence=probability_evidence(item.role, probability),
        )
        for item, probability in zip(subject.scenarios, probabilities, strict=True)
    )

    with localcontext(Context(prec=3)):
        with pytest.raises(ScenarioInvariantError) as error:
            ScenarioValuationEngine().run(replace(subject, scenarios=scenarios))
    assert error.value.code == "SCENARIO_PROBABILITY_EVIDENCE_INVALID"


def test_scenario_requires_full_typed_driver_partition() -> None:
    subject = scenario_request()
    incomplete = replace(
        subject.scenarios[0],
        driver_overrides=subject.scenarios[0].driver_overrides[:-1],
    )

    with pytest.raises(ScenarioInvariantError) as error:
        ScenarioValuationEngine().run(
            replace(subject, scenarios=(incomplete,) + subject.scenarios[1:])
        )

    assert error.value.code == "SCENARIO_DRIVER_COVERAGE_INVALID"


def test_relative_methods_can_only_be_built_from_existing_gated_results() -> None:
    with pytest.raises(TypeError):
        RelativeMultipleSpec(
            method_id="peer_comps",
            status="ready",
            metric="ebit",
            value_basis="enterprise_value",
            multiple_low=Decimal("8"),
            multiple_base=Decimal("9"),
            multiple_high=Decimal("10"),
            evidence_refs=("Fact:made_up",),
        )

    forged = method_result("peer_comps")
    bad = replace(
        forged,
        assumptions={**forged.assumptions, "currency_checked": False},
    )
    with pytest.raises(ScenarioInvariantError) as error:
        industrial_family().bind_relative_multiple(
            bad, subject_id="002897.SZ", as_of=AS_OF
        )
    assert error.value.code == "RELATIVE_GATE_INVALID"


def test_dcf_inputs_must_replay_the_existing_gate_and_sensitivity_policy() -> None:
    forged = MethodResult(
        method_id="dcf",
        label="DCF",
        status="ready",
        role="intrinsic_valuation",
        explanation="Caller says this passed.",
        evidence_ids=("made_up",),
    )
    with pytest.raises(ScenarioInvariantError) as missing_exact:
        industrial_family().bind_dcf_applicability(
            forged,
            subject_id="002897.SZ",
            as_of=AS_OF,
        )
    assert missing_exact.value.code == "DCF_GATE_INVALID"

    declared_only = dcf_gate_result()
    disconnected_metrics = deepcopy(declared_only.metrics)
    disconnected_metrics["exact_calculation"]["dimensioned_inputs"][
        "wacc_components"
    ]["risk_free_rate"]["value"] = "0.99"
    with pytest.raises(ScenarioInvariantError) as forged_components:
        industrial_family().bind_dcf_applicability(
            replace(declared_only, metrics=disconnected_metrics),
            subject_id="002897.SZ",
            as_of=AS_OF,
        )
    assert forged_components.value.code == "DCF_GATE_INVALID"

    plan = valuation_plan()
    wrong_horizon_metrics = deepcopy(declared_only.metrics)
    wrong_horizon_metrics["exact_calculation"]["dimensioned_inputs"][
        "terminal_growth"
    ]["period"] = "2099E"
    wrong_horizon_gate = industrial_family().bind_dcf_applicability(
        replace(declared_only, metrics=wrong_horizon_metrics),
        subject_id="002897.SZ",
        as_of=AS_OF,
    )
    with pytest.raises(ScenarioInvariantError) as wrong_horizon:
        replace(plan.dcf, applicability=wrong_horizon_gate)
    assert wrong_horizon.value.code == "DCF_GATE_BINDING_INVALID"

    with pytest.raises(ScenarioInvariantError) as disconnected:
        replace(
            plan.dcf,
            discount_rate_base=replace(
                plan.dcf.discount_rate_base,
                value=Decimal("0.101"),
            ),
        )
    assert disconnected.value.code == "DCF_GATE_BINDING_INVALID"


def test_gated_historical_band_can_revalue_the_terminal_forecast() -> None:
    subject = scenario_request()
    plan = replace(
        subject.valuation_plan,
        relative_methods=(
            relative_spec("peer_comps"),
            relative_spec("historical_band"),
        ),
    )

    result = ScenarioValuationEngine().run(
        replace(subject, valuation_plan=plan)
    )

    for item in result.scenarios:
        historical = item.method("historical_band")
        assert historical.status == "ready"
        assert historical.value_basis == "equity_value"
        assert historical.conditional_value_range.base.basis_value.period == TERMINAL_PERIOD


def test_dcf_gate_blocks_only_dcf() -> None:
    subject = scenario_request()
    blocked_plan = valuation_plan(dcf_status="disabled")
    result = ScenarioValuationEngine().run(
        replace(subject, valuation_plan=blocked_plan)
    )

    for item in result.scenarios:
        assert item.method("fcff_dcf").status == "blocked"
        assert item.method("sotp").status == "ready"
        assert item.method("peer_comps").status == "ready"


def test_blocked_sotp_preserves_component_assumption_lineage() -> None:
    subject = scenario_request()
    components = subject.valuation_plan.sotp.components
    mismatched = replace(
        components[0],
        multiple_low=replace(components[0].multiple_low, as_of="2026-07-08"),
        multiple_base=replace(components[0].multiple_base, as_of="2026-07-08"),
        multiple_high=replace(components[0].multiple_high, as_of="2026-07-08"),
    )
    plan = replace(
        subject.valuation_plan,
        sotp=replace(
            subject.valuation_plan.sotp,
            components=(mismatched, components[1]),
        ),
    )

    result = ScenarioValuationEngine().run(
        replace(subject, valuation_plan=plan)
    )

    for item in result.scenarios:
        sotp = item.method("sotp")
        assert sotp.status == "blocked"
        assert "Assumption:components_multiple" in sotp.lineage_refs
        assert item.method("fcff_dcf").status == "ready"


def test_unresolved_bridge_fact_cannot_unlock_per_share_values() -> None:
    subject = scenario_request()
    bridge = subject.valuation_plan.present_value_bridge
    plan = replace(
        subject.valuation_plan,
        present_value_bridge=replace(
            bridge,
            diluted_shares=replace(
                bridge.diluted_shares,
                provenance_refs=("Fact:not_in_snapshot_or_gate",),
            ),
        ),
    )

    result = ScenarioValuationEngine().run(
        replace(subject, valuation_plan=plan)
    )
    for item in result.scenarios:
        assert item.method("fcff_dcf").status == "blocked"
        assert item.method("reverse_dcf").status == "blocked"
        assert item.method("sotp").status == "ready"
        assert item.method("peer_comps").status == "ready"
        assert "VALUATION_BRIDGE_EVIDENCE_INVALID" in item.method(
            "fcff_dcf"
        ).diagnostics[0]
        assert "Fact:not_in_snapshot_or_gate" in item.method(
            "fcff_dcf"
        ).lineage_refs
        assert "Fact:not_in_snapshot_or_gate" in item.method(
            "reverse_dcf"
        ).lineage_refs


def test_terminal_bridge_failure_blocks_only_terminal_value_methods() -> None:
    subject = scenario_request()
    bridge = subject.valuation_plan.terminal_value_bridge
    plan = replace(
        subject.valuation_plan,
        terminal_value_bridge=replace(
            bridge,
            diluted_shares=replace(
                bridge.diluted_shares,
                value=Decimal("101"),
            ),
        ),
    )

    result = ScenarioValuationEngine().run(
        replace(subject, valuation_plan=plan)
    )

    for item in result.scenarios:
        assert item.method("sotp").status == "blocked"
        assert item.method("peer_comps").status == "blocked"
        assert item.method("fcff_dcf").status == "ready"
        assert item.method("reverse_dcf").status == "ready"


def test_scaled_forecast_money_is_normalized_before_equity_bridge() -> None:
    subject = scenario_request()
    baseline = ScenarioValuationEngine().run(subject)
    opening = subject.base_forecast_request.data_snapshot.company_opening_balance_sheet
    scaled_cash = replace(
        opening.cash,
        value=opening.cash.normalized_value / Decimal("1000000"),
        unit=opening.cash.unit,
        scale=Decimal("1000000"),
    )
    scaled_snapshot = replace(
        subject.base_forecast_request.data_snapshot,
        company_opening_balance_sheet=replace(opening, cash=scaled_cash),
        content_hash="",
    )
    scaled = ScenarioValuationEngine().run(
        replace(
            subject,
            base_forecast_request=replace(
                subject.base_forecast_request,
                data_snapshot=scaled_snapshot,
            ),
        )
    )

    assert (
        scaled.scenarios[1].method("fcff_dcf").conditional_value_range.per_share_base
        == baseline.scenarios[1]
        .method("fcff_dcf")
        .conditional_value_range.per_share_base
    )


def test_dcf_uses_actual_period_distance() -> None:
    annual = ScenarioValuationEngine().run(scenario_request())
    annual_value = annual.scenarios[1].method(
        "fcff_dcf"
    ).conditional_value_range.per_share_base

    subject = scenario_request()
    gapped_periods = ("2026E", "2027E", "2028E", "2029E", "2034E")
    scenarios = tuple(
        replace(
            item,
            driver_overrides=tuple(
                replace(
                    override,
                    period="2034E" if override.period == TERMINAL_PERIOD else override.period,
                )
                for override in item.driver_overrides
            ),
        )
        for item in subject.scenarios
    )
    terminal_bridge = replace(
        subject.valuation_plan.terminal_value_bridge,
        diluted_shares=replace(
            subject.valuation_plan.terminal_value_bridge.diluted_shares,
            period="2034E",
        ),
        lease_debt=replace(subject.valuation_plan.terminal_value_bridge.lease_debt, period="2034E"),
        preferred_stock=replace(subject.valuation_plan.terminal_value_bridge.preferred_stock, period="2034E"),
        minority_interest=replace(subject.valuation_plan.terminal_value_bridge.minority_interest, period="2034E"),
        pension_deficit=replace(subject.valuation_plan.terminal_value_bridge.pension_deficit, period="2034E"),
        associates_jv_value=replace(subject.valuation_plan.terminal_value_bridge.associates_jv_value, period="2034E"),
        non_operating_assets=replace(subject.valuation_plan.terminal_value_bridge.non_operating_assets, period="2034E"),
    )
    gapped_gate_result = dcf_gate_result()
    gapped_gate_metrics = deepcopy(gapped_gate_result.metrics)
    gapped_gate_metrics["exact_calculation"]["dimensioned_inputs"][
        "terminal_growth"
    ]["period"] = "2034E"
    gapped_applicability = industrial_family().bind_dcf_applicability(
        replace(gapped_gate_result, metrics=gapped_gate_metrics),
        subject_id="002897.SZ",
        as_of=AS_OF,
    )
    plan = replace(
        subject.valuation_plan,
        terminal_value_bridge=terminal_bridge,
        dcf=replace(
            subject.valuation_plan.dcf,
            applicability=gapped_applicability,
            terminal_growth_low=replace(subject.valuation_plan.dcf.terminal_growth_low, period="2034E"),
            terminal_growth_base=replace(subject.valuation_plan.dcf.terminal_growth_base, period="2034E"),
            terminal_growth_high=replace(subject.valuation_plan.dcf.terminal_growth_high, period="2034E"),
        ),
        sotp=replace(
            subject.valuation_plan.sotp,
            components=tuple(
                replace(
                    component,
                    multiple_low=replace(component.multiple_low, period="2034E"),
                    multiple_base=replace(component.multiple_base, period="2034E"),
                    multiple_high=replace(component.multiple_high, period="2034E"),
                )
                for component in subject.valuation_plan.sotp.components
            ),
        ),
    )
    base = subject.base_forecast_request
    gapped = replace(
        subject,
        base_forecast_request=replace(base, forecast_periods=gapped_periods),
        scenarios=scenarios,
        valuation_plan=plan,
    )
    gapped_value = ScenarioValuationEngine().run(gapped).scenarios[1].method(
        "fcff_dcf"
    ).conditional_value_range.per_share_base

    assert gapped_value < annual_value


def test_dcf_timing_is_anchored_to_frozen_as_of_under_act_365() -> None:
    basis = ValuationBasis()
    times = basis.discount_times(FORECAST_PERIODS, AS_OF)

    expected_first = Decimal(
        (date(2026, 12, 31) - date.fromisoformat(AS_OF)).days
    ) / Decimal("365")
    assert times[0] == expected_first
    assert times[0] < Decimal("1")
    quarter_times = basis.discount_times(("2026Q2", "2026Q3"), "2026-01-01")
    assert quarter_times[0] == Decimal(
        (date(2026, 6, 30) - date(2026, 1, 1)).days
    ) / Decimal("365")
    iso_times = basis.discount_times(
        ("2026-06-30", "2026-12-31"),
        "2026-01-01",
    )
    assert iso_times == (
        quarter_times[0],
        Decimal((date(2026, 12, 31) - date(2026, 1, 1)).days) / Decimal("365"),
    )


def test_present_value_methods_use_opening_bridge_and_terminal_methods_use_forecast_bridge() -> None:
    result = ScenarioValuationEngine().run(scenario_request())
    stress, _, improvement = result.scenarios

    stress_reverse = stress.method("reverse_dcf").conditional_value_range.per_share_base
    improvement_reverse = improvement.method(
        "reverse_dcf"
    ).conditional_value_range.per_share_base
    assert stress_reverse == improvement_reverse

    dcf = stress.method("fcff_dcf")
    sotp = stress.method("sotp")
    assert dcf.horizon.startswith(f"valuation_as_of={AS_OF}")
    assert sotp.horizon == f"terminal_period={TERMINAL_PERIOD}"
    assert dcf.conditional_value_range.base.basis_value.period == AS_OF
    assert sotp.conditional_value_range.base.basis_value.period == TERMINAL_PERIOD


def test_reverse_dcf_future_known_rate_blocks_only_reverse_method() -> None:
    subject = scenario_request()
    plan = replace(
        subject.valuation_plan,
        reverse_dcf=replace(
            subject.valuation_plan.reverse_dcf,
            discount_rate=replace(
                subject.valuation_plan.reverse_dcf.discount_rate,
                period="2027-01-01",
                as_of="2027-01-01",
            ),
        ),
    )

    result = ScenarioValuationEngine().run(
        replace(subject, valuation_plan=plan)
    )

    for item in result.scenarios:
        assert item.method("reverse_dcf").status == "blocked"
        assert item.method("fcff_dcf").status == "ready"


def test_reverse_dcf_failure_does_not_disable_other_methods() -> None:
    subject = scenario_request()
    plan = replace(
        subject.valuation_plan,
        reverse_dcf=replace(
            subject.valuation_plan.reverse_dcf,
            current_enterprise_value=money(
                "1",
                "impossible_enterprise_value",
                period=AS_OF,
                provenance_refs=("Fact:observed_enterprise_value",),
            ),
        ),
    )

    result = ScenarioValuationEngine().run(replace(subject, valuation_plan=plan))

    for item in result.scenarios:
        assert item.method("reverse_dcf").status == "blocked"
        assert item.method("fcff_dcf").status == "ready"
        assert item.method("sotp").status == "ready"
