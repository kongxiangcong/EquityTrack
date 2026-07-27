from __future__ import annotations

from pathlib import Path

import pytest

from trading_platform.account import AccountOpeningError, AccountOpeningService
from trading_platform.operations import PlatformOperations
from tests.platform.application_task_fixture import PlatformTaskFixture
from trading_platform.web_server import LocalChartWorkspaceServer
from tests.platform.test_chart_annotations import ROOT as REPO_ROOT, _root as chart_root
from tests.platform.test_tonghuashun_preview import _write


@pytest.fixture(autouse=True)
def _bootstrapped_account_root(tmp_path: Path) -> None:
    PlatformOperations(tmp_path / "data").bootstrap()


def _sources(root: Path, bad_weight: bool = False) -> list[Path]:
    positions = [
        [
            "",
            "1",
            "000001",
            "名称不参与身份",
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
            "16.3934" if not bad_weight else "99",
            "0",
            "0",
            "深A",
            "2",
        ],
        [
            "",
            "2",
            "600001",
            "另一个名称",
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
        ["20260710", "20260710", "", "", "起点", "", "", "0", "1000", "", "人民币"],
        ["20260710", "20260710", "", "", "正常", "", "", "100", "1100", "", "人民币"],
        ["20260710", "20260710", "", "", "申购配号", "", "", "0", "1500", "", "人民币"],
        ["20260710", "20260710", "", "", "恢复", "", "", "100", "1200", "", "人民币"],
        ["20260710", "20260710", "", "", "申购配号", "", "", "0", "1700", "", "人民币"],
        ["20260710", "20260710", "", "", "恢复", "", "", "-100", "1100", "", "人民币"],
    ]
    history = [
        ["", "000001", "历史名称", "20250101", "20250201", "31", "1", "1", "1", "1"]
    ]
    return [
        _write(root / "positions.xls", "current_positions", positions),
        _write(root / "cash.xls", "cash_ledger", cash),
        _write(root / "history.xls", "holding_history", history),
    ]


def test_atomic_opening_state_is_exact_idempotent_and_survives_restart(
    tmp_path: Path,
) -> None:
    sources = _sources(tmp_path / "sources")
    service = AccountOpeningService(tmp_path / "data", Path.cwd())
    result = service.initialize(
        "opening:1",
        sources,
        "本地账户",
        "CNY",
        "2026-07-10",
        tmp_path / "private",
        ("2026-07-10",),
    )
    replay = service.initialize(
        "opening:1",
        sources,
        "本地账户",
        "CNY",
        "2026-07-10",
        tmp_path / "private",
        ("2026-07-10",),
    )
    same_source = service.initialize(
        "opening:2",
        sources,
        "本地账户",
        "CNY",
        "2026-07-10",
        tmp_path / "private",
        ("2026-07-10",),
    )

    assert replay == result == same_source
    assert (
        result.selected_as_of == "2026-07-10"
        and result.quality_issue_count == 4
    )
    detail = service.get_detail(result.account_id)
    assert detail.opening == result
    assert detail.draft.status == "open"
    assert detail.draft.cash_value == "1100"
    assert len(detail.draft.positions) == 2
    assert {item.cost_value for item in detail.draft.positions} == {"8", "18"}
    composition = PlatformTaskFixture(tmp_path / "data")
    assert composition.accounts.get_detail(result.account_id) == detail
    composition.close()
    import sqlite3

    connection = sqlite3.connect(tmp_path / "data/platform.sqlite3")
    connection.row_factory = sqlite3.Row
    assert connection.execute("SELECT count(*) FROM account").fetchone()[0] == 1
    assert (
        connection.execute(
            "SELECT count(*) FROM account_snapshot_draft_position"
        ).fetchone()[0]
        == 2
    )
    assert (
        connection.execute(
            "SELECT count(*) FROM account_import_quality_issue WHERE code='CASH_RUNNING_BALANCE_JUMP'"
        ).fetchone()[0]
        == 4
    )
    assert (
        connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='transaction'"
        ).fetchone()[0]
        == 0
    )
    assert connection.execute(
        "SELECT count(*) FROM account_snapshot_version"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM portfolio_snapshot"
    ).fetchone()[0] == 0
    connection.close()
    chart = chart_root(tmp_path / "data")
    security_id = detail.draft.positions[0].security_id
    workspace = chart.workspace.build(security_id, "snapshot_chart")
    assert workspace["account_opening_state"] == []
    server = LocalChartWorkspaceServer(
        decision_workspace=chart.workspace,
        chart_workspace=chart.chart,
        chart_annotations=chart.chart,
        trade_plan=chart.plans,
        update_authorizations=chart.workspace,
        web_root=REPO_ROOT / "web/dist",
        security_id=security_id,
        snapshot_id="snapshot_chart",
    )
    import json
    from urllib.request import urlopen

    base = server.start()
    payload = json.loads(urlopen(base + "/api/workspace").read())
    assert payload["account_opening_state"] == []
    server.close()
    chart.close()
    archive = tmp_path / "opening.zip"
    PlatformOperations(tmp_path / "data").backup(archive)
    restored = tmp_path / "restored"
    PlatformOperations.restore(archive, restored)
    assert AccountOpeningService(restored, Path.cwd()).get(result.account_id) == result
    assert (
        AccountOpeningService(restored, Path.cwd()).get_detail(result.account_id)
        == detail
    )
    assert all(
        (
            restored
            / "objects/sha256"
            / item["object_sha256"][:2]
            / item["object_sha256"]
        ).is_file()
        for item in detail.source_objects
    )


