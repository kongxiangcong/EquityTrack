from __future__ import annotations

import json
import sqlite3

import pytest

from trading_platform.application import open_application
from trading_platform.evidence import build_evidence_set
from trading_platform.identifiers import digest
from trading_platform.integrated_migration import MigrationBlocked, migrate_synthetic_root
from trading_platform.storage import SQLiteStore
from tests.decision_core.test_monitor_review_application import market_evidence


def legacy_account_candidate() -> dict:
    return {
        "account_id": "account-orchid",
        "as_of": "2035-04-18T08:00:00+00:00",
        "confirmed": True,
        "confirmed_by": "synthetic-user",
        "cash": None,
        "positions": [
            {
                "security_id": "security-aster-001",
                "quantity": "120",
                "available_quantity": None,
                "cost_basis": None,
            }
        ],
    }


def update_fact(path, kind: str, update, *, old_id: str | None = None) -> None:
    connection = sqlite3.connect(path)
    if old_id is None:
        row = connection.execute("SELECT payload FROM old_facts WHERE kind=?", (kind,)).fetchone()
    else:
        row = connection.execute(
            "SELECT payload FROM old_facts WHERE kind=? AND old_id=?", (kind, old_id)
        ).fetchone()
    payload = json.loads(row[0])
    update(payload)
    if old_id is None:
        connection.execute(
            "UPDATE old_facts SET payload=? WHERE kind=? AND rowid=(SELECT MIN(rowid) FROM old_facts WHERE kind=?)",
            (json.dumps(payload), kind, kind),
        )
    else:
        connection.execute(
            "UPDATE old_facts SET payload=? WHERE kind=? AND old_id=?",
            (json.dumps(payload), kind, old_id),
        )
    connection.commit()
    connection.close()


