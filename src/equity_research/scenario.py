from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields, replace
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Literal, Mapping, cast

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
    CompanyArchetype,
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


def _validate_money_range(
    low: FinancialQuantity,
    base: FinancialQuantity,
    high: FinancialQuantity,
    field_name: str,
    *,
    nonnegative: bool = False,
) -> None:
    quantities = (low, base, high)
    if (
        any(not isinstance(item, FinancialQuantity) for item in quantities)
        or any(item.kind != "money" for item in quantities)
        or len(
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
        )
        != 1
    ):
        raise ScenarioInvariantError(
            "VALUATION_MONEY_RANGE_DIMENSION_MISMATCH",
            f"{field_name} requires money quantities on one exact dimension and time basis.",
        )
    values = tuple(item.normalized_value for item in quantities)
    if (
        values[0] > values[1]
        or values[1] > values[2]
        or (nonnegative and values[0] < 0)
    ):
        raise ScenarioInvariantError(
            "VALUATION_MONEY_RANGE_INVALID",
            f"{field_name} must be ordered low <= base <= high"
            + (" and nonnegative." if nonnegative else "."),
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


@dataclass(frozen=True)
class CommodityCurvePoint:
    segment_id: str
    period: str
    price_low: ForecastQuantity
    price_base: ForecastQuantity
    price_high: ForecastQuantity

    def __post_init__(self) -> None:
        if not self.segment_id.strip() or not self.period.strip():
            raise ScenarioInvariantError(
                "COMMODITY_CURVE_IDENTITY_INVALID",
                "Commodity curve points require a segment and period.",
            )
        prices = (self.price_low, self.price_base, self.price_high)
        if any(not isinstance(item, ForecastQuantity) for item in prices):
            raise ScenarioInvariantError(
                "COMMODITY_CURVE_QUANTITY_INVALID",
                "Commodity curve prices must be ForecastQuantity values.",
            )
        dimensions = {
            (item.unit, item.scale, item.currency, item.period, item.as_of)
            for item in prices
        }
        values = tuple(item.normalized_value for item in prices)
        if (
            len(dimensions) != 1
            or self.price_base.period != self.period
            or self.price_base.scale != Decimal("1")
            or self.price_base.currency in {"", "N/A"}
            or self.price_base.unit
            != f"{self.price_base.currency}/unit"
            or values[0] <= 0
            or values[0] > values[1]
            or values[1] > values[2]
        ):
            raise ScenarioInvariantError(
                "COMMODITY_CURVE_DIMENSION_INVALID",
                "Commodity prices must be positive ordered currency/unit quantities on one exact time basis.",
            )
        for field_name, quantity in (
            ("price_low", self.price_low),
            ("price_base", self.price_base),
            ("price_high", self.price_high),
        ):
            _require_refs(
                quantity.lineage_refs,
                f"CommodityCurvePoint.{field_name}",
                facts_only=True,
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.price_low.lineage_refs,
            self.price_base.lineage_refs,
            self.price_high.lineage_refs,
        )


@dataclass(frozen=True)
class ResourcePeriodSpec:
    period: str
    production_low: ForecastQuantity
    production_base: ForecastQuantity
    production_high: ForecastQuantity
    unit_cost_low: ForecastQuantity
    unit_cost_base: ForecastQuantity
    unit_cost_high: ForecastQuantity
    operating_expense_low: FinancialQuantity
    operating_expense_base: FinancialQuantity
    operating_expense_high: FinancialQuantity
    maintenance_capex_low: FinancialQuantity
    maintenance_capex_base: FinancialQuantity
    maintenance_capex_high: FinancialQuantity
    tax_rate: ForecastQuantity

    def __post_init__(self) -> None:
        if not self.period.strip():
            raise ScenarioInvariantError(
                "RESOURCE_PERIOD_INVALID",
                "Resource schedules require a period.",
            )
        production = (
            self.production_low,
            self.production_base,
            self.production_high,
        )
        costs = (self.unit_cost_low, self.unit_cost_base, self.unit_cost_high)
        operating_expenses = (
            self.operating_expense_low,
            self.operating_expense_base,
            self.operating_expense_high,
        )
        capex = (
            self.maintenance_capex_low,
            self.maintenance_capex_base,
            self.maintenance_capex_high,
        )
        if (
            any(not isinstance(item, ForecastQuantity) for item in production)
            or len(
                {
                    (item.unit, item.scale, item.currency, item.period, item.as_of)
                    for item in production
                }
            )
            != 1
            or self.production_base.period != self.period
            or self.production_base.currency != "N/A"
            or self.production_low.normalized_value <= 0
            or self.production_low.normalized_value
            > self.production_base.normalized_value
            or self.production_base.normalized_value
            > self.production_high.normalized_value
        ):
            raise ScenarioInvariantError(
                "RESOURCE_PRODUCTION_RANGE_INVALID",
                "Resource production must be an ordered physical range on one exact time basis.",
            )
        if (
            any(not isinstance(item, ForecastQuantity) for item in costs)
            or len(
                {
                    (item.unit, item.scale, item.currency, item.period, item.as_of)
                    for item in costs
                }
            )
            != 1
            or self.unit_cost_base.period != self.period
            or self.unit_cost_base.currency in {"", "N/A"}
            or self.unit_cost_base.unit
            != f"{self.unit_cost_base.currency}/unit"
            or self.unit_cost_low.normalized_value <= 0
            or self.unit_cost_low.normalized_value
            > self.unit_cost_base.normalized_value
            or self.unit_cost_base.normalized_value
            > self.unit_cost_high.normalized_value
        ):
            raise ScenarioInvariantError(
                "RESOURCE_COST_CURVE_INVALID",
                "Resource unit costs must be a positive ordered currency/unit range.",
            )
        if (
            any(
                not isinstance(item, FinancialQuantity)
                for item in operating_expenses
            )
            or any(item.kind != "money" for item in operating_expenses)
            or len(
                {
                    (item.unit, item.scale, item.currency, item.period, item.as_of)
                    for item in operating_expenses
                }
            )
            != 1
            or self.operating_expense_base.period != self.period
            or self.operating_expense_low.normalized_value < 0
            or self.operating_expense_low.normalized_value
            > self.operating_expense_base.normalized_value
            or self.operating_expense_base.normalized_value
            > self.operating_expense_high.normalized_value
        ):
            raise ScenarioInvariantError(
                "RESOURCE_OPERATING_EXPENSE_INVALID",
                "Resource operating expenses must be an ordered money range on one exact time basis.",
            )
        if (
            any(not isinstance(item, FinancialQuantity) for item in capex)
            or any(item.kind != "money" for item in capex)
            or len(
                {
                    (item.unit, item.scale, item.currency, item.period, item.as_of)
                    for item in capex
                }
            )
            != 1
            or self.maintenance_capex_base.period != self.period
            or self.maintenance_capex_low.normalized_value < 0
            or self.maintenance_capex_low.normalized_value
            > self.maintenance_capex_base.normalized_value
            or self.maintenance_capex_base.normalized_value
            > self.maintenance_capex_high.normalized_value
        ):
            raise ScenarioInvariantError(
                "RESOURCE_MAINTENANCE_CAPEX_INVALID",
                "Maintenance capex must be an ordered money range on one exact time basis.",
            )
        _validate_model_quantity(
            self.tax_rate,
            unit="decimal",
            field_name="ResourcePeriodSpec.tax_rate",
        )
        if (
            self.tax_rate.period != self.period
            or not Decimal("0")
            <= self.tax_rate.normalized_value
            <= Decimal("1")
        ):
            raise ScenarioInvariantError(
                "RESOURCE_TAX_RATE_INVALID",
                "Resource tax rates must bind the schedule period and remain within [0, 1].",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.production_low.lineage_refs,
            self.production_base.lineage_refs,
            self.production_high.lineage_refs,
            self.unit_cost_low.lineage_refs,
            self.unit_cost_base.lineage_refs,
            self.unit_cost_high.lineage_refs,
            self.operating_expense_low.provenance_refs,
            self.operating_expense_base.provenance_refs,
            self.operating_expense_high.provenance_refs,
            self.maintenance_capex_low.provenance_refs,
            self.maintenance_capex_base.provenance_refs,
            self.maintenance_capex_high.provenance_refs,
            self.tax_rate.lineage_refs,
        )


@dataclass(frozen=True)
class ResourceAssetSpec:
    segment_id: str
    reserve_quantity: ForecastQuantity
    schedule: tuple[ResourcePeriodSpec, ...]
    grade_yield_low: ForecastQuantity
    grade_yield_base: ForecastQuantity
    grade_yield_high: ForecastQuantity
    resource_life_years: int

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ScenarioInvariantError(
                "RESOURCE_ASSET_IDENTITY_INVALID",
                "Resource assets require a segment identifier.",
            )
        if (
            not isinstance(self.resource_life_years, int)
            or isinstance(self.resource_life_years, bool)
            or self.resource_life_years <= 0
        ):
            raise ScenarioInvariantError(
                "RESOURCE_LIFE_INVALID",
                "Resource life must be a positive whole number of years.",
            )
        if (
            not isinstance(self.reserve_quantity, ForecastQuantity)
            or self.reserve_quantity.normalized_value <= 0
            or self.reserve_quantity.scale != Decimal("1")
            or self.reserve_quantity.currency != "N/A"
        ):
            raise ScenarioInvariantError(
                "RESOURCE_RESERVE_INVALID",
                "Resource reserves must be positive physical ForecastQuantity values.",
            )
        _require_refs(
            self.reserve_quantity.lineage_refs,
            "ResourceAssetSpec.reserve_quantity",
            facts_only=True,
        )
        if (
            not isinstance(self.schedule, tuple)
            or not self.schedule
            or any(
                not isinstance(item, ResourcePeriodSpec)
                for item in self.schedule
            )
        ):
            raise ScenarioInvariantError(
                "RESOURCE_SCHEDULE_INVALID",
                "Resource assets require a typed finite-life production and cost schedule.",
            )
        schedule_periods = tuple(item.period for item in self.schedule)
        if len(schedule_periods) != len(set(schedule_periods)):
            raise ScenarioInvariantError(
                "RESOURCE_SCHEDULE_DUPLICATE",
                "Resource schedule periods must be unique.",
            )
        schedule_years: list[int] = []
        for period in schedule_periods:
            match = re.fullmatch(r"(\d{4})(?:E|FY)", period)
            if match is None:
                raise ScenarioInvariantError(
                    "RESOURCE_SCHEDULE_CHRONOLOGY_INVALID",
                    "Resource schedules require annual E or FY periods.",
                )
            schedule_years.append(int(match.group(1)))
        if any(
            current != previous + 1
            for previous, current in zip(
                schedule_years,
                schedule_years[1:],
            )
        ):
            raise ScenarioInvariantError(
                "RESOURCE_SCHEDULE_CHRONOLOGY_INVALID",
                "Resource schedule periods must be strictly increasing and contiguous.",
            )
        _validate_range(
            self.grade_yield_low,
            self.grade_yield_base,
            self.grade_yield_high,
            f"{self.segment_id}_grade_yield",
            unit="decimal",
            positive=True,
        )
        if self.grade_yield_high.normalized_value > Decimal("1.5"):
            raise ScenarioInvariantError(
                "RESOURCE_GRADE_YIELD_INVALID",
                "Grade or yield cannot exceed the supported 1.5 upper bound.",
            )
        if (
            self.resource_life_years != len(self.schedule)
        ):
            raise ScenarioInvariantError(
                "RESOURCE_LIFE_INVALID",
                "Resource life must be a positive whole number of years.",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.reserve_quantity.lineage_refs,
            *(item.lineage_refs for item in self.schedule),
            self.grade_yield_low.lineage_refs,
            self.grade_yield_base.lineage_refs,
            self.grade_yield_high.lineage_refs,
        )


@dataclass(frozen=True)
class HistoricalCycleObservation:
    observation_id: str
    period: str
    denominator_metric: Literal["ebit"]
    observation_date: str
    denominator_available_at: str
    market_value: FinancialQuantity
    pit_earnings_denominator: FinancialQuantity
    reported_multiple: ForecastQuantity

    def __post_init__(self) -> None:
        if (
            not self.observation_id.strip()
            or not self.period.strip()
            or self.denominator_metric != "ebit"
        ):
            raise ScenarioInvariantError(
                "CYCLICAL_HISTORY_IDENTITY_INVALID",
                "Historical cycle observations require identity, period, and the supported EBIT denominator.",
            )
        try:
            observation_date = date.fromisoformat(self.observation_date)
            denominator_available_at = date.fromisoformat(
                self.denominator_available_at
            )
        except (TypeError, ValueError) as exc:
            raise ScenarioInvariantError(
                "CYCLICAL_HISTORY_PIT_INVALID",
                "Historical observation and denominator availability dates must be ISO dates.",
            ) from exc
        if (
            not isinstance(self.market_value, FinancialQuantity)
            or not isinstance(self.pit_earnings_denominator, FinancialQuantity)
            or self.market_value.kind != "money"
            or self.pit_earnings_denominator.kind != "money"
            or self.market_value.normalized_value <= 0
            or self.pit_earnings_denominator.normalized_value <= 0
            or self.market_value.currency
            != self.pit_earnings_denominator.currency
            or self.market_value.period != self.period
            or self.pit_earnings_denominator.period != self.period
            or self.market_value.as_of
            != self.pit_earnings_denominator.as_of
            or denominator_available_at > observation_date
            or observation_date > date.fromisoformat(self.market_value.as_of)
        ):
            raise ScenarioInvariantError(
                "CYCLICAL_HISTORY_DENOMINATOR_INVALID",
                "Historical bands require positive PIT market value and earnings on one currency/time basis.",
            )
        _require_refs(
            self.market_value.provenance_refs,
            "HistoricalCycleObservation.market_value",
            facts_only=True,
        )
        _require_refs(
            self.pit_earnings_denominator.provenance_refs,
            "HistoricalCycleObservation.pit_earnings_denominator",
            facts_only=True,
        )
        _validate_model_quantity(
            self.reported_multiple,
            unit="x",
            field_name="HistoricalCycleObservation.reported_multiple",
        )
        expected_refs = _merge_refs(
            self.market_value.provenance_refs,
            self.pit_earnings_denominator.provenance_refs,
        )
        with valuation_decimal_context():
            replayed = (
                self.market_value.normalized_value
                / self.pit_earnings_denominator.normalized_value
            )
        if (
            self.reported_multiple.period != self.period
            or self.reported_multiple.as_of != self.market_value.as_of
            or self.reported_multiple.normalized_value != replayed
            or not set(expected_refs).issubset(self.reported_multiple.lineage_refs)
        ):
            raise ScenarioInvariantError(
                "CYCLICAL_HISTORY_REPLAY_INVALID",
                "Historical multiple must replay exactly from its PIT denominator and market value.",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.market_value.provenance_refs,
            self.pit_earnings_denominator.provenance_refs,
            self.reported_multiple.lineage_refs,
        )


@dataclass(frozen=True)
class CyclicalResourceValuationSpec:
    curve_version: str
    curve_as_of: str
    commodity_curve: tuple[CommodityCurvePoint, ...]
    assets: tuple[ResourceAssetSpec, ...]
    mid_cycle_multiple_low: ForecastQuantity
    mid_cycle_multiple_base: ForecastQuantity
    mid_cycle_multiple_high: ForecastQuantity
    nav_discount_rate_low: ForecastQuantity
    nav_discount_rate_base: ForecastQuantity
    nav_discount_rate_high: ForecastQuantity
    peak_earnings_threshold: ForecastQuantity
    historical_observations: tuple[HistoricalCycleObservation, ...]

    def __post_init__(self) -> None:
        try:
            date.fromisoformat(self.curve_as_of)
        except (TypeError, ValueError) as exc:
            raise ScenarioInvariantError(
                "COMMODITY_CURVE_VERSION_INVALID",
                "Commodity curve requires a version and ISO as-of date.",
            ) from exc
        if not self.curve_version.strip():
            raise ScenarioInvariantError(
                "COMMODITY_CURVE_VERSION_INVALID",
                "Commodity curve requires a version and ISO as-of date.",
            )
        if (
            not isinstance(self.commodity_curve, tuple)
            or not self.commodity_curve
            or any(
                not isinstance(item, CommodityCurvePoint)
                for item in self.commodity_curve
            )
        ):
            raise ScenarioInvariantError(
                "COMMODITY_CURVE_INVALID",
                "A versioned commodity curve requires typed points.",
            )
        curve_keys = tuple(
            (item.segment_id, item.period) for item in self.commodity_curve
        )
        if len(curve_keys) != len(set(curve_keys)):
            raise ScenarioInvariantError(
                "COMMODITY_CURVE_DUPLICATE",
                "Commodity curve may define each segment-period only once.",
            )
        if (
            not isinstance(self.assets, tuple)
            or not self.assets
            or any(not isinstance(item, ResourceAssetSpec) for item in self.assets)
        ):
            raise ScenarioInvariantError(
                "RESOURCE_ASSETS_INVALID",
                "Resource NAV requires typed asset specifications.",
            )
        asset_ids = tuple(item.segment_id for item in self.assets)
        if len(asset_ids) != len(set(asset_ids)):
            raise ScenarioInvariantError(
                "RESOURCE_ASSET_DUPLICATE",
                "Resource NAV may define each segment only once.",
            )
        _validate_range(
            self.mid_cycle_multiple_low,
            self.mid_cycle_multiple_base,
            self.mid_cycle_multiple_high,
            "mid_cycle_multiple",
            unit="x",
            positive=True,
        )
        _validate_range(
            self.nav_discount_rate_low,
            self.nav_discount_rate_base,
            self.nav_discount_rate_high,
            "nav_discount_rate",
            unit="decimal",
            positive=True,
        )
        _validate_model_quantity(
            self.peak_earnings_threshold,
            unit="x",
            field_name="peak_earnings_threshold",
        )
        if self.peak_earnings_threshold.normalized_value <= Decimal("1"):
            raise ScenarioInvariantError(
                "CYCLICAL_PEAK_THRESHOLD_INVALID",
                "Peak-earnings recognition requires a threshold greater than one times the PIT median denominator.",
            )
        if (
            not isinstance(self.historical_observations, tuple)
            or len(self.historical_observations) < 3
            or any(
                not isinstance(item, HistoricalCycleObservation)
                for item in self.historical_observations
            )
        ):
            raise ScenarioInvariantError(
                "CYCLICAL_HISTORY_INSUFFICIENT",
                "Cyclical historical bands require at least three replayable PIT observations.",
            )
        observation_ids = tuple(
            item.observation_id for item in self.historical_observations
        )
        if len(observation_ids) != len(set(observation_ids)):
            raise ScenarioInvariantError(
                "CYCLICAL_HISTORY_DUPLICATE",
                "Historical cycle observation identifiers must be unique.",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            *(item.lineage_refs for item in self.commodity_curve),
            *(item.lineage_refs for item in self.assets),
            self.mid_cycle_multiple_low.lineage_refs,
            self.mid_cycle_multiple_base.lineage_refs,
            self.mid_cycle_multiple_high.lineage_refs,
            self.nav_discount_rate_low.lineage_refs,
            self.nav_discount_rate_base.lineage_refs,
            self.nav_discount_rate_high.lineage_refs,
            self.peak_earnings_threshold.lineage_refs,
            *(item.lineage_refs for item in self.historical_observations),
            (f"Assumption:commodity_curve_version:{self.curve_version}",),
        )


@dataclass(frozen=True)
class FinancialMetricRange:
    metric_id: str
    low: ForecastQuantity
    base: ForecastQuantity
    high: ForecastQuantity

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9_]+", self.metric_id or ""):
            raise ScenarioInvariantError(
                "FINANCIAL_METRIC_ID_INVALID",
                "Financial metric identifiers must be stable lowercase tokens.",
            )
        _validate_range(
            self.low,
            self.base,
            self.high,
            self.metric_id,
            unit="decimal",
        )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.low.lineage_refs,
            self.base.lineage_refs,
            self.high.lineage_refs,
        )


