from __future__ import annotations

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture

from trading_platform.application.contracts import StartResearchWorkflow


from dataclasses import replace
from pathlib import Path

import pytest

from trading_platform.domain.plans import (
    ActivatePlanVersionCommand, AdjustedPriceEvidence, ChangePlanLifecycleCommand,
    ConfirmPlanDraftCommand, CreatePlanDraftCommand, DiscardPlanDraftCommand,
    PlanCondition, PlanConstant, PlanDraftContent, PlanReference, PlanRule,
    UpdatePlanDraftCommand,
)
from trading_platform.plans import PlanError
from tests.platform.test_chart_annotations import _root as chart_root
from tests.platform.test_research_workflow import _request as research_request


def _root(path: Path):
    root = chart_root(path)
    root.faults.record_official_filing_workflow_snapshot()
    research = root.research.handle(
        StartResearchWorkflow(research_request("plan:research"))
    )
    root.research_run_id = research.research_run_id
    adapter = SQLiteOwningAdapterFixture(root.data_root)
    with adapter.transaction():
        adapter.execute("INSERT OR IGNORE INTO price_factor_set VALUES(?,?,?,?,?)", ("factor_set_fixture", "snapshot_chart", "fixture:corporate-action-factor", "unique_deterministic", "deterministic_reverse@1"))
    adapter.close()
    return root


def _leaf(metric: str = "security.close_unadjusted", value: str = "80.00") -> PlanCondition:
    return PlanCondition("leaf", metric, "lte", PlanConstant("decimal", value, "CNY_per_share", "CNY"), "current_complete_session")


def _content(root, **changes: object) -> PlanDraftContent:
    research_run_id = root.research_run_id
    base = PlanDraftContent(
        security_id="security_yihua",
        based_on_version_id=None,
        references=(PlanReference("ResearchRun", research_run_id), PlanReference("Evidence", "evidence_fixture", "unresolved_external")),
        data_snapshot_id="snapshot_chart",
        horizon_start="2026-07-11",
        horizon_end="2026-10-11",
        review_by="2026-08-11",
        rules=(PlanRule("rule_price_review", "entry_review", "prompt_review", "entry", _leaf()),),
        max_planned_notional="10000.00",
        max_planned_loss="500.00",
        currency="CNY",
        market_gate_policy_version="market-gate@1",
        metric_catalog_version="metric-catalog@1",
        evaluator_policy_version="plan-evaluator@1",
        user_input_source="user_fixture_input",
        rationale="用于验证用户明确输入的规则，不构成平台建议。",
    )
    return replace(base, **changes)


def _create(root, invocation: str = "plan:draft", content=None, plan_id=None):
    return root.plans.create_draft(CreatePlanDraftCommand(invocation, content or _content(root), plan_id))


def test_atomic_confirmation_idempotency_preview_and_restart(tmp_path: Path) -> None:
    root = _root(tmp_path)
    draft = _create(root)
    assert _create(root) == draft
    preview = root.plans.confirmation(draft.draft_id)
    assert tuple(section.name for section in preview.sections) == ("basis_and_horizon", "rules", "risk_budget", "market_gates")
    assert dict(preview.sections[0].fields)["data_snapshot_id"] == "snapshot_chart"
    assert root.plans.confirmation(draft.draft_id).diff == preview.diff
    assert preview.execution_boundary == "records_user_rules_only_no_trade_execution"
    version = root.plans.confirm_draft(ConfirmPlanDraftCommand("plan:confirm", draft.draft_id, 1, "activate"))
    assert root.plans.confirm_draft(ConfirmPlanDraftCommand("plan:confirm", draft.draft_id, 1, "activate")) == version
    assert root.plans.get_active_for_security("security_yihua").active_version == version
    root.close()
    rebuilt = _root(tmp_path)
    assert rebuilt.plans.get_active_for_security("security_yihua").active_version == version
    rebuilt.close()


