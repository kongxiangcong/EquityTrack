from __future__ import annotations

from tests.decision_core.test_monitor_review_application import market_evidence
from tests.decision_core.test_planning_application import prepare_request, seed
from trading_platform.application import open_application
from trading_platform.evidence import build_evidence_set
from trading_platform.projection import cycle_summary
from trading_platform.storage import SQLiteStore


def test_complete_synthetic_decision_loop_survives_restart_and_restore(tmp_path) -> None:
    root = tmp_path / "root"
    app = open_application(root)
    account, case, valuation = seed(app)
    shown = app.account_show("account-orchid")
    assert shown.ok and shown.value["cash"]["amount"] == "800"

    missing_evidence = build_evidence_set(
        "2035-04-18T08:00:00+00:00",
        [{"name": "free_cash_flow", "missing_reason": "fixture omission", "as_of": "2035-04-18T08:00:00+00:00"}],
    ).as_dict()
    insufficient = app.valuation_assess(
        {"investment_case_id": case["investment_case_id"], "evidence_set": missing_evidence, "method": "dcf", "company_archetype": "mature_non_financial"},
        idempotency_key="e2e-insufficient-valuation",
    )
    assert valuation["status"] == "completed"
    assert insufficient.ok and insufficient.value["status"] == "insufficient"

    prepared = app.planning_prepare(prepare_request(account, case, valuation), idempotency_key="e2e-prepare")
    draft = prepared.value["trade_plan_draft"]
    plan = app.planning_confirm(
        {"draft_id": draft["draft_id"], "content_hash": draft["content_hash"], "explicit_confirmation": True, "confirmed_at": "2035-04-19T08:00:00+00:00", "confirmed_by": "synthetic-user", "channel": "fixture-chat"},
        idempotency_key="e2e-confirm",
    ).value

    outcomes = {}
    for label, price in (("not_triggered", "18"), ("triggered", "20"), ("insufficient", None)):
        outcomes[label] = app.monitor_evaluate(
            {"trade_plan_id": plan["trade_plan_id"], "evidence_set": market_evidence(price)},
            idempotency_key=f"e2e-monitor-{label}",
        ).value
    assert outcomes["not_triggered"]["decision_task"] is None
    assert outcomes["triggered"]["decision_task"] is not None
    assert outcomes["insufficient"]["decision_task"] is None

    task = outcomes["triggered"]["decision_task"]
    process_request = {"review_type": "PROCESS", "trade_plan_id": plan["trade_plan_id"], "task_id": task["task_id"], "as_of": "2035-04-20T08:00:00+00:00", "frozen_refs": [plan["decision_card_id"], task["plan_evaluation_id"]], "assessment": "Fixture process assessment."}
    process = app.review_commit(process_request, idempotency_key="e2e-process")
    outcome = app.review_commit(
        {"review_type": "OUTCOME", "trade_plan_id": plan["trade_plan_id"], "process_review_id": process.value["decision_review_id"], "as_of": "2035-05-21T08:00:00+00:00", "assessment": "Fixture outcome assessment."},
        idempotency_key="e2e-outcome",
    )
    assert outcome.ok and outcome.value["process_review_id"] == process.value["decision_review_id"]

    revision_draft = app.planning_prepare(
        prepare_request(account, case, valuation, supersedes_plan_id=plan["trade_plan_id"], review_window_end="2035-06-20T08:00:00+00:00"),
        idempotency_key="e2e-revision-prepare",
    ).value["trade_plan_draft"]
    revision = app.planning_confirm(
        {"draft_id": revision_draft["draft_id"], "content_hash": revision_draft["content_hash"], "explicit_confirmation": True, "confirmed_at": "2035-04-19T09:00:00+00:00", "confirmed_by": "synthetic-user", "channel": "fixture-chat"},
        idempotency_key="e2e-revision-confirm",
    ).value
    assert revision["revision"] == 2 and revision["supersedes_plan_id"] == plan["trade_plan_id"]
    close_draft = app.planning_prepare(
        prepare_request(account, case, valuation, close_plan_id=revision["trade_plan_id"], rules=[]),
        idempotency_key="e2e-close-prepare",
    ).value["trade_plan_draft"]
    closed = app.planning_confirm(
        {"draft_id": close_draft["draft_id"], "content_hash": close_draft["content_hash"], "explicit_confirmation": True, "confirmed_at": "2035-04-19T10:00:00+00:00", "confirmed_by": "synthetic-user", "channel": "fixture-chat"},
        idempotency_key="e2e-close-confirm",
    )
    assert closed.ok and closed.value["closed_plan_id"] == revision["trade_plan_id"]

    restarted = open_application(root)
    assert restarted.review_commit(process_request, idempotency_key="e2e-process").value == process.value
    conflict = restarted.review_commit(process_request | {"assessment": "different"}, idempotency_key="e2e-process")
    assert not conflict.ok and conflict.error["code"] == "IDEMPOTENCY_CONFLICT"

    backup = SQLiteStore(root).backup(tmp_path / "decision-core-backup.sqlite3")
    restored_root = tmp_path / "restored"
    SQLiteStore.restore(backup, restored_root)
    assert SQLiteStore(restored_root).doctor()["ok"]
    restored = open_application(restored_root)
    assert restored.account_show("account-orchid").value == shown.value
    restored_account, restored_case, restored_valuation = seed(restored)
    restored_prepared = restored.planning_prepare(
        prepare_request(restored_account, restored_case, restored_valuation),
        idempotency_key="e2e-prepare",
    )
    restored_draft = restored_prepared.value["trade_plan_draft"]
    restored_plan = restored.planning_confirm(
        {"draft_id": restored_draft["draft_id"], "content_hash": restored_draft["content_hash"], "explicit_confirmation": True, "confirmed_at": "2035-04-19T08:00:00+00:00", "confirmed_by": "synthetic-user", "channel": "fixture-chat"},
        idempotency_key="e2e-confirm",
    )
    restored_monitor = restored.monitor_evaluate(
        {"trade_plan_id": restored_plan.value["trade_plan_id"], "evidence_set": market_evidence("20")},
        idempotency_key="e2e-monitor-triggered",
    )
    restored_task = restored_monitor.value["decision_task"]
    restored_process_request = {
        "review_type": "PROCESS",
        "trade_plan_id": restored_plan.value["trade_plan_id"],
        "task_id": restored_task["task_id"],
        "as_of": "2035-04-20T08:00:00+00:00",
        "frozen_refs": [restored_plan.value["decision_card_id"], restored_task["plan_evaluation_id"]],
        "assessment": "Fixture process assessment.",
    }
    restored_process = restored.review_commit(restored_process_request, idempotency_key="e2e-process")
    restored_outcome = restored.review_commit(
        {"review_type": "OUTCOME", "trade_plan_id": restored_plan.value["trade_plan_id"], "process_review_id": restored_process.value["decision_review_id"], "as_of": "2035-05-21T08:00:00+00:00", "assessment": "Fixture outcome assessment."},
        idempotency_key="e2e-outcome",
    )
    restored_store = SQLiteStore(restored_root)
    summary = cycle_summary(
        account_snapshot=restored.account_show("account-orchid").value,
        executions=[],
        open_tasks=[restored_task],
        reviews=[restored_process.value, restored_outcome.value],
    )
    assert all(result.ok for result in (restored_prepared, restored_plan, restored_monitor, restored_process, restored_outcome))
    assert restored_outcome.value == outcome.value
    assert summary["account_as_of"] == "2035-04-18T08:00:00+00:00"
    assert summary["open_task_ids"] == [task["task_id"]]
    assert summary["process_review_count"] == 1 and summary["outcome_review_count"] == 1
    assert restored_store.doctor()["ok"]
