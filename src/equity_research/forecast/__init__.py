from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from .evidence import (
    CompanyArchetype,
    CompanyOpeningBalanceSheet,
    DataInsufficientForecastRequest,
    DataInsufficientSnapshot,
    DataSnapshot,
    ForecastAssumption,
    ForecastEvidence,
    ForecastInvariantError,
    ForecastNarrativeStatement,
    ForecastQuantity,
    ForecastRequest,
    NarrativeBasis,
    NarrativeCategory,
    Security,
    SegmentBaseline,
    SegmentForecastOverride,
    SnapshotFact,
)


from .graph import (
    ConditionOperator,
    FormulaId,
    ForecastCondition,
    ForecastEdge,
    ForecastGraph,
    ForecastGraphCompiler,
    ForecastNode,
    ForecastNodeKind,
    ForecastOperandDeclaration,
    LeadingIndicator,
    NodeOrigin,
)


from .manufacturing import ManufacturingForecast


class ForecastEngine:
    """Build a deterministic, replayable event-driver-three-statement graph."""

    def __init__(self) -> None:
        self._manufacturing = ManufacturingForecast()
        self._graph = ForecastGraphCompiler()

    def build(
        self,
        request: ForecastRequest | DataInsufficientForecastRequest,
    ) -> ForecastGraph:
        if isinstance(request, DataInsufficientForecastRequest):
            return self._build_data_insufficient(request)
        baselines, overrides = ForecastEvidence.validate(request)
        if (
            request.security.archetype
            == CompanyArchetype.FINANCIAL_INSTITUTION
        ):
            return self._build_financial_institution_shell(request)
        if request.security.archetype == CompanyArchetype.BIOPHARMA:
            return self._build_biopharma_shell(request)
        if request.security.archetype not in {
            CompanyArchetype.GENERAL_MANUFACTURING,
            CompanyArchetype.MULTI_SEGMENT_MANUFACTURING,
            CompanyArchetype.CYCLICAL_MANUFACTURING,
            CompanyArchetype.CYCLICAL_RESOURCE,
        }:
            raise ForecastInvariantError(
                "FORECAST_TEMPLATE_UNSUPPORTED",
                f"No Forecast template is registered for {request.security.archetype.value}.",
            )
        return self._manufacturing.project(request, baselines, overrides)

    def _build_data_insufficient(
        self,
        request: DataInsufficientForecastRequest,
    ) -> ForecastGraph:
        """Publish an explicit blocked graph without creating financial facts."""

        period = request.forecast_periods[-1]
        missing_identity = hashlib.sha256(
            json.dumps(
                list(request.data_snapshot.missing_fields),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        available = self._graph.input_node(
            request,
            node_id="availability.required_inputs",
            label="required financial inputs unavailable",
            quantity=self._graph.quantity(
                Decimal("1"),
                unit="availability_state",
                currency="N/A",
                period=period,
                as_of=request.as_of,
                lineage_refs=(f"Assumption:data_insufficient:{missing_identity}",),
            ),
        )
        blocked, edges = self._graph.derived_node(
            request,
            node_id=f"availability.blocked.{period}",
            kind=ForecastNodeKind.DRIVER,
            label="forecast and valuation blocked",
            period=period,
            unit="availability_state",
            currency="N/A",
            formula=FormulaId.PASSTHROUGH,
            operands=(("value", available, Decimal("1")),),
            probability=Decimal("1"),
        )
        return self._graph.compile(
            self._graph.blueprint(
                request=request,
                template_id="data_insufficient@1",
                routing_explanation=(
                    "Required official financial inputs are missing; forecast and "
                    "valuation remain blocked."
                ),
                nodes=(available, blocked),
                edges=tuple(edges),
            )
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
        first = self._graph.input_node(
            request,
            node_id=f"financial.horizon.{first_period}",
            label=f"financial institution forecast horizon {first_period}",
            quantity=self._graph.quantity(
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
        built_edges: list[ForecastOperandDeclaration] = []
        previous = first
        for period in request.forecast_periods[1:]:
            node, node_edges = self._graph.derived_node(
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
        template_id = "financial_institution_valuation_shell@1"
        routing_explanation = (
            "Routed financial-institution economics to a dedicated regulatory-capital, "
            "clean-surplus, dividend, and residual-income valuation shell. Industrial "
            "FCFF/WACC and manufacturing operating templates are disabled."
        )
        return self._graph.compile(
            self._graph.blueprint(
                request=request,
                template_id=template_id,
                routing_explanation=routing_explanation,
                nodes=nodes,
                edges=edges,
            )
        )

    def _build_biopharma_shell(
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
        opening = request.data_snapshot.company_opening_balance_sheet
        opening_nodes = [
            self._graph.input_node(
                request,
                node_id=f"company.baseline.{metric}.{quantity.period}",
                label=f"company frozen {metric}",
                quantity=quantity,
            )
            for metric, quantity in (
                ("cash", opening.cash),
                ("debt", opening.debt),
            )
        ]
        first = self._graph.input_node(
            request,
            node_id=f"biopharma.horizon.{first_period}",
            label=f"biopharma pipeline forecast horizon {first_period}",
            quantity=self._graph.quantity(
                Decimal("1"),
                unit="count",
                currency="N/A",
                period=first_period,
                as_of=request.as_of,
                lineage_refs=(
                    f"Assumption:biopharma_horizon:{first_period}",
                    f"Assumption:biopharma_scenario_overrides:{override_hash}",
                ),
            ),
        )
        built_nodes = [*opening_nodes, first]
        built_edges: list[ForecastOperandDeclaration] = []
        previous = first
        for period in request.forecast_periods[1:]:
            node, node_edges = self._graph.derived_node(
                request,
                node_id=f"biopharma.horizon.{period}",
                kind=ForecastNodeKind.DRIVER,
                label=f"biopharma pipeline forecast horizon {period}",
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
        template_id = "biopharma_pipeline_valuation_shell@1"
        routing_explanation = (
            "Routed pre-revenue and pipeline-driven biopharma through an asset/indication "
            "event tree, finite rNPV/SOTP, licensing economics, and cash-runway gate. "
            "Ordinary FCFF/WACC and mature-revenue manufacturing templates are disabled."
        )
        return self._graph.compile(
            self._graph.blueprint(
                request=request,
                template_id=template_id,
                routing_explanation=routing_explanation,
                nodes=nodes,
                edges=edges,
            )
        )


__all__ = [
    "CompanyArchetype",
    "CompanyOpeningBalanceSheet",
    "ConditionOperator",
    "DataInsufficientForecastRequest",
    "DataInsufficientSnapshot",
    "DataSnapshot",
    "FormulaId",
    "ForecastAssumption",
    "ForecastCondition",
    "ForecastEdge",
    "ForecastEngine",
    "ForecastGraph",
    "ForecastInvariantError",
    "ForecastNarrativeStatement",
    "ForecastNode",
    "ForecastNodeKind",
    "ForecastQuantity",
    "ForecastRequest",
    "LeadingIndicator",
    "NarrativeBasis",
    "NarrativeCategory",
    "NodeOrigin",
    "Security",
    "SegmentBaseline",
    "SegmentForecastOverride",
    "SnapshotFact",
]