@dataclass(frozen=True)
class FinancialInstitutionPeriodSpec:
    period: str
    roe_low: ForecastQuantity
    roe_base: ForecastQuantity
    roe_high: ForecastQuantity
    payout_low: ForecastQuantity
    payout_base: ForecastQuantity
    payout_high: ForecastQuantity
    rwa_growth_low: ForecastQuantity
    rwa_growth_base: ForecastQuantity
    rwa_growth_high: ForecastQuantity
    clean_surplus_adjustment_low: FinancialQuantity
    clean_surplus_adjustment_base: FinancialQuantity
    clean_surplus_adjustment_high: FinancialQuantity
    regulatory_capital_adjustment_low: FinancialQuantity
    regulatory_capital_adjustment_base: FinancialQuantity
    regulatory_capital_adjustment_high: FinancialQuantity
    dilution_factor_low: ForecastQuantity
    dilution_factor_base: ForecastQuantity
    dilution_factor_high: ForecastQuantity
    operating_exposure_to_equity_low: ForecastQuantity
    operating_exposure_to_equity_base: ForecastQuantity
    operating_exposure_to_equity_high: ForecastQuantity
    operating_metrics: tuple[FinancialMetricRange, ...]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"\d{4}(?:E|FY)", self.period or ""):
            raise ScenarioInvariantError(
                "FINANCIAL_PERIOD_INVALID",
                "Financial institution schedules require annual E or FY periods.",
            )
        for name, quantities in (
            (
                "roe",
                (self.roe_low, self.roe_base, self.roe_high),
            ),
            (
                "payout",
                (self.payout_low, self.payout_base, self.payout_high),
            ),
            (
                "rwa_growth",
                (
                    self.rwa_growth_low,
                    self.rwa_growth_base,
                    self.rwa_growth_high,
                ),
            ),
        ):
            _validate_range(
                *quantities,
                name,
                unit="decimal",
            )
            if any(item.period != self.period for item in quantities):
                raise ScenarioInvariantError(
                    "FINANCIAL_PERIOD_BINDING_INVALID",
                    f"{name} must bind the financial schedule period.",
                )
        if (
            self.payout_low.normalized_value < 0
            or self.payout_high.normalized_value > 1
            or self.rwa_growth_low.normalized_value <= -1
        ):
            raise ScenarioInvariantError(
                "FINANCIAL_RATE_RANGE_INVALID",
                "Payout must remain within [0,1] and RWA growth above -1.",
            )
        _validate_range(
            self.dilution_factor_low,
            self.dilution_factor_base,
            self.dilution_factor_high,
            "dilution_factor",
            unit="x",
            positive=True,
        )
        if any(
            item.period != self.period
            for item in (
                self.dilution_factor_low,
                self.dilution_factor_base,
                self.dilution_factor_high,
            )
        ):
            raise ScenarioInvariantError(
                "FINANCIAL_PERIOD_BINDING_INVALID",
                "Dilution factors must bind the financial schedule period.",
            )
        _validate_range(
            self.operating_exposure_to_equity_low,
            self.operating_exposure_to_equity_base,
            self.operating_exposure_to_equity_high,
            "operating_exposure_to_equity",
            unit="x",
            positive=True,
        )
        if any(
            item.period != self.period
            for item in (
                self.operating_exposure_to_equity_low,
                self.operating_exposure_to_equity_base,
                self.operating_exposure_to_equity_high,
            )
        ):
            raise ScenarioInvariantError(
                "FINANCIAL_PERIOD_BINDING_INVALID",
                "Operating exposure-to-equity factors must bind the financial schedule period.",
            )
        money_ranges = (
            (
                self.clean_surplus_adjustment_low,
                self.clean_surplus_adjustment_base,
                self.clean_surplus_adjustment_high,
            ),
            (
                self.regulatory_capital_adjustment_low,
                self.regulatory_capital_adjustment_base,
                self.regulatory_capital_adjustment_high,
            ),
        )
        for quantities in money_ranges:
            if (
                any(not isinstance(item, FinancialQuantity) for item in quantities)
                or any(item.kind != "money" for item in quantities)
                or len(
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
                )
                != 1
                or quantities[0].period != self.period
                or quantities[0].normalized_value
                > quantities[1].normalized_value
                or quantities[1].normalized_value
                > quantities[2].normalized_value
            ):
                raise ScenarioInvariantError(
                    "FINANCIAL_MONEY_RANGE_INVALID",
                    "Clean-surplus and regulatory-capital adjustments require ordered money ranges.",
                )
        if (
            not isinstance(self.operating_metrics, tuple)
            or not self.operating_metrics
            or any(
                not isinstance(item, FinancialMetricRange)
                for item in self.operating_metrics
            )
        ):
            raise ScenarioInvariantError(
                "FINANCIAL_OPERATING_METRICS_INVALID",
                "Financial periods require typed operating metrics.",
            )
        metric_ids = tuple(item.metric_id for item in self.operating_metrics)
        if len(metric_ids) != len(set(metric_ids)) or any(
            quantity.period != self.period
            for metric in self.operating_metrics
            for quantity in (metric.low, metric.base, metric.high)
        ):
            raise ScenarioInvariantError(
                "FINANCIAL_OPERATING_METRICS_INVALID",
                "Operating metric identifiers must be unique and period-bound.",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.roe_low.lineage_refs,
            self.roe_base.lineage_refs,
            self.roe_high.lineage_refs,
            self.payout_low.lineage_refs,
            self.payout_base.lineage_refs,
            self.payout_high.lineage_refs,
            self.rwa_growth_low.lineage_refs,
            self.rwa_growth_base.lineage_refs,
            self.rwa_growth_high.lineage_refs,
            self.clean_surplus_adjustment_low.provenance_refs,
            self.clean_surplus_adjustment_base.provenance_refs,
            self.clean_surplus_adjustment_high.provenance_refs,
            self.regulatory_capital_adjustment_low.provenance_refs,
            self.regulatory_capital_adjustment_base.provenance_refs,
            self.regulatory_capital_adjustment_high.provenance_refs,
            self.dilution_factor_low.lineage_refs,
            self.dilution_factor_base.lineage_refs,
            self.dilution_factor_high.lineage_refs,
            self.operating_exposure_to_equity_low.lineage_refs,
            self.operating_exposure_to_equity_base.lineage_refs,
            self.operating_exposure_to_equity_high.lineage_refs,
            *(item.lineage_refs for item in self.operating_metrics),
        )


@dataclass(frozen=True)
class FinancialInstitutionValuationSpec:
    institution_type: Literal["bank", "insurance", "broker"]
    opening_book_value: FinancialQuantity
    opening_regulatory_capital: FinancialQuantity
    opening_risk_weighted_assets: FinancialQuantity
    minimum_regulatory_capital_ratio: ForecastQuantity
    specialized_risk_limit: ForecastQuantity
    cost_of_equity_low: ForecastQuantity
    cost_of_equity_base: ForecastQuantity
    cost_of_equity_high: ForecastQuantity
    terminal_growth_low: ForecastQuantity
    terminal_growth_base: ForecastQuantity
    terminal_growth_high: ForecastQuantity
    periods: tuple[FinancialInstitutionPeriodSpec, ...]

    def __post_init__(self) -> None:
        required_metrics = {
            "bank": {"nim", "credit_cost", "npl_ratio"},
            "insurance": {"combined_ratio", "solvency_ratio"},
            "broker": {"net_capital_ratio", "fee_income_yield"},
        }
        if self.institution_type not in required_metrics:
            raise ScenarioInvariantError(
                "FINANCIAL_INSTITUTION_TYPE_INVALID",
                "Financial institution type must be bank, insurance, or broker.",
            )
        opening = (
            self.opening_book_value,
            self.opening_regulatory_capital,
            self.opening_risk_weighted_assets,
        )
        if (
            any(not isinstance(item, FinancialQuantity) for item in opening)
            or any(item.kind != "money" for item in opening)
            or any(item.normalized_value <= 0 for item in opening)
            or len(
                {
                    (
                        item.unit,
                        item.scale,
                        item.currency,
                        item.period,
                        item.as_of,
                    )
                    for item in opening
                }
            )
            != 1
        ):
            raise ScenarioInvariantError(
                "FINANCIAL_OPENING_BALANCE_INVALID",
                "Opening book value, regulatory capital, and RWA require positive money quantities on one basis.",
            )
        for item in opening:
            _require_refs(
                item.provenance_refs,
                "FinancialInstitutionValuationSpec.opening_balance",
                facts_only=True,
            )
        _validate_model_quantity(
            self.minimum_regulatory_capital_ratio,
            unit="decimal",
            field_name="minimum_regulatory_capital_ratio",
        )
        if not Decimal("0") < self.minimum_regulatory_capital_ratio.normalized_value < 1:
            raise ScenarioInvariantError(
                "FINANCIAL_REGULATORY_MINIMUM_INVALID",
                "Minimum regulatory capital ratio must be within (0,1).",
            )
        _validate_model_quantity(
            self.specialized_risk_limit,
            unit="decimal",
            field_name="specialized_risk_limit",
        )
        if self.specialized_risk_limit.normalized_value <= 0:
            raise ScenarioInvariantError(
                "FINANCIAL_SPECIALIZED_RISK_LIMIT_INVALID",
                "The institution-specific risk limit must be positive.",
            )
        _validate_range(
            self.cost_of_equity_low,
            self.cost_of_equity_base,
            self.cost_of_equity_high,
            "cost_of_equity",
            unit="decimal",
            positive=True,
        )
        _validate_range(
            self.terminal_growth_low,
            self.terminal_growth_base,
            self.terminal_growth_high,
            "financial_terminal_growth",
            unit="decimal",
        )
        if (
            self.cost_of_equity_low.normalized_value
            <= self.terminal_growth_high.normalized_value
        ):
            raise ScenarioInvariantError(
                "FINANCIAL_TERMINAL_SPREAD_INVALID",
                "Every cost-of-equity case must exceed terminal growth.",
            )
        if (
            not isinstance(self.periods, tuple)
            or not self.periods
            or any(
                not isinstance(item, FinancialInstitutionPeriodSpec)
                for item in self.periods
            )
        ):
            raise ScenarioInvariantError(
                "FINANCIAL_PERIODS_INVALID",
                "Financial valuation requires a typed finite forecast schedule.",
            )
        years = [int(item.period[:4]) for item in self.periods]
        if any(
            current != previous + 1
            for previous, current in zip(years, years[1:])
        ):
            raise ScenarioInvariantError(
                "FINANCIAL_PERIODS_INVALID",
                "Financial forecast periods must be strictly increasing and contiguous.",
            )
        for item in self.periods:
            metrics = {
                metric.metric_id: metric
                for metric in item.operating_metrics
            }
            if not required_metrics[self.institution_type].issubset(metrics):
                raise ScenarioInvariantError(
                    "FINANCIAL_SPECIALIZED_INPUT_MISSING",
                    f"{self.institution_type} requires {sorted(required_metrics[self.institution_type])}.",
                )
            values = {
                metric_id: tuple(
                    getattr(metric, case_name).normalized_value
                    for case_name in ("low", "base", "high")
                )
                for metric_id, metric in metrics.items()
            }
            if self.institution_type == "bank" and (
                self.specialized_risk_limit.normalized_value > 1
                or any(
                    value < 0 or value > 1
                    for metric_id in ("nim", "credit_cost", "npl_ratio")
                    for value in values[metric_id]
                )
            ):
                raise ScenarioInvariantError(
                    "FINANCIAL_SPECIALIZED_METRIC_DOMAIN_INVALID",
                    "Bank NIM, credit cost, NPL ratio, and the NPL risk limit must remain within [0,1].",
                )
            if self.institution_type == "insurance" and (
                any(value < 0 for value in values["combined_ratio"])
                or any(value <= 0 for value in values["solvency_ratio"])
            ):
                raise ScenarioInvariantError(
                    "FINANCIAL_SPECIALIZED_METRIC_DOMAIN_INVALID",
                    "Insurance combined ratios must be nonnegative and solvency ratios positive.",
                )
            if self.institution_type == "broker" and (
                any(value <= 0 for value in values["net_capital_ratio"])
                or any(
                    value < 0 or value > 1
                    for value in values["fee_income_yield"]
                )
            ):
                raise ScenarioInvariantError(
                    "FINANCIAL_SPECIALIZED_METRIC_DOMAIN_INVALID",
                    "Broker net-capital ratios must be positive and fee-income yields within [0,1].",
                )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.opening_book_value.provenance_refs,
            self.opening_regulatory_capital.provenance_refs,
            self.opening_risk_weighted_assets.provenance_refs,
            self.minimum_regulatory_capital_ratio.lineage_refs,
            self.specialized_risk_limit.lineage_refs,
            self.cost_of_equity_low.lineage_refs,
            self.cost_of_equity_base.lineage_refs,
            self.cost_of_equity_high.lineage_refs,
            self.terminal_growth_low.lineage_refs,
            self.terminal_growth_base.lineage_refs,
            self.terminal_growth_high.lineage_refs,
            *(item.lineage_refs for item in self.periods),
        )


