from __future__ import annotations

from tests.decision_core.test_planning_application import AS_OF, prepare_request, seed
from trading_platform.application import open_application
from trading_platform.evidence import build_evidence_set


def active_plan(app) -> dict:
    account, case, valuation = seed(app)
    draft = app.planning_prepare(prepare_request(account, case, valuation), idempotency_key="monitor-prepare").value["trade_plan_draft"]
    return app.planning_confirm(
        {"draft_id": draft["draft_id"], "content_hash": draft["content_hash"], "explicit_confirmation": True, "confirmed_at": "2035-04-19T08:00:00+00:00", "confirmed_by": "synthetic-user", "channel": "fixture-chat"},
        idempotency_key="monitor-confirm",
    ).value


def market_evidence(value: str | None) -> dict:
    item = {"name": "market_price", "missing_reason": "fixture price unavailable", "as_of": "2035-04-20T08:00:00+00:00"} if value is None else {"name": "market_price", "value": value, "source_id": "fixture-source-price", "as_of": "2035-04-20T08:00:00+00:00"}
    return build_evidence_set("2035-04-20T08:00:00+00:00", [item]).as_dict()


def test_monitor_distinguishes_not_triggered_triggered_and_insufficient(tmp_path) -> None:
    app = open_application(tmp_path)
    plan = active_plan(app)
    not_triggered = app.monitor_evaluate(
        {"trade_plan_id": plan["trade_plan_id"], "evidence_set": market_evidence("18")},
        idempotency_key="monitor-not-triggered",
    )
    triggered = app.monitor_evaluate(
        {"trade_plan_id": plan["trade_plan_id"], "evidence_set": market_evidence("20")},
        idempotency_key="monitor-triggered",
    )
    insufficient = app.monitor_evaluate(
        {"trade_plan_id": plan["trade_plan_id"], "evidence_set": market_evidence(None)},
        idempotency_key="monitor-insufficient",
    )

    assert not_triggered.ok and not_triggered.value["plan_evaluation"]["status"] == "not_triggered"
    assert not_triggered.value["decision_task"] is None
    assert triggered.value["plan_evaluation"]["status"] == "triggered"
    assert triggered.value["decision_task"]["task_id"]
    assert insufficient.value["plan_evaluation"]["status"] == "insufficient"
    assert insufficient.value["decision_task"] is None
    assert insufficient.value["plan_evaluation"]["rule_results"][0]["missing"] == ["market_price"]


def test_triggered_monitor_replays_same_task_after_restart(tmp_path) -> None:
    app = open_application(tmp_path)
    plan = active_plan(app)
    request = {"trade_plan_id": plan["trade_plan_id"], "evidence_set": market_evidence("20")}
    first = app.monitor_evaluate(request, idempotency_key="same-monitor")
    replay = open_application(tmp_path).monitor_evaluate(request, idempotency_key="same-monitor")
    assert replay.value == first.value


def test_triggered_monitor_failure_rolls_back_evaluation_task_and_command(tmp_path) -> None:
    app = open_application(tmp_path)
    plan = active_plan(app)
    request = {"trade_plan_id": plan["trade_plan_id"], "evidence_set": market_evidence("20")}

    failed = open_application(tmp_path, fault_at="before_commit").monitor_evaluate(
        request, idempotency_key="monitor-retry"
    )
    retry = open_application(tmp_path).monitor_evaluate(
        request, idempotency_key="monitor-retry"
    )

    assert not failed.ok and failed.error["code"] == "PERSISTENCE_FAILURE"
    assert retry.ok and retry.value["decision_task"]["task_id"]


def test_process_then_outcome_review_enforces_window_and_reference(tmp_path) -> None:
    app = open_application(tmp_path)
    plan = active_plan(app)
    task = app.monitor_evaluate(
        {"trade_plan_id": plan["trade_plan_id"], "evidence_set": market_evidence("20")},
        idempotency_key="review-trigger",
    ).value["decision_task"]
    process = app.review_commit(
        {"review_type": "PROCESS", "trade_plan_id": plan["trade_plan_id"], "task_id": task["task_id"], "as_of": "2035-04-20T08:00:00+00:00", "frozen_refs": [plan["decision_card_id"], task["plan_evaluation_id"]], "assessment": "Fixture process assessment without outcome knowledge."},
        idempotency_key="process-review",
    )
    assert process.ok and process.value["review_type"] == "PROCESS"

    early = app.review_commit(
        {"review_type": "OUTCOME", "trade_plan_id": plan["trade_plan_id"], "process_review_id": process.value["decision_review_id"], "as_of": "2035-05-01T08:00:00+00:00", "assessment": "Fixture outcome assessment."},
        idempotency_key="early-outcome",
    )
    assert not early.ok and early.error["code"] == "STALE_INPUT"

    outcome = app.review_commit(
        {"review_type": "OUTCOME", "trade_plan_id": plan["trade_plan_id"], "process_review_id": process.value["decision_review_id"], "as_of": "2035-05-21T08:00:00+00:00", "assessment": "Fixture outcome assessment."},
        idempotency_key="outcome-review",
    )
    assert outcome.ok and outcome.value["process_review_id"] == process.value["decision_review_id"]
    assert app.review_commit(
        {"review_type": "PROCESS", "trade_plan_id": plan["trade_plan_id"], "task_id": task["task_id"], "as_of": "2035-04-20T08:00:00+00:00", "frozen_refs": [plan["decision_card_id"], task["plan_evaluation_id"]], "assessment": "Fixture process assessment without outcome knowledge."},
        idempotency_key="process-review",
    ).value == process.value


def test_process_rejects_unrelated_or_later_frozen_information(tmp_path) -> None:
    app = open_application(tmp_path)
    plan = active_plan(app)
    task = app.monitor_evaluate(
        {"trade_plan_id": plan["trade_plan_id"], "evidence_set": market_evidence("20")},
        idempotency_key="frozen-trigger",
    ).value["decision_task"]
    unrelated = app.review_commit(
        {"review_type": "PROCESS", "trade_plan_id": plan["trade_plan_id"], "task_id": task["task_id"], "as_of": "2035-04-20T08:00:00+00:00", "frozen_refs": ["later-or-unrelated-record"], "assessment": "Fixture assessment."},
        idempotency_key="unrelated-process",
    )
    assert not unrelated.ok and unrelated.error["code"] == "INVALID_INPUT"

    later = app.review_commit(
        {"review_type": "PROCESS", "trade_plan_id": plan["trade_plan_id"], "task_id": task["task_id"], "as_of": "2035-04-19T09:00:00+00:00", "frozen_refs": [task["plan_evaluation_id"]], "assessment": "Fixture assessment."},
        idempotency_key="later-process",
    )
    assert not later.ok and later.error["code"] == "STALE_INPUT"
