from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable

from ..evidence import period_rank
from ..financial import valuation_decimal_context


class ForecastInvariantError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class ForecastEvidence:
    """Own cross-object evidence, scope, and reporting-dimension validation."""

    _MANUFACTURING_ARCHETYPES = {
        "general_manufacturing",
        "multi_segment_manufacturing",
        "cyclical_manufacturing",
        "cyclical_resource",
    }

    @classmethod
    def validate(
        cls,
        request: Any,
    ) -> tuple[dict[str, Any], dict[tuple[str, str], Any]]:
        cls.validate_request(request)
        baselines = {
            baseline.segment_id: baseline
            for baseline in request.data_snapshot.segment_baselines
        }
        if set(baselines) != set(request.security.segment_ids):
            raise ForecastInvariantError(
                "FORECAST_SEGMENT_MISMATCH",
                "Security segments must match DataSnapshot baselines.",
            )
        overrides = {
            (override.segment_id, override.period): override
            for override in request.assumption_overrides
        }
        if any(
            segment_id not in baselines or period not in request.forecast_periods
            for segment_id, period in overrides
        ):
            raise ForecastInvariantError(
                "FORECAST_OVERRIDE_SCOPE_INVALID",
                "Typed overrides must target a requested segment and period.",
            )
        if request.security.archetype.value in cls._MANUFACTURING_ARCHETYPES:
            cls._validate_reporting_dimensions(request, baselines)
        return baselines, overrides

    @staticmethod
    def validate_request(request: Any) -> None:
        if not isinstance(request.assumption_overrides, tuple) or any(
            not isinstance(item, SegmentForecastOverride)
            for item in request.assumption_overrides
        ):
            raise ForecastInvariantError(
                "FORECAST_OVERRIDE_TYPE_INVALID",
                "assumption_overrides must be a tuple of SegmentForecastOverride.",
            )
        if (
            not isinstance(request.assumptions, tuple)
            or any(not isinstance(item, ForecastAssumption) for item in request.assumptions)
            or len({item.assumption_id for item in request.assumptions})
            != len(request.assumptions)
        ):
            raise ForecastInvariantError(
                "FORECAST_ASSUMPTION_INVALID",
                "assumptions must be a unique tuple of typed assumptions.",
            )
        if (
            not isinstance(request.narrative_statements, tuple)
            or any(
                not isinstance(item, ForecastNarrativeStatement)
                for item in request.narrative_statements
            )
            or len({item.statement_id for item in request.narrative_statements})
            != len(request.narrative_statements)
        ):
            raise ForecastInvariantError(
                "FORECAST_NARRATIVE_INVALID",
                "narrative_statements must be a unique tuple of typed statements.",
            )
        fact_refs = {f"Fact:{item.fact_id}" for item in request.data_snapshot.facts}
        assumption_refs = {
            f"Assumption:{item.assumption_id}" for item in request.assumptions
        }
        if any(
            date.fromisoformat(item.available_at) > date.fromisoformat(request.as_of)
            or any(ref not in fact_refs for ref in item.evidence_refs)
            for item in request.assumptions
        ):
            raise ForecastInvariantError(
                "FORECAST_ASSUMPTION_EVIDENCE_INVALID",
                "Assumptions must be available by as-of and resolve to frozen facts.",
            )
        if any(
            ref not in fact_refs | assumption_refs
            for item in request.narrative_statements
            for ref in item.evidence_refs
        ):
            raise ForecastInvariantError(
                "FORECAST_NARRATIVE_EVIDENCE_MISSING",
                "Narrative fact lineage must resolve inside the frozen DataSnapshot.",
            )
        if any(
            ref.startswith("Assumption:") and ref not in assumption_refs
            for fact in request.data_snapshot.facts
            for ref in fact.derivation_refs
        ):
            raise ForecastInvariantError(
                "FORECAST_DERIVED_FACT_ASSUMPTION_MISSING",
                "Derived facts must resolve assumption lineage in the Forecast request.",
            )
        if request.as_of != request.data_snapshot.as_of:
            raise ForecastInvariantError(
                "FORECAST_AS_OF_MISMATCH",
                "ForecastRequest.as_of must match DataSnapshot.as_of.",
            )
        if request.security.security_id != request.data_snapshot.security_id:
            raise ForecastInvariantError(
                "FORECAST_SNAPSHOT_SUBJECT_MISMATCH",
                "DataSnapshot must be frozen for the requested Security.",
            )
        ranks = [period_rank(period) for period in request.forecast_periods]
        if (
            not isinstance(request.forecast_periods, tuple)
            or not request.forecast_periods
            or any(rank < 0 for rank in ranks)
            or ranks != sorted(ranks)
            or len(set(request.forecast_periods)) != len(request.forecast_periods)
        ):
            raise ForecastInvariantError(
                "FORECAST_PERIODS_INVALID",
                "forecast_periods must be a unique, increasing tuple.",
            )
        latest_baseline_rank = max(
            period_rank(quantity.period)
            for quantity in (
                *(
                    quantity
                    for baseline in request.data_snapshot.segment_baselines
                    for quantity in baseline.quantities()
                ),
                *request.data_snapshot.company_opening_balance_sheet.quantities(),
            )
        )
        if any(rank <= latest_baseline_rank for rank in ranks):
            raise ForecastInvariantError(
                "FORECAST_PERIOD_NOT_FORWARD",
                "Every forecast period must follow the frozen baseline period.",
            )
        try:
            if date.fromisoformat(request.review_date) < date.fromisoformat(request.as_of):
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ForecastInvariantError(
                "FORECAST_REVIEW_DATE_INVALID",
                "review_date must be an ISO date on or after as_of.",
            ) from exc
        keys = [
            (override.segment_id, override.period)
            for override in request.assumption_overrides
        ]
        if len(keys) != len(set(keys)):
            raise ForecastInvariantError(
                "FORECAST_OVERRIDE_DUPLICATE",
                "Only one typed override is allowed per segment and period.",
            )

    @staticmethod
    def _validate_reporting_dimensions(
        request: Any,
        baselines: dict[str, Any],
    ) -> None:
        currency = request.security.reporting_currency
        for baseline in baselines.values():
            money = (
                baseline.operating_expense,
                baseline.capex,
                baseline.working_capital,
                baseline.depreciation,
            )
            per_unit = (baseline.asp, baseline.unit_cost)
            if any(
                item.currency != currency or item.unit != currency for item in money
            ) or any(
                item.currency != currency or item.unit != f"{currency}/unit"
                for item in per_unit
            ):
                raise ForecastInvariantError(
                    "FORECAST_CURRENCY_MISMATCH",
                    "Manufacturing money and per-unit facts must use the reporting currency.",
                )
        if any(
            item.currency != currency or item.unit != currency
            for item in request.data_snapshot.company_opening_balance_sheet.quantities()
        ):
            raise ForecastInvariantError(
                "FORECAST_CURRENCY_MISMATCH",
                "Company opening balances must use the reporting currency.",
            )
