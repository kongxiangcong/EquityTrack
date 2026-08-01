from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from tests.platform.canonical_plan_journey_fixture import (
    arrange_canonical_plan_journey,
)
from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.test_plan_confirmation import _authority_root
from tests.platform.test_account_snapshots import _draft as _account_draft
from tests.platform.test_estimated_account_state import _confirmed
from trading_platform.application import (
    GetManualPortfolioReview,
    ResumeManualPortfolioReview,
    StartManualPortfolioReview,
    open_manual_portfolio_review,
    open_watchlist,
)
from trading_platform.application.contracts import SecurityIdentity
from trading_platform.domain.manual_review import ManualReviewError
from trading_platform.domain.plans import PlanValidationError

ROOT = Path(__file__).resolve().parents[2]


def _complete_session(
    data_root: Path,
    session: str,
    *,
    source_snapshot_id: str = "data_snapshot_plan_fixture",
    security_id: str = "security_600000",
) -> None:
    connection = SQLiteOwningAdapterFixture(data_root)
    source = connection.execute(
        "SELECT * FROM data_snapshot WHERE data_snapshot_id=?",
        (source_snapshot_id,),
    ).fetchone()
    assert source is not None
    values = list(source)
    values[0] = f"data_snapshot_review_{session.replace('-', '')}"
    values[3] = session
    values[4] = session
    values[5] = f"{session}T15:00:00+08:00"
    values[14] = 1
    values[15] = 1
    values[16] = 0
    values[17] = 0
    values[19] = "effective_complete_session"
    values[20] = f"{session}T15:00:00+08:00"
    universe_id = (
        f"market_universe_review_{session.replace('-', '')}"
    )
    connection.execute(
        "INSERT INTO market_universe_version VALUES(?,?,?,?,?)",
        (
            universe_id,
            "CN_A_SHARE",
            f"{session}T15:00:00+08:00",
            "source_policy_plan_fixture@1",
            f"manual-review-membership-{session}",
        ),
    )
    connection.execute(
        "INSERT INTO market_universe_member VALUES(?,?,?,?,?,?,?)",
        (
            universe_id,
            security_id,
            "1999-11-10",
            None,
            None,
            None,
            "manual-review-fixture",
        ),
    )
    connection.execute(
        "INSERT INTO data_snapshot VALUES("
        + ",".join("?" for _ in values)
        + ")",
        values,
    )
    connection.execute(
        "INSERT INTO data_snapshot_universe_ref VALUES(?,?,?)",
        (values[0], universe_id, "CN_A_SHARE"),
    )
    connection.close()


