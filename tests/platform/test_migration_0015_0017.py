from __future__ import annotations

import json
import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from trading_platform.persistence import PersistenceError, PlatformStore
from trading_platform.persistence.plans import SQLiteTradePlanRepository


ROOT = Path(__file__).resolve().parents[2]


def _copy_migrations(tmp_path: Path, through: int) -> Path:
    target = tmp_path / f"migrations-{through}"
    target.mkdir()
    for source in sorted((ROOT / "migrations").glob("*.sql"))[:through]:
        shutil.copy2(source, target / source.name)
    return target


def _legacy_root(tmp_path: Path) -> tuple[Path, Path]:
    data_root = tmp_path / "legacy-data"
    old_migrations = _copy_migrations(tmp_path, 14)
    store = PlatformStore(data_root, old_migrations)
    store.migrate()
    connection = store.connection
    connection.execute(
        "INSERT INTO account VALUES(?,?,?,?,?)",
        ("account_legacy", "legacy", "CNY", "2026-07-20T00:00:00+00:00", "source-hash"),
    )
    connection.execute("INSERT INTO security VALUES(?,?)", ("security_legacy", "CNY"))
    evidence = {
        "schema_version": "AccountOpeningEvidence@1",
        "confirmation": {
            "invocation_id": "legacy-confirm",
            "confirmed_at": "2026-07-20T01:00:00+00:00",
            "confirmed_as_of": "2026-07-18",
        },
        "cash_source_row_identity": "cash-row",
        "source_snapshot_hash": "source-hash",
    }
    connection.execute(
        "INSERT INTO account_import_batch VALUES(?,?,?,?,?,?,?)",
        (
            "batch_legacy",
            "account_legacy",
            "legacy-confirm",
            "2026-07-18",
            "source-hash",
            "pass",
            json.dumps(evidence),
        ),
    )
    connection.execute(
        "INSERT INTO account_cash_opening VALUES(?,?,?,?,?,?)",
        ("account_legacy", "25.5", "CNY", "cash-row", "2026-07-18", "2026-07-18"),
    )
    connection.execute(
        "INSERT INTO account_position VALUES(?,?,?,?,?,?,?,?)",
        (
            "position_legacy",
            "account_legacy",
            "security_legacy",
            "legacy security",
            "100",
            "80",
            "20",
            "opening_snapshot",
        ),
    )
    connection.execute(
        "INSERT INTO account_position_lot VALUES(?,?,?,?,?,?,?)",
        (
            "lot_legacy",
            "position_legacy",
            "100",
            "unknown-marker",
            "CNY",
            "opening_snapshot",
            "position-row",
        ),
    )
    connection.execute(
        "INSERT INTO account_position_observation VALUES(?,?,?,?,?,?)",
        ("position_legacy", "10", "1000", "0", "97.51", "2026-07-18"),
    )
    connection.execute(
        "INSERT INTO portfolio_snapshot VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "portfolio_legacy",
            "account_legacy",
            "2026-07-18",
            "25.5",
            "1000",
            "1025.5",
            "reconciled",
            "source-hash",
            "[]",
        ),
    )
    connection.execute(
        "INSERT INTO query_policy_record VALUES(?,?,?,?,?)",
        (
            "query_policy_fixture@1",
            "QueryPolicy@1",
            "query-policy-hash",
            "{}",
            "2026-07-18T15:00:00+08:00",
        ),
    )
    connection.execute(
        "INSERT INTO source_policy_record VALUES(?,?,?,?,?)",
        (
            "source_policy_fixture@1",
            "SourcePolicy@1",
            "source-policy-hash",
            "{}",
            "2026-07-18T15:00:00+08:00",
        ),
    )
    connection.execute(
        "INSERT INTO data_snapshot VALUES("
        "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "data_snapshot_legacy",
            "security_legacy",
            "research",
            "2026-07-18",
            "2026-07-18",
            "2026-07-18T15:00:00+08:00",
            "Asia/Shanghai",
            "calendar_fixture@1",
            "query_policy_fixture@1",
            "source_policy_fixture@1",
            "freshness_fixture@1",
            "membership-legacy",
            "valid",
            "pass",
            0,
            0,
            0,
            0,
            0,
            "fixture",
            "2026-07-18T15:00:00+08:00",
        ),
    )
    connection.execute(
        "INSERT INTO trade_plan VALUES(?,?,?,?,?)",
        (
            "plan_legacy",
            "security_legacy",
            "inactive",
            0,
            "2026-07-18T15:00:00+08:00",
        ),
    )
    connection.execute(
        "INSERT INTO trade_plan_version VALUES("
        "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "plan_version_legacy",
            "plan_legacy",
            1,
            None,
            "security_legacy",
            None,
            "data_snapshot_legacy",
            "2026-07-18",
            "2026-08-18",
            "2026-07-25",
            "market-gate@1",
            "metric-catalog@1",
            "evaluator@1",
            "user_fixture_input",
            "{}",
            "plan-content-legacy",
            "2026-07-18T15:00:00+08:00",
            "plan-confirm-legacy",
        ),
    )
    connection.execute(
        "INSERT INTO plan_account_snapshot_reference VALUES(?,?,?,?,?,?,?,?)",
        (
            "plan_version_legacy",
            "PortfolioSnapshot",
            "portfolio_legacy",
            "account_legacy",
            "2026-07-18",
            "reconciled",
            '{"preserved":true}',
            "context-hash-legacy",
        ),
    )
    connection.commit()
    store.close()
    return data_root, old_migrations


