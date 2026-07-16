from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Literal, Mapping

from .financial import (
    EquityBridge,
    EquityBridgeResult,
    FinancialInvariantError,
    FinancialQuantity,
    ValueBasis,
    exact_decimal_from_legacy,
    valuation_decimal_context,
)
from .forecast import (
    ForecastEngine,
    ForecastGraph,
    ForecastInvariantError,
    ForecastQuantity,
    ForecastRequest,
    SegmentForecastOverride,
)
from .models import MethodResult


MethodStatus = Literal["ready", "blocked"]
ProbabilityMode = Literal["conditional_only", "evidence_weighted"]


class ScenarioInvariantError(ValueError):
    """A stable diagnostic for an invalid deterministic scenario valuation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class ScenarioRole(str, Enum):
    STRESS = "stress"
    BASE = "base"
    IMPROVEMENT = "improvement"


class EquityBridgeTiming(str, Enum):
    OPENING = "opening"
    TERMINAL = "terminal"


def _decimal_text(value: Decimal) -> str:
    with valuation_decimal_context():
        if value == 0:
            return "0"
        return format(value.normalize(), "f")


def _require_decimal(value: Any, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ScenarioInvariantError(
            "SCENARIO_DECIMAL_REQUIRED",
            f"{field_name} must be a finite Decimal.",
        )
    return value


def _require_refs(
    refs: tuple[str, ...],
    field_name: str,
    *,
    facts_only: bool = False,
) -> None:
    prefixes = ("Fact:",) if facts_only else ("Fact:", "Assumption:")
    if not isinstance(refs, tuple) or not refs or any(
        not isinstance(ref, str) or not ref.startswith(prefixes) for ref in refs
    ):
        raise ScenarioInvariantError(
            "SCENARIO_LINEAGE_INVALID",
            f"{field_name} requires resolved {'Fact' if facts_only else 'Fact or Assumption'} references.",
        )


def _merge_refs(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ref for group in groups for ref in group))


def _same_dimension(*quantities: ForecastQuantity) -> bool:
    return len(
        {
            (
                item.unit,
                item.scale,
                item.currency,
                item.period,
                item.as_of,
            )
            for item in quantities
        }
    ) == 1


def _validate_model_quantity(
    quantity: ForecastQuantity,
    *,
    unit: str,
    field_name: str,
) -> None:
    if not isinstance(quantity, ForecastQuantity):
        raise ScenarioInvariantError(
            "VALUATION_QUANTITY_INVALID",
            f"{field_name} must be a ForecastQuantity.",
        )
    if (
        quantity.unit != unit
        or quantity.scale != Decimal("1")
        or quantity.currency != "N/A"
    ):
        raise ScenarioInvariantError(
            "VALUATION_QUANTITY_DIMENSION_INVALID",
            f"{field_name} must use {unit}, scale one, and N/A currency.",
        )


def _validate_range(
    low: ForecastQuantity,
    base: ForecastQuantity,
    high: ForecastQuantity,
    field_name: str,
    *,
    unit: str,
    positive: bool = False,
) -> None:
    for suffix, quantity in (("low", low), ("base", base), ("high", high)):
        _validate_model_quantity(
            quantity,
            unit=unit,
            field_name=f"{field_name}_{suffix}",
        )
    if not _same_dimension(low, base, high):
        raise ScenarioInvariantError(
            "VALUATION_RANGE_DIMENSION_MISMATCH",
            f"{field_name} range quantities must share one dimension and time basis.",
        )
    values = tuple(item.normalized_value for item in (low, base, high))
    if values[0] > values[1] or values[1] > values[2] or (
        positive and values[0] <= 0
    ):
        raise ScenarioInvariantError(
            "VALUATION_RANGE_INVALID",
            f"{field_name} must be ordered low <= base <= high"
            + (" and positive." if positive else "."),
        )


def _percentile(values: tuple[Decimal, ...], probability: Decimal) -> Decimal:
    if not values:
        raise ScenarioInvariantError(
            "RELATIVE_GATE_INVALID",
            "A gated multiple distribution cannot be empty.",
        )
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] * (Decimal("1") - fraction) + ordered[upper] * fraction


@dataclass(frozen=True, init=False)
class DcfApplicability:
    """Immutable adapter output from the existing method router and DCF gate."""

    status: Literal["allowed", "caution", "blocked"]
    reason: str
    subject_id: str
    as_of: str
    evidence_refs: tuple[str, ...]
    diagnostics: tuple[str, ...]
    gate_version: str
    gated_wacc: ForecastQuantity | None
    gated_terminal_growth: ForecastQuantity | None

    def __init__(self, *_: Any, **__: Any) -> None:
        raise TypeError("Use DcfApplicability.from_gated_method_result().")

    @classmethod
    def from_gated_method_result(
        cls,
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
            _require_refs(refs, "DcfApplicability.evidence_refs", facts_only=True)
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
                    refs_for_component = tuple(
                        component.get("provenance_refs", ())
                    )
                    _require_refs(
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
            _require_refs(wacc_refs, "DCF gated WACC lineage")
            _require_refs(terminal_refs, "DCF gated terminal-growth lineage")
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
                or abs(equity_weight + debt_weight - Decimal("1"))
                > Decimal("0.000001")
                or not Decimal("0") <= tax_rate < Decimal("1")
            ):
                raise ScenarioInvariantError(
                    "DCF_GATE_INVALID",
                    "WACC weights and tax rate do not satisfy the canonical gate.",
                )
            replayed_wacc = (
                equity_weight
                * (
                    component_values["risk_free_rate"]
                    + component_values["beta"]
                    * component_values["equity_risk_premium"]
                )
                + debt_weight
                * component_values["pre_tax_cost_of_debt"]
                * (Decimal("1") - tax_rate)
            )
            if (
                abs(wacc - replayed_wacc) > Decimal("0.000001")
                or abs(declared_calculated_wacc - replayed_wacc)
                > Decimal("0.000001")
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
        instance = object.__new__(cls)
        for field_name, value in {
            "status": status,
            "reason": result.explanation,
            "subject_id": subject_id,
            "as_of": as_of,
            "evidence_refs": refs,
            "diagnostics": tuple(result.diagnostics),
            "gate_version": "existing-method-router+dcf-applicability@1",
            "gated_wacc": gated_wacc,
            "gated_terminal_growth": gated_terminal_growth,
        }.items():
            object.__setattr__(instance, field_name, value)
        return instance


@dataclass(frozen=True)
class ScenarioProbabilityEvidence:
    evidence_id: str
    schema_version: str
    formula_version: str
    calibration_window_start: str
    calibration_window_end: str
    calibration_sample_size: int
    observed_count: int
    prior_count: Decimal
    prior_total_count: Decimal
    observed_count_fact_ref: str
    sample_size_fact_ref: str
    subject_id: str
    scenario_id: str
    mutually_exclusive_group: str
    probability: ForecastQuantity
    basis_fact_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.evidence_id,
                self.schema_version,
                self.formula_version,
                self.calibration_window_start,
                self.calibration_window_end,
                self.subject_id,
                self.scenario_id,
                self.mutually_exclusive_group,
                self.observed_count_fact_ref,
                self.sample_size_fact_ref,
            )
        ):
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                "Probability evidence identity and partition binding are required.",
            )
        _validate_model_quantity(
            self.probability,
            unit="decimal",
            field_name="ScenarioProbabilityEvidence.probability",
        )
        try:
            window_start = date.fromisoformat(self.calibration_window_start)
            window_end = date.fromisoformat(self.calibration_window_end)
        except (TypeError, ValueError) as exc:
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                "Probability calibration window must contain ISO dates.",
            ) from exc
        if (
            self.schema_version != "ScenarioProbabilityCalibration@1"
            or self.formula_version != "observed-frequency@1"
            or not isinstance(self.calibration_sample_size, int)
            or self.calibration_sample_size < 30
            or not isinstance(self.observed_count, int)
            or self.observed_count < 0
            or self.observed_count > self.calibration_sample_size
            or not isinstance(self.prior_count, Decimal)
            or not self.prior_count.is_finite()
            or self.prior_count != 0
            or not isinstance(self.prior_total_count, Decimal)
            or not self.prior_total_count.is_finite()
            or self.prior_total_count != 0
            or window_start > window_end
            or window_end > date.fromisoformat(self.probability.as_of)
        ):
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                "Probability weighting requires a versioned, PIT-safe calibration artifact with at least 30 observations.",
            )
        with valuation_decimal_context():
            denominator = Decimal(self.calibration_sample_size)
            if denominator <= 0:
                raise ScenarioInvariantError(
                    "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                    "Probability calibration denominator must be positive.",
                )
            replayed_probability = Decimal(self.observed_count) / denominator
        if replayed_probability != self.probability.normalized_value:
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                "Probability must replay from the versioned observed-frequency formula.",
            )
        if not Decimal("0") <= self.probability.normalized_value <= Decimal("1"):
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_INVALID",
                "Scenario probability must be between zero and one.",
            )
        _require_refs(
            self.basis_fact_refs,
            "ScenarioProbabilityEvidence.basis_fact_refs",
            facts_only=True,
        )
        calibration_ref = f"Assumption:calibration:{self.evidence_id}"
        if (
            self.basis_fact_refs
            != (self.observed_count_fact_ref, self.sample_size_fact_ref)
            or not set(self.basis_fact_refs).issubset(self.probability.lineage_refs)
            or calibration_ref not in self.probability.lineage_refs
        ):
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                "Probability quantity must preserve its calibration artifact and input-fact lineage.",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "schema_version": self.schema_version,
            "formula_version": self.formula_version,
            "calibration_window_start": self.calibration_window_start,
            "calibration_window_end": self.calibration_window_end,
            "calibration_sample_size": self.calibration_sample_size,
            "observed_count": self.observed_count,
            "prior_count": _decimal_text(self.prior_count),
            "prior_total_count": _decimal_text(self.prior_total_count),
            "observed_count_fact_ref": self.observed_count_fact_ref,
            "sample_size_fact_ref": self.sample_size_fact_ref,
            "subject_id": self.subject_id,
            "scenario_id": self.scenario_id,
            "mutually_exclusive_group": self.mutually_exclusive_group,
            "probability": self.probability.to_dict(),
            "basis_fact_refs": list(self.basis_fact_refs),
        }


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    role: ScenarioRole
    label: str
    mutually_exclusive_group: str
    partition_basis: str
    driver_overrides: tuple[SegmentForecastOverride, ...]
    probability_evidence: ScenarioProbabilityEvidence | None = None
    rationale_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.scenario_id,
                self.label,
                self.mutually_exclusive_group,
                self.partition_basis,
            )
        ):
            raise ScenarioInvariantError(
                "SCENARIO_IDENTITY_MISSING",
                "Scenario identity, group, and partition basis are required.",
            )
        if not isinstance(self.role, ScenarioRole):
            raise ScenarioInvariantError(
                "SCENARIO_ROLE_INVALID",
                "Scenario role must be a ScenarioRole.",
            )
        if not isinstance(self.driver_overrides, tuple) or any(
            not isinstance(item, SegmentForecastOverride)
            for item in self.driver_overrides
        ):
            raise ScenarioInvariantError(
                "SCENARIO_DRIVER_TYPE_INVALID",
                "driver_overrides must contain SegmentForecastOverride values.",
            )
        if self.probability_evidence is not None and not isinstance(
            self.probability_evidence, ScenarioProbabilityEvidence
        ):
            raise ScenarioInvariantError(
                "SCENARIO_PROBABILITY_EVIDENCE_INVALID",
                "Probability weighting requires typed evidence.",
            )
        _require_refs(self.rationale_refs, "ScenarioDefinition.rationale_refs")

    @property
    def probability(self) -> Decimal | None:
        if self.probability_evidence is None:
            return None
        return self.probability_evidence.probability.normalized_value


@dataclass(frozen=True)
class EquityBridgeSpec:
    timing: EquityBridgeTiming
    diluted_shares: FinancialQuantity
    lease_debt: FinancialQuantity
    preferred_stock: FinancialQuantity
    minority_interest: FinancialQuantity
    pension_deficit: FinancialQuantity
    associates_jv_value: FinancialQuantity
    non_operating_assets: FinancialQuantity
    output_currency: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.timing, EquityBridgeTiming):
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_TIMING_INVALID",
                "Equity bridge timing must be opening or terminal.",
            )
        quantities = (
            self.diluted_shares,
            self.lease_debt,
            self.preferred_stock,
            self.minority_interest,
            self.pension_deficit,
            self.associates_jv_value,
            self.non_operating_assets,
        )
        if any(not isinstance(item, FinancialQuantity) for item in quantities):
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_INPUT_INVALID",
                "Every equity-bridge input must be a FinancialQuantity.",
            )
        if self.diluted_shares.kind != "shares":
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_INPUT_INVALID",
                "diluted_shares must carry a shares dimension.",
            )
        money_inputs = quantities[1:]
        if any(item.kind != "money" for item in money_inputs):
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_INPUT_INVALID",
                "Equity-bridge adjustments must carry a money dimension.",
            )
        time_bases = {(item.period, item.as_of) for item in quantities}
        money_currencies = {item.currency for item in money_inputs}
        if len(time_bases) != 1 or len(money_currencies) != 1:
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_DIMENSION_MISMATCH",
                "Bridge adjustments and shares must share one time basis; money adjustments share one currency.",
            )

    @property
    def balance_sheet_period(self) -> str:
        return self.diluted_shares.period

    @property
    def provenance_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.diluted_shares.provenance_refs,
            self.lease_debt.provenance_refs,
            self.preferred_stock.provenance_refs,
            self.minority_interest.provenance_refs,
            self.pension_deficit.provenance_refs,
            self.associates_jv_value.provenance_refs,
            self.non_operating_assets.provenance_refs,
        )


@dataclass(frozen=True)
class DcfValuationSpec:
    applicability: DcfApplicability
    discount_rate_low: ForecastQuantity
    discount_rate_base: ForecastQuantity
    discount_rate_high: ForecastQuantity
    terminal_growth_low: ForecastQuantity
    terminal_growth_base: ForecastQuantity
    terminal_growth_high: ForecastQuantity
    minimum_explicit_periods: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.applicability, DcfApplicability):
            raise ScenarioInvariantError(
                "DCF_GATE_INVALID",
                "DCF requires the existing router/applicability gate result.",
            )
        _validate_range(
            self.discount_rate_low,
            self.discount_rate_base,
            self.discount_rate_high,
            "discount_rate",
            unit="decimal",
            positive=True,
        )
        _validate_range(
            self.terminal_growth_low,
            self.terminal_growth_base,
            self.terminal_growth_high,
            "terminal_growth",
            unit="decimal",
        )
        if (
            self.discount_rate_low.normalized_value
            <= self.terminal_growth_high.normalized_value
        ):
            raise ScenarioInvariantError(
                "DCF_TERMINAL_SPREAD_INVALID",
                "Every discount-rate case must exceed every terminal-growth case.",
            )
        if self.applicability.status in {"allowed", "caution"}:
            if (
                self.applicability.gated_wacc is None
                or self.applicability.gated_terminal_growth is None
                or not _same_dimension(
                    self.discount_rate_base,
                    self.applicability.gated_wacc,
                )
                or not _same_dimension(
                    self.terminal_growth_base,
                    self.applicability.gated_terminal_growth,
                )
                or self.discount_rate_base.normalized_value
                != self.applicability.gated_wacc.normalized_value
                or self.terminal_growth_base.normalized_value
                != self.applicability.gated_terminal_growth.normalized_value
                or self.discount_rate_base.normalized_value
                - self.discount_rate_low.normalized_value
                > Decimal("0.02")
                or self.discount_rate_high.normalized_value
                - self.discount_rate_base.normalized_value
                > Decimal("0.02")
                or self.terminal_growth_base.normalized_value
                - self.terminal_growth_low.normalized_value
                > Decimal("0.01")
                or self.terminal_growth_high.normalized_value
                - self.terminal_growth_base.normalized_value
                > Decimal("0.01")
                or any(
                    not set(self.applicability.gated_wacc.lineage_refs).issubset(
                        quantity.lineage_refs
                    )
                    for quantity in (
                        self.discount_rate_low,
                        self.discount_rate_base,
                        self.discount_rate_high,
                    )
                )
                or any(
                    not set(
                        self.applicability.gated_terminal_growth.lineage_refs
                    ).issubset(quantity.lineage_refs)
                    for quantity in (
                        self.terminal_growth_low,
                        self.terminal_growth_base,
                        self.terminal_growth_high,
                    )
                )
            ):
                raise ScenarioInvariantError(
                    "DCF_GATE_BINDING_INVALID",
                    "DCF base assumptions must equal the gated inputs and sensitivity bounds must stay within the permitted policy.",
                )
        if not isinstance(self.minimum_explicit_periods, int) or self.minimum_explicit_periods < 1:
            raise ScenarioInvariantError(
                "DCF_EXPLICIT_PERIOD_INVALID",
                "DCF minimum_explicit_periods must be a positive integer.",
            )


@dataclass(frozen=True)
class SotpComponentSpec:
    segment_id: str
    metric: str
    multiple_low: ForecastQuantity
    multiple_base: ForecastQuantity
    multiple_high: ForecastQuantity

    def __post_init__(self) -> None:
        if not self.segment_id.strip() or self.metric not in {"ebit", "revenue"}:
            raise ScenarioInvariantError(
                "SOTP_COMPONENT_INVALID",
                "SOTP components require a segment and supported metric.",
            )
        _validate_range(
            self.multiple_low,
            self.multiple_base,
            self.multiple_high,
            f"{self.segment_id}_multiple",
            unit="x",
            positive=True,
        )


@dataclass(frozen=True)
class SotpValuationSpec:
    components: tuple[SotpComponentSpec, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.components, tuple) or not self.components or any(
            not isinstance(item, SotpComponentSpec) for item in self.components
        ):
            raise ScenarioInvariantError(
                "SOTP_COMPONENTS_INVALID",
                "SOTP requires typed component specifications.",
            )
        segment_ids = tuple(item.segment_id for item in self.components)
        if len(segment_ids) != len(set(segment_ids)):
            raise ScenarioInvariantError(
                "SOTP_COMPONENT_DUPLICATE",
                "SOTP may define only one component per segment.",
            )


@dataclass(frozen=True)
class ReverseDcfSpec:
    current_enterprise_value: FinancialQuantity
    discount_rate: ForecastQuantity

    def __post_init__(self) -> None:
        if (
            not isinstance(self.current_enterprise_value, FinancialQuantity)
            or self.current_enterprise_value.kind != "money"
            or self.current_enterprise_value.normalized_value <= 0
        ):
            raise ScenarioInvariantError(
                "REVERSE_DCF_MARKET_VALUE_INVALID",
                "Reverse DCF requires a positive money enterprise value.",
            )
        _validate_model_quantity(
            self.discount_rate,
            unit="decimal",
            field_name="ReverseDcfSpec.discount_rate",
        )
        if self.discount_rate.normalized_value <= 0:
            raise ScenarioInvariantError(
                "REVERSE_DCF_RATE_INVALID",
                "Reverse DCF discount rate must be positive.",
            )


@dataclass(frozen=True, init=False)
class RelativeMultipleSpec:
    """A copied, exact multiple range from the existing evidence-gated seam."""

    method_id: str
    status: MethodStatus
    metric: str
    value_basis: ValueBasis
    multiple_low: ForecastQuantity | None
    multiple_base: ForecastQuantity | None
    multiple_high: ForecastQuantity | None
    evidence_refs: tuple[str, ...]
    diagnostics: tuple[str, ...]
    subject_id: str
    gate_as_of: str
    gate_version: str

    def __init__(self, *_: Any, **__: Any) -> None:
        raise TypeError("Use RelativeMultipleSpec.from_gated_method_result().")

    @classmethod
    def from_gated_method_result(
        cls,
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
            return cls._build(
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
            return cls._build(
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
                scale = exact_decimal_from_legacy(item.get("scale"), "gated multiple scale")
                item_as_of = date.fromisoformat(str(item.get("as_of", "")))
            except (FinancialInvariantError, TypeError, ValueError) as exc:
                raise ScenarioInvariantError(
                    "RELATIVE_GATE_INVALID",
                    "Gated multiple observation has invalid exact dimensions.",
                ) from exc
            item_refs = tuple(item.get("provenance_refs", ()))
            _require_refs(item_refs, "gated multiple provenance", facts_only=True)
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
                _percentile(tuple(values), Decimal("0.25")),
                _percentile(tuple(values), Decimal("0.50")),
                _percentile(tuple(values), Decimal("0.75")),
            )
            try:
                supplied = tuple(
                    exact_decimal_from_legacy(exact.get(key), key)
                    for key in range_keys
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
        return cls._build(
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

    @classmethod
    def _build(
        cls,
        *,
        method_id: str,
        status: MethodStatus,
        metric: str,
        value_basis: ValueBasis,
        multiples: tuple[
            ForecastQuantity | None,
            ForecastQuantity | None,
            ForecastQuantity | None,
        ],
        evidence_refs: tuple[str, ...],
        diagnostics: tuple[str, ...],
        subject_id: str,
        as_of: str,
    ) -> RelativeMultipleSpec:
        instance = object.__new__(cls)
        for field_name, value in {
            "method_id": method_id,
            "status": status,
            "metric": metric,
            "value_basis": value_basis,
            "multiple_low": multiples[0],
            "multiple_base": multiples[1],
            "multiple_high": multiples[2],
            "evidence_refs": evidence_refs,
            "diagnostics": diagnostics,
            "subject_id": subject_id,
            "gate_as_of": as_of,
            "gate_version": "existing-relative-method-gate@1",
        }.items():
            object.__setattr__(instance, field_name, value)
        return instance


@dataclass(frozen=True)
class ValuationPlan:
    present_value_bridge: EquityBridgeSpec
    terminal_value_bridge: EquityBridgeSpec
    dcf: DcfValuationSpec
    sotp: SotpValuationSpec
    reverse_dcf: ReverseDcfSpec
    relative_methods: tuple[RelativeMultipleSpec, ...] = ()

    def __post_init__(self) -> None:
        if self.present_value_bridge.timing != EquityBridgeTiming.OPENING:
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_TIMING_INVALID",
                "present_value_bridge must use opening balance-sheet values.",
            )
        if self.terminal_value_bridge.timing != EquityBridgeTiming.TERMINAL:
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_TIMING_INVALID",
                "terminal_value_bridge must use terminal forecast values.",
            )
        if not isinstance(self.relative_methods, tuple) or any(
            not isinstance(item, RelativeMultipleSpec)
            for item in self.relative_methods
        ):
            raise ScenarioInvariantError(
                "VALUATION_METHOD_TYPE_INVALID",
                "relative_methods must come from the gated relative adapter.",
            )
        method_ids = tuple(item.method_id for item in self.relative_methods)
        if len(method_ids) != len(set(method_ids)):
            raise ScenarioInvariantError(
                "VALUATION_METHOD_DUPLICATE",
                "Valuation method identifiers must be unique.",
            )


@dataclass(frozen=True)
class DeterministicScenarioRequest:
    base_forecast_request: ForecastRequest
    scenarios: tuple[ScenarioDefinition, ...]
    valuation_plan: ValuationPlan

    def __post_init__(self) -> None:
        if not isinstance(self.base_forecast_request, ForecastRequest):
            raise ScenarioInvariantError(
                "SCENARIO_FORECAST_REQUEST_INVALID",
                "base_forecast_request must be a ForecastRequest.",
            )
        if not isinstance(self.scenarios, tuple) or any(
            not isinstance(item, ScenarioDefinition) for item in self.scenarios
        ):
            raise ScenarioInvariantError(
                "SCENARIO_SET_TYPE_INVALID",
                "scenarios must contain ScenarioDefinition values.",
            )


@dataclass(frozen=True)
class ValuationAssumption:
    name: str
    quantity: ForecastQuantity

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "quantity": self.quantity.to_dict()}


@dataclass(frozen=True)
class ValuationSensitivity:
    name: str
    low: ForecastQuantity
    base: ForecastQuantity
    high: ForecastQuantity

    def __post_init__(self) -> None:
        if not _same_dimension(self.low, self.base, self.high):
            raise ScenarioInvariantError(
                "VALUATION_SENSITIVITY_DIMENSION_MISMATCH",
                "Sensitivity bounds must share one exact dimension and time basis.",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "low": self.low.to_dict(),
            "base": self.base.to_dict(),
            "high": self.high.to_dict(),
        }


@dataclass(frozen=True)
class ValuationPoint:
    basis_value: FinancialQuantity
    equity_value: FinancialQuantity
    per_share_value: FinancialQuantity
    bridge_trace: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "basis_value": self.basis_value.to_dict(),
            "equity_value": self.equity_value.to_dict(),
            "per_share_value": self.per_share_value.to_dict(),
            "bridge_trace": [dict(item) for item in self.bridge_trace],
        }


@dataclass(frozen=True)
class ConditionalValueRange:
    low: ValuationPoint
    base: ValuationPoint
    high: ValuationPoint

    @property
    def basis_value_low(self) -> Decimal:
        return self.low.basis_value.normalized_value

    @property
    def basis_value_base(self) -> Decimal:
        return self.base.basis_value.normalized_value

    @property
    def basis_value_high(self) -> Decimal:
        return self.high.basis_value.normalized_value

    @property
    def equity_value_low(self) -> Decimal:
        return self.low.equity_value.normalized_value

    @property
    def equity_value_base(self) -> Decimal:
        return self.base.equity_value.normalized_value

    @property
    def equity_value_high(self) -> Decimal:
        return self.high.equity_value.normalized_value

    @property
    def per_share_low(self) -> Decimal:
        return self.low.per_share_value.normalized_value

    @property
    def per_share_base(self) -> Decimal:
        return self.base.per_share_value.normalized_value

    @property
    def per_share_high(self) -> Decimal:
        return self.high.per_share_value.normalized_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "low": self.low.to_dict(),
            "base": self.base.to_dict(),
            "high": self.high.to_dict(),
        }


@dataclass(frozen=True)
class ScenarioMethodResult:
    method_id: str
    status: MethodStatus
    applicability: str
    value_basis: ValueBasis
    horizon: str
    assumptions: tuple[ValuationAssumption, ...]
    formula_version: str
    conditional_value_range: ConditionalValueRange | None
    sensitivity: tuple[ValuationSensitivity, ...]
    diagnostics: tuple[str, ...]
    lineage_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "status": self.status,
            "applicability": self.applicability,
            "value_basis": self.value_basis,
            "horizon": self.horizon,
            "assumptions": [item.to_dict() for item in self.assumptions],
            "formula_version": self.formula_version,
            "conditional_value_range": (
                self.conditional_value_range.to_dict()
                if self.conditional_value_range is not None
                else None
            ),
            "sensitivity": [item.to_dict() for item in self.sensitivity],
            "diagnostics": list(self.diagnostics),
            "lineage_refs": list(self.lineage_refs),
        }


@dataclass(frozen=True)
class ScenarioValuationResult:
    scenario_id: str
    role: ScenarioRole
    label: str
    probability_evidence: ScenarioProbabilityEvidence | None
    rationale_refs: tuple[str, ...]
    forecast_graph: ForecastGraph
    methods: tuple[ScenarioMethodResult, ...]

    @property
    def probability(self) -> Decimal | None:
        if self.probability_evidence is None:
            return None
        return self.probability_evidence.probability.normalized_value

    def method(self, method_id: str) -> ScenarioMethodResult:
        matches = [item for item in self.methods if item.method_id == method_id]
        if len(matches) != 1:
            raise KeyError(method_id)
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "role": self.role.value,
            "label": self.label,
            "probability_evidence": (
                self.probability_evidence.to_dict()
                if self.probability_evidence is not None
                else None
            ),
            "rationale_refs": list(self.rationale_refs),
            "forecast_graph": self.forecast_graph.to_dict(),
            "methods": [item.to_dict() for item in self.methods],
        }


@dataclass(frozen=True)
class WeightedMethodRange:
    method_id: str
    value_basis: ValueBasis
    horizon: str
    probability_sum_quantity: ForecastQuantity
    per_share_low_quantity: FinancialQuantity
    per_share_base_quantity: FinancialQuantity
    per_share_high_quantity: FinancialQuantity
    lineage_refs: tuple[str, ...]

    @property
    def probability_sum(self) -> Decimal:
        return self.probability_sum_quantity.normalized_value

    @property
    def per_share_low(self) -> Decimal:
        return self.per_share_low_quantity.normalized_value

    @property
    def per_share_base(self) -> Decimal:
        return self.per_share_base_quantity.normalized_value

    @property
    def per_share_high(self) -> Decimal:
        return self.per_share_high_quantity.normalized_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "value_basis": self.value_basis,
            "horizon": self.horizon,
            "probability_sum": self.probability_sum_quantity.to_dict(),
            "per_share_low": self.per_share_low_quantity.to_dict(),
            "per_share_base": self.per_share_base_quantity.to_dict(),
            "per_share_high": self.per_share_high_quantity.to_dict(),
            "lineage_refs": list(self.lineage_refs),
        }


@dataclass(frozen=True)
class DeterministicScenarioResult:
    probability_mode: ProbabilityMode
    scenarios: tuple[ScenarioValuationResult, ...]
    weighted_method_ranges: tuple[WeightedMethodRange, ...]
    weighting_diagnostics: tuple[str, ...]
    cross_method_composite: None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "probability_mode": self.probability_mode,
            "scenarios": [item.to_dict() for item in self.scenarios],
            "weighted_method_ranges": [
                item.to_dict() for item in self.weighted_method_ranges
            ],
            "weighting_diagnostics": list(self.weighting_diagnostics),
            "cross_method_composite": None,
        }


class _MethodBlocked(ValueError):
    pass


MethodCalculation = Callable[
    [],
    tuple[
        ConditionalValueRange,
        tuple[ValuationAssumption, ...],
        tuple[ValuationSensitivity, ...],
        tuple[str, ...],
        tuple[str, ...],
    ],
]


class ScenarioValuationEngine:
    """Reforecast coherent scenarios and triangulate gated methods independently."""

    DCF_FORMULA_VERSION = "fcff_dcf_act365@3"
    SOTP_FORMULA_VERSION = "sotp_segment_multiple@2"
    REVERSE_DCF_FORMULA_VERSION = "reverse_dcf_terminal_growth_act365@3"
    RELATIVE_FORMULA_VERSION = "gated_relative_multiple@2"

    def run(self, request: DeterministicScenarioRequest) -> DeterministicScenarioResult:
        with valuation_decimal_context():
            self._validate_scenarios(request)
            probability_mode = self._probability_mode(request.scenarios)
            results: list[ScenarioValuationResult] = []
            for scenario in request.scenarios:
                graph = ForecastEngine().build(
                    replace(
                        request.base_forecast_request,
                        assumption_overrides=scenario.driver_overrides,
                    )
                )
                methods = self._run_methods(
                    graph,
                    request.valuation_plan,
                    request.base_forecast_request,
                )
                results.append(
                    ScenarioValuationResult(
                        scenario_id=scenario.scenario_id,
                        role=scenario.role,
                        label=scenario.label,
                        probability_evidence=scenario.probability_evidence,
                        rationale_refs=scenario.rationale_refs,
                        forecast_graph=graph,
                        methods=methods,
                    )
                )
            weighted: tuple[WeightedMethodRange, ...] = ()
            diagnostics: tuple[str, ...] = ()
            if probability_mode == "evidence_weighted":
                weighted, diagnostics = self._weight_methods(tuple(results))
            return DeterministicScenarioResult(
                probability_mode=probability_mode,
                scenarios=tuple(results),
                weighted_method_ranges=weighted,
                weighting_diagnostics=diagnostics,
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
            if len(actual_keys) != len(set(actual_keys)) or set(actual_keys) != expected_keys:
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
            scenario.probability_evidence is not None
            for scenario in request.scenarios
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
            observed = facts.get(
                evidence.observed_count_fact_ref.removeprefix("Fact:")
            )
            sample = facts.get(
                evidence.sample_size_fact_ref.removeprefix("Fact:")
            )
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

    def _validate_bridge_evidence(
        self,
        bridge: EquityBridgeSpec,
        facts: Mapping[str, Any],
        *,
        subject_id: str,
        as_of: str,
    ) -> None:
        quantities = {
            "diluted_shares": bridge.diluted_shares,
            "lease_debt": bridge.lease_debt,
            "preferred_stock": bridge.preferred_stock,
            "minority_interest": bridge.minority_interest,
            "pension_deficit": bridge.pension_deficit,
            "associates_jv_value": bridge.associates_jv_value,
            "non_operating_assets": bridge.non_operating_assets,
        }
        for field_name, quantity in quantities.items():
            fact_refs = tuple(
                ref for ref in quantity.provenance_refs if ref.startswith("Fact:")
            )
            assumption_refs = tuple(
                ref
                for ref in quantity.provenance_refs
                if ref.startswith("Assumption:")
            )
            resolved = tuple(
                facts.get(ref.removeprefix("Fact:")) for ref in fact_refs
            )
            if (
                not fact_refs
                or any(fact is None for fact in resolved)
                or any(
                    fact.subject_id != subject_id
                    or fact.scope != "company"
                    or fact.metric_id != field_name
                    or not fact.official
                    or date.fromisoformat(fact.available_at)
                    > date.fromisoformat(as_of)
                    for fact in resolved
                )
            ):
                raise _MethodBlocked(
                    f"VALUATION_BRIDGE_EVIDENCE_INVALID: {field_name} must resolve through an official frozen company fact.",
                )
            if bridge.timing == EquityBridgeTiming.OPENING and assumption_refs:
                raise _MethodBlocked(
                    f"VALUATION_BRIDGE_EVIDENCE_INVALID: opening {field_name} cannot be replaced by an uncalibrated assumption.",
                )
            if bridge.timing == EquityBridgeTiming.OPENING and not any(
                fact.value == quantity.normalized_value
                and fact.unit == quantity.unit
                and fact.currency == quantity.currency
                and fact.period == quantity.period
                for fact in resolved
            ):
                raise _MethodBlocked(
                    f"VALUATION_BRIDGE_EVIDENCE_INVALID: opening {field_name} does not match its exact snapshot fact.",
                )
            expected_roll_forward = (
                f"Assumption:bridge_roll_forward:no_change:{field_name}"
            )
            if bridge.timing == EquityBridgeTiming.TERMINAL and (
                assumption_refs != (expected_roll_forward,)
            ):
                raise _MethodBlocked(
                    f"VALUATION_BRIDGE_EVIDENCE_INVALID: terminal {field_name} requires one explicit no-change roll-forward assumption.",
                )
            if bridge.timing == EquityBridgeTiming.TERMINAL and not any(
                fact.value == quantity.normalized_value
                and fact.currency == quantity.currency
                for fact in resolved
            ):
                raise _MethodBlocked(
                    f"VALUATION_BRIDGE_EVIDENCE_INVALID: terminal {field_name} no-change roll-forward does not reconcile to its opening fact."
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

    def _run_methods(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
    ) -> tuple[ScenarioMethodResult, ...]:
        periods = self._periods(graph)
        dcf_horizon = (
            f"valuation_as_of={self._as_of(graph)};cash_flows={periods[0]}..{periods[-1]}"
        )
        terminal_horizon = f"terminal_period={periods[-1]}"
        present_horizon = f"valuation_as_of={self._as_of(graph)}"
        methods = [
            self._isolate_method(
                "fcff_dcf",
                (
                    f"{plan.dcf.applicability.status}: "
                    f"{plan.dcf.applicability.reason}"
                ),
                "enterprise_value",
                dcf_horizon,
                graph,
                self.DCF_FORMULA_VERSION,
                lambda: self._dcf(graph, plan, base_request),
                _merge_refs(
                    plan.dcf.applicability.evidence_refs,
                    plan.dcf.discount_rate_base.lineage_refs,
                    plan.dcf.terminal_growth_base.lineage_refs,
                    plan.present_value_bridge.provenance_refs,
                ),
            ),
            self._isolate_method(
                "sotp",
                "Applicable because every modeled segment has a gated terminal metric.",
                "enterprise_value",
                terminal_horizon,
                graph,
                self.SOTP_FORMULA_VERSION,
                lambda: self._sotp(graph, plan, base_request),
                _merge_refs(
                    *(
                        _merge_refs(
                            component.multiple_low.lineage_refs,
                            component.multiple_base.lineage_refs,
                            component.multiple_high.lineage_refs,
                        )
                        for component in plan.sotp.components
                    ),
                    plan.terminal_value_bridge.provenance_refs,
                ),
            ),
            self._isolate_method(
                "reverse_dcf",
                "Expectation diagnostic against observed present enterprise value.",
                "enterprise_value",
                present_horizon,
                graph,
                self.REVERSE_DCF_FORMULA_VERSION,
                lambda: self._reverse_dcf(graph, plan, base_request),
                _merge_refs(
                    plan.reverse_dcf.current_enterprise_value.provenance_refs,
                    plan.reverse_dcf.discount_rate.lineage_refs,
                    plan.present_value_bridge.provenance_refs,
                ),
            ),
        ]
        methods.extend(
            self._relative(graph, plan, spec, terminal_horizon, base_request)
            for spec in plan.relative_methods
        )
        return tuple(methods)

    def _isolate_method(
        self,
        method_id: str,
        applicability: str,
        value_basis: ValueBasis,
        horizon: str,
        graph: ForecastGraph,
        formula_version: str,
        calculate: MethodCalculation,
        blocked_lineage_refs: tuple[str, ...] = (),
    ) -> ScenarioMethodResult:
        try:
            value_range, assumptions, sensitivity, lineage_refs, diagnostics = calculate()
            return ScenarioMethodResult(
                method_id=method_id,
                status="ready",
                applicability=applicability,
                value_basis=value_basis,
                horizon=horizon,
                assumptions=assumptions,
                formula_version=formula_version,
                conditional_value_range=value_range,
                sensitivity=sensitivity,
                diagnostics=diagnostics,
                lineage_refs=lineage_refs,
            )
        except (FinancialInvariantError, ForecastInvariantError, _MethodBlocked) as exc:
            return ScenarioMethodResult(
                method_id=method_id,
                status="blocked",
                applicability=applicability,
                value_basis=value_basis,
                horizon=horizon,
                assumptions=(),
                formula_version=formula_version,
                conditional_value_range=None,
                sensitivity=(),
                diagnostics=(str(exc),),
                lineage_refs=_merge_refs(
                    blocked_lineage_refs,
                    self._forecast_lineage(graph),
                ),
            )

    def _validate_method_bridge(
        self,
        graph: ForecastGraph,
        bridge: EquityBridgeSpec,
        base_request: ForecastRequest,
    ) -> None:
        expected_period = (
            base_request.data_snapshot.company_opening_balance_sheet.cash.period
            if bridge.timing == EquityBridgeTiming.OPENING
            else self._periods(graph)[-1]
        )
        if (
            bridge.balance_sheet_period != expected_period
            or bridge.diluted_shares.as_of != self._as_of(graph)
        ):
            raise _MethodBlocked(
                "VALUATION_HORIZON_MISMATCH: equity bridge does not bind the method horizon and frozen as-of."
            )
        self._validate_bridge_evidence(
            bridge,
            {
                fact.fact_id: fact
                for fact in base_request.data_snapshot.facts
            },
            subject_id=graph.security_id,
            as_of=self._as_of(graph),
        )

    def _validate_observed_enterprise_value(
        self,
        graph: ForecastGraph,
        spec: ReverseDcfSpec,
        base_request: ForecastRequest,
    ) -> None:
        observed_value = spec.current_enterprise_value
        facts = {
            fact.fact_id: fact
            for fact in base_request.data_snapshot.facts
        }
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
                <= date.fromisoformat(self._as_of(graph))
                for fact in observed_facts
            )
        ):
            raise _MethodBlocked(
                "REVERSE_DCF_EVIDENCE_INVALID: observed enterprise value must bind an exact PIT snapshot fact."
            )
        if (
            observed_value.period != self._as_of(graph)
            or observed_value.as_of != self._as_of(graph)
        ):
            raise _MethodBlocked(
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
        self._validate_method_bridge(
            graph,
            plan.present_value_bridge,
            base_request,
        )
        terminal_period = self._periods(graph)[-1]
        if (
            spec.applicability.subject_id != graph.security_id
            or spec.applicability.as_of != self._as_of(graph)
            or spec.discount_rate_base.as_of != self._as_of(graph)
            or spec.discount_rate_base.period != self._as_of(graph)
            or spec.terminal_growth_base.as_of != self._as_of(graph)
            or spec.terminal_growth_base.period != terminal_period
        ):
            raise _MethodBlocked(
                "DCF_GATE_BINDING_INVALID: DCF gate and assumptions do not bind the requested subject and time basis."
            )
        if spec.applicability.status == "blocked":
            raise _MethodBlocked(
                f"DCF applicability gate blocked this method: {spec.applicability.reason}"
            )
        periods = self._periods(graph)
        if len(periods) < spec.minimum_explicit_periods:
            raise _MethodBlocked(
                f"DCF requires at least {spec.minimum_explicit_periods} explicit forecast periods."
            )
        times = self._discount_times(periods, self._as_of(graph))
        fcff = tuple(graph.quantity(f"valuation.fcff.{period}") for period in periods)
        if fcff[-1].normalized_value <= 0:
            raise _MethodBlocked("DCF requires positive terminal FCFF.")

        def enterprise_value(
            discount_rate: ForecastQuantity,
            growth: ForecastQuantity,
        ) -> tuple[Decimal, Decimal]:
            rate = discount_rate.normalized_value
            growth_value = growth.normalized_value
            if rate <= growth_value:
                raise _MethodBlocked("DCF terminal spread must be positive.")
            explicit = sum(
                (
                    quantity.normalized_value
                    / ((Decimal("1") + rate) ** timing)
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
        lineage = _merge_refs(
            spec.applicability.evidence_refs,
            spec.discount_rate_low.lineage_refs,
            spec.discount_rate_base.lineage_refs,
            spec.discount_rate_high.lineage_refs,
            spec.terminal_growth_low.lineage_refs,
            spec.terminal_growth_base.lineage_refs,
            spec.terminal_growth_high.lineage_refs,
            *(item.lineage_refs for item in fcff),
        )
        value_range = self._bridge_range(
            graph,
            plan.present_value_bridge,
            "enterprise_value",
            values,
            self.DCF_FORMULA_VERSION,
            basis_period=self._as_of(graph),
            basis_refs=lineage,
        )
        terminal_share = self._model_quantity(
            cases[1][1],
            unit="decimal",
            period=self._as_of(graph),
            as_of=self._as_of(graph),
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
            diagnostics.append("DCF applicability gate permits this method only as a cross-check.")
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
        self._validate_method_bridge(
            graph,
            plan.terminal_value_bridge,
            base_request,
        )
        plan_segments = {item.segment_id for item in plan.sotp.components}
        modeled_segments = set(base_request.security.segment_ids)
        if plan_segments != modeled_segments:
            raise _MethodBlocked(
                "SOTP_COMPONENT_COVERAGE_INVALID: SOTP must cover every forecast segment exactly once."
            )
        final_period = self._periods(graph)[-1]
        values = [Decimal("0"), Decimal("0"), Decimal("0")]
        assumptions: list[ValuationAssumption] = []
        sensitivity: list[ValuationSensitivity] = []
        lineage: tuple[str, ...] = ()
        for component in plan.sotp.components:
            quantity = graph.quantity(
                f"{component.segment_id}.{component.metric}.{final_period}"
            )
            if quantity.normalized_value <= 0:
                raise _MethodBlocked(
                    f"SOTP component {component.segment_id} has a non-positive metric."
                )
            multiples = (
                component.multiple_low,
                component.multiple_base,
                component.multiple_high,
            )
            if any(
                item.period != final_period or item.as_of != self._as_of(graph)
                for item in multiples
            ):
                raise _MethodBlocked(
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
            lineage = _merge_refs(
                lineage,
                quantity.lineage_refs,
                *(item.lineage_refs for item in multiples),
            )
        value_range = self._bridge_range(
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
        self._validate_method_bridge(
            graph,
            plan.present_value_bridge,
            base_request,
        )
        self._validate_observed_enterprise_value(
            graph,
            spec,
            base_request,
        )
        periods = self._periods(graph)
        if (
            spec.discount_rate.period != self._as_of(graph)
            or spec.discount_rate.as_of != self._as_of(graph)
        ):
            raise _MethodBlocked(
                "Reverse DCF discount rate must bind the valuation as-of date."
            )
        times = self._discount_times(periods, self._as_of(graph))
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
            raise _MethodBlocked(
                "Observed enterprise value cannot support a finite terminal-growth solution."
            )
        terminal_at_horizon = remaining_present_value * (
            (Decimal("1") + rate) ** times[-1]
        )
        implied_growth = (
            terminal_at_horizon * rate - fcff[-1].normalized_value
        ) / (terminal_at_horizon + fcff[-1].normalized_value)
        if not Decimal("-1") < implied_growth < rate:
            raise _MethodBlocked(
                "Implied terminal growth is outside the finite DCF solution domain."
            )
        lineage = _merge_refs(
            spec.current_enterprise_value.provenance_refs,
            spec.discount_rate.lineage_refs,
            *(item.lineage_refs for item in fcff),
        )
        observed = spec.current_enterprise_value.normalized_value
        value_range = self._bridge_range(
            graph,
            plan.present_value_bridge,
            "enterprise_value",
            (observed, observed, observed),
            self.REVERSE_DCF_FORMULA_VERSION,
            basis_period=self._as_of(graph),
            basis_refs=spec.current_enterprise_value.provenance_refs,
        )
        implied = self._model_quantity(
            implied_growth,
            unit="decimal",
            period=self._periods(graph)[-1],
            as_of=self._as_of(graph),
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
    ) -> ScenarioMethodResult:
        applicability = (
            f"{spec.status}: copied from {spec.gate_version}; no caller-declared multiples are accepted."
        )
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
            self._validate_method_bridge(
                graph,
                plan.terminal_value_bridge,
                base_request,
            )
            if (
                spec.subject_id != graph.security_id
                or spec.gate_as_of != self._as_of(graph)
            ):
                raise _MethodBlocked(
                    "RELATIVE_GATE_BINDING_INVALID: relative gate does not bind the requested subject and as-of."
                )
            final_period = self._periods(graph)[-1]
            quantity = graph.quantity(f"company.{spec.metric}.{final_period}")
            if quantity.normalized_value <= 0:
                raise _MethodBlocked(
                    f"Relative method {spec.method_id} has a non-positive metric."
                )
            multiples = (spec.multiple_low, spec.multiple_base, spec.multiple_high)
            if any(item is None for item in multiples):
                raise _MethodBlocked("Ready relative method lost its gated multiple range.")
            values = tuple(
                quantity.normalized_value * item.normalized_value for item in multiples
            )
            lineage = _merge_refs(
                spec.evidence_refs,
                quantity.lineage_refs,
                *(item.lineage_refs for item in multiples),
            )
            value_range = self._bridge_range(
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

        return self._isolate_method(
            spec.method_id,
            applicability,
            spec.value_basis,
            horizon,
            graph,
            self.RELATIVE_FORMULA_VERSION,
            calculate,
            _merge_refs(
                spec.evidence_refs,
                plan.terminal_value_bridge.provenance_refs,
            ),
        )

    def _bridge_range(
        self,
        graph: ForecastGraph,
        spec: EquityBridgeSpec,
        value_basis: ValueBasis,
        values: tuple[Decimal, Decimal, Decimal],
        formula_version: str,
        *,
        basis_period: str,
        basis_refs: tuple[str, ...],
    ) -> ConditionalValueRange:
        refs = _merge_refs(
            basis_refs,
            (f"Assumption:formula:{formula_version}",),
        )
        points = tuple(
            self._bridge_one(
                graph,
                spec,
                value_basis,
                value,
                basis_period,
                refs,
            )
            for value in values
        )
        return ConditionalValueRange(
            low=points[0],
            base=points[1],
            high=points[2],
        )

    def _bridge_one(
        self,
        graph: ForecastGraph,
        spec: EquityBridgeSpec,
        value_basis: ValueBasis,
        value: Decimal,
        basis_period: str,
        refs: tuple[str, ...],
    ) -> ValuationPoint:
        cash, debt = self._bridge_cash_debt(graph, spec)
        currency = cash.currency
        as_of = cash.as_of
        basis = FinancialQuantity(
            value=value,
            unit=currency,
            scale=Decimal("1"),
            currency=currency,
            period=basis_period,
            as_of=as_of,
            provenance_refs=refs,
            kind="money",
        )
        if value_basis == "enterprise_value":
            adjustments: dict[str, FinancialQuantity | None] = {
                "cash": cash,
                "debt": debt,
                "lease_debt": self._normalized_financial(spec.lease_debt),
                "preferred_stock": self._normalized_financial(spec.preferred_stock),
                "minority_interest": self._normalized_financial(spec.minority_interest),
                "pension_deficit": self._normalized_financial(spec.pension_deficit),
                "associates_jv_value": self._normalized_financial(spec.associates_jv_value),
                "non_operating_assets": self._normalized_financial(spec.non_operating_assets),
            }
        else:
            adjustments = {
                "cash": None,
                "debt": None,
                "lease_debt": None,
                "preferred_stock": None,
                "minority_interest": None,
                "pension_deficit": None,
                "associates_jv_value": None,
                "non_operating_assets": None,
            }
        result = EquityBridge(
            basis_value=basis,
            value_basis=value_basis,
            balance_sheet_period=spec.balance_sheet_period,
            valuation_as_of=as_of,
            output_currency=spec.output_currency or currency,
            diluted_shares=self._normalized_financial(spec.diluted_shares),
            **adjustments,
        ).evaluate()
        return self._valuation_point(basis, result)

    def _bridge_cash_debt(
        self,
        graph: ForecastGraph,
        spec: EquityBridgeSpec,
    ) -> tuple[FinancialQuantity, FinancialQuantity]:
        period = spec.balance_sheet_period
        if spec.timing == EquityBridgeTiming.OPENING:
            cash_id = f"company.baseline.cash.{period}"
            debt_id = f"company.baseline.debt.{period}"
        else:
            cash_id = f"company.ending_cash.{period}"
            debt_id = f"company.debt.{period}"
        return (
            self._financial_from_forecast(graph.quantity(cash_id)),
            self._financial_from_forecast(graph.quantity(debt_id)),
        )

    def _valuation_point(
        self,
        basis: FinancialQuantity,
        result: EquityBridgeResult,
    ) -> ValuationPoint:
        refs = tuple(
            dict.fromkeys(
                ref
                for step in result.trace
                for ref in step.get("ref_ids", ())
            )
        )
        equity = FinancialQuantity(
            value=result.equity_value,
            unit=result.output_currency,
            scale=Decimal("1"),
            currency=result.output_currency,
            period=basis.period,
            as_of=result.valuation_as_of,
            provenance_refs=refs,
            kind="money",
        )
        per_share = FinancialQuantity(
            value=result.per_share_value,
            unit=f"{result.output_currency}/share",
            scale=Decimal("1"),
            currency=result.output_currency,
            period=basis.period,
            as_of=result.valuation_as_of,
            provenance_refs=refs,
            kind="per_share",
        )
        return ValuationPoint(
            basis_value=basis,
            equity_value=equity,
            per_share_value=per_share,
            bridge_trace=result.trace,
        )

    def _financial_from_forecast(self, quantity: ForecastQuantity) -> FinancialQuantity:
        return FinancialQuantity(
            value=quantity.normalized_value,
            unit=quantity.currency,
            scale=Decimal("1"),
            currency=quantity.currency,
            period=quantity.period,
            as_of=quantity.as_of,
            provenance_refs=quantity.lineage_refs,
            kind="money",
        )

    def _normalized_financial(
        self,
        quantity: FinancialQuantity,
    ) -> FinancialQuantity:
        if quantity.kind == "money":
            unit = quantity.currency
        elif quantity.kind == "shares":
            unit = "shares"
        else:
            unit = quantity.unit
        return FinancialQuantity(
            value=quantity.normalized_value,
            unit=unit,
            scale=Decimal("1"),
            currency=quantity.currency,
            period=quantity.period,
            as_of=quantity.as_of,
            provenance_refs=quantity.provenance_refs,
            kind=quantity.kind,
        )

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
            lineage = _merge_refs(
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
            probability_sum = self._model_quantity(
                sum(probabilities, Decimal("0")),
                unit="decimal",
                period=probability_evidence[0].probability.period,
                as_of=probability_evidence[0].probability.as_of,
                refs=_merge_refs(
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

    def _discount_times(
        self,
        periods: tuple[str, ...],
        valuation_as_of: str,
    ) -> tuple[Decimal, ...]:
        try:
            valuation_date = date.fromisoformat(valuation_as_of)
        except (TypeError, ValueError) as exc:
            raise ForecastInvariantError(
                "FORECAST_AS_OF_INVALID",
                "DCF valuation_as_of must be an ISO date.",
            ) from exc
        period_ends = tuple(self._period_end(period) for period in periods)
        times = tuple(
            Decimal((period_end - valuation_date).days) / Decimal("365")
            for period_end in period_ends
        )
        if (
            any(value <= 0 for value in times)
            or tuple(sorted(times)) != times
            or len(times) != len(set(times))
        ):
            raise ForecastInvariantError(
                "FORECAST_PERIODS_INVALID",
                "DCF periods must map to increasing positive discount times.",
            )
        return times

    def _period_end(self, period: str) -> date:
        try:
            return date.fromisoformat(period)
        except (TypeError, ValueError):
            pass
        text = period.upper().replace(" ", "")
        year_match = re.search(r"(19\d{2}|20\d{2})", text)
        if year_match is None:
            raise ForecastInvariantError(
                "FORECAST_PERIODS_INVALID",
                f"Cannot derive exact DCF timing from period {period!r}.",
            )
        year = int(year_match.group(1))
        if "Q1" in text or "0331" in text:
            month, day = 3, 31
        elif "Q2" in text or "H1" in text or "1H" in text or "0630" in text:
            month, day = 6, 30
        elif "Q3" in text or "0930" in text:
            month, day = 9, 30
        else:
            month, day = 12, 31
        return date(year, month, day)

    def _model_quantity(
        self,
        value: Decimal,
        *,
        unit: str,
        period: str,
        as_of: str,
        refs: tuple[str, ...],
    ) -> ForecastQuantity:
        return ForecastQuantity(
            value=value,
            unit=unit,
            scale=Decimal("1"),
            currency="N/A",
            period=period,
            as_of=as_of,
            lineage_refs=refs,
        )

    def _periods(self, graph: ForecastGraph) -> tuple[str, ...]:
        periods = tuple(
            node.quantity.period
            for node in graph.nodes
            if node.node_id.startswith("valuation.fcff.")
        )
        if not periods:
            raise ForecastInvariantError(
                "FORECAST_VALUATION_INPUT_MISSING",
                "Forecast graph has no gated FCFF valuation inputs.",
            )
        return periods

    def _as_of(self, graph: ForecastGraph) -> str:
        return graph.quantity(f"valuation.fcff.{self._periods(graph)[0]}").as_of

    def _forecast_lineage(self, graph: ForecastGraph) -> tuple[str, ...]:
        return _merge_refs(
            *(
                node.lineage_refs
                for node in graph.nodes
                if node.node_id.startswith("valuation.fcff.")
            )
        )