@dataclass(frozen=True)
class BiopharmaEventSpec:
    event_id: str
    event_type: Literal["clinical", "regulatory", "commercial"]
    probability_basis: Literal["standalone", "conditional_on_parents"]
    period: str
    parent_event_ids: tuple[str, ...]
    probability_low: ForecastQuantity
    probability_base: ForecastQuantity
    probability_high: ForecastQuantity
    calibration_version: str
    calibration_method_version: str
    calibration_window_start: str
    calibration_window_end: str
    calibration_sample_size: int
    calibration_record_id: str

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[A-Za-z0-9_.:-]+", self.event_id or "")
            or self.event_type
            not in {"clinical", "regulatory", "commercial"}
            or self.probability_basis
            not in {"standalone", "conditional_on_parents"}
            or not re.fullmatch(r"\d{4}(?:E|FY)", self.period or "")
            or not self.calibration_version.strip()
            or not self.calibration_method_version.strip()
            or self.calibration_sample_size <= 0
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_EVENT_IDENTITY_INVALID",
                "Biopharma events require a stable id, typed event class, annual period, and calibration version.",
            )
        try:
            window_start = date.fromisoformat(
                self.calibration_window_start
            )
            window_end = date.fromisoformat(
                self.calibration_window_end
            )
        except (TypeError, ValueError) as exc:
            raise ScenarioInvariantError(
                "BIOPHARMA_CALIBRATION_RECORD_INVALID",
                "Probability calibration windows must use ISO dates.",
            ) from exc
        expected_record_id = (
            "BIOPHARMA_POS_CALIBRATION:"
            f"{self.event_id}:"
            f"{self.calibration_version}:"
            f"{self.calibration_method_version}:"
            f"{self.probability_basis}:"
            f"{self.calibration_window_start}:"
            f"{self.calibration_window_end}:"
            f"n={self.calibration_sample_size}"
        )
        if (
            window_end < window_start
            or self.calibration_record_id != expected_record_id
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_CALIBRATION_RECORD_INVALID",
                "Calibration record identity must exactly bind version, method, basis, window, and sample size.",
            )
        if (
            not isinstance(self.parent_event_ids, tuple)
            or len(self.parent_event_ids) != len(set(self.parent_event_ids))
            or self.event_id in self.parent_event_ids
            or len(self.parent_event_ids) > 1
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_EVENT_DEPENDENCY_INVALID",
                "Event parents must be a unique zero-or-one tuple; unsupported multi-parent joint probabilities fail closed.",
            )
        if (
            bool(self.parent_event_ids)
            != (self.probability_basis == "conditional_on_parents")
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_EVENT_PROBABILITY_BASIS_INVALID",
                "Root probabilities must be standalone and dependent-event probabilities explicitly conditional on parents.",
            )
        _validate_range(
            self.probability_low,
            self.probability_base,
            self.probability_high,
            f"event_probability:{self.event_id}",
            unit="decimal",
        )
        probabilities = (
            self.probability_low,
            self.probability_base,
            self.probability_high,
        )
        if (
            any(item.period != self.period for item in probabilities)
            or self.probability_low.normalized_value < 0
            or self.probability_high.normalized_value > 1
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_EVENT_PROBABILITY_INVALID",
                "Event probability ranges must bind the event period and remain within [0,1].",
            )
        base_fact_refs = tuple(
            ref
            for ref in self.probability_base.lineage_refs
            if ref.startswith("Fact:")
        )
        if not base_fact_refs or any(
            ref not in item.lineage_refs
            for ref in base_fact_refs
            for item in (
                self.probability_low,
                self.probability_high,
            )
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_PROBABILITY_EVIDENCE_INVALID",
                "Low, base, and high probabilities must share a frozen fact supporting the calibrated base probability.",
            )

    @property
    def base_fact_refs(self) -> tuple[str, ...]:
        return tuple(
            ref
            for ref in self.probability_base.lineage_refs
            if ref.startswith("Fact:")
        )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.probability_low.lineage_refs,
            self.probability_base.lineage_refs,
            self.probability_high.lineage_refs,
            (
                f"Assumption:biopharma_probability_calibration:{self.calibration_version}",
                f"Assumption:biopharma_probability_method:{self.calibration_method_version}",
                f"Assumption:biopharma_probability_window:{self.calibration_window_start}/{self.calibration_window_end}",
                f"Assumption:biopharma_probability_sample_size:{self.calibration_sample_size}",
                f"Fact:{self.calibration_record_id}",
                f"Assumption:biopharma_probability_basis:{self.probability_basis}",
            ),
        )


@dataclass(frozen=True)
class BiopharmaCashFlowPeriodSpec:
    period: str
    gross_sales_low: FinancialQuantity
    gross_sales_base: FinancialQuantity
    gross_sales_high: FinancialQuantity
    development_cost_low: FinancialQuantity
    development_cost_base: FinancialQuantity
    development_cost_high: FinancialQuantity
    milestone_cash_low: FinancialQuantity
    milestone_cash_base: FinancialQuantity
    milestone_cash_high: FinancialQuantity
    milestone_event_id: str
    commercial_cost_rate_low: ForecastQuantity
    commercial_cost_rate_base: ForecastQuantity
    commercial_cost_rate_high: ForecastQuantity

    def __post_init__(self) -> None:
        if not re.fullmatch(r"\d{4}(?:E|FY)", self.period or ""):
            raise ScenarioInvariantError(
                "BIOPHARMA_PERIOD_INVALID",
                "Biopharma cash-flow schedules require annual E or FY periods.",
            )
        _validate_money_range(
            self.gross_sales_low,
            self.gross_sales_base,
            self.gross_sales_high,
            "biopharma_gross_sales",
            nonnegative=True,
        )
        _validate_money_range(
            self.development_cost_low,
            self.development_cost_base,
            self.development_cost_high,
            "biopharma_development_cost",
            nonnegative=True,
        )
        _validate_money_range(
            self.milestone_cash_low,
            self.milestone_cash_base,
            self.milestone_cash_high,
            "biopharma_milestone_cash",
        )
        money = (
            self.gross_sales_low,
            self.gross_sales_base,
            self.gross_sales_high,
            self.development_cost_low,
            self.development_cost_base,
            self.development_cost_high,
            self.milestone_cash_low,
            self.milestone_cash_base,
            self.milestone_cash_high,
        )
        if any(item.period != self.period for item in money):
            raise ScenarioInvariantError(
                "BIOPHARMA_PERIOD_BINDING_INVALID",
                "Every biopharma cash-flow quantity must bind its schedule period.",
            )
        _validate_range(
            self.commercial_cost_rate_low,
            self.commercial_cost_rate_base,
            self.commercial_cost_rate_high,
            "biopharma_commercial_cost_rate",
            unit="decimal",
        )
        rates = (
            self.commercial_cost_rate_low,
            self.commercial_cost_rate_base,
            self.commercial_cost_rate_high,
        )
        if (
            any(item.period != self.period for item in rates)
            or self.commercial_cost_rate_low.normalized_value < 0
            or self.commercial_cost_rate_high.normalized_value > 1
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_COMMERCIAL_COST_INVALID",
                "Commercial cost rates must bind the schedule period and remain within [0,1].",
            )
        if self.milestone_event_id and not re.fullmatch(
            r"[A-Za-z0-9_.:-]+",
            self.milestone_event_id,
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_MILESTONE_EVENT_INVALID",
                "Milestone event ids must be empty or stable tokens.",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.gross_sales_low.provenance_refs,
            self.gross_sales_base.provenance_refs,
            self.gross_sales_high.provenance_refs,
            self.development_cost_low.provenance_refs,
            self.development_cost_base.provenance_refs,
            self.development_cost_high.provenance_refs,
            self.milestone_cash_low.provenance_refs,
            self.milestone_cash_base.provenance_refs,
            self.milestone_cash_high.provenance_refs,
            self.commercial_cost_rate_low.lineage_refs,
            self.commercial_cost_rate_base.lineage_refs,
            self.commercial_cost_rate_high.lineage_refs,
        )


@dataclass(frozen=True)
class BiopharmaAssetSpec:
    asset_id: str
    indication_id: str
    economic_right_id: str
    development_stage: Literal[
        "discovery",
        "preclinical",
        "phase1",
        "phase2",
        "phase3",
        "filed",
        "approved",
    ]
    required_event_ids: tuple[str, ...]
    ownership_low: ForecastQuantity
    ownership_base: ForecastQuantity
    ownership_high: ForecastQuantity
    royalty_burden_low: ForecastQuantity
    royalty_burden_base: ForecastQuantity
    royalty_burden_high: ForecastQuantity
    launch_delay_years_low: ForecastQuantity
    launch_delay_years_base: ForecastQuantity
    launch_delay_years_high: ForecastQuantity
    delay_carry_cost_low: FinancialQuantity
    delay_carry_cost_base: FinancialQuantity
    delay_carry_cost_high: FinancialQuantity
    periods: tuple[BiopharmaCashFlowPeriodSpec, ...]

    def __post_init__(self) -> None:
        stable = (self.asset_id, self.indication_id, self.economic_right_id)
        if any(
            not re.fullmatch(r"[A-Za-z0-9_.:-]+", value or "")
            for value in stable
        ) or self.development_stage not in {
            "discovery",
            "preclinical",
            "phase1",
            "phase2",
            "phase3",
            "filed",
            "approved",
        }:
            raise ScenarioInvariantError(
                "BIOPHARMA_ASSET_IDENTITY_INVALID",
                "Assets require stable asset, indication, economic-right ids and a recognized development stage.",
            )
        if (
            not isinstance(self.required_event_ids, tuple)
            or not self.required_event_ids
            or len(self.required_event_ids)
            != len(set(self.required_event_ids))
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_ASSET_EVENTS_INVALID",
                "Every asset/indication requires a unique non-empty event path.",
            )
        _validate_range(
            self.ownership_low,
            self.ownership_base,
            self.ownership_high,
            "biopharma_ownership",
            unit="decimal",
        )
        _validate_range(
            self.royalty_burden_low,
            self.royalty_burden_base,
            self.royalty_burden_high,
            "biopharma_royalty_burden",
            unit="decimal",
        )
        if (
            self.ownership_low.normalized_value < 0
            or self.ownership_high.normalized_value > 1
            or self.royalty_burden_low.normalized_value < 0
            or self.royalty_burden_high.normalized_value > 1
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_LICENSE_ECONOMICS_INVALID",
                "Ownership and royalty burdens must remain within [0,1].",
            )
        _validate_range(
            self.launch_delay_years_low,
            self.launch_delay_years_base,
            self.launch_delay_years_high,
            "biopharma_launch_delay",
            unit="years",
        )
        delays = (
            self.launch_delay_years_low.normalized_value,
            self.launch_delay_years_base.normalized_value,
            self.launch_delay_years_high.normalized_value,
        )
        if delays[0] < 0 or any(
            value != value.to_integral_value() for value in delays
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_DELAY_INVALID",
                "Launch delay must be a nonnegative whole number of years.",
            )
        _validate_money_range(
            self.delay_carry_cost_low,
            self.delay_carry_cost_base,
            self.delay_carry_cost_high,
            "biopharma_delay_carry_cost",
            nonnegative=True,
        )
        if (
            not isinstance(self.periods, tuple)
            or not self.periods
            or any(
                not isinstance(item, BiopharmaCashFlowPeriodSpec)
                for item in self.periods
            )
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_ASSET_PERIODS_INVALID",
                "Every asset requires a typed finite cash-flow schedule.",
            )
        years = tuple(int(item.period[:4]) for item in self.periods)
        if len(years) != len(set(years)) or any(
            current != previous + 1
            for previous, current in zip(years, years[1:])
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_ASSET_PERIODS_INVALID",
                "Asset cash-flow periods must be unique, increasing, and contiguous.",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.ownership_low.lineage_refs,
            self.ownership_base.lineage_refs,
            self.ownership_high.lineage_refs,
            self.royalty_burden_low.lineage_refs,
            self.royalty_burden_base.lineage_refs,
            self.royalty_burden_high.lineage_refs,
            self.launch_delay_years_low.lineage_refs,
            self.launch_delay_years_base.lineage_refs,
            self.launch_delay_years_high.lineage_refs,
            self.delay_carry_cost_low.provenance_refs,
            self.delay_carry_cost_base.provenance_refs,
            self.delay_carry_cost_high.provenance_refs,
            *(item.lineage_refs for item in self.periods),
            (
                f"Assumption:biopharma_stage:{self.development_stage}",
                f"Assumption:biopharma_economic_right:{self.economic_right_id}",
            ),
        )


@dataclass(frozen=True)
class BiopharmaFinancingSpec:
    record_id: str
    period: str
    proceeds: FinancialQuantity
    issue_price: FinancialQuantity
    new_shares: FinancialQuantity

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[A-Za-z0-9_.:-]+", self.record_id or "")
            or not re.fullmatch(r"\d{4}(?:E|FY)", self.period or "")
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_FINANCING_IDENTITY_INVALID",
                "Committed financing requires a stable record id and annual period.",
            )
        if (
            not isinstance(self.proceeds, FinancialQuantity)
            or self.proceeds.kind != "money"
            or not isinstance(self.issue_price, FinancialQuantity)
            or self.issue_price.kind != "per_share"
            or not isinstance(self.new_shares, FinancialQuantity)
            or self.new_shares.kind != "shares"
            or any(
                item.normalized_value <= 0
                for item in (
                    self.proceeds,
                    self.issue_price,
                    self.new_shares,
                )
            )
            or any(
                item.period != self.period
                for item in (
                    self.proceeds,
                    self.issue_price,
                    self.new_shares,
                )
            )
            or len(
                {
                    item.as_of
                    for item in (
                        self.proceeds,
                        self.issue_price,
                        self.new_shares,
                    )
                }
            )
            != 1
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_FINANCING_TERMS_INVALID",
                "Committed financing requires positive proceeds, per-share issue price, and new shares on one period/as-of basis.",
            )
        if (
            self.issue_price.currency != self.proceeds.currency
            or self.issue_price.unit
            != f"{self.proceeds.currency}/share"
            or self.new_shares.unit != "shares"
            or self.new_shares.currency != "N/A"
            or self.proceeds.normalized_value
            != self.issue_price.normalized_value
            * self.new_shares.normalized_value
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_FINANCING_PRICING_INVALID",
                "Committed proceeds must equal issue price times new shares with exact units.",
            )
        for field_name, quantity in (
            ("proceeds", self.proceeds),
            ("issue_price", self.issue_price),
            ("new_shares", self.new_shares),
        ):
            _require_refs(
                quantity.provenance_refs,
                f"BiopharmaFinancingSpec.{field_name}",
                facts_only=True,
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.proceeds.provenance_refs,
            self.issue_price.provenance_refs,
            self.new_shares.provenance_refs,
            (f"Assumption:committed_financing_record:{self.record_id}",),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "period": self.period,
            "proceeds": self.proceeds.to_dict(),
            "issue_price": self.issue_price.to_dict(),
            "new_shares": self.new_shares.to_dict(),
        }


