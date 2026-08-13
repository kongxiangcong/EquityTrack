from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.platform.test_manual_review_universe_migration import (
    _copy_migrations,
    _legacy_snapshot,
)
from tests.platform.test_plan_confirmation import USER, _draft
from trading_platform.application.trade_plan_authoring import (
    _OpenTradePlanDrafts,
    _UpsertOpenTradePlanDraft,
)
from trading_platform.domain.plans import PlanValidationError
from trading_platform.persistence import PlatformStore
from trading_platform.persistence.plans import SQLiteTradePlanRepository


ROOT = Path(__file__).resolve().parents[2]


def _upsert(
    drafts: _OpenTradePlanDrafts,
    *,
    snapshot_id: str,
    invocation_id: str,
    suffix: str,
):
    source = _draft(
        snapshot_id,
        suffix=suffix,
        purpose=suffix,
    )
    return drafts.upsert(
        _UpsertOpenTradePlanDraft(
            invocation_id=invocation_id,
            account_id=source.account_id,
            security_id=source.security_id,
            proposed_graph=source.proposed_graph,
            parameters=source.parameters,
            updated_at=source.updated_at,
            actor=USER,
        )
    )


def test_0023_rewrites_retired_draft_receipts_to_one_current_identity(
    tmp_path: Path,
) -> None:
    through_22 = _copy_migrations(tmp_path, 22)
    data_root = tmp_path / "open-draft-receipt-v22"
    prior = PlatformStore(data_root, through_22)
    prior.migrate()
    with prior.connection:
        prior.connection.execute(
            "INSERT INTO account VALUES(?,?,?,?,?)",
            (
                "account_local",
                "local",
                "CNY",
                "2026-07-27T00:00:00+00:00",
                "migration-0023-fixture",
            ),
        )
        prior.connection.execute(
            "INSERT INTO security VALUES(?,?)",
            ("security_600000", "CNY"),
        )
    prior.close()
    snapshot_id = _legacy_snapshot(data_root, through_22)

    prior = PlatformStore(data_root, through_22)
    with prior.connection:
        prior.connection.execute(
            "INSERT INTO query_policy_record VALUES(?,?,?,?,?)",
            (
                "query_policy_migration_0023@1",
                "QueryPolicy@1",
                "query-policy-migration-0023",
                "{}",
                "2026-07-27T00:00:00+08:00",
            ),
        )
        prior.connection.execute(
            "INSERT INTO source_policy_record VALUES(?,?,?,?,?)",
            (
                "source_policy_migration_0023@1",
                "SourcePolicy@1",
                "source-policy-migration-0023",
                "{}",
                "2026-07-27T00:00:00+08:00",
            ),
        )
        prior.connection.execute(
            "INSERT INTO data_snapshot VALUES("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "data_snapshot_plan_fixture",
                "security_600000",
                "research",
                "2026-07-27",
                "2026-07-24",
                "2026-07-24T15:00:00+08:00",
                "Asia/Shanghai",
                "calendar_fixture@1",
                "query_policy_migration_0023@1",
                "source_policy_migration_0023@1",
                "freshness_fixture@1",
                "membership-plan",
                "valid",
                "pass",
                0,
                0,
                0,
                0,
                0,
                "fixture",
                "2026-07-24T15:00:00+08:00",
            ),
        )
    repository = SQLiteTradePlanRepository(
        prior.connection, prior.writer_lock
    )
    drafts = _OpenTradePlanDrafts(repository)
    created = _upsert(
        drafts,
        snapshot_id=snapshot_id,
        invocation_id="migration-0023:create",
        suffix="migration-0023-create",
    )
    revised = _upsert(
        drafts,
        snapshot_id=snapshot_id,
        invocation_id="migration-0023:revise",
        suffix="migration-0023-revise",
    )
    assert created.draft_id == revised.draft_id
    assert revised.revision == 2

    with prior.connection:
        prior.connection.execute(
            "DROP TRIGGER application_command_receipt_no_update"
        )
        prior.connection.execute(
            "UPDATE application_command_receipt "
            "SET command_name='CreateTradePlanDraft' "
            "WHERE invocation_id='migration-0023:create'"
        )
        prior.connection.execute(
            "UPDATE application_command_receipt "
            "SET command_name='ReviseTradePlanDraft' "
            "WHERE invocation_id='migration-0023:revise'"
        )
        prior.connection.execute(
            "CREATE TRIGGER application_command_receipt_no_update "
            "BEFORE UPDATE ON application_command_receipt "
            "BEGIN SELECT RAISE("
            "ABORT,'APPLICATION_COMMAND_RECEIPT_IMMUTABLE'); END"
        )
    preserved = {
        row["invocation_id"]: dict(row)
        for row in prior.connection.execute(
            "SELECT * FROM application_command_receipt "
            "WHERE invocation_id LIKE 'migration-0023:%'"
        )
    }
    prior.close()

    upgraded = PlatformStore(data_root, ROOT / "migrations")
    upgraded.migrate()
    upgraded.migrate()
    assert upgraded.connection.execute(
        "SELECT max(version) FROM schema_migration"
    ).fetchone()[0] == 25
    migrated = {
        row["invocation_id"]: dict(row)
        for row in upgraded.connection.execute(
            "SELECT * FROM application_command_receipt "
            "WHERE invocation_id LIKE 'migration-0023:%'"
        )
    }
    assert set(migrated) == set(preserved)
    for invocation_id, before in preserved.items():
        after = migrated[invocation_id]
        assert after["command_name"] == "UpsertOpenTradePlanDraft"
        assert {
            key: value
            for key, value in after.items()
            if key != "command_name"
        } == {
            key: value
            for key, value in before.items()
            if key != "command_name"
        }
    assert upgraded.connection.execute(
        "SELECT count(*) FROM application_command_receipt "
        "WHERE command_name IN "
        "('CreateTradePlanDraft','ReviseTradePlanDraft')"
    ).fetchone()[0] == 0
    with pytest.raises(
        sqlite3.IntegrityError,
        match="APPLICATION_COMMAND_RECEIPT_IMMUTABLE",
    ):
        upgraded.connection.execute(
            "UPDATE application_command_receipt SET status='tampered' "
            "WHERE invocation_id='migration-0023:revise'"
        )
    upgraded.close()

    restarted = PlatformStore(data_root, ROOT / "migrations")
    replay = _OpenTradePlanDrafts(
        SQLiteTradePlanRepository(
            restarted.connection, restarted.writer_lock
        )
    )
    assert replay.get_by_invocation("migration-0023:revise") == revised
    with restarted.connection:
        restarted.connection.execute(
            "DROP TRIGGER application_command_receipt_no_update"
        )
        restarted.connection.execute(
            "UPDATE application_command_receipt "
            "SET command_name='ReviseTradePlanDraft' "
            "WHERE invocation_id='migration-0023:revise'"
        )
    with pytest.raises(PlanValidationError, match="INVOCATION_CONFLICT"):
        replay.get_by_invocation("migration-0023:revise")
    restarted.close()