def populated_source(path, *, ambiguous: bool = False) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE old_facts(kind TEXT, old_id TEXT, payload TEXT)")
    connection.execute("CREATE TABLE old_commands(operation TEXT,idempotency_key TEXT,request_digest TEXT,result_kind TEXT,result_id TEXT)")
    as_of = "2035-04-18T08:00:00+00:00"
    facts = [
        ("AccountSnapshot", "snapshot-old", {"snapshot_id": "snapshot-old", "account_id": "account-orchid", "as_of": as_of, "confirmed_by": "synthetic-user", "cash": None, "positions": legacy_account_candidate()["positions"], "change_kind": "new", "replaces_snapshot_id": None, "correction_reason": None}),
        ("ExecutionRecord", "execution-old", {"execution_id": "execution-old", "account_id": "account-orchid", "base_snapshot_id": "snapshot-old", "security_id": "security-aster-001", "quantity_delta": "5", "verification_status": "user_declared", "declared_by": "synthetic-user", "declared_at": "2035-04-18T09:00:00+00:00"}),
        ("RiskPolicy", "risk-policy-old", {"policy_id": "risk-policy-old", "max_concentration": "0.7", "max_position_value": "1500", "confirmed": True, "confirmed_by": "synthetic-user"}),
        ("RiskLimitResult", "risk-result-old", {"risk_limit_result_id": "risk-result-old", "status": "within_limits", "policy_id": "risk-policy-old", "portfolio_state_ref": "portfolio-state-old", "portfolio_state": {"account_snapshot_id": "snapshot-old", "as_of": as_of, "currency": "XCU", "cash": None, "positions": [{"security_id": "security-aster-001", "quantity": "125", "market_value": "1250"}], "total_value": None, "execution_refs": ["execution-old"], "price_inputs": [{"security_id": "security-aster-001", "amount": "10", "currency": "XCU", "source_id": "fixture-source-price"}]}, "input_refs": {"account_snapshot_id": "snapshot-old", "execution_record_ids": ["execution-old"], "price_source_ids": ["fixture-source-price"]}, "limits": {}}),
        ("EvidenceSet", "evidence-old", {"evidence_set_id": "evidence-old", "as_of": as_of, "items": [{"name": "market_price", "value": "17.5", "source_id": "fixture-source-price"}]}),
        ("InvestmentCase", "case-old", {"investment_case_id": "case-old", "security_id": "security-aster-001", "as_of": as_of, "evidence_set_id": "evidence-old", "thesis": "fixture thesis", "counterargument": "fixture counterargument", "drivers": ["fixture driver"], "risks": ["fixture risk"], "falsifiers": ["fixture falsifier"], "uncertainties": ["fixture uncertainty"], "limitations": []}),
        ("ValuationAssessment", "valuation-old", {"valuation_assessment_id": "valuation-old", "investment_case_id": "case-old", "evidence_set_id": "evidence-old", "as_of": as_of, "method": "dcf", "company_archetype": "mature_non_financial", "status": "insufficient", "missing_inputs": ["free_cash_flow"], "disabled_reason": None, "disabled_conclusion": "dcf_valuation", "result": None, "scenarios": {}, "sensitivity": []}),
        ("DecisionCard", "card-old", {"decision_card_id": "card-old", "investment_case_id": "case-old", "valuation_assessment_id": "valuation-old", "risk_limit_result_id": "risk-result-old", "account_snapshot_id": "snapshot-old", "as_of": as_of}),
        ("TradePlanDraft", "draft-old", {"draft_id": "draft-old", "content_hash": "fixture-hash", "decision_card_id": "card-old", "account_id": "account-orchid", "security_id": "security-aster-001", "expires_at": "2035-04-20T08:00:00+00:00", "review_window_end": "2035-05-20T08:00:00+00:00", "rules": [{"rule_id": "rule-old", "type": "price_above", "threshold": "19", "evidence_name": "market_price"}], "plan_family_id": "family-old", "revision": 1, "supersedes_plan_id": None, "close_plan_id": None}),
        ("TradePlan", "plan-old", {"trade_plan_id": "plan-old", "draft_id": "draft-old", "content_hash": "fixture-hash", "decision_card_id": "card-old", "account_id": "account-orchid", "security_id": "security-aster-001", "rules": [{"rule_id": "rule-old", "type": "price_above", "threshold": "19", "evidence_name": "market_price"}], "review_window_end": "2035-05-20T08:00:00+00:00", "plan_family_id": "family-old", "revision": 1, "supersedes_plan_id": None, "confirmed_at": "2035-04-19T08:00:00+00:00", "confirmed_by": "synthetic-user", "confirmation_channel": "fixture-chat"}),
        ("PlanEvaluation", "evaluation-old", {"plan_evaluation_id": "evaluation-old", "trade_plan_id": "plan-old", "evidence_set_id": "evidence-old", "as_of": "2035-04-20T08:00:00+00:00", "status": "triggered", "rule_results": [{"rule_id": "rule-old", "status": "triggered"}]}),
        ("DecisionTask", "task-old", {"task_id": "task-old", "trade_plan_id": "plan-old", "plan_evaluation_id": "evaluation-old", "triggered_rule_ids": ["rule-old"], "created_at": "2035-04-20T08:00:00+00:00", "status": "open"}),
        ("DecisionReview", "process-old", {"decision_review_id": "process-old", "review_type": "PROCESS", "trade_plan_id": "plan-old", "task_id": "task-old", "as_of": "2035-04-20T08:00:00+00:00", "frozen_refs": ["card-old"], "assessment": "fixture process", "process_review_id": None}),
        ("DecisionReview", "outcome-old", {"decision_review_id": "outcome-old", "review_type": "OUTCOME", "trade_plan_id": "plan-old", "task_id": "task-old", "as_of": "2035-05-21T08:00:00+00:00", "frozen_refs": [], "assessment": "fixture outcome", "process_review_id": "process-old"}),
        ("TradePlanDraft", "draft-close-old", {"draft_id": "draft-close-old", "content_hash": "fixture-close-hash", "decision_card_id": "card-old", "account_id": "account-orchid", "security_id": "security-aster-001", "expires_at": "2035-05-23T08:00:00+00:00", "review_window_end": "2035-05-20T08:00:00+00:00", "rules": [], "plan_family_id": "family-old", "revision": 1, "supersedes_plan_id": None, "close_plan_id": "plan-old"}),
        ("PlanClosed", "closed-old", {"plan_closed_id": "closed-old", "draft_id": "draft-close-old", "closed_plan_id": "plan-old", "plan_family_id": "family-old", "closed_at": "2035-05-22T08:00:00+00:00", "closed_by": "synthetic-user", "channel": "fixture-chat"}),
    ]
    for kind, _, payload in facts:
        if kind != "TradePlanDraft":
            continue
        content = {key: payload.get(key) for key in ("decision_card_id", "account_id", "security_id", "expires_at", "review_window_end", "rules", "plan_family_id", "revision", "supersedes_plan_id", "close_plan_id")}
        payload["content_hash"] = digest(content)
        if payload["close_plan_id"] is None:
            plan = next(record for record_kind, _, record in facts if record_kind == "TradePlan")
            plan["content_hash"] = payload["content_hash"]
    if ambiguous:
        plan = next(payload for kind, _, payload in facts if kind == "TradePlan")
        facts.append(("TradePlan", "plan-copy", plan | {"trade_plan_id": "plan-copy"}))
    connection.executemany("INSERT INTO old_facts VALUES(?,?,?)", [(kind, old_id, json.dumps(payload)) for kind, old_id, payload in facts])
    connection.execute(
        "INSERT INTO old_commands VALUES(?,?,?,?,?)",
        ("account.confirm", "legacy-account-command", digest(legacy_account_candidate()), "AccountSnapshot", "snapshot-old"),
    )
    connection.commit()
    connection.close()


