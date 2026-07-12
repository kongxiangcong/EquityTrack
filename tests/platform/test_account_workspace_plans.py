from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from urllib.request import urlopen

from trading_platform.account import AccountOpeningService
from trading_platform.account_history import AccountHistoryImportService
from trading_platform.account_acceptance import AccountAcceptanceService
from trading_platform.application.market_contracts import EvaluatePlanCommand
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


def test_workspace_distinguishes_position_and_plan_freezes_account_snapshot(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path / "data")
    sources = _sources(tmp_path / "sources")
    opening = AccountOpeningService(tmp_path / "data", Path.cwd()).initialize(
        "account:workspace",
        sources,
        "local-account",
        "CNY",
        "2026-07-10",
        tmp_path / "private",
        ("2026-07-10",),
    )
    detail = AccountOpeningService(tmp_path / "data", Path.cwd()).get_detail(
        opening.account_id
    )
    security_id = detail.positions[0].security_id
    workspace = root.facade.get_workspace(security_id, "snapshot_chart")
    assert workspace["security_relationship"] == "position"
    position = workspace["current_positions"][0]
    assert {
        "account_label",
        "snapshot_as_of",
        "quantity_decimal",
        "available_decimal",
        "frozen_decimal",
        "cost_price_decimal",
        "cash_decimal",
        "freshness",
    } <= position.keys()
    assert "account_id" not in position and "source_row_identity" not in position
    assert (
        root.facade.get_workspace("security_yihua", "snapshot_chart")[
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
        account_snapshot_id=opening.portfolio_snapshot_id,
    )
    draft = _create(root, "account-plan:draft", content)
    confirmation = root.facade.get_plan_confirmation(draft.draft_id)
    assert (
        dict(confirmation.sections[0].fields)["account_snapshot_id"]
        == opening.portfolio_snapshot_id
    )
    version = root.facade.confirm_plan_draft(
        ConfirmPlanDraftCommand("account-plan:confirm", draft.draft_id, 1, "activate")
    )
    frozen = root._store.connection.execute(
        "SELECT snapshot_id,context_json,context_hash FROM plan_account_snapshot_reference WHERE plan_version_id=?",
        (version.plan_version_id,),
    ).fetchone()
    assert (
        frozen[0] == opening.portfolio_snapshot_id
        and '"position_quantity":"0"' in frozen[1]
    )
    assert (
        root.facade.get_plan_version(version.plan_version_id).content_hash
        == version.content_hash
    )
    tables = ("account", "account_position", "account_transaction", "cash_ledger_entry")
    before = tuple(
        root._store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in tables
    )
    evaluation_root, _ = market_root(tmp_path / "evaluation")
    market = evaluation_root.facade.build_market_snapshot(_market_command())
    _, _, _, results = evaluate_rules(content, market, {"position_quantity": "0"})
    assert dict(results[0].operands)["actual"] == "0"
    evaluation_root.close()
    after = tuple(
        root._store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in tables
    )
    assert after == before
    imported = AccountHistoryImportService(
        tmp_path / "data", Path.cwd()
    ).import_history(
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
    manifest_path = AccountAcceptanceService(
        tmp_path / "data", Path.cwd() / "migrations"
    ).write_manifest(opening.account_id, suite_artifacts)
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
        root._store.connection.execute(
            "SELECT snapshot_id FROM plan_account_snapshot_reference WHERE plan_version_id=?",
            (version.plan_version_id,),
        ).fetchone()[0]
        == opening.portfolio_snapshot_id
    )
    server = LocalChartWorkspaceServer(
        root.facade, Path.cwd() / "web/dist", security_id, "snapshot_chart"
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
    workspace = root.facade.get_workspace("security_yihua", "snapshot_chart")
    assert workspace["security_relationship"] == "account_data_missing"
    assert workspace["current_positions"] == []
    with root._store.connection:
        root._store.connection.execute(
            "INSERT INTO account VALUES('incomplete-account','local','CNY','2026-07-10','incomplete-source')"
        )
    assert (
        root.facade.get_workspace("security_yihua", "snapshot_chart")[
            "security_relationship"
        ]
        == "position_data_missing"
    )
    root.close()


def test_incremental_snapshot_creates_parallel_evaluation_without_rewriting_history(
    tmp_path: Path,
) -> None:
    root, v1 = market_root(tmp_path / "data")
    market = root.facade.build_market_snapshot(_market_command())
    old_evaluation = root.facade.evaluate_plan(
        EvaluatePlanCommand(
            "evaluation:old-account-context",
            v1.plan_version_id,
            market.market_snapshot_id,
            "plan-evaluator@1",
            "evaluation-policy@1",
        )
    )
    sources = _sources(tmp_path / "sources")
    opening = AccountOpeningService(tmp_path / "data", Path.cwd()).initialize(
        "parallel:opening",
        sources,
        "local-account",
        "CNY",
        "2026-07-10",
        tmp_path / "private-opening",
        ("2026-07-10",),
    )
    imported = AccountHistoryImportService(
        tmp_path / "data", Path.cwd()
    ).import_history(
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
        "unknown",
    )
    content = replace(
        v1.content,
        based_on_version_id=v1.plan_version_id,
        account_snapshot_id=imported.account_history_snapshot_id,
        rules=(account_rule,),
    )
    draft = _create(root, "parallel:draft", content, v1.plan_id)
    v2 = root.facade.confirm_plan_draft(
        ConfirmPlanDraftCommand("parallel:confirm", draft.draft_id, 1, "activate")
    )
    new_evaluation = root.facade.evaluate_plan(
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
        root.facade.get_plan_version(v1.plan_version_id).content.account_snapshot_id
        is None
    )
    assert (
        root.facade.get_plan_version(v2.plan_version_id).content.account_snapshot_id
        == imported.account_history_snapshot_id
    )
    assert (
        root._store.connection.execute(
            "SELECT count(*) FROM plan_evaluation"
        ).fetchone()[0]
        == 2
    )
    root.close()