def test_invalid_position_or_reconciliation_rolls_back_entire_account(
    tmp_path: Path,
) -> None:
    sources = _sources(tmp_path / "sources", bad_weight=True)
    service = AccountOpeningService(tmp_path / "data", Path.cwd())
    with pytest.raises(
        AccountOpeningError, match="POSITION_WEIGHT_RECONCILIATION_FAILED"
    ):
        service.initialize(
            "opening:bad",
            sources,
            "账户",
            "CNY",
            "2026-07-10",
            tmp_path / "private",
            ("2026-07-10",),
        )
    import sqlite3

    connection = sqlite3.connect(tmp_path / "data/platform.sqlite3")
    assert connection.execute("SELECT count(*) FROM account").fetchone()[0] == 0
    connection.close()


def test_unknown_market_and_quantity_relation_fail_closed(tmp_path: Path) -> None:
    sources = _sources(tmp_path / "sources")
    text = sources[0].read_bytes().decode("gb18030").replace("深A", "未知市场", 1)
    sources[0].write_bytes(text.encode("gb18030"))
    with pytest.raises(AccountOpeningError, match="POSITION_SECURITY_INVALID"):
        AccountOpeningService(tmp_path / "data", Path.cwd()).initialize(
            "opening:market",
            sources,
            "账户",
            "CNY",
            "2026-07-10",
            tmp_path / "private",
            ("2026-07-10",),
        )


def test_mid_commit_failure_leaves_no_partial_account(tmp_path: Path) -> None:
    from trading_platform.persistence import PlatformStore

    store = PlatformStore(tmp_path / "data", Path.cwd() / "migrations")
    store.migrate()
    store.connection.execute(
        "CREATE TRIGGER reject_draft BEFORE INSERT ON account_snapshot_draft BEGIN SELECT RAISE(ABORT,'INJECTED'); END"
    )
    store.connection.commit()
    store.close()
    with pytest.raises(Exception, match="INJECTED"):
        AccountOpeningService(tmp_path / "data", Path.cwd()).initialize(
            "opening:crash",
            _sources(tmp_path / "sources"),
            "账户",
            "CNY",
            "2026-07-10",
            tmp_path / "private",
            ("2026-07-10",),
        )
    import sqlite3

    connection = sqlite3.connect(tmp_path / "data/platform.sqlite3")
    assert [
        connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in (
            "account",
            "account_import_batch",
            "account_snapshot_draft",
            "account_snapshot_draft_position",
            "account_snapshot_version",
        )
    ] == [0, 0, 0, 0, 0]
    connection.close()


def test_existing_identifier_history_wins_over_display_name(tmp_path: Path) -> None:
    from trading_platform.persistence import PlatformStore

    store = PlatformStore(tmp_path / "data", Path.cwd() / "migrations")
    store.migrate()
    with store.connection:
        store.connection.execute(
            "INSERT INTO security VALUES('security_existing','CNY')"
        )
        store.connection.execute(
            "INSERT INTO security_identifier VALUES('identifier_existing','security_existing','SZSE','000001','2020-01-01','date',NULL,NULL)"
        )
    store.close()
    result = AccountOpeningService(tmp_path / "data", Path.cwd()).initialize(
        "opening:identity",
        _sources(tmp_path / "sources"),
        "账户",
        "CNY",
        "2026-07-10",
        tmp_path / "private",
        ("2026-07-10",),
    )
    detail = AccountOpeningService(tmp_path / "data", Path.cwd()).get_detail(
        result.account_id
    )
    position = next(
        item
        for item in detail.draft.positions
        if item.total_quantity == "100"
    )
    assert position.security_id == "security_existing"


