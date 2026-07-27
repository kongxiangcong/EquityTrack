from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.test_decision_tasks import _task_review
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    ApplicationCommandFailure,
    ApplicationCommandResult,
    CorrectExecution,
    DeclareExecution,
    GetEstimatedAccountState,
    ListDecisionTasks,
    ListDecisionJournal,
    open_account_state_queries,
    open_decision_journal,
    open_decision_tasks,
    open_application_commands,
)
from trading_platform.domain.decision_journal import (
    DecisionJournalError,
    ExecutionVerificationState,
)
from trading_platform.domain.decision_tasks import DecisionTaskState


def _declare(task_id: str, invocation_id: str) -> DeclareExecution:
    return DeclareExecution(
        invocation_id=invocation_id,
        decision_task_id=task_id,
        reason="user declared completed execution",
        effective_at="2026-07-27T14:30:00+08:00",
        effective_session="2026-07-27",
        intent_type="increase",
        quantity="100",
        price_state="known",
        price_value="10.25",
        fee_state="unknown",
        fee_value=None,
        currency="CNY",
        confirmed_at="2026-07-27T18:00:00+08:00",
        decision_actor="user:local-user",
        interaction_channel="skill",
        transport_actor="agent:codex",
    )


def test_executed_disposition_updates_estimated_state(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="execution",
        invocation_id="execution:review",
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    before_snapshot = tuple(
        connection.execute(
            "SELECT account_snapshot_version_id,graph_seal_hash "
            "FROM account_snapshot_version ORDER BY version_no"
        )
    )
    connection.close()
    with open_account_state_queries(data_root) as states:
        before = states.get(GetEstimatedAccountState("account_local"))
    with open_decision_journal(data_root) as journal:
        execution = journal.declare(
            _declare(task.decision_task_id, "execution:declare")
        )
    with open_account_state_queries(data_root) as states:
        after = states.get(GetEstimatedAccountState("account_local"))
    position_before = next(
        item for item in before.positions if item.security_id == "security_600000"
    )
    position_after = next(
        item for item in after.positions if item.security_id == "security_600000"
    )
    assert position_after.total_quantity == str(
        int(position_before.total_quantity) + 100
    )
    assert after.cash_state == "unknown"
    assert after.execution_record_ids == (execution.execution_record_id,)
    assert after.unverified_evidence == (execution.execution_record_id,)
    assert (
        execution.verification_status
        is ExecutionVerificationState.USER_DECLARED_UNVERIFIED
    )
    with open_decision_tasks(data_root) as tasks:
        projected = tasks.list(ListDecisionTasks("account_local"))[0]
    assert projected.state is DecisionTaskState.RESOLVED
    connection = SQLiteOwningAdapterFixture(data_root)
    assert tuple(
        connection.execute(
            "SELECT account_snapshot_version_id,graph_seal_hash "
            "FROM account_snapshot_version ORDER BY version_no"
        )
    ) == before_snapshot
    connection.close()


def test_execution_correction_replaces_original_projection(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="execution-correction",
        invocation_id="execution:correction-review",
    )
    with open_account_state_queries(data_root) as states:
        before = states.get(GetEstimatedAccountState("account_local"))
    before_quantity = next(
        item.total_quantity
        for item in before.positions
        if item.security_id == "security_600000"
    )
    with open_decision_journal(data_root) as journal:
        original = journal.declare(
            _declare(task.decision_task_id, "execution:correction-original")
        )
        corrected = journal.correct(
            CorrectExecution(
                invocation_id="execution:correction",
                original_execution_record_id=original.execution_record_id,
                reason="correct quantity",
                effective_at=original.effective_at,
                effective_session=original.effective_session,
                intent_type=original.intent_type,
                quantity="120",
                price_state=original.price_state,
                price_value=original.price_value,
                fee_state=original.fee_state,
                fee_value=original.fee_value,
                currency=original.currency,
                confirmed_at="2026-07-27T18:30:00+08:00",
                decision_actor="user:local-user",
                interaction_channel="skill",
                transport_actor="agent:codex",
            )
        )
        replay = journal.correct(
            CorrectExecution(
                invocation_id="execution:correction",
                original_execution_record_id=original.execution_record_id,
                reason="correct quantity",
                effective_at=original.effective_at,
                effective_session=original.effective_session,
                intent_type=original.intent_type,
                quantity="120",
                price_state=original.price_state,
                price_value=original.price_value,
                fee_state=original.fee_state,
                fee_value=original.fee_value,
                currency=original.currency,
                confirmed_at="2026-07-27T18:30:00+08:00",
                decision_actor="user:local-user",
                interaction_channel="skill",
                transport_actor="agent:codex",
            )
        )
    assert replay == corrected
    assert corrected.corrects_execution_record_id == original.execution_record_id
    with open_account_state_queries(data_root) as states:
        projected = states.get(GetEstimatedAccountState("account_local"))
    assert projected.execution_record_ids == (corrected.execution_record_id,)
    corrected_quantity = next(
        item.total_quantity
        for item in projected.positions
        if item.security_id == "security_600000"
    )
    assert corrected_quantity == str(int(before_quantity) + 120)
    with open_decision_journal(data_root) as journal:
        view = journal.list(ListDecisionJournal("account_local"))
    assert len(view.executions) == 2
    assert len(view.actions) == 2


def test_execution_invocation_conflict_and_invalid_quantity_fail_closed(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="execution-invalid",
        invocation_id="execution:invalid-review",
    )
    command = _declare(task.decision_task_id, "execution:invalid")
    with open_decision_journal(data_root) as journal:
        with pytest.raises(
            DecisionJournalError, match="EXECUTION_QUANTITY_INVALID"
        ):
            journal.declare(replace(command, quantity="0"))
        original = journal.declare(command)
        assert journal.declare(command) == original
        with pytest.raises(
            DecisionJournalError, match="DECISION_JOURNAL_INVOCATION_CONFLICT"
        ):
            journal.declare(replace(command, quantity="101"))


def test_missing_broker_evidence_is_unverified_not_not_executed(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="execution-unverified",
        invocation_id="execution:unverified-review",
    )
    with open_decision_journal(data_root) as journal:
        execution = journal.declare(
            _declare(task.decision_task_id, "execution:unverified")
        )
    assert execution.verification_status.value == "user_declared_unverified"
    assert "not_executed" not in execution.verification_status.value


def test_execution_action_transition_and_receipt_rollback_together(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="execution-rollback",
        invocation_id="execution:rollback-review",
    )

    def fail(boundary: str) -> None:
        if boundary == "decision_journal.before_commit":
            raise RuntimeError("injected execution failure")

    with open_decision_journal(
        data_root, fault_injector=fail
    ) as journal, pytest.raises(RuntimeError, match="injected"):
        journal.declare(
            _declare(task.decision_task_id, "execution:rollback")
        )
    connection = SQLiteOwningAdapterFixture(data_root)
    for table in (
        "action_log_entry",
        "execution_record",
        "decision_task_transition",
    ):
        assert connection.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM application_command_receipt "
        "WHERE invocation_id='execution:rollback'"
    ).fetchone()[0] == 0
    connection.close()


