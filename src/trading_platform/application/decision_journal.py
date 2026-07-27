from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trading_platform.domain.decision_journal import (
    ActionLogEntry,
    DecisionJournalError,
    ExecutionRecord,
)
from trading_platform.domain.decision_tasks import (
    DeferralCondition,
    UserDisposition,
)


@dataclass(frozen=True)
class RecordTaskAction:
    invocation_id: str
    decision_task_id: str
    disposition: UserDisposition
    reason: str
    occurred_at: str
    recorded_at: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    deferral_condition: DeferralCondition | None = None
    command_name: str = ""
    request_hash: str = ""


@dataclass(frozen=True)
class DeclareExecution:
    invocation_id: str
    decision_task_id: str
    reason: str
    effective_at: str
    effective_session: str
    intent_type: str
    quantity: str
    price_state: str
    price_value: str | None
    fee_state: str
    fee_value: str | None
    currency: str
    confirmed_at: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    schema_version: str = "DeclareExecutionRecord@1"


@dataclass(frozen=True)
class CorrectExecution:
    invocation_id: str
    original_execution_record_id: str
    reason: str
    effective_at: str
    effective_session: str
    intent_type: str
    quantity: str
    price_state: str
    price_value: str | None
    fee_state: str
    fee_value: str | None
    currency: str
    confirmed_at: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    schema_version: str = "CorrectExecutionRecord@1"


@dataclass(frozen=True)
class ListDecisionJournal:
    account_id: str


@dataclass(frozen=True)
class DecisionJournalView:
    account_id: str
    actions: tuple[ActionLogEntry, ...]
    executions: tuple[ExecutionRecord, ...]


class DecisionJournalRepository(Protocol):
    def declare(self, command: DeclareExecution) -> ExecutionRecord: ...

    def correct(self, command: CorrectExecution) -> ExecutionRecord: ...

    def list(
        self, query: ListDecisionJournal
    ) -> DecisionJournalView: ...


class DecisionJournal:
    """Owns formal user-declared behavior and execution operations."""

    def __init__(self, repository: DecisionJournalRepository) -> None:
        self._repository = repository

    def declare(self, command: DeclareExecution) -> ExecutionRecord:
        self._require_user(
            command.decision_actor,
            command.interaction_channel,
            command.transport_actor,
        )
        if (
            command.schema_version != "DeclareExecutionRecord@1"
            or not command.invocation_id
            or not command.decision_task_id
            or not command.reason.strip()
        ):
            raise DecisionJournalError(
                "DECISION_JOURNAL_COMMAND_INVALID"
            )
        return self._repository.declare(command)

    def correct(self, command: CorrectExecution) -> ExecutionRecord:
        self._require_user(
            command.decision_actor,
            command.interaction_channel,
            command.transport_actor,
        )
        if (
            command.schema_version != "CorrectExecutionRecord@1"
            or not command.invocation_id
            or not command.original_execution_record_id
            or not command.reason.strip()
        ):
            raise DecisionJournalError(
                "DECISION_JOURNAL_COMMAND_INVALID"
            )
        return self._repository.correct(command)

    def list(self, query: ListDecisionJournal) -> DecisionJournalView:
        if not query.account_id:
            raise DecisionJournalError(
                "DECISION_JOURNAL_ACCOUNT_REQUIRED"
            )
        return self._repository.list(query)

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
            or (
                interaction_channel == "cli"
                and not transport_actor.startswith(
                    ("user:", "agent:", "adapter:")
                )
            )
        ):
            raise DecisionJournalError(
                "USER_DECISION_CAPABILITY_REQUIRED"
            )


__all__ = [
    "CorrectExecution",
    "DecisionJournal",
    "DeclareExecution",
    "ListDecisionJournal",
    "RecordTaskAction",
]
