from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.test_plan_confirmation import (
    _authority_root,
    _confirm,
    _create_and_challenge,
    _draft as _plan_draft,
)
from tests.platform.test_account_snapshots import _draft as _account_draft
from tests.platform.test_estimated_account_state import _confirmed
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    ApplicationCommandResult,
    GetManualPortfolioReview,
    ResumeManualPortfolioReview,
    StartManualPortfolioReview,
    open_manual_portfolio_review,
    open_application_commands,
    open_trade_plan,
)
from trading_platform.domain.manual_review import ManualReviewError
from trading_platform.domain.approvals import ActivationIntent
from trading_platform.domain.plans import PlanValidationError

ROOT = Path(__file__).resolve().parents[2]


def _complete_session(data_root: Path, session: str) -> None:
    connection = SQLiteOwningAdapterFixture(data_root)
    source = connection.execute(
        "SELECT * FROM data_snapshot "
        "WHERE data_snapshot_id='data_snapshot_plan_fixture'"
    ).fetchone()
    values = list(source)
    values[0] = f"data_snapshot_review_{session.replace('-', '')}"
    values[3] = session
    values[4] = session
    values[5] = f"{session}T15:00:00+08:00"
    values[19] = "effective_complete_session"
    values[20] = f"{session}T15:00:00+08:00"
    connection.execute(
        "INSERT INTO data_snapshot VALUES("
        + ",".join("?" for _ in values)
        + ")",
        values,
    )
    connection.close()


def _start(
    data_root: Path,
    *,
    invocation_id: str,
    selected_session: str,
    first_window_start_exclusive: str | None = "2026-07-24",
    fault_injector=None,
):
    with open_manual_portfolio_review(
        data_root, fault_injector=fault_injector
    ) as review:
        return review.start(
            StartManualPortfolioReview(
                invocation_id=invocation_id,
                account_id="account_local",
                requested_at=f"{selected_session}T16:00:00+08:00",
                selected_complete_session=selected_session,
                first_window_start_exclusive=first_window_start_exclusive,
                code_identity="code:test",
                config_identity="config:test",
                decision_actor="agent:codex",
                interaction_channel="skill",
                transport_actor="agent:codex",
            )
        )