@dataclass(frozen=True)
class BiopharmaRunwayPeriodSpec:
    period: str
    corporate_cash_burn_low: FinancialQuantity
    corporate_cash_burn_base: FinancialQuantity
    corporate_cash_burn_high: FinancialQuantity
    financing: BiopharmaFinancingSpec | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"\d{4}(?:E|FY)", self.period or ""):
            raise ScenarioInvariantError(
                "BIOPHARMA_RUNWAY_PERIOD_INVALID",
                "Runway schedules require annual E or FY periods.",
            )
        _validate_money_range(
            self.corporate_cash_burn_low,
            self.corporate_cash_burn_base,
            self.corporate_cash_burn_high,
            "biopharma_corporate_cash_burn",
            nonnegative=True,
        )
        money = (
            self.corporate_cash_burn_low,
            self.corporate_cash_burn_base,
            self.corporate_cash_burn_high,
        )
        if any(item.period != self.period for item in money):
            raise ScenarioInvariantError(
                "BIOPHARMA_RUNWAY_PERIOD_BINDING_INVALID",
                "Runway cash quantities must bind the runway period.",
            )
        if self.financing is not None and (
            not isinstance(self.financing, BiopharmaFinancingSpec)
            or self.financing.period != self.period
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_FINANCING_PERIOD_INVALID",
                "Committed financing must bind its runway period.",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            self.corporate_cash_burn_low.provenance_refs,
            self.corporate_cash_burn_base.provenance_refs,
            self.corporate_cash_burn_high.provenance_refs,
            (
                self.financing.lineage_refs
                if self.financing is not None
                else ()
            ),
        )


