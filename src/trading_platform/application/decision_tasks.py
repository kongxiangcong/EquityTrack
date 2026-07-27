from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trading_platform.domain.decision_tasks import (
    DecisionTask,
    DecisionTaskError,
    DecisionTaskState,
    DeferralCondition,
    UserDisposition,
)
from trading_platform.identity import canonical_hash


@dataclass(frozen=True)
class ListDecisionTasks:
    account_id: str
    states: tuple[DecisionTaskState, ...] = ()


@dataclass(frozen=True)
class DeferDecisionTask:
    invocation_id: str
    decision_task_id: str
    condition: DeferralCondition
    occurred_at: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    schema_version: str = "DeferDecisionTask@1"


@dataclass(frozen=True)
class ResolveDecisionTask:
    invocation_id: str
    decision_task_id: str
    disposition: UserDisposition
    reason: str
    occurred_at: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    schema_version: str = "ResolveDecisionTask@1"


@dataclass(frozen=True)
class SupersedeDecisionTask:
    decision_task_id: str
    trigger_kind: str
    evidence_ref: str
    occurred_at: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str


@dataclass(frozen=True)
class ReopenDecisionTasks:
    trigger_kind: str
    trigger_value: str
    occurred_at: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str


@dataclass(frozen=True)
class AppendDecisionTaskTransition:
    decision_task_id: str
    allowed_from: tuple[DecisionTaskState, ...]
    to_status: DecisionTaskState
    trigger_kind: str
    disposition: UserDisposition | None
    deferral_condition: DeferralCondition | None
    evidence_ref: str | None
    occurred_at: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    invocation_id: str | None = None
    command_name: str | None = None
    request_hash: str | None = None


class DecisionTaskRepository(Protocol):
    def list(
        self, query: ListDecisionTasks
    ) -> tuple[DecisionTask, ...]: ...

    def append(
        self, request: AppendDecisionTaskTransition
    ) -> DecisionTask: ...

    def reopen(
        self, command: ReopenDecisionTasks
    ) -> tuple[DecisionTask, ...]: ...


class DecisionTasks:
    """Owns complete user and workflow task-lifecycle operations."""

    def __init__(self, repository: DecisionTaskRepository) -> None:
        self._repository = repository

    def list(
        self, query: ListDecisionTasks
    ) -> tuple[DecisionTask, ...]:
        if not query.account_id:
            raise DecisionTaskError("DECISION_TASK_ACCOUNT_REQUIRED")
        return self._repository.list(query)

    def defer(self, command: DeferDecisionTask) -> DecisionTask:
        self._require_user(
            command.decision_actor,
            command.interaction_channel,
            command.transport_actor,
        )
        if (
            command.schema_version != "DeferDecisionTask@1"
            or not command.invocation_id
            or not command.decision_task_id
        ):
            raise DecisionTaskError("DECISION_TASK_COMMAND_INVALID")
        command.condition.validate()
        return self._repository.append(
            AppendDecisionTaskTransition(
                decision_task_id=command.decision_task_id,
                allowed_from=(DecisionTaskState.OPEN,),
                to_status=DecisionTaskState.DEFERRED,
                trigger_kind="user_disposition",
                disposition=UserDisposition.DEFERRED,
                deferral_condition=command.condition,
                evidence_ref=None,
                occurred_at=command.occurred_at,
                decision_actor=command.decision_actor,
                interaction_channel=command.interaction_channel,
                transport_actor=command.transport_actor,
                invocation_id=command.invocation_id,
                command_name="decision_task.defer@1",
                request_hash=canonical_hash(command),
            )
        )

    def resolve(self, command: ResolveDecisionTask) -> DecisionTask:
        self._require_user(
            command.decision_actor,
            command.interaction_channel,
            command.transport_actor,
        )
        if (
            command.schema_version != "ResolveDecisionTask@1"
            or not command.invocation_id
            or not command.decision_task_id
            or not command.reason.strip()
            or command.disposition is UserDisposition.DEFERRED
        ):
            raise DecisionTaskError("DECISION_TASK_COMMAND_INVALID")
        if command.disposition is UserDisposition.EXECUTED:
            raise DecisionTaskError("EXECUTION_RECORD_REQUIRED")
        return self._repository.append(
            AppendDecisionTaskTransition(
                decision_task_id=command.decision_task_id,
                allowed_from=(DecisionTaskState.OPEN,),
                to_status=DecisionTaskState.RESOLVED,
                trigger_kind="user_disposition",
                disposition=command.disposition,
                deferral_condition=None,
                evidence_ref=command.reason,
                occurred_at=command.occurred_at,
                decision_actor=command.decision_actor,
                interaction_channel=command.interaction_channel,
                transport_actor=command.transport_actor,
                invocation_id=command.invocation_id,
                command_name="decision_task.resolve@1",
                request_hash=canonical_hash(command),
            )
        )

    def supersede(
        self, command: SupersedeDecisionTask
    ) -> DecisionTask:
        if (
            command.trigger_kind
            not in {"plan_superseded", "condition_invalidated"}
            or not command.decision_actor.startswith("system:")
            or command.interaction_channel != "workflow"
            or not command.transport_actor.startswith("adapter:")
            or not command.evidence_ref
        ):
            raise DecisionTaskError(
                "SYSTEM_TASK_TRANSITION_CAPABILITY_REQUIRED"
            )
        return self._repository.append(
            AppendDecisionTaskTransition(
                decision_task_id=command.decision_task_id,
                allowed_from=(
                    DecisionTaskState.OPEN,
                    DecisionTaskState.DEFERRED,
                ),
                to_status=DecisionTaskState.SUPERSEDED,
                trigger_kind=command.trigger_kind,
                disposition=None,
                deferral_condition=None,
                evidence_ref=command.evidence_ref,
                occurred_at=command.occurred_at,
                decision_actor=command.decision_actor,
                interaction_channel=command.interaction_channel,
                transport_actor=command.transport_actor,
            )
        )

    def reopen(
        self, command: ReopenDecisionTasks
    ) -> tuple[DecisionTask, ...]:
        if (
            command.trigger_kind
            not in {"date_or_session", "next_review", "evidence_trigger"}
            or not command.trigger_value
            or not command.decision_actor.startswith("system:")
            or command.interaction_channel != "workflow"
            or not command.transport_actor.startswith("adapter:")
        ):
            raise DecisionTaskError(
                "SYSTEM_TASK_TRANSITION_CAPABILITY_REQUIRED"
            )
        return self._repository.reopen(command)

    @staticmethod
    def _require_user(
        decision_actor: str,
        interaction_channel: str,
        transport_actor: str,
    ) -> None:
        if (
            not decision_actor.startswith("user:")
            or interaction_channel not in {"skill", "cli"}
            or (
                interaction_channel == "skill"
                and not transport_actor.startswith("agent:")
            )
            or interaction_channel == "cli"
            and not transport_actor.startswith(
                ("user:", "agent:", "adapter:")
            )
        ):
            raise DecisionTaskError(
                "USER_DECISION_CAPABILITY_REQUIRED"
            )


__all__ = [
    "DecisionTasks",
    "DeferDecisionTask",
    "ListDecisionTasks",
    "ReopenDecisionTasks",
    "ResolveDecisionTask",
    "SupersedeDecisionTask",
]