def test_window_uses_last_successful_cutoff_to_selected_complete_session(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-27")
    first = _start(
        data_root,
        invocation_id="manual-review:first",
        selected_session="2026-07-27",
    )
    assert first.window_start_exclusive == "2026-07-24"
    assert first.window_end_inclusive == "2026-07-27"
    assert first.status == "succeeded_with_limits"
    item_outcome = SQLiteOwningAdapterFixture(data_root)
    item = item_outcome.execute(
        "SELECT outcome,decision_task_ids_json "
        "FROM manual_portfolio_review_item "
        "WHERE review_run_id=?",
        (first.review_run_id,),
    ).fetchone()
    assert item["outcome"] == "REVIEW_REQUIRED"
    assert len(json.loads(item["decision_task_ids_json"])) == 1
    item_outcome.close()

    _complete_session(data_root, "2026-07-31")
    second = _start(
        data_root,
        invocation_id="manual-review:second",
        selected_session="2026-07-31",
    )
    assert second.window_start_exclusive == "2026-07-27"
    assert second.window_end_inclusive == "2026-07-31"
    assert second.prior_successful_review_run_id == first.review_run_id


def test_active_plan_without_compatible_evaluation_is_monitor_only(
    tmp_path: Path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with open_trade_plan(data_root) as plans:
        _, challenge = _create_and_challenge(
            plans,
            _plan_draft(snapshot_id, suffix="manual-monitor"),
            "manual-monitor",
            ActivationIntent.CONFIRM_AND_ACTIVATE,
        )
        _confirm(plans, challenge, "manual-monitor")
    _complete_session(data_root, "2026-07-27")
    review = _start(
        data_root,
        invocation_id="manual-review:monitor",
        selected_session="2026-07-27",
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    item = connection.execute(
        "SELECT outcome,decision_task_ids_json,unable_reasons_json "
        "FROM manual_portfolio_review_item WHERE review_run_id=?",
        (review.review_run_id,),
    ).fetchone()
    assert tuple(item) == (
        "MONITOR",
        "[]",
        '["COMPATIBLE_PLAN_EVALUATION_MISSING"]',
    )
    connection.close()


def test_no_action_evaluation_produces_no_change_without_task(
    tmp_path: Path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with open_trade_plan(data_root) as plans:
        draft, challenge = _create_and_challenge(
            plans,
            _plan_draft(snapshot_id, suffix="manual-no-change"),
            "manual-no-change",
            ActivationIntent.CONFIRM_AND_ACTIVATE,
        )
        _confirm(plans, challenge, "manual-no-change")
    _complete_session(data_root, "2026-07-27")
    connection = SQLiteOwningAdapterFixture(data_root)
    with connection.transaction():
        connection.execute(
            "INSERT INTO market_universe_version VALUES(?,?,?,?,?)",
            (
                "market_universe_manual_review",
                "CN_A_SHARE",
                "2026-07-27T15:00:00+08:00",
                "fixture",
                "manual-review-membership",
            ),
        )
        connection.execute(
            "INSERT INTO market_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "market_snapshot_manual_review",
                "security_600000",
                "CN_A_SHARE",
                "2026-07-27",
                "2026-07-27",
                "data_snapshot_review_20260727",
                "market_universe_manual_review",
                "cn-a-share-market@1",
                "freshness_fixture@1",
                "code:test",
                "manual-review-market-input",
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
                "plan_evaluation_manual_review",
                draft.proposed_graph.version.plan_version_id,
                "market_snapshot_manual_review",
                "plan-evaluator@2",
                "trade-plan-conflict@1",
                "completed",
                "no_action",
                "NO_RULE_TRIGGERED",
                "{}",
                "manual-review-resolution-hash",
                "complete",
                0,
                "manual-review-evaluation-hash",
                0,
                "2026-07-27T15:30:00+08:00",
            ),
        )
    connection.close()
    review = _start(
        data_root,
        invocation_id="manual-review:no-change",
        selected_session="2026-07-27",
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    item = connection.execute(
        "SELECT outcome,decision_task_ids_json "
        "FROM manual_portfolio_review_item WHERE review_run_id=?",
        (review.review_run_id,),
    ).fetchone()
    assert tuple(item) == ("NO_CHANGE", "[]")
    assert connection.execute(
        "SELECT count(*) FROM decision_task"
    ).fetchone()[0] == 0
    connection.close()


def test_corrupt_active_plan_graph_fails_whole_review_closed(
    tmp_path: Path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with open_trade_plan(data_root) as plans:
        draft, challenge = _create_and_challenge(
            plans,
            _plan_draft(snapshot_id, suffix="manual-corrupt"),
            "manual-corrupt",
            ActivationIntent.CONFIRM_AND_ACTIVATE,
        )
        _confirm(plans, challenge, "manual-corrupt")
    _complete_session(data_root, "2026-07-27")
    connection = SQLiteOwningAdapterFixture(data_root)
    connection.execute("DROP TRIGGER trade_plan_version_sealed_update")
    connection.execute(
        "UPDATE trade_plan_version SET graph_seal_hash='tampered' "
        "WHERE plan_version_id=?",
        (draft.proposed_graph.version.plan_version_id,),
    )
    connection.close()
    with pytest.raises(
        PlanValidationError, match="PLAN_GRAPH_SEAL_MISMATCH"
    ):
        _start(
            data_root,
            invocation_id="manual-review:corrupt",
            selected_session="2026-07-27",
        )
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT status FROM workflow_run "
        "WHERE invocation_id='manual-review:corrupt'"
    ).fetchone()[0] == "failed"
    assert connection.execute(
        "SELECT count(*) FROM manual_portfolio_review_run"
    ).fetchone()[0] == 0
    connection.close()


def test_shared_envelope_dispatches_manual_review_and_persists_same_hash(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-27")
    envelope = ApplicationCommandEnvelopeV1.from_bytes(
        (
            "{"
            '"schema_version":"ApplicationCommandEnvelope@1",'
            '"command_name":"manual_portfolio_review.run@1",'
            '"invocation_id":"manual-review:envelope",'
            '"payload_schema_version":"RunManualPortfolioReview@1",'
            '"expected_revision":null,'
            '"decision_actor":{"actor_type":"agent","actor_id":"codex"},'
            '"interaction_channel":"skill",'
            '"transport_actor":{"actor_type":"agent","actor_id":"codex"},'
            '"approval":null,'
            '"payload":{'
            '"account_id":"account_local",'
            '"requested_at":"2026-07-27T16:00:00+08:00",'
            '"selected_complete_session":"2026-07-27",'
            '"first_window_start_exclusive":"2026-07-24",'
            '"code_identity":"code:test",'
            '"config_identity":"config:test"'
            "}}"
        ).encode()
    )
    with open_application_commands(data_root) as dispatcher:
        result = dispatcher.dispatch(envelope)
    assert isinstance(result, ApplicationCommandResult)
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT request_hash FROM application_command_receipt "
        "WHERE invocation_id=?",
        (result.invocation_id,),
    ).fetchone()[0] == result.request_hash
    connection.close()


def test_incomplete_session_fails_before_review_truth_is_written(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    with pytest.raises(
        ManualReviewError, match="SELECTED_COMPLETE_SESSION_NOT_PROVEN"
    ):
        _start(
            data_root,
            invocation_id="manual-review:incomplete",
            selected_session="2026-07-28",
        )
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM manual_portfolio_review_run"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT status FROM workflow_run "
        "WHERE invocation_id='manual-review:incomplete'"
    ).fetchone()[0] == "failed"
    connection.close()


def test_first_review_requires_explicit_confirmed_snapshot_cutoff(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-27")
    with pytest.raises(
        ManualReviewError, match="FIRST_REVIEW_CUTOFF_REQUIRED"
    ):
        _start(
            data_root,
            invocation_id="manual-review:no-first-cutoff",
            selected_session="2026-07-27",
            first_window_start_exclusive=None,
        )
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM manual_portfolio_review_run"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT status FROM workflow_run "
        "WHERE invocation_id='manual-review:no-first-cutoff'"
    ).fetchone()[0] == "failed"
    connection.close()


def test_failed_run_does_not_advance_cutoff_and_can_be_resumed(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-27")

    def fail(boundary: str) -> None:
        if boundary == "manual_review.before_terminal_update":
            raise RuntimeError("injected manual review failure")

    with pytest.raises(RuntimeError, match="injected"):
        _start(
            data_root,
            invocation_id="manual-review:failed",
            selected_session="2026-07-27",
            fault_injector=fail,
        )
    connection = SQLiteOwningAdapterFixture(data_root)
    failed_id = connection.execute(
        "SELECT review_run_id FROM manual_portfolio_review_run "
        "WHERE status='failed'"
    ).fetchone()[0]
    assert connection.execute(
        "SELECT count(*) FROM manual_portfolio_review_item "
        "WHERE review_run_id=?",
        (failed_id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM manual_portfolio_review_manifest "
        "WHERE review_run_id=?",
        (failed_id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM manual_portfolio_review_checkpoint "
        "WHERE review_run_id=?",
        (failed_id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM decision_task WHERE review_run_id=?",
        (failed_id,),
    ).fetchone()[0] == 0
    connection.close()

    with open_manual_portfolio_review(data_root) as review:
        resumed = review.resume(
            ResumeManualPortfolioReview(
                invocation_id="manual-review:resumed",
                failed_review_run_id=failed_id,
                requested_at="2026-07-27T16:30:00+08:00",
                code_identity="code:test",
                config_identity="config:test",
                decision_actor="agent:codex",
                interaction_channel="skill",
                transport_actor="agent:codex",
            )
        )
    assert resumed.status == "succeeded_with_limits"
    assert resumed.window_start_exclusive == "2026-07-24"
    assert resumed.prior_successful_review_run_id is None


def test_manifest_items_and_checkpoints_are_frozen_and_replay_safe(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-27")
    first = _start(
        data_root,
        invocation_id="manual-review:replay",
        selected_session="2026-07-27",
    )
    replay = _start(
        data_root,
        invocation_id="manual-review:replay",
        selected_session="2026-07-27",
    )
    assert replay == first

    with open_manual_portfolio_review(data_root) as review:
        queried = review.get(GetManualPortfolioReview(first.review_run_id))
    assert queried == first
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM manual_portfolio_review_item "
        "WHERE review_run_id=?",
        (first.review_run_id,),
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT count(*) FROM manual_portfolio_review_checkpoint "
        "WHERE review_run_id=? AND status='committed'",
        (first.review_run_id,),
    ).fetchone()[0] == 1
    manifest = connection.execute(
        "SELECT manifest_id,artifact_manifest_id,object_sha256 "
        "FROM manual_portfolio_review_manifest WHERE review_run_id=?",
        (first.review_run_id,),
    ).fetchone()
    assert all(manifest)
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
        connection.execute(
            "UPDATE manual_portfolio_review_manifest "
            "SET content_hash='tampered' WHERE review_run_id=?",
            (first.review_run_id,),
        )
    connection.close()


def test_same_invocation_with_different_review_input_is_rejected(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-27")
    _complete_session(data_root, "2026-07-31")
    _start(
        data_root,
        invocation_id="manual-review:conflict",
        selected_session="2026-07-27",
    )
    with pytest.raises(
        ManualReviewError, match="MANUAL_REVIEW_INVOCATION_CONFLICT"
    ):
        _start(
            data_root,
            invocation_id="manual-review:conflict",
            selected_session="2026-07-31",
        )


def test_zero_quantity_is_not_a_holding(
    tmp_path: Path,
) -> None:
    data_root, prior_snapshot_id = _authority_root(tmp_path)
    draft = _account_draft()
    zero = replace(
        draft,
        draft_id="draft_local_zero",
        previous_snapshot_version_id=prior_snapshot_id,
        positions=(
            replace(draft.positions[0], total_quantity="0"),
        ),
    )
    _confirmed(
        data_root,
        zero,
        create_invocation="manual-review:zero:create",
        confirm_invocation="manual-review:zero:confirm",
    )
    _complete_session(data_root, "2026-07-27")
    result = _start(
        data_root,
        invocation_id="manual-review:zero",
        selected_session="2026-07-27",
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM manual_portfolio_review_item "
        "WHERE review_run_id=?",
        (result.review_run_id,),
    ).fetchone()[0] == 0
    connection.close()


def test_public_daily_portfolio_route_is_deleted() -> None:
    cli = (ROOT / "src/trading_platform/cli.py").read_text(encoding="utf-8")
    skill = (ROOT / "skills/SKILL.md").read_text(encoding="utf-8")
    exports = (
        ROOT / "src/trading_platform/application/__init__.py"
    ).read_text(encoding="utf-8")
    assert 'add_parser("daily")' not in cli
    assert '("sync", "daily")' not in cli
    assert "open_daily_research_cycle" not in cli + exports
    assert "DailyResearchCycle" not in (
        ROOT / "src/trading_platform/application/cli_tasks.py"
    ).read_text(encoding="utf-8")
    assert " cli daily " not in f" {skill} "
