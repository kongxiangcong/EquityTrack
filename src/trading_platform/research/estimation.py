from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


@dataclass(frozen=True)
class _Observation:
    field_name: str
    period: str
    period_date: date
    value: Decimal
    unit: str
    currency: str
    source_id: str


@dataclass(frozen=True)
class FrozenSnapshotEstimator:
    """Build conservative, labeled estimates from frozen sourced facts only."""

    IDENTITY = "FrozenSnapshotEstimator@1"
    RANGE_POLICY = "RelativeUncertaintyBand20Percent@1"
    _BALANCE_FIELDS = frozenset(
        {
            "lease_debt",
            "diluted_shares",
            "working_capital",
        }
    )
    _FLOW_FIELDS = frozenset(
        {
            "capex",
            "cfo",
            "d_and_a",
            "ebit",
            "tax",
            "fcf",
        }
    )
    _MAX_AGE_DAYS = 550

    def build(
        self,
        manifest: Mapping[str, object],
        *,
        as_of_date: str,
    ) -> Mapping[str, object] | None:
        company = manifest.get("company")
        if not isinstance(company, Mapping):
            return None
        target_period = str(company.get("latest_financial_period", "")).strip()
        target_date = _period_date(target_period)
        if target_date is None:
            return None

        observations = self._observations(manifest)
        estimates: list[Mapping[str, object]] = []
        for field_name in sorted(self._BALANCE_FIELDS | self._FLOW_FIELDS):
            field_observations = tuple(
                item for item in observations if item.field_name == field_name
            )
            if any(item.period_date == target_date for item in field_observations):
                continue
            basis = self._basis(field_name, field_observations, target_date)
            if basis is None:
                continue
            spread = abs(basis.value) * Decimal("0.20")
            estimates.append(
                {
                    "field_name": field_name,
                    "period": target_period,
                    "estimate_value": _decimal_text(basis.value),
                    "unit": basis.unit,
                    "currency": basis.currency,
                    "estimate_method": (
                        "latest_balance_carry_forward@1"
                        if field_name in self._BALANCE_FIELDS
                        else "same_period_prior_year_carry_forward@1"
                    ),
                    "basis_sources": [basis.source_id],
                    "basis_period": basis.period,
                    "lower_bound": _decimal_text(basis.value - spread),
                    "upper_bound": _decimal_text(basis.value + spread),
                    "policy": self.IDENTITY,
                    "range_policy": self.RANGE_POLICY,
                    "calibration_window": {
                        "basis_period": basis.period,
                        "target_period": target_period,
                        "maximum_basis_age_days": self._MAX_AGE_DAYS,
                    },
                    "rationale": (
                        "No sourced target-period value exists; carry forward "
                        "the nearest comparable sourced observation with an "
                        "explicit uncertainty band."
                    ),
                    "invalidation_condition": (
                        "Invalidate when a sourced target-period value becomes "
                        "available, the basis is restated, or the basis age "
                        f"exceeds {self._MAX_AGE_DAYS} days."
                    ),
                    "confidence": "low",
                    "formal_gate_coverage": False,
                }
            )
        if not estimates:
            return None
        return {
            "company": str(company.get("name", "")).strip(),
            "ticker": str(company.get("ticker", "")).strip(),
            "as_of_date": as_of_date,
            "policy": self.IDENTITY,
            "estimates": estimates,
        }

    @classmethod
    def _observations(
        cls,
        manifest: Mapping[str, object],
    ) -> tuple[_Observation, ...]:
        sources = manifest.get("sources")
        if not isinstance(sources, list):
            return ()
        observations: list[_Observation] = []
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            if str(source.get("tier", "")).strip() in {"estimate", "missing"}:
                continue
            source_id = str(source.get("source_id", "")).strip()
            fields = source.get("extracted_fields")
            if not source_id or not isinstance(fields, list):
                continue
            for field in fields:
                if not isinstance(field, Mapping):
                    continue
                field_name = str(field.get("field_name", "")).strip()
                if field_name not in cls._BALANCE_FIELDS | cls._FLOW_FIELDS:
                    continue
                period = str(field.get("period", "")).strip()
                parsed_period = _period_date(period)
                value = _decimal(field.get("value"))
                unit = str(field.get("unit", "")).strip()
                currency = str(field.get("currency", "")).strip()
                if parsed_period is None or value is None or not unit or not currency:
                    continue
                observations.append(
                    _Observation(
                        field_name,
                        period,
                        parsed_period,
                        value,
                        unit,
                        currency,
                        source_id,
                    )
                )
        return tuple(observations)

    @classmethod
    def _basis(
        cls,
        field_name: str,
        observations: tuple[_Observation, ...],
        target_date: date,
    ) -> _Observation | None:
        candidates = tuple(
            item
            for item in observations
            if item.period_date < target_date
            and (target_date - item.period_date).days <= cls._MAX_AGE_DAYS
        )
        if field_name in cls._FLOW_FIELDS:
            candidates = tuple(
                item
                for item in candidates
                if (item.period_date.month, item.period_date.day)
                == (target_date.month, target_date.day)
            )
        return max(candidates, key=lambda item: item.period_date, default=None)


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _period_date(value: str) -> date | None:
    text = str(value).strip()
    try:
        if len(text) == 8 and text.isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:]))
        if len(text) == 6 and text[4].upper() == "Q" and text[5] in "1234":
            quarter = int(text[5])
            month_day = ((3, 31), (6, 30), (9, 30), (12, 31))[quarter - 1]
            return date(int(text[:4]), *month_day)
        return date.fromisoformat(text)
    except ValueError:
        return None


__all__ = ["FrozenSnapshotEstimator"]
