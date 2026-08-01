from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from trading_platform.domain.plan_content_diff import (
    PlanContentRevisionError,
    merge_plan_content,
)
from trading_platform.domain.plan_impacts import (
    PlanChangeProposal,
    PlanImpactAssessment,
    PlanImpactError,
    PlanImpactFinding,
    ProposalDisposition,
)
from trading_platform.identity import canonical_hash

from .manual_portfolio_review import (
    FreezePlanImpactInput,
    ManualPortfolioReview,
)
from .trade_plan_authoring import (
    GetTradePlanGraph,
    PlanCommandActor,
    TradePlanTasks,
    _OpenTradePlanDrafts,
    _UpsertOpenTradePlanDraft,
)


@dataclass(frozen=True)
class CreatePlanImpactAssessment:
    invocation_id: str
    review_run_id: str
    review_item_id: str
    review_rule_id: str
    impact_kind: str
    materiality: str
    uncertainties: tuple[str, ...]
    what_changed: str
    what_would_change_the_view: str
    model_identity: str
    policy_identity: str
    prompt_identity: str
    created_by: str
    created_at: str
    decision_actor: str = "agent:codex"
    interaction_channel: str = "skill"
    transport_actor: str = "agent:codex"

    def validate(self) -> None:
        if self.created_by not in {"agent", "system"}:
            raise PlanImpactError("PLAN_IMPACT_AUTHOR_DENIED")
        if (
            not self.invocation_id
            or not self.review_run_id
            or not self.review_item_id
            or not self.review_rule_id
            or not self.decision_actor.startswith(
                f"{self.created_by}:"
            )
            or self.interaction_channel
            not in {"skill", "cli", "web", "workflow"}
            or not self.transport_actor.startswith(
                ("agent:", "adapter:", "system:")
            )
        ):
            raise PlanImpactError("PLAN_IMPACT_COMMAND_INVALID")


@dataclass(frozen=True)
class CreatePlanChangeProposal:
    invocation_id: str
    assessment_id: str
    proposed_content: Mapping[str, object]
    parameters: Mapping[str, object]
    created_by: str
    created_at: str
    decision_actor: str = "agent:codex"
    interaction_channel: str = "skill"
    transport_actor: str = "agent:codex"

    def validate(self) -> None:
        if self.created_by not in {"agent", "system"}:
            raise PlanImpactError("PLAN_IMPACT_AUTHOR_DENIED")
        if not self.invocation_id or not self.assessment_id:
            raise PlanImpactError("PROPOSAL_COMMAND_INVALID")
        if (
            not self.decision_actor.startswith(
                f"{self.created_by}:"
            )
            or self.interaction_channel
            not in {"skill", "cli", "web", "workflow"}
            or not self.transport_actor.startswith(
                ("agent:", "adapter:", "system:")
            )
        ):
            raise PlanImpactError("PROPOSAL_COMMAND_INVALID")


@dataclass(frozen=True)
class AcceptPlanChangeProposal:
    invocation_id: str
    proposal_id: str
    expected_revision: int
    decided_at: str
    actor: PlanCommandActor

    def validate(self) -> None:
        self.actor.validate()
        if (
            not self.actor.decision_actor.startswith("user:")
            or not self.invocation_id
            or not self.proposal_id
            or self.expected_revision < 1
        ):
            raise PlanImpactError("PROPOSAL_DISPOSITION_DENIED")


@dataclass(frozen=True)
class RejectPlanChangeProposal:
    invocation_id: str
    proposal_id: str
    expected_revision: int
    decided_at: str
    actor: PlanCommandActor

    def validate(self) -> None:
        self.actor.validate()
        if (
            not self.actor.decision_actor.startswith("user:")
            or not self.invocation_id
            or not self.proposal_id
            or self.expected_revision < 1
        ):
            raise PlanImpactError("PROPOSAL_DISPOSITION_DENIED")


class PlanImpactRepository(Protocol):
    def save_assessment(
        self,
        command: CreatePlanImpactAssessment,
        assessment: PlanImpactAssessment,
    ) -> PlanImpactAssessment: ...

    def get_assessment(
        self, assessment_id: str
    ) -> PlanImpactAssessment: ...

    def save_proposal(
        self,
        command: CreatePlanChangeProposal,
        proposal: PlanChangeProposal,
    ) -> PlanChangeProposal: ...

    def get_proposal(
        self, proposal_id: str
    ) -> PlanChangeProposal: ...

    def assert_base_is_active(
        self, proposal: PlanChangeProposal
    ) -> None: ...

    def plan_owner(
        self, plan_version_id: str
    ) -> tuple[str, str]: ...

    def dispose(
        self,
        *,
        invocation_id: str,
        request_hash: str,
        proposal: PlanChangeProposal,
        actor: PlanCommandActor,
    ) -> PlanChangeProposal: ...