def test_confirmation_failure_rolls_back_every_record(tmp_path: Path) -> None:
    root = _root(tmp_path)
    draft = _create(root)
    SQLiteOwningAdapterFixture(root.data_root).execute("CREATE TRIGGER reject_activation BEFORE INSERT ON plan_activation BEGIN SELECT RAISE(ABORT,'INJECTED'); END")
    with pytest.raises(PlanError, match="PLAN_CONFIRMATION_ATOMIC_FAILURE"):
        root.plans.confirm_draft(ConfirmPlanDraftCommand("plan:confirm:fail", draft.draft_id, 1, "activate"))
    for table in ("trade_plan", "trade_plan_version", "plan_activation", "trade_plan_transition"):
        assert SQLiteOwningAdapterFixture(root.data_root).execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert root.plans.get_draft(draft.draft_id).status == "open"
    root.close()


def test_revision_v2_switch_discard_and_ended_terminal(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first = _create(root)
    v1 = root.plans.confirm_draft(ConfirmPlanDraftCommand("plan:confirm", first.draft_id, 1, "activate"))
    second_content = replace(_content(root), based_on_version_id=v1.plan_version_id, max_planned_loss="450")
    second = _create(root, "plan:draft:2", second_content, v1.plan_id)
    assert root.plans.get_active_for_security("security_yihua").active_version == v1
    with pytest.raises(PlanError, match="PLAN_DRAFT_REVISION_CONFLICT"):
        root.plans.update_draft(UpdatePlanDraftCommand("plan:stale", second.draft_id, v1.plan_id, 0, second.content))
    updated = root.plans.update_draft(UpdatePlanDraftCommand("plan:update", second.draft_id, v1.plan_id, 1, replace(second.content, rationale="用户更新理由。")))
    assert {
        item.field for item in root.plans.confirmation(second.draft_id).diff
    } >= {"max_planned_loss", "rationale"}
    v2 = root.plans.confirm_draft(ConfirmPlanDraftCommand("plan:confirm:2", second.draft_id, 2, "activate"))
    assert root.plans.get_active_for_security("security_yihua").active_version == v2
    assert root.plans.get_version(v1.plan_version_id).content_hash == v1.content_hash
    disposable = _create(root, "plan:discard:create", replace(_content(root), based_on_version_id=v2.plan_version_id), v1.plan_id)
    assert root.plans.discard_draft(DiscardPlanDraftCommand("plan:discard", disposable.draft_id, 1)).status == "discarded"
    lifecycle = root.plans.end(ChangePlanLifecycleCommand("plan:end", v1.plan_id, 4, "user_ended"))
    assert lifecycle.lifecycle_status == "ended"
    with pytest.raises(PlanError, match="PLAN_ENDED_TERMINAL"):
        root.plans.activate_version(ActivatePlanVersionCommand("plan:reactivate", v1.plan_id, v1.plan_version_id, 5))
    continuation = _create(root, "plan:continue", replace(_content(root), based_on_version_id=v2.plan_version_id), v1.plan_id)
    new = root.plans.confirm_draft(ConfirmPlanDraftCommand("plan:continue:confirm", continuation.draft_id, 1, "activate"))
    assert new.plan_id != v1.plan_id and new.version_no == 1
    root.close()


@pytest.mark.parametrize("mutation,code", [
    ({"max_planned_loss": "10000.01"}, "PLAN_RISK_LIMIT_INVALID"),
    ({"max_planned_notional": "-1"}, "PLAN_AMOUNT_INVALID"),
    ({"currency": "USD"}, "PLAN_CURRENCY_INVALID"),
    ({"review_by": "2027-01-01"}, "PLAN_HORIZON_INVALID"),
])
def test_confirmation_contract_rejects_invalid_risk_and_time(tmp_path: Path, mutation: dict[str, str], code: str) -> None:
    root = _root(tmp_path)
    with pytest.raises(PlanError, match=code):
        _create(root, "invalid:" + code, replace(_content(root), **mutation))
    root.close()


def test_typed_ast_references_account_applicability_and_adjusted_evidence(tmp_path: Path) -> None:
    root = _root(tmp_path)
    composite = PlanCondition("all", children=(_leaf(), PlanCondition("not", children=(PlanCondition("leaf", "market.trend", "eq", PlanConstant("enum", "down", "market_trend"), "current_complete_session"),))))
    valid_draft = _create(root, "ast:valid", replace(_content(root), rules=(PlanRule("composite", "market_gate", "block_user_intent", "entry", composite),)))
    assert valid_draft.revision == 1
    root.plans.discard_draft(
        DiscardPlanDraftCommand("ast:discard", valid_draft.draft_id, 1)
    )
    with pytest.raises(PlanError, match="PLAN_RESEARCH_REFERENCE_INVALID"):
        _create(root, "refs:bad", replace(_content(root), references=(PlanReference("ResearchRun", "missing"), PlanReference("Evidence", "e", "unresolved_external"))))
    bad_enum_operator = PlanRule("bad-enum", "market_gate", "observe", "plan", PlanCondition("leaf", "market.trend", "lt", PlanConstant("enum", "down", "market_trend"), "current_complete_session"))
    with pytest.raises(PlanError, match="PLAN_OPERATOR_INVALID"):
        _create(root, "ast:bad-operator", replace(_content(root), rules=(bad_enum_operator,)))
    account_rule = PlanRule("position", "risk_limit", "mark_risk_limit_breach", "plan", PlanCondition("leaf", "position.quantity", "gte", PlanConstant("decimal", "1", "share"), "current_complete_session"))
    with pytest.raises(PlanError, match="PLAN_ACCOUNT_INPUT_APPLICABILITY_REQUIRED"):
        _create(root, "account:bad", replace(_content(root), rules=(account_rule,)))
    accepted_account = replace(account_rule, input_applicability="not_applicable")
    draft = _create(root, "account:ok", replace(_content(root), rules=(accepted_account,)))
    assert draft.content.rules[0].input_applicability == "not_applicable"
    root.plans.discard_draft(DiscardPlanDraftCommand("account:discard", draft.draft_id, 1))
    adjusted_rule = PlanRule("adjusted", "entry_review", "prompt_review", "entry", _leaf("security.close_adjusted"))
    evidence = AdjustedPriceEvidence("adjusted", (), "snapshot_chart", "factor_set_fixture", "80.00", "82.00", "1.025", "deterministic_reverse@1")
    adjusted_draft = _create(root, "adjusted:ok", replace(_content(root), rules=(adjusted_rule,), adjusted_price_evidence=(evidence,)))
    assert adjusted_draft.revision == 1
    root.plans.discard_draft(DiscardPlanDraftCommand("adjusted:discard", adjusted_draft.draft_id, 1))
    two_adjusted = PlanCondition("all", children=(_leaf("security.close_adjusted", "80.00"), _leaf("security.close_adjusted", "75.00")))
    two_rule = replace(adjusted_rule, condition=two_adjusted)
    evidence_two = (
        replace(evidence, condition_path=(0,)),
        replace(evidence, condition_path=(1,), adjusted_price_decimal="75.00", canonical_unadjusted_price_decimal="76.875"),
    )
    multi = _create(root, "adjusted:multi", replace(_content(root), rules=(two_rule,), adjusted_price_evidence=evidence_two))
    assert len(multi.content.adjusted_price_evidence) == 2
    root.plans.discard_draft(DiscardPlanDraftCommand("adjusted:multi:discard", multi.draft_id, 1))
    with pytest.raises(PlanError, match="PLAN_ADJUSTED_PRICE_EVIDENCE_INVALID"):
        _create(root, "adjusted:wrong", replace(_content(root), rules=(adjusted_rule,), adjusted_price_evidence=(replace(evidence, rule_id="other"),)))
    with pytest.raises(PlanError, match="PLAN_ADJUSTED_PRICE_EVIDENCE_INVALID"):
        _create(root, "adjusted:factor-missing", replace(_content(root), rules=(adjusted_rule,), adjusted_price_evidence=(replace(evidence, factor_set_id="missing"),)))
    adapter = SQLiteOwningAdapterFixture(root.data_root)
    with adapter.transaction():
        adapter.execute("INSERT INTO price_factor_set VALUES(?,?,?,?,?)", ("wrong_algorithm", "snapshot_chart", "fixture:factor", "unique_deterministic", "other@1"))
    adapter.close()
    with pytest.raises(PlanError, match="PLAN_ADJUSTED_PRICE_EVIDENCE_INVALID"):
        _create(root, "adjusted:factor-algorithm", replace(_content(root), rules=(adjusted_rule,), adjusted_price_evidence=(replace(evidence, factor_set_id="wrong_algorithm"),)))
    root.close()