def test_fresh_and_populated_roots_migrate_and_restart(tmp_path) -> None:
    fresh = tmp_path / "fresh.sqlite3"
    sqlite3.connect(fresh).close()
    assert migrate_synthetic_root(fresh, tmp_path / "fresh-target")["migrated"] == 0

    populated = tmp_path / "populated.sqlite3"
    populated_source(populated)
    target = tmp_path / "target"
    result = migrate_synthetic_root(populated, target)
    assert result["migrated"] == 16 and result["commands_migrated"] == 1 and result["backup_verified"]
    assert SQLiteStore(target).doctor()["ok"]
    assert open_application(target).account_show("account-orchid").value["snapshot_id"] == "snapshot-old"
    assert migrate_synthetic_root(populated, target)["replayed"]


def test_ambiguity_corruption_and_interruption_never_half_migrate(tmp_path) -> None:
    ambiguous = tmp_path / "ambiguous.sqlite3"
    populated_source(ambiguous, ambiguous=True)
    with pytest.raises(MigrationBlocked, match="duplicate plan revision"):
        migrate_synthetic_root(ambiguous, tmp_path / "ambiguous-target")

    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")
    with pytest.raises(MigrationBlocked, match="unreadable"):
        migrate_synthetic_root(corrupt, tmp_path / "corrupt-target")

    interrupted = tmp_path / "interrupted.sqlite3"
    populated_source(interrupted)
    target = tmp_path / "interrupted-target"
    with pytest.raises(MigrationBlocked, match="injected before commit"):
        migrate_synthetic_root(interrupted, target, fault_at="before_commit")
    assert SQLiteStore(target).list("AccountSnapshot") == []
    assert migrate_synthetic_root(interrupted, target)["migrated"] == 16


