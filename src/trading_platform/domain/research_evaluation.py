from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Mapping

from trading_platform.domain.research_bundle import (
    verify_research_evaluation_bundle,
)
from trading_platform.domain.research_decision_projection import (
    project_research_decision,
)
from trading_platform.domain.workflow import ReferenceDisposition
from trading_platform.identity import canonical_hash

RESEARCH_EVALUATION_POLICY_IDENTITY = "ResearchEvaluationPolicy@3"


class EvaluationPurpose(str, Enum):
    COMPANY_OUTLOOK = "company_outlook"
    VALUATION_REVIEW = "valuation_review"
    PORTFOLIO_REVIEW = "portfolio_review"


class EvaluationDimension(str, Enum):
    SOURCE_QUALITY = "source_quality"
    FORECAST = "forecast"
    VALUATION = "valuation"
    VALUATION_SIMULATION = "valuation_simulation"
    MARKET_PATH = "market_path"


class StrategyValidationSelection(str, Enum):
    NOT_REQUESTED = "not_requested"
    REQUESTED_UNAVAILABLE = "requested_unavailable"


class DegradationPolicy(str, Enum):
    FAIL_CLOSED = "fail_closed"
    ALLOW_DATA_INSUFFICIENT = "allow_data_insufficient"


@dataclass(frozen=True)
class EvaluationHorizon:
    as_of: str
    forecast_end: str
    review_by: str

    def __post_init__(self) -> None:
        try:
            as_of = date.fromisoformat(self.as_of)
            forecast_end = date.fromisoformat(self.forecast_end)
            review_by = date.fromisoformat(self.review_by)
        except ValueError:
            raise ValueError("RESEARCH_EVALUATION_HORIZON_INVALID") from None
        if forecast_end < as_of or review_by < as_of:
            raise ValueError("RESEARCH_EVALUATION_HORIZON_INVALID")


@dataclass(frozen=True)
class ResearchEvaluationPlan:
    schema_version: str
    purpose: EvaluationPurpose
    horizon: EvaluationHorizon
    required_dimensions: tuple[EvaluationDimension, ...]
    strategy_validation: StrategyValidationSelection
    degradation_policy: DegradationPolicy = (
        DegradationPolicy.ALLOW_DATA_INSUFFICIENT
    )

    def __post_init__(self) -> None:
        if self.schema_version != "ResearchEvaluationPlan@1":
            raise ValueError("RESEARCH_EVALUATION_PLAN_SCHEMA_INVALID")
        if not self.required_dimensions:
            raise ValueError("RESEARCH_EVALUATION_DIMENSIONS_REQUIRED")
        if len(set(self.required_dimensions)) != len(
            self.required_dimensions
        ):
            raise ValueError("RESEARCH_EVALUATION_DIMENSION_DUPLICATE")

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "purpose": self.purpose.value,
            "horizon": {
                "as_of": self.horizon.as_of,
                "forecast_end": self.horizon.forecast_end,
                "review_by": self.horizon.review_by,
            },
            "required_dimensions": [
                dimension.value for dimension in self.required_dimensions
            ],
            "strategy_validation": self.strategy_validation.value,
            "degradation_policy": self.degradation_policy.value,
        }

    @property
    def identity(self) -> str:
        return (
            "evaluation_plan_"
            + canonical_hash(self.canonical_content)[:24]
        )

    @property
    def strategy_reason_code(self) -> str | None:
        if (
            self.strategy_validation
            is StrategyValidationSelection.REQUESTED_UNAVAILABLE
        ):
            return "STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE"
        return None


