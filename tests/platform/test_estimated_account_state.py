from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from trading_platform.application import (
    CompareConfirmedAccountState,
    ConfirmAccountSnapshot,
    CreateAccountSnapshotDraft,
    GetAccountSnapshot,
    GetEstimatedAccountState,
    open_account_snapshot_commands,
    open_account_snapshot_queries,
    open_account_state_queries,
)
from trading_platform.domain.account_snapshots import (
    AccountSnapshotDraft,
    AccountSnapshotVersion,
)
from trading_platform.domain.account_state import ExecutionProjectionRecord
from trading_platform.identity import canonical_hash
from tests.platform.test_account_snapshots import _draft, _ready_root


class FixtureExecutionReader:
    def __init__(self, records: tuple[ExecutionProjectionRecord, ...]) -> None:
        self.records = records

    def read_confirmed(
        self,
        account_id: str,
        *,
        after_snapshot: AccountSnapshotVersion,
        through_snapshot: AccountSnapshotVersion | None = None,
    ) -> tuple[ExecutionProjectionRecord, ...]:
        return tuple(
            record for record in self.records if record.account_id == account_id
        )


def _execution(
    record_id: str,
    *,
    intent: str,
    quantity: str,
    effective_session: str = "2026-07-25",
    price_state: str = "known",
    price: str | None = "10",
    fee_state: str = "known",
    fee: str | None = "1",
    corrects: str | None = None,
    verification: str = "user_declared_unverified",
) -> ExecutionProjectionRecord:
    values = {
        "execution_record_id": record_id,
        "account_id": "account_local",
        "security_id": "security_600000",
        "effective_at": f"{effective_session}T15:00:00+08:00",
        "effective_session": effective_session,
        "intent_type": intent,
        "quantity": quantity,
        "price_state": price_state,
        "price_value": price,
        "fee_state": fee_state,
        "fee_value": fee,
        "currency": "CNY",
        "verification_status": verification,
        "corrects_execution_record_id": corrects,
    }
    return ExecutionProjectionRecord(
        **values, content_hash=canonical_hash(values)
    )


def _confirmed(
    data_root: Path,
    draft: AccountSnapshotDraft,
    *,
    create_invocation: str,
    confirm_invocation: str,
) -> AccountSnapshotVersion:
    with open_account_snapshot_commands(data_root) as commands:
        created = commands.execute(
            CreateAccountSnapshotDraft(
                invocation_id=create_invocation,
                draft=draft,
                decision_actor_type="agent",
                decision_actor_id="codex",
                interaction_channel="skill",
                transport_actor_type="agent",
                transport_actor_id="codex",
            )
        )
        assert isinstance(created, AccountSnapshotDraft)
        confirmed = commands.execute(
            ConfirmAccountSnapshot(
                invocation_id=confirm_invocation,
                draft_id=created.draft_id,
                expected_revision=created.revision,
                decision_actor_type="user",
                decision_actor_id="local-user",
                interaction_channel="skill",
                transport_actor_type="agent",
                transport_actor_id="codex",
            )
        )
    assert isinstance(confirmed, AccountSnapshotVersion)
    return confirmed


def test_projection_uses_latest_snapshot_and_confirmed_executions_only(
    tmp_path: Path,
) -> None:
    data_root = _ready_root(tmp_path)
    baseline = _confirmed(
        data_root,
        _draft(
            cash_state="known",
            cash_value="1000",
            available_state="known",
            available_value="80",
        ),
        create_invocation="state:create:1",
        confirm_invocation="state:confirm:1",
    )
    increase = _execution("execution_b", intent="increase", quantity="10")
    decrease = _execution(
        "execution_a", intent="decrease", quantity="5", price="12", fee="2"
    )
    before_cutoff = _execution(
        "execution_old",
        intent="increase",
        quantity="999",
        effective_session="2026-07-20",
    )
    reader = FixtureExecutionReader(
        (increase, decrease, increase, before_cutoff)
    )
    with open_account_state_queries(
        data_root, execution_reader=reader
    ) as queries:
        state = queries.get(GetEstimatedAccountState("account_local"))
    assert state.derived_from_snapshot_id == baseline.account_snapshot_version_id
    assert state.execution_record_ids == ("execution_a", "execution_b")
    assert state.positions[0].total_quantity == "105"
    assert (state.cash_state, state.cash_value) == ("known", "957")
    assert state.unverified_evidence == ("execution_a", "execution_b")

    with open_account_state_queries(
        data_root,
        execution_reader=FixtureExecutionReader(
            tuple(reversed(reader.records))
        ),
    ) as restarted:
        replay = restarted.get(GetEstimatedAccountState("account_local"))
    assert replay == state


