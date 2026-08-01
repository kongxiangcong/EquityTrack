from __future__ import annotations

import json
import shutil
from pathlib import Path

from tests.platform.test_account_snapshots import _draft as _account_draft
from trading_platform.application import (
    ConfirmAccountSnapshot,
    CreateAccountSnapshotDraft,
    GetManualPortfolioReview,
    open_account_snapshot_commands,
    open_manual_portfolio_review,
)
from trading_platform.domain.account_snapshots import AccountSnapshotVersion
from trading_platform.persistence import PlatformStore


ROOT = Path(__file__).resolve().parents[2]


def _copy_migrations(tmp_path: Path, through: int) -> Path:
    target = tmp_path / f"migrations-{through}"
    target.mkdir()
    for source in sorted((ROOT / "migrations").glob("*.sql"))[:through]:
        shutil.copy2(source, target / source.name)
    return target


def _legacy_snapshot(data_root: Path, migrations_root: Path) -> str:
    with open_account_snapshot_commands(
        data_root, migrations_root
    ) as commands:
        draft = commands.execute(
            CreateAccountSnapshotDraft(
                invocation_id="migration-0022:snapshot:create",
                draft=_account_draft(),
                decision_actor_type="agent",
                decision_actor_id="codex",
                interaction_channel="skill",
                transport_actor_type="agent",
                transport_actor_id="codex",
            )
        )
        confirmed = commands.execute(
            ConfirmAccountSnapshot(
                invocation_id="migration-0022:snapshot:confirm",
                draft_id=draft.draft_id,
                expected_revision=draft.revision,
                decision_actor_type="user",
                decision_actor_id="local-user",
                interaction_channel="skill",
                transport_actor_type="agent",
                transport_actor_id="codex",
            )
        )
    assert isinstance(confirmed, AccountSnapshotVersion)
    return confirmed.account_snapshot_version_id