def test_fresh_and_populated_roots_upgrade_idempotently(tmp_path: Path) -> None:
    fresh = PlatformStore(tmp_path / "fresh", ROOT / "migrations")
    fresh.migrate()
    fresh.migrate()
    assert fresh.connection.execute(
        "SELECT max(version) FROM schema_migration"
    ).fetchone()[0] == 16
    fresh.close()

    data_root, _ = _legacy_root(tmp_path)
    upgraded = PlatformStore(data_root, ROOT / "migrations")
    upgraded.migrate()
    first = upgraded.connection.execute(
        "SELECT account_snapshot_version_id,graph_seal_hash "
        "FROM account_snapshot_version"
    ).fetchone()
    upgraded.migrate()
    assert upgraded.connection.execute(
        "SELECT account_snapshot_version_id,graph_seal_hash "
        "FROM account_snapshot_version"
    ).fetchone() == first
    upgraded.close()


def test_legacy_account_values_unknowns_and_refs_migrate_losslessly(
    tmp_path: Path,
) -> None:
    data_root, _ = _legacy_root(tmp_path)
    store = PlatformStore(data_root, ROOT / "migrations")
    store.migrate()
    cash = store.connection.execute(
        "SELECT cash_state,cash_value,nav_state,nav_value,fees_state,fees_value "
        "FROM account_snapshot_cash"
    ).fetchone()
    assert tuple(cash) == ("known", "25.5", "unknown", None, "unknown", None)
    position = store.connection.execute(
        "SELECT total_quantity,available_quantity_state,available_quantity_value,"
        "cost_state,cost_value,market_value_state,market_value_value "
        "FROM account_snapshot_position"
    ).fetchone()
    assert tuple(position) == (
        "100",
        "known",
        "80",
        "unknown",
        None,
        "known",
        "1000",
    )
    version = store.connection.execute(
        "SELECT as_of_at,as_of_precision,timezone,session_semantics,source_kind "
        "FROM account_snapshot_version"
    ).fetchone()
    assert tuple(version) == (
        "2026-07-18",
        "date",
        "Asia/Shanghai",
        "legacy_unknown",
        "legacy_broker_opening_import",
    )
    assert store.connection.execute(
        "SELECT source_row_identity,migration_manifest_hash "
        "FROM account_snapshot_migration_provenance"
    ).fetchone() is not None
    reference = store.connection.execute(
        "SELECT snapshot_type,snapshot_id,context_json,context_hash "
        "FROM plan_account_snapshot_reference"
    ).fetchone()
    assert tuple(reference) == (
        "AccountSnapshotVersion",
        store.connection.execute(
            "SELECT account_snapshot_version_id FROM account_snapshot_version"
        ).fetchone()[0],
        '{"preserved":true}',
        "context-hash-legacy",
    )
    store.close()


