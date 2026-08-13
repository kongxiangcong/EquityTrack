from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from trading_platform.application.workflow_ledger import (
    SnapshotEvidence,
    SnapshotMemberEvidence,
)
from trading_platform.domain.research_bundle import ResearchEvaluationBundle
from trading_platform.domain.research_evaluation import (
    EvaluationDimension,
    ResearchWorkflowRequest,
)
from trading_platform.domain.research_model_input import (
    exact_model_path,
    model_value_is_valid,
    typed_model_field_failure,
)
from trading_platform.identity import canonical_hash


@dataclass(frozen=True)
class _NodeContract:
    node_id: str
    dependencies: tuple[str, ...]
    output_contract: str
    component: str | None
    dimensions: tuple[EvaluationDimension, ...]
    capability_datasets: tuple[str, ...]
    validators: tuple[str, ...]
    always_required: bool = False


_NODE_CONTRACTS = (
    _NodeContract(
        "evidence_binding",
        (),
        "FrozenCapabilityBinding@1",
        None,
        (EvaluationDimension.SOURCE_QUALITY,),
        ("*",),
        (
            "snapshot_identity",
            "pit_cutoff",
            "source_policy_identity",
            "typed_field_contract",
        ),
        True,
    ),
    _NodeContract(
        "research_core",
        ("evidence_binding",),
        "ResearchRun",
        None,
        (EvaluationDimension.SOURCE_QUALITY,),
        ("*",),
        ("source_manifest_lineage", "typed_input_origin"),
        True,
    ),
    _NodeContract(
        "forecast",
        ("evidence_binding", "research_core"),
        "ResearchComponentResult@1:forecast",
        "forecast",
        (EvaluationDimension.FORECAST,),
        ("research_model_input",),
        (
            "quantity_dimensions",
            "forecast_graph_integrity",
            "forecast_invalidation_conditions",
        ),
    ),
    _NodeContract(
        "scenario_valuation",
        ("evidence_binding", "forecast"),
        "ResearchComponentResult@1:scenario_valuation",
        "scenario_valuation",
        (EvaluationDimension.VALUATION,),
        ("research_model_input",),
        (
            "scenario_partition",
            "method_applicability",
            "equity_bridge_reconciliation",
        ),
    ),
    _NodeContract(
        "valuation_method_route",
        ("research_core", "scenario_valuation"),
        "ResearchComponentResult@1:valuation_method_route",
        "valuation_method_route",
        (EvaluationDimension.VALUATION,),
        ("research_model_input",),
        ("method_local_degradation", "output_permission"),
    ),
    _NodeContract(
        "valuation_simulation_decision",
        ("scenario_valuation", "valuation_method_route"),
        "ResearchComponentResult@1:valuation_simulation_decision",
        "valuation_simulation_decision",
        (EvaluationDimension.VALUATION_SIMULATION,),
        ("research_model_input",),
        (
            "calibration_evidence",
            "dependency_model",
            "convergence_gate",
        ),
    ),
    _NodeContract(
        "recent_trend_assessment",
        ("evidence_binding",),
        "ResearchComponentResult@1:recent_trend_assessment",
        "recent_trend_assessment",
        (EvaluationDimension.MARKET_PATH,),
        ("daily", "trade_cal"),
        ("trading_session_identity", "market_bar_contract"),
    ),
    _NodeContract(
        "market_path_decision",
        (
            "evidence_binding",
            "recent_trend_assessment",
            "valuation_simulation_decision",
        ),
        "ResearchComponentResult@1:market_path_decision",
        "market_path_decision",
        (EvaluationDimension.MARKET_PATH,),
        ("daily", "trade_cal", "market_path_policy"),
        (
            "market_path_parent_binding",
            "a_share_execution_constraints",
            "path_calibration_gate",
        ),
    ),
    _NodeContract(
        "decision_projection",
        (
            "research_core",
            "forecast",
            "scenario_valuation",
            "valuation_method_route",
            "valuation_simulation_decision",
            "recent_trend_assessment",
            "market_path_decision",
        ),
        "ResearchDecisionProjection@1",
        None,
        tuple(EvaluationDimension),
        (),
        (
            "bundle_identity",
            "snapshot_lineage",
            "financial_output_boundary",
        ),
        True,
    ),
)