def _populated_v21_root(tmp_path: Path) -> tuple[Path, str]:
    migrations_root = _copy_migrations(tmp_path, 21)
    data_root = tmp_path / "manual-review-v21"
    store = PlatformStore(data_root, migrations_root)
    store.migrate()
    store.connection.execute(
        "INSERT INTO account VALUES(?,?,?,?,?)",
        (
            "account_local",
            "local",
            "CNY",
            "2026-07-27T00:00:00+00:00",
            "migration-0022-fixture",
        ),
    )
    store.connection.execute(
        "INSERT INTO security VALUES(?,?)",
        ("security_600000", "CNY"),
    )
    store.connection.commit()
    store.close()
    snapshot_id = _legacy_snapshot(data_root, migrations_root)

    store = PlatformStore(data_root, migrations_root)
    connection = store.connection
    connection.execute(
        "INSERT INTO query_policy_record VALUES(?,?,?,?,?)",
        (
            "query_policy_migration_0022@1",
            "QueryPolicy@1",
            "query-policy-migration-0022",
            "{}",
            "2026-07-27T15:00:00+08:00",
        ),
    )
    connection.execute(
        "INSERT INTO source_policy_record VALUES(?,?,?,?,?)",
        (
            "source_policy_migration_0022@1",
            "SourcePolicy@1",
            "source-policy-migration-0022",
            "{}",
            "2026-07-27T15:00:00+08:00",
        ),
    )
    connection.execute(
        "INSERT INTO data_snapshot VALUES("
        + ",".join("?" for _ in range(21))
        + ")",
        (
            "data_snapshot_migration_0022",
            "security_600000",
            "research",
            "2026-07-27",
            "2026-07-27",
            "2026-07-27T15:00:00+08:00",
            "Asia/Shanghai",
            "calendar_migration_0022@1",
            "query_policy_migration_0022@1",
            "source_policy_migration_0022@1",
            "freshness_migration_0022@1",
            "membership-migration-0022",
            "valid",
            "pass",
            1,
            1,
            0,
            0,
            0,
            "effective_complete_session",
            "2026-07-27T15:00:00+08:00",
        ),
    )
    connection.execute(
        "INSERT INTO market_universe_version VALUES(?,?,?,?,?)",
        (
            "market_universe_migration_0022",
            "CN_A_SHARE",
            "2026-07-27T15:00:00+08:00",
            "source_policy_migration_0022@1",
            "market-universe-membership-migration-0022",
        ),
    )
    connection.execute(
        "INSERT INTO market_universe_member VALUES(?,?,?,?,?,?,?)",
        (
            "market_universe_migration_0022",
            "security_600000",
            "1999-11-10",
            None,
            None,
            None,
            "migration-0022-fixture",
        ),
    )
    connection.execute(
        "INSERT INTO data_snapshot_universe_ref VALUES(?,?,?)",
        (
            "data_snapshot_migration_0022",
            "market_universe_migration_0022",
            "CN_A_SHARE",
        ),
    )
    connection.execute(
        "INSERT INTO workflow_run VALUES("
        + ",".join("?" for _ in range(15))
        + ")",
        (
            "workflow_manual_review_legacy",
            "manual-review:migration-0022",
            "manual_portfolio_review",
            "1",
            "legacy-workflow-fingerprint",
            "2026-07-27",
            "2026-07-27",
            "succeeded_with_limits",
            "2026-07-27T16:00:00+08:00",
            "2026-07-27T16:00:00+08:00",
            None,
            None,
            None,
            "legacy-manual-review-definition",
            0,
        ),
    )
    connection.execute(
        "INSERT INTO trade_plan_master("
        "plan_id,account_id,security_id,strategy_version_id,"
        "lifecycle_status,transition_seq,created_at,legacy_read_only"
        ") VALUES(?,?,?,?,?,?,?,?)",
        (
            "plan_legacy_migration_0022",
            "account_local",
            "security_600000",
            None,
            "legacy_read_only",
            0,
            "2026-07-27T15:00:00+08:00",
            1,
        ),
    )
    connection.execute(
        "INSERT INTO trade_plan_version("
        "plan_version_id,plan_id,version_no,supersedes_version_id,"
        "strategy_version_id,investment_thesis_version_id,"
        "account_snapshot_version_id,data_snapshot_id,horizon_start,"
        "horizon_end,review_by,risk_policy_version_id,"
        "metric_catalog_version,evaluator_policy_version,"
        "conflict_policy_version,ast_version,content_json,content_hash,"
        "graph_seal_hash,graph_sealed,confirmed_at,"
        "user_approval_receipt_id,legacy_read_only"
        ") VALUES(" + ",".join("?" for _ in range(23)) + ")",
        (
            "plan_version_legacy_migration_0022",
            "plan_legacy_migration_0022",
            1,
            None,
            None,
            None,
            snapshot_id,
            "data_snapshot_migration_0022",
            "2026-07-27",
            "2026-12-31",
            "2026-08-31",
            None,
            "metric-catalog-legacy",
            "plan-evaluator-legacy",
            "trade-plan-conflict-legacy",
            "plan-rule-ast-legacy",
            "{}",
            "plan-content-migration-0022",
            "plan-graph-migration-0022",
            1,
            "2026-07-27T15:00:00+08:00",
            None,
            1,
        ),
    )
    connection.execute(
        "INSERT INTO object_blob VALUES(?,?,?)",
        (
            "manual-review-object-migration-0022",
            0,
            "objects/manual-review-migration-0022.json",
        ),
    )
    connection.execute(
        "INSERT INTO manual_portfolio_review_run VALUES("
        + ",".join("?" for _ in range(15))
        + ")",
        (
            "manual_review_legacy_migration_0022",
            "workflow_manual_review_legacy",
            "manual-review:migration-0022",
            "account_local",
            "2026-07-27T16:00:00+08:00",
            "2026-07-27",
            "Asia/Shanghai",
            "2026-07-24",
            "2026-07-27",
            None,
            "succeeded_with_limits",
            "legacy-review-fingerprint",
            "2026-07-27T16:00:00+08:00",
            "2026-07-27T16:00:00+08:00",
            "ManualPortfolioReviewRun@1",
        ),
    )
    connection.execute(
        "INSERT INTO manual_portfolio_review_item VALUES("
        + ",".join("?" for _ in range(31))
        + ")",
        (
            "review_item_legacy_migration_0022",
            "manual_review_legacy_migration_0022",
            "account_local",
            "security_600000",
            "legacy-position-identity",
            snapshot_id,
            "legacy-account-snapshot-hash",
            "legacy-estimated-state-hash",
            None,
            None,
            None,
            None,
            None,
            "[]",
            '["data_snapshot_migration_0022"]',
            "[]",
            "[]",
            "[]",
            "[]",
            "[]",
            "{}",
            "REVIEW_REQUIRED",
            "[]",
            '["ACTIVE_PLAN_MISSING"]',
            "[]",
            '["decision_task_legacy_migration_0022"]',
            '["plan_impact_legacy_migration_0022"]',
            "[]",
            "legacy-review-item-hash",
            "2026-07-27T16:00:00+08:00",
            "SecurityReviewItem@1",
        ),
    )
    connection.execute(
        "INSERT INTO manual_portfolio_review_manifest VALUES("
        + ",".join("?" for _ in range(25))
        + ")",
        (
            "manual_review_manifest_legacy_migration_0022",
            "manual_review_legacy_migration_0022",
            "manual-review-object-migration-0022",
            None,
            "2026-07-24..2026-07-27",
            "calendar_migration_0022@1",
            '["query_policy_migration_0022@1",'
            '"source_policy_migration_0022@1"]',
            snapshot_id,
            "legacy-estimated-state-hash",
            "[]",
            '["data_snapshot_migration_0022"]',
            "[]",
            "[]",
            "[]",
            '["plan-rule-ast@2","plan-evaluator@2",'
            '"trade-plan-conflict@1"]',
            '["review_item_legacy_migration_0022"]',
            '["review_checkpoint_legacy_migration_0022"]',
            '["decision_task_legacy_migration_0022"]',
            '["plan_impact_legacy_migration_0022"]',
            "[]",
            "code:legacy",
            "config:legacy",
            "legacy-manifest-hash",
            "2026-07-27T16:00:00+08:00",
            "ManualPortfolioReviewManifest@1",
        ),
    )
    connection.execute(
        "INSERT INTO manual_portfolio_review_checkpoint VALUES("
        + ",".join("?" for _ in range(10))
        + ")",
        (
            "review_checkpoint_legacy_migration_0022",
            "manual_review_legacy_migration_0022",
            "security_600000",
            "review_item",
            "legacy-review-item-hash",
            "committed",
            "manual_review_manifest_legacy_migration_0022",
            1,
            "2026-07-27T16:00:00+08:00",
            "ReviewCheckpoint@1",
        ),
    )
    connection.execute(
        "INSERT INTO decision_task VALUES("
        + ",".join("?" for _ in range(16))
        + ")",
        (
            "decision_task_legacy_migration_0022",
            "account_local",
            "security_600000",
            "manual_review_legacy_migration_0022",
            "review_item_legacy_migration_0022",
            None,
            None,
            "review",
            "ACTIVE_PLAN_MISSING",
            "normal",
            "open",
            "legacy-condition-migration-0022",
            "manual_review_manifest_legacy_migration_0022",
            "2026-07-27T16:00:00+08:00",
            "legacy-decision-task-hash",
            "DecisionTask@1",
        ),
    )
    connection.execute(
        "INSERT INTO discipline_review_version("
        "discipline_review_id,version_no,supersedes_version_no,"
        "account_id,period_kind,period_start_session,period_end_session,"
        "timezone,status,review_run_ids_json,decision_task_ids_json,"
        "action_log_entry_ids_json,execution_record_ids_json,"
        "plan_version_ids_json,account_snapshot_version_ids_json,"
        "exceptions_json,overridden_items_json,unrecorded_items_json,"
        "unverified_items_json,drift_assessment_ids_json,"
        "evidence_gap_summary_json,content_hash,created_at,"
        "draft_invocation_id,confirmed_at,"
        "confirmation_command_receipt_id,schema_version"
        ") VALUES(" + ",".join("?" for _ in range(27)) + ")",
        (
            "discipline_review_legacy_migration_0022",
            1,
            None,
            "account_local",
            "weekly",
            "2026-07-21",
            "2026-07-27",
            "Asia/Shanghai",
            "draft",
            '["manual_review_legacy_migration_0022"]',
            '["decision_task_legacy_migration_0022"]',
            "[]",
            "[]",
            '["plan_version_legacy_migration_0022"]',
            json.dumps([snapshot_id]),
            "[]",
            "[]",
            "[]",
            "[]",
            "[]",
            "{}",
            "legacy-discipline-hash",
            "2026-07-27T16:30:00+08:00",
            "discipline:migration-0022",
            None,
            None,
            "DisciplineReviewVersion@1",
        ),
    )
    connection.execute(
        "INSERT INTO plan_impact_assessment("
        "assessment_id,invocation_id,request_hash,review_run_id,"
        "review_item_id,plan_version_id,review_rule_id,"
        "review_rule_result,evidence_manifest_id,research_refs_json,"
        "market_refs_json,industry_refs_json,sector_refs_json,"
        "unable_reasons_json,authority_content_hash,impact_kind,"
        "materiality,uncertainties_json,what_changed,"
        "what_would_change_the_view,finding_schema_version,"
        "model_identity,policy_identity,prompt_identity,content_hash,"
        "created_by,created_at,schema_version"
        ") VALUES(" + ",".join("?" for _ in range(28)) + ")",
        (
            "plan_impact_legacy_migration_0022",
            "plan-impact:migration-0022",
            "legacy-plan-impact-request",
            "manual_review_legacy_migration_0022",
            "review_item_legacy_migration_0022",
            "plan_version_legacy_migration_0022",
            "review_rule_legacy_migration_0022",
            "unable_to_determine",
            "manual_review_manifest_legacy_migration_0022",
            "[]",
            "[]",
            "[]",
            "[]",
            '["LEGACY_FIXTURE"]',
            "legacy-authority-hash",
            "monitor",
            "unknown",
            "[]",
            "legacy migration fixture",
            "new evidence",
            "PlanImpactFinding@1",
            "model:legacy",
            "policy:legacy",
            "prompt:legacy",
            "legacy-plan-impact-hash",
            "agent",
            "2026-07-27T16:15:00+08:00",
            "PlanImpactAssessment@1",
        ),
    )
    connection.commit()
    store.close()
    return data_root, snapshot_id