def test_broken_relationship_malformed_fact_and_command_reference_block(tmp_path) -> None:
    broken = tmp_path / "broken.sqlite3"
    populated_source(broken)
    connection = sqlite3.connect(broken)
    row = connection.execute(
        "SELECT payload FROM old_facts WHERE kind='RiskLimitResult'"
    ).fetchone()
    payload = json.loads(row[0])
    payload["input_refs"]["account_snapshot_id"] = "snapshot-missing"
    connection.execute(
        "UPDATE old_facts SET payload=? WHERE kind='RiskLimitResult'", (json.dumps(payload),)
    )
    connection.commit()
    connection.close()
    with pytest.raises(MigrationBlocked, match="RiskLimitResult account relationship"):
        migrate_synthetic_root(broken, tmp_path / "broken-target")

    malformed = tmp_path / "malformed.sqlite3"
    populated_source(malformed)
    connection = sqlite3.connect(malformed)
    connection.execute(
        "UPDATE old_facts SET payload=? WHERE kind='DecisionTask'", (json.dumps({"task_id": "task-old"}),)
    )
    connection.commit()
    connection.close()
    with pytest.raises(MigrationBlocked, match="malformed"):
        migrate_synthetic_root(malformed, tmp_path / "malformed-target")

    command = tmp_path / "command.sqlite3"
    populated_source(command)
    connection = sqlite3.connect(command)
    connection.execute("UPDATE old_commands SET result_id='snapshot-missing'")
    connection.commit()
    connection.close()
    with pytest.raises(MigrationBlocked, match="application command result relationship"):
        migrate_synthetic_root(command, tmp_path / "command-target")


def test_migration_blocks_unknown_confirmation_revision_and_outcome_semantics(tmp_path) -> None:
    confirmation = tmp_path / "confirmation.sqlite3"
    populated_source(confirmation)
    update_fact(confirmation, "TradePlan", lambda payload: payload.update(content_hash="wrong"))
    with pytest.raises(MigrationBlocked, match="confirmation content"):
        migrate_synthetic_root(confirmation, tmp_path / "confirmation-target")

    revision = tmp_path / "revision.sqlite3"
    populated_source(revision)
    def make_second_revision(payload) -> None:
        payload["revision"] = 2
        content = {key: payload.get(key) for key in ("decision_card_id", "account_id", "security_id", "expires_at", "review_window_end", "rules", "plan_family_id", "revision", "supersedes_plan_id", "close_plan_id")}
        payload["content_hash"] = digest(content)
    update_fact(revision, "TradePlanDraft", make_second_revision, old_id="draft-old")
    connection = sqlite3.connect(revision)
    revised_hash = json.loads(connection.execute("SELECT payload FROM old_facts WHERE old_id='draft-old'").fetchone()[0])["content_hash"]
    connection.close()
    update_fact(revision, "TradePlan", lambda payload: payload.update(revision=2, content_hash=revised_hash))
    with pytest.raises(MigrationBlocked, match="revision chain"):
        migrate_synthetic_root(revision, tmp_path / "revision-target")

    outcome = tmp_path / "outcome.sqlite3"
    populated_source(outcome)
    update_fact(outcome, "DecisionReview", lambda payload: payload.update(as_of="2035-05-01T08:00:00+00:00"), old_id="outcome-old")
    with pytest.raises(MigrationBlocked, match="OUTCOME review window"):
        migrate_synthetic_root(outcome, tmp_path / "outcome-target")


