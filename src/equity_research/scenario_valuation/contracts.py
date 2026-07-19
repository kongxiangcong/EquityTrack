from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Literal

from ..financial import (
    FinancialInvariantError,
    FinancialQuantity,
    ValueBasis,
    valuation_decimal_context,
)
from ..forecast import (
    ForecastGraph,
    ForecastInvariantError,
    ForecastQuantity,
    ForecastRequest,
    SegmentForecastOverride,
)

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


def decimal_text(value: Decimal) -> str:
    with valuation_decimal_context():
        if value == 0:
            return "0"
        return format(value.normalize(), "f")


def require_decimal(value: Any, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ScenarioInvariantError(
            "SCENARIO_DECIMAL_REQUIRED",
            f"{field_name} must be a finite Decimal.",
        )
    return value


def require_refs(
    refs: tuple[str, ...],
    field_name: str,
    *,
    facts_only: bool = False,
) -> None:
    prefixes = ("Fact:",) if facts_only else ("Fact:", "Assumption:")
    if (
        not isinstance(refs, tuple)
        or not refs
        or any(not isinstance(ref, str) or not ref.startswith(prefixes) for ref in refs)
    ):
        raise ScenarioInvariantError(
            "SCENARIO_LINEAGE_INVALID",
            f"{field_name} requires resolved {'Fact' if facts_only else 'Fact or Assumption'} references.",
        )


def merge_refs(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ref for group in groups for ref in group))