class CompanyArchetype(str, Enum):
    GENERAL_MANUFACTURING = "general_manufacturing"
    MULTI_SEGMENT_MANUFACTURING = "multi_segment_manufacturing"
    FINANCIAL_INSTITUTION = "financial_institution"
    BIOPHARMA = "biopharma"
    CYCLICAL_MANUFACTURING = "cyclical_manufacturing"
    CYCLICAL_RESOURCE = "cyclical_resource"


class NarrativeCategory(str, Enum):
    CORE_THESIS = "core_thesis"
    VARIANT_VIEW = "variant_view"
    BUSINESS_QUALITY = "business_quality"
    EARNINGS_OUTLOOK = "earnings_outlook"
    VALUATION_VIEW = "valuation_view"
    RISK_REWARD = "risk_reward_summary"
    KEY_UNCERTAINTY = "key_uncertainties"
    VALUATION_GUARDRAIL = "valuation_guardrails"
    VIEW_CHANGE = "what_would_change_the_view"


class NarrativeBasis(str, Enum):
    FACT = "fact"
    CALCULATION = "calculation"
    ASSUMPTION = "assumption"
    JUDGMENT = "judgment"
    RISK = "risk"


@dataclass(frozen=True)
class ForecastNarrativeStatement:
    statement_id: str
    category: NarrativeCategory
    basis: NarrativeBasis
    text: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[A-Za-z0-9_.:-]+", self.statement_id or "")
            or not isinstance(self.category, NarrativeCategory)
            or not isinstance(self.basis, NarrativeBasis)
            or not self.text.strip()
            or not self.evidence_refs
            or len(self.evidence_refs) != len(set(self.evidence_refs))
            or any(
                not ref.startswith(("Fact:", "Assumption:"))
                for ref in self.evidence_refs
            )
        ):
            raise ForecastInvariantError(
                "FORECAST_NARRATIVE_INVALID",
                "Narrative statements require typed category, basis, text, and unique fact/assumption lineage.",
            )
        if self.basis == NarrativeBasis.FACT and any(
            not ref.startswith("Fact:") for ref in self.evidence_refs
        ):
            raise ForecastInvariantError(
                "FORECAST_NARRATIVE_FACT_LINEAGE_INVALID",
                "Fact narrative statements may reference only resolved facts.",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement_id": self.statement_id,
            "category": self.category.value,
            "basis": self.basis.value,
            "text": self.text,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class ForecastAssumption:
    assumption_id: str
    description: str
    available_at: str
    evidence_refs: tuple[str, ...]
    value: Decimal | None = None
    unit: str = ""
    currency: str = ""
    period: str = ""
    scope: str = ""
    segment_id: str = ""
    metric_id: str = ""

    def __post_init__(self) -> None:
        try:
            date.fromisoformat(self.available_at)
        except ValueError:
            raise ForecastInvariantError(
                "FORECAST_ASSUMPTION_AVAILABLE_AT_INVALID",
                "Forecast assumption available_at must be an ISO date.",
            ) from None
        if (
            not re.fullmatch(r"[A-Za-z0-9_.:@-]+", self.assumption_id or "")
            or not self.description.strip()
            or not self.evidence_refs
            or len(self.evidence_refs) != len(set(self.evidence_refs))
            or any(not ref.startswith("Fact:") for ref in self.evidence_refs)
        ):
            raise ForecastInvariantError(
                "FORECAST_ASSUMPTION_INVALID",
                "Forecast assumptions require identity, rationale, availability, and unique Fact lineage.",
            )
        dimension_values = (
            self.unit,
            self.currency,
            self.period,
            self.scope,
            self.metric_id,
        )
        if self.value is None and any(dimension_values) or (
            self.value is not None and not all(dimension_values)
        ):
            raise ForecastInvariantError(
                "FORECAST_ASSUMPTION_DIMENSION_INVALID",
                "A quantified assumption requires complete value dimensions; a qualitative assumption must omit them.",
            )
        if self.value is not None:
            require_decimal(self.value, "ForecastAssumption.value")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "description": self.description,
            "available_at": self.available_at,
            "evidence_refs": list(self.evidence_refs),
            "value": decimal_text(self.value) if self.value is not None else None,
            "unit": self.unit,
            "currency": self.currency,
            "period": self.period,
            "scope": self.scope,
            "segment_id": self.segment_id,
            "metric_id": self.metric_id,
        }