@dataclass(frozen=True)
class ResearchWorkflowRequest:
    schema_version: str
    invocation_id: str
    security_id: str
    requested_date: str
    effective_session_date: str
    data_snapshot_id: str
    evaluation_plan: ResearchEvaluationPlan
    workflow_snapshot_id: str | None = None
    market_data_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "ResearchWorkflowRequest@2":
            raise ValueError("RESEARCH_WORKFLOW_REQUEST_SCHEMA_INVALID")
        if not all(
            (
                self.invocation_id,
                self.security_id,
                self.data_snapshot_id,
            )
        ):
            raise ValueError("RESEARCH_WORKFLOW_REQUEST_IDENTITY_INVALID")
        try:
            requested = date.fromisoformat(self.requested_date)
            effective = date.fromisoformat(self.effective_session_date)
        except ValueError:
            raise ValueError("RESEARCH_WORKFLOW_REQUEST_DATE_INVALID") from None
        if effective > requested:
            raise ValueError("WORKFLOW_PIT_INVARIANT_FAILED")
        if self.evaluation_plan.horizon.as_of != self.requested_date:
            raise ValueError("RESEARCH_EVALUATION_AS_OF_MISMATCH")

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "invocation_id": self.invocation_id,
            "security_id": self.security_id,
            "requested_date": self.requested_date,
            "effective_session_date": self.effective_session_date,
            "data_snapshot_id": self.data_snapshot_id,
            "evaluation_plan": self.evaluation_plan.canonical_content,
            "workflow_snapshot_id": self.workflow_snapshot_id,
            "market_data_snapshot_id": self.market_data_snapshot_id,
        }

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, Any]
    ) -> "ResearchWorkflowRequest":
        if payload.get("schema_version") != "ResearchWorkflowRequest@2":
            raise ValueError("ResearchWorkflowRequest@2 required")
        allowed = {
            "schema_version",
            "invocation_id",
            "security_id",
            "requested_date",
            "effective_session_date",
            "data_snapshot_id",
            "evaluation_plan",
            "workflow_snapshot_id",
            "market_data_snapshot_id",
        }
        if set(payload) != allowed:
            raise ValueError("ResearchWorkflowRequest@2 fields invalid")
        raw_plan = payload["evaluation_plan"]
        if not isinstance(raw_plan, Mapping):
            raise ValueError("ResearchEvaluationPlan@1 required")
        horizon = raw_plan.get("horizon")
        if not isinstance(horizon, Mapping):
            raise ValueError("ResearchEvaluationHorizon invalid")
        plan = ResearchEvaluationPlan(
            schema_version=str(raw_plan.get("schema_version", "")),
            purpose=EvaluationPurpose(str(raw_plan.get("purpose", ""))),
            horizon=EvaluationHorizon(
                as_of=str(horizon.get("as_of", "")),
                forecast_end=str(horizon.get("forecast_end", "")),
                review_by=str(horizon.get("review_by", "")),
            ),
            required_dimensions=tuple(
                EvaluationDimension(str(value))
                for value in raw_plan.get("required_dimensions", ())
            ),
            strategy_validation=StrategyValidationSelection(
                str(raw_plan.get("strategy_validation", ""))
            ),
            degradation_policy=DegradationPolicy(
                str(raw_plan.get("degradation_policy", ""))
            ),
        )
        return cls(
            schema_version=str(payload["schema_version"]),
            invocation_id=str(payload["invocation_id"]),
            security_id=str(payload["security_id"]),
            requested_date=str(payload["requested_date"]),
            effective_session_date=str(payload["effective_session_date"]),
            data_snapshot_id=str(payload["data_snapshot_id"]),
            evaluation_plan=plan,
            workflow_snapshot_id=(
                None
                if payload["workflow_snapshot_id"] is None
                else str(payload["workflow_snapshot_id"])
            ),
            market_data_snapshot_id=(
                None
                if payload["market_data_snapshot_id"] is None
                else str(payload["market_data_snapshot_id"])
            ),
        )


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
    pdf_artifact_id: str
    artifact_record_ids: tuple[str, ...] = ()
    recent_trend_assessment_id: str | None = None
    workbook_artifact_id: str | None = None
    workbook_status: str = "limited"
    workbook_media_type: str = "application/json"
    workbook_schema_version: str = "ResearchWorkbookProjection@1"
    workbook_filename: str = "research-workbook-limitation.json"
    workbook_reason_code: str | None = None


