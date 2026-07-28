from __future__ import annotations

import sqlite3
import json
from dataclasses import replace
from pathlib import Path

import pytest

from trading_platform.application import (
    ConfirmAccountSnapshot,
    CreateAccountSnapshotDraft,
    GetAccountSnapshot,
    UpdateAccountSnapshotDraft,
    open_account_snapshot_commands,
    open_account_snapshot_queries,
)
from trading_platform.domain.account_snapshots import (
    AccountSnapshotDraft,
    AccountSnapshotError,
    AccountSnapshotPosition,
    AccountSnapshotVersion,
)
from trading_platform.operations import PlatformOperations
from trading_platform.persistence import PlatformStore


ROOT = Path(__file__).resolve().parents[2]


def _ready_root(tmp_path: Path) -> Path:
    data_root = tmp_path / "data"
    operations = PlatformOperations(data_root, ROOT / "migrations")
    operations.bootstrap()
    store = PlatformStore(data_root, ROOT / "migrations")
    store.connection.execute(
        "INSERT INTO account VALUES(?,?,?,?,?)",
        ("account_local", "local", "CNY", "2026-07-27T00:00:00+00:00", "fixture"),
    )
    store.connection.execute(
        "INSERT INTO security VALUES(?,?)", ("security_600000", "CNY")
    )
    store.connection.commit()
    store.close()
    return data_root


def _draft(
    *,
    cash_state: str = "unknown",
    cash_value: str | None = None,
    available_state: str = "unknown",
    available_value: str | None = None,
) -> AccountSnapshotDraft:
    return AccountSnapshotDraft(
        draft_id="draft_local_1",
        account_id="account_local",
        revision=1,
        status="open",
        source_kind="user_declared",
        redacted_source_ref="manual-entry",
        as_of_at="2026-07-24",
        as_of_precision="date",
        timezone="Asia/Shanghai",
        session_semantics="complete_session",
        currency="CNY",
        cash_state=cash_state,
        cash_value=cash_value,
        positions=(
            AccountSnapshotPosition(
                security_id="security_600000",
                total_quantity="100",
                available_quantity_state=available_state,
                available_quantity_value=available_value,
            ),
        ),
        created_by="agent:codex",
    )


def _create(data_root: Path, draft: AccountSnapshotDraft) -> AccountSnapshotDraft:
    with open_account_snapshot_commands(data_root) as commands:
        result = commands.execute(
            CreateAccountSnapshotDraft(
                invocation_id="snapshot:create:1",
                draft=draft,
                decision_actor_type="agent",
                decision_actor_id="codex",
                interaction_channel="skill",
                transport_actor_type="agent",
                transport_actor_id="codex",
            )
        )
    assert isinstance(result, AccountSnapshotDraft)
    return result


def test_agent_draft_and_user_confirmation_capabilities(tmp_path: Path) -> None:
    data_root = _ready_root(tmp_path)
    created = _create(data_root, _draft())
    assert created.validation_state == "valid"
    assert created.status == "open"
    canonical_diff = json.loads(created.canonical_diff)
    assert canonical_diff["before"] is None
    assert canonical_diff["after"]["positions"][0]["total_quantity"] == "100"

    denied = ConfirmAccountSnapshot(
        invocation_id="snapshot:confirm:denied",
        draft_id=created.draft_id,
        expected_revision=created.revision,
        decision_actor_type="agent",
        decision_actor_id="codex",
        interaction_channel="skill",
        transport_actor_type="agent",
        transport_actor_id="codex",
    )
    with open_account_snapshot_commands(data_root) as commands:
        with pytest.raises(
            AccountSnapshotError, match="USER_CONFIRMATION_CAPABILITY_REQUIRED"
        ):
            commands.execute(denied)

        confirmed = commands.execute(
            replace(
                denied,
                invocation_id="snapshot:confirm:1",
                decision_actor_type="user",
                decision_actor_id="local-user",
            )
        )
    assert isinstance(confirmed, AccountSnapshotVersion)
    assert confirmed.confirmed_by == "user:local-user"
    assert confirmed.positions[0].total_quantity == "100"

    connection = sqlite3.connect(data_root / "platform.sqlite3")
    transition = connection.execute(
        "SELECT reason,decision_actor,interaction_channel,transport_actor "
        "FROM account_snapshot_transition"
    ).fetchone()
    assert transition == (
        "initial_confirmation",
        "user:local-user",
        "skill",
        "agent:codex",
    )
    assert connection.execute(
        "SELECT account_snapshot_version_id FROM account_snapshot_projection_checkpoint"
    ).fetchone() == (confirmed.account_snapshot_version_id,)
    assert connection.execute(
        "SELECT event_type FROM application_event"
    ).fetchone() == ("AccountSnapshotConfirmed",)
    assert connection.execute(
        "SELECT status,decision_actor FROM application_command_receipt "
        "WHERE invocation_id='snapshot:confirm:1'"
    ).fetchone() == ("succeeded", "user:local-user")
    connection.close()