def test_unknown_operands_corrections_and_conflicts_are_localized(
    tmp_path: Path,
) -> None:
    data_root = _ready_root(tmp_path)
    _confirmed(
        data_root,
        _draft(cash_state="known", cash_value="1000"),
        create_invocation="state:create:unknown",
        confirm_invocation="state:confirm:unknown",
    )
    original = _execution("execution_original", intent="increase", quantity="10")
    correction = _execution(
        "execution_correction",
        intent="increase",
        quantity="7",
        fee_state="unknown",
        fee=None,
        corrects="execution_original",
    )
    with open_account_state_queries(
        data_root,
        execution_reader=FixtureExecutionReader((original, correction)),
    ) as queries:
        state = queries.get(GetEstimatedAccountState("account_local"))
    assert state.execution_record_ids == ("execution_correction",)
    assert state.positions[0].total_quantity == "107"
    assert state.cash_state == "unknown"
    assert state.status == "partial"

    conflict = replace(
        correction,
        content_hash="different-content",
        quantity="8",
    )
    with open_account_state_queries(
        data_root,
        execution_reader=FixtureExecutionReader(
            (original, correction, conflict)
        ),
    ) as queries:
        blocked = queries.get(GetEstimatedAccountState("account_local"))
    assert blocked.status == "blocked"
    assert blocked.blocking_reasons == (
        "EXECUTION_ID_CONFLICT:execution_correction",
    )

    with open_account_state_queries(
        data_root,
        execution_reader=FixtureExecutionReader(
            (_execution("execution_too_large", intent="decrease", quantity="101"),)
        ),
    ) as queries:
        negative = queries.get(GetEstimatedAccountState("account_local"))
    assert negative.status == "blocked"
    assert negative.positions[0].total_quantity == "100"
    assert negative.blocking_reasons == (
        "POSITION_QUANTITY_NEGATIVE:execution_too_large",
    )


def test_new_snapshot_assesses_drift_without_rewriting_history(
    tmp_path: Path,
) -> None:
    data_root = _ready_root(tmp_path)
    first = _confirmed(
        data_root,
        _draft(cash_state="unknown"),
        create_invocation="state:create:first",
        confirm_invocation="state:confirm:first",
    )
    execution = _execution(
        "execution_drift",
        intent="increase",
        quantity="10",
        effective_session="2026-07-25",
    )
    second_draft = replace(
        _draft(cash_state="unknown"),
        draft_id="draft_state_second",
        as_of_at="2026-07-25",
        previous_snapshot_version_id=first.account_snapshot_version_id,
        positions=(
            replace(_draft().positions[0], total_quantity="108"),
        ),
    )
    second = _confirmed(
        data_root,
        second_draft,
        create_invocation="state:create:second",
        confirm_invocation="state:confirm:second",
    )
    with open_account_state_queries(
        data_root,
        execution_reader=FixtureExecutionReader((execution,)),
    ) as queries:
        latest = queries.get(GetEstimatedAccountState("account_local"))
        drift = queries.compare(
            CompareConfirmedAccountState(
                first.account_snapshot_version_id,
                second.account_snapshot_version_id,
            )
        )
    assert latest.derived_from_snapshot_id == second.account_snapshot_version_id
    assert latest.execution_record_ids == ()
    assert drift.status == "drift_detected"
    assert drift.position_differences == (
        ("security_600000", "110", "108", "-2"),
    )
    assert drift.explained_by_execution_ids == ("execution_drift",)

    with open_account_snapshot_queries(data_root) as snapshots:
        persisted_first = snapshots.get(
            GetAccountSnapshot(
                account_snapshot_version_id=first.account_snapshot_version_id
            )
        )
    assert isinstance(persisted_first, AccountSnapshotVersion)
    assert persisted_first.graph_seal_hash == first.graph_seal_hash
