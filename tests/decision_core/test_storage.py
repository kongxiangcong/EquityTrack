from __future__ import annotations

import sqlite3

import pytest

from trading_platform.application import open_application
from trading_platform.storage import SQLiteStore, StorageError


def test_backup_restore_doctor_and_non_overwrite(tmp_path) -> None:
    source = tmp_path / "source"
    app = open_application(source)
    confirmed = app.account_confirm(
        {"account_id": "account-orchid", "as_of": "2035-04-18T08:00:00+00:00", "confirmed": True, "confirmed_by": "synthetic-user", "cash": None, "positions": []},
        idempotency_key="backup-account",
    )
    backup = SQLiteStore(source).backup(tmp_path / "verified.sqlite3")
    restored = tmp_path / "restored"
    SQLiteStore.restore(backup, restored)

    assert SQLiteStore(restored).doctor()["ok"]
    assert open_application(restored).account_show("account-orchid").value == confirmed.value
    with pytest.raises(FileExistsError):
        SQLiteStore.restore(backup, restored)


def test_concurrent_writer_is_rejected_without_partial_record(tmp_path) -> None:
    first = SQLiteStore(tmp_path)
    second = SQLiteStore(tmp_path)
    with first.transaction():
        first.put("AccountSnapshot", "snapshot-held", {"snapshot_id": "snapshot-held"})
        with pytest.raises(StorageError, match="SQLite operation failed") as failure:
            with second.transaction():
                second.put("AccountSnapshot", "snapshot-second", {"snapshot_id": "snapshot-second"})
        assert failure.value.step == "transaction.begin"
    assert second.get("AccountSnapshot", "snapshot-held") is not None
    assert second.get("AccountSnapshot", "snapshot-second") is None
