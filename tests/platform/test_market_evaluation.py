from __future__ import annotations

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.application_task_fixture import (
    TEST_MARKET_QUERY_POLICY,
    TEST_QUERY_POLICY,
    TEST_SOURCE_POLICY,
)

from trading_platform.application.contracts import StartResearchWorkflow


from datetime import date, timedelta
from pathlib import Path

import pytest

from trading_platform.application.contracts import SecurityIdentity
from trading_platform.application.market_contracts import BuildMarketSnapshotCommand, EvaluatePlanCommand
from dataclasses import replace
from trading_platform.domain.plans import ConfirmPlanDraftCommand, CreatePlanDraftCommand, PlanCondition, PlanConstant, PlanRule
from trading_platform.market import MarketError
from trading_platform.identity.code import CodeIdentity
from trading_platform.identity import canonical_hash
from tests.platform.test_chart_annotations import _root as chart_root
from tests.platform.test_research_workflow import _request as research_request
from tests.platform.test_trade_plans import _content


def _root(path: Path, *, missing_amount: bool = False, freshness: str = "valid", suspended: bool = False, peer_suspended: bool = False, at_limit_up: bool = False, corporate_conflict: bool = False):
    root = chart_root(path)
    root.faults.record_official_filing_workflow_snapshot()
    research = root.research.handle(
        StartResearchWorkflow(research_request("market:research"))
    )
    root.research_run_id = research.research_run_id
    for stable_id, code in (("security_benchmark", "000300"), ("security_peer", "000002")):
        root.watchlist.add(f"watch:{stable_id}", SecurityIdentity(stable_id, "SZSE", code, "CNY", "2010-01-01"))
    connection = SQLiteOwningAdapterFixture(root.data_root)
    with connection.transaction():
        universe_members = [
            {"security_id": security_id, "listed_from": "2010-01-01", "delisted_after": None, "st_from": None, "st_to": None, "source_ref": f"fixture:{security_id}"}
            for security_id in ("security_yihua", "security_peer")
        ] + [{"security_id": "security_future", "listed_from": "2026-07-12", "delisted_after": None, "st_from": None, "st_to": None, "source_ref": "fixture:future-listing"}]
        universe_members.sort(key=lambda item: item["security_id"])
        connection.execute("INSERT INTO market_universe_version VALUES(?,?,?,?,?)", ("universe_market", "CN_A_SHARE", "2026-07-11T00:00:00+00:00", "universe-source@1", canonical_hash(universe_members)))
        for item in universe_members:
            connection.execute("INSERT INTO market_universe_member VALUES(?,?,?,?,?,?,?)", ("universe_market", item["security_id"], item["listed_from"], item["delisted_after"], item["st_from"], item["st_to"], item["source_ref"]))
        connection.execute("INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("attempt_market", "market-fixture", "fixture", "fixture@1", "daily", "synthetic-contract-fixture", "fixture", "urn:test:market", "{}", "{}", "timestamp", "test-terms", "complete", "created", None, "2026-07-10T09:00:00+00:00", None, None, None, "not_applicable", TEST_QUERY_POLICY.identity, TEST_SOURCE_POLICY.identity, "rights_test_fixture"))
        members = []
        start = date(2025, 6, 1)
        for offset in range(280):
            session = (start + timedelta(days=offset)).isoformat()
            for position, security_id in enumerate(("security_yihua", "security_benchmark", "security_peer")):
                version_id = f"market_v_{offset}_{position}"
                base = 50 + position * 10
                close = base + offset / 10
                amount = None if missing_amount and offset == 279 and security_id == "security_peer" else str(1000000 + offset * 1000 + position * 100)
                connection.execute("INSERT INTO normalized_record VALUES(?,?,?)", (f"market_r_{offset}_{position}", "daily", f"{security_id}:{session}"))
                connection.execute("INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (version_id, f"market_r_{offset}_{position}", 1, f"hash_{offset}_{position}", "attempt_market", session, session, "date", f"{session}T08:00:00+00:00", "publisher_timestamp", "2026-07-10T09:00:00+00:00", "pass", None))
                connection.execute("INSERT INTO ohlcv_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (version_id, security_id, session, "Asia/Shanghai", "none", str(close - 1), str(close + 1), str(close - 2), str(close), "1000", "hand", amount, "CNY", "CNY"))
                members.append(version_id)
        connection.execute("INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("snapshot_market", "security_yihua", "market", "2026-07-11", (start + timedelta(days=279)).isoformat(), "2026-07-11T00:00:00+00:00", "Asia/Shanghai", "cn-calendar@2026", TEST_MARKET_QUERY_POLICY.identity, TEST_SOURCE_POLICY.identity, "freshness@1", "market-members", freshness, "pass", 3, 3, 0, 0, 0 if freshness == "valid" else 1, "effective_complete_session", "2026-07-10T09:00:00+00:00"))
        for index, version_id in enumerate(members):
            connection.execute("INSERT INTO data_snapshot_member VALUES(?,?,?,?)", ("snapshot_market", version_id, "daily", index))
        connection.execute("INSERT INTO data_snapshot_universe_ref VALUES(?,?,?)", ("snapshot_market", "universe_market", "CN_A_SHARE"))
        current_close = str(50 + 279 / 10)
        effective_session = (start + timedelta(days=279)).isoformat()
        connection.execute("INSERT INTO security_market_constraint VALUES(?,?,?,?,?,?,?,?)", ("snapshot_market", "security_yihua", effective_session, int(suspended), current_close if at_limit_up else "90", "40", int(corporate_conflict), '["fixture:exchange-limit","fixture:corporate-action-check"]'))
        connection.execute("INSERT INTO security_market_constraint VALUES(?,?,?,?,?,?,?,?)", ("snapshot_market", "security_peer", effective_session, int(peer_suspended), "100", "1", 0, '["fixture:peer-suspension-status"]'))
    base_content = _content(root)
    rules = (
        base_content.rules[0],
        PlanRule("rule_market_gate", "market_gate", "block_user_intent", "entry", PlanCondition("leaf", "market.trend", "eq", PlanConstant("enum", "down", "market_trend"), "current_complete_session")),
        PlanRule("rule_invalidation", "invalidation", "mark_invalidation_candidate", "plan", PlanCondition("leaf", "security.close_unadjusted", "lt", PlanConstant("decimal", "90", "CNY_per_share", "CNY"), "current_complete_session")),
        PlanRule("rule_exit", "exit_review", "prompt_review", "exit", PlanCondition("leaf", "security.close_unadjusted", "gt", PlanConstant("decimal", "100", "CNY_per_share", "CNY"), "current_complete_session")),
        PlanRule("rule_position", "risk_limit", "mark_risk_limit_breach", "plan", PlanCondition("leaf", "position.quantity", "gt", PlanConstant("decimal", "0", "share"), "current_complete_session"), "not_applicable"),
        PlanRule("rule_suspension", "market_gate", "block_user_intent", "entry", PlanCondition("leaf", "security.suspended", "eq", PlanConstant("bool", "false", "market_status"), "current_complete_session")),
        PlanRule("rule_limit", "market_gate", "block_user_intent", "entry", PlanCondition("leaf", "security.limit_state", "eq", PlanConstant("enum", "none", "security_limit_state"), "current_complete_session")),
        PlanRule("rule_liquidity", "market_gate", "block_user_intent", "increase", PlanCondition("leaf", "market.liquidity", "eq", PlanConstant("enum", "ample", "market_liquidity"), "current_complete_session")),
    )
    draft = root.plans.create_draft(CreatePlanDraftCommand("market:plan:draft", replace(base_content, rules=rules)))
    version = root.plans.confirm_draft(ConfirmPlanDraftCommand("market:plan:confirm", draft.draft_id, 1, "activate"))
    return root, version


def _market_command(invocation: str = "market:build", **changes):
    code_identity = CodeIdentity("fixture", "source", "lock", "migration", "workflow", "frontend", "config", "package", "model-policy", "licenses")
    values = dict(invocation_id=invocation, security_id="security_yihua", market_scope_id="CN_A_SHARE", data_snapshot_id="snapshot_market", market_model_version="cn-a-share-market@1", freshness_policy_version="freshness@1", code_identity=code_identity)
    values.update(changes)
    return BuildMarketSnapshotCommand(**values)


def test_transparent_market_snapshot_and_read_only_plan_evaluation(tmp_path: Path) -> None:
    root, plan = _root(tmp_path)
    market = root.market.build_market_snapshot(_market_command())
    assert root.market.build_market_snapshot(_market_command("market:replay")) == market
    assert market.status == "limited"  # unsupported optional components remain explicit
    components = {item.component_id: item for item in market.components}
    assert set(components) >= {"market.trend", "market.breadth", "market.liquidity", "market.volatility", "security.price_context", "market.macro", "market.news", "market.sentiment"}
    assert components["market.breadth"].coverage_expected == 3 and components["market.breadth"].coverage_eligible == 2
    assert components["market.breadth"].coverage_excluded == 1 and components["market.breadth"].coverage_missing == 0
    assert "security_future:NOT_LISTED_AT_CUTOFF" in components["market.breadth"].evidence_refs
    assert dict(components["security.price_context"].values)["limit_state"] == "none"
    assert components["market.macro"].status == "unsupported"
    changed_code = replace(_market_command("market:code"), code_identity=replace(_market_command().code_identity, source_hash="changed-source"))
    assert root.market.build_market_snapshot(changed_code).market_snapshot_id != market.market_snapshot_id
    with pytest.raises(Exception, match="MARKET_UNIVERSE_IMMUTABLE"):
        SQLiteOwningAdapterFixture(root.data_root).execute("UPDATE market_universe_member SET source_ref='changed' WHERE market_universe_version_id='universe_market' AND security_id='security_yihua'")
    with pytest.raises(Exception, match="MARKET_CONSTRAINT_IMMUTABLE"):
        SQLiteOwningAdapterFixture(root.data_root).execute("UPDATE security_market_constraint SET limit_up_decimal='999' WHERE data_snapshot_id='snapshot_market'")
    before = root.plans.get_lifecycle(plan.plan_id)
    evaluation = root.market.evaluate_plan(EvaluatePlanCommand("evaluation:one", plan.plan_version_id, market.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@1"))
    replay = root.market.evaluate_plan(EvaluatePlanCommand("evaluation:two", plan.plan_version_id, market.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@1"))
    assert replay == evaluation and evaluation.status == "completed" and evaluation.outcome == "triggered"
    assert {item.result for item in evaluation.rule_results} >= {"triggered", "not_triggered", "not_applicable"}
    assert {item.effect for item in evaluation.rule_results} >= {"prompt_review", "block_user_intent", "mark_invalidation_candidate", "mark_risk_limit_breach"}
    assert evaluation.rule_results[0].operands and evaluation.rule_results[0].evidence_refs
    assert root.plans.get_lifecycle(plan.plan_id) == before
    changed_policy = root.market.evaluate_plan(EvaluatePlanCommand("evaluation:policy", plan.plan_version_id, market.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@2"))
    assert changed_policy.plan_evaluation_id != evaluation.plan_evaluation_id
    second_content = replace(plan.content, based_on_version_id=plan.plan_version_id, rationale="用户更新但尚未确认。")
    second_draft = root.plans.create_draft(CreatePlanDraftCommand("market:plan:v2-draft", second_content, plan.plan_id))
    assert root.plans.get_active_for_security("security_yihua").active_version.plan_version_id == plan.plan_version_id
    assert root.market.get_plan_evaluation(evaluation.plan_evaluation_id) == evaluation
    v2 = root.plans.confirm_draft(ConfirmPlanDraftCommand("market:plan:v2-confirm", second_draft.draft_id, 1, "activate"))
    v2_evaluation = root.market.evaluate_plan(EvaluatePlanCommand("evaluation:v2", v2.plan_version_id, market.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@1"))
    assert v2_evaluation.plan_version_id == v2.plan_version_id and root.market.get_plan_evaluation(evaluation.plan_evaluation_id).plan_version_id == plan.plan_version_id
    adapter = SQLiteOwningAdapterFixture(root.data_root)
    with adapter.transaction():
        adapter.execute("INSERT INTO data_snapshot SELECT 'snapshot_market_revision',scope_id,snapshot_purpose,requested_date,effective_session_date,'2026-07-11T01:00:00+00:00',market_timezone,calendar_version,query_policy_identity,source_policy_identity,freshness_policy_version,'market-members-revision',freshness_status,quality_status,coverage_expected,coverage_eligible,coverage_excluded,coverage_missing,stale_by_days,freshness_basis,last_success_at FROM data_snapshot WHERE data_snapshot_id='snapshot_market'")
        adapter.execute("INSERT INTO data_snapshot_member SELECT 'snapshot_market_revision',normalized_version_id,member_role,member_order FROM data_snapshot_member WHERE data_snapshot_id='snapshot_market'")
        adapter.execute("INSERT INTO data_snapshot_universe_ref VALUES('snapshot_market_revision','universe_market','CN_A_SHARE')")
    adapter.close()
    revised_market = root.market.build_market_snapshot(_market_command("market:revision", data_snapshot_id="snapshot_market_revision"))
    assert revised_market.market_snapshot_id != market.market_snapshot_id and root.market.get_market_snapshot(market.market_snapshot_id) == market
    with pytest.raises(Exception, match="PLAN_EVALUATION_IMMUTABLE"):
        SQLiteOwningAdapterFixture(root.data_root).execute("DELETE FROM plan_evaluation WHERE plan_evaluation_id=?", (evaluation.plan_evaluation_id,))
    root.close()


def test_coverage_and_freshness_fail_closed_without_erasing_history(tmp_path: Path) -> None:
    root, plan = _root(tmp_path / "missing", missing_amount=True)
    limited = root.market.build_market_snapshot(_market_command())
    liquidity = next(item for item in limited.components if item.component_id == "market.liquidity")
    assert liquidity.status == "blocked" and liquidity.coverage_missing == 1
    evaluation = root.market.evaluate_plan(EvaluatePlanCommand("evaluation:limited", plan.plan_version_id, limited.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@1"))
    assert evaluation.status == "blocked" and evaluation.outcome is None and evaluation.completeness == "partial"
    assert any(item.result == "triggered" for item in evaluation.rule_results)
    assert any(item.result == "blocked" for item in evaluation.rule_results)
    root.close()

    stale_root, stale_plan = _root(tmp_path / "stale", freshness="stale")
    blocked = stale_root.market.build_market_snapshot(_market_command())
    assert blocked.status == "blocked"
    blocked_evaluation = stale_root.market.evaluate_plan(EvaluatePlanCommand("evaluation:blocked", stale_plan.plan_version_id, blocked.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@1"))
    assert blocked_evaluation.status == "blocked" and blocked_evaluation.outcome is None
    assert {item.reason_code for item in blocked_evaluation.rule_results} == {"INPUT_STALE"}
    assert stale_root.market.get_market_snapshot(blocked.market_snapshot_id) == blocked
    stale_root.close()


def test_evaluation_requires_exact_active_version_and_snapshot_scope(tmp_path: Path) -> None:
    root, plan = _root(tmp_path)
    market = root.market.build_market_snapshot(_market_command())
    with pytest.raises(MarketError, match="PLAN_VERSION_NOT_ACTIVE"):
        root.market.evaluate_plan(EvaluatePlanCommand("evaluation:inactive", "missing", market.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@1"))
    with pytest.raises(MarketError, match="MARKET_SNAPSHOT_SCOPE_MISMATCH"):
        root.market.build_market_snapshot(_market_command("market:scope", market_scope_id="OTHER"))
    with pytest.raises(MarketError, match="MARKET_MODEL_OR_POLICY_UNAVAILABLE"):
        root.market.build_market_snapshot(_market_command("market:model", market_model_version="unknown@1"))
    root.close()


def test_suspension_and_limit_facts_are_evaluated_without_lifecycle_side_effects(tmp_path: Path) -> None:
    limit_root, limit_plan = _root(tmp_path / "limit", at_limit_up=True)
    limit_market = limit_root.market.build_market_snapshot(_market_command())
    assert dict(next(item for item in limit_market.components if item.component_id == "security.price_context").values)["limit_state"] == "up"
    limit_evaluation = limit_root.market.evaluate_plan(EvaluatePlanCommand("evaluation:limit", limit_plan.plan_version_id, limit_market.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@1"))
    assert any(dict(item.operands).get("metric_ref") == "security.limit_state" for item in limit_evaluation.rule_results)
    assert limit_root.plans.get_lifecycle(limit_plan.plan_id).lifecycle_status == "active"
    limit_root.close()

    suspended_root, suspended_plan = _root(tmp_path / "suspended", suspended=True)
    suspended_market = suspended_root.market.build_market_snapshot(_market_command())
    context = next(item for item in suspended_market.components if item.component_id == "security.price_context")
    assert dict(context.values)["suspended"] == "true"
    suspended_evaluation = suspended_root.market.evaluate_plan(EvaluatePlanCommand("evaluation:suspended", suspended_plan.plan_version_id, suspended_market.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@1"))
    assert any(item.result == "not_triggered" and dict(item.operands).get("metric_ref") == "security.suspended" and dict(item.operands).get("actual") == "true" for item in suspended_evaluation.rule_results)
    assert suspended_root.plans.get_lifecycle(suspended_plan.plan_id).lifecycle_status == "active"
    suspended_root.close()

    cross_section_root, _ = _root(tmp_path / "cross-section-suspended", peer_suspended=True)
    cross_section_market = cross_section_root.market.build_market_snapshot(_market_command())
    breadth = next(item for item in cross_section_market.components if item.component_id == "market.breadth")
    assert breadth.coverage_excluded == 2 and breadth.coverage_missing == 0
    assert "security_peer:SUSPENDED_AT_CUTOFF" in breadth.evidence_refs
    cross_section_root.close()

    conflict_root, _ = _root(tmp_path / "corporate-conflict", corporate_conflict=True)
    conflict_market = conflict_root.market.build_market_snapshot(_market_command())
    assert conflict_market.status == "blocked"
    assert next(item for item in conflict_market.components if item.component_id == "security.price_context").reason_code == "INPUT_CONFLICTED"
    conflict_root.close()