def test_migration_blocks_unverified_execution_process_refs_close_and_command_contract(tmp_path) -> None:
    execution = tmp_path / "execution.sqlite3"
    populated_source(execution)
    update_fact(execution, "ExecutionRecord", lambda payload: payload.update(verification_status="provider_claimed"))
    with pytest.raises(MigrationBlocked, match="user declaration"):
        migrate_synthetic_root(execution, tmp_path / "execution-target")

    malformed_execution = tmp_path / "malformed-execution.sqlite3"
    populated_source(malformed_execution)
    update_fact(malformed_execution, "ExecutionRecord", lambda payload: payload.update(quantity_delta="not-a-number"))
    with pytest.raises(MigrationBlocked, match="user declaration.*malformed"):
        migrate_synthetic_root(malformed_execution, tmp_path / "malformed-execution-target")

    account = tmp_path / "account-confirmation.sqlite3"
    populated_source(account)
    update_fact(account, "AccountSnapshot", lambda payload: payload.update(confirmed_by=""))
    with pytest.raises(MigrationBlocked, match="AccountSnapshot user confirmation"):
        migrate_synthetic_root(account, tmp_path / "account-confirmation-target")

    policy = tmp_path / "policy.sqlite3"
    populated_source(policy)
    update_fact(policy, "RiskPolicy", lambda payload: payload.update(max_concentration="1.5"))
    with pytest.raises(MigrationBlocked, match="RiskPolicy user confirmation or limits"):
        migrate_synthetic_root(policy, tmp_path / "policy-target")

    nonfinite_policy = tmp_path / "nonfinite-policy.sqlite3"
    populated_source(nonfinite_policy)
    update_fact(nonfinite_policy, "RiskPolicy", lambda payload: payload.update(max_position_value="NaN"))
    with pytest.raises(MigrationBlocked, match="RiskPolicy user confirmation or limits"):
        migrate_synthetic_root(nonfinite_policy, tmp_path / "nonfinite-policy-target")

    invalid_cash = tmp_path / "invalid-cash.sqlite3"
    populated_source(invalid_cash)
    update_fact(invalid_cash, "AccountSnapshot", lambda payload: payload.update(cash={}))
    with pytest.raises(MigrationBlocked, match="AccountSnapshot user confirmation"):
        migrate_synthetic_root(invalid_cash, tmp_path / "invalid-cash-target")

    process = tmp_path / "process.sqlite3"
    populated_source(process)
    update_fact(process, "DecisionReview", lambda payload: payload.update(frozen_refs=["valuation-old"]), old_id="process-old")
    update_fact(process, "ValuationAssessment", lambda payload: payload.update(as_of="2035-04-21T08:00:00+00:00"))
    with pytest.raises(MigrationBlocked, match="after its as_of"):
        migrate_synthetic_root(process, tmp_path / "process-target")

    closed = tmp_path / "closed.sqlite3"
    populated_source(closed)
    update_fact(closed, "PlanClosed", lambda payload: payload.update(closed_by=""))
    with pytest.raises(MigrationBlocked, match="confirmation content"):
        migrate_synthetic_root(closed, tmp_path / "closed-target")

    command = tmp_path / "command-kind.sqlite3"
    populated_source(command)
    connection = sqlite3.connect(command)
    connection.execute("UPDATE old_commands SET result_kind='InvestmentCase', result_id='case-old'")
    connection.commit()
    connection.close()
    with pytest.raises(MigrationBlocked, match="result kind"):
        migrate_synthetic_root(command, tmp_path / "command-kind-target")


def test_verified_backup_restores_complete_database(tmp_path) -> None:
    source = tmp_path / "populated.sqlite3"
    populated_source(source)
    target = tmp_path / "target"
    migrate_synthetic_root(source, target)
    backup = target / "pre-migration-source.sqlite3"
    restored_source = tmp_path / "restored-source.sqlite3"
    restored_source.write_bytes(backup.read_bytes())
    restored_target = tmp_path / "restored-target"
    assert migrate_synthetic_root(restored_source, restored_target)["migrated"] == 16
    assert SQLiteStore(restored_target).doctor()["ok"]


