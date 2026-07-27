from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from trading_platform.persistence import PersistenceError, PlatformStore


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
    ).fetchone()[0] == 15
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
