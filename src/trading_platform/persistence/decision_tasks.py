from __future__ import annotations

import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING

from trading_platform.domain.decision_tasks import (
    DecisionTask,
    DecisionTaskError,
    DecisionTaskState,
    DecisionTaskTransition,
    DeferralCondition,
    UserDisposition,
    build_transition,
)

from .locking import DataRootWriterLock

if TYPE_CHECKING:
    from trading_platform.application.decision_tasks import (
        AppendDecisionTaskTransition,
        ListDecisionTasks,
        ReopenDecisionTasks,
    )


class SQLiteDecisionTaskRepository:
    """Owns immutable task materialization and transition replay."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        writer_lock: DataRootWriterLock,
    ) -> None:
        self._connection = connection
        self._writer_lock = writer_lock

    def materialize_in_transaction(
        self, tasks: tuple[DecisionTask, ...]
    ) -> None:
        if not self._connection.in_transaction:
            raise DecisionTaskError(
                "DECISION_TASK_TRANSACTION_REQUIRED"
            )
        for task in tasks:
            task.validate()
            existing = self._connection.execute(
                "SELECT * FROM decision_task WHERE decision_task_id=? "
                "OR (account_id=? AND security_id=? AND condition_identity=?)",
                (
                    task.decision_task_id,
                    task.account_id,
                    task.security_id,
                    task.condition_identity,
                ),
            ).fetchone()
            if existing is not None:
                stored = self._base_task(existing)
                if not stored.represents_same_persistent_condition(task):
                    raise DecisionTaskError(
                        "DECISION_TASK_IDENTITY_CONFLICT"
                    )
                continue
            self._connection.execute(
                "INSERT INTO decision_task VALUES("
                + ",".join("?" for _ in range(16))
                + ")",
                (
                    task.decision_task_id,
                    task.account_id,
                    task.security_id,
                    task.review_run_id,
                    task.review_item_id,
                    task.plan_version_id,
                    task.plan_evaluation_id,
                    task.task_kind,
                    task.reason_code,
                    task.priority,
                    DecisionTaskState.OPEN.value,
                    task.condition_identity,
                    task.evidence_manifest_id,
                    task.created_at,
                    task.content_hash,
                    task.schema_version,
                ),
            )

    def list(
        self, query: "ListDecisionTasks"
    ) -> tuple[DecisionTask, ...]:
        rows = self._connection.execute(
            "SELECT decision_task_id FROM decision_task "
            "WHERE account_id=? ORDER BY created_at,decision_task_id",
            (query.account_id,),
        ).fetchall()
        tasks = tuple(
            self._project(str(row["decision_task_id"])) for row in rows
        )
        if query.states:
            allowed = set(query.states)
            tasks = tuple(task for task in tasks if task.state in allowed)
        return tasks

    def get(
        self,
        decision_task_id: str,
        *,
        through_seq: int | None = None,
    ) -> DecisionTask:
        return self._project(
            decision_task_id, through_seq=through_seq
        )

    def project_in_transaction(
        self,
        decision_task_id: str,
        *,
        through_seq: int | None = None,
    ) -> DecisionTask:
        if not self._connection.in_transaction:
            raise DecisionTaskError(
                "DECISION_TASK_TRANSACTION_REQUIRED"
            )
        return self._project(
            decision_task_id, through_seq=through_seq
        )

    def append_in_transaction(
        self, transition: DecisionTaskTransition
    ) -> None:
        if not self._connection.in_transaction:
            raise DecisionTaskError(
                "DECISION_TASK_TRANSACTION_REQUIRED"
            )
        self._insert_transition(transition)

    def append(
        self, request: "AppendDecisionTaskTransition"
    ) -> DecisionTask:
        with self._writer_lock.acquire(
            f"decision-task-transition:{request.decision_task_id}"
        ):
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._receipt_replay(request)
                if replay is not None:
                    self._connection.rollback()
                    return replay
                task = self._project(request.decision_task_id)
                if (
                    request.invocation_id is None
                    and task.state is request.to_status
                    and task.latest_transition_id is not None
                ):
                    latest = self._connection.execute(
                        "SELECT trigger_kind,evidence_ref "
                        "FROM decision_task_transition "
                        "WHERE transition_id=?",
                        (task.latest_transition_id,),
                    ).fetchone()
                    if (
                        latest is not None
                        and latest["trigger_kind"]
                        == request.trigger_kind
                        and latest["evidence_ref"]
                        == request.evidence_ref
                    ):
                        self._connection.rollback()
                        return task
                if task.state not in request.allowed_from:
                    raise DecisionTaskError(
                        "DECISION_TASK_STATE_CONFLICT"
                    )
                transition = build_transition(
                    task=task,
                    to_status=request.to_status,
                    trigger_kind=request.trigger_kind,
                    disposition=request.disposition,
                    deferral_condition=request.deferral_condition,
                    evidence_ref=request.evidence_ref,
                    action_log_entry_id=None,
                    decision_actor=request.decision_actor,
                    interaction_channel=request.interaction_channel,
                    transport_actor=request.transport_actor,
                    occurred_at=request.occurred_at,
                )
                self._insert_transition(transition)
                if request.invocation_id is not None:
                    self._insert_receipt(request, task, transition)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return self._project(
            request.decision_task_id,
            through_seq=transition.transition_seq,
        )

    def reopen(
        self, command: "ReopenDecisionTasks"
    ) -> tuple[DecisionTask, ...]:
        reopened: list[tuple[str, int]] = []
        with self._writer_lock.acquire(
            f"decision-task-reopen:{command.trigger_kind}:"
            f"{command.trigger_value}"
        ):
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                rows = self._connection.execute(
                    "SELECT decision_task_id FROM decision_task "
                    "ORDER BY decision_task_id"
                ).fetchall()
                for row in rows:
                    task = self._project(
                        str(row["decision_task_id"])
                    )
                    if (
                        task.state is not DecisionTaskState.DEFERRED
                        or task.deferral_condition is None
                        or not self._matches(command, task)
                    ):
                        continue
                    transition = build_transition(
                        task=task,
                        to_status=DecisionTaskState.OPEN,
                        trigger_kind=command.trigger_kind,
                        disposition=None,
                        deferral_condition=None,
                        evidence_ref=command.trigger_value,
                        action_log_entry_id=None,
                        decision_actor=command.decision_actor,
                        interaction_channel=command.interaction_channel,
                        transport_actor=command.transport_actor,
                        occurred_at=command.occurred_at,
                    )
                    self._insert_transition(transition)
                    reopened.append(
                        (
                            task.decision_task_id,
                            transition.transition_seq,
                        )
                    )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return tuple(
            self._project(task_id, through_seq=seq)
            for task_id, seq in reopened
        )

    def _receipt_replay(
        self, request: "AppendDecisionTaskTransition"
    ) -> DecisionTask | None:
        if request.invocation_id is None:
            return None
        row = self._connection.execute(
            "SELECT command_name,request_hash,aggregate_id,"
            "revision_or_version_id FROM application_command_receipt "
            "WHERE invocation_id=?",
            (request.invocation_id,),
        ).fetchone()
        if row is None:
            return None
        if (
            row["command_name"] != request.command_name
            or row["request_hash"] != request.request_hash
            or row["aggregate_id"] != request.decision_task_id
        ):
            raise DecisionTaskError("DECISION_TASK_INVOCATION_CONFLICT")
        transition = self._connection.execute(
            "SELECT transition_seq FROM decision_task_transition "
            "WHERE transition_id=? AND decision_task_id=?",
            (
                row["revision_or_version_id"],
                request.decision_task_id,
            ),
        ).fetchone()
        if transition is None:
            raise DecisionTaskError("DECISION_TASK_RECEIPT_CORRUPT")
        return self._project(
            request.decision_task_id,
            through_seq=int(transition["transition_seq"]),
        )

    def _insert_receipt(
        self,
        request: "AppendDecisionTaskTransition",
        task: DecisionTask,
        transition: DecisionTaskTransition,
    ) -> None:
        self._connection.execute(
            "INSERT INTO application_command_receipt VALUES("
            "?,?,?,?,?,?,?,?,?,?,?)",
            (
                request.invocation_id,
                request.command_name,
                request.request_hash,
                "DecisionTask",
                task.decision_task_id,
                transition.transition_id,
                transition.to_status.value,
                request.decision_actor,
                request.interaction_channel,
                request.transport_actor,
                request.occurred_at,
            ),
        )

    def _insert_transition(
        self, transition: DecisionTaskTransition
    ) -> None:
        transition.validate()
        condition = transition.deferral_condition
        self._connection.execute(
            "INSERT INTO decision_task_transition VALUES("
            + ",".join("?" for _ in range(17))
            + ")",
            (
                transition.transition_id,
                transition.decision_task_id,
                transition.transition_seq,
                transition.from_status.value,
                transition.to_status.value,
                transition.trigger_kind,
                (
                    transition.disposition.value
                    if transition.disposition is not None
                    else None
                ),
                condition.target_type if condition is not None else None,
                condition.target_value if condition is not None else None,
                transition.evidence_ref,
                transition.action_log_entry_id,
                transition.decision_actor,
                transition.interaction_channel,
                transition.transport_actor,
                transition.occurred_at,
                transition.content_hash,
                transition.schema_version,
            ),
        )

    def _project(
        self,
        decision_task_id: str,
        *,
        through_seq: int | None = None,
    ) -> DecisionTask:
        row = self._connection.execute(
            "SELECT * FROM decision_task WHERE decision_task_id=?",
            (decision_task_id,),
        ).fetchone()
        if row is None:
            raise DecisionTaskError("DECISION_TASK_NOT_FOUND")
        task = self._base_task(row)
        sql = (
            "SELECT * FROM decision_task_transition "
            "WHERE decision_task_id=?"
        )
        parameters: tuple[object, ...] = (decision_task_id,)
        if through_seq is not None:
            sql += " AND transition_seq<=?"
            parameters += (through_seq,)
        sql += " ORDER BY transition_seq"
        expected = 1
        for transition_row in self._connection.execute(sql, parameters):
            transition = self._transition(transition_row)
            if (
                transition.transition_seq != expected
                or transition.from_status is not task.state
            ):
                raise DecisionTaskError(
                    "DECISION_TASK_TRANSITION_CORRUPT"
                )
            task = replace(
                task,
                state=transition.to_status,
                transition_seq=transition.transition_seq,
                latest_transition_id=transition.transition_id,
                disposition=transition.disposition,
                deferral_condition=transition.deferral_condition,
            )
            expected += 1
        task.validate()
        return task

    @staticmethod
    def _base_task(row: sqlite3.Row) -> DecisionTask:
        task = DecisionTask(
            decision_task_id=row["decision_task_id"],
            account_id=row["account_id"],
            security_id=row["security_id"],
            review_run_id=row["review_run_id"],
            review_item_id=row["review_item_id"],
            plan_version_id=row["plan_version_id"],
            plan_evaluation_id=row["plan_evaluation_id"],
            task_kind=row["task_kind"],
            reason_code=row["reason_code"],
            priority=row["priority"],
            condition_identity=row["condition_identity"],
            evidence_manifest_id=row["evidence_manifest_id"],
            created_at=row["created_at"],
            content_hash=row["content_hash"],
            state=DecisionTaskState(row["initial_status"]),
            schema_version=row["schema_version"],
        )
        task.validate()
        return task

    @staticmethod
    def _transition(row: sqlite3.Row) -> DecisionTaskTransition:
        condition = (
            DeferralCondition(
                row["defer_target_type"], row["defer_target_value"]
            )
            if row["defer_target_type"] is not None
            else None
        )
        transition = DecisionTaskTransition(
            transition_id=row["transition_id"],
            decision_task_id=row["decision_task_id"],
            transition_seq=int(row["transition_seq"]),
            from_status=DecisionTaskState(row["from_status"]),
            to_status=DecisionTaskState(row["to_status"]),
            trigger_kind=row["trigger_kind"],
            disposition=(
                UserDisposition(row["disposition"])
                if row["disposition"] is not None
                else None
            ),
            deferral_condition=condition,
            evidence_ref=row["evidence_ref"],
            action_log_entry_id=row["action_log_entry_id"],
            decision_actor=row["decision_actor"],
            interaction_channel=row["interaction_channel"],
            transport_actor=row["transport_actor"],
            occurred_at=row["occurred_at"],
            content_hash=row["content_hash"],
            schema_version=row["schema_version"],
        )
        transition.validate()
        return transition

    @staticmethod
    def _matches(
        command: "ReopenDecisionTasks", task: DecisionTask
    ) -> bool:
        assert task.deferral_condition is not None
        condition = task.deferral_condition
        if (
            command.trigger_kind == "date_or_session"
            and condition.target_type == "specific_date_or_session"
        ):
            return command.trigger_value >= str(condition.target_value)
        if (
            command.trigger_kind == "next_review"
            and condition.target_type == "next_manual_review"
        ):
            return command.trigger_value != task.review_run_id
        return (
            command.trigger_kind == "evidence_trigger"
            and condition.target_type == "evidence_trigger"
            and command.trigger_value == condition.target_value
        )


__all__ = ["SQLiteDecisionTaskRepository"]
