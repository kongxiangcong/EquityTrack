from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from typing import Mapping, cast

from ..financial import FinancialQuantity
from ..forecast import (
    ForecastGraph,
    ForecastQuantity,
    ForecastRequest,
)
from .contracts import (
    FinancialInstitutionValuationSpec,
    MethodBlocked,
    MethodCalculationResult,
    ScenarioMethodResult,
    ScenarioRole,
    ValuationAssumption,
    ValuationPlan,
    ValuationSensitivity,
    decimal_text,
    isolate_method,
    merge_refs,
)
from .basis import ValuationBasis, ValuationContext


@dataclass(frozen=True)
class FinancialProjection:
    case: str
    scenario_case: str
    book: Decimal
    dividends: tuple[Decimal, ...]
    residual_incomes: tuple[Decimal, ...]
    opening_books: tuple[Decimal, ...]
    capital_ratios: tuple[Decimal, ...]
    roe: Decimal
    payout: Decimal
    dilution: Decimal
    coe: Decimal
    growth: Decimal
    declared_growth: Decimal
    operating_metrics: Mapping[str, Decimal]


class FinancialInstitutionValuation:
    """Own the complete FinancialInstitutionValuation method-family economics."""

    FINANCIAL_PB_FORMULA_VERSION = "justified_pb_roe_coe_act365@3"
    FINANCIAL_DDM_FORMULA_VERSION = "financial_ddm_clean_surplus_act365@3"
    FINANCIAL_RI_FORMULA_VERSION = "residual_income_clean_surplus_act365@3"

    def __init__(self, basis: ValuationBasis) -> None:
        self._basis = basis

    def evaluate(
        self,
        context: ValuationContext,
        plan: ValuationPlan,
        scenario_role: ScenarioRole,
    ) -> tuple[ScenarioMethodResult, ...]:
        graph = context.graph
        base_request = context.request
        horizon = f"terminal_period={context.periods[-1]}"
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
            f"valuation_as_of={self._basis.as_of(graph)};"
            f"financial_periods={self._basis.periods(graph)[0]}..{self._basis.periods(graph)[-1]}"
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
                    lineage_refs=("Assumption:financial_institution_spec_missing",),
                )
                for method_id, formula_version, _ in method_definitions
            )
        common_refs = merge_refs(
            spec.lineage_refs,
            plan.present_value_bridge.provenance_refs,
        )
        return tuple(
            isolate_method(
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
        self._basis.validate_method_bridge(
            graph,
            plan.present_value_bridge,
            base_request,
        )
        periods = self._basis.periods(graph)
        if tuple(item.period for item in spec.periods) != periods:
            raise MethodBlocked(
                "FINANCIAL_PERIOD_COVERAGE_INVALID: specialized financial schedule must exactly cover the routed forecast periods."
            )
        if any(
            quantity.as_of != self._basis.as_of(graph)
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
            raise MethodBlocked(
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
            quantity.as_of != self._basis.as_of(graph) for quantity in period_quantities
        ):
            raise MethodBlocked(
                "FINANCIAL_AS_OF_INVALID: every period-level driver and adjustment must bind the frozen valuation as-of."
            )
        opening_balances = (
            spec.opening_book_value,
            spec.opening_regulatory_capital,
            spec.opening_risk_weighted_assets,
        )
        if any(
            quantity.period != plan.present_value_bridge.balance_sheet_period
            or quantity.as_of != self._basis.as_of(graph)
            for quantity in opening_balances
        ):
            raise MethodBlocked(
                "FINANCIAL_OPENING_PERIOD_INVALID: opening balances must bind the present-value bridge balance-sheet period and frozen as-of."
            )
        if (
            spec.opening_regulatory_capital.normalized_value
            / spec.opening_risk_weighted_assets.normalized_value
            < spec.minimum_regulatory_capital_ratio.normalized_value
        ):
            raise MethodBlocked(
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
            raise MethodBlocked(
                "FINANCIAL_CURRENCY_MISMATCH: all book, capital, RWA, and adjustment quantities must use the reporting currency."
            )
        facts = {fact.fact_id: fact for fact in base_request.data_snapshot.facts}
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
                facts.get(ref.removeprefix("Fact:")) for ref in quantity.provenance_refs
            )
            if any(fact is None for fact in resolved) or not any(
                fact.subject_id == graph.security_id
                and fact.scope == "company"
                and fact.metric_id == metric_id
                and fact.value == quantity.normalized_value
                and fact.unit == quantity.unit
                and fact.currency == quantity.currency
                and fact.period == quantity.period
                and fact.official
                and date.fromisoformat(fact.available_at)
                <= date.fromisoformat(self._basis.as_of(graph))
                for fact in resolved
                if fact is not None
            ):
                raise MethodBlocked(
                    "FINANCIAL_EVIDENCE_INVALID: opening book value, regulatory capital, and RWA must resolve exactly through official frozen facts."
                )

    def _project(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: FinancialInstitutionValuationSpec,
        scenario_role: ScenarioRole,
    ) -> tuple[FinancialProjection, FinancialProjection, FinancialProjection]:
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
            raise MethodBlocked(
                "FINANCIAL_TERMINAL_CLEAN_SURPLUS_UNSUPPORTED: a continuing terminal clean-surplus adjustment requires an explicit separate terminal model."
            )
        discount_times = self._basis.discount_times(
            tuple(item.period for item in spec.periods),
            self._basis.as_of(graph),
        )
        projections: list[FinancialProjection] = []
        case_fields = (
            ("low", spec.cost_of_equity_high),
            ("base", spec.cost_of_equity_base),
            ("high", spec.cost_of_equity_low),
        )
        for case_name, coe_quantity in case_fields:
            book = spec.opening_book_value.normalized_value
            regulatory_capital = spec.opening_regulatory_capital.normalized_value
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
                metrics = {item.metric_id: item for item in period.operating_metrics}
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
                    if npl_ratio > spec.specialized_risk_limit.normalized_value:
                        raise MethodBlocked(
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
                    roe = roe + (Decimal("1") - combined_ratio) * operating_exposure
                    selected_metrics = {
                        "combined_ratio": combined_ratio,
                        "solvency_ratio": solvency_ratio,
                        "operating_exposure_to_equity": operating_exposure,
                    }
                    if solvency_ratio < spec.specialized_risk_limit.normalized_value:
                        raise MethodBlocked(
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
                    roe = roe + fee_income_yield * operating_exposure
                    selected_metrics = {
                        "net_capital_ratio": net_capital_ratio,
                        "fee_income_yield": fee_income_yield,
                        "operating_exposure_to_equity": operating_exposure,
                    }
                    if net_capital_ratio < spec.specialized_risk_limit.normalized_value:
                        raise MethodBlocked(
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
                    Decimal("1") + coe_quantity.normalized_value
                ) ** (timing - previous_time) - Decimal("1")
                residual_income = (
                    net_income + clean_adjustment - interval_required_return * book
                )
                sustainable_growth = (net_income - dividend + clean_adjustment) / book
                book = book + net_income - dividend + clean_adjustment
                regulatory_capital = (
                    regulatory_capital + net_income - dividend + capital_adjustment
                )
                rwa = rwa * (Decimal("1") + rwa_growth)
                if book <= 0 or rwa <= 0 or dilution <= 0:
                    raise MethodBlocked(
                        "FINANCIAL_BALANCE_INVALID: book value, RWA, and dilution must remain positive."
                    )
                capital_ratio = regulatory_capital / rwa
                if (
                    capital_ratio
                    < spec.minimum_regulatory_capital_ratio.normalized_value
                ):
                    raise MethodBlocked(
                        "FINANCIAL_REGULATORY_CAPITAL_BREACH: projected capital falls below the declared regulatory minimum."
                    )
                dividends.append(dividend)
                residual_incomes.append(residual_income)
                capital_ratios.append(capital_ratio)
                last_roe = roe
                last_payout = payout
                previous_time = timing
            if abs(sustainable_growth - selected_growth) > Decimal("0.02"):
                raise MethodBlocked(
                    "FINANCIAL_TERMINAL_GROWTH_INCONSISTENT: declared terminal growth must reconcile within two percentage points of ROE retention plus the clean-surplus adjustment."
                )
            if coe_quantity.normalized_value <= sustainable_growth:
                raise MethodBlocked(
                    "FINANCIAL_TERMINAL_SPREAD_INVALID: cost of equity must exceed sustainable clean-surplus growth."
                )
            projections.append(
                FinancialProjection(
                    case=case_name,
                    scenario_case=scenario_case,
                    book=book,
                    dividends=tuple(dividends),
                    residual_incomes=tuple(residual_incomes),
                    opening_books=tuple(opening_books),
                    capital_ratios=tuple(capital_ratios),
                    roe=last_roe,
                    payout=last_payout,
                    dilution=dilution,
                    coe=coe_quantity.normalized_value,
                    growth=sustainable_growth,
                    declared_growth=selected_growth,
                    operating_metrics=selected_metrics,
                )
            )
        return cast(
            tuple[FinancialProjection, FinancialProjection, FinancialProjection],
            tuple(projections),
        )

    def _financial_common_output(
        self,
        graph: ForecastGraph,
        plan: ValuationPlan,
        base_request: ForecastRequest,
        spec: FinancialInstitutionValuationSpec,
        values: tuple[Decimal, Decimal, Decimal],
        projections: tuple[
            FinancialProjection, FinancialProjection, FinancialProjection
        ],
        *,
        formula_version: str,
        method_diagnostic: str,
    ) -> MethodCalculationResult:
        if not values[0] <= values[1] <= values[2]:
            raise MethodBlocked(
                "FINANCIAL_VALUE_RANGE_INVALID: stress/base/improvement assumptions did not produce an ordered conditional value range."
            )
        lineage = merge_refs(
            spec.lineage_refs,
            graph.quantity(
                f"financial.horizon.{self._basis.periods(graph)[0]}"
            ).lineage_refs,
            ("Assumption:financial_scenario_case:" f"{projections[0].scenario_case}",),
            (f"Assumption:formula:{formula_version}",),
        )
        value_range = self._basis.bridge_range(
            graph,
            plan.present_value_bridge,
            "equity_value",
            values,
            formula_version,
            basis_period=plan.present_value_bridge.balance_sheet_period,
            basis_refs=lineage,
            share_multipliers=cast(
                tuple[Decimal, Decimal, Decimal],
                tuple(item.dilution for item in projections),
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
                f"{projections[0].scenario_case}; terminal clean-surplus "
                f"growth={decimal_text(projections[1].growth)}, declared "
                f"growth={decimal_text(projections[1].declared_growth)}, "
                f"cumulative share factor={decimal_text(projections[1].dilution)}."
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
        projections = self._project(
            graph,
            plan,
            base_request,
            spec,
            scenario_role,
        )
        discount_times = self._basis.discount_times(
            tuple(item.period for item in spec.periods),
            self._basis.as_of(graph),
        )
        values: list[Decimal] = []
        for projection in projections:
            coe = projection.coe
            growth = projection.growth
            explicit_dividends = sum(
                (
                    dividend / ((Decimal("1") + coe) ** timing)
                    for timing, dividend in zip(
                        discount_times,
                        projection.dividends,
                        strict=True,
                    )
                ),
                Decimal("0"),
            )
            terminal_equity = (
                projection.book * (projection.roe - growth) / (coe - growth)
            )
            values.append(
                explicit_dividends
                + terminal_equity / ((Decimal("1") + coe) ** discount_times[-1])
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
        projections = self._project(
            graph,
            plan,
            base_request,
            spec,
            scenario_role,
        )
        discount_times = self._basis.discount_times(
            tuple(item.period for item in spec.periods),
            self._basis.as_of(graph),
        )
        values: list[Decimal] = []
        for projection in projections:
            coe = projection.coe
            growth = projection.growth
            dividends = projection.dividends
            explicit = sum(
                (
                    dividend / ((Decimal("1") + coe) ** timing)
                    for timing, dividend in zip(
                        discount_times,
                        dividends,
                        strict=True,
                    )
                ),
                Decimal("0"),
            )
            terminal_dividend = projection.book * projection.roe * projection.payout
            terminal = terminal_dividend / (coe - growth)
            values.append(
                explicit + terminal / ((Decimal("1") + coe) ** discount_times[-1])
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
        projections = self._project(
            graph,
            plan,
            base_request,
            spec,
            scenario_role,
        )
        discount_times = self._basis.discount_times(
            tuple(item.period for item in spec.periods),
            self._basis.as_of(graph),
        )
        values: list[Decimal] = []
        for projection in projections:
            coe = projection.coe
            growth = projection.growth
            explicit = sum(
                (
                    residual_income / ((Decimal("1") + coe) ** timing)
                    for timing, residual_income in zip(
                        discount_times,
                        projection.residual_incomes,
                        strict=True,
                    )
                ),
                Decimal("0"),
            )
            terminal_residual_income = (
                projection.book * (projection.roe - coe) / (coe - growth)
            )
            values.append(
                spec.opening_book_value.normalized_value
                + explicit
                + terminal_residual_income
                / ((Decimal("1") + coe) ** discount_times[-1])
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
