from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping


class WorkflowStatus(str, Enum):
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_LIMITS = "succeeded_with_limits"
    FAILED = "failed"


class ReferenceDisposition(str, Enum):
    CREATED = "created"
    REUSED = "reused"
    INPUT = "input"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _contains_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, Mapping):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_float(item) for item in value)
    return False


def simulation_fallback_matches_valuation(
    fallback: Mapping[str, Any],
    valuation_payload: Mapping[str, Any],
) -> bool:
    def comparable_decimal(value: Any) -> str:
        try:
            rendered = format(
                Decimal(str(value)).quantize(Decimal("0.000000000001")),
                "f",
            ).rstrip("0").rstrip(".")
        except (InvalidOperation, ValueError):
            return ""
        return rendered or "0"

    scenarios = valuation_payload.get("scenarios")
    if not isinstance(scenarios, list):
        return False
    scenario = next(
        (
            item
            for item in scenarios
            if isinstance(item, Mapping)
            and item.get("scenario_id") == fallback.get("scenario_id")
        ),
        None,
    )
    methods = scenario.get("methods") if isinstance(scenario, Mapping) else None
    if not isinstance(methods, list):
        return False
    method = next(
        (
            item
            for item in methods
            if isinstance(item, Mapping)
            and item.get("method_id") == fallback.get("method_id")
        ),
        None,
    )
    if (
        not isinstance(method, Mapping)
        or method.get("status") != "ready"
        or method.get("formula_version") != fallback.get("formula_version")
    ):
        return False
    value_range = method.get("conditional_value_range")
    if not isinstance(value_range, Mapping):
        return False
    for label in ("low", "base", "high"):
        item = value_range.get(label)
        quantity = item.get("per_share_value") if isinstance(item, Mapping) else None
        if (
            not isinstance(quantity, Mapping)
            or comparable_decimal(
                quantity.get("normalized_value", quantity.get("value"))
            )
            != comparable_decimal(fallback.get(label))
            or quantity.get("unit") != fallback.get("unit")
            or quantity.get("currency") != fallback.get("currency")
            or quantity.get("period") != fallback.get("period")
        ):
            return False
    return True


def forecast_structure_identity(value: Mapping[str, Any]) -> str:
    """Hash scenario-invariant forecast topology without forecasted values."""

    nodes = value.get("nodes")
    edges = value.get("edges")
    template_id = value.get("template_id")
    if (
        not isinstance(template_id, str)
        or not template_id.strip()
        or not isinstance(nodes, list)
        or not nodes
        or not isinstance(edges, list)
        or not edges
        or any(not isinstance(item, Mapping) for item in (*nodes, *edges))
    ):
        raise ValueError("RESEARCH_ARTIFACT_FORECAST_STRUCTURE_INVALID")
    node_fields = ("node_id", "kind", "origin")
    edge_fields = (
        "source_id",
        "target_id",
        "formula_id",
        "operand_role",
        "source_unit",
        "source_scale",
        "target_unit",
        "target_scale",
        "period_rule",
        "currency_rule",
    )
    node_topology = [
        {name: node.get(name) for name in node_fields}
        for node in nodes
    ]
    edge_topology = [
        {name: edge.get(name) for name in edge_fields}
        for edge in edges
    ]
    if (
        any(
            not isinstance(item[name], str) or not item[name]
            for item in (*node_topology, *edge_topology)
            for name in item
        )
        or len({item["node_id"] for item in node_topology}) != len(node_topology)
    ):
        raise ValueError("RESEARCH_ARTIFACT_FORECAST_STRUCTURE_INVALID")
    identity = {
        "template_id": template_id,
        "nodes": sorted(node_topology, key=lambda item: item["node_id"]),
        "edges": sorted(
            edge_topology,
            key=lambda item: (
                item["source_id"],
                item["target_id"],
                item["formula_id"],
                item["operand_role"],
            ),
        ),
    }
    return "forecast-structure:" + hashlib.sha256(
        _canonical_json(identity).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, init=False)
