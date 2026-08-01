from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    TradePlanDraftGraph,
    TradePlanGraph,
    build_trade_plan_draft,
)
from trading_platform.identity import canonical_hash


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
class _CreateTradePlanDraft:
    invocation_id: str
    draft: TradePlanDraft
    actor: PlanCommandActor


@dataclass(frozen=True)
class _ReviseTradePlanDraft:
    invocation_id: str
    draft_id: str
    expected_revision: int
    proposed_graph: TradePlanDraftGraph
    parameters: Mapping[str, object]
    updated_at: str
    actor: PlanCommandActor


@dataclass(frozen=True)
class _UpsertOpenTradePlanDraft:
    invocation_id: str
    account_id: str
    security_id: str
    proposed_graph: TradePlanDraftGraph
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
    RejectTradePlanDraft
    | IssuePlanConfirmationChallenge
    | ConfirmTradePlanVersion
)
TradePlanQuery: TypeAlias = GetActiveTradePlan | GetTradePlanGraph


class _TradePlanStore(Protocol):
    def create_draft(
        self, command: _CreateTradePlanDraft
    ) -> TradePlanDraft: ...

    def revise_draft(
        self, command: _ReviseTradePlanDraft
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

    def get_open_draft(
        self, account_id: str, security_id: str
    ) -> TradePlanDraft | None: ...

    def get_draft_by_invocation(
        self, invocation_id: str
    ) -> TradePlanDraft | None: ...


class _OpenTradePlanDrafts:
    """Owns the sole internal create-or-revise policy for OPEN drafts."""

    def __init__(self, store: _TradePlanStore) -> None:
        self._store = store

    def get_open(
        self, account_id: str, security_id: str
    ) -> TradePlanDraft | None:
        return self._store.get_open_draft(account_id, security_id)

    def get_by_invocation(
        self, invocation_id: str
    ) -> TradePlanDraft | None:
        if not invocation_id:
            raise PlanValidationError("COMMAND_INVOCATION_ID_REQUIRED")
        return self._store.get_draft_by_invocation(invocation_id)

    def get_active(
        self, account_id: str, security_id: str
    ) -> ActiveTradePlan:
        return self._store.get_active_master(account_id, security_id)

    def upsert(
        self, command: _UpsertOpenTradePlanDraft
    ) -> TradePlanDraft:
        command.actor.validate()
        command.proposed_graph.validate()
        try:
            updated = datetime.fromisoformat(command.updated_at)
        except ValueError as error:
            raise PlanValidationError(
                "PLAN_DRAFT_UPSERT_INVALID"
            ) from error
        if (
            not command.invocation_id
            or not command.account_id
            or not command.security_id
            or updated.tzinfo is None
            or updated.utcoffset() is None
        ):
            raise PlanValidationError("PLAN_DRAFT_UPSERT_INVALID")
        replay = self.get_by_invocation(command.invocation_id)
        if replay is not None:
            if (
                replay.status != "open"
                or replay.account_id != command.account_id
                or replay.security_id != command.security_id
                or replay.proposed_graph != command.proposed_graph
                or replay.parameters != command.parameters
                or replay.updated_at != command.updated_at
                or replay.decision_actor
                != command.actor.decision_actor
                or replay.interaction_channel
                != command.actor.interaction_channel
                or replay.transport_actor
                != command.actor.transport_actor
            ):
                raise PlanValidationError("INVOCATION_CONFLICT")
            return replay
        graph = command.proposed_graph
        version = graph.version
        open_draft = self.get_open(
            command.account_id, command.security_id
        )
        if open_draft is None:
            draft = build_trade_plan_draft(
                draft_id=self._deterministic_draft_id(command),
                account_id=command.account_id,
                security_id=command.security_id,
                proposed_graph=graph,
                parameters=command.parameters,
                created_at=command.updated_at,
                decision_actor=command.actor.decision_actor,
                interaction_channel=command.actor.interaction_channel,
                transport_actor=command.actor.transport_actor,
            )
            return self._store.create_draft(
                _CreateTradePlanDraft(
                    invocation_id=command.invocation_id,
                    draft=draft,
                    actor=command.actor,
                )
            )
        open_draft.validate()
        if (
            open_draft.status != "open"
            or open_draft.plan_id != version.plan_id
            or open_draft.account_id != command.account_id
            or open_draft.security_id != command.security_id
            or open_draft.strategy_version_id
            != version.strategy_version_id
            or open_draft.based_on_version_id
            != version.supersedes_version_id
        ):
            raise PlanValidationError("PLAN_DRAFT_GRAPH_MISMATCH")
        return self._store.revise_draft(
            _ReviseTradePlanDraft(
                invocation_id=command.invocation_id,
                draft_id=open_draft.draft_id,
                expected_revision=open_draft.revision,
                proposed_graph=graph,
                parameters=command.parameters,
                updated_at=command.updated_at,
                actor=command.actor,
            )
        )

    @staticmethod
    def _deterministic_draft_id(
        command: _UpsertOpenTradePlanDraft,
    ) -> str:
        version = command.proposed_graph.version
        digest = canonical_hash(
            {
                "schema_version": "OpenTradePlanDraftIdentity@1",
                "account_id": command.account_id,
                "security_id": command.security_id,
                "plan_id": version.plan_id,
                "plan_version_id": version.plan_version_id,
                "supersedes_version_id": (
                    version.supersedes_version_id
                ),
            }
        )
        return f"trade_plan_draft_{digest[:24]}"


class TradePlanTasks:
    """Owns reject, challenge, confirmation, and plan read tasks."""

    def __init__(self, store: _TradePlanStore) -> None:
        self._store = store

    def execute(
        self, command: TradePlanCommand
    ) -> (
        PlanDraftRejected
        | PlanConfirmationChallenge
        | PlanConfirmationResult
    ):
        if not command.invocation_id:
            raise PlanValidationError("COMMAND_INVOCATION_ID_REQUIRED")
        command.actor.validate(
            confirmation=isinstance(command, ConfirmTradePlanVersion)
        )
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
    "GetActiveTradePlan",
    "GetTradePlanGraph",
    "IssuePlanConfirmationChallenge",
    "PlanCommandActor",
    "PlanConfirmationResult",
    "RejectTradePlanDraft",
    "TradePlanTasks",
]