def _require_bundle_mapping(
    value: object,
    code: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _component_summary(
    component: Mapping[str, Any],
) -> Mapping[str, Any]:
    content = _require_bundle_mapping(
        component["content"],
        "RESEARCH_BUNDLE_COMPONENT_INVALID",
    )
    return {
        "artifact_id": str(component["artifact_id"]),
        "schema_version": str(component["schema_version"]),
        "component": str(component["component"]),
        "status": str(component["status"]),
        "reason_codes": tuple(
            str(item) for item in component["reason_codes"]
        ),
        "source_member_ids": tuple(
            str(item) for item in component["source_member_ids"]
        ),
        "content_schema_version": content.get("schema_version"),
    }


def _component_decision(
    component: Mapping[str, Any],
) -> Mapping[str, Any]:
    content = dict(
        _require_bundle_mapping(
            component["content"],
            "RESEARCH_BUNDLE_COMPONENT_INVALID",
        )
    )
    content.setdefault("status", str(component["status"]))
    content.setdefault(
        "reason_code",
        str(component["reason_codes"][0]),
    )
    content.update(
        {
            "component_artifact_id": str(component["artifact_id"]),
            "component_status": str(component["status"]),
            "reason_codes": tuple(
                str(item) for item in component["reason_codes"]
            ),
            "source_member_ids": tuple(
                str(item) for item in component["source_member_ids"]
            ),
        }
    )
    return content


def _global_integrity_failure(
    research_run: Mapping[str, Any],
) -> bool:
    issues = research_run.get("integrity_issues")
    if not isinstance(issues, (list, tuple)):
        return True
    return any(
        not isinstance(issue, Mapping)
        or str(issue.get("severity", "")).lower() == "error"
        for issue in issues
    )


def _decision_status(
    *,
    global_integrity_failure: bool,
    components: Mapping[str, Mapping[str, Any]],
) -> str:
    if global_integrity_failure:
        return "blocked"
    if all(
        component["status"] == "complete"
        for component in components.values()
    ):
        return "completed"
    return "completed_with_limits"


def _bundle_valuation_view(
    *,
    global_integrity_failure: bool,
    scenario_component: Mapping[str, Any],
    route_component: Mapping[str, Any],
) -> Mapping[str, Any]:
    scenario_content = _require_bundle_mapping(
        scenario_component["content"],
        "RESEARCH_BUNDLE_COMPONENT_INVALID",
    )
    scenarios = scenario_content["scenarios"]
    base_scenario = next(
        item
        for item in scenarios
        if isinstance(item, Mapping) and item.get("role") == "base"
    )
    raw_methods = base_scenario.get("methods")
    if not isinstance(raw_methods, (list, tuple)):
        raise ValueError("RESEARCH_BUNDLE_SCENARIO_METHODS_INVALID")
    methods: list[Mapping[str, Any]] = []
    base_ready_ids: set[str] = set()
    all_method_ids: set[str] = set()
    for raw_method in raw_methods:
        method = _require_bundle_mapping(
            raw_method,
            "RESEARCH_BUNDLE_SCENARIO_METHODS_INVALID",
        )
        method_id = str(method.get("method_id", "")).strip()
        method_status = str(method.get("status", "")).strip()
        if (
            not method_id
            or method_id in all_method_ids
            or method_status not in {"ready", "blocked"}
        ):
            raise ValueError("RESEARCH_BUNDLE_SCENARIO_METHODS_INVALID")
        all_method_ids.add(method_id)
        if method_status == "ready":
            base_ready_ids.add(method_id)
        diagnostics = method.get("diagnostics")
        if not isinstance(diagnostics, (list, tuple)):
            raise ValueError("RESEARCH_BUNDLE_SCENARIO_METHODS_INVALID")
        diagnostic_codes = tuple(str(item) for item in diagnostics)
        projected_method = dict(method)
        projected_method.update(
            {
                "label": method_id,
                "explanation": str(
                    method.get("display_applicability")
                    or method.get("applicability")
                    or (
                        diagnostic_codes[0]
                        if diagnostic_codes
                        else method_status
                    )
                ),
                "missing_fields": (
                    ()
                    if method_status == "ready"
                    else diagnostic_codes
                ),
            }
        )
        methods.append(projected_method)

    route_content = _require_bundle_mapping(
        route_component["content"],
        "RESEARCH_BUNDLE_VALUATION_ROUTE_INVALID",
    )
    raw_ready_ids = route_content.get("ready_method_ids")
    if (
        not isinstance(raw_ready_ids, (list, tuple))
        or any(
            not isinstance(item, str) or not item
            for item in raw_ready_ids
        )
        or len(raw_ready_ids) != len(set(raw_ready_ids))
    ):
        raise ValueError("RESEARCH_BUNDLE_VALUATION_ROUTE_INVALID")
    ready_method_ids = tuple(
        item for item in raw_ready_ids if item in base_ready_ids
    )
    formal_per_share = (
        route_content.get("formal_per_share_valuation") is True
        and bool(ready_method_ids)
    )
    scenario_status = str(scenario_component["status"])
    route_status = str(route_component["status"])
    if global_integrity_failure:
        status = "blocked"
        summary = "全局证据完整性门禁未通过，正式估值视角已阻断。"
        reason_code = "RESEARCH_INTEGRITY_BLOCKED"
    elif (
        scenario_status == "complete"
        and route_status == "complete"
        and formal_per_share
    ):
        status = "ready"
        summary = "冻结基准情景和估值方法路由支持条件估值展示。"
        reason_code = str(scenario_component["reason_codes"][0])
    elif (
        scenario_status in {"complete", "limited"}
        and route_status in {"complete", "limited"}
        and ready_method_ids
    ):
        status = "limited"
        summary = "冻结基准情景支持部分条件估值，仍需保留方法边界。"
        reason_code = str(scenario_component["reason_codes"][0])
    else:
        status = "unavailable"
        summary = "冻结情景或方法适用性不足，未形成正式估值视角。"
        reason_code = str(scenario_component["reason_codes"][0])
    return {
        "status": status,
        "reason_code": reason_code,
        "summary": summary,
        "formal_per_share_valuation": formal_per_share,
        "ready_method_ids": ready_method_ids,
        "methods": tuple(methods),
        "missing_fields": tuple(
            dict.fromkeys(
                code
                for method in methods
                for code in method["missing_fields"]
            )
        ),
    }


_ANALYSIS_PLAN_FIELDS = frozenset(
    {
        "plan_identity",
        "schema_version",
        "compiler_identity",
        "evaluation_plan_identity",
        "data_snapshot_id",
        "source_policy_identity",
        "snapshot_member_ids",
        "capability_binding",
        "layers",
        "nodes",
    }
)
_ANALYSIS_NODE_RECEIPT_FIELDS = frozenset(
    {
        "node_id",
        "node_hash",
        "output_contract",
        "requirement",
        "component",
    }
)


def _verified_analysis_plan(
    value: Mapping[str, Any],
    *,
    request: ResearchWorkflowRequest,
    source_policy_identity: str,
    expected_snapshot_member_ids: tuple[str, ...],
    expected_analysis_plan_identity: str,
) -> Mapping[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value) != _ANALYSIS_PLAN_FIELDS
        or value.get("schema_version") != "ResearchAnalysisPlan@1"
        or value.get("compiler_identity") != "ResearchAnalysisPlanCompiler@1"
    ):
        raise ValueError("RESEARCH_ANALYSIS_PLAN_REQUIRED")
    raw_members = value.get("snapshot_member_ids")
    if (
        value.get("data_snapshot_id") != request.data_snapshot_id
        or value.get("source_policy_identity") != source_policy_identity
        or value.get("evaluation_plan_identity")
        != request.evaluation_plan.identity
        or not isinstance(raw_members, (list, tuple))
        or tuple(raw_members) != expected_snapshot_member_ids
    ):
        raise ValueError("RESEARCH_ANALYSIS_PLAN_CONTEXT_MISMATCH")
    if value.get("plan_identity") != expected_analysis_plan_identity:
        raise ValueError("RESEARCH_ANALYSIS_PLAN_IDENTITY_MISMATCH")

    canonical_content = {
        key: value[key] for key in value if key != "plan_identity"
    }
    if value.get("plan_identity") != (
        "research_analysis_plan_" + canonical_hash(canonical_content)[:24]
    ):
        raise ValueError("RESEARCH_ANALYSIS_PLAN_IDENTITY_MISMATCH")
    nodes = value.get("nodes")
    capability = value.get("capability_binding")
    if (
        not isinstance(nodes, (list, tuple))
        or not nodes
        or any(
            not isinstance(node, Mapping)
            or not _ANALYSIS_NODE_RECEIPT_FIELDS.issubset(node)
            for node in nodes
        )
        or not isinstance(capability, Mapping)
        or capability.get("schema_version") != "FrozenCapabilityBinding@1"
    ):
        raise ValueError("RESEARCH_ANALYSIS_PLAN_CONTENT_INVALID")
    node_ids = tuple(str(node["node_id"]) for node in nodes)
    if (
        any(not node_id for node_id in node_ids)
        or len(node_ids) != len(set(node_ids))
    ):
        raise ValueError("RESEARCH_ANALYSIS_PLAN_CONTENT_INVALID")
    return {
        **dict(value),
        "snapshot_member_ids": tuple(str(item) for item in raw_members),
        "capability_binding": dict(capability),
        "nodes": tuple(dict(node) for node in nodes),
    }