def decimal_text(value: Decimal) -> str:
    with valuation_decimal_context():
        if value == 0:
            return "0"
        return format(value.normalize(), "f")


def require_decimal(value: Any, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ForecastInvariantError(
            "FORECAST_DECIMAL_REQUIRED",
            f"{field_name} must be a finite Decimal.",
        )
    return value


def merge_lineage(*groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ref for group in groups for ref in group))


@dataclass(frozen=True)
class ForecastQuantity:
    value: Decimal
    unit: str
    scale: Decimal
    currency: str
    period: str
    as_of: str
    lineage_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_decimal(self.value, "ForecastQuantity.value")
        require_decimal(self.scale, "ForecastQuantity.scale")
        if self.scale <= 0:
            raise ForecastInvariantError(
                "FORECAST_SCALE_INVALID",
                "ForecastQuantity.scale must be positive.",
            )
        if not self.unit or not self.period:
            raise ForecastInvariantError(
                "FORECAST_DIMENSION_MISSING",
                "ForecastQuantity requires unit and period.",
            )
        try:
            date.fromisoformat(self.as_of)
        except (TypeError, ValueError) as exc:
            raise ForecastInvariantError(
                "FORECAST_AS_OF_INVALID",
                "ForecastQuantity.as_of must be an ISO date.",
            ) from exc
        if not self.lineage_refs or any(
            not ref.startswith(("Fact:", "Assumption:")) for ref in self.lineage_refs
        ):
            raise ForecastInvariantError(
                "FORECAST_LINEAGE_INVALID",
                "Forecast quantities require Fact or Assumption lineage.",
            )

    @property
    def normalized_value(self) -> Decimal:
        with valuation_decimal_context():
            return self.value * self.scale

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": decimal_text(self.value),
            "unit": self.unit,
            "scale": decimal_text(self.scale),
            "currency": self.currency,
            "period": self.period,
            "as_of": self.as_of,
            "lineage_refs": list(self.lineage_refs),
            "normalized_value": decimal_text(self.normalized_value),
        }