class ImmutableArtifactDraft:
    """Canonical, factory-only handoff from typed models to persistence."""

    artifact_kind: str
    schema_version: str
    subject_id: str
    as_of: str
    source_identity: str
    model_identity: str
    policy_identity: str
    status: str
    formula_identities: tuple[str, ...]
    dependency_kinds: tuple[str, ...]
    payload_json: str
    summary_json: str
    content_hash: str

    def __init__(self, *_: Any, **__: Any) -> None:
        raise TypeError("Use an ImmutableArtifactDraft typed factory.")

    @classmethod
    def from_data_snapshot(
        cls,
        snapshot: Any,
        *,
        model_identity: str,
        policy_identity: str,
    ) -> ImmutableArtifactDraft:
        from equity_research import DataSnapshot

        if not isinstance(snapshot, DataSnapshot):
            raise TypeError("from_data_snapshot requires a typed DataSnapshot.")
        return cls._build(
            artifact_kind="DataSnapshot",
            schema_version="DataSnapshotArtifact@1",
            subject_id=snapshot.security_id,
            as_of=snapshot.as_of,
            source_identity=snapshot.snapshot_id,
            model_identity=model_identity,
            policy_identity=policy_identity,
            status="ready",
            formula_identities=("data_snapshot_content_hash@1",),
            dependency_kinds=(),
            payload=snapshot.to_dict(),
            summary={
                "snapshot_id": snapshot.snapshot_id,
                "content_hash": snapshot.content_hash,
                "fact_count": len(snapshot.facts),
            },
        )

    @classmethod
    def from_forecast_graph(
        cls,
        graph: Any,
        *,
        model_identity: str,
        policy_identity: str,
    ) -> ImmutableArtifactDraft:
        from equity_research import ForecastGraph

        if not isinstance(graph, ForecastGraph):
            raise TypeError("from_forecast_graph requires a typed ForecastGraph.")
        formulas = tuple(
            sorted(
                {
                    getattr(edge.formula_id, "value", str(edge.formula_id))
                    for edge in graph.edges
                }
            )
        )
        graph_as_of_dates = {node.quantity.as_of for node in graph.nodes}
        if len(graph_as_of_dates) != 1:
            raise ValueError("RESEARCH_ARTIFACT_FORECAST_AS_OF_INVALID")
        return cls._build(
            artifact_kind="Forecast",
            schema_version="ForecastArtifact@1",
            subject_id=graph.security_id,
            as_of=next(iter(graph_as_of_dates)),
            source_identity=graph.graph_id,
            model_identity=model_identity,
            policy_identity=policy_identity,
            status="ready",
            formula_identities=formulas,
            dependency_kinds=("DataSnapshot",),
            payload=graph.to_dict(),
            summary={
                "graph_id": graph.graph_id,
                "data_snapshot_id": graph.data_snapshot_id,
                "template_id": graph.template_id,
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
            },
        )

    @classmethod
    def from_scenario_valuation(
        cls,
        result: Any,
        *,
        forecast_graph: Any,
        model_identity: str,
        policy_identity: str,
    ) -> ImmutableArtifactDraft:
        from equity_research import DeterministicScenarioResult, ForecastGraph

        if not isinstance(result, DeterministicScenarioResult) or not isinstance(
            forecast_graph, ForecastGraph
        ):
            raise TypeError(
                "from_scenario_valuation requires typed scenario and forecast results."
            )
        graphs = tuple(scenario.forecast_graph for scenario in result.scenarios)
        forecast_structure = forecast_structure_identity(forecast_graph.to_dict())
        scenario_structures = {
            forecast_structure_identity(graph.to_dict()) for graph in graphs
        }
        subjects = {graph.security_id for graph in graphs}
        model_snapshot_identities = {graph.data_snapshot_id for graph in graphs}
        as_of_dates = {
            node.quantity.as_of
            for graph in graphs
            for node in graph.nodes
        }
        if (
            not graphs
            or len(subjects) != 1
            or len(model_snapshot_identities) != 1
            or len(as_of_dates) != 1
            or forecast_graph.security_id not in subjects
            or forecast_graph.data_snapshot_id not in model_snapshot_identities
            or {
                node.quantity.as_of for node in forecast_graph.nodes
            }
            != as_of_dates
            or scenario_structures != {forecast_structure}
        ):
            raise ValueError("RESEARCH_ARTIFACT_VALUATION_LINEAGE_INVALID")
        source_identity = "deterministic-scenario-set:" + hashlib.sha256(
            _canonical_json(
                {
                    "forecast_graph_identity": forecast_graph.graph_id,
                    "forecast_structure_identity": forecast_structure,
                    "forecast_graph_ids": [graph.graph_id for graph in graphs],
                    "model_data_snapshot_identity": next(
                        iter(model_snapshot_identities)
                    ),
                }
            ).encode("utf-8")
        ).hexdigest()
        methods = tuple(
            method
            for scenario in result.scenarios
            for method in scenario.methods
        )
        formulas = tuple(sorted({method.formula_version for method in methods}))
        status = "ready" if all(method.status == "ready" for method in methods) else "partial"
        return cls._build(
            artifact_kind="Valuation",
            schema_version="ValuationArtifact@1",
            subject_id=next(iter(subjects)),
            as_of=next(iter(as_of_dates)),
            source_identity=source_identity,
            model_identity=model_identity,
            policy_identity=policy_identity,
            status=status,
            formula_identities=formulas,
            dependency_kinds=("Forecast",),
            payload=result.to_dict(),
            summary={
                "probability_mode": result.probability_mode,
                "forecast_graph_identity": forecast_graph.graph_id,
                "forecast_structure_identity": forecast_structure,
                "model_data_snapshot_identity": next(
                    iter(model_snapshot_identities)
                ),
                "scenario_count": len(result.scenarios),
                "ready_method_count": sum(
                    method.status == "ready" for method in methods
                ),
                "blocked_method_count": sum(
                    method.status == "blocked" for method in methods
                ),
            },
        )

    @classmethod
    def from_valuation_simulation(
        cls,
        result: Any,
        *,
        valuation_artifact: ImmutableArtifactDraft,
        model_identity: str,
        policy_identity: str,
    ) -> ImmutableArtifactDraft:
        from equity_research import ValuationSimulationResult

        if not isinstance(result, ValuationSimulationResult) or not isinstance(
            valuation_artifact, ImmutableArtifactDraft
        ):
            raise TypeError(
                "from_valuation_simulation requires a typed simulation result "
                "and valuation artifact."
            )
        if (
            valuation_artifact.artifact_kind != "Valuation"
            or result.security_id != valuation_artifact.subject_id
            or result.as_of != valuation_artifact.as_of
            or result.valuation_source_identity
            != valuation_artifact.source_identity
        ):
            raise ValueError("RESEARCH_ARTIFACT_SIMULATION_LINEAGE_INVALID")
        if not simulation_fallback_matches_valuation(
            result.deterministic_fallback,
            valuation_artifact.payload,
        ):
            raise ValueError("RESEARCH_ARTIFACT_SIMULATION_FALLBACK_INVALID")
        source_identity = "valuation-simulation:" + hashlib.sha256(
            _canonical_json(
                {
                    "simulation_id": result.simulation_id,
                    "valuation_input_fingerprint": valuation_artifact.content_hash,
                    "simulation_model_identity": result.model_identity,
                    "simulation_policy_identity": result.policy_identity,
                    "assumptions": [
                        item.to_dict() for item in result.assumptions
                    ],
                    "dependency_model": result.dependency_model.to_dict(),
                    "valuation_model": result.valuation_model.to_dict(),
                    "deterministic_fallback": result.deterministic_fallback,
                    "tail_threshold": result.tail_threshold,
                    "budget": result.budget.to_dict(),
                }
            ).encode("utf-8")
        ).hexdigest()
        return cls._build(
            artifact_kind="Simulation",
            schema_version="ValuationSimulationArtifact@1",
            subject_id=result.security_id,
            as_of=result.as_of,
            source_identity=source_identity,
            model_identity=model_identity,
            policy_identity=policy_identity,
            status=result.status,
            formula_identities=tuple(
                sorted(
                    {
                        result.valuation_model.formula_id,
                        result.dependency_model.model_identity,
                        result.budget.rng_algorithm,
                        "variance_euler_linear@1",
                    }
                )
            ),
            dependency_kinds=("Valuation",),
            payload=result.to_dict(),
            summary={
                "simulation_id": result.simulation_id,
                "valuation_source_identity": valuation_artifact.source_identity,
                "valuation_input_fingerprint": valuation_artifact.content_hash,
                "converged": result.converged,
                "sample_budget": result.budget.sample_budget,
                "completed_samples": result.completed_samples,
                "invalid_path_rate": result.invalid_path_rate,
                "rng_algorithm": result.budget.rng_algorithm,
                "seed": result.budget.seed,
            },
        )

    @classmethod
    def from_market_data_snapshot(
        cls,
        calibration: Any,
        *,
        security_id: str,
        model_identity: str,
        policy_identity: str,
    ) -> ImmutableArtifactDraft:
        from equity_research import MarketPathCalibration

        if not isinstance(calibration, MarketPathCalibration):
            raise TypeError(
                "from_market_data_snapshot requires a typed market calibration."
            )
        payload = calibration.to_dict()
        source_identity = "market-data-snapshot:" + hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()
        return cls._build(
            artifact_kind="MarketDataSnapshot",
            schema_version="MarketDataSnapshotArtifact@1",
            subject_id=security_id,
            as_of=calibration.as_of,
            source_identity=source_identity,
            model_identity=model_identity,
            policy_identity=policy_identity,
            status="ready",
            formula_identities=("market_calibration_content_hash@1",),
            dependency_kinds=(),
            payload=payload,
            summary={
                "snapshot_id": calibration.snapshot_id,
                "market": calibration.market,
                "market_timezone": calibration.market_timezone,
                "series_identity": calibration.series_identity,
                "trading_calendar_identity": (
                    calibration.trading_calendar_identity
                ),
                "observation_count": len(calibration.observations),
            },
        )

    @classmethod
    def from_market_path_simulation(
        cls,
        result: Any,
        *,
        valuation_simulation_artifact: ImmutableArtifactDraft,
        market_data_snapshot_artifact: ImmutableArtifactDraft,
        model_identity: str,
        policy_identity: str,
    ) -> ImmutableArtifactDraft:
        from equity_research import MarketPathEngine, MarketPathResult

        if (
            not isinstance(result, MarketPathResult)
            or not isinstance(
                valuation_simulation_artifact,
                ImmutableArtifactDraft,
            )
            or not isinstance(
                market_data_snapshot_artifact,
                ImmutableArtifactDraft,
            )
        ):
            raise TypeError(
                "from_market_path_simulation requires a typed market-path "
                "result, Simulation artifact, and market-data snapshot."
            )
        fallback = valuation_simulation_artifact.payload.get(
            "deterministic_fallback"
        )
        execution_period = (
            f"T+{result.constraints.minimum_execution_lag_sessions} "
            "trading sessions"
        )
        terminal_period = (
            "T+"
            f"{result.constraints.minimum_execution_lag_sessions + result.budget.horizon_sessions} "
            "trading sessions"
        )
        risk_horizon_period = (
            f"T+{result.constraints.minimum_execution_lag_sessions} through "
            "T+"
            f"{result.constraints.minimum_execution_lag_sessions + result.budget.horizon_sessions} "
            "trading sessions"
        )
        if (
            valuation_simulation_artifact.artifact_kind != "Simulation"
            or market_data_snapshot_artifact.artifact_kind
            != "MarketDataSnapshot"
            or result.security_id != valuation_simulation_artifact.subject_id
            or result.security_id != market_data_snapshot_artifact.subject_id
            or result.as_of != valuation_simulation_artifact.as_of
            or result.as_of != market_data_snapshot_artifact.as_of
            or result.valuation_simulation_source_identity
            != valuation_simulation_artifact.source_identity
            or result.calibration.to_dict()
            != market_data_snapshot_artifact.payload
            or not isinstance(fallback, Mapping)
            or result.price_unit != fallback.get("unit")
            or result.currency != fallback.get("currency")
            or result.interpretation != MarketPathEngine.INTERPRETATION
            or result.horizon_return_basis
            != "net_of_declared_round_trip_transaction_costs"
            or result.execution_period != execution_period
            or result.terminal_period != terminal_period
            or result.risk_horizon_period != risk_horizon_period
            or {
                item.adjustment_factor
                for item in result.calibration.observations
            }
            != {Decimal("1")}
            or any(
                item.corporate_action_identity
                for item in result.calibration.observations
            )
            or result.calibration.adjustment_member_ids
            or result.calibration.corporate_action_member_ids
        ):
            raise ValueError("RESEARCH_ARTIFACT_MARKET_PATH_LINEAGE_INVALID")
        source_value = {
            "simulation_id": result.simulation_id,
            "as_of_at": result.as_of_at,
            "valuation_simulation_input_fingerprint": (
                valuation_simulation_artifact.content_hash
            ),
            "market_data_snapshot_identity": (
                market_data_snapshot_artifact.source_identity
            ),
            "market_data_input_fingerprint": (
                market_data_snapshot_artifact.content_hash
            ),
            "market_path_model_identity": result.model_identity,
            "market_path_policy_identity": result.policy_identity,
            "price_unit": result.price_unit,
            "currency": result.currency,
            "calibration": result.calibration.to_dict(),
            "constraints": result.constraints.to_dict(),
            "budget": result.budget.to_dict(),
            "starting_price": result.starting_price,
            "starting_price_session": result.starting_price_session,
            "starting_price_member_id": result.starting_price_member_id,
            "starting_price_available_at": result.starting_price_available_at,
            "starting_price_evidence_refs": list(
                result.starting_price_evidence_refs
            ),
            "current_market_state": result.current_market_state,
            "current_state_available_at": result.current_state_available_at,
            "current_state_evidence_refs": list(
                result.current_state_evidence_refs
            ),
            "price_thresholds": list(result.price_thresholds),
            "tail_return_threshold": result.tail_return_threshold,
        }
        source_identity = "market-path-simulation:" + hashlib.sha256(
            _canonical_json(source_value).encode("utf-8")
        ).hexdigest()
        return cls._build(
            artifact_kind="MarketPathSimulation",
            schema_version="MarketPathSimulationArtifact@1",
            subject_id=result.security_id,
            as_of=result.as_of,
            source_identity=source_identity,
            model_identity=model_identity,
            policy_identity=policy_identity,
            status=result.status,
            formula_identities=tuple(
                sorted(
                    {
                        result.model_identity,
                        result.constraints.policy_identity,
                        result.budget.rng_algorithm,
                    }
                )
            ),
            dependency_kinds=("Simulation", "MarketDataSnapshot"),
            payload=result.to_dict(),
            summary={
                "simulation_id": result.simulation_id,
                "valuation_simulation_source_identity": (
                    valuation_simulation_artifact.source_identity
                ),
                "valuation_simulation_input_fingerprint": (
                    valuation_simulation_artifact.content_hash
                ),
                "market_data_snapshot_identity": (
                    market_data_snapshot_artifact.source_identity
                ),
                "market_data_input_fingerprint": (
                    market_data_snapshot_artifact.content_hash
                ),
                "completed_paths": result.completed_paths,
                "market_state": result.current_market_state,
                "interpretation": result.interpretation,
            },
        )

    @classmethod
    def from_serialized(cls, value: Mapping[str, Any]) -> ImmutableArtifactDraft:
        required = {
            "artifact_kind",
            "schema_version",
            "subject_id",
            "as_of",
            "source_identity",
            "model_identity",
            "policy_identity",
            "status",
            "formula_identities",
            "dependency_kinds",
            "payload_json",
            "summary_json",
            "content_hash",
        }
        if set(value) != required:
            raise ValueError("RESEARCH_ARTIFACT_DRAFT_SCHEMA_INVALID")
        if not isinstance(value["formula_identities"], list) or not isinstance(
            value["dependency_kinds"], list
        ):
            raise ValueError("RESEARCH_ARTIFACT_DRAFT_SCHEMA_INVALID")
        instance = cls._from_fields(
            artifact_kind=str(value["artifact_kind"]),
            schema_version=str(value["schema_version"]),
            subject_id=str(value["subject_id"]),
            as_of=str(value["as_of"]),
            source_identity=str(value["source_identity"]),
            model_identity=str(value["model_identity"]),
            policy_identity=str(value["policy_identity"]),
            status=str(value["status"]),
            formula_identities=tuple(value["formula_identities"]),
            dependency_kinds=tuple(value["dependency_kinds"]),
            payload_json=str(value["payload_json"]),
            summary_json=str(value["summary_json"]),
        )
        if instance.content_hash != value["content_hash"]:
            raise ValueError("RESEARCH_ARTIFACT_DRAFT_HASH_MISMATCH")
        return instance

    @classmethod
    def _build(cls, *, payload: Mapping[str, Any], summary: Mapping[str, Any], **identity: Any) -> ImmutableArtifactDraft:
        if _contains_float(payload) or _contains_float(summary):
            raise ValueError("RESEARCH_ARTIFACT_BINARY_FLOAT_FORBIDDEN")
        return cls._from_fields(
            **identity,
            payload_json=_canonical_json(payload),
            summary_json=_canonical_json(summary),
        )

    @classmethod
    def _from_fields(cls, **fields: Any) -> ImmutableArtifactDraft:
        dependency_contracts = {
            "DataSnapshot": (),
            "Forecast": ("DataSnapshot",),
            "Valuation": ("Forecast",),
            "Simulation": ("Valuation",),
            "MarketDataSnapshot": (),
            "MarketPathSimulation": ("Simulation", "MarketDataSnapshot"),
            "ForecastReview": ("Forecast",),
        }
        if (
            not all(
                str(fields[name]).strip()
                for name in (
                    "artifact_kind",
                    "schema_version",
                    "subject_id",
                    "as_of",
                    "source_identity",
                    "model_identity",
                    "policy_identity",
                    "status",
                    "payload_json",
                    "summary_json",
                )
            )
            or fields["status"] not in {"ready", "partial", "blocked"}
            or not fields["formula_identities"]
            or fields["artifact_kind"] not in dependency_contracts
            or fields["dependency_kinds"]
            != dependency_contracts[fields["artifact_kind"]]
        ):
            raise ValueError("RESEARCH_ARTIFACT_DRAFT_IDENTITY_INVALID")
        payload = json.loads(fields["payload_json"])
        summary = json.loads(fields["summary_json"])
        if (
            not isinstance(payload, Mapping)
            or not isinstance(summary, Mapping)
            or _contains_float(payload)
            or _contains_float(summary)
            or _canonical_json(payload) != fields["payload_json"]
            or _canonical_json(summary) != fields["summary_json"]
            or any(
                not isinstance(item, str) or not item.strip()
                for item in (
                    *fields["formula_identities"],
                    *fields["dependency_kinds"],
                )
            )
            or len(fields["formula_identities"])
            != len(set(fields["formula_identities"]))
        ):
            raise ValueError("RESEARCH_ARTIFACT_DRAFT_CONTENT_INVALID")
        canonical = _canonical_json(fields)
        instance = object.__new__(cls)
        for name, item in fields.items():
            object.__setattr__(instance, name, item)
        object.__setattr__(instance, "content_hash", hashlib.sha256(canonical.encode()).hexdigest())
        return instance

    @property
    def payload(self) -> Mapping[str, Any]:
        return json.loads(self.payload_json)

    @property
    def summary(self) -> Mapping[str, Any]:
        return json.loads(self.summary_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_kind": self.artifact_kind,
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
            "as_of": self.as_of,
            "source_identity": self.source_identity,
            "model_identity": self.model_identity,
            "policy_identity": self.policy_identity,
            "status": self.status,
            "formula_identities": list(self.formula_identities),
            "dependency_kinds": list(self.dependency_kinds),
            "payload_json": self.payload_json,
            "summary_json": self.summary_json,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FieldSemantics:
    source_id: str
    source_authority: str
    field_name: str
    period: str
    statement_scope: str
    unit: str
    currency: str
    scale: str
    restatement_status: str
    published_at: str
    available_at: str
    retrieved_at: str
    supersedes_identity: str | None = None
    availability_basis: str = "publisher_timestamp"


@dataclass(frozen=True)
class ResearchProjection:
    manifest: Mapping[str, Any]
    estimates: Mapping[str, Any] | None
    context: Mapping[str, Any] | None
    as_of_date: str
    profile: str
    field_semantics: tuple[FieldSemantics, ...]
    diluted_share_identity: str
    net_debt_bridge_identity: str


@dataclass(frozen=True)
class ResearchWorkflowRequest:
    invocation_id: str
    security_id: str
    requested_date: str
    effective_session_date: str
    projection: ResearchProjection
    workflow_snapshot_id: str | None = None
    candidate_member_ids: tuple[str, ...] = ()
    market_only_member_ids: tuple[str, ...] = ()
    analysis_artifacts: tuple[ImmutableArtifactDraft, ...] = ()


@dataclass(frozen=True)
class ResearchWorkflowResult:
    workflow_run_id: str
    research_run_id: str
    research_snapshot_id: str
    workflow_snapshot_id: str | None
    final_manifest_id: str
    disposition: ReferenceDisposition
    reason_code: str
    stale_by_days: int
    json_artifact_id: str
    html_artifact_id: str
    artifact_record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowHistory:
    workflow_run_id: str
    status: str
    refs: tuple[Mapping[str, str], ...]
    attempts: tuple[Mapping[str, Any], ...]
    transitions: tuple[Mapping[str, Any], ...]
    reuse_decision: Mapping[str, Any]
    final_manifest_id: str


@dataclass(frozen=True)
class ArtifactManifestView:
    artifact_manifest_id: str
    manifest_role: str
    producer_type: str
    producer_id: str
    membership_hash: str
    members: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ResearchArtifactView:
    artifact_record_id: str
    artifact_kind: str
    schema_version: str
    research_run_id: str
    data_snapshot_id: str
    model_data_snapshot_identity: str
    platform_security_id: str
    subject_id: str
    as_of: str
    source_identity: str
    model_identity: str
    formula_identities: tuple[str, ...]
    code_identity: str
    policy_identity: str
    status: str
    content_hash: str
    dependency_record_ids: tuple[str, ...]
    summary: Mapping[str, Any]
    payload: Mapping[str, Any]
