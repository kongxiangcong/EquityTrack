from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from urllib.request import urlopen

from trading_platform.application.market_contracts import EvaluatePlanCommand
from trading_platform.application import (
    ConfirmAccountSnapshot,
    open_account_snapshot_commands,
)
from trading_platform.domain.account_snapshots import AccountSnapshotVersion
from trading_platform.web_server import LocalChartWorkspaceServer
from trading_platform.domain.market import evaluate_rules
from trading_platform.domain.plans import (
    ConfirmPlanDraftCommand,
    PlanCondition,
    PlanConstant,
    PlanRule,
)
from tests.platform.test_account_opening import _sources
from tests.platform.test_trade_plans import _content, _create, _root
from tests.platform.test_market_evaluation import _market_command, _root as market_root
from tests.platform.test_account_history_import import _history_sources


def _confirm_snapshot(data_root: Path, opening) -> AccountSnapshotVersion:
    with open_account_snapshot_commands(data_root) as commands:
        confirmed = commands.execute(
            ConfirmAccountSnapshot(
                invocation_id=f"{opening.account_snapshot_draft_id}:confirm",
                draft_id=opening.account_snapshot_draft_id,
                expected_revision=1,
                decision_actor_type="user",
                decision_actor_id="local-user",
                interaction_channel="cli",
                transport_actor_type="user",
                transport_actor_id="local-user",
            )
        )
    assert isinstance(confirmed, AccountSnapshotVersion)
    return confirmed


def test_workspace_distinguishes_position_and_plan_freezes_account_snapshot(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path / "data")
    sources = _sources(tmp_path / "sources")
    opening = root.accounts.initialize(
        "account:workspace",
        sources,
        "local-account",
        "CNY",
        "2026-07-10",
        tmp_path / "private",
        ("2026-07-10",),
    )
    confirmed = _confirm_snapshot(tmp_path / "data", opening)
    detail = root.accounts.get_detail(opening.account_id)
    security_id = detail.draft.positions[0].security_id
    workspace = root.workspace.build(security_id, "snapshot_chart")
    assert workspace["security_relationship"] == "position"
    position = workspace["current_positions"][0]
    assert {
        "account_label",
        "derived_from_snapshot_as_of",
        "total_quantity",
        "available_quantity_state",
        "available_quantity_value",
        "cost_state",
        "cost_value",
        "freshness",
    } <= position.keys()
    assert "account_id" not in position and "source_row_identity" not in position
    assert (
        root.workspace.build("security_yihua", "snapshot_chart")[
            "security_relationship"
        ]
        == "watchlist_not_held"
    )

    account_rule = PlanRule(
        "position-context",
        "risk_limit",
        "mark_risk_limit_breach",
        "plan",
        PlanCondition(
            "leaf",
            "position.quantity",
            "gte",
            PlanConstant("decimal", "0", "share"),
            "current_complete_session",
        ),
        "applicable",
    )
    content = replace(
        _content(root),
        rules=(account_rule,),
        account_snapshot_id=confirmed.account_snapshot_version_id,
    )
    draft = _create(root, "account-plan:draft", content)
    confirmation = root.plans.confirmation(draft.draft_id)
    assert (
        dict(confirmation.sections[0].fields)["account_snapshot_id"]
        == confirmed.account_snapshot_version_id
    )
    version = root.plans.confirm_draft(
        ConfirmPlanDraftCommand("account-plan:confirm", draft.draft_id, 1, "activate")
    )
    stored_version = root.plans.get_version(version.plan_version_id)
    assert (
        stored_version.content.account_snapshot_id
        == confirmed.account_snapshot_version_id
    )
    assert stored_version.content_hash == version.content_hash
    before = root.accounts.get_detail(opening.account_id)
    evaluation_root, _ = market_root(tmp_path / "evaluation")
    market = evaluation_root.market.build_market_snapshot(_market_command())
    _, _, _, results = evaluate_rules(content, market, {"position_quantity": "0"})
    assert dict(results[0].operands)["actual"] == "0"
    evaluation_root.close()
    after = root.accounts.get_detail(opening.account_id)
    assert after == before
    imported = root.account_history.import_history(
        "account:incremental",
        opening.account_id,
        _history_sources(tmp_path / "history"),
        tmp_path / "private-history",
        ("2026-07-10",),
    )
    assert imported.account_history_snapshot_id is not None
    suite_artifacts = tuple(
        tmp_path / f"{name}.json"
        for name in (
            "account-import",
            "workspace-browser",
            "backup-restore",
            "full-regression",
        )
    )
    for artifact in suite_artifacts:
        artifact.write_text('{"status":"passed"}', encoding="utf-8")
    manifest_path = root.account_acceptance.write_manifest(
        opening.account_id, suite_artifacts
    )
    acceptance = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert acceptance["checks"] == {
        "current_state_initialized": True,
        "cash_reconciled": True,
        "positions_reconciled": True,
        "history_complete": False,
    }
    assert acceptance["current_slice_complete"] is True
    assert acceptance["long_term_platform_complete"] is False
    assert (
        root.plans.get_version(version.plan_version_id).content.account_snapshot_id
        == confirmed.account_snapshot_version_id
    )
    server = LocalChartWorkspaceServer(
        decision_workspace=root.workspace,
        chart_workspace=root.chart,
        chart_annotations=root.chart,
        trade_plan=root.plans,
        update_authorizations=root.workspace,
        web_root=Path.cwd() / "web/dist",
        security_id=security_id,
        snapshot_id="snapshot_chart",
    )
    base = server.start()
    browser_model = json.loads(urlopen(base + "/api/workspace").read())
    assert browser_model["security_relationship"] == "position"
    assert (
        browser_model["history"]["account_imports"][-1]["account_history_snapshot_id"]
        == imported.account_history_snapshot_id
    )
    assert "source_object_sha256" not in json.dumps(browser_model)
    server.close()
    root.close()