def test_shared_envelope_declares_execution_with_same_receipt_hash(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="execution-envelope",
        invocation_id="execution:envelope-review",
    )

    def envelope(actor_type: str):
        return ApplicationCommandEnvelopeV1.from_bytes(
            json.dumps(
                {
                    "schema_version": "ApplicationCommandEnvelope@1",
                    "command_name": "execution_record.declare@1",
                    "invocation_id": "execution:envelope",
                    "payload_schema_version": "DeclareExecutionRecord@1",
                    "expected_revision": None,
                    "decision_actor": {
                        "actor_type": actor_type,
                        "actor_id": (
                            "local-user"
                            if actor_type == "user"
                            else "codex"
                        ),
                    },
                    "interaction_channel": "skill",
                    "transport_actor": {
                        "actor_type": "agent",
                        "actor_id": "codex",
                    },
                    "approval": None,
                    "payload": {
                        "decision_task_id": task.decision_task_id,
                        "reason": "user declared completed execution",
                        "effective_at": "2026-07-27T14:30:00+08:00",
                        "effective_session": "2026-07-27",
                        "intent_type": "increase",
                        "quantity": "100",
                        "price_state": "known",
                        "price_value": "10.25",
                        "fee_state": "unknown",
                        "fee_value": None,
                        "currency": "CNY",
                        "confirmed_at": "2026-07-27T18:00:00+08:00",
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )

    with open_application_commands(data_root) as dispatcher:
        denied = dispatcher.dispatch(envelope("agent"))
        result = dispatcher.dispatch(envelope("user"))
        replay = dispatcher.dispatch(envelope("user"))
    assert isinstance(denied, ApplicationCommandFailure)
    assert denied.code == "USER_DECISION_CAPABILITY_REQUIRED"
    assert isinstance(result, ApplicationCommandResult)
    assert replay == result
    connection = SQLiteOwningAdapterFixture(data_root)
    receipt = connection.execute(
        "SELECT request_hash FROM application_command_receipt "
        "WHERE invocation_id='execution:envelope'"
    ).fetchone()
    assert receipt["request_hash"] == result.request_hash
    connection.close()