class PlanImpacts:
    """Owns frozen impact authorship and accept-to-draft orchestration."""

    def __init__(
        self,
        repository: PlanImpactRepository,
        manual_reviews: ManualPortfolioReview,
        plan_tasks: TradePlanTasks,
        drafts: _OpenTradePlanDrafts,
    ) -> None:
        self._repository = repository
        self._manual_reviews = manual_reviews
        self._plan_tasks = plan_tasks
        self._drafts = drafts

    def create_assessment(
        self, command: CreatePlanImpactAssessment
    ) -> PlanImpactAssessment:
        command.validate()
        evidence = self._manual_reviews.freeze_plan_impact_input(
            FreezePlanImpactInput(
                command.review_run_id,
                command.review_item_id,
                command.review_rule_id,
            )
        )
        assessment = PlanImpactAssessment.build(
            evidence=evidence,
            finding=PlanImpactFinding(
                impact_kind=command.impact_kind,
                materiality=command.materiality,
                uncertainties=command.uncertainties,
                what_changed=command.what_changed,
                what_would_change_the_view=(
                    command.what_would_change_the_view
                ),
            ),
            model_identity=command.model_identity,
            policy_identity=command.policy_identity,
            prompt_identity=command.prompt_identity,
            created_by=command.created_by,
            created_at=command.created_at,
        )
        return self._repository.save_assessment(command, assessment)

    def create_proposal(
        self, command: CreatePlanChangeProposal
    ) -> PlanChangeProposal:
        command.validate()
        assessment = self._repository.get_assessment(
            command.assessment_id
        )
        base = self._plan_tasks.get(
            GetTradePlanGraph(assessment.evidence.plan_version_id)
        )
        try:
            proposed_content = merge_plan_content(
                base.version.content, command.proposed_content
            )
        except PlanContentRevisionError as error:
            raise PlanImpactError(error.code) from error
        proposal = PlanChangeProposal.open(
            assessment=assessment,
            base_graph=base,
            proposed_content=proposed_content,
            parameters=command.parameters,
            created_by=command.created_by,
            created_at=command.created_at,
        )
        return self._repository.save_proposal(command, proposal)

    def accept(
        self, command: AcceptPlanChangeProposal
    ) -> PlanChangeProposal:
        command.validate()
        request_hash = canonical_hash(command)
        replay = self._repository.get_proposal(command.proposal_id)
        if replay.status == "accepted":
            return self._repository.dispose(
                invocation_id=command.invocation_id,
                request_hash=request_hash,
                proposal=replay,
                actor=command.actor,
            )
        if (
            replay.status != "open"
            or replay.revision != command.expected_revision
        ):
            raise PlanImpactError("PROPOSAL_REVISION_CONFLICT")
        self._repository.assert_base_is_active(replay)
        base = self._plan_tasks.get(
            GetTradePlanGraph(replay.base_plan_version_id)
        )
        graph = replay.proposed_graph(base)
        account_id, security_id = self._repository.plan_owner(
            replay.base_plan_version_id
        )
        produced = self._drafts.upsert(
            _UpsertOpenTradePlanDraft(
                invocation_id=f"{command.invocation_id}:draft",
                account_id=account_id,
                security_id=security_id,
                proposed_graph=graph,
                parameters=replay.parameters(),
                updated_at=command.decided_at,
                actor=command.actor,
            )
        )
        accepted = replay.dispose(
            ProposalDisposition.ACCEPTED,
            decided_at=command.decided_at,
            accepted_draft_id=produced.draft_id,
        )
        return self._repository.dispose(
            invocation_id=command.invocation_id,
            request_hash=request_hash,
            proposal=accepted,
            actor=command.actor,
        )

    def reject(
        self, command: RejectPlanChangeProposal
    ) -> PlanChangeProposal:
        command.validate()
        current = self._repository.get_proposal(command.proposal_id)
        request_hash = canonical_hash(command)
        if current.status == "rejected":
            return self._repository.dispose(
                invocation_id=command.invocation_id,
                request_hash=request_hash,
                proposal=current,
                actor=command.actor,
            )
        if (
            current.status != "open"
            or current.revision != command.expected_revision
        ):
            raise PlanImpactError("PROPOSAL_REVISION_CONFLICT")
        rejected = current.dispose(
            ProposalDisposition.REJECTED,
            decided_at=command.decided_at,
        )
        return self._repository.dispose(
            invocation_id=command.invocation_id,
            request_hash=request_hash,
            proposal=rejected,
            actor=command.actor,
        )

    def get_proposal(self, proposal_id: str) -> PlanChangeProposal:
        return self._repository.get_proposal(proposal_id)


__all__ = [
    "AcceptPlanChangeProposal",
    "CreatePlanChangeProposal",
    "CreatePlanImpactAssessment",
    "PlanImpacts",
    "RejectPlanChangeProposal",
]