def test_account_snapshot_preflight_failure_is_a_noop(tmp_path: Path) -> None:
    data_root, _ = _legacy_root(tmp_path)
    connection = sqlite3.connect(data_root / "platform.sqlite3")
    connection.execute(
        "UPDATE account_import_batch SET evidence_json='{}' "
        "WHERE account_id='account_legacy'"
    )
    connection.commit()
    before = tuple(connection.iterdump())
    connection.close()

    store = PlatformStore(data_root, ROOT / "migrations")
    with pytest.raises(PersistenceError) as failure:
        store.migrate()
    assert failure.value.code == "ACCOUNT_SNAPSHOT_HISTORY_UNMIGRATABLE"
    assert store.connection.execute(
        "SELECT max(version) FROM schema_migration"
    ).fetchone()[0] == 14
    assert store.connection.execute(
        "SELECT name FROM sqlite_master WHERE name='account_snapshot_version'"
    ).fetchone() is None
    store.close()
    connection = sqlite3.connect(data_root / "platform.sqlite3")
    after = tuple(connection.iterdump())
    connection.close()
    assert after == before


def test_account_snapshot_migration_rolls_back_and_replays_after_crash(
    tmp_path: Path,
) -> None:
    data_root, _ = _legacy_root(tmp_path)
    store = PlatformStore(data_root, ROOT / "migrations")
    with pytest.raises(PersistenceError) as failure:
        store.migrate(fail_after=5)
    assert failure.value.code == "MIGRATION_INJECTED_FAILURE"
    assert store.connection.execute(
        "SELECT max(version) FROM schema_migration"
    ).fetchone()[0] == 14
    assert store.connection.execute(
        "SELECT name FROM sqlite_master WHERE name='account_snapshot_version'"
    ).fetchone() is None
    store.migrate()
    assert store.connection.execute(
        "SELECT count(*) FROM account_snapshot_version"
    ).fetchone()[0] == 1
    store.close()


def test_strategy_plan_0016_installs_full_cohort_schema_idempotently(
    tmp_path: Path,
) -> None:
    store = PlatformStore(tmp_path / "strategy-fresh", ROOT / "migrations")
    store.migrate()
    store.migrate()
    assert store.connection.execute(
        "SELECT max(version) FROM schema_migration"
    ).fetchone()[0] == 16
    expected_tables = {
        "investment_thesis_version",
        "strategy_definition",
        "strategy_version",
        "strategy_parameter_contract",
        "trade_plan_master",
        "trade_plan_draft",
        "trade_plan_version",
        "trade_plan_sleeve",
        "trade_plan_rule",
        "grid_constraint",
        "plan_confirmation_challenge",
        "user_approval_receipt",
        "plan_activation",
    }
    installed = {
        row[0]
        for row in store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert expected_tables <= installed
    public_versions = tuple(
        row[0]
        for row in store.connection.execute(
            "SELECT strategy_key || '@' || version_no "
            "FROM strategy_version WHERE publicly_selectable=1 "
            "ORDER BY strategy_key"
        )
    )
    assert public_versions == ("core_plus_grid@1", "trend_hold_break_exit@1")
    store.close()


def test_active_legacy_plan_requires_explicit_sleeve_mapping(
    tmp_path: Path,
) -> None:
    data_root, _ = _legacy_root(tmp_path)
    through_15 = _copy_migrations(tmp_path, 15)
    store = PlatformStore(data_root, through_15)
    store.migrate()
    store.connection.execute(
        "UPDATE trade_plan SET lifecycle_status='active' "
        "WHERE plan_id='plan_legacy'"
    )
    store.connection.commit()
    before = tuple(store.connection.iterdump())
    store.close()

    blocked = PlatformStore(data_root, ROOT / "migrations")
    with pytest.raises(PersistenceError) as failure:
        blocked.migrate()
    assert failure.value.code == "STRATEGY_PLAN_HISTORY_UNMIGRATABLE"
    assert blocked.connection.execute(
        "SELECT max(version) FROM schema_migration"
    ).fetchone()[0] == 15
    assert blocked.connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE name='strategy_definition'"
    ).fetchone() is None
    after = tuple(blocked.connection.iterdump())
    blocked.close()
    assert after == before


