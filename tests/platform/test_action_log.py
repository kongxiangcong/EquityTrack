from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.test_decision_tasks import _actor_fields, _task_review
from trading_platform.application import (
    DeferDecisionTask,
    ListDecisionJournal,
    ReopenDecisionTasks,
    ResolveDecisionTask,
    open_decision_journal,
    open_decision_tasks,
)
from trading_platform.domain.decision_tasks import (
    DecisionTaskState,
    DeferralCondition,
    UserDisposition,
)


def test_defer_and_resolve_write_immutable_action_entries(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="action-log",
        invocation_id="action-log:review",
    )
    with open_decision_tasks(data_root) as tasks:
        deferred = tasks.defer(
            DeferDecisionTask(
                invocation_id="action-log:defer",
                decision_task_id=task.decision_task_id,
                condition=DeferralCondition(
                    "evidence_trigger", "announcement:new"
                ),
                occurred_at="2026-07-27T17:00:00+08:00",
                **_actor_fields(),
            )
        )
        assert deferred.state is DecisionTaskState.DEFERRED
        reopened = tasks.reopen(
            ReopenDecisionTasks(
                trigger_kind="evidence_trigger",
                trigger_value="announcement:new",
                occurred_at="2026-07-27T17:30:00+08:00",
                decision_actor="system:workflow",
                interaction_channel="workflow",
                transport_actor="adapter:decision-tasks",
            )
        )
        assert reopened[0].state is DecisionTaskState.OPEN
        resolved = tasks.resolve(
            ResolveDecisionTask(
                invocation_id="action-log:resolve",
                decision_task_id=task.decision_task_id,
                disposition=UserDisposition.SKIPPED,
                reason="explicit user disposition",
                occurred_at="2026-07-27T18:00:00+08:00",
                **_actor_fields(),
            )
        )
    assert resolved.state is DecisionTaskState.RESOLVED
    with open_decision_journal(data_root) as journal:
        view = journal.list(ListDecisionJournal("account_local"))
    assert tuple(entry.disposition for entry in view.actions) == (
        UserDisposition.DEFERRED,
        UserDisposition.SKIPPED,
    )
    assert all(entry.decision_actor == "user:local-user" for entry in view.actions)
    connection = SQLiteOwningAdapterFixture(data_root)
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
        connection.execute(
            "UPDATE action_log_entry SET reason='tampered' "
            "WHERE action_log_entry_id=?",
            (view.actions[0].action_log_entry_id,),
        )
    connection.close()


def test_action_and_task_transition_rollback_together(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="action-rollback",
        invocation_id="action-log:rollback-review",
    )

    def fail(boundary: str) -> None:
        if boundary == "decision_journal.before_commit":
            raise RuntimeError("injected journal failure")

    with open_decision_tasks(
        data_root, fault_injector=fail
    ) as tasks, pytest.raises(RuntimeError, match="injected"):
        tasks.resolve(
            ResolveDecisionTask(
                invocation_id="action-log:rollback",
                decision_task_id=task.decision_task_id,
                disposition=UserDisposition.NOT_APPLICABLE,
                reason="fixture",
                occurred_at="2026-07-27T18:00:00+08:00",
                **_actor_fields(),
            )
        )
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM action_log_entry"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM decision_task_transition"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM application_command_receipt "
        "WHERE invocation_id='action-log:rollback'"
    ).fetchone()[0] == 0
    connection.close()