@dataclass(frozen=True)
class SnapshotFact:
    fact_id: str
    subject_id: str
    scope: str
    segment_id: str
    metric_id: str
    field_name: str
    period: str
    value: Decimal
    unit: str
    currency: str
    source_id: str
    available_at: str
    official: bool
    derivation_refs: tuple[str, ...] = ()
    evidence_kind: str = "reported"
    calculation_identity: str = ""
    calculation_formula: str = ""

    def __post_init__(self) -> None:
        require_decimal(self.value, "SnapshotFact.value")
        if not all(
            (
                self.fact_id,
                self.subject_id,
                self.scope,
                self.metric_id,
                self.field_name,
                self.period,
                self.unit,
                self.source_id,
            )
        ):
            raise ForecastInvariantError(
                "FORECAST_FACT_IDENTITY_INVALID",
                "SnapshotFact requires typed identity, field, dimensions, and source.",
            )
        if (
            self.scope not in {"segment", "company"}
            or (self.scope == "segment" and not self.segment_id)
            or (self.scope == "company" and self.segment_id)
        ):
            raise ForecastInvariantError(
                "FORECAST_FACT_SCOPE_INVALID",
                "SnapshotFact scope and raw segment identity are inconsistent.",
            )
        try:
            date.fromisoformat(self.available_at)
        except (TypeError, ValueError) as exc:
            raise ForecastInvariantError(
                "FORECAST_FACT_AVAILABLE_AT_INVALID",
                "SnapshotFact.available_at must be an ISO date.",
            ) from exc
        if self.evidence_kind not in {
            "reported",
            "source_extracted",
            "calculated_from_official",
            "model_derived",
        } or (
            self.evidence_kind in {"reported", "source_extracted"}
            and (self.calculation_identity or self.calculation_formula or self.derivation_refs)
        ) or (
            self.evidence_kind in {"calculated_from_official", "model_derived"}
            and (
                not self.calculation_identity.strip()
                or not self.calculation_formula.strip()
            )
        ):
            raise ForecastInvariantError(
                "FORECAST_FACT_EVIDENCE_KIND_INVALID",
                "Snapshot facts must distinguish reported, calculated-from-official, and model-derived evidence.",
            )
        if self.evidence_kind in {"calculated_from_official", "model_derived"} and (
            not self.derivation_refs
            or f"Fact:{self.fact_id}" in self.derivation_refs
            or (
            len(self.derivation_refs) != len(set(self.derivation_refs))
            or not any(ref.startswith("Fact:") for ref in self.derivation_refs)
            or any(
                not ref.startswith(("Fact:", "Assumption:"))
                for ref in self.derivation_refs
            )
            )
        ):
            raise ForecastInvariantError(
                "FORECAST_DERIVED_FACT_LINEAGE_INVALID",
                "Non-official derived facts require unique official-fact and optional assumption lineage.",
            )
        if self.evidence_kind == "calculated_from_official" and (
            not self.official
            or any(not ref.startswith("Fact:") for ref in self.derivation_refs)
            or self.calculation_formula
            not in {
                "identity(operand)",
                "sum(operands)",
                "difference(operands)",
                "product(operands)",
                "ratio(operands)",
            }
        ):
            raise ForecastInvariantError(
                "FORECAST_DERIVED_FACT_KIND_INVALID",
                "Calculated-from-official facts require only official Fact operands.",
            )
        if self.evidence_kind == "model_derived" and self.official:
            raise ForecastInvariantError(
                "FORECAST_DERIVED_FACT_KIND_INVALID",
                "Model-derived facts cannot be marked as official evidence.",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "subject_id": self.subject_id,
            "scope": self.scope,
            "segment_id": self.segment_id,
            "metric_id": self.metric_id,
            "field_name": self.field_name,
            "period": self.period,
            "value": decimal_text(self.value),
            "unit": self.unit,
            "currency": self.currency,
            "source_id": self.source_id,
            "available_at": self.available_at,
            "official": self.official,
            "derivation_refs": list(self.derivation_refs),
            "evidence_kind": self.evidence_kind,
            "calculation_identity": self.calculation_identity,
            "calculation_formula": self.calculation_formula,
        }


@dataclass(frozen=True)
class SegmentBaseline:
    segment_id: str
    volume: ForecastQuantity
    asp: ForecastQuantity
    capacity: ForecastQuantity
    utilization: ForecastQuantity
    unit_cost: ForecastQuantity
    operating_expense: ForecastQuantity
    capex: ForecastQuantity
    working_capital: ForecastQuantity
    depreciation: ForecastQuantity
    tax_rate: ForecastQuantity

    def named_quantities(self) -> tuple[tuple[str, ForecastQuantity], ...]:
        return tuple(
            (name, getattr(self, name))
            for name in (
                "volume",
                "asp",
                "capacity",
                "utilization",
                "unit_cost",
                "operating_expense",
                "capex",
                "working_capital",
                "depreciation",
                "tax_rate",
            )
        )

    def quantities(self) -> tuple[ForecastQuantity, ...]:
        return tuple(quantity for _, quantity in self.named_quantities())

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            **{name: quantity.to_dict() for name, quantity in self.named_quantities()},
        }

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9_-]+", self.segment_id or ""):
            raise ForecastInvariantError(
                "FORECAST_SEGMENT_ID_INVALID",
                "Segment ids must use lowercase letters, digits, underscores, or hyphens.",
            )
        periods = {quantity.period for quantity in self.quantities()}
        as_of_dates = {quantity.as_of for quantity in self.quantities()}
        if len(periods) != 1 or len(as_of_dates) != 1:
            raise ForecastInvariantError(
                "FORECAST_PERIOD_MISMATCH",
                "A segment baseline must share one period and as-of date.",
            )
        if (
            self.volume.unit != "units"
            or self.capacity.unit != "units"
            or self.volume.currency not in {"", "N/A"}
            or self.capacity.currency not in {"", "N/A"}
            or self.utilization.unit != "decimal"
            or self.tax_rate.unit != "decimal"
            or self.utilization.currency not in {"", "N/A"}
            or self.tax_rate.currency not in {"", "N/A"}
        ):
            raise ForecastInvariantError(
                "FORECAST_UNIT_MISMATCH",
                "Volume, capacity, utilization, or tax-rate dimensions are invalid.",
            )
        if not Decimal("0") <= self.utilization.normalized_value <= Decimal("1.5"):
            raise ForecastInvariantError(
                "FORECAST_UTILIZATION_INVALID",
                "Baseline utilization must be between zero and 1.5.",
            )
        if not Decimal("0") <= self.tax_rate.normalized_value < Decimal("1"):
            raise ForecastInvariantError(
                "FORECAST_TAX_RATE_INVALID",
                "Baseline tax rate must be in [0, 1).",
            )
        non_negative = tuple(
            quantity
            for name, quantity in self.named_quantities()
            if name not in {"tax_rate", "utilization", "working_capital"}
        )
        if any(quantity.normalized_value < 0 for quantity in non_negative):
            raise ForecastInvariantError(
                "FORECAST_BASELINE_NEGATIVE",
                "Manufacturing baseline quantities cannot be negative.",
            )
        if any(
            not ref.startswith("Fact:")
            for quantity in self.quantities()
            for ref in quantity.lineage_refs
        ):
            raise ForecastInvariantError(
                "FORECAST_SNAPSHOT_LINEAGE_INVALID",
                "DataSnapshot baselines must contain Fact lineage only.",
            )