def same_dimension(*quantities: ForecastQuantity) -> bool:
    return (
        len(
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
        == 1
    )


def validate_model_quantity(
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


def validate_range(
    low: ForecastQuantity,
    base: ForecastQuantity,
    high: ForecastQuantity,
    field_name: str,
    *,
    unit: str,
    positive: bool = False,
) -> None:
    for suffix, quantity in (("low", low), ("base", base), ("high", high)):
        validate_model_quantity(
            quantity,
            unit=unit,
            field_name=f"{field_name}_{suffix}",
        )
    if not same_dimension(low, base, high):
        raise ScenarioInvariantError(
            "VALUATION_RANGE_DIMENSION_MISMATCH",
            f"{field_name} range quantities must share one dimension and time basis.",
        )
    values = tuple(item.normalized_value for item in (low, base, high))
    if values[0] > values[1] or values[1] > values[2] or (positive and values[0] <= 0):
        raise ScenarioInvariantError(
            "VALUATION_RANGE_INVALID",
            f"{field_name} must be ordered low <= base <= high"
            + (" and positive." if positive else "."),
        )


def validate_money_range(
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


def percentile(values: tuple[Decimal, ...], probability: Decimal) -> Decimal:
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
        raise TypeError("Use IndustrialValuation.bind_dcf_applicability().")

    @classmethod
    def from_validated_gate(
        cls,
        *,
        status: Literal["allowed", "caution", "blocked"],
        reason: str,
        subject_id: str,
        as_of: str,
        evidence_refs: tuple[str, ...],
        diagnostics: tuple[str, ...],
        gated_wacc: ForecastQuantity | None,
        gated_terminal_growth: ForecastQuantity | None,
    ) -> DcfApplicability:
        if (
            not reason.strip()
            or not subject_id.strip()
            or (status in {"allowed", "caution"})
            and (gated_wacc is None or gated_terminal_growth is None)
        ):
            raise ScenarioInvariantError(
                "DCF_GATE_INVALID",
                "Validated DCF gate fields are incomplete.",
            )
        instance = object.__new__(cls)
        for field_name, value in {
            "status": status,
            "reason": reason,
            "subject_id": subject_id,
            "as_of": as_of,
            "evidence_refs": evidence_refs,
            "diagnostics": diagnostics,
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
        validate_model_quantity(
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
        require_refs(
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
            "prior_count": decimal_text(self.prior_count),
            "prior_total_count": decimal_text(self.prior_total_count),
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
        require_refs(self.rationale_refs, "ScenarioDefinition.rationale_refs")

    @property
    def probability(self) -> Decimal | None:
        if self.probability_evidence is None:
            return None
        return self.probability_evidence.probability.normalized_value


@dataclass(frozen=True)
class EquityBridgeSpec:
    timing: EquityBridgeTiming
    diluted_shares: FinancialQuantity | None
    lease_debt: FinancialQuantity
    preferred_stock: FinancialQuantity
    minority_interest: FinancialQuantity
    pension_deficit: FinancialQuantity | None
    associates_jv_value: FinancialQuantity
    non_operating_assets: FinancialQuantity
    output_currency: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.timing, EquityBridgeTiming):
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_TIMING_INVALID",
                "Equity bridge timing must be opening or terminal.",
            )
        required_money_inputs = (
            self.lease_debt,
            self.preferred_stock,
            self.minority_interest,
            self.associates_jv_value,
            self.non_operating_assets,
        )
        if any(
            not isinstance(item, FinancialQuantity) for item in required_money_inputs
        ) or (
            self.pension_deficit is not None
            and not isinstance(self.pension_deficit, FinancialQuantity)
        ):
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_INPUT_INVALID",
                "Every equity-bridge adjustment must be a FinancialQuantity.",
            )
        if self.diluted_shares is not None and not isinstance(
            self.diluted_shares, FinancialQuantity
        ):
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_INPUT_INVALID",
                "diluted_shares must be a FinancialQuantity when supplied.",
            )
        if self.diluted_shares is not None and self.diluted_shares.kind != "shares":
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_INPUT_INVALID",
                "diluted_shares must carry a shares dimension.",
            )
        money_inputs = required_money_inputs + (
            (self.pension_deficit,) if self.pension_deficit is not None else ()
        )
        if any(item.kind != "money" for item in money_inputs):
            raise ScenarioInvariantError(
                "VALUATION_BRIDGE_INPUT_INVALID",
                "Equity-bridge adjustments must carry a money dimension.",
            )
        quantities = money_inputs + (
            (self.diluted_shares,) if self.diluted_shares is not None else ()
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
        return self.lease_debt.period

    @property
    def provenance_refs(self) -> tuple[str, ...]:
        return merge_refs(
            *(
                (self.diluted_shares.provenance_refs,)
                if self.diluted_shares is not None
                else ()
            ),
            self.lease_debt.provenance_refs,
            self.preferred_stock.provenance_refs,
            self.minority_interest.provenance_refs,
            *(
                (self.pension_deficit.provenance_refs,)
                if self.pension_deficit is not None
                else ()
            ),
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
        validate_range(
            self.discount_rate_low,
            self.discount_rate_base,
            self.discount_rate_high,
            "discount_rate",
            unit="decimal",
            positive=True,
        )
        validate_range(
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
                or not same_dimension(
                    self.discount_rate_base,
                    self.applicability.gated_wacc,
                )
                or not same_dimension(
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
        if (
            not isinstance(self.minimum_explicit_periods, int)
            or self.minimum_explicit_periods < 1
        ):
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
        validate_range(
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
        if (
            not isinstance(self.components, tuple)
            or not self.components
            or any(not isinstance(item, SotpComponentSpec) for item in self.components)
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
        validate_model_quantity(
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
            or self.price_base.unit != f"{self.price_base.currency}/unit"
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
            require_refs(
                quantity.lineage_refs,
                f"CommodityCurvePoint.{field_name}",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return merge_refs(
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
            or self.unit_cost_base.unit != f"{self.unit_cost_base.currency}/unit"
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
            any(not isinstance(item, FinancialQuantity) for item in operating_expenses)
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
        validate_model_quantity(
            self.tax_rate,
            unit="decimal",
            field_name="ResourcePeriodSpec.tax_rate",
        )
        if self.tax_rate.period != self.period or not Decimal(
            "0"
        ) <= self.tax_rate.normalized_value <= Decimal("1"):
            raise ScenarioInvariantError(
                "RESOURCE_TAX_RATE_INVALID",
                "Resource tax rates must bind the schedule period and remain within [0, 1].",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return merge_refs(
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
        require_refs(
            self.reserve_quantity.lineage_refs,
            "ResourceAssetSpec.reserve_quantity",
            facts_only=True,
        )
        if (
            not isinstance(self.schedule, tuple)
            or not self.schedule
            or any(not isinstance(item, ResourcePeriodSpec) for item in self.schedule)
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
        validate_range(
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
        if self.resource_life_years != len(self.schedule):
            raise ScenarioInvariantError(
                "RESOURCE_LIFE_INVALID",
                "Resource life must be a positive whole number of years.",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return merge_refs(
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
            denominator_available_at = date.fromisoformat(self.denominator_available_at)
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
            or self.market_value.currency != self.pit_earnings_denominator.currency
            or self.market_value.period != self.period
            or self.pit_earnings_denominator.period != self.period
            or self.market_value.as_of != self.pit_earnings_denominator.as_of
            or denominator_available_at > observation_date
            or observation_date > date.fromisoformat(self.market_value.as_of)
        ):
            raise ScenarioInvariantError(
                "CYCLICAL_HISTORY_DENOMINATOR_INVALID",
                "Historical bands require positive PIT market value and earnings on one currency/time basis.",
            )
        require_refs(
            self.market_value.provenance_refs,
            "HistoricalCycleObservation.market_value",
            facts_only=True,
        )
        require_refs(
            self.pit_earnings_denominator.provenance_refs,
            "HistoricalCycleObservation.pit_earnings_denominator",
            facts_only=True,
        )
        validate_model_quantity(
            self.reported_multiple,
            unit="x",
            field_name="HistoricalCycleObservation.reported_multiple",
        )
        expected_refs = merge_refs(
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
        return merge_refs(
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
        if not isinstance(self.assets, tuple) or any(
            not isinstance(item, ResourceAssetSpec) for item in self.assets
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
        validate_range(
            self.mid_cycle_multiple_low,
            self.mid_cycle_multiple_base,
            self.mid_cycle_multiple_high,
            "mid_cycle_multiple",
            unit="x",
            positive=True,
        )
        validate_range(
            self.nav_discount_rate_low,
            self.nav_discount_rate_base,
            self.nav_discount_rate_high,
            "nav_discount_rate",
            unit="decimal",
            positive=True,
        )
        validate_model_quantity(
            self.peak_earnings_threshold,
            unit="x",
            field_name="peak_earnings_threshold",
        )
        if self.peak_earnings_threshold.normalized_value <= Decimal("1"):
            raise ScenarioInvariantError(
                "CYCLICAL_PEAK_THRESHOLD_INVALID",
                "Peak-earnings recognition requires a threshold greater than one times the PIT median denominator.",
            )
        if not isinstance(self.historical_observations, tuple) or any(
            not isinstance(item, HistoricalCycleObservation)
            for item in self.historical_observations
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
        return merge_refs(
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
        validate_range(
            self.low,
            self.base,
            self.high,
            self.metric_id,
            unit="decimal",
        )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return merge_refs(
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
            validate_range(
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
        validate_range(
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
        validate_range(
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
                or quantities[0].normalized_value > quantities[1].normalized_value
                or quantities[1].normalized_value > quantities[2].normalized_value
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
        return merge_refs(
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
            require_refs(
                item.provenance_refs,
                "FinancialInstitutionValuationSpec.opening_balance",
                facts_only=True,
            )
        validate_model_quantity(
            self.minimum_regulatory_capital_ratio,
            unit="decimal",
            field_name="minimum_regulatory_capital_ratio",
        )
        if (
            not Decimal("0")
            < self.minimum_regulatory_capital_ratio.normalized_value
            < 1
        ):
            raise ScenarioInvariantError(
                "FINANCIAL_REGULATORY_MINIMUM_INVALID",
                "Minimum regulatory capital ratio must be within (0,1).",
            )
        validate_model_quantity(
            self.specialized_risk_limit,
            unit="decimal",
            field_name="specialized_risk_limit",
        )
        if self.specialized_risk_limit.normalized_value <= 0:
            raise ScenarioInvariantError(
                "FINANCIAL_SPECIALIZED_RISK_LIMIT_INVALID",
                "The institution-specific risk limit must be positive.",
            )
        validate_range(
            self.cost_of_equity_low,
            self.cost_of_equity_base,
            self.cost_of_equity_high,
            "cost_of_equity",
            unit="decimal",
            positive=True,
        )
        validate_range(
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
        if any(current != previous + 1 for previous, current in zip(years, years[1:])):
            raise ScenarioInvariantError(
                "FINANCIAL_PERIODS_INVALID",
                "Financial forecast periods must be strictly increasing and contiguous.",
            )
        for item in self.periods:
            metrics = {metric.metric_id: metric for metric in item.operating_metrics}
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
                or any(value < 0 or value > 1 for value in values["fee_income_yield"])
            ):
                raise ScenarioInvariantError(
                    "FINANCIAL_SPECIALIZED_METRIC_DOMAIN_INVALID",
                    "Broker net-capital ratios must be positive and fee-income yields within [0,1].",
                )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return merge_refs(
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
            or self.event_type not in {"clinical", "regulatory", "commercial"}
            or self.probability_basis not in {"standalone", "conditional_on_parents"}
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
            window_start = date.fromisoformat(self.calibration_window_start)
            window_end = date.fromisoformat(self.calibration_window_end)
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
        if bool(self.parent_event_ids) != (
            self.probability_basis == "conditional_on_parents"
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_EVENT_PROBABILITY_BASIS_INVALID",
                "Root probabilities must be standalone and dependent-event probabilities explicitly conditional on parents.",
            )
        validate_range(
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
            ref for ref in self.probability_base.lineage_refs if ref.startswith("Fact:")
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
            ref for ref in self.probability_base.lineage_refs if ref.startswith("Fact:")
        )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return merge_refs(
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
        validate_money_range(
            self.gross_sales_low,
            self.gross_sales_base,
            self.gross_sales_high,
            "biopharma_gross_sales",
            nonnegative=True,
        )
        validate_money_range(
            self.development_cost_low,
            self.development_cost_base,
            self.development_cost_high,
            "biopharma_development_cost",
            nonnegative=True,
        )
        validate_money_range(
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
        validate_range(
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
        return merge_refs(
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
            not re.fullmatch(r"[A-Za-z0-9_.:-]+", value or "") for value in stable
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
            or len(self.required_event_ids) != len(set(self.required_event_ids))
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_ASSET_EVENTS_INVALID",
                "Every asset/indication requires a unique non-empty event path.",
            )
        validate_range(
            self.ownership_low,
            self.ownership_base,
            self.ownership_high,
            "biopharma_ownership",
            unit="decimal",
        )
        validate_range(
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
        validate_range(
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
        if delays[0] < 0 or any(value != value.to_integral_value() for value in delays):
            raise ScenarioInvariantError(
                "BIOPHARMA_DELAY_INVALID",
                "Launch delay must be a nonnegative whole number of years.",
            )
        validate_money_range(
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
            current != previous + 1 for previous, current in zip(years, years[1:])
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_ASSET_PERIODS_INVALID",
                "Asset cash-flow periods must be unique, increasing, and contiguous.",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return merge_refs(
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
        if not re.fullmatch(
            r"[A-Za-z0-9_.:-]+", self.record_id or ""
        ) or not re.fullmatch(r"\d{4}(?:E|FY)", self.period or ""):
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
            or self.issue_price.unit != f"{self.proceeds.currency}/share"
            or self.new_shares.unit != "shares"
            or self.new_shares.currency != "N/A"
            or self.proceeds.normalized_value
            != self.issue_price.normalized_value * self.new_shares.normalized_value
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
            require_refs(
                quantity.provenance_refs,
                f"BiopharmaFinancingSpec.{field_name}",
                facts_only=True,
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return merge_refs(
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
        validate_money_range(
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
        return merge_refs(
            self.corporate_cash_burn_low.provenance_refs,
            self.corporate_cash_burn_base.provenance_refs,
            self.corporate_cash_burn_high.provenance_refs,
            (self.financing.lineage_refs if self.financing is not None else ()),
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
            or any(not isinstance(item, BiopharmaEventSpec) for item in self.events)
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
            or int(events[parent_id].period[:4]) > int(item.period[:4])
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
            or any(not isinstance(item, BiopharmaAssetSpec) for item in self.assets)
        ):
            raise ScenarioInvariantError(
                "BIOPHARMA_ASSETS_INVALID",
                "Biopharma valuation requires typed asset/indication schedules.",
            )
        asset_keys = tuple((item.asset_id, item.indication_id) for item in self.assets)
        rights = tuple(item.economic_right_id for item in self.assets)
        if len(asset_keys) != len(set(asset_keys)) or len(rights) != len(set(rights)):
            raise ScenarioInvariantError(
                "BIOPHARMA_ECONOMIC_RIGHT_DUPLICATE",
                "Each asset/indication and economic right may be valued exactly once.",
            )
        if any(
            event_id not in events
            for asset in self.assets
            for event_id in asset.required_event_ids
        ) or any(
            period.milestone_event_id and period.milestone_event_id not in events
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
            left_id not in ancestors(right_id) and right_id not in ancestors(left_id)
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
                and events[period.milestone_event_id].period != period.period
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
        require_refs(
            self.opening_cash.provenance_refs,
            "BiopharmaValuationSpec.opening_cash",
            facts_only=True,
        )
        validate_range(
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
        runway_years = tuple(int(item.period[:4]) for item in self.runway_periods)
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
        if len(financing_record_ids) != len(set(financing_record_ids)):
            raise ScenarioInvariantError(
                "BIOPHARMA_FINANCING_RECORD_DUPLICATE",
                "Each committed financing tranche record may enter the runway and dilution bridge exactly once.",
            )

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return merge_refs(
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
                    "calibration_method_version": (event.calibration_method_version),
                    "calibration_window_start": (event.calibration_window_start),
                    "calibration_window_end": (event.calibration_window_end),
                    "calibration_sample_size": (event.calibration_sample_size),
                    "calibration_record_id": (event.calibration_record_id),
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
                    "required_event_ids": list(asset.required_event_ids),
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
                            "milestone_event_id": (period.milestone_event_id),
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
        raise TypeError("Use IndustrialValuation.bind_relative_multiple().")

    @classmethod
    def from_validated_gate(
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
        if (
            not subject_id.strip()
            or not evidence_refs
            or (status == "ready" and any(item is None for item in multiples))
            or (status == "blocked" and any(item is not None for item in multiples))
        ):
            raise ScenarioInvariantError(
                "RELATIVE_GATE_INVALID",
                "Validated relative gate fields are incomplete.",
            )
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
            not isinstance(item, RelativeMultipleSpec) for item in self.relative_methods
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
        if not same_dimension(self.low, self.base, self.high):
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
    equity_value: FinancialQuantity | None
    per_share_value: FinancialQuantity | None
    bridge_trace: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "basis_value": self.basis_value.to_dict(),
            "equity_value": (
                self.equity_value.to_dict() if self.equity_value is not None else None
            ),
            "per_share_value": (
                self.per_share_value.to_dict()
                if self.per_share_value is not None
                else None
            ),
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
        if self.low.equity_value is None:
            raise ScenarioInvariantError(
                "EQUITY_BRIDGE_INCOMPLETE",
                "Equity value is unavailable because the bridge is incomplete.",
            )
        return self.low.equity_value.normalized_value

    @property
    def equity_value_base(self) -> Decimal:
        if self.base.equity_value is None:
            raise ScenarioInvariantError(
                "EQUITY_BRIDGE_INCOMPLETE",
                "Equity value is unavailable because the bridge is incomplete.",
            )
        return self.base.equity_value.normalized_value

    @property
    def equity_value_high(self) -> Decimal:
        if self.high.equity_value is None:
            raise ScenarioInvariantError(
                "EQUITY_BRIDGE_INCOMPLETE",
                "Equity value is unavailable because the bridge is incomplete.",
            )
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
            "component_trace": [json.loads(item) for item in self.component_trace],
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

    def __post_init__(self) -> None:
        method_ids = tuple(item.method_id for item in self.methods)
        if len(method_ids) != len(set(method_ids)):
            raise ScenarioInvariantError(
                "SCENARIO_METHOD_ID_DUPLICATE",
                f"Scenario {self.scenario_id} contains a duplicate method id.",
            )

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


class MethodBlocked(ValueError):
    pass


MethodCalculationResult = tuple[
    ConditionalValueRange,
    tuple[ValuationAssumption, ...],
    tuple[ValuationSensitivity, ...],
    tuple[str, ...],
    tuple[str, ...],
]
MethodCalculation = Callable[[], MethodCalculationResult]


def forecast_lineage(graph: ForecastGraph) -> tuple[str, ...]:
    return merge_refs(
        *(
            node.lineage_refs
            for node in graph.nodes
            if node.node_id.startswith(
                ("valuation.fcff.", "financial.horizon.", "biopharma.horizon.")
            )
        )
    )


def isolate_method(
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
    except (FinancialInvariantError, ForecastInvariantError, MethodBlocked) as exc:
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
            lineage_refs=merge_refs(
                blocked_lineage_refs,
                forecast_lineage(graph),
            ),
        )