def _analysis_execution_receipt(
    *,
    analysis_plan: Mapping[str, Any],
    research_run: Mapping[str, Any],
    components: Mapping[str, Mapping[str, Any]],
    decision_status: str,
    decision_projection: Mapping[str, Any],
    model_identity: str,
    policy_identity: str,
) -> Mapping[str, Any]:
    capability = _require_bundle_mapping(
        analysis_plan["capability_binding"],
        "RESEARCH_ANALYSIS_PLAN_CONTENT_INVALID",
    )
    integrity_reasons = tuple(
        str(issue["code"])
        for issue in research_run.get("integrity_issues", ())
        if isinstance(issue, Mapping) and issue.get("code")
    )
    research_status = str(research_run.get("status", "blocked"))
    research_core_reasons = integrity_reasons
    if research_status != "completed" and not research_core_reasons:
        research_core_reasons = (
            "RESEARCH_CORE_COMPLETED_WITH_LIMITS",
        )
    decision_reasons = tuple(
        dict.fromkeys(
            str(reason)
            for component in components.values()
            if component["status"] != "complete"
            for reason in component["reason_codes"]
        )
    )
    receipts: list[Mapping[str, Any]] = []
    for node in analysis_plan["nodes"]:
        node_id = str(node["node_id"])
        component_name = node.get("component")
        if isinstance(component_name, str):
            actual = components.get(component_name)
            if actual is None:
                raise ValueError("RESEARCH_ANALYSIS_PLAN_OUTPUT_MISMATCH")
            status = str(actual["status"])
            artifact_id: str | None = str(actual["artifact_id"])
            reasons = tuple(str(reason) for reason in actual["reason_codes"])
            output_hash = canonical_hash(actual)
        elif node_id == "evidence_binding":
            output_hash = canonical_hash(capability)
            status = str(capability.get("status", "limited"))
            artifact_id = str(capability.get("capability_digest", "")) or None
            reasons = tuple(
                str(reason) for reason in capability.get("reason_codes", ())
            )
        elif node_id == "research_core":
            status = research_status
            artifact_id = str(research_run["run_id"])
            output_hash = canonical_hash(research_run)
            reasons = research_core_reasons
        elif node_id == "decision_projection":
            status = decision_status
            artifact_id = None
            output_hash = canonical_hash(decision_projection)
            reasons = (
                integrity_reasons
                if decision_status == "blocked"
                else decision_reasons
            )
            if decision_status != "completed" and not reasons:
                reasons = (
                    "RESEARCH_DECISION_COMPLETED_WITH_LIMITS",
                )
        else:
            raise ValueError("RESEARCH_ANALYSIS_PLAN_OUTPUT_MISMATCH")
        receipts.append(
            {
                "node_id": node_id,
                "node_hash": str(node["node_hash"]),
                "output_contract": str(node["output_contract"]),
                "requirement": str(node["requirement"]),
                "status": status,
                "artifact_id": artifact_id,
                "output_hash": output_hash,
                "reason_codes": reasons,
            }
        )
    content = {
        "schema_version": "ResearchAnalysisExecutionReceipt@1",
        "plan_identity": str(analysis_plan["plan_identity"]),
        "model_identity": model_identity,
        "policy_identity": policy_identity,
        "nodes": tuple(receipts),
    }
    return {
        "receipt_id": "research_analysis_execution_"
        + canonical_hash(content)[:24],
        **content,
    }