def test_optional_unknowns_only_disable_dependent_capabilities(
    tmp_path: Path,
) -> None:
    data_root = _ready_root(tmp_path)
    created = _create(data_root, _draft())
    assert created.cash_value is None
    assert created.positions[0].available_quantity_value is None

    with open_account_snapshot_commands(data_root) as commands:
        confirmed = commands.execute(
            ConfirmAccountSnapshot(
                invocation_id="snapshot:confirm:unknowns",
                draft_id=created.draft_id,
                expected_revision=1,
                decision_actor_type="user",
                decision_actor_id="local-user",
                interaction_channel="cli",
                transport_actor_type="user",
                transport_actor_id="local-user",
            )
        )
    assert isinstance(confirmed, AccountSnapshotVersion)
    capabilities = {row[0]: row[1:] for row in confirmed.capabilities}
    assert capabilities["cash_rules"][0] == "unable"
    assert capabilities["total_quantity:security_600000"][0] == "available"
    assert capabilities["available_quantity:security_600000"][0] == "unable"

    connection = sqlite3.connect(data_root / "platform.sqlite3")
    assert connection.execute(
        "SELECT cash_state,cash_value FROM account_snapshot_cash"
    ).fetchone() == ("unknown", None)
    assert connection.execute(
        "SELECT available_quantity_state,available_quantity_value "
        "FROM account_snapshot_position"
    ).fetchone() == ("unknown", None)
    connection.close()


def test_confirmation_is_atomic_immutable_and_idempotent(tmp_path: Path) -> None:
    data_root = _ready_root(tmp_path)
    created = _create(
        data_root,
        _draft(
            cash_state="known",
            cash_value="1000.00",
            available_state="known",
            available_value="80.0",
        ),
    )
    command = ConfirmAccountSnapshot(
        invocation_id="snapshot:confirm:stable",
        draft_id=created.draft_id,
        expected_revision=1,
        decision_actor_type="user",
        decision_actor_id="local-user",
        interaction_channel="web",
        transport_actor_type="user",
        transport_actor_id="local-user",
    )
    with open_account_snapshot_commands(data_root) as commands:
        first = commands.execute(command)
        replay = commands.execute(command)
    assert first == replay

    connection = sqlite3.connect(data_root / "platform.sqlite3")
    assert connection.execute(
        "SELECT count(*) FROM account_snapshot_version"
    ).fetchone() == (1,)
    assert connection.execute(
        "SELECT count(*) FROM account_snapshot_transition"
    ).fetchone() == (1,)
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
        connection.execute("UPDATE account_snapshot_version SET currency='USD'")
    connection.rollback()
    connection.execute(
        "CREATE TRIGGER inject_snapshot_failure BEFORE INSERT ON application_event "
        "BEGIN SELECT RAISE(ABORT,'INJECTED'); END"
    )
    connection.commit()
    connection.close()

    second = replace(
        _draft(),
        draft_id="draft_local_2",
        previous_snapshot_version_id=first.account_snapshot_version_id,
    )
    with open_account_snapshot_commands(data_root) as commands:
        commands.execute(
            CreateAccountSnapshotDraft(
                invocation_id="snapshot:create:2",
                draft=second,
                decision_actor_type="agent",
                decision_actor_id="codex",
                interaction_channel="skill",
                transport_actor_type="agent",
                transport_actor_id="codex",
            )
        )
        with pytest.raises(sqlite3.IntegrityError, match="INJECTED"):
            commands.execute(
                replace(
                    command,
                    invocation_id="snapshot:confirm:injected",
                    draft_id="draft_local_2",
                )
            )
    connection = sqlite3.connect(data_root / "platform.sqlite3")
    assert connection.execute(
        "SELECT count(*) FROM account_snapshot_version"
    ).fetchone() == (1,)
    assert connection.execute(
        "SELECT status FROM account_snapshot_draft WHERE draft_id='draft_local_2'"
    ).fetchone() == ("open",)
    connection.close()


