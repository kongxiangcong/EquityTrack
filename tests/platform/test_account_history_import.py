from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from trading_platform.account import AccountOpeningService
from trading_platform.account_history import (
    AccountHistoryImportService,
    HistoryImportError,
)
from trading_platform.persistence import PlatformStore
from trading_platform.operations import PlatformOperations
from trading_platform.application import (
    ConfirmAccountSnapshot,
    open_account_snapshot_commands,
)
from tests.platform.test_account_opening import _sources
from tests.platform.test_tonghuashun_preview import _write


@pytest.fixture(autouse=True)
def _bootstrapped_account_root(tmp_path: Path) -> None:
    PlatformOperations(tmp_path / "data").bootstrap()


def _opened_account(tmp_path: Path) -> tuple[str, list[Path]]:
    sources = _sources(tmp_path / "opening")
    opening = AccountOpeningService(tmp_path / "data", Path.cwd()).initialize(
        "opening:history",
        sources,
        "local-account",
        "CNY",
        "2026-07-10",
        tmp_path / "private-opening",
        ("2026-07-10",),
    )
    with open_account_snapshot_commands(tmp_path / "data") as commands:
        commands.execute(
            ConfirmAccountSnapshot(
                invocation_id="opening:history:confirm",
                draft_id=opening.account_snapshot_draft_id,
                expected_revision=1,
                decision_actor_type="user",
                decision_actor_id="local-user",
                interaction_channel="cli",
                transport_actor_type="user",
                transport_actor_id="local-user",
            )
        )
    return opening.account_id, sources


def _history_sources(
    root: Path,
    *,
    revised: bool = False,
    extension: bool = False,
    broken: bool = False,
    position_label: str = "name",
    order_changed: bool = False,
    history_revised: bool = False,
    partial: bool = False,
    collision_count: int = 1,
) -> list[Path]:
    positions = [
        [
            "",
            "1",
            "000001",
            position_label,
            "100",
            "80",
            "20",
            "8",
            "10",
            "0",
            "0",
            "5",
            "0",
            "1000",
            "16.3934",
            "0",
            "0",
            "深A",
            "2",
        ],
        [
            "",
            "2",
            "600001",
            position_label,
            "200",
            "200",
            "0",
            "18",
            "20",
            "0",
            "0",
            "-5",
            "0",
            "4000",
            "65.5738",
            "0",
            "0",
            "沪A",
            "3",
        ],
    ]
    cash = [
        [
            "20260710",
            "20260710",
            "000001",
            "name",
            "证券买入",
            "10",
            "10",
            "-110",
            "1100",
            "深A",
            "人民币",
        ],
        ["20260709", "20260709", "", "", "申购配号", "", "", "0", "9999", "", "人民币"],
        ["20260709", "20260709", "", "", "利息归本", "", "", "1", "1201", "", "人民币"],
        [
            "20260709",
            "20260709",
            "000001",
            "name",
            "证券卖出",
            "-1",
            "10",
            "9",
            "1210",
            "深A",
            "人民币",
        ],
        [
            "20260708",
            "20260708",
            "",
            "",
            "银行转存",
            "",
            "",
            "1200",
            "1200",
            "",
            "人民币",
        ],
    ]
    for _ in range(collision_count - 1):
        cash.insert(2, list(cash[1]))
    if revised:
        cash[0][7] = "-109"
        cash[0][8] = "1101"
    if extension:
        cash.insert(
            0,
            [
                "20260711",
                "20260711",
                "",
                "",
                "银行转存",
                "",
                "",
                "2",
                "1102",
                "",
                "人民币",
            ],
        )
    if partial:
        cash = [
            row for row in cash if not (row[0] == "20260708" and row[4] == "银行转存")
        ]
    if broken:
        cash[0][8] = "1109"
    if order_changed:
        cash[1], cash[2] = cash[2], cash[1]
    history = [
        [
            "",
            "000001",
            "name",
            f"20250{month}01",
            f"20250{month}02",
            "1",
            "1",
            "1",
            "1",
            "1",
        ]
        for month in range(1, 5)
    ]
    if history_revised:
        history[0][6] = "2"
    return [
        _write(root / "positions.xls", "current_positions", positions),
        _write(root / "cash.xls", "cash_ledger", cash),
        _write(root / "history.xls", "holding_history", history),
    ]


