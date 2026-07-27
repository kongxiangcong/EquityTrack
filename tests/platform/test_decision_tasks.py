from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.test_manual_portfolio_review import (
    _complete_session,
    _start,
)
from tests.platform.test_plan_confirmation import (
    _authority_root,
    _confirm,
    _create_and_challenge,
    _draft as _plan_draft,
)
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    ApplicationCommandFailure,
    ApplicationCommandResult,
    DeferDecisionTask,
    ListDecisionTasks,
    ReopenDecisionTasks,
    ResolveDecisionTask,
    SupersedeDecisionTask,
    open_application_commands,
    open_decision_tasks,
    open_trade_plan,
)
from trading_platform.domain.approvals import ActivationIntent
from trading_platform.domain.decision_tasks import (
    DecisionTaskError,
    DecisionTaskState,
    DeferralCondition,
    UserDisposition,
)


def _task_review(
    tmp_path: Path,
    *,
    suffix: str,
    invocation_id: str,
    run_review: bool = True,
    resolution_outcome: str = "decision_task",
    rule_id: str = "grid-rule",
    intent_type: str = "decrease",
):
    data_root, snapshot_id = _authority_root(tmp_path)
    with open_trade_plan(data_root) as plans:
        draft, challenge = _create_and_challenge(
            plans,
            _plan_draft(snapshot_id, suffix=suffix),
            suffix,
            ActivationIntent.CONFIRM_AND_ACTIVATE,
        )
        _confirm(plans, challenge, suffix)
    _complete_session(data_root, "2026-07-27")
    connection = SQLiteOwningAdapterFixture(data_root)
    with connection.transaction():
        connection.execute(
            "INSERT INTO market_universe_version VALUES(?,?,?,?,?)",
            (
                f"market_universe_{suffix}",
                "CN_A_SHARE",
                "2026-07-27T15:00:00+08:00",
                "fixture",
                f"membership-{suffix}",
            ),
        )
        connection.execute(
            "INSERT INTO market_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"market_snapshot_{suffix}",
                "security_600000",
                "CN_A_SHARE",
                "2026-07-27",
                "2026-07-27",
                "data_snapshot_review_20260727",
                f"market_universe_{suffix}",
                "cn-a-share-market@1",
                "freshness_fixture@1",
                "code:test",
                f"market-input-{suffix}",
                "complete",
                1,
                "2026-07-27T15:00:00+08:00",
            ),
        )
        connection.execute(
            "INSERT INTO plan_evaluation VALUES("
            + ",".join("?" for _ in range(15))
            + ")",
            (
                f"plan_evaluation_{suffix}",
                draft.proposed_graph.version.plan_version_id,
                f"market_snapshot_{suffix}",
                "plan-evaluator@2",
                "trade-plan-conflict@1",
                "completed",
                resolution_outcome,
                "GRID_TRIGGER_REQUIRES_DISPOSITION",
                (
                    f'{{"winner":{{"rule_id":"{rule_id}",'
                    f'"intent_type":"{intent_type}"}},'
                    f'"evidence_identity":"evidence-{suffix}"}}'
                ),
                f"resolution-hash-{suffix}",
                "complete",
                0,
                f"evaluation-hash-{suffix}",
                1,
                "2026-07-27T15:30:00+08:00",
            ),
        )
    connection.close()
    if not run_review:
        return data_root, None, None
    review = _start(
        data_root,
        invocation_id=invocation_id,
        selected_session="2026-07-27",
    )
    with open_decision_tasks(data_root) as tasks:
        listed = tasks.list(ListDecisionTasks("account_local"))
    assert len(listed) == 1
    return data_root, review, listed[0]


def _actor_fields() -> dict[str, str]:
    return {
        "decision_actor": "user:local-user",
        "interaction_channel": "skill",
        "transport_actor": "agent:codex",
    }