@dataclass(frozen=True)
class CompiledResearchAnalysisPlan:
    compiler_identity: str
    evaluation_plan_identity: str
    data_snapshot_id: str
    source_policy_identity: str
    snapshot_member_ids: tuple[str, ...]
    capability_binding: Mapping[str, object]
    layers: tuple[tuple[str, ...], ...]
    nodes: tuple[Mapping[str, object], ...]
    schema_version: str = "ResearchAnalysisPlan@1"

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "compiler_identity": self.compiler_identity,
            "evaluation_plan_identity": self.evaluation_plan_identity,
            "data_snapshot_id": self.data_snapshot_id,
            "source_policy_identity": self.source_policy_identity,
            "snapshot_member_ids": list(self.snapshot_member_ids),
            "capability_binding": dict(self.capability_binding),
            "layers": [list(layer) for layer in self.layers],
            "nodes": [dict(node) for node in self.nodes],
        }

    @property
    def identity(self) -> str:
        return "research_analysis_plan_" + canonical_hash(self.canonical_content)[:24]

    def to_dict(self) -> Mapping[str, object]:
        return {
            "plan_identity": self.identity,
            **self.canonical_content,
        }

    def validate_context(
        self,
        *,
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
    ) -> None:
        member_ids = tuple(
            member.normalized_version_id for member in evidence.member_evidence
        )
        if (
            self.evaluation_plan_identity != request.evaluation_plan.identity
            or self.data_snapshot_id != evidence.data_snapshot_id
            or self.source_policy_identity != evidence.source_policy_identity
            or self.snapshot_member_ids != member_ids
        ):
            raise ValueError("RESEARCH_ANALYSIS_PLAN_CONTEXT_MISMATCH")
    def validate_bundle(self, bundle: ResearchEvaluationBundle) -> None:
        if (
            bundle.origin.data_snapshot_id != self.data_snapshot_id
            or bundle.origin.source_policy_identity != self.source_policy_identity
            or bundle.origin.snapshot_member_ids != self.snapshot_member_ids
        ):
            raise ValueError("RESEARCH_ANALYSIS_PLAN_ORIGIN_MISMATCH")
        for node in self.nodes:
            component_name = node.get("component")
            if not isinstance(component_name, str) or not component_name:
                continue
            component = getattr(bundle, component_name, None)
            if component is None or component.component != component_name:
                raise ValueError("RESEARCH_ANALYSIS_PLAN_OUTPUT_INVALID")


