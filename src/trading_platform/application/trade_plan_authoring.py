from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, TypeAlias

from trading_platform.domain.approvals import (
    ActivationIntent,
    PlanConfirmationChallenge,
    UserApprovalReceipt,
)
from trading_platform.domain.plans import (
    ActiveTradePlan,
    PlanDraftRejected,
    PlanValidationError,
    TradePlanDraft,
    TradePlanGraph,
)


@dataclass(frozen=True)
class PlanCommandActor:
    decision_actor: str
    interaction_channel: str
    transport_actor: str

    def validate(self, *, confirmation: bool = False) -> None:
        if (
            not any(
                self.decision_actor.startswith(prefix)
                for prefix in ("user:", "agent:")
            )
            or self.interaction_channel not in {"skill", "cli", "web"}
            or not any(
                self.transport_actor.startswith(prefix)
                for prefix in ("user:", "agent:", "adapter:")
            )
            or (
                confirmation
                and not self.decision_actor.startswith("user:")
            )
        ):
            raise PlanValidationError("PLAN_COMMAND_ACTOR_INVALID")


@dataclass(frozen=True)
class CreateTradePlanDraft:
    invocation_id: str
    draft: TradePlanDraft
    actor: PlanCommandActor


@dataclass(frozen=True)
class ReviseTradePlanDraft:
    invocation_id: str
    draft_id: str
    expected_revision: int
    proposed_graph: TradePlanGraph
    parameters: Mapping[str, object]
    updated_at: str
    actor: PlanCommandActor


@dataclass(frozen=True)
class RejectTradePlanDraft:
    invocation_id: str
    draft_id: str
    expected_revision: int
    rejected_at: str
    actor: PlanCommandActor


@dataclass(frozen=True)
class IssuePlanConfirmationChallenge:
    invocation_id: str
    draft_id: str
    expected_revision: int
    activation_intent: ActivationIntent
    issued_at: str
    expires_at: str | None
    actor: PlanCommandActor


@dataclass(frozen=True)
class ConfirmTradePlanVersion:
    invocation_id: str
    challenge_id: str
    expected_revision: int
    expected_draft_hash: str
    expected_diff_hash: str
    activation_intent: ActivationIntent
    approved_at: str
    actor: PlanCommandActor


@dataclass(frozen=True)
class PlanConfirmationResult:
    graph: TradePlanGraph
    receipt: UserApprovalReceipt
    active_plan: ActiveTradePlan | None


@dataclass(frozen=True)
class GetActiveTradePlan:
    account_id: str
    security_id: str


@dataclass(frozen=True)
class GetTradePlanGraph:
    plan_version_id: str


TradePlanCommand: TypeAlias = (
    CreateTradePlanDraft
    | ReviseTradePlanDraft
    | RejectTradePlanDraft
    | IssuePlanConfirmationChallenge
    | ConfirmTradePlanVersion
)
TradePlanQuery: TypeAlias = GetActiveTradePlan | GetTradePlanGraph


class TradePlanStore(Protocol):
    def create_draft(
        self, command: CreateTradePlanDraft
    ) -> TradePlanDraft: ...

    def revise_draft(
        self, command: ReviseTradePlanDraft
    ) -> TradePlanDraft: ...

    def reject_draft(
        self, command: RejectTradePlanDraft
    ) -> PlanDraftRejected: ...

    def issue_challenge(
        self, command: IssuePlanConfirmationChallenge
    ) -> PlanConfirmationChallenge: ...

    def confirm_plan(
        self, command: ConfirmTradePlanVersion
    ) -> PlanConfirmationResult: ...

    def get_active_master(
        self, account_id: str, security_id: str
    ) -> ActiveTradePlan: ...

    def get_graph(self, plan_version_id: str) -> TradePlanGraph: ...


class TradePlanTasks:
    """Owns draft-to-confirmed-plan tasks behind one application seam."""

    def __init__(self, store: TradePlanStore) -> None:
        self._store = store

    def execute(
        self, command: TradePlanCommand
    ) -> (
        TradePlanDraft
        | PlanDraftRejected
        | PlanConfirmationChallenge
        | PlanConfirmationResult
    ):
        if not command.invocation_id:
            raise PlanValidationError("COMMAND_INVOCATION_ID_REQUIRED")
        command.actor.validate(
            confirmation=isinstance(command, ConfirmTradePlanVersion)
        )
        if isinstance(command, CreateTradePlanDraft):
            return self._store.create_draft(command)
        if isinstance(command, ReviseTradePlanDraft):
            return self._store.revise_draft(command)
        if isinstance(command, RejectTradePlanDraft):
            return self._store.reject_draft(command)
        if isinstance(command, IssuePlanConfirmationChallenge):
            return self._store.issue_challenge(command)
        return self._store.confirm_plan(command)

    def get(
        self, query: TradePlanQuery
    ) -> ActiveTradePlan | TradePlanGraph:
        if isinstance(query, GetActiveTradePlan):
            return self._store.get_active_master(
                query.account_id, query.security_id
            )
        return self._store.get_graph(query.plan_version_id)


__all__ = [
    "ConfirmTradePlanVersion",
    "CreateTradePlanDraft",
    "GetActiveTradePlan",
    "GetTradePlanGraph",
    "IssuePlanConfirmationChallenge",
    "PlanCommandActor",
    "PlanConfirmationResult",
    "RejectTradePlanDraft",
    "ReviseTradePlanDraft",
    "TradePlanTasks",
]
