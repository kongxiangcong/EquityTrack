from __future__ import annotations

import sqlite3

import pytest

from trading_platform.domain.plans import (
    PlanValidationError,
    TradePlanMaster,
    TradePlanMasterId,
)
from tests.platform.test_account_snapshots import _ready_root


def test_plan_master_identity_is_owned_by_account_and_security() -> None:
    first = TradePlanMasterId.derive("account_local", "security_600000")
    replay = TradePlanMasterId.derive("account_local", "security_600000")
    other_account = TradePlanMasterId.derive(
        "account_other", "security_600000"
    )
    assert first == replay
    assert first != other_account
    master = TradePlanMaster(
        plan_id=first,
        strategy_version_id="strategy_version_core_plus_grid_1",
        lifecycle_status="inactive",
        transition_seq=0,
        created_at="2026-07-27T00:00:00+08:00",
    )
    master.validate()
    with pytest.raises(PlanValidationError) as missing:
        TradePlanMasterId.derive("", "security_600000")
    assert missing.value.code == "PLAN_OWNERSHIP_REQUIRED"


def test_storage_rejects_a_master_without_account_ownership(tmp_path) -> None:
    data_root = _ready_root(tmp_path)
    connection = sqlite3.connect(data_root / "platform.sqlite3")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO trade_plan_master VALUES(?,?,?,?,?,?,?,?)",
            (
                "master_without_account",
                None,
                "security_600000",
                "strategy_version_core_plus_grid_1",
                "inactive",
                0,
                "2026-07-27T00:00:00+08:00",
                0,
            ),
        )
    connection.close()
