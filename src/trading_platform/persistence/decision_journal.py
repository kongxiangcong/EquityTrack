from __future__ import annotations

import sqlite3

from trading_platform.application.decision_journal import (
    CorrectExecution,
    DecisionJournalView,
    DeclareExecution,
    ListDecisionJournal,
    RecordTaskAction,
)
from trading_platform.domain.account_snapshots import AccountSnapshotVersion
from trading_platform.domain.account_state import ExecutionProjectionRecord
from trading_platform.domain.decision_journal import (
    ActionLogEntry,
    DecisionJournalError,
    ExecutionCorrection,
    ExecutionRecord,
    ExecutionVerificationState,
    build_action_log_entry,
    build_execution_record,
)
from trading_platform.domain.decision_tasks import (
    DecisionTask,
    DecisionTaskState,
    UserDisposition,
    build_transition,
)
from trading_platform.identity import canonical_hash

from .decision_tasks import SQLiteDecisionTaskRepository
from .locking import DataRootWriterLock


class SQLiteDecisionJournalRepository:
    """Owns atomic action, execution, task, and receipt persistence."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        writer_lock: DataRootWriterLock,
    ) -> None:
        self._connection = connection
        self._writer_lock = writer_lock
        self._tasks = SQLiteDecisionTaskRepository(
            connection, writer_lock
        )
        self.fault_injector = None

    def _fault(self, boundary: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(boundary)

    def record_action(
        self, command: RecordTaskAction
    ) -> DecisionTask:
        if (
            not command.command_name
            or not command.request_hash
            or command.disposition is UserDisposition.EXECUTED
        ):
            raise DecisionJournalError(
                "DECISION_JOURNAL_ACTION_INVALID"
            )
        with self._writer_lock.acquire(
            f"decision-journal-action:{command.decision_task_id}"
        ):
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._task_receipt_replay(
                    command.invocation_id,
                    command.command_name,
                    command.request_hash,
                    command.decision_task_id,
                )
                if replay is not None:
                    self._connection.rollback()
                    return replay
                task = self._tasks.project_in_transaction(
                    command.decision_task_id
                )
                if task.state is not DecisionTaskState.OPEN:
                    raise DecisionJournalError(
                        "DECISION_TASK_STATE_CONFLICT"
                    )
                if (
                    command.disposition is UserDisposition.DEFERRED
                    and command.deferral_condition is None
                ) or (
                    command.disposition is not UserDisposition.DEFERRED
                    and command.deferral_condition is not None
                ):
                    raise DecisionJournalError(
                        "DECISION_JOURNAL_ACTION_INVALID"
                    )
                action = build_action_log_entry(
                    decision_task_id=task.decision_task_id,
                    disposition=command.disposition,
                    reason=command.reason,
                    occurred_at=command.occurred_at,
                    recorded_at=command.recorded_at,
                    decision_actor=command.decision_actor,
                    interaction_channel=command.interaction_channel,
                    transport_actor=command.transport_actor,
                )
                target = (
                    DecisionTaskState.DEFERRED
                    if command.disposition is UserDisposition.DEFERRED
                    else DecisionTaskState.RESOLVED
                )
                transition = build_transition(
                    task=task,
                    to_status=target,
                    trigger_kind="user_disposition",
                    disposition=command.disposition,
                    deferral_condition=command.deferral_condition,
                    evidence_ref=command.reason,
                    action_log_entry_id=action.action_log_entry_id,
                    decision_actor=command.decision_actor,
                    interaction_channel=command.interaction_channel,
                    transport_actor=command.transport_actor,
                    occurred_at=command.occurred_at,
                )
                self._insert_action(action)
                self._tasks.append_in_transaction(transition)
                self._insert_receipt(
                    invocation_id=command.invocation_id,
                    command_name=command.command_name,
                    request_hash=command.request_hash,
                    result_type="DecisionTask",
                    aggregate_id=task.decision_task_id,
                    version_id=transition.transition_id,
                    status=target.value,
                    decision_actor=command.decision_actor,
                    interaction_channel=command.interaction_channel,
                    transport_actor=command.transport_actor,
                    created_at=command.recorded_at,
                )
                self._fault("decision_journal.before_commit")
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return self._task_projection_for_transition(
            task.decision_task_id, transition.transition_id
        )

    def declare(self, command: DeclareExecution) -> ExecutionRecord:
        request_hash = canonical_hash(command)
        with self._writer_lock.acquire(
            f"decision-journal-declare:{command.decision_task_id}"
        ):
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._execution_receipt_replay(
                    command.invocation_id,
                    "execution_record.declare@1",
                    request_hash,
                )
                if replay is not None:
                    self._connection.rollback()
                    return replay
                task = self._tasks.project_in_transaction(
                    command.decision_task_id
                )
                if task.state is not DecisionTaskState.OPEN:
                    raise DecisionJournalError(
                        "DECISION_TASK_STATE_CONFLICT"
                    )
                action = build_action_log_entry(
                    decision_task_id=task.decision_task_id,
                    disposition=UserDisposition.EXECUTED,
                    reason=command.reason,
                    occurred_at=command.effective_at,
                    recorded_at=command.confirmed_at,
                    decision_actor=command.decision_actor,
                    interaction_channel=command.interaction_channel,
                    transport_actor=command.transport_actor,
                )
                execution = build_execution_record(
                    action=action,
                    account_id=task.account_id,
                    security_id=task.security_id,
                    plan_version_id=task.plan_version_id,
                    effective_at=command.effective_at,
                    effective_session=command.effective_session,
                    intent_type=command.intent_type,
                    quantity=command.quantity,
                    price_state=command.price_state,
                    price_value=command.price_value,
                    fee_state=command.fee_state,
                    fee_value=command.fee_value,
                    currency=command.currency,
                    confirmed_at=command.confirmed_at,
                )
                transition = build_transition(
                    task=task,
                    to_status=DecisionTaskState.RESOLVED,
                    trigger_kind="user_disposition",
                    disposition=UserDisposition.EXECUTED,
                    deferral_condition=None,
                    evidence_ref=execution.execution_record_id,
                    action_log_entry_id=action.action_log_entry_id,
                    decision_actor=command.decision_actor,
                    interaction_channel=command.interaction_channel,
                    transport_actor=command.transport_actor,
                    occurred_at=command.confirmed_at,
                )
                self._insert_action(action)
                self._insert_execution(execution)
                self._tasks.append_in_transaction(transition)
                self._insert_receipt(
                    invocation_id=command.invocation_id,
                    command_name="execution_record.declare@1",
                    request_hash=request_hash,
                    result_type="ExecutionRecord",
                    aggregate_id=task.decision_task_id,
                    version_id=execution.execution_record_id,
                    status="succeeded",
                    decision_actor=command.decision_actor,
                    interaction_channel=command.interaction_channel,
                    transport_actor=command.transport_actor,
                    created_at=command.confirmed_at,
                )
                self._fault("decision_journal.before_commit")
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return execution

    def correct(self, command: CorrectExecution) -> ExecutionRecord:
        request_hash = canonical_hash(command)
        with self._writer_lock.acquire(
            "decision-journal-correct:"
            + command.original_execution_record_id
        ):
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._execution_receipt_replay(
                    command.invocation_id,
                    "execution_record.correct@1",
                    request_hash,
                )
                if replay is not None:
                    self._connection.rollback()
                    return replay
                original = self._execution(
                    command.original_execution_record_id
                )
                original_action = self._action(
                    original.action_log_entry_id
                )
                if self._connection.execute(
                    "SELECT 1 FROM execution_record "
                    "WHERE corrects_execution_record_id=?",
                    (original.execution_record_id,),
                ).fetchone():
                    raise DecisionJournalError(
                        "EXECUTION_ALREADY_CORRECTED"
                    )
                action = build_action_log_entry(
                    decision_task_id=original.decision_task_id,
                    disposition=UserDisposition.EXECUTED,
                    reason=command.reason,
                    occurred_at=command.effective_at,
                    recorded_at=command.confirmed_at,
                    decision_actor=command.decision_actor,
                    interaction_channel=command.interaction_channel,
                    transport_actor=command.transport_actor,
                    corrects_entry_id=(
                        original_action.action_log_entry_id
                    ),
                )
                execution = build_execution_record(
                    action=action,
                    account_id=original.account_id,
                    security_id=original.security_id,
                    plan_version_id=original.plan_version_id,
                    effective_at=command.effective_at,
                    effective_session=command.effective_session,
                    intent_type=command.intent_type,
                    quantity=command.quantity,
                    price_state=command.price_state,
                    price_value=command.price_value,
                    fee_state=command.fee_state,
                    fee_value=command.fee_value,
                    currency=command.currency,
                    confirmed_at=command.confirmed_at,
                    corrects_execution_record_id=(
                        original.execution_record_id
                    ),
                )
                correction = ExecutionCorrection(
                    original_execution_record_id=(
                        original.execution_record_id
                    ),
                    original_action_log_entry_id=(
                        original_action.action_log_entry_id
                    ),
                    corrected_execution_record_id=(
                        execution.execution_record_id
                    ),
                    corrected_action_log_entry_id=(
                        action.action_log_entry_id
                    ),
                    reason=command.reason,
                )
                correction.validate()
                self._insert_action(action)
                self._insert_execution(execution)
                self._insert_receipt(
                    invocation_id=command.invocation_id,
                    command_name="execution_record.correct@1",
                    request_hash=request_hash,
                    result_type="ExecutionRecord",
                    aggregate_id=original.decision_task_id,
                    version_id=execution.execution_record_id,
                    status="succeeded",
                    decision_actor=command.decision_actor,
                    interaction_channel=command.interaction_channel,
                    transport_actor=command.transport_actor,
                    created_at=command.confirmed_at,
                )
                self._fault("decision_journal.before_commit")
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return execution

    def list(
        self, query: ListDecisionJournal
    ) -> DecisionJournalView:
        actions = tuple(
            self._action(str(row["action_log_entry_id"]))
            for row in self._connection.execute(
                "SELECT a.action_log_entry_id FROM action_log_entry a "
                "JOIN decision_task t USING(decision_task_id) "
                "WHERE t.account_id=? "
                "ORDER BY a.recorded_at,a.action_log_entry_id",
                (query.account_id,),
            )
        )
        executions = tuple(
            self._execution(str(row["execution_record_id"]))
            for row in self._connection.execute(
                "SELECT execution_record_id FROM execution_record "
                "WHERE account_id=? "
                "ORDER BY confirmed_at,execution_record_id",
                (query.account_id,),
            )
        )
        return DecisionJournalView(
            query.account_id, actions, executions
        )

    def read_confirmed(
        self,
        account_id: str,
        *,
        after_snapshot: AccountSnapshotVersion,
        through_snapshot: AccountSnapshotVersion | None = None,
    ) -> tuple[ExecutionProjectionRecord, ...]:
        del after_snapshot, through_snapshot
        return tuple(
            ExecutionProjectionRecord(
                execution_record_id=row["execution_record_id"],
                account_id=row["account_id"],
                security_id=row["security_id"],
                effective_at=row["effective_at"],
                effective_session=row["effective_session"],
                intent_type=row["intent_type"],
                quantity=row["quantity"],
                price_state=row["price_state"],
                price_value=row["price_value"],
                fee_state=row["fee_state"],
                fee_value=row["fee_value"],
                currency=row["currency"],
                verification_status=row["verification_status"],
                corrects_execution_record_id=row[
                    "corrects_execution_record_id"
                ],
                content_hash=row["content_hash"],
            )
            for row in self._connection.execute(
                "SELECT * FROM execution_record WHERE account_id=? "
                "ORDER BY effective_at,effective_session,"
                "execution_record_id",
                (account_id,),
            )
        )

    def _task_receipt_replay(
        self,
        invocation_id: str,
        command_name: str,
        request_hash: str,
        decision_task_id: str,
    ) -> DecisionTask | None:
        row = self._receipt(invocation_id)
        if row is None:
            return None
        if (
            row["command_name"] != command_name
            or row["request_hash"] != request_hash
            or row["aggregate_id"] != decision_task_id
        ):
            raise DecisionJournalError(
                "DECISION_TASK_INVOCATION_CONFLICT"
            )
        return self._task_projection_for_transition(
            decision_task_id, row["revision_or_version_id"]
        )

    def _execution_receipt_replay(
        self,
        invocation_id: str,
        command_name: str,
        request_hash: str,
    ) -> ExecutionRecord | None:
        row = self._receipt(invocation_id)
        if row is None:
            return None
        if (
            row["command_name"] != command_name
            or row["request_hash"] != request_hash
        ):
            raise DecisionJournalError(
                "DECISION_JOURNAL_INVOCATION_CONFLICT"
            )
        return self._execution(str(row["revision_or_version_id"]))

    def _receipt(self, invocation_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM application_command_receipt "
            "WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()

    def _task_projection_for_transition(
        self, decision_task_id: str, transition_id: str
    ) -> DecisionTask:
        row = self._connection.execute(
            "SELECT transition_seq FROM decision_task_transition "
            "WHERE transition_id=? AND decision_task_id=?",
            (transition_id, decision_task_id),
        ).fetchone()
        if row is None:
            raise DecisionJournalError(
                "DECISION_JOURNAL_RECEIPT_CORRUPT"
            )
        sequence = int(row["transition_seq"])
        if self._connection.in_transaction:
            return self._tasks.project_in_transaction(
                decision_task_id, through_seq=sequence
            )
        return self._tasks.get(
            decision_task_id, through_seq=sequence
        )

    def _insert_action(self, action: ActionLogEntry) -> None:
        action.validate()
        self._connection.execute(
            "INSERT INTO action_log_entry VALUES("
            + ",".join("?" for _ in range(12))
            + ")",
            (
                action.action_log_entry_id,
                action.decision_task_id,
                action.decision_actor,
                action.interaction_channel,
                action.transport_actor,
                action.disposition.value,
                action.reason,
                action.occurred_at,
                action.recorded_at,
                action.corrects_entry_id,
                action.content_hash,
                action.schema_version,
            ),
        )

    def _insert_execution(self, execution: ExecutionRecord) -> None:
        execution.validate()
        self._connection.execute(
            "INSERT INTO execution_record VALUES("
            + ",".join("?" for _ in range(20))
            + ")",
            (
                execution.execution_record_id,
                execution.action_log_entry_id,
                execution.account_id,
                execution.security_id,
                execution.plan_version_id,
                execution.decision_task_id,
                execution.effective_at,
                execution.effective_session,
                execution.intent_type,
                execution.quantity,
                execution.price_state,
                execution.price_value,
                execution.fee_state,
                execution.fee_value,
                execution.currency,
                execution.verification_status.value,
                execution.corrects_execution_record_id,
                execution.content_hash,
                execution.confirmed_at,
                execution.schema_version,
            ),
        )

    def _insert_receipt(
        self,
        *,
        invocation_id: str,
        command_name: str,
        request_hash: str,
        result_type: str,
        aggregate_id: str,
        version_id: str,
        status: str,
        decision_actor: str,
        interaction_channel: str,
        transport_actor: str,
        created_at: str,
    ) -> None:
        self._connection.execute(
            "INSERT INTO application_command_receipt VALUES("
            "?,?,?,?,?,?,?,?,?,?,?)",
            (
                invocation_id,
                command_name,
                request_hash,
                result_type,
                aggregate_id,
                version_id,
                status,
                decision_actor,
                interaction_channel,
                transport_actor,
                created_at,
            ),
        )

    def _action(self, action_log_entry_id: str) -> ActionLogEntry:
        row = self._connection.execute(
            "SELECT * FROM action_log_entry "
            "WHERE action_log_entry_id=?",
            (action_log_entry_id,),
        ).fetchone()
        if row is None:
            raise DecisionJournalError("ACTION_LOG_ENTRY_NOT_FOUND")
        action = ActionLogEntry(
            action_log_entry_id=row["action_log_entry_id"],
            decision_task_id=row["decision_task_id"],
            decision_actor=row["decision_actor"],
            interaction_channel=row["interaction_channel"],
            transport_actor=row["transport_actor"],
            disposition=UserDisposition(row["disposition"]),
            reason=row["reason"],
            occurred_at=row["occurred_at"],
            recorded_at=row["recorded_at"],
            corrects_entry_id=row["corrects_entry_id"],
            content_hash=row["content_hash"],
            schema_version=row["schema_version"],
        )
        action.validate()
        return action

    def _execution(self, execution_record_id: str) -> ExecutionRecord:
        row = self._connection.execute(
            "SELECT * FROM execution_record WHERE execution_record_id=?",
            (execution_record_id,),
        ).fetchone()
        if row is None:
            raise DecisionJournalError("EXECUTION_RECORD_NOT_FOUND")
        execution = ExecutionRecord(
            execution_record_id=row["execution_record_id"],
            action_log_entry_id=row["action_log_entry_id"],
            account_id=row["account_id"],
            security_id=row["security_id"],
            plan_version_id=row["plan_version_id"],
            decision_task_id=row["decision_task_id"],
            effective_at=row["effective_at"],
            effective_session=row["effective_session"],
            intent_type=row["intent_type"],
            quantity=row["quantity"],
            price_state=row["price_state"],
            price_value=row["price_value"],
            fee_state=row["fee_state"],
            fee_value=row["fee_value"],
            currency=row["currency"],
            verification_status=ExecutionVerificationState(
                row["verification_status"]
            ),
            corrects_execution_record_id=row[
                "corrects_execution_record_id"
            ],
            content_hash=row["content_hash"],
            confirmed_at=row["confirmed_at"],
            schema_version=row["schema_version"],
        )
        execution.validate()
        return execution


__all__ = ["SQLiteDecisionJournalRepository"]
