from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable

from .evidence import period_rank
from .financial import valuation_decimal_context


class ForecastInvariantError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class CompanyArchetype(str, Enum):
    GENERAL_MANUFACTURING = "general_manufacturing"
    MULTI_SEGMENT_MANUFACTURING = "multi_segment_manufacturing"
    FINANCIAL_INSTITUTION = "financial_institution"
    BIOPHARMA = "biopharma"
    CYCLICAL_RESOURCE = "cyclical_resource"


class ForecastNodeKind(str, Enum):
    EVENT = "Event"
    DRIVER = "Driver"
    FINANCIAL_FORECAST = "FinancialForecast"
    VALUATION_INPUT = "ValuationInput"


class NodeOrigin(str, Enum):
    INPUT = "input"
    DERIVED = "derived"


class FormulaId(str, Enum):
    GROWTH = "growth"
    PRODUCT = "product"
    MINIMUM = "minimum"
    SUM = "sum"
    RATIO = "ratio"
    POSITIVE_TAX = "positive_tax"
    PASSTHROUGH = "passthrough"
    CONSENSUS = "consensus"
    VALUATION_GATE = "valuation_gate"


class ConditionOperator(str, Enum):
    ACTUAL_WITHIN = "actual_within"
    ACTUAL_OUTSIDE = "actual_outside"


def _decimal_text(value: Decimal) -> str:
    with valuation_decimal_context():
        if value == 0:
            return "0"
        return format(value.normalize(), "f")


def _require_decimal(value: Any, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ForecastInvariantError(
            "FORECAST_DECIMAL_REQUIRED",
            f"{field_name} must be a finite Decimal.",
        )
    return value


def _merge_lineage(*groups: Iterable[str]) -> tuple[str, ...]:
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
        _require_decimal(self.value, "ForecastQuantity.value")
        _require_decimal(self.scale, "ForecastQuantity.scale")
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
            "value": _decimal_text(self.value),
            "unit": self.unit,
            "scale": _decimal_text(self.scale),
            "currency": self.currency,
            "period": self.period,
            "as_of": self.as_of,
            "lineage_refs": list(self.lineage_refs),
            "normalized_value": _decimal_text(self.normalized_value),
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

    def __post_init__(self) -> None:
        _require_decimal(self.value, "SnapshotFact.value")
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "subject_id": self.subject_id,
            "scope": self.scope,
            "segment_id": self.segment_id,
            "metric_id": self.metric_id,
            "field_name": self.field_name,
            "period": self.period,
            "value": _decimal_text(self.value),
            "unit": self.unit,
            "currency": self.currency,
            "source_id": self.source_id,
            "available_at": self.available_at,
            "official": self.official,
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
                if not fact.official:
                    raise ForecastInvariantError(
                        "FORECAST_OFFICIAL_FACT_REQUIRED",
                        f"Critical Forecast Fact {fact_id} requires an official source.",
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
                _require_decimal(value, field_name)
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
                name: _decimal_text(value) if value is not None else None
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

    def __post_init__(self) -> None:
        if not isinstance(self.assumption_overrides, tuple) or any(
            not isinstance(item, SegmentForecastOverride)
            for item in self.assumption_overrides
        ):
            raise ForecastInvariantError(
                "FORECAST_OVERRIDE_TYPE_INVALID",
                "assumption_overrides must be a tuple of SegmentForecastOverride.",
            )
        if self.as_of != self.data_snapshot.as_of:
            raise ForecastInvariantError(
                "FORECAST_AS_OF_MISMATCH",
                "ForecastRequest.as_of must match DataSnapshot.as_of.",
            )
        if self.security.security_id != self.data_snapshot.security_id:
            raise ForecastInvariantError(
                "FORECAST_SNAPSHOT_SUBJECT_MISMATCH",
                "DataSnapshot must be frozen for the requested Security.",
            )
        ranks = [period_rank(period) for period in self.forecast_periods]
        if (
            not isinstance(self.forecast_periods, tuple)
            or not self.forecast_periods
            or any(rank < 0 for rank in ranks)
            or ranks != sorted(ranks)
            or len(set(self.forecast_periods)) != len(self.forecast_periods)
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
                    for baseline in self.data_snapshot.segment_baselines
                    for quantity in baseline.quantities()
                ),
                *self.data_snapshot.company_opening_balance_sheet.quantities(),
            )
        )
        if any(rank <= latest_baseline_rank for rank in ranks):
            raise ForecastInvariantError(
                "FORECAST_PERIOD_NOT_FORWARD",
                "Every forecast period must follow the frozen baseline period.",
            )
        try:
            if date.fromisoformat(self.review_date) < date.fromisoformat(self.as_of):
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ForecastInvariantError(
                "FORECAST_REVIEW_DATE_INVALID",
                "review_date must be an ISO date on or after as_of.",
            ) from exc
        keys = [
            (override.segment_id, override.period)
            for override in self.assumption_overrides
        ]
        if len(keys) != len(set(keys)):
            raise ForecastInvariantError(
                "FORECAST_OVERRIDE_DUPLICATE",
                "Only one typed override is allowed per segment and period.",
            )

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
        }


@dataclass(frozen=True)
class LeadingIndicator:
    metric_id: str
    expected_direction: str
    unit: str
    scale: Decimal
    currency: str
    period: str


@dataclass(frozen=True)
class ForecastCondition:
    metric_id: str
    operator: ConditionOperator | str
    threshold: ForecastQuantity

    def __post_init__(self) -> None:
        try:
            operator = ConditionOperator(self.operator)
        except ValueError as exc:
            raise ForecastInvariantError(
                "FORECAST_CONDITION_OPERATOR_INVALID",
                "ForecastCondition.operator is unsupported.",
            ) from exc
        object.__setattr__(self, "operator", operator)


@dataclass(frozen=True)
class ForecastNode:
    node_id: str
    kind: ForecastNodeKind
    origin: NodeOrigin
    label: str
    quantity: ForecastQuantity
    horizon: str
    milestone: str
    leading_indicators: tuple[LeadingIndicator, ...]
    trigger_conditions: tuple[ForecastCondition, ...]
    invalidation_conditions: tuple[ForecastCondition, ...]
    review_date: str
    conditional_probability: Decimal
    lineage_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_decimal(self.conditional_probability, "conditional_probability")
        if not Decimal("0") <= self.conditional_probability <= Decimal("1"):
            raise ForecastInvariantError(
                "FORECAST_PROBABILITY_INVALID",
                "conditional_probability must be in [0, 1].",
            )
        if (
            not self.node_id
            or not isinstance(self.kind, ForecastNodeKind)
            or not isinstance(self.origin, NodeOrigin)
            or self.horizon != self.quantity.period
            or not self.milestone
            or not self.leading_indicators
            or not self.trigger_conditions
            or not self.invalidation_conditions
            or self.lineage_refs != self.quantity.lineage_refs
        ):
            raise ForecastInvariantError(
                "FORECAST_NODE_METADATA_INVALID",
                "Forecast nodes require typed horizon, monitoring, review, and lineage metadata.",
            )