@dataclass(frozen=True)
class CompanyOpeningBalanceSheet:
    cash: ForecastQuantity
    working_capital: ForecastQuantity
    net_ppe: ForecastQuantity
    other_assets: ForecastQuantity
    debt: ForecastQuantity
    other_liabilities: ForecastQuantity
    equity: ForecastQuantity

    def named_quantities(self) -> tuple[tuple[str, ForecastQuantity], ...]:
        return tuple(
            (name, getattr(self, name))
            for name in (
                "cash",
                "working_capital",
                "net_ppe",
                "other_assets",
                "debt",
                "other_liabilities",
                "equity",
            )
        )

    def quantities(self) -> tuple[ForecastQuantity, ...]:
        return tuple(quantity for _, quantity in self.named_quantities())

    def to_dict(self) -> dict[str, Any]:
        return {name: quantity.to_dict() for name, quantity in self.named_quantities()}

    def __post_init__(self) -> None:
        periods = {quantity.period for quantity in self.quantities()}
        as_of_dates = {quantity.as_of for quantity in self.quantities()}
        dimensions = {
            (quantity.unit, quantity.currency) for quantity in self.quantities()
        }
        if len(periods) != 1 or len(as_of_dates) != 1 or len(dimensions) != 1:
            raise ForecastInvariantError(
                "FORECAST_OPENING_BALANCE_DIMENSION_MISMATCH",
                "Company opening balances must share one period, as-of, unit, and currency.",
            )
        if any(
            quantity.normalized_value < 0
            for name, quantity in self.named_quantities()
            if name != "working_capital"
        ):
            raise ForecastInvariantError(
                "FORECAST_OPENING_BALANCE_NEGATIVE",
                "Company opening balance-sheet quantities cannot be negative.",
            )
        if any(
            not ref.startswith("Fact:")
            for quantity in self.quantities()
            for ref in quantity.lineage_refs
        ):
            raise ForecastInvariantError(
                "FORECAST_SNAPSHOT_LINEAGE_INVALID",
                "Company opening balances require Fact lineage only.",
            )
        with valuation_decimal_context():
            assets = sum(
                (
                    self.cash.normalized_value,
                    self.working_capital.normalized_value,
                    self.net_ppe.normalized_value,
                    self.other_assets.normalized_value,
                ),
                Decimal("0"),
            )
            liabilities_and_equity = sum(
                (
                    self.debt.normalized_value,
                    self.other_liabilities.normalized_value,
                    self.equity.normalized_value,
                ),
                Decimal("0"),
            )
        if assets != liabilities_and_equity:
            raise ForecastInvariantError(
                "FORECAST_OPENING_BALANCE_UNRECONCILED",
                "Sourced company opening assets must equal liabilities plus equity.",
            )