@dataclass(frozen=True)
class ResearchDecisionViewFactory:
    """Projects the complete evaluation bundle without recomputing meaning."""

    SCHEMA_VERSION = "ResearchDecisionView@2"

    def build(
        self,
        *,
        workflow_run_id: str,
        request: ResearchWorkflowRequest,
        evaluation_bundle: Mapping[str, Any],
        model_identity: str,
        source_policy_identity: str,
        expected_snapshot_member_ids: tuple[str, ...],
        analysis_plan: Mapping[str, Any],
        expected_analysis_plan_identity: str,
    ) -> Mapping[str, Any]:
        verified = verify_research_evaluation_bundle(
            evaluation_bundle,
            expected_data_snapshot_id=request.data_snapshot_id,
            expected_source_policy_identity=source_policy_identity,
            expected_snapshot_member_ids=expected_snapshot_member_ids,
        )
        verified_analysis_plan = _verified_analysis_plan(
            analysis_plan,
            request=request,
            source_policy_identity=source_policy_identity,
            expected_snapshot_member_ids=expected_snapshot_member_ids,
            expected_analysis_plan_identity=expected_analysis_plan_identity,
        )
        origin = verified.origin
        if (
            origin.get("research_policy_identity")
            != RESEARCH_EVALUATION_POLICY_IDENTITY
        ):
            raise ValueError("RESEARCH_EVALUATION_POLICY_MISMATCH")
        research_run = verified.research_run
        components = verified.components
        audit = research_run.get("audit")
        audit = dict(audit) if isinstance(audit, Mapping) else {}
        audit.update(
            {
                "evaluation_plan": request.evaluation_plan.canonical_content,
                "evaluation_plan_identity": request.evaluation_plan.identity,
                "source_policy_identity": source_policy_identity,
                "research_analysis_plan": verified_analysis_plan,
                "strategy_validation": {
                    "status": request.evaluation_plan.strategy_validation.value,
                    "reason_code": (
                        request.evaluation_plan.strategy_reason_code
                    ),
                },
                "permissions": dict(
                    research_run.get("permissions", {})
                    if isinstance(
                        research_run.get("permissions"), Mapping
                    )
                    else {}
                ),
            }
        )
        _, audit_projection = project_research_decision(
            as_of=request.evaluation_plan.horizon.as_of,
            required_dimensions=tuple(
                value.value
                for value in request.evaluation_plan.required_dimensions
            ),
            research_payload=research_run,
        )
        decision_payload = dict(research_run)
        decision_payload["methods"] = {}
        decision_synthesis = decision_payload.get("synthesis")
        if isinstance(decision_synthesis, Mapping):
            decision_synthesis = dict(decision_synthesis)
            decision_synthesis.pop("valuation_view", None)
            decision_payload["synthesis"] = decision_synthesis
        projection, _ = project_research_decision(
            as_of=request.evaluation_plan.horizon.as_of,
            required_dimensions=tuple(
                value.value
                for value in request.evaluation_plan.required_dimensions
            ),
            research_payload=decision_payload,
        )
        projection = dict(projection)
        scenario_content = _require_bundle_mapping(
            components["scenario_valuation"]["content"],
            "RESEARCH_BUNDLE_COMPONENT_INVALID",
        )
        projection["scenarios"] = tuple(
            dict(item) for item in scenario_content["scenarios"]
        )
        projection["valuation_simulation"] = _component_decision(
            components["valuation_simulation_decision"]
        )
        projection["market_price_paths"] = _component_decision(
            components["market_path_decision"]
        )
        global_integrity_failure = _global_integrity_failure(research_run)
        decision_status = _decision_status(
            global_integrity_failure=global_integrity_failure,
            components=components,
        )
        previous_valuation_summary = str(
            _require_bundle_mapping(
                projection["valuation_view"],
                "RESEARCH_VIEW_VALUATION_INVALID",
            ).get("summary", "")
        )
        projection["valuation_view"] = _bundle_valuation_view(
            global_integrity_failure=global_integrity_failure,
            scenario_component=components["scenario_valuation"],
            route_component=components["valuation_method_route"],
        )
        story = dict(
            _require_bundle_mapping(
                projection["story"],
                "RESEARCH_VIEW_STORY_INVALID",
            )
        )
        formal_valuation_summary = str(
            projection["valuation_view"]["summary"]
        )
        transmission = story.get("transmission")
        story["transmission"] = tuple(
            item
            for item in (
                transmission
                if isinstance(transmission, (list, tuple))
                else ()
            )
            if str(item) != previous_valuation_summary
        ) or (formal_valuation_summary,)
        story["valuation_view"] = formal_valuation_summary
        story["valuation_guardrails"] = tuple(
            code
            for method in projection["valuation_view"]["methods"]
            for code in method["missing_fields"]
        ) or tuple(projection["key_uncertainties"])
        story["status"] = decision_status
        projection["story"] = story
        if not isinstance(
            research_run.get("value_market_divergence"),
            Mapping,
        ):
            projection["value_market_divergence"] = {
                "status": "not_run",
                "reason_code": (
                    "VALUE_MARKET_DIVERGENCE_NOT_PRODUCED"
                ),
                "explanation": (
                    "本次研究没有独立产生价值与市场路径偏离结论。"
                ),
            }

        summaries = {
            name: _component_summary(component)
            for name, component in components.items()
        }
        audit["analysis_execution_receipt"] = (
            _analysis_execution_receipt(
                analysis_plan=verified_analysis_plan,
                research_run=research_run,
                components=components,
                decision_status=decision_status,
                decision_projection=projection,
                model_identity=model_identity,
                policy_identity=str(origin["research_policy_identity"]),
            )
        )
        audit.update(audit_projection)
        audit["simulation_decision"] = projection[
            "valuation_simulation"
        ]
        audit["market_path_decision"] = projection[
            "market_price_paths"
        ]
        audit["evaluation_bundle"] = {
            "bundle_id": str(evaluation_bundle["bundle_id"]),
            "schema_version": str(evaluation_bundle["schema_version"]),
            "origin": dict(origin),
            "estimates": (
                dict(evaluation_bundle["estimates"])
                if isinstance(evaluation_bundle["estimates"], Mapping)
                else None
            ),
            "components": summaries,
        }
        audit["forecast"] = summaries["forecast"]
        audit["valuation_method_route"] = {
            **summaries["valuation_method_route"],
            "route": dict(
                _require_bundle_mapping(
                    components["valuation_method_route"]["content"],
                    "RESEARCH_BUNDLE_COMPONENT_INVALID",
                )
            ),
        }
        audit["recent_trend_assessment"] = {
            **summaries["recent_trend_assessment"],
            "assessment": dict(
                _require_bundle_mapping(
                    components["recent_trend_assessment"]["content"],
                    "RESEARCH_BUNDLE_COMPONENT_INVALID",
                )
            ),
        }
        versions = audit.get("versions")
        versions = dict(versions) if isinstance(versions, Mapping) else {}
        versions.update(
            {
                "research_bundle_schema": evaluation_bundle[
                    "schema_version"
                ],
                "research_run_schema": research_run.get("schema_version"),
            }
        )
        audit["versions"] = versions
        content = {
            "schema_version": self.SCHEMA_VERSION,
            "workflow_run_id": workflow_run_id,
            "research_run_id": str(research_run["run_id"]),
            "data_snapshot_id": request.data_snapshot_id,
            "model_data_snapshot_identity": request.data_snapshot_id,
            "security_id": request.security_id,
            "forecast_artifact_record_id": None,
            "valuation_artifact_record_id": None,
            "simulation_artifact_record_id": None,
            "market_path_artifact_record_id": None,
            "subject_id": request.security_id,
            "as_of": request.evaluation_plan.horizon.as_of,
            "model_identity": model_identity,
            "policy_identity": str(origin["research_policy_identity"]),
            "status": decision_status,
            **projection,
            "audit": audit,
            "boundary": (
                "Conditional research output supports understanding of "
                "uncertainty and is not personalized investment advice."
            ),
        }
        return {
            "view_id": "research_view_"
            + canonical_hash(content)[:24],
            **content,
        }


__all__ = [
    "DegradationPolicy",
    "EvaluationDimension",
    "EvaluationHorizon",
    "EvaluationPurpose",
    "ResearchEvaluationPlan",
    "ResearchWorkflowRequest",
    "ResearchWorkflowResult",
    "ResearchDecisionViewFactory",
    "StrategyValidationSelection",
]