def test_no_change_creates_no_task(tmp_path: Path) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with open_trade_plan(data_root) as plans:
        draft, challenge = _create_and_challenge(
            plans,
            _plan_draft(snapshot_id, suffix="task-no-change"),
            "task-no-change",
            ActivationIntent.CONFIRM_AND_ACTIVATE,
        )
        _confirm(plans, challenge, "task-no-change")
    _complete_session(data_root, "2026-07-27")
    connection = SQLiteOwningAdapterFixture(data_root)
    with connection.transaction():
        connection.execute(
            "INSERT INTO market_universe_version VALUES(?,?,?,?,?)",
            (
                "market_universe_task_no_change",
                "CN_A_SHARE",
                "2026-07-27T15:00:00+08:00",
                "fixture",
                "task-no-change-membership",
            ),
        )
        connection.execute(
            "INSERT INTO market_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "market_snapshot_task_no_change",
                "security_600000",
                "CN_A_SHARE",
                "2026-07-27",
                "2026-07-27",
                "data_snapshot_review_20260727",
                "market_universe_task_no_change",
                "cn-a-share-market@1",
                "freshness_fixture@1",
                "code:test",
                "task-no-change-market-input",
                "complete",
                1,
                "2026-07-27T15:00:00+08:00",
            ),
        )
        connection.execute(
            "INSERT INTO plan_evaluation VALUES("
            + ",".join("?" for _ in range(15))
            + ")",
            (
                "plan_evaluation_task_no_change",
                draft.proposed_graph.version.plan_version_id,
                "market_snapshot_task_no_change",
                "plan-evaluator@2",
                "trade-plan-conflict@1",
                "completed",
                "no_action",
                "NO_RULE_TRIGGERED",
                "{}",
                "task-no-change-resolution-hash",
                "complete",
                0,
                "task-no-change-evaluation-hash",
                0,
                "2026-07-27T15:30:00+08:00",
            ),
        )
    connection.close()
    _start(
        data_root,
        invocation_id="decision-task:no-change",
        selected_session="2026-07-27",
    )
    with open_decision_tasks(data_root) as tasks:
        assert tasks.list(ListDecisionTasks("account_local")) == ()


def test_single_grid_trigger_creates_one_persistent_task(
    tmp_path: Path,
) -> None:
    data_root, review, task = _task_review(
        tmp_path,
        suffix="single-grid",
        invocation_id="decision-task:single-grid",
    )
    replay = _start(
        data_root,
        invocation_id="decision-task:single-grid",
        selected_session="2026-07-27",
    )
    assert replay.review_run_id == review.review_run_id
    assert task.state is DecisionTaskState.OPEN
    assert task.task_kind == "grid_trigger"
    assert task.plan_evaluation_id == "plan_evaluation_single-grid"
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM decision_task"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT decision_task_ids_json FROM manual_portfolio_review_item "
        "WHERE review_run_id=?",
        (review.review_run_id,),
    ).fetchone()[0] == f'["{task.decision_task_id}"]'
    connection.close()


@pytest.mark.parametrize("intent_type", ("increase", "decrease"))
def test_manual_review_intents_create_persistent_user_tasks(
    tmp_path: Path,
    intent_type: str,
) -> None:
    _, _, task = _task_review(
        tmp_path / intent_type,
        suffix=f"manual-{intent_type}",
        invocation_id=f"decision-task:manual-{intent_type}",
        resolution_outcome="manual_review_required",
        rule_id="review-rule",
        intent_type=intent_type,
    )
    assert task.task_kind == "manual_review"
    assert task.state is DecisionTaskState.OPEN


