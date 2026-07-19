from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from ..evidence import period_rank
from ..financial import valuation_decimal_context
from .evidence import (
    ForecastAssumption,
    ForecastInvariantError,
    ForecastNarrativeStatement,
    ForecastQuantity,
    ForecastRequest,
    decimal_text,
    merge_lineage,
    require_decimal,
)


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


@dataclass(frozen=True)
class ForecastNodeDeclaration:
    """Minimal semantic input from which the compiler owns node policy."""

    node_id: str
    kind: ForecastNodeKind
    origin: NodeOrigin
    label: str
    quantity: ForecastQuantity
    conditional_probability: Decimal

    @property
    def lineage_refs(self) -> tuple[str, ...]:
        return self.quantity.lineage_refs


@dataclass(frozen=True)
class ForecastOperandDeclaration:
    """Named dependency declaration awaiting edge construction."""

    source: ForecastNodeDeclaration
    target_id: str
    formula_id: FormulaId
    operand_role: str
    coefficient: Decimal
    period_rule: str
    currency_rule: str


@dataclass(frozen=True)
class ForecastEquation:
    """One derived target and its complete named operand declaration."""

    target: ForecastNodeDeclaration
    operands: tuple[ForecastOperandDeclaration, ...]


@dataclass(frozen=True)
class ForecastBlueprint:
    """Package-private input quantities and derived equations for one graph."""

    request: ForecastRequest
    template_id: str
    routing_explanation: str
    inputs: tuple[ForecastNodeDeclaration, ...]
    equations: tuple[ForecastEquation, ...]


