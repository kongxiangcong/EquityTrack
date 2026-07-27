from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping

from trading_platform.identity import canonical_hash

from .plans import TradePlanGraph, build_plan_version


class PlanImpactError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProposalDisposition(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class FrozenPlanImpactEvidence:
    review_run_id: str
    review_item_id: str
    plan_version_id: str
    review_rule_id: str
    review_rule_result: str
    evidence_manifest_id: str
    research_refs: tuple[str, ...]
    market_refs: tuple[str, ...]
    industry_refs: tuple[str, ...]
    sector_refs: tuple[str, ...]
    unable_reasons: tuple[str, ...]
    authority_content_hash: str
    schema_version: str = "FrozenPlanImpactEvidence@1"

    def validate(self) -> None:
        identity = {
            key: value
            for key, value in self.__dict__.items()
            if key != "authority_content_hash"
        }
        if (
            self.schema_version != "FrozenPlanImpactEvidence@1"
            or not self.review_run_id
            or not self.review_item_id
            or not self.plan_version_id
            or not self.review_rule_id
            or self.review_rule_result
            not in {"pass", "fail", "unable_to_determine"}
            or not self.evidence_manifest_id
            or self.authority_content_hash != canonical_hash(identity)
        ):
            raise PlanImpactError("PLAN_IMPACT_EVIDENCE_INVALID")


@dataclass(frozen=True)
class PlanImpactFinding:
    impact_kind: str
    materiality: str
    uncertainties: tuple[str, ...]
    what_changed: str
    what_would_change_the_view: str
    schema_version: str = "PlanImpactFinding@1"

    def validate(self, review_rule_result: str) -> None:
        if (
            self.schema_version != "PlanImpactFinding@1"
            or self.impact_kind
            not in {
                "supports_current_plan",
                "challenges_current_plan",
                "requires_review",
                "unable_to_determine",
            }
            or self.materiality not in {"low", "medium", "high", "unable"}
            or not self.what_changed
            or not self.what_would_change_the_view
            or (
                review_rule_result == "unable_to_determine"
                and (
                    self.impact_kind != "unable_to_determine"
                    or self.materiality != "unable"
                    or not self.uncertainties
                )
            )
        ):
            raise PlanImpactError("PLAN_IMPACT_FINDING_INVALID")


@dataclass(frozen=True)
class PlanImpactAssessment:
    assessment_id: str
    evidence: FrozenPlanImpactEvidence
    finding: PlanImpactFinding
    model_identity: str
    policy_identity: str
    prompt_identity: str
    content_hash: str
    created_by: str
    created_at: str
    schema_version: str = "PlanImpactAssessment@1"

    @classmethod
    def build(
        cls,
        *,
        evidence: FrozenPlanImpactEvidence,
        finding: PlanImpactFinding,
        model_identity: str,
        policy_identity: str,
        prompt_identity: str,
        created_by: str,
        created_at: str,
    ) -> "PlanImpactAssessment":
        evidence.validate()
        finding.validate(evidence.review_rule_result)
        payload = {
            "schema_version": "PlanImpactAssessment@1",
            "evidence": evidence,
            "finding": finding,
            "model_identity": model_identity,
            "policy_identity": policy_identity,
            "prompt_identity": prompt_identity,
            "created_by": created_by,
            "created_at": created_at,
        }
        digest = canonical_hash(payload)
        assessment = cls(
            assessment_id=f"plan_impact_assessment_{digest[:24]}",
            evidence=evidence,
            finding=finding,
            model_identity=model_identity,
            policy_identity=policy_identity,
            prompt_identity=prompt_identity,
            content_hash=digest,
            created_by=created_by,
            created_at=created_at,
        )
        assessment.validate()
        return assessment

    def validate(self) -> None:
        self.evidence.validate()
        self.finding.validate(self.evidence.review_rule_result)
        try:
            created = datetime.fromisoformat(self.created_at)
        except ValueError as error:
            raise PlanImpactError("PLAN_IMPACT_ASSESSMENT_INVALID") from error
        payload = {
            "schema_version": self.schema_version,
            "evidence": self.evidence,
            "finding": self.finding,
            "model_identity": self.model_identity,
            "policy_identity": self.policy_identity,
            "prompt_identity": self.prompt_identity,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }
        digest = canonical_hash(payload)
        if (
            self.schema_version != "PlanImpactAssessment@1"
            or self.created_by not in {"agent", "system"}
            or created.tzinfo is None
            or not self.model_identity
            or not self.policy_identity
            or not self.prompt_identity
            or self.content_hash != digest
            or self.assessment_id
            != f"plan_impact_assessment_{digest[:24]}"
        ):
            raise PlanImpactError("PLAN_IMPACT_ASSESSMENT_INVALID")


@dataclass(frozen=True)
class PlanChangeProposal:
    proposal_id: str
    revision: int
    status: str
    assessment_id: str
    base_plan_version_id: str
    base_graph_seal_hash: str
    proposed_canonical_patch: Mapping[str, object]
    proposed_diff_hash: str
    created_by: str
    created_at: str
    updated_at: str
    accepted_draft_id: str | None
    content_hash: str
    schema_version: str = "PlanChangeProposal@1"

    @classmethod
    def open(
        cls,
        *,
        assessment: PlanImpactAssessment,
        base_graph: TradePlanGraph,
        proposed_content: Mapping[str, object],
        parameters: Mapping[str, object],
        created_by: str,
        created_at: str,
    ) -> "PlanChangeProposal":
        assessment.validate()
        base_graph.validate()
        if assessment.evidence.plan_version_id != (
            base_graph.version.plan_version_id
        ):
            raise PlanImpactError("PROPOSAL_BASE_PLAN_MISMATCH")
        patch = {
            "schema_version": "PlanContentReplacementPatch@1",
            "content": proposed_content,
            "parameters": parameters,
        }
        diff_hash = cls.diff_hash(
            base_graph.version.graph_seal_hash, patch
        )
        proposal_id = f"plan_change_proposal_{canonical_hash({'assessment_id': assessment.assessment_id, 'proposed_diff_hash': diff_hash})[:24]}"
        proposal = cls._build_revision(
            proposal_id=proposal_id,
            revision=1,
            status="open",
            assessment_id=assessment.assessment_id,
            base_plan_version_id=base_graph.version.plan_version_id,
            base_graph_seal_hash=base_graph.version.graph_seal_hash,
            patch=patch,
            proposed_diff_hash=diff_hash,
            created_by=created_by,
            created_at=created_at,
            updated_at=created_at,
            accepted_draft_id=None,
        )
        proposal.validate()
        return proposal

    def dispose(
        self,
        disposition: ProposalDisposition,
        *,
        decided_at: str,
        accepted_draft_id: str | None = None,
    ) -> "PlanChangeProposal":
        self.validate()
        if self.status != "open":
            raise PlanImpactError("PROPOSAL_ALREADY_DISPOSED")
        if (
            disposition is ProposalDisposition.ACCEPTED
            and not accepted_draft_id
        ) or (
            disposition is ProposalDisposition.REJECTED
            and accepted_draft_id is not None
        ):
            raise PlanImpactError("PROPOSAL_DISPOSITION_INVALID")
        proposal = self._build_revision(
            proposal_id=self.proposal_id,
            revision=self.revision + 1,
            status=disposition.value,
            assessment_id=self.assessment_id,
            base_plan_version_id=self.base_plan_version_id,
            base_graph_seal_hash=self.base_graph_seal_hash,
            patch=self.proposed_canonical_patch,
            proposed_diff_hash=self.proposed_diff_hash,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=decided_at,
            accepted_draft_id=accepted_draft_id,
        )
        proposal.validate()
        return proposal

    def proposed_graph(self, base_graph: TradePlanGraph) -> TradePlanGraph:
        self.validate()
        base_graph.validate()
        if (
            base_graph.version.plan_version_id
            != self.base_plan_version_id
            or base_graph.version.graph_seal_hash
            != self.base_graph_seal_hash
            or self.proposed_diff_hash
            != self.diff_hash(
                self.base_graph_seal_hash,
                self.proposed_canonical_patch,
            )
        ):
            raise PlanImpactError("PROPOSAL_BASE_PLAN_STALE")
        content = self.proposed_canonical_patch.get("content")
        if not isinstance(content, Mapping):
            raise PlanImpactError("PROPOSAL_PATCH_INVALID")
        version = base_graph.version
        version_seed = canonical_hash(
            {
                "proposal_id": self.proposal_id,
                "base_plan_version_id": self.base_plan_version_id,
                "proposed_diff_hash": self.proposed_diff_hash,
            }
        )
        return build_plan_version(
            plan_version_id=f"trade_plan_version_{version_seed[:24]}",
            plan_id=version.plan_id,
            version_no=version.version_no + 1,
            supersedes_version_id=version.plan_version_id,
            strategy_version_id=version.strategy_version_id,
            investment_thesis_version_id=(
                version.investment_thesis_version_id
            ),
            account_snapshot_version_id=version.account_snapshot_version_id,
            data_snapshot_id=version.data_snapshot_id,
            horizon_start=version.horizon_start,
            horizon_end=version.horizon_end,
            review_by=version.review_by,
            risk_policy_version_id=version.risk_policy_version_id,
            metric_catalog_version=version.metric_catalog_version,
            evaluator_policy_version=version.evaluator_policy_version,
            content=content,
            sleeves=base_graph.sleeves,
            rules=base_graph.rules,
            evidence_references=base_graph.evidence_references,
            adjusted_price_evidence=base_graph.adjusted_price_evidence,
            confirmed_at="1970-01-01T00:00:00+00:00",
            user_approval_receipt_id="pending-user-approval",
        )

    def parameters(self) -> Mapping[str, object]:
        value = self.proposed_canonical_patch.get("parameters")
        if not isinstance(value, Mapping):
            raise PlanImpactError("PROPOSAL_PATCH_INVALID")
        return value

    @staticmethod
    def diff_hash(
        base_graph_seal_hash: str, patch: Mapping[str, object]
    ) -> str:
        return canonical_hash(
            {
                "schema_version": "PlanChangeDiff@1",
                "base_graph_seal_hash": base_graph_seal_hash,
                "proposed_canonical_patch": patch,
            }
        )

    def validate(self) -> None:
        try:
            created = datetime.fromisoformat(self.created_at)
            updated = datetime.fromisoformat(self.updated_at)
        except ValueError as error:
            raise PlanImpactError("PLAN_CHANGE_PROPOSAL_INVALID") from error
        if (
            self.schema_version != "PlanChangeProposal@1"
            or not self.proposal_id
            or self.revision < 1
            or self.status
            not in {"open", "accepted", "rejected", "superseded"}
            or not self.assessment_id
            or not self.base_plan_version_id
            or not self.base_graph_seal_hash
            or self.proposed_canonical_patch.get("schema_version")
            != "PlanContentReplacementPatch@1"
            or not isinstance(
                self.proposed_canonical_patch.get("content"), Mapping
            )
            or not isinstance(
                self.proposed_canonical_patch.get("parameters"), Mapping
            )
            or self.proposed_diff_hash
            != self.diff_hash(
                self.base_graph_seal_hash,
                self.proposed_canonical_patch,
            )
            or self.created_by not in {"agent", "system"}
            or created.tzinfo is None
            or updated.tzinfo is None
            or updated < created
            or (
                self.status == "accepted"
                and not self.accepted_draft_id
            )
            or (
                self.status != "accepted"
                and self.accepted_draft_id is not None
            )
            or self.content_hash != canonical_hash(
                {
                    "schema_version": self.schema_version,
                    "proposal_id": self.proposal_id,
                    "revision": self.revision,
                    "status": self.status,
                    "assessment_id": self.assessment_id,
                    "base_plan_version_id": self.base_plan_version_id,
                    "base_graph_seal_hash": self.base_graph_seal_hash,
                    "proposed_canonical_patch": (
                        self.proposed_canonical_patch
                    ),
                    "proposed_diff_hash": self.proposed_diff_hash,
                    "created_by": self.created_by,
                    "created_at": self.created_at,
                    "updated_at": self.updated_at,
                    "accepted_draft_id": self.accepted_draft_id,
                }
            )
        ):
            raise PlanImpactError("PLAN_CHANGE_PROPOSAL_INVALID")

    @classmethod
    def _build_revision(
        cls,
        *,
        proposal_id: str,
        revision: int,
        status: str,
        assessment_id: str,
        base_plan_version_id: str,
        base_graph_seal_hash: str,
        patch: Mapping[str, object],
        proposed_diff_hash: str,
        created_by: str,
        created_at: str,
        updated_at: str,
        accepted_draft_id: str | None,
    ) -> "PlanChangeProposal":
        payload = {
            "schema_version": "PlanChangeProposal@1",
            "proposal_id": proposal_id,
            "revision": revision,
            "status": status,
            "assessment_id": assessment_id,
            "base_plan_version_id": base_plan_version_id,
            "base_graph_seal_hash": base_graph_seal_hash,
            "proposed_canonical_patch": patch,
            "proposed_diff_hash": proposed_diff_hash,
            "created_by": created_by,
            "created_at": created_at,
            "updated_at": updated_at,
            "accepted_draft_id": accepted_draft_id,
        }
        return cls(
            proposal_id=proposal_id,
            revision=revision,
            status=status,
            assessment_id=assessment_id,
            base_plan_version_id=base_plan_version_id,
            base_graph_seal_hash=base_graph_seal_hash,
            proposed_canonical_patch=patch,
            proposed_diff_hash=proposed_diff_hash,
            created_by=created_by,
            created_at=created_at,
            updated_at=updated_at,
            accepted_draft_id=accepted_draft_id,
            content_hash=canonical_hash(payload),
        )


__all__ = [
    "FrozenPlanImpactEvidence",
    "PlanChangeProposal",
    "PlanImpactAssessment",
    "PlanImpactError",
    "PlanImpactFinding",
    "ProposalDisposition",
]