def test_all_deferral_conditions_reopen_the_same_task(
    tmp_path: Path,
) -> None:
    data_root, review, original = _task_review(
        tmp_path,
        suffix="all-deferrals",
        invocation_id="decision-task:all-deferrals",
    )
    cases = (
        (
            DeferralCondition(
                "specific_date_or_session", "2026-07-31"
            ),
            "date_or_session",
            "2026-07-31",
        ),
        (
            DeferralCondition("next_manual_review", None),
            "next_review",
            f"{review.review_run_id}:next",
        ),
        (
            DeferralCondition("evidence_trigger", "announcement:new"),
            "evidence_trigger",
            "announcement:new",
        ),
    )
    with open_decision_tasks(data_root) as tasks:
        for index, (condition, trigger_kind, trigger_value) in enumerate(
            cases, start=1
        ):
            deferred = tasks.defer(
                DeferDecisionTask(
                    invocation_id=f"decision-task:defer:{index}",
                    decision_task_id=original.decision_task_id,
                    condition=condition,
                    occurred_at=(
                        f"2026-07-{27 + index:02d}T10:00:00+08:00"
                    ),
                    **_actor_fields(),
                )
            )
            assert deferred.state is DecisionTaskState.DEFERRED
            reopened = tasks.reopen(
                ReopenDecisionTasks(
                    trigger_kind=trigger_kind,
                    trigger_value=trigger_value,
                    occurred_at=(
                        f"2026-07-{27 + index:02d}T11:00:00+08:00"
                    ),
                    decision_actor="system:workflow",
                    interaction_channel="workflow",
                    transport_actor="adapter:decision-tasks",
                )
            )
            assert tuple(task.decision_task_id for task in reopened) == (
                original.decision_task_id,
            )
            assert reopened[0].state is DecisionTaskState.OPEN
    with open_decision_tasks(data_root) as tasks:
        final = tasks.list(ListDecisionTasks("account_local"))[0]
    assert final.decision_task_id == original.decision_task_id
    assert final.transition_seq == 6


def test_agent_cannot_dispose_and_executed_requires_execution_record(
    tmp_path: Path,
) -> None:
    data_root, review, task = _task_review(
        tmp_path,
        suffix="actor-gate",
        invocation_id="decision-task:actor-gate",
    )
    with open_decision_tasks(data_root) as tasks:
        with pytest.raises(
            DecisionTaskError, match="USER_DECISION_CAPABILITY_REQUIRED"
        ):
            tasks.resolve(
                ResolveDecisionTask(
                    invocation_id="decision-task:agent-resolve",
                    decision_task_id=task.decision_task_id,
                    disposition=UserDisposition.SKIPPED,
                    reason="fixture",
                    occurred_at="2026-07-27T17:00:00+08:00",
                    decision_actor="agent:codex",
                    interaction_channel="skill",
                    transport_actor="agent:codex",
                )
            )
        with pytest.raises(
            DecisionTaskError, match="EXECUTION_RECORD_REQUIRED"
        ):
            tasks.resolve(
                ResolveDecisionTask(
                    invocation_id="decision-task:executed-without-record",
                    decision_task_id=task.decision_task_id,
                    disposition=UserDisposition.EXECUTED,
                    reason="fixture",
                    occurred_at="2026-07-27T17:01:00+08:00",
                    **_actor_fields(),
                )
            )
        resolved = tasks.resolve(
            ResolveDecisionTask(
                invocation_id="decision-task:user-resolve",
                decision_task_id=task.decision_task_id,
                disposition=UserDisposition.SKIPPED,
                reason="user chose not to act",
                occurred_at="2026-07-27T17:02:00+08:00",
                **_actor_fields(),
            )
        )
    assert resolved.state is DecisionTaskState.RESOLVED
    assert resolved.disposition is UserDisposition.SKIPPED


@pytest.mark.parametrize(
    "disposition",
    (
        UserDisposition.SKIPPED,
        UserDisposition.OVERRIDDEN,
        UserDisposition.NOT_APPLICABLE,
    ),
)
def test_user_resolutions_are_immutable_and_restart_visible(
    tmp_path: Path,
    disposition: UserDisposition,
) -> None:
    data_root, _, task = _task_review(
        tmp_path / disposition.value,
        suffix=f"resolve-{disposition.value}",
        invocation_id=f"decision-task:resolve:{disposition.value}",
    )
    with open_decision_tasks(data_root) as tasks:
        resolved = tasks.resolve(
            ResolveDecisionTask(
                invocation_id=(
                    f"decision-task:resolve-command:{disposition.value}"
                ),
                decision_task_id=task.decision_task_id,
                disposition=disposition,
                reason="explicit user disposition",
                occurred_at="2026-07-27T17:10:00+08:00",
                **_actor_fields(),
            )
        )
    with open_decision_tasks(data_root) as restarted:
        loaded = restarted.list(ListDecisionTasks("account_local"))[0]
    assert loaded == resolved
    connection = SQLiteOwningAdapterFixture(data_root)
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
        connection.execute(
            "UPDATE decision_task_transition SET content_hash='tampered' "
            "WHERE decision_task_id=?",
            (task.decision_task_id,),
        )
    connection.close()