def _start(
    data_root: Path,
    *,
    invocation_id: str,
    account_id: str = "account_local",
    selected_session: str | None = None,
    requested_at: str | None = None,
    fault_injector=None,
):
    if requested_at is None:
        if selected_session is None:
            raise AssertionError("test request time is required")
        requested_at = f"{selected_session}T16:00:00+08:00"
    with open_manual_portfolio_review(
        data_root, fault_injector=fault_injector
    ) as review:
        return review.start(
            StartManualPortfolioReview(
                invocation_id=invocation_id,
                account_id=account_id,
                requested_at=requested_at,
                session_selection="latest_proven_complete_session",
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
    with arrange_canonical_plan_journey(
        tmp_path, activate=True
    ) as journey:
        data_root = journey.data_root
        account_id = journey.account_id
        source_snapshot_id = journey.data_snapshot_id
        security_id = journey.security_id
    _complete_session(
        data_root,
        "2026-07-27",
        source_snapshot_id=source_snapshot_id,
        security_id=security_id,
    )
    review = _start(
        data_root,
        invocation_id="manual-review:monitor",
        account_id=account_id,
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
    with arrange_canonical_plan_journey(
        tmp_path, activate=True
    ) as journey:
        data_root = journey.data_root
        account_id = journey.account_id
        source_snapshot_id = journey.data_snapshot_id
        security_id = journey.security_id
        plan_version_id = journey.plan_version_id
    _complete_session(
        data_root,
        "2026-07-27",
        source_snapshot_id=source_snapshot_id,
        security_id=security_id,
    )
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
                security_id,
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
                plan_version_id,
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
        account_id=account_id,
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
    with arrange_canonical_plan_journey(
        tmp_path, activate=True
    ) as journey:
        data_root = journey.data_root
        account_id = journey.account_id
        source_snapshot_id = journey.data_snapshot_id
        security_id = journey.security_id
        plan_version_id = journey.plan_version_id
    _complete_session(
        data_root,
        "2026-07-27",
        source_snapshot_id=source_snapshot_id,
        security_id=security_id,
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    connection.execute("DROP TRIGGER trade_plan_version_sealed_update")
    connection.execute(
        "UPDATE trade_plan_version SET graph_seal_hash='tampered' "
        "WHERE plan_version_id=?",
        (plan_version_id,),
    )
    connection.close()
    with pytest.raises(
        PlanValidationError, match="PLAN_GRAPH_SEAL_MISMATCH"
    ):
        _start(
            data_root,
            invocation_id="manual-review:corrupt",
            account_id=account_id,
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


def test_single_security_snapshot_is_not_market_session_proof(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    connection = SQLiteOwningAdapterFixture(data_root)
    source = connection.execute(
        "SELECT * FROM data_snapshot "
        "WHERE data_snapshot_id='data_snapshot_plan_fixture'"
    ).fetchone()
    values = list(source)
    values[0] = "data_snapshot_single_security_only"
    values[3] = "2026-07-27"
    values[4] = "2026-07-27"
    values[5] = "2026-07-27T15:00:00+08:00"
    values[14] = 1
    values[15] = 1
    values[16] = 0
    values[17] = 0
    values[19] = "effective_complete_session"
    values[20] = "2026-07-27T15:00:00+08:00"
    connection.execute(
        "INSERT INTO data_snapshot VALUES("
        + ",".join("?" for _ in values)
        + ")",
        values,
    )
    connection.close()

    with pytest.raises(
        ManualReviewError,
        match="LATEST_PROVEN_COMPLETE_SESSION_UNAVAILABLE",
    ):
        _start(
            data_root,
            invocation_id="manual-review:single-security-not-proof",
            requested_at="2026-07-27T16:00:00+08:00",
        )
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM manual_portfolio_review_run"
    ).fetchone()[0] == 0
    connection.close()


def test_no_proven_session_at_requested_time_writes_no_review_truth(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    with pytest.raises(
        ManualReviewError,
        match="LATEST_PROVEN_COMPLETE_SESSION_UNAVAILABLE",
    ):
        _start(
            data_root,
            invocation_id="manual-review:incomplete",
            requested_at="2026-07-23T16:00:00+08:00",
        )
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM manual_portfolio_review_run"
    ).fetchone()[0] == 0
    connection.close()


def test_first_review_derives_confirmed_snapshot_cutoff(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-27")
    review = _start(
        data_root,
        invocation_id="manual-review:derived-cutoff",
        selected_session="2026-07-27",
    )
    assert review.window_start_exclusive == "2026-07-24"
    assert review.selected_complete_session == "2026-07-27"
    assert review.session_selection == "latest_proven_complete_session"


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


def test_zero_quantity_on_watchlist_remains_watchlist_only(
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
    with open_watchlist(data_root) as watchlist:
        watchlist.add(
            "manual-review:zero:watchlist",
            SecurityIdentity(
                "security_600000",
                "SSE",
                "600000",
                "CNY",
                "1999-11-10",
            ),
        )
    _complete_session(data_root, "2026-07-27")
    result = _start(
        data_root,
        invocation_id="manual-review:zero",
        selected_session="2026-07-27",
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    row = connection.execute(
        "SELECT security_id,universe_roles_json "
        "FROM manual_portfolio_review_item WHERE review_run_id=?",
        (result.review_run_id,),
    ).fetchone()
    assert tuple(row) == ("security_600000", '["watchlist"]')
    connection.close()


def test_review_universe_freezes_holding_only_role(tmp_path: Path) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-27")
    review = _start(
        data_root,
        invocation_id="manual-review:holding-only",
        selected_session="2026-07-27",
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    row = connection.execute(
        "SELECT security_id,universe_member_identity,universe_roles_json "
        "FROM manual_portfolio_review_item WHERE review_run_id=?",
        (review.review_run_id,),
    ).fetchone()
    assert row["security_id"] == "security_600000"
    assert row["universe_member_identity"]
    assert row["universe_roles_json"] == '["holding"]'
    connection.close()


def test_review_universe_includes_default_watchlist_only_security(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    with open_watchlist(data_root) as watchlist:
        watchlist.add(
            "manual-review:watchlist-only:add",
            SecurityIdentity(
                "security_watchlist_only",
                "SZSE",
                "000001",
                "CNY",
                "1991-04-03",
            ),
        )
    _complete_session(data_root, "2026-07-27")
    review = _start(
        data_root,
        invocation_id="manual-review:watchlist-only",
        selected_session="2026-07-27",
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    rows = connection.execute(
        "SELECT security_id,universe_roles_json "
        "FROM manual_portfolio_review_item WHERE review_run_id=? "
        "ORDER BY security_id",
        (review.review_run_id,),
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("security_600000", '["holding"]'),
        ("security_watchlist_only", '["watchlist"]'),
    ]
    connection.close()


def test_review_universe_deduplicates_holding_watchlist_overlap(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    with open_watchlist(data_root) as watchlist:
        watchlist.add(
            "manual-review:overlap:add",
            SecurityIdentity(
                "security_600000",
                "SSE",
                "600000",
                "CNY",
                "1999-11-10",
            ),
        )
    _complete_session(data_root, "2026-07-27")
    review = _start(
        data_root,
        invocation_id="manual-review:overlap",
        selected_session="2026-07-27",
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    rows = connection.execute(
        "SELECT security_id,universe_roles_json "
        "FROM manual_portfolio_review_item WHERE review_run_id=?",
        (review.review_run_id,),
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("security_600000", '["holding","watchlist"]')
    ]
    connection.close()


def test_weekend_request_selects_latest_proven_complete_session(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-31")
    _complete_session(data_root, "2026-08-03")
    review = _start(
        data_root,
        invocation_id="manual-review:weekend",
        requested_at="2026-08-02T12:00:00+08:00",
    )
    assert review.selected_complete_session == "2026-07-31"
    assert review.window_end_inclusive == "2026-07-31"


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