@dataclass(frozen=True)
class DataSnapshot:
    snapshot_id: str
    security_id: str
    as_of: str
    segment_baselines: tuple[SegmentBaseline, ...]
    company_opening_balance_sheet: CompanyOpeningBalanceSheet
    facts: tuple[SnapshotFact, ...]
    content_hash: str = ""

    def __post_init__(self) -> None:
        try:
            date.fromisoformat(self.as_of)
        except (TypeError, ValueError) as exc:
            raise ForecastInvariantError(
                "FORECAST_AS_OF_INVALID",
                "DataSnapshot.as_of must be an ISO date.",
            ) from exc
        if not self.snapshot_id or not self.security_id:
            raise ForecastInvariantError(
                "FORECAST_SNAPSHOT_IDENTITY_INVALID",
                "DataSnapshot requires snapshot and Security identities.",
            )
        if not isinstance(self.segment_baselines, tuple) or not self.segment_baselines:
            raise ForecastInvariantError(
                "FORECAST_SNAPSHOT_EMPTY",
                "DataSnapshot requires typed segment baselines.",
            )
        if not isinstance(
            self.company_opening_balance_sheet,
            CompanyOpeningBalanceSheet,
        ):
            raise ForecastInvariantError(
                "FORECAST_OPENING_BALANCE_TYPE_INVALID",
                "DataSnapshot requires a typed company opening balance sheet.",
            )
        if (
            not isinstance(self.facts, tuple)
            or not self.facts
            or any(not isinstance(fact, SnapshotFact) for fact in self.facts)
        ):
            raise ForecastInvariantError(
                "FORECAST_FACT_REGISTRY_INVALID",
                "DataSnapshot requires a typed non-empty SnapshotFact registry.",
            )
        fact_by_id = {fact.fact_id: fact for fact in self.facts}
        if len(fact_by_id) != len(self.facts):
            raise ForecastInvariantError(
                "FORECAST_FACT_DUPLICATE",
                "SnapshotFact ids must be unique.",
            )
        for fact in self.facts:
            if fact.evidence_kind in {"reported", "source_extracted"}:
                continue
            operands = tuple(
                fact_by_id.get(ref.removeprefix("Fact:"))
                for ref in fact.derivation_refs
                if ref.startswith("Fact:")
            )
            if not operands or any(
                operand is None
                or not operand.official
                or operand.evidence_kind == "model_derived"
                or date.fromisoformat(operand.available_at)
                > date.fromisoformat(self.as_of)
                for operand in operands
            ):
                raise ForecastInvariantError(
                    "FORECAST_DERIVED_FACT_BASIS_INVALID",
                    f"Derived Forecast Fact {fact.fact_id} requires resolved, PIT-legal official operands.",
                )
            if fact.evidence_kind == "calculated_from_official":
                operand_values = tuple(
                    operand.value for operand in operands if operand is not None
                )
                if fact.calculation_formula == "identity(operand)":
                    calculated = operand_values[0] if len(operand_values) == 1 else None
                elif fact.calculation_formula == "sum(operands)":
                    calculated = sum(operand_values, Decimal("0"))
                elif fact.calculation_formula == "difference(operands)":
                    calculated = (
                        operand_values[0] - sum(operand_values[1:], Decimal("0"))
                        if operand_values
                        else None
                    )
                elif fact.calculation_formula == "product(operands)":
                    calculated = Decimal("1")
                    for operand_value in operand_values:
                        calculated *= operand_value
                else:
                    calculated = (
                        operand_values[0] / operand_values[1]
                        if len(operand_values) == 2 and operand_values[1] != 0
                        else None
                    )
                if calculated != fact.value:
                    raise ForecastInvariantError(
                        "FORECAST_CALCULATED_FACT_MISMATCH",
                        f"Calculated Forecast Fact {fact.fact_id} does not recompute from its operands.",
                    )
        ids = [baseline.segment_id for baseline in self.segment_baselines]
        if len(ids) != len(set(ids)):
            raise ForecastInvariantError(
                "FORECAST_SEGMENT_DUPLICATE",
                "DataSnapshot segment ids must be unique.",
            )
        if any(
            quantity.as_of != self.as_of
            for baseline in self.segment_baselines
            for quantity in baseline.quantities()
        ):
            raise ForecastInvariantError(
                "FORECAST_AS_OF_MISMATCH",
                "DataSnapshot facts must share the snapshot as-of date.",
            )
        if any(
            quantity.as_of != self.as_of
            for quantity in self.company_opening_balance_sheet.quantities()
        ):
            raise ForecastInvariantError(
                "FORECAST_AS_OF_MISMATCH",
                "Company opening balances must share the snapshot as-of date.",
            )
        segment_periods = {
            quantity.period
            for baseline in self.segment_baselines
            for quantity in baseline.quantities()
        }
        opening_periods = {
            quantity.period
            for quantity in self.company_opening_balance_sheet.quantities()
        }
        if len(segment_periods) != 1 or segment_periods != opening_periods:
            raise ForecastInvariantError(
                "FORECAST_OPENING_BALANCE_PERIOD_MISMATCH",
                "Operational baselines and the sourced company opening balance must share one period.",
            )
        if any(
            period_rank(quantity.period) > period_rank(self.as_of)
            for baseline in self.segment_baselines
            for quantity in baseline.quantities()
        ):
            raise ForecastInvariantError(
                "FORECAST_FUTURE_FACT",
                "DataSnapshot cannot contain facts after its as-of date.",
            )
        if any(
            period_rank(quantity.period) > period_rank(self.as_of)
            for quantity in self.company_opening_balance_sheet.quantities()
        ):
            raise ForecastInvariantError(
                "FORECAST_FUTURE_FACT",
                "Company opening balances cannot be after the snapshot as-of date.",
            )
        with valuation_decimal_context():
            allocated_working_capital = sum(
                (
                    baseline.working_capital.normalized_value
                    for baseline in self.segment_baselines
                ),
                Decimal("0"),
            )
        if (
            allocated_working_capital
            != self.company_opening_balance_sheet.working_capital.normalized_value
        ):
            raise ForecastInvariantError(
                "FORECAST_OPENING_WORKING_CAPITAL_MISMATCH",
                "Segment working-capital drivers must reconcile to the sourced company opening balance.",
            )
        bound_quantities = tuple(
            ("segment", baseline.segment_id, metric, quantity)
            for baseline in self.segment_baselines
            for metric, quantity in baseline.named_quantities()
        ) + tuple(
            ("company", "", metric, quantity)
            for metric, quantity in self.company_opening_balance_sheet.named_quantities()
        )
        for (
            expected_scope,
            expected_segment_id,
            expected_metric_id,
            quantity,
        ) in bound_quantities:
            for lineage_ref in quantity.lineage_refs:
                fact_id = lineage_ref.removeprefix("Fact:")
                fact = fact_by_id.get(fact_id)
                if fact is None:
                    raise ForecastInvariantError(
                        "FORECAST_FACT_REFERENCE_MISSING",
                        f"Snapshot Fact reference does not resolve: {fact_id}.",
                    )
                if (
                    fact.subject_id != self.security_id
                    or fact.scope != expected_scope
                    or fact.segment_id != expected_segment_id
                    or fact.metric_id != expected_metric_id
                    or fact.period != quantity.period
                    or fact.unit != quantity.unit
                    or fact.currency != quantity.currency
                    or fact.value != quantity.normalized_value
                    or date.fromisoformat(fact.available_at)
                    > date.fromisoformat(self.as_of)
                ):
                    raise ForecastInvariantError(
                        "FORECAST_FACT_BINDING_MISMATCH",
                        f"Snapshot Fact {fact_id} does not match its quantity and PIT dimensions.",
                    )
                if fact.evidence_kind in {"calculated_from_official", "model_derived"}:
                    basis_facts = tuple(
                        fact_by_id.get(ref.removeprefix("Fact:"))
                        for ref in fact.derivation_refs
                        if ref.startswith("Fact:")
                    )
                    if not basis_facts or any(
                        basis is None
                        or not basis.official
                        or basis.evidence_kind == "model_derived"
                        or date.fromisoformat(basis.available_at)
                        > date.fromisoformat(self.as_of)
                        for basis in basis_facts
                    ):
                        raise ForecastInvariantError(
                            "FORECAST_DERIVED_FACT_BASIS_INVALID",
                            f"Derived Forecast Fact {fact_id} requires resolved, PIT-legal official operands.",
                        )
        expected = self.canonical_content_hash(
            self.security_id,
            self.as_of,
            self.segment_baselines,
            self.company_opening_balance_sheet,
            self.facts,
        )
        if self.content_hash and self.content_hash != expected:
            raise ForecastInvariantError(
                "FORECAST_SNAPSHOT_HASH_MISMATCH",
                "DataSnapshot.content_hash does not match its typed content.",
            )
        object.__setattr__(self, "content_hash", expected)

    @staticmethod
    def canonical_content_hash(
        security_id: str,
        as_of: str,
        baselines: tuple[SegmentBaseline, ...],
        opening_balance_sheet: CompanyOpeningBalanceSheet,
        facts: tuple[SnapshotFact, ...],
    ) -> str:
        payload = {
            "security_id": security_id,
            "as_of": as_of,
            "segment_baselines": [
                baseline.to_dict()
                for baseline in sorted(baselines, key=lambda item: item.segment_id)
            ],
            "company_opening_balance_sheet": opening_balance_sheet.to_dict(),
            "facts": [
                fact.to_dict() for fact in sorted(facts, key=lambda item: item.fact_id)
            ],
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "security_id": self.security_id,
            "as_of": self.as_of,
            "content_hash": self.content_hash,
            "segment_baselines": [
                baseline.to_dict() for baseline in self.segment_baselines
            ],
            "company_opening_balance_sheet": self.company_opening_balance_sheet.to_dict(),
            "facts": [fact.to_dict() for fact in self.facts],
        }


