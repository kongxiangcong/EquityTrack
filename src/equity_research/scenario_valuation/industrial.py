from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Callable, Mapping

from ..financial import (
    FinancialInvariantError,
    exact_decimal_from_legacy,
    valuation_decimal_context,
)
from ..forecast import (
    CompanyArchetype,
    ForecastGraph,
    ForecastQuantity,
    ForecastRequest,
)
from .contracts import (
    ConditionalValueRange,
    DcfApplicability,
    MethodCalculationResult,
    MethodBlocked,
    RelativeMultipleSpec,
    ReverseDcfSpec,
    ScenarioMethodResult,
    ScenarioInvariantError,
    ValuationAssumption,
    ValuationPlan,
    ValuationSensitivity,
    isolate_method,
    merge_refs,
    percentile,
    require_refs,
)
from ..models import MethodResult
from .basis import ValuationBasis, ValuationContext


class IndustrialValuation:
    """Own the complete IndustrialValuation method-family economics."""

    DCF_FORMULA_VERSION = "fcff_dcf_act365@3"
    SOTP_FORMULA_VERSION = "sotp_segment_multiple@2"
    REVERSE_DCF_FORMULA_VERSION = "reverse_dcf_terminal_growth_act365@3"
    RELATIVE_FORMULA_VERSION = "gated_relative_multiple@2"

    def __init__(self, basis: ValuationBasis) -> None:
        self._basis = basis

    def evaluate(
        self,
        context: ValuationContext,
        plan: ValuationPlan,
    ) -> tuple[ScenarioMethodResult, ...]:
        graph = context.graph
        base_request = context.request
        periods = context.periods
        dcf_horizon = f"valuation_as_of={context.valuation_as_of};cash_flows={periods[0]}..{periods[-1]}"
        terminal_horizon = f"terminal_period={periods[-1]}"
        present_horizon = f"valuation_as_of={context.valuation_as_of}"
        disabled = self._disabled_reasons(base_request.security.archetype)
        methods = [
            isolate_method(
                "fcff_dcf",
                f"{plan.dcf.applicability.status}: {plan.dcf.applicability.reason}",
                "enterprise_value",
                dcf_horizon,
                graph,
                self.DCF_FORMULA_VERSION,
                lambda: self._calculate_if_applicable(
                    disabled.get("fcff_dcf"),
                    lambda: self._dcf(graph, plan, base_request),
                ),
                merge_refs(
                    plan.dcf.applicability.evidence_refs,
                    plan.dcf.discount_rate_base.lineage_refs,
                    plan.dcf.terminal_growth_base.lineage_refs,
                    plan.present_value_bridge.provenance_refs,
                ),
            ),
            isolate_method(
                "sotp",
                "Applicable because every modeled segment has a gated terminal metric.",
                "enterprise_value",
                terminal_horizon,
                graph,
                self.SOTP_FORMULA_VERSION,
                lambda: self._calculate_if_applicable(
                    disabled.get("sotp"),
                    lambda: self._sotp(graph, plan, base_request),
                ),
                merge_refs(
                    *(
                        merge_refs(
                            component.multiple_low.lineage_refs,
                            component.multiple_base.lineage_refs,
                            component.multiple_high.lineage_refs,
                        )
                        for component in plan.sotp.components
                    ),
                    plan.terminal_value_bridge.provenance_refs,
                ),
            ),
            isolate_method(
                "reverse_dcf",
                "Expectation diagnostic against observed present enterprise value.",
                "enterprise_value",
                present_horizon,
                graph,
                self.REVERSE_DCF_FORMULA_VERSION,
                lambda: self._calculate_if_applicable(
                    disabled.get("reverse_dcf"),
                    lambda: self._reverse_dcf(graph, plan, base_request),
                ),
                merge_refs(
                    plan.reverse_dcf.current_enterprise_value.provenance_refs,
                    plan.reverse_dcf.discount_rate.lineage_refs,
                    plan.present_value_bridge.provenance_refs,
                ),
            ),
        ]
        methods.extend(
            self._relative(
                graph,
                plan,
                spec,
                terminal_horizon,
                base_request,
                disabled.get("relative"),
            )
            for spec in plan.relative_methods
        )
        return tuple(methods)

    @staticmethod
    def _disabled_reasons(archetype: CompanyArchetype) -> dict[str, str]:
        if archetype in {
            CompanyArchetype.CYCLICAL_MANUFACTURING,
            CompanyArchetype.CYCLICAL_RESOURCE,
        }:
            return {
                "fcff_dcf": "CYCLICAL_STABLE_GROWTH_DISABLED: ordinary FCFF/WACC DCF is disabled because a current commodity price or peak margin must not be capitalized in perpetuity; use finite-life NAV and mid-cycle methods."
            }
        if archetype == CompanyArchetype.FINANCIAL_INSTITUTION:
            return {
                "fcff_dcf": "FINANCIAL_FCFF_DISABLED: deposits, policyholder liabilities, and regulatory capital are operating inputs rather than industrial financing debt; use P/B-ROE/COE, DDM, or residual income.",
                "sotp": "FINANCIAL_INDUSTRIAL_METHOD_DISABLED: industrial segment EV multiples are disabled for financial institutions.",
                "reverse_dcf": "FINANCIAL_FCFF_DISABLED: reverse FCFF DCF is not meaningful for financial institutions.",
                "relative": "FINANCIAL_GENERIC_RELATIVE_DISABLED: use the specialized P/B-ROE/COE method instead of industrial revenue multiples.",
            }
        if archetype == CompanyArchetype.BIOPHARMA:
            return {
                "fcff_dcf": "BIOPHARMA_FCFF_DISABLED: pre-revenue pipeline economics require finite asset/indication rNPV, event probabilities, licensing terms, and cash runway rather than ordinary FCFF/WACC.",
                "sotp": "BIOPHARMA_INDUSTRIAL_METHOD_DISABLED: generic industrial SOTP is disabled; use unique-right asset/indication rNPV SOTP.",
                "reverse_dcf": "BIOPHARMA_FCFF_DISABLED: reverse FCFF DCF is not meaningful for a pre-revenue event-driven pipeline.",
                "relative": "BIOPHARMA_GENERIC_RELATIVE_DISABLED: pre-revenue pipeline value cannot be inferred from generic mature-company revenue multiples.",
            }
        return {}

    @staticmethod
    def _calculate_if_applicable(
        reason: str | None,
        calculate: Callable[[], MethodCalculationResult],
    ) -> MethodCalculationResult:
        if reason is not None:
            raise MethodBlocked(reason)
        return calculate()

    def _validate_observed_enterprise_value(
        self,
        graph: ForecastGraph,
        spec: ReverseDcfSpec,
        base_request: ForecastRequest,
    ) -> None:
        observed_value = spec.current_enterprise_value
        facts = {fact.fact_id: fact for fact in base_request.data_snapshot.facts}
        observed_refs = tuple(
            ref for ref in observed_value.provenance_refs if ref.startswith("Fact:")
        )
        observed_facts = tuple(
            facts.get(ref.removeprefix("Fact:")) for ref in observed_refs
        )
        if (
            len(observed_refs) != len(observed_value.provenance_refs)
            or any(fact is None for fact in observed_facts)
            or not any(
                fact.subject_id == graph.security_id
                and fact.scope == "company"
                and fact.metric_id == "observed_enterprise_value"
                and fact.value == observed_value.normalized_value
                and fact.unit == observed_value.unit
                and fact.currency == observed_value.currency
                and fact.period == observed_value.period
                and date.fromisoformat(fact.available_at)
                <= date.fromisoformat(self._basis.as_of(graph))
                for fact in observed_facts
            )
        ):
            raise MethodBlocked(
                "REVERSE_DCF_EVIDENCE_INVALID: observed enterprise value must bind an exact PIT snapshot fact."
            )
        if observed_value.period != self._basis.as_of(
            graph
        ) or observed_value.as_of != self._basis.as_of(graph):
            raise MethodBlocked(
                "VALUATION_AS_OF_MISMATCH: observed enterprise value must use the valuation as-of date."
            )

    def _dcf(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
    ) -> tuple[
        ConditionalValueRange,
        tuple[ValuationAssumption, ...],
        tuple[ValuationSensitivity, ...],
        tuple[str, ...],
        tuple[str, ...],
    ]:
        spec = plan.dcf
        self._basis.validate_method_bridge(
            graph,
            plan.present_value_bridge,
            base_request,
        )
        terminal_period = self._basis.periods(graph)[-1]
        if (
            spec.applicability.subject_id != graph.security_id
            or spec.applicability.as_of != self._basis.as_of(graph)
            or spec.discount_rate_base.as_of != self._basis.as_of(graph)
            or spec.discount_rate_base.period != self._basis.as_of(graph)
            or spec.terminal_growth_base.as_of != self._basis.as_of(graph)
            or spec.terminal_growth_base.period != terminal_period
        ):
            raise MethodBlocked(
                "DCF_GATE_BINDING_INVALID: DCF gate and assumptions do not bind the requested subject and time basis."
            )
        if spec.applicability.status == "blocked":
            raise MethodBlocked(
                f"DCF applicability gate blocked this method: {spec.applicability.reason}"
            )
        periods = self._basis.periods(graph)
        if len(periods) < spec.minimum_explicit_periods:
            raise MethodBlocked(
                f"DCF requires at least {spec.minimum_explicit_periods} explicit forecast periods."
            )
        times = self._basis.discount_times(periods, self._basis.as_of(graph))
        fcff = tuple(graph.quantity(f"valuation.fcff.{period}") for period in periods)
        if fcff[-1].normalized_value <= 0:
            raise MethodBlocked("DCF requires positive terminal FCFF.")

        def enterprise_value(
            discount_rate: ForecastQuantity,
            growth: ForecastQuantity,
        ) -> tuple[Decimal, Decimal]:
            rate = discount_rate.normalized_value
            growth_value = growth.normalized_value
            if rate <= growth_value:
                raise MethodBlocked("DCF terminal spread must be positive.")
            explicit = sum(
                (
                    quantity.normalized_value / ((Decimal("1") + rate) ** timing)
                    for timing, quantity in zip(times, fcff, strict=True)
                ),
                Decimal("0"),
            )
            terminal = (
                fcff[-1].normalized_value
                * (Decimal("1") + growth_value)
                / (rate - growth_value)
            )
            present_terminal = terminal / ((Decimal("1") + rate) ** times[-1])
            enterprise = explicit + present_terminal
            return enterprise, present_terminal / enterprise

        cases = (
            enterprise_value(spec.discount_rate_high, spec.terminal_growth_low),
            enterprise_value(spec.discount_rate_base, spec.terminal_growth_base),
            enterprise_value(spec.discount_rate_low, spec.terminal_growth_high),
        )
        values = tuple(item[0] for item in cases)
        lineage = merge_refs(
            spec.applicability.evidence_refs,
            spec.discount_rate_low.lineage_refs,
            spec.discount_rate_base.lineage_refs,
            spec.discount_rate_high.lineage_refs,
            spec.terminal_growth_low.lineage_refs,
            spec.terminal_growth_base.lineage_refs,
            spec.terminal_growth_high.lineage_refs,
            *(item.lineage_refs for item in fcff),
        )
        value_range = self._basis.bridge_range(
            graph,
            plan.present_value_bridge,
            "enterprise_value",
            values,
            self.DCF_FORMULA_VERSION,
            basis_period=self._basis.as_of(graph),
            basis_refs=lineage,
        )
        terminal_share = self._basis.model_quantity(
            cases[1][1],
            unit="decimal",
            period=self._basis.as_of(graph),
            as_of=self._basis.as_of(graph),
            refs=lineage,
        )
        assumptions = (
            ValuationAssumption("discount_rate", spec.discount_rate_base),
            ValuationAssumption("terminal_growth", spec.terminal_growth_base),
            ValuationAssumption("terminal_value_share", terminal_share),
        )
        sensitivity = (
            ValuationSensitivity(
                "discount_rate",
                spec.discount_rate_low,
                spec.discount_rate_base,
                spec.discount_rate_high,
            ),
            ValuationSensitivity(
                "terminal_growth",
                spec.terminal_growth_low,
                spec.terminal_growth_base,
                spec.terminal_growth_high,
            ),
        )
        diagnostics: list[str] = []
        if cases[1][1] > Decimal("0.80"):
            diagnostics.append(
                "Terminal value exceeds 80% of enterprise value; treat DCF as high risk."
            )
        elif cases[1][1] > Decimal("0.70"):
            diagnostics.append(
                "Terminal value exceeds 70% of enterprise value; cross-checks are required."
            )
        if spec.applicability.status == "caution":
            diagnostics.append(
                "DCF applicability gate permits this method only as a cross-check."
            )
        return value_range, assumptions, sensitivity, lineage, tuple(diagnostics)

    def _sotp(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
    ) -> tuple[
        ConditionalValueRange,
        tuple[ValuationAssumption, ...],
        tuple[ValuationSensitivity, ...],
        tuple[str, ...],
        tuple[str, ...],
    ]:
        self._basis.validate_method_bridge(
            graph,
            plan.terminal_value_bridge,
            base_request,
        )
        plan_segments = {item.segment_id for item in plan.sotp.components}
        modeled_segments = set(base_request.security.segment_ids)
        if plan_segments != modeled_segments:
            raise MethodBlocked(
                "SOTP_COMPONENT_COVERAGE_INVALID: SOTP must cover every forecast segment exactly once."
            )
        final_period = self._basis.periods(graph)[-1]
        values = [Decimal("0"), Decimal("0"), Decimal("0")]
        assumptions: list[ValuationAssumption] = []
        sensitivity: list[ValuationSensitivity] = []
        lineage: tuple[str, ...] = ()
        for component in plan.sotp.components:
            quantity = graph.quantity(
                f"{component.segment_id}.{component.metric}.{final_period}"
            )
            if quantity.normalized_value <= 0:
                raise MethodBlocked(
                    f"SOTP component {component.segment_id} has a non-positive metric."
                )
            multiples = (
                component.multiple_low,
                component.multiple_base,
                component.multiple_high,
            )
            if any(
                item.period != final_period or item.as_of != self._basis.as_of(graph)
                for item in multiples
            ):
                raise MethodBlocked(
                    f"SOTP component {component.segment_id} multiple time basis mismatches the terminal metric."
                )
            values = [
                current + quantity.normalized_value * multiple.normalized_value
                for current, multiple in zip(values, multiples, strict=True)
            ]
            assumptions.append(
                ValuationAssumption(
                    f"{component.segment_id}_{component.metric}_multiple",
                    component.multiple_base,
                )
            )
            sensitivity.append(
                ValuationSensitivity(
                    f"{component.segment_id}_{component.metric}_multiple",
                    component.multiple_low,
                    component.multiple_base,
                    component.multiple_high,
                )
            )
            lineage = merge_refs(
                lineage,
                quantity.lineage_refs,
                *(item.lineage_refs for item in multiples),
            )
        value_range = self._basis.bridge_range(
            graph,
            plan.terminal_value_bridge,
            "enterprise_value",
            tuple(values),
            self.SOTP_FORMULA_VERSION,
            basis_period=final_period,
            basis_refs=lineage,
        )
        return value_range, tuple(assumptions), tuple(sensitivity), lineage, ()

    def _reverse_dcf(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
    ) -> tuple[
        ConditionalValueRange,
        tuple[ValuationAssumption, ...],
        tuple[ValuationSensitivity, ...],
        tuple[str, ...],
        tuple[str, ...],
    ]:
        spec = plan.reverse_dcf
        self._basis.validate_method_bridge(
            graph,
            plan.present_value_bridge,
            base_request,
        )
        self._validate_observed_enterprise_value(
            graph,
            spec,
            base_request,
        )
        periods = self._basis.periods(graph)
        if spec.discount_rate.period != self._basis.as_of(
            graph
        ) or spec.discount_rate.as_of != self._basis.as_of(graph):
            raise MethodBlocked(
                "Reverse DCF discount rate must bind the valuation as-of date."
            )
        times = self._basis.discount_times(periods, self._basis.as_of(graph))
        fcff = tuple(graph.quantity(f"valuation.fcff.{period}") for period in periods)
        rate = spec.discount_rate.normalized_value
        explicit = sum(
            (
                quantity.normalized_value / ((Decimal("1") + rate) ** timing)
                for timing, quantity in zip(times, fcff, strict=True)
            ),
            Decimal("0"),
        )
        remaining_present_value = (
            spec.current_enterprise_value.normalized_value - explicit
        )
        if remaining_present_value <= 0 or fcff[-1].normalized_value <= 0:
            raise MethodBlocked(
                "Observed enterprise value cannot support a finite terminal-growth solution."
            )
        terminal_at_horizon = remaining_present_value * (
            (Decimal("1") + rate) ** times[-1]
        )
        implied_growth = (terminal_at_horizon * rate - fcff[-1].normalized_value) / (
            terminal_at_horizon + fcff[-1].normalized_value
        )
        if not Decimal("-1") < implied_growth < rate:
            raise MethodBlocked(
                "Implied terminal growth is outside the finite DCF solution domain."
            )
        lineage = merge_refs(
            spec.current_enterprise_value.provenance_refs,
            spec.discount_rate.lineage_refs,
            *(item.lineage_refs for item in fcff),
        )
        observed = spec.current_enterprise_value.normalized_value
        value_range = self._basis.bridge_range(
            graph,
            plan.present_value_bridge,
            "enterprise_value",
            (observed, observed, observed),
            self.REVERSE_DCF_FORMULA_VERSION,
            basis_period=self._basis.as_of(graph),
            basis_refs=spec.current_enterprise_value.provenance_refs,
        )
        implied = self._basis.model_quantity(
            implied_growth,
            unit="decimal",
            period=self._basis.periods(graph)[-1],
            as_of=self._basis.as_of(graph),
            refs=lineage,
        )
        assumptions = (
            ValuationAssumption("discount_rate", spec.discount_rate),
            ValuationAssumption("implied_terminal_growth", implied),
        )
        sensitivity = ValuationSensitivity(
            "implied_terminal_growth", implied, implied, implied
        )
        return value_range, assumptions, (sensitivity,), lineage, ()

    def _relative(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        spec: RelativeMultipleSpec,
        horizon: str,
        base_request: ForecastRequest,
        disabled_reason: str | None,
    ) -> ScenarioMethodResult:
        applicability = f"{spec.status}: copied from {spec.gate_version}; no caller-declared multiples are accepted."
        if spec.status == "blocked":
            return ScenarioMethodResult(
                method_id=spec.method_id,
                status="blocked",
                applicability=applicability,
                value_basis=spec.value_basis,
                horizon=horizon,
                assumptions=(),
                formula_version=self.RELATIVE_FORMULA_VERSION,
                conditional_value_range=None,
                sensitivity=(),
                diagnostics=spec.diagnostics,
                lineage_refs=spec.evidence_refs,
            )

        def calculate() -> tuple[
            ConditionalValueRange,
            tuple[ValuationAssumption, ...],
            tuple[ValuationSensitivity, ...],
            tuple[str, ...],
            tuple[str, ...],
        ]:
            if disabled_reason is not None:
                raise MethodBlocked(disabled_reason)
            self._basis.validate_method_bridge(
                graph,
                plan.terminal_value_bridge,
                base_request,
            )
            if (
                spec.subject_id != graph.security_id
                or spec.gate_as_of != self._basis.as_of(graph)
            ):
                raise MethodBlocked(
                    "RELATIVE_GATE_BINDING_INVALID: relative gate does not bind the requested subject and as-of."
                )
            final_period = self._basis.periods(graph)[-1]
            quantity = graph.quantity(f"company.{spec.metric}.{final_period}")
            if quantity.normalized_value <= 0:
                raise MethodBlocked(
                    f"Relative method {spec.method_id} has a non-positive metric."
                )
            multiples = (spec.multiple_low, spec.multiple_base, spec.multiple_high)
            if any(item is None for item in multiples):
                raise MethodBlocked(
                    "Ready relative method lost its gated multiple range."
                )
            values = tuple(
                quantity.normalized_value * item.normalized_value for item in multiples
            )
            lineage = merge_refs(
                spec.evidence_refs,
                quantity.lineage_refs,
                *(item.lineage_refs for item in multiples),
            )
            value_range = self._basis.bridge_range(
                graph,
                plan.terminal_value_bridge,
                spec.value_basis,
                values,
                self.RELATIVE_FORMULA_VERSION,
                basis_period=final_period,
                basis_refs=lineage,
            )
            assumption = ValuationAssumption(
                f"{spec.method_id}_{spec.metric}_multiple",
                spec.multiple_base,
            )
            sensitivity = ValuationSensitivity(
                f"{spec.method_id}_{spec.metric}_multiple",
                spec.multiple_low,
                spec.multiple_base,
                spec.multiple_high,
            )
            return value_range, (assumption,), (sensitivity,), lineage, spec.diagnostics

        return isolate_method(
            spec.method_id,
            applicability,
            spec.value_basis,
            horizon,
            graph,
            self.RELATIVE_FORMULA_VERSION,
            calculate,
            merge_refs(
                spec.evidence_refs,
                plan.terminal_value_bridge.provenance_refs,
            ),
        )

    def bind_dcf_applicability(
        self,
        result: MethodResult,
        *,
        subject_id: str,
        as_of: str,
    ) -> DcfApplicability:
        if not isinstance(result, MethodResult) or result.method_id != "dcf":
            raise ScenarioInvariantError(
                "DCF_GATE_INVALID",
                "DCF applicability must adapt the existing dcf MethodResult.",
            )
        try:
            date.fromisoformat(as_of)
        except (TypeError, ValueError) as exc:
            raise ScenarioInvariantError(
                "DCF_GATE_INVALID",
                "DCF gate as_of must be an ISO date.",
            ) from exc
        if not subject_id.strip() or not result.explanation.strip():
            raise ScenarioInvariantError(
                "DCF_GATE_INVALID",
                "DCF gate subject and explanation are required.",
            )
        status = {
            "ready": "allowed",
            "caution": "caution",
        }.get(result.status, "blocked")
        refs = tuple(f"Fact:{item}" for item in result.evidence_ids)
        if status in {"allowed", "caution"}:
            require_refs(refs, "DcfApplicability.evidence_refs", facts_only=True)
        elif not refs:
            refs = ("Assumption:dcf_gate_blocked",)
        gated_wacc: ForecastQuantity | None = None
        gated_terminal_growth: ForecastQuantity | None = None
        if status in {"allowed", "caution"}:
            exact = result.metrics.get("exact_calculation")
            if not isinstance(exact, Mapping):
                raise ScenarioInvariantError(
                    "DCF_GATE_INVALID",
                    "Ready DCF MethodResult requires exact_calculation inputs.",
                )
            dimensioned = exact.get("dimensioned_inputs")
            if not isinstance(dimensioned, Mapping):
                raise ScenarioInvariantError(
                    "DCF_GATE_INVALID",
                    "Ready DCF gate must expose dimensioned inputs.",
                )
            wacc_components = dimensioned.get("wacc_components")
            terminal_input = dimensioned.get("terminal_growth")
            if not isinstance(wacc_components, Mapping) or not isinstance(
                terminal_input, Mapping
            ):
                raise ScenarioInvariantError(
                    "DCF_GATE_INVALID",
                    "DCF gate must preserve WACC-component and terminal-growth quantities.",
                )
            required_wacc_units = {
                "risk_free_rate": "decimal",
                "equity_risk_premium": "decimal",
                "beta": "x",
                "pre_tax_cost_of_debt": "decimal",
                "tax_rate": "decimal",
                "equity_weight": "decimal",
                "debt_weight": "decimal",
            }
            if set(wacc_components) != set(required_wacc_units):
                raise ScenarioInvariantError(
                    "DCF_GATE_INVALID",
                    "DCF gate must expose the complete canonical WACC component set.",
                )
            component_values: dict[str, Decimal] = {}
            component_periods: set[str] = set()
            component_refs: list[str] = []
            try:
                for name, expected_unit in required_wacc_units.items():
                    component = wacc_components[name]
                    if not isinstance(component, Mapping):
                        raise FinancialInvariantError(
                            "FINANCIAL_VALUE_INVALID",
                            f"WACC component {name} is not dimensioned.",
                        )
                    component_values[name] = exact_decimal_from_legacy(
                        component.get("value"), f"WACC component {name}"
                    )
                    component_scale = exact_decimal_from_legacy(
                        component.get("scale"), f"WACC component {name} scale"
                    )
                    period = str(component.get("period", ""))
                    period_date = date.fromisoformat(period)
                    refs_for_component = tuple(component.get("provenance_refs", ()))
                    require_refs(
                        refs_for_component,
                        f"WACC component {name} lineage",
                    )
                    if (
                        component.get("unit") != expected_unit
                        or component_scale != Decimal("1")
                        or component.get("currency") not in {"", "N/A"}
                        or component.get("as_of") != as_of
                        or period_date > date.fromisoformat(as_of)
                        or len(refs_for_component) != 1
                    ):
                        raise ScenarioInvariantError(
                            "DCF_GATE_INVALID",
                            f"WACC component {name} has invalid dimensions, time basis, or lineage.",
                        )
                    component_periods.add(period)
                    component_refs.extend(refs_for_component)
                wacc = exact_decimal_from_legacy(exact.get("wacc"), "gated WACC")
                declared_calculated_wacc = exact_decimal_from_legacy(
                    exact.get("calculated_wacc"), "declared calculated WACC"
                )
                terminal_growth = exact_decimal_from_legacy(
                    exact.get("terminal_growth"), "gated terminal growth"
                )
                typed_terminal = exact_decimal_from_legacy(
                    terminal_input.get("value"), "dimensioned terminal growth"
                )
                terminal_scale = exact_decimal_from_legacy(
                    terminal_input.get("scale"), "terminal growth scale"
                )
            except (FinancialInvariantError, TypeError, ValueError) as exc:
                raise ScenarioInvariantError(
                    "DCF_GATE_INVALID",
                    "DCF WACC components or terminal growth are not exact, dimensioned, and PIT-safe.",
                ) from exc
            if len(component_periods) != 1 or len(set(component_refs)) != len(
                component_refs
            ):
                raise ScenarioInvariantError(
                    "DCF_GATE_INVALID",
                    "WACC components must share one valuation date and unique evidence lineage.",
                )
            wacc_refs = tuple(component_refs)
            terminal_refs = tuple(terminal_input.get("provenance_refs", ()))
            require_refs(wacc_refs, "DCF gated WACC lineage")
            require_refs(terminal_refs, "DCF gated terminal-growth lineage")
            evidence_ids = set(result.evidence_ids)
            if any(
                ref.split(":", 1)[1] not in evidence_ids
                for ref in (*wacc_refs, *terminal_refs)
            ):
                raise ScenarioInvariantError(
                    "DCF_GATE_INVALID",
                    "DCF dimensioned-input lineage must resolve through MethodResult.evidence_ids.",
                )
            equity_weight = component_values["equity_weight"]
            debt_weight = component_values["debt_weight"]
            tax_rate = component_values["tax_rate"]
            if (
                equity_weight < 0
                or debt_weight < 0
                or abs(equity_weight + debt_weight - Decimal("1")) > Decimal("0.000001")
                or not Decimal("0") <= tax_rate < Decimal("1")
            ):
                raise ScenarioInvariantError(
                    "DCF_GATE_INVALID",
                    "WACC weights and tax rate do not satisfy the canonical gate.",
                )
            replayed_wacc = equity_weight * (
                component_values["risk_free_rate"]
                + component_values["beta"] * component_values["equity_risk_premium"]
            ) + debt_weight * component_values["pre_tax_cost_of_debt"] * (
                Decimal("1") - tax_rate
            )
            if (
                abs(wacc - replayed_wacc) > Decimal("0.000001")
                or abs(declared_calculated_wacc - replayed_wacc) > Decimal("0.000001")
                or typed_terminal != terminal_growth
                or terminal_input.get("unit") != "decimal"
                or terminal_scale != Decimal("1")
                or terminal_input.get("currency") not in {"", "N/A"}
                or terminal_input.get("as_of") != as_of
            ):
                raise ScenarioInvariantError(
                    "DCF_GATE_INVALID",
                    "DCF WACC or terminal-growth exact values and dimensions do not replay.",
                )
            gated_wacc = ForecastQuantity(
                value=wacc,
                unit="decimal",
                scale=Decimal("1"),
                currency="N/A",
                period=as_of,
                as_of=as_of,
                lineage_refs=wacc_refs,
            )
            gated_terminal_growth = ForecastQuantity(
                value=terminal_growth,
                unit="decimal",
                scale=Decimal("1"),
                currency="N/A",
                period=str(terminal_input.get("period", "terminal")),
                as_of=as_of,
                lineage_refs=terminal_refs,
            )
        return DcfApplicability.from_validated_gate(
            status=status,
            reason=result.explanation,
            subject_id=subject_id,
            as_of=as_of,
            evidence_refs=refs,
            diagnostics=tuple(result.diagnostics),
            gated_wacc=gated_wacc,
            gated_terminal_growth=gated_terminal_growth,
        )

    def bind_relative_multiple(
        self,
        result: MethodResult,
        *,
        subject_id: str,
        as_of: str,
    ) -> RelativeMultipleSpec:
        if (
            not isinstance(result, MethodResult)
            or result.method_id not in {"peer_comps", "historical_band"}
            or not subject_id.strip()
        ):
            raise ScenarioInvariantError(
                "RELATIVE_GATE_INVALID",
                "Relative valuation must adapt a gated peer_comps or historical_band MethodResult.",
            )
        try:
            date.fromisoformat(as_of)
        except (TypeError, ValueError) as exc:
            raise ScenarioInvariantError(
                "RELATIVE_GATE_INVALID",
                "Relative gate as_of must be an ISO date.",
            ) from exc
        if result.status != "ready":
            refs = tuple(f"Fact:{item}" for item in result.evidence_ids) or (
                f"Assumption:{result.method_id}:gate_blocked",
            )
            return RelativeMultipleSpec.from_validated_gate(
                method_id=result.method_id,
                status="blocked",
                metric="",
                value_basis="enterprise_value",
                multiples=(None, None, None),
                evidence_refs=refs,
                diagnostics=tuple(result.diagnostics) or (result.explanation,),
                subject_id=subject_id,
                as_of=as_of,
            )

        exact = result.metrics.get("exact_calculation")
        if not isinstance(exact, Mapping):
            raise ScenarioInvariantError(
                "RELATIVE_GATE_INVALID",
                "Ready relative MethodResult requires exact_calculation evidence.",
            )
        metric = str(exact.get("metric") or result.metrics.get("metric") or "").lower()
        if metric != "ps":
            refs = tuple(f"Fact:{item}" for item in result.evidence_ids) or (
                f"Assumption:{result.method_id}:unsupported_metric",
            )
            return RelativeMultipleSpec.from_validated_gate(
                method_id=result.method_id,
                status="blocked",
                metric=metric,
                value_basis="enterprise_value",
                multiples=(None, None, None),
                evidence_refs=refs,
                diagnostics=(
                    f"Gated {metric or 'unknown'} multiple has no compatible Forecast metric in this template.",
                ),
                subject_id=subject_id,
                as_of=as_of,
            )
        inputs_container = exact.get("dimensioned_inputs")
        if result.method_id == "peer_comps":
            if not isinstance(inputs_container, Mapping):
                raise ScenarioInvariantError(
                    "RELATIVE_GATE_INVALID",
                    "Peer gate must expose dimensioned_inputs.peer_multiples.",
                )
            raw_inputs = inputs_container.get("peer_multiples")
            minimum = 3
            if (
                result.assumptions.get("currency_checked") is not True
                or result.assumptions.get("accounting_checked") is not True
                or int(result.assumptions.get("minimum_peer_count", 0)) < minimum
            ):
                raise ScenarioInvariantError(
                    "RELATIVE_GATE_INVALID",
                    "Peer gate must preserve currency/accounting checks and the minimum peer count.",
                )
            range_keys = (
                "peer_q25_multiple",
                "peer_median_multiple",
                "peer_q75_multiple",
            )
        else:
            raw_inputs = inputs_container
            minimum = 12
            if int(result.assumptions.get("minimum_observations", 0)) < minimum:
                raise ScenarioInvariantError(
                    "RELATIVE_GATE_INVALID",
                    "Historical gate must preserve the minimum observation rule.",
                )
            range_keys = ("q25", "median", "q75")
        if not isinstance(raw_inputs, list) or len(raw_inputs) < minimum:
            raise ScenarioInvariantError(
                "RELATIVE_GATE_INVALID",
                f"{result.method_id} gate has too few dimensioned observations.",
            )
        values: list[Decimal] = []
        refs: list[str] = []
        for item in raw_inputs:
            if not isinstance(item, Mapping):
                raise ScenarioInvariantError(
                    "RELATIVE_GATE_INVALID",
                    "Gated multiple observations must be mappings.",
                )
            try:
                value = exact_decimal_from_legacy(item.get("value"), "gated multiple")
                scale = exact_decimal_from_legacy(
                    item.get("scale"), "gated multiple scale"
                )
                item_as_of = date.fromisoformat(str(item.get("as_of", "")))
            except (FinancialInvariantError, TypeError, ValueError) as exc:
                raise ScenarioInvariantError(
                    "RELATIVE_GATE_INVALID",
                    "Gated multiple observation has invalid exact dimensions.",
                ) from exc
            item_refs = tuple(item.get("provenance_refs", ()))
            require_refs(item_refs, "gated multiple provenance", facts_only=True)
            if (
                value <= 0
                or item.get("unit") != "x"
                or scale != Decimal("1")
                or item.get("currency") not in {"", "N/A"}
                or not str(item.get("period", "")).strip()
                or item_as_of > date.fromisoformat(as_of)
            ):
                raise ScenarioInvariantError(
                    "RELATIVE_GATE_INVALID",
                    "Gated multiples must be positive, dimensionless, PIT-safe observations.",
                )
            values.append(value)
            refs.extend(item_refs)
        if len(refs) != len(set(refs)):
            raise ScenarioInvariantError(
                "RELATIVE_GATE_INVALID",
                "Gated relative observations require distinct evidence references.",
            )
        evidence_ids = set(result.evidence_ids)
        if any(ref.removeprefix("Fact:") not in evidence_ids for ref in refs):
            raise ScenarioInvariantError(
                "RELATIVE_GATE_INVALID",
                "Dimensioned observation lineage must be present in MethodResult.evidence_ids.",
            )
        with valuation_decimal_context():
            expected = (
                percentile(tuple(values), Decimal("0.25")),
                percentile(tuple(values), Decimal("0.50")),
                percentile(tuple(values), Decimal("0.75")),
            )
            try:
                supplied = tuple(
                    exact_decimal_from_legacy(exact.get(key), key) for key in range_keys
                )
            except FinancialInvariantError as exc:
                raise ScenarioInvariantError(
                    "RELATIVE_GATE_INVALID",
                    "Gated exact multiple range is missing or invalid.",
                ) from exc
        if supplied != expected:
            raise ScenarioInvariantError(
                "RELATIVE_GATE_INVALID",
                "Gated exact multiple range does not replay from its observations.",
            )
        lineage = tuple(refs)
        quantities = tuple(
            ForecastQuantity(
                value=value,
                unit="x",
                scale=Decimal("1"),
                currency="N/A",
                period=as_of,
                as_of=as_of,
                lineage_refs=lineage,
            )
            for value in supplied
        )
        return RelativeMultipleSpec.from_validated_gate(
            method_id=result.method_id,
            status="ready",
            metric="revenue",
            value_basis="equity_value",
            multiples=quantities,
            evidence_refs=lineage,
            diagnostics=tuple(result.diagnostics),
            subject_id=subject_id,
            as_of=as_of,
        )
