from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..financial import valuation_decimal_context
from .evidence import (
    CompanyArchetype,
    ForecastInvariantError,
    ForecastRequest,
    SegmentForecastOverride,
    merge_lineage,
)
from .graph import (
    FormulaId,
    ForecastOperandDeclaration,
    ForecastNodeKind,
    ForecastNodeDeclaration,
    ForecastGraphCompiler,
    ForecastGraph,
)


@dataclass(frozen=True)
class _SegmentState:
    nodes: dict[str, ForecastNodeDeclaration]


@dataclass(frozen=True)
class _CompanyState:
    cash: ForecastNodeDeclaration
    net_ppe: ForecastNodeDeclaration
    debt: ForecastNodeDeclaration
    other_assets: ForecastNodeDeclaration
    other_liabilities: ForecastNodeDeclaration
    equity: ForecastNodeDeclaration
    working_capital: ForecastNodeDeclaration


class ManufacturingForecast:
    """Own manufacturing drivers, period projection, and three-statement reconciliation."""

    TEMPLATE_ID = "manufacturing_driver_graph@2"

    def __init__(self) -> None:
        self._graph = ForecastGraphCompiler()

    def project(
        self,
        request: ForecastRequest,
        baselines: dict[str, object],
        overrides: dict[tuple[str, str], SegmentForecastOverride],
    ) -> ForecastGraph:
        nodes: list[ForecastNodeDeclaration] = []
        edges: list[ForecastOperandDeclaration] = []
        states: dict[str, _SegmentState] = {}
        for segment_id in request.security.segment_ids:
            current: dict[str, ForecastNodeDeclaration] = {}
            for metric, quantity in baselines[segment_id].named_quantities():
                node = self._graph.input_node(
                    request,
                    node_id=f"baseline.{segment_id}.{metric}.{quantity.period}",
                    label=f"{segment_id} frozen {metric.replace('_', ' ')}",
                    quantity=quantity,
                )
                current[metric] = node
                nodes.append(node)
            states[segment_id] = _SegmentState(nodes=current)

        company_state, company_nodes, company_edges = self._company_baseline(request)
        nodes.extend(company_nodes)
        edges.extend(company_edges)
        with valuation_decimal_context():
            for period in request.forecast_periods:
                period_nodes: dict[str, dict[str, ForecastNodeDeclaration]] = {}
                for segment_id in request.security.segment_ids:
                    override = overrides.get(
                        (segment_id, period),
                        SegmentForecastOverride(segment_id=segment_id, period=period),
                    )
                    built, built_edges, next_state = self._build_segment_period(
                        request, states[segment_id], override, period
                    )
                    nodes.extend(built.values())
                    edges.extend(built_edges)
                    states[segment_id] = next_state
                    period_nodes[segment_id] = built
                built, built_edges, company_state = self._company_period(
                    request, period, period_nodes, company_state
                )
                nodes.extend(built.values())
                edges.extend(built_edges)

        template_id = (
            "cyclical_manufacturing_driver_graph@1"
            if request.security.archetype == CompanyArchetype.CYCLICAL_MANUFACTURING
            else "cyclical_resource_driver_graph@1"
            if request.security.archetype == CompanyArchetype.CYCLICAL_RESOURCE
            else self.TEMPLATE_ID
        )
        archetype_label = request.security.archetype.value.replace(
            "multi_segment", "multi-segment"
        ).replace("_", " ")
        if request.security.archetype in {
            CompanyArchetype.CYCLICAL_MANUFACTURING,
            CompanyArchetype.CYCLICAL_RESOURCE,
        }:
            routing_explanation = (
                "Routed cyclical economics through explicit volume, utilization, "
                "price, unit-cost, tax, and maintenance-capex drivers. Ordinary stable-growth "
                "valuation is disabled downstream; mid-cycle methods are required, while finite-life NAV "
                "applies only when reserve-backed resource assets are present."
            )
        else:
            routing_explanation = (
                f"Routed {archetype_label} through a typed demand, capacity, cost, "
                "three-statement, FCFF manufacturing graph with consolidated tax."
            )
        graph_nodes = tuple(nodes)
        graph_edges = tuple(edges)
        return self._graph.compile(
            self._graph.blueprint(
                request=request,
                template_id=template_id,
                routing_explanation=routing_explanation,
                nodes=graph_nodes,
                edges=graph_edges,
            )
        )


    def _company_baseline(
        self,
        request: ForecastRequest,
    ) -> tuple[
        _CompanyState,
        list[ForecastNodeDeclaration],
        list[ForecastOperandDeclaration],
    ]:
        opening = request.data_snapshot.company_opening_balance_sheet
        built: dict[str, ForecastNodeDeclaration] = {}
        for metric, quantity in opening.named_quantities():
            node = self._graph.input_node(
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
    ) -> ForecastNodeDeclaration:
        supplied = getattr(override, field_name)
        value = default if supplied is None else supplied
        origin = "default" if supplied is None else "override"
        lineage = merge_lineage(
            default_lineage,
            (
                f"Assumption:{origin}:{override.segment_id}:{override.period}:{field_name}",
            ),
        )
        quantity = self._graph.quantity(
            value,
            unit=unit,
            currency=currency,
            period=override.period,
            as_of=request.as_of,
            lineage_refs=lineage,
        )
        return self._graph.input_node(
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
    ) -> tuple[
        dict[str, ForecastNodeDeclaration],
        list[ForecastOperandDeclaration],
        _SegmentState,
    ]:
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
                default_lineage=merge_lineage(
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
        built: dict[str, ForecastNodeDeclaration] = {
            f"assumption_{name}": node for name, node in assumptions.items()
        }
        edges: list[ForecastOperandDeclaration] = []

        def derive(
            metric: str,
            kind: ForecastNodeKind,
            unit: str,
            out_currency: str,
            formula: FormulaId,
            operands: tuple[tuple[str, ForecastNodeDeclaration, Decimal], ...],
        ) -> ForecastNodeDeclaration:
            node, node_edges = self._graph.derived_node(
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
        segment_nodes: dict[str, dict[str, ForecastNodeDeclaration]],
        prior: _CompanyState,
    ) -> tuple[
        dict[str, ForecastNodeDeclaration],
        list[ForecastOperandDeclaration],
        _CompanyState,
    ]:
        currency = request.security.reporting_currency
        probability = min(
            segment_nodes[segment_id][
                "assumption_event_probability"
            ].quantity.normalized_value
            for segment_id in request.security.segment_ids
        )
        built: dict[str, ForecastNodeDeclaration] = {}
        edges: list[ForecastOperandDeclaration] = []

        def derive(
            metric: str,
            formula: FormulaId,
            operands: tuple[tuple[str, ForecastNodeDeclaration, Decimal], ...],
            *,
            kind: ForecastNodeKind = ForecastNodeKind.FINANCIAL_FORECAST,
            unit: str = currency,
            out_currency: str = currency,
            prefix: str = "company",
        ) -> ForecastNodeDeclaration:
            node, node_edges = self._graph.derived_node(
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
        distributions = self._graph.input_node(
            request,
            node_id=f"assumption.company.distributions.{period}",
            label="company distributions assumption",
            quantity=self._graph.quantity(
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
        other_assets_growth = self._graph.input_node(
            request,
            node_id=f"assumption.company.other_assets_growth.{period}",
            label="company other assets growth assumption",
            quantity=self._graph.quantity(
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
        other_liabilities_growth = self._graph.input_node(
            request,
            node_id=f"assumption.company.other_liabilities_growth.{period}",
            label="company other liabilities growth assumption",
            quantity=self._graph.quantity(
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