class ForecastGraphCompiler:
    """Compile typed inputs and equations into replayable graph nodes and edges."""

    def blueprint(
        self,
        *,
        request: ForecastRequest,
        template_id: str,
        routing_explanation: str,
        nodes: tuple[ForecastNodeDeclaration, ...],
        edges: tuple[ForecastOperandDeclaration, ...],
    ) -> ForecastBlueprint:
        incoming: dict[str, list[ForecastOperandDeclaration]] = {
            node.node_id: [] for node in nodes
        }
        for edge in edges:
            if edge.target_id not in incoming:
                raise ForecastInvariantError(
                    "FORECAST_EDGE_NODE_MISSING",
                    "Forecast equation targets must resolve inside the blueprint.",
                )
            incoming[edge.target_id].append(edge)
        inputs = tuple(node for node in nodes if node.origin == NodeOrigin.INPUT)
        equations = tuple(
            ForecastEquation(target=node, operands=tuple(incoming[node.node_id]))
            for node in nodes
            if node.origin == NodeOrigin.DERIVED
        )
        if any(not equation.operands for equation in equations):
            raise ForecastInvariantError(
                "FORECAST_DERIVED_FORMULA_MISSING",
                "Every derived blueprint declaration requires named operands.",
            )
        return ForecastBlueprint(
            request=request,
            template_id=template_id,
            routing_explanation=routing_explanation,
            inputs=inputs,
            equations=equations,
        )

    def compile(
        self,
        blueprint: ForecastBlueprint,
    ) -> ForecastGraph:
        request = blueprint.request
        declarations = blueprint.inputs + tuple(
            equation.target for equation in blueprint.equations
        )
        leading_by_target = {
            equation.target.node_id: equation.operands[0].source
            for equation in blueprint.equations
        }
        nodes = tuple(
            self._materialize_node(
                request,
                item,
                leading=leading_by_target.get(item.node_id),
            )
            for item in declarations
        )
        edges = tuple(
            ForecastEdge(
                source_id=item.source.node_id,
                target_id=item.target_id,
                formula_id=item.formula_id,
                operand_role=item.operand_role,
                coefficient=item.coefficient,
                source_unit=item.source.quantity.unit,
                source_scale=item.source.quantity.scale,
                target_unit=equation.target.quantity.unit,
                target_scale=equation.target.quantity.scale,
                period_rule=item.period_rule,
                currency_rule=item.currency_rule,
            )
            for equation in blueprint.equations
            for item in equation.operands
        )
        return ForecastGraph(
            graph_id=ForecastGraphIdentity.build(
                request=request,
                template_id=blueprint.template_id,
                routing_explanation=blueprint.routing_explanation,
                nodes=nodes,
                edges=edges,
            ),
            security_id=request.security.security_id,
            data_snapshot_id=request.data_snapshot.snapshot_id,
            template_id=blueprint.template_id,
            routing_explanation=blueprint.routing_explanation,
            nodes=nodes,
            edges=edges,
            assumptions=request.assumptions,
            narrative_statements=request.narrative_statements,
        )
    @staticmethod
    def quantity(
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
        leading: ForecastNodeDeclaration | None,
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
                return self.quantity(
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

    def _materialize_node(
        self,
        request: ForecastRequest,
        declaration: ForecastNodeDeclaration,
        *,
        leading: ForecastNodeDeclaration | None,
    ) -> ForecastNode:
        indicators, triggers, invalidations = self._monitoring(
            node_id=declaration.node_id,
            quantity=declaration.quantity,
            leading=leading,
        )
        action = "Observe" if declaration.origin == NodeOrigin.INPUT else "Validate"
        return ForecastNode(
            node_id=declaration.node_id,
            kind=declaration.kind,
            origin=declaration.origin,
            label=declaration.label,
            quantity=declaration.quantity,
            horizon=declaration.quantity.period,
            milestone=f"{action} {declaration.label} by {request.review_date}",
            leading_indicators=indicators,
            trigger_conditions=triggers,
            invalidation_conditions=invalidations,
            review_date=request.review_date,
            conditional_probability=declaration.conditional_probability,
            lineage_refs=declaration.quantity.lineage_refs,
        )

    def input_node(
        self,
        request: ForecastRequest,
        *,
        node_id: str,
        label: str,
        quantity: ForecastQuantity,
        probability: Decimal = Decimal("1"),
    ) -> ForecastNodeDeclaration:
        return ForecastNodeDeclaration(
            node_id=node_id,
            kind=ForecastNodeKind.DRIVER,
            origin=NodeOrigin.INPUT,
            label=label,
            quantity=quantity,
            conditional_probability=probability,
        )

    def derived_node(
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
        operands: tuple[tuple[str, ForecastNodeDeclaration, Decimal], ...],
        probability: Decimal,
    ) -> tuple[ForecastNodeDeclaration, list[ForecastOperandDeclaration]]:
        operand_values = {
            role: (source.quantity.normalized_value, coefficient)
            for role, source, coefficient in operands
        }
        value = _calculate_formula(formula, operand_values)
        lineage = merge_lineage(*(source.lineage_refs for _, source, _ in operands))
        quantity = self.quantity(
            value,
            unit=unit,
            currency=currency,
            period=period,
            as_of=request.as_of,
            lineage_refs=lineage,
        )
        node = ForecastNodeDeclaration(
            node_id=node_id,
            kind=kind,
            origin=NodeOrigin.DERIVED,
            label=label,
            quantity=quantity,
            conditional_probability=probability,
        )
        edges = [
            ForecastOperandDeclaration(
                source=source,
                target_id=node.node_id,
                formula_id=formula,
                operand_role=role,
                coefficient=coefficient,
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


class ForecastGraphIdentity:
    """Canonical identity policy for newly built Forecast graphs."""

    SCHEMA = "ForecastGraphIdentity@2"

    @classmethod
    def build(
        cls,
        *,
        request: Any,
        template_id: str,
        routing_explanation: str,
        nodes: tuple[ForecastNode, ...],
        edges: tuple[ForecastEdge, ...],
    ) -> str:
        graph_content = ForecastGraph(
            graph_id="fg2_pending",
            security_id=request.security.security_id,
            data_snapshot_id=request.data_snapshot.snapshot_id,
            template_id=template_id,
            routing_explanation=routing_explanation,
            nodes=nodes,
            edges=edges,
            assumptions=request.assumptions,
            narrative_statements=request.narrative_statements,
        ).to_dict()
        graph_content.pop("graph_id")
        semantic_content = {
            "security": request.security.to_dict(),
            "snapshot_id": request.data_snapshot.snapshot_id,
            "snapshot_hash": request.data_snapshot.content_hash,
            "periods": list(request.forecast_periods),
            "review_date": request.review_date,
            "assumption_overrides": [
                item.to_dict() for item in request.assumption_overrides
            ],
            "graph": graph_content,
        }
        payload = {
            "identity_schema": cls.SCHEMA,
            "semantic_content": semantic_content,
        }
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return f"fg2_{digest[:24]}"
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
        require_decimal(self.conditional_probability, "conditional_probability")
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
        require_decimal(self.coefficient, "ForecastEdge.coefficient")
        require_decimal(self.source_scale, "ForecastEdge.source_scale")
        require_decimal(self.target_scale, "ForecastEdge.target_scale")
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
            "coefficient": decimal_text(self.coefficient),
            "source_unit": self.source_unit,
            "source_scale": decimal_text(self.source_scale),
            "target_unit": self.target_unit,
            "target_scale": decimal_text(self.target_scale),
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
    assumptions: tuple[ForecastAssumption, ...] = ()
    narrative_statements: tuple[ForecastNarrativeStatement, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.nodes, tuple) or not isinstance(self.edges, tuple):
            raise ForecastInvariantError(
                "FORECAST_GRAPH_TYPE_INVALID",
                "ForecastGraph nodes and edges must be tuples.",
            )
        if (
            not isinstance(self.narrative_statements, tuple)
            or any(
                not isinstance(item, ForecastNarrativeStatement)
                for item in self.narrative_statements
            )
        ):
            raise ForecastInvariantError(
                "FORECAST_NARRATIVE_INVALID",
                "ForecastGraph narrative statements must remain typed.",
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
                expected_lineage = merge_lineage(
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
            "assumptions": [item.to_dict() for item in self.assumptions],
            "narrative_statements": [
                item.to_dict() for item in self.narrative_statements
            ],
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
                            "scale": decimal_text(indicator.scale),
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
                    "conditional_probability": decimal_text(
                        node.conditional_probability
                    ),
                    "lineage_refs": list(node.lineage_refs),
                }
                for node in self.nodes
            ],
            "edges": [edge.to_dict() for edge in self.edges],
        }