@dataclass(frozen=True)
class DataInsufficientSnapshot:
    """Explicit missing-data state; it carries no financial facts."""

    snapshot_id: str
    security_id: str
    as_of: str
    missing_fields: tuple[str, ...]
    content_hash: str = ""

    def __post_init__(self) -> None:
        try:
            date.fromisoformat(self.as_of)
        except (TypeError, ValueError) as exc:
            raise ForecastInvariantError(
                "FORECAST_AS_OF_INVALID",
                "DataInsufficientSnapshot.as_of must be an ISO date.",
            ) from exc
        if (
            not self.snapshot_id
            or not self.security_id
            or not self.missing_fields
            or len(self.missing_fields) != len(set(self.missing_fields))
        ):
            raise ForecastInvariantError(
                "FORECAST_DATA_INSUFFICIENT_INVALID",
                "Missing-data snapshots require identity and unique missing fields.",
            )
        payload = self.to_dict()
        payload.pop("content_hash")
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if self.content_hash and self.content_hash != digest:
            raise ForecastInvariantError(
                "FORECAST_SNAPSHOT_HASH_MISMATCH",
                "Data-insufficient snapshot content hash does not replay.",
            )
        object.__setattr__(self, "content_hash", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "security_id": self.security_id,
            "as_of": self.as_of,
            "content_hash": self.content_hash,
            "segment_baselines": [],
            "company_opening_balance_sheet": None,
            "facts": [],
            "missing_fields": list(self.missing_fields),
            "degradation_code": "DATA_INSUFFICIENT",
        }


@dataclass(frozen=True)
class Security:
    security_id: str
    company_name: str
    market: str
    reporting_currency: str
    archetype: CompanyArchetype
    segment_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all(
            (self.security_id, self.company_name, self.market, self.reporting_currency)
        ):
            raise ForecastInvariantError(
                "FORECAST_SECURITY_INVALID",
                "Security identity, market, and reporting currency are required.",
            )
        if not isinstance(self.archetype, CompanyArchetype):
            raise ForecastInvariantError(
                "FORECAST_ARCHETYPE_INVALID",
                "Security.archetype must be a CompanyArchetype.",
            )
        if (
            not isinstance(self.segment_ids, tuple)
            or not self.segment_ids
            or len(self.segment_ids) != len(set(self.segment_ids))
        ):
            raise ForecastInvariantError(
                "FORECAST_SEGMENTS_INVALID",
                "Security.segment_ids must be a non-empty unique tuple.",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "company_name": self.company_name,
            "market": self.market,
            "reporting_currency": self.reporting_currency,
            "archetype": self.archetype.value,
            "segment_ids": list(self.segment_ids),
        }


