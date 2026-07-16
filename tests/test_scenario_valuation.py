from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Context, Decimal, localcontext

import pytest

from equity_research import (
    DcfApplicability,
    DcfValuationSpec,
    DeterministicScenarioRequest,
    EquityBridgeSpec,
    EquityBridgeTiming,
    FinancialQuantity,
    ForecastQuantity,
    MethodResult,
    RelativeMultipleSpec,
    ReverseDcfSpec,
    ScenarioDefinition,
    ScenarioInvariantError,
    ScenarioProbabilityEvidence,
    ScenarioRole,
    ScenarioValuationEngine,
    SegmentForecastOverride,
    SnapshotFact,
    SotpComponentSpec,
    SotpValuationSpec,
    ValuationPlan,
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
    return DcfApplicability.from_gated_method_result(
        dcf_gate_result(status),
        subject_id="002897.SZ",
        as_of=AS_OF,
    )


def relative_spec(method_id: str, *, status: str = "ready") -> RelativeMultipleSpec:
    return RelativeMultipleSpec.from_gated_method_result(
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
        RelativeMultipleSpec.from_gated_method_result(
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
        DcfApplicability.from_gated_method_result(
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
        DcfApplicability.from_gated_method_result(
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
    wrong_horizon_gate = DcfApplicability.from_gated_method_result(
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
    quantity = ForecastQuantity(
        value=Decimal("2"),
        unit="CNY million",
        scale=Decimal("1000000"),
        currency="CNY",
        period=OPENING_PERIOD,
        as_of=AS_OF,
        lineage_refs=("Fact:scaled_cash",),
    )

    normalized = ScenarioValuationEngine()._financial_from_forecast(quantity)

    assert normalized.value == Decimal("2000000")
    assert normalized.unit == "CNY"
    assert normalized.scale == Decimal("1")

    opening = bridge_spec(EquityBridgeTiming.OPENING)
    compatible_scaled_adjustment = replace(
        opening,
        lease_debt=FinancialQuantity(
            value=Decimal("2"),
            unit="CNY million",
            scale=Decimal("1000000"),
            currency="CNY",
            period=OPENING_PERIOD,
            as_of=AS_OF,
            provenance_refs=("Fact:lease_debt",),
            kind="money",
        ),
    )
    assert compatible_scaled_adjustment.lease_debt.normalized_value == Decimal(
        "2000000"
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
    gapped_applicability = DcfApplicability.from_gated_method_result(
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
    times = ScenarioValuationEngine()._discount_times(FORECAST_PERIODS, AS_OF)

    expected_first = Decimal((date(2026, 12, 31) - date.fromisoformat(AS_OF)).days) / Decimal("365")
    assert times[0] == expected_first
    assert times[0] < Decimal("1")
    quarter_times = ScenarioValuationEngine()._discount_times(
        ("2026Q2", "2026Q3"),
        "2026-01-01",
    )
    assert quarter_times[0] == Decimal(
        (date(2026, 6, 30) - date(2026, 1, 1)).days
    ) / Decimal("365")
    iso_times = ScenarioValuationEngine()._discount_times(
        ("2026-06-30", "2026-12-31"),
        "2026-01-01",
    )
    assert iso_times == (
        quarter_times[0],
        Decimal((date(2026, 12, 31) - date(2026, 1, 1)).days)
        / Decimal("365"),
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