def test_history_import_maps_events_reconciles_cash_and_is_idempotent(
    tmp_path: Path,
) -> None:
    account_id, _ = _opened_account(tmp_path)
    sources = _history_sources(tmp_path / "history")
    service = AccountHistoryImportService(tmp_path / "data", Path.cwd())

    result = service.import_history(
        "history:1", account_id, sources, tmp_path / "private-history", ("2026-07-10",)
    )
    replay = service.import_history(
        "history:2", account_id, sources, tmp_path / "private-history", ("2026-07-10",)
    )

    assert replay == result
    assert (
        result.new_event_count,
        result.transaction_count,
        result.cash_entry_count,
    ) == (5, 2, 4)
    assert (result.informational_count, result.holding_summary_count) == (1, 4)
    assert (result.opening_history_gap_count, result.cash_transition_count) == (1, 3)
    assert result.reconciliation_status == "limited_opening_history"
    connection = sqlite3.connect(tmp_path / "data/platform.sqlite3")
    assert connection.execute(
        "SELECT event_type,cash_effect FROM account_event ORDER BY event_date,source_order"
    ).fetchall() == [
        ("bank_deposit", 1),
        ("subscription_allocation_info", 0),
        ("interest_credit", 1),
        ("security_sell", 1),
        ("security_buy", 1),
    ]
    assert (
        connection.execute(
            "SELECT count(*) FROM account_transaction WHERE charges_status='aggregate_charges_inferred'"
        ).fetchone()[0]
        == 2
    )
    assert (
        connection.execute(
            "SELECT count(*) FROM account_position_lot WHERE source_type != 'opening_snapshot'"
        ).fetchone()[0]
        == 0
    )
    connection.execute(
        "INSERT INTO account VALUES('account_other','other','CNY','2026-07-10','other-source')"
    )
    connection.commit()
    connection.close()
    with pytest.raises(HistoryImportError, match="INVOCATION_ACCOUNT_MISMATCH"):
        service.import_history(
            "history:1",
            "account_other",
            sources,
            tmp_path / "private-history",
            ("2026-07-10",),
        )


def test_overlap_extension_appends_only_new_rows_and_revision_blocks_snapshot(
    tmp_path: Path,
) -> None:
    account_id, _ = _opened_account(tmp_path)
    service = AccountHistoryImportService(tmp_path / "data", Path.cwd())
    first = service.import_history(
        "history:first",
        account_id,
        _history_sources(tmp_path / "first"),
        tmp_path / "private-first",
        ("2026-07-10",),
    )
    extension = service.import_history(
        "history:extension",
        account_id,
        _history_sources(tmp_path / "extension", extension=True, partial=True),
        tmp_path / "private-extension",
        ("2026-07-11",),
    )
    assert first.new_event_count == 5
    assert extension.new_event_count == 1 and extension.reused_event_count == 4

    collisions = service.import_history(
        "history:collisions",
        account_id,
        _history_sources(tmp_path / "collisions", collision_count=2),
        tmp_path / "private-collisions",
        ("2026-07-10",),
    )
    assert collisions.new_event_count == 1 and collisions.reused_event_count == 5
    collision_extension = service.import_history(
        "history:collision-extension",
        account_id,
        _history_sources(tmp_path / "collision-extension", collision_count=3),
        tmp_path / "private-collision-extension",
        ("2026-07-10",),
    )
    assert (
        collision_extension.new_event_count == 1
        and collision_extension.reused_event_count == 6
    )

    complete_overlap = service.import_history(
        "history:overlap",
        account_id,
        _history_sources(tmp_path / "overlap", position_label="renamed"),
        tmp_path / "private-overlap",
        ("2026-07-10",),
    )
    assert (
        complete_overlap.new_event_count == 0
        and complete_overlap.reused_event_count == 5
    )
    reordered = service.import_history(
        "history:reordered",
        account_id,
        _history_sources(tmp_path / "reordered", order_changed=True),
        tmp_path / "private-reordered",
        ("2026-07-10",),
    )
    assert reordered.new_event_count == 0 and reordered.reused_event_count == 5

    revision = service.import_history(
        "history:revision",
        account_id,
        _history_sources(tmp_path / "revision", revised=True),
        tmp_path / "private-revision",
        ("2026-07-10",),
    )
    assert revision.revision_count >= 1
    assert (
        revision.account_history_snapshot_id is None
        and revision.reconciliation_status == "blocked"
    )
    summary_revision = service.import_history(
        "history:summary-revision",
        account_id,
        _history_sources(tmp_path / "summary-revision", history_revised=True),
        tmp_path / "private-summary-revision",
        ("2026-07-10",),
    )
    assert summary_revision.revision_count == 1


def test_cash_chain_failure_and_injected_crash_leave_no_partial_batch(
    tmp_path: Path,
) -> None:
    account_id, _ = _opened_account(tmp_path)
    sources = _history_sources(tmp_path / "bad", broken=True)
    service = AccountHistoryImportService(tmp_path / "data", Path.cwd())
    with pytest.raises(HistoryImportError, match="CASH_CHAIN_MISMATCH"):
        service.import_history(
            "history:bad",
            account_id,
            sources,
            tmp_path / "private-bad",
            ("2026-07-10",),
        )
    store = PlatformStore(tmp_path / "data", Path.cwd() / "migrations")
    store.migrate()
    assert (
        store.connection.execute(
            "SELECT count(*) FROM history_import_batch"
        ).fetchone()[0]
        == 0
    )
    store.close()

    def crash(stage: str) -> None:
        assert stage == "before_history_snapshot"
        raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        AccountHistoryImportService(
            tmp_path / "data", Path.cwd(), fault_injector=crash
        ).import_history(
            "history:crash",
            account_id,
            _history_sources(tmp_path / "crash"),
            tmp_path / "private-crash",
            ("2026-07-10",),
        )
    recovered = service.import_history(
        "history:recovered",
        account_id,
        _history_sources(tmp_path / "crash"),
        tmp_path / "private-crash",
        ("2026-07-10",),
    )
    assert recovered.new_event_count == 5
