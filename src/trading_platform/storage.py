from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, cast


SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    kind TEXT NOT NULL,
    record_id TEXT NOT NULL,
    account_id TEXT,
    as_of TEXT,
    payload TEXT NOT NULL,
    PRIMARY KEY(kind, record_id)
);
CREATE INDEX IF NOT EXISTS records_lookup ON records(kind, account_id, as_of);
CREATE TABLE IF NOT EXISTS application_commands (
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    result_kind TEXT NOT NULL,
    result_id TEXT NOT NULL,
    PRIMARY KEY(operation, idempotency_key)
);
"""


class StorageError(sqlite3.Error):
    def __init__(self, step: str) -> None:
        super().__init__("SQLite operation failed")
        self.step = step


class SQLiteStore:
    """The sole persistence Adapter for canonical decision records."""

    def __init__(self, data_root: Path, *, fault_at: str | None = None) -> None:
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.path = self.data_root / "decision-core.sqlite3"
        self.fault_at = fault_at
        self.connection = sqlite3.connect(self.path, timeout=0.1)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator["SQLiteStore"]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as error:
            raise StorageError("transaction.begin") from error
        try:
            yield self
            if self.fault_at == "before_commit":
                raise sqlite3.OperationalError("injected failure before commit")
            try:
                self.connection.commit()
            except sqlite3.Error as error:
                raise StorageError("transaction.commit") from error
        except sqlite3.Error as error:
            self.connection.rollback()
            if isinstance(error, StorageError):
                raise
            raise StorageError("transaction.commit") from error
        except Exception:
            self.connection.rollback()
            raise

    def put(self, kind: str, record_id: str, payload: dict[str, Any], *, account_id: str | None = None, as_of: str | None = None) -> None:
        encoded = _json(payload)
        try:
            existing = self.connection.execute(
                "SELECT payload FROM records WHERE kind=? AND record_id=?", (kind, record_id)
            ).fetchone()
            if existing is not None:
                if existing["payload"] != encoded:
                    raise StorageError("records.identity_conflict")
                return
            self.connection.execute(
                "INSERT INTO records(kind,record_id,account_id,as_of,payload) VALUES(?,?,?,?,?)",
                (kind, record_id, account_id, as_of, encoded),
            )
        except sqlite3.Error as error:
            if isinstance(error, StorageError):
                raise
            raise StorageError("records.write") from error

    def get(self, kind: str, record_id: str) -> dict[str, Any] | None:
        try:
            row = self.connection.execute(
                "SELECT payload FROM records WHERE kind=? AND record_id=?", (kind, record_id)
            ).fetchone()
        except sqlite3.Error as error:
            raise StorageError("records.read") from error
        return json.loads(row["payload"]) if row else None

    def latest(self, kind: str, *, account_id: str | None = None, as_of: str | None = None) -> dict[str, Any] | None:
        conditions = ["kind=?"]
        parameters: list[object] = [kind]
        if account_id is not None:
            conditions.append("account_id=?")
            parameters.append(account_id)
        if as_of is not None:
            conditions.append("as_of<=?")
            parameters.append(as_of)
        try:
            row = self.connection.execute(
                f"SELECT payload FROM records WHERE {' AND '.join(conditions)} ORDER BY as_of DESC, rowid DESC LIMIT 1",
                parameters,
            ).fetchone()
        except sqlite3.Error as error:
            raise StorageError("records.read") from error
        return json.loads(row["payload"]) if row else None

    def list(self, kind: str) -> list[dict[str, Any]]:
        try:
            rows = self.connection.execute(
                "SELECT payload FROM records WHERE kind=? ORDER BY rowid", (kind,)
            ).fetchall()
        except sqlite3.Error as error:
            raise StorageError("records.read") from error
        return [json.loads(row["payload"]) for row in rows]

    def command(self, operation: str, key: str) -> sqlite3.Row | None:
        try:
            return cast(sqlite3.Row | None, self.connection.execute(
                "SELECT * FROM application_commands WHERE operation=? AND idempotency_key=?",
                (operation, key),
            ).fetchone())
        except sqlite3.Error as error:
            raise StorageError("commands.read") from error

    def put_command(self, operation: str, key: str, digest: str, result_kind: str, result_id: str) -> None:
        try:
            self.connection.execute(
                "INSERT INTO application_commands VALUES(?,?,?,?,?)",
                (operation, key, digest, result_kind, result_id),
            )
        except sqlite3.Error as error:
            raise StorageError("commands.write") from error

    def backup(self, destination: Path) -> Path:
        destination = Path(destination)
        if destination.exists():
            raise FileExistsError(destination)
        self.connection.commit()
        backup = sqlite3.connect(destination)
        try:
            self.connection.backup(backup)
        finally:
            backup.close()
        return destination

    def doctor(self) -> dict[str, Any]:
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {"ok": integrity == "ok", "integrity": integrity, "schema": "current"}

    @staticmethod
    def restore(backup: Path, data_root: Path) -> Path:
        target = Path(data_root) / "decision-core.sqlite3"
        Path(data_root).mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(target)
        shutil.copy2(backup, target)
        return target


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