@dataclass(frozen=True)
class DataInsufficientForecastRequest:
    security: Security
    as_of: str
    data_snapshot: DataInsufficientSnapshot
    forecast_periods: tuple[str, ...]
    review_date: str
    assumption_overrides: tuple[SegmentForecastOverride, ...] = ()
    assumptions: tuple[ForecastAssumption, ...] = ()
    narrative_statements: tuple[ForecastNarrativeStatement, ...] = ()

    def __post_init__(self) -> None:
        try:
            date.fromisoformat(self.as_of)
            date.fromisoformat(self.review_date)
        except (TypeError, ValueError) as exc:
            raise ForecastInvariantError(
                "FORECAST_DATA_INSUFFICIENT_REQUEST_INVALID",
                "Degraded forecast dates must be ISO dates.",
            ) from exc
        if (
            self.security.security_id != self.data_snapshot.security_id
            or self.as_of != self.data_snapshot.as_of
            or not self.forecast_periods
            or any(not period.endswith("E") for period in self.forecast_periods)
            or self.assumption_overrides
            or self.assumptions
            or self.narrative_statements
        ):
            raise ForecastInvariantError(
                "FORECAST_DATA_INSUFFICIENT_REQUEST_INVALID",
                "Degraded forecasts require one subject, forecast periods, and no assumptions.",
            )


@dataclass(frozen=True)
class SegmentForecastOverride:
    segment_id: str
    period: str
    demand_growth: Decimal | None = None
    asp_growth: Decimal | None = None
    capacity_growth: Decimal | None = None
    target_utilization: Decimal | None = None
    unit_cost_growth: Decimal | None = None
    operating_expense_growth: Decimal | None = None
    capex_growth: Decimal | None = None
    depreciation_growth: Decimal | None = None
    working_capital_to_revenue: Decimal | None = None
    tax_rate: Decimal | None = None
    debt_change: Decimal | None = None
    event_probability: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.segment_id or period_rank(self.period) < 0:
            raise ForecastInvariantError(
                "FORECAST_OVERRIDE_IDENTITY_INVALID",
                "Override segment and forecast period are required.",
            )
        for field_name in self.field_names():
            value = getattr(self, field_name)
            if value is not None:
                require_decimal(value, field_name)
        for field_name in (
            "demand_growth",
            "asp_growth",
            "capacity_growth",
            "unit_cost_growth",
            "operating_expense_growth",
            "capex_growth",
            "depreciation_growth",
        ):
            value = getattr(self, field_name)
            if value is not None and value <= Decimal("-1"):
                raise ForecastInvariantError(
                    "FORECAST_GROWTH_INVALID",
                    f"{field_name} must be greater than -1.",
                )
        if self.target_utilization is not None and not (
            Decimal("0") <= self.target_utilization <= Decimal("1.5")
        ):
            raise ForecastInvariantError(
                "FORECAST_UTILIZATION_INVALID",
                "target_utilization must be in [0, 1.5].",
            )
        for field_name in ("tax_rate", "event_probability"):
            value = getattr(self, field_name)
            if value is not None and not Decimal("0") <= value <= Decimal("1"):
                raise ForecastInvariantError(
                    "FORECAST_PROBABILITY_INVALID",
                    f"{field_name} must be in [0, 1].",
                )

    @staticmethod
    def field_names() -> tuple[str, ...]:
        return (
            "demand_growth",
            "asp_growth",
            "capacity_growth",
            "target_utilization",
            "unit_cost_growth",
            "operating_expense_growth",
            "capex_growth",
            "depreciation_growth",
            "working_capital_to_revenue",
            "tax_rate",
            "debt_change",
            "event_probability",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "period": self.period,
            **{
                name: decimal_text(value) if value is not None else None
                for name in self.field_names()
                for value in (getattr(self, name),)
            },
        }


@dataclass(frozen=True)
class ForecastRequest:
    security: Security
    as_of: str
    data_snapshot: DataSnapshot
    forecast_periods: tuple[str, ...]
    assumption_overrides: tuple[SegmentForecastOverride, ...] = ()
    review_date: str = ""
    assumptions: tuple[ForecastAssumption, ...] = ()
    narrative_statements: tuple[ForecastNarrativeStatement, ...] = ()

    def __post_init__(self) -> None:
        ForecastEvidence.validate_request(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "security": self.security.to_dict(),
            "as_of": self.as_of,
            "data_snapshot": self.data_snapshot.to_dict(),
            "forecast_periods": list(self.forecast_periods),
            "assumption_overrides": [
                item.to_dict() for item in self.assumption_overrides
            ],
            "review_date": self.review_date,
            "assumptions": [item.to_dict() for item in self.assumptions],
            "narrative_statements": [
                item.to_dict() for item in self.narrative_statements
            ],
        }