@dataclass(frozen=True)
class ForecastEdge:
    source_id: str
    target_id: str
    formula_id: FormulaId | str
    operand_role: str
    coefficient: Decimal
    source_unit: str
    source_scale: Decimal
    target_unit: str
    target_scale: Decimal
    period_rule: str
    currency_rule: str

    def __post_init__(self) -> None:
        try:
            formula_id = FormulaId(self.formula_id)
        except ValueError as exc:
            raise ForecastInvariantError(
                "FORECAST_FORMULA_INVALID",
                f"Unsupported forecast formula: {self.formula_id}.",
            ) from exc
        object.__setattr__(self, "formula_id", formula_id)
        _require_decimal(self.coefficient, "ForecastEdge.coefficient")
        _require_decimal(self.source_scale, "ForecastEdge.source_scale")
        _require_decimal(self.target_scale, "ForecastEdge.target_scale")
        if not self.operand_role:
            raise ForecastInvariantError(
                "FORECAST_OPERAND_ROLE_INVALID",
                "ForecastEdge requires a named operand role.",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "formula_id": self.formula_id.value,
            "operand_role": self.operand_role,
            "coefficient": _decimal_text(self.coefficient),
            "source_unit": self.source_unit,
            "source_scale": _decimal_text(self.source_scale),
            "target_unit": self.target_unit,
            "target_scale": _decimal_text(self.target_scale),
            "period_rule": self.period_rule,
            "currency_rule": self.currency_rule,
        }


def _calculate_formula(
    formula_id: FormulaId,
    operands: dict[str, tuple[Decimal, Decimal]],
) -> Decimal:
    with valuation_decimal_context():
        if formula_id == FormulaId.GROWTH:
            return operands["base"][0] * (Decimal("1") + operands["rate"][0])
        if formula_id == FormulaId.PRODUCT:
            return operands["left"][0] * operands["right"][0]
        if formula_id == FormulaId.MINIMUM:
            return min(value for value, _ in operands.values())
        if formula_id == FormulaId.SUM:
            return sum(
                (value * coefficient for value, coefficient in operands.values()),
                Decimal("0"),
            )
        if formula_id == FormulaId.RATIO:
            denominator = operands["denominator"][0]
            return (
                operands["numerator"][0] / denominator if denominator else Decimal("0")
            )
        if formula_id == FormulaId.POSITIVE_TAX:
            return (
                max(operands["taxable_income"][0], Decimal("0")) * operands["rate"][0]
            )
        if formula_id == FormulaId.PASSTHROUGH:
            return operands["value"][0]
        if formula_id == FormulaId.CONSENSUS:
            values = {value for value, _ in operands.values()}
            if len(values) != 1:
                raise ForecastInvariantError(
                    "FORECAST_CONSENSUS_MISMATCH",
                    "Consensus operands must contain one exact value.",
                )
            return next(iter(values))
        if formula_id == FormulaId.VALUATION_GATE:
            if (
                operands["balance_sheet_check"][0] != 0
                or operands["cash_flow_check"][0] != 0
            ):
                raise ForecastInvariantError(
                    "FORECAST_STATEMENT_RECONCILIATION_FAILED",
                    "Valuation input is blocked until all statement checks equal zero.",
                )
            if any(operands[role][0] < 0 for role in ("cash", "debt", "net_ppe")):
                raise ForecastInvariantError(
                    "FORECAST_ECONOMIC_BALANCE_INVALID",
                    "Negative cash, debt, or net PPE must be reclassified or corrected before valuation.",
                )
            return operands["value"][0]
    raise AssertionError(formula_id)