class ResearchAnalysisPlanCompiler:
    """Compiles a closed, deterministic plan from frozen capabilities."""

    IDENTITY = "ResearchAnalysisPlanCompiler@1"

    def compile(
        self,
        *,
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
    ) -> CompiledResearchAnalysisPlan:
        member_ids = tuple(
            member.normalized_version_id for member in evidence.member_evidence
        )
        if (
            not member_ids
            or len(member_ids) != len(set(member_ids))
            or evidence.data_snapshot_id != request.data_snapshot_id
        ):
            raise ValueError("RESEARCH_ANALYSIS_CAPABILITY_BINDING_INVALID")
        capability_members = tuple(
            self._capability_member(evidence.scope_id, member)
            for member in evidence.member_evidence
        )
        contract_reasons = self._contract_reasons(
            evidence.scope_id,
            evidence.member_evidence,
        )
        capability_binding = {
            "schema_version": "FrozenCapabilityBinding@1",
            "capability_digest": canonical_hash(
                {
                    "data_snapshot_id": evidence.data_snapshot_id,
                    "source_policy_identity": evidence.source_policy_identity,
                    "requested_date": evidence.requested_date,
                    "effective_session_date": (evidence.effective_session_date),
                    "members": capability_members,
                }
            ),
            "status": "limited" if contract_reasons else "bound",
            "reason_codes": list(contract_reasons),
            "member_count": len(capability_members),
            "datasets": sorted(
                {str(member["dataset"]) for member in capability_members}
            ),
            "typed_field_count": sum(
                len(member["fields"]) for member in capability_members
            ),
        }
        layers = self._layers()
        layer_by_node = {
            node_id: index for index, layer in enumerate(layers) for node_id in layer
        }
        requested_dimensions = set(request.evaluation_plan.required_dimensions)
        node_hashes: dict[str, str] = {}
        nodes: list[Mapping[str, object]] = []
        for contract in _NODE_CONTRACTS:
            relevant_members = self._relevant_members(
                capability_members,
                contract.capability_datasets,
            )
            direct_capability_digest = canonical_hash(
                {
                    "source_policy_identity": evidence.source_policy_identity,
                    "data_snapshot_id": evidence.data_snapshot_id,
                    "requested_date": evidence.requested_date,
                    "effective_session_date": evidence.effective_session_date,
                    "datasets": list(contract.capability_datasets),
                    "members": relevant_members,
                }
            )
            requirement = (
                "required"
                if contract.always_required
                or requested_dimensions.intersection(contract.dimensions)
                else "supporting"
            )
            node_content = {
                "node_id": contract.node_id,
                "layer": layer_by_node[contract.node_id],
                "dependencies": list(contract.dependencies),
                "dependency_hashes": [
                    node_hashes[node_id] for node_id in contract.dependencies
                ],
                "output_contract": contract.output_contract,
                "component": contract.component,
                "dimensions": [dimension.value for dimension in contract.dimensions],
                "requirement": requirement,
                "capability_datasets": list(contract.capability_datasets),
                "direct_capability_digest": direct_capability_digest,
                "validators": list(contract.validators),
            }
            node_hash = canonical_hash(
                {
                    "compiler_identity": self.IDENTITY,
                    "evaluation_plan_identity": (request.evaluation_plan.identity),
                    **node_content,
                }
            )
            node_hashes[contract.node_id] = node_hash
            nodes.append({**node_content, "node_hash": node_hash})
        return CompiledResearchAnalysisPlan(
            compiler_identity=self.IDENTITY,
            evaluation_plan_identity=request.evaluation_plan.identity,
            data_snapshot_id=evidence.data_snapshot_id,
            source_policy_identity=evidence.source_policy_identity,
            snapshot_member_ids=member_ids,
            capability_binding=capability_binding,
            layers=layers,
            nodes=tuple(nodes),
        )

    @staticmethod
    def _capability_member(
        scope_id: str, member: SnapshotMemberEvidence
    ) -> Mapping[str, object]:
        fields = tuple(
            sorted(
                (
                    {
                        **{
                            key: str(field.get(key, ""))
                            for key in (
                                "model_path",
                                "field_name",
                                "subject_id",
                                "semantic_role",
                                "period",
                                "unit",
                                "currency",
                                "confidence",
                            )
                        },
                        "value_hash": canonical_hash(
                            {"value": field.get("value")}
                            if model_value_is_valid(field.get("value"))
                            else {
                                "invalid_type": type(
                                    field.get("value")
                                ).__name__
                            }
                        ),
                    }
                    for field in member.extracted_fields
                ),
                key=lambda item: (
                    item["model_path"],
                    item["field_name"],
                    item["period"],
                ),
            )
        )
        return {
            "member_id": member.normalized_version_id,
            "dataset": member.dataset,
            "source_authority": member.source_authority,
            "quality_status": member.quality_status,
            "available_at": member.available_at,
            "scope_id": scope_id,
            "fields": fields,
        }

    @staticmethod
    def _contract_reasons(
        scope_id: str,
        members: tuple[SnapshotMemberEvidence, ...],
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        paths: set[str] = set()
        for member in members:
            if member.dataset != "research_model_input":
                continue
            for field in member.extracted_fields:
                try:
                    path = exact_model_path(field)
                except ValueError as error:
                    reasons.append(str(error))
                    continue
                field_failure = typed_model_field_failure(
                    field,
                    expected_subject_id=scope_id,
                )
                if field_failure is not None:
                    reasons.append(field_failure)
                if path in paths:
                    reasons.append("RESEARCH_MODEL_INPUT_DUPLICATE")
                paths.add(path)
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _relevant_members(
        members: tuple[Mapping[str, object], ...],
        datasets: tuple[str, ...],
    ) -> tuple[Mapping[str, object], ...]:
        if "*" in datasets:
            return members
        allowed = set(datasets)
        return tuple(member for member in members if str(member["dataset"]) in allowed)

    @staticmethod
    def _layers() -> tuple[tuple[str, ...], ...]:
        remaining = {item.node_id: item for item in _NODE_CONTRACTS}
        completed: set[str] = set()
        layers: list[tuple[str, ...]] = []
        while remaining:
            layer = tuple(
                node_id
                for node_id, contract in remaining.items()
                if set(contract.dependencies).issubset(completed)
            )
            if not layer:
                raise ValueError("RESEARCH_ANALYSIS_PLAN_CYCLE")
            layers.append(layer)
            completed.update(layer)
            for node_id in layer:
                remaining.pop(node_id)
        return tuple(layers)


__all__ = [
    "CompiledResearchAnalysisPlan",
    "ResearchAnalysisPlanCompiler",
]