@dataclass(frozen=True)
class BiopharmaValuationSpec:
    events: tuple[BiopharmaEventSpec, ...]
    assets: tuple[BiopharmaAssetSpec, ...]
    opening_cash: FinancialQuantity
    minimum_cash_buffer: FinancialQuantity
    discount_rate_low: ForecastQuantity
    discount_rate_base: ForecastQuantity
    discount_rate_high: ForecastQuantity
    runway_periods: tuple[BiopharmaRunwayPeriodSpec, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.events, tuple)
            or not self.events
            or any(
                not isinstance(item, BiopharmaEventSpec)
                for item in self.events
            )
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_EVENTS_INVALID",
                "Biopharma valuation requires a typed non-empty event tree.",
            )
        event_ids = tuple(item.event_id for item in self.events)
        if len(event_ids) != len(set(event_ids)):
            raise ScenarioInvariantError(
                "BIOPHARMA_EVENT_DUPLICATE",
                "Biopharma event ids must be unique.",
            )
        events = {item.event_id: item for item in self.events}
        if any(
            parent_id not in events
            or int(events[parent_id].period[:4])
            > int(item.period[:4])
            for item in self.events
            for parent_id in item.parent_event_ids
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_EVENT_DEPENDENCY_INVALID",
                "Event parents must exist and cannot occur after their dependent event.",
            )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(event_id: str) -> None:
            if event_id in visiting:
                raise ScenarioInvariantError(
                    "BIOPHARMA_EVENT_CYCLE",
                    "Biopharma event dependencies must form an acyclic graph.",
                )
            if event_id in visited:
                return
            visiting.add(event_id)
            for parent_id in events[event_id].parent_event_ids:
                visit(parent_id)
            visiting.remove(event_id)
            visited.add(event_id)

        for event_id in event_ids:
            visit(event_id)
        if (
            not isinstance(self.assets, tuple)
            or not self.assets
            or any(
                not isinstance(item, BiopharmaAssetSpec)
                for item in self.assets
            )
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_ASSETS_INVALID",
                "Biopharma valuation requires typed asset/indication schedules.",
            )
        asset_keys = tuple(
            (item.asset_id, item.indication_id) for item in self.assets
        )
        rights = tuple(item.economic_right_id for item in self.assets)
        if (
            len(asset_keys) != len(set(asset_keys))
            or len(rights) != len(set(rights))
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_ECONOMIC_RIGHT_DUPLICATE",
                "Each asset/indication and economic right may be valued exactly once.",
            )
        if any(
            event_id not in events
            for asset in self.assets
            for event_id in asset.required_event_ids
        ) or any(
            period.milestone_event_id
            and period.milestone_event_id not in events
            for asset in self.assets
            for period in asset.periods
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_ASSET_EVENTS_INVALID",
                "Asset and milestone event references must resolve in the declared event tree.",
            )
        def ancestors(event_id: str) -> set[str]:
            result: set[str] = set()
            stack = list(events[event_id].parent_event_ids)
            while stack:
                parent_id = stack.pop()
                if parent_id in result:
                    continue
                result.add(parent_id)
                stack.extend(events[parent_id].parent_event_ids)
            return result

        if any(
            left_id not in ancestors(right_id)
            and right_id not in ancestors(left_id)
            for asset in self.assets
            for index, left_id in enumerate(asset.required_event_ids)
            for right_id in asset.required_event_ids[index + 1 :]
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_JOINT_PROBABILITY_UNSUPPORTED",
                "An asset event path must be a single dependency chain unless an explicit joint-probability model is supplied.",
            )
        for asset in self.assets:
            latest_required_year = max(
                int(events[event_id].period[:4])
                for event_id in asset.required_event_ids
            )
            if any(
                int(period.period[:4]) < latest_required_year
                and period.gross_sales_high.normalized_value > 0
                for period in asset.periods
            ):
                raise ScenarioInvariantError(
                    "BIOPHARMA_COMMERCIAL_TIMING_INVALID",
                    "Commercial sales cannot precede the asset's required event path.",
                )
            if any(
                period.milestone_event_id
                and events[period.milestone_event_id].period
                != period.period
                for period in asset.periods
            ):
                raise ScenarioInvariantError(
                    "BIOPHARMA_MILESTONE_TIMING_INVALID",
                    "Milestone cash must bind the exact period of its referenced event.",
                )
        opening = (self.opening_cash, self.minimum_cash_buffer)
        if (
            any(not isinstance(item, FinancialQuantity) for item in opening)
            or any(item.kind != "money" for item in opening)
            or self.opening_cash.normalized_value <= 0
            or self.minimum_cash_buffer.normalized_value < 0
            or len(
                {
                    (
                        item.unit,
                        item.scale,
                        item.currency,
                        item.period,
                        item.as_of,
                    )
                    for item in opening
                }
            )
            != 1
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_OPENING_CASH_INVALID",
                "Opening cash and minimum cash buffer require one nonnegative money basis.",
            )
        _require_refs(
            self.opening_cash.provenance_refs,
            "BiopharmaValuationSpec.opening_cash",
            facts_only=True,
        )
        _validate_range(
            self.discount_rate_low,
            self.discount_rate_base,
            self.discount_rate_high,
            "biopharma_discount_rate",
            unit="decimal",
            positive=True,
        )
        if (
            not isinstance(self.runway_periods, tuple)
            or not self.runway_periods
            or any(
                not isinstance(item, BiopharmaRunwayPeriodSpec)
                for item in self.runway_periods
            )
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_RUNWAY_INVALID",
                "Biopharma valuation requires a typed finite runway schedule.",
            )
        runway_years = tuple(
            int(item.period[:4]) for item in self.runway_periods
        )
        if len(runway_years) != len(set(runway_years)) or any(
            current != previous + 1
            for previous, current in zip(runway_years, runway_years[1:])
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_RUNWAY_INVALID",
                "Runway periods must be unique, increasing, and contiguous.",
            )
        financing_record_ids = tuple(
            period.financing.record_id
            for period in self.runway_periods
            if period.financing is not None
        )
        if len(financing_record_ids) != len(
            set(financing_record_ids)
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_FINANCING_RECORD_DUPLICATE",
                "Each committed financing tranche record may enter the runway and dilution bridge exactly once.",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return _merge_refs(
            *(item.lineage_refs for item in self.events),
            *(item.lineage_refs for item in self.assets),
            self.opening_cash.provenance_refs,
            self.minimum_cash_buffer.provenance_refs,
            self.discount_rate_low.lineage_refs,
            self.discount_rate_base.lineage_refs,
            self.discount_rate_high.lineage_refs,
            *(item.lineage_refs for item in self.runway_periods),
        )

    def to_dict(self) -> dict[str, Any]:
        def money_range(
            owner: Any,
            prefix: str,
        ) -> dict[str, Any]:
            return {
                case_name: getattr(
                    owner,
                    f"{prefix}_{case_name}",
                ).to_dict()
                for case_name in ("low", "base", "high")
            }

        def model_range(
            owner: Any,
            prefix: str,
        ) -> dict[str, Any]:
            return {
                case_name: getattr(
                    owner,
                    f"{prefix}_{case_name}",
                ).to_dict()
                for case_name in ("low", "base", "high")
            }

        return {
            "schema_version": "biopharma_valuation_spec@1",
            "events": [
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "probability_basis": event.probability_basis,
                    "period": event.period,
                    "parent_event_ids": list(event.parent_event_ids),
                    "probability": model_range(event, "probability"),
                    "calibration_version": event.calibration_version,
                    "calibration_method_version": (
                        event.calibration_method_version
                    ),
                    "calibration_window_start": (
                        event.calibration_window_start
                    ),
                    "calibration_window_end": (
                        event.calibration_window_end
                    ),
                    "calibration_sample_size": (
                        event.calibration_sample_size
                    ),
                    "calibration_record_id": (
                        event.calibration_record_id
                    ),
                    "base_fact_refs": list(event.base_fact_refs),
                }
                for event in self.events
            ],
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "indication_id": asset.indication_id,
                    "economic_right_id": asset.economic_right_id,
                    "development_stage": asset.development_stage,
                    "required_event_ids": list(
                        asset.required_event_ids
                    ),
                    "ownership": model_range(asset, "ownership"),
                    "royalty_burden": model_range(
                        asset,
                        "royalty_burden",
                    ),
                    "launch_delay_years": model_range(
                        asset,
                        "launch_delay_years",
                    ),
                    "delay_carry_cost": money_range(
                        asset,
                        "delay_carry_cost",
                    ),
                    "periods": [
                        {
                            "period": period.period,
                            "gross_sales": money_range(
                                period,
                                "gross_sales",
                            ),
                            "development_cost": money_range(
                                period,
                                "development_cost",
                            ),
                            "milestone_cash": money_range(
                                period,
                                "milestone_cash",
                            ),
                            "milestone_event_id": (
                                period.milestone_event_id
                            ),
                            "commercial_cost_rate": model_range(
                                period,
                                "commercial_cost_rate",
                            ),
                        }
                        for period in asset.periods
                    ],
                }
                for asset in self.assets
            ],
            "opening_cash": self.opening_cash.to_dict(),
            "minimum_cash_buffer": self.minimum_cash_buffer.to_dict(),
            "discount_rate": model_range(self, "discount_rate"),
            "runway_periods": [
                {
                    "period": period.period,
                    "corporate_cash_burn": money_range(
                        period,
                        "corporate_cash_burn",
                    ),
                    "financing": (
                        period.financing.to_dict()
                        if period.financing is not None
                        else None
                    ),
                }
                for period in self.runway_periods
            ],
        }


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
    cyclical_resource: CyclicalResourceValuationSpec | None = None
    financial_institution: FinancialInstitutionValuationSpec | None = None
    biopharma: BiopharmaValuationSpec | None = None

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
        if self.cyclical_resource is not None and not isinstance(
            self.cyclical_resource, CyclicalResourceValuationSpec
        ):
            raise ScenarioInvariantError(
                "CYCLICAL_RESOURCE_SPEC_INVALID",
                "cyclical_resource must be a CyclicalResourceValuationSpec.",
            )
        if self.financial_institution is not None and not isinstance(
            self.financial_institution,
            FinancialInstitutionValuationSpec,
        ):
            raise ScenarioInvariantError(
                "FINANCIAL_INSTITUTION_SPEC_INVALID",
                "financial_institution must be a FinancialInstitutionValuationSpec.",
            )
        if self.biopharma is not None and not isinstance(
            self.biopharma,
            BiopharmaValuationSpec,
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_SPEC_INVALID",
                "biopharma must be a BiopharmaValuationSpec.",
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
    component_trace: tuple[str, ...] = ()

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
            "component_trace": [
                json.loads(item) for item in self.component_trace
            ],
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


MethodCalculationResult = tuple[
    ConditionalValueRange,
    tuple[ValuationAssumption, ...],
    tuple[ValuationSensitivity, ...],
    tuple[str, ...],
    tuple[str, ...],
]
MethodCalculation = Callable[[], MethodCalculationResult]


class ScenarioValuationEngine:
    """Reforecast coherent scenarios and triangulate gated methods independently."""

    DCF_FORMULA_VERSION = "fcff_dcf_act365@3"
    SOTP_FORMULA_VERSION = "sotp_segment_multiple@2"
    REVERSE_DCF_FORMULA_VERSION = "reverse_dcf_terminal_growth_act365@3"
    RELATIVE_FORMULA_VERSION = "gated_relative_multiple@2"
    MID_CYCLE_FORMULA_VERSION = "cycle_normalized_ev_ebitda@1"
    RESOURCE_NAV_FORMULA_VERSION = "finite_resource_nav_after_tax@1"
    CYCLICAL_HISTORY_FORMULA_VERSION = "pit_cycle_band_derived_peak@2"
    FINANCIAL_PB_FORMULA_VERSION = "justified_pb_roe_coe_act365@3"
    FINANCIAL_DDM_FORMULA_VERSION = "financial_ddm_clean_surplus_act365@3"
    FINANCIAL_RI_FORMULA_VERSION = "residual_income_clean_surplus_act365@3"
    BIOPHARMA_RNPV_FORMULA_VERSION = "pipeline_rnpv_event_tree_act365@1"
    BIOPHARMA_SOTP_FORMULA_VERSION = "pipeline_sotp_unique_rights_act365@1"

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
                    scenario.role,
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
        scenario_role: ScenarioRole,
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
        if (
            base_request.security.archetype
            == CompanyArchetype.CYCLICAL_RESOURCE
        ):
            methods.extend(
                self._cyclical_methods(
                    graph,
                    plan,
                    base_request,
                    terminal_horizon,
                )
            )
        if (
            base_request.security.archetype
            == CompanyArchetype.FINANCIAL_INSTITUTION
        ):
            methods.extend(
                self._financial_institution_methods(
                    graph,
                    plan,
                    base_request,
                    scenario_role,
                )
            )
        if base_request.security.archetype == CompanyArchetype.BIOPHARMA:
            methods.extend(
                self._biopharma_methods(
                    graph,
                    plan,
                    base_request,
                    scenario_role,
                )
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
        if (
            base_request.security.archetype
            in {
                CompanyArchetype.CYCLICAL_RESOURCE,
                CompanyArchetype.FINANCIAL_INSTITUTION,
                CompanyArchetype.BIOPHARMA,
            }
        ):
            archetype = base_request.security.archetype.value
            raise _MethodBlocked(
                (
                    "CYCLICAL_STABLE_GROWTH_DISABLED: ordinary FCFF/WACC DCF is disabled because a current commodity price or peak margin must not be capitalized in perpetuity; use finite-life NAV and mid-cycle methods."
                    if archetype == CompanyArchetype.CYCLICAL_RESOURCE.value
                    else (
                        "FINANCIAL_FCFF_DISABLED: deposits, policyholder liabilities, and regulatory capital are operating inputs rather than industrial financing debt; use P/B-ROE/COE, DDM, or residual income."
                        if archetype
                        == CompanyArchetype.FINANCIAL_INSTITUTION.value
                        else "BIOPHARMA_FCFF_DISABLED: pre-revenue pipeline economics require finite asset/indication rNPV, event probabilities, licensing terms, and cash runway rather than ordinary FCFF/WACC."
                    )
                )
            )
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
        if base_request.security.archetype in {
            CompanyArchetype.FINANCIAL_INSTITUTION,
            CompanyArchetype.BIOPHARMA,
        }:
            raise _MethodBlocked(
                (
                    "FINANCIAL_INDUSTRIAL_METHOD_DISABLED: industrial segment EV multiples are disabled for financial institutions."
                    if base_request.security.archetype
                    == CompanyArchetype.FINANCIAL_INSTITUTION
                    else "BIOPHARMA_INDUSTRIAL_METHOD_DISABLED: generic industrial SOTP is disabled; use unique-right asset/indication rNPV SOTP."
                )
            )
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
        if base_request.security.archetype in {
            CompanyArchetype.FINANCIAL_INSTITUTION,
            CompanyArchetype.BIOPHARMA,
        }:
            raise _MethodBlocked(
                (
                    "FINANCIAL_FCFF_DISABLED: reverse FCFF DCF is not meaningful for financial institutions."
                    if base_request.security.archetype
                    == CompanyArchetype.FINANCIAL_INSTITUTION
                    else "BIOPHARMA_FCFF_DISABLED: reverse FCFF DCF is not meaningful for a pre-revenue event-driven pipeline."
                )
            )
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
            if base_request.security.archetype in {
                CompanyArchetype.FINANCIAL_INSTITUTION,
                CompanyArchetype.BIOPHARMA,
            }:
                raise _MethodBlocked(
                    (
                        "FINANCIAL_GENERIC_RELATIVE_DISABLED: use the specialized P/B-ROE/COE method instead of industrial revenue multiples."
                        if base_request.security.archetype
                        == CompanyArchetype.FINANCIAL_INSTITUTION
                        else "BIOPHARMA_GENERIC_RELATIVE_DISABLED: pre-revenue pipeline value cannot be inferred from generic mature-company revenue multiples."
                    )
                )
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

    def _cyclical_methods(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        horizon: str,
    ) -> tuple[ScenarioMethodResult, ...]:
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
        common_refs = _merge_refs(
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
            self._isolate_method(
                "mid_cycle_ev_ebitda",
                curve_label
                + " Normalizes price, volume, yield, and cost instead of extrapolating peak earnings.",
                "enterprise_value",
                horizon,
                graph,
                self.MID_CYCLE_FORMULA_VERSION,
                lambda: self._mid_cycle(graph, plan, base_request, spec),
                common_refs,
            ),
            self._isolate_method(
                "resource_nav",
                curve_label
                + " Discounts only finite reserve-backed after-tax cash flows.",
                "enterprise_value",
                f"valuation_as_of={self._as_of(graph)};finite_resource_life",
                graph,
                self.RESOURCE_NAV_FORMULA_VERSION,
                lambda: self._resource_nav(graph, plan, base_request, spec),
                common_refs,
            ),
            self._isolate_method(
                "cyclical_historical_band",
                "PIT historical cross-check derives and excludes peak-earnings observations from the reusable range under a versioned threshold rule.",
                "equity_value",
                horizon,
                graph,
                self.CYCLICAL_HISTORY_FORMULA_VERSION,
                lambda: self._cyclical_historical_band(
                    graph, plan, base_request, spec
                ),
                common_refs,
            ),
        )

    def _validate_cyclical_runtime(
        self,
        graph: ForecastGraph,
        base_request: ForecastRequest,
        spec: CyclicalResourceValuationSpec,
    ) -> None:
        periods = self._periods(graph)
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
        curve_keys = {
            (item.segment_id, item.period) for item in spec.commodity_curve
        }
        asset_ids = {item.segment_id for item in spec.assets}
        if (
            not forecast_curve_keys.issubset(curve_keys)
            or curve_keys != schedule_curve_keys
        ):
            raise _MethodBlocked(
                "COMMODITY_CURVE_COVERAGE_INVALID: curve must cover every forecast and finite resource-schedule segment-period exactly once."
            )
        if asset_ids != set(base_request.security.segment_ids):
            raise _MethodBlocked(
                "RESOURCE_ASSET_COVERAGE_INVALID: resource assets must cover every modeled segment exactly once."
            )
        if any(
            asset.schedule[0].period != periods[0]
            for asset in spec.assets
        ):
            raise _MethodBlocked(
                "RESOURCE_SCHEDULE_ANCHOR_INVALID: every finite-life resource schedule must begin at the first forward forecast period."
            )
        if (
            date.fromisoformat(spec.curve_as_of)
            > date.fromisoformat(self._as_of(graph))
            or any(
                item.price_base.as_of != self._as_of(graph)
                for item in spec.commodity_curve
            )
        ):
            raise _MethodBlocked(
                "COMMODITY_CURVE_AS_OF_INVALID: curve version and points must bind the frozen valuation as-of."
            )
        reporting_currency = base_request.security.reporting_currency
        if any(
            point.price_base.currency != reporting_currency
            for point in spec.commodity_curve
        ) or any(
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
        ):
            raise _MethodBlocked(
                "RESOURCE_REPORTING_CURRENCY_MISMATCH: every asset curve, cost, opex, and capex input must use the reporting currency unless an explicit FX conversion model is present."
            )
        if (
            spec.peak_earnings_threshold.as_of != self._as_of(graph)
            or spec.peak_earnings_threshold.period != self._as_of(graph)
        ):
            raise _MethodBlocked(
                "CYCLICAL_PEAK_THRESHOLD_BINDING_INVALID: peak-earnings rule must bind the valuation as-of."
            )
        self._validate_cyclical_evidence(base_request, spec)

    def _validate_cyclical_evidence(
        self,
        base_request: ForecastRequest,
        spec: CyclicalResourceValuationSpec,
    ) -> None:
        facts = {
            fact.fact_id: fact for fact in base_request.data_snapshot.facts
        }

        def exact_fact(
            quantity: ForecastQuantity | FinancialQuantity,
            *,
            scope: str,
            segment_id: str,
            available_by: str,
            official_required: bool,
            metric_id: str,
        ) -> None:
            refs = (
                quantity.lineage_refs
                if isinstance(quantity, ForecastQuantity)
                else quantity.provenance_refs
            )
            resolved = tuple(
                facts.get(ref.removeprefix("Fact:")) for ref in refs
            )
            if (
                not refs
                or any(not ref.startswith("Fact:") for ref in refs)
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
            ):
                raise _MethodBlocked(
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
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: CyclicalResourceValuationSpec,
    ) -> MethodCalculationResult:
        self._validate_cyclical_runtime(graph, base_request, spec)
        self._validate_method_bridge(
            graph,
            plan.terminal_value_bridge,
            base_request,
        )
        periods = self._periods(graph)
        curve = {
            (item.segment_id, item.period): item
            for item in spec.commodity_curve
        }
        assets = {item.segment_id: item for item in spec.assets}
        reference_graph = ForecastEngine().build(base_request)
        case_ebitda = [Decimal("0"), Decimal("0"), Decimal("0")]
        lineage: tuple[str, ...] = ()
        for segment_id in base_request.security.segment_ids:
            asset = assets[segment_id]
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
                raise _MethodBlocked(
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
                    (
                        "production_low",
                        "unit_cost_low",
                        production_totals[0],
                    ),
                    (
                        "production_base",
                        "unit_cost_base",
                        production_totals[1],
                    ),
                    (
                        "production_high",
                        "unit_cost_high",
                        production_totals[2],
                    ),
                )
            )
            cost_factors = (
                weighted_costs[2] / weighted_costs[1],
                Decimal("1"),
                weighted_costs[0] / weighted_costs[1],
            )
            for period in periods:
                point = curve[(segment_id, period)]
                prices = (
                    point.price_low.normalized_value,
                    point.price_base.normalized_value,
                    point.price_high.normalized_value,
                )
                volume = graph.quantity(f"{segment_id}.volume.{period}")
                scenario_asp = graph.quantity(f"{segment_id}.asp.{period}")
                reference_asp = reference_graph.quantity(
                    f"{segment_id}.asp.{period}"
                )
                unit_cost = graph.quantity(f"{segment_id}.unit_cost.{period}")
                operating_expense = graph.quantity(
                    f"{segment_id}.operating_expense.{period}"
                )
                if (
                    volume.unit != asset.reserve_quantity.unit
                    or unit_cost.unit != point.price_base.unit
                    or unit_cost.currency != point.price_base.currency
                    or operating_expense.currency != point.price_base.currency
                    or reference_asp.normalized_value <= 0
                ):
                    raise _MethodBlocked(
                        "RESOURCE_UNIT_MISMATCH: curve price, production, reserve, cost, and operating expense dimensions must reconcile."
                    )
                for index in range(3):
                    modeled_volume = (
                        volume.normalized_value * production_factors[index]
                    )
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
                lineage = _merge_refs(
                    lineage,
                    point.lineage_refs,
                    asset.lineage_refs,
                    volume.lineage_refs,
                    scenario_asp.lineage_refs,
                    reference_asp.lineage_refs,
                    unit_cost.lineage_refs,
                    operating_expense.lineage_refs,
                )
        normalized = tuple(
            value / Decimal(len(periods)) for value in case_ebitda
        )
        multiples = (
            spec.mid_cycle_multiple_low.normalized_value,
            spec.mid_cycle_multiple_base.normalized_value,
            spec.mid_cycle_multiple_high.normalized_value,
        )
        values = tuple(
            ebitda * multiple
            for ebitda, multiple in zip(normalized, multiples, strict=True)
        )
        lineage = _merge_refs(
            lineage,
            spec.mid_cycle_multiple_low.lineage_refs,
            spec.mid_cycle_multiple_base.lineage_refs,
            spec.mid_cycle_multiple_high.lineage_refs,
            (f"Assumption:formula:{self.MID_CYCLE_FORMULA_VERSION}",),
        )
        value_range = self._bridge_range(
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
                self._model_quantity(
                    normalized[1],
                    unit=base_request.security.reporting_currency,
                    period=periods[-1],
                    as_of=self._as_of(graph),
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
            self._cyclical_sensitivities(graph, base_request, spec),
            lineage,
            (
                "No terminal commodity-price perpetuity is used; the result is conditional on a finite explicit cycle window.",
            ),
        )

    def _resource_nav(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: CyclicalResourceValuationSpec,
    ) -> MethodCalculationResult:
        self._validate_cyclical_runtime(graph, base_request, spec)
        self._validate_method_bridge(
            graph,
            plan.present_value_bridge,
            base_request,
        )
        forecast_periods = self._periods(graph)
        curve = {
            (item.segment_id, item.period): item
            for item in spec.commodity_curve
        }
        assets = {item.segment_id: item for item in spec.assets}
        reference_graph = ForecastEngine().build(base_request)
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
                    graph.quantity(
                        f"{segment_id}.volume.{period}"
                    ).normalized_value
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
                    graph.quantity(
                        f"{segment_id}.unit_cost.{period}"
                    ).normalized_value
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
                    graph.quantity(
                        f"{segment_id}.asp.{period}"
                    ).normalized_value
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
                    graph.quantity(
                        f"{segment_id}.capex.{period}"
                    ).normalized_value
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
                raise _MethodBlocked(
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
                    schedule.production_base.unit
                    != asset.reserve_quantity.unit
                    or point.price_base.unit != schedule.unit_cost_base.unit
                    or point.price_base.currency
                    != schedule.unit_cost_base.currency
                    or schedule.operating_expense_base.currency
                    != schedule.unit_cost_base.currency
                    or schedule.maintenance_capex_base.currency
                    != schedule.unit_cost_base.currency
                ):
                    raise _MethodBlocked(
                        "RESOURCE_UNIT_MISMATCH: NAV curve, schedule production, reserve, cost, opex, tax, and capex dimensions must reconcile."
                    )
                for index in range(3):
                    modeled_production = production[index] * volume_factor
                    saleable = modeled_production * yields[index]
                    extracted[index] += modeled_production
                    pre_tax = (
                        saleable * prices[index] * price_factor
                        - modeled_production
                        * unit_costs[index]
                        * cost_factor
                        - operating_expenses[index] * opex_factor
                    )
                    after_tax = max(pre_tax, Decimal("0")) * (
                        Decimal("1") - schedule.tax_rate.normalized_value
                    ) + min(pre_tax, Decimal("0"))
                    cash_flow = (
                        after_tax
                        - maintenance_capex[index] * capex_factor
                    )
                    values[index] += cash_flow / (
                        (Decimal("1") + rates[index]) ** year_index
                    )
                lineage = _merge_refs(
                    lineage,
                    point.lineage_refs,
                    asset.lineage_refs,
                    *(
                        graph.quantity(
                            f"{segment_id}.{metric}.{period}"
                        ).lineage_refs
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
                amount > asset.reserve_quantity.normalized_value
                for amount in extracted
            ):
                raise _MethodBlocked(
                    "RESOURCE_RESERVE_OVER_EXTRACTION: modeled saleable production exceeds documented reserves."
                )
        lineage = _merge_refs(
            lineage,
            spec.nav_discount_rate_low.lineage_refs,
            spec.nav_discount_rate_base.lineage_refs,
            spec.nav_discount_rate_high.lineage_refs,
            (f"Assumption:formula:{self.RESOURCE_NAV_FORMULA_VERSION}",),
        )
        value_range = self._bridge_range(
            graph,
            plan.present_value_bridge,
            "enterprise_value",
            tuple(values),
            self.RESOURCE_NAV_FORMULA_VERSION,
            basis_period=self._as_of(graph),
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
            self._cyclical_sensitivities(graph, base_request, spec),
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
        self._validate_cyclical_runtime(graph, base_request, spec)
        self._validate_method_bridge(
            graph,
            plan.terminal_value_bridge,
            base_request,
        )
        denominator_values = tuple(
            item.pit_earnings_denominator.normalized_value
            for item in spec.historical_observations
        )
        median_denominator = _percentile(
            denominator_values,
            Decimal("0.50"),
        )
        peak_cutoff = (
            median_denominator
            * spec.peak_earnings_threshold.normalized_value
        )
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
            raise _MethodBlocked(
                "CYCLICAL_HISTORY_INSUFFICIENT: fewer than three non-peak PIT observations remain."
            )
        if any(
            date.fromisoformat(item.market_value.as_of)
            > date.fromisoformat(self._as_of(graph))
            for item in observations
        ):
            raise _MethodBlocked(
                "CYCLICAL_HISTORY_LOOKAHEAD: historical observations must be available by the valuation as-of."
            )
        multiples = tuple(
            item.reported_multiple.normalized_value for item in observations
        )
        ranges = (
            _percentile(multiples, Decimal("0.25")),
            _percentile(multiples, Decimal("0.50")),
            _percentile(multiples, Decimal("0.75")),
        )
        periods = self._periods(graph)
        denominator_values = tuple(
            graph.quantity(f"company.ebit.{period}").normalized_value
            for period in periods
        )
        denominator = sum(denominator_values, Decimal("0")) / Decimal(
            len(denominator_values)
        )
        if denominator <= 0:
            raise _MethodBlocked(
                "CYCLICAL_HISTORY_DENOMINATOR_NON_POSITIVE: normalized forecast EBIT must be positive."
            )
        values = tuple(denominator * multiple for multiple in ranges)
        lineage = _merge_refs(
            *(item.lineage_refs for item in spec.historical_observations),
            spec.peak_earnings_threshold.lineage_refs,
            *(
                graph.quantity(f"company.ebit.{period}").lineage_refs
                for period in periods
            ),
            (f"Assumption:formula:{self.CYCLICAL_HISTORY_FORMULA_VERSION}",),
        )
        value_range = self._bridge_range(
            graph,
            plan.terminal_value_bridge,
            "equity_value",
            values,
            self.CYCLICAL_HISTORY_FORMULA_VERSION,
            basis_period=periods[-1],
            basis_refs=lineage,
        )
        multiple_quantities = tuple(
            self._model_quantity(
                value,
                unit="x",
                period=self._as_of(graph),
                as_of=self._as_of(graph),
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
                    self._model_quantity(
                        denominator,
                        unit=base_request.security.reporting_currency,
                        period=periods[-1],
                        as_of=self._as_of(graph),
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
        base_request: ForecastRequest,
        spec: CyclicalResourceValuationSpec,
    ) -> tuple[ValuationSensitivity, ...]:
        periods = self._periods(graph)
        assets = spec.assets
        reference_graph = ForecastEngine().build(base_request)
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
                    raise _MethodBlocked(
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
        refs = _merge_refs(
            spec.lineage_refs,
            *(
                graph.quantity(
                    f"{segment_id}.{metric}.{period}"
                ).lineage_refs
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
                    self._model_quantity(
                        value,
                        unit=unit,
                        period=self._as_of(graph),
                        as_of=self._as_of(graph),
                        refs=refs,
                    )
                    for value in values
                ),
            )

        grade_values = tuple(
            sum(
                (
                    getattr(asset, field_name).normalized_value
                    for asset in assets
                ),
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
                (
                    "production_low",
                    "unit_cost_low",
                    production_values[0],
                ),
                (
                    "production_base",
                    "unit_cost_base",
                    production_values[1],
                ),
                (
                    "production_high",
                    "unit_cost_high",
                    production_values[2],
                ),
            )
        )
        opex_values = tuple(
            sum(
                (
                    getattr(item, field_name).normalized_value
                    * scenario_factors[asset.segment_id][
                        "operating_expense"
                    ]
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

    def _financial_institution_methods(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        scenario_role: ScenarioRole,
    ) -> tuple[ScenarioMethodResult, ...]:
        spec = plan.financial_institution
        method_definitions = (
            (
                "justified_pb",
                self.FINANCIAL_PB_FORMULA_VERSION,
                self._financial_pb,
            ),
            (
                "dividend_discount_model",
                self.FINANCIAL_DDM_FORMULA_VERSION,
                self._financial_ddm,
            ),
            (
                "residual_income",
                self.FINANCIAL_RI_FORMULA_VERSION,
                self._financial_residual_income,
            ),
        )
        horizon = (
            f"valuation_as_of={self._as_of(graph)};"
            f"financial_periods={self._periods(graph)[0]}..{self._periods(graph)[-1]}"
        )
        if spec is None:
            return tuple(
                ScenarioMethodResult(
                    method_id=method_id,
                    status="blocked",
                    applicability=(
                        "Financial-institution valuation requires typed book value, "
                        "regulatory capital, clean-surplus, ROE/COE, payout, dilution, "
                        "and institution-specific operating metrics."
                    ),
                    value_basis="equity_value",
                    horizon=horizon,
                    assumptions=(),
                    formula_version=formula_version,
                    conditional_value_range=None,
                    sensitivity=(),
                    diagnostics=(
                        "FINANCIAL_SPECIALIZED_INPUT_MISSING: no financial-institution valuation specification was supplied.",
                    ),
                    lineage_refs=(
                        "Assumption:financial_institution_spec_missing",
                    ),
                )
                for method_id, formula_version, _ in method_definitions
            )
        common_refs = _merge_refs(
            spec.lineage_refs,
            plan.present_value_bridge.provenance_refs,
        )
        return tuple(
            self._isolate_method(
                method_id,
                (
                    f"Applicable to {spec.institution_type}; uses regulatory-capital "
                    "and clean-surplus economics rather than industrial enterprise debt."
                ),
                "equity_value",
                horizon,
                graph,
                formula_version,
                lambda calculation=calculation: calculation(
                    graph,
                    plan,
                    base_request,
                    spec,
                    scenario_role,
                ),
                common_refs,
            )
            for method_id, formula_version, calculation in method_definitions
        )

    def _validate_financial_runtime(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: FinancialInstitutionValuationSpec,
    ) -> None:
        self._validate_method_bridge(
            graph,
            plan.present_value_bridge,
            base_request,
        )
        periods = self._periods(graph)
        if tuple(item.period for item in spec.periods) != periods:
            raise _MethodBlocked(
                "FINANCIAL_PERIOD_COVERAGE_INVALID: specialized financial schedule must exactly cover the routed forecast periods."
            )
        if any(
            quantity.as_of != self._as_of(graph)
            for quantity in (
                spec.minimum_regulatory_capital_ratio,
                spec.specialized_risk_limit,
                spec.cost_of_equity_low,
                spec.cost_of_equity_base,
                spec.cost_of_equity_high,
                spec.terminal_growth_low,
                spec.terminal_growth_base,
                spec.terminal_growth_high,
            )
        ):
            raise _MethodBlocked(
                "FINANCIAL_AS_OF_INVALID: financial valuation assumptions must bind the frozen valuation as-of."
            )
        period_quantities = tuple(
            quantity
            for period in spec.periods
            for quantity in (
                *(
                    value
                    for field in fields(period)
                    for value in (getattr(period, field.name),)
                    if isinstance(
                        value,
                        (ForecastQuantity, FinancialQuantity),
                    )
                ),
                *(
                    quantity
                    for metric in period.operating_metrics
                    for quantity in (
                        metric.low,
                        metric.base,
                        metric.high,
                    )
                ),
            )
        )
        if any(
            quantity.as_of != self._as_of(graph)
            for quantity in period_quantities
        ):
            raise _MethodBlocked(
                "FINANCIAL_AS_OF_INVALID: every period-level driver and adjustment must bind the frozen valuation as-of."
            )
        opening_balances = (
            spec.opening_book_value,
            spec.opening_regulatory_capital,
            spec.opening_risk_weighted_assets,
        )
        if any(
            quantity.period
            != plan.present_value_bridge.balance_sheet_period
            or quantity.as_of != self._as_of(graph)
            for quantity in opening_balances
        ):
            raise _MethodBlocked(
                "FINANCIAL_OPENING_PERIOD_INVALID: opening balances must bind the present-value bridge balance-sheet period and frozen as-of."
            )
        if (
            spec.opening_regulatory_capital.normalized_value
            / spec.opening_risk_weighted_assets.normalized_value
            < spec.minimum_regulatory_capital_ratio.normalized_value
        ):
            raise _MethodBlocked(
                "FINANCIAL_OPENING_CAPITAL_BREACH: opening regulatory capital is already below the declared minimum."
            )
        reporting_currency = base_request.security.reporting_currency
        if any(
            item.currency != reporting_currency
            for item in (
                spec.opening_book_value,
                spec.opening_regulatory_capital,
                spec.opening_risk_weighted_assets,
            )
        ) or any(
            quantity.currency != reporting_currency
            for period in spec.periods
            for quantity in (
                period.clean_surplus_adjustment_low,
                period.clean_surplus_adjustment_base,
                period.clean_surplus_adjustment_high,
                period.regulatory_capital_adjustment_low,
                period.regulatory_capital_adjustment_base,
                period.regulatory_capital_adjustment_high,
            )
        ):
            raise _MethodBlocked(
                "FINANCIAL_CURRENCY_MISMATCH: all book, capital, RWA, and adjustment quantities must use the reporting currency."
            )
        facts = {
            fact.fact_id: fact for fact in base_request.data_snapshot.facts
        }
        for metric_id, quantity in (
            ("opening_book_value", spec.opening_book_value),
            (
                "opening_regulatory_capital",
                spec.opening_regulatory_capital,
            ),
            (
                "opening_risk_weighted_assets",
                spec.opening_risk_weighted_assets,
            ),
        ):
            resolved = tuple(
                facts.get(ref.removeprefix("Fact:"))
                for ref in quantity.provenance_refs
            )
            if (
                any(fact is None for fact in resolved)
                or not any(
                    fact.subject_id == graph.security_id
                    and fact.scope == "company"
                    and fact.metric_id == metric_id
                    and fact.value == quantity.normalized_value
                    and fact.unit == quantity.unit
                    and fact.currency == quantity.currency
                    and fact.period == quantity.period
                    and fact.official
                    and date.fromisoformat(fact.available_at)
                    <= date.fromisoformat(self._as_of(graph))
                    for fact in resolved
                    if fact is not None
                )
            ):
                raise _MethodBlocked(
                    "FINANCIAL_EVIDENCE_INVALID: opening book value, regulatory capital, and RWA must resolve exactly through official frozen facts."
                )

    def _financial_projections(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: FinancialInstitutionValuationSpec,
        scenario_role: ScenarioRole,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        self._validate_financial_runtime(
            graph,
            plan,
            base_request,
            spec,
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
        selected_growth = getattr(
            spec,
            f"terminal_growth_{scenario_case}",
        ).normalized_value
        terminal_clean_adjustment = getattr(
            spec.periods[-1],
            f"clean_surplus_adjustment_{scenario_case}",
        ).normalized_value
        if terminal_clean_adjustment != 0:
            raise _MethodBlocked(
                "FINANCIAL_TERMINAL_CLEAN_SURPLUS_UNSUPPORTED: a continuing terminal clean-surplus adjustment requires an explicit separate terminal model."
            )
        discount_times = self._discount_times(
            tuple(item.period for item in spec.periods),
            self._as_of(graph),
        )
        projections: list[dict[str, Any]] = []
        case_fields = (
            ("low", spec.cost_of_equity_high),
            ("base", spec.cost_of_equity_base),
            ("high", spec.cost_of_equity_low),
        )
        for case_name, coe_quantity in case_fields:
            book = spec.opening_book_value.normalized_value
            regulatory_capital = (
                spec.opening_regulatory_capital.normalized_value
            )
            rwa = spec.opening_risk_weighted_assets.normalized_value
            dividends: list[Decimal] = []
            residual_incomes: list[Decimal] = []
            opening_books: list[Decimal] = []
            capital_ratios: list[Decimal] = []
            last_roe = Decimal("0")
            last_payout = Decimal("0")
            dilution = Decimal("1")
            sustainable_growth = Decimal("0")
            selected_metrics: dict[str, Decimal] = {}
            previous_time = Decimal("0")
            for period, timing in zip(
                spec.periods,
                discount_times,
                strict=True,
            ):
                opening_books.append(book)
                metrics = {
                    item.metric_id: item
                    for item in period.operating_metrics
                }
                roe = getattr(
                    period,
                    f"roe_{scenario_case}",
                ).normalized_value
                operating_exposure = getattr(
                    period,
                    f"operating_exposure_to_equity_{scenario_case}",
                ).normalized_value
                if spec.institution_type == "bank":
                    nim = getattr(
                        metrics["nim"],
                        scenario_case,
                    ).normalized_value
                    credit_cost = getattr(
                        metrics["credit_cost"],
                        adverse_case,
                    ).normalized_value
                    npl_ratio = getattr(
                        metrics["npl_ratio"],
                        adverse_case,
                    ).normalized_value
                    roe = roe + (nim - credit_cost) * operating_exposure
                    selected_metrics = {
                        "nim": nim,
                        "credit_cost": credit_cost,
                        "npl_ratio": npl_ratio,
                        "operating_exposure_to_equity": operating_exposure,
                    }
                    if (
                        npl_ratio
                        > spec.specialized_risk_limit.normalized_value
                    ):
                        raise _MethodBlocked(
                            "FINANCIAL_SPECIALIZED_RISK_BREACH: projected bank NPL ratio exceeds the declared asset-quality limit."
                        )
                elif spec.institution_type == "insurance":
                    combined_ratio = getattr(
                        metrics["combined_ratio"],
                        adverse_case,
                    ).normalized_value
                    solvency_ratio = getattr(
                        metrics["solvency_ratio"],
                        scenario_case,
                    ).normalized_value
                    roe = (
                        roe
                        + (Decimal("1") - combined_ratio)
                        * operating_exposure
                    )
                    selected_metrics = {
                        "combined_ratio": combined_ratio,
                        "solvency_ratio": solvency_ratio,
                        "operating_exposure_to_equity": operating_exposure,
                    }
                    if (
                        solvency_ratio
                        < spec.specialized_risk_limit.normalized_value
                    ):
                        raise _MethodBlocked(
                            "FINANCIAL_SPECIALIZED_CAPITAL_BREACH: projected insurance solvency ratio falls below the declared regulatory minimum."
                        )
                else:
                    net_capital_ratio = getattr(
                        metrics["net_capital_ratio"],
                        scenario_case,
                    ).normalized_value
                    fee_income_yield = getattr(
                        metrics["fee_income_yield"],
                        scenario_case,
                    ).normalized_value
                    roe = (
                        roe
                        + fee_income_yield
                        * operating_exposure
                    )
                    selected_metrics = {
                        "net_capital_ratio": net_capital_ratio,
                        "fee_income_yield": fee_income_yield,
                        "operating_exposure_to_equity": operating_exposure,
                    }
                    if (
                        net_capital_ratio
                        < spec.specialized_risk_limit.normalized_value
                    ):
                        raise _MethodBlocked(
                            "FINANCIAL_SPECIALIZED_CAPITAL_BREACH: projected broker net-capital ratio falls below the declared regulatory minimum."
                        )
                payout = getattr(
                    period,
                    f"payout_{scenario_case}",
                ).normalized_value
                rwa_growth = getattr(
                    period,
                    f"rwa_growth_{adverse_case}",
                ).normalized_value
                clean_adjustment = getattr(
                    period,
                    f"clean_surplus_adjustment_{scenario_case}",
                ).normalized_value
                capital_adjustment = getattr(
                    period,
                    f"regulatory_capital_adjustment_{scenario_case}",
                ).normalized_value
                period_dilution = getattr(
                    period,
                    f"dilution_factor_{adverse_case}",
                ).normalized_value
                dilution *= period_dilution
                net_income = book * roe
                dividend = net_income * payout
                interval_required_return = (
                    (Decimal("1") + coe_quantity.normalized_value)
                    ** (timing - previous_time)
                    - Decimal("1")
                )
                residual_income = (
                    net_income
                    + clean_adjustment
                    - interval_required_return * book
                )
                sustainable_growth = (
                    net_income - dividend + clean_adjustment
                ) / book
                book = book + net_income - dividend + clean_adjustment
                regulatory_capital = (
                    regulatory_capital
                    + net_income
                    - dividend
                    + capital_adjustment
                )
                rwa = rwa * (Decimal("1") + rwa_growth)
                if book <= 0 or rwa <= 0 or dilution <= 0:
                    raise _MethodBlocked(
                        "FINANCIAL_BALANCE_INVALID: book value, RWA, and dilution must remain positive."
                    )
                capital_ratio = regulatory_capital / rwa
                if (
                    capital_ratio
                    < spec.minimum_regulatory_capital_ratio.normalized_value
                ):
                    raise _MethodBlocked(
                        "FINANCIAL_REGULATORY_CAPITAL_BREACH: projected capital falls below the declared regulatory minimum."
                    )
                dividends.append(dividend)
                residual_incomes.append(residual_income)
                capital_ratios.append(capital_ratio)
                last_roe = roe
                last_payout = payout
                previous_time = timing
            if (
                abs(sustainable_growth - selected_growth)
                > Decimal("0.02")
            ):
                raise _MethodBlocked(
                    "FINANCIAL_TERMINAL_GROWTH_INCONSISTENT: declared terminal growth must reconcile within two percentage points of ROE retention plus the clean-surplus adjustment."
                )
            if coe_quantity.normalized_value <= sustainable_growth:
                raise _MethodBlocked(
                    "FINANCIAL_TERMINAL_SPREAD_INVALID: cost of equity must exceed sustainable clean-surplus growth."
                )
            projections.append(
                {
                    "case": case_name,
                    "scenario_case": scenario_case,
                    "book": book,
                    "dividends": tuple(dividends),
                    "residual_incomes": tuple(residual_incomes),
                    "opening_books": tuple(opening_books),
                    "capital_ratios": tuple(capital_ratios),
                    "roe": last_roe,
                    "payout": last_payout,
                    "dilution": dilution,
                    "coe": coe_quantity.normalized_value,
                    "growth": sustainable_growth,
                    "declared_growth": selected_growth,
                    "operating_metrics": selected_metrics,
                }
            )
        return cast(
            tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
            tuple(projections),
        )

    def _financial_common_output(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: FinancialInstitutionValuationSpec,
        values: tuple[Decimal, Decimal, Decimal],
        projections: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
        *,
        formula_version: str,
        method_diagnostic: str,
    ) -> MethodCalculationResult:
        if not values[0] <= values[1] <= values[2]:
            raise _MethodBlocked(
                "FINANCIAL_VALUE_RANGE_INVALID: stress/base/improvement assumptions did not produce an ordered conditional value range."
            )
        lineage = _merge_refs(
            spec.lineage_refs,
            graph.quantity(
                f"financial.horizon.{self._periods(graph)[0]}"
            ).lineage_refs,
            (
                "Assumption:financial_scenario_case:"
                f"{projections[0]['scenario_case']}",
            ),
            (f"Assumption:formula:{formula_version}",),
        )
        value_range = self._bridge_range(
            graph,
            plan.present_value_bridge,
            "equity_value",
            values,
            formula_version,
            basis_period=plan.present_value_bridge.balance_sheet_period,
            basis_refs=lineage,
            share_multipliers=cast(
                tuple[Decimal, Decimal, Decimal],
                tuple(item["dilution"] for item in projections),
            ),
            share_multiplier_ref_prefix="financial_cumulative_dilution",
        )
        terminal = spec.periods[-1]
        sensitivities = (
            ValuationSensitivity(
                "terminal_roe",
                terminal.roe_low,
                terminal.roe_base,
                terminal.roe_high,
            ),
            ValuationSensitivity(
                "cost_of_equity",
                spec.cost_of_equity_low,
                spec.cost_of_equity_base,
                spec.cost_of_equity_high,
            ),
            ValuationSensitivity(
                "payout_ratio",
                terminal.payout_low,
                terminal.payout_base,
                terminal.payout_high,
            ),
            ValuationSensitivity(
                "dilution_factor",
                terminal.dilution_factor_low,
                terminal.dilution_factor_base,
                terminal.dilution_factor_high,
            ),
            ValuationSensitivity(
                "operating_exposure_to_equity",
                terminal.operating_exposure_to_equity_low,
                terminal.operating_exposure_to_equity_base,
                terminal.operating_exposure_to_equity_high,
            ),
            *(
                ValuationSensitivity(
                    metric.metric_id,
                    metric.low,
                    metric.base,
                    metric.high,
                )
                for metric in terminal.operating_metrics
            ),
        )
        assumptions = (
            ValuationAssumption(
                "minimum_regulatory_capital_ratio",
                spec.minimum_regulatory_capital_ratio,
            ),
            ValuationAssumption(
                "specialized_risk_limit",
                spec.specialized_risk_limit,
            ),
            ValuationAssumption(
                "cost_of_equity",
                spec.cost_of_equity_base,
            ),
            ValuationAssumption(
                "declared_terminal_growth_guardrail",
                spec.terminal_growth_base,
            ),
        )
        diagnostics = (
            method_diagnostic,
            (
                "Scenario-specific financial drivers were selected as "
                f"{projections[0]['scenario_case']}; terminal clean-surplus "
                f"growth={_decimal_text(projections[1]['growth'])}, declared "
                f"growth={_decimal_text(projections[1]['declared_growth'])}, "
                f"cumulative share factor={_decimal_text(projections[1]['dilution'])}."
            ),
            "Explicit financial cash flows and terminal value are discounted from the frozen valuation date to exact period ends using ACT/365.",
            "Values are conditional on clean-surplus reconciliation and regulatory-capital compliance; no cross-method averaging is performed.",
        )
        return value_range, assumptions, sensitivities, lineage, diagnostics

    def _financial_pb(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: FinancialInstitutionValuationSpec,
        scenario_role: ScenarioRole,
    ) -> MethodCalculationResult:
        projections = self._financial_projections(
            graph,
            plan,
            base_request,
            spec,
            scenario_role,
        )
        discount_times = self._discount_times(
            tuple(item.period for item in spec.periods),
            self._as_of(graph),
        )
        values: list[Decimal] = []
        for projection in projections:
            coe = projection["coe"]
            growth = projection["growth"]
            explicit_dividends = sum(
                (
                    dividend
                    / ((Decimal("1") + coe) ** timing)
                    for timing, dividend in zip(
                        discount_times,
                        projection["dividends"],
                        strict=True,
                    )
                ),
                Decimal("0"),
            )
            terminal_equity = (
                projection["book"]
                * (projection["roe"] - growth)
                / (coe - growth)
            )
            values.append(
                explicit_dividends
                + terminal_equity
                / ((Decimal("1") + coe) ** discount_times[-1])
            )
        return self._financial_common_output(
            graph,
            plan,
            base_request,
            spec,
            cast(tuple[Decimal, Decimal, Decimal], tuple(values)),
            projections,
            formula_version=self.FINANCIAL_PB_FORMULA_VERSION,
            method_diagnostic=(
                "Justified P/B adds explicit distributable dividends to the discounted terminal ROE/COE franchise value; dilution changes only the per-share denominator."
            ),
        )

    def _financial_ddm(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: FinancialInstitutionValuationSpec,
        scenario_role: ScenarioRole,
    ) -> MethodCalculationResult:
        projections = self._financial_projections(
            graph,
            plan,
            base_request,
            spec,
            scenario_role,
        )
        discount_times = self._discount_times(
            tuple(item.period for item in spec.periods),
            self._as_of(graph),
        )
        values: list[Decimal] = []
        for projection in projections:
            coe = projection["coe"]
            growth = projection["growth"]
            dividends = projection["dividends"]
            explicit = sum(
                (
                    dividend
                    / ((Decimal("1") + coe) ** timing)
                    for timing, dividend in zip(
                        discount_times,
                        dividends,
                        strict=True,
                    )
                ),
                Decimal("0"),
            )
            terminal_dividend = (
                projection["book"]
                * projection["roe"]
                * projection["payout"]
            )
            terminal = terminal_dividend / (coe - growth)
            values.append(
                explicit
                + terminal
                / (
                    (Decimal("1") + coe)
                    ** discount_times[-1]
                )
            )
        return self._financial_common_output(
            graph,
            plan,
            base_request,
            spec,
            cast(tuple[Decimal, Decimal, Decimal], tuple(values)),
            projections,
            formula_version=self.FINANCIAL_DDM_FORMULA_VERSION,
            method_diagnostic=(
                "DDM discounts distributable cash only after the projected regulatory-capital minimum remains satisfied."
            ),
        )

    def _financial_residual_income(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: FinancialInstitutionValuationSpec,
        scenario_role: ScenarioRole,
    ) -> MethodCalculationResult:
        projections = self._financial_projections(
            graph,
            plan,
            base_request,
            spec,
            scenario_role,
        )
        discount_times = self._discount_times(
            tuple(item.period for item in spec.periods),
            self._as_of(graph),
        )
        values: list[Decimal] = []
        for projection in projections:
            coe = projection["coe"]
            growth = projection["growth"]
            explicit = sum(
                (
                    residual_income
                    / ((Decimal("1") + coe) ** timing)
                    for timing, residual_income in zip(
                        discount_times,
                        projection["residual_incomes"],
                        strict=True,
                    )
                ),
                Decimal("0"),
            )
            terminal_residual_income = (
                projection["book"]
                * (projection["roe"] - coe)
                / (coe - growth)
            )
            values.append(
                spec.opening_book_value.normalized_value
                + explicit
                + terminal_residual_income
                / (
                    (Decimal("1") + coe)
                    ** discount_times[-1]
                )
            )
        return self._financial_common_output(
            graph,
            plan,
            base_request,
            spec,
            cast(tuple[Decimal, Decimal, Decimal], tuple(values)),
            projections,
            formula_version=self.FINANCIAL_RI_FORMULA_VERSION,
            method_diagnostic=(
                "Residual income values only returns above COE and reconciles through the clean-surplus book-value roll-forward."
            ),
        )

    def _biopharma_methods(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        scenario_role: ScenarioRole,
    ) -> tuple[ScenarioMethodResult, ...]:
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
            f"valuation_as_of={self._as_of(graph)};"
            f"pipeline_periods={self._periods(graph)[0]}..{self._periods(graph)[-1]}"
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
        common_refs = _merge_refs(
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
            result = self._isolate_method(
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
                projection = self._biopharma_projection(
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
                            key: _decimal_text(value)
                            for key, value in projection[
                                "event_probabilities"
                            ].items()
                        },
                        "asset_cash_flows": list(
                            projection["asset_cash_flow_trace"]
                        ),
                        "corporate_cash_flows": list(
                            projection["corporate_cash_flow_trace"]
                        ),
                        "discount_rate_cases": [
                            _decimal_text(value)
                            for value in projection[
                                "discount_rate_cases"
                            ]
                        ],
                        "enterprise_value_range": [
                            _decimal_text(value)
                            for value in projection["values"]
                        ],
                        "runway_paths": [
                            {
                                **path,
                                "ending_cash": _decimal_text(
                                    path["ending_cash"]
                                ),
                                "minimum_cash": _decimal_text(
                                    path["minimum_cash"]
                                ),
                                "period_ledger": [
                                    {
                                        **entry,
                                        "opening_cash": _decimal_text(
                                            entry["opening_cash"]
                                        ),
                                        "asset_cash_flow": (
                                            _decimal_text(
                                                entry[
                                                    "asset_cash_flow"
                                                ]
                                            )
                                        ),
                                        "corporate_cash_burn": (
                                            _decimal_text(
                                                entry[
                                                    "corporate_cash_burn"
                                                ]
                                            )
                                        ),
                                        "committed_financing": (
                                            _decimal_text(
                                                entry[
                                                    "committed_financing"
                                                ]
                                            )
                                        ),
                                        "ending_cash": _decimal_text(
                                            entry["ending_cash"]
                                        ),
                                        "minimum_buffer": (
                                            _decimal_text(
                                                entry[
                                                    "minimum_buffer"
                                                ]
                                            )
                                        ),
                                    }
                                    for entry in path[
                                        "period_ledger"
                                    ]
                                ],
                            }
                            for path in projection["runway_paths"]
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
        self._validate_method_bridge(
            graph,
            plan.present_value_bridge,
            base_request,
        )
        periods = self._periods(graph)
        if (
            tuple(item.period for item in spec.runway_periods) != periods
            or any(
                tuple(item.period for item in asset.periods) != periods
                for asset in spec.assets
            )
            or any(event.period not in periods for event in spec.events)
        ):
            raise _MethodBlocked(
                "BIOPHARMA_PERIOD_COVERAGE_INVALID: events, assets, and runway must bind the routed finite forecast periods."
            )
        as_of = self._as_of(graph)
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
                *(
                    period
                    for asset in spec.assets
                    for period in asset.periods
                ),
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
            raise _MethodBlocked(
                "BIOPHARMA_AS_OF_INVALID: every pipeline, probability, licensing, runway, and financing input must bind the frozen valuation as-of."
            )
        if (
            spec.opening_cash.period
            != plan.present_value_bridge.balance_sheet_period
            or spec.minimum_cash_buffer.period
            != plan.present_value_bridge.balance_sheet_period
        ):
            raise _MethodBlocked(
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
            if isinstance(quantity, FinancialQuantity)
            and quantity.kind == "money"
        )
        if any(
            quantity.currency != reporting_currency
            or quantity.unit != reporting_currency
            for quantity in money_quantities
        ):
            raise _MethodBlocked(
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
            raise _MethodBlocked(
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
            if any(
                quantity.period != as_of
                for quantity in valuation_date_quantities
            ):
                raise _MethodBlocked(
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
            raise _MethodBlocked(
                "BIOPHARMA_DISCOUNT_RATE_PERIOD_INVALID: discount rates must bind the valuation as-of."
            )
        facts = {
            fact.fact_id: fact
            for fact in base_request.data_snapshot.facts
        }
        opening_facts = tuple(
            facts.get(ref.removeprefix("Fact:"))
            for ref in spec.opening_cash.provenance_refs
        )
        if (
            any(fact is None for fact in opening_facts)
            or not any(
                fact.subject_id == graph.security_id
                and fact.scope == "company"
                and fact.metric_id == "cash"
                and fact.value == spec.opening_cash.normalized_value
                and fact.unit == spec.opening_cash.unit
                and fact.currency == spec.opening_cash.currency
                and fact.period == spec.opening_cash.period
                and fact.official
                and date.fromisoformat(fact.available_at)
                <= date.fromisoformat(as_of)
                for fact in opening_facts
                if fact is not None
            )
        ):
            raise _MethodBlocked(
                "BIOPHARMA_OPENING_CASH_EVIDENCE_INVALID: opening cash must resolve exactly through an official frozen fact."
            )
        for event in spec.events:
            resolved = tuple(
                facts.get(ref.removeprefix("Fact:"))
                for ref in event.base_fact_refs
            )
            if (
                any(fact is None for fact in resolved)
                or not any(
                    fact.subject_id == graph.security_id
                    and fact.scope == "company"
                    and fact.metric_id == "biopharma_event_probability"
                    and fact.field_name == event.event_id
                    and fact.value
                    == event.probability_base.normalized_value
                    and fact.unit == "decimal"
                    and fact.currency == "N/A"
                    and fact.period == event.period
                    and fact.source_id
                    == event.calibration_record_id
                    and date.fromisoformat(
                        event.calibration_window_end
                    )
                    <= date.fromisoformat(as_of)
                    and date.fromisoformat(fact.available_at)
                    >= date.fromisoformat(
                        event.calibration_window_end
                    )
                    and date.fromisoformat(fact.available_at)
                    <= date.fromisoformat(as_of)
                    for fact in resolved
                    if fact is not None
                )
            ):
                raise _MethodBlocked(
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
                if (
                    any(fact is None for fact in resolved)
                    or not any(
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
                    )
                ):
                    raise _MethodBlocked(
                        "BIOPHARMA_FINANCING_EVIDENCE_INVALID: financing proceeds, issue price, and new shares must resolve exactly to frozen committed terms."
                    )
        events = {item.event_id: item for item in spec.events}
        for asset in spec.assets:
            closure = self._biopharma_event_closure(
                events,
                asset.required_event_ids,
            )
            if any(
                period.milestone_event_id
                and period.milestone_event_id not in closure
                for period in asset.periods
            ):
                raise _MethodBlocked(
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

    def _biopharma_projection(
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
        periods = self._periods(graph)
        valuation_date = date.fromisoformat(self._as_of(graph))

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
        asset_cash_flow_trace: list[dict[str, Any]] = []
        full_probabilities: dict[str, Decimal] = {}
        for asset in spec.assets:
            closure = self._biopharma_event_closure(
                events,
                asset.required_event_ids,
            )
            full_probability = probability(closure)
            full_probabilities[
                f"{asset.asset_id}:{asset.indication_id}"
            ] = full_probability
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
                expected_development_cost = (
                    development_cost * survival_probability
                )
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
                expected_milestone = (
                    milestone_cash * milestone_probability
                )
                components.extend(
                    (
                        (expected_sales, timing),
                        (-expected_development_cost, timing),
                        (expected_milestone, timing),
                    )
                )
                shifted_period = (
                    f"{int(period[:4]) + delay_years}E"
                )
                asset_cash_flow_trace.extend(
                    (
                        {
                            "asset_key": (
                                f"{asset.asset_id}:{asset.indication_id}"
                            ),
                            "cash_flow_type": "commercial_cash",
                            "source_period": period,
                            "shifted_period": shifted_period,
                            "timing_act365": _decimal_text(timing),
                            "amount": _decimal_text(expected_sales),
                        },
                        {
                            "asset_key": (
                                f"{asset.asset_id}:{asset.indication_id}"
                            ),
                            "cash_flow_type": "development_cost",
                            "source_period": period,
                            "shifted_period": shifted_period,
                            "timing_act365": _decimal_text(timing),
                            "amount": _decimal_text(
                                -expected_development_cost
                            ),
                        },
                        {
                            "asset_key": (
                                f"{asset.asset_id}:{asset.indication_id}"
                            ),
                            "cash_flow_type": "milestone_cash",
                            "source_period": period,
                            "shifted_period": shifted_period,
                            "timing_act365": _decimal_text(timing),
                            "amount": _decimal_text(expected_milestone),
                        },
                    )
                )
            for carry_year in range(1, delay_years + 1):
                carry_anchor = max(
                    (
                        events[event_id].period
                        for event_id in closure
                    ),
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
                    {
                        "asset_key": (
                            f"{asset.asset_id}:{asset.indication_id}"
                        ),
                        "cash_flow_type": "delay_carry_cost",
                        "source_period": carry_anchor,
                        "shifted_period": (
                            f"{int(carry_anchor[:4]) + carry_year}E"
                        ),
                        "timing_act365": _decimal_text(carry_timing),
                        "amount": _decimal_text(
                            -(carry_cost * full_probability)
                        ),
                    }
                )
            asset_components[
                f"{asset.asset_id}:{asset.indication_id}"
            ] = tuple(components)

        rate_cases = (
            spec.discount_rate_high.normalized_value,
            spec.discount_rate_base.normalized_value,
            spec.discount_rate_low.normalized_value,
        )
        corporate_components: list[tuple[Decimal, Decimal]] = []
        corporate_cash_flow_trace: list[dict[str, Any]] = []
        current_shares = (
            plan.present_value_bridge.diluted_shares.normalized_value
        )
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
                final_shares += (
                    runway.financing.new_shares.normalized_value
                )
            timing = discount_time(runway.period)
            corporate_components.extend(((-burn, timing), (financing, timing)))
            corporate_cash_flow_trace.extend(
                (
                    {
                        "cash_flow_type": "corporate_cash_burn",
                        "period": runway.period,
                        "timing_act365": _decimal_text(timing),
                        "amount": _decimal_text(-burn),
                    },
                    {
                        "cash_flow_type": "committed_financing",
                        "period": runway.period,
                        "timing_act365": _decimal_text(timing),
                        "amount": _decimal_text(financing),
                        "record_id": (
                            runway.financing.record_id
                            if runway.financing is not None
                            else ""
                        ),
                        "issue_price": (
                            _decimal_text(
                                runway.financing.issue_price.normalized_value
                            )
                            if runway.financing is not None
                            else "0"
                        ),
                        "new_shares": (
                            _decimal_text(
                                runway.financing.new_shares.normalized_value
                            )
                            if runway.financing is not None
                            else "0"
                        ),
                    },
                )
            )

        if len(spec.events) > 12:
            raise _MethodBlocked(
                "BIOPHARMA_RUNWAY_PATH_LIMIT: more than 12 dependent events requires an explicit path-aggregation model."
            )
        ordered_events: list[BiopharmaEventSpec] = []
        remaining = list(spec.events)
        while remaining:
            ready = [
                event
                for event in remaining
                if all(
                    parent_id in {
                        item.event_id for item in ordered_events
                    }
                    for parent_id in event.parent_event_ids
                )
            ]
            if not ready:
                raise _MethodBlocked(
                    "BIOPHARMA_EVENT_DEPENDENCY_INVALID: event paths could not be ordered."
                )
            ready.sort(key=lambda item: (item.period, item.event_id))
            ordered_events.extend(ready)
            remaining = [
                item for item in remaining if item not in ready
            ]

        path_states: list[dict[str, bool]] = [dict()]
        for event in ordered_events:
            next_states: list[dict[str, bool]] = []
            conditional_probability = event_probabilities[event.event_id]
            for state in path_states:
                if any(
                    not state[parent_id]
                    for parent_id in event.parent_event_ids
                ):
                    next_states.append({**state, event.event_id: False})
                    continue
                if conditional_probability < 1:
                    next_states.append({**state, event.event_id: False})
                if conditional_probability > 0:
                    next_states.append({**state, event.event_id: True})
            path_states = next_states

        path_results: list[dict[str, Any]] = []
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
                        (
                            item
                            for item in periods
                            if int(item[:4]) == shifted_year
                        ),
                        "",
                    )
                    if not shifted_period:
                        if development_cost > 0 or milestone_cash < 0:
                            raise _MethodBlocked(
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
                if delay_years and all(
                    state[event_id] for event_id in closure
                ):
                    carry_anchor_year = max(
                        int(events[event_id].period[:4])
                        for event_id in closure
                    )
                    for carry_year in range(1, delay_years + 1):
                        shifted_year = carry_anchor_year + carry_year
                        shifted_period = next(
                            (
                                item
                                for item in periods
                                if int(item[:4]) == shifted_year
                            ),
                            "",
                        )
                        if not shifted_period and carry_cost > 0:
                            raise _MethodBlocked(
                                "BIOPHARMA_RUNWAY_COVERAGE_INSUFFICIENT: "
                                f"{asset.asset_id}:{asset.indication_id} has delay carry cost in {shifted_year}E beyond the declared runway."
                            )
                        if shifted_period:
                            path_cash_flows[shifted_period] -= carry_cost
            cash = spec.opening_cash.normalized_value
            minimum_cash = cash
            breach_period = ""
            period_ledger: list[dict[str, Any]] = []
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
                    {
                        "period": runway.period,
                        "opening_cash": opening_cash,
                        "asset_cash_flow": path_cash_flows[
                            runway.period
                        ],
                        "corporate_cash_burn": burn,
                        "committed_financing": financing,
                        "ending_cash": cash,
                        "minimum_buffer": (
                            spec.minimum_cash_buffer.normalized_value
                        ),
                        "above_buffer": (
                            cash
                            >= spec.minimum_cash_buffer.normalized_value
                        ),
                    }
                )
                if (
                    not breach_period
                    and cash < spec.minimum_cash_buffer.normalized_value
                ):
                    breach_period = runway.period
            path_results.append(
                {
                    "path_id": path_index,
                    "events": dict(sorted(state.items())),
                    "ending_cash": cash,
                    "minimum_cash": minimum_cash,
                    "breach_period": breach_period,
                    "period_ledger": tuple(period_ledger),
                }
            )
        breached = next(
            (
                item
                for item in path_results
                if item["breach_period"]
            ),
            None,
        )
        if breached is not None:
            raise _MethodBlocked(
                "BIOPHARMA_RUNWAY_PATH_BREACH: "
                f"path={breached['path_id']} falls below the minimum buffer in {breached['breach_period']}."
            )
        minimum_path = min(
            path_results,
            key=lambda item: item["minimum_cash"],
        )
        ending_path = min(
            path_results,
            key=lambda item: item["ending_cash"],
        )
        cumulative_dilution = final_shares / current_shares
        asset_values_by_rate: list[dict[str, Decimal]] = []
        total_values: list[Decimal] = []
        for rate in rate_cases:
            by_asset = {
                asset_key: sum(
                    (
                        cash_flow
                        / ((Decimal("1") + rate) ** timing)
                        for cash_flow, timing in components
                    ),
                    Decimal("0"),
                )
                for asset_key, components in asset_components.items()
            }
            corporate_value = sum(
                (
                    cash_flow
                    / ((Decimal("1") + rate) ** timing)
                    for cash_flow, timing in corporate_components
                ),
                Decimal("0"),
            )
            asset_values_by_rate.append(by_asset)
            total_values.append(
                sum(by_asset.values(), Decimal("0"))
                + corporate_value
            )
        values = (
            min(total_values),
            total_values[1],
            max(total_values),
        )
        return {
            "scenario_case": scenario_case,
            "values": values,
            "asset_values_by_rate": tuple(asset_values_by_rate),
            "event_probabilities": event_probabilities,
            "full_probabilities": full_probabilities,
            "ending_cash": ending_path["ending_cash"],
            "minimum_cash": minimum_path["minimum_cash"],
            "dilution": cumulative_dilution,
            "runway_paths": tuple(path_results),
            "asset_cash_flow_trace": tuple(asset_cash_flow_trace),
            "corporate_cash_flow_trace": tuple(
                corporate_cash_flow_trace
            ),
            "discount_rate_cases": rate_cases,
        }

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
        projection = self._biopharma_projection(
            graph,
            plan,
            base_request,
            spec,
            scenario_role,
        )
        lineage = _merge_refs(
            spec.lineage_refs,
            graph.quantity(
                f"biopharma.horizon.{self._periods(graph)[0]}"
            ).lineage_refs,
            (
                "Assumption:biopharma_scenario_case:"
                f"{projection['scenario_case']}",
                f"Assumption:formula:{formula_version}",
            ),
        )
        dilution = projection["dilution"]
        value_range = self._bridge_range(
            graph,
            plan.present_value_bridge,
            "enterprise_value",
            projection["values"],
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
            raise _MethodBlocked(
                "BIOPHARMA_COMMON_EQUITY_INVALID: enterprise pipeline value less debt, preferred claims, and other bridge adjustments does not support positive common equity."
            )
        reporting_currency = base_request.security.reporting_currency
        ending_cash = ForecastQuantity(
            value=projection["ending_cash"],
            unit=reporting_currency,
            scale=Decimal("1"),
            currency=reporting_currency,
            period=self._periods(graph)[-1],
            as_of=self._as_of(graph),
            lineage_refs=lineage,
        )
        minimum_cash = ForecastQuantity(
            value=projection["minimum_cash"],
            unit=reporting_currency,
            scale=Decimal("1"),
            currency=reporting_currency,
            period=self._periods(graph)[-1],
            as_of=self._as_of(graph),
            lineage_refs=lineage,
        )
        dilution_quantity = self._model_quantity(
            dilution,
            unit="x",
            period=self._periods(graph)[-1],
            as_of=self._as_of(graph),
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
        base_asset_values = projection["asset_values_by_rate"][1]
        diagnostics = (
            method_diagnostic,
            (
                "Scenario event probabilities: "
                + ", ".join(
                    f"{event_id}={_decimal_text(value)}"
                    for event_id, value in sorted(
                        projection["event_probabilities"].items()
                    )
                )
            ),
            (
                "Base-rate unique-right SOTP contributions: "
                + ", ".join(
                    f"{asset_key}={_decimal_text(value)}"
                    for asset_key, value in sorted(
                        base_asset_values.items()
                    )
                )
            ),
            (
                "Asset cumulative success probabilities: "
                + ", ".join(
                    f"{asset_key}={_decimal_text(value)}"
                    for asset_key, value in sorted(
                        projection["full_probabilities"].items()
                    )
                )
            ),
            (
                "Cash runway remains above the declared buffer after committed "
                f"financing; minimum={_decimal_text(projection['minimum_cash'])}, "
                f"ending={_decimal_text(projection['ending_cash'])}, cumulative "
                f"dilution={_decimal_text(dilution)}."
            ),
            "Financing proceeds enter post-financing equity value and cash runway together with their declared share dilution; no issuance economics are invented.",
            "Low/high conditional bounds are the minimum and maximum audited discount-rate cases around the declared base case because early development outflows can make rNPV non-monotonic in the discount rate.",
            "Only declared asset/indication economic rights are valued; platform know-how or technical reserves receive no automatic mature-revenue or full-probability value.",
            "Shared parent events are evaluated once per asset dependency closure, preserving correlated failure exposure without duplicate probability multiplication.",
        )
        return value_range, assumptions, sensitivity, lineage, diagnostics

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
        share_multipliers: tuple[Decimal, Decimal, Decimal] = (
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
        ),
        share_multiplier_ref_prefix: str = "cumulative_dilution",
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
                share_multiplier,
                share_multiplier_ref_prefix,
            )
            for value, share_multiplier in zip(
                values,
                share_multipliers,
                strict=True,
            )
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
        share_multiplier: Decimal = Decimal("1"),
        share_multiplier_ref_prefix: str = "cumulative_dilution",
    ) -> ValuationPoint:
        if share_multiplier <= 0:
            raise _MethodBlocked(
                "FINANCIAL_DILUTION_INVALID: cumulative share multiplier must remain positive."
            )
        if value_basis == "enterprise_value":
            cash, debt = self._bridge_cash_debt(graph, spec)
            currency = cash.currency
            as_of = cash.as_of
        else:
            cash = None
            debt = None
            currency = (
                spec.output_currency
                or spec.lease_debt.currency
            )
            as_of = spec.diluted_shares.as_of
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
        diluted_shares = self._normalized_financial(spec.diluted_shares)
        if share_multiplier != Decimal("1"):
            diluted_shares = FinancialQuantity(
                value=diluted_shares.normalized_value * share_multiplier,
                unit=diluted_shares.unit,
                scale=Decimal("1"),
                currency=diluted_shares.currency,
                period=diluted_shares.period,
                as_of=diluted_shares.as_of,
                provenance_refs=_merge_refs(
                    diluted_shares.provenance_refs,
                    (
                        f"Assumption:{share_multiplier_ref_prefix}:"
                        f"{_decimal_text(share_multiplier)}",
                    ),
                ),
                kind=diluted_shares.kind,
            )
        result = EquityBridge(
            basis_value=basis,
            value_basis=value_basis,
            balance_sheet_period=spec.balance_sheet_period,
            valuation_as_of=as_of,
            output_currency=spec.output_currency or currency,
            diluted_shares=diluted_shares,
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
        if not periods and graph.template_id == "financial_institution_valuation_shell@1":
            periods = tuple(
                node.quantity.period
                for node in graph.nodes
                if node.node_id.startswith("financial.horizon.")
            )
        if not periods and graph.template_id == "biopharma_pipeline_valuation_shell@1":
            periods = tuple(
                node.quantity.period
                for node in graph.nodes
                if node.node_id.startswith("biopharma.horizon.")
            )
        if not periods:
            raise ForecastInvariantError(
                "FORECAST_VALUATION_INPUT_MISSING",
                "Forecast graph has no gated FCFF valuation inputs.",
            )
        return periods

    def _as_of(self, graph: ForecastGraph) -> str:
        first_period = self._periods(graph)[0]
        node_id = (
            f"financial.horizon.{first_period}"
            if graph.template_id
            == "financial_institution_valuation_shell@1"
            else (
                f"biopharma.horizon.{first_period}"
                if graph.template_id
                == "biopharma_pipeline_valuation_shell@1"
                else f"valuation.fcff.{first_period}"
            )
        )
        return graph.quantity(node_id).as_of

    def _forecast_lineage(self, graph: ForecastGraph) -> tuple[str, ...]:
        return _merge_refs(
            *(
                node.lineage_refs
                for node in graph.nodes
                if node.node_id.startswith(
                    (
                        "valuation.fcff.",
                        "financial.horizon.",
                        "biopharma.horizon.",
                    )
                )
            )
        )
