from __future__ import annotations

import re
from datetime import date
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from ..financial import (
    EquityBridge,
    EquityBridgeResult,
    FinancialQuantity,
    ValueBasis,
)
from ..forecast import (
    ForecastGraph,
    ForecastInvariantError,
    ForecastQuantity,
    ForecastRequest,
)
from .contracts import (
    ConditionalValueRange,
    EquityBridgeSpec,
    EquityBridgeTiming,
    MethodBlocked,
    ValuationPoint,
    decimal_text,
    forecast_lineage,
    merge_refs,
)


@dataclass(frozen=True)
class ValuationContext:
    graph: ForecastGraph
    request: ForecastRequest
    reference_graph: ForecastGraph | None
    periods: tuple[str, ...]
    valuation_as_of: str
    valuation_input_lineage: tuple[str, ...]


class ValuationBasis:
    """Bind Forecast semantics and execute shared timing, quantity and equity policy."""

    def bind(
        self,
        graph: ForecastGraph,
        request: ForecastRequest,
        *,
        reference_graph: ForecastGraph | None = None,
    ) -> ValuationContext:
        periods = self.periods(graph)
        return ValuationContext(
            graph=graph,
            request=request,
            reference_graph=reference_graph,
            periods=periods,
            valuation_as_of=self.as_of(graph),
            valuation_input_lineage=forecast_lineage(graph),
        )

    def validate_bridge_evidence(
        self,
        bridge: EquityBridgeSpec,
        facts: Mapping[str, Any],
        *,
        subject_id: str,
        as_of: str,
    ) -> None:
        quantities = {
            "lease_debt": bridge.lease_debt,
            "preferred_stock": bridge.preferred_stock,
            "minority_interest": bridge.minority_interest,
            "associates_jv_value": bridge.associates_jv_value,
            "non_operating_assets": bridge.non_operating_assets,
        }
        if bridge.pension_deficit is not None:
            quantities["pension_deficit"] = bridge.pension_deficit
        if bridge.diluted_shares is not None:
            quantities["diluted_shares"] = bridge.diluted_shares
        for field_name, quantity in quantities.items():
            fact_refs = tuple(
                ref for ref in quantity.provenance_refs if ref.startswith("Fact:")
            )
            assumption_refs = tuple(
                ref for ref in quantity.provenance_refs if ref.startswith("Assumption:")
            )
            resolved = tuple(facts.get(ref.removeprefix("Fact:")) for ref in fact_refs)
            if (
                not fact_refs
                or any(fact is None for fact in resolved)
                or any(
                    fact.subject_id != subject_id
                    or fact.scope != "company"
                    or fact.metric_id != field_name
                    or not fact.official
                    or date.fromisoformat(fact.available_at) > date.fromisoformat(as_of)
                    for fact in resolved
                )
            ):
                raise MethodBlocked(
                    f"VALUATION_BRIDGE_EVIDENCE_INVALID: {field_name} must resolve through an official frozen company fact.",
                )
            if bridge.timing == EquityBridgeTiming.OPENING and assumption_refs:
                raise MethodBlocked(
                    f"VALUATION_BRIDGE_EVIDENCE_INVALID: opening {field_name} cannot be replaced by an uncalibrated assumption.",
                )
            if bridge.timing == EquityBridgeTiming.OPENING and not any(
                fact.value == quantity.normalized_value
                and fact.unit == quantity.unit
                and fact.currency == quantity.currency
                and fact.period == quantity.period
                for fact in resolved
            ):
                raise MethodBlocked(
                    f"VALUATION_BRIDGE_EVIDENCE_INVALID: opening {field_name} does not match its exact snapshot fact.",
                )
            expected_roll_forward = (
                f"Assumption:bridge_roll_forward:no_change:{field_name}"
            )
            if bridge.timing == EquityBridgeTiming.TERMINAL and (
                assumption_refs != (expected_roll_forward,)
            ):
                raise MethodBlocked(
                    f"VALUATION_BRIDGE_EVIDENCE_INVALID: terminal {field_name} requires one explicit no-change roll-forward assumption.",
                )
            if bridge.timing == EquityBridgeTiming.TERMINAL and not any(
                fact.value == quantity.normalized_value
                and fact.currency == quantity.currency
                for fact in resolved
            ):
                raise MethodBlocked(
                    f"VALUATION_BRIDGE_EVIDENCE_INVALID: terminal {field_name} no-change roll-forward does not reconcile to its opening fact."
                )

    def validate_method_bridge(
        self,
        graph: ForecastGraph,
        bridge: EquityBridgeSpec,
        base_request: ForecastRequest,
    ) -> None:
        expected_period = (
            base_request.data_snapshot.company_opening_balance_sheet.cash.period
            if bridge.timing == EquityBridgeTiming.OPENING
            else self.periods(graph)[-1]
        )
        if bridge.balance_sheet_period != expected_period or (
            bridge.diluted_shares is not None
            and bridge.diluted_shares.as_of != self.as_of(graph)
        ):
            raise MethodBlocked(
                "VALUATION_HORIZON_MISMATCH: equity bridge does not bind the method horizon and frozen as-of."
            )
        self.validate_bridge_evidence(
            bridge,
            {fact.fact_id: fact for fact in base_request.data_snapshot.facts},
            subject_id=graph.security_id,
            as_of=self.as_of(graph),
        )

    def bridge_range(
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
        refs = merge_refs(
            basis_refs,
            (f"Assumption:formula:{formula_version}",),
        )
        points = tuple(
            self.bridge_one(
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

    def bridge_one(
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
            raise MethodBlocked(
                "FINANCIAL_DILUTION_INVALID: cumulative share multiplier must remain positive."
            )
        if value_basis == "enterprise_value":
            cash, debt = self.bridge_cash_debt(graph, spec)
            currency = cash.currency
            as_of = cash.as_of
        else:
            cash = None
            debt = None
            currency = spec.output_currency or spec.lease_debt.currency
            as_of = spec.lease_debt.as_of
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
            if spec.pension_deficit is None:
                return ValuationPoint(
                    basis_value=basis,
                    equity_value=None,
                    per_share_value=None,
                    bridge_trace=(
                        {
                            "operation": "equity_bridge_incomplete",
                            "amount": None,
                            "ref_ids": ["Missing:pension_deficit"],
                        },
                    ),
                )
            adjustments: dict[str, FinancialQuantity | None] = {
                "cash": cash,
                "debt": debt,
                "lease_debt": self.normalized_financial(spec.lease_debt),
                "preferred_stock": self.normalized_financial(spec.preferred_stock),
                "minority_interest": self.normalized_financial(spec.minority_interest),
                "pension_deficit": self.normalized_financial(spec.pension_deficit),
                "associates_jv_value": self.normalized_financial(
                    spec.associates_jv_value
                ),
                "non_operating_assets": self.normalized_financial(
                    spec.non_operating_assets
                ),
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
        diluted_shares = (
            self.normalized_financial(spec.diluted_shares)
            if spec.diluted_shares is not None
            else None
        )
        if diluted_shares is not None and share_multiplier != Decimal("1"):
            diluted_shares = FinancialQuantity(
                value=diluted_shares.normalized_value * share_multiplier,
                unit=diluted_shares.unit,
                scale=Decimal("1"),
                currency=diluted_shares.currency,
                period=diluted_shares.period,
                as_of=diluted_shares.as_of,
                provenance_refs=merge_refs(
                    diluted_shares.provenance_refs,
                    (
                        f"Assumption:{share_multiplier_ref_prefix}:"
                        f"{decimal_text(share_multiplier)}",
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
        return self.valuation_point(basis, result)

    def bridge_cash_debt(
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
            self.financial_from_forecast(graph.quantity(cash_id)),
            self.financial_from_forecast(graph.quantity(debt_id)),
        )

    def valuation_point(
        self,
        basis: FinancialQuantity,
        result: EquityBridgeResult,
    ) -> ValuationPoint:
        refs = tuple(
            dict.fromkeys(
                ref for step in result.trace for ref in step.get("ref_ids", ())
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
        per_share = (
            FinancialQuantity(
                value=result.per_share_value,
                unit=f"{result.output_currency}/share",
                scale=Decimal("1"),
                currency=result.output_currency,
                period=basis.period,
                as_of=result.valuation_as_of,
                provenance_refs=refs,
                kind="per_share",
            )
            if result.per_share_value is not None
            else None
        )
        return ValuationPoint(
            basis_value=basis,
            equity_value=equity,
            per_share_value=per_share,
            bridge_trace=result.trace,
        )

    def financial_from_forecast(self, quantity: ForecastQuantity) -> FinancialQuantity:
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

    def normalized_financial(
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

    def discount_times(
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
        period_ends = tuple(self.period_end(period) for period in periods)
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

    def period_end(self, period: str) -> date:
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

    def model_quantity(
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

    def periods(self, graph: ForecastGraph) -> tuple[str, ...]:
        periods = tuple(
            node.quantity.period
            for node in graph.nodes
            if node.node_id.startswith("valuation.fcff.")
        )
        if (
            not periods
            and graph.template_id == "financial_institution_valuation_shell@1"
        ):
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

    def as_of(self, graph: ForecastGraph) -> str:
        first_period = self.periods(graph)[0]
        node_id = (
            f"financial.horizon.{first_period}"
            if graph.template_id == "financial_institution_valuation_shell@1"
            else (
                f"biopharma.horizon.{first_period}"
                if graph.template_id == "biopharma_pipeline_valuation_shell@1"
                else f"valuation.fcff.{first_period}"
            )
        )
        return graph.quantity(node_id).as_of