def test_query_reads_only_latest_confirmed_projection(tmp_path: Path) -> None:
    data_root = _ready_root(tmp_path)
    created = _create(data_root, _draft())
    with open_account_snapshot_queries(data_root) as queries:
        assert queries.get(GetAccountSnapshot(draft_id=created.draft_id)) == created
        with pytest.raises(AccountSnapshotError, match="SNAPSHOT_NOT_FOUND"):
            queries.get(GetAccountSnapshot(account_id="account_local"))


def test_update_requires_current_revision_and_required_identity_validation(
    tmp_path: Path,
) -> None:
    data_root = _ready_root(tmp_path)
    created = _create(data_root, _draft())
    updated_input = replace(
        created,
        cash_state="known",
        cash_value="12.50",
    )
    with open_account_snapshot_commands(data_root) as commands:
        updated = commands.execute(
            UpdateAccountSnapshotDraft(
                invocation_id="snapshot:update:1",
                draft=updated_input,
                expected_revision=1,
                decision_actor_type="agent",
                decision_actor_id="codex",
                interaction_channel="skill",
                transport_actor_type="agent",
                transport_actor_id="codex",
            )
        )
        assert isinstance(updated, AccountSnapshotDraft)
        assert updated.revision == 2
        assert updated.cash_value == "12.5"
        with pytest.raises(AccountSnapshotError, match="SNAPSHOT_DRAFT_REVISION_STALE"):
            commands.execute(
                UpdateAccountSnapshotDraft(
                    invocation_id="snapshot:update:stale",
                    draft=updated_input,
                    expected_revision=1,
                    decision_actor_type="agent",
                    decision_actor_id="codex",
                    interaction_channel="skill",
                    transport_actor_type="agent",
                    transport_actor_id="codex",
                )
            )

    invalid = replace(
        _draft(),
        draft_id="draft_invalid",
        timezone="",
        session_semantics="invalid",
    )
    with open_account_snapshot_commands(data_root) as commands:
        persisted = commands.execute(
            CreateAccountSnapshotDraft(
                invocation_id="snapshot:create:invalid",
                draft=invalid,
                decision_actor_type="agent",
                decision_actor_id="codex",
                interaction_channel="skill",
                transport_actor_type="agent",
                transport_actor_id="codex",
            )
        )
        assert isinstance(persisted, AccountSnapshotDraft)
        assert persisted.validation_state == "invalid"
        assert {
            "TIMEZONE_INVALID",
            "SESSION_SEMANTICS_INVALID",
        } <= set(persisted.validation_errors)
        with pytest.raises(AccountSnapshotError, match="SNAPSHOT_DRAFT_INVALID"):
            commands.execute(
                ConfirmAccountSnapshot(
                    invocation_id="snapshot:confirm:invalid",
                    draft_id=persisted.draft_id,
                    expected_revision=1,
                    decision_actor_type="user",
                    decision_actor_id="local-user",
                    interaction_channel="skill",
                    transport_actor_type="agent",
                    transport_actor_id="codex",
                )
            )


def test_nav_reconciliation_conflict_invalidates_draft(tmp_path: Path) -> None:
    data_root = _ready_root(tmp_path)
    original = _draft(cash_state="known", cash_value="10")
    mismatch = replace(
        original,
        draft_id="draft_nav_mismatch",
        nav_state="known",
        nav_value="100",
        positions=(
            replace(
                original.positions[0],
                market_value_state="known",
                market_value_value="50",
            ),
        ),
    )

    persisted = _create(data_root, mismatch)

    assert persisted.validation_state == "invalid"
    assert "NAV_RECONCILIATION_MISMATCH" in persisted.validation_errors
    assert "nav_reconciliation_conflict" in persisted.capability_impacts