def test_all_eight_operations_continue_after_migrated_restart(tmp_path) -> None:
    source = tmp_path / "populated.sqlite3"
    populated_source(source)
    target = tmp_path / "target"
    migrate_synthetic_root(source, target)
    app = open_application(target)
    account = app.account_show("account-orchid")
    replay = app.account_confirm(
        legacy_account_candidate(), idempotency_key="legacy-account-command"
    )
    assert account.ok and replay.value["snapshot_id"] == "snapshot-old"

    evidence = build_evidence_set(
        "2035-04-18T08:00:00+00:00",
        [
            {
                "name": "market_price",
                "value": "17.5",
                "source_id": "fixture-source-price",
                "as_of": "2035-04-18T08:00:00+00:00",
            }
        ],
    ).as_dict()
    case = app.research_commit(
        {
            "security_id": "security-aster-001",
            "as_of": "2035-04-18T08:00:00+00:00",
            "evidence_set": evidence,
            "candidate": {
                "thesis": "fixture migrated-path thesis",
                "counterargument": "fixture migrated-path counterargument",
                "drivers": ["fixture driver"],
                "risks": ["fixture risk"],
                "falsifiers": ["fixture falsifier"],
                "uncertainties": ["fixture uncertainty"],
            },
        },
        idempotency_key="post-migration-research",
    )
    valuation = app.valuation_assess(
        {
            "investment_case_id": case.value["investment_case_id"],
            "evidence_set": evidence,
            "method": "dcf",
            "company_archetype": "mature_non_financial",
        },
        idempotency_key="post-migration-valuation",
    )
    prepared = app.planning_prepare(
        {
            "investment_case_id": case.value["investment_case_id"],
            "valuation_assessment_id": valuation.value["valuation_assessment_id"],
            "account_snapshot_id": account.value["snapshot_id"],
            "prices": {
                "security-aster-001": {
                    "amount": "10",
                    "currency": "XCU",
                    "source_id": "fixture-source-price",
                }
            },
            "risk_policy": {
                "policy_id": "risk-policy-post-migration",
                "max_concentration": "0.7",
                "max_position_value": "1500",
                "confirmed": True,
                "confirmed_by": "synthetic-user",
            },
            "plan": {
                "expires_at": "2035-04-20T08:00:00+00:00",
                "review_window_end": "2035-05-20T08:00:00+00:00",
                "rules": [
                    {
                        "rule_id": "rule-post-migration",
                        "type": "price_above",
                        "threshold": "19",
                        "evidence_name": "market_price",
                    }
                ],
            },
        },
        idempotency_key="post-migration-prepare",
    )
    draft = prepared.value["trade_plan_draft"]
    plan_result = app.planning_confirm(
        {
            "draft_id": draft["draft_id"],
            "content_hash": draft["content_hash"],
            "explicit_confirmation": True,
            "confirmed_at": "2035-04-19T08:00:00+00:00",
            "confirmed_by": "synthetic-user",
            "channel": "fixture-chat",
        },
        idempotency_key="post-migration-confirm",
    )
    plan = plan_result.value
    monitored = app.monitor_evaluate(
        {"trade_plan_id": plan["trade_plan_id"], "evidence_set": market_evidence("20")},
        idempotency_key="post-migration-monitor",
    )
    reviewed = app.review_commit(
        {"review_type": "PROCESS", "trade_plan_id": plan["trade_plan_id"], "task_id": monitored.value["decision_task"]["task_id"], "as_of": "2035-04-20T08:00:00+00:00", "frozen_refs": [plan["decision_card_id"]], "assessment": "Fixture post-migration process assessment."},
        idempotency_key="post-migration-review",
    )
    assert case.ok and valuation.ok and prepared.ok and plan_result.ok and monitored.ok and reviewed.ok


@pytest.mark.parametrize("fault_at", ["after_backup", "after_prepare", "after_schema", "after_first_record", "after_commands", "before_marker", "before_commit", "after_commit"])
def test_each_migration_failure_boundary_is_empty_or_complete(tmp_path, fault_at) -> None:
    source = tmp_path / f"{fault_at}.sqlite3"
    populated_source(source)
    target = tmp_path / f"target-{fault_at}"
    with pytest.raises(MigrationBlocked, match="injected"):
        migrate_synthetic_root(source, target, fault_at=fault_at)
    store = SQLiteStore(target)
    count = len(store.list("AccountSnapshot"))
    assert count in {0, 1}
    if count == 1:
        assert store.get("MigrationMarker", "integrated") is not None
        assert migrate_synthetic_root(source, target)["replayed"]
    else:
        assert migrate_synthetic_root(source, target)["migrated"] == 16