@pytest.mark.parametrize(
    "field,value,code",
    [
        (5, "80.5", "POSITION_QUANTITY_RELATION_INVALID"),
        (4, "-1", "POSITION_QUANTITY_INVALID"),
        (7, "NaN", "POSITION_DECIMAL_INVALID"),
    ],
)
def test_exact_position_contract_rejects_fractional_negative_and_nonfinite(
    tmp_path: Path, field: int, value: str, code: str
) -> None:
    sources = _sources(tmp_path / "sources")
    lines = sources[0].read_bytes().decode("gb18030").splitlines()
    row = lines[1].split("\t")
    row[field] = value
    lines[1] = "\t".join(row)
    sources[0].write_bytes("\n".join(lines).encode("gb18030"))
    with pytest.raises(AccountOpeningError, match=code):
        AccountOpeningService(tmp_path / "data", Path.cwd()).initialize(
            "opening:invalid",
            sources,
            "账户",
            "CNY",
            "2026-07-10",
            tmp_path / "private",
            ("2026-07-10",),
        )


def test_cash_currency_mismatch_fails_closed(tmp_path: Path) -> None:
    sources = _sources(tmp_path / "sources")
    sources[1].write_bytes(
        sources[1]
        .read_bytes()
        .decode("gb18030")
        .replace("人民币", "美元")
        .encode("gb18030")
    )
    with pytest.raises(AccountOpeningError, match="CASH_CURRENCY_MISMATCH"):
        AccountOpeningService(tmp_path / "data", Path.cwd()).initialize(
            "opening:currency",
            sources,
            "账户",
            "CNY",
            "2026-07-10",
            tmp_path / "private",
            ("2026-07-10",),
        )


def test_concurrent_replay_returns_one_opening_identity(tmp_path: Path) -> None:
    import threading

    sources = _sources(tmp_path / "sources")
    results = []

    def run():
        try:
            results.append(
                AccountOpeningService(tmp_path / "data", Path.cwd()).initialize(
                    "opening:concurrent",
                    sources,
                    "账户",
                    "CNY",
                    "2026-07-10",
                    tmp_path / "private",
                    ("2026-07-10",),
                )
            )
        except BaseException as error:
            results.append(error)

    workers = [threading.Thread(target=run) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert (
        len(results) == 2
        and not any(isinstance(item, BaseException) for item in results)
        and results[0] == results[1]
    )


def test_identifier_rollover_uses_half_open_validity_interval(tmp_path: Path) -> None:
    from trading_platform.persistence import PlatformStore

    store = PlatformStore(tmp_path / "data", Path.cwd() / "migrations")
    store.migrate()
    with store.connection:
        store.connection.execute("INSERT INTO security VALUES('security_old','CNY')")
        store.connection.execute("INSERT INTO security VALUES('security_new','CNY')")
        store.connection.execute(
            "INSERT INTO security_identifier VALUES('id_old','security_old','SZSE','000001','2020-01-01','date','2026-07-10','date')"
        )
        store.connection.execute(
            "INSERT INTO security_identifier VALUES('id_new','security_new','SZSE','000001','2026-07-10','date',NULL,NULL)"
        )
    store.close()
    result = AccountOpeningService(tmp_path / "data", Path.cwd()).initialize(
        "opening:rollover",
        _sources(tmp_path / "sources"),
        "账户",
        "CNY",
        "2026-07-10",
        tmp_path / "private",
        ("2026-07-10",),
    )
    detail = AccountOpeningService(tmp_path / "data", Path.cwd()).get_detail(
        result.account_id
    )
    assert (
        next(
            item
            for item in detail.draft.positions
            if item.total_quantity == "100"
        ).security_id
        == "security_new"
    )


def test_rows_without_trailing_tab_match_preview_contract(tmp_path: Path) -> None:
    sources = _sources(tmp_path / "sources")
    for source in sources:
        source.write_bytes(
            "\n".join(
                line.removesuffix("\t")
                for line in source.read_bytes().decode("gb18030").splitlines()
            ).encode("gb18030")
        )
    assert (
        len(
            AccountOpeningService(tmp_path / "data", Path.cwd())
            .initialize(
                "opening:no-tail",
                sources,
                "账户",
                "CNY",
                "2026-07-10",
                tmp_path / "private",
                ("2026-07-10",),
            )
            .account_snapshot_draft_id
        )
        > 0
    )