def test_0022_rewrites_populated_manual_review_without_fk_breakage(
    tmp_path: Path,
) -> None:
    data_root, _ = _populated_v21_root(tmp_path)
    upgraded = PlatformStore(data_root, ROOT / "migrations")
    upgraded.migrate()
    upgraded.migrate()
    item = upgraded.connection.execute(
        "SELECT universe_member_identity,universe_roles_json,"
        "schema_version,content_hash "
        "FROM manual_portfolio_review_item"
    ).fetchone()
    assert tuple(item)[:3] == (
        "legacy-position-identity",
        '["holding"]',
        "SecurityReviewItem@2",
    )
    assert item["content_hash"] != "legacy-review-item-hash"
    checkpoint = upgraded.connection.execute(
        "SELECT input_fingerprint FROM manual_portfolio_review_checkpoint"
    ).fetchone()
    assert checkpoint["input_fingerprint"] == item["content_hash"]
    run_contract = upgraded.connection.execute(
        "SELECT session_selection,schema_version "
        "FROM manual_portfolio_review_run"
    ).fetchone()
    assert tuple(run_contract) == (
        "latest_proven_complete_session",
        "ManualPortfolioReviewRun@2",
    )
    columns = {
        row["name"]
        for row in upgraded.connection.execute(
            "PRAGMA table_info(manual_portfolio_review_item)"
        )
    }
    assert "position_identity" not in columns
    assert "review_item_contract_version" not in columns
    assert {
        "universe_member_identity",
        "universe_roles_json",
        "schema_version",
    } <= columns
    assert upgraded.connection.execute(
        "SELECT count(*) FROM decision_task"
    ).fetchone()[0] == 1
    assert upgraded.connection.execute(
        "SELECT count(*) FROM discipline_review_version"
    ).fetchone()[0] == 1
    assert upgraded.connection.execute(
        "SELECT count(*) FROM plan_impact_assessment"
    ).fetchone()[0] == 1
    assert upgraded.connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []
    upgraded.close()

    with open_manual_portfolio_review(data_root) as review:
        restarted = review.get(
            GetManualPortfolioReview(
                "manual_review_legacy_migration_0022"
            )
        )
    assert restarted.schema_version == "ManualPortfolioReviewRun@2"
    assert (
        restarted.session_selection
        == "latest_proven_complete_session"
    )
    assert restarted.selected_complete_session == "2026-07-27"