def test_plan_invalidation_supersedes_deferred_task_after_restart(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="superseded",
        invocation_id="decision-task:superseded",
    )
    with open_decision_tasks(data_root) as tasks:
        tasks.defer(
            DeferDecisionTask(
                invocation_id="decision-task:superseded:defer",
                decision_task_id=task.decision_task_id,
                condition=DeferralCondition(
                    "evidence_trigger", "announcement:new"
                ),
                occurred_at="2026-07-27T17:00:00+08:00",
                **_actor_fields(),
            )
        )
    with open_decision_tasks(data_root) as restarted:
        superseded = restarted.supersede(
            SupersedeDecisionTask(
                decision_task_id=task.decision_task_id,
                trigger_kind="condition_invalidated",
                evidence_ref="condition:invalidated",
                occurred_at="2026-07-27T18:00:00+08:00",
                decision_actor="system:workflow",
                interaction_channel="workflow",
                transport_actor="adapter:decision-tasks",
            )
        )
    assert superseded.state is DecisionTaskState.SUPERSEDED
    assert superseded.transition_seq == 2


def test_shared_envelope_enforces_actor_and_replays_same_receipt(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="envelope",
        invocation_id="decision-task:envelope-review",
    )

    def envelope(actor_type: str, target: str = "2026-07-31"):
        return ApplicationCommandEnvelopeV1.from_bytes(
            json.dumps(
                {
                    "schema_version": "ApplicationCommandEnvelope@1",
                    "command_name": "decision_task.defer@1",
                    "invocation_id": "decision-task:envelope-defer",
                    "payload_schema_version": "DeferDecisionTask@1",
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
                        "defer_target_type": "specific_date_or_session",
                        "defer_target_value": target,
                        "occurred_at": "2026-07-27T17:00:00+08:00",
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )

    with open_application_commands(data_root) as dispatcher:
        denied = dispatcher.dispatch(envelope("agent"))
        first = dispatcher.dispatch(envelope("user"))
        replay = dispatcher.dispatch(envelope("user"))
        conflict = dispatcher.dispatch(
            envelope("user", target="2026-08-01")
        )
    assert isinstance(denied, ApplicationCommandFailure)
    assert denied.code == "USER_DECISION_CAPABILITY_REQUIRED"
    assert isinstance(first, ApplicationCommandResult)
    assert replay == first
    assert isinstance(conflict, ApplicationCommandFailure)
    assert conflict.code == "DECISION_TASK_INVOCATION_CONFLICT"
    connection = SQLiteOwningAdapterFixture(data_root)
    receipt = connection.execute(
        "SELECT request_hash,revision_or_version_id "
        "FROM application_command_receipt WHERE invocation_id=?",
        ("decision-task:envelope-defer",),
    ).fetchone()
    assert receipt["request_hash"] == first.request_hash
    assert receipt["revision_or_version_id"] == (
        first.result["latest_transition_id"]
    )
    connection.close()


def test_concurrent_review_replay_materializes_one_task(
    tmp_path: Path,
) -> None:
    data_root, _, _ = _task_review(
        tmp_path,
        suffix="concurrent-base",
        invocation_id="decision-task:concurrent-base",
        run_review=False,
    )

    def attempt(_):
        try:
            return _start(
                data_root,
                invocation_id="decision-task:concurrent-base",
                selected_session="2026-07-27",
            )
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(attempt, range(2)))
    successes = tuple(
        result for result in outcomes if not isinstance(result, Exception)
    )
    failures = tuple(
        result for result in outcomes if isinstance(result, Exception)
    )
    assert successes
    assert all(
        getattr(error, "code", None) == "RUNTIME_BUSY"
        for error in failures
    )
    replay = _start(
        data_root,
        invocation_id="decision-task:concurrent-base",
        selected_session="2026-07-27",
    )
    assert {result.review_run_id for result in successes} == {
        replay.review_run_id
    }
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM decision_task",
    ).fetchone()[0] == 1
    connection.close()