def test_active_nonrepresentable_ast1_rule_blocks_0016(
    tmp_path: Path,
) -> None:
    data_root, _ = _legacy_root(tmp_path)
    through_15 = _copy_migrations(tmp_path, 15)
    prior = PlatformStore(data_root, through_15)
    prior.migrate()
    prior.connection.execute(
        "UPDATE trade_plan SET lifecycle_status='active' "
        "WHERE plan_id='plan_legacy'"
    )
    prior.connection.execute(
        "INSERT INTO plan_rule VALUES(?,?,?,?,?,?,?)",
        (
            "plan_version_legacy",
            0,
            "rule_unrepresentable",
            "legacy_fixture",
            "record_outcome",
            "plan",
            "applicable",
        ),
    )
    prior.connection.execute(
        "INSERT INTO plan_rule_condition VALUES(?,?,?,?,?)",
        (
            "plan_version_legacy",
            0,
            "plan-rule-ast@1",
            json.dumps(
                {
                    "node_kind": "leaf",
                    "metric_ref": "filesystem.secret",
                    "operator": "eq",
                    "constant": {
                        "constant_type": "enum",
                        "value": "anything",
                    },
                    "applicability": "current_complete_session",
                },
                sort_keys=True,
            ),
            "unrepresentable-condition-hash",
        ),
    )
    prior.connection.commit()
    before = tuple(prior.connection.iterdump())
    prior.close()
    mapping = {
        "schema_version": "LegacySleeveMapping@1",
        "approved_by": "user:synthetic-migration-reviewer",
        "approved_at": "2026-07-27T00:00:00+08:00",
        "plans": [
            {
                "plan_id": "plan_legacy",
                "strategy_version_id": (
                    "strategy_version_trend_hold_break_exit_1"
                ),
                "sleeves": [
                    {
                        "sleeve_id": "legacy_core",
                        "sleeve_kind": "core",
                        "quantity_budget_state": "unknown",
                        "quantity_budget_value": None,
                        "core_floor_state": "known",
                        "core_floor_value": "0",
                        "max_notional_state": "unknown",
                        "max_notional_value": None,
                        "max_loss_state": "unknown",
                        "max_loss_value": None,
                    }
                ],
                "rule_scopes": {
                    "rule_unrepresentable": "legacy_core"
                },
            }
        ],
    }
    mapping_dir = data_root / "migration-inputs"
    mapping_dir.mkdir()
    (mapping_dir / "0016-legacy-sleeve-mapping.json").write_text(
        json.dumps(
            mapping,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    blocked = PlatformStore(data_root, ROOT / "migrations")
    with pytest.raises(PersistenceError) as failure:
        blocked.migrate()
    assert failure.value.code == "STRATEGY_PLAN_HISTORY_UNMIGRATABLE"
    assert tuple(blocked.connection.iterdump()) == before
    blocked.close()


def test_legacy_plan_without_exact_account_owner_blocks_0016(
    tmp_path: Path,
) -> None:
    data_root, _ = _legacy_root(tmp_path)
    through_15 = _copy_migrations(tmp_path, 15)
    prior = PlatformStore(data_root, through_15)
    prior.migrate()
    prior.connection.execute(
        "DELETE FROM plan_account_snapshot_reference "
        "WHERE plan_version_id='plan_version_legacy'"
    )
    prior.connection.commit()
    before = tuple(prior.connection.iterdump())
    prior.close()

    blocked = PlatformStore(data_root, ROOT / "migrations")
    with pytest.raises(PersistenceError) as failure:
        blocked.migrate()
    assert failure.value.code == "STRATEGY_PLAN_HISTORY_UNMIGRATABLE"
    assert tuple(blocked.connection.iterdump()) == before
    blocked.close()


def test_duplicate_active_legacy_ownership_blocks_0016(
    tmp_path: Path,
) -> None:
    data_root, _ = _legacy_root(tmp_path)
    through_15 = _copy_migrations(tmp_path, 15)
    prior = PlatformStore(data_root, through_15)
    prior.migrate()
    prior.connection.execute(
        "UPDATE trade_plan SET lifecycle_status='active' "
        "WHERE plan_id='plan_legacy'"
    )
    prior.connection.execute(
        "INSERT INTO trade_plan SELECT 'plan_legacy_2',security_id,"
        "'active',transition_seq,created_at FROM trade_plan "
        "WHERE plan_id='plan_legacy'"
    )
    prior.connection.execute(
            "INSERT INTO trade_plan_version SELECT 'plan_version_legacy_2',"
            "'plan_legacy_2',version_no,supersedes_version_id,security_id,"
            "based_on_version_id,data_snapshot_id,horizon_start,"
            "horizon_end,review_by,market_gate_policy_version,"
            "metric_catalog_version,evaluator_policy_version,user_input_source,"
            "content_json,'plan-content-legacy-2',confirmed_at,"
        "'plan-confirm-legacy-2' FROM trade_plan_version "
        "WHERE plan_version_id='plan_version_legacy'"
    )
    prior.connection.execute(
        "INSERT INTO plan_account_snapshot_reference SELECT "
        "'plan_version_legacy_2',snapshot_type,snapshot_id,account_id,"
        "snapshot_as_of,reconciliation_status,context_json,"
        "'context-hash-legacy-2' FROM plan_account_snapshot_reference "
        "WHERE plan_version_id='plan_version_legacy'"
    )
    prior.connection.commit()
    before = tuple(prior.connection.iterdump())
    prior.close()

    sleeve = {
        "sleeve_id": "legacy_core",
        "sleeve_kind": "core",
        "quantity_budget_state": "unknown",
        "quantity_budget_value": None,
        "core_floor_state": "known",
        "core_floor_value": "0",
        "max_notional_state": "unknown",
        "max_notional_value": None,
        "max_loss_state": "unknown",
        "max_loss_value": None,
    }
    mapping = {
        "schema_version": "LegacySleeveMapping@1",
        "approved_by": "user:synthetic-migration-reviewer",
        "approved_at": "2026-07-27T00:00:00+08:00",
        "plans": [
            {
                "plan_id": plan_id,
                "strategy_version_id": (
                    "strategy_version_trend_hold_break_exit_1"
                ),
                "sleeves": [sleeve],
                "rule_scopes": {},
            }
            for plan_id in ("plan_legacy", "plan_legacy_2")
        ],
    }
    mapping_dir = data_root / "migration-inputs"
    mapping_dir.mkdir()
    (mapping_dir / "0016-legacy-sleeve-mapping.json").write_text(
        json.dumps(
            mapping,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    blocked = PlatformStore(data_root, ROOT / "migrations")
    with pytest.raises(PersistenceError) as failure:
        blocked.migrate()
    assert failure.value.code == "STRATEGY_PLAN_HISTORY_UNMIGRATABLE"
    assert tuple(blocked.connection.iterdump()) == before
    blocked.close()


def test_inactive_legacy_plan_content_is_byte_preserved_by_0016(
    tmp_path: Path,
) -> None:
    data_root, _ = _legacy_root(tmp_path)
    through_15 = _copy_migrations(tmp_path, 15)
    prior = PlatformStore(data_root, through_15)
    prior.migrate()
    original = '{"说明":"保留空格", "nested":{"value":"001.00"}}'
    prior.connection.execute("DROP TRIGGER trade_plan_version_no_update")
    prior.connection.execute(
        "UPDATE trade_plan_version SET content_json=?,content_hash=? "
        "WHERE plan_version_id='plan_version_legacy'",
        (original, "byte-preserved-content-hash"),
    )
    prior.connection.commit()
    prior.close()

    upgraded = PlatformStore(data_root, ROOT / "migrations")
    upgraded.migrate()
    migrated = upgraded.connection.execute(
        "SELECT content_json,content_hash,legacy_read_only "
        "FROM trade_plan_version "
        "WHERE plan_version_id='plan_version_legacy'"
    ).fetchone()
    assert tuple(migrated) == (
        original,
        "byte-preserved-content-hash",
        1,
    )
    upgraded.close()


def test_explicit_legacy_mapping_preserves_history_and_active_ownership(
    tmp_path: Path,
) -> None:
    data_root, _ = _legacy_root(tmp_path)
    through_15 = _copy_migrations(tmp_path, 15)
    prior = PlatformStore(data_root, through_15)
    prior.migrate()
    prior.connection.execute(
        "UPDATE trade_plan SET lifecycle_status='active' "
        "WHERE plan_id='plan_legacy'"
    )
    prior.connection.execute(
        "INSERT INTO plan_rule VALUES(?,?,?,?,?,?,?)",
        (
            "plan_version_legacy",
            0,
            "rule_representable",
            "price_gate",
            "record_outcome",
            "entry",
            "applicable",
        ),
    )
    prior.connection.execute(
        "INSERT INTO plan_rule_condition VALUES(?,?,?,?,?)",
        (
            "plan_version_legacy",
            0,
            "plan-rule-ast@1",
            json.dumps(
                {
                    "node_kind": "leaf",
                    "metric_ref": "security.close_unadjusted",
                    "operator": "gte",
                    "constant": {
                        "constant_type": "decimal",
                        "value": "10",
                    },
                    "applicability": "current_complete_session",
                },
                sort_keys=True,
            ),
            "representable-condition-hash",
        ),
    )
    original_content = prior.connection.execute(
        "SELECT content_json FROM trade_plan_version "
        "WHERE plan_version_id='plan_version_legacy'"
    ).fetchone()[0]
    prior.connection.commit()
    prior.close()
    mapping = {
        "schema_version": "LegacySleeveMapping@1",
        "approved_by": "user:synthetic-migration-reviewer",
        "approved_at": "2026-07-27T00:00:00+08:00",
        "plans": [
            {
                "plan_id": "plan_legacy",
                "strategy_version_id": (
                    "strategy_version_core_plus_grid_1"
                ),
                "sleeves": [
                    {
                        "sleeve_id": "legacy_core",
                        "sleeve_kind": "core",
                        "quantity_budget_state": "unknown",
                        "quantity_budget_value": None,
                        "core_floor_state": "known",
                        "core_floor_value": "0",
                        "max_notional_state": "unknown",
                        "max_notional_value": None,
                        "max_loss_state": "unknown",
                        "max_loss_value": None,
                    },
                    {
                        "sleeve_id": "legacy_grid",
                        "sleeve_kind": "grid",
                        "quantity_budget_state": "known",
                        "quantity_budget_value": "100",
                        "core_floor_state": "known",
                        "core_floor_value": "0",
                        "max_notional_state": "unknown",
                        "max_notional_value": None,
                        "max_loss_state": "unknown",
                        "max_loss_value": None,
                        "grid_constraint": {
                            "grid_constraint_id": (
                                "grid_constraint_legacy"
                            ),
                            "lower_price": "8",
                            "upper_price": "12",
                            "level_count": 5,
                            "quantity_per_level": "100",
                            "total_quantity_budget": "100",
                            "price_basis": "unadjusted",
                            "trigger_mode": "crosses_level",
                            "cooldown_trading_sessions": 1,
                        },
                    }
                ],
                "rule_scopes": {
                    "rule_representable": "legacy_grid"
                },
            }
        ],
    }
    mapping_path = data_root / "migration-inputs"
    mapping_path.mkdir()
    artifact = mapping_path / "0016-legacy-sleeve-mapping.json"
    artifact.write_text(
        json.dumps(
            mapping,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    upgraded = PlatformStore(data_root, ROOT / "migrations")
    upgraded.migrate()
    assert tuple(
        upgraded.connection.execute(
            "SELECT account_id,security_id,lifecycle_status,legacy_read_only "
            "FROM trade_plan_master WHERE plan_id='plan_legacy'"
        ).fetchone()
    ) == ("account_legacy", "security_legacy", "active", 0)
    assert upgraded.connection.execute(
        "SELECT content_json FROM trade_plan_version "
        "WHERE plan_version_id='plan_version_legacy'"
    ).fetchone()[0] == original_content
    assert tuple(
        upgraded.connection.execute(
            "SELECT sleeve_kind,core_floor_state,core_floor_value "
            "FROM trade_plan_sleeve "
            "WHERE plan_version_id='plan_version_legacy'"
        ).fetchone()
    ) == ("core", "known", "0")
    assert tuple(
        upgraded.connection.execute(
            "SELECT s.sleeve_kind,g.lower_price,g.upper_price,"
            "g.quantity_per_level,g.total_quantity_budget "
            "FROM trade_plan_sleeve s JOIN grid_constraint g "
            "USING(grid_constraint_id) "
            "WHERE s.plan_version_id='plan_version_legacy'"
        ).fetchone()
    ) == ("grid", "8", "12", "100", "100")
    assert upgraded.connection.execute(
        "SELECT count(*) FROM plan_activation "
        "WHERE plan_id='plan_legacy' AND ended_at IS NULL"
    ).fetchone()[0] == 1
    assert upgraded.connection.execute(
        "SELECT mapping_artifact_hash "
        "FROM strategy_plan_migration_manifest"
    ).fetchone()[0] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    graph = SQLiteTradePlanRepository(
        upgraded.connection, upgraded.writer_lock
    ).get_graph("plan_version_legacy")
    assert graph.rules[0].ast_version == "plan-rule-ast@2"
    assert graph.rules[0].condition.operand_id == (
        "security.close_unadjusted"
    )
    upgraded.close()


def test_strategy_plan_0016_rolls_back_and_replays_after_injected_failure(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "strategy-crash"
    through_15 = _copy_migrations(tmp_path, 15)
    prior = PlatformStore(data_root, through_15)
    prior.migrate()
    prior.close()

    store = PlatformStore(data_root, ROOT / "migrations")
    with pytest.raises(PersistenceError) as failure:
        store.migrate(fail_after=20)
    assert failure.value.code == "MIGRATION_INJECTED_FAILURE"
    assert store.connection.execute(
        "SELECT max(version) FROM schema_migration"
    ).fetchone()[0] == 15
    assert store.connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE name='strategy_definition'"
    ).fetchone() is None
    store.migrate()
    assert store.connection.execute(
        "SELECT max(version) FROM schema_migration"
    ).fetchone()[0] == 16
    assert store.connection.execute(
        "SELECT count(*) FROM strategy_version "
        "WHERE publicly_selectable=1"
    ).fetchone()[0] == 2
    store.close()
