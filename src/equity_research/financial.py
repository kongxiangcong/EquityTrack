from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from typing import Any, Literal


QuantityKind = Literal["money", "shares", "per_share", "fx"]
ValueBasis = Literal["enterprise_value", "equity_value"]
VALUATION_DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
_DECIMAL_PATTERN = re.compile(
    r"^[+-]?(?:(?:\d+)|(?:\d{1,3}(?:,\d{3})+))(?:\.\d+)?$"
)


class FinancialInvariantError(ValueError):
    """A stable, method-blocking financial calculation diagnostic."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def valuation_decimal_context():
    return localcontext(VALUATION_DECIMAL_CONTEXT)


def exact_decimal_from_legacy(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise FinancialInvariantError(
            "FINANCIAL_VALUE_INVALID",
            f"A strict decimal value is required for {field_name}.",
        )
    if isinstance(value, Decimal):
        number = value
    else:
        text = str(value).strip()
        if not _DECIMAL_PATTERN.fullmatch(text):
            raise FinancialInvariantError(
                "FINANCIAL_VALUE_INVALID",
                f"A strict decimal value is required for {field_name}.",
            )
        try:
            number = Decimal(text.replace(",", ""))
        except InvalidOperation as exc:
            raise FinancialInvariantError(
                "FINANCIAL_VALUE_INVALID",
                f"A strict decimal value is required for {field_name}.",
            ) from exc
    if not number.is_finite():
        raise FinancialInvariantError(
            "FINANCIAL_VALUE_INVALID",
            f"A finite decimal value is required for {field_name}.",
        )
    return number


def _decimal_text(value: Decimal) -> str:
    with valuation_decimal_context():
        if value == 0:
            return "0"
        return format(value.normalize(), "f")


def _expected_unit(kind: QuantityKind, currency: str, scale: Decimal) -> set[str]:
    if kind == "money":
        names = {
            Decimal("1"): {currency, f"{currency} units"},
            Decimal("1000"): {f"{currency} thousand", f"thousand {currency}"},
            Decimal("10000"): {f"{currency} ten-thousand", f"ten-thousand {currency}"},
            Decimal("1000000"): {f"{currency} million", f"million {currency}"},
            Decimal("100000000"): {f"{currency} hundred-million", f"hundred-million {currency}"},
            Decimal("1000000000"): {f"{currency} billion", f"billion {currency}"},
        }
        return names.get(scale, set())
    if kind == "shares":
        names = {
            Decimal("1"): {"share", "shares"},
            Decimal("1000"): {"thousand shares"},
            Decimal("10000"): {"ten-thousand shares", "10k shares", "万股"},
            Decimal("1000000"): {"million shares", "百万股"},
            Decimal("100000000"): {"hundred-million shares", "亿股"},
            Decimal("1000000000"): {"billion shares"},
        }
        return names.get(scale, set())
    if kind == "per_share":
        names = {
            Decimal("1"): {
                f"{currency}/share",
                f"{currency} per share",
            },
        }
        return names.get(scale, set())
    return set()


@dataclass(frozen=True)
class FinancialQuantity:
    """One exact, dimensioned input to a formal valuation calculation."""

    value: Decimal
    unit: str
    scale: Decimal
    currency: str
    period: str
    as_of: str
    provenance_refs: tuple[str, ...]
    kind: QuantityKind

    @classmethod
    def from_legacy(
        cls,
        *,
        value: Any,
        unit: str,
        currency: str,
        period: str,
        as_of: str,
        provenance_refs: tuple[str, ...],
        kind: QuantityKind,
        expected_scale: Any | None = None,
    ) -> FinancialQuantity:
        """Adapt a validated legacy manifest value without preserving binary floats."""

        exact_value = exact_decimal_from_legacy(value, "legacy financial value")

        normalized_currency = "N/A" if kind == "shares" else currency
        if expected_scale is not None:
            scale = (
                expected_scale
                if isinstance(expected_scale, Decimal)
                else exact_decimal_from_legacy(expected_scale, "financial scale")
            )
        else:
            supported_scales = (
                Decimal("1"),
                Decimal("1000"),
                Decimal("10000"),
                Decimal("1000000"),
                Decimal("100000000"),
                Decimal("1000000000"),
            )
            matches = [
                candidate
                for candidate in supported_scales
                if unit in _expected_unit(kind, normalized_currency, candidate)
            ]
            if len(matches) != 1:
                raise FinancialInvariantError(
                    "FINANCIAL_UNIT_SCALE_MISMATCH",
                    f"Cannot infer one supported scale from unit {unit!r}.",
                )
            scale = matches[0]
        return cls(
            value=exact_value,
            unit=unit,
            scale=scale,
            currency=normalized_currency,
            period=period,
            as_of=as_of,
            provenance_refs=provenance_refs,
            kind=kind,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise FinancialInvariantError(
                "FINANCIAL_VALUE_INVALID",
                "FinancialQuantity.value must be a finite Decimal.",
            )
        if not isinstance(self.scale, Decimal) or not self.scale.is_finite() or self.scale <= 0:
            raise FinancialInvariantError(
                "FINANCIAL_SCALE_INVALID",
                "FinancialQuantity.scale must be a finite positive Decimal.",
            )
        if not self.period.strip():
            raise FinancialInvariantError(
                "FINANCIAL_PERIOD_MISSING",
                "FinancialQuantity.period is required.",
            )
        try:
            date.fromisoformat(self.as_of)
        except (TypeError, ValueError) as exc:
            raise FinancialInvariantError(
                "FINANCIAL_AS_OF_INVALID",
                "FinancialQuantity.as_of must be an ISO date.",
            ) from exc
        if not self.provenance_refs or any(
            not ref.startswith(("Fact:", "Assumption:"))
            for ref in self.provenance_refs
        ):
            raise FinancialInvariantError(
                "FINANCIAL_PROVENANCE_INVALID",
                "Every quantity needs at least one Fact or Assumption reference.",
            )
        if self.kind not in {"money", "shares", "per_share", "fx"}:
            raise FinancialInvariantError(
                "FINANCIAL_KIND_INVALID",
                f"Unsupported financial quantity kind: {self.kind}.",
            )
        if self.kind in {"money", "per_share"} and self.currency in {"", "N/A"}:
            raise FinancialInvariantError(
                "FINANCIAL_CURRENCY_MISSING",
                "Money quantities require an explicit currency.",
            )
        if self.kind == "shares" and self.currency not in {"", "N/A"}:
            raise FinancialInvariantError(
                "FINANCIAL_CURRENCY_INVALID",
                "Share quantities must not carry a money currency.",
            )
        if self.kind == "fx" and (
            self.currency in {"", "N/A"}
            or "/" not in self.unit
            or self.scale != Decimal("1")
        ):
            raise FinancialInvariantError(
                "FINANCIAL_FX_DIMENSION_INVALID",
                "FX quantities require an output/input currency unit and scale one.",
            )
        if self.kind != "fx" and self.unit not in _expected_unit(
            self.kind,
            self.currency,
            self.scale,
        ):
            raise FinancialInvariantError(
                "FINANCIAL_UNIT_SCALE_MISMATCH",
                f"Unit {self.unit!r} does not reconcile to scale {_decimal_text(self.scale)}.",
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
            "provenance_refs": list(self.provenance_refs),
            "kind": self.kind,
            "normalized_value": _decimal_text(self.normalized_value),
        }


@dataclass(frozen=True)
class EquityBridgeResult:
    value_basis: ValueBasis
    input_currency: str
    output_currency: str
    balance_sheet_period: str
    valuation_as_of: str
    equity_value: Decimal
    diluted_shares: Decimal
    per_share_value: Decimal
    trace: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "value_basis": self.value_basis,
            "input_currency": self.input_currency,
            "output_currency": self.output_currency,
            "balance_sheet_period": self.balance_sheet_period,
            "valuation_as_of": self.valuation_as_of,
            "equity_value": _decimal_text(self.equity_value),
            "diluted_shares": _decimal_text(self.diluted_shares),
            "per_share_value": _decimal_text(self.per_share_value),
            "trace": [dict(step) for step in self.trace],
        }


@dataclass(frozen=True)
class EquityBridge:
    """The sole enterprise-to-equity and per-share conversion seam."""

    basis_value: FinancialQuantity
    value_basis: ValueBasis
    balance_sheet_period: str
    valuation_as_of: str
    output_currency: str
    cash: FinancialQuantity | None
    debt: FinancialQuantity | None
    lease_debt: FinancialQuantity | None
    preferred_stock: FinancialQuantity | None
    minority_interest: FinancialQuantity | None
    pension_deficit: FinancialQuantity | None
    associates_jv_value: FinancialQuantity | None
    non_operating_assets: FinancialQuantity | None
    diluted_shares: FinancialQuantity
    fx_rate: FinancialQuantity | None = None

    def _fail(self, code: str, message: str) -> None:
        raise FinancialInvariantError(code, message)

    def evaluate(self) -> EquityBridgeResult:
        with valuation_decimal_context():
            return self._evaluate()

    def _evaluate(self) -> EquityBridgeResult:
        if self.value_basis not in {"enterprise_value", "equity_value"}:
            self._fail(
                "FINANCIAL_VALUE_BASIS_INVALID",
                f"Unsupported value basis: {self.value_basis}.",
            )
        if self.basis_value.kind != "money":
            self._fail("FINANCIAL_KIND_MISMATCH", "Basis value must be money.")
        if self.basis_value.as_of != self.valuation_as_of:
            self._fail(
                "FINANCIAL_AS_OF_MISMATCH",
                "Basis value as-of does not match valuation_as_of.",
            )

        raw_additions = (
            ("cash", self.cash),
            ("non_operating_assets", self.non_operating_assets),
            ("associates_jv_value", self.associates_jv_value),
        )
        raw_deductions = (
            ("debt", self.debt),
            ("lease_debt", self.lease_debt),
            ("preferred_stock", self.preferred_stock),
            ("minority_interest", self.minority_interest),
            ("pension_deficit", self.pension_deficit),
        )
        raw_adjustments = raw_additions + raw_deductions
        if self.value_basis == "enterprise_value" and any(
            quantity is None for _, quantity in raw_adjustments
        ):
            self._fail(
                "FINANCIAL_BRIDGE_INPUT_MISSING",
                "Enterprise-value inputs require every equity-bridge adjustment.",
            )
        if self.value_basis == "equity_value" and any(
            quantity is not None for _, quantity in raw_adjustments
        ):
            self._fail(
                "FINANCIAL_VALUE_BASIS_DOUBLE_BRIDGE",
                "Equity-value inputs must omit enterprise-value adjustments.",
            )
        additions = tuple(
            (field_name, quantity)
            for field_name, quantity in raw_additions
            if quantity is not None
        )
        deductions = tuple(
            (field_name, quantity)
            for field_name, quantity in raw_deductions
            if quantity is not None
        )
        adjustments = additions + deductions
        for field_name, quantity in adjustments:
            if quantity.kind != "money":
                self._fail(
                    "FINANCIAL_KIND_MISMATCH",
                    f"{field_name} must be a money quantity.",
                )
            if quantity.currency != self.basis_value.currency:
                self._fail(
                    "FINANCIAL_CURRENCY_MISMATCH",
                    f"{field_name} currency {quantity.currency} does not match {self.basis_value.currency}.",
                )
            if quantity.scale != self.basis_value.scale:
                self._fail(
                    "FINANCIAL_SCALE_MISMATCH",
                    f"{field_name} scale does not match the basis-value scale.",
                )
            if quantity.unit != self.basis_value.unit:
                self._fail(
                    "FINANCIAL_UNIT_MISMATCH",
                    f"{field_name} unit does not match the basis-value unit.",
                )
            if quantity.period != self.balance_sheet_period:
                self._fail(
                    "FINANCIAL_PERIOD_MISMATCH",
                    f"{field_name} period {quantity.period} does not match {self.balance_sheet_period}.",
                )
            if quantity.as_of != self.valuation_as_of:
                self._fail(
                    "FINANCIAL_AS_OF_MISMATCH",
                    f"{field_name} as-of does not match valuation_as_of.",
                )

        if self.diluted_shares.kind != "shares":
            self._fail(
                "FINANCIAL_SHARE_BASIS_INVALID",
                "diluted_shares must be a shares quantity.",
            )
        if (
            self.value_basis == "equity_value"
            and self.basis_value.period != self.balance_sheet_period
        ):
            self._fail(
                "FINANCIAL_PERIOD_MISMATCH",
                "Equity value and diluted shares must share one period basis.",
            )
        if self.diluted_shares.period != self.balance_sheet_period:
            self._fail(
                "FINANCIAL_PERIOD_MISMATCH",
                "diluted_shares period does not match the balance-sheet period.",
            )
        if self.diluted_shares.as_of != self.valuation_as_of:
            self._fail(
                "FINANCIAL_AS_OF_MISMATCH",
                "diluted_shares as-of does not match valuation_as_of.",
            )
        shares = self.diluted_shares.normalized_value
        if shares <= 0:
            self._fail(
                "FINANCIAL_SHARES_NON_POSITIVE",
                "Diluted shares must be positive.",
            )

        if self.output_currency == self.basis_value.currency and self.fx_rate is not None:
            self._fail(
                "FINANCIAL_FX_UNEXPECTED",
                "FX rate must be omitted when input and output currencies match.",
            )
        if self.output_currency != self.basis_value.currency:
            if self.fx_rate is None:
                self._fail(
                    "FINANCIAL_FX_REQUIRED",
                    "A dimensioned FX rate is required when output currency differs.",
                )
            if (
                self.fx_rate.kind != "fx"
                or self.fx_rate.unit
                != f"{self.output_currency}/{self.basis_value.currency}"
                or self.fx_rate.currency != self.output_currency
                or self.fx_rate.period != self.valuation_as_of
                or self.fx_rate.as_of != self.valuation_as_of
                or self.fx_rate.normalized_value <= 0
            ):
                self._fail(
                    "FINANCIAL_FX_DIMENSION_INVALID",
                    "FX rate must be positive output-currency per input-currency at valuation_as_of.",
                )

        trace: list[dict[str, Any]] = [
            {
                "operation": "basis_value",
                "amount": _decimal_text(self.basis_value.normalized_value),
                "ref_ids": list(self.basis_value.provenance_refs),
            }
        ]
        equity_value = self.basis_value.normalized_value
        if self.value_basis == "enterprise_value":
            for field_name, quantity in additions:
                equity_value += quantity.normalized_value
                trace.append(
                    {
                        "operation": f"add_{field_name}",
                        "amount": _decimal_text(quantity.normalized_value),
                        "ref_ids": list(quantity.provenance_refs),
                    }
                )
            for field_name, quantity in deductions:
                equity_value -= quantity.normalized_value
                trace.append(
                    {
                        "operation": f"subtract_{field_name}",
                        "amount": _decimal_text(quantity.normalized_value),
                        "ref_ids": list(quantity.provenance_refs),
                    }
                )

        if self.fx_rate is not None:
            equity_value *= self.fx_rate.normalized_value
            trace.append(
                {
                    "operation": "convert_fx",
                    "amount": _decimal_text(self.fx_rate.normalized_value),
                    "ref_ids": list(self.fx_rate.provenance_refs),
                }
            )

        trace.append(
            {
                "operation": "divide_diluted_shares",
                "amount": _decimal_text(shares),
                "ref_ids": list(self.diluted_shares.provenance_refs),
            }
        )
        return EquityBridgeResult(
            value_basis=self.value_basis,
            input_currency=self.basis_value.currency,
            output_currency=self.output_currency,
            balance_sheet_period=self.balance_sheet_period,
            valuation_as_of=self.valuation_as_of,
            equity_value=equity_value,
            diluted_shares=shares,
            per_share_value=equity_value / shares,
            trace=tuple(trace),
        )