def test_watchlist_without_position_is_not_reported_as_missing_data(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path / "data")
    workspace = root.workspace.build("security_yihua", "snapshot_chart")
    assert workspace["security_relationship"] == "account_data_missing"
    assert workspace["current_positions"] == []
    root.faults.record_incomplete_account()
    assert (
        root.workspace.build("security_yihua", "snapshot_chart")[
            "security_relationship"
        ]
        == "position_data_missing"
    )
    root.close()


def test_incremental_snapshot_creates_parallel_evaluation_without_rewriting_history(
    tmp_path: Path,
) -> None:
    root, v1 = market_root(tmp_path / "data")
    market = root.market.build_market_snapshot(_market_command())
    old_evaluation = root.market.evaluate_plan(
        EvaluatePlanCommand(
            "evaluation:old-account-context",
            v1.plan_version_id,
            market.market_snapshot_id,
            "plan-evaluator@1",
            "evaluation-policy@1",
        )
    )
    sources = _sources(tmp_path / "sources")
    opening = root.accounts.initialize(
        "parallel:opening",
        sources,
        "local-account",
        "CNY",
        "2026-07-10",
        tmp_path / "private-opening",
        ("2026-07-10",),
    )
    confirmed = _confirm_snapshot(tmp_path / "data", opening)
    imported = root.account_history.import_history(
        "parallel:history",
        opening.account_id,
        _history_sources(tmp_path / "history"),
        tmp_path / "private-history",
        ("2026-07-10",),
    )
    account_rule = PlanRule(
        "position-context",
        "risk_limit",
        "mark_risk_limit_breach",
        "plan",
        PlanCondition(
            "leaf",
            "position.quantity",
            "gte",
            PlanConstant("decimal", "0", "share"),
            "current_complete_session",
        ),
        "applicable",
    )
    content = replace(
        v1.content,
        based_on_version_id=v1.plan_version_id,
        account_snapshot_id=confirmed.account_snapshot_version_id,
        rules=(account_rule,),
    )
    draft = _create(root, "parallel:draft", content, v1.plan_id)
    v2 = root.plans.confirm_draft(
        ConfirmPlanDraftCommand("parallel:confirm", draft.draft_id, 1, "activate")
    )
    new_evaluation = root.market.evaluate_plan(
        EvaluatePlanCommand(
            "evaluation:new-account-context",
            v2.plan_version_id,
            market.market_snapshot_id,
            "plan-evaluator@1",
            "evaluation-policy@1",
        )
    )
    assert old_evaluation.plan_evaluation_id != new_evaluation.plan_evaluation_id
    assert (
        root.plans.get_version(v1.plan_version_id).content.account_snapshot_id is None
    )
    assert (
        root.plans.get_version(v2.plan_version_id).content.account_snapshot_id
        == confirmed.account_snapshot_version_id
    )
    assert (
        root.market.get_plan_evaluation(old_evaluation.plan_evaluation_id)
        == old_evaluation
    )
    assert (
        root.market.get_plan_evaluation(new_evaluation.plan_evaluation_id)
        == new_evaluation
    )
    root.close()