@dataclass(frozen=True)
class ForecastGraph:
    graph_id: str
    security_id: str
    data_snapshot_id: str
    template_id: str
    routing_explanation: str
    nodes: tuple[ForecastNode, ...]
    edges: tuple[ForecastEdge, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.nodes, tuple) or not isinstance(self.edges, tuple):
            raise ForecastInvariantError(
                "FORECAST_GRAPH_TYPE_INVALID",
                "ForecastGraph nodes and edges must be tuples.",
            )
        node_by_id = {node.node_id: node for node in self.nodes}
        if len(node_by_id) != len(self.nodes):
            raise ForecastInvariantError(
                "FORECAST_NODE_DUPLICATE",
                "ForecastGraph node ids must be unique.",
            )
        incoming: dict[str, list[ForecastEdge]] = {
            node_id: [] for node_id in node_by_id
        }
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_by_id}
        indegree = {node_id: 0 for node_id in node_by_id}
        for edge in self.edges:
            if edge.source_id not in node_by_id or edge.target_id not in node_by_id:
                raise ForecastInvariantError(
                    "FORECAST_EDGE_NODE_MISSING",
                    f"ForecastEdge {edge.source_id} -> {edge.target_id} must reference existing nodes.",
                )
            source = node_by_id[edge.source_id]
            target = node_by_id[edge.target_id]
            if (
                source.quantity.unit != edge.source_unit
                or source.quantity.scale != edge.source_scale
                or target.quantity.unit != edge.target_unit
                or target.quantity.scale != edge.target_scale
            ):
                raise ForecastInvariantError(
                    "FORECAST_EDGE_UNIT_MISMATCH",
                    "ForecastEdge declared units or scales do not match its nodes.",
                )
            if (
                edge.period_rule == "same"
                and source.quantity.period != target.quantity.period
            ):
                raise ForecastInvariantError(
                    "FORECAST_EDGE_PERIOD_MISMATCH",
                    "A same-period edge crosses periods.",
                )
            if edge.period_rule == "prior" and not (
                period_rank(source.quantity.period)
                < period_rank(target.quantity.period)
            ):
                raise ForecastInvariantError(
                    "FORECAST_EDGE_PERIOD_MISMATCH",
                    "A prior-period edge is not strictly earlier.",
                )
            if edge.period_rule not in {"same", "prior"}:
                raise ForecastInvariantError(
                    "FORECAST_EDGE_PERIOD_RULE_INVALID",
                    "ForecastEdge period_rule must be same or prior.",
                )
            if (
                edge.currency_rule == "same"
                and source.quantity.currency != target.quantity.currency
            ):
                raise ForecastInvariantError(
                    "FORECAST_EDGE_CURRENCY_MISMATCH",
                    "A same-currency edge crosses currencies.",
                )
            if edge.currency_rule == "target" and (
                source.quantity.currency not in {"", "N/A", target.quantity.currency}
            ):
                raise ForecastInvariantError(
                    "FORECAST_EDGE_CURRENCY_MISMATCH",
                    "A target-currency edge crosses two money currencies.",
                )
            if edge.currency_rule not in {"same", "target", "not_applicable"}:
                raise ForecastInvariantError(
                    "FORECAST_EDGE_CURRENCY_RULE_INVALID",
                    "ForecastEdge currency_rule is invalid.",
                )
            incoming[edge.target_id].append(edge)
            adjacency[edge.source_id].append(edge.target_id)
            indegree[edge.target_id] += 1

        frontier = sorted(
            node_id for node_id, degree in indegree.items() if degree == 0
        )
        visited: list[str] = []
        work_indegree = dict(indegree)
        while frontier:
            node_id = frontier.pop(0)
            visited.append(node_id)
            for target_id in adjacency[node_id]:
                work_indegree[target_id] -= 1
                if work_indegree[target_id] == 0:
                    frontier.append(target_id)
                    frontier.sort()
        if len(visited) != len(node_by_id):
            raise ForecastInvariantError(
                "FORECAST_GRAPH_CYCLE",
                "ForecastGraph dependencies must be acyclic.",
            )

        for node_id, edges in incoming.items():
            node = node_by_id[node_id]
            if node.origin == NodeOrigin.DERIVED and not edges:
                raise ForecastInvariantError(
                    "FORECAST_DERIVED_FORMULA_MISSING",
                    f"Derived node {node_id} must retain its declared formula operands.",
                )
            if node.origin == NodeOrigin.INPUT and edges:
                raise ForecastInvariantError(
                    "FORECAST_INPUT_DEPENDENCY_INVALID",
                    f"Input node {node_id} cannot have calculation dependencies.",
                )
            if edges:
                self._validate_formula(node, edges, node_by_id)
                expected_lineage = _merge_lineage(
                    *(node_by_id[edge.source_id].lineage_refs for edge in edges)
                )
                if node_by_id[node_id].lineage_refs != expected_lineage:
                    raise ForecastInvariantError(
                        "FORECAST_LINEAGE_PROPAGATION_INVALID",
                        f"{node_id} lineage must follow its declared operands.",
                    )
            self._validate_monitoring(node_by_id[node_id], node_by_id)

        allowed_targets = {
            ForecastNodeKind.EVENT: {
                ForecastNodeKind.DRIVER,
                ForecastNodeKind.FINANCIAL_FORECAST,
            },
            ForecastNodeKind.DRIVER: {
                ForecastNodeKind.EVENT,
                ForecastNodeKind.DRIVER,
                ForecastNodeKind.FINANCIAL_FORECAST,
            },
            ForecastNodeKind.FINANCIAL_FORECAST: {
                ForecastNodeKind.FINANCIAL_FORECAST,
                ForecastNodeKind.VALUATION_INPUT,
            },
            ForecastNodeKind.VALUATION_INPUT: set(),
        }
        for edge in self.edges:
            source = node_by_id[edge.source_id]
            target = node_by_id[edge.target_id]
            if target.kind not in allowed_targets[source.kind]:
                raise ForecastInvariantError(
                    "FORECAST_DEPENDENCY_KIND_INVALID",
                    f"{source.kind.value} cannot feed {target.kind.value}.",
                )
        self.replay()

    @staticmethod
    def _validate_monitoring(
        node: ForecastNode,
        node_by_id: dict[str, ForecastNode],
    ) -> None:
        for indicator in node.leading_indicators:
            referenced = node_by_id.get(indicator.metric_id)
            if referenced is None:
                raise ForecastInvariantError(
                    "FORECAST_MONITORING_REFERENCE_MISSING",
                    f"Leading indicator {indicator.metric_id} does not resolve.",
                )
            quantity = referenced.quantity
            if (
                indicator.unit != quantity.unit
                or indicator.scale != quantity.scale
                or indicator.currency != quantity.currency
                or indicator.period != quantity.period
            ):
                raise ForecastInvariantError(
                    "FORECAST_MONITORING_DIMENSION_MISMATCH",
                    "Leading-indicator dimensions must match the referenced metric.",
                )
        for condition in node.trigger_conditions + node.invalidation_conditions:
            referenced = node_by_id.get(condition.metric_id)
            if referenced is None:
                raise ForecastInvariantError(
                    "FORECAST_MONITORING_REFERENCE_MISSING",
                    f"Condition metric {condition.metric_id} does not resolve.",
                )
            metric = referenced.quantity
            threshold = condition.threshold
            if (
                threshold.unit != metric.unit
                or threshold.scale != metric.scale
                or threshold.currency != metric.currency
                or threshold.period != metric.period
            ):
                raise ForecastInvariantError(
                    "FORECAST_MONITORING_DIMENSION_MISMATCH",
                    "Condition threshold dimensions must match the monitored metric.",
                )

    @staticmethod
    def _validate_formula(
        target: ForecastNode,
        edges: list[ForecastEdge],
        node_by_id: dict[str, ForecastNode],
    ) -> None:
        formulas = {edge.formula_id for edge in edges}
        roles = {edge.operand_role for edge in edges}
        if len(formulas) != 1 or len(roles) != len(edges):
            raise ForecastInvariantError(
                "FORECAST_FORMULA_SIGNATURE_INVALID",
                "Each target requires one formula and unique named operands.",
            )
        formula = next(iter(formulas))
        required = {
            FormulaId.GROWTH: {"base", "rate"},
            FormulaId.PRODUCT: {"left", "right"},
            FormulaId.RATIO: {"numerator", "denominator"},
            FormulaId.POSITIVE_TAX: {"taxable_income", "rate"},
            FormulaId.PASSTHROUGH: {"value"},
            FormulaId.VALUATION_GATE: {
                "value",
                "balance_sheet_check",
                "cash_flow_check",
                "cash",
                "debt",
                "net_ppe",
            },
        }
        if formula in required and roles != required[formula]:
            raise ForecastInvariantError(
                "FORECAST_FORMULA_SIGNATURE_INVALID",
                f"{formula.value} operands must be {sorted(required[formula])}.",
            )
        if formula == FormulaId.MINIMUM and len(edges) < 2:
            raise ForecastInvariantError(
                "FORECAST_FORMULA_SIGNATURE_INVALID",
                "minimum requires at least two named candidates.",
            )
        if formula == FormulaId.SUM and not edges:
            raise ForecastInvariantError(
                "FORECAST_FORMULA_SIGNATURE_INVALID",
                "sum requires at least one signed term.",
            )
        if formula == FormulaId.CONSENSUS and not edges:
            raise ForecastInvariantError(
                "FORECAST_FORMULA_SIGNATURE_INVALID",
                "consensus requires at least one exact candidate.",
            )
        if formula != FormulaId.SUM and any(
            edge.coefficient != Decimal("1") for edge in edges
        ):
            raise ForecastInvariantError(
                "FORECAST_FORMULA_SIGNATURE_INVALID",
                "Only sum operands may carry signed coefficients.",
            )
        sources = {edge.operand_role: node_by_id[edge.source_id] for edge in edges}
        target_q = target.quantity
        if formula in {
            FormulaId.SUM,
            FormulaId.MINIMUM,
            FormulaId.PASSTHROUGH,
            FormulaId.CONSENSUS,
            FormulaId.VALUATION_GATE,
        }:
            if any(
                source.quantity.unit != target_q.unit
                or source.quantity.currency != target_q.currency
                for source in sources.values()
            ):
                raise ForecastInvariantError(
                    "FORECAST_EDGE_UNIT_MISMATCH",
                    f"{formula.value} operands must match the target dimensions.",
                )
        elif formula == FormulaId.GROWTH:
            base = sources["base"].quantity
            rate = sources["rate"].quantity
            if (
                (base.unit, base.currency) != (target_q.unit, target_q.currency)
                or rate.unit != "decimal"
                or rate.currency not in {"", "N/A"}
            ):
                raise ForecastInvariantError(
                    "FORECAST_EDGE_UNIT_MISMATCH",
                    "growth requires a same-dimension base and decimal rate.",
                )
        elif formula == FormulaId.PRODUCT:
            left = sources["left"].quantity
            right = sources["right"].quantity
            if not ForecastGraph._product_dimensions_match(left, right, target_q):
                raise ForecastInvariantError(
                    "FORECAST_EDGE_UNIT_MISMATCH",
                    "product operands do not algebraically produce the target dimensions.",
                )
        elif formula == FormulaId.RATIO:
            numerator = sources["numerator"].quantity
            denominator = sources["denominator"].quantity
            if (
                target_q.unit != "decimal"
                or target_q.currency not in {"", "N/A"}
                or (numerator.unit, numerator.currency)
                != (denominator.unit, denominator.currency)
            ):
                raise ForecastInvariantError(
                    "FORECAST_EDGE_UNIT_MISMATCH",
                    "ratio requires same-dimension operands and a decimal target.",
                )
        elif formula == FormulaId.POSITIVE_TAX:
            taxable = sources["taxable_income"].quantity
            rate = sources["rate"].quantity
            if (
                (taxable.unit, taxable.currency) != (target_q.unit, target_q.currency)
                or rate.unit != "decimal"
                or rate.currency not in {"", "N/A"}
            ):
                raise ForecastInvariantError(
                    "FORECAST_EDGE_UNIT_MISMATCH",
                    "positive_tax requires taxable money and a decimal rate.",
                )

    @staticmethod
    def _product_dimensions_match(
        left: ForecastQuantity,
        right: ForecastQuantity,
        target: ForecastQuantity,
    ) -> bool:
        if left.unit == "decimal" and left.currency in {"", "N/A"}:
            return (right.unit, right.currency) == (target.unit, target.currency)
        if right.unit == "decimal" and right.currency in {"", "N/A"}:
            return (left.unit, left.currency) == (target.unit, target.currency)
        pairs = ((left, right), (right, left))
        return any(
            units.unit == "units"
            and units.currency in {"", "N/A"}
            and per_unit.unit == f"{target.currency}/unit"
            and per_unit.currency == target.currency
            and target.unit == target.currency
            for units, per_unit in pairs
        )

    def replay(self) -> dict[str, Decimal]:
        node_by_id = {node.node_id: node for node in self.nodes}
        incoming: dict[str, list[ForecastEdge]] = {
            node_id: [] for node_id in node_by_id
        }
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_by_id}
        indegree = {node_id: 0 for node_id in node_by_id}
        for edge in self.edges:
            incoming[edge.target_id].append(edge)
            adjacency[edge.source_id].append(edge.target_id)
            indegree[edge.target_id] += 1
        frontier = sorted(
            node_id for node_id, degree in indegree.items() if degree == 0
        )
        values: dict[str, Decimal] = {}
        while frontier:
            node_id = frontier.pop(0)
            edges = incoming[node_id]
            if edges:
                formula = edges[0].formula_id
                operands = {
                    edge.operand_role: (values[edge.source_id], edge.coefficient)
                    for edge in edges
                }
                value = _calculate_formula(formula, operands)
                if value != node_by_id[node_id].quantity.normalized_value:
                    raise ForecastInvariantError(
                        "FORECAST_REPLAY_MISMATCH",
                        f"Graph replay does not reproduce {node_id}.",
                    )
                values[node_id] = value
            else:
                values[node_id] = node_by_id[node_id].quantity.normalized_value
            for target_id in adjacency[node_id]:
                indegree[target_id] -= 1
                if indegree[target_id] == 0:
                    frontier.append(target_id)
                    frontier.sort()
        return values

    def node(self, node_id: str) -> ForecastNode:
        matches = [node for node in self.nodes if node.node_id == node_id]
        if len(matches) != 1:
            raise KeyError(node_id)
        return matches[0]

    def quantity(self, node_id: str) -> ForecastQuantity:
        return self.node(node_id).quantity

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "security_id": self.security_id,
            "data_snapshot_id": self.data_snapshot_id,
            "template_id": self.template_id,
            "routing_explanation": self.routing_explanation,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "kind": node.kind.value,
                    "origin": node.origin.value,
                    "label": node.label,
                    "quantity": node.quantity.to_dict(),
                    "horizon": node.horizon,
                    "milestone": node.milestone,
                    "leading_indicators": [
                        {
                            "metric_id": indicator.metric_id,
                            "expected_direction": indicator.expected_direction,
                            "unit": indicator.unit,
                            "scale": _decimal_text(indicator.scale),
                            "currency": indicator.currency,
                            "period": indicator.period,
                        }
                        for indicator in node.leading_indicators
                    ],
                    "trigger_conditions": [
                        {
                            "metric_id": condition.metric_id,
                            "operator": condition.operator.value,
                            "threshold": condition.threshold.to_dict(),
                        }
                        for condition in node.trigger_conditions
                    ],
                    "invalidation_conditions": [
                        {
                            "metric_id": condition.metric_id,
                            "operator": condition.operator.value,
                            "threshold": condition.threshold.to_dict(),
                        }
                        for condition in node.invalidation_conditions
                    ],
                    "review_date": node.review_date,
                    "conditional_probability": _decimal_text(
                        node.conditional_probability
                    ),
                    "lineage_refs": list(node.lineage_refs),
                }
                for node in self.nodes
            ],
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass(frozen=True)
class _SegmentState:
    nodes: dict[str, ForecastNode]


