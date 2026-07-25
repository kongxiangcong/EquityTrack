from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from equity_research import ResearchEngine, ResearchRequest, ResearchRun

from trading_platform.application.workflow_ledger import SnapshotEvidence
from trading_platform.domain.research_evaluation import (
    DegradationPolicy,
    ResearchWorkflowRequest,
)
from trading_platform.domain.research_inputs import ResearchInputs
from trading_platform.identity import canonical_hash


class ResearchEvaluationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ResearchEvaluation:
    """Owns deterministic research policy behind the workflow lifecycle."""

    engine: ResearchEngine

    POLICY_IDENTITY = "ResearchEvaluationPolicy@1"
    _CRITICAL_FIELDS = (
        "revenue",
        "net_income",
        "cash",
        "debt",
        "diluted_shares",
    )

    def evaluate(
        self,
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
    ) -> ResearchRun:
        self._validate_frozen_evidence(request, evidence)
        manifest = self._manifest(request, evidence)
        run = self.engine.run(
            ResearchRequest(
                manifest=manifest,
                as_of_date=request.evaluation_plan.horizon.as_of,
                research_inputs=ResearchInputs(
                    workflow_research_member_ids=tuple(
                        member.normalized_version_id
                        for member in evidence.member_evidence
                    )
                ),
            )
        )
        if (
            request.evaluation_plan.degradation_policy
            is DegradationPolicy.FAIL_CLOSED
            and run.status != "completed"
        ):
            raise ResearchEvaluationError("RESEARCH_EVALUATION_DATA_INSUFFICIENT")
        return run

    def fingerprint(
        self,
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
    ) -> str:
        return canonical_hash(
            {
                "policy": self.POLICY_IDENTITY,
                "security_id": request.security_id,
                "snapshot_id": evidence.data_snapshot_id,
                "snapshot_members": [
                    member.normalized_version_id
                    for member in evidence.member_evidence
                ],
                "source_policy_identity": evidence.source_policy_identity,
                "evaluation_plan_identity": request.evaluation_plan.identity,
            }
        )

    @staticmethod
    def _validate_frozen_evidence(
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
    ) -> None:
        if evidence.data_snapshot_id != request.data_snapshot_id:
            raise ResearchEvaluationError("WORKFLOW_SNAPSHOT_INVALID")
        if evidence.scope_id != request.security_id:
            raise ResearchEvaluationError("WORKFLOW_DOMAIN_REFERENCE_INVALID")
        if evidence.purpose not in {"research", "workflow"}:
            raise ResearchEvaluationError("WORKFLOW_SNAPSHOT_PURPOSE_INVALID")
        if evidence.effective_session_date != request.effective_session_date:
            raise ResearchEvaluationError("WORKFLOW_PIT_INVARIANT_FAILED")
        if evidence.requested_date > request.requested_date:
            raise ResearchEvaluationError("WORKFLOW_PIT_INVARIANT_FAILED")
        if evidence.freshness_status == "missing":
            raise ResearchEvaluationError("WORKFLOW_SNAPSHOT_INVALID")
        if evidence.quality_status == "blocking":
            raise ResearchEvaluationError("WORKFLOW_QUALITY_BLOCKED")
        cutoff = datetime.fromisoformat(
            request.evaluation_plan.horizon.as_of + "T23:59:59+00:00"
        )
        if any(
            datetime.fromisoformat(member.available_at) > cutoff
            for member in evidence.member_evidence
        ):
            raise ResearchEvaluationError("WORKFLOW_PIT_INVARIANT_FAILED")

    def _manifest(
        self,
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
    ) -> Mapping[str, object]:
        sources = []
        for member in evidence.member_evidence:
            source_id = "source_" + canonical_hash(
                {
                    "snapshot": evidence.data_snapshot_id,
                    "member": member.normalized_version_id,
                    "source": member.source_identity,
                }
            )[:24]
            sources.append(
                {
                    "source_id": source_id,
                    "tier": (
                        "primary"
                        if member.source_authority == "official"
                        else "secondary"
                    ),
                    "publisher": member.source_identity,
                    "title": (
                        f"{member.dataset} frozen evidence "
                        f"{member.normalized_version_id}"
                    ),
                    "url_or_api": member.real_source_url,
                    "retrieved_at": member.retrieved_at,
                    "available_at": member.available_at,
                    "report_date": member.published_at[:10],
                    "official": member.source_authority == "official",
                    "extracted_fields": [],
                }
            )
        return {
            "source_manifest_version": 2,
            "company": {
                "name": request.security_id,
                "ticker": request.security_id,
                "market": "A-share",
                "reporting_currency": "CNY",
                "trading_currency": "CNY",
                "accounting_standard": "PRC-GAAP",
                "latest_reporting_period": (
                    request.evaluation_plan.horizon.as_of
                ),
            },
            "sources": sources,
            "missing_critical_data": [
                {
                    "field_name": field,
                    "missing_reason": (
                        "No qualified semantic fact is present in the frozen "
                        "snapshot; unknown is not zero."
                    ),
                }
                for field in self._CRITICAL_FIELDS
            ],
        }
