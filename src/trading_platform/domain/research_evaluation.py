from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Mapping

from trading_platform.identity import canonical_hash
from trading_platform.domain.workflow import ReferenceDisposition


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


@dataclass(frozen=True)
class ResearchDecisionViewFactory:
    """Canonicalizes evaluation output into the sole presentation contract."""

    SCHEMA_VERSION = "ResearchDecisionView@2"

    def build(
        self,
        *,
        workflow_run_id: str,
        request: ResearchWorkflowRequest,
        research_payload: Mapping[str, Any],
        model_identity: str,
        source_policy_identity: str,
    ) -> Mapping[str, Any]:
        audit = research_payload.get("audit")
        audit = dict(audit) if isinstance(audit, Mapping) else {}
        audit.update(
            {
                "evaluation_plan": request.evaluation_plan.canonical_content,
                "evaluation_plan_identity": request.evaluation_plan.identity,
                "source_policy_identity": source_policy_identity,
                "strategy_validation": {
                    "status": request.evaluation_plan.strategy_validation.value,
                    "reason_code": (
                        request.evaluation_plan.strategy_reason_code
                    ),
                },
                "permissions": dict(
                    research_payload.get("permissions", {})
                    if isinstance(
                        research_payload.get("permissions"), Mapping
                    )
                    else {}
                ),
            }
        )
        content = {
            "schema_version": self.SCHEMA_VERSION,
            "workflow_run_id": workflow_run_id,
            "research_run_id": str(research_payload.get("run_id", "")),
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
            "policy_identity": "ResearchEvaluationPolicy@1",
            "status": str(research_payload.get("status", "blocked")),
            "valuation_view": {
                "status": "not_ready",
                "reason_code": "FORMAL_VALUATION_UNAVAILABLE",
            },
            "risk_reward_summary": (
                "Risk/reward is not comparable because required official "
                "semantic inputs are missing."
            ),
            "data_quality_grade": "insufficient",
            "key_uncertainties": (
                "Critical financial statement facts are unavailable as "
                "qualified semantic inputs.",
            ),
            "what_would_change_the_view": (
                "A frozen snapshot containing qualified official financial "
                "facts required by the selected valuation method.",
            ),
            "story": {
                "status": str(research_payload.get("status", "blocked")),
                "summary": (
                    "Frozen evidence is insufficient for a numeric valuation "
                    "conclusion."
                ),
            },
            "key_drivers": (),
            "scenarios": (),
            "market_implied_expectations": (),
            "valuation_simulation": None,
            "market_price_paths": None,
            "value_market_divergence": {
                "status": "not_comparable",
                "reason_code": "FORMAL_VALUATION_UNAVAILABLE",
            },
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
