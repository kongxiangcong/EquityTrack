from __future__ import annotations

from dataclasses import replace

from datetime import date
from decimal import Decimal

from ..financial import FinancialQuantity, valuation_decimal_context
from ..forecast import (
    CompanyArchetype,
    ForecastEngine,
    SegmentForecastOverride,
)
from .contracts import (
    DeterministicScenarioRequest,
    DeterministicScenarioResult,
    ProbabilityMode,
    ScenarioDefinition,
    ScenarioInvariantError,
    ScenarioRole,
    ScenarioValuationResult,
    WeightedMethodRange,
    merge_refs,
)
from .basis import ValuationBasis
from .industrial import IndustrialValuation
from .cyclical import CyclicalValuation
from .financial_institution import FinancialInstitutionValuation
from .biopharma import BiopharmaValuation


class ScenarioValuationEngine:
    """Value one coherent scenario partition through complete method families."""

    def __init__(self) -> None:
        self._basis = ValuationBasis()
        self._industrial = IndustrialValuation(self._basis)
        self._cyclical = CyclicalValuation(self._basis)
        self._financial = FinancialInstitutionValuation(self._basis)
        self._biopharma = BiopharmaValuation(self._basis)

    def run(self, request: DeterministicScenarioRequest) -> DeterministicScenarioResult:
        with valuation_decimal_context():
            self._validate_scenarios(request)
            probability_mode = self._probability_mode(request.scenarios)
            archetype = request.base_forecast_request.security.archetype
            reference_graph = (
                ForecastEngine().build(request.base_forecast_request)
                if archetype
                in {
                    CompanyArchetype.CYCLICAL_MANUFACTURING,
                    CompanyArchetype.CYCLICAL_RESOURCE,
                }
                else None
            )
            results: list[ScenarioValuationResult] = []
            for scenario in request.scenarios:
                graph = ForecastEngine().build(
                    replace(
                        request.base_forecast_request,
                        assumption_overrides=scenario.driver_overrides,
                    )
                )
                context = self._basis.bind(
                    graph,
                    request.base_forecast_request,
                    reference_graph=reference_graph,
                )
                methods = list(
                    self._industrial.evaluate(context, request.valuation_plan)
                )
                if archetype in {
                    CompanyArchetype.CYCLICAL_MANUFACTURING,
                    CompanyArchetype.CYCLICAL_RESOURCE,
                }:
                    methods.extend(
                        self._cyclical.evaluate(context, request.valuation_plan)
                    )
                elif archetype == CompanyArchetype.FINANCIAL_INSTITUTION:
                    methods.extend(
                        self._financial.evaluate(
                            context, request.valuation_plan, scenario.role
                        )
                    )
                elif archetype == CompanyArchetype.BIOPHARMA:
                    methods.extend(
                        self._biopharma.evaluate(
                            context, request.valuation_plan, scenario.role
                        )
                    )
                results.append(
                    ScenarioValuationResult(
                        scenario_id=scenario.scenario_id,
                        role=scenario.role,
                        label=scenario.label,
                        probability_evidence=scenario.probability_evidence,
                        rationale_refs=scenario.rationale_refs,
                        forecast_graph=graph,
                        methods=tuple(methods),
                    )
                )
            scenario_results = tuple(results)
            self._validate_method_order(scenario_results)
            weighted = ()
            diagnostics: tuple[str, ...] = ()
            if probability_mode == "evidence_weighted":
                weighted, diagnostics = self._weight_methods(scenario_results)
            return DeterministicScenarioResult(
                probability_mode=probability_mode,
                scenarios=scenario_results,
                weighted_method_ranges=weighted,
                weighting_diagnostics=diagnostics,
            )

    def _validate_method_order(
        self, scenarios: tuple[ScenarioValuationResult, ...]
    ) -> None:
        method_orders = [
            tuple(method.method_id for method in scenario.methods)
            for scenario in scenarios
        ]
        if method_orders and any(
            method_order != method_orders[0] for method_order in method_orders[1:]
        ):
            raise ScenarioInvariantError(
                "SCENARIO_METHOD_PARTITION_INVALID",
                "Every scenario must expose the same method ids in the same order.",
            )

    def _validate_scenarios(self, request: DeterministicScenarioRequest) -> None:
        expected_roles = set(ScenarioRole)
        roles = [item.role for item in request.scenarios]
        if len(roles) != len(expected_roles) or set(roles) != expected_roles:
            raise ScenarioInvariantError(
                "SCENARIO_PARTITION_INVALID",
                "The deterministic partition requires exactly stress, base, and improvement.",
            )
        scenario_ids = [item.scenario_id for item in request.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ScenarioInvariantError(
                "SCENARIO_ID_DUPLICATE",
                "Scenario identifiers must be unique.",
            )
        groups = {item.mutually_exclusive_group for item in request.scenarios}
        bases = {item.partition_basis for item in request.scenarios}
        if len(groups) != 1 or len(bases) != 1:
            raise ScenarioInvariantError(
                "SCENARIO_PARTITION_INVALID",
                "Scenarios must document one mutually exclusive partition.",
            )
        base = request.base_forecast_request
        expected_keys = {
            (segment_id, period)
            for segment_id in base.security.segment_ids
            for period in base.forecast_periods
        }
        for scenario in request.scenarios:
            actual_keys = [
                (item.segment_id, item.period) for item in scenario.driver_overrides
            ]
            if (
                len(actual_keys) != len(set(actual_keys))
                or set(actual_keys) != expected_keys
            ):
                raise ScenarioInvariantError(
                    "SCENARIO_DRIVER_COVERAGE_INVALID",
                    f"Scenario {scenario.scenario_id} must override every segment-period exactly once.",
                )
            if any(
                getattr(override, field_name) is None
                for override in scenario.driver_overrides
                for field_name in SegmentForecastOverride.field_names()
            ):
                raise ScenarioInvariantError(
                    "SCENARIO_DRIVER_COVERAGE_INVALID",
                    f"Scenario {scenario.scenario_id} must specify every typed driver.",
                )
            evidence = scenario.probability_evidence
            if evidence is not None and (
                evidence.subject_id != base.security.security_id
                or evidence.scenario_id != scenario.scenario_id
                or evidence.mutually_exclusive_group
                != scenario.mutually_exclusive_group
                or evidence.probability.period != base.forecast_periods[-1]
                or evidence.probability.as_of != base.as_of
            ):
                raise ScenarioInvariantError(
                    "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                    "Probability evidence must bind the scenario, subject, partition, horizon, and as-of.",
                )
        self._validate_probability_evidence(request)

    def _validate_probability_evidence(
        self, request: DeterministicScenarioRequest
    ) -> None:
        present = tuple(
            scenario.probability_evidence is not None for scenario in request.scenarios
        )
        if any(present) and not all(present):
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_INCOMPLETE",
                "Scenario probabilities must be all evidence-backed or all absent.",
            )
        evidences = tuple(
            scenario.probability_evidence
            for scenario in request.scenarios
            if scenario.probability_evidence is not None
        )
        if not evidences:
            return
        facts = {
            fact.fact_id: fact
            for fact in request.base_forecast_request.data_snapshot.facts
        }
        calibration_bases = {
            (
                item.schema_version,
                item.formula_version,
                item.calibration_window_start,
                item.calibration_window_end,
                item.calibration_sample_size,
                item.prior_total_count,
                item.sample_size_fact_ref,
            )
            for item in evidences
        }
        if len(calibration_bases) != 1:
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                "Every scenario probability must share one calibration window, sample, formula, and prior partition.",
            )
        base = request.base_forecast_request
        expected_period = (
            f"{evidences[0].calibration_window_start}/"
            f"{evidences[0].calibration_window_end}"
        )
        for evidence in evidences:
            observed = facts.get(evidence.observed_count_fact_ref.removeprefix("Fact:"))
            sample = facts.get(evidence.sample_size_fact_ref.removeprefix("Fact:"))
            if not (
                observed is not None
                and observed.subject_id == base.security.security_id
                and observed.scope == "company"
                and observed.metric_id == "scenario_observed_count"
                and observed.field_name == evidence.scenario_id
                and observed.value == Decimal(evidence.observed_count)
                and observed.unit == "count"
                and observed.currency == "N/A"
                and observed.period == expected_period
                and date.fromisoformat(observed.available_at)
                <= date.fromisoformat(base.as_of)
            ):
                raise ScenarioInvariantError(
                    "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                    f"Observed count does not bind a PIT calibration fact for {evidence.scenario_id}.",
                )
            if not (
                sample is not None
                and sample.subject_id == base.security.security_id
                and sample.scope == "company"
                and sample.metric_id == "scenario_calibration_sample_size"
                and sample.value == Decimal(evidence.calibration_sample_size)
                and sample.unit == "count"
                and sample.currency == "N/A"
                and sample.period == expected_period
                and date.fromisoformat(sample.available_at)
                <= date.fromisoformat(base.as_of)
            ):
                raise ScenarioInvariantError(
                    "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                    "Calibration sample size does not bind one shared PIT fact.",
                )
        if (
            sum((item.observed_count for item in evidences), 0)
            != evidences[0].calibration_sample_size
            or sum((item.prior_count for item in evidences), Decimal("0"))
            != evidences[0].prior_total_count
        ):
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                "Observed counts and priors must form one exhaustive calibration partition.",
            )

    def _probability_mode(
        self, scenarios: tuple[ScenarioDefinition, ...]
    ) -> ProbabilityMode:
        present = tuple(item.probability_evidence is not None for item in scenarios)
        if any(present) and not all(present):
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_INCOMPLETE",
                "Scenario probabilities must be all evidence-backed or all absent.",
            )
        if not any(present):
            return "conditional_only"
        total = sum(
            (item.probability for item in scenarios if item.probability is not None),
            Decimal("0"),
        )
        if total != Decimal("1"):
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_SUM_INVALID",
                "Scenario probabilities must sum exactly to one.",
            )
        return "evidence_weighted"

    def _weight_methods(
        self, scenarios: tuple[ScenarioValuationResult, ...]
    ) -> tuple[tuple[WeightedMethodRange, ...], tuple[str, ...]]:
        method_ids = tuple(item.method_id for item in scenarios[0].methods)
        weighted: list[WeightedMethodRange] = []
        diagnostics: list[str] = []
        for method_id in method_ids:
            methods = tuple(item.method(method_id) for item in scenarios)
            if any(
                item.status != "ready" or item.conditional_value_range is None
                for item in methods
            ):
                diagnostics.append(
                    f"{method_id}: not weighted because at least one scenario is blocked."
                )
                continue
            comparison_keys = {
                (item.value_basis, item.horizon, item.formula_version)
                for item in methods
            }
            if len(comparison_keys) != 1:
                diagnostics.append(
                    f"{method_id}: not weighted because basis, horizon, or formula differs."
                )
                continue
            probability_evidence = tuple(
                item.probability_evidence for item in scenarios
            )
            if any(item is None for item in probability_evidence):
                raise ScenarioInvariantError(
                    "SCENARIO_PROBABILITY_INCOMPLETE",
                    "Weighted methods require evidence for every scenario probability.",
                )
            probabilities = tuple(
                item.probability.normalized_value for item in probability_evidence
            )
            ranges = tuple(item.conditional_value_range for item in methods)
            if any(
                point.per_share_value is None
                for item in ranges
                for point in (item.low, item.base, item.high)
            ):
                diagnostics.append(
                    f"{method_id}: not weighted because the per-share basis is unavailable."
                )
                continue
            per_share_dimensions = {
                (
                    item.base.per_share_value.unit,
                    item.base.per_share_value.scale,
                    item.base.per_share_value.currency,
                    item.base.per_share_value.period,
                    item.base.per_share_value.as_of,
                )
                for item in ranges
            }
            if len(per_share_dimensions) != 1:
                diagnostics.append(
                    f"{method_id}: not weighted because per-share dimensions differ."
                )
                continue
            lineage = merge_refs(
                *(item.lineage_refs for item in methods),
                *(item.rationale_refs for item in scenarios),
                *(item.basis_fact_refs for item in probability_evidence),
                *(item.probability.lineage_refs for item in probability_evidence),
            )
            template = ranges[0].base.per_share_value
            low = sum(
                (
                    probability * item.per_share_low
                    for probability, item in zip(probabilities, ranges, strict=True)
                ),
                Decimal("0"),
            )
            base = sum(
                (
                    probability * item.per_share_base
                    for probability, item in zip(probabilities, ranges, strict=True)
                ),
                Decimal("0"),
            )
            high = sum(
                (
                    probability * item.per_share_high
                    for probability, item in zip(probabilities, ranges, strict=True)
                ),
                Decimal("0"),
            )

            def quantity(value: Decimal) -> FinancialQuantity:
                return FinancialQuantity(
                    value=value,
                    unit=template.unit,
                    scale=template.scale,
                    currency=template.currency,
                    period=template.period,
                    as_of=template.as_of,
                    provenance_refs=lineage,
                    kind="per_share",
                )

            probability_sum = self._basis.model_quantity(
                sum(probabilities, Decimal("0")),
                unit="decimal",
                period=probability_evidence[0].probability.period,
                as_of=probability_evidence[0].probability.as_of,
                refs=merge_refs(
                    *(item.probability.lineage_refs for item in probability_evidence)
                ),
            )
            weighted.append(
                WeightedMethodRange(
                    method_id=method_id,
                    value_basis=methods[0].value_basis,
                    horizon=methods[0].horizon,
                    probability_sum_quantity=probability_sum,
                    per_share_low_quantity=quantity(low),
                    per_share_base_quantity=quantity(base),
                    per_share_high_quantity=quantity(high),
                    lineage_refs=lineage,
                )
            )
        return tuple(weighted), tuple(diagnostics)