@dataclass(frozen=True)
class _CompanyState:
    cash: ForecastNode
    net_ppe: ForecastNode
    debt: ForecastNode
    other_assets: ForecastNode
    other_liabilities: ForecastNode
    equity: ForecastNode
    working_capital: ForecastNode


class ForecastEngine:
    """Build a deterministic, replayable event-driver-three-statement graph."""

    TEMPLATE_ID = "manufacturing_driver_graph@2"

    def build(self, request: ForecastRequest) -> ForecastGraph:
        if (
            request.security.archetype
            == CompanyArchetype.FINANCIAL_INSTITUTION
        ):
            return self._build_financial_institution_shell(request)
        if request.security.archetype not in {
            CompanyArchetype.GENERAL_MANUFACTURING,
            CompanyArchetype.MULTI_SEGMENT_MANUFACTURING,
            CompanyArchetype.CYCLICAL_RESOURCE,
        }:
            raise ForecastInvariantError(
                "FORECAST_TEMPLATE_UNSUPPORTED",
                f"No Forecast template is registered for {request.security.archetype.value}.",
            )
        baselines = {
            baseline.segment_id: baseline
            for baseline in request.data_snapshot.segment_baselines
        }
        if set(baselines) != set(request.security.segment_ids):
            raise ForecastInvariantError(
                "FORECAST_SEGMENT_MISMATCH",
                "Security segments must match DataSnapshot baselines.",
            )
        self._validate_baselines(request, baselines)
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

        nodes: list[ForecastNode] = []
        edges: list[ForecastEdge] = []
        states: dict[str, _SegmentState] = {}
        baseline_nodes: dict[str, dict[str, ForecastNode]] = {}
        for segment_id in request.security.segment_ids:
            current: dict[str, ForecastNode] = {}
            for metric, quantity in baselines[segment_id].named_quantities():
                node = self._input_node(
                    request,
                    node_id=f"baseline.{segment_id}.{metric}.{quantity.period}",
                    label=f"{segment_id} frozen {metric.replace('_', ' ')}",
                    quantity=quantity,
                )
                current[metric] = node
                nodes.append(node)
            baseline_nodes[segment_id] = current
            states[segment_id] = _SegmentState(nodes=current)

        company_state, company_baseline_nodes, company_baseline_edges = (
            self._company_baseline(request)
        )
        nodes.extend(company_baseline_nodes)
        edges.extend(company_baseline_edges)

        with valuation_decimal_context():
            for period in request.forecast_periods:
                period_nodes: dict[str, dict[str, ForecastNode]] = {}
                for segment_id in request.security.segment_ids:
                    override = overrides.get(
                        (segment_id, period),
                        SegmentForecastOverride(segment_id=segment_id, period=period),
                    )
                    built, built_edges, next_state = self._build_segment_period(
                        request,
                        states[segment_id],
                        override,
                        period,
                    )
                    nodes.extend(built.values())
                    edges.extend(built_edges)
                    states[segment_id] = next_state
                    period_nodes[segment_id] = built
                company_built, company_edges, company_state = self._company_period(
                    request,
                    period,
                    period_nodes,
                    company_state,
                )
                nodes.extend(company_built.values())
                edges.extend(company_edges)

        template_id = (
            "cyclical_resource_driver_graph@1"
            if request.security.archetype == CompanyArchetype.CYCLICAL_RESOURCE
            else self.TEMPLATE_ID
        )
        identity_payload = {
            "template_id": template_id,
            "security_id": request.security.security_id,
            "snapshot_id": request.data_snapshot.snapshot_id,
            "snapshot_hash": request.data_snapshot.content_hash,
            "periods": list(request.forecast_periods),
            "review_date": request.review_date,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "quantity": node.quantity.to_dict(),
                    "probability": _decimal_text(node.conditional_probability),
                }
                for node in nodes
            ],
            "edges": [edge.to_dict() for edge in edges],
        }
        identity = hashlib.sha256(
            json.dumps(
                identity_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        archetype_label = request.security.archetype.value.replace(
            "multi_segment", "multi-segment"
        ).replace("_", " ")
        if request.security.archetype == CompanyArchetype.CYCLICAL_RESOURCE:
            routing_explanation = (
                "Routed cyclical/resource economics through explicit volume, utilization, "
                "price, unit-cost, tax, and maintenance-capex drivers. Ordinary stable-growth "
                "valuation is disabled downstream; finite-life NAV and mid-cycle methods are required."
            )
        else:
            routing_explanation = (
                f"Routed {archetype_label} through a typed demand, capacity, cost, "
                "three-statement, FCFF manufacturing graph with consolidated tax."
            )
        return ForecastGraph(
            graph_id=f"fg_{identity[:24]}",
            security_id=request.security.security_id,
            data_snapshot_id=request.data_snapshot.snapshot_id,
            template_id=template_id,
            routing_explanation=routing_explanation,
            nodes=tuple(nodes),
            edges=tuple(edges),
        )

    def _build_financial_institution_shell(
        self,
        request: ForecastRequest,
    ) -> ForecastGraph:
        override_payload = [
            item.to_dict() for item in request.assumption_overrides
        ]
        override_hash = hashlib.sha256(
            json.dumps(
                override_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        first_period = request.forecast_periods[0]
        first = self._input_node(
            request,
            node_id=f"financial.horizon.{first_period}",
            label=f"financial institution forecast horizon {first_period}",
            quantity=self._quantity(
                Decimal("1"),
                unit="count",
                currency="N/A",
                period=first_period,
                as_of=request.as_of,
                lineage_refs=(
                    f"Assumption:financial_institution_horizon:{first_period}",
                    f"Assumption:financial_scenario_overrides:{override_hash}",
                ),
            ),
        )
        built_nodes = [first]
        built_edges: list[ForecastEdge] = []
        previous = first
        for period in request.forecast_periods[1:]:
            node, node_edges = self._derived_node(
                request,
                node_id=f"financial.horizon.{period}",
                kind=ForecastNodeKind.DRIVER,
                label=f"financial institution forecast horizon {period}",
                period=period,
                unit="count",
                currency="N/A",
                formula=FormulaId.PASSTHROUGH,
                operands=(("value", previous, Decimal("1")),),
                probability=Decimal("1"),
            )
            built_nodes.append(node)
            built_edges.extend(node_edges)
            previous = node
        nodes = tuple(built_nodes)
        edges = tuple(built_edges)
        identity_payload = {
            "template_id": "financial_institution_valuation_shell@1",
            "security_id": request.security.security_id,
            "snapshot_id": request.data_snapshot.snapshot_id,
            "snapshot_hash": request.data_snapshot.content_hash,
            "periods": list(request.forecast_periods),
            "review_date": request.review_date,
            "assumption_overrides": override_payload,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "quantity": node.quantity.to_dict(),
                }
                for node in nodes
            ],
            "edges": [edge.to_dict() for edge in edges],
        }
        identity = hashlib.sha256(
            json.dumps(
                identity_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return ForecastGraph(
            graph_id=f"fg_{identity[:24]}",
            security_id=request.security.security_id,
            data_snapshot_id=request.data_snapshot.snapshot_id,
            template_id="financial_institution_valuation_shell@1",
            routing_explanation=(
                "Routed financial-institution economics to a dedicated regulatory-capital, "
                "clean-surplus, dividend, and residual-income valuation shell. Industrial "
                "FCFF/WACC and manufacturing operating templates are disabled."
            ),
            nodes=nodes,
            edges=edges,
        )

    @staticmethod
    def _validate_baselines(
        request: ForecastRequest,
        baselines: dict[str, SegmentBaseline],
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

    @staticmethod
    def _quantity(
        value: Decimal,
        *,
        unit: str,
        currency: str,
        period: str,
        as_of: str,
        lineage_refs: tuple[str, ...],
        scale: Decimal = Decimal("1"),
    ) -> ForecastQuantity:
        return ForecastQuantity(
            value=value,
            unit=unit,
            scale=scale,
            currency=currency,
            period=period,
            as_of=as_of,
            lineage_refs=lineage_refs,
        )

    def _monitoring(
        self,
        *,
        node_id: str,
        quantity: ForecastQuantity,
        leading: ForecastNode | None,
    ) -> tuple[
        tuple[LeadingIndicator, ...],
        tuple[ForecastCondition, ...],
        tuple[ForecastCondition, ...],
    ]:
        leading_quantity = leading.quantity if leading is not None else quantity
        leading_id = leading.node_id if leading is not None else node_id
        with valuation_decimal_context():
            minimum = Decimal("0.000001")
            trigger_tolerance = max(
                abs(quantity.normalized_value) * Decimal("0.10"), minimum
            )
            invalidation_tolerance = max(
                abs(quantity.normalized_value) * Decimal("0.20"), minimum
            )

        def threshold(value: Decimal, suffix: str) -> ForecastQuantity:
            with valuation_decimal_context():
                return self._quantity(
                    value / quantity.scale,
                    unit=quantity.unit,
                    currency=quantity.currency,
                    period=quantity.period,
                    as_of=quantity.as_of,
                    lineage_refs=(f"Assumption:monitoring:{node_id}:{suffix}",),
                    scale=quantity.scale,
                )

        return (
            (
                LeadingIndicator(
                    metric_id=leading_id,
                    expected_direction="track_expected_path",
                    unit=leading_quantity.unit,
                    scale=leading_quantity.scale,
                    currency=leading_quantity.currency,
                    period=leading_quantity.period,
                ),
            ),
            (
                ForecastCondition(
                    metric_id=node_id,
                    operator=ConditionOperator.ACTUAL_WITHIN,
                    threshold=threshold(trigger_tolerance, "trigger_tolerance"),
                ),
            ),
            (
                ForecastCondition(
                    metric_id=node_id,
                    operator=ConditionOperator.ACTUAL_OUTSIDE,
                    threshold=threshold(
                        invalidation_tolerance,
                        "invalidation_tolerance",
                    ),
                ),
            ),
        )

    def _input_node(
        self,
        request: ForecastRequest,
        *,
        node_id: str,
        label: str,
        quantity: ForecastQuantity,
        probability: Decimal = Decimal("1"),
    ) -> ForecastNode:
        indicators, triggers, invalidations = self._monitoring(
            node_id=node_id,
            quantity=quantity,
            leading=None,
        )
        return ForecastNode(
            node_id=node_id,
            kind=ForecastNodeKind.DRIVER,
            origin=NodeOrigin.INPUT,
            label=label,
            quantity=quantity,
            horizon=quantity.period,
            milestone=f"Observe {label} by {request.review_date}",
            leading_indicators=indicators,
            trigger_conditions=triggers,
            invalidation_conditions=invalidations,
            review_date=request.review_date,
            conditional_probability=probability,
            lineage_refs=quantity.lineage_refs,
        )

    def _derived_node(
        self,
        request: ForecastRequest,
        *,
        node_id: str,
        kind: ForecastNodeKind,
        label: str,
        period: str,
        unit: str,
        currency: str,
        formula: FormulaId,
        operands: tuple[tuple[str, ForecastNode, Decimal], ...],
        probability: Decimal,
    ) -> tuple[ForecastNode, list[ForecastEdge]]:
        operand_values = {
            role: (source.quantity.normalized_value, coefficient)
            for role, source, coefficient in operands
        }
        value = _calculate_formula(formula, operand_values)
        lineage = _merge_lineage(*(source.lineage_refs for _, source, _ in operands))
        quantity = self._quantity(
            value,
            unit=unit,
            currency=currency,
            period=period,
            as_of=request.as_of,
            lineage_refs=lineage,
        )
        leading = operands[0][1]
        indicators, triggers, invalidations = self._monitoring(
            node_id=node_id,
            quantity=quantity,
            leading=leading,
        )
        node = ForecastNode(
            node_id=node_id,
            kind=kind,
            origin=NodeOrigin.DERIVED,
            label=label,
            quantity=quantity,
            horizon=period,
            milestone=f"Validate {label} by {request.review_date}",
            leading_indicators=indicators,
            trigger_conditions=triggers,
            invalidation_conditions=invalidations,
            review_date=request.review_date,
            conditional_probability=probability,
            lineage_refs=lineage,
        )
        edges = [
            ForecastEdge(
                source_id=source.node_id,
                target_id=node.node_id,
                formula_id=formula,
                operand_role=role,
                coefficient=coefficient,
                source_unit=source.quantity.unit,
                source_scale=source.quantity.scale,
                target_unit=node.quantity.unit,
                target_scale=node.quantity.scale,
                period_rule=(
                    "prior"
                    if period_rank(source.quantity.period) < period_rank(period)
                    else "same"
                ),
                currency_rule=(
                    "same"
                    if source.quantity.currency == node.quantity.currency
                    else (
                        "target"
                        if source.quantity.currency in {"", "N/A"}
                        else "not_applicable"
                    )
                ),
            )
            for role, source, coefficient in operands
        ]
        return node, edges

    def _company_baseline(
        self,
        request: ForecastRequest,
    ) -> tuple[_CompanyState, list[ForecastNode], list[ForecastEdge]]:
        opening = request.data_snapshot.company_opening_balance_sheet
        built: dict[str, ForecastNode] = {}
        for metric, quantity in opening.named_quantities():
            node = self._input_node(
                request,
                node_id=f"company.baseline.{metric}.{quantity.period}",
                label=f"company frozen {metric.replace('_', ' ')}",
                quantity=quantity,
            )
            built[metric] = node
        state = _CompanyState(
            cash=built["cash"],
            net_ppe=built["net_ppe"],
            debt=built["debt"],
            other_assets=built["other_assets"],
            other_liabilities=built["other_liabilities"],
            equity=built["equity"],
            working_capital=built["working_capital"],
        )
        return state, list(built.values()), []

    def _assumption_node(
        self,
        request: ForecastRequest,
        override: SegmentForecastOverride,
        *,
        field_name: str,
        default: Decimal,
        unit: str = "decimal",
        currency: str = "N/A",
        default_lineage: tuple[str, ...] = (),
    ) -> ForecastNode:
        supplied = getattr(override, field_name)
        value = default if supplied is None else supplied
        origin = "default" if supplied is None else "override"
        lineage = _merge_lineage(
            default_lineage,
            (
                f"Assumption:{origin}:{override.segment_id}:{override.period}:{field_name}",
            ),
        )
        quantity = self._quantity(
            value,
            unit=unit,
            currency=currency,
            period=override.period,
            as_of=request.as_of,
            lineage_refs=lineage,
        )
        return self._input_node(
            request,
            node_id=f"assumption.{override.segment_id}.{field_name}.{override.period}",
            label=f"{override.segment_id} {field_name.replace('_', ' ')} assumption",
            quantity=quantity,
            probability=Decimal("1"),
        )

    def _build_segment_period(
        self,
        request: ForecastRequest,
        state: _SegmentState,
        override: SegmentForecastOverride,
        period: str,
    ) -> tuple[dict[str, ForecastNode], list[ForecastEdge], _SegmentState]:
        prior = state.nodes
        currency = request.security.reporting_currency
        prior_revenue = (
            prior["volume"].quantity.normalized_value
            * prior["asp"].quantity.normalized_value
        )
        default_wc_ratio = (
            prior["working_capital"].quantity.normalized_value / prior_revenue
            if prior_revenue
            else Decimal("0")
        )
        assumptions = {
            "demand_growth": self._assumption_node(
                request, override, field_name="demand_growth", default=Decimal("0")
            ),
            "asp_growth": self._assumption_node(
                request, override, field_name="asp_growth", default=Decimal("0")
            ),
            "capacity_growth": self._assumption_node(
                request, override, field_name="capacity_growth", default=Decimal("0")
            ),
            "target_utilization": self._assumption_node(
                request,
                override,
                field_name="target_utilization",
                default=prior["utilization"].quantity.normalized_value,
                default_lineage=prior["utilization"].lineage_refs,
            ),
            "unit_cost_growth": self._assumption_node(
                request, override, field_name="unit_cost_growth", default=Decimal("0")
            ),
            "operating_expense_growth": self._assumption_node(
                request,
                override,
                field_name="operating_expense_growth",
                default=Decimal("0"),
            ),
            "capex_growth": self._assumption_node(
                request, override, field_name="capex_growth", default=Decimal("0")
            ),
            "depreciation_growth": self._assumption_node(
                request,
                override,
                field_name="depreciation_growth",
                default=Decimal("0"),
            ),
            "working_capital_to_revenue": self._assumption_node(
                request,
                override,
                field_name="working_capital_to_revenue",
                default=default_wc_ratio,
                default_lineage=_merge_lineage(
                    prior["working_capital"].lineage_refs,
                    prior["volume"].lineage_refs,
                    prior["asp"].lineage_refs,
                ),
            ),
            "tax_rate": self._assumption_node(
                request,
                override,
                field_name="tax_rate",
                default=prior["tax_rate"].quantity.normalized_value,
                default_lineage=prior["tax_rate"].lineage_refs,
            ),
            "debt_change": self._assumption_node(
                request,
                override,
                field_name="debt_change",
                default=Decimal("0"),
                unit=currency,
                currency=currency,
            ),
            "event_probability": self._assumption_node(
                request,
                override,
                field_name="event_probability",
                default=Decimal("1"),
            ),
        }
        probability = assumptions["event_probability"].quantity.normalized_value
        built: dict[str, ForecastNode] = {
            f"assumption_{name}": node for name, node in assumptions.items()
        }
        edges: list[ForecastEdge] = []

        def derive(
            metric: str,
            kind: ForecastNodeKind,
            unit: str,
            out_currency: str,
            formula: FormulaId,
            operands: tuple[tuple[str, ForecastNode, Decimal], ...],
        ) -> ForecastNode:
            node, node_edges = self._derived_node(
                request,
                node_id=f"{override.segment_id}.{metric}.{period}",
                kind=kind,
                label=f"{override.segment_id} {metric.replace('_', ' ')}",
                period=period,
                unit=unit,
                currency=out_currency,
                formula=formula,
                operands=operands,
                probability=probability,
            )
            built[metric] = node
            edges.extend(node_edges)
            return node

        demand = derive(
            "demand_event",
            ForecastNodeKind.EVENT,
            "units",
            "N/A",
            FormulaId.GROWTH,
            (
                ("base", prior["volume"], Decimal("1")),
                ("rate", assumptions["demand_growth"], Decimal("1")),
            ),
        )
        capacity = derive(
            "capacity",
            ForecastNodeKind.DRIVER,
            "units",
            "N/A",
            FormulaId.GROWTH,
            (
                ("base", prior["capacity"], Decimal("1")),
                ("rate", assumptions["capacity_growth"], Decimal("1")),
            ),
        )
        utilization = derive(
            "utilization",
            ForecastNodeKind.DRIVER,
            "decimal",
            "N/A",
            FormulaId.PASSTHROUGH,
            (("value", assumptions["target_utilization"], Decimal("1")),),
        )
        available = derive(
            "capacity_available",
            ForecastNodeKind.DRIVER,
            "units",
            "N/A",
            FormulaId.PRODUCT,
            (("left", capacity, Decimal("1")), ("right", utilization, Decimal("1"))),
        )
        volume = derive(
            "volume",
            ForecastNodeKind.DRIVER,
            "units",
            "N/A",
            FormulaId.MINIMUM,
            (
                ("demand", demand, Decimal("1")),
                ("capacity_available", available, Decimal("1")),
            ),
        )
        asp = derive(
            "asp",
            ForecastNodeKind.DRIVER,
            f"{currency}/unit",
            currency,
            FormulaId.GROWTH,
            (
                ("base", prior["asp"], Decimal("1")),
                ("rate", assumptions["asp_growth"], Decimal("1")),
            ),
        )
        unit_cost = derive(
            "unit_cost",
            ForecastNodeKind.DRIVER,
            f"{currency}/unit",
            currency,
            FormulaId.GROWTH,
            (
                ("base", prior["unit_cost"], Decimal("1")),
                ("rate", assumptions["unit_cost_growth"], Decimal("1")),
            ),
        )
        operating_expense = derive(
            "operating_expense",
            ForecastNodeKind.DRIVER,
            currency,
            currency,
            FormulaId.GROWTH,
            (
                ("base", prior["operating_expense"], Decimal("1")),
                ("rate", assumptions["operating_expense_growth"], Decimal("1")),
            ),
        )
        capex = derive(
            "capex",
            ForecastNodeKind.DRIVER,
            currency,
            currency,
            FormulaId.GROWTH,
            (
                ("base", prior["capex"], Decimal("1")),
                ("rate", assumptions["capex_growth"], Decimal("1")),
            ),
        )
        depreciation = derive(
            "depreciation",
            ForecastNodeKind.DRIVER,
            currency,
            currency,
            FormulaId.GROWTH,
            (
                ("base", prior["depreciation"], Decimal("1")),
                ("rate", assumptions["depreciation_growth"], Decimal("1")),
            ),
        )
        wc_ratio = derive(
            "working_capital_ratio",
            ForecastNodeKind.DRIVER,
            "decimal",
            "N/A",
            FormulaId.PASSTHROUGH,
            (("value", assumptions["working_capital_to_revenue"], Decimal("1")),),
        )
        tax_rate = derive(
            "tax_rate",
            ForecastNodeKind.DRIVER,
            "decimal",
            "N/A",
            FormulaId.PASSTHROUGH,
            (("value", assumptions["tax_rate"], Decimal("1")),),
        )
        debt_change = derive(
            "debt_change",
            ForecastNodeKind.DRIVER,
            currency,
            currency,
            FormulaId.PASSTHROUGH,
            (("value", assumptions["debt_change"], Decimal("1")),),
        )
        revenue = derive(
            "revenue",
            ForecastNodeKind.FINANCIAL_FORECAST,
            currency,
            currency,
            FormulaId.PRODUCT,
            (("left", volume, Decimal("1")), ("right", asp, Decimal("1"))),
        )
        cogs = derive(
            "cogs",
            ForecastNodeKind.FINANCIAL_FORECAST,
            currency,
            currency,
            FormulaId.PRODUCT,
            (("left", volume, Decimal("1")), ("right", unit_cost, Decimal("1"))),
        )
        gross_profit = derive(
            "gross_profit",
            ForecastNodeKind.FINANCIAL_FORECAST,
            currency,
            currency,
            FormulaId.SUM,
            (("revenue", revenue, Decimal("1")), ("cogs", cogs, Decimal("-1"))),
        )
        derive(
            "gross_margin",
            ForecastNodeKind.FINANCIAL_FORECAST,
            "decimal",
            "N/A",
            FormulaId.RATIO,
            (
                ("numerator", gross_profit, Decimal("1")),
                ("denominator", revenue, Decimal("1")),
            ),
        )
        derive(
            "ebit",
            ForecastNodeKind.FINANCIAL_FORECAST,
            currency,
            currency,
            FormulaId.SUM,
            (
                ("gross_profit", gross_profit, Decimal("1")),
                ("operating_expense", operating_expense, Decimal("-1")),
                ("depreciation", depreciation, Decimal("-1")),
            ),
        )
        working_capital = derive(
            "working_capital",
            ForecastNodeKind.FINANCIAL_FORECAST,
            currency,
            currency,
            FormulaId.PRODUCT,
            (("left", revenue, Decimal("1")), ("right", wc_ratio, Decimal("1"))),
        )
        next_state = _SegmentState(
            nodes={
                "volume": volume,
                "asp": asp,
                "capacity": capacity,
                "utilization": utilization,
                "unit_cost": unit_cost,
                "operating_expense": operating_expense,
                "capex": capex,
                "working_capital": working_capital,
                "depreciation": depreciation,
                "tax_rate": tax_rate,
                "debt_change": debt_change,
            }
        )
        return built, edges, next_state

    def _company_period(
        self,
        request: ForecastRequest,
        period: str,
        segment_nodes: dict[str, dict[str, ForecastNode]],
        prior: _CompanyState,
    ) -> tuple[dict[str, ForecastNode], list[ForecastEdge], _CompanyState]:
        currency = request.security.reporting_currency
        probability = min(
            segment_nodes[segment_id][
                "assumption_event_probability"
            ].quantity.normalized_value
            for segment_id in request.security.segment_ids
        )
        built: dict[str, ForecastNode] = {}
        edges: list[ForecastEdge] = []

        def derive(
            metric: str,
            formula: FormulaId,
            operands: tuple[tuple[str, ForecastNode, Decimal], ...],
            *,
            kind: ForecastNodeKind = ForecastNodeKind.FINANCIAL_FORECAST,
            unit: str = currency,
            out_currency: str = currency,
            prefix: str = "company",
        ) -> ForecastNode:
            node, node_edges = self._derived_node(
                request,
                node_id=f"{prefix}.{metric}.{period}",
                kind=kind,
                label=f"{prefix} {metric.replace('_', ' ')}",
                period=period,
                unit=unit,
                currency=out_currency,
                formula=formula,
                operands=operands,
                probability=probability,
            )
            built[metric if prefix == "company" else f"{prefix}_{metric}"] = node
            edges.extend(node_edges)
            return node

        aggregate_metrics = (
            "revenue",
            "cogs",
            "gross_profit",
            "operating_expense",
            "depreciation",
            "ebit",
            "working_capital",
            "capex",
            "debt_change",
        )
        for metric in aggregate_metrics:
            derive(
                metric,
                FormulaId.SUM,
                tuple(
                    (
                        f"segment_{segment_id}",
                        segment_nodes[segment_id][metric],
                        Decimal("1"),
                    )
                    for segment_id in request.security.segment_ids
                ),
            )
        gross_margin = derive(
            "gross_margin",
            FormulaId.RATIO,
            (
                ("numerator", built["gross_profit"], Decimal("1")),
                ("denominator", built["revenue"], Decimal("1")),
            ),
            unit="decimal",
            out_currency="N/A",
        )
        del gross_margin
        tax_rates = [
            segment_nodes[segment_id]["tax_rate"]
            for segment_id in request.security.segment_ids
        ]
        if len({node.quantity.normalized_value for node in tax_rates}) != 1:
            raise ForecastInvariantError(
                "FORECAST_TAX_ENTITY_REQUIRED",
                "Different segment tax rates require an explicit tax-entity and loss-offset model.",
            )
        tax_rate = derive(
            "tax_rate",
            FormulaId.CONSENSUS,
            tuple(
                (
                    f"segment_{segment_id}",
                    segment_nodes[segment_id]["tax_rate"],
                    Decimal("1"),
                )
                for segment_id in request.security.segment_ids
            ),
            unit="decimal",
            out_currency="N/A",
        )
        change_wc = derive(
            "change_working_capital",
            FormulaId.SUM,
            (
                ("current", built["working_capital"], Decimal("1")),
                ("prior", prior.working_capital, Decimal("-1")),
            ),
        )
        tax = derive(
            "tax",
            FormulaId.POSITIVE_TAX,
            (
                ("taxable_income", built["ebit"], Decimal("1")),
                ("rate", tax_rate, Decimal("1")),
            ),
        )
        nopat = derive(
            "nopat",
            FormulaId.SUM,
            (("ebit", built["ebit"], Decimal("1")), ("tax", tax, Decimal("-1"))),
        )
        cfo = derive(
            "cash_flow_from_operations",
            FormulaId.SUM,
            (
                ("nopat", nopat, Decimal("1")),
                ("depreciation", built["depreciation"], Decimal("1")),
                ("change_working_capital", change_wc, Decimal("-1")),
            ),
        )
        cfi = derive(
            "cash_flow_from_investing",
            FormulaId.SUM,
            (("capex", built["capex"], Decimal("-1")),),
        )
        distributions = self._input_node(
            request,
            node_id=f"assumption.company.distributions.{period}",
            label="company distributions assumption",
            quantity=self._quantity(
                Decimal("0"),
                unit=currency,
                currency=currency,
                period=period,
                as_of=request.as_of,
                lineage_refs=(f"Assumption:default:company:{period}:distributions",),
            ),
        )
        built["assumption_distributions"] = distributions
        cff = derive(
            "cash_flow_from_financing",
            FormulaId.SUM,
            (
                ("debt_change", built["debt_change"], Decimal("1")),
                ("distributions", distributions, Decimal("-1")),
            ),
        )
        net_cash_change = derive(
            "net_cash_change",
            FormulaId.SUM,
            (
                ("cfo", cfo, Decimal("1")),
                ("cfi", cfi, Decimal("1")),
                ("cff", cff, Decimal("1")),
            ),
        )
        ending_cash = derive(
            "ending_cash",
            FormulaId.SUM,
            (
                ("beginning_cash", prior.cash, Decimal("1")),
                ("net_cash_change", net_cash_change, Decimal("1")),
            ),
        )
        cash_flow_check = derive(
            "cash_flow_reconciliation",
            FormulaId.SUM,
            (
                ("ending_cash", ending_cash, Decimal("1")),
                ("beginning_cash", prior.cash, Decimal("-1")),
                ("net_cash_change", net_cash_change, Decimal("-1")),
            ),
        )
        fcff = derive(
            "fcff",
            FormulaId.SUM,
            (("cfo", cfo, Decimal("1")), ("capex", built["capex"], Decimal("-1"))),
        )
        net_ppe = derive(
            "net_ppe",
            FormulaId.SUM,
            (
                ("prior_net_ppe", prior.net_ppe, Decimal("1")),
                ("capex", built["capex"], Decimal("1")),
                ("depreciation", built["depreciation"], Decimal("-1")),
            ),
        )
        other_assets_growth = self._input_node(
            request,
            node_id=f"assumption.company.other_assets_growth.{period}",
            label="company other assets growth assumption",
            quantity=self._quantity(
                Decimal("0"),
                unit="decimal",
                currency="N/A",
                period=period,
                as_of=request.as_of,
                lineage_refs=(
                    f"Assumption:default:company:{period}:other_assets_growth",
                ),
            ),
        )
        built["assumption_other_assets_growth"] = other_assets_growth
        other_assets = derive(
            "other_assets",
            FormulaId.GROWTH,
            (
                ("base", prior.other_assets, Decimal("1")),
                ("rate", other_assets_growth, Decimal("1")),
            ),
        )
        other_liabilities_growth = self._input_node(
            request,
            node_id=f"assumption.company.other_liabilities_growth.{period}",
            label="company other liabilities growth assumption",
            quantity=self._quantity(
                Decimal("0"),
                unit="decimal",
                currency="N/A",
                period=period,
                as_of=request.as_of,
                lineage_refs=(
                    f"Assumption:default:company:{period}:other_liabilities_growth",
                ),
            ),
        )
        built["assumption_other_liabilities_growth"] = other_liabilities_growth
        other_liabilities = derive(
            "other_liabilities",
            FormulaId.GROWTH,
            (
                ("base", prior.other_liabilities, Decimal("1")),
                ("rate", other_liabilities_growth, Decimal("1")),
            ),
        )
        debt = derive(
            "debt",
            FormulaId.SUM,
            (
                ("prior_debt", prior.debt, Decimal("1")),
                ("debt_change", built["debt_change"], Decimal("1")),
            ),
        )
        assets = derive(
            "assets",
            FormulaId.SUM,
            (
                ("cash", ending_cash, Decimal("1")),
                ("working_capital", built["working_capital"], Decimal("1")),
                ("net_ppe", net_ppe, Decimal("1")),
                ("other_assets", other_assets, Decimal("1")),
            ),
        )
        equity = derive(
            "equity",
            FormulaId.SUM,
            (
                ("prior_equity", prior.equity, Decimal("1")),
                ("nopat", nopat, Decimal("1")),
                ("distributions", distributions, Decimal("-1")),
            ),
        )
        liabilities_and_equity = derive(
            "liabilities_and_equity",
            FormulaId.SUM,
            (
                ("debt", debt, Decimal("1")),
                ("other_liabilities", other_liabilities, Decimal("1")),
                ("equity", equity, Decimal("1")),
            ),
        )
        balance_check = derive(
            "balance_sheet_reconciliation",
            FormulaId.SUM,
            (
                ("assets", assets, Decimal("1")),
                ("liabilities_and_equity", liabilities_and_equity, Decimal("-1")),
            ),
        )
        derive(
            "fcff",
            FormulaId.VALUATION_GATE,
            (
                ("value", fcff, Decimal("1")),
                ("balance_sheet_check", balance_check, Decimal("1")),
                ("cash_flow_check", cash_flow_check, Decimal("1")),
                ("cash", ending_cash, Decimal("1")),
                ("debt", debt, Decimal("1")),
                ("net_ppe", net_ppe, Decimal("1")),
            ),
            kind=ForecastNodeKind.VALUATION_INPUT,
            prefix="valuation",
        )
        next_state = _CompanyState(
            cash=ending_cash,
            net_ppe=net_ppe,
            debt=debt,
            other_assets=other_assets,
            other_liabilities=other_liabilities,
            equity=equity,
            working_capital=built["working_capital"],
        )
        return built, edges, next_state
